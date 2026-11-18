from datetime import datetime, timedelta

import pytest

from app.core import checker
from app.core.carriers import detect, dex, leopards, split_numbers
from app.core.carriers.base import TrackingEvent
from app.core.checker import Backoff, FetchResult, apply_result, due, parse_numbers_file
from app.core.stages import Stage
from app.core.store import ACTIVE, DELIVERED, PROBLEMS, DuplicateShipment, Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def ev(minutes_ago: int, desc: str, stage: Stage, now=datetime(2026, 11, 18, 12, 0)) -> TrackingEvent:
    return TrackingEvent(when=now - timedelta(minutes=minutes_ago), description=desc, stage=stage)


# ---- carriers ---------------------------------------------------------------

@pytest.mark.parametrize("desc,stage", [
    # Leopards wording (sample data, not real shipments)
    ("Shipment Picked at ORIGIN KARACHI", Stage.BOOKED),
    ("Shipment Dispatched from KARACHI to MULTAN", Stage.IN_TRANSIT),
    ("Arrived in MULTAN", Stage.IN_TRANSIT),
    ("Forwarded to SAHIWAL", Stage.IN_TRANSIT),
    ("Assigned to Leopards in SAHIWAL", Stage.OUT_FOR_DELIVERY),
    ("Delivered at SAHIWAL TEST CUSTOMER ~ SELF", Stage.DELIVERED),
    # Plausible failure wording must not read as delivered
    ("Undelivered - Consignee not available", Stage.FAILED_ATTEMPT),
    ("Returned to shipper", Stage.RETURNED),
])
def test_leopards_classify(desc, stage):
    assert leopards.classify(desc) is stage


def test_leopards_classify_falls_back_to_css_class():
    assert leopards.classify("Something new", "intransit") is Stage.IN_TRANSIT
    assert leopards.classify("Something new", "") is Stage.UNKNOWN


def test_leopards_parse_events():
    html = """
    <div class="tracking-item"><div class="tracking-icon status-outfordelivery"></div>
      <div class="tracking-date">07 November, 2026 <span>(16:08)</span></div>
      <div class="tracking-content">Delivered at SAHIWAL   TEST CUSTOMER ~ SELF</div></div>
    <div class="tracking-item"><div class="tracking-icon status-intransit"></div>
      <div class="tracking-date">05 November, 2026 <span>(16:26)</span></div>
      <div class="tracking-content">Shipment Picked at ORIGIN LAHORE</div></div>
    """
    events = leopards.parse_events(html)
    assert events[0].when == datetime(2026, 11, 7, 16, 8)
    assert events[0].description == "Delivered at SAHIWAL TEST CUSTOMER ~ SELF"
    assert events[0].stage is Stage.DELIVERED
    assert events[1].stage is Stage.BOOKED


def test_dex_parse_timeline():
    timeline = [
        {"status": "domestic_pickup/sign_in_success", "processTime": 1700000000000, "location": "Lahore - Hub"},
        {"status": "domestic_out_for_delivery", "processTime": 1700200000000, "location": "Multan"},
        {"status": "domestic_package_stationed_in", "processTime": 1700100000000, "location": "Multan"},
        {"status": "brand_new_code", "processTime": 1700200000100},
    ]
    events = dex.parse_timeline(timeline)
    assert [e.stage for e in events] == [Stage.UNKNOWN, Stage.OUT_FOR_DELIVERY, Stage.IN_CITY, Stage.BOOKED]
    assert events[0].description == "Brand new code"
    assert events[1].description == "Out for delivery [Multan]"
    assert events[3].description == "Order collected [Lahore - Hub]"


def test_detect_and_split():
    assert detect("AB1234567890") == "leopards"
    assert detect("PK-DEX100000001") == "dex"
    assert detect("123") is None
    assert split_numbers(" pk-dex1, AB1234567890\nAB1234567890 ;x ") == ["PK-DEX1", "AB1234567890", "X"]


def test_parse_numbers_file():
    text = "# comment\nAB1234567890\n\ndex: pk-dex9\nnonsense\n"
    assert parse_numbers_file(text) == [("leopards", "AB1234567890"), ("dex", "PK-DEX9")]


# ---- store & categories -----------------------------------------------------

def test_add_duplicate_rename_remove(store):
    s = store.add("dex", "pk-dex1", " Shoes ")
    assert (s.number, s.nickname, s.display_name) == ("PK-DEX1", "Shoes", "Shoes")
    with pytest.raises(DuplicateShipment):
        store.add("dex", "PK-DEX1")
    store.rename(s.id, "")
    assert store.get(s.id).display_name == "PK-DEX1"
    store.remove(s.id)
    assert store.shipments() == []


def test_settings_defaults_and_roundtrip(store):
    assert store.setting("interval_minutes") == 15
    store.set_setting("interval_minutes", 30)
    assert store.setting("interval_minutes") == 30


def test_categories(store):
    now = datetime(2026, 11, 18, 12, 0)
    s = store.add("dex", "PK-DEX1")
    store.save_events(s.id, [ev(0, "Delivered", Stage.DELIVERED, now)], now)
    assert store.get(s.id).category(now) == ACTIVE  # recently delivered stays visible
    assert store.get(s.id).category(now + timedelta(days=3)) == DELIVERED
    assert not store.get(s.id).wants_checking(now + timedelta(days=3))

    store.save_events(s.id, [ev(0, "Attempt failed", Stage.FAILED_ATTEMPT, now)], now)
    assert store.get(s.id).category(now) == PROBLEMS


def test_stage_skips_unknown_events(store):
    now = datetime(2026, 11, 18, 12, 0)
    s = store.add("dex", "PK-DEX1")
    store.save_events(s.id, [ev(0, "??", Stage.UNKNOWN, now), ev(5, "Out", Stage.OUT_FOR_DELIVERY, now)], now)
    assert store.get(s.id).stage is Stage.OUT_FOR_DELIVERY


# ---- change detection -------------------------------------------------------

def test_first_check_is_silent_then_changes_notify(store):
    now = datetime(2026, 11, 18, 12, 0)
    s = store.add("dex", "PK-DEX1")
    first = [ev(60, "In transit", Stage.IN_TRANSIT, now)]
    assert apply_result(store, FetchResult(s.id, "dex", events=first), now) is None

    assert apply_result(store, FetchResult(s.id, "dex", events=first), now) is None  # no change

    second = [ev(0, "Out for delivery", Stage.OUT_FOR_DELIVERY, now)] + first
    change = apply_result(store, FetchResult(s.id, "dex", events=second), now)
    assert change and change.event.description == "Out for delivery"
    assert change.previous_stage is Stage.IN_TRANSIT and change.is_milestone

    third = [ev(-5, "Out for delivery again", Stage.OUT_FOR_DELIVERY, now)] + second
    change = apply_result(store, FetchResult(s.id, "dex", events=third), now)
    assert change and not change.is_milestone


def test_not_found_keeps_history_and_first_info_notifies(store):
    now = datetime(2026, 11, 18, 12, 0)
    s = store.add("dex", "PK-DEX1")
    assert apply_result(store, FetchResult(s.id, "dex", events=[]), now) is None
    events = [ev(0, "Order collected", Stage.BOOKED, now)]
    change = apply_result(store, FetchResult(s.id, "dex", events=events), now)
    assert change is not None  # first info after "not found yet" is news
    assert apply_result(store, FetchResult(s.id, "dex", events=[]), now) is None
    assert store.get(s.id).events == events


def test_error_is_recorded_and_cleared(store):
    now = datetime(2026, 11, 18, 12, 0)
    s = store.add("dex", "PK-DEX1")
    apply_result(store, FetchResult(s.id, "dex", error="Couldn't reach DEX"), now)
    assert store.get(s.id).last_error == "Couldn't reach DEX"
    apply_result(store, FetchResult(s.id, "dex", events=[ev(0, "x", Stage.BOOKED, now)]), now)
    assert store.get(s.id).last_error == ""


def test_friendly_error():
    import requests
    assert checker.friendly_error("DEX", requests.ConnectionError()) == "Couldn't reach DEX"
    assert checker.friendly_error("DEX", ValueError()) == "Couldn't read DEX's tracking page"


# ---- scheduling -------------------------------------------------------------

def test_backoff_grows_and_resets():
    b, now = Backoff(), datetime(2026, 11, 18, 12, 0)
    b.failed("dex", now)
    assert b.blocked_until("dex", now) == now + timedelta(minutes=5)
    b.failed("dex", now)
    assert b.blocked_until("dex", now) == now + timedelta(minutes=10)
    for _ in range(10):
        b.failed("dex", now)
    assert b.blocked_until("dex", now) == now + timedelta(hours=2)
    b.succeeded("dex")
    assert b.blocked_until("dex", now) is None


def test_due(store):
    now = datetime(2026, 11, 18, 12, 0)
    fresh = store.add("dex", "PK-DEX1")
    recent = store.add("dex", "PK-DEX2")
    store.save_checked(recent.id, now - timedelta(minutes=5))
    old = store.add("leopards", "KI0000000001")
    store.save_checked(old.id, now - timedelta(minutes=20))

    b = Backoff()
    ids = lambda xs: sorted(s.id for s in xs)  # noqa: E731
    assert ids(due(store.shipments(), now, timedelta(minutes=15), b)) == ids([fresh, old])
    b.failed("dex", now)
    assert ids(due(store.shipments(), now, timedelta(minutes=15), b)) == [old.id]
    assert len(due(store.shipments(), now, timedelta(minutes=15), b, force=True)) == 3
