"""
Add/Subtract Declination Tool for Linear Geoscience Mapping Tools
Allows adding or subtracting a declination value from azimuth fields with preview
"""

from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                   QComboBox, QPushButton, QSpinBox, QRadioButton,
                                   QButtonGroup, QTableWidget, QTableWidgetItem,
                                   QMessageBox, QHeaderView, QGroupBox,
                                   QCheckBox, QDateEdit)
from qgis.PyQt.QtCore import Qt, QDate
from qgis.core import QgsProject, QgsVectorLayer
from qgis.utils import iface
from datetime import datetime

try:
    from .layer_select import layer_candidates, populate_layer_combo, combo_current_layer
except ImportError:
    from layer_select import layer_candidates, populate_layer_combo, combo_current_layer


class DeclinationAdjusterDialog(QDialog):
    """Dialog for adjusting declination values in azimuth fields"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add/Subtract Declination")
        self.setMinimumWidth(800)
        self.setMinimumHeight(650)

        self.layer = None
        self.field_name = None
        self.date_field_name = None
        self.preview_data = []

        self.init_ui()
        self.populate_layers()

    def init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout()

        # Layer selection
        layer_group = QGroupBox("Layer Selection")
        layer_layout = QVBoxLayout()

        layer_select_layout = QHBoxLayout()
        layer_select_layout.addWidget(QLabel("Select Layer:"))
        self.layer_combo = QComboBox()
        self.layer_combo.currentIndexChanged.connect(self.on_layer_changed)
        layer_select_layout.addWidget(self.layer_combo)
        layer_layout.addLayout(layer_select_layout)

        field_select_layout = QHBoxLayout()
        field_select_layout.addWidget(QLabel("Select Field (Azimuth):"))
        self.field_combo = QComboBox()
        self.field_combo.currentIndexChanged.connect(self.update_preview)
        field_select_layout.addWidget(self.field_combo)
        layer_layout.addLayout(field_select_layout)

        layer_group.setLayout(layer_layout)
        layout.addWidget(layer_group)

        # Operation selection
        operation_group = QGroupBox("Operation")
        operation_layout = QVBoxLayout()

        self.operation_group = QButtonGroup()
        self.add_radio = QRadioButton("Add")
        self.subtract_radio = QRadioButton("Subtract")
        self.add_radio.setChecked(True)
        self.operation_group.addButton(self.add_radio)
        self.operation_group.addButton(self.subtract_radio)

        operation_layout.addWidget(self.add_radio)
        operation_layout.addWidget(self.subtract_radio)

        value_layout = QHBoxLayout()
        value_layout.addWidget(QLabel("Declination Value (degrees):"))
        self.value_spin = QSpinBox()
        self.value_spin.setMinimum(0)
        self.value_spin.setMaximum(359)
        self.value_spin.setValue(20)
        self.value_spin.valueChanged.connect(self.update_preview)
        value_layout.addWidget(self.value_spin)
        value_layout.addStretch()

        operation_layout.addLayout(value_layout)
        operation_group.setLayout(operation_layout)
        layout.addWidget(operation_group)

        self.add_radio.toggled.connect(self.update_preview)

        # Selection Filter
        selection_group = QGroupBox("Feature Selection")
        selection_layout = QVBoxLayout()

        self.selected_only_check = QCheckBox("Apply to selected features only")
        self.selected_only_check.stateChanged.connect(self.update_preview)
        selection_layout.addWidget(self.selected_only_check)

        selection_group.setLayout(selection_layout)
        layout.addWidget(selection_group)

        # Date Filter
        date_filter_group = QGroupBox("Date Filter (Optional)")
        date_filter_layout = QVBoxLayout()

        self.date_filter_enable = QCheckBox("Enable Date Filter")
        self.date_filter_enable.stateChanged.connect(self.on_date_filter_toggled)
        date_filter_layout.addWidget(self.date_filter_enable)

        # Date field selection
        date_field_layout = QHBoxLayout()
        date_field_layout.addWidget(QLabel("Date Field:"))
        self.date_field_combo = QComboBox()
        self.date_field_combo.currentIndexChanged.connect(self.update_preview)
        date_field_layout.addWidget(self.date_field_combo)
        date_filter_layout.addLayout(date_field_layout)

        # Date filter type
        self.date_filter_group = QButtonGroup()
        self.before_radio = QRadioButton("Before")
        self.after_radio = QRadioButton("After")
        self.date_range_radio = QRadioButton("Date Range")
        self.after_radio.setChecked(True)
        self.date_filter_group.addButton(self.before_radio)
        self.date_filter_group.addButton(self.after_radio)
        self.date_filter_group.addButton(self.date_range_radio)

        date_type_layout = QHBoxLayout()
        date_type_layout.addWidget(self.before_radio)
        date_type_layout.addWidget(self.after_radio)
        date_type_layout.addWidget(self.date_range_radio)
        date_filter_layout.addLayout(date_type_layout)

        self.before_radio.toggled.connect(self.on_date_type_changed)
        self.after_radio.toggled.connect(self.on_date_type_changed)
        self.date_range_radio.toggled.connect(self.on_date_type_changed)

        # Single date picker
        single_date_layout = QHBoxLayout()
        single_date_layout.addWidget(QLabel("Date:"))
        self.single_date_edit = QDateEdit()
        self.single_date_edit.setCalendarPopup(True)
        self.single_date_edit.setDate(QDate.currentDate())
        self.single_date_edit.dateChanged.connect(self.update_preview)
        single_date_layout.addWidget(self.single_date_edit)
        single_date_layout.addStretch()
        date_filter_layout.addLayout(single_date_layout)

        # Date range pickers
        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel("From:"))
        self.from_date_edit = QDateEdit()
        self.from_date_edit.setCalendarPopup(True)
        self.from_date_edit.setDate(QDate.currentDate().addMonths(-1))
        self.from_date_edit.dateChanged.connect(self.update_preview)
        range_layout.addWidget(self.from_date_edit)

        range_layout.addWidget(QLabel("To:"))
        self.to_date_edit = QDateEdit()
        self.to_date_edit.setCalendarPopup(True)
        self.to_date_edit.setDate(QDate.currentDate())
        self.to_date_edit.dateChanged.connect(self.update_preview)
        range_layout.addWidget(self.to_date_edit)
        date_filter_layout.addLayout(range_layout)

        date_filter_group.setLayout(date_filter_layout)
        layout.addWidget(date_filter_group)

        # Initially disable date filter widgets
        self.date_field_combo.setEnabled(False)
        self.before_radio.setEnabled(False)
        self.after_radio.setEnabled(False)
        self.date_range_radio.setEnabled(False)
        self.single_date_edit.setEnabled(False)
        self.from_date_edit.setEnabled(False)
        self.to_date_edit.setEnabled(False)

        # Preview button
        preview_button_layout = QHBoxLayout()
        self.preview_button = QPushButton("Generate Preview")
        self.preview_button.clicked.connect(self.update_preview)
        preview_button_layout.addWidget(self.preview_button)
        preview_button_layout.addStretch()
        layout.addLayout(preview_button_layout)

        # Preview table
        preview_label = QLabel("Preview (showing first 100 non-null values):")
        layout.addWidget(preview_label)

        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(3)
        self.preview_table.setHorizontalHeaderLabels(["Feature ID", "Original Value", "New Value"])
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.preview_table)

        # Buttons
        button_layout = QHBoxLayout()
        self.apply_button = QPushButton("Apply Changes")
        self.apply_button.clicked.connect(self.apply_changes)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)

        button_layout.addStretch()
        button_layout.addWidget(self.apply_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def populate_layers(self):
        """Populate the layer combo box with vector layers"""
        populate_layer_combo(self.layer_combo, layer_candidates())
        # Signals are blocked during population — refresh dependent UI manually
        self.on_layer_changed()

    def on_layer_changed(self):
        """Handle layer selection change"""
        self.field_combo.clear()
        self.date_field_combo.clear()

        if self.layer_combo.currentIndex() < 0:
            return

        self.layer = combo_current_layer(self.layer_combo)

        if self.layer is None:
            return

        # Populate azimuth fields - only numeric fields
        for field in self.layer.fields():
            if field.type() in [2, 3, 4, 6]:  # Integer and Double types
                self.field_combo.addItem(field.name(), field.name())

        # Populate date fields - Date, DateTime, and String fields (for text dates)
        for field in self.layer.fields():
            if field.type() in [14, 16, 10]:  # Date, DateTime, and String types
                self.date_field_combo.addItem(field.name(), field.name())

        # Update selected features count
        if self.layer.selectedFeatureCount() > 0:
            self.selected_only_check.setText(
                f"Apply to selected features only ({self.layer.selectedFeatureCount()} selected)")
        else:
            self.selected_only_check.setText("Apply to selected features only (none selected)")
            self.selected_only_check.setChecked(False)

        self.update_preview()

    def calculate_new_azimuth(self, original_value, adjustment, is_addition):
        """Calculate new azimuth value with mod 360"""
        if original_value is None:
            return None

        try:
            original = float(original_value)

            if is_addition:
                new_value = original + adjustment
            else:
                new_value = original - adjustment

            # Apply mod 360 to keep value in 0-359 range
            new_value = new_value % 360

            return round(new_value, 2)
        except (ValueError, TypeError):
            return None

    def on_date_filter_toggled(self):
        """Handle date filter enable/disable"""
        enabled = self.date_filter_enable.isChecked()
        self.date_field_combo.setEnabled(enabled)
        self.before_radio.setEnabled(enabled)
        self.after_radio.setEnabled(enabled)
        self.date_range_radio.setEnabled(enabled)
        self.on_date_type_changed()
        self.update_preview()

    def on_date_type_changed(self):
        """Handle date filter type change"""
        if not self.date_filter_enable.isChecked():
            self.single_date_edit.setEnabled(False)
            self.from_date_edit.setEnabled(False)
            self.to_date_edit.setEnabled(False)
            return

        if self.date_range_radio.isChecked():
            self.single_date_edit.setEnabled(False)
            self.from_date_edit.setEnabled(True)
            self.to_date_edit.setEnabled(True)
        else:
            self.single_date_edit.setEnabled(True)
            self.from_date_edit.setEnabled(False)
            self.to_date_edit.setEnabled(False)

        self.update_preview()

    def parse_date_value(self, date_value):
        """Parse a date value from various formats"""
        if date_value is None:
            return None

        # If it's already a QDate
        if isinstance(date_value, QDate):
            return date_value.toPyDate()

        # If it's a string, try to parse it
        if isinstance(date_value, str):
            # Try common date formats
            for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d', '%d-%m-%Y']:
                try:
                    return datetime.strptime(date_value, fmt).date()
                except ValueError:
                    continue
            return None

        # If it's a datetime object
        try:
            return date_value.date() if hasattr(date_value, 'date') else date_value
        except Exception:
            return None

    def feature_passes_date_filter(self, feature):
        """Check if a feature passes the date filter"""
        if not self.date_filter_enable.isChecked():
            return True

        if self.date_field_combo.currentIndex() < 0:
            return True

        date_field_name = self.date_field_combo.currentData()
        if not date_field_name:
            return True

        date_field_index = self.layer.fields().indexOf(date_field_name)
        if date_field_index < 0:
            return True

        feature_date_value = feature[date_field_index]
        feature_date = self.parse_date_value(feature_date_value)

        if feature_date is None:
            return False

        if self.before_radio.isChecked():
            compare_date = self.single_date_edit.date().toPyDate()
            return feature_date < compare_date
        elif self.after_radio.isChecked():
            compare_date = self.single_date_edit.date().toPyDate()
            return feature_date > compare_date
        elif self.date_range_radio.isChecked():
            from_date = self.from_date_edit.date().toPyDate()
            to_date = self.to_date_edit.date().toPyDate()
            return from_date <= feature_date <= to_date

        return True

    def get_filtered_features(self):
        """Get features that pass all filters"""
        if self.layer is None:
            return []

        # Start with all features or selected features
        if self.selected_only_check.isChecked():
            if self.layer.selectedFeatureCount() == 0:
                return []
            features = self.layer.selectedFeatures()
        else:
            features = list(self.layer.getFeatures())

        # Apply date filter if enabled
        if self.date_filter_enable.isChecked():
            features = [f for f in features if self.feature_passes_date_filter(f)]

        return features

    def update_preview(self):
        """Update the preview table"""
        self.preview_table.setRowCount(0)
        self.preview_data = []

        if self.layer_combo.currentIndex() < 0 or self.field_combo.currentIndex() < 0:
            return

        self.layer = combo_current_layer(self.layer_combo)
        self.field_name = self.field_combo.currentData()

        if self.layer is None or self.field_name is None:
            return

        adjustment = self.value_spin.value()
        is_addition = self.add_radio.isChecked()

        # Get field index
        field_index = self.layer.fields().indexOf(self.field_name)

        if field_index < 0:
            return

        # Get filtered features
        filtered_features = self.get_filtered_features()

        # Collect preview data (limit to first 100 non-null values)
        count = 0
        for feature in filtered_features:
            original_value = feature[field_index]

            if original_value is not None and original_value != '':
                new_value = self.calculate_new_azimuth(original_value, adjustment, is_addition)

                if new_value is not None:
                    self.preview_data.append({
                        'fid': feature.id(),
                        'original': original_value,
                        'new': new_value
                    })

                    count += 1
                    if count >= 100:
                        break

        # Populate table
        self.preview_table.setRowCount(len(self.preview_data))

        for row, data in enumerate(self.preview_data):
            self.preview_table.setItem(row, 0, QTableWidgetItem(str(data['fid'])))
            self.preview_table.setItem(row, 1, QTableWidgetItem(str(data['original'])))
            self.preview_table.setItem(row, 2, QTableWidgetItem(str(data['new'])))

    def apply_changes(self):
        """Apply the declination adjustment to filtered non-null values"""
        if self.layer is None or self.field_name is None:
            QMessageBox.warning(self, "Error", "Please select a layer and field")
            return

        # Validate filters
        if self.selected_only_check.isChecked() and self.layer.selectedFeatureCount() == 0:
            QMessageBox.warning(self, "Error", "No features are selected")
            return

        # Get filtered features
        filtered_features = self.get_filtered_features()

        # Count features that will be modified
        field_index = self.layer.fields().indexOf(self.field_name)
        total_features = sum(1 for f in filtered_features
                            if f[field_index] is not None and f[field_index] != '')

        if total_features == 0:
            QMessageBox.warning(self, "No Features", "No features match the current filters with non-null values.")
            return

        # Confirm with user
        adjustment = self.value_spin.value()
        operation = "add" if self.add_radio.isChecked() else "subtract"

        # Build confirmation message with filter info
        filter_info = []
        if self.selected_only_check.isChecked():
            filter_info.append(f"Selected features only ({self.layer.selectedFeatureCount()} selected)")
        if self.date_filter_enable.isChecked():
            date_field = self.date_field_combo.currentText()
            if self.before_radio.isChecked():
                filter_info.append(f"Before {self.single_date_edit.date().toString('yyyy-MM-dd')}")
            elif self.after_radio.isChecked():
                filter_info.append(f"After {self.single_date_edit.date().toString('yyyy-MM-dd')}")
            elif self.date_range_radio.isChecked():
                filter_info.append(f"Between {self.from_date_edit.date().toString('yyyy-MM-dd')} and {self.to_date_edit.date().toString('yyyy-MM-dd')}")

        msg = f"This will {operation} {adjustment} degrees to {total_features} features."
        if filter_info:
            msg += f"\n\nFilters applied:\n  - " + "\n  - ".join(filter_info)
        msg += "\n\nContinue?"

        reply = QMessageBox.question(self, "Confirm Changes", msg,
                                     QMessageBox.Yes | QMessageBox.No)

        if reply != QMessageBox.Yes:
            return

        # Apply changes
        is_addition = self.add_radio.isChecked()
        update_count = 0

        # Create a set of feature IDs to update for efficient lookup
        feature_ids_to_update = {f.id() for f in filtered_features}

        # Check if layer is already in edit mode, if not start editing
        was_editable = self.layer.isEditable()
        if not was_editable:
            if not self.layer.startEditing():
                QMessageBox.critical(self, "Error",
                                   f"Cannot start editing layer '{self.layer.name()}'. "
                                   "The layer may be read-only or not support editing.")
                return

        try:
            for feature in self.layer.getFeatures():
                # Only update if feature is in our filtered set
                if feature.id() not in feature_ids_to_update:
                    continue

                original_value = feature[field_index]

                if original_value is not None and original_value != '':
                    new_value = self.calculate_new_azimuth(original_value, adjustment, is_addition)

                    if new_value is not None:
                        self.layer.changeAttributeValue(feature.id(), field_index, new_value)
                        update_count += 1

            # Commit changes if we started the edit session
            if not was_editable:
                if not self.layer.commitChanges():
                    error_msg = "Failed to commit changes:\n" + "\n".join(self.layer.commitErrors())
                    QMessageBox.critical(self, "Error", error_msg)
                    return
        except Exception as e:
            # Rollback if we started the edit session and an error occurred
            if not was_editable and self.layer.isEditable():
                self.layer.rollBack()
            QMessageBox.critical(self, "Error", f"An error occurred while updating features: {str(e)}")
            return

        # Refresh the layer
        self.layer.triggerRepaint()
        iface.mapCanvas().refresh()

        QMessageBox.information(self, "Success",
                               f"Successfully updated {update_count} features!")

        self.accept()


def run_declination_adjuster():
    """Main function to run the declination adjuster"""
    dialog = DeclinationAdjusterDialog(iface.mainWindow())
    dialog.exec()


# Allow running from QGIS Python console
if __name__ == '__console__':
    run_declination_adjuster()
