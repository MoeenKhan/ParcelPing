"""Settings dialog."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .. import __version__, autostart, config
from ..core.store import Store

INTERVALS = [5, 10, 15, 30, 60]
NOTIFY = [("all", "Every update"), ("milestones", "Major steps only")]
THEMES = [("system", "Same as Windows"), ("light", "Light"), ("dark", "Dark")]


class SettingsDialog(QDialog):
    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Settings")
        self.setMinimumWidth(440)

        self.interval = QComboBox()
        for m in INTERVALS:
            self.interval.addItem(f"Every {m} minutes" if m < 60 else "Every hour", m)
        self._select(self.interval, store.setting("interval_minutes"))

        self.notify = QComboBox()
        for key, label in NOTIFY:
            self.notify.addItem(label, key)
        self._select(self.notify, store.setting("notify"))
        notify_hint = QLabel("Major steps: a parcel reaches a new step (like out for delivery or "
                             "delivered) or runs into a problem.", objectName="Muted")
        notify_hint.setWordWrap(True)

        self.theme = QComboBox()
        for key, label in THEMES:
            self.theme.addItem(label, key)
        self._select(self.theme, store.setting("theme"))

        self.autostart = QCheckBox("Start when I sign in to Windows")
        self.autostart.setChecked(autostart.is_enabled())
        self.autostart.setVisible(sys.platform == "win32")

        self.updates = QCheckBox("Tell me when a new version is available")
        self.updates.setChecked(bool(store.setting("check_updates")))
        self.updates.setVisible(bool(config.GITHUB_REPO))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.addRow("Check parcels", self.interval)
        form.addRow("Notify me about", self.notify)
        form.addRow("", notify_hint)
        form.addRow("Theme", self.theme)
        form.addRow("", self.autostart)
        form.addRow("", self.updates)

        data = config.data_dir()
        data_row = QHBoxLayout()
        data_label = QLabel(objectName="Muted")
        data_label.setText(data_label.fontMetrics().elidedText(str(data), Qt.ElideMiddle, 250))
        data_label.setToolTip(str(data))
        open_btn = QPushButton("Open", objectName="Flat")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data))))
        data_row.addWidget(data_label, 1)
        data_row.addWidget(open_btn)
        form.addRow("Data folder", data_row)

        about = QLabel(f"{config.APP_NAME} {__version__} · GPL-3.0"
                       + (" · portable" if config.is_portable() else ""), objectName="Muted")
        about.setToolTip("Free software: you can share and modify it under the GNU GPL v3.")

        save = QPushButton("Save", objectName="Primary")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(about)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(16)
        lay.addLayout(form)
        lay.addStretch(1)
        lay.addLayout(buttons)

    @staticmethod
    def _select(combo: QComboBox, value) -> None:
        i = combo.findData(value)
        if i >= 0:
            combo.setCurrentIndex(i)

    def save(self) -> None:
        s = self.store
        s.set_setting("interval_minutes", self.interval.currentData())
        s.set_setting("notify", self.notify.currentData())
        s.set_setting("theme", self.theme.currentData())
        s.set_setting("check_updates", self.updates.isChecked())
        if sys.platform == "win32" and self.autostart.isChecked() != autostart.is_enabled():
            autostart.set_enabled(self.autostart.isChecked())
