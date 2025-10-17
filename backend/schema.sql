
CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  stripe_customer_id VARCHAR(255) UNIQUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE subscriptions (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  stripe_subscription_id VARCHAR(255) UNIQUE NOT NULL,
  plan_type VARCHAR(50),
  status VARCHAR(50) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (user_id, stripe_subscription_id)
);

CREATE TABLE broken_links (
  id SERIAL PRIMARY KEY,
  channel_id VARCHAR(255) NOT NULL,
  video_id VARCHAR(255) NOT NULL,
  broken_link TEXT NOT NULL,
  checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);