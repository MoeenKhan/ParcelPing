"""Shared types for carrier modules.

Each carrier module exposes:
  NAME            display name, e.g. "DEX"
  BADGE_COLOR     hex colour for the courier badge
  NUMBER_PATTERN  compiled regex used to auto-detect the courier
  fetch_events(number) -> list[TrackingEvent], newest first ([] = not found)
  public_url(number) -> str | None   courier's own tracking page
"""

from __future__ import annotations

import ssl
import threading
import time
from dataclasses import dataclass
from datetime import datetime

import certifi
import requests
from requests.adapters import HTTPAdapter

from ..stages import Stage

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
TIMEOUT = 15

_ssl_context: ssl.SSLContext | None = None
_ssl_lock = threading.Lock()


def _shared_ssl_context() -> ssl.SSLContext:
    """Certificate store loaded once per run.

    requests re-reads the CA bundle for every new connection, which costs
    ~300 ms of CPU each time; a check every few minutes would pay it per
    parcel.
    """
    global _ssl_context
    with _ssl_lock:
        if _ssl_context is None:
            _ssl_context = ssl.create_default_context(cafile=certifi.where())
        return _ssl_context


class _SharedContextAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = _shared_ssl_context()
        super().init_poolmanager(*args, **kwargs)

    def cert_verify(self, conn, url, verify, cert):
        super().cert_verify(conn, url, verify, cert)
        if verify is True:
            # Already in the shared context; don't make urllib3 load it again.
            conn.ca_certs = None
            conn.ca_cert_dir = None


def new_session() -> requests.Session:
    """A requests session that verifies certificates via the shared context."""
    session = requests.Session()
    session.mount("https://", _SharedContextAdapter())
    session.headers["User-Agent"] = USER_AGENT
    return session


class SharedSession:
    """One session per courier, reused while checks follow each other closely.

    Keeps the connection open across the parcels in a batch. After a minute
    idle it starts over, since routers may silently drop idle connections.

        with _http as session:
            session.get(...)
    """

    def __init__(self, max_idle: float = 60.0):
        self.max_idle = max_idle
        self._lock = threading.Lock()
        self._session: requests.Session | None = None
        self._last_used = 0.0

    def __enter__(self) -> requests.Session:
        self._lock.acquire()
        if self._session is None or time.monotonic() - self._last_used > self.max_idle:
            if self._session is not None:
                self._session.close()
            self._session = new_session()
        return self._session

    def __exit__(self, *exc) -> None:
        self._last_used = time.monotonic()
        self._lock.release()


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
    def from_dict(cls, d: dict) -> TrackingEvent:
        return cls(
            when=datetime.fromisoformat(d["when"]) if d.get("when") else None,
            description=d.get("description", ""),
            stage=Stage(d.get("stage", Stage.UNKNOWN.value)),
            location=d.get("location", ""),
            raw_status=d.get("raw_status", ""),
        )
