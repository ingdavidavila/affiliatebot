"""Import commission reports (CSV) from affiliate networks.

Networks name their columns differently, so each field is matched against a
list of common header names. Download the transaction/earnings report from
your network, then import it from the dashboard's Earnings page or with:

    python -m bot import-earnings report.csv --network ebay

Rows whose tracking/custom id matches one of our posts are credited to that
post; everything else counts as "unattributed" earnings.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import sqlite3
from datetime import datetime
from typing import IO, Any, Iterable

from . import db

FIELD_ALIASES: dict[str, list[str]] = {
    # Headers are normalized first: lower case, underscores -> spaces ("Custom_ID" -> "custom id").
    "tracking_id": ["tracking id", "custom id", "customid", "sub id", "subid", "subid1", "sub id 1",
                    "shared id", "sharedid", "u1", "member id", "sid"],
    "commission": ["commission", "earnings", "total earnings", "payout", "ad fees", "ad fees($)",
                   "ad fees ($)", "publisher commission", "commission amount", "action earnings"],
    "event_date": ["event date", "eventdate", "date", "transaction date", "date shipped",
                   "action date", "sale date", "order date", "click date", "posting date"],
    "sale_amount": ["sale amount", "sales", "revenue", "order amount",
                    "item price", "price", "price($)", "price ($)", "sale value", "gmv"],
    "order_ref": ["order ref", "epntransactionid", "epn transaction id", "order id", "transaction id",
                  "checkout transaction id", "action id", "event id", "item id", "asin", "id"],
}


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").replace("_", " ").strip().lower())


def map_columns(headers: Iterable[str]) -> dict[str, str | None]:
    normalized = {_norm(h): h for h in headers}
    mapping: dict[str, str | None] = {}
    for field, aliases in FIELD_ALIASES.items():
        mapping[field] = next((normalized[a] for a in aliases if a in normalized), None)
    return mapping


def _money(raw: Any) -> float:
    if raw is None:
        return 0.0
    s = str(raw).strip().replace(",", "")
    neg = s.startswith("(") and s.endswith(")") or s.startswith("-")
    s = re.sub(r"[^0-9.]", "", s)
    if not s:
        return 0.0
    val = float(s)
    return -val if neg else val


def _date(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return datetime.now().date().isoformat()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    date_part = s.split(" ")[0] if re.match(r"^\d", s) else s
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y", "%b %d, %Y", "%B %d, %Y"):
        for candidate in (s, date_part):
            try:
                return datetime.strptime(candidate, fmt).date().isoformat()
            except ValueError:
                continue
    return s[:10]


def import_rows(conn: sqlite3.Connection, rows: list[dict[str, Any]], network: str) -> dict[str, int]:
    if not rows:
        return {"imported": 0, "duplicates": 0, "matched": 0, "skipped": 0}
    mapping = map_columns(rows[0].keys())
    if not mapping["commission"]:
        raise ValueError(
            "Couldn't find a commission/earnings column. Columns in file: "
            + ", ".join(rows[0].keys())
        )
    known = {r["tracking_id"] for r in conn.execute("SELECT tracking_id FROM deals")}
    stats = {"imported": 0, "updated": 0, "duplicates": 0, "matched": 0, "skipped": 0}
    seen: dict[str, int] = {}
    for row in rows:
        get = lambda f: row.get(mapping[f]) if mapping[f] else None  # noqa: E731
        commission = _money(get("commission"))
        if commission == 0 and not get("order_ref"):
            stats["skipped"] += 1
            continue
        tracking = (str(get("tracking_id") or "").strip()) or None
        order_ref = str(get("order_ref") or "").strip()
        if not order_ref:  # no id column: fingerprint the row so re-imports don't double count
            order_ref = "row-" + hashlib.sha1(repr(sorted(row.items())).encode()).hexdigest()[:16]
        # Same id twice in one report (e.g. a return adjustment) -> keep both lines.
        seen[order_ref] = seen.get(order_ref, 0) + 1
        if seen[order_ref] > 1:
            order_ref = f"{order_ref}#{seen[order_ref]}"
        values = (tracking, _date(get("event_date")), _money(get("sale_amount")), commission)
        old = conn.execute(
            "SELECT tracking_id, event_date, sale_amount, commission FROM earnings "
            "WHERE network = ? AND order_ref = ?", (network, order_ref)).fetchone()
        if old is None:
            conn.execute(
                "INSERT INTO earnings(network, tracking_id, event_date, sale_amount, "
                "commission, order_ref, imported_at) VALUES (?,?,?,?,?,?,?)",
                (network, *values, order_ref, db.now_iso()),
            )
            stats["imported"] += 1
            if tracking in known:
                stats["matched"] += 1
        elif tuple(old) != values:
            # Networks revise commissions later (pending -> approved, returns), so keep the latest.
            conn.execute(
                "UPDATE earnings SET tracking_id=?, event_date=?, sale_amount=?, commission=?, imported_at=? "
                "WHERE network = ? AND order_ref = ?", (*values, db.now_iso(), network, order_ref))
            stats["updated"] += 1
        else:
            stats["duplicates"] += 1
    conn.commit()
    return stats


def import_csv(conn: sqlite3.Connection, fh: IO[str] | str, network: str) -> dict[str, int]:
    text = fh if isinstance(fh, str) else fh.read()
    text = text.lstrip("﻿")
    # Some reports have a few title lines before the real header; skip to the first line with commas.
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.count(",") >= 2), 0)
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    rows = [r for r in reader if any((v or "").strip() for v in r.values())]
    return import_rows(conn, rows, network)
