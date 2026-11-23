"""Trax (sonic.pk, Trax's consumer tracking site).

The tracking page is a Laravel app. Tracking is a form post that needs the
page's CSRF token and session cookie:

    GET  /tracking                -> <meta name="csrf-token" content="...">
    POST /tracking/track  tracking_numbers=<number>&_token=<token>

The JSON reply holds {"shipments": {<id>: {tracking_number, pickup.origin,
consignee.destination, tracking_history: [{date_time, status}]}}}, or
{"invalid": [<number>]} for numbers Trax doesn't know (yet).

The token stays valid for the session, so it's fetched once and reused for
every Trax parcel in a batch.
"""

from __future__ import annotations

import re
from datetime import datetime

from ..stages import Stage
from .base import TIMEOUT, SharedSession, TrackingEvent

NAME = "Trax"
BADGE_COLOR = "#7B3FE4"
# e.g. 12345678901234 (14 digits)
NUMBER_PATTERN = re.compile(r"^\d{14}$")

SITE = "https://sonic.pk"
TRACKING_PAGE = f"{SITE}/tracking"
TRACK_API = f"{SITE}/tracking/track"


def public_url(number: str) -> str:
    return f"{TRACKING_PAGE}?tracking_number={number}"


# Checked in order; first match wins.
_RULES: list[tuple[re.Pattern, Stage]] = [
    (re.compile(r"return", re.I), Stage.RETURNED),
    (re.compile(r"unsuccessful|undeliver|not deliver|refus|attempt|not available|unable|"
                r"incomplete address|wrong address|address not found|closed|not respond|unreachable",
                re.I), Stage.FAILED_ATTEMPT),
    (re.compile(r"\bhold\b|pending|awaiting", re.I), Stage.ON_HOLD),
    (re.compile(r"lost|damage|cancel|misroute|non[- ]?service", re.I), Stage.EXCEPTION),
    (re.compile(r"\bdelivered\b", re.I), Stage.DELIVERED),
    (re.compile(r"out for delivery|on route|with rider|assigned to rider", re.I), Stage.OUT_FOR_DELIVERY),
    (re.compile(r"arrived at destination|at destination|destination (hub|facility)", re.I), Stage.IN_CITY),
    (re.compile(r"booked|picked|pick ?up", re.I), Stage.BOOKED),
    (re.compile(r"arrived|departed|dispatch|transit|forward|received at|in process|manifest", re.I),
     Stage.IN_TRANSIT),
]

_PREFIX = re.compile(r"^\s*shipment\s*-\s*", re.I)


def clean_status(status: str) -> str:
    """'Shipment - Out for Delivery' -> 'Out for Delivery'."""
    return re.sub(r"\s+", " ", _PREFIX.sub("", status or "")).strip()


def classify(status: str) -> Stage:
    for pattern, stage in _RULES:
        if pattern.search(status):
            return stage
    return Stage.UNKNOWN


def _parse_when(text: str | None) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime((text or "").strip(), fmt)
        except ValueError:
            continue
    return None


_http = SharedSession()
_token: tuple[int, str] | None = None  # (id of the session it belongs to, token)


def _csrf_token(session, refresh: bool = False) -> str:
    global _token
    if refresh or _token is None or _token[0] != id(session):
        r = session.get(TRACKING_PAGE, timeout=TIMEOUT)
        r.raise_for_status()
        m = re.search(r'name="csrf-token"\s+content="([^"]+)"', r.text)
        if not m:
            raise RuntimeError("could not find the CSRF token on the tracking page")
        _token = (id(session), m.group(1))
    return _token[1]


def fetch_events(number: str) -> list[TrackingEvent]:
    if not number.isdigit():
        return []  # the site only accepts numbers; never send free text
    with _http as session:
        for attempt in range(2):
            r = session.post(
                TRACK_API,
                data={"tracking_numbers": number, "_token": _csrf_token(session, refresh=attempt > 0)},
                headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json",
                         "Referer": TRACKING_PAGE},
                timeout=TIMEOUT,
            )
            if r.status_code != 419:  # 419 = Laravel's "token expired"
                break
    r.raise_for_status()
    try:
        payload = r.json()
    except ValueError:
        return []
    return parse_response(payload, number)


def parse_response(payload: dict, number: str) -> list[TrackingEvent]:
    shipments = payload.get("shipments") or {}
    if isinstance(shipments, dict):
        shipments = list(shipments.values())
    # Only the requested parcel, even if the reply ever holds others.
    mine = [s for s in shipments if isinstance(s, dict) and str(s.get("tracking_number", "")) == number]
    if not mine:
        return []
    s = mine[0]
    origin = ((s.get("pickup") or {}).get("origin") or "").strip()
    destination = ((s.get("consignee") or {}).get("destination") or "").strip()

    events: list[TrackingEvent] = []
    for h in s.get("tracking_history") or []:
        raw = (h.get("status") or "").strip()
        status = clean_status(raw)
        if not status:
            continue
        stage = classify(status)
        # Trax gives no per-scan location; add the city where the step itself implies it.
        if stage in (Stage.IN_CITY, Stage.OUT_FOR_DELIVERY, Stage.DELIVERED):
            location = destination
        elif stage is Stage.BOOKED or re.search(r"\borigin\b", status, re.I):
            location = origin
        else:
            location = ""
        events.append(TrackingEvent(
            when=_parse_when(h.get("date_time")),
            description=f"{status} [{location}]" if location else status,
            stage=stage,
            location=location,
            raw_status=raw,
        ))
    events.sort(key=lambda e: e.when or datetime.min, reverse=True)
    return events
