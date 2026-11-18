"""DEX / Daraz Express (www.dex.com.pk).

The tracking page is a React app that calls a plain JSON endpoint:
POST /api/get_package_history {"trackingNumber": "..."} -> timeline of
{status, processTime (epoch ms), location}. No token or cookie needed.
"""

from __future__ import annotations

import re
from datetime import datetime

import requests

from ..stages import Stage
from .base import TIMEOUT, USER_AGENT, TrackingEvent

NAME = "DEX"
BADGE_COLOR = "#3B6FD8"
# e.g. PK-DEX100000001
NUMBER_PATTERN = re.compile(r"^PK-DEX\d+$", re.IGNORECASE)

HISTORY_API = "https://www.dex.com.pk/api/get_package_history"


def public_url(number: str) -> str:
    return f"https://www.dex.com.pk/tracking?references={number}"


S = Stage
# status code -> (title as shown on dex.com.pk, common stage).
# Titles come from the site's tracking.js bundle.
STATUSES: dict[str, tuple[str, Stage]] = {
    "package_created": ("Package created", S.BOOKED),
    "package_ready_to_be_shipped": ("Ready for pick-up", S.BOOKED),
    "domestic_planned_for_pickup": ("Planned for pickup", S.BOOKED),
    "requesting_driver": ("Allocating a driver", S.BOOKED),
    "driver_assigned": ("Driver assigned", S.BOOKED),
    "domestic_about_to_pickup": ("About to pickup", S.BOOKED),
    "domestic_pickup_sign_in_failure": ("Order not received", S.BOOKED),
    "domestic_pickup_sign_in_success": ("Order collected", S.BOOKED),
    "domestic_sc_sign_in_success": ("Order collected", S.BOOKED),
    "domestic_ib_failure_in_sort_center": ("Order collected", S.BOOKED),
    "domestic_handover_accepted": ("Received by the delivery service", S.IN_TRANSIT),
    "domestic_ib_success_in_sort_center": ("Arrived at logistics facility", S.IN_TRANSIT),
    "domestic_ob_success_in_sort_center": ("Departing from the logistics hub", S.IN_TRANSIT),
    "domestic_pkg_outbound_attendance": ("Outbound attendance", S.IN_TRANSIT),
    "domestic_linehaul_packed": ("Linehaul packed", S.IN_TRANSIT),
    "domestic_multi_leg_waiting_for_handover": ("Waiting for handover", S.IN_TRANSIT),
    "domestic_package_stationed_in": ("Arrived at the local delivery hub", S.IN_CITY),
    "domestic_package_stationed_out": ("Departing from the local delivery hub", S.IN_CITY),
    "need_review": ("Allocating new delivery driver", S.IN_CITY),
    "domestic_about_to_deliver": ("About to deliver", S.OUT_FOR_DELIVERY),
    "domestic_out_for_delivery": ("Out for delivery", S.OUT_FOR_DELIVERY),
    "domestic_redelivery": ("Out for delivery again", S.OUT_FOR_DELIVERY),
    "domestic_handover_to_cp": ("On its way to the collection point", S.OUT_FOR_DELIVERY),
    "domestic_last_mile_customer_station_inbound": ("Ready at the collection point", S.OUT_FOR_DELIVERY),
    "domestic_delivered": ("Delivered", S.DELIVERED),
    "domestic_last_mile_customer_station_outbound_success": ("Collected from the collection point", S.DELIVERED),
    "domestic_1st_attempt_failed": ("Unsuccessful delivery attempt", S.FAILED_ATTEMPT),
    "domestic_reattempts_failed": ("Unsuccessful delivery attempt", S.FAILED_ATTEMPT),
    "domestic_delivery_failed": ("Delivery failed", S.FAILED_ATTEMPT),
    "domestic_last_mile_station_customer_failed_pickup": ("Not collected from the collection point", S.FAILED_ATTEMPT),
    "domestic_on_hold": ("Package on hold", S.ON_HOLD),
    "package_intercepted": ("Parcel intercepted", S.ON_HOLD),
    "domestic_package_returned": ("Delivery failed, returning", S.RETURNED),
    "domestic_back_to_shipper": ("Returning to seller", S.RETURNED),
    "domestic_return_at_transit_hub": ("Return: at logistics facility", S.RETURNED),
    "domestic_return_with_last_mile_3pl": ("Return: at logistics facility", S.RETURNED),
    "domestic_cp_return_to_3pl": ("Return: at logistics facility", S.RETURNED),
    "domestic_with_hub_returned_from_station": ("Package returned", S.RETURNED),
    "domestic_warehouse_returned": ("Package returned to seller", S.RETURNED),
    "domestic_package_return_attempt_failed": ("Failed to return to seller", S.RETURNED),
    "domestic_package_return_failed": ("Failed to return to seller", S.RETURNED),
    "domestic_package_return_failed_pickup_pending": ("Failed to return to seller", S.RETURNED),
    "package_cancelled": ("Order cancelled", S.EXCEPTION),
    "package_damaged": ("Package damaged", S.EXCEPTION),
    "package_lost": ("Lost by delivery partner", S.EXCEPTION),
    "package_scrapped": ("Package scrapped", S.EXCEPTION),
    "package_breached": ("Package breached", S.EXCEPTION),
}


def describe(status: str) -> tuple[str, Stage]:
    # The API sometimes sends e.g. "domestic_pickup/sign_in_success".
    code = status.replace("/", "_")
    if code in STATUSES:
        return STATUSES[code]
    return code.removeprefix("domestic_").replace("_", " ").capitalize(), Stage.UNKNOWN


def fetch_events(number: str) -> list[TrackingEvent]:
    r = requests.post(
        HISTORY_API,
        json={"trackingNumber": number},
        headers={"User-Agent": USER_AGENT, "Referer": public_url(number)},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    try:
        payload = r.json()
    except ValueError:
        return []
    data = payload.get("data") if payload.get("success") else None
    if not data:
        return []
    return parse_timeline(data.get("timeline") or [])


def parse_timeline(timeline: list[dict]) -> list[TrackingEvent]:
    events: list[TrackingEvent] = []
    for e in sorted(timeline, key=lambda e: e.get("processTime", 0), reverse=True):
        title, stage = describe(e.get("status", ""))
        location = e.get("location") or ""
        events.append(
            TrackingEvent(
                when=datetime.fromtimestamp(e["processTime"] / 1000) if e.get("processTime") else None,
                description=f"{title} [{location}]" if location else title,
                stage=stage,
                location=location,
                raw_status=e.get("status", ""),
            )
        )
    return events
