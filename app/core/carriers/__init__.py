"""Carrier registry.

To add a courier: create carriers/<name>.py following the contract in
base.py, then add it to CARRIERS below. When two couriers share a number
format, the first listed is tried first; the checker then finds out which
one actually has the parcel (see checker.fetch).
"""

from __future__ import annotations

import re
from types import ModuleType

from . import dex, leopards, postex, tcs, trax
from .base import TrackingEvent

CARRIERS: dict[str, ModuleType] = {
    "leopards": leopards,
    "dex": dex,
    "tcs": tcs,
    "trax": trax,
    "postex": postex,
}


def candidates(number: str) -> list[str]:
    """Every courier whose number format fits, in CARRIERS order."""
    return [key for key, mod in CARRIERS.items() if mod.NUMBER_PATTERN.match(number)]


def detect(number: str) -> str | None:
    """Best guess at the courier from the number's format."""
    found = candidates(number)
    return found[0] if found else None


def split_numbers(text: str) -> list[str]:
    """Split pasted text (one or many numbers) into normalised numbers."""
    parts = re.split(r"[\s,;]+", text.strip())
    seen: dict[str, None] = {}
    for p in parts:
        p = p.strip().upper()
        if p:
            seen.setdefault(p, None)
    return list(seen)


__all__ = ["CARRIERS", "TrackingEvent", "candidates", "detect", "split_numbers"]
