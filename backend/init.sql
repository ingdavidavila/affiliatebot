CREATE TABLE broken_links (
    id SERIAL PRIMARY KEY,
    channel_id VARCHAR(255) NOT NULL,
    video_id VARCHAR(50) NOT NULL,
    broken_link TEXT NOT NULL,
    checked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);