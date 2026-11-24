"""PostEx (postex.pk).

The tracking page is a Next.js app that calls its own API route:

    POST /api/tracking-order  {"trackingNumber": "<number>"}

The reply is {"statusCode": "200", "dist": {..., "transactionStatusHistory":
[{transactionStatusMessage, transactionStatusMessageCode, modifiedDatetime}]}}.
Unknown numbers come back without "dist".

Status codes are grouped the way the site's own tracking page groups them
(by the icon it shows); the message text decides for codes not listed.
"""

from __future__ import annotations

import re
from datetime import datetime

from ..stages import Stage
from .base import TIMEOUT, SharedSession, TrackingEvent

NAME = "PostEx"
BADGE_COLOR = "#E4572E"
# e.g. 12345678901234 (14 digits; Trax uses the same format)
NUMBER_PATTERN = re.compile(r"^\d{14}$")

SITE = "https://postex.pk"
TRACK_API = f"{SITE}/api/tracking-order"


def public_url(number: str) -> str:
    return f"{SITE}/tracking?cn={number}"


# Code groups from the site's tracking page.
CODES: dict[str, Stage] = {
    **dict.fromkeys(("0001", "0032", "0036"), Stage.BOOKED),  # at the shop's warehouse
    "0031": Stage.BOOKED,  # left the shop for PostEx's warehouse
    **dict.fromkeys(("0003", "0033", "0035", "0037", "0038", "0039"), Stage.IN_TRANSIT),
    "0004": Stage.OUT_FOR_DELIVERY,
    **dict.fromkeys(("0005", "0047"), Stage.DELIVERED),
    **dict.fromkeys(("0008", "0045"), Stage.ON_HOLD),  # delivery under review
    **dict.fromkeys(("0013", "0046"), Stage.FAILED_ATTEMPT),  # attempt made / re-attempt
    **dict.fromkeys(("0002", "0006", "0007", "0040"), Stage.RETURNED),
}

# For codes not listed above. Checked in order; first match wins.
_RULES: list[tuple[re.Pattern, Stage]] = [
    (re.compile(r"return", re.I), Stage.RETURNED),
    (re.compile(r"unsuccessful|undeliver|not deliver|refus|attempt|not available|unable|"
                r"incomplete address|wrong address|not respond|unreachable", re.I), Stage.FAILED_ATTEMPT),
    (re.compile(r"\bhold\b|pending|under review|awaiting", re.I), Stage.ON_HOLD),
    (re.compile(r"lost|damage|cancel|expired", re.I), Stage.EXCEPTION),
    (re.compile(r"\bdelivered\b", re.I), Stage.DELIVERED),
    (re.compile(r"out for delivery|on route|en[- ]?route to customer|with rider", re.I), Stage.OUT_FOR_DELIVERY),
    (re.compile(r"booked|picked|pick ?up|order placed|confirmed", re.I), Stage.BOOKED),
    (re.compile(r"arrived|departed|dispatch|transit|received at|warehouse", re.I), Stage.IN_TRANSIT),
]


def classify(code: str, message: str) -> Stage:
    if code in CODES:
        return CODES[code]
    for pattern, stage in _RULES:
        if pattern.search(message):
            return stage
    return Stage.UNKNOWN


def _parse_when(text: str | None) -> datetime | None:
    """'2026-11-24T10:46:09.000+0500' -> local time as shown on the site."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}(?::\d{2})?)", text or "")
    if not m:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)}", fmt)
        except ValueError:
            continue
    return None


_http = SharedSession()


def fetch_events(number: str) -> list[TrackingEvent]:
    if not number.isdigit():
        return []  # never send free text
    with _http as session:
        r = session.post(TRACK_API, json={"trackingNumber": number}, timeout=TIMEOUT,
                         headers={"Origin": SITE, "Referer": public_url(number)})
    r.raise_for_status()
    try:
        payload = r.json()
    except ValueError:
        return []
    return parse_response(payload, number)


def parse_response(payload: dict, number: str) -> list[TrackingEvent]:
    if not str(payload.get("statusCode", "")).startswith("20"):
        return []
    dist = payload.get("dist")
    if not isinstance(dist, dict):
        return []  # not found (yet)
    if str(dist.get("trackingNumber", number)) != number:
        return []  # only the requested parcel
    events: list[TrackingEvent] = []
    for h in dist.get("transactionStatusHistory") or []:
        message = re.sub(r"\s+", " ", (h.get("transactionStatusMessage") or "")).strip()
        if not message:
            continue
        code = str(h.get("transactionStatusMessageCode") or "")
        events.append(TrackingEvent(
            when=_parse_when(h.get("modifiedDatetime")),
            description=message,
            stage=classify(code, message),
            raw_status=code,
        ))
    events.sort(key=lambda e: e.when or datetime.min, reverse=True)
    return events
