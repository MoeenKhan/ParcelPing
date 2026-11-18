"""TCS (www.tcsexpress.com).

The tracking page is a React app. It posts the lookup to the site's own
bridge, which forwards it to TCS's tracking API:

    POST /apibridge
    {"body": {"url": "trackapinew", "type": "GET", "headers": {}, "payload": {},
              "param": "consignee=<number>"}}

The response's responseData holds shipmentinfo (origin/destination),
checkpoints (the timeline) and deliveryinfo. Unknown numbers come back with
checkpoints = null.

The lookup also matches shipments by their reference text, which can return
other people's parcels. So only plain digit numbers are ever sent, and only
entries whose consignmentno equals the requested number are used.
"""

from __future__ import annotations

import re
from datetime import datetime

from ..stages import Stage
from .base import TIMEOUT, SharedSession, TrackingEvent

NAME = "TCS"
BADGE_COLOR = "#D40511"
# e.g. 1234567890 or 123456789012 (10-12 digits)
NUMBER_PATTERN = re.compile(r"^\d{10,12}$")

SITE = "https://www.tcsexpress.com"
BRIDGE_API = f"{SITE}/apibridge"


def public_url(number: str) -> str:
    return f"{SITE}/track/{number}"


# Checked in order; first match wins. Failure wording before "delivered" so
# "Not delivered" isn't read as delivered.
_RULES: list[tuple[re.Pattern, Stage]] = [
    (re.compile(r"return|\brts\b", re.I), Stage.RETURNED),
    (re.compile(r"undeliver|not deliver|refus|attempt|not available|unable|incomplete address|"
                r"wrong address|address not found|closed|not respond|unreachable", re.I), Stage.FAILED_ATTEMPT),
    (re.compile(r"\bhold\b|pending|awaiting", re.I), Stage.ON_HOLD),
    (re.compile(r"lost|damage|cancel|misroute", re.I), Stage.EXCEPTION),
    (re.compile(r"\bdelivered\b", re.I), Stage.DELIVERED),
    (re.compile(r"out for delivery|on route|with courier|with rider", re.I), Stage.OUT_FOR_DELIVERY),
    (re.compile(r"booked|picked|pick ?up|received from shipper", re.I), Stage.BOOKED),
    (re.compile(r"arrived|departed|dispatch|transit|forward|received at|in process|manifest", re.I),
     Stage.IN_TRANSIT),
]


def classify(status: str) -> Stage:
    for pattern, stage in _RULES:
        if pattern.search(status):
            return stage
    return Stage.UNKNOWN


def _parse_when(text: str | None) -> datetime | None:
    text = re.sub(r"\s+", " ", (text or "").strip())
    for fmt in ("%A %b %d, %Y %H:%M", "%A %B %d, %Y %H:%M", "%b %d, %Y %H:%M", "%B %d, %Y %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


_http = SharedSession()


def fetch_events(number: str) -> list[TrackingEvent]:
    if not number.isdigit():
        # Free text is matched against other shipments' references; never send it.
        return []
    with _http as session:
        r = session.post(
            BRIDGE_API,
            json={"body": {"url": "trackapinew", "type": "GET", "headers": {}, "payload": {},
                           "param": f"consignee={number}"}},
            headers={"Origin": SITE, "Referer": public_url(number)},
            timeout=TIMEOUT,
        )
    r.raise_for_status()
    try:
        payload = r.json()
    except ValueError:
        return []
    if not payload.get("isSuccess"):
        return []
    return parse_response(payload.get("responseData") or {}, number)


def _own(entries, number: str) -> list[dict]:
    """Only this parcel's entries (see the module docstring for why)."""
    return [e for e in entries or [] if isinstance(e, dict) and str(e.get("consignmentno", "")) == number]


def parse_response(data: dict, number: str) -> list[TrackingEvent]:
    info = _own(data.get("shipmentinfo"), number)
    destination = (info[0].get("destination") or "").strip().upper() if info else ""
    deliveries = _own(data.get("deliveryinfo"), number)
    delivery_station = (deliveries[0].get("station") or "").strip() if deliveries else ""

    events: list[TrackingEvent] = []
    seen: set[tuple] = set()
    for c in _own(data.get("checkpoints"), number):
        status = re.sub(r"\s+", " ", (c.get("status") or "").strip())
        if not status:
            continue
        stage = classify(status)
        if stage is Stage.DELIVERED:
            # On delivery, "recievedby" is the person who signed; show the city instead.
            location = delivery_station
        else:
            location = (c.get("recievedby") or "").strip()
        if stage is Stage.IN_TRANSIT and destination and location.upper() == destination:
            stage = Stage.IN_CITY
        when = _parse_when(c.get("datetime"))
        seen.add((when, stage))
        events.append(TrackingEvent(
            when=when,
            description=f"{status} [{location}]" if location else status,
            stage=stage,
            location=location,
            raw_status=status,
        ))

    # The delivery record, if the timeline doesn't already include it.
    for d in deliveries:
        status = re.sub(r"\s+", " ", (d.get("status") or "").strip())
        when, stage = _parse_when(d.get("datetime")), classify(status)
        if not status or (when, stage) in seen:
            continue
        location = (d.get("station") or "").strip()
        events.append(TrackingEvent(
            when=when,
            description=f"{status} [{location}]" if location else status,
            stage=stage,
            location=location,
            raw_status=status,
        ))

    events.sort(key=lambda e: e.when or datetime.min, reverse=True)
    return events
