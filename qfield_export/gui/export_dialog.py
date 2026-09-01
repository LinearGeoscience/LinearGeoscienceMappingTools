"""
Main export dialog for LGS QField Exporter.
Professional dark theme with depth and clear hierarchy.
"""

import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List

from qgis.core import QgsProject, QgsMapLayer, QgsRasterLayer, Qgis
from qgis.core import QgsSettings
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import Qt, QUrl, pyqtSlot, QThread
from qgis.PyQt.QtGui import QDesktopServices, QFont
from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QProgressBar,
    QFileDialog,
    QMessageBox,
    QFrame,
    QSpacerItem,
    QSizePolicy,
    QTextEdit,
    QCheckBox,
    QDoubleSpinBox
)

from ..core.offline_converter import OfflineConverter
from ..utils.qgis_utils import get_project_layers, get_layer_info, get_raster_format_warning

try:
    from ...recode_workflow.widgets import CollapsibleSection
except ImportError:
    from recode_workflow.widgets import CollapsibleSection

# QSettings key for persisting last export directory
_SETTINGS_LAST_EXPORT_DIR = 'LGS_QField_Exporter/lastExportDir'

# Known cloud-sync folder markers
_CLOUD_SYNC_MARKERS = ('OneDrive', 'Dropbox', 'Google Drive', 'iCloudDrive', 'pCloud')

# Shared checkbox styling. 'border: none; background: transparent' matters:
# the QField-plugin checkboxes live inside a CollapsibleSection whose content
# widget carries an unscoped 'border: 1px solid ...' rule that would otherwise
# propagate to every child (recode_workflow/widgets.py does the same reset on
# its own labels). The ::indicator rules below are more specific, so the tick
# boxes keep their own border.
_CHECKBOX_QSS = """
    QCheckBox {
        color: #475569;
        font-size: 12px;
        padding: 4px 0px;
        border: none;
        background: transparent;
    }
    QCheckBox::indicator {
        width: 14px;
        height: 14px;
        border: 2px solid #cbd5e1;
        border-radius: 3px;
        background-color: #ffffff;
    }
    QCheckBox::indicator:checked {
        background-color: #64748b;
        border-color: #64748b;
    }
    QCheckBox::indicator:unchecked:hover {
        border-color: #64748b;
    }
"""

# The QField companion-plugin features, as (attribute, label, tooltip). Each
# entry becomes a checkbox inside the collapsed "QField Plugin Tools" section;
# the attribute names are the ones start_export() reads back, and every one
# must have a matching include_*_plugin kwarg on OfflineConverter.
# Labels carry no "(QField plugin)" suffix — the section header says it once.
_PLUGIN_TOOLS = (
    (
        "include_zfilter_check",
        "Include Z-Filter level switcher",
        "Ships a small QField plugin next to the exported project so the "
        "mapping layers can be filtered by bench/level elevation on the "
        "device. The export itself always contains ALL levels.",
    ),
    (
        "include_scale_check",
        "Include scale display",
        "Shows the live map scale on the QField map as a tappable pill — "
        "tap to lock the map at a fixed scale (presets or custom) for "
        "consistent mapping.",
    ),
    (
        "include_opacity_check",
        "Include imagery opacity toggle",
        "Adds a small button on the QField map that dims or hides the "
        "exported imagery/raster layers while drawing linework "
        "(100% → 50% → 25% → off).",
    ),
    (
        "include_clipping_check",
        "Include polygon clip tool",
        "Adds a Clip button on the QField map: tap the polygon(s) to "
        "keep, tap the polygon(s) to cut, and the overlap is removed on "
        "the device — polygons split apart become separate features.",
    ),
    (
        "include_spline_check",
        "Include spline drawing/reshaping",
        "Adds a Spline button on the QField map: while armed, the "
        "points you place are smoothed into a curve live — for new "
        "features and for reshaping — using the desktop Map Cleaning "
        "spline settings. Save with QField's normal confirm button.",
    ),
    (
        "include_reshape_check",
        "Include multi-polygon reshape tool",
        "Adds a Reshape button on the QField map: tap out a line "
        "across one or more polygons on the active layer and every "
        "crossed polygon is reshaped to it — optionally limited to "
        "polygons you tap first. The line is smoothed while the "
        "Spline tool is armed.",
    ),
    (
        "include_reverse_check",
        "Include line direction reverse tool",
        "Adds a Reverse button on the QField map: tap a line to flip "
        "its vertex order so asymmetric line symbology (ticks, teeth, "
        "dip marks) renders on the other side. Tap the line again to "
        "flip it back.",
    ),
    (
        "include_copyattrs_check",
        "Include attribute copy tool",
        "Adds a Copy button on the QField map: tap a feature to copy "
        "FROM, then tap features to copy TO — non-empty attributes "
        "are stamped across, including between layers (e.g. Basemap "
        "lithology, minerals and modal percents onto Field Notebook "
        "points). The source stays armed for stamping several "
        "features; one-tap undo covers the last one.",
    ),
    (
        "include_merge_check",
        "Include polygon merge tool",
        "Adds a Merge button on the QField map: tap two or more "
        "touching polygons on one layer and merge them into one — "
        "the first polygon you tap keeps its attributes and "
        "identity, and its empty fields are filled from the others. "
        "One-tap undo restores the original polygons.",
    ),
    (
        "include_layerswitch_check",
        "Include active layer switcher",
        "Adds a column of layer name pills up the left edge of the "
        "QField map: tap one to make that mapping layer the active "
        "one for digitising, without opening the layer tree. The "
        "names fade away to the right a moment after you stop "
        "using them, leaving the map clear.",
    ),
)


class ExportDialog(QDialog):
    """Professional export dialog with modern dark theme and clear hierarchy."""

    def __init__(self, iface: QgisInterface, parent=None):
        """
        Initialize the export dialog.

        Args:
            iface: QGIS interface
            parent: Parent widget
        """
        super().__init__(parent)
        self.iface = iface
        self.project = QgsProject.instance()
        self.converter = None
        self.export_dir = None
        self._export_thread = None

        self.setWindowTitle("LGS QField Exporter")
        self.setMinimumSize(800, 700)
        self.setStyleSheet(self._get_stylesheet())

        self.setup_ui()
        self.load_layers()
        self.set_default_export_path()

    def _get_stylesheet(self):
        """Professional light theme with slate blue accent."""
        return """
            /* Base dialog - light background */
            QDialog {
                background-color: #f8fafc;
            }

            /* Typography hierarchy */
            QLabel {
                color: #334155;
                font-size: 13px;
            }

            QLabel.header {
                font-size: 20px;
                font-weight: 600;
                color: #0f172a;
                padding: 12px 0px 4px 0px;
            }

            QLabel.subheader {
                font-size: 12px;
                color: #64748b;
                font-weight: 400;
                padding-bottom: 12px;
            }

            QLabel.section-header {
                font-size: 13px;
                font-weight: 600;
                color: #1e293b;
                padding-top: 8px;
                padding-bottom: 6px;
            }

            /* Input fields - white with border */
            QLineEdit {
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 8px 12px;
                background-color: #ffffff;
                font-size: 13px;
                color: #1e293b;
                selection-background-color: #64748b;
                selection-color: #ffffff;
            }

            QLineEdit:focus {
                border: 1px solid #64748b;
                background-color: #ffffff;
            }

            QLineEdit::placeholder {
                color: #94a3b8;
            }

            /* Primary buttons - slate blue */
            QPushButton {
                background-color: #64748b;
                color: #ffffff;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 500;
            }

            QPushButton:hover {
                background-color: #475569;
            }

            QPushButton:pressed {
                background-color: #334155;
            }

            QPushButton:disabled {
                background-color: #cbd5e1;
                color: #94a3b8;
            }

            /* Secondary buttons - subtle */
            QPushButton.secondary {
                background-color: #f1f5f9;
                color: #475569;
                border: 1px solid #cbd5e1;
            }

            QPushButton.secondary:hover {
                background-color: #e2e8f0;
                border-color: #64748b;
            }

            QPushButton.secondary:pressed {
                background-color: #cbd5e1;
            }

            /* Layer tree - white card */
            QTreeWidget {
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                background-color: #ffffff;
                alternate-background-color: #f8fafc;
                font-size: 13px;
                color: #1e293b;
                outline: none;
            }

            QTreeWidget::item {
                padding: 6px 4px;
                border-bottom: 1px solid #f1f5f9;
            }

            QTreeWidget::item:selected {
                background-color: rgba(100, 116, 139, 0.1);
                color: #1e293b;
            }

            QTreeWidget::item:hover {
                background-color: #f8fafc;
            }

            QTreeWidget::item:selected:hover {
                background-color: rgba(100, 116, 139, 0.15);
            }

            /* Table header */
            QHeaderView::section {
                background-color: #f8fafc;
                padding: 8px;
                border: none;
                border-bottom: 2px solid #e2e8f0;
                font-weight: 600;
                font-size: 11px;
                color: #64748b;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }

            /* Progress bar - slate blue */
            QProgressBar {
                border: none;
                border-radius: 3px;
                background-color: #e2e8f0;
                height: 6px;
                text-align: center;
            }

            QProgressBar::chunk {
                background-color: #64748b;
                border-radius: 2px;
            }

            /* Separator line */
            QFrame.separator {
                background-color: #e2e8f0;
                max-height: 1px;
                border: none;
            }

            /* Export log */
            QTextEdit {
                border: 1px solid #e2e8f0;
                border-radius: 5px;
                background-color: #f8fafc;
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                font-size: 11px;
                color: #475569;
                padding: 10px;
                selection-background-color: #64748b;
                selection-color: #ffffff;
            }

            /* Scrollbars */
            QScrollBar:vertical {
                background-color: #f8fafc;
                width: 10px;
                border-radius: 5px;
            }

            QScrollBar::handle:vertical {
                background-color: #cbd5e1;
                border-radius: 5px;
                min-height: 30px;
            }

            QScrollBar::handle:vertical:hover {
                background-color: #94a3b8;
            }

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }

            QScrollBar:horizontal {
                background-color: #f8fafc;
                height: 10px;
                border-radius: 5px;
            }

            QScrollBar::handle:horizontal {
                background-color: #cbd5e1;
                border-radius: 5px;
                min-width: 30px;
            }

            QScrollBar::handle:horizontal:hover {
                background-color: #94a3b8;
            }

            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }

            /* Checkboxes */
            QTreeWidget::indicator:unchecked {
                background-color: #ffffff;
                border: 2px solid #cbd5e1;
                border-radius: 3px;
                width: 14px;
                height: 14px;
            }

            QTreeWidget::indicator:checked {
                background-color: #64748b;
                border: 2px solid #64748b;
                border-radius: 3px;
                width: 14px;
                height: 14px;
            }

            QTreeWidget::indicator:unchecked:hover {
                border-color: #64748b;
            }
        """

    def setup_ui(self):
        """Set up the user interface with efficient layout."""
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        # Header
        header = QLabel("Export to QField")
        header.setProperty("class", "header")
        layout.addWidget(header)

        project_name = self.project.title() or "Untitled Project"
        layer_count = len(self.project.mapLayers())
        subheader = QLabel(f"{project_name} • {layer_count} layers")
        subheader.setProperty("class", "subheader")
        layout.addWidget(subheader)

        # Separator
        separator = QFrame()
        separator.setProperty("class", "separator")
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)

        # Export path section
        path_label = QLabel("Export Location")
        path_label.setProperty("class", "section-header")
        layout.addWidget(path_label)

        path_layout = QHBoxLayout()
        path_layout.setSpacing(12)

        self.export_dir_edit = QLineEdit()
        self.export_dir_edit.setPlaceholderText("Select export folder...")
        path_layout.addWidget(self.export_dir_edit)

        self.browse_button = QPushButton("Browse")
        self.browse_button.setProperty("class", "secondary")
        self.browse_button.setFixedWidth(100)
        self.browse_button.clicked.connect(self.browse_export_dir)
        path_layout.addWidget(self.browse_button)

        layout.addLayout(path_layout)

        # Layer selection section
        layers_label = QLabel("Select Layers")
        layers_label.setProperty("class", "section-header")
        layout.addWidget(layers_label)

        # Quick selection buttons
        quick_buttons = QHBoxLayout()
        quick_buttons.setSpacing(8)

        self.select_all_button = QPushButton("All")
        self.select_all_button.setProperty("class", "secondary")
        self.select_all_button.setMinimumWidth(80)
        self.select_all_button.clicked.connect(self.select_all_layers)
        quick_buttons.addWidget(self.select_all_button)

        self.select_none_button = QPushButton("None")
        self.select_none_button.setProperty("class", "secondary")
        self.select_none_button.setMinimumWidth(80)
        self.select_none_button.clicked.connect(self.select_no_layers)
        quick_buttons.addWidget(self.select_none_button)

        self.select_vector_button = QPushButton("Vector")
        self.select_vector_button.setProperty("class", "secondary")
        self.select_vector_button.setMinimumWidth(80)
        self.select_vector_button.clicked.connect(self.select_vector_layers)
        quick_buttons.addWidget(self.select_vector_button)

        self.select_raster_button = QPushButton("Raster")
        self.select_raster_button.setProperty("class", "secondary")
        self.select_raster_button.setMinimumWidth(80)
        self.select_raster_button.clicked.connect(self.select_raster_layers)
        quick_buttons.addWidget(self.select_raster_button)

        quick_buttons.addStretch()
        layout.addLayout(quick_buttons)

        # Convert unsupported rasters checkbox
        self.convert_unsupported_check = QCheckBox("Convert unsupported raster formats to GeoTIFF")
        self.convert_unsupported_check.setChecked(True)
        self.convert_unsupported_check.setToolTip(
            "When enabled, raster formats not supported by QField (ECW, MrSID, etc.) "
            "will be automatically converted to GeoTIFF with LZW compression during export."
        )
        self.convert_unsupported_check.setStyleSheet(_CHECKBOX_QSS)
        self.convert_unsupported_check.setVisible(False)  # Hidden until unsupported layers detected
        # Deliberately NOT inside the collapsible section below:
        # _build_tree_structure reveals this one with setVisible(True) when an
        # unsupported raster turns up, which a collapsed parent would swallow.
        layout.addWidget(self.convert_unsupported_check)

        # QField companion-plugin features. Always-on defaults that are
        # rarely changed, so they live in a section that starts COLLAPSED —
        # the nine rows they used to occupy go to the layer tree instead.
        self._plugin_section = CollapsibleSection(
            "QField Plugin Tools", expanded=False)
        self._plugin_checks = []
        for attr, label, tooltip in _PLUGIN_TOOLS:
            check = QCheckBox(label)
            check.setChecked(True)
            check.setToolTip(tooltip)
            check.setStyleSheet(_CHECKBOX_QSS)
            check.toggled.connect(self._update_plugin_badge)
            setattr(self, attr, check)
            self._plugin_checks.append(check)
            self._plugin_section.content_layout().addWidget(check)
        self._update_plugin_badge()
        layout.addWidget(self._plugin_section)

        # 3D terrain baking. Data configuration rather than a plugin
        # tool, so it sits outside the collapsed section above.
        self._terrain_layer_id = None
        terrain_row = QHBoxLayout()
        self.bake_terrain_check = QCheckBox("Bake 3D terrain (QField 4.1+)")
        self.bake_terrain_check.setStyleSheet(_CHECKBOX_QSS)
        self.bake_terrain_check.setToolTip(
            "Write the DEM as the exported project's terrain so QField's "
            "3D map view works offline with your mapping draped on it. "
            "Needs QField 4.1 or newer on the device.")
        terrain_row.addWidget(self.bake_terrain_check)
        self.terrain_z_label = QLabel("Exaggeration:")
        terrain_row.addWidget(self.terrain_z_label)
        self.terrain_z_spin = QDoubleSpinBox()
        self.terrain_z_spin.setRange(1.0, 10.0)
        self.terrain_z_spin.setDecimals(1)
        self.terrain_z_spin.setSingleStep(0.5)
        self.terrain_z_spin.setValue(1.0)
        self.terrain_z_spin.setSuffix("x")
        self.terrain_z_spin.setToolTip(
            "Vertical exaggeration baked into the exported terrain "
            "(1.0x = true scale). Fixed on the device once exported.")
        terrain_row.addWidget(self.terrain_z_spin)
        terrain_row.addStretch()
        layout.addLayout(terrain_row)
        self._setup_terrain_row()

        # Layer tree with groups
        self.layer_tree = QTreeWidget()
        self.layer_tree.setHeaderLabels(["Layer", "Type", "Geometry", "CRS"])
        self.layer_tree.setRootIsDecorated(True)  # Show tree structure
        self.layer_tree.setAlternatingRowColors(True)
        self.layer_tree.setSortingEnabled(False)  # Keep QGIS order
        self.layer_tree.setIndentation(20)  # Indent for groups
        layout.addWidget(self.layer_tree)

        # Progress section (hidden initially)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setVisible(False)
        self.status_label.setStyleSheet("color: #a0a0a0; font-size: 12px;")
        layout.addWidget(self.status_label)

        # Export log (visible during export)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setVisible(False)
        self.log_text.setMaximumHeight(180)
        layout.addWidget(self.log_text)

        # Bottom buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setProperty("class", "secondary")
        self.cancel_button.setFixedWidth(100)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        button_layout.addWidget(self.cancel_button)

        self.export_button = QPushButton("Export")
        self.export_button.setFixedWidth(100)
        self.export_button.clicked.connect(self.start_export)
        button_layout.addWidget(self.export_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def _update_plugin_badge(self):
        """Show how many plugin tools are on, so the collapsed header still
        tells you when this export is not the default."""
        total = len(self._plugin_checks)
        on = sum(1 for check in self._plugin_checks if check.isChecked())
        # 'required' is the neutral grey badge; 'loaded' is green and would
        # fight this dialog's slate palette.
        self._plugin_section.set_status(
            "required", "{} of {} included".format(on, total))

    def _setup_terrain_row(self):
        """Auto-detect the terrain DEM (same convention as View in 3D)
        and pre-check baking when one is found; exaggeration defaults to
        the desktop 3D panel's persisted setting."""
        try:
            try:
                from ...view3d import terrain as view3d_terrain
            except ImportError:  # standalone use outside the plugin package
                from view3d import terrain as view3d_terrain

            layer = view3d_terrain.current_terrain_layer(self.project)
            reason = 'terrain'
            if layer is None:
                layer, reason = view3d_terrain.choose_dem_layer(self.project)
            if layer is None:
                self.bake_terrain_check.setText(
                    "Bake 3D terrain (QField 4.1+) — no DEM found")
                self.bake_terrain_check.setChecked(False)
                self.bake_terrain_check.setEnabled(False)
                self.terrain_z_spin.setEnabled(False)
                self.terrain_z_label.setEnabled(False)
                return
            self._terrain_layer_id = layer.id()
            self.bake_terrain_check.setText(
                "Bake 3D terrain: {0} (QField 4.1+)".format(layer.name()))
            self.bake_terrain_check.setChecked(True)

            settings = QgsSettings()
            prefix = "LinearGeosciencePlugin/View3D/"
            if settings.value(prefix + "zEnabled", False, bool):
                self.terrain_z_spin.setValue(
                    settings.value(prefix + "zFactor", 1.0, float))
        except Exception as e:
            # A detection hiccup must never block the export dialog.
            self.bake_terrain_check.setChecked(False)
            self.bake_terrain_check.setEnabled(False)
            from qgis.core import QgsMessageLog
            QgsMessageLog.logMessage(
                "3D terrain detection failed: {0}".format(e),
                "Linear Geoscience", Qgis.MessageLevel.Warning)

    def _on_cancel_clicked(self):
        """Handle cancel button click - cancel export if running, otherwise close."""
        if self._export_thread is not None and self._export_thread.isRunning():
            self.converter.cancel()
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("Cancelling...")
        else:
            self.reject()

    def load_layers(self):
        """Load layers from the project into the tree widget, preserving QGIS layer tree structure."""
        self.layer_tree.clear()

        # Get the root layer tree group from the project
        root = self.project.layerTreeRoot()

        # Recursively build the tree structure
        self._build_tree_structure(root, self.layer_tree)

        # Expand all groups
        self.layer_tree.expandAll()

        # Resize columns to content
        for i in range(self.layer_tree.columnCount()):
            self.layer_tree.resizeColumnToContents(i)

    def _build_tree_structure(self, tree_node, parent_item):
        """
        Recursively build the layer tree structure matching QGIS.

        Args:
            tree_node: QgsLayerTreeNode from QGIS
            parent_item: QTreeWidget or QTreeWidgetItem to add children to
        """
        from qgis.core import QgsLayerTreeLayer, QgsLayerTreeGroup

        for child in tree_node.children():
            if isinstance(child, QgsLayerTreeGroup):
                # Create group item
                group_item = QTreeWidgetItem()
                group_item.setText(0, child.name())
                group_item.setData(0, Qt.ItemDataRole.UserRole, "GROUP")
                group_item.setFlags(group_item.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
                group_item.setCheckState(0, Qt.CheckState.Checked)

                # Style group item
                font = group_item.font(0)
                font.setBold(True)
                group_item.setFont(0, font)
                # Use dark color for light theme
                from qgis.PyQt.QtGui import QColor
                group_item.setForeground(0, QColor("#0f172a"))

                if isinstance(parent_item, QTreeWidget):
                    parent_item.addTopLevelItem(group_item)
                else:
                    parent_item.addChild(group_item)

                # Recursively add children
                self._build_tree_structure(child, group_item)

            elif isinstance(child, QgsLayerTreeLayer):
                # Get the actual layer
                layer = child.layer()
                if layer:
                    info = get_layer_info(layer)

                    item = QTreeWidgetItem()
                    item.setText(0, info['name'])
                    item.setText(1, info['type'])
                    item.setText(2, info.get('geometry', ''))
                    item.setText(3, info['crs'])
                    item.setData(0, Qt.ItemDataRole.UserRole, layer.id())

                    # Add checkbox
                    item.setCheckState(0, Qt.CheckState.Checked if info['is_valid'] else Qt.CheckState.Unchecked)
                    item.setDisabled(not info['is_valid'])

                    # Check for unsupported raster formats
                    if isinstance(layer, QgsRasterLayer) and info['is_valid']:
                        format_warning = get_raster_format_warning(layer)
                        if format_warning:
                            from qgis.PyQt.QtGui import QColor
                            item.setText(1, "Raster \u26a0")
                            item.setForeground(1, QColor("#d97706"))
                            item.setToolTip(0, f"Unsupported format: {format_warning}")
                            item.setToolTip(1, f"Unsupported format: {format_warning}")
                            # Show the conversion checkbox
                            self.convert_unsupported_check.setVisible(True)

                    # Set tooltip for invalid layers
                    if not info['is_valid']:
                        item.setToolTip(0, "This layer is invalid and cannot be exported")

                    if isinstance(parent_item, QTreeWidget):
                        parent_item.addTopLevelItem(item)
                    else:
                        parent_item.addChild(item)

    def set_default_export_path(self):
        """Set a default export path based on saved setting, then project location."""
        # Try last used export directory from QSettings
        last_dir = QgsSettings().value(_SETTINGS_LAST_EXPORT_DIR, '')
        if last_dir and Path(last_dir).parent.exists():
            self.export_dir_edit.setText(last_dir)
            return

        # Fallback to project directory
        project_path = self.project.fileName()
        if project_path:
            project_dir = Path(project_path).parent
            export_dir = project_dir / "QField_Export"
        else:
            export_dir = Path.home() / "QField_Export"

        self.export_dir_edit.setText(str(export_dir))

    @pyqtSlot()
    def browse_export_dir(self):
        """Open a file dialog to select the export directory."""
        current_dir = self.export_dir_edit.text()
        if not current_dir:
            current_dir = str(Path.home())

        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Export Directory",
            current_dir
        )

        if directory:
            self.export_dir_edit.setText(directory)

    @pyqtSlot()
    def select_all_layers(self):
        """Select all valid layers recursively."""
        def select_all_recursive(item):
            if not item.isDisabled() and item.data(0, Qt.ItemDataRole.UserRole) != "GROUP":
                item.setCheckState(0, Qt.CheckState.Checked)
            for i in range(item.childCount()):
                select_all_recursive(item.child(i))

        for i in range(self.layer_tree.topLevelItemCount()):
            select_all_recursive(self.layer_tree.topLevelItem(i))

    @pyqtSlot()
    def select_no_layers(self):
        """Deselect all layers recursively."""
        def deselect_all_recursive(item):
            item.setCheckState(0, Qt.CheckState.Unchecked)
            for i in range(item.childCount()):
                deselect_all_recursive(item.child(i))

        for i in range(self.layer_tree.topLevelItemCount()):
            deselect_all_recursive(self.layer_tree.topLevelItem(i))

    @pyqtSlot()
    def select_vector_layers(self):
        """Select only vector layers recursively."""
        def select_vector_recursive(item):
            if item.text(1) == "Vector" and not item.isDisabled():
                item.setCheckState(0, Qt.CheckState.Checked)
            elif item.data(0, Qt.ItemDataRole.UserRole) != "GROUP":
                item.setCheckState(0, Qt.CheckState.Unchecked)
            for i in range(item.childCount()):
                select_vector_recursive(item.child(i))

        for i in range(self.layer_tree.topLevelItemCount()):
            select_vector_recursive(self.layer_tree.topLevelItem(i))

    @pyqtSlot()
    def select_raster_layers(self):
        """Select only raster layers recursively."""
        def select_raster_recursive(item):
            if item.text(1) == "Raster" and not item.isDisabled():
                item.setCheckState(0, Qt.CheckState.Checked)
            elif item.data(0, Qt.ItemDataRole.UserRole) != "GROUP":
                item.setCheckState(0, Qt.CheckState.Unchecked)
            for i in range(item.childCount()):
                select_raster_recursive(item.child(i))

        for i in range(self.layer_tree.topLevelItemCount()):
            select_raster_recursive(self.layer_tree.topLevelItem(i))

    def get_selected_layers(self) -> List[str]:
        """Get list of selected layer IDs from the tree (including nested layers)."""
        selected = []

        def collect_checked_layers(item):
            """Recursively collect checked layer IDs."""
            layer_id = item.data(0, Qt.ItemDataRole.UserRole)

            # If it's a layer (not a group), add it if checked
            if layer_id != "GROUP" and item.checkState(0) == Qt.CheckState.Checked:
                selected.append(layer_id)

            # Process children
            for i in range(item.childCount()):
                collect_checked_layers(item.child(i))

        # Process all top-level items
        for i in range(self.layer_tree.topLevelItemCount()):
            collect_checked_layers(self.layer_tree.topLevelItem(i))

        return selected

    def _validate_export_path(self, export_dir: str) -> bool:
        """
        Validate the export path is usable before starting export.

        Args:
            export_dir: Path string to validate

        Returns:
            True if valid and writable, False otherwise
        """
        export_path = Path(export_dir)

        # Check for invalid characters (Windows-specific)
        invalid_chars = '<>"|?*'
        if any(c in export_dir for c in invalid_chars):
            QMessageBox.warning(
                self, "Invalid Path",
                f"Export path contains invalid characters: {invalid_chars}"
            )
            return False

        # Check parent directory exists (we'll create the export dir itself)
        parent = export_path.parent
        if not parent.exists():
            QMessageBox.warning(
                self, "Invalid Path",
                f"Parent directory does not exist:\n{parent}"
            )
            return False

        # Check write permissions by trying to create a temp file
        test_dir = export_path if export_path.exists() else parent
        try:
            fd, tmp = tempfile.mkstemp(dir=str(test_dir))
            os.close(fd)
            os.unlink(tmp)
        except OSError:
            QMessageBox.warning(
                self, "Permission Denied",
                f"Cannot write to:\n{test_dir}\n\n"
                "Please choose a different directory or check permissions."
            )
            return False

        # Warn if path is inside a cloud-synced folder
        path_str = str(export_path)
        for marker in _CLOUD_SYNC_MARKERS:
            if marker in path_str:
                reply = QMessageBox.question(
                    self, "Cloud-Synced Folder",
                    f"The export path appears to be inside a cloud-synced folder ({marker}).\n\n"
                    "This may cause sync conflicts with GeoPackage files. "
                    "Consider exporting to a local folder instead.\n\n"
                    "Continue anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return False
                break  # Only warn once

        return True

    def _ensure_cover_opacity_style(self):
        """Bake the data-defined transported-cover opacity onto Basemap.

        Runs before the save prompt, so the expression reaches the saved
        .qgs the converter copies. Silent on every failure path: an
        unstyled export just means the device ladder falls back to
        Off/100 behaviour.
        """
        try:
            from ... import cover_toggle
        except ImportError:
            try:
                import cover_toggle
            except ImportError:
                return
        try:
            layer = cover_toggle.get_basemap_layer(self.project)
            if layer is not None:
                cover_toggle.ensure_cover_opacity_dd(layer)
        except Exception:
            pass

    @pyqtSlot()
    def start_export(self):
        """Start the export process on a background thread."""
        # The device fades transported cover by rewriting
        # @lgs_cover_opacity, which only bites if the Basemap renderer
        # carries the expression that reads it. Bake it before the
        # save-check below so an export is ready for the ladder even when
        # the desktop button was never pressed (idempotent, and invisible
        # until the variable moves off 100). Best-effort — a styling
        # failure must never block an export.
        self._ensure_cover_opacity_style()
        # The converter reads the project file from disk, so it must exist
        # and be current.
        if not self.project.fileName():
            QMessageBox.warning(
                self, "Save Project First",
                "The project has not been saved yet. Save it to a file, "
                "then export.")
            return
        if self.project.isDirty():
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "The project has unsaved changes. The export reads the "
                "saved project file, so it should be saved first.\n\n"
                "Save now and continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes)
            if reply != QMessageBox.StandardButton.Yes:
                return
            if not self.project.write():
                QMessageBox.warning(
                    self, "Save Failed",
                    "Could not save the project — export cancelled.")
                return

        # Validate input
        export_dir = self.export_dir_edit.text().strip()
        if not export_dir:
            QMessageBox.warning(self, "Export Location Required",
                              "Please select an export directory.")
            return

        selected_layers = self.get_selected_layers()
        if not selected_layers:
            QMessageBox.warning(self, "No Layers Selected",
                              "Please select at least one layer to export.")
            return

        # Validate export path
        if not self._validate_export_path(export_dir):
            return

        # Prepare UI for export - disable controls
        self._set_export_ui_enabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setVisible(True)
        self.log_text.setVisible(True)
        self.log_text.clear()
        self.export_button.setEnabled(False)
        self.export_button.setText("Exporting...")
        self.cancel_button.setText("Cancel")
        self.cancel_button.setEnabled(True)

        # Clean up any previous converter/thread
        self._cleanup_export()

        # Create converter
        self.export_dir = Path(export_dir)
        self.converter = OfflineConverter(
            self.project, self.export_dir, selected_layers,
            convert_unsupported=self.convert_unsupported_check.isChecked(),
            include_zfilter_plugin=self.include_zfilter_check.isChecked(),
            include_scale_plugin=self.include_scale_check.isChecked(),
            include_opacity_plugin=self.include_opacity_check.isChecked(),
            include_clipping_plugin=self.include_clipping_check.isChecked(),
            include_spline_plugin=self.include_spline_check.isChecked(),
            include_reshape_plugin=self.include_reshape_check.isChecked(),
            include_reverse_plugin=self.include_reverse_check.isChecked(),
            include_copyattrs_plugin=self.include_copyattrs_check.isChecked(),
            include_merge_plugin=self.include_merge_check.isChecked(),
            include_layerswitch_plugin=(
                self.include_layerswitch_check.isChecked()),
            bake_terrain=(self.bake_terrain_check.isChecked()
                          and self._terrain_layer_id is not None),
            terrain_layer_id=self._terrain_layer_id,
            terrain_scale=self.terrain_z_spin.value()
        )

        try:
            from ...z_filter.controller import active_z_filter_summary
            summary = active_z_filter_summary(self.project)
        except Exception:
            summary = None
        if summary:
            self.add_log(
                f"Z filter is active ({summary}) — the export ships all "
                "levels unfiltered; the QField plugin restores the level on "
                "the device.")

        # Connect signals
        self.converter.progress_updated.connect(self.update_progress)
        self.converter.warning.connect(self.show_warning)
        self.converter.finished.connect(self._on_export_finished)
        self.converter.log_message.connect(self.add_log)

        # Initial log
        self.add_log(f"Starting export to: {self.export_dir}")
        self.add_log(f"Exporting {len(selected_layers)} layers\n")

        # Set up background thread
        self._export_thread = QThread()
        self.converter.moveToThread(self._export_thread)
        self._export_thread.started.connect(self.converter.export)
        self._export_thread.start()

    def _set_export_ui_enabled(self, enabled: bool):
        """Enable or disable UI controls during export."""
        self.browse_button.setEnabled(enabled)
        self.export_dir_edit.setEnabled(enabled)
        self.select_all_button.setEnabled(enabled)
        self.select_none_button.setEnabled(enabled)
        self.select_vector_button.setEnabled(enabled)
        self.select_raster_button.setEnabled(enabled)
        self.convert_unsupported_check.setEnabled(enabled)
        self._plugin_section.setEnabled(enabled)  # covers all nine checkboxes
        self.layer_tree.setEnabled(enabled)

    def _cleanup_export(self):
        """Clean up converter and thread from a previous export."""
        if self._export_thread is not None:
            if self._export_thread.isRunning():
                self._export_thread.quit()
                self._export_thread.wait(5000)
            self._export_thread.deleteLater()
            self._export_thread = None
        if self.converter is not None:
            self.converter.deleteLater()
            self.converter = None

    @pyqtSlot(int, int, str)
    def update_progress(self, current, total, message):
        """Update the progress bar and status label."""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.status_label.setText(message)

    @pyqtSlot(str)
    def show_warning(self, message):
        """Show a warning message."""
        self.status_label.setText(f"Warning: {message}")
        self.status_label.setStyleSheet("color: #f59e0b; font-size: 12px;")
        self.add_log(f"WARNING: {message}")

    @pyqtSlot(str)
    def add_log(self, message):
        """Add a message to the export log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        # Scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    @pyqtSlot(bool)
    def _on_export_finished(self, success):
        """Handle export completion - stop thread and update UI."""
        # Stop the background thread
        if self._export_thread is not None:
            self._export_thread.quit()
            self._export_thread.wait(5000)

        # Re-enable UI controls
        self._set_export_ui_enabled(True)
        self.export_button.setEnabled(True)
        self.export_button.setText("Export")
        self.cancel_button.setText("Close")
        self.cancel_button.setEnabled(True)

        if success:
            # Persist the export directory for next time
            QgsSettings().setValue(_SETTINGS_LAST_EXPORT_DIR, str(self.export_dir))

            self.status_label.setText("Export completed successfully")
            self.status_label.setStyleSheet("color: #10b981; font-size: 12px; font-weight: 600;")

            # Show success message with option to open folder
            reply = QMessageBox.information(
                self,
                "Export Complete",
                f"Project exported successfully to:\n{self.export_dir}\n\n"
                "Would you like to open the export folder?",
                QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.Ok
            )

            if reply == QMessageBox.StandardButton.Open:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.export_dir)))
        else:
            self.status_label.setText("Export failed")
            self.status_label.setStyleSheet("color: #ef4444; font-size: 12px; font-weight: 600;")
            QMessageBox.critical(
                self,
                "Export Failed",
                "The export process failed. Please check the log for details."
            )

        # Clean up converter (keep thread reference for cleanup later)
        if self.converter is not None:
            self.converter.deleteLater()
            self.converter = None
