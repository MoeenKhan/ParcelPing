"""Build a single-file Windows .exe into dist/.

    venv\\Scripts\\python build.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app import __version__, config  # noqa: E402


def make_icon() -> Path:
    from PySide6.QtGui import QGuiApplication

    from app.ui.icon import render

    app = QGuiApplication.instance() or QGuiApplication(["build", "-platform", "offscreen"])  # noqa: F841
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    ico = assets / "icon.ico"
    # Qt's ICO writer stores one size per file; 256px scales down well in Explorer.
    if not render(256).save(str(ico), "ICO"):
        raise SystemExit("could not write icon.ico")
    return ico


def main() -> None:
    ico = make_icon()
    for d in ("build", "dist"):
        shutil.rmtree(ROOT / d, ignore_errors=True)
    name = config.APP_NAME
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller", "main.py",
            "--name", name,
            "--onefile",
            "--windowed",
            "--noconfirm",
            "--icon", str(ico),
            # Trim Qt modules we don't use.
            "--exclude-module", "tkinter",
            "--exclude-module", "PySide6.QtQml",
            "--exclude-module", "PySide6.QtQuick",
            "--exclude-module", "PySide6.QtSql",
            "--exclude-module", "PySide6.QtTest",
            "--exclude-module", "PySide6.QtOpenGL",
            "--exclude-module", "PySide6.QtPdf",
        ],
        cwd=ROOT,
        check=True,
    )
    exe = ROOT / "dist" / f"{name}.exe"
    print(f"\nBuilt {exe}  ({exe.stat().st_size / 1e6:.1f} MB), version {__version__}")


if __name__ == "__main__":
    main()
