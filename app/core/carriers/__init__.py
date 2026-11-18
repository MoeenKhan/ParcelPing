"""Carrier registry.

To add a courier: create carriers/<name>.py following the contract in
base.py, then add it to CARRIERS below.
"""

from __future__ import annotations

import re
from types import ModuleType

from . import dex, leopards, tcs
from .base import TrackingEvent

CARRIERS: dict[str, ModuleType] = {
    "leopards": leopards,
    "dex": dex,
    "tcs": tcs,
}


def detect(number: str) -> str | None:
    """Guess the carrier key from the number's format."""
    for key, mod in CARRIERS.items():
        if mod.NUMBER_PATTERN.match(number):
            return key
    return None


def split_numbers(text: str) -> list[str]:
    """Split pasted text (one or many numbers) into normalised numbers."""
    parts = re.split(r"[\s,;]+", text.strip())
    seen: dict[str, None] = {}
    for p in parts:
        p = p.strip().upper()
        if p:
            seen.setdefault(p, None)
    return list(seen)


__all__ = ["CARRIERS", "TrackingEvent", "detect", "split_numbers"]
