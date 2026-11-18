"""SQLite storage for shipments, their full timelines, and settings.

Use from the main (UI) thread only; background checks hand results back.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .. import config
from .carriers import CARRIERS, TrackingEvent
from .stages import Stage

ACTIVE, DELIVERED, PROBLEMS = "active", "delivered", "problems"

DEFAULT_SETTINGS: dict[str, Any] = {
    "interval_minutes": 15,
    "notify": "all",  # "all" | "milestones"
    "theme": "system",  # "system" | "light" | "dark"
    "paused": False,
    "legacy_imported": False,
    "tray_hint_shown": False,
    "check_updates": True,
}


@dataclass
class Shipment:
    id: int
    carrier: str
    number: str
    nickname: str = ""
    added_at: datetime = field(default_factory=datetime.now)
    events: list[TrackingEvent] = field(default_factory=list)
    last_checked_at: datetime | None = None
    last_error: str = ""

    @property
    def carrier_module(self):
        return CARRIERS[self.carrier]

    @property
    def carrier_name(self) -> str:
        return self.carrier_module.NAME

    @property
    def display_name(self) -> str:
        return self.nickname or self.number

    @property
    def latest(self) -> TrackingEvent | None:
        return self.events[0] if self.events else None

    @property
    def stage(self) -> Stage | None:
        """Stage of the newest classifiable event (None = no events yet)."""
        for e in self.events:
            if e.stage is not Stage.UNKNOWN:
                return e.stage
        return Stage.UNKNOWN if self.events else None

    @property
    def delivered_at(self) -> datetime | None:
        if self.stage is not Stage.DELIVERED:
            return None
        return (self.latest and self.latest.when) or self.last_checked_at

    def category(self, now: datetime) -> str:
        stage = self.stage
        if stage is not None and stage.is_problem:
            return PROBLEMS
        delivered = self.delivered_at
        if delivered and now - delivered >= timedelta(days=config.ARCHIVE_AFTER_DAYS):
            return DELIVERED
        return ACTIVE

    def wants_checking(self, now: datetime) -> bool:
        return self.category(now) != DELIVERED


class DuplicateShipment(Exception):
    pass


_SCHEMA = """
CREATE TABLE IF NOT EXISTS shipments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    carrier TEXT NOT NULL,
    number TEXT NOT NULL,
    nickname TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL,
    events TEXT NOT NULL DEFAULT '[]',
    last_checked_at TEXT,
    last_error TEXT NOT NULL DEFAULT '',
    UNIQUE (carrier, number)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


class Store:
    def __init__(self, path: Path | str | None = None):
        self.db = sqlite3.connect(str(path or config.db_path()))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self.db.commit()

    # ---- shipments -------------------------------------------------------

    def _row(self, r: sqlite3.Row) -> Shipment:
        return Shipment(
            id=r["id"],
            carrier=r["carrier"],
            number=r["number"],
            nickname=r["nickname"],
            added_at=_dt(r["added_at"]) or datetime.now(),
            events=[TrackingEvent.from_dict(d) for d in json.loads(r["events"])],
            last_checked_at=_dt(r["last_checked_at"]),
            last_error=r["last_error"],
        )

    def shipments(self) -> list[Shipment]:
        rows = self.db.execute("SELECT * FROM shipments WHERE carrier IN (%s) ORDER BY id DESC"
                               % ",".join("?" * len(CARRIERS)), list(CARRIERS)).fetchall()
        return [self._row(r) for r in rows]

    def get(self, shipment_id: int) -> Shipment | None:
        r = self.db.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
        return self._row(r) if r else None

    def add(self, carrier: str, number: str, nickname: str = "") -> Shipment:
        if carrier not in CARRIERS:
            raise ValueError(f"unknown carrier {carrier!r}")
        try:
            cur = self.db.execute(
                "INSERT INTO shipments (carrier, number, nickname, added_at) VALUES (?, ?, ?, ?)",
                (carrier, number.upper(), nickname.strip(), datetime.now().isoformat()),
            )
        except sqlite3.IntegrityError:
            raise DuplicateShipment(number) from None
        self.db.commit()
        return self.get(cur.lastrowid)  # type: ignore[return-value]

    def rename(self, shipment_id: int, nickname: str) -> None:
        self.db.execute("UPDATE shipments SET nickname = ? WHERE id = ?", (nickname.strip(), shipment_id))
        self.db.commit()

    def remove(self, shipment_id: int) -> None:
        self.db.execute("DELETE FROM shipments WHERE id = ?", (shipment_id,))
        self.db.commit()

    def save_events(self, shipment_id: int, events: list[TrackingEvent], checked_at: datetime) -> None:
        self.db.execute(
            "UPDATE shipments SET events = ?, last_checked_at = ?, last_error = '' WHERE id = ?",
            (json.dumps([e.to_dict() for e in events]), checked_at.isoformat(), shipment_id),
        )
        self.db.commit()

    def save_checked(self, shipment_id: int, checked_at: datetime, error: str = "") -> None:
        self.db.execute(
            "UPDATE shipments SET last_checked_at = ?, last_error = ? WHERE id = ?",
            (checked_at.isoformat(), error, shipment_id),
        )
        self.db.commit()

    # ---- settings --------------------------------------------------------

    def setting(self, key: str) -> Any:
        r = self.db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(r["value"]) if r else DEFAULT_SETTINGS.get(key)

    def set_setting(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()
