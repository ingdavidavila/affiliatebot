from __future__ import annotations

import secrets
import string
from dataclasses import dataclass, field
from typing import Optional

_ALPHABET = string.ascii_lowercase + string.digits


def new_tracking_id() -> str:
    """Short unique id attached to each affiliate link (as sub-ID / custom ID),
    so a sale in the network's report can be matched back to the exact post."""
    return "ab" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


@dataclass
class Deal:
    source: str
    external_id: str
    title: str
    url: str
    price: float
    original_price: Optional[float] = None
    currency: str = "USD"
    category: Optional[str] = None
    image_url: Optional[str] = None
    extra: dict = field(default_factory=dict)

    @property
    def discount_pct(self) -> Optional[float]:
        if self.original_price and self.original_price > self.price > 0:
            return round((1 - self.price / self.original_price) * 100, 1)
        return None
