"""Tests for the no-human-input features. Run with:  python -m unittest discover tests"""
from __future__ import annotations

import copy
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from bot import autopilot, db
from bot.composer import compose
from bot.config import DEFAULTS, load_config
from bot.earnings import import_csv
from bot.earnings_sync import sync_earnings
from bot.finder import find_deals
from bot.models import new_tracking_id
from bot.poster import run_poster
from bot.sources.keepa import KeepaSource


def make_cfg(tmp: str) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    cfg["database"] = os.path.join(tmp, "test.db")
    cfg["settings"]["min_minutes_between_posts"] = 0
    return cfg


def add_deal(conn, category="Electronics", pct=40, price=50.0, status="approved", found_at=None, ext=None):
    tid = new_tracking_id()
    cur = conn.execute(
        "INSERT INTO deals(source, external_id, title, url, affiliate_url, price, original_price, discount_pct, "
        "category, tracking_id, status, found_at) VALUES ('demo',?,?,?,?,?,?,?,?,?,?,?)",
        (ext or tid, f"{category} thing {tid}", "https://example.com/x", "https://example.com/x?s=" + tid,
         price, round(price / (1 - pct / 100), 2), pct, category, tid, status, found_at or db.now_iso()))
    return cur.lastrowid, tid


class Resp:
    def __init__(self, status=200, json_data=None, content=b""):
        self.status_code, self._json, self.content = status, json_data, content
        self.text = content.decode() if content else ""

    def json(self):
        return self._json


class DefaultsTests(unittest.TestCase):
    def test_autopilot_is_default(self):
        self.assertFalse(DEFAULTS["settings"]["approval_mode"])
        cfg = load_config(os.path.join(os.path.dirname(__file__), "..", "config.example.yaml"))
        self.assertFalse(cfg["settings"]["approval_mode"])
        self.assertTrue(cfg["dry_run"])  # still safe until you switch it

    def test_new_deals_go_straight_to_posting(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            find_deals(cfg)
            self.assertEqual(run_poster(cfg)["posted"], 1)


class KeepaTests(unittest.TestCase):
    ITEM = {
        "asin": "B0TEST1234", "title": "Noise Cancelling Headphones",
        "current": [12999, 13500, -1], "avg": [[15000, 15000], [16000, 16000], [18000, 18000], [21999, 22000]],
        "rootCat": 172282, "image": [ord(c) for c in "71abc.jpg"],
    }

    def test_parses_deal_against_90_day_average(self):
        deal = KeepaSource({}).to_deal(self.ITEM)
        self.assertEqual(deal.price, 129.99)
        self.assertEqual(deal.original_price, 219.99)
        self.assertAlmostEqual(deal.discount_pct, 40.9, places=1)
        self.assertEqual(deal.category, "Electronics")
        self.assertEqual(deal.url, "https://www.amazon.com/dp/B0TEST1234")
        self.assertTrue(deal.image_url.endswith("/71abc.jpg"))

    def test_rejects_missing_or_higher_prices(self):
        src = KeepaSource({})
        self.assertIsNone(src.to_deal({**self.ITEM, "current": [-1]}))
        self.assertIsNone(src.to_deal({**self.ITEM, "avg": [[1], [1], [1], [100]]}))  # avg below current

    def test_fetch_builds_request_and_tagged_links(self):
        body = {"deals": {"dr": [self.ITEM]}, "tokensLeft": 55}
        with mock.patch.dict(os.environ, {"KEEPA_API_KEY": "k", "AMAZON_ASSOCIATE_TAG": "me-20"}):
            src = KeepaSource({"min_drop_pct": 25, "min_price": 20, "max_price": 300})
            with mock.patch.object(src.session, "get", return_value=Resp(json_data=body)) as get:
                deals = src.fetch()
            params = get.call_args.kwargs["params"]
            self.assertEqual(params["domain"], 1)
            self.assertIn('"deltaPercentRange": [25, 100]', params["selection"])
            self.assertIn('"currentRange": [2000, 30000]', params["selection"])
            self.assertEqual(len(deals), 1)
            self.assertIn("tag=me-20", src.affiliate_url(deals[0], "x"))

    def test_keepa_posts_hide_price(self):
        deal = {"source": "keepa", "title": "Headphones", "price": 129.99, "original_price": 219.99,
                "discount_pct": 41, "affiliate_url": "https://www.amazon.com/dp/B0?tag=me-20"}
        text = compose(deal, DEFAULTS["settings"])
        self.assertNotIn("$", text)
        self.assertIn("41%", text)
        self.assertIn("#ad", text)


class EarningsSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = make_cfg(self.tmp.name)
        self.cfg["earnings_sync"] = {"networks": ["ebay"], "every_hours": 6, "days_back": 45}
        with db.session(self.cfg["database"]) as conn:
            _, self.tid = add_deal(conn, status="posted")

    def tearDown(self):
        self.tmp.cleanup()

    def report(self, earnings):
        return ("EpnTransactionId,EventDate,CustomId,Sales,Earnings\n"
                f"5001,2026-09-20,{self.tid},120.00,{earnings}\n").encode()

    def test_sync_imports_updates_and_throttles(self):
        env = {"EPN_ACCOUNT_SID": "sid", "EPN_AUTH_TOKEN": "tok"}
        with mock.patch.dict(os.environ, env), \
                mock.patch("bot.earnings_sync.requests.get", return_value=Resp(content=self.report("3.60"))) as get:
            first = sync_earnings(self.cfg)
            skipped = sync_earnings(self.cfg)  # within 6 hours -> not due
        self.assertTrue(first["ran"])
        self.assertFalse(skipped["ran"])
        self.assertEqual(first["networks"]["ebay"]["matched"], 1)
        url = get.call_args.args[0]
        self.assertEqual(url, "https://api.partner.ebay.com/mediapartners/sid/reports/ebay_partner_transaction_detail.csv")
        self.assertEqual(get.call_args.kwargs["auth"], ("sid", "tok"))
        self.assertEqual(get.call_args.kwargs["params"]["STATUS"], "ALL")

        # later the commission is revised (e.g. pending -> approved at a different amount)
        with mock.patch.dict(os.environ, env), \
                mock.patch("bot.earnings_sync.requests.get", return_value=Resp(content=self.report("4.10"))):
            again = sync_earnings(self.cfg, force=True)
        self.assertEqual(again["networks"]["ebay"]["updated"], 1)
        with db.session(self.cfg["database"]) as conn:
            rows = conn.execute("SELECT commission FROM earnings").fetchall()
        self.assertEqual([r[0] for r in rows], [4.10])

    def test_sync_error_is_reported_not_raised(self):
        with mock.patch.dict(os.environ, {"EPN_ACCOUNT_SID": "sid", "EPN_AUTH_TOKEN": "bad"}), \
                mock.patch("bot.earnings_sync.requests.get", return_value=Resp(401, content=b"Unauthorized")):
            result = sync_earnings(self.cfg, force=True)
        self.assertIn("401", result["errors"][0])

    def test_repeated_ids_in_one_report_are_kept(self):
        csv = ("EpnTransactionId,EventDate,CustomId,Sales,Earnings\n"
               f"77,2026-09-20,{self.tid},50,2.00\n77,2026-09-22,{self.tid},-50,-2.00\n")
        with db.session(self.cfg["database"]) as conn:
            st = import_csv(conn, csv, "ebay")
            total = conn.execute("SELECT SUM(commission) FROM earnings").fetchone()[0]
        self.assertEqual(st["imported"], 2)
        self.assertEqual(total, 0)


class AutopilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "a.db")
        self.settings = dict(DEFAULTS["settings"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_category_rotation(self):
        with db.session(self.path) as conn:
            for _ in range(3):  # three recent electronics posts
                did, _ = add_deal(conn, "Electronics", status="posted")
                conn.execute("INSERT INTO posts(deal_id, text, posted_at, cost_usd) VALUES (?, 't', ?, 0.2)",
                             (did, db.now_iso()))
            add_deal(conn, "Electronics", pct=50)
            add_deal(conn, "Home & Kitchen", pct=40)
            best = autopilot.pick_best(conn, self.settings)
        self.assertEqual(best["category"], "Home & Kitchen")

    def test_learns_which_categories_earn(self):
        with db.session(self.path) as conn:
            for cat, commission in (("Toys", 0.0), ("Clothing", 3.0)):
                for _ in range(10):
                    did, tid = add_deal(conn, cat, status="posted")
                    conn.execute("INSERT INTO posts(deal_id, text, posted_at, cost_usd) VALUES (?, 't', ?, 0.2)",
                                 (did, (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()))
                    if commission:
                        conn.execute("INSERT INTO earnings(network, tracking_id, event_date, commission, order_ref, "
                                     "imported_at) VALUES ('ebay', ?, '2026-09-20', ?, ?, ?)",
                                     (tid, commission, tid, db.now_iso()))
            perf = autopilot.category_performance(conn)
            self.assertGreater(perf["Clothing"], 0)
            self.assertLess(perf["Toys"], 0)
            self.settings["category_cooldown_posts"] = 0
            add_deal(conn, "Toys", pct=45)
            add_deal(conn, "Clothing", pct=35)
            best = autopilot.pick_best(conn, self.settings)
        self.assertEqual(best["category"], "Clothing")  # smaller discount, but it actually sells

    def test_stale_deals_expire(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        with db.session(self.path) as conn:
            add_deal(conn, found_at=old)
            add_deal(conn)
            n = autopilot.expire_stale(conn, 24)
            left = conn.execute("SELECT COUNT(*) FROM deals WHERE status='approved'").fetchone()[0]
        self.assertEqual((n, left), (1, 1))

    def test_cooldown_after_repeated_failures_then_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            cfg["dry_run"] = False
            find_deals(cfg)

            class Broken:
                def post(self, text):
                    raise RuntimeError("X API 403: forbidden")

            for _ in range(3):
                run_poster(cfg, client=Broken())
            blocked = run_poster(cfg, client=Broken())
            self.assertEqual(blocked["posted"], 0)
            self.assertIn("Retrying automatically", blocked["reasons"][0])
            # 7 hours later it tries again on its own
            with db.session(cfg["database"]) as conn:
                later = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
                conn.execute("UPDATE posts SET posted_at = ?", (later,))
                self.assertIsNone(autopilot.failure_cooldown(conn, False, 6))


if __name__ == "__main__":
    unittest.main()
