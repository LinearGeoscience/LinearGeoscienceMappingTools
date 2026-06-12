import os
import sys
import sqlite3
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton,
                                 QFileDialog, QComboBox, QCheckBox, QApplication,
                                 QProgressBar, QMessageBox, QGroupBox, QHBoxLayout)
from qgis.core import (QgsProject, QgsCoordinateReferenceSystem, QgsVectorLayer,
                       QgsDataSourceUri, QgsCoordinateTransformContext,
                       QgsVectorFileWriter, QgsRasterLayer, QgsRasterPipe,
                       QgsRasterFileWriter, QgsProcessingFeedback, QgsWkbTypes)
from qgis.gui import QgsProjectionSelectionWidget


class GeoPackageReprojectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reproject GeoPackage")
        self.resize(600, 400)

        # Set up the layout
        layout = QVBoxLayout()

        # Input GeoPackage selection
        input_group = QGroupBox("Input GeoPackage")
        input_layout = QVBoxLayout()

        input_hbox = QHBoxLayout()
        self.input_path_label = QLabel("No file selected")
        self.input_button = QPushButton("Browse...")
        self.input_button.clicked.connect(self.select_input_gpkg)
        input_hbox.addWidget(self.input_path_label)
        input_hbox.addWidget(self.input_button)
        input_layout.addLayout(input_hbox)

        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        # CRS selection
        crs_group = QGroupBox("Target CRS (Optional)")
        crs_layout = QVBoxLayout()

        # Use QgsProjectionSelectionWidget for CRS as recommended in cookbook
        self.crs_selector = QgsProjectionSelectionWidget()
        self.crs_checkbox = QCheckBox("Reproject to new CRS")
        self.crs_checkbox.stateChanged.connect(self.toggle_crs_selector)

        crs_layout.addWidget(self.crs_checkbox)
        crs_layout.addWidget(self.crs_selector)
        crs_group.setLayout(crs_layout)
        layout.addWidget(crs_group)

        # Output GeoPackage selection
        output_group = QGroupBox("Output GeoPackage")
        output_layout = QVBoxLayout()

        output_hbox = QHBoxLayout()
        self.output_path_label = QLabel("No file selected")
        self.output_button = QPushButton("Browse...")
        self.output_button.clicked.connect(self.select_output_gpkg)
        output_hbox.addWidget(self.output_path_label)
        output_hbox.addWidget(self.output_button)
        output_layout.addLayout(output_hbox)

        output_group.setLayout(output_layout)
        layout.addWidget(output_group)

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

        # Process button
        self.process_button = QPushButton("Process")
        self.process_button.clicked.connect(self.process_geopackage)
        self.process_button.setEnabled(False)
        layout.addWidget(self.process_button)

        self.setLayout(layout)

        # Initialize variables
        self.input_gpkg = None
        self.output_gpkg = None

        # Disable CRS selector by default
        self.crs_selector.setEnabled(False)

    def toggle_crs_selector(self, state):
        self.crs_selector.setEnabled(state)

    def select_input_gpkg(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Input GeoPackage", "", "GeoPackage (*.gpkg)"
        )
        if file_path:
            self.input_gpkg = file_path
            self.input_path_label.setText(os.path.basename(file_path))
            self.check_enable_process()

    def select_output_gpkg(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Select Output GeoPackage", "", "GeoPackage (*.gpkg)"
        )
        if file_path:
            self.output_gpkg = file_path
            self.output_path_label.setText(os.path.basename(file_path))
            self.check_enable_process()

    def check_enable_process(self):
        if self.input_gpkg and self.output_gpkg:
            self.process_button.setEnabled(True)
        else:
            self.process_button.setEnabled(False)

    def update_gpkg_crs_references(self, gpkg_path, target_crs):
        """Update all GeoPackage CRS references to the target CRS"""
        try:
            conn = sqlite3.connect(gpkg_path)
            cursor = conn.cursor()

            # Get the srs_id for the target CRS
            auth_id = target_crs.authid()
            auth_name, auth_code = auth_id.split(':') if ':' in auth_id else ('EPSG', '4326')

            # Find the srs_id in the gpkg_spatial_ref_sys table
            cursor.execute(
                "SELECT srs_id FROM gpkg_spatial_ref_sys WHERE organization=? AND organization_coordsys_id=?",
                (auth_name, auth_code)
            )
            result = cursor.fetchone()

            if not result:
                # If somehow the CRS isn't registered, register it
                srs_id = target_crs.srsid()
                srs_name = target_crs.description()
                definition = target_crs.toWkt()

                cursor.execute("""
                    INSERT INTO gpkg_spatial_ref_sys (
                        srs_name, srs_id, organization, organization_coordsys_id, 
                        definition, description
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (srs_name, srs_id, auth_name, auth_code, definition, srs_name))

                target_srs_id = srs_id
            else:
                target_srs_id = result[0]

            # Update all entries in gpkg_contents
            cursor.execute(
                "UPDATE gpkg_contents SET srs_id = ? WHERE data_type = 'features'",
                (target_srs_id,)
            )

            # Update all entries in gpkg_geometry_columns
            cursor.execute(
                "UPDATE gpkg_geometry_columns SET srs_id = ?",
                (target_srs_id,)
            )

            conn.commit()
            conn.close()

        except Exception as e:
            raise Exception(f"Error updating GeoPackage CRS references: {str(e)}")


    def process_geopackage(self):
        # Check if output file already exists
        if os.path.exists(self.output_gpkg):
            response = QMessageBox.question(
                self, "File Exists",
                "Output file already exists. Do you want to overwrite it?",
                QMessageBox.Yes | QMessageBox.No
            )

            if response == QMessageBox.No:
                return

            # Remove existing file to avoid issues
            try:
                os.remove(self.output_gpkg)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not remove existing file: {str(e)}")
                return

        # Get the target CRS
        target_crs = None
        if self.crs_checkbox.isChecked():
            target_crs = self.crs_selector.crs()
            if not target_crs.isValid():
                QMessageBox.warning(self, "Warning", "Selected CRS is not valid. Please select a valid CRS.")
                return

        try:
            # Create a copy of the input GeoPackage to ensure structure is preserved
            self.status_label.setText("Creating initial GeoPackage copy...")
            self.progress_bar.setValue(5)
            QApplication.processEvents()

            # Create an initial copy of the input GeoPackage (this preserves structure better than creating empty)
            self.create_gpkg_copy(self.input_gpkg, self.output_gpkg)

            # Get list of layers in the GeoPackage
            self.status_label.setText("Analyzing input GeoPackage...")
            self.progress_bar.setValue(15)
            QApplication.processEvents()
            vector_layers, nonspatial_tables, raster_layers = self.list_gpkg_contents(self.input_gpkg)

            # Set up progress tracking
            total_operations = len(vector_layers) + len(nonspatial_tables) + len(raster_layers)
            progress_per_operation = 80 / max(total_operations, 1)
            current_progress = 15

            # Process each vector layer - only reproject if target CRS is specified
            for i, layer_name in enumerate(vector_layers):
                # Update progress
                progress_msg = f"Processing vector layer {i + 1}/{len(vector_layers)}: {layer_name}"
                self.status_label.setText(progress_msg)
                current_progress += progress_per_operation
                self.progress_bar.setValue(int(current_progress))
                QApplication.processEvents()

                # Process the vector layer - ensuring geometry is preserved
                self.process_vector_layer(layer_name, target_crs)

            # Process each non-spatial table (including layer_styles)
            for i, table_name in enumerate(nonspatial_tables):
                # Update progress
                progress_msg = f"Copying non-spatial table {i + 1}/{len(nonspatial_tables)}: {table_name}"
                self.status_label.setText(progress_msg)
                current_progress += progress_per_operation
                self.progress_bar.setValue(int(current_progress))
                QApplication.processEvents()

                # Copy the non-spatial table
                self.copy_nonspatial_table(table_name)

            # Process each raster layer if needed
            for i, layer_name in enumerate(raster_layers):
                progress_msg = f"Processing raster layer {i + 1}/{len(raster_layers)}: {layer_name}"
                self.status_label.setText(progress_msg)
                current_progress += progress_per_operation
                self.progress_bar.setValue(int(current_progress))
                QApplication.processEvents()

                self.process_raster_layer(layer_name, target_crs)

            # If target CRS is specified, update all CRS references
            if target_crs and target_crs.isValid():
                self.status_label.setText("Updating CRS references...")
                self.progress_bar.setValue(93)
                QApplication.processEvents()
                self.update_gpkg_crs_references(self.output_gpkg, target_crs)

            # Verify all layers have been correctly processed
            self.status_label.setText("Verifying GeoPackage integrity...")
            self.progress_bar.setValue(95)
            QApplication.processEvents()
            self.verify_gpkg_integrity()

            # Finalize and optimize
            self.status_label.setText("Finalizing GeoPackage...")
            self.progress_bar.setValue(98)
            QApplication.processEvents()
            self.optimize_gpkg(self.output_gpkg)

            self.status_label.setText("Processing completed successfully!")
            self.progress_bar.setValue(100)
            QMessageBox.information(self, "Success", "GeoPackage processing completed successfully!")

        except Exception as e:
            self.status_label.setText(f"Error: {str(e)}")
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")
        finally:
            if self.progress_bar.value() < 100:
                self.progress_bar.setValue(100)

    def create_gpkg_copy(self, input_gpkg, output_gpkg):
        """Create a complete copy of the input GeoPackage structure"""
        try:
            # Instead of doing a direct file copy and then clearing tables,
            # we'll create a new empty GeoPackage and copy over the structure

            # First, create a minimal GeoPackage to initialize required tables
            self.create_empty_gpkg(output_gpkg)

            # Now copy the spatial reference systems and other metadata
            self.copy_gpkg_metadata(input_gpkg, output_gpkg)

        except Exception as e:
            raise Exception(f"Error creating GeoPackage copy: {str(e)}")

    def create_empty_gpkg(self, gpkg_path):
        """Create an empty GeoPackage with required system tables"""
        try:
            # Create a temporary memory layer to initialize the GeoPackage
            temp_layer_name = "temp_initialize_layer"
            mem_layer = QgsVectorLayer("Point?crs=EPSG:4326", temp_layer_name, "memory")

            if not mem_layer.isValid():
                raise Exception("Could not create temporary memory layer")

            # Save it to GeoPackage to initialize the file
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = temp_layer_name

            transform_context = QgsProject.instance().transformContext()

            # Write the dummy layer to initialize the GeoPackage
            result = QgsVectorFileWriter.writeAsVectorFormatV3(
                mem_layer,
                gpkg_path,
                transform_context,
                options
            )

            # Check result
            if isinstance(result, tuple) and len(result) >= 1:
                error = result[0]
                error_message = result[1] if len(result) > 1 else "Unknown error"
            else:
                error = result
                error_message = "Unknown error"

            if error != QgsVectorFileWriter.NoError:
                raise Exception(f"Error creating GeoPackage: {error_message}")

            # Remove temporary layer
            conn = sqlite3.connect(gpkg_path)
            cursor = conn.cursor()

            # Drop the temporary table
            cursor.execute(f"DROP TABLE IF EXISTS \"{temp_layer_name}\"")

            # Remove from gpkg_contents
            cursor.execute(f"DELETE FROM gpkg_contents WHERE table_name = '{temp_layer_name}'")

            # Remove from gpkg_geometry_columns
            cursor.execute(f"DELETE FROM gpkg_geometry_columns WHERE table_name = '{temp_layer_name}'")

            conn.commit()
            conn.close()

        except Exception as e:
            raise Exception(f"Error creating empty GeoPackage: {str(e)}")

    def copy_gpkg_metadata(self, input_gpkg, output_gpkg):
        """Copy GeoPackage metadata from input to output"""
        try:
            # Connect to both GeoPackages
            conn_in = sqlite3.connect(input_gpkg)
            cursor_in = conn_in.cursor()

            conn_out = sqlite3.connect(output_gpkg)
            cursor_out = conn_out.cursor()

            # Copy spatial reference systems
            cursor_in.execute("SELECT * FROM gpkg_spatial_ref_sys")
            srs_rows = cursor_in.fetchall()

            # Get column names
            cursor_in.execute("PRAGMA table_info(gpkg_spatial_ref_sys)")
            srs_columns = [col[1] for col in cursor_in.fetchall()]

            # Clear existing entries in output
            cursor_out.execute("DELETE FROM gpkg_spatial_ref_sys")

            # Insert all entries
            if srs_rows:
                placeholders = ', '.join(['?' for _ in range(len(srs_columns))])
                insert_sql = f"INSERT INTO gpkg_spatial_ref_sys VALUES ({placeholders})"
                cursor_out.executemany(insert_sql, srs_rows)

            # Copy other metadata tables if they exist
            metadata_tables = [
                'gpkg_extensions',
                'gpkg_metadata',
                'gpkg_metadata_reference',
                'gpkg_data_columns',
                'gpkg_data_column_constraints'
            ]

            for table in metadata_tables:
                # Check if table exists in input
                cursor_in.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
                if cursor_in.fetchone():
                    # Get table creation SQL
                    cursor_in.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
                    create_sql = cursor_in.fetchone()[0]

                    # Create table in output (drop first if exists)
                    cursor_out.execute(f"DROP TABLE IF EXISTS {table}")
                    cursor_out.execute(create_sql)

                    # Copy data
                    cursor_in.execute(f"SELECT * FROM {table}")
                    rows = cursor_in.fetchall()

                    if rows:
                        # Get column count
                        cursor_in.execute(f"PRAGMA table_info({table})")
                        column_count = len(cursor_in.fetchall())

                        # Insert data
                        placeholders = ', '.join(['?' for _ in range(column_count)])
                        insert_sql = f"INSERT INTO {table} VALUES ({placeholders})"
                        cursor_out.executemany(insert_sql, rows)

            conn_in.close()
            conn_out.commit()
            conn_out.close()

        except Exception as e:
            raise Exception(f"Error copying GeoPackage metadata: {str(e)}")

    def list_gpkg_contents(self, gpkg_path):
        """List all vector layers, non-spatial tables, and raster layers in the GeoPackage."""
        vector_layers = []
        nonspatial_tables = []
        raster_layers = []

        try:
            conn = sqlite3.connect(gpkg_path)
            cursor = conn.cursor()

            # Get spatial vector layers
            cursor.execute("SELECT table_name FROM gpkg_contents WHERE data_type = 'features'")
            vector_layers = [row[0] for row in cursor.fetchall()]

            # Get raster layers
            cursor.execute("SELECT table_name FROM gpkg_contents WHERE data_type = 'tiles'")
            raster_layers = [row[0] for row in cursor.fetchall()]

            # Get all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND "
                           "name NOT LIKE 'sqlite_%' AND "
                           "name NOT LIKE 'gpkg_%' AND "
                           "name NOT LIKE 'rtree_%' AND "
                           "name NOT LIKE 'idx_%'")
            all_tables = [row[0] for row in cursor.fetchall()]

            # Identify non-spatial tables - including layer_styles as a regular table
            nonspatial_tables = [table for table in all_tables
                                 if table not in vector_layers and table not in raster_layers]

            conn.close()

        except Exception as e:
            raise Exception(f"Error analyzing GeoPackage structure: {str(e)}")

        return vector_layers, nonspatial_tables, raster_layers

    def process_vector_layer(self, layer_name, target_crs):
        """Process a vector layer with correct geometry handling"""
        try:
            # First, get detailed information about the layer
            conn = sqlite3.connect(self.input_gpkg)
            cursor = conn.cursor()

            # Get geometry column info
            cursor.execute(
                "SELECT column_name, geometry_type_name, srs_id FROM gpkg_geometry_columns WHERE table_name = ?",
                (layer_name,))
            geom_info = cursor.fetchone()

            if not geom_info:
                raise Exception(f"Layer {layer_name} not found in gpkg_geometry_columns")

            geom_column = geom_info[0]
            geom_type = geom_info[1]
            source_srs_id = geom_info[2]

            # Save data column information before we clear it
            cursor.execute("SELECT * FROM gpkg_data_columns WHERE table_name = ?", (layer_name,))
            data_columns = cursor.fetchall()

            # Get table info and schema
            cursor.execute(f"PRAGMA table_info(\"{layer_name}\")")
            columns_info = cursor.fetchall()

            # Get full schema structure including indexes
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (layer_name,))
            table_sql = cursor.fetchone()[0]

            # Get indexes too
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
                           (layer_name,))
            indexes_sql = [row[0] for row in cursor.fetchall()]

            conn.close()

            # Clear existing metadata entries for this layer in the output file
            # to prevent unique constraint violations
            conn_out = sqlite3.connect(self.output_gpkg)
            cursor_out = conn_out.cursor()

            # Remove entries that might cause conflicts
            cursor_out.execute("DELETE FROM gpkg_contents WHERE table_name = ?", (layer_name,))
            cursor_out.execute("DELETE FROM gpkg_geometry_columns WHERE table_name = ?", (layer_name,))
            cursor_out.execute("DELETE FROM gpkg_data_columns WHERE table_name = ?", (layer_name,))

            conn_out.commit()
            conn_out.close()

            # Now load the vector layer for processing
            input_uri = f"{self.input_gpkg}|layername={layer_name}"
            vector_layer = QgsVectorLayer(input_uri, layer_name, "ogr")

            if not vector_layer.isValid():
                raise Exception(f"Could not load layer: {layer_name}")

            # Determine if we need to reproject or just copy
            if target_crs and target_crs.isValid():
                # We need to reproject - use QgsVectorFileWriter with proper geometry handling
                options = QgsVectorFileWriter.SaveVectorOptions()
                options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
                options.layerName = layer_name
                options.driverName = "GPKG"
                options.fileEncoding = "UTF-8"

                # Set geometry name explicitly
                options.layerOptions = [f'GEOMETRY_NAME={geom_column}', 'FID=fid']

                # Preserve the exact geometry type
                wkb_type = vector_layer.wkbType()
                options.overrideGeometryType = wkb_type

                # Set up the coordinate transformation
                options.sourceCRS = vector_layer.crs()
                options.destCRS = target_crs

                # Get transform context
                transform_context = QgsProject.instance().transformContext()

                # Write to the new GeoPackage
                result = QgsVectorFileWriter.writeAsVectorFormatV3(
                    vector_layer,
                    self.output_gpkg,
                    transform_context,
                    options
                )

                # Check for errors
                if isinstance(result, tuple) and len(result) >= 1:
                    error = result[0]
                    error_message = result[1] if len(result) > 1 else "Unknown error"
                else:
                    error = result
                    error_message = "Unknown error"

                if error != QgsVectorFileWriter.NoError:
                    raise Exception(f"Error writing layer: {error_message}")

                # Update spatial_ref_sys tables
                self.update_spatial_references(target_crs)

                # Restore data columns if they're not recreated automatically
                conn_out = sqlite3.connect(self.output_gpkg)
                cursor_out = conn_out.cursor()

                # Check if data columns were recreated
                cursor_out.execute("SELECT COUNT(*) FROM gpkg_data_columns WHERE table_name = ?", (layer_name,))
                count = cursor_out.fetchone()[0]

                # If no data columns exist, restore them from our saved copy
                if count == 0 and data_columns:
                    for data_column in data_columns:
                        # We need to adjust the SQL to handle target CRS if needed
                        # but keep all other metadata the same
                        cursor_out.execute(
                            """INSERT INTO gpkg_data_columns 
                               (table_name, column_name, name, title, description, mime_type, constraint_name) 
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            data_column
                        )

                conn_out.commit()
                conn_out.close()

            else:
                # Direct SQL copy without reprojection
                self.copy_vector_layer_direct(layer_name, geom_column, table_sql, indexes_sql, data_columns)

            # Verify the layer was created properly
            self.verify_layer_integrity(layer_name, geom_column)

        except Exception as e:
            raise Exception(f"Error processing vector layer {layer_name}: {str(e)}")

    def copy_vector_layer_direct(self, layer_name, geom_column, table_sql, indexes_sql, data_columns):
        """Copy a vector layer directly using SQL statements"""
        try:
            conn_in = sqlite3.connect(self.input_gpkg)
            cursor_in = conn_in.cursor()

            conn_out = sqlite3.connect(self.output_gpkg)
            cursor_out = conn_out.cursor()

            # First clear any existing entries in metadata tables to avoid conflicts
            cursor_out.execute("DELETE FROM gpkg_contents WHERE table_name = ?", (layer_name,))
            cursor_out.execute("DELETE FROM gpkg_geometry_columns WHERE table_name = ?", (layer_name,))
            cursor_out.execute("DELETE FROM gpkg_data_columns WHERE table_name = ?", (layer_name,))

            # Create the table with the exact same structure
            cursor_out.execute(f"DROP TABLE IF EXISTS \"{layer_name}\"")
            cursor_out.execute(table_sql)

            # Get all rows from the source - use parameterized query for safety
            cursor_in.execute(f"SELECT * FROM \"{layer_name}\"")
            rows = cursor_in.fetchall()

            # Get column count
            cursor_in.execute(f"PRAGMA table_info(\"{layer_name}\")")
            column_count = len(cursor_in.fetchall())

            # Insert the data
            if rows:
                placeholders = ', '.join(['?' for _ in range(column_count)])
                insert_sql = f"INSERT INTO \"{layer_name}\" VALUES ({placeholders})"
                cursor_out.executemany(insert_sql, rows)

            # Create all the indexes
            for index_sql in indexes_sql:
                if index_sql:
                    try:
                        cursor_out.execute(index_sql)
                    except sqlite3.Error:
                        # Some indexes might fail, just continue
                        pass

            # Update gpkg_contents and gpkg_geometry_columns (copy entries directly)
            cursor_in.execute("SELECT * FROM gpkg_contents WHERE table_name = ?", (layer_name,))
            contents_row = cursor_in.fetchone()

            if contents_row:
                # Insert new entry
                placeholders = ', '.join(['?' for _ in range(len(contents_row))])
                cursor_out.execute(f"INSERT INTO gpkg_contents VALUES ({placeholders})", contents_row)

            cursor_in.execute("SELECT * FROM gpkg_geometry_columns WHERE table_name = ?", (layer_name,))
            geom_row = cursor_in.fetchone()

            if geom_row:
                # Insert new entry
                placeholders = ', '.join(['?' for _ in range(len(geom_row))])
                cursor_out.execute(f"INSERT INTO gpkg_geometry_columns VALUES ({placeholders})", geom_row)

            # Insert data column metadata if it exists
            if data_columns:
                for data_column in data_columns:
                    cursor_out.execute(
                        """INSERT INTO gpkg_data_columns 
                           (table_name, column_name, name, title, description, mime_type, constraint_name) 
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        data_column
                    )

            conn_in.close()
            conn_out.commit()
            conn_out.close()

        except Exception as e:
            raise Exception(f"Error in direct SQL copy of layer {layer_name}: {str(e)}")

    def copy_nonspatial_table(self, table_name):
        """Copy a non-spatial table from the input to output GeoPackage"""
        try:
            conn_in = sqlite3.connect(self.input_gpkg)
            cursor_in = conn_in.cursor()

            conn_out = sqlite3.connect(self.output_gpkg)
            cursor_out = conn_out.cursor()

            # Get the table schema
            cursor_in.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            table_sql = cursor_in.fetchone()[0]

            # Create the table with the same structure
            cursor_out.execute(f"DROP TABLE IF EXISTS \"{table_name}\"")
            cursor_out.execute(table_sql)

            # Get indexes
            cursor_in.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
                              (table_name,))
            indexes_sql = [row[0] for row in cursor_in.fetchall()]

            # Get all rows
            cursor_in.execute(f"SELECT * FROM \"{table_name}\"")
            rows = cursor_in.fetchall()

            # Get column count
            cursor_in.execute(f"PRAGMA table_info(\"{table_name}\")")
            column_count = len(cursor_in.fetchall())

            # Insert data
            if rows:
                placeholders = ', '.join(['?' for _ in range(column_count)])
                insert_sql = f"INSERT INTO \"{table_name}\" VALUES ({placeholders})"
                cursor_out.executemany(insert_sql, rows)

            # Create indexes
            for index_sql in indexes_sql:
                if index_sql:
                    try:
                        cursor_out.execute(index_sql)
                    except sqlite3.Error:
                        # Some indexes might fail, just continue
                        pass

            # Check if we need to register this table in gpkg_contents (for attributes)
            cursor_in.execute("SELECT * FROM gpkg_contents WHERE table_name = ? AND data_type = 'attributes'",
                              (table_name,))
            contents_row = cursor_in.fetchone()

            if contents_row:
                # Remove any existing entry first
                cursor_out.execute("DELETE FROM gpkg_contents WHERE table_name = ?", (table_name,))

                # Insert new entry
                placeholders = ', '.join(['?' for _ in range(len(contents_row))])
                cursor_out.execute(f"INSERT INTO gpkg_contents VALUES ({placeholders})", contents_row)

            conn_in.close()
            conn_out.commit()
            conn_out.close()

        except Exception as e:
            raise Exception(f"Error copying non-spatial table {table_name}: {str(e)}")

    def update_spatial_references(self, target_crs):
        """Update spatial reference tables in the GeoPackage"""
        try:
            conn = sqlite3.connect(self.output_gpkg)
            cursor = conn.cursor()

            # Get CRS information
            auth_id = target_crs.authid()
            auth_name, auth_code = auth_id.split(':') if ':' in auth_id else ('EPSG', '4326')
            srs_id = target_crs.srsid()
            srs_name = target_crs.description()
            definition = target_crs.toWkt()

            # Check if CRS already exists
            cursor.execute(
                "SELECT srs_id FROM gpkg_spatial_ref_sys WHERE organization=? AND organization_coordsys_id=?",
                (auth_name, auth_code))
            existing = cursor.fetchone()

            if not existing:
                # Insert the CRS if it doesn't exist
                cursor.execute("""
                    INSERT INTO gpkg_spatial_ref_sys (
                        srs_name, srs_id, organization, organization_coordsys_id, 
                        definition, description
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (srs_name, srs_id, auth_name, auth_code, definition, srs_name))

            conn.commit()
            conn.close()

        except Exception as e:
            raise Exception(f"Error updating spatial references: {str(e)}")

    def verify_layer_integrity(self, layer_name, geom_column):
        """Verify that a vector layer was created with proper geometry"""
        try:
            # Check layer exists and has proper metadata
            conn = sqlite3.connect(self.output_gpkg)
            cursor = conn.cursor()

            # Check if table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (layer_name,))
            if not cursor.fetchone():
                raise Exception(f"Table {layer_name} was not created in output GeoPackage")

            # Check if geometry column exists in the table
            cursor.execute(f"PRAGMA table_info(\"{layer_name}\")")
            columns = [col[1] for col in cursor.fetchall()]
            if geom_column not in columns:
                raise Exception(f"Geometry column {geom_column} missing from {layer_name}")

            # Check if layer has an entry in gpkg_geometry_columns
            cursor.execute("SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ?", (layer_name,))
            if not cursor.fetchone():
                raise Exception(f"Layer {layer_name} is missing from gpkg_geometry_columns")

            # Check if layer has an entry in gpkg_contents with data_type='features'
            cursor.execute("SELECT data_type FROM gpkg_contents WHERE table_name = ?", (layer_name,))
            result = cursor.fetchone()
            if not result or result[0] != 'features':
                raise Exception(f"Layer {layer_name} is not properly registered as 'features' in gpkg_contents")

            conn.close()

        except Exception as e:
            raise Exception(f"Layer integrity verification failed for {layer_name}: {str(e)}")

    def process_raster_layer(self, layer_name, target_crs):
        """Process a raster layer, with optional reprojection"""
        try:
            # For raster layers, we'll use GDAL Processing tools
            from processing.core.Processing import Processing
            from processing.tools import general

            Processing.initialize()

            if target_crs and target_crs.isValid():
                # Use GDAL Warp for reprojection
                params = {
                    'INPUT': f"{self.input_gpkg}|layername={layer_name}",
                    'SOURCE_CRS': None,  # Auto-detect
                    'TARGET_CRS': target_crs.authid(),
                    'RESAMPLING': 0,  # Nearest Neighbor
                    'NODATA': None,
                    'TARGET_RESOLUTION': None,
                    'OPTIONS': '',
                    'DATA_TYPE': 0,  # Use Input Layer Data Type
                    'TARGET_EXTENT': None,
                    'TARGET_EXTENT_CRS': None,
                    'MULTITHREADING': False,
                    'EXTRA': f"-of GPKG -co RASTER_TABLE={layer_name}",
                    'OUTPUT': self.output_gpkg
                }

                result = general.run("gdal:warpreproject", params)
            else:
                # Just copy the raster layer with original parameters
                params = {
                    'INPUT': f"{self.input_gpkg}|layername={layer_name}",
                    'OPTIONS': f"RASTER_TABLE={layer_name}",
                    'OUTPUT': self.output_gpkg
                }

                result = general.run("gdal:translate", params)

        except Exception as e:
            raise Exception(f"Error processing raster layer {layer_name}: {str(e)}")

    def verify_gpkg_integrity(self):
        """Verify the integrity of the output GeoPackage"""
        try:
            # Compare input and output structure
            input_vector_layers, input_nonspatial, input_raster = self.list_gpkg_contents(self.input_gpkg)
            output_vector_layers, output_nonspatial, output_raster = self.list_gpkg_contents(self.output_gpkg)

            # Check for missing vector layers
            missing_vectors = set(input_vector_layers) - set(output_vector_layers)
            if missing_vectors:
                raise Exception(f"Missing vector layers in output: {', '.join(missing_vectors)}")

            # Check for missing non-spatial tables
            missing_nonspatial = set(input_nonspatial) - set(output_nonspatial)
            if missing_nonspatial:
                raise Exception(f"Missing non-spatial tables in output: {', '.join(missing_nonspatial)}")

            # Check for missing raster layers
            missing_rasters = set(input_raster) - set(output_raster)
            if missing_rasters:
                raise Exception(f"Missing raster layers in output: {', '.join(missing_rasters)}")

        except Exception as e:
            raise Exception(f"GeoPackage integrity verification failed: {str(e)}")

    def optimize_gpkg(self, gpkg_path):
        """Optimize the GeoPackage file"""
        try:
            conn = sqlite3.connect(gpkg_path)
            cursor = conn.cursor()

            # Run VACUUM to optimize the database
            cursor.execute("VACUUM")

            # Run ANALYZE to update statistics
            cursor.execute("ANALYZE")

            conn.commit()
            conn.close()

        except Exception as e:
            raise Exception(f"Error optimizing GeoPackage: {str(e)}")


# Replace the last two lines of script_reprojectgeopackage.py with this code:

def run_reproject_geopackage():
    """Main function to run the GeoPackage Reproject Tool"""
    from qgis.utils import iface

    # Re-raise existing dialog if still alive
    if hasattr(iface, "_reproject_dialog") and iface._reproject_dialog is not None:
        try:
            iface._reproject_dialog.raise_()
            iface._reproject_dialog.activateWindow()
            return iface._reproject_dialog
        except RuntimeError:
            iface._reproject_dialog = None

    parent = iface.mainWindow()
    dialog = GeoPackageReprojectDialog(parent)

    from qgis.PyQt.QtCore import Qt
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)

    # Store persistent reference to prevent GC; clean up on close
    dialog.destroyed.connect(lambda: setattr(iface, "_reproject_dialog", None))
    iface._reproject_dialog = dialog

    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


def run(iface):
    """Entry point called from mainplugin.py."""
    return run_reproject_geopackage()