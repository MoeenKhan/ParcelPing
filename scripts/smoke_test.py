"""Start a built ParcelPing.exe and check it runs: window, parcels, clean exit.

    python scripts/smoke_test.py dist/ParcelPing.exe

Uses a throwaway data folder with made-up parcels and checking paused, so it
needs no network and never touches your real data. Fails if the app crashes,
hangs (a windowed crash shows a dialog and never exits) or exits non-zero.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TIMEOUT = 90


def seed(data_dir: Path) -> int:
    os.environ["PARCELPING_DATA_DIR"] = str(data_dir)
    from app.core.carriers.base import TrackingEvent
    from app.core.stages import Stage
    from app.core.store import Store

    store = Store()
    for key, value in {"paused": True, "check_updates": False,
                       "legacy_imported": True, "tray_hint_shown": True}.items():
        store.set_setting(key, value)
    now = datetime.now()
    samples = [
        ("dex", "PK-DEX100000001", Stage.OUT_FOR_DELIVERY, "Out for delivery [Multan]"),
        ("dex", "PK-DEX100000002", Stage.FAILED_ATTEMPT, "Unsuccessful delivery attempt [Multan]"),
        ("leopards", "AB1234567890", Stage.IN_TRANSIT, "Shipment Dispatched from KARACHI to MULTAN"),
        ("tcs", "1234567890", Stage.IN_CITY, "Arrived at TCS Facility [MULTAN]"),
    ]
    for carrier, number, stage, text in samples:
        s = store.add(carrier, number, "Smoke test")
        store.save_events(s.id, [TrackingEvent(now - timedelta(hours=2), text, stage)], now)
    store.close()
    return len(samples)


def main() -> int:
    exe = Path(sys.argv[1]).resolve()
    if not exe.is_file():
        print(f"not found: {exe}")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        expected = seed(data)
        env = {**os.environ, "PARCELPING_DATA_DIR": str(data), "PARCELPING_SMOKE_TEST": "1",
               # Own single-instance name, so a copy you have running isn't reused.
               "USERNAME": "parcelping-smoke-test"}
        print(f"starting {exe.name} ({exe.stat().st_size / 1e6:.1f} MB)")
        proc = subprocess.Popen([str(exe)], env=env)
        try:
            code = proc.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            print(f"FAIL: still running after {TIMEOUT}s (crashed with an error dialog, or hung)")
            # Only the tree we started; never a copy the user has open.
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            proc.wait()
            return 1
        if code != 0:
            print(f"FAIL: exited with code {code}")
            return 1

        from app.core.store import Store
        store = Store(data / "parcels.db")
        found = len(store.shipments())
        store.close()
        if found != expected:
            print(f"FAIL: expected {expected} parcels after the run, found {found}")
            return 1
    print("OK: started, showed the window and quit cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
