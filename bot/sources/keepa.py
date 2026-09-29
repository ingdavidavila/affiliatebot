"""Automatic Amazon deals from Keepa's price-history database (keepa.com).

Why Keepa: Amazon's own product API needs 10 sales in 30 days before you can
use it. Keepa tracks Amazon prices independently, so the bot can find real
price drops (compared with the 90-day average, not a made-up "list price")
from day one.

Needs in .env:
    KEEPA_API_KEY         - from keepa.com > API (paid plan)
    AMAZON_ASSOCIATE_TAG  - your Associates store tag, e.g. yourname-20

Amazon's Associates rules restrict showing prices that didn't come from
Amazon's own API, so posts for these deals show the % drop but no price
(see `show_price = False`). Check Amazon's current Program Policies yourself.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import requests

from ..config import secret
from ..models import Deal
from .base import Source
from .manual import add_amazon_tag

log = logging.getLogger(__name__)

DEAL_URL = "https://api.keepa.com/deal"

DOMAINS = {  # Keepa domain ids -> Amazon site
    "US": (1, "www.amazon.com", "USD"),
    "GB": (2, "www.amazon.co.uk", "GBP"),
    "DE": (3, "www.amazon.de", "EUR"),
    "CA": (6, "www.amazon.ca", "CAD"),
}
PRICE_TYPES = {"amazon": 0, "new": 1}      # 0 = sold by Amazon, 1 = new from third-party sellers
DATE_RANGES = {"day": 0, "week": 1, "month": 2, "90days": 3}

# Amazon US top-level category ids (Keepa "rootCat") -> names, for the dashboard.
ROOT_CATEGORIES = {
    172282: "Electronics", 1055398: "Home & Kitchen", 228013: "Tools", 165793011: "Toys",
    3375251: "Sports", 7141123011: "Clothing", 3760911: "Beauty", 3760901: "Health",
    468642: "Video Games", 2619533011: "Pet Supplies", 1064954: "Office", 283155: "Books",
    16310101: "Grocery", 165796011: "Baby", 15684181: "Automotive", 2972638011: "Garden",
    2619525011: "Appliances", 2617941011: "Arts & Crafts", 11091801: "Musical Instruments",
}


def _pick(arr: Any, *idx: int) -> Any:
    """Safe nested index into Keepa's arrays (missing values are -1 or absent)."""
    for i in idx:
        if not isinstance(arr, list) or i >= len(arr):
            return None
        arr = arr[i]
    return arr


def _image_name(raw: Any) -> str | None:
    # Keepa sends the image file name either as a string or as a list of character codes.
    if isinstance(raw, str):
        return raw or None
    if isinstance(raw, list) and raw and all(isinstance(c, int) for c in raw):
        return "".join(chr(c) for c in raw)
    return None


class KeepaSource(Source):
    name = "keepa"
    show_price = False

    def __init__(self, options: dict[str, Any]):
        super().__init__(options)
        self.session = requests.Session()

    def _selection(self, page: int) -> dict[str, Any]:
        o = self.options
        domain_id = DOMAINS.get(o.get("domain", "US"), DOMAINS["US"])[0]
        sel: dict[str, Any] = {
            "page": page,
            "domainId": domain_id,
            "priceTypes": [PRICE_TYPES.get(o.get("price_type", "amazon"), 0)],
            "dateRange": DATE_RANGES.get(o.get("compare_to", "90days"), 3),
            "deltaPercentRange": [int(o.get("min_drop_pct", 30)), 100],
            "currentRange": [int(float(o.get("min_price", 10)) * 100), int(float(o.get("max_price", 1000)) * 100)],
            "isRangeEnabled": True,
            "hasReviews": True,
            "filterErotic": True,
        }
        if o.get("include_categories"):
            sel["includeCategories"] = [int(c) for c in o["include_categories"]]
        if o.get("exclude_categories"):
            sel["excludeCategories"] = [int(c) for c in o["exclude_categories"]]
        return sel

    def fetch(self) -> list[Deal]:
        key = secret("KEEPA_API_KEY")
        if not key:
            raise RuntimeError("KEEPA_API_KEY missing from .env")
        domain, host, currency = DOMAINS.get(self.options.get("domain", "US"), DOMAINS["US"])
        price_type = PRICE_TYPES.get(self.options.get("price_type", "amazon"), 0)
        date_range = DATE_RANGES.get(self.options.get("compare_to", "90days"), 3)
        deals: list[Deal] = []
        for page in range(int(self.options.get("pages", 1))):  # 150 deals per page, 5 tokens each
            resp = self.session.get(
                DEAL_URL,
                params={"key": key, "domain": domain, "selection": json.dumps(self._selection(page))},
                timeout=30,
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"Keepa {resp.status_code}: {resp.text[:200]}")
            body = resp.json()
            if body.get("error"):
                raise RuntimeError(f"Keepa error: {body['error']}")
            items = (body.get("deals") or {}).get("dr") or []
            log.info("Keepa page %d: %d deals, %s tokens left", page, len(items), body.get("tokensLeft"))
            for item in items:
                deal = self.to_deal(item, host, currency, price_type, date_range)
                if deal:
                    deals.append(deal)
            if len(items) < 150:
                break
        return deals

    def to_deal(self, item: dict[str, Any], host: str = "www.amazon.com", currency: str = "USD",
                price_type: int = 0, date_range: int = 3) -> Deal | None:
        asin = item.get("asin")
        current = _pick(item.get("current"), price_type)
        avg = _pick(item.get("avg"), date_range, price_type)
        if not asin or not isinstance(current, int) or not isinstance(avg, int) or current <= 0 or avg <= current:
            return None
        image = _image_name(item.get("image"))
        return Deal(
            source=self.name,
            # include the price so the same product can come back later if it drops again
            external_id=f"{asin}-{current}",
            title=str(item.get("title") or asin),
            url=f"https://{host}/dp/{asin}",
            price=current / 100,
            original_price=avg / 100,  # the 90-day average price, not a list price
            currency=currency,
            category=ROOT_CATEGORIES.get(item.get("rootCat"), "Amazon other") if item.get("rootCat") else None,
            image_url=f"https://images-na.ssl-images-amazon.com/images/I/{image}" if image else None,
            extra={"asin": asin, "compare": "90-day average"},
        )

    def affiliate_url(self, deal: Deal, tracking_id: str) -> str:
        tag = secret("AMAZON_ASSOCIATE_TAG")
        if not tag:
            raise RuntimeError("AMAZON_ASSOCIATE_TAG missing from .env")
        return add_amazon_tag(deal.url, tag)
