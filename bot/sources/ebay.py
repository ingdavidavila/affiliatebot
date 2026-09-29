"""eBay deals via the eBay Browse API + eBay Partner Network (EPN) affiliate links.

Needs (in .env):
    EBAY_APP_ID       - "App ID (Client ID)" from developer.ebay.com
    EBAY_CERT_ID      - "Cert ID (Client Secret)"
    EPN_CAMPAIGN_ID   - campaign ID from partnernetwork.ebay.com

The Browse API reports discounts in `marketingPrice` (original price + % off),
so only items eBay itself marks as discounted are returned.
The tracking id goes into EPN's `customid` so each sale maps to one post.
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests

from ..config import secret
from ..models import Deal
from .base import Source

log = logging.getLogger(__name__)

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"

# EPN rover ids per marketplace (used in affiliate links).
ROVER_IDS = {
    "EBAY_US": "711-53200-19255-0",
    "EBAY_GB": "710-53481-19255-0",
    "EBAY_CA": "706-53473-19255-0",
    "EBAY_AU": "705-53470-19255-0",
    "EBAY_DE": "707-53477-19255-0",
}


class EbaySource(Source):
    name = "ebay"

    def __init__(self, options: dict[str, Any]):
        super().__init__(options)
        self._token: str | None = None
        self._token_expiry = 0.0
        self.session = requests.Session()

    # ---- auth ----
    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        app_id, cert_id = secret("EBAY_APP_ID"), secret("EBAY_CERT_ID")
        if not (app_id and cert_id):
            raise RuntimeError("EBAY_APP_ID / EBAY_CERT_ID missing from .env")
        basic = base64.b64encode(f"{app_id}:{cert_id}".encode()).decode()
        resp = self.session.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {basic}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials", "scope": SCOPE},
            timeout=20,
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._token_expiry = time.time() + int(body.get("expires_in", 7200))
        return self._token

    # ---- fetch ----
    def fetch(self) -> list[Deal]:
        marketplace = self.options.get("marketplace", "EBAY_US")
        limit = int(self.options.get("limit", 50))
        queries: list[dict[str, str]] = []
        for kw in self.options.get("keywords") or []:
            queries.append({"q": kw})
        for cat in self.options.get("category_ids") or []:
            queries.append({"category_ids": str(cat)})

        deals: dict[str, Deal] = {}
        for query in queries:
            params = {
                **query,
                "limit": str(limit),
                "filter": "buyingOptions:{FIXED_PRICE},conditions:{NEW}",
            }
            try:
                resp = self.session.get(
                    SEARCH_URL,
                    headers={
                        "Authorization": f"Bearer {self._get_token()}",
                        "X-EBAY-C-MARKETPLACE-ID": marketplace,
                    },
                    params=params,
                    timeout=20,
                )
                resp.raise_for_status()
            except requests.RequestException as exc:
                log.warning("eBay search failed for %s: %s", query, exc)
                continue
            for item in resp.json().get("itemSummaries", []) or []:
                deal = self._to_deal(item)
                if deal:
                    deals[deal.external_id] = deal
        return list(deals.values())

    def _to_deal(self, item: dict[str, Any]) -> Deal | None:
        try:
            price = float(item["price"]["value"])
            mp = item.get("marketingPrice") or {}
            original = mp.get("originalPrice", {}).get("value")
            if original is None:
                return None  # not marked as discounted
            cats = item.get("categories") or [{}]
            return Deal(
                source=self.name,
                external_id=item["itemId"],
                title=item["title"],
                url=item["itemWebUrl"],
                price=price,
                original_price=float(original),
                currency=item["price"].get("currency", "USD"),
                category=cats[0].get("categoryName"),
                image_url=(item.get("image") or {}).get("imageUrl"),
            )
        except (KeyError, TypeError, ValueError):
            return None

    # ---- affiliate link ----
    def affiliate_url(self, deal: Deal, tracking_id: str) -> str:
        campaign = secret("EPN_CAMPAIGN_ID")
        if not campaign:
            raise RuntimeError("EPN_CAMPAIGN_ID missing from .env")
        marketplace = self.options.get("marketplace", "EBAY_US")
        parts = urlsplit(deal.url)
        query = urlencode({
            "mkcid": "1",
            "mkrid": ROVER_IDS.get(marketplace, ROVER_IDS["EBAY_US"]),
            "siteid": "0",
            "campid": campaign,
            "customid": tracking_id,
            "toolid": "10001",
            "mkevt": "1",
        })
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
