#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Unified recoding interface - replaces the old 3-widget system.

This provides a single, intuitive interface for:
- Layer mapping
- Field mapping with auto-matching
- Value recoding with default values
- Template management
"""

import os
from typing import Dict, List, Optional
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                 QLineEdit, QPushButton, QTableWidget,
                                 QTableWidgetItem, QComboBox, QGroupBox,
                                 QCheckBox, QScrollArea, QWidget, QHeaderView,
                                 QDialogButtonBox, QMessageBox, QProgressBar,
                                 QTabWidget, QTextEdit)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtSql import QSqlDatabase, QSqlQuery
from qgis.core import QgsVectorLayer, QgsField, QgsMessageLog, Qgis
from .utils import (LayerRecoding, ValueRecoding, fuzzy_match_field_names,
                    analyze_unique_values, validate_field_type_compatibility,
                    find_matching_field)
from .templates import TemplateManager
from ..ui_scaling import get_scale_manager


class UnifiedRecodingDialog(QDialog):
    """
    Unified dialog for all recoding configuration.

    Replaces:
    - RecodingDialog
    - FieldMappingWidget
    - ValueRecodingWidget

    With a single, intuitive interface.
    """

    def __init__(self, layer_name: str, source_fields: Dict[str, QgsField],
                 master_gpkg: str, source_gpkg: str,
                 existing_recoding: Optional[LayerRecoding] = None, parent=None):
        super().__init__(parent)
        self.layer_name = layer_name
        self.source_fields = source_fields
        self.master_gpkg = master_gpkg
        self.source_gpkg = source_gpkg
        self.recoding = existing_recoding or LayerRecoding()

        self.master_layers = []
        self.master_fields = {}
        self.value_combos = {}  # Track value mapping combos

        self.setWindowTitle(f"Configure Mapping & Recoding: {layer_name}")
        self.setModal(True)
        scale = get_scale_manager()
        self.resize(*scale.dialog_size(1000, 700))

        self.load_master_layers()
        self.setup_ui()

    def load_master_layers(self):
        """Load available layers from master GeoPackage"""
        if not os.path.exists(self.master_gpkg):
            return

        connection_name = f"unified_recoding_{id(self)}"
        db = QSqlDatabase.addDatabase("QSQLITE", connection_name)
        db.setDatabaseName(self.master_gpkg)

        if db.open():
            query = QSqlQuery(db)
            if query.exec("SELECT table_name FROM gpkg_contents WHERE data_type IN ('features', 'attributes')"):
                while query.next():
                    self.master_layers.append(query.value(0))
            db.close()

        QSqlDatabase.removeDatabase(connection_name)

    def setup_ui(self):
        layout = QVBoxLayout()

        # Title and quick actions
        title_layout = QHBoxLayout()
        title_label = QLabel(f"<h2>Configure Mapping: <i>{self.layer_name}</i></h2>")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        # Quick actions bar
        actions_layout = QHBoxLayout()

        # Template controls
        actions_layout.addWidget(QLabel("<b>Templates:</b>"))
        self.template_combo = QComboBox()
        self.template_combo.addItem("<Load Template...>")
        self._populate_templates()
        self.template_combo.currentTextChanged.connect(self._on_load_template)
        actions_layout.addWidget(self.template_combo)

        save_template_btn = QPushButton("💾 Save as Template")
        save_template_btn.clicked.connect(self._save_as_template)
        actions_layout.addWidget(save_template_btn)

        actions_layout.addStretch()

        # Auto-match button
        auto_match_btn = QPushButton("✨ Auto-Match Fields")
        auto_match_btn.setToolTip("Automatically match source fields to target fields using fuzzy matching")
        auto_match_btn.clicked.connect(self._auto_match_fields)
        actions_layout.addWidget(auto_match_btn)

        layout.addLayout(actions_layout)

        # Tab widget for different configuration sections
        self.tab_widget = QTabWidget()

        # Tab 1: Layer & Field Mapping
        mapping_tab = self._create_mapping_tab()
        self.tab_widget.addTab(mapping_tab, "🔗 Layer && Field Mapping")

        # Tab 2: Value Recoding
        value_tab = self._create_value_recoding_tab()
        self.tab_widget.addTab(value_tab, "🔄 Value Recoding")

        # Tab 3: Advanced Options
        advanced_tab = self._create_advanced_tab()
        self.tab_widget.addTab(advanced_tab, "⚙ Advanced Options")

        layout.addWidget(self.tab_widget)

        # Progress indicator
        progress_layout = QHBoxLayout()
        self.progress_label = QLabel()
        self._update_progress()
        progress_layout.addWidget(self.progress_label)
        progress_layout.addStretch()
        layout.addLayout(progress_layout)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        preview_btn = buttons.addButton("Preview", QDialogButtonBox.ActionRole)
        preview_btn.clicked.connect(self._preview_recoding)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def _create_mapping_tab(self) -> QWidget:
        """Create the layer and field mapping tab"""
        widget = QWidget()
        layout = QVBoxLayout()

        # Layer mapping section
        layer_group = QGroupBox("1. Target Layer")
        layer_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        layer_layout = QHBoxLayout()
        layer_layout.addWidget(QLabel("Map to master layer:"))
        self.target_layer_combo = QComboBox()
        self.target_layer_combo.addItem(f"<Same as source: {self.layer_name}>")
        self.target_layer_combo.addItems(self.master_layers)
        # NOTE: Don't connect signal yet - need to create field_mapping_table first

        layer_layout.addWidget(self.target_layer_combo)
        layer_layout.addStretch()
        layer_group.setLayout(layer_layout)
        layout.addWidget(layer_group)

        # Field mapping section
        field_group = QGroupBox("2. Field Mapping")
        field_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        field_layout = QVBoxLayout()

        # Instructions
        instructions = QLabel(
            "Map source fields to target fields. Unmapped fields will use the same name. "
            "You can set default values for any field."
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("font-weight: normal; font-style: italic; color: #666;")
        field_layout.addWidget(instructions)

        # Field mapping table - CREATE THIS BEFORE connecting signal
        self.field_mapping_table = QTableWidget()
        self.field_mapping_table.setColumnCount(5)
        self.field_mapping_table.setHorizontalHeaderLabels([
            "Source Field", "Source Type", "→", "Target Field", "Default Value"
        ])
        self.field_mapping_table.horizontalHeader().setStretchLastSection(False)
        self.field_mapping_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.field_mapping_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.field_mapping_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.field_mapping_table.setAlternatingRowColors(True)

        # NOW connect signal and set initial value (after table exists)
        self.target_layer_combo.currentTextChanged.connect(self._on_target_layer_changed)

        # Set existing target layer (this may trigger _on_target_layer_changed)
        if self.recoding.target_layer:
            idx = self.target_layer_combo.findText(self.recoding.target_layer)
            if idx >= 0:
                self.target_layer_combo.setCurrentIndex(idx)

        self._populate_field_mapping_table()
        field_layout.addWidget(self.field_mapping_table)

        field_group.setLayout(field_layout)
        layout.addWidget(field_group)

        widget.setLayout(layout)
        return widget

    def _populate_field_mapping_table(self):
        """Populate the field mapping table"""
        self.field_mapping_table.setRowCount(len(self.source_fields))

        for row, (field_name, field) in enumerate(self.source_fields.items()):
            # Source field (read-only)
            source_item = QTableWidgetItem(field_name)
            source_item.setFlags(source_item.flags() & ~Qt.ItemIsEditable)
            self.field_mapping_table.setItem(row, 0, source_item)

            # Source type (read-only)
            type_item = QTableWidgetItem(field.typeName())
            type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)
            self.field_mapping_table.setItem(row, 1, type_item)

            # Arrow (read-only)
            arrow_item = QTableWidgetItem("→")
            arrow_item.setTextAlignment(Qt.AlignCenter)
            arrow_item.setFlags(arrow_item.flags() & ~Qt.ItemIsEditable)
            self.field_mapping_table.setItem(row, 2, arrow_item)

            # Target field combo
            target_combo = QComboBox()
            target_combo.addItem(f"<Same: {field_name}>")
            target_combo.addItem("<Unmapped>")

            # Add master fields if target layer is selected
            if self.master_fields:
                target_combo.insertSeparator(2)
                for master_field_name in sorted(self.master_fields.keys()):
                    target_combo.addItem(master_field_name)

            # Set existing mapping
            if field_name in self.recoding.field_mappings:
                idx = target_combo.findText(self.recoding.field_mappings[field_name])
                if idx >= 0:
                    target_combo.setCurrentIndex(idx)

            target_combo.currentTextChanged.connect(
                lambda text, r=row: self._check_field_compatibility(r)
            )
            self.field_mapping_table.setCellWidget(row, 3, target_combo)

            # Default value input (defaults are keyed by target field name;
            # fall back to source name for configs saved by older versions)
            default_input = QLineEdit()
            default_input.setPlaceholderText("Optional default value...")
            target_name = self.recoding.field_mappings.get(field_name, field_name)
            default_val = self.recoding.default_values.get(
                target_name, self.recoding.default_values.get(field_name))
            if default_val is not None:
                default_input.setText(str(default_val))
            self.field_mapping_table.setCellWidget(row, 4, default_input)

            # Initial compatibility check
            self._check_field_compatibility(row)

    def _check_field_compatibility(self, row: int):
        """Check and indicate field type compatibility"""
        source_field_name = self.field_mapping_table.item(row, 0).text()
        target_combo = self.field_mapping_table.cellWidget(row, 3)
        target_text = target_combo.currentText()

        # Reset colors
        self.field_mapping_table.item(row, 1).setBackground(QColor())
        target_combo.setStyleSheet("")

        if target_text.startswith("<Same:") or target_text == "<Unmapped>":
            return

        # Check type compatibility
        source_field = self.source_fields[source_field_name]
        if target_text in self.master_fields:
            target_field = self.master_fields[target_text]
            is_compatible, warning = validate_field_type_compatibility(source_field, target_field)

            if not is_compatible:
                self.field_mapping_table.item(row, 1).setBackground(QColor(255, 200, 200))
                target_combo.setToolTip(warning or "Type mismatch")
                target_combo.setStyleSheet("QComboBox { background-color: #ffcccc; }")
            elif warning:
                self.field_mapping_table.item(row, 1).setBackground(QColor(255, 255, 200))
                target_combo.setToolTip(warning)
                target_combo.setStyleSheet("QComboBox { background-color: #ffffcc; }")
            else:
                self.field_mapping_table.item(row, 1).setBackground(QColor(200, 255, 200))
                target_combo.setToolTip("Types compatible")
                target_combo.setStyleSheet("QComboBox { background-color: #ccffcc; }")

    def _on_target_layer_changed(self, layer_text: str):
        """Handle target layer selection"""
        if layer_text.startswith("<Same as source:"):
            self.recoding.target_layer = None
            self.master_fields = {}
        else:
            self.recoding.target_layer = layer_text
            self._load_master_fields(layer_text)

        # Refresh field mapping table
        self._populate_field_mapping_table()
        # The value-recoding tab's master field list depends on the target layer
        self._refresh_master_value_field_combo()
        self._update_progress()

    def _refresh_master_value_field_combo(self):
        """Repopulate the master value field combo for the current target layer"""
        combo = getattr(self, 'master_value_field_combo', None)
        if combo is None:
            # Value recoding tab not built yet (during initial setup)
            return
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("<Select master field...>")
        self._populate_master_value_fields()
        combo.blockSignals(False)
        self._master_field_values = []

    def _load_master_fields(self, layer_name: str):
        """Load fields from master layer"""
        self.master_fields = {}

        if not os.path.exists(self.master_gpkg):
            return

        master_uri = f"{self.master_gpkg}|layername={layer_name}"
        master_layer = QgsVectorLayer(master_uri, layer_name, "ogr")

        if master_layer.isValid():
            for field in master_layer.fields():
                self.master_fields[field.name()] = field

    def _auto_match_fields(self):
        """Auto-match source fields to target fields using fuzzy matching"""
        if not self.master_fields:
            QMessageBox.information(self, "Auto-Match",
                                    "Please select a target layer first.")
            return

        source_field_names = list(self.source_fields.keys())
        target_field_names = list(self.master_fields.keys())

        # Use fuzzy matching
        mappings = fuzzy_match_field_names(source_field_names, target_field_names, threshold=70)

        # Apply mappings
        matched_count = 0
        for row in range(self.field_mapping_table.rowCount()):
            source_field = self.field_mapping_table.item(row, 0).text()
            if source_field in mappings:
                target_field = mappings[source_field]
                target_combo = self.field_mapping_table.cellWidget(row, 3)
                idx = target_combo.findText(target_field)
                if idx >= 0:
                    target_combo.setCurrentIndex(idx)
                    matched_count += 1

        QMessageBox.information(self, "Auto-Match Complete",
                                f"Matched {matched_count} of {len(source_field_names)} fields.")
        self._update_progress()

    def _create_value_recoding_tab(self) -> QWidget:
        """Create the value recoding tab"""
        widget = QWidget()
        layout = QVBoxLayout()

        # Instructions
        instructions = QLabel(
            "<b>Value Recoding:</b> Select a field to configure value mapping. "
            "You can map old values to new values and set a default for unmapped values."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        # Field selector
        field_layout = QHBoxLayout()
        field_layout.addWidget(QLabel("Select field to recode:"))
        self.value_field_combo = QComboBox()
        self.value_field_combo.addItem("<Select a field...>")
        self.value_field_combo.addItems(sorted(self.source_fields.keys()))
        self.value_field_combo.currentTextChanged.connect(self._on_value_field_selected)
        field_layout.addWidget(self.value_field_combo)

        analyze_btn = QPushButton("🔍 Analyze Values")
        analyze_btn.clicked.connect(self._analyze_field_values)
        field_layout.addWidget(analyze_btn)

        field_layout.addStretch()
        layout.addLayout(field_layout)

        # Master field selector for value lookup
        master_layout = QHBoxLayout()
        master_layout.addWidget(QLabel("Map to master field:"))
        self.master_value_field_combo = QComboBox()
        self.master_value_field_combo.addItem("<Select master field...>")
        # Populate with master layer fields if target is set
        self._populate_master_value_fields()
        self.master_value_field_combo.currentTextChanged.connect(self._on_master_value_field_selected)
        master_layout.addWidget(self.master_value_field_combo)

        auto_match_values_btn = QPushButton("Auto-Match Values")
        auto_match_values_btn.setToolTip("Fuzzy match source values to master field values")
        auto_match_values_btn.clicked.connect(self._auto_match_values)
        master_layout.addWidget(auto_match_values_btn)

        master_layout.addStretch()
        layout.addLayout(master_layout)

        # Initialize master field values store
        self._master_field_values = []

        # Value mapping area
        self.value_mapping_widget = QWidget()
        value_mapping_layout = QVBoxLayout()

        self.value_mapping_table = QTableWidget()
        self.value_mapping_table.setColumnCount(3)
        self.value_mapping_table.setHorizontalHeaderLabels([
            "Source Value", "→", "Target Value"
        ])
        self.value_mapping_table.horizontalHeader().setStretchLastSection(True)
        self.value_mapping_table.setAlternatingRowColors(True)

        value_mapping_layout.addWidget(self.value_mapping_table)

        # Default value for unmapped
        default_layout = QHBoxLayout()
        default_layout.addWidget(QLabel("Default for unmapped values:"))
        self.unmapped_default_input = QLineEdit()
        self.unmapped_default_input.setPlaceholderText("Leave blank to keep original")
        default_layout.addWidget(self.unmapped_default_input)
        value_mapping_layout.addLayout(default_layout)

        # Preserve original field option
        preserve_layout = QHBoxLayout()
        self.preserve_original_checkbox = QCheckBox("Preserve original values in field:")
        self.preserve_original_field_input = QLineEdit()
        self.preserve_original_field_input.setPlaceholderText("e.g. Original_Lithology")
        self.preserve_original_field_input.setEnabled(False)
        self.preserve_original_checkbox.toggled.connect(self.preserve_original_field_input.setEnabled)
        preserve_layout.addWidget(self.preserve_original_checkbox)
        preserve_layout.addWidget(self.preserve_original_field_input)
        value_mapping_layout.addLayout(preserve_layout)

        self.value_mapping_widget.setLayout(value_mapping_layout)
        self.value_mapping_widget.setVisible(False)
        layout.addWidget(self.value_mapping_widget)

        widget.setLayout(layout)
        return widget

    def _on_value_field_selected(self, field_name: str):
        """Handle value field selection"""
        # BUG 4 fix: save current field's recodings before switching
        self._save_current_value_recodings()

        if field_name == "<Select a field...>" or not field_name:
            self.value_mapping_widget.setVisible(False)
            self._current_value_field = None
            return

        self._current_value_field = field_name
        self.value_mapping_widget.setVisible(True)
        self._load_value_mappings(field_name)

    def _save_current_value_recodings(self):
        """Save the current field's value recodings from the table to self.recoding"""
        current_field = getattr(self, '_current_value_field', None)
        if not current_field or current_field == "<Select a field...>":
            return

        mappings = self._read_value_table()
        default_for_unmapped = self.unmapped_default_input.text().strip()
        preserve_field = ""
        if self.preserve_original_checkbox.isChecked():
            preserve_field = self.preserve_original_field_input.text().strip()

        if not (mappings or default_for_unmapped or preserve_field):
            # Nothing configured for this field
            return

        value_recoding = self.recoding.value_recodings.setdefault(current_field, ValueRecoding())
        value_recoding.manual_mappings = mappings
        value_recoding.default_value = default_for_unmapped or None
        value_recoding.preserve_original_field = preserve_field or None

        # Save master field association
        master_combo = getattr(self, 'master_value_field_combo', None)
        if master_combo and master_combo.currentText() not in ("", "<Select master field...>"):
            value_recoding.value_field = master_combo.currentText()
            value_recoding.lookup_layer = self.recoding.target_layer or self.layer_name

    def _load_value_mappings(self, field_name: str):
        """Load existing value mappings for a field"""
        self.value_mapping_table.setRowCount(0)

        # Reset preserve original UI
        self.preserve_original_checkbox.setChecked(False)
        self.preserve_original_field_input.clear()

        # Reset master field combo if it exists
        master_combo = getattr(self, 'master_value_field_combo', None)
        if master_combo:
            master_combo.setCurrentIndex(0)

        # Clear master values so new rows don't get stale combos
        self._master_field_values = []

        if field_name not in self.recoding.value_recodings:
            self.unmapped_default_input.clear()
            return

        value_recoding = self.recoding.value_recodings[field_name]
        self.unmapped_default_input.setText(value_recoding.default_value or "")

        # Restore preserve original field
        if value_recoding.preserve_original_field:
            self.preserve_original_checkbox.setChecked(True)
            self.preserve_original_field_input.setText(value_recoding.preserve_original_field)

        # Restore master field selection
        if value_recoding.value_field and master_combo:
            idx = master_combo.findText(value_recoding.value_field)
            if idx >= 0:
                master_combo.setCurrentIndex(idx)

        for old_value, new_value in value_recoding.manual_mappings.items():
            self._add_value_mapping_row(old_value, new_value)

    def _add_value_mapping_row(self, source_value: str = "", target_value: str = "",
                              read_only_source: bool = False,
                              raw_value: Optional[str] = None):
        """Add a row to the value mapping table.

        raw_value is the actual source data value; source_value may carry a
        display suffix like " (123 records)". The raw value is stored in
        Qt.UserRole so it is never reconstructed by parsing the display text
        (which corrupts values that themselves contain " (").
        """
        row = self.value_mapping_table.rowCount()
        self.value_mapping_table.insertRow(row)

        # Source value
        source_item = QTableWidgetItem(source_value)
        source_item.setData(Qt.UserRole, raw_value if raw_value is not None else source_value)
        if read_only_source:
            source_item.setFlags(source_item.flags() & ~Qt.ItemIsEditable)
        self.value_mapping_table.setItem(row, 0, source_item)

        # Arrow
        arrow_item = QTableWidgetItem("→")
        arrow_item.setFlags(arrow_item.flags() & ~Qt.ItemIsEditable)
        arrow_item.setTextAlignment(Qt.AlignCenter)
        self.value_mapping_table.setItem(row, 1, arrow_item)

        # Target value - use QComboBox if master values are available
        master_values = getattr(self, '_master_field_values', [])
        if master_values:
            target_combo = QComboBox()
            target_combo.setEditable(True)
            target_combo.addItems(master_values)
            target_combo.setCurrentText(target_value)
            self.value_mapping_table.setCellWidget(row, 2, target_combo)
        else:
            target_item = QTableWidgetItem(target_value)
            self.value_mapping_table.setItem(row, 2, target_item)

    def _get_target_value(self, row: int) -> str:
        """Get target value from row, handling both QComboBox widgets and plain items"""
        widget = self.value_mapping_table.cellWidget(row, 2)
        if isinstance(widget, QComboBox):
            return widget.currentText()
        item = self.value_mapping_table.item(row, 2)
        return item.text() if item else ""

    def _get_source_value(self, row: int) -> Optional[str]:
        """Get the raw source value from a row (stored in Qt.UserRole)"""
        item = self.value_mapping_table.item(row, 0)
        if item is None:
            return None
        data = item.data(Qt.UserRole)
        return data if data is not None else item.text()

    def _read_value_table(self) -> Dict[str, str]:
        """Read {source_value: target_value} from the value mapping table.

        Single source of truth for reading the table - used by saving,
        finalizing and the progress display so they can't drift apart.
        """
        mappings = {}
        for row in range(self.value_mapping_table.rowCount()):
            source_value = self._get_source_value(row)
            if source_value is not None:
                mappings[source_value] = self._get_target_value(row)
        return mappings

    def _populate_master_value_fields(self):
        """Populate master value field combo with fields from the target master layer"""
        target_layer = self.recoding.target_layer or self.layer_name
        master_uri = f"{self.master_gpkg}|layername={target_layer}"
        layer = QgsVectorLayer(master_uri, target_layer, "ogr")
        if layer.isValid():
            for field in layer.fields():
                self.master_value_field_combo.addItem(field.name())

    def _on_master_value_field_selected(self, field_name: str):
        """Handle master value field selection - load unique values from master"""
        if field_name == "<Select master field...>" or not field_name:
            self._master_field_values = []
            return
        self._load_master_field_values(field_name)

    def _load_master_field_values(self, master_field_name: str):
        """Load unique values from a master layer field"""
        target_layer = self.recoding.target_layer or self.layer_name
        master_uri = f"{self.master_gpkg}|layername={target_layer}"
        layer = QgsVectorLayer(master_uri, target_layer, "ogr")
        if layer.isValid():
            value_counts = analyze_unique_values(layer, master_field_name)
            self._master_field_values = sorted(
                [k for k in value_counts.keys() if k != '<TOO_MANY_UNIQUE_VALUES>' and k != '<NULL>']
            )
        else:
            self._master_field_values = []

        # Update existing rows to use QComboBox with master values
        self._refresh_target_combos()

    def _refresh_target_combos(self):
        """Replace target value cells with QComboBoxes populated with master values"""
        for row in range(self.value_mapping_table.rowCount()):
            current_value = self._get_target_value(row)
            target_combo = QComboBox()
            target_combo.setEditable(True)
            if self._master_field_values:
                target_combo.addItems(self._master_field_values)
            target_combo.setCurrentText(current_value)
            self.value_mapping_table.setCellWidget(row, 2, target_combo)

    def _auto_match_values(self):
        """Auto-match source values to master field values using fuzzy matching"""
        from .utils import fuzzy_match_values

        if not self._master_field_values:
            QMessageBox.information(self, "No Master Values",
                                    "Please select a master field to load values first.")
            return

        source_values = []
        for row in range(self.value_mapping_table.rowCount()):
            source_val = self._get_source_value(row)
            if source_val is not None:
                source_values.append(source_val)

        if not source_values:
            QMessageBox.information(self, "No Source Values",
                                    "Please analyze field values first.")
            return

        matches = fuzzy_match_values(source_values, self._master_field_values)
        matched = 0
        for row in range(self.value_mapping_table.rowCount()):
            source_val = self._get_source_value(row)
            if source_val is not None and source_val in matches:
                widget = self.value_mapping_table.cellWidget(row, 2)
                if isinstance(widget, QComboBox):
                    widget.setCurrentText(matches[source_val])
                    matched += 1
        QMessageBox.information(self, "Auto-Match Complete",
                                f"Matched {matched} of {len(source_values)} values.")

    def _analyze_field_values(self):
        """Analyze unique values in the selected field"""
        field_name = self.value_field_combo.currentText()
        if field_name == "<Select a field...>" or not field_name:
            QMessageBox.warning(self, "No Field Selected", "Please select a field to analyze.")
            return

        # Open source layer
        source_uri = f"{self.source_gpkg}|layername={self.layer_name}"
        source_layer = QgsVectorLayer(source_uri, self.layer_name, "ogr")

        if not source_layer.isValid():
            QMessageBox.critical(self, "Error", "Could not open source layer.")
            return

        # Analyze unique values
        value_counts = analyze_unique_values(source_layer, field_name)

        if '<TOO_MANY_UNIQUE_VALUES>' in value_counts:
            QMessageBox.warning(self, "Too Many Values",
                                f"Field '{field_name}' has more than 1000 unique values. "
                                "Only the first 1000 will be shown.")

        # Check for existing mappings before clearing
        existing_mappings = {}
        existing_count = self.value_mapping_table.rowCount()
        if existing_count > 0:
            msg = QMessageBox(self)
            msg.setWindowTitle("Existing Mappings Found")
            msg.setText(f"This field already has {existing_count} value mappings configured.\n"
                        f"Analysis found {len(value_counts)} unique values in source.")
            msg.setInformativeText("What would you like to do?")
            merge_btn = msg.addButton("Merge (keep existing)", QMessageBox.AcceptRole)
            replace_btn = msg.addButton("Replace all", QMessageBox.DestructiveRole)
            msg.addButton(QMessageBox.Cancel)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked == merge_btn:
                # Collect existing mappings before clearing
                existing_mappings = self._read_value_table()
            elif clicked == replace_btn:
                pass  # Continue to clear and rebuild
            else:
                return  # Cancel

        # Clear existing mappings
        self.value_mapping_table.setRowCount(0)

        # Add rows for each unique value
        for value, count in sorted(value_counts.items(), key=lambda x: -x[1]):
            if value == '<TOO_MANY_UNIQUE_VALUES>':
                continue
            # Use existing target value if merging, otherwise default to same value
            target_value = existing_mappings.get(value, value)
            self._add_value_mapping_row(f"{value} ({count} records)", target_value,
                                        read_only_source=True, raw_value=value)

    def _create_advanced_tab(self) -> QWidget:
        """Create the advanced options tab"""
        widget = QWidget()
        layout = QVBoxLayout()

        # Summary/notes area
        notes_group = QGroupBox("Configuration Summary")
        notes_layout = QVBoxLayout()
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMaximumHeight(get_scale_manager().dimension(200))
        notes_layout.addWidget(self.summary_text)
        notes_group.setLayout(notes_layout)
        layout.addWidget(notes_group)

        # Refresh summary
        refresh_btn = QPushButton("🔄 Refresh Summary")
        refresh_btn.clicked.connect(self._update_summary)
        layout.addWidget(refresh_btn)

        layout.addStretch()
        widget.setLayout(layout)

        self._update_summary()
        return widget

    def _update_summary(self):
        """Update the configuration summary"""
        summary_lines = []
        summary_lines.append("<h3>Configuration Summary</h3>")

        # Target layer
        target_layer = self.recoding.target_layer or self.layer_name
        summary_lines.append(f"<b>Target Layer:</b> {target_layer}")

        # Field mappings
        field_mappings = self._collect_field_mappings()
        if field_mappings:
            summary_lines.append(f"<b>Field Mappings:</b> {len(field_mappings)}")
            for source, target in list(field_mappings.items())[:5]:
                summary_lines.append(f"  • {source} → {target}")
            if len(field_mappings) > 5:
                summary_lines.append(f"  • ... and {len(field_mappings) - 5} more")

        # Default values
        default_values = self._collect_default_values()
        if default_values:
            summary_lines.append(f"<b>Default Values:</b> {len(default_values)}")
            for field, value in list(default_values.items())[:5]:
                summary_lines.append(f"  • {field} = {value}")

        # Value recodings
        value_recodings = self._collect_value_recodings()
        if value_recodings:
            summary_lines.append(f"<b>Value Recodings:</b> {len(value_recodings)} fields")
            for field, mappings in list(value_recodings.items())[:3]:
                summary_lines.append(f"  • {field}: {len(mappings)} value mappings")

        self.summary_text.setHtml("<br>".join(summary_lines))

    def _collect_field_mappings(self) -> Dict[str, str]:
        """Collect field mappings from the table"""
        mappings = {}
        for row in range(self.field_mapping_table.rowCount()):
            source_field = self.field_mapping_table.item(row, 0).text()
            target_combo = self.field_mapping_table.cellWidget(row, 3)
            target_text = target_combo.currentText()

            if not target_text.startswith("<Same:") and target_text != "<Unmapped>":
                mappings[source_field] = target_text

        return mappings

    def _collect_default_values(self) -> Dict[str, str]:
        """Collect default values, keyed by TARGET field name.

        Processing applies defaults after field mapping, so they must be
        keyed by the target name or they are silently lost for renamed fields.
        """
        defaults = {}
        field_mappings = self._collect_field_mappings()
        for row in range(self.field_mapping_table.rowCount()):
            source_field = self.field_mapping_table.item(row, 0).text()
            default_input = self.field_mapping_table.cellWidget(row, 4)
            default_value = default_input.text().strip()

            if default_value:
                target_field = field_mappings.get(source_field, source_field)
                defaults[target_field] = default_value

        return defaults

    def _collect_value_recodings(self) -> Dict[str, Dict[str, str]]:
        """Collect value recodings"""
        recodings = {}

        # Get current field selection
        current_field = self.value_field_combo.currentText()
        if current_field and current_field != "<Select a field...>":
            mappings = {s: t for s, t in self._read_value_table().items() if s != t}
            if mappings:
                recodings[current_field] = mappings

        # Add existing recodings for other fields
        for field, value_recoding in self.recoding.value_recodings.items():
            if field != current_field and value_recoding.manual_mappings:
                recodings[field] = value_recoding.manual_mappings

        return recodings

    def _populate_templates(self):
        """Populate template dropdown"""
        try:
            template_mgr = TemplateManager(self.master_gpkg)
            templates = template_mgr.list_templates(self.layer_name)

            for template in templates:
                self.template_combo.addItem(template['template_name'])
        except Exception as e:
            QgsMessageLog.logMessage(f"Could not load templates: {e}", 'Linear Geoscience', Qgis.Warning)

    def _on_load_template(self, template_name: str):
        """Load a template"""
        if template_name == "<Load Template...>" or not template_name:
            return

        try:
            template_mgr = TemplateManager(self.master_gpkg)
            template_data = template_mgr.load_template(template_name)

            if template_data:
                # Load configuration
                config = template_data['configuration']
                self.recoding = LayerRecoding.from_dict(config)

                # Reset the value-recoding tab BEFORE touching combos so the
                # stale table isn't saved over the freshly loaded template
                self._current_value_field = None
                self.value_field_combo.setCurrentIndex(0)
                self.value_mapping_table.setRowCount(0)
                self.value_mapping_widget.setVisible(False)

                # Apply the template's target layer to the combo and load the
                # master fields - without this, the field mapping combos can't
                # find their targets and the mappings are lost on OK
                target = self.recoding.target_layer
                self.target_layer_combo.blockSignals(True)
                idx = self.target_layer_combo.findText(target) if target else -1
                self.target_layer_combo.setCurrentIndex(idx if idx >= 0 else 0)
                self.target_layer_combo.blockSignals(False)
                if target:
                    self._load_master_fields(target)
                else:
                    self.master_fields = {}
                self._refresh_master_value_field_combo()

                # Refresh UI
                self._populate_field_mapping_table()
                self._update_progress()

                QMessageBox.information(self, "Template Loaded",
                                        f"Template '{template_name}' loaded successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not load template: {e}")

    def _save_as_template(self):
        """Save current configuration as a template"""
        from qgis.PyQt.QtWidgets import QInputDialog

        template_name, ok = QInputDialog.getText(
            self, "Save Template", "Enter template name:"
        )

        if ok and template_name:
            # Collect current configuration
            self._finalize_recoding()

            try:
                template_mgr = TemplateManager(self.master_gpkg)
                target_layer = self.recoding.target_layer or self.layer_name
                template_mgr.save_template(template_name, self.layer_name,
                                           target_layer, self.recoding)

                QMessageBox.information(self, "Template Saved",
                                        f"Template '{template_name}' saved successfully.")

                # Refresh template list
                self.template_combo.clear()
                self.template_combo.addItem("<Load Template...>")
                self._populate_templates()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not save template: {e}")

    def _preview_recoding(self):
        """Preview the recoding configuration"""
        self._finalize_recoding()
        self._update_summary()
        self.tab_widget.setCurrentIndex(2)  # Switch to advanced tab

    def _update_progress(self):
        """Update progress indicator"""
        field_mappings = len(self._collect_field_mappings())
        value_recodings = len(self._collect_value_recodings())
        default_values = len(self._collect_default_values())

        total_config = field_mappings + value_recodings + default_values
        self.progress_label.setText(
            f"Configuration: {field_mappings} field mappings, "
            f"{value_recodings} value recodings, "
            f"{default_values} default values"
        )

    def _finalize_recoding(self):
        """Finalize recoding configuration before saving"""
        self.recoding.field_mappings = self._collect_field_mappings()
        self.recoding.default_values = self._collect_default_values()
        # Value recodings for the currently displayed field (other fields were
        # saved when the selection changed)
        self._save_current_value_recodings()

    def get_recoding(self) -> LayerRecoding:
        """Get the configured recoding"""
        self._finalize_recoding()
        return self.recoding
