"""Shipment detail view: full timeline plus actions."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..core.carriers.base import TrackingEvent
from ..core.store import Shipment
from . import theme
from .widgets import Badge, Stepper, clock, full_datetime


class _Dot(QWidget):
    def __init__(self, first: bool, last: bool, color: str):
        super().__init__()
        self.first, self.last, self.color = first, last, color
        self.setFixedWidth(22)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, 12
        p.setPen(QColor(theme.current["faint"]))
        if not self.last:
            p.drawLine(int(cx), cy, int(cx), self.height())
        if not self.first:
            p.drawLine(int(cx), 0, int(cx), cy)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.color))
        r = 6 if self.first else 4
        p.drawEllipse(int(cx - r), cy - r, 2 * r, 2 * r)
        p.end()


def _event_row(e: TrackingEvent, first: bool, last: bool) -> QWidget:
    t = theme.current
    color = t["danger"] if e.stage.is_problem else (t["accent"] if first else t["faint"])
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    lay.addWidget(_Dot(first, last, color))
    text = QVBoxLayout()
    text.setContentsMargins(0, 2, 0, 14)
    text.setSpacing(2)
    desc = QLabel(e.description)
    desc.setTextFormat(Qt.PlainText)
    desc.setWordWrap(True)
    if first:
        desc.setStyleSheet("font-weight: 600;")
    when = QLabel(full_datetime(e.when), objectName="Muted")
    text.addWidget(desc)
    text.addWidget(when)
    lay.addLayout(text, 1)
    return row


class DetailsDialog(QDialog):
    action = Signal(str, int)  # rename, copy, website, remove, check

    def __init__(self, shipment: Shipment, parent: QWidget | None = None):
        super().__init__(parent)
        self.shipment_id = shipment.id
        self.setMinimumSize(460, 520)
        self.resize(500, 620)

        self.title = QLabel(objectName="BigTitle")
        self.title.setTextFormat(Qt.PlainText)
        self.title.setWordWrap(True)
        self.badge = Badge("", "#888888")
        self.number = QLabel(objectName="Muted")
        self.number.setTextInteractionFlags(Qt.TextSelectableByMouse)
        copy_btn = QPushButton("Copy", objectName="Flat")
        copy_btn.clicked.connect(lambda: self.action.emit("copy", self.shipment_id))

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(self.badge)
        head.addWidget(self.number)
        head.addWidget(copy_btn)
        head.addStretch(1)

        self.stage_label = QLabel(objectName="Title")
        self.stepper = Stepper()
        self.error = QLabel(objectName="BannerError")
        self.error.setWordWrap(True)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        for label, key, name in [("Check now", "check", ""), ("Rename…", "rename", ""),
                                 ("Courier website", "website", "")]:
            b = QPushButton(label, objectName=name)
            b.clicked.connect(lambda _=False, k=key: self.action.emit(k, self.shipment_id))
            buttons.addWidget(b)
        buttons.addStretch(1)
        remove = QPushButton("Remove", objectName="Danger")
        remove.clicked.connect(lambda: self.action.emit("remove", self.shipment_id))
        buttons.addWidget(remove)

        self.timeline_host = QWidget(objectName="Page")
        self.timeline = QVBoxLayout(self.timeline_host)
        self.timeline.setContentsMargins(0, 0, 8, 0)
        self.timeline.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.timeline_host)
        scroll.setFrameShape(QFrame.NoFrame)

        self.footer = QLabel(objectName="Muted")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(10)
        lay.addWidget(self.title)
        lay.addLayout(head)
        lay.addSpacing(4)
        lay.addWidget(self.stage_label)
        lay.addWidget(self.stepper)
        lay.addWidget(self.error)
        lay.addLayout(buttons)
        lay.addSpacing(6)
        lay.addWidget(QLabel("HISTORY", objectName="Section"))
        lay.addWidget(scroll, 1)
        lay.addWidget(self.footer)
        self.update_from(shipment)

    def update_from(self, s: Shipment) -> None:
        self.setWindowTitle(s.display_name)
        self.title.setText(s.display_name)
        self.badge.set_badge(s.carrier_name, s.carrier_module.BADGE_COLOR)
        self.number.setText(s.number)

        stage = s.stage
        self.stage_label.setText(stage.label if stage else "No tracking info yet")
        self.stage_label.setObjectName("ProblemText" if stage and stage.is_problem else "Title")
        self.stage_label.style().unpolish(self.stage_label)
        self.stage_label.style().polish(self.stage_label)
        self.stepper.set_stage(stage)
        self.stepper.setVisible(stage is not None and not stage.is_problem)
        self.error.setText(s.last_error)
        self.error.setVisible(bool(s.last_error))

        while self.timeline.count():
            item = self.timeline.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not s.events:
            msg = ("The courier doesn't have any tracking info for this number yet. "
                   "New bookings can take a few hours to appear.")
            empty = QLabel(msg if s.last_checked_at else "Checking…", objectName="Muted")
            empty.setWordWrap(True)
            self.timeline.addWidget(empty)
        for i, e in enumerate(s.events):
            self.timeline.addWidget(_event_row(e, i == 0, i == len(s.events) - 1))
        self.timeline.addStretch(1)

        self.footer.setText(f"Last checked {clock(s.last_checked_at)}" if s.last_checked_at else "")
