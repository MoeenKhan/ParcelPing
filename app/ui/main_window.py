"""Main window: add box, Active / Delivered / Problems tabs, card list, footer."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..core.carriers import CARRIERS, candidates, detect, split_numbers
from ..core.store import ACTIVE, DELIVERED, PROBLEMS, DuplicateShipment, Shipment
from .icon import app_icon
from .widgets import Badge, PasteLineEdit, ShipmentCard

if TYPE_CHECKING:
    from .controller import Controller

TABS = [(ACTIVE, "Active"), (DELIVERED, "Delivered"), (PROBLEMS, "Problems")]
EMPTY_TEXT = {
    ACTIVE: "No parcels on the way.\nPaste a tracking number above to start.",
    DELIVERED: "Delivered parcels move here {days} days after delivery.",
    PROBLEMS: "No problems. Failed deliveries and returns show up here.",
}


def _sort_key(s: Shipment):
    latest = s.latest.when if s.latest and s.latest.when else None
    # Never-checked first, then most recently updated.
    return (s.last_checked_at is not None, -(latest.timestamp() if latest else 0))


class MainWindow(QMainWindow):
    def __init__(self, controller: Controller):
        super().__init__()
        self.c = controller
        self.cards: dict[int, ShipmentCard] = {}  # cards in the current tab
        self._categories: dict[int, str] = {}  # every parcel's tab at last refresh
        self._stale = False  # a refresh was skipped while hidden
        self._stale_rebuild = False
        self.setWindowTitle(config.APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(540, 700)
        self.setMinimumSize(420, 480)

        # ---- add box ----
        self.input = PasteLineEdit()
        self.input.setPlaceholderText("Paste tracking number(s)…")
        self.input.setClearButtonEnabled(True)
        self.input.textChanged.connect(self._preview)
        self.input.submitted.connect(self._add)

        self.courier = QComboBox()
        self.courier.addItem("Auto-detect", None)
        for key, mod in CARRIERS.items():
            self.courier.addItem(mod.NAME, key)
        self.courier.setToolTip("Courier. Auto-detect works for most numbers.")
        self.courier.currentIndexChanged.connect(self._preview)

        self.nickname = QLineEdit()
        self.nickname.setPlaceholderText("Nickname (optional), e.g. New headphones")
        self.nickname.returnPressed.connect(self._add)

        self.add_btn = QPushButton("Add", objectName="Primary")
        self.add_btn.clicked.connect(self._add)

        self.detected = Badge("", "#888888")
        self.detected.hide()

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(self.input, 1)
        row1.addWidget(self.courier)
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(self.nickname, 1)
        row2.addWidget(self.detected)
        row2.addWidget(self.add_btn)

        self.message = QLabel(objectName="Banner")
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.PlainText)
        self.message.hide()
        self._message_timer = QTimer(self, singleShot=True, timeout=self.message.hide)

        self.update_banner = QLabel(objectName="Banner")
        self.update_banner.setWordWrap(True)
        self.update_banner.linkActivated.connect(self._update_link)
        self.update_banner.hide()

        # ---- tabs + list ----
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        for _, label in TABS:
            self.tabs.addTab(label)
        self.tabs.currentChanged.connect(lambda _: self.refresh())

        self.list_host = QWidget(objectName="CardList")
        self.list = QVBoxLayout(self.list_host)
        self.list.setContentsMargins(0, 4, 4, 4)
        self.list.setSpacing(10)
        self.empty = QLabel(objectName="Empty")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.list_host)

        # ---- footer ----
        self.status = QLabel(objectName="Muted")
        self.status.setTextFormat(Qt.PlainText)
        self.check_btn = QPushButton("Check now", objectName="Flat")
        self.check_btn.clicked.connect(lambda: self.c.check(force=True))
        settings_btn = QPushButton("Settings", objectName="Flat")
        settings_btn.clicked.connect(self.c.open_settings)
        footer = QFrame(objectName="Footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(0, 8, 0, 0)
        fl.addWidget(self.status, 1)
        fl.addWidget(self.check_btn)
        fl.addWidget(settings_btn)

        page = QWidget(objectName="Page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 16, 18, 12)
        lay.setSpacing(10)
        lay.addLayout(row1)
        lay.addLayout(row2)
        lay.addWidget(self.message)
        lay.addWidget(self.update_banner)
        lay.addSpacing(4)
        lay.addWidget(self.tabs)
        lay.addWidget(scroll, 1)
        lay.addWidget(footer)
        self.setCentralWidget(page)

        # Keep "2h ago" labels fresh.
        QTimer(self, interval=60_000, timeout=self.refresh).start()

    # ---- list ---------------------------------------------------------------

    def current_category(self) -> str:
        return TABS[self.tabs.currentIndex()][0]

    def refresh(self, rebuild: bool = False) -> None:
        """Re-sort and redraw the current tab. Deferred while the window is hidden."""
        if not self.isVisible():
            self._stale = True
            self._stale_rebuild |= rebuild
            return
        rebuild |= self._stale_rebuild
        self._stale = self._stale_rebuild = False

        now = datetime.now()
        shipments = self.c.store.shipments()
        by_cat: dict[str, list[Shipment]] = {k: [] for k, _ in TABS}
        self._categories = {}
        for s in shipments:
            cat = s.category(now)
            by_cat[cat].append(s)
            self._categories[s.id] = cat
        for i, (key, label) in enumerate(TABS):
            n = len(by_cat[key])
            self.tabs.setTabText(i, f"{label} ({n})" if n else label)

        if rebuild:
            for card in self.cards.values():
                card.hide()
                card.deleteLater()
            self.cards.clear()

        visible = sorted(by_cat[self.current_category()], key=_sort_key)
        visible_ids = {s.id for s in visible}

        # Empty the layout (widgets stay alive), drop cards no longer shown,
        # then re-add the visible ones in order.
        while self.list.count():
            self.list.takeAt(0)
        for sid in [sid for sid in self.cards if sid not in visible_ids]:
            card = self.cards.pop(sid)
            card.hide()  # deleteLater only runs on a later event-loop pass
            card.deleteLater()

        for s in visible:
            card = self.cards.get(s.id)
            if card is None:
                card = ShipmentCard(s)
                card.clicked.connect(self.c.open_details)
                card.action.connect(self.c.shipment_action)
                self.cards[s.id] = card
            else:
                card.update_from(s, now)
            self.list.addWidget(card)
            card.show()

        if visible:
            self.empty.hide()
            self.list.addStretch(1)
        else:
            self.empty.setText(EMPTY_TEXT[self.current_category()].format(days=config.ARCHIVE_AFTER_DAYS))
            self.list.addWidget(self.empty, 1)
            self.empty.show()

    def update_shipment(self, s: Shipment) -> None:
        """One parcel changed (e.g. a check result): update just its card.

        The full re-sort waits for the end of the batch, so checking N parcels
        costs N card updates rather than N full redraws.
        """
        if not self.isVisible():
            self._stale = True
            return
        now = datetime.now()
        cat = s.category(now)
        if cat != self._categories.get(s.id):
            self.refresh()  # moved to another tab: counts and lists change
            return
        card = self.cards.get(s.id)
        if card is not None:
            card.update_from(s, now)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._stale:
            self.refresh()

    def show_category(self, key: str) -> None:
        self.tabs.setCurrentIndex([k for k, _ in TABS].index(key))

    # ---- add ----------------------------------------------------------------

    def _preview(self) -> None:
        numbers = split_numbers(self.input.text())
        forced = self.courier.currentData()
        self.nickname.setEnabled(len(numbers) <= 1)
        if not numbers:
            self.detected.hide()
            return
        self.detected.setToolTip("")
        if len(numbers) > 1:
            self.detected.set_badge(f"{len(numbers)} numbers", "#687180")
        else:
            keys = [forced] if forced else candidates(numbers[0])
            if len(keys) == 1:
                self.detected.set_badge(CARRIERS[keys[0]].NAME, CARRIERS[keys[0]].BADGE_COLOR)
            elif keys:
                self.detected.set_badge(" or ".join(CARRIERS[k].NAME for k in keys), "#687180")
                self.detected.setToolTip("These couriers use the same number format. PingParcel checks "
                                         "which one has the parcel.")
            else:
                self.detected.set_badge("Courier?", "#C93C3C")
                self.detected.setToolTip("Couldn't recognise this number. Pick the courier from the list.")
        self.detected.show()

    def _add(self) -> None:
        numbers = split_numbers(self.input.text())
        if not numbers:
            self.input.setFocus()
            return
        forced = self.courier.currentData()
        nickname = self.nickname.text() if len(numbers) == 1 else ""
        added: list[Shipment] = []
        problems: list[str] = []
        for n in numbers:
            key = forced or detect(n)
            if key is None:
                problems.append(f"Couldn't tell which courier {n} is. Pick one from the list and add it again.")
                continue
            try:
                added.append(self.c.store.add(key, n, nickname))
            except DuplicateShipment:
                problems.append(f"You're already tracking {n}.")

        if added:
            self.input.clear()
            self.nickname.clear()
            self.courier.setCurrentIndex(0)
            self.show_category(ACTIVE)
            self.c.check(ids={s.id for s in added})
        self.refresh()
        if problems:
            self.flash("\n".join(problems), error=True)
        elif len(added) > 1:
            self.flash(f"Added {len(added)} parcels.")

    # ---- messages -----------------------------------------------------------

    def flash(self, text: str, error: bool = False, seconds: int = 6) -> None:
        self.message.setText(text)
        self.message.setObjectName("BannerError" if error else "Banner")
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self.message.show()
        self._message_timer.start(seconds * 1000)

    def show_update(self, version: str, url: str) -> None:
        self.update_banner.setText(f'Version {version} is available. <a href="{url}">Download</a>')
        self.update_banner.show()

    def show_update_ready(self, version: str, url: str) -> None:
        self.update_banner.setText(f'Version {version} is ready. <a href="install">Restart to update</a>'
                                   f' · <a href="{url}">What\'s new</a>')
        self.update_banner.show()

    def _update_link(self, href: str) -> None:
        if href == "install":
            self.c.install_update()
        else:
            self.open_url(href)

    def set_status(self, text: str, checking: bool) -> None:
        self.status.setText(text)
        self.check_btn.setEnabled(not checking)

    # ---- window behaviour ---------------------------------------------------

    def closeEvent(self, event) -> None:
        if self.c.hide_to_tray():
            event.ignore()
        else:
            event.accept()

    def open_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))
