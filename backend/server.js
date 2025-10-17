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
const path = require('path');

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.raw({ type: 'application/json' })); // For Stripe webhooks

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
    await pool.connect(); // Test connection
    const schema = fs.readFileSync('schema.sql', 'utf8');
    await pool.query(schema);
    console.log('Database schema applied successfully');
  } catch (err) {
    console.error('Error applying schema or connecting:', err.message);
    if (!err.message.includes('already exists')) {
      process.exit(1);
    }
  } finally {
    await pool.end(); // Close test connection
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

// ---------------- Broken Link Checker with Job Tracking ----------------
async function getOrCreateJob(channelId, maxVideos) {
  const result = await pool.query(
    'SELECT id, status FROM jobs WHERE channel_id = $1 AND max_videos = $2 AND status IN (\'pending\', \'in_progress\') ORDER BY created_at DESC LIMIT 1',
    [channelId, maxVideos]
  );
  if (result.rows.length > 0) {
    return { id: result.rows[0].id, status: result.rows[0].status };
  }
  const newJob = await pool.query(
    'INSERT INTO jobs (channel_id, max_videos, status) VALUES ($1, $2, $3) RETURNING id',
    [channelId, maxVideos, 'in_progress']
  );
  return { id: newJob.rows[0].id, status: 'in_progress' };
}

app.post('/api/check-links', async (req, res) => {
  const { channelId, maxVideos } = req.body;
  if (!channelId) {
    return res.status(400).json({ error: 'Missing channelId' });
  }

  try {
    const job = await getOrCreateJob(channelId, maxVideos);
    if (job.status === 'in_progress') {
      return res.json({ jobId: job.id, status: 'in_progress', message: 'Check already in progress' });
    }

    console.log(`Spawning Python with channelId: ${channelId}, maxVideos: ${maxVideos}, jobId: ${job.id}`);
    const python = spawn('python3', ['check_links.py', channelId, maxVideos.toString()], {
      env: { ...process.env, YOUTUBE_API_KEY: process.env.YOUTUBE_API_KEY },
    });

    let stdoutData = '';
    let stderrData = '';

    python.stdout.on('data', (data) => {
      stdoutData += data.toString();
      console.log(`[PYTHON STDOUT]: ${data}`);
    });

    python.stderr.on('data', (data) => {
      stderrData += data.toString();
      console.error(`[PYTHON STDERR]: ${data}`);
    });

    python.on('close', async (code) => {
      console.log(`Python process exited with code ${code} for jobId: ${job.id}`);
      if (code === 0) {
        let parsed;
        try {
          const lines = stdoutData.trim().split('\n');
          for (let i = 0; i < lines.length; i++) {
            try {
              const tempParsed = JSON.parse(lines[i]);
              if (tempParsed.brokenLinks && tempParsed.brokenLinks.length > 0) {
                parsed = tempParsed;
                console.log('Parsed JSON with data:', parsed);
                break;
              }
            } catch (e) {
              continue;
            }
          }
          if (!parsed) {
            parsed = { brokenLinks: [] };
            console.log('No valid data found, using empty array');
          }
          await pool.query(
            'UPDATE jobs SET status = $1, result = $2, updated_at = CURRENT_TIMESTAMP WHERE id = $3',
            ['completed', parsed, job.id]
          );
        } catch (err) {
          console.error("❌ Failed to parse Python JSON output:", err);
          console.error("Raw output:", stdoutData);
          await pool.query(
            'UPDATE jobs SET status = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2',
            ['failed', job.id]
          );
        }
      } else {
        await pool.query(
          'UPDATE jobs SET status = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2',
          ['failed', job.id]
        );
      }
    });

    python.on('error', (err) => {
      console.error('Python spawn error:', err.message);
      pool.query(
        'UPDATE jobs SET status = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2',
        ['failed', job.id]
      );
      res.status(500).json({ error: 'Failed to spawn Python', details: err.message });
    });

    res.json({ jobId: job.id, status: 'in_progress', message: 'Check started' });
  } catch (err) {
    console.error('Check-links error:', err.stack); // Add stack trace for debugging
    res.status(500).json({ error: err.message, stack: err.stack }); // Return detailed error
  }
});

app.get('/api/check-links-status/:jobId', async (req, res) => {
  const { jobId } = req.params;
  try {
    const queryResult = await pool.query('SELECT status, result FROM jobs WHERE id = $1', [jobId]); // Renamed to queryResult
    if (queryResult.rows.length === 0) {
      return res.status(404).json({ error: 'Job not found' });
    }
    const { status, result: jobResult } = queryResult.rows[0]; // Renamed inner 'result' to 'jobResult'
    res.json({ jobId, status, brokenLinks: jobResult?.brokenLinks || [] });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
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
    const session = await stripe.checkout.sessions.create({
      customer: customerId,
      payment_method_types: ['card'],
      mode: 'subscription',
      line_items: [
        {
          price:
            plan === 'monthly'
              ? process.env.STRIPE_MONTHLY_PRICE_ID
              : process.env.STRIPE_YEARLY_PRICE_ID,
          quantity: 1,
        },
      ],
      success_url: 'https://www.affiliatesbot.com/success?session_id={CHECKOUT_SESSION_ID}', // Updated to production domain
      cancel_url: 'https://www.affiliatesbot.com/cancel', // Updated to production domain
    });
    res.json({ sessionId: session.id });
  } catch (err) {
    console.error('Stripe checkout error:', err.message);
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