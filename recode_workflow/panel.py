"""
Recode & Restyle Workflow Wizard – sidebar + QStackedWidget layout.

Three-page wizard combining Update Tables, Plot Symbols, and Remove Unused Symbology.
All colours use plugin_theme, all dimensions use ui_scaling.
"""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QStackedWidget, QButtonGroup,
    QFrame, QTextEdit, QProgressBar,
)
from qgis.PyQt.QtGui import QCursor

from .widgets import CollapsibleSection, StepButton

try:
    from ..ui_scaling import get_scale_manager
except ImportError:
    from ui_scaling import get_scale_manager

try:
    from .. import plugin_theme as theme
except ImportError:
    import plugin_theme as theme

from .constants import PAGE_UPDATE_TABLES, PAGE_PLOT_SYMBOLS, PAGE_REMOVE_UNUSED, PAGE_INFO
from .update_tables import UpdateTablesPage
from .plot_symbols import PlotSymbolsPage
from .remove_unused import RemoveUnusedPage


class RecodeWorkflowWizard(QDialog):
    """Non-modal Recode & Restyle workflow wizard with sidebar navigation."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._setup_ui()

    # ─── main layout ──────────────────────────────────────────────

    def _setup_ui(self):
        s = get_scale_manager()

        self.setWindowTitle("Recode & Restyle Wizard")
        w, h = s.dialog_size(1000, 700)
        self.setMinimumSize(w, h)
        self.setStyleSheet(theme.dialog_style())
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left: sidebar
        root.addWidget(self._create_sidebar())

        # Right: content
        right = QWidget()
        right.setStyleSheet(theme.content_area_style())
        rl = QVBoxLayout(right)
        m = s.margins(16, 16, 12, 16)
        rl.setContentsMargins(*m)
        rl.setSpacing(s.dimension(8))

        # Page title / subtitle
        self._page_title = QLabel()
        self._page_title.setStyleSheet(theme.page_header_style())
        rl.addWidget(self._page_title)

        self._page_subtitle = QLabel()
        self._page_subtitle.setWordWrap(True)
        self._page_subtitle.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {s.font_size(11)}px; "
            f"font-family: {theme.FONT_FAMILY}; padding: 0;"
        )
        rl.addWidget(self._page_subtitle)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(theme.separator_style())
        rl.addWidget(sep)

        # Page stack
        self._stack = QStackedWidget()
        self._page_update = UpdateTablesPage(self.iface, self)
        self._page_plot = PlotSymbolsPage(self.iface, self)
        self._page_remove = RemoveUnusedPage(self.iface, self)

        self._stack.addWidget(self._page_update)
        self._stack.addWidget(self._page_plot)
        self._stack.addWidget(self._page_remove)
        rl.addWidget(self._stack, 1)

        # Connect page signals
        for page in (self._page_update, self._page_plot, self._page_remove):
            page.log_message.connect(self._append_log)
            page.status_changed.connect(self._on_page_status)

        # Collapsible processing log
        self._log_section = CollapsibleSection("Processing Log", expanded=False)
        self._log_area = QTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setMaximumHeight(s.dimension(120))
        self._log_area.setStyleSheet(
            f"font-size: {s.font_size(10)}px; font-family: monospace; "
            f"background-color: {theme.BG_CARD}; border: 1px solid {theme.BORDER}; "
            f"border-radius: {s.dimension(4)}px;"
        )
        self._log_section.content_layout().addWidget(self._log_area)
        rl.addWidget(self._log_section)

        # Nav bar
        rl.addLayout(self._create_nav_bar())

        root.addWidget(right, 1)

        # Initial page
        self._go_to_page(PAGE_UPDATE_TABLES)

    # ─── sidebar ──────────────────────────────────────────────────

    def _create_sidebar(self):
        s = get_scale_manager()

        scroll = QScrollArea()
        scroll.setMinimumWidth(s.dimension(220))
        scroll.setMaximumWidth(s.dimension(260))
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(theme.sidebar_style() + "\n" + theme.scrollbar_style())

        sidebar = QWidget()
        lay = QVBoxLayout(sidebar)
        m = s.margins(8, 8, 8, 8)
        lay.setContentsMargins(*m)
        lay.setSpacing(s.dimension(4))
        scroll.setWidget(sidebar)

        # WORKFLOW
        wf = QLabel("WORKFLOW")
        wf.setStyleSheet(theme.section_label_style())
        lay.addWidget(wf)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)

        self._step_update = StepButton(1, "Update Tables",  is_workflow=True)
        self._step_plot   = StepButton(2, "Plot Symbols",   is_workflow=True)
        self._step_remove = StepButton(3, "Remove Unused",  is_workflow=True)

        for idx, btn in enumerate([self._step_update, self._step_plot, self._step_remove]):
            self._nav_group.addButton(btn, idx)
            lay.addWidget(btn)

        lay.addStretch()

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(theme.separator_style())
        lay.addWidget(sep)

        self._sidebar_status = QLabel("Ready")
        self._sidebar_status.setStyleSheet(theme.version_label_style())
        lay.addWidget(self._sidebar_status)

        self._nav_group.buttonClicked[int].connect(self._on_sidebar_clicked)
        return scroll

    # ─── nav bar ──────────────────────────────────────────────────

    def _create_nav_bar(self):
        s = get_scale_manager()
        nav = QHBoxLayout()
        nav.setSpacing(s.dimension(8))

        self._back_btn = QPushButton("\u2190 Back")
        self._back_btn.setStyleSheet(theme.action_button_style(primary=False))
        self._back_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._back_btn.setMinimumHeight(s.dimension(36))
        self._back_btn.setFixedWidth(s.dimension(100))
        self._back_btn.clicked.connect(self._on_back)

        self._next_btn = QPushButton("Next \u2192")
        self._next_btn.setStyleSheet(theme.action_button_style(primary=True))
        self._next_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._next_btn.setMinimumHeight(s.dimension(36))
        self._next_btn.setFixedWidth(s.dimension(100))
        self._next_btn.clicked.connect(self._on_next)

        nav.addWidget(self._back_btn)
        nav.addStretch()
        nav.addWidget(self._next_btn)
        return nav

    # ─── navigation helpers ───────────────────────────────────────

    def _go_to_page(self, idx):
        self._stack.setCurrentIndex(idx)
        title, subtitle = PAGE_INFO.get(idx, ("", ""))
        self._page_title.setText(title)
        self._page_subtitle.setText(subtitle)

        # Update sidebar button checked state
        btn = self._nav_group.button(idx)
        if btn:
            btn.setChecked(True)

        # Update nav button visibility
        self._back_btn.setEnabled(idx > 0)
        self._next_btn.setEnabled(idx < 2)

    def _on_sidebar_clicked(self, idx):
        self._go_to_page(idx)

    def _on_back(self):
        cur = self._stack.currentIndex()
        if cur > 0:
            self._go_to_page(cur - 1)

    def _on_next(self):
        cur = self._stack.currentIndex()
        if cur < 2:
            self._go_to_page(cur + 1)

    # ─── signals from pages ───────────────────────────────────────

    def _append_log(self, msg):
        self._log_area.append(msg)

    def _on_page_status(self, status):
        """Update sidebar step button icon based on page status."""
        sender = self.sender()
        if sender is self._page_update:
            self._step_update.set_step_status(status)
        elif sender is self._page_plot:
            self._step_plot.set_step_status(status)
        elif sender is self._page_remove:
            self._step_remove.set_step_status(status)

    # ─── public ───────────────────────────────────────────────────

    def log_message(self, msg):
        self._append_log(msg)
