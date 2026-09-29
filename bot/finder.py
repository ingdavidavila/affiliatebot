"""Fetch deals from every enabled source, filter them, and queue the good ones."""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from . import db
from .models import Deal, new_tracking_id
from .sources import enabled_sources

log = logging.getLogger(__name__)


def _keywords(raw: str) -> list[str]:
    return [k.strip().lower() for k in (raw or "").split(",") if k.strip()]


def passes_filters(deal: Deal, settings: dict[str, Any]) -> tuple[bool, str]:
    pct = deal.discount_pct
    if pct is None:
        return False, "no discount"
    if pct < float(settings["min_discount_pct"]):
        return False, f"discount {pct}% below minimum"
    if deal.price < float(settings["min_price"]):
        return False, "price below minimum"
    if deal.price > float(settings["max_price"]):
        return False, "price above maximum"
    title = deal.title.lower()
    for kw in _keywords(settings.get("blocked_keywords", "")):
        if kw in title:
            return False, f"blocked keyword '{kw}'"
    return True, "ok"


def save_deal(conn: sqlite3.Connection, deal: Deal, affiliate_url: str, tracking_id: str, status: str) -> bool:
    """Insert a deal. Returns False if we've already seen it (dedupe)."""
    cur = conn.execute(
        """INSERT OR IGNORE INTO deals
           (source, external_id, title, url, affiliate_url, price, original_price,
            discount_pct, currency, category, image_url, tracking_id, status, found_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (deal.source, deal.external_id, deal.title, deal.url, affiliate_url, deal.price,
         deal.original_price, deal.discount_pct, deal.currency, deal.category,
         deal.image_url, tracking_id, status, db.now_iso()),
    )
    return cur.rowcount == 1


def find_deals(cfg: dict[str, Any]) -> dict[str, int]:
    """One finder pass. Returns counts for logging and the dashboard."""
    counts = {"found": 0, "passed": 0, "added": 0, "errors": 0}
    with db.session(cfg["database"]) as conn:
        settings = db.get_settings(conn, cfg["settings"])
        run_id = db.start_run(conn, "find")
        status = "queued" if settings["approval_mode"] else "approved"
        messages = []
        for source in enabled_sources(cfg):
            try:
                deals = source.fetch()
            except Exception as exc:  # one broken source shouldn't stop the others
                counts["errors"] += 1
                messages.append(f"{source.name}: {exc}")
                log.exception("Source %s failed", source.name)
                continue
            counts["found"] += len(deals)
            for deal in deals:
                ok, reason = passes_filters(deal, settings)
                if not ok:
                    log.debug("Skip %s: %s", deal.title, reason)
                    continue
                counts["passed"] += 1
                exists = conn.execute(
                    "SELECT 1 FROM deals WHERE source=? AND external_id=?",
                    (deal.source, deal.external_id),
                ).fetchone()
                if exists:
                    continue
                tracking_id = new_tracking_id()
                try:
                    link = source.affiliate_url(deal, tracking_id)
                except Exception as exc:
                    counts["errors"] += 1
                    messages.append(f"{source.name} link: {exc}")
                    break  # usually a missing key; same error for every deal
                if save_deal(conn, deal, link, tracking_id, status):
                    counts["added"] += 1
        conn.commit()
        db.finish_run(conn, run_id, found=counts["found"], added=counts["added"],
                      message="; ".join(messages)[:500] or None)
    log.info("Finder: %s", counts)
    return counts
