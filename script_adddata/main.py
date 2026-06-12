#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Enhanced GeoPackage Append Tool - Main Window
----------------------------------------------
Main application window and tree widget for the GeoPackage Append Tool.
Integrates all refactored modules into a cohesive user interface.
"""

import os
from typing import Dict, List, Optional

# PyQt imports (using qgis.PyQt for forward compatibility with PyQt6)
from qgis.PyQt.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QFileDialog, QCheckBox, QSlider,
    QTextEdit, QProgressBar, QMessageBox, QTreeWidget, QTreeWidgetItem,
    QAbstractItemView, QComboBox, QScrollArea
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtSql import QSqlDatabase, QSqlQuery

# QGIS imports
from qgis.core import QgsVectorLayer, QgsFeatureRequest, QgsMessageLog, Qgis

# Import from refactored modules
from .utils import (
    LayerRecoding, EXCLUDED_FIELDS, FUZZY_MATCHING_AVAILABLE,
    NO_UUID_FIELD, NO_UUID_DISPLAY, is_date_field, find_matching_field,
    detect_uuid_field as utils_detect_uuid_field
)
from .metadata import UUIDTracker, MetadataManager
from .date_filter import EnhancedTimezoneSelector, GlobalDateFilterWidget
from .templates import TemplateManager
from .preview import EnhancedPreviewDialog
from .recoding_unified import UnifiedRecodingDialog
from .data_processing import WorkerThread
from ..ui_scaling import get_scale_manager


class LayerFieldTreeWidget(QTreeWidget):
    """Custom tree widget for integrated layer and field selection"""
    selection_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        scale = get_scale_manager()
        self.setHeaderLabels(["Item", "Type", "UUID Field", "Recoding"])
        self.setColumnWidth(0, scale.dimension(250))
        self.setColumnWidth(1, scale.dimension(100))
        self.setColumnWidth(2, scale.dimension(100))
        self.setColumnWidth(3, scale.dimension(100))

        # Enable extended selection
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

        # Store references
        self.layer_items = {}
        self.layer_recodings = {}

    def add_layer(self, layer_name, layer_info):
        """Add a layer to the tree"""
        layer_item = QTreeWidgetItem(self)
        layer_item.setText(0, layer_name)
        layer_item.setText(1, "Layer")
        layer_item.setCheckState(0, Qt.Checked)  # Checked by default
        layer_item.setExpanded(False)  # Collapsed by default

        # Style the layer item
        font = layer_item.font(0)
        font.setBold(True)
        layer_item.setFont(0, font)
        layer_item.setBackground(0, QColor(240, 240, 240))

        # Add UUID field selector
        uuid_combo = QComboBox()
        # Add "No UUID" option first for layers without UUID fields
        uuid_combo.addItem(NO_UUID_DISPLAY)
        uuid_combo.addItems(layer_info.get('fields', []))

        detected_uuid = layer_info.get('detected_uuid')
        if detected_uuid:
            idx = uuid_combo.findText(detected_uuid)
            if idx >= 0:
                uuid_combo.setCurrentIndex(idx)
        # If no UUID detected, keep "No UUID" selected (index 0)

        # Style combo to indicate warning when "No UUID" is selected
        uuid_combo.currentTextChanged.connect(
            lambda text, combo=uuid_combo: self._style_uuid_combo(combo, text)
        )
        self._style_uuid_combo(uuid_combo, uuid_combo.currentText())

        self.setItemWidget(layer_item, 2, uuid_combo)

        # Add recoding button
        recoding_btn = QPushButton("Configure")
        recoding_btn.setMaximumWidth(get_scale_manager().dimension(100))
        recoding_btn.clicked.connect(lambda: self.configure_recoding(layer_name))
        self.setItemWidget(layer_item, 3, recoding_btn)

        # Add duplicate analysis info
        duplicate_info = layer_info.get('duplicate_analysis', {})
        if duplicate_info:
            cutoff_date = duplicate_info.get('cutoff_date')
            duplicate_count = duplicate_info.get('duplicate_count', 0)
            total_count = duplicate_info.get('total_count', 0)

            if cutoff_date:
                info_text = f"Duplicates <{cutoff_date}, New >{cutoff_date} ({duplicate_count}/{total_count})"
            else:
                info_text = f"No existing data in master ({total_count} source records)"

            layer_item.setToolTip(0, info_text)
            # Add visual indicator
            if duplicate_count > 0:
                layer_item.setBackground(1, QColor(255, 255, 200))  # Light yellow for layers with duplicates

        self.layer_items[layer_name] = {
            'item': layer_item,
            'uuid_combo': uuid_combo,
            'fields': {},
            'field_info': layer_info.get('field_info', {}),
            'date_fields': layer_info.get('date_fields', []),
            'duplicate_analysis': layer_info.get('duplicate_analysis', {})
        }

        # Add fields
        for field_name in layer_info.get('fields', []):
            self.add_field(layer_name, field_name, field_name.lower() not in EXCLUDED_FIELDS)

        return layer_item

    def add_field(self, layer_name, field_name, checked=True):
        """Add a field to a layer"""
        if layer_name not in self.layer_items:
            return

        layer_item = self.layer_items[layer_name]['item']
        field_item = QTreeWidgetItem(layer_item)
        field_item.setText(0, field_name)
        field_item.setText(1, "Field")
        field_item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)

        self.layer_items[layer_name]['fields'][field_name] = field_item

        # Update visual indicators if recoding exists
        self.update_recoding_indicators(layer_name)

    def configure_recoding(self, layer_name):
        """Open recoding configuration dialog"""
        if layer_name not in self.layer_items:
            return

        # Get source fields
        source_fields = self.layer_items[layer_name]['field_info']

        # Get master and source GeoPackage paths from parent
        parent_window = self.window()
        master_gpkg = parent_window.master_input.text().strip()
        source_gpkg = parent_window.source_input.text().strip()

        if not master_gpkg:
            QMessageBox.warning(self, "Configuration Error",
                                "Please select a master GeoPackage first")
            return

        existing_recoding = self.layer_recodings.get(layer_name)

        # UPDATED: Use UnifiedRecodingDialog instead of RecodingDialog
        dialog = UnifiedRecodingDialog(layer_name, source_fields, master_gpkg,
                                       source_gpkg, existing_recoding, self)

        if dialog.exec():
            recoding = dialog.get_recoding()
            self.layer_recodings[layer_name] = recoding
            self.update_recoding_indicators(layer_name)

    def update_recoding_indicators(self, layer_name):
        """Update visual indicators for recodings"""
        if layer_name not in self.layer_items:
            return

        recoding = self.layer_recodings.get(layer_name)
        if not recoding:
            return

        layer_item = self.layer_items[layer_name]['item']

        # Update layer indicator
        if recoding.target_layer or recoding.field_mappings or recoding.value_recodings:
            layer_item.setBackground(3, QColor(200, 255, 200))
            tooltip_parts = []
            if recoding.target_layer:
                tooltip_parts.append(f"Target: {recoding.target_layer}")
            if recoding.field_mappings:
                tooltip_parts.append(f"{len(recoding.field_mappings)} field mappings")
            if recoding.value_recodings:
                # Count total manual mappings
                total_mappings = sum(len(vr.manual_mappings) for vr in recoding.value_recodings.values())
                tooltip_parts.append(f"{len(recoding.value_recodings)} fields with {total_mappings} value mappings")
            layer_item.setToolTip(3, "\n".join(tooltip_parts))
        else:
            layer_item.setBackground(3, QColor())
            layer_item.setToolTip(3, "")

        # Update field indicators
        for field_name, field_item in self.layer_items[layer_name]['fields'].items():
            if field_name in recoding.field_mappings:
                field_item.setBackground(0, QColor(255, 255, 200))
                field_item.setToolTip(0, f"Mapped to: {recoding.field_mappings[field_name]}")
            elif field_name in recoding.value_recodings:
                field_item.setBackground(0, QColor(200, 200, 255))
                mappings_count = len(recoding.value_recodings[field_name].manual_mappings)
                field_item.setToolTip(0, f"Value recoding configured: {mappings_count} mappings")
            else:
                field_item.setBackground(0, QColor())
                field_item.setToolTip(0, "")

    def get_selected_layers(self):
        """Get list of checked layers"""
        selected = []
        for layer_name, layer_info in self.layer_items.items():
            if layer_info['item'].checkState(0) == Qt.Checked:
                selected.append(layer_name)
        return selected

    def get_selected_fields(self, layer_name):
        """Get list of checked fields for a layer"""
        if layer_name not in self.layer_items:
            return []

        selected = []
        for field_name, field_item in self.layer_items[layer_name]['fields'].items():
            if field_item.checkState(0) == Qt.Checked:
                selected.append(field_name)
        return selected

    def get_uuid_field(self, layer_name):
        """Get selected UUID field for a layer. Returns NO_UUID_FIELD constant if 'No UUID' is selected."""
        if layer_name in self.layer_items:
            selected = self.layer_items[layer_name]['uuid_combo'].currentText()
            if selected == NO_UUID_DISPLAY:
                return NO_UUID_FIELD
            return selected
        return None

    def _style_uuid_combo(self, combo, text):
        """Style the UUID combo box based on selection"""
        if text == NO_UUID_DISPLAY:
            combo.setStyleSheet("QComboBox { background-color: #fff3cd; border: 1px solid #ffc107; }")
            combo.setToolTip("No duplicate checking - ALL features will be added")
        else:
            combo.setStyleSheet("")
            combo.setToolTip(f"Using '{text}' for duplicate detection")

    def has_no_uuid_layers(self):
        """Check if any selected layer has 'No UUID' mode enabled"""
        for layer_name in self.get_selected_layers():
            if self.get_uuid_field(layer_name) == NO_UUID_FIELD:
                return True
        return False

    def get_no_uuid_layer_names(self):
        """Get list of selected layers with 'No UUID' mode"""
        no_uuid_layers = []
        for layer_name in self.get_selected_layers():
            if self.get_uuid_field(layer_name) == NO_UUID_FIELD:
                no_uuid_layers.append(layer_name)
        return no_uuid_layers


class GeoPackageAppendTool(QMainWindow):
    """Main application window for the Enhanced GeoPackage Append Tool"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scale = get_scale_manager()
        self.setWindowTitle("Enhanced GeoPackage Append Tool with Recoding")
        w, h = self.scale.dialog_size(1000, 700)
        self.setGeometry(300, 300, w, h)
        self.setup_ui()
        self.worker = None
        self.source_gpkg = ""
        self.master_gpkg = ""

    def setup_ui(self):
        # IMPROVE 3: wrap content in scroll area for smaller screens
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        main_widget = QWidget()
        main_layout = QVBoxLayout()

        # File selection section
        file_group = QGroupBox("File Selection")
        file_layout = QVBoxLayout()

        source_layout = QHBoxLayout()
        source_label = QLabel("Source GeoPackage:")
        self.source_input = QLineEdit()
        source_button = QPushButton("Browse...")
        source_button.clicked.connect(self.browse_source)
        source_layout.addWidget(source_label)
        source_layout.addWidget(self.source_input)
        source_layout.addWidget(source_button)

        master_layout = QHBoxLayout()
        master_label = QLabel("Master GeoPackage:")
        self.master_input = QLineEdit()
        master_button = QPushButton("Browse...")
        master_button.clicked.connect(self.browse_master)
        master_layout.addWidget(master_label)
        master_layout.addWidget(self.master_input)
        master_layout.addWidget(master_button)

        file_layout.addLayout(source_layout)
        file_layout.addLayout(master_layout)
        file_group.setLayout(file_layout)

        # UUID configuration
        uuid_layout = QHBoxLayout()
        uuid_label = QLabel("Default UUID Field:")
        self.uuid_input = QLineEdit("UUID")
        self.auto_detect_uuid = QCheckBox("Auto-detect UUID fields")
        self.auto_detect_uuid.setChecked(True)
        uuid_layout.addWidget(uuid_label)
        uuid_layout.addWidget(self.uuid_input)
        uuid_layout.addWidget(self.auto_detect_uuid)

        # UPDATED: Global date filter using enhanced version
        self.global_date_filter = GlobalDateFilterWidget()

        # Fuzzy matching threshold
        fuzzy_layout = QHBoxLayout()
        if FUZZY_MATCHING_AVAILABLE:
            fuzzy_label = QLabel("Fuzzy Match Threshold:")
            self.fuzzy_threshold = QSlider(Qt.Horizontal)
            self.fuzzy_threshold.setMinimum(50)
            self.fuzzy_threshold.setMaximum(90)
            self.fuzzy_threshold.setValue(75)
            self.fuzzy_threshold.setTickPosition(QSlider.TicksBelow)
            self.fuzzy_threshold.setTickInterval(5)
            self.fuzzy_threshold_value = QLabel("75%")
            self.fuzzy_threshold.valueChanged.connect(self.update_fuzzy_threshold)
            fuzzy_layout.addWidget(fuzzy_label)
            fuzzy_layout.addWidget(self.fuzzy_threshold)
            fuzzy_layout.addWidget(self.fuzzy_threshold_value)
        else:
            fuzzy_not_available = QLabel("(Fuzzy matching not available: install fuzzywuzzy for better UUID detection)")
            fuzzy_not_available.setStyleSheet("color: gray;")
            fuzzy_layout.addWidget(fuzzy_not_available)

        # Load button
        load_button = QPushButton("Load Layers and Fields")
        load_button.clicked.connect(self.load_layers)

        # Main content area - integrated tree view
        content_group = QGroupBox("Layer and Field Selection with Recoding")
        content_layout = QVBoxLayout()

        # Instructions
        instructions = QLabel(
            "Select layers and fields to process. Use 'Configure' to set up layer mapping, field mapping, and value recoding.")
        instructions.setWordWrap(True)
        content_layout.addWidget(instructions)

        # Action buttons
        action_layout = QHBoxLayout()
        select_all_layers_btn = QPushButton("Select All Layers")
        select_all_layers_btn.clicked.connect(self.select_all_layers)
        deselect_all_layers_btn = QPushButton("Deselect All Layers")
        deselect_all_layers_btn.clicked.connect(self.deselect_all_layers)
        expand_all_btn = QPushButton("Expand All")
        expand_all_btn.clicked.connect(lambda: self.tree_widget.expandAll())
        collapse_all_btn = QPushButton("Collapse All")
        collapse_all_btn.clicked.connect(lambda: self.tree_widget.collapseAll())

        action_layout.addWidget(select_all_layers_btn)
        action_layout.addWidget(deselect_all_layers_btn)
        action_layout.addWidget(expand_all_btn)
        action_layout.addWidget(collapse_all_btn)
        action_layout.addStretch()

        # Tree widget
        self.tree_widget = LayerFieldTreeWidget()

        content_layout.addLayout(action_layout)
        content_layout.addWidget(self.tree_widget)
        content_group.setLayout(content_layout)

        # Progress and log area
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        log_label = QLabel("Processing Log:")
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(self.scale.dimension(150))

        # Control buttons
        button_layout = QHBoxLayout()
        self.preview_button = QPushButton("Preview Changes")
        self.preview_button.clicked.connect(self.preview_changes)
        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self.run_process)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_process)
        self.cancel_button.setEnabled(False)

        button_layout.addWidget(self.preview_button)
        button_layout.addStretch()
        button_layout.addWidget(self.run_button)
        button_layout.addWidget(self.cancel_button)

        # Add all to main layout
        main_layout.addWidget(file_group)
        main_layout.addLayout(uuid_layout)
        main_layout.addLayout(fuzzy_layout)
        main_layout.addWidget(self.global_date_filter)
        main_layout.addWidget(load_button)
        main_layout.addWidget(content_group)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(log_label)
        main_layout.addWidget(self.log_area)
        main_layout.addLayout(button_layout)


        main_widget.setLayout(main_layout)
        scroll_area.setWidget(main_widget)
        self.setCentralWidget(scroll_area)

    def reset_ui(self):
        """Reset UI to clean state for new session"""
        self.log_area.clear()
        self.progress_bar.setValue(0)
        self.tree_widget.clear()
        self.tree_widget.layer_items.clear()
        self.tree_widget.layer_recodings.clear()
        self.run_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def update_fuzzy_threshold(self, value):
        if hasattr(self, 'fuzzy_threshold_value'):
            self.fuzzy_threshold_value.setText(f"{value}%")

    def browse_source(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Source GeoPackage", "", "GeoPackage Files (*.gpkg)"
        )
        if file_path:
            self.source_input.setText(file_path)
            self.source_gpkg = file_path

    def analyze_duplicates_for_layer(self, layer_name, source_layer, uuid_field):
        """Analyze duplicate data ranges for a layer"""
        master_gpkg = self.master_input.text().strip()
        if not master_gpkg or not os.path.exists(master_gpkg):
            return {}

        try:
            # Check if layer exists in master
            master_uri = f"{master_gpkg}|layername={layer_name}"
            master_layer = QgsVectorLayer(master_uri, layer_name, "ogr")

            if not master_layer.isValid():
                # No master layer exists - all source data is new
                total_count = source_layer.featureCount()
                return {
                    'cutoff_date': None,
                    'duplicate_count': 0,
                    'total_count': total_count,
                    'analysis': 'no_master_layer'
                }

            # Find date fields in both layers
            source_date_fields = []
            master_date_fields = []

            for field in source_layer.fields():
                if is_date_field(field):
                    source_date_fields.append(field.name())

            for field in master_layer.fields():
                if is_date_field(field):
                    master_date_fields.append(field.name())

            # Find common date field
            common_date_field = None
            for source_field in source_date_fields:
                if source_field in master_date_fields:
                    common_date_field = source_field
                    break

            if not common_date_field:
                # No date field to analyze
                return {
                    'cutoff_date': None,
                    'duplicate_count': 0,
                    'total_count': source_layer.featureCount(),
                    'analysis': 'no_date_field'
                }

            # Get UUID field in master
            master_field_names = [field.name() for field in master_layer.fields()]
            uuid_field_in_master = find_matching_field(master_field_names, uuid_field)

            if not uuid_field_in_master:
                return {
                    'cutoff_date': None,
                    'duplicate_count': 0,
                    'total_count': source_layer.featureCount(),
                    'analysis': 'no_uuid_field'
                }

            # Collect existing UUIDs and their dates from master.
            # Attribute-subset + NoGeometry request - this runs on the UI
            # thread, so keep it as light as possible
            master_uuid_idx = master_layer.fields().lookupField(uuid_field_in_master)
            master_date_idx = master_layer.fields().lookupField(common_date_field)
            request = (QgsFeatureRequest()
                       .setFlags(QgsFeatureRequest.NoGeometry)
                       .setSubsetOfAttributes([master_uuid_idx, master_date_idx]))
            existing_data = {}  # {uuid: date}
            for feature in master_layer.getFeatures(request):
                uuid_val = feature[master_uuid_idx]
                date_val = feature[master_date_idx]
                if uuid_val and date_val:
                    existing_data[str(uuid_val)] = date_val

            if not existing_data:
                return {
                    'cutoff_date': None,
                    'duplicate_count': 0,
                    'total_count': source_layer.featureCount(),
                    'analysis': 'no_existing_data'
                }

            # Find the latest date in existing data
            latest_existing_date = max(existing_data.values())

            # Count duplicates and analyze source data
            duplicate_count = 0
            total_source_count = 0

            source_uuid_idx = source_layer.fields().lookupField(uuid_field)
            source_request = (QgsFeatureRequest()
                              .setFlags(QgsFeatureRequest.NoGeometry)
                              .setSubsetOfAttributes([source_uuid_idx]))
            for feature in source_layer.getFeatures(source_request):
                total_source_count += 1
                uuid_val = feature[source_uuid_idx]
                if uuid_val and str(uuid_val) in existing_data:
                    duplicate_count += 1

            # Format the cutoff date
            if hasattr(latest_existing_date, 'toString'):
                cutoff_date_str = latest_existing_date.toString("dd/MM/yy")
            else:
                cutoff_date_str = latest_existing_date.strftime("%d/%m/%y")

            return {
                'cutoff_date': cutoff_date_str,
                'duplicate_count': duplicate_count,
                'total_count': total_source_count,
                'latest_master_date': latest_existing_date,
                'analysis': 'success'
            }

        except Exception as e:
            QgsMessageLog.logMessage(f"Error analyzing duplicates for {layer_name}: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            return {
                'cutoff_date': None,
                'duplicate_count': 0,
                'total_count': 0,
                'analysis': f'error: {str(e)}'
            }

    def browse_master(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Select or Create Master GeoPackage", "", "GeoPackage Files (*.gpkg)",
            options=QFileDialog.DontConfirmOverwrite
        )
        if file_path:
            # Ensure .gpkg extension
            if not file_path.lower().endswith('.gpkg'):
                file_path += '.gpkg'
            self.master_input.setText(file_path)
            self.master_gpkg = file_path

    def detect_uuid_field(self, field_names):
        """Auto-detect UUID field from field names"""
        if not field_names:
            return None

        # Check user-specified default UUID field first
        default_uuid = self.uuid_input.text().strip()
        if default_uuid:
            if default_uuid in field_names:
                return default_uuid
            for field in field_names:
                if field.lower() == default_uuid.lower():
                    return field

        if not self.auto_detect_uuid.isChecked():
            return None

        # IMPROVE 5: delegate to utils.detect_uuid_field instead of reimplementing
        threshold = self.fuzzy_threshold.value() if hasattr(self, 'fuzzy_threshold') else 75
        return utils_detect_uuid_field(field_names, fuzzy_threshold=threshold)

    def load_layers(self):
        """Load layers from source GeoPackage with duplicate analysis"""
        source_gpkg_path = self.source_input.text().strip()
        if not source_gpkg_path:
            QMessageBox.warning(self, "Input Error", "Please select a source GeoPackage.")
            return
        if not os.path.exists(source_gpkg_path):
            QMessageBox.warning(self, "Input Error", f"Source GeoPackage does not exist: {source_gpkg_path}")
            return

        self.source_gpkg = source_gpkg_path
        self.master_gpkg = self.master_input.text().strip()
        self.log_message(f"Loading layers from: {self.source_gpkg}")

        # Clear existing items
        self.tree_widget.clear()
        self.tree_widget.layer_items.clear()
        self.tree_widget.layer_recodings.clear()

        # BUG 12 fix: use try/finally to ensure DB connection cleanup
        connection_name = f"gpkg_connection_load_{os.path.basename(self.source_gpkg).replace('.', '_')}"
        try:
            # Connect to GeoPackage
            if QSqlDatabase.contains(connection_name):
                QSqlDatabase.removeDatabase(connection_name)

            db = QSqlDatabase.addDatabase("QSQLITE", connection_name)
            db.setDatabaseName(self.source_gpkg)

            if not db.open():
                QMessageBox.critical(self, "DB Error", f"Could not open GeoPackage: {db.lastError().text()}")
                return

            query_str = ("SELECT table_name, data_type FROM gpkg_contents "
                         "WHERE data_type IN ('features', 'attributes')")
            query = QSqlQuery(db)
            if not query.exec(query_str):
                QMessageBox.critical(self, "Query Error", f"Failed to query gpkg_contents: {query.lastError().text()}")
                return

            layer_count = 0
            while query.next():
                layer_name = query.value(0)

                # Open layer to get fields
                layer_uri = f"{self.source_gpkg}|layername={layer_name}"
                layer = QgsVectorLayer(layer_uri, layer_name, "ogr")

                if layer.isValid():
                    field_names = [field.name() for field in layer.fields()]
                    field_info = {}
                    date_fields = []

                    for field in layer.fields():
                        field_info[field.name()] = field
                        # Check if field is a date/datetime field
                        if is_date_field(field):
                            date_fields.append(field.name())

                    detected_uuid = self.detect_uuid_field(field_names)

                    # Perform duplicate analysis
                    duplicate_analysis = {}
                    if detected_uuid:
                        self.log_message(f"Analyzing duplicates for layer '{layer_name}'...")
                        duplicate_analysis = self.analyze_duplicates_for_layer(layer_name, layer, detected_uuid)

                    layer_info = {
                        'fields': field_names,
                        'field_info': field_info,
                        'date_fields': date_fields,
                        'detected_uuid': detected_uuid,
                        'duplicate_analysis': duplicate_analysis,
                        'crs': layer.crs().authid() if layer.crs().isValid() else "N/A"
                    }

                    self.tree_widget.add_layer(layer_name, layer_info)
                    layer_count += 1

                    if detected_uuid:
                        self.log_message(f"Layer '{layer_name}': Auto-detected UUID field '{detected_uuid}'")
                    if date_fields:
                        self.log_message(
                            f"Layer '{layer_name}': Found {len(date_fields)} date field(s): {', '.join(date_fields)}")

                    # Log duplicate analysis results
                    if duplicate_analysis.get('analysis') == 'success':
                        cutoff = duplicate_analysis.get('cutoff_date', 'N/A')
                        dup_count = duplicate_analysis.get('duplicate_count', 0)
                        total_count = duplicate_analysis.get('total_count', 0)
                        self.log_message(
                            f"Layer '{layer_name}': {dup_count}/{total_count} duplicates, cutoff: {cutoff}")
                    elif duplicate_analysis.get('analysis') == 'no_master_layer':
                        self.log_message(f"Layer '{layer_name}': No existing master layer - all records are new")

            if layer_count > 0:
                self.log_message(f"Loaded {layer_count} layers successfully")
            else:
                self.log_message("No valid layers found in the GeoPackage")

        except Exception as e:
            import traceback
            self.log_message(f"Error loading layers: {str(e)}\n{traceback.format_exc()}")
            QMessageBox.critical(self, "Error", f"Failed to load layers: {str(e)}")
        finally:
            # Ensure DB connection is always cleaned up
            if QSqlDatabase.contains(connection_name):
                db = QSqlDatabase.database(connection_name)
                if db.isOpen():
                    db.close()
                QSqlDatabase.removeDatabase(connection_name)

    def select_all_layers(self):
        """Select all layers in the tree"""
        for layer_name, layer_info in self.tree_widget.layer_items.items():
            layer_info['item'].setCheckState(0, Qt.Checked)
        self.log_message("Selected all layers")

    def deselect_all_layers(self):
        """Deselect all layers in the tree"""
        for layer_name, layer_info in self.tree_widget.layer_items.items():
            layer_info['item'].setCheckState(0, Qt.Unchecked)
        self.log_message("Deselected all layers")

    def log_message(self, message):
        """Add message to log area"""
        self.log_area.append(message)
        self.log_area.ensureCursorVisible()

    def preview_changes(self):
        """Generate and show preview of changes"""
        if not self.validate_inputs():
            return

        # Sync paths from the inputs - they may have been typed manually
        # rather than set via the Browse buttons
        self.source_gpkg = self.source_input.text().strip()
        self.master_gpkg = self.master_input.text().strip()

        # Gather configuration
        config = self.gather_configuration()

        self.log_message("Generating preview...")
        self.run_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        # Create worker
        self.worker = WorkerThread(
            self.source_gpkg,
            self.master_gpkg,
            config['default_uuid_field'],
            config['selected_layers'],
            config['field_selections'],
            config['uuid_field_map'],
            config['layer_crs_map'],
            config['layer_recodings'],
            config['global_date_filter'],
            preview_only=True
        )

        self.worker.update_progress.connect(self.update_progress)
        self.worker.preview_ready.connect(self.show_preview_dialog)
        self.worker.finished.connect(self.preview_finished)
        self.worker.start()

    def show_preview_dialog(self, preview_data):
        """Show the preview dialog"""
        # UPDATED: Use EnhancedPreviewDialog instead of PreviewDialog
        dialog = EnhancedPreviewDialog(preview_data, self)
        if dialog.exec():
            self.log_message("Preview accepted, ready to process")
        else:
            self.log_message("Preview cancelled")

    def preview_finished(self, success, message):
        """Handle preview completion"""
        self.run_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if not success:
            self.log_message(f"Preview failed: {message}")

    def validate_inputs(self):
        """Validate inputs before processing"""
        source_gpkg = self.source_input.text().strip()
        master_gpkg = self.master_input.text().strip()

        if not source_gpkg or not os.path.exists(source_gpkg):
            QMessageBox.warning(self, "Input Error", "Valid source GeoPackage must be selected.")
            return False
        if not master_gpkg:
            QMessageBox.warning(self, "Input Error", "Master GeoPackage must be specified.")
            return False

        # BUG 8 fix: check source and master are different files
        if os.path.normpath(os.path.abspath(source_gpkg)) == os.path.normpath(os.path.abspath(master_gpkg)):
            QMessageBox.warning(self, "Input Error",
                                "Source and master GeoPackage cannot be the same file.")
            return False

        selected_layers = self.tree_widget.get_selected_layers()
        if not selected_layers:
            QMessageBox.warning(self, "Input Error", "No layers are selected for processing.")
            return False

        return True

    def gather_configuration(self):
        """Gather all configuration from UI"""
        config = {
            'default_uuid_field': self.uuid_input.text().strip(),
            'selected_layers': self.tree_widget.get_selected_layers(),
            'field_selections': {},
            'uuid_field_map': {},
            'layer_crs_map': {},
            'layer_recodings': self.tree_widget.layer_recodings,
            'global_date_filter': self.global_date_filter.get_filter_config()
        }

        # Gather field selections and UUID fields
        for layer_name in config['selected_layers']:
            config['field_selections'][layer_name] = self.tree_widget.get_selected_fields(layer_name)
            uuid_field = self.tree_widget.get_uuid_field(layer_name)
            if uuid_field:
                config['uuid_field_map'][layer_name] = uuid_field

        return config

    def run_process(self):
        """Run the actual append process"""
        if not self.validate_inputs():
            return

        # Sync paths from the inputs - they may have been typed manually
        # rather than set via the Browse buttons
        self.source_gpkg = self.source_input.text().strip()
        self.master_gpkg = self.master_input.text().strip()

        # Check for layers with "No UUID" mode and show confirmation
        no_uuid_layers = self.tree_widget.get_no_uuid_layer_names()
        if no_uuid_layers:
            layer_list = "\n".join(f"  • {name}" for name in no_uuid_layers)
            reply = QMessageBox.warning(
                self,
                "No Duplicate Checking",
                f"The following layers have no UUID field configured:\n\n"
                f"{layer_list}\n\n"
                f"ALL features from these layers will be added without duplicate checking.\n"
                f"If you run this again, duplicate features may be added.\n\n"
                f"Do you want to continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                self.log_message("Processing cancelled - No UUID confirmation declined")
                return

        master_gpkg = self.master_input.text().strip()
        if not os.path.exists(master_gpkg):
            reply = QMessageBox.question(self, "Create Master GeoPackage?",
                                         f"Master GeoPackage '{master_gpkg}' does not exist. Do you want to create it?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            # Don't pre-create the file here: an empty SQLite database is NOT
            # a valid GeoPackage. QgsVectorFileWriter creates the file itself
            # when the first layer is written.
            self.log_message(f"Master GeoPackage will be created: {master_gpkg}")

        # Gather configuration
        config = self.gather_configuration()

        # Build confirmation summary
        source_gpkg = self.source_input.text().strip()
        master_gpkg = self.master_input.text().strip()
        summary_lines = ["<b>Processing Summary:</b><br>"]
        summary_lines.append(f"Source: {os.path.basename(source_gpkg)}")
        summary_lines.append(f"Master: {os.path.basename(master_gpkg)}")
        summary_lines.append(f"Layers: {len(config['selected_layers'])}<br>")
        for layer_name in config['selected_layers']:
            recoding = self.tree_widget.layer_recodings.get(layer_name)
            target = recoding.target_layer if recoding and recoding.target_layer else layer_name
            n_fields = len(config['field_selections'].get(layer_name, []))
            n_recodings = len(recoding.value_recodings) if recoding else 0
            uuid_mode = config['uuid_field_map'].get(layer_name, 'No UUID')
            if uuid_mode == NO_UUID_FIELD:
                uuid_mode = 'No UUID'
            summary_lines.append(
                f"<b>{layer_name}</b> \u2192 {target} ({n_fields} fields, "
                f"{n_recodings} recodings, UUID: {uuid_mode})")
        if config.get('global_date_filter') and config['global_date_filter'].get('enabled'):
            summary_lines.append(f"<br>Date filter: ACTIVE")

        reply = QMessageBox.question(
            self, "Confirm Processing",
            "<br>".join(summary_lines) + "<br><br>Proceed?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply != QMessageBox.Yes:
            self.log_message("Processing cancelled by user")
            return

        self.run_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.log_area.clear()
        self.progress_bar.setValue(0)

        self.log_message(f"Starting processing of {len(config['selected_layers'])} selected layers")

        # Create worker
        self.worker = WorkerThread(
            self.source_gpkg,
            self.master_gpkg,
            config['default_uuid_field'],
            config['selected_layers'],
            config['field_selections'],
            config['uuid_field_map'],
            config['layer_crs_map'],
            config['layer_recodings'],
            config['global_date_filter'],
            preview_only=False
        )

        self.worker.update_progress.connect(self.update_progress)
        self.worker.finished.connect(self.process_finished)
        self.worker.start()

    def cancel_process(self):
        """Cancel the running process"""
        if self.worker and self.worker.isRunning():
            self.log_message("Attempting to cancel operation...")
            self.worker.abort = True
            self.cancel_button.setEnabled(False)

    def update_progress(self, value, message):
        """Update progress bar and log"""
        self.progress_bar.setValue(value)
        self.log_message(message)

    def closeEvent(self, event):
        """Stop the worker before the window (and the QThread) is destroyed"""
        if self.worker and self.worker.isRunning():
            self.worker.abort = True
            self.worker.wait(15000)
        super().closeEvent(event)

    def process_finished(self, success, message):
        """Handle process completion"""
        self.progress_bar.setValue(100)
        self.log_message(message)

        if success:
            QMessageBox.information(self, "Process Complete", message)
        else:
            QMessageBox.warning(self, "Process Ended", message)

        self.run_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.worker = None


def run_gpkg_append_tool_dialog(qgis_iface):
    """Creates and shows the Enhanced GeoPackage Append Tool dialog."""
    # Re-raise existing dialog if still alive
    if hasattr(qgis_iface, "_adddata_dialog") and qgis_iface._adddata_dialog is not None:
        try:
            qgis_iface._adddata_dialog.reset_ui()
            qgis_iface._adddata_dialog.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
            qgis_iface._adddata_dialog.setWindowModality(Qt.ApplicationModal)
            qgis_iface._adddata_dialog.show()
            qgis_iface._adddata_dialog.activateWindow()
            qgis_iface._adddata_dialog.raise_()
            return qgis_iface._adddata_dialog
        except RuntimeError:
            qgis_iface._adddata_dialog = None

    main_window = qgis_iface.mainWindow()
    dialog = GeoPackageAppendTool(parent=main_window)

    dialog.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
    dialog.setWindowModality(Qt.ApplicationModal)

    # Store persistent reference on iface to prevent GC; clean up on close
    dialog.destroyed.connect(lambda: setattr(qgis_iface, "_adddata_dialog", None))
    qgis_iface._adddata_dialog = dialog

    dialog.show()
    dialog.activateWindow()
    dialog.raise_()

    return dialog
