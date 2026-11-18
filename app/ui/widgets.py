"""Reusable widgets: courier badge, progress stepper, shipment card, paste box."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.stages import PROGRESS, PROGRESS_SHORT, Stage
from ..core.store import Shipment
from . import theme

# ---- formatting -------------------------------------------------------------

def clock(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def humanize(dt: datetime | None, now: datetime | None = None) -> str:
    if dt is None:
        return ""
    now = now or datetime.now()
    secs = (now - dt).total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if dt.date() == now.date():
        return f"{int(secs // 3600)}h ago"
    days = (now.date() - dt.date()).days
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    return short_date(dt, now)


def short_date(dt: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now()
    s = f"{dt.day} {dt.strftime('%b')}"
    return s if dt.year == now.year else f"{s} {dt.year}"


def full_datetime(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return f"{dt.strftime('%a')} {short_date(dt)}, {clock(dt)}"


# ---- badge ------------------------------------------------------------------

class Badge(QLabel):
    def __init__(self, text: str, color: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.set_badge(text, color)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_badge(self, text: str, color: str) -> None:
        self.setText(text)
        c = QColor(color)
        dark = QColor(theme.current["bg"]).lightness() < 128
        fg = c.lighter(150) if dark else c.darker(110)
        self.setStyleSheet(
            f"background: rgba({c.red()},{c.green()},{c.blue()},{60 if dark else 34});"
            f"color: {fg.name()}; border-radius: 9px; padding: 2px 9px;"
            "font-size: 8.5pt; font-weight: 700;"
        )


# ---- stepper ----------------------------------------------------------------

class Stepper(QWidget):
    """Booked -> In transit -> In city -> Out -> Delivered."""

    def __init__(self, stage: Stage | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.stage = stage
        self.setMinimumHeight(38)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(320, 38)

    def set_stage(self, stage: Stage | None) -> None:
        self.stage = stage
        self.update()

    def paintEvent(self, _event) -> None:
        t = theme.current
        idx = PROGRESS.index(self.stage) if self.stage in PROGRESS else -1
        n = len(PROGRESS)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        margin = 26.0
        w = self.width() - 2 * margin
        y = 9.0
        xs = [margin + w * i / (n - 1) for i in range(n)]
        accent, faint = QColor(t["accent"]), QColor(t["faint"])

        for i in range(n - 1):
            p.setPen(QPen(accent if i < idx else faint, 3, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(xs[i], y), QPointF(xs[i + 1], y))

        for i, x in enumerate(xs):
            if i < idx or (i == idx and self.stage is Stage.DELIVERED):
                p.setPen(Qt.NoPen)
                p.setBrush(accent)
                p.drawEllipse(QPointF(x, y), 5.5, 5.5)
            elif i == idx:
                p.setPen(QPen(accent, 3))
                p.setBrush(QColor(t["surface"]))
                p.drawEllipse(QPointF(x, y), 6.5, 6.5)
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(faint)
                p.drawEllipse(QPointF(x, y), 4.5, 4.5)

        f = QFont(self.font())
        f.setPointSizeF(8)
        for i, x in enumerate(xs):
            f.setBold(i == idx)
            p.setFont(f)
            p.setPen(QColor(t["text"] if i == idx else t["muted"]))
            p.drawText(QRectF(x - 40, y + 10, 80, 16), Qt.AlignHCenter | Qt.AlignTop, PROGRESS_SHORT[i])
        p.end()


# ---- shipment card ----------------------------------------------------------

class ShipmentCard(QFrame):
    clicked = Signal(int)
    action = Signal(str, int)  # (action, shipment id): rename, copy, website, remove, check

    def __init__(self, shipment: Shipment, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        self.shipment_id = shipment.id

        self.title = QLabel(objectName="Title")
        self.title.setTextFormat(Qt.PlainText)
        self.badge = Badge("", "#888888")
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        self.when = QLabel(objectName="Muted")
        self.stepper = Stepper()
        self.error = QLabel(objectName="Error")
        self.error.setTextFormat(Qt.PlainText)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.title, 1)
        top.addWidget(self.badge)
        mid = QHBoxLayout()
        mid.setSpacing(8)
        mid.addWidget(self.status, 1)
        mid.addWidget(self.when, 0, Qt.AlignTop)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 10)
        lay.setSpacing(6)
        lay.addLayout(top)
        lay.addLayout(mid)
        lay.addWidget(self.stepper)
        lay.addWidget(self.error)
        self.update_from(shipment)

    def update_from(self, s: Shipment, now: datetime | None = None) -> None:
        now = now or datetime.now()
        self.title.setText(s.display_name)
        self.title.setToolTip(s.number if s.nickname else "")
        self.badge.set_badge(s.carrier_name, s.carrier_module.BADGE_COLOR)

        latest, stage = s.latest, s.stage
        problem = stage is not None and stage.is_problem
        if latest is None:
            self.status.setText("Waiting for the first update from the courier"
                                if s.last_checked_at else "Checking…")
            self.status.setObjectName("Muted")
        else:
            text = latest.description
            if problem:
                text = f"⚠  {stage.label}: {latest.description}"
            self.status.setText(text)
            self.status.setObjectName("ProblemText" if problem else "")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

        self.when.setText(humanize(latest.when if latest else None, now))
        self.when.setToolTip(full_datetime(latest.when) if latest else "")
        self.stepper.set_stage(stage)
        self.stepper.setVisible(stage is not None and not problem)
        self.error.setText(s.last_error)
        self.error.setVisible(bool(s.last_error))

        if self.property("problem") != problem:
            self.setProperty("problem", problem)
            self.style().unpolish(self)
            self.style().polish(self)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.shipment_id)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        items = [
            ("Open details", "open"),
            ("Check now", "check"),
            None,
            ("Rename…", "rename"),
            ("Copy tracking number", "copy"),
            ("Open on courier website", "website"),
            None,
            ("Remove", "remove"),
        ]
        for item in items:
            if item is None:
                menu.addSeparator()
                continue
            label, key = item
            menu.addAction(label, lambda k=key: self.action.emit(k, self.shipment_id))
        menu.exec(event.globalPos())


# ---- paste box --------------------------------------------------------------

class PasteLineEdit(QLineEdit):
    """Line edit that keeps multi-line pastes (one number per line) intact."""

    submitted = Signal()

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.Paste):
            text = QGuiApplication.clipboard().text()
            self.insert(" ".join(text.split()))
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.submitted.emit()
            return
        super().keyPressEvent(event)
