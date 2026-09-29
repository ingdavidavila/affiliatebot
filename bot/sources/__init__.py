"""Deal sources. Each source fetches discounted products and builds affiliate links.

To add a network: create a module with a class that subclasses `Source`,
then register it in SOURCE_CLASSES below and add a section in config.yaml.
"""
from __future__ import annotations

from typing import Any

from .base import Source
from .demo import DemoSource
from .ebay import EbaySource
from .keepa import KeepaSource
from .manual import ManualSource

SOURCE_CLASSES: dict[str, type[Source]] = {
    "demo": DemoSource,
    "ebay": EbaySource,
    "keepa": KeepaSource,
    "manual": ManualSource,
}


def shows_price(source_name: str) -> bool:
    """Some networks don't allow showing prices from third-party data (see keepa.py)."""
    cls = SOURCE_CLASSES.get(source_name)
    return getattr(cls, "show_price", True) if cls else True


def enabled_sources(cfg: dict[str, Any]) -> list[Source]:
    out: list[Source] = []
    for name, opts in (cfg.get("sources") or {}).items():
        if not (opts or {}).get("enabled"):
            continue
        cls = SOURCE_CLASSES.get(name)
        if cls is None:
            raise ValueError(f"Unknown source '{name}' in config.yaml")
        out.append(cls(opts or {}))
    return out


def source_for(name: str, cfg: dict[str, Any]) -> Source:
    opts = (cfg.get("sources") or {}).get(name) or {}
    return SOURCE_CLASSES[name](opts)
