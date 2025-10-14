require('dotenv').config();
const express = require('express');
const { spawn } = require('child_process');
const { Pool } = require('pg');
const cors = require('cors');
const { google } = require('googleapis');

const app = express();
app.use(cors());
app.use(express.json());

const pool = new Pool({
  user: 'postgres',
  host: 'localhost',
  database: 'affiliatebot',
  password: process.env.POSTGRES_PASSWORD, // Loaded from .env
  port: 5432,
});

const oauth2Client = new google.auth.OAuth2(
  process.env.GOOGLE_CLIENT_ID, // Loaded from .env
  process.env.GOOGLE_CLIENT_SECRET, // Loaded from .env
  'http://localhost:3001/api/auth/google/callback'
);

app.post('/api/auth/google', async (req, res) => {
  const { token } = req.body;
  if (!token) {
    return res.status(400).json({ error: 'Missing token' });
  }

  try {
    oauth2Client.setCredentials({ access_token: token });
    const youtube = google.youtube({ version: 'v3', auth: oauth2Client });
    const channelResponse = await youtube.channels.list({
      part: 'id,snippet',
      mine: true,
    });

    if (!channelResponse.data.items || channelResponse.data.items.length === 0) {
      return res.status(400).json({ error: 'No YouTube channel found for this account' });
    }

    const user = {
      channelId: channelResponse.data.items[0].id,
      email: channelResponse.data.items[0].snippet.customUrl || 'unknown',
    };

    res.json({ user });
  } catch (err) {
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