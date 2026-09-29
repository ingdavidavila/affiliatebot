"""Fills a separate database with 30 days of fake history so you can preview the dashboard."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db
from .composer import compose
from .models import new_tracking_id
from .sources.demo import PRODUCTS


def seed(path: str, days: int = 30, seed_value: int = 7) -> None:
    Path(path).unlink(missing_ok=True)
    rng = random.Random(seed_value)
    settings = {"disclosure": "#ad", "hashtags": "#deal #sale"}
    with db.session(path) as conn:
        now = datetime.now(timezone.utc)
        n = 0
        for day in range(days, 0, -1):
            date = now - timedelta(days=day)
            for _ in range(rng.randint(3, 7)):
                n += 1
                title, category, list_price = rng.choice(PRODUCTS)
                pct = rng.choice([30, 35, 40, 45, 50, 60])
                price = round(list_price * (1 - pct / 100), 2)
                tid = new_tracking_id()
                ts = (date.replace(hour=rng.randint(13, 23), minute=rng.randint(0, 59))).replace(microsecond=0)
                deal = {
                    "title": title, "price": price, "original_price": list_price, "discount_pct": pct,
                    "currency": "USD", "affiliate_url": f"https://example.com/p/{n}?subid={tid}",
                }
                cur = conn.execute(
                    "INSERT INTO deals(source, external_id, title, url, affiliate_url, price, original_price, "
                    "discount_pct, category, tracking_id, status, found_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rng.choice(["ebay", "manual"]), f"seed-{n}", title, f"https://example.com/p/{n}",
                     deal["affiliate_url"], price, list_price, pct, category, tid, "posted",
                     (ts - timedelta(minutes=40)).isoformat()),
                )
                conn.execute(
                    "INSERT INTO posts(deal_id, tweet_id, text, posted_at, cost_usd, dry_run) VALUES (?,?,?,?,?,1)",
                    (cur.lastrowid, f"demo{n}", compose(deal, settings, rng), ts.isoformat(), 0.20),
                )
                # Made-up but deliberately modest: ~1 in 10 posts leads to a sale.
                sales = sum(1 for _ in range(2) if rng.random() < 0.02 + pct / 1500)
                for s in range(sales):
                    sale_day = (ts + timedelta(days=rng.choice([0, 0, 1, 2]))).date()
                    if sale_day > now.date():
                        continue
                    rate = {"Electronics": 0.03, "Home & Kitchen": 0.045, "Clothing": 0.07}.get(category, 0.04)
                    conn.execute(
                        "INSERT INTO earnings(network, tracking_id, event_date, sale_amount, commission, "
                        "order_ref, imported_at) VALUES (?,?,?,?,?,?,?)",
                        ("ebay", tid, sale_day.isoformat(), price, round(price * rate, 2),
                         f"order-{n}-{s}", db.now_iso()),
                    )
        # a few unattributed (e.g. Amazon) earnings and one expense
        for d in range(0, days, 6):
            conn.execute(
                "INSERT INTO earnings(network, tracking_id, event_date, sale_amount, commission, order_ref, "
                "imported_at) VALUES ('amazon', NULL, ?, ?, ?, ?, ?)",
                ((now - timedelta(days=d)).date().isoformat(), 60.0, round(rng.uniform(1.5, 4.5), 2),
                 f"amz-{d}", db.now_iso()),
            )
        conn.execute("INSERT INTO expenses(date, amount_usd, note) VALUES (?, 5.0, 'Server (example)')",
                     ((now - timedelta(days=12)).date().isoformat(),))
        # a few deals waiting in the queue
        for i, (title, category, list_price) in enumerate(rng.sample(PRODUCTS, 5)):
            pct = rng.choice([30, 40, 50])
            conn.execute(
                "INSERT INTO deals(source, external_id, title, url, affiliate_url, price, original_price, "
                "discount_pct, category, tracking_id, status, found_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("ebay", f"queue-{i}", title, f"https://example.com/q/{i}",
                 f"https://example.com/q/{i}?subid=x", round(list_price * (1 - pct / 100), 2), list_price,
                 pct, category, new_tracking_id(), "queued", db.now_iso()),
            )
        db.start_run(conn, "find")
