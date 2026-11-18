"""Ties everything together: scheduler, background checks, tray, notifications."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox, QSystemTrayIcon

from .. import __version__, config, updates
from ..core.carriers import CARRIERS
from ..core.checker import Backoff, Change, FetchResult, apply_result, due, fetch, parse_numbers_file
from ..core.store import ACTIVE, PROBLEMS, Store
from . import theme
from .details import DetailsDialog
from .icon import app_icon
from .main_window import MainWindow
from .settings_dialog import SettingsDialog
from .widgets import clock

TICK_MS = 30_000


UPDATE_CHECK_MS = 24 * 60 * 60 * 1000


class _Signals(QObject):
    result = Signal(object)  # FetchResult
    done = Signal()
    update_available = Signal(object)  # updates.Release we can't install ourselves
    update_ready = Signal(object, str)  # updates.Release, path of the verified .exe


class Controller(QObject):
    def __init__(self, app: QApplication, store: Store):
        super().__init__()
        self.app, self.store = app, store
        self.backoff = Backoff()
        self.running = False
        self.progress = (0, 0)
        self.queued_ids: set[int] = set()
        self.queued_force = False
        self.pending: list[Change] = []
        self.notify_target: int | None = None
        self.quitting = False
        self.details: dict[int, DetailsDialog] = {}
        self.updating = False  # an update check/download is running
        self.ready_update: tuple[updates.Release, str] | None = None

        self.sig = _Signals()
        self.sig.result.connect(self._on_result)
        self.sig.done.connect(self._on_done)
        self.sig.update_available.connect(self._update_available)
        self.sig.update_ready.connect(self._update_ready)

        self._import_legacy_numbers()

        theme.apply(app, store.setting("theme"))
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._system_theme_changed)
        except AttributeError:
            pass

        self.window = MainWindow(self)
        self._build_tray()

        self.timer = QTimer(self, interval=TICK_MS, timeout=self.check)
        self.timer.start()
        self.update_timer = QTimer(self, interval=UPDATE_CHECK_MS, timeout=self.check_for_update)
        self.update_timer.start()
        self.window.refresh()
        self._update_status()

    def start(self, just_updated: bool = False) -> None:
        QTimer.singleShot(500, self.check)
        QTimer.singleShot(3000, self.check_for_update)
        if just_updated and self.tray:
            self.notify_target = None
            self.tray.showMessage(config.APP_NAME, f"Updated to {config.APP_NAME} {__version__}.",
                                  app_icon(), 8000)

    # ---- tray ---------------------------------------------------------------

    def _build_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(app_icon(), self)
        menu = QMenu()
        open_action = menu.addAction(f"Open {config.APP_NAME}", self.show_window)
        f = open_action.font()
        f.setBold(True)
        open_action.setFont(f)
        menu.addAction("Check now", lambda: self.check(force=True))
        self.pause_action = QAction("Pause checking", menu, checkable=True)
        self.pause_action.setChecked(bool(self.store.setting("paused")))
        self.pause_action.toggled.connect(self._set_paused)
        menu.addAction(self.pause_action)
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_activated)
        tray.messageClicked.connect(self._notification_clicked)
        tray.show()
        self._tray_menu = menu  # keep a reference
        self._tray_alert = False
        self.tray = tray

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.window.isVisible() and not self.window.isMinimized() and self.window.isActiveWindow():
                self.window.hide()
            else:
                self.show_window()

    def _notification_clicked(self) -> None:
        self.show_window()
        if self.notify_target is not None:
            self.open_details(self.notify_target)

    def _set_paused(self, paused: bool) -> None:
        self.store.set_setting("paused", paused)
        self._update_status()

    def hide_to_tray(self) -> bool:
        """Called on window close. True = we hid it instead of quitting."""
        if self.quitting or self.tray is None:
            if not self.quitting:
                self.quit()
            return False
        self.window.hide()
        if not self.store.setting("tray_hint_shown"):
            self.store.set_setting("tray_hint_shown", True)
            self.notify_target = None
            self.tray.showMessage(config.APP_NAME,
                                  "Still checking your parcels in the background. "
                                  "Right-click the tray icon to quit.",
                                  app_icon(), 8000)
        QTimer.singleShot(0, self._maybe_auto_install)
        return True

    def show_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def quit(self) -> None:
        self.quitting = True
        if self.tray:
            self.tray.hide()
        self.app.quit()

    # ---- checking -----------------------------------------------------------

    def check(self, force: bool = False, ids: set[int] | None = None) -> None:
        if self.running:
            # Run it once the current batch finishes instead of dropping it.
            if ids:
                self.queued_ids |= ids
            elif force:
                self.queued_force = True
            return
        if self.store.setting("paused") and not force and not ids:
            self._update_status()
            return
        now = datetime.now()
        shipments = self.store.shipments()
        if ids:
            batch = [s for s in shipments if s.id in ids]
        else:
            interval = timedelta(minutes=self.store.setting("interval_minutes"))
            batch = due(shipments, now, interval, self.backoff, force)
        if not batch:
            self._update_status()
            return
        self.running = True
        self.progress = (0, len(batch))
        items = [(s.id, s.carrier, s.number) for s in batch]
        threading.Thread(target=self._work, args=(items,), daemon=True).start()
        self._update_status()

    def _work(self, items: list[tuple[int, str, str]]) -> None:
        """Background thread: network only, results go back via signals."""
        failed: set[str] = set()
        for sid, carrier, number in items:
            if carrier in failed:
                self.sig.result.emit(FetchResult(sid, carrier, skipped=True))
                continue
            r = fetch(sid, carrier, number)
            if r.error:
                failed.add(carrier)
            self.sig.result.emit(r)
        self.sig.done.emit()

    def _on_result(self, r: FetchResult) -> None:
        now = datetime.now()
        if r.error:
            self.backoff.failed(r.carrier, now)
        elif not r.skipped:
            self.backoff.succeeded(r.carrier)
        change = apply_result(self.store, r, now)
        if change:
            self.pending.append(change)
        done, total = self.progress
        self.progress = (done + 1, total)
        self._shipment_changed(r.shipment_id)
        self._update_status()

    def _on_done(self) -> None:
        self.running = False
        changes, self.pending = self.pending, []
        self.window.refresh()  # re-sort once per batch
        self._notify(changes)
        self._update_tray()
        if self.queued_force:
            self.queued_force = False
            self.queued_ids.clear()  # a full check covers them
            self.check(force=True)
        elif self.queued_ids:
            ids, self.queued_ids = self.queued_ids, set()
            self.check(ids=ids)
        self._update_status()
        self._maybe_auto_install()

    def _shipment_changed(self, sid: int) -> None:
        s = self.store.get(sid)
        if s is None:
            self.window.refresh()
            return
        self.window.update_shipment(s)
        dlg = self.details.get(sid)
        if dlg:
            dlg.update_from(s)

    # ---- notifications ------------------------------------------------------

    def _notify(self, changes: list[Change]) -> None:
        if self.tray is None:
            return
        if self.store.setting("notify") == "milestones":
            changes = [c for c in changes if c.is_milestone]
        if not changes:
            return
        if len(changes) == 1:
            c = changes[0]
            s, e = c.shipment, c.event
            title = f"{s.display_name} · {s.carrier_name}"
            prefix = f"⚠ {s.stage.label}: " if s.stage and s.stage.is_problem else ""
            when = f"\n{clock(e.when)}" if e.when else ""
            message = f"{prefix}{e.description}{when}"
            self.notify_target = s.id
        else:
            title = f"{len(changes)} parcels updated"
            lines = [f"{c.shipment.display_name}: {c.event.description}" for c in changes[:4]]
            if len(changes) > 4:
                lines.append(f"…and {len(changes) - 4} more")
            message = "\n".join(lines)
            self.notify_target = None
        self.tray.showMessage(title, message, app_icon(), 15000)

    def _update_tray(self) -> None:
        if self.tray is None:
            return
        now = datetime.now()
        cats = [s.category(now) for s in self.store.shipments()]
        active, problems = cats.count(ACTIVE), cats.count(PROBLEMS)
        tip = f"{config.APP_NAME}: {active} on the way"
        if problems:
            tip += f", {problems} need attention"
        if tip != self.tray.toolTip():
            self.tray.setToolTip(tip)
        alert = problems > 0
        if alert != self._tray_alert:
            self._tray_alert = alert
            self.tray.setIcon(app_icon(alert=alert))

    def _update_status(self) -> None:
        if self.running:
            done, total = self.progress
            text = f"Checking… {done} of {total}"
        elif self.store.setting("paused"):
            text = "Paused. Parcels aren't being checked."
        else:
            now = datetime.now()
            interval = timedelta(minutes=self.store.setting("interval_minutes"))
            to_check = [s for s in self.store.shipments() if s.wants_checking(now)]
            checked = [s.last_checked_at for s in to_check if s.last_checked_at]
            if not to_check:
                text = "Nothing to check right now."
            elif checked:
                nxt = max(min(checked) + interval, now)
                text = f"Last checked {clock(max(checked))} · next check {clock(nxt)}"
            else:
                text = "Waiting to check…"
            blocked = [(CARRIERS[c].NAME, self.backoff.blocked_until(c, now)) for c in CARRIERS]
            blocked = [(n, t) for n, t in blocked if t]
            if blocked:
                text += " · " + ", ".join(f"{n} unreachable, retrying {clock(t)}" for n, t in blocked)
        self.window.set_status(text, self.running)
        self._update_tray()

    # ---- shipment actions ---------------------------------------------------

    def open_details(self, sid: int) -> None:
        dlg = self.details.get(sid)
        if dlg is None:
            s = self.store.get(sid)
            if s is None:
                return
            dlg = DetailsDialog(s, self.window)
            dlg.setAttribute(Qt.WA_DeleteOnClose)
            dlg.action.connect(self.shipment_action)
            dlg.finished.connect(lambda _=0, i=sid: self.details.pop(i, None))
            self.details[sid] = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def shipment_action(self, action: str, sid: int) -> None:
        s = self.store.get(sid)
        if s is None:
            return
        parent = self.details.get(sid) or self.window
        if action == "open":
            self.open_details(sid)
        elif action == "check":
            self.check(ids={sid})
        elif action == "copy":
            QGuiApplication.clipboard().setText(s.number)
            self.window.flash(f"Copied {s.number}.", seconds=3)
        elif action == "website":
            url = s.carrier_module.public_url(s.number)
            if s.number not in url:
                QGuiApplication.clipboard().setText(s.number)
                self.window.flash(f"Copied {s.number}. Paste it into {s.carrier_name}'s tracking page.")
            self.window.open_url(url)
        elif action == "rename":
            text, ok = QInputDialog.getText(parent, "Rename parcel",
                                            f"Nickname for {s.number} (leave empty to show the number):",
                                            text=s.nickname)
            if ok:
                self.store.rename(sid, text)
                self._shipment_changed(sid)
        elif action == "remove":
            answer = QMessageBox.question(parent, "Remove parcel",
                                          f"Stop tracking {s.display_name}?\nIts history will be deleted.")
            if answer == QMessageBox.Yes:
                self.store.remove(sid)
                dlg = self.details.pop(sid, None)
                if dlg:
                    dlg.close()
                self.window.refresh()
                self._update_status()

    # ---- settings & misc ----------------------------------------------------

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.store, self.window)
        if dlg.exec():
            dlg.save()
            self._apply_theme()
            self._update_status()

    def _apply_theme(self) -> None:
        theme.apply(self.app, self.store.setting("theme"))
        self.window.refresh(rebuild=True)
        for sid, dlg in self.details.items():
            s = self.store.get(sid)
            if s:
                dlg.update_from(s)

    def _system_theme_changed(self, *_):
        if self.store.setting("theme") == "system":
            self._apply_theme()

    # ---- updates ------------------------------------------------------------

    def check_for_update(self) -> None:
        if (self.updating or self.ready_update or not config.GITHUB_REPO
                or not self.store.setting("check_updates")):
            return
        self.updating = True
        threading.Thread(target=self._update_work, daemon=True).start()

    def _update_work(self) -> None:
        """Background thread: find, download and verify a newer release."""
        try:
            release = updates.latest_release()
            if release is None:
                return
            if updates.can_self_update(release):
                try:
                    path = updates.download(release)
                except Exception:  # noqa: BLE001 - fall back to the download link
                    self.sig.update_available.emit(release)
                    return
                self.sig.update_ready.emit(release, str(path))
            else:
                self.sig.update_available.emit(release)
        except Exception:  # noqa: BLE001 - update checks must never break the app
            pass
        finally:
            self.updating = False

    def _update_available(self, release: updates.Release) -> None:
        self.window.show_update(release.version, release.page_url)

    def _update_ready(self, release: updates.Release, path: str) -> None:
        self.ready_update = (release, path)
        self.window.show_update_ready(release.version, release.page_url)
        if self.store.setting("auto_update"):
            self._maybe_auto_install()
        elif self.tray:
            self.notify_target = None
            self.tray.showMessage(config.APP_NAME,
                                  f"Version {release.version} is ready. Open {config.APP_NAME} "
                                  "and click \"Restart to update\".", app_icon(), 10000)

    def _maybe_auto_install(self) -> None:
        """With automatic updates on, install while you're not using the window."""
        if (self.ready_update and self.store.setting("auto_update")
                and not self.running and not self.window.isVisible()):
            self.install_update()

    def install_update(self) -> None:
        if not self.ready_update:
            return
        release, path = self.ready_update
        args = ["--updated"] + ([] if self.window.isVisible() else ["--minimized"])
        try:
            updates.install(Path(path), args=args)
        except Exception:  # noqa: BLE001 - keep running the current version
            self.ready_update = None
            self.window.show_update(release.version, release.page_url)
            self.window.flash("Couldn't install the update. You can download it from the "
                              "release page instead.", error=True)
            return
        self.quit()

    def _import_legacy_numbers(self) -> None:
        """One-time import of tracking_numbers.txt from the old console version."""
        if self.store.setting("legacy_imported"):
            return
        self.store.set_setting("legacy_imported", True)
        path = config.app_dir() / "tracking_numbers.txt"
        if not path.exists():
            return
        for carrier, number in parse_numbers_file(path.read_text(encoding="utf-8")):
            try:
                self.store.add(carrier, number)
            except Exception:  # noqa: BLE001 - duplicates etc.
                pass
