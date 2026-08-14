import os
from qgis.core import QgsSettings
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QMessageBox, QWidget, QGroupBox, QFrame, QSizePolicy, QScrollArea,
    QStackedWidget, QButtonGroup, QApplication
)
from qgis.PyQt.QtGui import (
    QIcon, QColor, QPalette, QLinearGradient, QCursor, QKeySequence,
    QAction, QShortcut
)
from qgis.PyQt.QtSvg import QSvgRenderer
try:
    # Qt6 (QGIS 4): QSvgWidget lives in QtSvgWidgets
    from qgis.PyQt.QtSvgWidgets import QSvgWidget
except ImportError:
    # Qt5 (QGIS 3.x): still in QtSvg
    from qgis.PyQt.QtSvg import QSvgWidget

# Import UI scaling system for DPI-aware interface
from .ui_scaling import get_scale_manager

# Import centralized theme
from . import plugin_theme as theme

# The stereonet and recode-workflow modules pull in matplotlib/pandas/numpy —
# the heaviest imports in the plugin. They (and the other feature modules) are
# imported lazily inside their launcher methods so plugin load (paid on every
# QGIS startup) stays cheap and the stereonet dock is only built when first
# opened. Only map_cleaning stays eager (it registers a Processing provider at
# load). feature_info is a lightweight constants module, kept eager for the
# sidebar builder.
from .map_cleaning import MapCleaningToolkit
from . import feature_info
from . import version_info

# QSettings keys
SETTINGS_PREFIX = "LinearGeoscience"
SETTING_LAST_PAGE = f"{SETTINGS_PREFIX}/lastPage"
SETTING_GEOMETRY = f"{SETTINGS_PREFIX}/dialogGeometry"


def _esc_amp(text):
    """Escape '&' as '&&' so Qt shows a literal ampersand in mnemonic-parsing widgets."""
    return text.replace("&", "&&")

# Page definitions: (nav_label, icon_file, tooltip, page_title)
PAGE_DEFS = [
    ("Set Mapping Scale", None, "Configure your mapping geopackage for QField", "Set Mapping Scale"),
    ("Field Photos", None, "Georeference, view, and export field photos", "Field Photos"),
    ("Data Management", None, "Backup, update, reproject, and merge data", "Data Management"),
    ("Declination", None, "Calculate and adjust magnetic declination", "Declination"),
    ("Structural Domains", None, "Create and classify structural domains", "Structural Domains"),
    ("Mapsheets & Layouts", None, "Create mapsheet grids and print layouts", "Mapsheets & Layouts"),
    ("Modify Symbology", None, "Re-classify coding and apply symbology", "Symbology"),
    ("Pit / Underground", None, "Filter mapping layers by bench or level elevation", "Z Filtering"),
]


class ActionButton(QPushButton):
    """Modern styled action button with consistent appearance."""

    def __init__(self, text, icon_name=None, parent=None, plugin_dir=None, primary=True):
        super().__init__(_esc_amp(text), parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._original_text = text

        scale = get_scale_manager()
        self.setMinimumHeight(scale.dimension(40))

        if icon_name and plugin_dir:
            icon_path = os.path.join(plugin_dir, "icons", icon_name)
            if os.path.exists(icon_path):
                self.setIcon(QIcon(icon_path))
                self.setIconSize(scale.icon_size(20, 20))

        self.setStyleSheet(theme.action_button_style(primary))


class BrandHeader(QWidget):
    """Modern header with logo, centered title, and subtle bottom shadow."""

    def __init__(self, plugin_dir, parent=None):
        super().__init__(parent)
        self.plugin_dir = plugin_dir
        self.scale = get_scale_manager()
        self.setMinimumHeight(self.scale.dimension(80))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.setAutoFillBackground(True)
        self._apply_gradient(self.width())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Inner content row
        content = QWidget()
        content_layout = QHBoxLayout(content)
        margins = self.scale.margins(16, 30, 16, 16)
        content_layout.setContentsMargins(margins[0], margins[3], margins[1], margins[2])
        content_layout.setSpacing(self.scale.spacing(30))

        # Logo
        self.logo_path = os.path.join(plugin_dir, "icons", "LGS_Logo_Cropped.svg")
        self.logo = None
        if os.path.exists(self.logo_path):
            self.logo = QSvgWidget(self.logo_path)
            renderer = QSvgRenderer(self.logo_path)
            original_size = renderer.defaultSize()
            height = self.scale.dimension(60)
            aspect_ratio = original_size.width() / original_size.height()
            width = int(height * aspect_ratio)
            self.logo.setFixedSize(width, height)
            content_layout.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Title
        self.title = QLabel("QField Geological Mapping Plugin")
        self.title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet(theme.header_title_style())
        content_layout.addWidget(self.title, 1)

        layout.addWidget(content, 1)

        # Bottom shadow line
        shadow_line = QFrame()
        shadow_line.setFrameShape(QFrame.Shape.HLine)
        shadow_line.setFrameShadow(QFrame.Shadow.Plain)
        shadow_line.setStyleSheet(theme.header_bottom_shadow())
        layout.addWidget(shadow_line)

    def _apply_gradient(self, width):
        palette = self.palette()
        gradient = QLinearGradient(0, 0, max(width, 1), 0)
        gradient.setColorAt(0, QColor(theme.HEADER_START))
        gradient.setColorAt(1, QColor(theme.HEADER_END))
        palette.setBrush(QPalette.ColorRole.Window, gradient)
        self.setPalette(palette)

    def resizeEvent(self, event):
        self._apply_gradient(event.size().width())

        if self.logo:
            current_width = event.size().width()
            bp_wide = self.scale.dimension(1000)
            bp_narrow = self.scale.dimension(500)
            margin = self.scale.dimension(20)

            renderer = QSvgRenderer(self.logo_path)
            aspect_ratio = renderer.defaultSize().width() / renderer.defaultSize().height()

            if current_width > bp_wide:
                h = min(self.scale.dimension(70), self.height() - margin)
            elif current_width < bp_narrow:
                h = self.scale.dimension(45)
            else:
                h = self.scale.dimension(60)
            self.logo.setFixedSize(int(h * aspect_ratio), h)

        super().resizeEvent(event)


class FeatureGroup(QGroupBox):
    """Styled feature group containing action buttons and info buttons."""

    def __init__(self, title, plugin_dir, parent=None):
        super().__init__(_esc_amp(title), parent)
        self.plugin_dir = plugin_dir
        self.scale = get_scale_manager()

        self.setStyleSheet(theme.group_box_style())

        self.group_layout = QVBoxLayout(self)
        top = self.scale.dimension(20)
        side = self.scale.dimension(16)
        self.group_layout.setContentsMargins(top, side, side, side)
        self.group_layout.setSpacing(self.scale.spacing(16))

    def addFeature(self, text, icon_name, info_text, callback):
        """Add a feature row with action button (70%) and info button (30%)."""
        row = QHBoxLayout()
        row.setSpacing(self.scale.spacing(12))

        btn_action = ActionButton(text, icon_name, self, self.plugin_dir)
        btn_action.clicked.connect(callback)
        row.addWidget(btn_action, 7)

        btn_info = ActionButton("More Info", None, self, self.plugin_dir, primary=False)
        btn_info.clicked.connect(lambda checked, t=text, c=info_text: self._show_info(t, c))
        row.addWidget(btn_info, 3)

        self.group_layout.addLayout(row)
        return btn_action

    def addSeparator(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setStyleSheet(theme.separator_style())
        self.group_layout.addWidget(line)

    def _show_info(self, title, content):
        """Show a themed info dialog."""
        dlg = QDialog(self)
        dlg.setWindowTitle(title)

        dialog_width, dialog_height = self.scale.dialog_size(600, 400)
        dlg.setMinimumSize(dialog_width, dialog_height)
        dlg.setStyleSheet(theme.info_dialog_style())

        layout = QVBoxLayout(dlg)
        margins = self.scale.margins(20, 20, 20, 20)
        layout.setContentsMargins(*margins)
        layout.setSpacing(self.scale.spacing(16))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content_widget = QWidget()
        scroll.setWidget(content_widget)

        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, self.scale.dimension(10), 0)

        info_label = QLabel(content)
        info_label.setWordWrap(True)
        info_label.setTextFormat(Qt.TextFormat.RichText)
        info_label.setOpenExternalLinks(True)
        content_layout.addWidget(info_label)
        content_layout.addStretch()

        layout.addWidget(scroll)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setStyleSheet(theme.separator_style())
        layout.addWidget(sep)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_close = ActionButton("Close", None, dlg, self.plugin_dir)
        btn_close.setFixedWidth(self.scale.dimension(100))
        btn_close.clicked.connect(dlg.close)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

        dlg.exec()


class LinearGeosciencePluginMain:
    """Main class for the combined LinearGeosciencePlugin."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.toolbar = None
        self.action_main_button = None
        self.action_about = None
        self.stereonet_core = None
        self.photo_panel = None
        self.z_filter_panel = None
        self.map_cleaning = None
        self.main_dialog = None  # non-modal dialog reference
        # Plugin-owned singletons for the tools that used to stash them on
        # iface (torn down in unload so a reload rebuilds fresh).
        self.layout_panel = None
        self.reproject_dialog = None
        self.recode_wizard = None
        self.reconcile_dialog = None
        self.mining_import_dialog = None

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------
    def initGui(self):
        # Move any legacy bare-QSettings values into the QGIS profile once.
        try:
            from .settings import migrate_qsettings_once
            migrate_qsettings_once()
        except Exception:
            pass  # settings migration is best-effort, never blocks load

        self.toolbar = self.iface.addToolBar("Linear Geoscience Mapping Tools")
        self.toolbar.setObjectName("LinearGeoscienceMappingTools")

        icon_path = os.path.join(self.plugin_dir, "icons", "icon_main.svg")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(self.plugin_dir, "icons", "default_icon.svg")

        self.action_main_button = QAction(
            QIcon(icon_path),
            "Open Linear Geoscience Mapping Tools",
            self.iface.mainWindow()
        )
        self.action_main_button.setToolTip("Open the Linear Geoscience plugin dialog")
        self.action_main_button.triggered.connect(self.open_plugin_dialog)
        self.toolbar.addAction(self.action_main_button)

        # Add to Plugins menu (required for QGIS plugin repository)
        self.iface.addPluginToMenu("Linear Geoscience Mapping Tools", self.action_main_button)

        self.action_about = QAction("About...", self.iface.mainWindow())
        self.action_about.setToolTip("Plugin version and build information")
        self.action_about.triggered.connect(self.show_about_dialog)
        self.iface.addPluginToMenu("Linear Geoscience Mapping Tools", self.action_about)

        # The stereonet dock (+ matplotlib/pandas) is built lazily on first
        # open via _ensure_stereonet(), not at startup.
        self._stereonet_import_error = None

        # Map cleaning toolkit: adds its actions to the plugin toolbar
        self.map_cleaning = MapCleaningToolkit(self.iface)
        self.map_cleaning.initGui(toolbar=self.toolbar)

    def _ensure_stereonet(self):
        """Build the stereonet core + dock on first use. Returns the core or
        None if matplotlib/pandas are unavailable (hint already shown)."""
        if self.stereonet_core is not None:
            return self.stereonet_core
        if self._stereonet_import_error is not None:
            return None
        try:
            from .stereonet import StereonetPluginCore
        except ImportError as e:
            self._stereonet_import_error = str(e)
            return None
        core = StereonetPluginCore(self.iface)
        core.initGui()
        self.stereonet_core = core
        return core

    def unload(self):
        if self.main_dialog:
            self._save_geometry()
            self.main_dialog.close()
            # The dialog is cached across opens (no WA_DeleteOnClose), so a
            # plugin unload/reload must delete it explicitly.
            self.main_dialog.deleteLater()
            self.main_dialog = None

        if self.action_main_button:
            self.iface.removePluginMenu("Linear Geoscience Mapping Tools", self.action_main_button)
            self.action_main_button.triggered.disconnect()
            self.action_main_button = None

        if self.action_about:
            self.iface.removePluginMenu("Linear Geoscience Mapping Tools", self.action_about)
            self.action_about.triggered.disconnect()
            self.action_about = None

        if self.map_cleaning:
            try:
                self.map_cleaning.unload()
            except Exception as e:
                from qgis.core import QgsMessageLog, Qgis
                QgsMessageLog.logMessage(
                    f"Map cleaning toolkit unload failed: {e}",
                    'Linear Geoscience', Qgis.MessageLevel.Warning
                )
            self.map_cleaning = None

        if self.toolbar:
            self.iface.mainWindow().removeToolBar(self.toolbar)
            self.toolbar = None

        if self.stereonet_core:
            self.stereonet_core.unload()
            self.stereonet_core = None

        if self.photo_panel:
            try:
                # Full teardown: stops worker threads, disconnects signals
                self.photo_panel.shutdown()
            except Exception as e:
                from qgis.core import QgsMessageLog, Qgis
                QgsMessageLog.logMessage(
                    f"Photo panel shutdown failed during unload: {e}",
                    'Linear Geoscience', Qgis.MessageLevel.Warning
                )
            self.iface.removeDockWidget(self.photo_panel)
            self.photo_panel.deleteLater()
            self.photo_panel = None

        if self.z_filter_panel:
            try:
                # Disconnects project signals; applied filters stay in the
                # project (they are project state, deliberately persistent).
                self.z_filter_panel.shutdown()
            except Exception as e:
                from qgis.core import QgsMessageLog, Qgis
                QgsMessageLog.logMessage(
                    f"Z filter panel shutdown failed during unload: {e}",
                    'Linear Geoscience', Qgis.MessageLevel.Warning
                )
            self.iface.removeDockWidget(self.z_filter_panel)
            self.z_filter_panel.deleteLater()
            self.z_filter_panel = None

        # Plugin-owned singletons: tear down on unload so a reload rebuilds
        # fresh instead of re-raising a stale one. Also sweep up the old
        # iface-stashed attributes so panels created by a previous plugin
        # version are cleaned up during an in-place upgrade.
        for own_attr, iface_attr, is_dock in (
                ('layout_panel', '_layout_panel', True),
                ('reproject_dialog', '_reproject_dialog', False),
                ('recode_wizard', '_recode_wizard', False),
                ('reconcile_dialog', '_reconcile_dialog', False),
                ('mining_import_dialog', '_mining_import_dialog', False)):
            for holder, attr in ((self, own_attr),
                                 (self.iface, iface_attr)):
                widget = getattr(holder, attr, None)
                if widget is None:
                    continue
                try:
                    if is_dock:
                        self.iface.removeDockWidget(widget)
                    widget.close()
                    widget.deleteLater()
                except Exception:
                    pass  # already deleted
                try:
                    setattr(holder, attr, None)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Panel toggles
    # ------------------------------------------------------------------
    def _show_missing_dependency(self, feature_name, import_error):
        QMessageBox.warning(
            self.iface.mainWindow(),
            f"{feature_name} unavailable",
            f"{feature_name} could not be loaded because a required Python "
            f"package is missing:\n\n{import_error}\n\n"
            "Install the missing package into the QGIS Python environment "
            "(e.g. python3-matplotlib / python3-pandas via your package "
            "manager, or 'pip install matplotlib pandas'), then restart QGIS."
        )

    def toggle_stereonet_panel(self):
        core = self._ensure_stereonet()
        if core is None:
            self._show_missing_dependency(
                "Stereonet Analysis",
                self._stereonet_import_error or "matplotlib/pandas not found")
            return
        if not core.dock:
            return
        dock = core.dock
        dock.setVisible(not dock.isVisible())

    def toggle_photo_panel(self):
        if not self.photo_panel:
            from .photo_panel import run_photo_panel
            self.photo_panel = run_photo_panel(self.iface)
            if not self.photo_panel:
                return
        else:
            if self.photo_panel.isVisible():
                self.photo_panel.hide()
            else:
                self.photo_panel.show()

    def toggle_z_filter_panel(self):
        if not self.z_filter_panel:
            from .z_filter import run_z_filter_panel
            self.z_filter_panel = run_z_filter_panel(self.iface)
        else:
            if self.z_filter_panel.isVisible():
                self.z_filter_panel.hide()
            else:
                self.z_filter_panel.show()

    def run_add_elevation_field(self):
        from .z_filter import run_add_elevation_field
        run_add_elevation_field(self.iface)

    def toggle_map_cleaning_panel(self):
        # trigger() flips the checkable toolbar action and runs its toggle_panel
        # handler, keeping the toolbar button's checked state in sync
        if self.map_cleaning and self.map_cleaning.action_panel:
            self.map_cleaning.action_panel.trigger()

    # ------------------------------------------------------------------
    # Main dialog  (non-modal)
    # ------------------------------------------------------------------
    def show_about_dialog(self):
        """Show the About dialog (version, build stamp, environment)."""
        from .about_dialog import AboutDialog
        dlg = AboutDialog(self.iface.mainWindow())
        dlg.exec()

    def open_plugin_dialog(self):
        """Open or bring to front the main plugin dialog (non-modal).

        The dialog is built once and cached — closing hides it, reopening
        shows the same instance instantly with its state intact. It only
        rebuilds after a plugin reload (unload() deletes it)."""
        if self.main_dialog is not None:
            try:
                self._refresh_dialog_on_show(self.main_dialog)
                self.main_dialog.show()
                self.main_dialog.raise_()
                self.main_dialog.activateWindow()
                return
            except RuntimeError:
                # C++ object already deleted
                self.main_dialog = None

        scale = get_scale_manager()

        dialog = QDialog(self.iface.mainWindow())
        dialog.setWindowTitle("Linear Geoscience - Geological Mapping")
        dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        dialog_width, dialog_height = scale.dialog_size(800, 600)
        dialog.setStyleSheet(theme.dialog_style())

        # Main vertical layout
        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = BrandHeader(self.plugin_dir, dialog)
        main_layout.addWidget(header)

        # Horizontal: sidebar | content
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Build sidebar and content
        sidebar_scroll, nav_group = self._build_sidebar(dialog)
        content_area, stacked_widget, page_header_label = self._build_content_area()

        body.addWidget(sidebar_scroll)
        body.addWidget(content_area)
        main_layout.addLayout(body)

        # Minimum height must fit the full sidebar (incl. the template button
        # at the bottom) so it isn't hidden behind the sidebar scrollbar,
        # capped to the available screen height on small displays
        sidebar_h = sidebar_scroll.widget().sizeHint().height()
        header_h = header.sizeHint().height()
        needed_h = sidebar_h + header_h + scale.dimension(20)
        screen_h = QApplication.primaryScreen().availableGeometry().height()
        min_height = max(dialog_height, min(needed_h, screen_h - scale.dimension(80)))
        dialog.setMinimumSize(dialog_width, min_height)

        # Wire navigation
        self._connect_navigation(nav_group, stacked_widget, page_header_label)

        # Keyboard shortcuts
        self._setup_shortcuts(dialog, nav_group, stacked_widget)

        # Restore state
        self._restore_geometry(dialog)
        last_page = QgsSettings().value(SETTING_LAST_PAGE, 0, type=int)
        last_page = max(0, min(last_page, stacked_widget.count() - 1))
        nav_group.button(last_page).setChecked(True)
        stacked_widget.setCurrentIndex(last_page)
        page_header_label.setText(PAGE_DEFS[last_page][3])

        # Save geometry on close (the dialog itself is kept for reuse)
        dialog.finished.connect(lambda: self._save_geometry())

        # Store references for external access
        dialog._nav_group = nav_group
        dialog._stacked_widget = stacked_widget
        dialog._page_header = page_header_label

        self.main_dialog = dialog
        dialog.show()

    def _refresh_dialog_on_show(self, dialog):
        """Hook for state that must refresh when the cached dialog is
        re-shown. The current pages hold no layer-dependent state; any
        future page that does must repopulate itself here."""

    # ------------------------------------------------------------------
    # Sidebar builder
    # ------------------------------------------------------------------
    def _build_sidebar(self, dialog):
        """Build the sidebar scroll area with quick-access, nav buttons, version, and template button.
        Returns (sidebar_scroll, QButtonGroup).
        """
        scale = get_scale_manager()

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setMinimumWidth(scale.dimension(280))
        sidebar_scroll.setMaximumWidth(scale.dimension(350))
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sidebar_scroll.setStyleSheet(
            theme.sidebar_style() + "\n" + theme.scrollbar_style()
        )

        sidebar = QWidget()
        lay = QVBoxLayout(sidebar)
        m = scale.margins(8, 8, 8, 8)
        lay.setContentsMargins(m[0], m[1], m[2], m[3])
        lay.setSpacing(scale.spacing(4))
        sidebar_scroll.setWidget(sidebar)

        # --- Quick Access ---
        qa_label = QLabel("Quick Access")
        qa_label.setStyleSheet(theme.section_label_style())
        lay.addWidget(qa_label)

        qa_style = theme.quick_access_button_style()

        btn_stereonet = QPushButton("Launch Stereonet")
        btn_stereonet.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_stereonet.setMinimumHeight(scale.dimension(34))
        btn_stereonet.setToolTip("Open the interactive stereonet plotting panel")
        btn_stereonet.setStyleSheet(qa_style)
        btn_stereonet.clicked.connect(self.toggle_stereonet_panel)
        lay.addWidget(btn_stereonet)

        btn_map_cleaning = QPushButton("Launch Map Cleaning")
        btn_map_cleaning.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_map_cleaning.setMinimumHeight(scale.dimension(34))
        btn_map_cleaning.setToolTip("Open the map cleaning panel (clip, splines, fix geometry)")
        btn_map_cleaning.setStyleSheet(qa_style)
        btn_map_cleaning.clicked.connect(self.toggle_map_cleaning_panel)
        lay.addWidget(btn_map_cleaning)

        btn_photo = QPushButton("Launch Photo Panel")
        btn_photo.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_photo.setMinimumHeight(scale.dimension(34))
        btn_photo.setToolTip("Open the photo viewing dock panel")
        btn_photo.setStyleSheet(qa_style)
        btn_photo.clicked.connect(self.toggle_photo_panel)
        lay.addWidget(btn_photo)

        btn_zfilter = QPushButton("Launch Z Filter")
        btn_zfilter.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_zfilter.setMinimumHeight(scale.dimension(34))
        btn_zfilter.setToolTip(
            "Filter the mapping layers to one bench/level elevation")
        btn_zfilter.setStyleSheet(qa_style)
        btn_zfilter.clicked.connect(self.toggle_z_filter_panel)
        lay.addWidget(btn_zfilter)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setStyleSheet(theme.separator_style())
        sep_margin = scale.dimension(4)
        sep.setContentsMargins(0, sep_margin, 0, sep_margin)
        lay.addWidget(sep)

        # --- Navigation ---
        nav_label = QLabel("Navigation")
        nav_label.setStyleSheet(theme.section_label_style())
        lay.addWidget(nav_label)

        nav_style = theme.nav_button_style()
        nav_group = QButtonGroup(dialog)
        nav_group.setExclusive(True)

        for idx, (label, icon_file, tooltip, _title) in enumerate(PAGE_DEFS):
            btn = QPushButton(_esc_amp(label))
            btn.setCheckable(True)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            btn.setMinimumHeight(scale.dimension(36))
            btn.setToolTip(tooltip)
            btn.setStyleSheet(nav_style)
            if icon_file:
                icon_path = os.path.join(self.plugin_dir, "icons", icon_file)
                if os.path.exists(icon_path):
                    btn.setIcon(QIcon(icon_path))
            nav_group.addButton(btn, idx)
            lay.addWidget(btn)

        lay.addStretch()

        # Version info with top separator
        ver_sep = QFrame()
        ver_sep.setFrameShape(QFrame.Shape.HLine)
        ver_sep.setFrameShadow(QFrame.Shadow.Plain)
        ver_sep.setStyleSheet(theme.separator_style())
        lay.addWidget(ver_sep)

        version_label = QLabel(version_info.footer_text())
        version_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        version_label.setStyleSheet(theme.version_label_style())
        lay.addWidget(version_label)

        # QField export button (above template)
        btn_qfield = QPushButton("Export for QField")
        btn_qfield.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_qfield.setMinimumHeight(scale.dimension(34))
        btn_qfield.setToolTip("Export selected layers and the current project for QField (offline)")
        btn_qfield.setStyleSheet(theme.qfield_button_style())
        btn_qfield.clicked.connect(self.run_qfield_export)
        lay.addWidget(btn_qfield)

        # Reconcile button (below QField export, above template)
        btn_reconcile = QPushButton("Reconcile / Merge")
        btn_reconcile.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_reconcile.setMinimumHeight(scale.dimension(34))
        btn_reconcile.setToolTip("Reconcile and re-sync the working geopackage back into the master GeoPackage")
        btn_reconcile.setStyleSheet(theme.reconcile_button_style())
        btn_reconcile.clicked.connect(self.run_reconcile)
        lay.addWidget(btn_reconcile)

        # Template button
        btn_template = QPushButton("New Mapping Template")
        btn_template.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_template.setMinimumHeight(scale.dimension(34))
        btn_template.setToolTip("Load or configure the mapping geopackage template for your project")
        btn_template.setStyleSheet(theme.template_button_style())
        btn_template.clicked.connect(self.run_loadtemplate)
        lay.addWidget(btn_template)

        return sidebar_scroll, nav_group

    # ------------------------------------------------------------------
    # Content area builder
    # ------------------------------------------------------------------
    def _build_content_area(self):
        """Build the content area with page header and stacked widget.
        Returns (content_widget, stacked_widget, page_header_label).
        """
        scale = get_scale_manager()

        content_area = QWidget()
        content_area.setStyleSheet(theme.content_area_style())
        layout = QVBoxLayout(content_area)
        m = scale.margins(16, 16, 16, 16)
        layout.setContentsMargins(*m)
        layout.setSpacing(scale.spacing(12))

        # Page header label
        page_header = QLabel("Set Mapping Scale")
        page_header.setStyleSheet(theme.page_header_style())
        layout.addWidget(page_header)

        # Thin separator under page header
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setStyleSheet(theme.separator_style())
        layout.addWidget(sep)

        stacked = QStackedWidget()
        layout.addWidget(stacked)

        # Build all pages
        stacked.addWidget(self._build_page_setup())
        stacked.addWidget(self._build_page_photos())
        stacked.addWidget(self._build_page_data())
        stacked.addWidget(self._build_page_declination())
        stacked.addWidget(self._build_page_domains())
        stacked.addWidget(self._build_page_layouts())
        stacked.addWidget(self._build_page_symbology())
        stacked.addWidget(self._build_page_zfilter())

        return content_area, stacked, page_header

    # ------------------------------------------------------------------
    # Individual page builders
    # ------------------------------------------------------------------
    def _make_page(self):
        """Helper: create a blank page widget with standard layout."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(get_scale_manager().spacing(16))
        return page, lay

    def _build_page_setup(self):
        page, lay = self._make_page()
        grp = FeatureGroup("Set Mapping Scale", self.plugin_dir, page)
        grp.addFeature("Set Mapping Scale", None,
                        feature_info.INFO_SETUP_MAPPING, self.run_setmapping)
        grp.addSeparator()
        self.btn_cover = grp.addFeature(
            "Transported Cover Opacity", None,
            feature_info.INFO_COVER_OPACITY, self.run_cover_toggle)
        lay.addWidget(grp)
        lay.addStretch()
        return page

    def _build_page_photos(self):
        page, lay = self._make_page()
        grp = FeatureGroup("Field Photos", self.plugin_dir, page)
        grp.addFeature("Georeference Field Photos", None,
                        feature_info.INFO_GEOREFERENCE_PHOTOS, self.run_georeference)
        grp.addSeparator()
        grp.addFeature("View Photos Panel", None,
                        feature_info.INFO_VIEW_PHOTOS_PANEL, self.toggle_photo_panel)
        grp.addSeparator()
        grp.addFeature("Export Field Photos", None,
                        feature_info.INFO_EXPORT_PHOTOS, self.run_exportphotos)
        lay.addWidget(grp)
        lay.addStretch()
        return page

    def _build_page_data(self):
        page, lay = self._make_page()
        grp = FeatureGroup("Modify and Merge Data", self.plugin_dir, page)
        grp.addFeature("Hardcode Data & Update Legends", None,
                        feature_info.INFO_HARDCODE_DATA, self.run_hardcode_data)
        grp.addSeparator()
        grp.addFeature("Reproject GeoPackage", None,
                        feature_info.INFO_REPROJECT_GEOPACKAGE, self.run_reprojectgeopackage)
        grp.addSeparator()
        grp.addFeature("Append Mapping Data", None,
                        feature_info.INFO_APPEND_DATA, self.run_appenddata)
        grp.addSeparator()
        grp.addFeature("Import Mining Survey Data", None,
                        feature_info.INFO_MINING_IMPORT, self.run_mining_import)
        grp.addSeparator()
        grp.addFeature("Mapping Export", None,
                        feature_info.INFO_STATIC_MAPPING_EXPORT, self.run_static_mapping_export)
        lay.addWidget(grp)
        lay.addStretch()
        return page

    def _build_page_declination(self):
        page, lay = self._make_page()
        grp = FeatureGroup("Magnetic Declination Tools", self.plugin_dir, page)
        grp.addFeature("Calculate Declination (WMM)", None,
                        feature_info.INFO_DECLINATION_CALCULATOR, self.run_declination_calculator)
        grp.addSeparator()
        grp.addFeature("Add/Subtract Declination", None,
                        feature_info.DECLINATION_ADJUSTER_INFO, self.run_declination_adjuster)
        lay.addWidget(grp)
        lay.addStretch()
        return page

    def _build_page_domains(self):
        page, lay = self._make_page()
        grp = FeatureGroup("Domain Classification", self.plugin_dir, page)
        grp.addFeature("Create Domain Layer", None,
                        feature_info.INFO_CREATE_DOMAIN_LAYER, self.run_adddomainlayer)
        grp.addSeparator()
        grp.addFeature("Run Domain Classification", None,
                        feature_info.INFO_RUN_DOMAIN_CLASSIFICATION, self.run_domainclassification)
        lay.addWidget(grp)
        lay.addStretch()
        return page

    def _build_page_layouts(self):
        page, lay = self._make_page()
        grp = FeatureGroup("Layout & Mapsheet Generation", self.plugin_dir, page)
        grp.addFeature("Mapsheet Generator", None,
                        feature_info.INFO_MAPSHEET_GENERATOR, self.run_mapsheetgenerator)
        grp.addSeparator()
        grp.addFeature("Create Layouts", None,
                        feature_info.INFO_CREATE_LAYOUTS, self.run_createlayouts)
        lay.addWidget(grp)
        lay.addStretch()
        return page

    def _build_page_symbology(self):
        page, lay = self._make_page()
        grp = FeatureGroup("Re-classify & Symbology", self.plugin_dir, page)
        grp.addFeature("Recode & Restyle Wizard", None,
                        feature_info.INFO_RECODE_WORKFLOW, self.run_recode_workflow)
        lay.addWidget(grp)
        lay.addStretch()
        return page

    def _build_page_zfilter(self):
        page, lay = self._make_page()
        grp = FeatureGroup("Pit / Underground Level Filtering", self.plugin_dir, page)
        grp.addFeature("Open Z Filter Panel", None,
                        feature_info.INFO_Z_FILTER, self.toggle_z_filter_panel)
        grp.addSeparator()
        grp.addFeature("Add Elevation Field", None,
                        feature_info.INFO_ADD_ELEVATION, self.run_add_elevation_field)
        lay.addWidget(grp)
        lay.addStretch()
        return page

    # ------------------------------------------------------------------
    # Navigation wiring
    # ------------------------------------------------------------------
    def _connect_navigation(self, nav_group, stacked_widget, page_header_label):
        """Connect QButtonGroup to stacked widget and page header."""
        def on_button_clicked(btn_id):
            stacked_widget.setCurrentIndex(btn_id)
            if 0 <= btn_id < len(PAGE_DEFS):
                page_header_label.setText(PAGE_DEFS[btn_id][3])
            QgsSettings().setValue(SETTING_LAST_PAGE, btn_id)

        nav_group.idClicked.connect(on_button_clicked)

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------
    def _setup_shortcuts(self, dialog, nav_group, stacked_widget):
        """Set up keyboard navigation on the dialog."""
        def move_nav(delta):
            current = stacked_widget.currentIndex()
            new_idx = max(0, min(current + delta, stacked_widget.count() - 1))
            if new_idx != current:
                btn = nav_group.button(new_idx)
                if btn:
                    btn.setChecked(True)
                    btn.click()

        QShortcut(QKeySequence(Qt.Key.Key_Escape), dialog, dialog.close)
        QShortcut(QKeySequence(Qt.Key.Key_Up), dialog, lambda: move_nav(-1))
        QShortcut(QKeySequence(Qt.Key.Key_Down), dialog, lambda: move_nav(1))

    # ------------------------------------------------------------------
    # Geometry persistence
    # ------------------------------------------------------------------
    def _save_geometry(self):
        if self.main_dialog:
            QgsSettings().setValue(SETTING_GEOMETRY, self.main_dialog.saveGeometry())

    def _restore_geometry(self, dialog):
        geom = QgsSettings().value(SETTING_GEOMETRY)
        if geom:
            dialog.restoreGeometry(geom)

    # ------------------------------------------------------------------
    # Script execution methods (all use proper module imports)
    # ------------------------------------------------------------------
    def run_setmapping(self):
        from .script_setmapping import run
        run(self.iface)

    def run_cover_toggle(self):
        from . import cover_toggle
        # Read the live state first so the toggle self-corrects after a
        # project switch or an externally changed subset.
        hidden = not cover_toggle.is_cover_hidden()
        if cover_toggle.set_cover_hidden(self.iface, hidden):
            self.btn_cover.setText(
                "Transported Cover Opacity: %s"
                % ("Hidden" if hidden else "Visible"))

    def run_hardcode_data(self):
        from .hardcode_data import run
        run(self.iface)

    def run_georeference(self):
        from .script_georeference import run
        run(self.iface)

    def run_exportphotos(self):
        from .script_exportphotos import run
        run(self.iface)

    def run_recode_workflow(self):
        # recode_workflow pulls in pandas; import lazily so a missing
        # dependency only affects this feature, not plugin load.
        try:
            from .recode_workflow import run_recode_workflow
        except ImportError as e:
            self._show_missing_dependency("Recode & Restyle Wizard", str(e))
            return
        run_recode_workflow(self.iface, owner=self)

    def run_reprojectgeopackage(self):
        from .script_reprojectgeopackage import run
        run(self.iface, owner=self)

    def _confirm_z_filter_off(self, feature_name):
        """Full-table readers must not run behind an active Z filter.

        Returns True when it is safe to proceed (filter off, or the user
        agreed to turn it off). Level settings persist, so re-enabling
        afterwards is one click in the Z Filter panel.
        """
        from .z_filter.controller import (
            ZFilterController, active_z_filter_summary)
        summary = active_z_filter_summary()
        if not summary:
            return True
        answer = QMessageBox.question(
            self.iface.mainWindow(),
            f"{feature_name} — Z filter active",
            f"The Z elevation filter is active ({summary}).\n\n"
            f"{feature_name} reads whole tables, so the filter must be "
            "turned off first. Your level settings are kept — re-enable the "
            "filter afterwards from the Z Filter panel.\n\n"
            "Turn the filter off and continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes)
        if answer != QMessageBox.StandardButton.Yes:
            return False
        ZFilterController(self.iface).clear_filters()
        if self.z_filter_panel:
            self.z_filter_panel.sync_from_project()
        return True

    def run_static_mapping_export(self):
        if not self._confirm_z_filter_off("Mapping Export"):
            return
        from .static_mapping_export import run_static_mapping_export
        # Build the stereonet core on demand (it feeds the export); None is
        # handled downstream when matplotlib is unavailable.
        run_static_mapping_export(self.iface,
                                  stereonet_core=self._ensure_stereonet())

    def run_adddomainlayer(self):
        from .script_adddomainlayer import run
        run(self.iface)

    def run_domainclassification(self):
        from .script_domainclassification import run
        run(self.iface)

    def run_appenddata(self):
        if not self._confirm_z_filter_off("Append Mapping Data"):
            return
        from .script_adddata import run_gpkg_append_tool_dialog
        run_gpkg_append_tool_dialog(self.iface)

    def run_mining_import(self):
        from .mining_import import run
        run(self.iface, owner=self)

    def run_reconcile(self):
        if not self._confirm_z_filter_off("Reconcile / Merge"):
            return
        from .script_adddata.reconcile.dialog import run_reconcile_tool_dialog
        run_reconcile_tool_dialog(self.iface, owner=self)

    def run_qfield_export(self):
        from .qfield_export.gui.export_dialog import ExportDialog
        dlg = ExportDialog(self.iface, self.iface.mainWindow())
        dlg.exec()

    def run_mapsheetgenerator(self):
        from .script_mapsheet_generator import run
        run(self.iface)

    def run_createlayouts(self):
        from .script_create_layouts import run
        run(self.iface, owner=self)

    def run_loadtemplate(self):
        try:
            from .script_loadtemplate import run
            run(self.iface)
        except Exception as e:
            import traceback
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(
                f"run_loadtemplate failed: {e}\n{traceback.format_exc()}",
                'Linear Geoscience', Qgis.MessageLevel.Critical
            )
            self.iface.messageBar().pushCritical(
                "Linear Geoscience",
                f"Could not open New Mapping Template: {e}"
            )

    def run_declination_adjuster(self):
        from .script_declination_adjuster import DeclinationAdjusterDialog
        dialog = DeclinationAdjusterDialog(self.iface.mainWindow())
        dialog.exec()

    def run_declination_calculator(self):
        from .script_declination_calculator import CalculateDeclinationDialog
        dialog = CalculateDeclinationDialog(self.iface.mainWindow())
        dialog.exec()
