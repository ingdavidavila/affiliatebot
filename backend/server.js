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
const Queue = require('bull');
const redis = require('ioredis');

const app = express();

// ======== CORS ========
const allowedOrigins = ['https://www.affiliatesbot.com', 'http://localhost:3000'];
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
const redisUrl = process.env.REDIS_URL;
if (!redisUrl) {
  console.error('REDIS_URL not set, queue will not function. Check Heroku addon status.');
  process.exit(1); // Exit if Redis is unavailable
}
const linkCheckQueue = new Queue('link-check', redisUrl);

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

// ======== Link Checker with Queue ========
linkCheckQueue.process(async (job) => {
  const { channelId, maxVideos } = job.data;
  console.log(`Processing job ${job.id} for channel ${channelId}`);
  try {
    const python = spawn('python3', ['check_links.py', channelId, maxVideos || 50]);
    let output = '';
    python.stdout.on('data', (d) => (output += d.toString()));
    python.stderr.on('data', (d) => console.error(`PYTHON ERROR ${job.id}:`, d.toString()));

    const totalVideosPromise = getTotalVideoCount(channelId);
    await new Promise((resolve, reject) => {
      python.on('close', async (code) => {
        try {
          const parsed = JSON.parse(output);
          const totalVideos = await totalVideosPromise;
          await job.update({
            status: 'completed',
            result: { brokenLinks: parsed.brokenLinks || [], totalVideos },
          });
          resolve();
        } catch (err) {
          console.error(`❌ Job ${job.id} parse error:`, err.message, output);
          await job.update({ status: 'error', error: 'Invalid output' });
          reject(err);
        }
      });
    });
  } catch (err) {
    console.error(`Job ${job.id} failed:`, err.message);
    await job.update({ status: 'error', error: err.message });
  }
});

app.post('/api/check-links', async (req, res) => {
  const { channelId, maxVideos } = req.body;
  if (!channelId) return res.status(400).json({ error: 'Channel ID is required' });

  const job = await linkCheckQueue.add({ channelId, maxVideos });
  res.json({ jobId: job.id });
});

app.get('/api/check-links/status/:jobId', async (req, res) => {
  const job = await linkCheckQueue.getJob(req.params.jobId);
  if (!job) return res.status(404).json({ status: 'not_found' });

  const state = await job.getState();
  const data = await job.getJobData();
  if (state === 'completed') {
    return res.json({ status: 'completed', result: data.result });
  } else if (state === 'failed') {
    return res.status(500).json({ status: 'error', result: data.error });
  }
  res.json({ status: state });
});


// ======== /api/me ========
app.get('/api/me', async (req, res) => {
  const user = await verifySession(req);
  if (!user) return res.status(401).json({ error: 'Unauthorized' });
  res.json(user);
});

// ======== Create Checkout Session ========
app.post('/api/create-checkout-session', async (req, res) => {
  const user = await verifySession(req);
  if (!user) return res.status(401).json({ error: 'Unauthorized' });

  const { plan } = req.body;
  const priceId = plan === 'yearly' ? YEARLY_PRICE_ID : MONTHLY_PRICE_ID;

  let custId = user.stripe_customer_id;
  if (!custId) {
    const customer = await stripe.customers.create({
      email: user.email,
      metadata: { userId: String(user.id) },
    });
    custId = customer.id;
    await pool.query('UPDATE users SET stripe_customer_id = $1 WHERE id = $2', [custId, user.id]);
  }

  const session = await stripe.checkout.sessions.create({
    mode: 'subscription',
    customer: custId,
    customer_email: user.email,
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

      if (session.subscription && email) {
        // Fetch subscription details to get period end
        const subscription = await stripe.subscriptions.retrieve(session.subscription);
        const periodEnd = new Date(subscription.current_period_end * 1000).toISOString();

        await pool.query(
          `UPDATE users
           SET paid = TRUE,
               stripe_subscription_id = $1,
               subscription_end = $2
           WHERE email = $3`,
          [subscription.id, periodEnd, email]
        );

        console.log(`✅ Marked ${email} as paid until ${periodEnd}`);
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
