"""App identity and file locations.

Rename the app by changing APP_NAME (the build script reads it too).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "ParcelPing"

# "owner/repo" on GitHub. When set, the app checks that repo's latest release
# for a newer version (the repo must be public). Empty disables the check.
GITHUB_REPO = "MoeenKhan/ParcelPing"

# Delivered parcels move to the Delivered tab (and stop being checked) after this.
ARCHIVE_AFTER_DAYS = 3


def app_dir() -> Path:
    """Folder containing the .exe (frozen) or the project root (from source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def is_portable() -> bool:
    """A file named 'portable' next to the .exe keeps all data beside it."""
    return (app_dir() / "portable").exists()


def data_dir() -> Path:
    override = os.environ.get("PARCELPING_DATA_DIR")  # for development/testing
    if override:
        d = Path(override)
    elif is_portable():
        d = app_dir() / "data"
    else:
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "parcels.db"
