"""The common set of statuses every courier's events are mapped onto."""

from __future__ import annotations

from enum import Enum


class Stage(str, Enum):
    BOOKED = "booked"
    IN_TRANSIT = "in_transit"
    IN_CITY = "in_city"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    # Problems
    FAILED_ATTEMPT = "failed_attempt"
    ON_HOLD = "on_hold"
    RETURNED = "returned"
    EXCEPTION = "exception"  # lost, damaged, cancelled, ...
    # Couldn't classify; the shipment keeps its previous stage.
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return LABELS[self]

    @property
    def is_problem(self) -> bool:
        return self in PROBLEM_STAGES


# The happy path shown as the progress bar on each card.
PROGRESS = [
    Stage.BOOKED,
    Stage.IN_TRANSIT,
    Stage.IN_CITY,
    Stage.OUT_FOR_DELIVERY,
    Stage.DELIVERED,
]

PROGRESS_SHORT = ["Booked", "In transit", "In city", "Out", "Delivered"]

PROBLEM_STAGES = {Stage.FAILED_ATTEMPT, Stage.ON_HOLD, Stage.RETURNED, Stage.EXCEPTION}

LABELS = {
    Stage.BOOKED: "Booked",
    Stage.IN_TRANSIT: "In transit",
    Stage.IN_CITY: "In your city",
    Stage.OUT_FOR_DELIVERY: "Out for delivery",
    Stage.DELIVERED: "Delivered",
    Stage.FAILED_ATTEMPT: "Delivery attempt failed",
    Stage.ON_HOLD: "On hold",
    Stage.RETURNED: "Being returned",
    Stage.EXCEPTION: "Problem with shipment",
    Stage.UNKNOWN: "Update",
}
