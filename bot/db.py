"""SQLite storage shared by the bot and the dashboard."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,
    external_id     TEXT NOT NULL,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL,
    affiliate_url   TEXT NOT NULL,
    price           REAL NOT NULL,
    original_price  REAL,
    discount_pct    REAL,
    currency        TEXT DEFAULT 'USD',
    category        TEXT,
    image_url       TEXT,
    tracking_id     TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'queued',  -- queued | approved | posted | skipped | failed
    found_at        TEXT NOT NULL,
    UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id     INTEGER NOT NULL REFERENCES deals(id),
    tweet_id    TEXT,
    text        TEXT NOT NULL,
    posted_at   TEXT NOT NULL,
    cost_usd    REAL NOT NULL DEFAULT 0,
    dry_run     INTEGER NOT NULL DEFAULT 1,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS earnings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    network      TEXT NOT NULL,
    tracking_id  TEXT,
    event_date   TEXT NOT NULL,
    sale_amount  REAL DEFAULT 0,
    commission   REAL NOT NULL DEFAULT 0,
    order_ref    TEXT NOT NULL,
    imported_at  TEXT NOT NULL,
    UNIQUE (network, order_ref)
);

CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,
    amount_usd  REAL NOT NULL,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    found        INTEGER DEFAULT 0,
    added        INTEGER DEFAULT 0,
    posted       INTEGER DEFAULT 0,
    message      TEXT
);

CREATE INDEX IF NOT EXISTS idx_deals_status ON deals(status);
CREATE INDEX IF NOT EXISTS idx_posts_posted_at ON posts(posted_at);
CREATE INDEX IF NOT EXISTS idx_earnings_tracking ON earnings(tracking_id);
CREATE INDEX IF NOT EXISTS idx_earnings_date ON earnings(event_date);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # lets the bot write while the dashboard reads
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def session(path: str) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------- settings (dashboard-editable, override config defaults) ----------

def _coerce(raw: str, default: Any) -> Any:
    if isinstance(default, bool):
        return raw.lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(float(raw))
    if isinstance(default, float):
        return float(raw)
    return raw


def get_settings(conn: sqlite3.Connection, defaults: dict[str, Any]) -> dict[str, Any]:
    stored = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    out = dict(defaults)
    for key, default in defaults.items():
        if key in stored:
            try:
                out[key] = _coerce(stored[key], default)
            except ValueError:
                pass
    return out


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    if isinstance(value, bool):
        value = "true" if value else "false"
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


# ---------- runs log ----------

def start_run(conn: sqlite3.Connection, kind: str) -> int:
    cur = conn.execute("INSERT INTO runs(kind, started_at) VALUES(?, ?)", (kind, now_iso()))
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, **fields: Any) -> None:
    fields["finished_at"] = now_iso()
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE runs SET {cols} WHERE id = ?", (*fields.values(), run_id))
    conn.commit()
