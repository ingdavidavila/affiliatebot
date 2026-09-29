"""Fake deals for testing the whole pipeline without any API keys."""
from __future__ import annotations

import random
from datetime import datetime, timezone

from ..models import Deal
from .base import Source

PRODUCTS = [
    ("Wireless Noise Cancelling Headphones", "Electronics", 249.99),
    ("27\" 4K IPS Monitor", "Electronics", 379.00),
    ("Mechanical Keyboard, Hot-Swappable", "Electronics", 129.99),
    ("Air Fryer 6 Qt Digital", "Home & Kitchen", 119.99),
    ("Robot Vacuum with Self-Empty Base", "Home & Kitchen", 499.99),
    ("Cast Iron Dutch Oven 5.5 Qt", "Home & Kitchen", 89.95),
    ("Running Shoes, Men's Lightweight", "Clothing", 139.00),
    ("Insulated Water Bottle 32 oz", "Sports", 44.95),
    ("Adjustable Dumbbells 5-52 lb (Pair)", "Sports", 429.00),
    ("Smart Watch with GPS", "Electronics", 299.99),
    ("Portable Bluetooth Speaker, Waterproof", "Electronics", 99.99),
    ("Electric Toothbrush, 4 Modes", "Health", 79.99),
    ("LEGO Architecture Skyline Set", "Toys", 59.99),
    ("Espresso Machine with Milk Frother", "Home & Kitchen", 349.00),
    ("1TB Portable SSD USB-C", "Electronics", 159.99),
    ("Camping Tent, 4-Person Instant Setup", "Outdoors", 189.99),
]


class DemoSource(Source):
    name = "demo"

    def fetch(self) -> list[Deal]:
        # New "batch" of deals every hour so repeated runs don't just dedupe to nothing.
        hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        rng = random.Random(hour)
        deals = []
        for i, (title, category, list_price) in enumerate(rng.sample(PRODUCTS, 8)):
            discount = rng.choice([0.10, 0.20, 0.25, 0.35, 0.40, 0.50, 0.60])
            price = round(list_price * (1 - discount), 2)
            ext = f"demo-{hour}-{i}"
            deals.append(
                Deal(
                    source=self.name,
                    external_id=ext,
                    title=title,
                    url=f"https://example.com/product/{ext}",
                    price=price,
                    original_price=list_price,
                    category=category,
                )
            )
        return deals

    def affiliate_url(self, deal: Deal, tracking_id: str) -> str:
        return f"{deal.url}?aff=demo&subid={tracking_id}"
