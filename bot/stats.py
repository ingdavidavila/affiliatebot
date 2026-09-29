"""Numbers for the dashboard: earnings, X spend and profit over a period."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any


def _since(days: int) -> tuple[str, str]:
    """(UTC timestamp for posts, local date for earnings) at the start of the window."""
    start_local = (datetime.now().astimezone() - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(timezone.utc).isoformat(), start_local.date().isoformat()


def summary(conn: sqlite3.Connection, days: int = 30, dry_run: bool | None = None) -> dict[str, Any]:
    ts, d = _since(days)
    dry_clause, params = "", [ts]
    if dry_run is not None:
        dry_clause, params = " AND dry_run = ?", [ts, 1 if dry_run else 0]
    p = conn.execute(
        f"SELECT COUNT(*) n, COALESCE(SUM(cost_usd),0) spend FROM posts "
        f"WHERE posted_at >= ? AND error IS NULL{dry_clause}", params).fetchone()
    e = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(commission),0) c, COALESCE(SUM(sale_amount),0) s, "
        "COALESCE(SUM(CASE WHEN tracking_id IN (SELECT tracking_id FROM deals) THEN commission END),0) attributed "
        "FROM earnings WHERE event_date >= ?", (d,)).fetchone()
    x = conn.execute("SELECT COALESCE(SUM(amount_usd),0) a FROM expenses WHERE date >= ?", (d,)).fetchone()
    q = conn.execute("SELECT COUNT(*) n FROM deals WHERE status = 'queued'").fetchone()
    a = conn.execute("SELECT COUNT(*) n FROM deals WHERE status = 'approved'").fetchone()
    selling = conn.execute(
        f"SELECT COUNT(DISTINCT p.id) n FROM posts p JOIN deals dl ON dl.id = p.deal_id "
        f"JOIN earnings er ON er.tracking_id = dl.tracking_id "
        f"WHERE p.posted_at >= ? AND p.error IS NULL{dry_clause.replace('dry_run', 'p.dry_run')}",
        params).fetchone()
    commission = float(e["c"])
    spend = float(p["spend"])
    other = float(x["a"])
    return {
        "days": days,
        "posts": int(p["n"]),
        "spend": spend,
        "other_expenses": other,
        "commission": commission,
        "attributed": float(e["attributed"]),
        "unattributed": commission - float(e["attributed"]),
        "sales": int(e["n"]),
        "sales_volume": float(e["s"]),
        "net": commission - spend - other,
        "roi": (commission - spend - other) / (spend + other) if (spend + other) else None,
        "posts_with_sales": int(selling["n"]),
        "queued": int(q["n"]),
        "approved": int(a["n"]),
    }


def daily(conn: sqlite3.Connection, days: int = 30, dry_run: bool | None = None) -> list[dict[str, Any]]:
    """One row per local day: commission, X spend, net."""
    ts, d = _since(days)
    rows: dict[str, dict[str, Any]] = {}
    start = date.fromisoformat(d)
    for i in range(days):
        key = (start + timedelta(days=i)).isoformat()
        rows[key] = {"date": key, "commission": 0.0, "spend": 0.0, "posts": 0}
    dry_clause, params = "", [ts]
    if dry_run is not None:
        dry_clause, params = " AND dry_run = ?", [ts, 1 if dry_run else 0]
    for r in conn.execute(f"SELECT posted_at, cost_usd FROM posts WHERE posted_at >= ? AND error IS NULL{dry_clause}", params):
        key = datetime.fromisoformat(r["posted_at"]).astimezone().date().isoformat()
        if key in rows:
            rows[key]["spend"] += r["cost_usd"]
            rows[key]["posts"] += 1
    for r in conn.execute("SELECT event_date, SUM(commission) c FROM earnings WHERE event_date >= ? GROUP BY event_date", (d,)):
        if r["event_date"] in rows:
            rows[r["event_date"]]["commission"] += r["c"]
    for r in conn.execute("SELECT date, SUM(amount_usd) a FROM expenses WHERE date >= ? GROUP BY date", (d,)):
        if r["date"] in rows:
            rows[r["date"]]["spend"] += r["a"]
    out = list(rows.values())
    for r in out:
        r["net"] = r["commission"] - r["spend"]
    return out


def posts_table(conn: sqlite3.Connection, days: int = 30, limit: int = 200,
                dry_run: bool | None = None, order: str = "recent") -> list[dict[str, Any]]:
    ts, _ = _since(days)
    dry_clause, params = "", [ts]
    if dry_run is not None:
        dry_clause, params = " AND p.dry_run = ?", [ts, 1 if dry_run else 0]
    order_sql = "commission DESC, p.posted_at DESC" if order == "top" else "p.posted_at DESC"
    sql = f"""
        SELECT p.id, p.posted_at, p.text, p.cost_usd, p.tweet_id, p.dry_run, p.error,
               d.title, d.source, d.category, d.price, d.discount_pct, d.affiliate_url, d.tracking_id,
               COALESCE(SUM(e.commission), 0) AS commission, COUNT(e.id) AS sales
        FROM posts p JOIN deals d ON d.id = p.deal_id
        LEFT JOIN earnings e ON e.tracking_id = d.tracking_id
        WHERE p.posted_at >= ?{dry_clause}
        GROUP BY p.id ORDER BY {order_sql} LIMIT ?"""
    return [dict(r) for r in conn.execute(sql, (*params, limit))]


def by_category(conn: sqlite3.Connection, days: int = 30, dry_run: bool | None = None) -> list[dict[str, Any]]:
    rows = posts_table(conn, days, limit=100000, dry_run=dry_run)
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["error"]:
            continue
        k = r["category"] or "Other"
        a = agg.setdefault(k, {"category": k, "posts": 0, "commission": 0.0, "spend": 0.0, "sales": 0})
        a["posts"] += 1
        a["commission"] += r["commission"]
        a["spend"] += r["cost_usd"]
        a["sales"] += r["sales"]
    out = sorted(agg.values(), key=lambda a: a["commission"] - a["spend"], reverse=True)
    for a in out:
        a["net"] = a["commission"] - a["spend"]
    return out
