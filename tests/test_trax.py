"""Trax parsing and token handling, with made-up responses shaped like the real ones."""

from datetime import datetime

import pytest

from app.core.carriers import detect, trax
from app.core.stages import Stage

NUMBER = "12345678901234"


def reply(history, number=NUMBER, origin="Multan", destination="Faisalabad"):
    return {"shipments": {"10000001": {
        "tracking_number": number,
        "shipper": {"name": "Test Shop"},
        "pickup": {"origin": origin},
        "consignee": {"name": "Test Person", "destination": destination},
        "tracking_history": [{"date_time": when, "status": status} for when, status in history],
    }}}


SAMPLE = reply([
    ("2026-11-23 16:56:49", "Shipment - Delivered"),
    ("2026-11-23 11:34:36", "Shipment - Out for Delivery"),
    ("2026-11-23 01:50:07", "Shipment - Arrived at Destination"),
    ("2026-11-20 07:39:58", "Shipment - In Transit"),
    ("2026-11-19 22:58:31", "Shipment - Arrived at Origin"),
    ("2026-11-19 18:31:04", "Shipment - Rider Picked"),
    ("2026-11-18 15:11:53", "Shipment - Booked"),
])


def test_timeline():
    events = trax.parse_response(SAMPLE, NUMBER)
    assert [e.stage for e in events] == [
        Stage.DELIVERED, Stage.OUT_FOR_DELIVERY, Stage.IN_CITY, Stage.IN_TRANSIT,
        Stage.IN_TRANSIT, Stage.BOOKED, Stage.BOOKED,
    ]
    assert events[0].when == datetime(2026, 11, 23, 16, 56, 49)
    assert [e.description for e in events] == [
        "Delivered [Faisalabad]", "Out for Delivery [Faisalabad]", "Arrived at Destination [Faisalabad]",
        "In Transit", "Arrived at Origin [Multan]", "Rider Picked [Multan]", "Booked [Multan]",
    ]


def test_names_are_never_kept():
    events = trax.parse_response(SAMPLE, NUMBER)
    assert not any("Test" in e.description for e in events)


def test_unknown_number():
    assert trax.parse_response({"invalid": [NUMBER]}, NUMBER) == []


def test_other_shipments_ignored():
    assert trax.parse_response(reply([("2026-11-23 16:56:49", "Shipment - Delivered")],
                                     number="99999999999999"), NUMBER) == []


@pytest.mark.parametrize("status,stage", [
    ("Shipment - Booked", Stage.BOOKED),
    ("Shipment - Rider Picked", Stage.BOOKED),
    ("Shipment - Arrived at Origin", Stage.IN_TRANSIT),
    ("Shipment - In Transit", Stage.IN_TRANSIT),
    ("Shipment - Arrived at Destination", Stage.IN_CITY),
    ("Shipment - Out for Delivery", Stage.OUT_FOR_DELIVERY),
    ("Shipment - Delivered", Stage.DELIVERED),
    # Plausible problem wording
    ("Shipment - Delivery Unsuccessful", Stage.FAILED_ATTEMPT),
    ("Shipment - Return Confirmation Pending", Stage.RETURNED),
    ("Shipment - Returned to Shipper", Stage.RETURNED),
    ("Shipment - On Hold", Stage.ON_HOLD),
    ("Shipment - Cancelled", Stage.EXCEPTION),
])
def test_classify(status, stage):
    assert trax.classify(trax.clean_status(status)) is stage


def test_detect():
    assert detect("12345678901234") == "trax"
    assert detect("1234567890") == "tcs"  # TCS numbers are shorter
    assert detect("1234567890123") is None


class FakeResponse:
    def __init__(self, status=200, text="", data=None):
        self.status_code, self.text, self._data = status, text, data

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSite:
    """sonic.pk with a token that has to be fetched, and can expire."""

    def __init__(self):
        self.valid_token, self.page_loads, self.posts = "token-1", 0, []

    def get(self, url, **kw):
        self.page_loads += 1
        return FakeResponse(text=f'<meta name="csrf-token" content="{self.valid_token}">')

    def post(self, url, data=None, **kw):
        self.posts.append(data)
        if data["_token"] != self.valid_token:
            return FakeResponse(419)
        return FakeResponse(data=SAMPLE)


class FakeShared:
    def __init__(self, site):
        self.site = site

    def __enter__(self):
        return self.site

    def __exit__(self, *exc):
        return False


@pytest.fixture
def site(monkeypatch):
    s = FakeSite()
    monkeypatch.setattr(trax, "_http", FakeShared(s))
    monkeypatch.setattr(trax, "_token", None)
    return s


def test_token_fetched_once_and_reused(site):
    for _ in range(3):
        assert len(trax.fetch_events(NUMBER)) == 7
    assert site.page_loads == 1
    assert len(site.posts) == 3


def test_expired_token_refreshed(site):
    trax.fetch_events(NUMBER)
    site.valid_token = "token-2"  # the site rotated it
    assert len(trax.fetch_events(NUMBER)) == 7
    assert site.page_loads == 2


def test_free_text_never_sent(site):
    assert trax.fetch_events("ABC") == []
    assert site.posts == [] and site.page_loads == 0
