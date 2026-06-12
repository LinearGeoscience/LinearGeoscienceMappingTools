# -*- coding: utf-8 -*-
"""
Dock Widget UI for Map Cleaning Toolkit - Clipping Panel
Tabbed interface for clipping operations and spline settings
"""
from qgis.core import QgsMapLayerProxyModel
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import pyqtSignal, Qt, QVariant
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


def detect_uuid_field(layer):
    """
    Auto-detect UUID field in a layer by looking for common naming patterns.

    Args:
        layer: QgsVectorLayer

    Returns:
        str or None - field name if found, None otherwise
    """
    if not layer:
        return None

    # Common UUID field name patterns (case-insensitive)
    uuid_patterns = ['uuid', 'guid', 'globalid', 'unique_id', 'uniqueid', 'feature_uuid']

    for field in layer.fields():
        field_name_lower = field.name().lower()
        for pattern in uuid_patterns:
            if pattern in field_name_lower:
                return field.name()

    return None


def get_candidate_uuid_fields(layer):
    """
    Get list of fields that could be used as UUID fields.

    Args:
        layer: QgsVectorLayer

    Returns:
        list of tuples: [(display_name, field_name), ...]
    """
    if not layer:
        return []

    candidates = []
    uuid_patterns = ['uuid', 'guid', 'globalid', 'unique_id', 'uniqueid']

    for field in layer.fields():
        field_name_lower = field.name().lower()

        # Check if it matches UUID patterns (prioritize these)
        is_uuid_field = any(pattern in field_name_lower for pattern in uuid_patterns)

        # Only include string fields as candidates
        if field.type() == QVariant.String:
            if is_uuid_field:
                candidates.insert(0, (f"{field.name()} (detected)", field.name()))
            else:
                candidates.append((field.name(), field.name()))

    return candidates


class ClipperDockWidget(QDockWidget):
    """
    Main dock widget for Map Cleaning Toolkit clipping features.
    Provides tabbed UI with: Clip All, Clip Isolated, Smart Clip, and Spline Settings.
    """

    # Signals
    executeClicked = pyqtSignal()
    lockCuttersClicked = pyqtSignal()
    clearClicked = pyqtSignal()
    resetClicked = pyqtSignal()
    layerChanged = pyqtSignal(object)  # Emits QgsVectorLayer
    modeChanged = pyqtSignal(str)  # Emits 'clip_all', 'clip_isolated', 'clip_smart', 'find_overlaps', 'find_slivers', or 'fix_geometry'
    closingPanel = pyqtSignal()
    splineSettingsChanged = pyqtSignal()  # Emitted when spline settings change
    findOverlapsClicked = pyqtSignal()  # Emitted when find overlaps is clicked
    findSliversClicked = pyqtSignal()  # Emitted when find slivers is clicked
    detectGeometryIssuesClicked = pyqtSignal()  # Emitted when detect geometry issues is clicked
    viewGeometryIssuesClicked = pyqtSignal()  # Emitted when view issues is clicked
    fixGeometryIssuesClicked = pyqtSignal()  # Emitted when fix all is clicked

    def __init__(self, parent=None):
        super(ClipperDockWidget, self).__init__(parent)

        self.mode = 'clip_all'
        self.isolated_step = 1  # 1 = selecting cutters, 2 = selecting targets

        self.setup_ui()

    def setup_ui(self):
        """Build the tabbed dock widget UI"""
        self.setWindowTitle("Map Cleaning Toolkit")
        self.setObjectName("LinearGeoscienceMapCleaningDock")

        # Paint the dock title explicitly — works around a QGIS/Qt repaint
        # glitch where the native title bar can render partly blank
        self.setStyleSheet(
            "QDockWidget::title {"
            " background: palette(window);"
            " padding: 4px 4px 4px 6px;"
            "}"
        )

        # Main widget
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # Title
        title_label = QLabel("<b>Map Cleaning Toolkit</b>")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 11pt; padding: 4px; color: #2196F3;")
        main_layout.addWidget(title_label)

        # Layer selection (shared across all tabs)
        layer_group = QGroupBox("Active Layer")
        layer_group.setStyleSheet("QGroupBox { font-weight: bold; padding-top: 8px; margin-top: 6px; }")
        layer_layout = QVBoxLayout()
        layer_layout.setSpacing(4)
        layer_layout.setContentsMargins(6, 6, 6, 6)

        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.layer_combo.layerChanged.connect(self.on_layer_changed)

        layer_layout.addWidget(self.layer_combo)
        layer_group.setLayout(layer_layout)
        main_layout.addWidget(layer_group)

        # Create tabbed interface
        self.tab_widget = QTabWidget()
        self.tab_widget.currentChanged.connect(self.on_tab_changed)

        # Tab 1: Clip All
        self.clip_all_tab = self.create_clip_all_tab()
        self.tab_widget.addTab(self.clip_all_tab, "Clip All")

        # Tab 2: Clip Isolated
        self.clip_isolated_tab = self.create_clip_isolated_tab()
        self.tab_widget.addTab(self.clip_isolated_tab, "Clip Isolated")

        # Tab 3: Smart Clip
        self.clip_smart_tab = self.create_clip_smart_tab()
        self.tab_widget.addTab(self.clip_smart_tab, "Smart Clip")

        # Tab 4: Find Overlaps
        self.find_overlaps_tab = self.create_find_overlaps_tab()
        self.tab_widget.addTab(self.find_overlaps_tab, "Find Overlaps")

        # Tab 5: Find Slivers
        self.find_slivers_tab = self.create_find_slivers_tab()
        self.tab_widget.addTab(self.find_slivers_tab, "Find Slivers")

        # Tab 6: Fix Geometry
        self.fix_geometry_tab = self.create_fix_geometry_tab()
        self.tab_widget.addTab(self.fix_geometry_tab, "Fix Geometry")

        # Tab 7: Spline Settings
        self.spline_settings_tab = self.create_spline_settings_tab()
        self.tab_widget.addTab(self.spline_settings_tab, "Spline Settings")

        main_layout.addWidget(self.tab_widget)

        # Shared status at bottom
        status_group = QGroupBox("Status")
        status_group.setStyleSheet("QGroupBox { font-weight: bold; padding-top: 8px; margin-top: 6px; }")
        status_layout = QVBoxLayout()
        status_layout.setSpacing(2)
        status_layout.setContentsMargins(6, 6, 6, 6)

        self.status_text = QLabel("Ready. Select features...")
        self.status_text.setWordWrap(True)
        self.status_text.setStyleSheet("padding: 4px; font-size: 9pt;")

        status_layout.addWidget(self.status_text)
        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)

        # Set main widget
        main_widget.setLayout(main_layout)
        self.setWidget(main_widget)

    def create_clip_all_tab(self):
        """Create Clip All tab content"""
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # Description
        desc_label = QLabel("<b>Clip All Intersecting Mode</b><br>"
                           "One polygon clips all others it intersects")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("padding: 6px; background-color: #E3F2FD; border-radius: 3px;")
        layout.addWidget(desc_label)

        # Settings
        settings_group = QGroupBox("Settings")
        settings_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        settings_layout = QFormLayout()
        settings_layout.setSpacing(6)

        self.snap_spinbox_all = QDoubleSpinBox()
        self.snap_spinbox_all.setDecimals(4)
        self.snap_spinbox_all.setMinimum(0.0001)
        self.snap_spinbox_all.setMaximum(1.0)
        self.snap_spinbox_all.setSingleStep(0.001)
        self.snap_spinbox_all.setValue(0.001)
        self.snap_spinbox_all.setSuffix(" units")

        settings_layout.addRow("Snap Tolerance:", self.snap_spinbox_all)

        # Add checkbox for split multipart
        self.split_multipart_checkbox_all = QCheckBox("Split bisected polygons into separate features")
        self.split_multipart_checkbox_all.setToolTip(
            "When a polygon is cut into multiple parts by the clipping polygon,\n"
            "create separate features for each part instead of keeping only the largest."
        )
        self.split_multipart_checkbox_all.setChecked(False)  # Default to off for compatibility
        settings_layout.addRow("", self.split_multipart_checkbox_all)

        # UUID field selector (shown when split is enabled)
        self.uuid_field_label_all = QLabel("UUID Field:")
        self.uuid_field_combo_all = QComboBox()
        self.uuid_field_combo_all.setToolTip(
            "Select the UUID field to regenerate when splitting.\n"
            "New UUIDs will be generated for split features to avoid duplicates."
        )
        self.uuid_field_label_all.setVisible(False)
        self.uuid_field_combo_all.setVisible(False)

        # Connect checkbox to show/hide UUID selector
        self.split_multipart_checkbox_all.toggled.connect(
            lambda checked: self._toggle_uuid_visibility('all', checked)
        )

        settings_layout.addRow(self.uuid_field_label_all, self.uuid_field_combo_all)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # Selection status
        status_group = QGroupBox("Selection")
        status_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        status_layout = QVBoxLayout()
        status_layout.setSpacing(4)

        self.cutter_label_all = QLabel("Cutter: <b>0</b> selected")
        status_layout.addWidget(self.cutter_label_all)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # Actions
        actions_group = QGroupBox("Actions")
        actions_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(6)

        self.execute_button_all = QPushButton("Execute Clip Preview")
        self.execute_button_all.setEnabled(False)
        self.execute_button_all.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; "
            "padding: 10px; font-weight: bold; border-radius: 4px; }"
            "QPushButton:hover:enabled { background-color: #1976D2; }"
            "QPushButton:disabled { background-color: #CCCCCC; color: #888888; }"
        )
        self.execute_button_all.clicked.connect(self.on_execute_all)

        self.clear_button_all = QPushButton("Clear Selection")
        self.clear_button_all.setEnabled(False)
        self.clear_button_all.setStyleSheet("padding: 8px; border-radius: 4px;")
        self.clear_button_all.clicked.connect(self.clearClicked.emit)

        actions_layout.addWidget(self.execute_button_all)
        actions_layout.addWidget(self.clear_button_all)
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)

        layout.addStretch()
        tab.setLayout(layout)
        return tab

    def create_clip_isolated_tab(self):
        """Create Clip Isolated tab content"""
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # Description
        desc_label = QLabel("<b>Clip Isolated Mode (Two-Step)</b><br>"
                           "Step 1: Select cutters, lock them<br>"
                           "Step 2: Select targets to be clipped")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("padding: 6px; background-color: #E8F5E9; border-radius: 3px;")
        layout.addWidget(desc_label)

        # Settings
        settings_group = QGroupBox("Settings")
        settings_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        settings_layout = QFormLayout()
        settings_layout.setSpacing(6)

        self.snap_spinbox_isolated = QDoubleSpinBox()
        self.snap_spinbox_isolated.setDecimals(4)
        self.snap_spinbox_isolated.setMinimum(0.0001)
        self.snap_spinbox_isolated.setMaximum(1.0)
        self.snap_spinbox_isolated.setSingleStep(0.001)
        self.snap_spinbox_isolated.setValue(0.001)
        self.snap_spinbox_isolated.setSuffix(" units")

        settings_layout.addRow("Snap Tolerance:", self.snap_spinbox_isolated)

        # Add checkbox for split multipart
        self.split_multipart_checkbox_isolated = QCheckBox("Split bisected polygons into separate features")
        self.split_multipart_checkbox_isolated.setToolTip(
            "When a polygon is cut into multiple parts by the clipping polygon,\n"
            "create separate features for each part instead of keeping only the largest."
        )
        self.split_multipart_checkbox_isolated.setChecked(False)  # Default to off for compatibility
        settings_layout.addRow("", self.split_multipart_checkbox_isolated)

        # UUID field selector (shown when split is enabled)
        self.uuid_field_label_isolated = QLabel("UUID Field:")
        self.uuid_field_combo_isolated = QComboBox()
        self.uuid_field_combo_isolated.setToolTip(
            "Select the UUID field to regenerate when splitting.\n"
            "New UUIDs will be generated for split features to avoid duplicates."
        )
        self.uuid_field_label_isolated.setVisible(False)
        self.uuid_field_combo_isolated.setVisible(False)

        # Connect checkbox to show/hide UUID selector
        self.split_multipart_checkbox_isolated.toggled.connect(
            lambda checked: self._toggle_uuid_visibility('isolated', checked)
        )

        settings_layout.addRow(self.uuid_field_label_isolated, self.uuid_field_combo_isolated)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # Selection status
        status_group = QGroupBox("Selection")
        status_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        status_layout = QVBoxLayout()
        status_layout.setSpacing(4)

        self.cutter_label_isolated = QLabel("Cutters: <b>0</b> selected")
        self.target_label_isolated = QLabel("Targets: <b>0</b> selected")
        self.step_label_isolated = QLabel("Current Step: <b>1 of 2</b>")
        self.step_label_isolated.setStyleSheet("color: #FF9800; font-weight: bold;")

        status_layout.addWidget(self.step_label_isolated)
        status_layout.addWidget(self.cutter_label_isolated)
        status_layout.addWidget(self.target_label_isolated)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # Actions
        actions_group = QGroupBox("Actions")
        actions_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(6)

        self.primary_button_isolated = QPushButton("Lock Cutters & Select Targets")
        self.primary_button_isolated.setEnabled(False)
        self.primary_button_isolated.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; "
            "padding: 10px; font-weight: bold; border-radius: 4px; }"
            "QPushButton:hover:enabled { background-color: #1976D2; }"
            "QPushButton:disabled { background-color: #CCCCCC; color: #888888; }"
        )
        self.primary_button_isolated.clicked.connect(self.on_primary_isolated)

        self.clear_button_isolated = QPushButton("Clear Selection")
        self.clear_button_isolated.setEnabled(False)
        self.clear_button_isolated.setStyleSheet("padding: 8px; border-radius: 4px;")
        self.clear_button_isolated.clicked.connect(self.clearClicked.emit)

        actions_layout.addWidget(self.primary_button_isolated)
        actions_layout.addWidget(self.clear_button_isolated)
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)

        layout.addStretch()
        tab.setLayout(layout)
        return tab

    def create_clip_smart_tab(self):
        """Create Smart Clip tab content"""
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # Description
        desc_label = QLabel("<b>Smart Clip Mode</b><br>"
                           "Automatically clips smaller polygons into larger ones.<br>"
                           "Select multiple polygons - tool determines cutter/target by size.")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("padding: 6px; background-color: #FFF3E0; border-radius: 3px;")
        layout.addWidget(desc_label)

        # Settings
        settings_group = QGroupBox("Settings")
        settings_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        settings_layout = QFormLayout()
        settings_layout.setSpacing(6)

        self.snap_spinbox_smart = QDoubleSpinBox()
        self.snap_spinbox_smart.setDecimals(4)
        self.snap_spinbox_smart.setMinimum(0.0001)
        self.snap_spinbox_smart.setMaximum(1.0)
        self.snap_spinbox_smart.setSingleStep(0.001)
        self.snap_spinbox_smart.setValue(0.001)
        self.snap_spinbox_smart.setSuffix(" units")

        settings_layout.addRow("Snap Tolerance:", self.snap_spinbox_smart)

        # Add checkbox for split multipart
        self.split_multipart_checkbox = QCheckBox("Split bisected polygons into separate features")
        self.split_multipart_checkbox.setToolTip(
            "When a polygon is cut into multiple parts by the clipping polygon,\n"
            "create separate features for each part instead of keeping only the largest."
        )
        self.split_multipart_checkbox.setChecked(False)  # Default to off for compatibility
        settings_layout.addRow("", self.split_multipart_checkbox)

        # UUID field selector (shown when split is enabled)
        self.uuid_field_label_smart = QLabel("UUID Field:")
        self.uuid_field_combo_smart = QComboBox()
        self.uuid_field_combo_smart.setToolTip(
            "Select the UUID field to regenerate when splitting.\n"
            "New UUIDs will be generated for split features to avoid duplicates."
        )
        self.uuid_field_label_smart.setVisible(False)
        self.uuid_field_combo_smart.setVisible(False)

        # Connect checkbox to show/hide UUID selector
        self.split_multipart_checkbox.toggled.connect(
            lambda checked: self._toggle_uuid_visibility('smart', checked)
        )

        settings_layout.addRow(self.uuid_field_label_smart, self.uuid_field_combo_smart)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # Selection status
        status_group = QGroupBox("Selection")
        status_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        status_layout = QVBoxLayout()
        status_layout.setSpacing(4)

        self.selected_label_smart = QLabel("Selected: <b>0</b> polygons")
        status_layout.addWidget(self.selected_label_smart)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # Actions
        actions_group = QGroupBox("Actions")
        actions_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(6)

        self.execute_button_smart = QPushButton("Execute Smart Clip")
        self.execute_button_smart.setEnabled(False)
        self.execute_button_smart.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; "
            "padding: 10px; font-weight: bold; border-radius: 4px; }"
            "QPushButton:hover:enabled { background-color: #1976D2; }"
            "QPushButton:disabled { background-color: #CCCCCC; color: #888888; }"
        )
        self.execute_button_smart.clicked.connect(self.on_execute_smart)

        self.clear_button_smart = QPushButton("Clear Selection")
        self.clear_button_smart.setEnabled(False)
        self.clear_button_smart.setStyleSheet("padding: 8px; border-radius: 4px;")
        self.clear_button_smart.clicked.connect(self.clearClicked.emit)

        actions_layout.addWidget(self.execute_button_smart)
        actions_layout.addWidget(self.clear_button_smart)
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)

        layout.addStretch()
        tab.setLayout(layout)
        return tab

    def create_find_overlaps_tab(self):
        """Create Find Overlaps tab content"""
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # Description
        desc_label = QLabel("<b>Find Polygon Overlaps</b><br>"
                           "Detects areas where polygons overlap in the layer.<br>"
                           "Creates a preview showing only the overlapping regions.")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("padding: 6px; background-color: #FFE5E5; border-radius: 3px;")
        layout.addWidget(desc_label)

        # Results status
        status_group = QGroupBox("Results")
        status_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        status_layout = QVBoxLayout()
        status_layout.setSpacing(4)

        self.overlaps_count_label = QLabel("Overlaps Found: <b>0</b>")
        status_layout.addWidget(self.overlaps_count_label)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # Actions
        actions_group = QGroupBox("Actions")
        actions_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(6)

        self.find_overlaps_button = QPushButton("Find Overlaps")
        self.find_overlaps_button.setStyleSheet(
            "QPushButton { background-color: #FF5722; color: white; "
            "padding: 10px; font-weight: bold; border-radius: 4px; }"
            "QPushButton:hover { background-color: #E64A19; }"
        )
        self.find_overlaps_button.clicked.connect(self.on_find_overlaps)

        self.clear_button_overlaps = QPushButton("Clear Preview")
        self.clear_button_overlaps.setEnabled(False)
        self.clear_button_overlaps.setStyleSheet("padding: 8px; border-radius: 4px;")
        self.clear_button_overlaps.clicked.connect(self.clearClicked.emit)

        actions_layout.addWidget(self.find_overlaps_button)
        actions_layout.addWidget(self.clear_button_overlaps)
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)

        layout.addStretch()
        tab.setLayout(layout)
        return tab

    def create_find_slivers_tab(self):
        """Create Find Slivers tab content"""
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        desc_label = QLabel("<b>Find Polygon Slivers</b><br>"
                           "Detects small enclosed gaps between polygons in the layer.<br>"
                           "Creates a preview showing the sliver gap geometries.")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("padding: 6px; background-color: #E1F5FE; border-radius: 3px;")
        layout.addWidget(desc_label)

        # Settings
        settings_group = QGroupBox("Settings")
        settings_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        settings_layout = QFormLayout()
        settings_layout.setSpacing(6)

        self.min_sliver_area_spinbox = QDoubleSpinBox()
        self.min_sliver_area_spinbox.setDecimals(4)
        self.min_sliver_area_spinbox.setMinimum(0.0)
        self.min_sliver_area_spinbox.setMaximum(1_000_000.0)
        self.min_sliver_area_spinbox.setSingleStep(1.0)
        self.min_sliver_area_spinbox.setValue(1.0)
        self.min_sliver_area_spinbox.setSuffix(" units²")
        self.min_sliver_area_spinbox.setToolTip(
            "Gaps with area below this threshold are ignored.\n"
            "Set to 0 to include the very smallest gaps."
        )
        settings_layout.addRow("Min sliver area:", self.min_sliver_area_spinbox)

        self.max_sliver_area_spinbox = QDoubleSpinBox()
        self.max_sliver_area_spinbox.setDecimals(4)
        self.max_sliver_area_spinbox.setMinimum(0.0001)
        self.max_sliver_area_spinbox.setMaximum(1_000_000.0)
        self.max_sliver_area_spinbox.setSingleStep(1.0)
        self.max_sliver_area_spinbox.setValue(100.0)
        self.max_sliver_area_spinbox.setSuffix(" units²")
        self.max_sliver_area_spinbox.setToolTip(
            "Only gaps with area <= this threshold are flagged as slivers."
        )
        settings_layout.addRow("Max sliver area:", self.max_sliver_area_spinbox)

        self.sliver_snap_spinbox = QDoubleSpinBox()
        self.sliver_snap_spinbox.setDecimals(6)
        self.sliver_snap_spinbox.setMinimum(0.0)
        self.sliver_snap_spinbox.setMaximum(10.0)
        self.sliver_snap_spinbox.setSingleStep(0.001)
        self.sliver_snap_spinbox.setValue(0.001)
        self.sliver_snap_spinbox.setSuffix(" units")
        self.sliver_snap_spinbox.setToolTip(
            "Vertices on shared edges that differ by less than this distance are\n"
            "snapped together before gap detection. Suppresses false-positive\n"
            "micro-slivers caused by floating-point noise. Set to 0 to disable."
        )
        settings_layout.addRow("Snap tolerance:", self.sliver_snap_spinbox)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # Results
        status_group = QGroupBox("Results")
        status_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        status_layout = QVBoxLayout()
        status_layout.setSpacing(4)
        self.slivers_count_label = QLabel("Slivers Found: <b>0</b>")
        status_layout.addWidget(self.slivers_count_label)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # Actions
        actions_group = QGroupBox("Actions")
        actions_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(6)

        self.find_slivers_button = QPushButton("Find Slivers")
        self.find_slivers_button.setStyleSheet(
            "QPushButton { background-color: #0288D1; color: white; "
            "padding: 10px; font-weight: bold; border-radius: 4px; }"
            "QPushButton:hover { background-color: #0277BD; }"
        )
        self.find_slivers_button.clicked.connect(self.on_find_slivers)

        self.clear_button_slivers = QPushButton("Clear Preview")
        self.clear_button_slivers.setEnabled(False)
        self.clear_button_slivers.setStyleSheet("padding: 8px; border-radius: 4px;")
        self.clear_button_slivers.clicked.connect(self.clearClicked.emit)

        actions_layout.addWidget(self.find_slivers_button)
        actions_layout.addWidget(self.clear_button_slivers)
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)

        layout.addStretch()
        tab.setLayout(layout)
        return tab

    def create_fix_geometry_tab(self):
        """Create Fix Geometry tab content"""
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # Description
        desc_label = QLabel("<b>Fix Geometry Errors</b><br>"
                           "Detects and fixes invalid geometries, multipart features,<br>"
                           "and duplicate vertices in polygon layers.")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("padding: 6px; background-color: #E8F5E9; border-radius: 3px;")
        layout.addWidget(desc_label)

        # Info box
        info_box = QLabel(
            "<b>Safe Mode:</b> All fixes are done in edit mode.<br>"
            "You can undo (Ctrl+Z) if needed."
        )
        info_box.setWordWrap(True)
        info_box.setStyleSheet("padding: 4px; background-color: #FFF9C4; border-radius: 3px; font-size: 9pt;")
        layout.addWidget(info_box)

        # Results status
        status_group = QGroupBox("Detection Results")
        status_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        status_layout = QVBoxLayout()
        status_layout.setSpacing(4)

        self.geometry_issues_label = QLabel("Issues Found: <b>Not detected yet</b>")
        self.geometry_issues_breakdown = QLabel("")
        self.geometry_issues_breakdown.setWordWrap(True)
        self.geometry_issues_breakdown.setStyleSheet("font-size: 9pt; color: #666;")

        status_layout.addWidget(self.geometry_issues_label)
        status_layout.addWidget(self.geometry_issues_breakdown)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # Actions
        actions_group = QGroupBox("Actions")
        actions_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(6)

        self.detect_issues_button = QPushButton("Detect Geometry Issues")
        self.detect_issues_button.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; "
            "padding: 10px; font-weight: bold; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1976D2; }"
        )
        self.detect_issues_button.clicked.connect(self.on_detect_geometry_issues)

        self.view_issues_button = QPushButton("View Issues List")
        self.view_issues_button.setEnabled(False)
        self.view_issues_button.setStyleSheet("padding: 8px; border-radius: 4px;")
        self.view_issues_button.clicked.connect(self.on_view_geometry_issues)

        self.fix_issues_button = QPushButton("Fix All Issues")
        self.fix_issues_button.setEnabled(False)
        self.fix_issues_button.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "padding: 10px; font-weight: bold; border-radius: 4px; }"
            "QPushButton:hover:enabled { background-color: #45a049; }"
            "QPushButton:disabled { background-color: #CCCCCC; color: #888888; }"
        )
        self.fix_issues_button.clicked.connect(self.on_fix_geometry_issues)

        actions_layout.addWidget(self.detect_issues_button)
        actions_layout.addWidget(self.view_issues_button)
        actions_layout.addWidget(self.fix_issues_button)
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)

        layout.addStretch()
        tab.setLayout(layout)
        return tab

    def create_spline_settings_tab(self):
        """Create Spline Settings tab content"""
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # Description
        desc_label = QLabel("<b>Spline Interpolation Settings</b><br>"
                           "Configure spline behavior for all spline-based tools")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("padding: 6px; background-color: #F3E5F5; border-radius: 3px;")
        layout.addWidget(desc_label)

        # Spline parameters
        params_group = QGroupBox("Parameters")
        params_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        params_layout = QFormLayout()
        params_layout.setSpacing(10)

        # Tightness/Tension
        self.tightness_spinbox = QDoubleSpinBox()
        self.tightness_spinbox.setDecimals(3)
        self.tightness_spinbox.setMinimum(0.0)
        self.tightness_spinbox.setMaximum(1.0)
        self.tightness_spinbox.setSingleStep(0.05)
        self.tightness_spinbox.setValue(0.5)  # Default from spec
        self.tightness_spinbox.valueChanged.connect(self.on_spline_settings_changed)
        tightness_label = QLabel("0.0 = loose curves, 1.0 = tight curves")
        tightness_label.setStyleSheet("color: #666; font-size: 8pt;")

        # Tolerance
        self.tolerance_spinbox = QDoubleSpinBox()
        self.tolerance_spinbox.setDecimals(6)
        self.tolerance_spinbox.setMinimum(0.000001)
        self.tolerance_spinbox.setMaximum(10.0)
        self.tolerance_spinbox.setSingleStep(0.01)
        self.tolerance_spinbox.setValue(0.1)  # New default from spec
        self.tolerance_spinbox.valueChanged.connect(self.on_spline_settings_changed)
        tolerance_label = QLabel("Lower = more detail, higher = smoother")
        tolerance_label.setStyleSheet("color: #666; font-size: 8pt;")

        # Max Segments
        self.max_segments_spinbox = QSpinBox()
        self.max_segments_spinbox.setMinimum(10)
        self.max_segments_spinbox.setMaximum(500)
        self.max_segments_spinbox.setSingleStep(10)
        self.max_segments_spinbox.setValue(200)  # New default from spec
        self.max_segments_spinbox.valueChanged.connect(self.on_spline_settings_changed)
        segments_label = QLabel("Higher = smoother but slower")
        segments_label.setStyleSheet("color: #666; font-size: 8pt;")

        params_layout.addRow("Tightness / Tension:", self.tightness_spinbox)
        params_layout.addRow("", tightness_label)
        params_layout.addRow("Tolerance:", self.tolerance_spinbox)
        params_layout.addRow("", tolerance_label)
        params_layout.addRow("Max Segments:", self.max_segments_spinbox)
        params_layout.addRow("", segments_label)

        params_group.setLayout(params_layout)
        layout.addWidget(params_group)

        # Reset to defaults button
        reset_defaults_btn = QPushButton("Restore Defaults")
        reset_defaults_btn.setStyleSheet("padding: 8px; border-radius: 4px;")
        reset_defaults_btn.clicked.connect(self.restore_spline_defaults)
        layout.addWidget(reset_defaults_btn)

        # Apply button
        apply_btn = QPushButton("Apply Settings")
        apply_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "padding: 10px; font-weight: bold; border-radius: 4px; }"
            "QPushButton:hover { background-color: #45a049; }"
        )
        apply_btn.clicked.connect(self.apply_spline_settings)
        layout.addWidget(apply_btn)

        layout.addStretch()
        tab.setLayout(layout)
        return tab

    # Map tab text to mode name
    TAB_MODE_MAP = {
        'Clip All': 'clip_all',
        'Clip Isolated': 'clip_isolated',
        'Smart Clip': 'clip_smart',
        'Find Overlaps': 'find_overlaps',
        'Find Slivers': 'find_slivers',
        'Fix Geometry': 'fix_geometry',
    }

    def on_tab_changed(self, index):
        """Handle tab change"""
        tab_text = self.tab_widget.tabText(index)
        mode = self.TAB_MODE_MAP.get(tab_text)
        if mode is None:
            # Non-mode tabs (e.g. Spline Settings) - no mode change
            return

        self.mode = mode
        self.modeChanged.emit(self.mode)

    def on_execute_all(self):
        """Execute clip all"""
        self.mode = 'clip_all'
        self.executeClicked.emit()

    def on_primary_isolated(self):
        """Handle primary button in isolated mode"""
        if self.isolated_step == 1:
            self.lockCuttersClicked.emit()
        else:
            self.mode = 'clip_isolated'
            self.executeClicked.emit()

    def on_execute_smart(self):
        """Execute smart clip"""
        self.mode = 'clip_smart'
        self.executeClicked.emit()

    def on_find_overlaps(self):
        """Execute find overlaps"""
        self.mode = 'find_overlaps'
        self.findOverlapsClicked.emit()

    def on_find_slivers(self):
        """Execute find slivers"""
        self.mode = 'find_slivers'
        self.findSliversClicked.emit()

    def get_max_sliver_area(self):
        """Return the user-configured max sliver area threshold"""
        return self.max_sliver_area_spinbox.value()

    def get_min_sliver_area(self):
        """Return the user-configured min sliver area threshold"""
        return self.min_sliver_area_spinbox.value()

    def get_sliver_snap_tolerance(self):
        """Return the user-configured snap tolerance for sliver pre-processing"""
        return self.sliver_snap_spinbox.value()

    def on_detect_geometry_issues(self):
        """Detect geometry issues"""
        self.mode = 'fix_geometry'
        self.detectGeometryIssuesClicked.emit()

    def on_view_geometry_issues(self):
        """View geometry issues list"""
        self.viewGeometryIssuesClicked.emit()

    def on_fix_geometry_issues(self):
        """Fix all geometry issues"""
        self.fixGeometryIssuesClicked.emit()

    def on_spline_settings_changed(self):
        """Called when any spline setting changes"""
        # Settings are saved to QSettings automatically
        pass

    def apply_spline_settings(self):
        """Apply spline settings"""
        from qgis.PyQt.QtCore import QSettings
        from ..core.utils import SETTINGS_NAME

        settings = QSettings()
        settings.setValue(f"{SETTINGS_NAME}/tightness", self.tightness_spinbox.value())
        settings.setValue(f"{SETTINGS_NAME}/tolerance", self.tolerance_spinbox.value())
        settings.setValue(f"{SETTINGS_NAME}/max_segments", self.max_segments_spinbox.value())

        self.splineSettingsChanged.emit()
        self.update_status("Spline settings applied!", 'success')

    def restore_spline_defaults(self):
        """Restore default spline values"""
        self.tightness_spinbox.setValue(0.5)
        self.tolerance_spinbox.setValue(0.1)
        self.max_segments_spinbox.setValue(200)
        self.update_status("Defaults restored", 'info')

    def load_spline_settings(self):
        """Load spline settings from QSettings"""
        from qgis.PyQt.QtCore import QSettings
        from ..core.utils import SETTINGS_NAME, DEFAULT_TIGHTNESS, DEFAULT_TOLERANCE, DEFAULT_MAX_SEGMENTS

        settings = QSettings()
        tightness = settings.value(f"{SETTINGS_NAME}/tightness", DEFAULT_TIGHTNESS, float)
        tolerance = settings.value(f"{SETTINGS_NAME}/tolerance", DEFAULT_TOLERANCE, float)
        max_segments = settings.value(f"{SETTINGS_NAME}/max_segments", DEFAULT_MAX_SEGMENTS, int)

        self.tightness_spinbox.setValue(tightness)
        self.tolerance_spinbox.setValue(tolerance)
        self.max_segments_spinbox.setValue(max_segments)

    def advance_to_step_2(self):
        """Move to step 2 of isolated mode"""
        self.isolated_step = 2
        self.primary_button_isolated.setText("Execute Clip Preview")
        self.step_label_isolated.setText("Current Step: <b>2 of 2</b>")
        self.update_status("Step 2: Select target polygons to clip", 'info')

    def reset_to_step_1(self):
        """Reset to step 1"""
        self.isolated_step = 1
        self.primary_button_isolated.setText("Lock Cutters & Select Targets")
        self.step_label_isolated.setText("Current Step: <b>1 of 2</b>")

    def update_selection_counts(self, cutter_count, target_count):
        """Update selection count labels"""
        # Update all tabs
        self.cutter_label_all.setText(f"Cutter: <b>{cutter_count}</b> selected")
        self.cutter_label_isolated.setText(f"Cutters: <b>{cutter_count}</b> selected")
        self.target_label_isolated.setText(f"Targets: <b>{target_count}</b> selected")
        self.selected_label_smart.setText(f"Selected: <b>{cutter_count}</b> polygons")

        # Update button states
        self.update_button_states(cutter_count, target_count)

    def update_button_states(self, cutter_count, target_count):
        """Enable/disable buttons based on selections"""
        # Clip All tab
        self.execute_button_all.setEnabled(cutter_count == 1)
        self.clear_button_all.setEnabled(cutter_count > 0)

        # Clip Isolated tab
        if self.isolated_step == 1:
            self.primary_button_isolated.setEnabled(cutter_count > 0)
            self.clear_button_isolated.setEnabled(cutter_count > 0)
        else:
            self.primary_button_isolated.setEnabled(target_count > 0)
            self.clear_button_isolated.setEnabled(True)

        # Smart Clip tab
        self.execute_button_smart.setEnabled(cutter_count >= 2)
        self.clear_button_smart.setEnabled(cutter_count > 0)

    def update_overlaps_count(self, count, bisecting_count=0):
        """Update overlaps count label with optional bisecting breakdown"""
        if bisecting_count > 0:
            self.overlaps_count_label.setText(
                f"Overlaps Found: <b>{count}</b> (<b>{bisecting_count}</b> bisecting)"
            )
        else:
            self.overlaps_count_label.setText(f"Overlaps Found: <b>{count}</b>")
        self.clear_button_overlaps.setEnabled(count > 0)

    def update_slivers_count(self, count):
        """Update sliver count label"""
        self.slivers_count_label.setText(f"Slivers Found: <b>{count}</b>")
        self.clear_button_slivers.setEnabled(count > 0)

    def update_geometry_issues(self, total_issues, issue_stats):
        """
        Update geometry issues display.

        Args:
            total_issues: int - total number of issues found
            issue_stats: dict - breakdown of issues by type
        """
        if total_issues == 0:
            self.geometry_issues_label.setText("Issues Found: <b>0</b> (All geometries valid)")
            self.geometry_issues_breakdown.setText("")
            self.view_issues_button.setEnabled(False)
            self.fix_issues_button.setEnabled(False)
        else:
            self.geometry_issues_label.setText(f"Issues Found: <b>{total_issues}</b>")

            # Build breakdown text
            parts = []
            if issue_stats.get('invalid', 0) > 0:
                parts.append(f"• <b>{issue_stats['invalid']}</b> invalid geometries")
            if issue_stats.get('multipart', 0) > 0:
                parts.append(f"• <b>{issue_stats['multipart']}</b> multipart features")
            if issue_stats.get('duplicate_vertices', 0) > 0:
                parts.append(f"• <b>{issue_stats['duplicate_vertices']}</b> with duplicate vertices")
            if issue_stats.get('empty', 0) > 0:
                parts.append(f"• <b>{issue_stats['empty']}</b> empty/null geometries")

            self.geometry_issues_breakdown.setText("<br>".join(parts))
            self.view_issues_button.setEnabled(True)
            self.fix_issues_button.setEnabled(True)

    def update_status(self, message, level='info'):
        """Update status message with color coding"""
        colors = {
            'info': '#2196F3',
            'success': '#4CAF50',
            'warning': '#FF9800',
            'error': '#F44336'
        }

        color = colors.get(level, colors['info'])
        self.status_text.setText(message)
        self.status_text.setStyleSheet(f"padding: 5px; color: {color}; font-weight: bold;")

    def get_current_layer(self):
        """Get currently selected layer"""
        return self.layer_combo.currentLayer()

    def get_mode(self):
        """Get current clipping mode"""
        return self.mode

    def get_snap_tolerance(self):
        """Get snap tolerance value from active tab"""
        if self.mode == 'clip_all':
            return self.snap_spinbox_all.value()
        elif self.mode == 'clip_isolated':
            return self.snap_spinbox_isolated.value()
        else:  # clip_smart
            return self.snap_spinbox_smart.value()

    def _toggle_uuid_visibility(self, tab_name, visible):
        """Toggle visibility of UUID field selector for a specific tab"""
        if tab_name == 'all':
            self.uuid_field_label_all.setVisible(visible)
            self.uuid_field_combo_all.setVisible(visible)
            if visible:
                self._populate_uuid_combo(self.uuid_field_combo_all)
        elif tab_name == 'isolated':
            self.uuid_field_label_isolated.setVisible(visible)
            self.uuid_field_combo_isolated.setVisible(visible)
            if visible:
                self._populate_uuid_combo(self.uuid_field_combo_isolated)
        elif tab_name == 'smart':
            self.uuid_field_label_smart.setVisible(visible)
            self.uuid_field_combo_smart.setVisible(visible)
            if visible:
                self._populate_uuid_combo(self.uuid_field_combo_smart)

    def _populate_uuid_combo(self, combo):
        """Populate a UUID combo box with candidate fields from current layer"""
        combo.clear()

        # Add default options
        combo.addItem("Auto-detect", "auto")
        combo.addItem("None - Keep original UUIDs", None)

        layer = self.get_current_layer()
        if not layer:
            return

        # Get candidate fields
        candidates = get_candidate_uuid_fields(layer)

        # Add separator if we have candidates
        if candidates:
            combo.insertSeparator(2)

        # Add candidate fields
        for display_name, field_name in candidates:
            combo.addItem(display_name, field_name)

        # If auto-detect finds a UUID field, select it by default
        detected = detect_uuid_field(layer)
        if detected:
            # Find and select the detected field
            for i in range(combo.count()):
                if combo.itemData(i) == detected:
                    combo.setCurrentIndex(i)
                    break

    def populate_uuid_fields(self):
        """Populate all UUID combo boxes with fields from current layer"""
        self._populate_uuid_combo(self.uuid_field_combo_all)
        self._populate_uuid_combo(self.uuid_field_combo_isolated)
        self._populate_uuid_combo(self.uuid_field_combo_smart)

    def get_uuid_field(self):
        """
        Get the selected UUID field name for the current mode.

        Returns:
            str or None - field name for UUID regeneration, or None to keep original
        """
        if self.mode == 'clip_all':
            if not self.split_multipart_checkbox_all.isChecked():
                return None
            combo = self.uuid_field_combo_all
        elif self.mode == 'clip_isolated':
            if not self.split_multipart_checkbox_isolated.isChecked():
                return None
            combo = self.uuid_field_combo_isolated
        else:  # clip_smart
            if not self.split_multipart_checkbox.isChecked():
                return None
            combo = self.uuid_field_combo_smart

        selected_data = combo.currentData()

        # Handle special cases
        if selected_data == "auto":
            # Auto-detect UUID field
            return detect_uuid_field(self.get_current_layer())
        elif selected_data is None:
            # User explicitly chose to keep original UUIDs
            return None
        else:
            # User selected a specific field
            return selected_data

    def on_layer_changed(self, layer):
        """Handle layer combo box change"""
        # Repopulate UUID combos when layer changes
        self.populate_uuid_fields()
        self.layerChanged.emit(layer)

    def closeEvent(self, event):
        """Handle dock widget close event"""
        self.closingPanel.emit()
        event.ignore()
        self.setVisible(False)
