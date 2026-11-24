"""Entry point. Run with:  python main.py  [--minimized]

PingParcel - track parcels and get notified when they move.
Copyright (C) 2026 PingParcel contributors

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file.
"""

from __future__ import annotations

import getpass
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from app import autostart, config, updates
from app.core.store import Store
from app.ui.controller import Controller
from app.ui.icon import app_icon


def _server_name() -> str:
    return f"{config.APP_NAME}-{getpass.getuser()}"


def _already_running() -> bool:
    """If another copy is running, ask it to show its window and return True."""
    sock = QLocalSocket()
    sock.connectToServer(_server_name())
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def _arg_value(name: str) -> str | None:
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def main() -> int:
    # Started by an update: let the previous copy exit first.
    pid = _arg_value("--wait-pid")
    if pid and pid.isdigit():
        updates.wait_for_pid(int(pid))
    updates.cleanup()

    if sys.platform == "win32":
        # Own taskbar identity (and icon) instead of python.exe's.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(config.APP_NAME)

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())
    app.setFont(QFont("Segoe UI", 10))

    if _already_running():
        return 0

    QLocalServer.removeServer(_server_name())
    server = QLocalServer()
    server.listen(_server_name())
    autostart.adopt_old_entry()  # after a rename, keep "Start with Windows" on

    controller = Controller(app, Store())
    server.newConnection.connect(lambda: (server.nextPendingConnection(), controller.show_window()))

    if "--minimized" not in sys.argv or controller.tray is None:
        controller.show_window()
    controller.start(just_updated="--updated" in sys.argv)
    if os.environ.get("PINGPARCEL_SMOKE_TEST"):
        # Used by CI on the built .exe: start fully, then quit cleanly.
        QTimer.singleShot(3000, controller.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
