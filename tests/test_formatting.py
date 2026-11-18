from datetime import datetime

import pytest

pytest.importorskip("PySide6")

from app.ui.widgets import clock, full_datetime, humanize  # noqa: E402

NOW = datetime(2026, 11, 18, 14, 30)


@pytest.mark.parametrize("dt,expected", [
    (datetime(2026, 11, 18, 14, 29, 30), "just now"),
    (datetime(2026, 11, 18, 14, 5), "25 min ago"),
    (datetime(2026, 11, 18, 9, 0), "5h ago"),
    (datetime(2026, 11, 17, 23, 0), "yesterday"),
    (datetime(2026, 11, 14, 9, 0), "4 days ago"),
    (datetime(2026, 11, 1, 9, 0), "1 Nov"),
    (datetime(2025, 12, 30, 9, 0), "30 Dec 2025"),
    (None, ""),
])
def test_humanize(dt, expected):
    assert humanize(dt, NOW) == expected


def test_clock_and_full():
    assert clock(datetime(2026, 11, 7, 16, 8)) == "4:08 PM"
    assert full_datetime(datetime(2026, 11, 7, 9, 5)) == "Sat 7 Nov, 9:05 AM"
