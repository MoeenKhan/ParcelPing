"""Entry point. Run with:  python main.py  [--minimized]

ParcelPing - track parcels and get notified when they move.
Copyright (C) 2026 ParcelPing contributors

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file.
"""

from __future__ import annotations

import getpass
import sys

from PySide6.QtGui import QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from app import config
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


def main() -> int:
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

    controller = Controller(app, Store())
    server.newConnection.connect(lambda: (server.nextPendingConnection(), controller.show_window()))

    if "--minimized" not in sys.argv or controller.tray is None:
        controller.show_window()
    controller.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
