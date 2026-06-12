#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Enhanced preview dialogs with comprehensive statistics and pagination.
"""

from typing import Dict, List
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                 QTableWidget, QTableWidgetItem, QGroupBox,
                                 QComboBox, QDialogButtonBox, QCheckBox,
                                 QPushButton, QHeaderView, QSpinBox,
                                 QTabWidget, QWidget, QTextEdit)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont
from .utils import format_record_count
from ..ui_scaling import get_scale_manager


class EnhancedPreviewDialog(QDialog):
    """
    Enhanced preview dialog showing comprehensive statistics and sample data.

    Features:
    - Detailed statistics with color coding
    - Show up to 1000 records with pagination
    - Filter to show only records that will be added
    - Duplicate analysis
    - Temporal overlap warnings
    """

    def __init__(self, preview_data: Dict, parent=None):
        super().__init__(parent)
        self.preview_data = preview_data
        self.current_page = 0
        self.records_per_page = 100
        self.show_only_new = False

        self.setWindowTitle("Enhanced Data Preview")
        self.setModal(True)
        scale = get_scale_manager()
        self.resize(*scale.dialog_size(1200, 800))
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Create tab widget for different views
        self.tab_widget = QTabWidget()

        # Tab 1: Summary Statistics
        summary_tab = self._create_summary_tab()
        self.tab_widget.addTab(summary_tab, "📊 Summary Statistics")

        # Tab 2: Data Preview
        preview_tab = self._create_preview_tab()
        self.tab_widget.addTab(preview_tab, "👁 Data Preview")

        # Tab 3: Duplicates Analysis
        duplicates_tab = self._create_duplicates_tab()
        self.tab_widget.addTab(duplicates_tab, "⚠ Duplicates")

        layout.addWidget(self.tab_widget)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def _create_summary_tab(self) -> QWidget:
        """Create comprehensive summary statistics tab"""
        widget = QWidget()
        layout = QVBoxLayout()

        # Layer selector
        layer_layout = QHBoxLayout()
        layer_layout.addWidget(QLabel("<b>Select Layer:</b>"))
        self.summary_layer_combo = QComboBox()
        self.summary_layer_combo.addItems(list(self.preview_data.keys()))
        self.summary_layer_combo.currentTextChanged.connect(self._update_summary_statistics)
        layer_layout.addWidget(self.summary_layer_combo)
        layer_layout.addStretch()
        layout.addLayout(layer_layout)

        # Statistics table
        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(2)
        self.stats_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self.stats_table.horizontalHeader().setStretchLastSection(True)
        self.stats_table.setAlternatingRowColors(True)
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.setEditTriggers(QTableWidget.NoEditTriggers)

        layout.addWidget(self.stats_table)

        # Warnings/Notes section
        self.warnings_text = QTextEdit()
        self.warnings_text.setReadOnly(True)
        self.warnings_text.setMaximumHeight(get_scale_manager().dimension(150))
        self.warnings_text.setStyleSheet("""
            QTextEdit {
                background-color: #fff9e6;
                border: 2px solid #f0ad4e;
                border-radius: 5px;
                padding: 10px;
            }
        """)
        layout.addWidget(QLabel("<b>⚠ Warnings & Notes:</b>"))
        layout.addWidget(self.warnings_text)

        widget.setLayout(layout)

        # Initialize with first layer
        if self.preview_data:
            self._update_summary_statistics(list(self.preview_data.keys())[0])

        return widget

    def _update_summary_statistics(self, layer_name: str):
        """Update the summary statistics table for selected layer"""
        if layer_name not in self.preview_data:
            return

        data = self.preview_data[layer_name]
        self.stats_table.setRowCount(0)

        # Helper function to add row
        def add_stat_row(metric, value, color=None, bold=False):
            row = self.stats_table.rowCount()
            self.stats_table.insertRow(row)

            metric_item = QTableWidgetItem(metric)
            value_item = QTableWidgetItem(str(value))

            if bold:
                font = QFont()
                font.setBold(True)
                metric_item.setFont(font)
                value_item.setFont(font)

            if color:
                value_item.setBackground(QColor(color))

            self.stats_table.setItem(row, 0, metric_item)
            self.stats_table.setItem(row, 1, value_item)

        # Source Data Section
        add_stat_row("═══ SOURCE DATA ═══", "", None, True)
        add_stat_row("Total records in source", format_record_count(data.get("total_records", 0)))

        date_range = data.get("source_date_range")
        if date_range and date_range[0]:
            add_stat_row("Date range in source", f"{date_range[0]} to {date_range[1]}")
        else:
            add_stat_row("Date range in source", "None to None")

        # Show UUID mode status
        if data.get("no_uuid_mode"):
            add_stat_row("UUID Mode", "⚠ No UUID - Add All Features", "#fff3cd")
        else:
            add_stat_row("Unique UUIDs in source", format_record_count(data.get("unique_uuids", 0)))

            # Features without UUID - important warning (only if not in no_uuid_mode)
            features_without_uuid = data.get("features_without_uuid", 0)
            if features_without_uuid > 0:
                add_stat_row("⚠ Features WITHOUT UUID", format_record_count(features_without_uuid), "#ffcccc")

            source_duplicates = data.get("duplicates_in_source", 0)
            if source_duplicates > 0:
                add_stat_row("⚠ Source duplicates (same UUID)", format_record_count(source_duplicates), "#ffcccc")

        # Master Data Section
        add_stat_row("", "")
        add_stat_row("═══ MASTER DATA ═══", "", None, True)
        add_stat_row("Target layer", data.get("target_layer", layer_name))
        add_stat_row("Current records in master", format_record_count(data.get("master_records", 0)))

        master_date_range = data.get("master_date_range")
        if master_date_range:
            add_stat_row("Date range in master", f"{master_date_range[0]} to {master_date_range[1]}")

        # UUID tracker statistics (includes features later deleted/merged)
        tracker_stats = data.get("tracker_stats")
        if tracker_stats and tracker_stats.get("total_uuids"):
            add_stat_row("UUIDs tracked (incl. deleted/merged)",
                         format_record_count(tracker_stats["total_uuids"]))

        # Date Filter Section
        if data.get("date_filter_applied"):
            add_stat_row("", "")
            add_stat_row("═══ DATE FILTER APPLIED ═══", "", None, True)
            add_stat_row("Records passing filter", format_record_count(data.get("filtered_records", 0)), "#e6f7ff")
            add_stat_row("Records filtered out", format_record_count(data.get("filtered_out", 0)))
            add_stat_row("Filter details", data.get("filter_description", ""))

        # Duplicate Analysis Section
        add_stat_row("", "")
        add_stat_row("═══ DUPLICATE ANALYSIS ═══", "", None, True)

        if data.get("no_uuid_mode"):
            add_stat_row("Duplicate checking", "DISABLED (No UUID mode)", "#fff3cd")
        else:
            add_stat_row("UUID duplicates (already in master)", format_record_count(data.get("duplicate_records", 0)))

            if data.get("temporal_overlap"):
                add_stat_row("⚠ Temporal overlap detected", "YES - See warnings below", "#ffeb99")

        # Addition Summary Section
        add_stat_row("", "")
        add_stat_row("═══ ADDITION SUMMARY ═══", "", None, True)
        add_stat_row("✓ Records to be added", format_record_count(data.get("new_records", 0)), "#ccffcc", True)
        add_stat_row("Final total after addition",
                     format_record_count(data.get("master_records", 0) + data.get("new_records", 0)))

        field_count = len(data.get("fields", []))
        add_stat_row("Fields to be added", format_record_count(field_count))

        recoding_count = len(data.get("value_recodings", {}))
        if recoding_count > 0:
            add_stat_row("Value recodings to apply", format_record_count(recoding_count), "#e6e6ff")

        # Field-level default values
        defaults = data.get("default_values", {})
        if defaults:
            add_stat_row("Field defaults configured", format_record_count(len(defaults)), "#cce5ff")
            for field, val in list(defaults.items())[:5]:
                add_stat_row(f"  {field}", f"NULL \u2192 {val}", "#e6f2ff")
            if len(defaults) > 5:
                add_stat_row("  ...", f"and {len(defaults) - 5} more", "#e6f2ff")

        # Update warnings
        self._update_warnings(data)

        # Auto-resize columns
        self.stats_table.resizeColumnsToContents()

    def _update_warnings(self, data: Dict):
        """Update the warnings section"""
        warnings = []

        # Check for No UUID mode
        if data.get("no_uuid_mode"):
            warnings.append(
                f"<b>⚠ NO DUPLICATE CHECKING:</b> This layer has no UUID field configured. "
                f"<b>ALL</b> features will be added without checking for duplicates. "
                f"If you run this again, duplicate features may be added to the master layer."
            )

        # CRITICAL: Check for features without UUID (only if not in no_uuid_mode)
        features_without_uuid = data.get("features_without_uuid", 0)
        if features_without_uuid > 0 and not data.get("no_uuid_mode"):
            warnings.append(
                f"<b>🚨 MISSING UUIDs:</b> {features_without_uuid} features in the source layer "
                f"do not have a UUID value. These features will be <b>SKIPPED</b> during processing. "
                f"If you want these features to be added, please assign UUIDs to them in the source data first."
            )

        # Check for temporal overlap
        if data.get("temporal_overlap"):
            overlap_info = data["temporal_overlap"]
            warnings.append(
                f"<b>⚠ TEMPORAL OVERLAP:</b> New data overlaps with existing data. "
                f"Found {overlap_info.get('overlap_count', 0)} existing records in similar time range. "
                f"This may indicate duplicate data that was previously deleted/merged."
            )

        # Check for source duplicates (duplicate UUIDs within source)
        source_duplicates = data.get("duplicates_in_source", 0)
        if source_duplicates > 0:
            warnings.append(
                f"<b>⚠ SOURCE DUPLICATES:</b> The source data contains {source_duplicates} "
                f"records with duplicate UUIDs. Only the first occurrence of each UUID will be added."
            )

        # Check for high duplicate rate
        total = data.get("total_records", 0)
        duplicates = data.get("duplicate_records", 0)
        if total > 0 and duplicates / total > 0.5:
            warnings.append(
                f"<b>⚠ HIGH DUPLICATE RATE:</b> {(duplicates/total*100):.1f}% of records are duplicates. "
                f"You may want to review the date filter or source data."
            )

        if warnings:
            self.warnings_text.setHtml("<br><br>".join(warnings))
        else:
            self.warnings_text.setHtml("<b>✓ No warnings.</b> Data looks good to proceed.")

    def _create_preview_tab(self) -> QWidget:
        """Create data preview tab with pagination"""
        widget = QWidget()
        layout = QVBoxLayout()

        # Controls
        controls_layout = QHBoxLayout()

        # Layer selector
        controls_layout.addWidget(QLabel("<b>Layer:</b>"))
        self.preview_layer_combo = QComboBox()
        self.preview_layer_combo.addItems(list(self.preview_data.keys()))
        self.preview_layer_combo.currentTextChanged.connect(self._update_preview_table)
        controls_layout.addWidget(self.preview_layer_combo)

        # Show only new records checkbox
        self.show_only_new_checkbox = QCheckBox("Show only records that will be added")
        self.show_only_new_checkbox.setChecked(False)
        self.show_only_new_checkbox.toggled.connect(self._on_show_only_new_toggled)
        controls_layout.addWidget(self.show_only_new_checkbox)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        # Record counter and pagination
        pagination_layout = QHBoxLayout()

        self.record_counter_label = QLabel()
        pagination_layout.addWidget(self.record_counter_label)

        pagination_layout.addStretch()

        self.prev_page_btn = QPushButton("< Previous")
        self.prev_page_btn.clicked.connect(self._prev_page)
        pagination_layout.addWidget(self.prev_page_btn)

        self.page_label = QLabel("Page 1")
        pagination_layout.addWidget(self.page_label)

        self.next_page_btn = QPushButton("Next >")
        self.next_page_btn.clicked.connect(self._next_page)
        pagination_layout.addWidget(self.next_page_btn)

        pagination_layout.addWidget(QLabel("Records per page:"))
        self.records_per_page_spin = QSpinBox()
        self.records_per_page_spin.setRange(10, 500)
        self.records_per_page_spin.setValue(100)
        self.records_per_page_spin.setSingleStep(50)
        self.records_per_page_spin.valueChanged.connect(self._on_records_per_page_changed)
        pagination_layout.addWidget(self.records_per_page_spin)

        layout.addLayout(pagination_layout)

        # Preview table
        self.preview_table = QTableWidget()
        self.preview_table.setSortingEnabled(True)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.preview_table)

        widget.setLayout(layout)

        # Initialize with first layer
        if self.preview_data:
            self._update_preview_table(list(self.preview_data.keys())[0])

        return widget

    def _on_show_only_new_toggled(self, checked):
        """Handle show only new records toggle"""
        self.show_only_new = checked
        self.current_page = 0
        self._update_preview_table(self.preview_layer_combo.currentText())

    def _on_records_per_page_changed(self, value):
        """Handle records per page change"""
        self.records_per_page = value
        self.current_page = 0
        self._update_preview_table(self.preview_layer_combo.currentText())

    def _prev_page(self):
        """Go to previous page"""
        if self.current_page > 0:
            self.current_page -= 1
            self._update_preview_table(self.preview_layer_combo.currentText())

    def _next_page(self):
        """Go to next page"""
        self.current_page += 1
        self._update_preview_table(self.preview_layer_combo.currentText())

    def _update_preview_table(self, layer_name: str):
        """Update the preview table for selected layer"""
        # Inserting rows into a sorted table scrambles them - disable sorting
        # while populating, re-enable at the end
        self.preview_table.setSortingEnabled(False)
        self.preview_table.clear()

        if layer_name not in self.preview_data:
            return

        data = self.preview_data[layer_name]
        sample_records = data.get("sample_records", [])

        # Filter records if needed
        if self.show_only_new:
            sample_records = [r for r in sample_records if r.get("status") == "New"]

        total_records = len(sample_records)

        if not sample_records:
            self.preview_table.setRowCount(1)
            self.preview_table.setColumnCount(1)
            self.preview_table.setItem(0, 0, QTableWidgetItem("No records to display"))
            self.record_counter_label.setText("No records")
            return

        # Calculate pagination
        start_idx = self.current_page * self.records_per_page
        end_idx = min(start_idx + self.records_per_page, total_records)
        page_records = sample_records[start_idx:end_idx]

        # Update counter
        total_pages = (total_records + self.records_per_page - 1) // self.records_per_page
        self.record_counter_label.setText(
            f"Showing records {start_idx + 1}-{end_idx} of {format_record_count(total_records)}"
        )
        self.page_label.setText(f"Page {self.current_page + 1} of {total_pages}")

        # Enable/disable pagination buttons
        self.prev_page_btn.setEnabled(self.current_page > 0)
        self.next_page_btn.setEnabled(end_idx < total_records)

        # Set up columns
        fields = data.get("fields", [])
        self.preview_table.setColumnCount(len(fields) + 1)
        self.preview_table.setHorizontalHeaderLabels(["Status"] + fields)

        # Add rows
        self.preview_table.setRowCount(len(page_records))
        for row, record in enumerate(page_records):
            status = record.get("status", "Unknown")
            status_item = QTableWidgetItem(status)
            if status == "New":
                status_item.setBackground(QColor(200, 255, 200))
                status_item.setForeground(QColor(0, 100, 0))
            elif status == "Duplicate":
                status_item.setBackground(QColor(255, 200, 200))
                status_item.setForeground(QColor(150, 0, 0))
            elif status == "No UUID":
                status_item.setBackground(QColor(255, 200, 100))  # Orange background
                status_item.setForeground(QColor(150, 75, 0))
                status_item.setToolTip("This feature has no UUID and will be SKIPPED")
            self.preview_table.setItem(row, 0, status_item)

            for col, field in enumerate(fields):
                value = record.get("values", {}).get(field, "")
                recoded = record.get("recoded", {}).get(field)

                if recoded is not None and recoded != value:
                    display_text = f"{value} → {recoded}"
                    item = QTableWidgetItem(display_text)
                    item.setToolTip(f"Original: {value}\nRecoded: {recoded}")
                    item.setBackground(QColor(255, 255, 200))
                else:
                    item = QTableWidgetItem(str(value))

                self.preview_table.setItem(row, col + 1, item)

        # Auto-resize columns
        self.preview_table.resizeColumnsToContents()
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.setSortingEnabled(True)

    def _create_duplicates_tab(self) -> QWidget:
        """Create duplicates analysis tab"""
        widget = QWidget()
        layout = QVBoxLayout()

        # Layer selector
        layer_layout = QHBoxLayout()
        layer_layout.addWidget(QLabel("<b>Select Layer:</b>"))
        self.dup_layer_combo = QComboBox()
        self.dup_layer_combo.addItems(list(self.preview_data.keys()))
        self.dup_layer_combo.currentTextChanged.connect(self._update_duplicates_table)
        layer_layout.addWidget(self.dup_layer_combo)
        layer_layout.addStretch()
        layout.addLayout(layer_layout)

        # Duplicates table
        self.duplicates_table = QTableWidget()
        self.duplicates_table.setAlternatingRowColors(True)
        self.duplicates_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.duplicates_table)

        widget.setLayout(layout)

        # Initialize with first layer
        if self.preview_data:
            self._update_duplicates_table(list(self.preview_data.keys())[0])

        return widget

    def _update_duplicates_table(self, layer_name: str):
        """Update the duplicates analysis table"""
        self.duplicates_table.clear()

        if layer_name not in self.preview_data:
            return

        data = self.preview_data[layer_name]
        sample_records = data.get("sample_records", [])

        # Filter only duplicate records
        duplicate_records = [r for r in sample_records if r.get("status") == "Duplicate"]

        if not duplicate_records:
            self.duplicates_table.setRowCount(1)
            self.duplicates_table.setColumnCount(1)
            self.duplicates_table.setItem(0, 0, QTableWidgetItem("✓ No duplicates found in preview"))
            return

        # Set up columns
        fields = data.get("fields", [])
        self.duplicates_table.setColumnCount(len(fields))
        self.duplicates_table.setHorizontalHeaderLabels(fields)

        # Add rows
        self.duplicates_table.setRowCount(len(duplicate_records))
        for row, record in enumerate(duplicate_records):
            for col, field in enumerate(fields):
                value = record.get("values", {}).get(field, "")
                item = QTableWidgetItem(str(value))
                item.setBackground(QColor(255, 220, 220))
                self.duplicates_table.setItem(row, col, item)

        # Auto-resize columns
        self.duplicates_table.resizeColumnsToContents()
        self.duplicates_table.horizontalHeader().setStretchLastSection(True)
