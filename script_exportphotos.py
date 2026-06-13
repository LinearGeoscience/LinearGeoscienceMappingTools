"""
Enhanced Photo Export Script for QGIS
This script exports georeferenced field photos from a QGIS layer with multiple export options via GUI.

Features:
- Auto-loads the specified photo layer (configurable below)
- Multiple export options (All, Sample type, Favourites)
- Preview table showing photos to be exported
- Comprehensive error handling and warnings
- Two export modes:
  1. Copy Photos + CSV: Standard export that copies photos and creates CSV attribute table
  2. Package for Sharing: Creates a portable folder with:
     - GeoPackage containing photo points with embedded styling
     - Photos subfolder with copied images
     - Relative paths for portability
     - README with usage instructions for clients

Configuration:
- Change PHOTO_TABLE_NAME in the PhotoExportDialog.__init__() method to match your layer name
- Change PHOTO_POINTS_NAME for the spatial layer used in package mode
- Change field names if different from defaults (PhotoPath, Type, Favourite)
"""

from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QComboBox, QRadioButton, QButtonGroup, QTableWidget,
                             QTableWidgetItem, QPushButton, QLineEdit, QMessageBox,
                             QHeaderView, QGroupBox, QFileDialog, QProgressBar,
                             QTextEdit, QSplitter, QCheckBox)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal, QUrl
from qgis.PyQt.QtGui import QFont, QColor
from qgis.core import (QgsProject, QgsVectorLayer, QgsVectorFileWriter, QgsFeature,
                       QgsSymbol, QgsSingleSymbolRenderer, QgsSimpleMarkerSymbolLayer,
                       QgsPalLayerSettings, QgsVectorLayerSimpleLabeling,
                       QgsTextBufferSettings, QgsMessageLog, Qgis, QgsWkbTypes)
import os
import shutil
import datetime
import re

try:
    from .layer_select import layer_candidates, populate_layer_combo, combo_current_layer
except ImportError:
    from layer_select import layer_candidates, populate_layer_combo, combo_current_layer


class PhotoExportWorker(QThread):
    """Worker thread for photo export operations"""
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, features_to_export, dest_folder, layer_name, photo_path_field,
                 rename_by_sampleid=False, sampleid_field=None):
        super().__init__()
        self.features_to_export = features_to_export
        self.dest_folder = dest_folder
        self.layer_name = layer_name
        self.photo_path_field = photo_path_field
        self.rename_by_sampleid = rename_by_sampleid
        self.sampleid_field = sampleid_field

    def run(self):
        try:
            # Copy photos
            missing_photos = []
            missing_sampleids = []  # Track photos without SampleID
            sampleid_counts = {}    # Track counts for duplicate handling
            total_photos = len(self.features_to_export)

            for i, feature in enumerate(self.features_to_export):
                photo_path = feature[self.photo_path_field]

                if not photo_path or not os.path.isfile(photo_path):
                    missing_photos.append(photo_path or "Empty path")
                    self.log_message.emit(f"Missing: {photo_path or 'Empty path'}")
                else:
                    try:
                        # Determine output filename
                        if self.rename_by_sampleid and self.sampleid_field:
                            sampleid = feature[self.sampleid_field]
                            if sampleid and str(sampleid).strip():
                                # Capitalise and clean the SampleID
                                base_name = str(sampleid).strip().upper()
                                ext = os.path.splitext(photo_path)[1]

                                # Handle duplicates
                                if base_name in sampleid_counts:
                                    sampleid_counts[base_name] += 1
                                    filename = f"{base_name} ({sampleid_counts[base_name]}){ext}"
                                else:
                                    sampleid_counts[base_name] = 0
                                    filename = f"{base_name}{ext}"
                            else:
                                # Missing SampleID - use original filename
                                filename = os.path.basename(photo_path)
                                missing_sampleids.append(photo_path)
                                self.log_message.emit(f"Missing SampleID - keeping original name: {filename}")
                        else:
                            filename = os.path.basename(photo_path)

                        dest_path = os.path.join(self.dest_folder, filename)
                        shutil.copy(photo_path, dest_path)
                        self.log_message.emit(f"Copied: {filename}")
                    except Exception as e:
                        self.log_message.emit(f"Error copying {photo_path}: {e}")
                        missing_photos.append(photo_path)

                progress_percent = int((i + 1) / total_photos * 90)  # 90% for copying
                self.progress.emit(progress_percent)

            # Export CSV
            self.log_message.emit("Exporting CSV...")
            csv_path = os.path.join(self.dest_folder, f"{self.layer_name.replace(' ', '_')}.csv")

            # Get field names from first feature
            if self.features_to_export:
                fields = [field.name() for field in self.features_to_export[0].fields()]

                with open(csv_path, 'w', encoding='utf-8', newline='') as csv_file:
                    # Write header
                    csv_file.write(','.join(f'"{field}"' for field in fields) + '\n')

                    # Write feature data
                    for feature in self.features_to_export:
                        values = []
                        for field in fields:
                            value = str(feature[field]) if feature[field] is not None else ""
                            # Escape quotes in values
                            value = value.replace('"', '""')
                            values.append(f'"{value}"')
                        csv_file.write(','.join(values) + '\n')

            self.progress.emit(100)

            summary = f"Export completed!\n"
            summary += f"Total photos processed: {total_photos}\n"
            summary += f"Successfully copied: {total_photos - len(missing_photos)}\n"
            summary += f"Missing/failed: {len(missing_photos)}\n"
            summary += f"CSV exported to: {csv_path}"

            self.finished.emit(True, summary)

        except Exception as e:
            self.finished.emit(False, f"Export failed: {str(e)}")


class PhotoPackageWorker(QThread):
    """Worker thread for creating shareable photo packages with GeoPackage and styling"""
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, source_layer, features_to_export, dest_folder, photo_path_field,
                 folder_name=None, gpkg_name=None):
        super().__init__()
        self.source_layer = source_layer
        self.features_to_export = features_to_export
        self.dest_folder = dest_folder
        self.photo_path_field = photo_path_field
        self.folder_name = folder_name
        self.gpkg_name = gpkg_name

    def run(self):
        try:
            # 1. Create folder structure
            # Use custom folder name if provided, otherwise auto-generate with timestamp
            if self.folder_name and self.folder_name.strip():
                folder_name = self.folder_name.strip()
            else:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                folder_name = f"PhotoPackage_{timestamp}"
            package_folder = os.path.join(self.dest_folder, folder_name)
            photos_folder = os.path.join(package_folder, "photos")
            os.makedirs(photos_folder, exist_ok=True)
            self.log_message.emit(f"Created package folder: {package_folder}")

            # 2. Copy photos and build path mapping
            self.log_message.emit("Copying photos...")
            path_mapping = {}  # old_path -> new_relative_path
            missing_photos = []
            total_photos = len(self.features_to_export)

            for i, feature in enumerate(self.features_to_export):
                old_path = feature[self.photo_path_field]

                if not old_path or not os.path.isfile(old_path):
                    missing_photos.append(old_path or "Empty path")
                    self.log_message.emit(f"Missing: {old_path or 'Empty path'}")
                else:
                    try:
                        filename = self._get_unique_filename(old_path, photos_folder)
                        dest_path = os.path.join(photos_folder, filename)
                        shutil.copy(old_path, dest_path)
                        path_mapping[old_path] = f"./photos/{filename}"
                        self.log_message.emit(f"Copied: {filename}")
                    except Exception as e:
                        self.log_message.emit(f"Error copying {old_path}: {e}")
                        missing_photos.append(old_path)

                progress_percent = int((i + 1) / total_photos * 50)  # 50% for copying
                self.progress.emit(progress_percent)

            # 3. Create GeoPackage with updated paths
            self.log_message.emit("Creating GeoPackage...")
            # Use custom GeoPackage name if provided, otherwise default to 'photo_points'
            if self.gpkg_name and self.gpkg_name.strip():
                gpkg_filename = self.gpkg_name.strip()
                # Remove .gpkg extension if user included it
                if gpkg_filename.lower().endswith('.gpkg'):
                    gpkg_filename = gpkg_filename[:-5]
            else:
                gpkg_filename = "photo_points"
            gpkg_path = os.path.join(package_folder, f"{gpkg_filename}.gpkg")
            self._create_geopackage(gpkg_path, path_mapping)
            self.progress.emit(70)

            # 4. Apply styling to GeoPackage
            self.log_message.emit("Applying styling...")
            self._apply_styling(gpkg_path)
            self.progress.emit(90)

            # 5. Create readme file with instructions
            self._create_readme(package_folder, gpkg_filename)
            self.progress.emit(100)

            summary = f"Package created successfully!\n\n"
            summary += f"Location: {package_folder}\n"
            summary += f"Photos copied: {total_photos - len(missing_photos)}\n"
            summary += f"Missing/failed: {len(missing_photos)}\n\n"
            summary += f"To share:\n"
            summary += f"1. Zip the folder and send to client\n"
            summary += f"2. Client extracts to any location\n"
            summary += f"3. Open {gpkg_filename}.gpkg in QGIS\n"
            summary += f"4. Enable Map Tips (View > Map Tips) for photo previews"

            self.finished.emit(True, summary)

        except Exception as e:
            import traceback
            self.log_message.emit(f"Error: {traceback.format_exc()}")
            self.finished.emit(False, f"Package creation failed: {str(e)}")

    def _get_unique_filename(self, original_path, dest_folder):
        """Get unique filename, appending counter if duplicate exists"""
        filename = os.path.basename(original_path)
        base, ext = os.path.splitext(filename)
        counter = 1

        while os.path.exists(os.path.join(dest_folder, filename)):
            filename = f"{base}_{counter}{ext}"
            counter += 1

        return filename

    def _create_geopackage(self, gpkg_path, path_mapping):
        """Create GeoPackage with features that have updated relative paths"""
        # Clone the source layer structure
        fields = self.source_layer.fields()
        crs = self.source_layer.crs()

        # Create a memory layer with the same structure
        mem_layer = QgsVectorLayer(f"Point?crs={crs.authid()}", "temp", "memory")
        mem_provider = mem_layer.dataProvider()
        mem_provider.addAttributes(fields.toList())
        mem_layer.updateFields()

        # Add features with updated paths
        new_features = []
        for feature in self.features_to_export:
            new_feature = QgsFeature(fields)
            new_feature.setGeometry(feature.geometry())

            for field in fields:
                field_name = field.name()
                value = feature[field_name]

                # Update PhotoPath field
                if field_name == self.photo_path_field and value in path_mapping:
                    value = path_mapping[value]

                # Update PhotoHTML field - replace absolute paths with placeholder
                # The placeholder {{GPKG_FOLDER}} will be replaced at runtime by the map tip template
                # using QGIS expressions to build the full path based on the GeoPackage location
                #
                # Key insight: PhotoPath only contains the FIRST photo's path, but PhotoHTML contains
                # ALL photos for the point. We need to use PhotoFiles field (comma-separated filenames)
                # to find and replace ALL photo paths in the HTML.
                if field_name == 'PhotoHTML' and value:
                    # Get the photo folder from any path in path_mapping
                    if path_mapping:
                        sample_old_path = next(iter(path_mapping.keys()))
                        photo_folder = os.path.dirname(sample_old_path)

                        # Get all photo files for this feature from PhotoFiles field
                        photo_files_str = feature['PhotoFiles'] if 'PhotoFiles' in [f.name() for f in fields] else ''
                        if photo_files_str:
                            photo_files = [f.strip() for f in str(photo_files_str).split(',')]

                            for photo_file in photo_files:
                                if photo_file:
                                    # Construct the old absolute path
                                    old_abs_path = os.path.join(photo_folder, photo_file)

                                    # Create all possible path variants for replacement
                                    old_fwd = old_abs_path.replace('\\', '/')
                                    old_bwd = old_abs_path.replace('/', '\\')

                                    # New relative placeholder
                                    new_placeholder = '{{GPKG_FOLDER}}photos/' + photo_file

                                    # Replace all variants in PhotoHTML
                                    # Current georeference output: QUrl-encoded file URL
                                    # (forward slashes + %20 etc.) — match this first.
                                    old_url = QUrl.fromLocalFile(old_abs_path).toString()
                                    value = value.replace(old_url, new_placeholder)
                                    # Legacy/backward-compatible variants for layers built
                                    # before the URL was encoded:
                                    # Handle file:/// URLs with forward slashes (standard format)
                                    value = value.replace(f'file:///{old_fwd}', new_placeholder)
                                    # Handle file:/// URLs with backslashes (rare but possible)
                                    value = value.replace(f'file:///{old_bwd}', new_placeholder)
                                    # Handle paths in href/src attributes without file:/// prefix
                                    value = value.replace(f'"{old_fwd}"', f'"{new_placeholder}"')
                                    value = value.replace(f'"{old_bwd}"', f'"{new_placeholder}"')

                new_feature[field_name] = value

            new_features.append(new_feature)

        mem_provider.addFeatures(new_features)

        # Write to GeoPackage. "Photo Points" here names the layer inside the
        # NEW output GeoPackage — it is not a lookup of a project layer.
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "Photo Points"

        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            mem_layer, gpkg_path,
            QgsProject.instance().transformContext(),
            options
        )

        if error[0] != QgsVectorFileWriter.NoError:
            raise Exception(f"Failed to write GeoPackage: {error[1]}")

        self.log_message.emit(f"GeoPackage created: {gpkg_path}")

    def _apply_styling(self, gpkg_path):
        """Apply styling (renderer, labels, map tips) and save to GeoPackage"""
        # Load the exported layer with explicit provider
        # Use a URI that ensures we get a writable connection to the GeoPackage
        uri = f"{gpkg_path}|layername=Photo Points"
        layer = QgsVectorLayer(uri, "Photo Points", "ogr")

        if not layer.isValid():
            raise Exception("Failed to load exported layer for styling")

        # Apply rule-based renderer (categorized by geologist with stars for favourites)
        self._apply_symbol_renderer(layer)

        # Apply labels
        self._apply_labels(layer)

        # Apply map tips
        self._apply_map_tips(layer)

        # Log the map tip expression for debugging
        self.log_message.emit("Map tip template set with dynamic path expression")
        self.log_message.emit("Expression uses: file_path(array_first(string_to_array(layer_property(@layer_name, 'source'), '|')))")

        # Save style to GeoPackage database
        # The return type varies by QGIS version - handle all cases defensively
        try:
            # Check if the layer supports style storage (must be backed by a database)
            if not layer.dataProvider() or layer.dataProvider().name() != 'ogr':
                self.log_message.emit("Warning: Layer provider does not support style storage")
                return

            result = layer.saveStyleToDatabase(
                "default",  # style name
                "Photo points styled by geologist with star markers for favourites",  # description
                True,  # use as default
                ""  # UI file content (empty)
            )

            # Handle different return types defensively
            success = False
            msg_error = ""

            if result is None:
                # Some versions return None on success
                success = True
            elif isinstance(result, bool):
                success = result
            elif isinstance(result, (tuple, list)):
                if len(result) == 0:
                    # Empty tuple/list - assume failure but don't crash
                    success = False
                    msg_error = "Empty result returned"
                elif len(result) == 1:
                    success = bool(result[0])
                else:
                    success = bool(result[0])
                    msg_error = str(result[1]) if result[1] else ""
            elif isinstance(result, str):
                # Some versions might return just an error string
                success = (result == "" or result.lower() == "ok")
                msg_error = result if not success else ""
            else:
                # Unknown type - try to evaluate as boolean
                success = bool(result)

            if success:
                self.log_message.emit("Style saved to GeoPackage")
            else:
                self.log_message.emit(f"Warning: Could not save style ({msg_error}), but GeoPackage was created")

        except TypeError as e:
            # Handle unpacking errors specifically
            self.log_message.emit(f"Warning: Style save returned unexpected format: {e}")
            self.log_message.emit("GeoPackage was created but without embedded style")
        except ValueError as e:
            # Handle value/unpacking errors
            self.log_message.emit(f"Warning: Style save returned unexpected value: {e}")
            self.log_message.emit("GeoPackage was created but without embedded style")
        except Exception as e:
            self.log_message.emit(f"Warning: Could not save style to database: {e}")
            self.log_message.emit("GeoPackage was created but without embedded style")

    def _apply_symbol_renderer(self, layer):
        """Style every photo point as one simple, clean dot: white fill with a thin charcoal
        ring. Kept in sync with script_georeference.py :: apply_symbol_renderer (monochrome,
        uniform — no per-geologist colours, no favourite symbology)."""
        charcoal = QColor('#333333')

        symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        marker = QgsSimpleMarkerSymbolLayer()
        marker.setShape(QgsSimpleMarkerSymbolLayer.Circle)
        marker.setSize(4.5)
        marker.setColor(QColor(255, 255, 255))   # white fill
        marker.setStrokeColor(charcoal)          # thin charcoal ring
        marker.setStrokeWidth(0.5)
        symbol.changeSymbolLayer(0, marker)

        layer.setRenderer(QgsSingleSymbolRenderer(symbol))

    def _apply_labels(self, layer):
        """Apply labels showing photo count — charcoal text with a thin white halo, shown
        only on multi-photo points. Kept in sync with script_georeference.py :: apply_labels."""
        if layer.fields().indexFromName('PhotoCount') == -1:
            return

        label_settings = QgsPalLayerSettings()
        # Only label points that bundle more than one photo — singles stay plain dots.
        label_settings.fieldName = 'if("PhotoCount" > 1, to_string("PhotoCount"), \'\')'
        label_settings.isExpression = True

        # Handle QGIS version differences for placement enum
        try:
            from qgis.core import Qgis
            label_settings.placement = Qgis.LabelPlacement.OverPoint
        except (ImportError, AttributeError):
            # Fallback for older QGIS versions
            label_settings.placement = 1  # OverPoint numeric value

        label_format = label_settings.format()
        label_format.setSize(7)
        label_format.setColor(QColor('#333333'))   # charcoal, matches the ring
        label_format.setForcedBold(True)

        # Thin white halo so a 2-digit count that spills past the white dot stays crisp.
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setSize(0.5)
        buffer.setColor(QColor('white'))
        label_format.setBuffer(buffer)

        label_settings.setFormat(label_format)
        labeling = QgsVectorLayerSimpleLabeling(label_settings)
        layer.setLabelsEnabled(True)
        layer.setLabeling(labeling)

    def _apply_map_tips(self, layer):
        """Apply HTML map tip template for photo slideshow with dynamic path resolution.

        The PhotoHTML field contains {{GPKG_FOLDER}} placeholders which are replaced
        at runtime with the actual folder path where the GeoPackage is located.
        This allows the package to be portable - photos are found relative to the
        GeoPackage location regardless of where it's extracted.
        """
        # The expression replaces {{GPKG_FOLDER}} with the actual folder path:
        # 1. layer_property(@layer_name, 'source') gets the layer source URI
        #    e.g., "C:/folder/photo_points.gpkg|layername=Photo Points"
        # 2. Split on '|' and take first part (handles GeoPackage layer URIs)
        # 3. Get directory by removing filename
        # 4. 'file:///' || ... prepends the file protocol for HTML img src
        #
        # Using array_first and string_to_array to avoid regex escaping issues
        # Expression: 'file:///' || file_path(array_first(string_to_array(layer_property(@layer_name,'source'),'|')))
        # file_path() returns the directory containing a file
        # NOTE: This popup is kept in sync with script_georeference.py ::
        # apply_html_map_tip. The only intentional difference is the slideshow
        # expression below, which swaps {{GPKG_FOLDER}} placeholders for the package
        # location so the exported package is portable. If you change the
        # header/footer/JS here, mirror it there.
        html = r"""
        <style>
        .lgs-tip {display: inline-block; margin: auto; font-family: 'Segoe UI', Arial, sans-serif; border: 1px solid #D2D6DB; border-radius: 6px; overflow: hidden;}
        .lgs-head {background: #34A853; color: white; padding: 7px 12px; font-size: 13px; font-weight: bold;}
        .lgs-head .fav {color: #FFD54A;}
        .slideshow-container {position: relative; background: #000;}
        .mySlides {display: none; text-align: center;}
        .mySlides img {display: block;}
        .lgs-cap {color: #ddd; font-size: 10px; padding: 3px 6px; background: #000; text-align: center; word-break: break-all;}
        .prev, .next {cursor: pointer; position: absolute; top: 50%; width: auto; padding: 14px; margin-top: -22px; color: white; font-weight: bold; font-size: 18px; transition: 0.3s ease; border-radius: 0 3px 3px 0; user-select: none; background: rgba(0,0,0,0.3);}
        .next {right: 0; border-radius: 3px 0 0 3px;}
        .prev:hover, .next:hover {background-color: rgba(0,0,0,0.8);}
        .lgs-foot {display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 6px 12px; font-size: 11px; color: #202124; background: #F8F9FA;}
        .lgs-foot .cmt {flex: 1; min-width: 0;}
        .lgs-foot .cnt {color: #5F6368; white-space: nowrap; font-weight: bold;}
        </style>
        <div class="lgs-tip">
          <div class="lgs-head">[% "Geologist" %] &middot; #[% "PhotoID" %] <span class="fav">[% CASE WHEN upper("Favourite") = 'TRUE' THEN '&#9733;' ELSE '' END %]</span></div>
          <div class="slideshow-container">[% replace("PhotoHTML", '{{GPKG_FOLDER}}', 'file:///' || replace(file_path(array_first(string_to_array(layer_property(@layer_name, 'source'), '|'))), '\\', '/') || '/') %]</div>
          <div class="lgs-foot"><span class="cmt">[% coalesce("Comments", '') %]</span><span class="cnt" id="lgs-counter"></span></div>
        </div>
        <script>
        var slideIndex = 1; showSlides(slideIndex);
        function plusSlides(n) { showSlides(slideIndex += n); }
        function showSlides(n) {
          var i; var slides = document.getElementsByClassName("mySlides");
          if (slides.length == 0) return;
          if (n > slides.length) {slideIndex = 1}
          if (n < 1) {slideIndex = slides.length}
          for (i = 0; i < slides.length; i++) { slides[i].style.display = "none"; }
          slides[slideIndex-1].style.display = "block";
          var c = document.getElementById('lgs-counter');
          if (c) { c.innerText = slideIndex + ' / ' + slides.length; }
        }
        </script>
        """
        layer.setMapTipTemplate(html)

    def _create_readme(self, package_folder, gpkg_filename="photo_points"):
        """Create a README file with usage instructions"""
        readme_path = os.path.join(package_folder, "README.txt")
        gpkg_file = f"{gpkg_filename}.gpkg"
        with open(readme_path, 'w') as f:
            f.write("Photo Package - Usage Instructions\n")
            f.write("=" * 40 + "\n\n")
            f.write("This package contains georeferenced field photos.\n\n")
            f.write("Contents:\n")
            f.write(f"  - {gpkg_file}: GeoPackage with photo locations and styling\n")
            f.write("  - photos/: Folder containing the photo files\n\n")
            f.write("IMPORTANT - Folder Structure:\n")
            f.write("  The 'photos' folder MUST remain in the same folder as the GeoPackage.\n")
            f.write("  You can move or rename the parent folder, but the internal structure\n")
            f.write("  must stay the same:\n\n")
            f.write("    YourFolder/\n")
            f.write(f"      {gpkg_file}\n")
            f.write("      photos/\n")
            f.write("        photo1.jpg\n")
            f.write("        photo2.jpg\n")
            f.write("        ...\n\n")
            f.write("To view in QGIS:\n")
            f.write("  1. Open QGIS\n")
            f.write(f"  2. Drag {gpkg_file} into QGIS (or use Layer > Add Layer > Vector)\n")
            f.write("  3. The styling will load automatically\n")
            f.write("  4. Enable Map Tips: View > Map Tips\n")
            f.write("  5. Hover over points to see photo previews\n\n")
            f.write("The photo previews work from any location - just extract the folder\n")
            f.write("anywhere and drag the GeoPackage into QGIS.\n")


class PhotoExportDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Photo Export Tool")
        self.setMinimumSize(900, 700)
        self.resize(1200, 800)

        # Constants - matching original script parameters
        self.PHOTO_TABLE_NAME = "Photo Table"  # Non-spatial table for Copy+CSV mode
        self.PHOTO_POINTS_NAME = "Photo Points"  # Spatial layer for Package mode
        self.PHOTO_PATH_FIELD = "PhotoPath"
        self.TYPE_FIELD = "Type"
        self.FAVOURITE_FIELD = "Favourite"
        self.SAMPLEID_FIELD = "SampleID"

        # Initialize variables
        self.current_layer = None
        self.all_features = []
        self.export_worker = None
        self.is_package_mode = False  # Track current export mode

        self.setup_ui()
        self.load_photo_layer()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Layer info section
        layer_group = QGroupBox("Photo Layer")
        layer_layout = QVBoxLayout()

        layer_select_row = QHBoxLayout()
        layer_select_row.addWidget(QLabel("Layer:"))
        self.layer_combo = QComboBox()
        self.layer_combo.currentIndexChanged.connect(self.on_layer_selected)
        layer_select_row.addWidget(self.layer_combo, 1)
        layer_layout.addLayout(layer_select_row)

        self.layer_info_label = QLabel("Loading photo layer...")
        self.layer_info_label.setStyleSheet("font-weight: bold; color: blue;")
        layer_layout.addWidget(self.layer_info_label)

        layer_group.setLayout(layer_layout)
        layout.addWidget(layer_group)

        # Export mode section
        mode_group = QGroupBox("Export Mode")
        mode_layout = QVBoxLayout()

        self.mode_button_group = QButtonGroup()

        self.radio_copy_csv = QRadioButton("Copy Photos + CSV (standard export)")
        self.radio_copy_csv.setChecked(True)
        self.radio_copy_csv.toggled.connect(self.on_mode_changed)
        self.mode_button_group.addButton(self.radio_copy_csv)
        mode_layout.addWidget(self.radio_copy_csv)

        self.radio_package = QRadioButton("Package for Sharing (GeoPackage + photos folder with styling)")
        self.radio_package.toggled.connect(self.on_mode_changed)
        self.mode_button_group.addButton(self.radio_package)
        mode_layout.addWidget(self.radio_package)

        # Info label for package mode
        self.package_info_label = QLabel("Creates a portable folder with styled GeoPackage and photos that can be shared with clients.")
        self.package_info_label.setStyleSheet("color: #666; font-style: italic; margin-left: 20px;")
        self.package_info_label.setVisible(False)
        mode_layout.addWidget(self.package_info_label)

        # Package naming options (only visible in package mode)
        self.package_naming_widget = QGroupBox("Package Naming")
        naming_layout = QVBoxLayout()

        # Folder name
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Folder name:"))
        self.package_folder_edit = QLineEdit()
        self.package_folder_edit.setPlaceholderText("e.g., ProjectName_Photos")
        self.package_folder_edit.setToolTip("Name for the package folder. Leave blank for auto-generated name with timestamp.")
        folder_row.addWidget(self.package_folder_edit)
        naming_layout.addLayout(folder_row)

        # GeoPackage name
        gpkg_row = QHBoxLayout()
        gpkg_row.addWidget(QLabel("GeoPackage name:"))
        self.gpkg_name_edit = QLineEdit()
        self.gpkg_name_edit.setPlaceholderText("e.g., photo_points")
        self.gpkg_name_edit.setToolTip("Name for the GeoPackage file (without .gpkg extension). Leave blank for 'photo_points'.")
        gpkg_row.addWidget(self.gpkg_name_edit)
        gpkg_row.addWidget(QLabel(".gpkg"))
        naming_layout.addLayout(gpkg_row)

        self.package_naming_widget.setLayout(naming_layout)
        self.package_naming_widget.setVisible(False)
        mode_layout.addWidget(self.package_naming_widget)

        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)

        # Export options section
        options_group = QGroupBox("Export Options")
        options_layout = QVBoxLayout()

        self.export_group = QButtonGroup()

        self.radio_all = QRadioButton("Export All Photos")
        self.radio_all.setChecked(True)
        self.radio_all.toggled.connect(self.update_preview)
        self.export_group.addButton(self.radio_all)
        options_layout.addWidget(self.radio_all)

        self.radio_sample = QRadioButton("Export Only 'Sample' Type Photos")
        self.radio_sample.toggled.connect(self.update_preview)
        self.export_group.addButton(self.radio_sample)
        options_layout.addWidget(self.radio_sample)

        self.radio_favourites = QRadioButton("Export Favourite Photos (X or x)")
        self.radio_favourites.toggled.connect(self.update_preview)
        self.export_group.addButton(self.radio_favourites)
        options_layout.addWidget(self.radio_favourites)

        # Rename by SampleID checkbox (only visible in Copy+CSV mode)
        self.rename_by_sampleid_checkbox = QCheckBox("Rename photos by SampleID (auto-capitalised)")
        self.rename_by_sampleid_checkbox.setToolTip("Rename exported photos using the SampleID field. Multiple photos with the same ID will be numbered (1), (2), etc.")
        options_layout.addWidget(self.rename_by_sampleid_checkbox)

        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        # Create splitter for preview and log
        splitter = QSplitter(Qt.Vertical)

        # Preview table section
        preview_group = QGroupBox("Photos to Export - Preview")
        preview_layout = QVBoxLayout()

        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(4)
        self.preview_table.setHorizontalHeaderLabels(["Filename", "Type", "Full Path", "Status"])

        # Set column widths
        header = self.preview_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Filename
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Type
        header.setSectionResizeMode(2, QHeaderView.Stretch)           # Full Path
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Status

        preview_layout.addWidget(self.preview_table)
        preview_group.setLayout(preview_layout)
        splitter.addWidget(preview_group)

        # Log section
        log_group = QGroupBox("Export Log")
        log_layout = QVBoxLayout()

        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(150)
        self.log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_text)

        log_group.setLayout(log_layout)
        splitter.addWidget(log_group)

        # Set splitter proportions
        splitter.setSizes([500, 150])
        layout.addWidget(splitter)

        # Destination and export section
        dest_group = QGroupBox("Export Destination")
        dest_layout = QVBoxLayout()

        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("Destination Folder:"))
        self.dest_path_edit = QLineEdit()
        dest_row.addWidget(self.dest_path_edit)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_destination)
        dest_row.addWidget(self.browse_btn)

        dest_layout.addLayout(dest_row)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        dest_layout.addWidget(self.progress_bar)

        dest_group.setLayout(dest_layout)
        layout.addWidget(dest_group)

        # Export button
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.export_btn = QPushButton("Export Photos")
        self.export_btn.clicked.connect(self.export_photos)
        button_layout.addWidget(self.export_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def on_mode_changed(self):
        """Handle export mode change between Copy+CSV and Package modes"""
        self.is_package_mode = self.radio_package.isChecked()
        self.package_info_label.setVisible(self.is_package_mode)
        self.package_naming_widget.setVisible(self.is_package_mode)

        # Update button text based on mode
        if self.is_package_mode:
            self.export_btn.setText("Create Package")
        else:
            self.export_btn.setText("Export Photos")

        # Show/hide rename checkbox (only applicable in Copy+CSV mode)
        self.rename_by_sampleid_checkbox.setVisible(not self.is_package_mode)
        if self.is_package_mode:
            self.rename_by_sampleid_checkbox.setChecked(False)

        # Reload the appropriate layer
        self.load_photo_layer()

    def load_photo_layer(self):
        """Repopulate the layer combo for the current export mode and load the selection"""
        if self.is_package_mode:
            # Package mode needs a spatial points layer
            candidates = layer_candidates(geometry=QgsWkbTypes.PointGeometry,
                                          required_fields=[self.PHOTO_PATH_FIELD])
            target_name = self.PHOTO_POINTS_NAME
        else:
            # Copy+CSV mode works from any layer with a photo path field
            candidates = layer_candidates(required_fields=[self.PHOTO_PATH_FIELD])
            target_name = self.PHOTO_TABLE_NAME

        populate_layer_combo(self.layer_combo, candidates, target_name=target_name)
        self.on_layer_selected()

    def on_layer_selected(self):
        """Load the layer currently selected in the combo"""
        layer = combo_current_layer(self.layer_combo)
        if layer is None:
            self.layer_info_label.setText(
                "❌ No suitable photo layer found (needs a "
                f"'{self.PHOTO_PATH_FIELD}' field)!")
            self.layer_info_label.setStyleSheet("font-weight: bold; color: red;")
            # Don't show error dialog on mode switch, just update label
            self.current_layer = None
            self.all_features = []
            self.update_preview()
            return

        self.current_layer = layer

        # Check if required fields exist
        field_names = [field.name() for field in self.current_layer.fields()]

        if self.PHOTO_PATH_FIELD not in field_names:
            self.layer_info_label.setText(f"❌ Missing required field '{self.PHOTO_PATH_FIELD}'")
            self.layer_info_label.setStyleSheet("font-weight: bold; color: red;")
            QMessageBox.critical(self, "Missing Field",
                              f"Layer '{self.current_layer.name()}' does not contain "
                              f"the required field '{self.PHOTO_PATH_FIELD}'")
            self.current_layer = None
            return

        # Update layer info label with field information
        feature_count = self.current_layer.featureCount()
        has_sampleid_field = self.SAMPLEID_FIELD in field_names
        field_status = f"SampleID: {'✓' if has_sampleid_field else '✗'}"

        self.layer_info_label.setText(f"✓ Layer: {self.current_layer.name()} ({feature_count} features) | {field_status}")
        self.layer_info_label.setStyleSheet("font-weight: bold; color: green;")

        QgsMessageLog.logMessage(f"Field detection - SampleID: {'Found' if has_sampleid_field else 'Not found'}", 'Linear Geoscience', Qgis.Info)
        QgsMessageLog.logMessage(f"All fields: {field_names}", 'Linear Geoscience', Qgis.Info)
        QgsMessageLog.logMessage(f"Looking for field: '{self.SAMPLEID_FIELD}'", 'Linear Geoscience', Qgis.Info)

        # Check if Favourite field exists and update radio button accordingly
        if self.FAVOURITE_FIELD not in field_names:
            self.radio_favourites.setText("Export Favourite Photos (Field 'Favourite' not found)")
            self.radio_favourites.setEnabled(False)
            if self.radio_favourites.isChecked():
                self.radio_all.setChecked(True)
        else:
            self.radio_favourites.setText("Export Favourite Photos (X or x)")
            self.radio_favourites.setEnabled(True)

        # Load all features
        self.all_features = list(self.current_layer.getFeatures())

        # Force initial preview update
        QgsMessageLog.logMessage("Forcing initial preview update...", 'Linear Geoscience', Qgis.Info)
        self.update_preview()

        # Also add debugging for radio button connections
        QgsMessageLog.logMessage(f"Radio buttons connected: All={self.radio_all.isChecked()}, Sample={self.radio_sample.isChecked()}, Fav={self.radio_favourites.isChecked()}", 'Linear Geoscience', Qgis.Info)

        # Add explicit check after a moment to ensure UI is ready
        try:
            QTimer.singleShot(100, self.delayed_preview_update)
        except NameError:
            QgsMessageLog.logMessage("QTimer not available, skipping delayed update", 'Linear Geoscience', Qgis.Warning)
            # Fallback: call delayed update directly
            self.delayed_preview_update()

    def delayed_preview_update(self):
        """Delayed preview update to ensure everything is initialized"""
        QgsMessageLog.logMessage("=== DELAYED PREVIEW UPDATE ===", 'Linear Geoscience', Qgis.Info)
        QgsMessageLog.logMessage(f"Delayed check - All={self.radio_all.isChecked()}, Sample={self.radio_sample.isChecked()}, Fav={self.radio_favourites.isChecked()}", 'Linear Geoscience', Qgis.Info)
        self.update_preview()

    def manual_preview_update(self):
        """Manual preview update triggered by button"""
        QgsMessageLog.logMessage("=== MANUAL PREVIEW UPDATE TRIGGERED ===", 'Linear Geoscience', Qgis.Info)
        QgsMessageLog.logMessage(f"Manual check - All={self.radio_all.isChecked()}, Sample={self.radio_sample.isChecked()}, Fav={self.radio_favourites.isChecked()}", 'Linear Geoscience', Qgis.Info)
        self.update_preview()

    def on_radio_changed(self):
        """Debug wrapper for radio button changes"""
        sender = self.sender()
        if sender.isChecked():  # Only respond to the button being checked, not unchecked
            QgsMessageLog.logMessage(f"Radio button changed to: {sender.text()}", 'Linear Geoscience', Qgis.Info)
            QgsMessageLog.logMessage(f"Current state - All={self.radio_all.isChecked()}, Sample={self.radio_sample.isChecked()}, Fav={self.radio_favourites.isChecked()}", 'Linear Geoscience', Qgis.Info)
            self.update_preview()

    def get_filtered_features(self):
        """Get features based on selected export option"""
        if not self.all_features:
            return []

        if self.radio_all.isChecked():
            return self.all_features
        elif self.radio_sample.isChecked():
            return [f for f in self.all_features
                   if f.fields().indexOf(self.TYPE_FIELD) != -1 and
                   f[self.TYPE_FIELD] == 'Sample']
        elif self.radio_favourites.isChecked():
            return [f for f in self.all_features
                   if f.fields().indexOf(self.FAVOURITE_FIELD) != -1 and
                   str(f[self.FAVOURITE_FIELD]).lower() in ['x']]

        return []

    def update_preview(self):
        """Update the preview table based on current selection"""
        if not self.current_layer:
            self.preview_table.setRowCount(0)
            return

        # Temporarily disable sorting while updating table structure
        self.preview_table.setSortingEnabled(False)

        features = self.get_filtered_features()
        self.preview_table.setRowCount(len(features))

        # Determine if we should show SampleID column
        show_sampleid = (self.radio_sample.isChecked() and
                         self.SAMPLEID_FIELD in [field.name() for field in self.current_layer.fields()])

        # Set up columns dynamically
        if show_sampleid:
            self.preview_table.setColumnCount(5)
            self.preview_table.setHorizontalHeaderLabels(["Filename", "Type", "SampleID", "Full Path", "Status"])
            # Adjust column widths
            header = self.preview_table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Filename
            header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Type
            header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # SampleID
            header.setSectionResizeMode(3, QHeaderView.Stretch)  # Full Path
            header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Status
        else:
            self.preview_table.setColumnCount(4)
            self.preview_table.setHorizontalHeaderLabels(["Filename", "Type", "Full Path", "Status"])
            # Adjust column widths
            header = self.preview_table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Filename
            header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Type
            header.setSectionResizeMode(2, QHeaderView.Stretch)  # Full Path
            header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Status

        for row, feature in enumerate(features):
            col = 0

            # Filename
            photo_path = feature[self.PHOTO_PATH_FIELD]
            filename = os.path.basename(photo_path) if photo_path else "No path"
            self.preview_table.setItem(row, col, QTableWidgetItem(filename))
            col += 1

            # Type
            type_value = ""
            if feature.fields().indexOf(self.TYPE_FIELD) != -1:
                type_value = str(feature[self.TYPE_FIELD]) if feature[self.TYPE_FIELD] else ""
            self.preview_table.setItem(row, col, QTableWidgetItem(type_value))
            col += 1

            # SampleID (only if showing samples)
            if show_sampleid:
                sampleid_value = ""
                if feature.fields().indexOf(self.SAMPLEID_FIELD) != -1:
                    sampleid_value = str(feature[self.SAMPLEID_FIELD]) if feature[self.SAMPLEID_FIELD] else ""
                # Create a custom item that sorts numerically if the value is numeric
                sampleid_item = QTableWidgetItem()
                if sampleid_value.isdigit():
                    # For numeric SampleIDs, set the data as an integer for proper sorting
                    sampleid_item.setData(Qt.DisplayRole, sampleid_value)
                    sampleid_item.setData(Qt.UserRole, int(sampleid_value))
                else:
                    sampleid_item.setData(Qt.DisplayRole, sampleid_value)
                self.preview_table.setItem(row, col, sampleid_item)
                col += 1

            # Full Path
            full_path = photo_path if photo_path else ""
            self.preview_table.setItem(row, col, QTableWidgetItem(full_path))
            col += 1

            # Status - create custom sorting for status
            if not photo_path:
                status = "Missing Path"
                sort_value = 3  # Lowest priority
            elif os.path.isfile(photo_path):
                status = "✓ Found"
                sort_value = 1  # Highest priority
            else:
                status = "✗ Not Found"
                sort_value = 2  # Middle priority

            status_item = QTableWidgetItem(status)
            # Use UserRole data for sorting - this ensures Found items come first, then Not Found, then Missing
            status_item.setData(Qt.UserRole, sort_value)

            if status == "✓ Found":
                status_item.setBackground(Qt.lightGray)
            elif status == "✗ Not Found":
                status_item.setBackground(Qt.red)
            else:
                status_item.setBackground(Qt.yellow)

            self.preview_table.setItem(row, col, status_item)

        # Re-enable sorting after populating the table
        self.preview_table.setSortingEnabled(True)

    def browse_destination(self):
        """Browse for destination folder"""
        folder = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
        if folder:
            self.dest_path_edit.setText(folder)

    def export_photos(self):
        """Export photos based on current selection"""
        if not self.current_layer:
            QMessageBox.warning(self, "No Layer", "Please select a layer first.")
            return

        dest_folder = self.dest_path_edit.text().strip()
        if not dest_folder:
            QMessageBox.warning(self, "No Destination", "Please select a destination folder.")
            return

        if not os.path.exists(dest_folder):
            QMessageBox.warning(self, "Invalid Destination", "Destination folder does not exist.")
            return

        features_to_export = self.get_filtered_features()
        if not features_to_export:
            QMessageBox.information(self, "No Photos", "No photos match the selected criteria.")
            return

        # Check for missing photos and warn user
        missing_count = 0
        for feature in features_to_export:
            photo_path = feature[self.PHOTO_PATH_FIELD]
            if not photo_path or not os.path.isfile(photo_path):
                missing_count += 1

        if missing_count > 0:
            reply = QMessageBox.question(self, "Missing Photos",
                                       f"{missing_count} photos are missing or have invalid paths.\n"
                                       f"Do you want to continue with the export?",
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return

        # Check for missing SampleIDs if rename option is enabled
        rename_by_sampleid = self.rename_by_sampleid_checkbox.isChecked() and not self.is_package_mode
        if rename_by_sampleid:
            missing_sampleid_count = 0
            for feature in features_to_export:
                sampleid = feature[self.SAMPLEID_FIELD] if self.SAMPLEID_FIELD in [f.name() for f in feature.fields()] else None
                if not sampleid or not str(sampleid).strip():
                    missing_sampleid_count += 1

            if missing_sampleid_count > 0:
                reply = QMessageBox.question(self, "Missing SampleIDs",
                                           f"{missing_sampleid_count} photos are missing a SampleID.\n"
                                           f"These will be exported with their original filenames.\n\n"
                                           f"Do you want to continue?",
                                           QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.No:
                    return

        # Start export
        self.export_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.log_text.clear()

        if self.is_package_mode:
            # Package mode - create GeoPackage with styling
            self.log_text.append("Creating photo package...\n")
            self.export_worker = PhotoPackageWorker(
                self.current_layer,
                features_to_export,
                dest_folder,
                self.PHOTO_PATH_FIELD,
                folder_name=self.package_folder_edit.text(),
                gpkg_name=self.gpkg_name_edit.text()
            )
        else:
            # Standard mode - copy photos + CSV
            self.log_text.append("Starting export...\n")
            self.export_worker = PhotoExportWorker(
                features_to_export,
                dest_folder,
                self.current_layer.name(),
                self.PHOTO_PATH_FIELD,
                rename_by_sampleid=rename_by_sampleid,
                sampleid_field=self.SAMPLEID_FIELD if rename_by_sampleid else None
            )

        self.export_worker.progress.connect(self.progress_bar.setValue)
        self.export_worker.log_message.connect(self.add_log_message)
        self.export_worker.finished.connect(self.export_finished)

        self.export_worker.start()

    def add_log_message(self, message):
        """Add message to log"""
        self.log_text.append(message)
        self.log_text.ensureCursorVisible()

    def export_finished(self, success, message):
        """Handle export completion"""
        self.export_btn.setEnabled(True)
        self.close_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

        if success:
            self.log_text.append(f"\n{message}")
            QMessageBox.information(self, "Export Complete", message)
        else:
            self.log_text.append(f"\nERROR: {message}")
            QMessageBox.critical(self, "Export Failed", message)


def run_photo_export_tool():
    """Main function to run the photo export tool"""
    dialog = PhotoExportDialog()
    dialog.exec()


def run(iface):
    """Entry point called from mainplugin.py."""
    run_photo_export_tool()