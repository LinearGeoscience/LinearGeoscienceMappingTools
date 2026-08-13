"""
Column-mapping dialog for delimited files.

Only shown when it is actually needed — auto-detection resolves a well-headed
export like `mga_all_stations.csv` on its own, and asking anyway would be
noise. The dialog opens when easting/northing could not be identified, when
the two candidate columns cannot be told apart by magnitude, or when the user
asks to edit a mapping by hand.

Runs on the MAIN thread, between the scan task and the import task: lgs_tasks
workers may not touch widgets.
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

try:
    from .. import plugin_theme as theme
    from .formats import delimited
except ImportError:  # direct (non-package) execution inside QGIS
    import plugin_theme as theme
    from mining_import.formats import delimited

_ROLE_ORDER = (delimited.ROLE_IGNORE, delimited.ROLE_X, delimited.ROLE_Y,
               delimited.ROLE_Z, delimited.ROLE_ID, delimited.ROLE_CODE,
               delimited.ROLE_STRING)


class ColumnMapDialog(QDialog):
    """Returns mapping / group_strings / remember via .result_mapping()."""

    def __init__(self, path, info, parent=None):
        super().__init__(parent)
        self._path = path
        self._info = info
        self._combos = []

        self.setWindowTitle("Column mapping — {0}".format(
            os.path.basename(path)))
        self.resize(760, 520)
        self.setStyleSheet(_style())

        layout = QVBoxLayout(self)

        detail = "{0} column(s), delimiter {1}, {2}".format(
            info['width'],
            'whitespace' if info['delimiter'] is None
            else repr(info['delimiter']),
            'header row detected' if info['has_header'] else 'no header row')
        header_label = QLabel(detail)
        header_label.setStyleSheet(
            "color: {0}; font-family: {1};".format(
                theme.TEXT_SECONDARY, theme.FONT_FAMILY))
        layout.addWidget(header_label)

        if info.get('en_order') is None and info['roles'].get('x') is not None:
            warn = QLabel(
                "Easting and northing could not be told apart by their "
                "magnitudes — check the preview below before importing.")
            warn.setWordWrap(True)
            warn.setStyleSheet("color: {0}; font-family: {1};".format(
                theme.TEXT_PRIMARY, theme.FONT_FAMILY))
            layout.addWidget(warn)

        # --- roles + preview ------------------------------------------------
        preview_group = QGroupBox("Columns")
        preview_layout = QVBoxLayout(preview_group)
        rows = info['rows'][:12]
        self.table = QTableWidget(len(rows) + 1, info['width'])
        self.table.verticalHeader().setVisible(False)
        labels = []
        for col in range(info['width']):
            if info['has_header'] and col < len(info['header']):
                labels.append(info['header'][col])
            else:
                labels.append("Column {0}".format(col + 1))
        self.table.setHorizontalHeaderLabels(labels)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)

        current = {v: k for k, v in info['roles'].items()}
        for col in range(info['width']):
            combo = QComboBox()
            for role in _ROLE_ORDER:
                combo.addItem(delimited.ROLE_LABELS[role], role)
            role = current.get(col, delimited.ROLE_IGNORE)
            combo.setCurrentIndex(max(combo.findData(role), 0))
            combo.currentIndexChanged.connect(self._role_changed)
            self.table.setCellWidget(0, col, combo)
            self._combos.append(combo)

        for r, row in enumerate(rows, start=1):
            for col in range(info['width']):
                value = row[col] if col < len(row) else ''
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(r, col, item)
        preview_layout.addWidget(self.table)
        layout.addWidget(preview_group, 1)

        # --- options --------------------------------------------------------
        options = QGroupBox("Options")
        options_layout = QVBoxLayout(options)
        self.group_check = QCheckBox(
            "Join rows into lines using the String column")
        self.group_check.setChecked(False)
        self.group_check.setToolTip(
            "Off by default. Station exports often carry a constant string "
            "number, and joining on it would chain every point in the file "
            "into one line.")
        self.group_check.toggled.connect(self._update_summary)
        options_layout.addWidget(self.group_check)

        self.remember_check = QCheckBox(
            "Remember this mapping for files with the same columns")
        self.remember_check.setChecked(True)
        options_layout.addWidget(self.remember_check)
        layout.addWidget(options)

        self.summary = QLabel()
        self.summary.setStyleSheet("color: {0}; font-family: {1};".format(
            theme.TEXT_SECONDARY, theme.FONT_FAMILY))
        layout.addWidget(self.summary)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._buttons = buttons

        self._update_summary()

    # --- behaviour ---------------------------------------------------------

    def _role_changed(self, *_args):
        # A role other than "ignore" may only be claimed by one column.
        sender = self.sender()
        role = sender.currentData()
        if role != delimited.ROLE_IGNORE:
            for combo in self._combos:
                if combo is not sender and combo.currentData() == role:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(
                        combo.findData(delimited.ROLE_IGNORE))
                    combo.blockSignals(False)
        self._update_summary()

    def mapping(self):
        out = {}
        for index, combo in enumerate(self._combos):
            role = combo.currentData()
            if role != delimited.ROLE_IGNORE:
                out[role] = index
        return out

    def _update_summary(self, *_args):
        mapping = self.mapping()
        missing = [r for r in (delimited.ROLE_X, delimited.ROLE_Y)
                   if r not in mapping]
        ok = not missing
        self._buttons.button(
            QDialogButtonBox.StandardButton.Ok).setEnabled(ok)
        if missing:
            self.summary.setText(
                "Set a column for {0} to continue.".format(
                    ' and '.join(delimited.ROLE_LABELS[r] for r in missing)))
            return
        rows = len(self._info['rows'])
        if self.group_check.isChecked() and delimited.ROLE_STRING in mapping:
            self.summary.setText(
                "Rows will be joined into lines wherever the String column "
                "repeats. ({0}+ rows previewed.)".format(rows))
        else:
            self.summary.setText(
                "One survey station per row. ({0}+ rows previewed.)".format(
                    rows))

    def result_mapping(self):
        return {
            'mapping': self.mapping(),
            'group_strings': (self.group_check.isChecked()
                              and delimited.ROLE_STRING in self.mapping()),
            'remember': self.remember_check.isChecked(),
            'signature': self._info['signature'],
        }


def needs_mapping(info):
    """True when auto-detection did not resolve the file on its own.

    Deliberately narrow: a well-headed export resolves completely, and asking
    anyway would make every import a two-step chore.
    """
    roles = info.get('roles') or {}
    if delimited.ROLE_X not in roles or delimited.ROLE_Y not in roles:
        return True
    # Two columns that cannot be separated by magnitude might be transposed,
    # and importing a survey into the sea is worse than one question.
    return info.get('en_order') is None


def _style():
    return """
        QDialog {{ background-color: #FFFFFF; }}
        QLabel {{ font-family: {font}; color: {text}; }}
        QGroupBox {{
            font-family: {font}; font-weight: bold; color: {text};
            border: 1px solid {border}; border-radius: 2px;
            margin-top: 8px; padding-top: 12px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin; left: 8px; padding: 0 4px;
        }}
        QPushButton {{
            font-family: {font}; background-color: #FFFFFF; color: {text};
            border: 1px solid {border}; border-radius: 2px; padding: 5px 14px;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:disabled {{ color: {secondary}; background-color: {bg}; }}
        QTableWidget, QComboBox {{
            font-family: {font}; border: 1px solid {border};
            border-radius: 2px; background-color: #FFFFFF;
        }}
        QCheckBox {{ font-family: {font}; color: {text}; }}
    """.format(font=theme.FONT_FAMILY, text=theme.TEXT_PRIMARY,
               secondary=theme.TEXT_SECONDARY, border=theme.BORDER_DARK,
               hover=theme.HOVER, bg=theme.BG_PRIMARY)
