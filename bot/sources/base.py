from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models import Deal


class Source(ABC):
    name: str = "base"
    show_price: bool = True  # False = posts show the % drop but not the price

    def __init__(self, options: dict[str, Any]):
        self.options = options

    @abstractmethod
    def fetch(self) -> list[Deal]:
        """Return current deals. Should not raise for a single bad item."""

    @abstractmethod
    def affiliate_url(self, deal: Deal, tracking_id: str) -> str:
        """Build the tracked affiliate link for this deal."""
