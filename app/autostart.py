"""'Start with Windows' via the per-user Run registry key (no admin needed)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import config

_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    # From source: use pythonw so no console window appears.
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    main = config.app_dir() / "main.py"
    return f'"{pythonw if pythonw.exists() else exe}" "{main}" --minimized'


def is_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY) as k:
            winreg.QueryValueEx(k, config.APP_NAME)
            return True
    except OSError:
        return False


def adopt_old_entry() -> None:
    """First start after a rename: replace the old name's "Start with Windows"
    entry with one for this copy, so it's on if it was on before.

    Only for the built .exe in normal use; test runs (with a data-folder
    override) and runs from source never touch the real registry entry.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    if os.environ.get("PINGPARCEL_DATA_DIR"):
        return
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as k:
            for old_name in config.OLD_APP_NAMES:
                try:
                    winreg.QueryValueEx(k, old_name)
                except FileNotFoundError:
                    continue
                winreg.DeleteValue(k, old_name)
                winreg.SetValueEx(k, config.APP_NAME, 0, winreg.REG_SZ, command())
    except OSError:
        pass  # not worth failing start-up over


def set_enabled(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, config.APP_NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(k, config.APP_NAME)
            except FileNotFoundError:
                pass
