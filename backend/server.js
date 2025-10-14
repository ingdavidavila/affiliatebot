require('dotenv').config();
const fetch = require('node-fetch');
const express = require('express');
const { spawn } = require('child_process');
const { Pool } = require('pg');
const cors = require('cors');
const { google } = require('googleapis');
const { OAuth2Client } = require('google-auth-library');

const app = express();
app.use(cors());
app.use(express.json());

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
    client._httpClient = { fetch: require('node-fetch') };
    const ticket = await client.verifyIdToken({
      idToken: token,
      audience: process.env.GOOGLE_CLIENT_ID,
    });
    const payload = ticket.getPayload();
    const email = payload.email;
    const sub = payload.sub;

    // Return user data without a channelId for now
    const user = {
      email: email || 'unknown',
      sub: sub, // Keep sub for reference
    };

    res.json({ user });
  } catch (err) {
    console.error('OAuth Error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/check-links', async (req, res) => {
  const { channelId, maxVideos } = req.body;
  if (!channelId || !maxVideos) {
    return res.status(400).json({ error: 'Missing channelId or maxVideos' });
  }

  try {
    const python = spawn('python', ['check_links.py', channelId, maxVideos]);
    let output = '';
    let errorOutput = '';

    python.stdout.on('data', (data) => {
      output += data.toString();
    });

    python.stderr.on('data', (data) => {
      errorOutput += data.toString();
    });

    python.on('close', async (code) => {
      if (code !== 0) {
        return res.status(500).json({ error: `AffiliateBot script failed: ${errorOutput}` });
      }

      const brokenLinks = [];
      const lines = output.split('\n');
      let currentVideoId = null;
      for (const line of lines) {
        if (line.startsWith('Video: ')) {
          currentVideoId = line.split('v=')[1];
        } else if (line.startsWith('Broken link: ')) {
          const link = line.replace('Broken link: ', '');
          brokenLinks.push({ videoId: currentVideoId, link });
          await pool.query(
            'INSERT INTO broken_links (channel_id, video_id, broken_link, checked_at) VALUES ($1, $2, $3, NOW())',
            [channelId, currentVideoId, link]
          );
        }
      }

      res.json({ brokenLinks });
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.listen(3001, () => console.log('AffiliateBot server running on http://localhost:3001'));