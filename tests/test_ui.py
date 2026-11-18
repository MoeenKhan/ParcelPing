"""Main-window list updates (offscreen Qt, no network)."""

import os
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.carriers.base import TrackingEvent  # noqa: E402
from app.core.stages import Stage  # noqa: E402
from app.core.store import Store  # noqa: E402
from app.ui.controller import Controller  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctl(qapp, tmp_path):
    store = Store(tmp_path / "t.db")
    store.set_setting("legacy_imported", True)
    store.set_setting("paused", True)
    c = Controller(qapp, store)
    c.timer.stop()
    yield c
    c.window.hide()
    c.window.deleteLater()
    store.close()


def _events(stage: Stage, hours_ago: float) -> list[TrackingEvent]:
    return [TrackingEvent(datetime.now() - timedelta(hours=hours_ago), f"Sample {stage.value}", stage)]


def _add(c: Controller, number: str, stage: Stage, hours_ago: float = 1):
    s = c.store.add("dex", number)
    c.store.save_events(s.id, _events(stage, hours_ago), datetime.now())
    return s


def test_check_result_updates_card_in_place(ctl, qapp):
    a = _add(ctl, "PK-DEX100000001", Stage.IN_TRANSIT)
    _add(ctl, "PK-DEX100000002", Stage.BOOKED)
    ctl.window.show()
    qapp.processEvents()
    card = ctl.window.cards[a.id]

    ctl.store.save_events(a.id, _events(Stage.OUT_FOR_DELIVERY, 0.5), datetime.now())
    ctl._shipment_changed(a.id)

    assert ctl.window.cards[a.id] is card  # same widget, no rebuild
    assert card.status.text() == f"Sample {Stage.OUT_FOR_DELIVERY.value}"


def test_parcel_moving_tab_updates_lists_and_counts(ctl, qapp):
    a = _add(ctl, "PK-DEX100000001", Stage.IN_TRANSIT)
    _add(ctl, "PK-DEX100000002", Stage.BOOKED)
    ctl.window.show()
    qapp.processEvents()
    assert ctl.window.tabs.tabText(0) == "Active (2)"

    ctl.store.save_events(a.id, _events(Stage.FAILED_ATTEMPT, 0.5), datetime.now())
    ctl._shipment_changed(a.id)

    assert a.id not in ctl.window.cards
    assert ctl.window.tabs.tabText(0) == "Active (1)"
    assert ctl.window.tabs.tabText(2) == "Problems (1)"


def test_hidden_window_catches_up_when_shown(ctl, qapp):
    a = _add(ctl, "PK-DEX100000001", Stage.IN_TRANSIT)
    ctl.window.show()
    qapp.processEvents()
    ctl.window.hide()

    # Delivered long ago -> belongs in the Delivered tab.
    ctl.store.save_events(a.id, _events(Stage.DELIVERED, 24 * 10), datetime.now())
    ctl._shipment_changed(a.id)
    b = _add(ctl, "PK-DEX100000002", Stage.BOOKED)
    ctl._on_done()

    ctl.window.show()
    qapp.processEvents()
    assert set(ctl.window.cards) == {b.id}
    assert ctl.window.tabs.tabText(0) == "Active (1)"
    assert ctl.window.tabs.tabText(1) == "Delivered (1)"
