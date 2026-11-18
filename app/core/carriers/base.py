"""Shared types for carrier modules.

Each carrier module exposes:
  NAME            display name, e.g. "DEX"
  BADGE_COLOR     hex colour for the courier badge
  NUMBER_PATTERN  compiled regex used to auto-detect the courier
  fetch_events(number) -> list[TrackingEvent], newest first ([] = not found)
  public_url(number) -> str | None   courier's own tracking page
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..stages import Stage

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
TIMEOUT = 15


@dataclass(frozen=True)
class TrackingEvent:
    when: datetime | None
    description: str
    stage: Stage
    location: str = ""
    raw_status: str = ""

    def key(self) -> str:
        stamp = self.when.isoformat(timespec="minutes") if self.when else ""
        return f"{stamp}|{self.description}"

    def to_dict(self) -> dict:
        return {
            "when": self.when.isoformat() if self.when else None,
            "description": self.description,
            "stage": self.stage.value,
            "location": self.location,
            "raw_status": self.raw_status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TrackingEvent":
        return cls(
            when=datetime.fromisoformat(d["when"]) if d.get("when") else None,
            description=d.get("description", ""),
            stage=Stage(d.get("stage", Stage.UNKNOWN.value)),
            location=d.get("location", ""),
            raw_status=d.get("raw_status", ""),
        )
