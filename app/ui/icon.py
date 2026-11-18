"""App icon, drawn in code so there are no binary assets to keep in sync."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

ACCENT = QColor("#0E8F6A")
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render(size: int, alert: bool = False) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 64.0

    # Rounded tile
    p.setPen(Qt.NoPen)
    p.setBrush(ACCENT)
    p.drawRoundedRect(QRectF(2 * s, 2 * s, 60 * s, 60 * s), 14 * s, 14 * s)

    # Parcel: isometric box outline
    pen = QPen(QColor("white"), max(1.2, 3.6 * s), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    top, mid_y, bottom = 15 * s, 25 * s, 50 * s
    left, cx, right = 14 * s, 32 * s, 50 * s
    box = QPainterPath()
    box.moveTo(cx, top)
    box.lineTo(right, mid_y - 3 * s)
    box.lineTo(right, bottom - 10 * s)
    box.lineTo(cx, bottom)
    box.lineTo(left, bottom - 10 * s)
    box.lineTo(left, mid_y - 3 * s)
    box.closeSubpath()
    p.drawPath(box)
    p.drawLine(QPointF(left, mid_y - 3 * s), QPointF(cx, mid_y + 6 * s))
    p.drawLine(QPointF(right, mid_y - 3 * s), QPointF(cx, mid_y + 6 * s))
    p.drawLine(QPointF(cx, mid_y + 6 * s), QPointF(cx, bottom))

    # Ping dot (red when a parcel needs attention)
    p.setPen(QPen(ACCENT, 3 * s))
    p.setBrush(QColor("#E5484D") if alert else QColor("#FFD166"))
    p.drawEllipse(QPointF(50 * s, 14 * s), 9 * s, 9 * s)
    p.end()
    return pm


def app_icon(alert: bool = False) -> QIcon:
    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(render(size, alert))
    return icon
