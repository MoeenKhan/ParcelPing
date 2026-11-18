"""'Start with Windows' via the per-user Run registry key (no admin needed)."""

from __future__ import annotations

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
