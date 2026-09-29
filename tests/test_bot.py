"""Run with:  python -m unittest discover tests"""
from __future__ import annotations

import copy
import os
import random
import tempfile
import unittest

from bot import db
from bot.composer import X_LIMIT, compose, x_length
from bot.config import DEFAULTS
from bot.earnings import import_csv, map_columns
from bot.finder import find_deals, passes_filters
from bot.models import Deal
from bot.poster import limits_status, run_poster
from bot.sources.ebay import EbaySource
from bot.sources.manual import add_amazon_tag, is_amazon
from bot.x_client import oauth1_header


def make_cfg(tmp: str) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    cfg["database"] = os.path.join(tmp, "test.db")
    cfg["settings"]["approval_mode"] = False
    cfg["settings"]["min_minutes_between_posts"] = 0
    return cfg


class FakeX:
    def __init__(self):
        self.sent = []

    def post(self, text):
        self.sent.append(text)
        return str(1000 + len(self.sent))


class FilterTests(unittest.TestCase):
    settings = DEFAULTS["settings"]

    def deal(self, **kw):
        base = dict(source="t", external_id="1", title="Nice Headphones", url="https://x.test", price=50, original_price=100)
        base.update(kw)
        return Deal(**base)

    def test_good_deal_passes(self):
        self.assertTrue(passes_filters(self.deal(), self.settings)[0])

    def test_small_discount_rejected(self):
        self.assertFalse(passes_filters(self.deal(price=90), self.settings)[0])

    def test_no_original_price_rejected(self):
        self.assertFalse(passes_filters(self.deal(original_price=None), self.settings)[0])

    def test_blocked_keyword(self):
        self.assertFalse(passes_filters(self.deal(title="Refurbished Headphones"), self.settings)[0])

    def test_price_bounds(self):
        self.assertFalse(passes_filters(self.deal(price=5, original_price=20), self.settings)[0])
        self.assertFalse(passes_filters(self.deal(price=1500, original_price=3000), self.settings)[0])


class ComposerTests(unittest.TestCase):
    def test_fits_and_has_disclosure(self):
        deal = {"title": "Super long product name " * 30, "price": 19.99, "original_price": 49.99,
                "discount_pct": 60, "currency": "USD", "affiliate_url": "https://example.com/" + "a" * 300}
        for seed in range(20):
            text = compose(deal, DEFAULTS["settings"], random.Random(seed))
            self.assertLessEqual(x_length(text), X_LIMIT)
            self.assertIn("#ad", text)
            self.assertIn(deal["affiliate_url"], text)

    def test_url_counts_as_23(self):
        self.assertEqual(x_length("https://example.com/" + "x" * 100), 23)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = make_cfg(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_find_dedupes(self):
        first = find_deals(self.cfg)
        second = find_deals(self.cfg)
        self.assertGreater(first["added"], 0)
        self.assertEqual(second["added"], 0)

    def test_dry_run_posts_nothing_to_x(self):
        find_deals(self.cfg)
        fake = FakeX()
        result = run_poster(self.cfg, client=fake)
        self.assertEqual(result["posted"], 1)
        self.assertEqual(fake.sent, [])  # dry run never calls X

    def test_live_posting_respects_limits_and_budget(self):
        self.cfg["dry_run"] = False
        self.cfg["settings"]["posts_per_run"] = 10
        self.cfg["settings"]["daily_budget_usd"] = 0.50  # room for two $0.20 posts
        find_deals(self.cfg)
        fake = FakeX()
        result = run_poster(self.cfg, client=fake)
        self.assertEqual(result["posted"], 2)
        self.assertEqual(len(fake.sent), 2)
        self.assertTrue(any("budget" in r for r in result["reasons"]))
        with db.session(self.cfg["database"]) as conn:
            spend = conn.execute("SELECT SUM(cost_usd) FROM posts").fetchone()[0]
        self.assertAlmostEqual(spend, 0.40)

    def test_pause_blocks_posting(self):
        find_deals(self.cfg)
        with db.session(self.cfg["database"]) as conn:
            db.set_setting(conn, "paused", True)
            settings = db.get_settings(conn, self.cfg["settings"])
            ok, reason = limits_status(conn, self.cfg, settings)
        self.assertFalse(ok)
        self.assertIn("paused", reason.lower())

    def test_spacing_between_posts(self):
        self.cfg["settings"]["min_minutes_between_posts"] = 60
        self.cfg["settings"]["posts_per_run"] = 3
        find_deals(self.cfg)
        result = run_poster(self.cfg)
        self.assertEqual(result["posted"], 1)

    def test_approval_mode_queues(self):
        self.cfg["settings"]["approval_mode"] = True
        find_deals(self.cfg)
        result = run_poster(self.cfg)
        self.assertEqual(result["posted"], 0)


class EarningsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = make_cfg(self.tmp.name)
        find_deals(self.cfg)

    def tearDown(self):
        self.tmp.cleanup()

    def test_import_matches_and_dedupes(self):
        with db.session(self.cfg["database"]) as conn:
            tid = conn.execute("SELECT tracking_id FROM deals LIMIT 1").fetchone()[0]
            report = ("eBay Partner Network Transaction Report\n"
                      "Event Date,Custom ID,Sales,Earnings,Checkout Transaction ID\n"
                      f"09/20/2026,{tid},\"$1,250.00\",$12.50,111\n"
                      "09/21/2026,,$40.00,$1.20,222\n")
            first = import_csv(conn, report, "ebay")
            again = import_csv(conn, report, "ebay")
            row = conn.execute("SELECT * FROM earnings WHERE order_ref='111'").fetchone()
        self.assertEqual(first["imported"], 2)
        self.assertEqual(first["matched"], 1)
        self.assertEqual(again["imported"], 0)
        self.assertEqual(again["duplicates"], 2)
        self.assertEqual(row["event_date"], "2026-09-20")
        self.assertEqual(row["sale_amount"], 1250.0)

    def test_amazon_style_columns(self):
        m = map_columns(["Name", "ASIN", "Date Shipped", "Price($)", "Ad Fees($)", "Tracking ID"])
        self.assertEqual(m["commission"], "Ad Fees($)")
        self.assertEqual(m["event_date"], "Date Shipped")
        self.assertEqual(m["sale_amount"], "Price($)")

    def test_missing_commission_column_errors(self):
        with db.session(self.cfg["database"]) as conn:
            with self.assertRaises(ValueError):
                import_csv(conn, "a,b,c\n1,2,3\n", "x")


class LinkTests(unittest.TestCase):
    def test_amazon_tag(self):
        url = add_amazon_tag("https://www.amazon.com/dp/B0TEST?th=1&tag=old-20", "mine-20")
        self.assertIn("tag=mine-20", url)
        self.assertNotIn("old-20", url)
        self.assertTrue(is_amazon("https://www.amazon.co.uk/dp/x"))
        self.assertFalse(is_amazon("https://notamazon.com.evil.test/"))

    def test_ebay_affiliate_link(self):
        os.environ["EPN_CAMPAIGN_ID"] = "5338000000"
        try:
            src = EbaySource({"marketplace": "EBAY_US"})
            deal = Deal("ebay", "v1|1|0", "x", "https://www.ebay.com/itm/123456?hash=abc", 10, 20)
            url = src.affiliate_url(deal, "abtest1234")
        finally:
            del os.environ["EPN_CAMPAIGN_ID"]
        self.assertTrue(url.startswith("https://www.ebay.com/itm/123456?"))
        self.assertIn("campid=5338000000", url)
        self.assertIn("customid=abtest1234", url)
        self.assertIn("mkrid=711-53200-19255-0", url)

    def test_ebay_item_parsing(self):
        src = EbaySource({})
        item = {"itemId": "v1|9|0", "title": "Thing", "itemWebUrl": "https://www.ebay.com/itm/9",
                "price": {"value": "30.00", "currency": "USD"},
                "marketingPrice": {"originalPrice": {"value": "60.00"}, "discountPercentage": "50"}}
        deal = src._to_deal(item)
        self.assertEqual(deal.discount_pct, 50.0)
        item.pop("marketingPrice")
        self.assertIsNone(src._to_deal(item))


class OAuthTests(unittest.TestCase):
    def test_matches_x_documentation_example(self):
        # The worked example from X's "Creating a signature" docs.
        header = oauth1_header(
            "POST", "https://api.twitter.com/1.1/statuses/update.json",
            {"include_entities": "true", "status": "Hello Ladies + Gentlemen, a signed OAuth request!"},
            consumer_key="xvz1evFS4wEEPTGEFPHBog",
            consumer_secret="kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
            token="370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
            token_secret="LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE",
            nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg", timestamp="1318622958",
        )
        self.assertIn('oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"', header)


class StatsTests(unittest.TestCase):
    def test_demo_seed_and_dashboard_pages(self):
        from bot.demo_data import seed
        from dashboard.app import create_app
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "demo.db")
            seed(path)
            cfg = make_cfg(tmp)
            app = create_app(cfg, db_path=path, demo=True)
            client = app.test_client()
            for page in ["/", "/?days=7", "/posts", "/posts?order=top", "/queue", "/earnings", "/settings"]:
                self.assertEqual(client.get(page).status_code, 200, page)
            # forms without the CSRF token are rejected
            self.assertEqual(client.post("/pause").status_code, 400)


if __name__ == "__main__":
    unittest.main()
