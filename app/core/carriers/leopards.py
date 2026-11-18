"""Leopards Courier (pk.leopardscourier.com).

The site keeps the looked-up number in the session: fetch the page for a
CSRF token, submit the number via the AJAX endpoint, then re-fetch the page
and parse the rendered timeline.
"""

from __future__ import annotations

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from ..stages import Stage
from .base import TIMEOUT, USER_AGENT, TrackingEvent

NAME = "Leopards"
BADGE_COLOR = "#D9822B"
# e.g. AB1234567890 (two letters + 10 digits)
NUMBER_PATTERN = re.compile(r"^[A-Z]{2}\d{10}$", re.IGNORECASE)

BASE = "https://pk.leopardscourier.com"
TRACKING_PAGE = f"{BASE}/shipment_tracking_view"
TRACK_API = f"{BASE}/shipment_tracking-new"


def public_url(number: str) -> str:
    # The site has no per-number URL; the user pastes the number there.
    return TRACKING_PAGE


# Checked in order; first match wins. Failure wording is checked before
# "delivered" so "Undelivered" isn't read as delivered.
_RULES: list[tuple[re.Pattern, Stage]] = [
    (re.compile(r"return", re.I), Stage.RETURNED),
    (re.compile(r"undeliver|not deliver|refus|attempt|not available|incomplete address|"
                r"wrong address|closed|unable", re.I), Stage.FAILED_ATTEMPT),
    (re.compile(r"\bhold\b|pending", re.I), Stage.ON_HOLD),
    (re.compile(r"lost|damage|cancel", re.I), Stage.EXCEPTION),
    (re.compile(r"^delivered|\bdelivered (at|to)\b", re.I), Stage.DELIVERED),
    (re.compile(r"out for delivery|assigned to|with rider|on route", re.I), Stage.OUT_FOR_DELIVERY),
    (re.compile(r"picked|booked", re.I), Stage.BOOKED),
    (re.compile(r"dispatch|forward|arrived|transit|received at", re.I), Stage.IN_TRANSIT),
]

_CLASS_FALLBACK = {
    "intransit": Stage.IN_TRANSIT,
    "outfordelivery": Stage.OUT_FOR_DELIVERY,
    "delivered": Stage.DELIVERED,
    "picked": Stage.BOOKED,
}


def classify(description: str, status_class: str = "") -> Stage:
    for pattern, stage in _RULES:
        if pattern.search(description):
            return stage
    return _CLASS_FALLBACK.get(status_class, Stage.UNKNOWN)


def _extract_token(html: str) -> str:
    m = re.search(r"_token['\"]?\s*:\s*['\"]([A-Za-z0-9]+)['\"]", html)
    if not m:
        raise RuntimeError("could not find _token on tracking page")
    return m.group(1)


def fetch_events(number: str) -> list[TrackingEvent]:
    session = requests.Session()
    headers = {"User-Agent": USER_AGENT}

    r = session.get(TRACKING_PAGE, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    token = _extract_token(r.text)

    r = session.get(
        TRACK_API,
        params={"cn_number": number, "_token": token},
        headers={**headers, "X-Requested-With": "XMLHttpRequest", "Referer": TRACKING_PAGE},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    try:
        if not r.json().get("success"):
            return []
    except ValueError:
        return []

    r = session.get(TRACKING_PAGE, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    events = parse_events(r.text)
    events.sort(key=lambda e: e.when or datetime.min, reverse=True)
    return events


def _parse_when(date_text: str, time_text: str) -> datetime | None:
    for fmt in ("%d %B, %Y %H:%M", "%d %B %Y %H:%M", "%d %b, %Y %H:%M"):
        try:
            return datetime.strptime(f"{date_text} {time_text}".strip(), fmt)
        except ValueError:
            continue
    return None


def parse_events(html: str) -> list[TrackingEvent]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[TrackingEvent] = []
    for item in soup.select(".tracking-item"):
        status_class = ""
        icon = item.select_one(".tracking-icon")
        if icon:
            for cls in icon.get("class", []):
                if cls.startswith("status-"):
                    status_class = cls.removeprefix("status-")
                    break

        date_text = time_text = ""
        date_el = item.select_one(".tracking-date")
        if date_el:
            span = date_el.select_one("span")
            if span:
                time_text = span.get_text(strip=True).strip("()")
                span.extract()
            date_text = date_el.get_text(" ", strip=True)

        content_el = item.select_one(".tracking-content")
        description = content_el.get_text(" ", strip=True) if content_el else ""
        description = re.sub(r"\s+", " ", description)

        events.append(
            TrackingEvent(
                when=_parse_when(date_text, time_text),
                description=description,
                stage=classify(description, status_class),
                raw_status=status_class,
            )
        )
    return events
