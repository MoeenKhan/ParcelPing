"""Checking logic, independent of the UI.

The background worker only calls fetch(); everything that touches the
store (apply_result) runs on the main thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

from .carriers import CARRIERS, TrackingEvent, candidates
from .stages import Stage
from .store import Shipment, Store


@dataclass
class FetchResult:
    shipment_id: int
    carrier: str
    events: list[TrackingEvent] | None = None  # None when error/skipped
    error: str = ""
    skipped: bool = False  # carrier already failed earlier in this batch


@dataclass
class Change:
    shipment: Shipment
    event: TrackingEvent
    previous_stage: Stage | None

    @property
    def is_milestone(self) -> bool:
        stage = self.shipment.stage
        return stage != self.previous_stage or (stage is not None and stage.is_problem)


def friendly_error(carrier_name: str, exc: Exception) -> str:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return f"Couldn't reach {carrier_name}"
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return f"{carrier_name} returned an error (HTTP {exc.response.status_code})"
    return f"Couldn't read {carrier_name}'s tracking page"


def fetch(shipment_id: int, carrier: str, number: str, found_before: bool = True) -> FetchResult:
    """Ask the parcel's courier. Until a parcel has been found once, also ask
    the other couriers whose number format fits (some share one, like Trax
    and PostEx); a result from one of them has that courier as its carrier."""
    mod = CARRIERS[carrier]
    try:
        result = FetchResult(shipment_id, carrier, events=mod.fetch_events(number))
    except Exception as e:  # noqa: BLE001 - any failure is reported, never fatal
        result = FetchResult(shipment_id, carrier, error=friendly_error(mod.NAME, e))
    if result.events or found_before:
        return result
    for other in candidates(number):
        if other == carrier:
            continue
        try:
            events = CARRIERS[other].fetch_events(number)
        except Exception:  # noqa: BLE001 - only a hint; the main result stands
            continue
        if events:
            return FetchResult(shipment_id, other, events=events)
    return result


def apply_result(store: Store, result: FetchResult, now: datetime) -> Change | None:
    """Persist a fetch result. Returns a Change when the user should hear about it."""
    before = store.get(result.shipment_id)
    if before is None or result.skipped:
        return None

    if result.error:
        store.save_checked(before.id, now, result.error)
        return None

    events = result.events or []
    if not events:
        # Not found (yet). Keep any timeline we already had: a blip on the
        # courier's side shouldn't wipe history.
        store.save_checked(before.id, now)
        return None

    if result.carrier != before.carrier:
        # Found at another courier with the same number format: it's theirs.
        if not store.set_carrier(before.id, result.carrier):
            store.save_checked(before.id, now)  # already tracked there separately
            return None

    store.save_events(before.id, events, now)
    after = store.get(before.id)
    assert after is not None

    first_ever_check = before.last_checked_at is None
    if first_ever_check:
        return None  # just added: the user is looking at it already
    if before.latest and before.latest.key() == events[0].key():
        return None
    return Change(after, events[0], before.stage)


class Backoff:
    """Per-carrier exponential backoff after failures."""

    def __init__(self, base: timedelta = timedelta(minutes=5), cap: timedelta = timedelta(hours=2)):
        self.base, self.cap = base, cap
        self._failures: dict[str, int] = {}
        self._until: dict[str, datetime] = {}

    def failed(self, carrier: str, now: datetime) -> None:
        n = self._failures.get(carrier, 0) + 1
        self._failures[carrier] = n
        self._until[carrier] = now + min(self.base * (2 ** (n - 1)), self.cap)

    def succeeded(self, carrier: str) -> None:
        self._failures.pop(carrier, None)
        self._until.pop(carrier, None)

    def blocked_until(self, carrier: str, now: datetime) -> datetime | None:
        until = self._until.get(carrier)
        return until if until and until > now else None


def due(shipments: list[Shipment], now: datetime, interval: timedelta,
        backoff: Backoff, force: bool = False) -> list[Shipment]:
    out = []
    for s in shipments:
        if not s.wants_checking(now):
            continue
        if force:
            out.append(s)
            continue
        if backoff.blocked_until(s.carrier, now):
            continue
        if s.last_checked_at is None or now - s.last_checked_at >= interval:
            out.append(s)
    return out


def parse_numbers_file(text: str) -> list[tuple[str, str]]:
    """Read the old tracking_numbers.txt format: 'number' or 'carrier: number'."""
    from .carriers import detect

    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        carrier, sep, number = line.partition(":")
        if sep and carrier.strip().lower() in CARRIERS:
            out.append((carrier.strip().lower(), number.strip().upper()))
        elif (c := detect(line)) is not None:
            out.append((c, line.upper()))
    return out
