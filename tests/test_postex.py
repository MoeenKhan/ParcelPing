"""PostEx parsing, and finding the right courier when number formats are shared.

Responses are made up but shaped like the real ones.
"""

from datetime import datetime

import pytest

from app.core import checker
from app.core.carriers import CARRIERS, candidates, detect, postex
from app.core.carriers.base import TrackingEvent
from app.core.stages import Stage
from app.core.store import Store

NUMBER = "12345678901234"


def reply(history, number=NUMBER):
    return {"statusCode": "200", "statusMessage": "Successfully Operated", "dist": {
        "customerName": "Test Person",
        "trackingNumber": number,
        "orderPickupDate": "2026-11-23T19:52:00.000+0500",
        "transactionStatusHistory": [
            {"transactionStatusMessage": msg, "transactionStatusMessageCode": code, "modifiedDatetime": when}
            for when, code, msg in history],
    }}


SAMPLE = reply([
    ("2026-11-25T15:10:00.000+0500", "0005", "Delivered"),
    ("2026-11-25T09:30:00.000+0500", "0004", "Out for Delivery"),
    ("2026-11-24T10:46:09.000+0500", "0033", "Departed to MULTAN"),
    ("2026-11-24T03:13:59.000+0500", "0003", "Received at LHE Warehouse"),
    ("2026-11-23T19:52:00.000+0500", "0031", "Departed to PostEx. Warehouse"),
    ("2026-11-23T11:32:02.000+0500", "0001", "At Test Shop Warehouse"),
])


def test_timeline():
    events = postex.parse_response(SAMPLE, NUMBER)
    assert [e.stage for e in events] == [
        Stage.DELIVERED, Stage.OUT_FOR_DELIVERY, Stage.IN_TRANSIT, Stage.IN_TRANSIT, Stage.BOOKED, Stage.BOOKED,
    ]
    assert events[0].when == datetime(2026, 11, 25, 15, 10)
    assert events[2].description == "Departed to MULTAN"


def test_customer_name_is_never_kept():
    events = postex.parse_response(SAMPLE, NUMBER)
    assert not any("Test Person" in e.description for e in events)


def test_not_found():
    assert postex.parse_response({"statusCode": "200", "statusMessage": "Successfully Operated"}, NUMBER) == []


def test_other_parcel_ignored():
    assert postex.parse_response(reply([("2026-11-25T15:10:00.000+0500", "0005", "Delivered")],
                                       number="99999999999999"), NUMBER) == []


@pytest.mark.parametrize("code,message,stage", [
    ("0002", "Returned to shop", Stage.RETURNED),
    ("0013", "Attempt made", Stage.FAILED_ATTEMPT),
    ("0008", "Delivery Under Review", Stage.ON_HOLD),
    ("0047", "Delivered", Stage.DELIVERED),
    # Codes the site doesn't list fall back to the message
    ("0999", "Customer refused delivery", Stage.FAILED_ATTEMPT),
    ("0999", "Order cancelled", Stage.EXCEPTION),
    ("0999", "Something new", Stage.UNKNOWN),
])
def test_classify(code, message, stage):
    assert postex.classify(code, message) is stage


def test_free_text_never_sent(monkeypatch):
    class NoNetwork:
        def __enter__(self):
            raise AssertionError("must not hit the network")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(postex, "_http", NoNetwork())
    assert postex.fetch_events("ABC") == []


# ---- shared number formats ---------------------------------------------------

def test_trax_and_postex_share_a_format():
    assert candidates(NUMBER) == ["trax", "postex"]
    assert detect(NUMBER) == "trax"  # tried first; the first check finds the right one


EVENT = TrackingEvent(datetime(2026, 11, 24, 10, 46), "Departed to MULTAN", Stage.IN_TRANSIT)


@pytest.fixture
def couriers(monkeypatch):
    """Trax doesn't know the parcel; PostEx does. Records who was asked."""
    asked = []

    def fake(key, events):
        def fetch_events(number):
            asked.append(key)
            return events
        monkeypatch.setattr(CARRIERS[key], "fetch_events", fetch_events)

    fake("trax", [])
    fake("postex", [EVENT])
    return asked


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def test_first_check_finds_the_right_courier(couriers, store):
    s = store.add("trax", NUMBER)
    result = checker.fetch(s.id, "trax", NUMBER, found_before=False)
    assert couriers == ["trax", "postex"]
    assert result.carrier == "postex" and result.events == [EVENT]

    checker.apply_result(store, result, datetime(2026, 11, 24, 11, 0))
    after = store.get(s.id)
    assert after.carrier == "postex"
    assert after.latest == EVENT


def test_found_parcels_only_ask_their_own_courier(couriers):
    result = checker.fetch(1, "trax", NUMBER, found_before=True)
    assert couriers == ["trax"]
    assert result.carrier == "trax" and result.events == []


def test_switch_skipped_when_already_tracked_there(couriers, store):
    s = store.add("trax", NUMBER)
    store.add("postex", NUMBER)  # the user also added it under PostEx
    result = checker.fetch(s.id, "trax", NUMBER, found_before=False)
    checker.apply_result(store, result, datetime(2026, 11, 24, 11, 0))
    assert store.get(s.id).carrier == "trax"
    assert store.get(s.id).events == []
