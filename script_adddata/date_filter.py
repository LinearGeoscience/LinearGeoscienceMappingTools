#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Enhanced date filtering with comprehensive timezone support.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, available_timezones
from typing import Optional, Dict, List
from qgis.PyQt.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                                 QComboBox, QCheckBox, QDateTimeEdit, QGroupBox,
                                 QLineEdit, QPushButton, QCompleter)
from qgis.PyQt.QtCore import Qt, QDateTime, QStringListModel
from .utils import FILTER_TYPE_AFTER, FILTER_TYPE_BEFORE, FILTER_TYPE_BETWEEN


class EnhancedTimezoneSelector(QWidget):
    """
    Enhanced timezone selector with search, favorites, and regional grouping.
    """

    # Common timezones by region
    COMMON_TIMEZONES = {
        'Australia': [
            'Australia/Perth',
            'Australia/Sydney',
            'Australia/Melbourne',
            'Australia/Brisbane',
            'Australia/Adelaide',
            'Australia/Darwin',
            'Australia/Hobart',
        ],
        'Asia': [
            'Asia/Singapore',
            'Asia/Tokyo',
            'Asia/Shanghai',
            'Asia/Hong_Kong',
            'Asia/Dubai',
            'Asia/Bangkok',
            'Asia/Jakarta',
        ],
        'Europe': [
            'Europe/London',
            'Europe/Paris',
            'Europe/Berlin',
            'Europe/Rome',
            'Europe/Madrid',
            'Europe/Amsterdam',
            'Europe/Stockholm',
        ],
        'America': [
            'America/New_York',
            'America/Los_Angeles',
            'America/Chicago',
            'America/Denver',
            'America/Toronto',
            'America/Vancouver',
            'America/Mexico_City',
        ],
        'Africa': [
            'Africa/Cairo',
            'Africa/Johannesburg',
            'Africa/Nairobi',
            'Africa/Lagos',
            'Africa/Casablanca',
        ],
        'Pacific': [
            'Pacific/Auckland',
            'Pacific/Fiji',
            'Pacific/Honolulu',
            'Pacific/Guam',
        ]
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Search box
        search_layout = QHBoxLayout()
        search_label = QLabel("Search timezone:")
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Type to search timezones...")
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_box)
        layout.addLayout(search_layout)

        # Timezone combo box
        tz_layout = QHBoxLayout()
        tz_layout.addWidget(QLabel("Timezone:"))
        self.timezone_combo = QComboBox()
        self.timezone_combo.setEditable(True)
        self.timezone_combo.setMaxVisibleItems(20)
        tz_layout.addWidget(self.timezone_combo)
        layout.addLayout(tz_layout)

        # Populate combo box with grouped timezones
        self._populate_timezones()

        # Setup search functionality
        self.search_box.textChanged.connect(self._filter_timezones)

        # Show current UTC offset
        self.offset_label = QLabel()
        self.offset_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self.offset_label)

        # Update offset when timezone changes
        self.timezone_combo.currentTextChanged.connect(self._update_offset_label)
        self._update_offset_label(self.timezone_combo.currentText())

        self.setLayout(layout)

    def _populate_timezones(self):
        """Populate timezone combo box with grouped entries"""
        self.timezone_combo.clear()

        # Add UTC first
        self.timezone_combo.addItem("UTC")

        # Add separator
        self.timezone_combo.insertSeparator(self.timezone_combo.count())

        # Add common timezones by region
        for region, timezones in self.COMMON_TIMEZONES.items():
            # Add region header (disabled item)
            self.timezone_combo.addItem(f"--- {region} ---")
            idx = self.timezone_combo.count() - 1
            self.timezone_combo.model().item(idx).setEnabled(False)

            # Add timezones with UTC offset
            for tz_name in timezones:
                try:
                    tz = ZoneInfo(tz_name)
                    now = datetime.now(tz)
                    offset = now.strftime('%z')
                    offset_formatted = f"{offset[:3]}:{offset[3:]}"
                    display_text = f"{tz_name} (UTC{offset_formatted})"
                    self.timezone_combo.addItem(display_text, tz_name)
                except Exception:
                    self.timezone_combo.addItem(tz_name, tz_name)

        # Add separator
        self.timezone_combo.insertSeparator(self.timezone_combo.count())

        # Add "All Timezones" option
        self.timezone_combo.addItem("--- All Available Timezones ---")
        idx = self.timezone_combo.count() - 1
        self.timezone_combo.model().item(idx).setEnabled(False)

        # Add all available timezones. On Windows QGIS the IANA database may
        # be missing (needs the 'tzdata' package) - fall back to the common
        # list rather than failing to build the dialog.
        try:
            all_tzs = sorted(available_timezones())
        except Exception:
            all_tzs = sorted(tz for tzlist in self.COMMON_TIMEZONES.values() for tz in tzlist)
        common_tz_set = {tz for tzlist in self.COMMON_TIMEZONES.values() for tz in tzlist}
        for tz_name in all_tzs:
            if tz_name not in common_tz_set:
                self.timezone_combo.addItem(tz_name, tz_name)

        # Setup completer for search
        all_tz_list = ["UTC"] + all_tzs
        completer = QCompleter(all_tz_list)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.timezone_combo.setCompleter(completer)

        # Set default to Australia/Perth
        self.set_timezone("Australia/Perth")

    def _filter_timezones(self, search_text):
        """Filter timezones based on search text"""
        if not search_text:
            return

        # Find matching timezones
        search_lower = search_text.lower()
        for i in range(self.timezone_combo.count()):
            text = self.timezone_combo.itemText(i)
            if search_lower in text.lower():
                self.timezone_combo.setCurrentIndex(i)
                break

    def _update_offset_label(self, display_text):
        """Update the UTC offset label"""
        tz_name = self.get_timezone_name()
        if not tz_name:
            return

        try:
            if tz_name == "UTC":
                self.offset_label.setText("UTC±00:00 (No offset)")
            else:
                tz = ZoneInfo(tz_name)
                now = datetime.now(tz)
                offset = now.strftime('%z')
                offset_formatted = f"{offset[:3]}:{offset[3:]}"
                dst_info = " (DST active)" if now.dst() else ""
                self.offset_label.setText(f"Current offset: UTC{offset_formatted}{dst_info}")
        except Exception as e:
            self.offset_label.setText(f"Error: {e}")

    def get_timezone_name(self) -> str:
        """Get the selected timezone name"""
        # Get data from current item (which stores the clean tz name)
        current_data = self.timezone_combo.currentData()
        if current_data:
            return current_data

        # Fallback: extract from display text
        text = self.timezone_combo.currentText()
        if text == "UTC":
            return "UTC"

        # Extract timezone name before parenthesis
        if ' (' in text:
            return text.split(' (')[0]

        return text

    def set_timezone(self, tz_name: str):
        """Set the timezone by name"""
        for i in range(self.timezone_combo.count()):
            if self.timezone_combo.itemData(i) == tz_name:
                self.timezone_combo.setCurrentIndex(i)
                return
            # Also check display text
            if tz_name in self.timezone_combo.itemText(i):
                self.timezone_combo.setCurrentIndex(i)
                return


class GlobalDateFilterWidget(QWidget):
    """Enhanced global date filtering widget with comprehensive timezone support"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Main group box
        group_box = QGroupBox("Global Date Filter")
        group_layout = QVBoxLayout()

        # Enable checkbox
        self.enable_checkbox = QCheckBox("Enable global date filtering for all layers")
        self.enable_checkbox.toggled.connect(self.on_enable_toggled)
        group_layout.addWidget(self.enable_checkbox)

        # Configuration widget
        self.config_widget = QWidget()
        config_layout = QVBoxLayout()

        # Filter type
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Include records:"))
        self.filter_type_combo = QComboBox()
        self.filter_type_combo.addItems(["After date/time", "Before date/time", "Between dates"])
        self.filter_type_combo.currentTextChanged.connect(self.on_filter_type_changed)
        type_layout.addWidget(self.filter_type_combo)
        type_layout.addStretch()
        config_layout.addLayout(type_layout)

        # Enhanced timezone selection
        tz_label = QLabel("<b>Timezone Selection:</b>")
        config_layout.addWidget(tz_label)
        self.timezone_selector = EnhancedTimezoneSelector()
        self.timezone_selector.timezone_combo.currentTextChanged.connect(self.update_preview)
        config_layout.addWidget(self.timezone_selector)

        # Date/time selection
        datetime_layout = QHBoxLayout()

        # Start date/time
        self.start_label = QLabel("After:")
        self.start_datetime = QDateTimeEdit()
        self.start_datetime.setCalendarPopup(True)
        self.start_datetime.setDateTime(QDateTime.currentDateTime().addDays(-30))
        self.start_datetime.setDisplayFormat("dd/MM/yyyy hh:mm")
        datetime_layout.addWidget(self.start_label)
        datetime_layout.addWidget(self.start_datetime)

        # End date/time (for between option)
        self.end_label = QLabel("Before:")
        self.end_datetime = QDateTimeEdit()
        self.end_datetime.setCalendarPopup(True)
        self.end_datetime.setDateTime(QDateTime.currentDateTime())
        self.end_datetime.setDisplayFormat("dd/MM/yyyy hh:mm")
        datetime_layout.addWidget(self.end_label)
        datetime_layout.addWidget(self.end_datetime)

        datetime_layout.addStretch()
        config_layout.addLayout(datetime_layout)

        # Preview
        self.preview_label = QLabel("Preview: No filter active")
        self.preview_label.setStyleSheet(
            "font-style: italic; color: gray; padding: 10px; background-color: #f5f5f5; "
            "border-radius: 3px; border: 1px solid #ddd;"
        )
        self.preview_label.setWordWrap(True)
        config_layout.addWidget(self.preview_label)

        self.config_widget.setLayout(config_layout)
        self.config_widget.setEnabled(False)
        group_layout.addWidget(self.config_widget)

        group_box.setLayout(group_layout)
        layout.addWidget(group_box)

        # Connect signals
        self.start_datetime.dateTimeChanged.connect(self.update_preview)
        self.end_datetime.dateTimeChanged.connect(self.update_preview)

        self.setLayout(layout)
        self.on_filter_type_changed("After date/time")

    def on_enable_toggled(self, checked):
        """Handle enable checkbox toggle"""
        self.config_widget.setEnabled(checked)
        self.update_preview()

    def on_filter_type_changed(self, filter_type):
        """Handle filter type change"""
        if filter_type == "After date/time":
            self.start_label.setText("After:")
            self.start_label.setVisible(True)
            self.start_datetime.setVisible(True)
            self.end_label.setVisible(False)
            self.end_datetime.setVisible(False)
        elif filter_type == "Before date/time":
            self.start_label.setText("Before:")
            self.start_label.setVisible(True)
            self.start_datetime.setVisible(True)
            self.end_label.setVisible(False)
            self.end_datetime.setVisible(False)
        else:  # Between dates
            self.start_label.setText("After:")
            self.start_label.setVisible(True)
            self.start_datetime.setVisible(True)
            self.end_label.setVisible(True)
            self.end_datetime.setVisible(True)

        self.update_preview()

    def update_preview(self):
        """Update preview text"""
        if not self.enable_checkbox.isChecked():
            self.preview_label.setText("Preview: No filter active - all records will be processed")
            return

        filter_type = self.filter_type_combo.currentText()
        tz_name = self.timezone_selector.get_timezone_name()
        tz_display = tz_name if tz_name == "UTC" else tz_name.split('/')[-1]

        # Get local time display
        start_local = self.start_datetime.dateTime().toString("dd/MM/yyyy hh:mm")

        # Get UTC time display
        start_local_dt = self.start_datetime.dateTime().toPyDateTime()
        start_utc_dt = self.convert_local_to_utc(start_local_dt)
        start_utc = start_utc_dt.strftime("%d/%m/%Y %H:%M")

        if filter_type == "After date/time":
            self.preview_label.setText(
                f"Preview: Only records after <b>{start_local}</b> ({tz_display}) / "
                f"<b>{start_utc}</b> (UTC) will be processed"
            )
        elif filter_type == "Before date/time":
            self.preview_label.setText(
                f"Preview: Only records before <b>{start_local}</b> ({tz_display}) / "
                f"<b>{start_utc}</b> (UTC) will be processed"
            )
        else:  # Between
            end_local = self.end_datetime.dateTime().toString("dd/MM/yyyy hh:mm")
            end_local_dt = self.end_datetime.dateTime().toPyDateTime()
            end_utc_dt = self.convert_local_to_utc(end_local_dt)
            end_utc = end_utc_dt.strftime("%d/%m/%Y %H:%M")
            self.preview_label.setText(
                f"Preview: Records between <b>{start_local}</b> ({tz_display}) / "
                f"<b>{start_utc}</b> (UTC) and <b>{end_local}</b> ({tz_display}) / "
                f"<b>{end_utc}</b> (UTC) will be processed"
            )

    def convert_local_to_utc(self, local_dt: datetime) -> datetime:
        """Convert a naive datetime from local timezone to UTC"""
        tz_name = self.timezone_selector.get_timezone_name()
        if tz_name == "UTC":
            return local_dt.replace(tzinfo=timezone.utc)

        try:
            local_tz = ZoneInfo(tz_name)
            local_aware = local_dt.replace(tzinfo=local_tz)
            utc_dt = local_aware.astimezone(timezone.utc)
            return utc_dt.replace(tzinfo=None)
        except Exception:
            # Fallback to UTC
            return local_dt.replace(tzinfo=timezone.utc).replace(tzinfo=None)

    def get_filter_config(self) -> Optional[Dict]:
        """Get current filter configuration"""
        if not self.enable_checkbox.isChecked():
            return None

        # Map display text to filter type constants
        filter_text = self.filter_type_combo.currentText()
        filter_type_map = {
            "After date/time": FILTER_TYPE_AFTER,
            "Before date/time": FILTER_TYPE_BEFORE,
            "Between dates": FILTER_TYPE_BETWEEN,
        }
        filter_type = filter_type_map.get(filter_text, FILTER_TYPE_AFTER)

        # Get local datetimes from UI
        start_local = self.start_datetime.dateTime().toPyDateTime()
        end_local = self.end_datetime.dateTime().toPyDateTime() if filter_type == FILTER_TYPE_BETWEEN else None

        # Convert to UTC
        start_utc = self.convert_local_to_utc(start_local)
        end_utc = self.convert_local_to_utc(end_local) if end_local else None

        config = {
            'enabled': True,
            'type': filter_type,
            'start_datetime': start_utc,
            'end_datetime': end_utc,
            'timezone_name': self.timezone_selector.get_timezone_name()
        }
        return config
