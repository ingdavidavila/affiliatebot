"""Picks the best approved deal and posts it, within your daily limits and budget."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from . import db
from .composer import compose

log = logging.getLogger(__name__)


def _today_start_utc() -> str:
    # "Today" in your Mac's local time zone, expressed in UTC for the query.
    local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc).isoformat()


def post_cost(cfg: dict[str, Any], has_link: bool = True) -> float:
    costs = cfg["costs"]
    return float(costs["x_post_with_link_usd"] if has_link else costs["x_post_without_link_usd"])


def limits_status(conn: sqlite3.Connection, cfg: dict[str, Any], settings: dict[str, Any]) -> tuple[bool, str]:
    """Can we post right now? Returns (ok, reason)."""
    if settings["paused"]:
        return False, "Bot is paused"
    since = _today_start_utc()
    row = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(cost_usd),0) AS spend FROM posts "
        "WHERE posted_at >= ? AND error IS NULL AND dry_run = ?",
        (since, 1 if cfg["dry_run"] else 0),
    ).fetchone()
    if row["n"] >= int(settings["max_posts_per_day"]):
        return False, f"Daily post limit reached ({row['n']})"
    if row["spend"] + post_cost(cfg) > float(settings["daily_budget_usd"]) + 1e-9:
        return False, f"Daily budget reached (${row['spend']:.2f} spent)"
    last = conn.execute(
        "SELECT posted_at FROM posts WHERE error IS NULL AND dry_run = ? ORDER BY posted_at DESC LIMIT 1",
        (1 if cfg["dry_run"] else 0,),
    ).fetchone()
    if last:
        gap = datetime.now(timezone.utc) - datetime.fromisoformat(last["posted_at"])
        wait = timedelta(minutes=int(settings["min_minutes_between_posts"]))
        if gap < wait:
            mins = int((wait - gap).total_seconds() // 60) + 1
            return False, f"Waiting {mins} more min between posts"
    return True, "ok"


def _next_deal(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM deals WHERE status = 'approved' "
        "ORDER BY discount_pct DESC, found_at DESC LIMIT 1"
    ).fetchone()


def post_one(conn: sqlite3.Connection, cfg: dict[str, Any], settings: dict[str, Any],
             deal_id: int | None = None, client=None) -> dict[str, Any]:
    """Post a single deal (the best approved one, or a specific one)."""
    deal = (conn.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
            if deal_id else _next_deal(conn))
    if deal is None:
        return {"posted": False, "reason": "No approved deals waiting"}

    text = compose(dict(deal), settings)
    dry = bool(cfg["dry_run"])
    tweet_id, error = None, None
    if dry:
        tweet_id = f"dry-{deal['id']}"
        log.info("[DRY RUN] Would post:\n%s", text)
    else:
        try:
            if client is None:
                from .x_client import XClient
                client = XClient()
            tweet_id = client.post(text)
        except Exception as exc:
            error = str(exc)[:500]
            log.error("Posting failed: %s", error)

    cost = 0.0 if error else post_cost(cfg)
    conn.execute(
        "INSERT INTO posts(deal_id, tweet_id, text, posted_at, cost_usd, dry_run, error) "
        "VALUES (?,?,?,?,?,?,?)",
        (deal["id"], tweet_id, text, db.now_iso(), cost, 1 if dry else 0, error),
    )
    conn.execute("UPDATE deals SET status = ? WHERE id = ?",
                 ("failed" if error else "posted", deal["id"]))
    conn.commit()
    return {"posted": error is None, "reason": error or "ok", "text": text, "tweet_id": tweet_id}


def run_poster(cfg: dict[str, Any], client=None) -> dict[str, Any]:
    posted, reasons = 0, []
    with db.session(cfg["database"]) as conn:
        settings = db.get_settings(conn, cfg["settings"])
        run_id = db.start_run(conn, "post")
        for _ in range(max(1, int(settings["posts_per_run"]))):
            ok, reason = limits_status(conn, cfg, settings)
            if not ok:
                reasons.append(reason)
                break
            result = post_one(conn, cfg, settings, client=client)
            if not result["posted"]:
                reasons.append(result["reason"])
                break
            posted += 1
        db.finish_run(conn, run_id, posted=posted, message="; ".join(reasons) or None)
    log.info("Poster: posted %d. %s", posted, "; ".join(reasons))
    return {"posted": posted, "reasons": reasons}
