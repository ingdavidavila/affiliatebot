"""Deals you add yourself in a CSV file (handy for Amazon until you qualify for its API).

CSV columns: title,url,price,original_price,category
Amazon links get your Associates tag added automatically (AMAZON_ASSOCIATE_TAG in .env).
Other links are used as-is, so paste an affiliate link you already generated.
"""
from __future__ import annotations

import csv
import hashlib
import logging
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..config import ROOT, secret
from ..models import Deal
from .base import Source

log = logging.getLogger(__name__)


def is_amazon(url: str) -> bool:
    host = urlsplit(url).netloc.lower()
    return host.endswith("amazon.com") or ".amazon." in host or host.startswith("amazon.") or host == "amzn.to"


def add_amazon_tag(url: str, tag: str) -> str:
    parts = urlsplit(url)
    params = [(k, v) for k, v in parse_qsl(parts.query) if k != "tag"]
    params.append(("tag", tag))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))


class ManualSource(Source):
    name = "manual"

    def fetch(self) -> list[Deal]:
        path = Path(self.options.get("file", "data/manual_deals.csv"))
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            log.info("Manual deals file not found: %s", path)
            return []
        deals = []
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                try:
                    url = row["url"].strip()
                    deals.append(
                        Deal(
                            source=self.name,
                            external_id=hashlib.sha1(url.encode()).hexdigest()[:16],
                            title=row["title"].strip(),
                            url=url,
                            price=float(row["price"]),
                            original_price=float(row["original_price"]) if row.get("original_price") else None,
                            category=(row.get("category") or "").strip() or None,
                        )
                    )
                except (KeyError, ValueError) as exc:
                    log.warning("Skipping bad row in %s: %s (%s)", path.name, row, exc)
        return deals

    def affiliate_url(self, deal: Deal, tracking_id: str) -> str:
        if is_amazon(deal.url):
            tag = secret("AMAZON_ASSOCIATE_TAG")
            if not tag:
                raise RuntimeError("AMAZON_ASSOCIATE_TAG missing from .env")
            # Amazon reports earnings per tag, not per link, so these sales
            # show up in the dashboard as "unattributed" rather than per post.
            return add_amazon_tag(deal.url, tag)
        return deal.url
