require('dotenv').config();
const fetch = require('node-fetch');
const express = require('express');
const { spawn } = require('child_process');
const { Pool } = require('pg');
const cors = require('cors');
const { google } = require('googleapis');
const { OAuth2Client } = require('google-auth-library');
const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.raw({ type: 'application/json' })); // For webhook

const pool = new Pool({
  user: 'postgres',
  host: 'localhost',
  database: 'affiliatebot',
  password: process.env.POSTGRES_PASSWORD,
  port: 5432,
});

const oauth2Client = new google.auth.OAuth2(
  process.env.GOOGLE_CLIENT_ID,
  process.env.GOOGLE_CLIENT_SECRET,
  'http://localhost:3001/api/auth/google/callback'
);

app.post('/api/auth/google', async (req, res) => {
  const { token } = req.body;
  if (!token) {
    return res.status(400).json({ error: 'Missing token' });
  }

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

    const user = {
      email: email || 'unknown',
      sub: sub,
    };

    res.json({ user });
  } catch (err) {
    console.error('OAuth Error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/check-links', async (req, res) => {
  const { channelId, maxVideos } = req.body;
  if (!channelId) {
    return res.status(400).json({ error: 'Missing channelId' });
  }

  try {
    console.log(`Spawning Python with channelId: ${channelId}, maxVideos: ${maxVideos}`);
    let effectiveMaxVideos = maxVideos === -1 ? await getTotalVideoCount(channelId) : maxVideos;

    const python = spawn('python', ['check_links.py', channelId, effectiveMaxVideos], {
      env: { ...process.env, YOUTUBE_API_KEY: process.env.YOUTUBE_API_KEY },
    });
    let output = '';
    let errorOutput = '';

    python.stdout.on('data', (data) => {
      output += data.toString();
      console.log(`Python stdout: ${data}`);
    });

    python.stderr.on('data', (data) => {
      errorOutput += data.toString();
      console.log(`Python stderr: ${data}`);
    });

    python.on('close', async (code) => {
      console.log(`Python process exited with code ${code}`);
      if (code !== 0) {
        return res.status(500).json({ error: `AffiliateBot script failed: ${errorOutput}` });
      }

      const brokenLinks = [];
      const lines = output.split('\n');
      let currentVideoId = null;
      for (const line of lines) {
        if (line.startsWith('Video: https://www.youtube.com/watch?v=')) {
          currentVideoId = line.split('v=')[1].split('\n')[0];
        } else if (line.startsWith('Broken link: ')) {
          const link = line.replace('Broken link: ', '').trim();
          brokenLinks.push({ videoId: currentVideoId, link });
          try {
            await pool.query(
              'INSERT INTO broken_links (channel_id, video_id, broken_link, checked_at) VALUES ($1, $2, $3, NOW())',
              [channelId, currentVideoId, link]
            );
            console.log(`Inserted: channelId=${channelId}, videoId=${currentVideoId}, link=${link}`);
          } catch (dbErr) {
            console.error(`Database error: ${dbErr.message}`);
          }
        }
      }

      res.json({ brokenLinks });
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

async function getTotalVideoCount(channelId) {
  const youtube = google.youtube({
    version: 'v3',
    auth: process.env.YOUTUBE_API_KEY, // Using API key for simplicity
  });
  try {
    const response = await youtube.channels.list({
      part: 'statistics',
      id: channelId,
    });
    if (response.data.items.length > 0) {
      return parseInt(response.data.items[0].statistics.videoCount, 10) || 50; // Default to 50 if invalid
    }
    return 50; // Fallback if channel not found
  } catch (err) {
    console.error('Error fetching video count:', err.message);
    return 50; // Fallback
  }
}

app.post('/api/create-customer', async (req, res) => {
  const { email } = req.body;
  try {
    let customer = await stripe.customers.list({ email, limit: 1 });
    if (customer.data.length === 0) {
      customer = await stripe.customers.create({ email });
    }
    await pool.query(
      'INSERT INTO users (email, stripe_customer_id) VALUES ($1, $2) ON CONFLICT (email) DO UPDATE SET stripe_customer_id = $2',
      [email, customer.id]
    );
    res.json({ customerId: customer.id });
  } catch (err) {
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
          price: plan === 'monthly' ? process.env.STRIPE_MONTHLY_PRICE_ID : process.env.STRIPE_YEARLY_PRICE_ID,
          quantity: 1,
        },
      ],
      success_url: 'http://localhost:3000/success?session_id={CHECKOUT_SESSION_ID}',
      cancel_url: 'http://localhost:3000/cancel',
    });
    res.json({ sessionId: session.id });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/webhook', async (req, res) => {
  const sig = req.headers['stripe-signature'];
  try {
    const event = stripe.webhooks.constructEvent(req.body, sig, process.env.STRIPE_WEBHOOK_SECRET);
    if (event.type === 'checkout.session.completed') {
      const session = event.data.object;
      const userId = (await pool.query('SELECT id FROM users WHERE stripe_customer_id = $1', [session.customer])).rows[0]?.id;
      if (userId) {
        await pool.query(
          'INSERT INTO subscriptions (user_id, stripe_subscription_id, plan_type, status) VALUES ($1, $2, $3, $4) ON CONFLICT (stripe_subscription_id) DO UPDATE SET status = $4',
          [userId, session.subscription, session.metadata.plan || req.body.plan, 'active']
        );
      }
    }
    res.json({ received: true });
  } catch (err) {
    res.status(400).json({ error: err.message });
  }
});

app.get('/api/user-status', async (req, res) => {
  const { email } = req.query;
  try {
    const result = await pool.query('SELECT EXISTS (SELECT 1 FROM subscriptions WHERE user_id = (SELECT id FROM users WHERE email = $1) AND status = $2) AS paid', [email, 'active']);
    res.json({ paid: result.rows[0].paid });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/verify-payment', async (req, res) => {
  const { sessionId } = req.body;
  try {
    const session = await stripe.checkout.sessions.retrieve(sessionId);
    res.json({ paid: session.payment_status === 'paid' });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.listen(3001, () => console.log('AffiliateBot server running on http://localhost:3001'));