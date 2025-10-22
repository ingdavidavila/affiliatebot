// server.js
require('dotenv').config();

const fs = require('fs');
const path = require('path');
const express = require('express');
const cors = require('cors');
const { Pool } = require('pg');
const { spawn } = require('child_process');
const { google } = require('googleapis');
const { OAuth2Client } = require('google-auth-library');
const Stripe = require('stripe');
const { v4: uuidv4 } = require('uuid');

const app = express();

// ======== CORS ========
const allowedOrigins = [
  'https://www.affiliatesbot.com',
  'http://localhost:3000',
];
app.use(cors({
  origin(origin, cb) {
    if (!origin || allowedOrigins.includes(origin)) cb(null, true);
    else cb(new Error('CORS not allowed for this origin'));
  },
  credentials: true,
}));

// ======== Core Setup ========
const stripe = Stripe(process.env.STRIPE_SECRET_KEY);
const googleClient = new OAuth2Client(process.env.GOOGLE_CLIENT_ID);
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: { rejectUnauthorized: false },
});

const FRONTEND_URL = process.env.FRONTEND_URL || 'http://localhost:3000';
const MONTHLY_PRICE_ID = process.env.STRIPE_MONTHLY_PRICE_ID;
const YEARLY_PRICE_ID = process.env.STRIPE_YEARLY_PRICE_ID;

// ======== Body Parsers ========
app.use('/api/webhook', express.raw({ type: 'application/json' }));
app.use(express.json());

// ======== Safe DB Initialization ========
async function initializeDatabase() {
  const schema = fs.readFileSync('schema.sql', 'utf8');
  await pool.query(schema);
  console.log('✅ Schema verified');
}
initializeDatabase().catch(err => console.error('DB init error', err));

// ======== Google Auth ========
async function verifySession(req) {
  const auth = req.headers.authorization || '';
  const [, token] = auth.split(' ');
  if (!token) return null;

  try {
    const ticket = await googleClient.verifyIdToken({
      idToken: token,
      audience: process.env.GOOGLE_CLIENT_ID,
    });
    const payload = ticket.getPayload();
    const email = payload.email;

    const { rows } = await pool.query(
      `INSERT INTO users (email)
       VALUES ($1)
       ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email
       RETURNING *`,
      [email]
    );
    return rows[0];
  } catch (err) {
    console.error('Auth error:', err.message);
    return null;
  }
}

app.post('/api/auth/google', async (req, res) => {
  const { token } = req.body;
  if (!token) return res.status(400).json({ error: 'Missing token' });

  try {
    const ticket = await googleClient.verifyIdToken({
      idToken: token,
      audience: process.env.GOOGLE_CLIENT_ID,
    });
    const payload = ticket.getPayload();
    const email = payload.email;

    const { rows } = await pool.query(
      `INSERT INTO users (email)
       VALUES ($1)
       ON CONFLICT (email)
       DO UPDATE SET email = EXCLUDED.email
       RETURNING *`,
      [email]
    );

    const user = rows[0];

    // Include paid status from the users table
    const paid = user.paid || false;

    res.json({ user: { email: user.email, paid } });
  } catch (err) {
    console.error('OAuth Error:', err.message);
    res.status(500).json({ error: 'Failed to verify Google token' });
  }
});


// ======== YouTube Helper ========
async function getTotalVideoCount(channelId) {
  const youtube = google.youtube({ version: 'v3', auth: process.env.YOUTUBE_API_KEY });
  try {
    const r = await youtube.channels.list({ part: 'statistics', id: channelId });
    const count = parseInt(r.data.items?.[0]?.statistics?.videoCount || '50', 10);
    return Number.isFinite(count) ? count : 50;
  } catch {
    return 50;
  }
}

// ======== Link Checker ========
const jobs = {};
app.post('/api/check-links', async (req, res) => {
  const { channelId, maxVideos } = req.body;
  if (!channelId) return res.status(400).json({ error: 'Missing channelId' });

  const jobId = uuidv4();
  jobs[jobId] = { status: 'running', result: null };
  console.log(`Spawning Python with channelId: ${channelId}, maxVideos: ${maxVideos}, jobId: ${jobId}`);

  const python = spawn('python3', ['check_links.py', channelId, maxVideos.toString()], {
    env: { ...process.env, YOUTUBE_API_KEY: process.env.YOUTUBE_API_KEY },
  });

  let output = '';
  python.stdout.on('data', (d) => (output += d.toString()));
  python.stderr.on('data', (d) => console.error(`[PYTHON ERROR]: ${d}`));

  const totalVideosPromise = getTotalVideoCount(channelId);

  python.on('close', async (code) => {
    console.log(`Python process exited with code ${code}`);
    try {
      const parsed = JSON.parse(output.trim());
      const totalVideos = await totalVideosPromise;
      jobs[jobId] = {
        status: 'completed',
        result: { brokenLinks: parsed.brokenLinks || [], totalVideos },
      };
      console.log(`✅ Job ${jobId} completed with ${parsed.brokenLinks?.length || 0} broken links`);
    } catch (err) {
      console.error('❌ Python output parse error:', err.message);
      jobs[jobId] = { status: 'error', result: { error: 'Invalid output' } };
    }
  });

  // Return immediately — frontend will poll for status
  res.json({ jobId });
});

app.get('/api/check-links/status/:jobId', (req, res) => {
  const job = jobs[req.params.jobId];
  if (!job) return res.status(404).json({ error: 'Job not found' });
  res.json(job);
});


app.get('/api/check-links/status/:jobId', (req, res) => {
  const job = jobs[req.params.jobId];
  if (!job) return res.status(404).json({ error: 'Job not found' });
  res.json(job);
});

// ======== /api/me ========
app.get('/api/me', async (req, res) => {
  const user = await verifySession(req);
  if (!user) return res.status(401).json({ error: 'Unauthorized' });
  res.json(user);
});

// ======== Check Stripe Subscription by Email ========
app.get('/api/stripe/status', async (req, res) => {
  const user = await verifySession(req);
  if (!user) return res.status(401).json({ error: 'Unauthorized' });

  try {
    if (!user.stripe_customer_id) return res.json({ paid: false });

    const subs = await stripe.subscriptions.list({
      customer: user.stripe_customer_id,
      status: 'active',
      limit: 1,
    });

    const isPaid = subs.data.length > 0;
    if (isPaid && !user.paid) {
      await pool.query('UPDATE users SET paid = TRUE WHERE id = $1', [user.id]);
    }

    res.json({ paid: isPaid });
  } catch (err) {
    console.error('Stripe status check error:', err.message);
    res.status(500).json({ error: 'Stripe status check failed' });
  }
});





// ======== Create Checkout Session ========
app.post('/api/create-checkout-session', async (req, res) => {
  const user = await verifySession(req);
  if (!user) return res.status(401).json({ error: 'Unauthorized' });

  const { plan } = req.body;
  const priceId = plan === 'yearly' ? YEARLY_PRICE_ID : MONTHLY_PRICE_ID;

  // 🔐 Always require an existing Stripe customer (no guest checkout)
  let custId = user.stripe_customer_id;
  if (!custId) {
    // Create one now, before checkout
    const customer = await stripe.customers.create({
      email: user.email,
      metadata: { userId: String(user.id) },
    });
    custId = customer.id;

    // Save it immediately so future payments link correctly
    await pool.query(
      'UPDATE users SET stripe_customer_id = $1 WHERE id = $2',
      [custId, user.id]
    );
    console.log(`✅ Created Stripe customer for ${user.email}: ${custId}`);
  }

  // 🧾 Create checkout session strictly bound to that customer
  const session = await stripe.checkout.sessions.create({
    mode: 'subscription',
    customer: custId, // only customer, no customer_email allowed
    line_items: [{ price: priceId, quantity: 1 }],
    success_url: `${FRONTEND_URL}/?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${FRONTEND_URL}/payment-cancelled`,
  });

  res.json({ url: session.url });
});

// ======== Cancel Subscription ========
app.post('/api/cancel-subscription', async (req, res) => {
  const user = await verifySession(req);
  if (!user) return res.status(401).json({ error: 'Unauthorized' });

  const subs = await stripe.subscriptions.list({
    customer: user.stripe_customer_id,
    status: 'active',
    limit: 1,
  });

  if (!subs.data.length) return res.status(400).json({ error: 'No active subscription' });

  await stripe.subscriptions.update(subs.data[0].id, { cancel_at_period_end: true });
  await pool.query('UPDATE users SET paid = FALSE WHERE id = $1', [user.id]);

  res.json({ success: true });
});

// ======== Webhook ========
app.post('/api/webhook', async (req, res) => {
  const sig = req.headers['stripe-signature'];
  let event;

  try {
    event = stripe.webhooks.constructEvent(req.body, sig, process.env.STRIPE_WEBHOOK_SECRET);
  } catch (err) {
    console.error('Webhook error:', err.message);
    return res.status(400).send(`Webhook Error: ${err.message}`);
  }

  try {
   if (event.type === 'checkout.session.completed') {
  const session = event.data.object;
  const email = session.customer_details?.email;
  const customerId = session.customer;

  if (email && customerId) {
    try {
      // Retrieve the customer's subscriptions
      const subs = await stripe.subscriptions.list({
        customer: customerId,
        status: 'all', // include active, trialing, canceled, etc.
        limit: 1,
      });

      if (subs.data.length > 0) {
        const sub = subs.data[0];
        const isActive =
          sub.status === 'active' || sub.status === 'trialing';

        let periodEnd = null;
        if (sub.current_period_end) {
          try {
            periodEnd = new Date(sub.current_period_end * 1000).toISOString();
          } catch (e) {
            console.warn('⚠️ Could not parse period end:', e.message);
          }
        }

        await pool.query(
          `UPDATE users
           SET paid = $1,
               stripe_customer_id = $2,
               stripe_subscription_id = $3,
               subscription_end = $4
           WHERE email = $5`,
          [isActive, customerId, sub.id, periodEnd, email]
        );

        console.log(
          `✅ Updated ${email} — status: ${sub.status}, sub: ${sub.id}`
        );
      } else {
        console.warn(`⚠️ No subscriptions found for ${email}`);
      }
    } catch (err) {
      console.error('Stripe check error:', err);
    }
  }
    }

    if (event.type === 'customer.subscription.deleted') {
      const sub = event.data.object;
      await pool.query(
        'UPDATE users SET paid = FALSE, subscription_end = NULL WHERE stripe_customer_id = $1',
        [sub.customer]
      );
    }

    if (event.type === 'invoice.payment_failed') {
      const inv = event.data.object;
      await pool.query(
        'UPDATE users SET paid = FALSE WHERE stripe_customer_id = $1',
        [inv.customer]
      );
    }

  } catch (err) {
    console.error('Webhook handling failed:', err.message);
  }

  res.json({ received: true });
});


// ======== Serve Frontend ========
app.use(express.static(path.join(__dirname, '../build')));
app.get('*', (_, res) => {
  res.sendFile(path.join(__dirname, '../build/index.html'));
});

app.listen(process.env.PORT || 3001, () => console.log('✅ Server started.'));
