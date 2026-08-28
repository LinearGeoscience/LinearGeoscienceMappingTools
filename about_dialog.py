# -*- coding: utf-8 -*-
"""About dialog: plugin version, build stamp, and environment info."""

from qgis.core import Qgis
from qgis.PyQt.QtCore import Qt, QT_VERSION_STR
from qgis.PyQt.QtGui import QCursor
from qgis.PyQt.QtWidgets import (
    QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout,
)

from . import plugin_theme as theme
from . import version_info
from .ui_scaling import get_scale_manager


class AboutDialog(QDialog):
    """Shows the plugin version, the auto-generated build stamp (commit,
    branch, date), and the running QGIS/Qt versions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        info = version_info.get_version_info()
        scale = get_scale_manager()

        self.setWindowTitle("About " + info.name)
        self.setStyleSheet(theme.info_dialog_style())
        self.setMinimumWidth(scale.dimension(420))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*scale.margins(20, 20, 20, 20))
        layout.setSpacing(scale.spacing(12))

        title = QLabel(info.name)
        title.setStyleSheet(theme.page_header_style())
        layout.addWidget(title)

        subtitle = QLabel("Version " + version_info.short_version_string())
        subtitle.setStyleSheet(theme.section_label_style())
        layout.addWidget(subtitle)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setStyleSheet(theme.separator_style())
        layout.addWidget(sep)

        grid = QGridLayout()
        grid.setHorizontalSpacing(scale.spacing(16))
        grid.setVerticalSpacing(scale.spacing(6))
        for row, (key, value) in enumerate(self._detail_rows(info)):
            key_label = QLabel(key)
            key_label.setStyleSheet(theme.section_label_style())
            value_label = QLabel(value)
            value_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            grid.addWidget(key_label, row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value_label, row, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Plain)
        sep2.setStyleSheet(theme.separator_style())
        layout.addWidget(sep2)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_copy = QPushButton("Copy Info")
        btn_copy.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_copy.setStyleSheet(theme.action_button_style(primary=False))
        btn_copy.setMinimumHeight(scale.dimension(34))
        btn_copy.clicked.connect(self._copy_info)
        btn_row.addWidget(btn_copy)

        btn_close = QPushButton("Close")
        btn_close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_close.setStyleSheet(theme.action_button_style(primary=True))
        btn_close.setMinimumHeight(scale.dimension(34))
        btn_close.setFixedWidth(scale.dimension(100))
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)

        layout.addLayout(btn_row)

    @staticmethod
    def _detail_rows(info):
        rows = [
            ("Version", info.version),
            ("Build", info.commit or "unknown"),
            ("Branch", info.branch or "unknown"),
            ("Commit date", info.date or "unknown"),
            ("Commits", str(info.commit_count) if info.commit_count else "unknown"),
            ("Author", info.author),
            ("QGIS", Qgis.QGIS_VERSION),
            ("Qt", QT_VERSION_STR),
        ]
        return rows

    def _copy_info(self):
        info = version_info.get_version_info()
        lines = [info.name]
        lines += ["%s: %s" % (k, v) for k, v in self._detail_rows(info)]
        if info.commit_full:
            lines.append("Commit (full): %s" % info.commit_full)
        QApplication.clipboard().setText("\n".join(lines))
