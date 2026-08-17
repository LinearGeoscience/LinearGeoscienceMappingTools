"""
Shared look for the import wizard, and the two widgets it repeats.

Monochrome, 1px borders, no colour accents — same language as the mining
importer's dialog. The one place colour is allowed is the status badge, where
it carries meaning rather than decoration: a geologist scanning 140 rows of
code decisions needs "this one is fine" and "this one needs you" to separate
without reading.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtWidgets import QLabel, QTableWidget, QTableWidgetItem

try:
    from ... import plugin_theme as theme
    from ...ui_scaling import get_scale_manager
except ImportError:  # direct (non-package) execution inside QGIS
    import plugin_theme as theme
    from ui_scaling import get_scale_manager


# Badge palette. Deliberately desaturated: these sit behind text and must stay
# readable, and a table of 140 saturated rows is unreadable noise.
GOOD_BG = '#EEF6EE'
GOOD_FG = '#2E6B36'
INFO_BG = '#EEF2F7'
INFO_FG = '#3B5570'
WARN_BG = '#FCF3E3'
WARN_FG = '#8A5A12'
STOP_BG = '#FBEDED'
STOP_FG = '#8C2F2F'
MUTED_FG = theme.TEXT_SECONDARY


def wizard_style():
    return """
        QWizard, QWizardPage {{ background-color: #FFFFFF; }}
        QLabel {{ font-family: {font}; color: {text}; }}
        QGroupBox {{
            font-family: {font};
            font-weight: bold;
            color: {text};
            border: 1px solid {border_dark};
            border-radius: 2px;
            margin-top: 8px;
            padding-top: 12px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 4px;
        }}
        QPushButton {{
            font-family: {font};
            background-color: #FFFFFF;
            color: {text};
            border: 1px solid {border_dark};
            border-radius: 2px;
            padding: 5px 14px;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:pressed {{ background-color: {border}; }}
        QPushButton:disabled {{
            color: {muted};
            background-color: {bg};
        }}
        QLineEdit, QComboBox, QSpinBox {{
            font-family: {font};
            border: 1px solid {border_dark};
            border-radius: 2px;
            background-color: #FFFFFF;
            padding: 3px;
        }}
        QTableWidget, QListWidget, QTreeWidget, QPlainTextEdit,
        QTextEdit {{
            font-family: {font};
            border: 1px solid {border_dark};
            border-radius: 2px;
            background-color: #FFFFFF;
        }}
        QHeaderView::section {{
            font-family: {font};
            background-color: {bg};
            color: {muted};
            border: 0px;
            border-bottom: 1px solid {border_dark};
            padding: 4px;
        }}
        QCheckBox, QRadioButton {{ font-family: {font}; color: {text}; }}
        QTabBar::tab {{
            font-family: {font};
            background: {bg};
            border: 1px solid {border_dark};
            border-bottom: none;
            padding: 5px 12px;
        }}
        QTabBar::tab:selected {{ background: #FFFFFF; }}
        QTabWidget::pane {{ border: 1px solid {border_dark}; top: -1px; }}
        QProgressBar {{
            border: 1px solid {border_dark};
            border-radius: 2px;
            text-align: center;
            background-color: #FFFFFF;
        }}
        QProgressBar::chunk {{ background-color: {border_dark}; }}
    """.format(font=theme.FONT_FAMILY, text=theme.TEXT_PRIMARY,
               border=theme.BORDER, border_dark=theme.BORDER_DARK,
               hover=theme.HOVER, bg=theme.BG_PRIMARY, muted=theme.TEXT_SECONDARY)


def hint(text, parent=None):
    """A secondary explanatory line."""
    label = QLabel(text, parent)
    label.setWordWrap(True)
    label.setStyleSheet('color: {0}; font-family: {1};'.format(
        theme.TEXT_SECONDARY, theme.FONT_FAMILY))
    return label


def heading(text, parent=None):
    label = QLabel(text, parent)
    font = QFont()
    font.setBold(True)
    label.setFont(font)
    label.setWordWrap(True)
    return label


def badge_item(text, tone='info', tooltip=''):
    """A read-only status cell tinted by tone: good/info/warn/stop/muted."""
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    background, foreground = {
        'good': (GOOD_BG, GOOD_FG),
        'info': (INFO_BG, INFO_FG),
        'warn': (WARN_BG, WARN_FG),
        'stop': (STOP_BG, STOP_FG),
    }.get(tone, (None, MUTED_FG))
    if background:
        item.setBackground(QColor(background))
    item.setForeground(QColor(foreground))
    if tooltip:
        item.setToolTip(tooltip)
    return item


def read_only_item(text, tooltip='', muted=False):
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    if tooltip:
        item.setToolTip(tooltip)
    if muted:
        item.setForeground(QColor(MUTED_FG))
    return item


def make_table(headers, stretch_columns=()):
    """A table configured the way every table in this wizard should be."""
    from qgis.PyQt.QtWidgets import QAbstractItemView, QHeaderView

    table = QTableWidget()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    header = table.horizontalHeader()
    for index in range(len(headers)):
        mode = (QHeaderView.ResizeMode.Stretch if index in stretch_columns
                else QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(index, mode)
    scale = get_scale_manager()
    table.verticalHeader().setDefaultSectionSize(scale.dimension(26))
    return table


def scaled(width, height):
    return get_scale_manager().dialog_size(width, height)
