"""Turns a deal into post text that fits X's 280-character limit."""
from __future__ import annotations

import random
import re
from typing import Any, Mapping

from .sources import shows_price

X_LIMIT = 280
X_URL_LENGTH = 23  # X counts every link as 23 characters

OPENERS = ["🔥 Deal:", "💸 Price drop:", "⚡ Sale:", "👀 Spotted:", "🏷️ Discount:"]

_URL_RE = re.compile(r"https?://\S+")


def x_length(text: str) -> int:
    """Approximate X's weighted length: links = 23, emoji/wide chars = 2."""
    total = 0
    last = 0
    for m in _URL_RE.finditer(text):
        total += _weighted(text[last:m.start()]) + X_URL_LENGTH
        last = m.end()
    return total + _weighted(text[last:])


def _weighted(s: str) -> int:
    n = 0
    for ch in s:
        cp = ord(ch)
        if cp < 0x1100 or 0x2000 <= cp <= 0x200D or 0x2010 <= cp <= 0x201F or 0x2032 <= cp <= 0x2037:
            n += 1
        elif 0xFE00 <= cp <= 0xFE0F:  # variation selectors add nothing visible
            n += 0
        else:
            n += 2
    return n


def money(value: float, currency: str = "USD") -> str:
    symbol = {"USD": "$", "CAD": "CA$", "AUD": "A$", "GBP": "£", "EUR": "€"}.get(currency, "")
    return f"{symbol}{value:,.2f}" if symbol else f"{value:,.2f} {currency}"


def compose(deal: Mapping[str, Any], settings: Mapping[str, Any], rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    opener = rng.choice(OPENERS)
    currency = deal.get("currency") or "USD"
    if not shows_price(deal.get("source") or ""):
        # e.g. Amazon via Keepa: say how big the drop is, without quoting a price
        pct = round(deal.get("discount_pct") or 0)
        price_line = rng.choice([
            f"{pct}% below its 90-day average price",
            f"Down {pct}% vs. its usual price",
            f"Now {pct}% under its 3-month average",
        ])
    else:
        price_line = money(deal["price"], currency)
        if deal.get("original_price"):
            price_line += f" (was {money(deal['original_price'], currency)})"
        if deal.get("discount_pct"):
            price_line += f" · {round(deal['discount_pct'])}% off"

    tags = " ".join(t for t in [settings.get("disclosure", "#ad"), settings.get("hashtags", "")] if t).strip()
    title = " ".join(str(deal["title"]).split())

    def build(t: str) -> str:
        return f"{opener} {t}\n\n{price_line}\n\n{deal['affiliate_url']}\n\n{tags}".strip()

    text = build(title)
    while x_length(text) > X_LIMIT and len(title) > 10:
        title = title[: max(10, len(title) - 5)].rstrip() + "…"
        title = title.replace("……", "…")
        text = build(title)
    # The disclosure must never be cut off.
    if settings.get("disclosure") and settings["disclosure"] not in text:
        raise ValueError("Disclosure missing from composed post")
    return text
