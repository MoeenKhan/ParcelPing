"""App identity and file locations.

Rename the app by changing APP_NAME (the build script reads it too).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "PingParcel"

# Earlier names of the app, newest first. Their data folder and "Start with
# Windows" entry are taken over on first start.
OLD_APP_NAMES = ("ParcelPing",)

# "owner/repo" on GitHub. When set, the app checks that repo's latest release
# for a newer version (the repo must be public). Empty disables the check.
GITHUB_REPO = "MoeenKhan/PingParcel"

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
    override = os.environ.get("PINGPARCEL_DATA_DIR")  # for development/testing
    if override:
        d = Path(override)
    elif is_portable():
        d = app_dir() / "data"
    else:
        base = Path(os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming"))
        d = base / APP_NAME
        if not d.exists():
            _adopt_old_data(base, d)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _adopt_old_data(base: Path, new: Path) -> None:
    """First start after a rename: copy the old data folder (the old one stays as a backup)."""
    for old_name in OLD_APP_NAMES:
        old = base / old_name
        if (old / "parcels.db").is_file():
            try:
                shutil.copytree(old, new)
            except OSError:
                shutil.rmtree(new, ignore_errors=True)  # start fresh rather than half-copied
            return


def db_path() -> Path:
    return data_dir() / "parcels.db"
