"""TCS parsing, using responses shaped like the real API with made-up values."""

from datetime import datetime

import pytest

from app.core.carriers import detect, tcs
from app.core.stages import Stage

NUMBER = "1234567890"


def response(checkpoints, deliveryinfo=None, shipmentinfo=None):
    return {
        "shipmentinfo": shipmentinfo,
        "deliveryinfo": deliveryinfo,
        "checkpoints": checkpoints,
        "shipmentsummary": "",
        "message": "SUCCESS",
        "traceid": "00000000-0000-0000-0000-000000000000",
    }


def cp(when, status, by=None, number=NUMBER):
    return {"consignmentno": number, "datetime": when, "recievedby": by, "status": status}


SAMPLE = response(
    checkpoints=[
        cp("Monday Oct 12, 2026 13:26", "Shipment Delivered", "TEST PERSON"),
        cp("Monday Oct 12, 2026 08:49", "Out For Delivery"),
        cp("Sunday Oct 11, 2026 22:10", "Arrived at TCS Facility", "MULTAN"),
        cp("Saturday Oct 10, 2026 13:40", "Departed From TCS Facility", "KARACHI"),
        cp("Saturday Oct 10, 2026 11:05", "Shipment Booked", "KARACHI"),
    ],
    deliveryinfo=[{"consignmentno": NUMBER, "station": "MULTAN", "datetime": "Monday Oct 12, 2026 13:26",
                   "recievedby": "TEST PERSON", "status": "Delivered", "code": "OK", "allowshow": "Y"}],
    shipmentinfo=[{"consignmentno": NUMBER, "bookingdate": "Oct 10, 2026", "shipper": "TEST SHOP",
                   "consignee": "TEST PERSON", "origin": "KARACHI", "destination": "MULTAN"}],
)


def test_timeline():
    events = tcs.parse_response(SAMPLE, NUMBER)
    assert [e.stage for e in events] == [
        Stage.DELIVERED, Stage.OUT_FOR_DELIVERY, Stage.IN_CITY, Stage.IN_TRANSIT, Stage.BOOKED,
    ]
    assert events[0].when == datetime(2026, 10, 12, 13, 26)
    assert events[0].description == "Shipment Delivered [MULTAN]"
    assert events[2].description == "Arrived at TCS Facility [MULTAN]"


def test_who_signed_is_never_kept():
    events = tcs.parse_response(SAMPLE, NUMBER)
    assert not any("TEST PERSON" in (e.description + e.location) for e in events)


def test_other_peoples_shipments_are_ignored():
    mixed = response(
        checkpoints=[cp("Monday Oct 12, 2026 08:49", "Out For Delivery"),
                     cp("Monday Oct 12, 2026 09:00", "Shipment Delivered", "SOMEONE ELSE", number="999999999999")],
        deliveryinfo=[{"consignmentno": "999999999999", "station": "LAHORE", "datetime": "Monday Oct 12, 2026 09:00",
                       "recievedby": "SOMEONE ELSE", "status": "Delivered", "code": "OK"}],
    )
    events = tcs.parse_response(mixed, NUMBER)
    assert [e.description for e in events] == ["Out For Delivery"]


def test_delivery_record_added_when_missing_from_timeline():
    data = response(
        checkpoints=[cp("Monday Oct 12, 2026 08:49", "Out For Delivery")],
        deliveryinfo=[{"consignmentno": NUMBER, "station": "MULTAN", "datetime": "Monday Oct 12, 2026 13:26",
                       "recievedby": "TEST PERSON", "status": "Delivered", "code": "OK"}],
    )
    events = tcs.parse_response(data, NUMBER)
    assert [e.stage for e in events] == [Stage.DELIVERED, Stage.OUT_FOR_DELIVERY]
    assert events[0].description == "Delivered [MULTAN]"


def test_not_found():
    data = response(checkpoints=None)
    data["shipmentsummary"] = "No Data Found/Invalid CN"
    assert tcs.parse_response(data, NUMBER) == []


def test_free_text_is_never_sent(monkeypatch):
    class NoNetwork:
        def __enter__(self):
            raise AssertionError("must not hit the network")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(tcs, "_http", NoNetwork())
    assert tcs.fetch_events("ABC123") == []
    with pytest.raises(AssertionError):  # proves the guard above is what stopped it
        tcs.fetch_events("1234567890")


@pytest.mark.parametrize("status,stage", [
    ("Shipment Booked", Stage.BOOKED),
    ("Arrived at TCS Facility", Stage.IN_TRANSIT),
    ("Departed From TCS Facility", Stage.IN_TRANSIT),
    ("Out For Delivery", Stage.OUT_FOR_DELIVERY),
    ("Shipment Delivered", Stage.DELIVERED),
    ("Delivered", Stage.DELIVERED),
    # Plausible failure wording must not read as delivered
    ("Not Delivered - Consignee Not Available", Stage.FAILED_ATTEMPT),
    ("Delivery Attempted", Stage.FAILED_ATTEMPT),
    ("Return To Shipper", Stage.RETURNED),
    ("Shipment On Hold", Stage.ON_HOLD),
])
def test_classify(status, stage):
    assert tcs.classify(status) is stage


def test_detect():
    assert detect("1234567890") == "tcs"
    assert detect("123456789012") == "tcs"
    assert detect("123456789") is None
    assert detect("AB1234567890") == "leopards"
