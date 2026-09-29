"""Loads config.yaml (non-secret settings) and .env (API keys)."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional
    def load_dotenv(*_args, **_kwargs):
        return False

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict[str, Any] = {
    "database": "data/affiliate.db",
    "dry_run": True,
    "sources": {
        "demo": {"enabled": True},
        "ebay": {
            "enabled": False,
            "marketplace": "EBAY_US",
            "keywords": ["laptop", "headphones"],
            "category_ids": [],
            "limit": 50,
        },
        "keepa": {
            "enabled": False,
            "domain": "US",
            "price_type": "amazon",
            "compare_to": "90days",
            "min_drop_pct": 30,
            "min_price": 15,
            "max_price": 500,
            "pages": 1,
            "include_categories": [],
            "exclude_categories": [],
        },
        "manual": {"enabled": False, "file": "data/manual_deals.csv"},
    },
    "earnings_sync": {"networks": [], "every_hours": 6, "days_back": 45},
    # These are defaults. The dashboard's Settings page can override them
    # (stored in the database), so you rarely need to edit them here.
    "settings": {
        "paused": False,
        "approval_mode": False,
        "learn_from_sales": True,
        "category_cooldown_posts": 3,
        "max_deal_age_hours": 24,
        "failure_cooldown_hours": 6,
        "min_discount_pct": 30,
        "min_price": 10,
        "max_price": 1000,
        "max_posts_per_day": 8,
        "posts_per_run": 1,
        "min_minutes_between_posts": 60,
        "daily_budget_usd": 3.00,
        "blocked_keywords": "refurbished, for parts, replica",
        "hashtags": "#deal #sale",
        "disclosure": "#ad",
    },
    "costs": {
        # X API pay-per-use prices (Sept 2026). Check the X developer console
        # for current rates and update these if they change.
        "x_post_with_link_usd": 0.20,
        "x_post_without_link_usd": 0.015,
    },
    "dashboard": {"host": "127.0.0.1", "port": 8765},
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | os.PathLike | None = None) -> dict[str, Any]:
    """Load config: defaults <- config.yaml <- AFFBOT_* env overrides."""
    load_dotenv(ROOT / ".env")
    cfg_path = Path(path) if path else Path(os.environ.get("AFFBOT_CONFIG", ROOT / "config.yaml"))
    data: dict[str, Any] = {}
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    cfg = _deep_merge(DEFAULTS, data)
    if os.environ.get("AFFBOT_DB"):
        cfg["database"] = os.environ["AFFBOT_DB"]
    if os.environ.get("AFFBOT_DRY_RUN") is not None:
        cfg["dry_run"] = os.environ["AFFBOT_DRY_RUN"].lower() in ("1", "true", "yes")
    db = Path(cfg["database"])
    cfg["database"] = str(db if db.is_absolute() else ROOT / db)
    return cfg


def secret(name: str) -> str | None:
    """Read an API key from the environment / .env file."""
    load_dotenv(ROOT / ".env")
    value = os.environ.get(name, "").strip()
    return value or None
