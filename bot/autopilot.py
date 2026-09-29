"""Decisions the bot makes on its own, so it can run without anyone approving deals.

- score():         ranks approved deals. Starts from the discount, then learns from
                   your own sales history which categories actually earn money.
- expire_stale():  drops deals that sat too long (prices change, links go stale).
- failure_cooldown(): after several failed posts in a row, waits a few hours and
                   then tries again by itself, instead of burning money or needing a human.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

FAILURES_BEFORE_COOLDOWN = 3


def category_performance(conn: sqlite3.Connection, days: int = 60, min_posts: int = 8) -> dict[str, float]:
    """Net earnings per post, by category, for categories with enough history to trust."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    earned_by_tid = {r["tracking_id"]: r["c"] for r in conn.execute(
        "SELECT tracking_id, SUM(commission) c FROM earnings WHERE tracking_id IS NOT NULL GROUP BY tracking_id")}
    agg: dict[str, list[float]] = {}  # category -> [posts, net]
    for r in conn.execute(
            "SELECT COALESCE(d.category, 'Other') c, d.tracking_id, p.cost_usd FROM posts p "
            "JOIN deals d ON d.id = p.deal_id WHERE p.posted_at >= ? AND p.error IS NULL", (since,)):
        a = agg.setdefault(r["c"], [0, 0.0])
        a[0] += 1
        a[1] += earned_by_tid.get(r["tracking_id"], 0.0) - r["cost_usd"]
    return {cat: net / posts for cat, (posts, net) in agg.items() if posts >= min_posts}


def recent_categories(conn: sqlite3.Connection, n: int) -> list[str]:
    rows = conn.execute(
        "SELECT COALESCE(d.category, 'Other') c FROM posts p JOIN deals d ON d.id = p.deal_id "
        "WHERE p.error IS NULL ORDER BY p.posted_at DESC LIMIT ?", (n,)).fetchall()
    return [r["c"] for r in rows]


def score(deal: sqlite3.Row | dict, settings: dict[str, Any], perf: dict[str, float],
          recent: list[str]) -> float:
    s = float(deal["discount_pct"] or 0)
    price = float(deal["price"] or 0)
    if 25 <= price <= 300:          # big enough to earn a commission, cheap enough to impulse-buy
        s += 10
    cat = deal["category"] or "Other"
    s -= 15 * recent.count(cat)     # don't post five air fryers in a row
    if settings.get("learn_from_sales") and cat in perf:
        # +/- up to 25 points depending on how much this category has earned per post
        s += max(-25.0, min(25.0, perf[cat] * 25))
    return s


def pick_best(conn: sqlite3.Connection, settings: dict[str, Any]) -> sqlite3.Row | None:
    deals = conn.execute(
        "SELECT * FROM deals WHERE status = 'approved' ORDER BY found_at DESC LIMIT 300").fetchall()
    if not deals:
        return None
    perf = category_performance(conn) if settings.get("learn_from_sales") else {}
    recent = recent_categories(conn, int(settings.get("category_cooldown_posts", 3)))
    return max(deals, key=lambda d: score(d, settings, perf, recent))


def expire_stale(conn: sqlite3.Connection, max_age_hours: float) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    cur = conn.execute(
        "UPDATE deals SET status = 'expired' WHERE status IN ('queued', 'approved') AND found_at < ?",
        (cutoff,))
    return cur.rowcount


def failure_cooldown(conn: sqlite3.Connection, dry_run: bool, hours: float) -> str | None:
    """If the last few live posts all failed, wait `hours` before trying again."""
    rows = conn.execute(
        "SELECT posted_at, error FROM posts WHERE dry_run = ? ORDER BY posted_at DESC LIMIT ?",
        (1 if dry_run else 0, FAILURES_BEFORE_COOLDOWN)).fetchall()
    if len(rows) < FAILURES_BEFORE_COOLDOWN or not all(r["error"] for r in rows):
        return None
    last = datetime.fromisoformat(rows[0]["posted_at"])
    wait_until = last + timedelta(hours=hours)
    if datetime.now(timezone.utc) < wait_until:
        mins = int((wait_until - datetime.now(timezone.utc)).total_seconds() // 60) + 1
        return (f"Last {FAILURES_BEFORE_COOLDOWN} posts failed ({rows[0]['error'][:80]}). "
                f"Retrying automatically in {mins} min")
    return None


def housekeeping(conn: sqlite3.Connection, settings: dict[str, Any]) -> dict[str, int]:
    expired = expire_stale(conn, float(settings.get("max_deal_age_hours", 24)))
    conn.commit()
    return {"expired": expired}
