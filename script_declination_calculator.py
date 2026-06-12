"""
Calculate Magnetic Declination using WMM - PyQGIS Tool
Calculates magnetic declination for points using the World Magnetic Model (WMM)
"""

from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                  QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
                                  QMessageBox, QHeaderView, QGroupBox, QAction,
                                  QCheckBox, QDateEdit, QDoubleSpinBox, QRadioButton,
                                  QButtonGroup, QProgressDialog, QTextEdit)
from qgis.PyQt.QtCore import Qt, QDate, QVariant
from qgis.PyQt.QtGui import QIcon
from qgis.core import (QgsProject, QgsVectorLayer, QgsField, edit,
                       QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsPointXY, QgsWkbTypes)
from qgis.utils import iface
import os
from datetime import datetime
import datetime as dt

# Try to import geomag library for WMM calculations
try:
    import geomag
    GEOMAG_AVAILABLE = True
except ImportError:
    GEOMAG_AVAILABLE = False

try:
    from .layer_select import layer_candidates, populate_layer_combo, combo_current_layer
except ImportError:
    from layer_select import layer_candidates, populate_layer_combo, combo_current_layer


class CalculateDeclinationDialog(QDialog):
    """Dialog for calculating magnetic declination using WMM"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calculate Magnetic Declination (WMM)")
        self.setMinimumWidth(900)
        self.setMinimumHeight(700)

        self.layer = None
        self.preview_data = []

        self.init_ui()
        self.populate_layers()

    def init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout()

        # Check if geomag is available
        if not GEOMAG_AVAILABLE:
            warning_label = QLabel("⚠️ WARNING: 'geomag' library not installed!\n"
                                  "Install with: pip install geomag\n"
                                  "The script will not work without this library.")
            warning_label.setStyleSheet("color: red; font-weight: bold; padding: 10px; background-color: #ffeeee;")
            layout.addWidget(warning_label)

        # Layer selection
        layer_group = QGroupBox("Layer Selection")
        layer_layout = QVBoxLayout()

        layer_select_layout = QHBoxLayout()
        layer_select_layout.addWidget(QLabel("Select Layer:"))
        self.layer_combo = QComboBox()
        self.layer_combo.currentIndexChanged.connect(self.on_layer_changed)
        layer_select_layout.addWidget(self.layer_combo)
        layer_layout.addLayout(layer_select_layout)

        layer_group.setLayout(layer_layout)
        layout.addWidget(layer_group)

        # CRS Information
        crs_group = QGroupBox("Coordinate Reference System")
        crs_layout = QVBoxLayout()

        self.crs_info_label = QLabel("No layer selected")
        self.crs_info_label.setStyleSheet("padding: 5px; background-color: #f0f0f0; font-family: monospace;")
        self.crs_info_label.setWordWrap(True)
        crs_layout.addWidget(self.crs_info_label)

        crs_group.setLayout(crs_layout)
        layout.addWidget(crs_group)

        # Coordinate source selection
        coord_group = QGroupBox("Coordinate Source")
        coord_layout = QVBoxLayout()

        self.coord_source_group = QButtonGroup()
        self.use_geometry_radio = QRadioButton("Use layer geometry (automatic)")
        self.use_fields_radio = QRadioButton("Use coordinate fields")
        self.use_geometry_radio.setChecked(True)
        self.coord_source_group.addButton(self.use_geometry_radio)
        self.coord_source_group.addButton(self.use_fields_radio)

        coord_layout.addWidget(self.use_geometry_radio)
        coord_layout.addWidget(self.use_fields_radio)

        # Coordinate fields
        fields_layout = QHBoxLayout()
        fields_layout.addWidget(QLabel("Easting/X Field:"))
        self.x_field_combo = QComboBox()
        fields_layout.addWidget(self.x_field_combo)
        fields_layout.addWidget(QLabel("Northing/Y Field:"))
        self.y_field_combo = QComboBox()
        fields_layout.addWidget(self.y_field_combo)
        coord_layout.addLayout(fields_layout)

        self.use_geometry_radio.toggled.connect(self.on_coord_source_changed)
        coord_group.setLayout(coord_layout)
        layout.addWidget(coord_group)

        # Output field selection
        output_group = QGroupBox("Output Field")
        output_layout = QVBoxLayout()

        field_select_layout = QHBoxLayout()
        field_select_layout.addWidget(QLabel("Declination Field:"))
        self.declination_field_combo = QComboBox()
        field_select_layout.addWidget(self.declination_field_combo)

        self.create_field_button = QPushButton("Create New Field")
        self.create_field_button.clicked.connect(self.create_declination_field)
        field_select_layout.addWidget(self.create_field_button)

        output_layout.addLayout(field_select_layout)
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)

        # Optional parameters
        params_group = QGroupBox("Optional Parameters")
        params_layout = QVBoxLayout()

        # Elevation
        elevation_layout = QHBoxLayout()
        self.elevation_check = QCheckBox("Use elevation field:")
        self.elevation_field_combo = QComboBox()
        self.elevation_check.stateChanged.connect(self.on_elevation_toggled)
        elevation_layout.addWidget(self.elevation_check)
        elevation_layout.addWidget(self.elevation_field_combo)

        elevation_layout.addWidget(QLabel("Default elevation (m):"))
        self.default_elevation_spin = QDoubleSpinBox()
        self.default_elevation_spin.setMinimum(-500)
        self.default_elevation_spin.setMaximum(10000)
        self.default_elevation_spin.setValue(0)
        self.default_elevation_spin.setSuffix(" m")
        elevation_layout.addWidget(self.default_elevation_spin)
        params_layout.addLayout(elevation_layout)

        # Date
        date_layout = QHBoxLayout()
        self.date_check = QCheckBox("Use date field:")
        self.date_field_combo = QComboBox()
        self.date_check.stateChanged.connect(self.on_date_toggled)
        date_layout.addWidget(self.date_check)
        date_layout.addWidget(self.date_field_combo)

        date_layout.addWidget(QLabel("Default date:"))
        self.default_date_edit = QDateEdit()
        self.default_date_edit.setCalendarPopup(True)
        self.default_date_edit.setDate(QDate.currentDate())
        date_layout.addWidget(self.default_date_edit)
        params_layout.addLayout(date_layout)

        params_group.setLayout(params_layout)
        layout.addWidget(params_group)

        # Selection filter
        selection_group = QGroupBox("Feature Selection")
        selection_layout = QVBoxLayout()
        self.selected_only_check = QCheckBox("Calculate for selected features only")
        selection_layout.addWidget(self.selected_only_check)
        selection_group.setLayout(selection_layout)
        layout.addWidget(selection_group)

        # Preview button
        preview_button_layout = QHBoxLayout()
        self.preview_button = QPushButton("Generate Preview")
        self.preview_button.clicked.connect(self.update_preview)
        preview_button_layout.addWidget(self.preview_button)
        preview_button_layout.addStretch()
        layout.addLayout(preview_button_layout)

        # Preview table
        preview_label = QLabel("Preview (showing first 50 features):")
        layout.addWidget(preview_label)

        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(6)
        self.preview_table.setHorizontalHeaderLabels([
            "Feature ID", "Longitude", "Latitude", "Elevation (m)", "Date", "Declination (°)"
        ])
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.preview_table)

        # Buttons
        button_layout = QHBoxLayout()
        self.calculate_button = QPushButton("Calculate and Apply")
        self.calculate_button.clicked.connect(self.calculate_declination)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)

        button_layout.addStretch()
        button_layout.addWidget(self.calculate_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        # Initially disable coordinate fields
        self.on_coord_source_changed()
        self.on_elevation_toggled()
        self.on_date_toggled()

    def populate_layers(self):
        """Populate the layer combo box with vector layers"""
        populate_layer_combo(self.layer_combo, layer_candidates())
        # Signals are blocked during population — refresh dependent UI manually
        self.on_layer_changed()

    def on_layer_changed(self):
        """Handle layer selection change"""
        self.x_field_combo.clear()
        self.y_field_combo.clear()
        self.declination_field_combo.clear()
        self.elevation_field_combo.clear()
        self.date_field_combo.clear()

        if self.layer_combo.currentIndex() < 0:
            self.crs_info_label.setText("No layer selected")
            return

        self.layer = combo_current_layer(self.layer_combo)

        if self.layer is None:
            self.crs_info_label.setText("No layer selected")
            return

        # Update CRS information
        crs = self.layer.crs()
        feature_count = self.layer.featureCount()
        geom_type = QgsWkbTypes.displayString(self.layer.wkbType())

        crs_text = f"Layer CRS: {crs.authid()} - {crs.description()}\n"
        crs_text += f"Target CRS: EPSG:4326 (WGS 84) - Required for WMM calculations\n"
        crs_text += f"Geometry: {geom_type} | Features: {feature_count}"

        if not crs.isValid():
            crs_text += "\n⚠️ WARNING: Layer CRS is not valid!"
            self.crs_info_label.setStyleSheet("padding: 5px; background-color: #ffeeee; font-family: monospace; color: red;")
        else:
            self.crs_info_label.setStyleSheet("padding: 5px; background-color: #eeffee; font-family: monospace;")

        self.crs_info_label.setText(crs_text)

        # Populate numeric fields for coordinates and elevation
        for field in self.layer.fields():
            if field.type() in [2, 3, 4, 6]:  # Integer and Double types
                self.x_field_combo.addItem(field.name(), field.name())
                self.y_field_combo.addItem(field.name(), field.name())
                self.declination_field_combo.addItem(field.name(), field.name())
                self.elevation_field_combo.addItem(field.name(), field.name())

        # Populate date fields
        for field in self.layer.fields():
            if field.type() in [14, 16, 10]:  # Date, DateTime, and String types
                self.date_field_combo.addItem(field.name(), field.name())

        # Update selected features count
        if self.layer.selectedFeatureCount() > 0:
            self.selected_only_check.setText(
                f"Calculate for selected features only ({self.layer.selectedFeatureCount()} selected)")
        else:
            self.selected_only_check.setText("Calculate for selected features only (none selected)")
            self.selected_only_check.setChecked(False)

    def on_coord_source_changed(self):
        """Handle coordinate source radio button change"""
        use_fields = self.use_fields_radio.isChecked()
        self.x_field_combo.setEnabled(use_fields)
        self.y_field_combo.setEnabled(use_fields)

    def on_elevation_toggled(self):
        """Handle elevation checkbox toggle"""
        enabled = self.elevation_check.isChecked()
        self.elevation_field_combo.setEnabled(enabled)

    def on_date_toggled(self):
        """Handle date checkbox toggle"""
        enabled = self.date_check.isChecked()
        self.date_field_combo.setEnabled(enabled)

    def create_declination_field(self):
        """Create a new declination field in the layer"""
        if self.layer is None:
            QMessageBox.warning(self, "Error", "Please select a layer first")
            return

        field_name = "Declination"

        # Check if field already exists
        if self.layer.fields().indexOf(field_name) >= 0:
            reply = QMessageBox.question(
                self, "Field Exists",
                f"Field '{field_name}' already exists. Use it anyway?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                # Select the existing field
                index = self.declination_field_combo.findText(field_name)
                if index >= 0:
                    self.declination_field_combo.setCurrentIndex(index)
                return
            else:
                return

        # Create new field
        with edit(self.layer):
            field = QgsField(field_name, QVariant.Double)
            self.layer.addAttribute(field)

        # Refresh the combo box
        self.on_layer_changed()

        # Select the newly created field
        index = self.declination_field_combo.findText(field_name)
        if index >= 0:
            self.declination_field_combo.setCurrentIndex(index)

        QMessageBox.information(self, "Success", f"Field '{field_name}' created successfully!")

    def get_coordinates(self, feature):
        """Get coordinates for a feature (either from geometry or fields)"""
        if self.use_geometry_radio.isChecked():
            # Use geometry
            geom = feature.geometry()

            # Check if geometry is valid
            if geom is None or geom.isEmpty():
                return None, None

            # Handle different geometry types
            if geom.type() == QgsWkbTypes.PointGeometry:
                if geom.isMultipart():
                    # For multipart geometries, use the first point
                    points = geom.asMultiPoint()
                    point = points[0] if points else None
                else:
                    point = geom.asPoint()

                if point:
                    return point.x(), point.y()

            return None, None
        else:
            # Use fields
            x_field = self.x_field_combo.currentData()
            y_field = self.y_field_combo.currentData()

            if not x_field or not y_field:
                return None, None

            x_idx = self.layer.fields().indexOf(x_field)
            y_idx = self.layer.fields().indexOf(y_field)

            x = feature[x_idx]
            y = feature[y_idx]

            # Validate coordinates are numeric
            try:
                if x is not None and y is not None:
                    return float(x), float(y)
            except (ValueError, TypeError):
                return None, None

            return None, None

    def transform_to_wgs84(self, x, y):
        """Transform coordinates to WGS84 (lat/lon)"""
        source_crs = self.layer.crs()
        dest_crs = QgsCoordinateReferenceSystem("EPSG:4326")  # WGS84

        transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
        point = QgsPointXY(x, y)

        try:
            transformed_point = transform.transform(point)
            return transformed_point.y(), transformed_point.x()  # Return lat, lon
        except Exception as e:
            return None, None

    def get_elevation(self, feature):
        """Get elevation for a feature"""
        if self.elevation_check.isChecked():
            elevation_field = self.elevation_field_combo.currentData()
            if elevation_field:
                elevation_idx = self.layer.fields().indexOf(elevation_field)
                elevation = feature[elevation_idx]
                if elevation is not None:
                    return float(elevation)

        return self.default_elevation_spin.value()

    def get_date(self, feature):
        """Get date for a feature"""
        if self.date_check.isChecked():
            date_field = self.date_field_combo.currentData()
            if date_field:
                date_idx = self.layer.fields().indexOf(date_field)
                date_value = feature[date_idx]

                # Parse date
                if date_value is not None:
                    if isinstance(date_value, QDate):
                        py_date = date_value.toPyDate()
                        if py_date:
                            return py_date
                    elif isinstance(date_value, str):
                        # Try common date formats
                        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d']:
                            try:
                                return datetime.strptime(date_value, fmt).date()
                            except ValueError:
                                continue
                    elif hasattr(date_value, 'date'):
                        try:
                            return date_value.date()
                        except Exception:
                            pass

        # Always return default date as fallback
        default_qdate = self.default_date_edit.date()
        py_date = default_qdate.toPyDate()
        return py_date

    def calculate_declination_value(self, lat, lon, elevation_m, date):
        """Calculate magnetic declination using WMM"""
        if not GEOMAG_AVAILABLE:
            raise ImportError("geomag library not available")

        # Validate inputs
        if not isinstance(date, (dt.date, datetime)):
            raise TypeError(f"date must be a date object, got {type(date).__name__}: {date}")

        # Normalize date input for geomag (expects datetime/date object)
        if isinstance(date, datetime):
            date = date.date()

        # Convert elevation from meters to feet (geomag expects feet)
        elevation_ft = float(elevation_m) * 3.2808399

        # Calculate declination using geomag
        mag_field = geomag.declination(lat, lon, elevation_ft, date)

        return round(mag_field, 2)

    def update_preview(self):
        """Update the preview table"""
        self.preview_table.setRowCount(0)
        self.preview_data = []

        if not GEOMAG_AVAILABLE:
            QMessageBox.warning(self, "Error",
                              "geomag library not installed!\n\n"
                              "Install with: pip install geomag")
            return

        if self.layer_combo.currentIndex() < 0:
            return

        self.layer = combo_current_layer(self.layer_combo)
        if self.layer is None:
            return

        # Check if using fields mode and fields are selected
        if self.use_fields_radio.isChecked():
            if not self.x_field_combo.currentData() or not self.y_field_combo.currentData():
                QMessageBox.warning(self, "Error", "Please select X and Y coordinate fields")
                return

        # Get features
        if self.selected_only_check.isChecked():
            if self.layer.selectedFeatureCount() == 0:
                QMessageBox.warning(self, "Error", "No features are selected")
                return
            features = self.layer.selectedFeatures()
        else:
            features = list(self.layer.getFeatures())

        # Track errors for debugging
        total_features = 0
        geometry_errors = 0
        transform_errors = 0
        calculation_errors = 0

        # Limit preview to first 50 features
        preview_count = 0
        for feature in features:
            total_features += 1

            if preview_count >= 50:
                break

            # Get coordinates
            x, y = self.get_coordinates(feature)
            if x is None or y is None:
                geometry_errors += 1
                continue

            # Transform to WGS84
            lat, lon = self.transform_to_wgs84(x, y)
            if lat is None or lon is None:
                transform_errors += 1
                continue

            # Get elevation and date
            elevation = self.get_elevation(feature)
            date = self.get_date(feature)

            # Calculate declination
            try:
                declination = self.calculate_declination_value(lat, lon, elevation, date)

                self.preview_data.append({
                    'fid': feature.id(),
                    'lon': lon,
                    'lat': lat,
                    'elevation': elevation,
                    'date': date.strftime('%Y-%m-%d'),
                    'declination': declination
                })

                preview_count += 1
            except Exception as e:
                calculation_errors += 1
                # Store first error for debugging
                if calculation_errors == 1:
                    self.last_calculation_error = f"{type(e).__name__}: {str(e)}"
                    self.last_error_coords = f"Lat: {lat:.6f}, Lon: {lon:.6f}"
                continue

        # Populate table
        self.preview_table.setRowCount(len(self.preview_data))

        for row, data in enumerate(self.preview_data):
            self.preview_table.setItem(row, 0, QTableWidgetItem(str(data['fid'])))
            self.preview_table.setItem(row, 1, QTableWidgetItem(f"{data['lon']:.6f}"))
            self.preview_table.setItem(row, 2, QTableWidgetItem(f"{data['lat']:.6f}"))
            self.preview_table.setItem(row, 3, QTableWidgetItem(f"{data['elevation']:.1f}"))
            self.preview_table.setItem(row, 4, QTableWidgetItem(data['date']))
            self.preview_table.setItem(row, 5, QTableWidgetItem(f"{data['declination']:.2f}"))

        if len(self.preview_data) == 0:
            # Build detailed error message
            error_msg = f"No valid coordinates found to preview.\n\n"
            error_msg += f"Processed {total_features} features:\n"
            if geometry_errors > 0:
                error_msg += f"  • {geometry_errors} features with invalid/empty geometry\n"
            if transform_errors > 0:
                error_msg += f"  • {transform_errors} features failed coordinate transformation\n"
            if calculation_errors > 0:
                error_msg += f"  • {calculation_errors} features failed declination calculation\n"
                if hasattr(self, 'last_calculation_error'):
                    error_msg += f"\n❌ Error details:\n"
                    error_msg += f"   {self.last_calculation_error}\n"
                    error_msg += f"   {self.last_error_coords}\n"
            error_msg += f"\nSuggestions:\n"
            if calculation_errors > 0:
                error_msg += f"  • Install geomag library: pip install geomag\n"
                error_msg += f"  • Restart QGIS after installing geomag\n"
                error_msg += f"  • Check if coordinates are within valid range\n"
            if geometry_errors > 0:
                error_msg += f"  • Check that layer has valid point geometry\n"
            if transform_errors > 0:
                error_msg += f"  • Verify layer CRS is properly defined\n"

            QMessageBox.warning(self, "No Data", error_msg)

    def calculate_declination(self):
        """Calculate and apply declination to all filtered features"""
        if not GEOMAG_AVAILABLE:
            QMessageBox.warning(self, "Error",
                              "geomag library not installed!\n\n"
                              "Install with: pip install geomag")
            return

        if self.layer is None:
            QMessageBox.warning(self, "Error", "Please select a layer")
            return

        # Check declination field is selected
        declination_field = self.declination_field_combo.currentData()
        if not declination_field:
            QMessageBox.warning(self, "Error", "Please select a declination field")
            return

        # Check if using fields mode and fields are selected
        if self.use_fields_radio.isChecked():
            if not self.x_field_combo.currentData() or not self.y_field_combo.currentData():
                QMessageBox.warning(self, "Error", "Please select X and Y coordinate fields")
                return

        # Get features
        if self.selected_only_check.isChecked():
            if self.layer.selectedFeatureCount() == 0:
                QMessageBox.warning(self, "Error", "No features are selected")
                return
            features = self.layer.selectedFeatures()
        else:
            features = list(self.layer.getFeatures())

        # Confirm with user
        msg = f"This will calculate magnetic declination for {len(features)} features.\n\nContinue?"
        reply = QMessageBox.question(self, "Confirm Calculation", msg,
                                    QMessageBox.Yes | QMessageBox.No)

        if reply != QMessageBox.Yes:
            return

        # Create progress dialog
        progress = QProgressDialog("Calculating declination...", "Cancel", 0, len(features), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        # Get field index
        declination_field_idx = self.layer.fields().indexOf(declination_field)

        # Calculate and apply
        update_count = 0
        error_count = 0

        with edit(self.layer):
            for i, feature in enumerate(features):
                progress.setValue(i)

                if progress.wasCanceled():
                    break

                # Get coordinates
                x, y = self.get_coordinates(feature)
                if x is None or y is None:
                    error_count += 1
                    continue

                # Transform to WGS84
                lat, lon = self.transform_to_wgs84(x, y)
                if lat is None or lon is None:
                    error_count += 1
                    continue

                # Get elevation and date
                elevation = self.get_elevation(feature)
                date = self.get_date(feature)

                # Calculate declination
                try:
                    declination = self.calculate_declination_value(lat, lon, elevation, date)

                    # Update feature
                    self.layer.changeAttributeValue(feature.id(), declination_field_idx, declination)
                    update_count += 1
                except Exception as e:
                    error_count += 1
                    continue

        progress.setValue(len(features))

        # Refresh the layer
        self.layer.triggerRepaint()
        iface.mapCanvas().refresh()

        # Show results
        msg = f"Successfully calculated declination for {update_count} features"
        if error_count > 0:
            msg += f"\n\n{error_count} features had errors (invalid coordinates or geometry)"

        QMessageBox.information(self, "Success", msg)

        self.accept()


def run_declination_calculator():
    """Main function to run the declination calculator"""
    dialog = CalculateDeclinationDialog(iface.mainWindow())
    dialog.exec()


# Allow running from QGIS Python console
if __name__ == '__console__':
    run_declination_calculator()
