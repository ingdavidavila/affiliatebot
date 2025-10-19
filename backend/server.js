require('dotenv').config();
const fs = require('fs');
const fetch = require('node-fetch');
const express = require('express');
const { spawn } = require('child_process');
const { Pool } = require('pg');
const cors = require('cors');
const { google } = require('googleapis');
const { OAuth2Client } = require('google-auth-library');
const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
const path = require('path'); // Added for serving static files
const { v4: uuidv4 } = require('uuid');

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.raw({ type: 'application/json' })); // For Stripe webhooks

const jobs = {}; // temporary in-memory job tracker

const allowedOrigins = [
  'https://www.affiliatesbot.com',
  'http://localhost:3000', // for local React dev
];

app.use(
  cors({
    origin: function (origin, callback) {
      if (!origin || allowedOrigins.includes(origin)) {
        callback(null, true);
      } else {
        callback(new Error('CORS not allowed for this origin'));
      }
    },
    methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    allowedHeaders: ['Content-Type', 'Authorization'],
    credentials: true,
  })
);

// ---------------- PostgreSQL ----------------
const pool = new Pool({
  connectionString: process.env.DATABASE_URL, // Use Heroku's DATABASE_URL
  ssl: {
    rejectUnauthorized: false, // Required for Heroku Postgres SSL
  },
});

async function initializeDatabase() {
  try {
    const schema = fs.readFileSync('schema.sql', 'utf8');
    await pool.query(schema);
    console.log('Database schema applied successfully');
  } catch (err) {
    console.error('Error applying schema:', err.message);
    // Ignore "already exists" errors to avoid crashes on redeploy
    if (!err.message.includes('already exists')) {
      process.exit(1); // Exit if critical error
    }
  }
}


// ---------------- Google OAuth ----------------
const oauth2Client = new google.auth.OAuth2(
  process.env.GOOGLE_CLIENT_ID,
  process.env.GOOGLE_CLIENT_SECRET,
  'https://www.affiliatesbot.com/api/auth/google/callback' // Updated to production domain
);

app.post('/api/auth/google', async (req, res) => {
  const { token } = req.body;
  if (!token) return res.status(400).json({ error: 'Missing token' });

  try {
    const client = new OAuth2Client(process.env.GOOGLE_CLIENT_ID);
    client._httpClient = { fetch: fetch };
    const ticket = await client.verifyIdToken({
      idToken: token,
      audience: process.env.GOOGLE_CLIENT_ID,
    });
    const payload = ticket.getPayload();
    const email = payload.email;
    const sub = payload.sub;

    const user = { email, sub };
    res.json({ user });
  } catch (err) {
    console.error('OAuth Error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ---------------- YouTube Video Count ----------------
async function getTotalVideoCount(channelId) {
  const youtube = google.youtube({
    version: 'v3',
    auth: process.env.YOUTUBE_API_KEY,
  });
  try {
    const response = await youtube.channels.list({
      part: 'statistics',
      id: channelId,
    });
    if (response.data.items.length > 0) {
      return parseInt(response.data.items[0].statistics.videoCount, 10) || 50;
    }
    return 50;
  } catch (err) {
    console.error('Error fetching video count:', err.message);
    return 50;
  }
}

// ---------------- Broken Link Checker ----------------
app.post('/api/check-links', (req, res) => {
  const { channelId, maxVideos } = req.body;
  const jobId = uuidv4();

  jobs[jobId] = { status: 'running', result: null };

  const python = spawn('python3', ['check_links.py', channelId, maxVideos]);

  let output = '';
  python.stdout.on('data', data => {
    output += data.toString();
  });

  python.on('close', code => {
    try {
      const parsed = JSON.parse(output);
      jobs[jobId] = { status: 'completed', result: parsed };
    } catch (err) {
      jobs[jobId] = { status: 'error', result: { error: 'Invalid output' } };
    }
  });

  res.json({ jobId }); // respond immediately before Heroku timeout
});

//ads polling status
app.get('/api/check-links/status/:jobId', (req, res) => {
  const job = jobs[req.params.jobId];
  if (!job) return res.status(404).json({ error: 'Job not found' });
  res.json(job);
});


// ---------------- Stripe Integration ----------------
app.post('/api/create-customer', async (req, res) => {
  const { email } = req.body;
  try {
    let customer = await stripe.customers.list({ email, limit: 1 });
    if (customer.data.length === 0) {
      customer = await stripe.customers.create({ email });
    } else {
      customer = customer.data[0];
    }

    await pool.query(
      `INSERT INTO users (email, stripe_customer_id)
       VALUES ($1, $2)
       ON CONFLICT (email)
       DO UPDATE SET stripe_customer_id = EXCLUDED.stripe_customer_id`,
      [email, customer.id]
    );

    res.json({ customerId: customer.id });
  } catch (err) {
    console.error('Stripe create-customer error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/create-checkout-session', async (req, res) => {
  const { customerId, plan } = req.body;
  try {
    console.log('Creating Payment Intent with customerId:', customerId, 'plan:', plan);
    console.log('Env vars:', {
      monthlyPriceId: process.env.STRIPE_MONTHLY_PRICE_ID,
      yearlyPriceId: process.env.STRIPE_YEARLY_PRICE_ID,
    });
    const amount = plan === 'monthly' ? 1499 : 9999; // $14.99 or $99.99 in cents
    const paymentIntent = await stripe.paymentIntents.create({
      customer: customerId,
      amount: amount,
      currency: 'usd',
      automatic_payment_methods: {
        enabled: true,
      },
      metadata: { plan },
    });
    console.log('Stripe API response:', paymentIntent);
    if (!paymentIntent.client_secret) {
      throw new Error('Payment Intent created but client_secret is missing');
    }
    res.json({ clientSecret: paymentIntent.client_secret, sessionId: paymentIntent.id });
  } catch (err) {
    console.error('Stripe payment error:', err.message, err.stack);
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/webhook', async (req, res) => {
  const sig = req.headers['stripe-signature'];
  try {
    const event = stripe.webhooks.constructEvent(
      req.body,
      sig,
      process.env.STRIPE_WEBHOOK_SECRET
    );

    if (event.type === 'checkout.session.completed') {
      const session = event.data.object;
      const userResult = await pool.query(
        'SELECT id FROM users WHERE stripe_customer_id = $1',
        [session.customer]
      );
      const userId = userResult.rows[0]?.id;

      if (userId) {
        await pool.query(
          `INSERT INTO subscriptions (user_id, stripe_subscription_id, plan_type, status)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (stripe_subscription_id)
           DO UPDATE SET status = EXCLUDED.status`,
          [
            userId,
            session.subscription,
            session.metadata?.plan || 'unknown',
            'active',
          ]
        );
      }
    }

    res.json({ received: true });
  } catch (err) {
    console.error('Webhook error:', err.message);
    res.status(400).json({ error: err.message });
  }
});

app.get('/api/user-status', async (req, res) => {
  const { email } = req.query;
  try {
    const result = await pool.query(
      `SELECT EXISTS (
         SELECT 1
         FROM subscriptions
         WHERE user_id = (SELECT id FROM users WHERE email = $1)
         AND status = 'active'
       ) AS paid`,
      [email]
    );
    res.json({ paid: result.rows[0].paid });
  } catch (err) {
    console.error('User status error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/verify-payment', async (req, res) => {
  const { sessionId } = req.body;
  try {
    const session = await stripe.checkout.sessions.retrieve(sessionId);
    res.json({ paid: session.payment_status === 'paid' });
  } catch (err) {
    console.error('Verify payment error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ---------------- Serve Frontend ----------------
app.use(express.static(path.join(__dirname, '../build'))); // Serve static files from build folder
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, '../build', 'index.html')); // Catch-all for React routing
});

// ---------------- Start Server ----------------
initializeDatabase().then(() => {
  app.listen(process.env.PORT || 3001, () => {
    console.log('✅ AffiliateBot server running on http://localhost:3001 or Heroku port');
  });
});