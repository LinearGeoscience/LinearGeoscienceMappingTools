import os
import sys
import sqlite3
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton,
                                 QFileDialog, QLineEdit, QApplication,
                                 QProgressBar, QMessageBox, QGroupBox, QHBoxLayout,
                                 QCheckBox)
from qgis.core import (QgsProject, QgsCoordinateReferenceSystem, QgsVectorLayer,
                       QgsDataSourceUri, QgsCoordinateTransformContext,
                       QgsVectorFileWriter, QgsWkbTypes, QgsMessageLog, Qgis)
from qgis.gui import QgsProjectionSelectionWidget


class TemplateLoaderDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Mapping Template")
        self.resize(600, 450)

        # Set up the layout
        layout = QVBoxLayout()

        # Header info
        info_label = QLabel(
            "<b>Create a new mapping template geopackage</b><br>"
            "This will create a reprojected template in your specified location."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Template source selection (optional custom override)
        source_group = QGroupBox("Template Source")
        source_layout = QVBoxLayout()

        self.use_custom_checkbox = QCheckBox("Use custom template (override default)")
        self.use_custom_checkbox.toggled.connect(self.toggle_custom_template)
        source_layout.addWidget(self.use_custom_checkbox)

        default_template_path = os.path.join(
            os.path.dirname(__file__), "Template", "LGS_MappingTemplate.gpkg"
        )

        custom_hbox = QHBoxLayout()
        self.custom_template_path_label = QLineEdit(default_template_path)
        self.custom_template_path_label.setReadOnly(True)
        self.custom_template_path_label.setEnabled(False)
        self.custom_template_button = QPushButton("Browse...")
        self.custom_template_button.setEnabled(False)
        self.custom_template_button.clicked.connect(self.select_custom_template)
        custom_hbox.addWidget(self.custom_template_path_label)
        custom_hbox.addWidget(self.custom_template_button)
        source_layout.addLayout(custom_hbox)

        source_group.setLayout(source_layout)
        layout.addWidget(source_group)

        # Output location selection
        location_group = QGroupBox("Output Location")
        location_layout = QVBoxLayout()

        location_hbox = QHBoxLayout()
        self.location_path_label = QLabel("No location selected")
        self.location_button = QPushButton("Browse...")
        self.location_button.clicked.connect(self.select_output_location)
        location_hbox.addWidget(self.location_path_label)
        location_hbox.addWidget(self.location_button)
        location_layout.addLayout(location_hbox)

        location_group.setLayout(location_layout)
        layout.addWidget(location_group)

        # Template name input
        name_group = QGroupBox("Template Name")
        name_layout = QVBoxLayout()

        name_hbox = QHBoxLayout()
        name_label = QLabel("Name:")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g., MyProject, SiteA, Field2025")
        self.name_input.textChanged.connect(self.update_filename_preview)
        name_hbox.addWidget(name_label)
        name_hbox.addWidget(self.name_input)
        name_layout.addLayout(name_hbox)

        # Filename preview
        self.filename_preview = QLabel("Output: LGS_[name]_[epsg].gpkg")
        self.filename_preview.setStyleSheet("color: #666; font-style: italic; padding: 5px;")
        name_layout.addWidget(self.filename_preview)

        name_group.setLayout(name_layout)
        layout.addWidget(name_group)

        # CRS selection
        crs_group = QGroupBox("Target CRS")
        crs_layout = QVBoxLayout()

        crs_info = QLabel("Select the coordinate reference system for the template:")
        crs_layout.addWidget(crs_info)

        self.crs_selector = QgsProjectionSelectionWidget()
        # Set default to project CRS or WGS84
        project_crs = QgsProject.instance().crs()
        if project_crs.isValid():
            self.crs_selector.setCrs(project_crs)
        else:
            self.crs_selector.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

        self.crs_selector.crsChanged.connect(self.update_filename_preview)
        crs_layout.addWidget(self.crs_selector)

        crs_group.setLayout(crs_layout)
        layout.addWidget(crs_group)

        # Change tracking (optional) — register the template for reconcile
        tracking_group = QGroupBox("Change Tracking (optional)")
        tracking_layout = QVBoxLayout()
        tracking_info = QLabel(
            "Register this template for three-way reconcile. If you select the "
            "master GeoPackage now, a base snapshot is recorded so the mapper's "
            "edits can be merged back later without loss.")
        tracking_info.setWordWrap(True)
        tracking_layout.addWidget(tracking_info)

        mapper_hbox = QHBoxLayout()
        mapper_hbox.addWidget(QLabel("Mapper ID:"))
        self.mapper_input = QLineEdit()
        self.mapper_input.setPlaceholderText("e.g., HW (who will collect this data)")
        mapper_hbox.addWidget(self.mapper_input)
        tracking_layout.addLayout(mapper_hbox)

        master_hbox = QHBoxLayout()
        master_hbox.addWidget(QLabel("Master GeoPackage:"))
        self.tracking_master_label = QLineEdit()
        self.tracking_master_label.setReadOnly(True)
        self.tracking_master_label.setPlaceholderText("(optional)")
        self.tracking_master_button = QPushButton("Browse...")
        self.tracking_master_button.clicked.connect(self.select_tracking_master)
        master_hbox.addWidget(self.tracking_master_label)
        master_hbox.addWidget(self.tracking_master_button)
        tracking_layout.addLayout(master_hbox)

        tracking_group.setLayout(tracking_layout)
        layout.addWidget(tracking_group)

        # Progress bar
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout()

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        progress_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready")
        progress_layout.addWidget(self.status_label)

        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)

        # Create button
        self.create_button = QPushButton("Create Template")
        self.create_button.clicked.connect(self.process_template)
        self.create_button.setEnabled(False)
        self.create_button.setStyleSheet("""
            QPushButton {
                background-color: #34A853;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2E9648;
            }
            QPushButton:disabled {
                background-color: #CCCCCC;
            }
        """)
        layout.addWidget(self.create_button)

        self.setLayout(layout)

        # Initialize variables
        self.output_location = None
        self.custom_template_path = None
        self.tracking_master_path = None

        # Try to set default location to project path
        self.set_default_location()

    def toggle_custom_template(self, checked):
        """Enable/disable the custom template browse row"""
        self.custom_template_path_label.setEnabled(checked)
        self.custom_template_button.setEnabled(checked)
        if not checked:
            self.custom_template_path = None
            default_template_path = os.path.join(
                os.path.dirname(__file__), "Template", "LGS_MappingTemplate.gpkg"
            )
            self.custom_template_path_label.setText(default_template_path)
        self.check_enable_create()

    def select_custom_template(self):
        """Browse for a custom template geopackage"""
        start_dir = ""
        if self.custom_template_path and os.path.exists(self.custom_template_path):
            start_dir = os.path.dirname(self.custom_template_path)
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Custom Template", start_dir, "GeoPackage (*.gpkg)"
        )
        if file_path:
            self.custom_template_path = file_path
            self.custom_template_path_label.setText(file_path)
            self.check_enable_create()

    def select_tracking_master(self):
        """Browse for the master GeoPackage to register this template against."""
        start_dir = ""
        if self.tracking_master_path and os.path.exists(self.tracking_master_path):
            start_dir = os.path.dirname(self.tracking_master_path)
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Master GeoPackage", start_dir, "GeoPackage (*.gpkg)"
        )
        if file_path:
            self.tracking_master_path = file_path
            self.tracking_master_label.setText(file_path)

    def set_default_location(self):
        """Set default output location to project path"""
        project_path = QgsProject.instance().homePath()
        if project_path and os.path.exists(project_path):
            self.output_location = project_path
            self.location_path_label.setText(project_path)
            self.check_enable_create()

    def select_output_location(self):
        """Select output directory"""
        folder_path = QFileDialog.getExistingDirectory(
            self, "Select Output Location", self.output_location or ""
        )
        if folder_path:
            self.output_location = folder_path
            self.location_path_label.setText(folder_path)
            self.check_enable_create()
            self.update_filename_preview()

    def update_filename_preview(self):
        """Update the filename preview label"""
        name = self.name_input.text().strip()
        crs = self.crs_selector.crs()

        if name and crs.isValid():
            # Extract EPSG code
            auth_id = crs.authid()
            if ':' in auth_id:
                epsg = auth_id.split(':')[1]
            else:
                epsg = "XXXX"

            preview_filename = f"LGS_{name}_{epsg}.gpkg"
            self.filename_preview.setText(f"Output: {preview_filename}")
        else:
            self.filename_preview.setText("Output: LGS_[name]_[epsg].gpkg")

        self.check_enable_create()

    def check_enable_create(self):
        """Check if all required fields are filled"""
        name = self.name_input.text().strip()
        crs = self.crs_selector.crs()

        custom_ok = True
        if self.use_custom_checkbox.isChecked():
            custom_ok = bool(self.custom_template_path) and os.path.exists(self.custom_template_path)

        if self.output_location and name and crs.isValid() and custom_ok:
            self.create_button.setEnabled(True)
        else:
            self.create_button.setEnabled(False)

    def get_template_path(self):
        """Get the path to the template geopackage"""
        if self.use_custom_checkbox.isChecked() and self.custom_template_path:
            return self.custom_template_path
        plugin_dir = os.path.dirname(__file__)
        return os.path.join(plugin_dir, "Template", "LGS_MappingTemplate.gpkg")

    def process_template(self):
        """Main processing logic"""
        # Validate template exists
        template_path = self.get_template_path()
        if not os.path.exists(template_path):
            QMessageBox.critical(
                self, "Error",
                f"Template geopackage not found at:\n{template_path}\n\n"
                "Please ensure the template file exists in the Template folder."
            )
            return

        # Get parameters
        name = self.name_input.text().strip()
        target_crs = self.crs_selector.crs()

        # Extract EPSG code
        auth_id = target_crs.authid()
        if ':' in auth_id:
            epsg = auth_id.split(':')[1]
        else:
            epsg = "unknown"

        # Create geopackage filename and path
        gpkg_filename = f"LGS_{name}_{epsg}.gpkg"
        group_name = f"LGS_{name}_{epsg}"  # Name for the QGIS layer group
        output_gpkg = os.path.join(self.output_location, gpkg_filename)

        # Check if file already exists
        if os.path.exists(output_gpkg):
            response = QMessageBox.question(
                self, "File Exists",
                f"File already exists:\n{output_gpkg}\n\nDo you want to overwrite it?",
                QMessageBox.Yes | QMessageBox.No
            )

            if response == QMessageBox.No:
                return

        # Remove existing output file if it exists
        if os.path.exists(output_gpkg):
            try:
                os.remove(output_gpkg)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not remove existing file:\n{str(e)}")
                return

        try:
            from .script_reprojectgeopackage import GeoPackageReprojectDialog

            # Create a temporary instance to access its methods
            temp_reprojector = GeoPackageReprojectDialog()
            temp_reprojector.input_gpkg = template_path
            temp_reprojector.output_gpkg = output_gpkg
            temp_reprojector.progress_bar = self.progress_bar
            temp_reprojector.status_label = self.status_label

            # Process the geopackage
            self.status_label.setText("Creating initial GeoPackage copy...")
            self.progress_bar.setValue(5)
            QApplication.processEvents()

            temp_reprojector.create_gpkg_copy(template_path, output_gpkg)

            # Get list of layers
            self.status_label.setText("Analyzing template structure...")
            self.progress_bar.setValue(15)
            QApplication.processEvents()

            vector_layers, nonspatial_tables, raster_layers = temp_reprojector.list_gpkg_contents(template_path)

            # Set up progress tracking
            total_operations = len(vector_layers) + len(nonspatial_tables) + len(raster_layers)
            progress_per_operation = 70 / max(total_operations, 1)
            current_progress = 15

            # Process each vector layer
            for i, layer_name in enumerate(vector_layers):
                progress_msg = f"Processing layer {i + 1}/{len(vector_layers)}: {layer_name}"
                self.status_label.setText(progress_msg)
                current_progress += progress_per_operation
                self.progress_bar.setValue(int(current_progress))
                QApplication.processEvents()

                temp_reprojector.process_vector_layer(layer_name, target_crs)

            # Process non-spatial tables
            for i, table_name in enumerate(nonspatial_tables):
                progress_msg = f"Copying table {i + 1}/{len(nonspatial_tables)}: {table_name}"
                self.status_label.setText(progress_msg)
                current_progress += progress_per_operation
                self.progress_bar.setValue(int(current_progress))
                QApplication.processEvents()

                temp_reprojector.copy_nonspatial_table(table_name)

            # Process raster layers if any
            for i, layer_name in enumerate(raster_layers):
                progress_msg = f"Processing raster {i + 1}/{len(raster_layers)}: {layer_name}"
                self.status_label.setText(progress_msg)
                current_progress += progress_per_operation
                self.progress_bar.setValue(int(current_progress))
                QApplication.processEvents()

                temp_reprojector.process_raster_layer(layer_name, target_crs)

            # Update CRS references
            self.status_label.setText("Updating CRS references...")
            self.progress_bar.setValue(90)
            QApplication.processEvents()
            temp_reprojector.update_gpkg_crs_references(output_gpkg, target_crs)

            # Verify integrity
            self.status_label.setText("Verifying integrity...")
            self.progress_bar.setValue(95)
            QApplication.processEvents()
            temp_reprojector.verify_gpkg_integrity()

            # Optimize
            self.status_label.setText("Optimizing GeoPackage...")
            self.progress_bar.setValue(97)
            QApplication.processEvents()
            temp_reprojector.optimize_gpkg(output_gpkg)

            # Load layers into QGIS project
            self.status_label.setText("Loading layers into project...")
            self.progress_bar.setValue(98)
            QApplication.processEvents()
            self.load_template_to_project(output_gpkg, group_name, vector_layers, nonspatial_tables)

            # Register the template for reconcile change-tracking (optional,
            # non-fatal — a failure here must not break template creation).
            tracking_note = ""
            mapper = self.mapper_input.text().strip()
            if self.tracking_master_path and os.path.exists(self.tracking_master_path):
                self.status_label.setText("Registering for change tracking...")
                QApplication.processEvents()
                try:
                    from .script_adddata.reconcile import engine as _recon_engine
                    res = _recon_engine.register_and_snapshot(
                        self.tracking_master_path, output_gpkg, mapper)
                    if res.get("errors"):
                        tracking_note = ("\n\nChange tracking: registered with "
                                         "warnings: " + "; ".join(res["errors"]))
                    else:
                        tracking_note = ("\n\nChange tracking: template registered "
                                         f"for reconcile (mapper: {mapper or 'n/a'}).")
                except Exception as track_exc:
                    QgsMessageLog.logMessage(
                        f"Reconcile registration failed: {track_exc}",
                        'Linear Geoscience', Qgis.Warning)
                    tracking_note = f"\n\nChange tracking could not be set up: {track_exc}"

            self.status_label.setText("Template created successfully!")
            self.progress_bar.setValue(100)

            QMessageBox.information(
                self, "Success",
                f"Template created successfully!\n\n"
                f"Location: {self.output_location}\n"
                f"Geopackage: {gpkg_filename}\n\n"
                f"All layers have been loaded into your QGIS project."
                f"{tracking_note}"
            )

        except Exception as e:
            self.status_label.setText(f"Error: {str(e)}")
            QMessageBox.critical(self, "Error", f"An error occurred:\n{str(e)}")
        finally:
            if self.progress_bar.value() < 100:
                self.progress_bar.setValue(100)

    def load_template_to_project(self, gpkg_path, group_name, layer_names, nonspatial_tables):
        """Load the template layers into the QGIS project organized in a group"""
        try:
            # Get the root of the layer tree
            root = QgsProject.instance().layerTreeRoot()

            # Create a group for this template
            template_group = root.addGroup(group_name)

            # Load each spatial layer into the main group
            for layer_name in layer_names:
                layer_uri = f"{gpkg_path}|layername={layer_name}"
                layer = QgsVectorLayer(layer_uri, layer_name, "ogr")

                if layer.isValid():
                    QgsProject.instance().addMapLayer(layer, False)
                    template_group.addLayer(layer)

            # Create a "Codes" subgroup for non-spatial tables
            codes_group = template_group.addGroup("Codes")

            # Load each non-spatial table into the Codes subgroup
            for table_name in nonspatial_tables:
                # Skip layer_styles table as it's internal QGIS styling
                if table_name == "layer_styles":
                    continue

                layer_uri = f"{gpkg_path}|layername={table_name}"
                layer = QgsVectorLayer(layer_uri, table_name, "ogr")

                if layer.isValid():
                    QgsProject.instance().addMapLayer(layer, False)
                    codes_group.addLayer(layer)

        except Exception as e:
            # Non-critical error
            QgsMessageLog.logMessage(f"Warning: Could not load layers into project: {str(e)}", 'Linear Geoscience', Qgis.Warning)


def run_template_loader():
    """Main function to run the Template Loader Tool"""
    from qgis.utils import iface
    from qgis.PyQt.QtCore import Qt

    try:
        # Re-raise existing dialog if still alive
        if hasattr(iface, "_template_dialog") and iface._template_dialog is not None:
            try:
                iface._template_dialog.show()
                iface._template_dialog.raise_()
                iface._template_dialog.activateWindow()
                return iface._template_dialog
            except RuntimeError:
                iface._template_dialog = None

        parent = iface.mainWindow()
        dialog = TemplateLoaderDialog(parent)

        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)

        # Store persistent reference to prevent GC; clean up on close
        dialog.destroyed.connect(lambda: setattr(iface, "_template_dialog", None))
        iface._template_dialog = dialog

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog
    except Exception as e:
        import traceback
        QgsMessageLog.logMessage(
            f"run_template_loader failed: {e}\n{traceback.format_exc()}",
            'Linear Geoscience', Qgis.Critical
        )
        iface.messageBar().pushCritical(
            "Linear Geoscience",
            f"Failed to open Template Loader: {e}"
        )
        raise


def run(iface):
    """Entry point called from mainplugin.py."""
    return run_template_loader()
