"""Pulls commissions automatically from affiliate network reporting APIs.

eBay Partner Network (Transaction Detail Report API)
    Needs in .env: EPN_ACCOUNT_SID and EPN_AUTH_TOKEN
    (partner portal > Account > API / "Access Tokens").
    Report fields used: CustomId, Earnings, Sales, EventDate, EpnTransactionId.

Amazon Associates has no earnings API. Amazon commissions only reach the
dashboard if you import the Earnings report CSV yourself (optional).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from . import db
from .config import secret
from .earnings import import_csv

log = logging.getLogger(__name__)

EPN_REPORT_URL = "https://api.partner.ebay.com/mediapartners/{sid}/reports/ebay_partner_transaction_detail.csv"


def sync_epn(conn, days_back: int = 45) -> dict[str, int]:
    sid, token = secret("EPN_ACCOUNT_SID"), secret("EPN_AUTH_TOKEN")
    if not (sid and token):
        raise RuntimeError("EPN_ACCOUNT_SID / EPN_AUTH_TOKEN missing from .env")
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days_back)
    resp = requests.get(
        EPN_REPORT_URL.format(sid=sid),
        auth=(sid, token),
        params={
            "STATUS": "ALL",                    # pending + approved, so new sales show up quickly
            "START_DATE": start.isoformat(),
            "END_DATE": end.isoformat(),
            "DATE_TYPE": "update_date",         # catch older sales whose status changed
        },
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"eBay Partner Network {resp.status_code}: {resp.text[:200]}")
    text = resp.content.decode("utf-8-sig", errors="replace")
    if not text.strip() or text.count("\n") < 1:
        return {"imported": 0, "updated": 0, "duplicates": 0, "matched": 0, "skipped": 0}
    return import_csv(conn, text, "ebay")


SYNCERS = {"ebay": sync_epn}


def sync_due(conn, every_hours: float) -> bool:
    last = conn.execute(
        "SELECT started_at FROM runs WHERE kind = 'sync' ORDER BY id DESC LIMIT 1").fetchone()
    if not last:
        return True
    age = datetime.now(timezone.utc) - datetime.fromisoformat(last["started_at"])
    return age >= timedelta(hours=every_hours)


def sync_earnings(cfg: dict[str, Any], force: bool = False) -> dict[str, Any]:
    """Sync every configured network. Runs at most every `earnings_sync.every_hours` unless forced."""
    opts = cfg.get("earnings_sync") or {}
    networks = [n for n in (opts.get("networks") or []) if n in SYNCERS]
    result: dict[str, Any] = {"ran": False, "networks": {}, "errors": []}
    if not networks:
        return result
    with db.session(cfg["database"]) as conn:
        if not force and not sync_due(conn, float(opts.get("every_hours", 6))):
            return result
        run_id = db.start_run(conn, "sync")
        result["ran"] = True
        for name in networks:
            try:
                stats = SYNCERS[name](conn, int(opts.get("days_back", 45)))
                result["networks"][name] = stats
                log.info("Earnings sync %s: %s", name, stats)
            except Exception as exc:
                result["errors"].append(f"{name}: {exc}")
                log.error("Earnings sync %s failed: %s", name, exc)
        new = sum(s.get("imported", 0) for s in result["networks"].values())
        db.finish_run(conn, run_id, added=new,
                      message="; ".join(result["errors"])[:500] or None)
    return result
