"""
This script georeferences and organizes field photos in QGIS by geologists. It performs the following tasks:
1. Identifies active geologists in the '1 - FieldNotebook' layer and their corresponding photo folders.
2. Matches photos to georeferenced points based on PhotoIDs.
3. Plots georeferenced photo points and creates a photo table in QGIS.
4. Generates HTML tooltips for visualizing photos in a slideshow format within QGIS.
5. Applies customized symbology and labeling for easy identification.
6. Includes Type and Favourite fields for export functionality.

This script integrates data from the 'GeologistCodes' and '1 - FieldNotebook' layers to streamline photo georeferencing workflows.
"""

import os
from qgis.PyQt.QtWidgets import (
    QFileDialog, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QDialogButtonBox, QApplication, QMessageBox
)
from qgis.core import (
    QgsProject, QgsPointXY, QgsFeature, QgsGeometry, QgsVectorLayer, QgsField,
    QgsCoordinateReferenceSystem, QgsPalLayerSettings, QgsVectorLayerSimpleLabeling,
    QgsSimpleMarkerSymbolLayer, QgsSymbol, QgsSingleSymbolRenderer, QgsLayerTreeGroup, QgsRendererCategory,
    QgsCategorizedSymbolRenderer, QgsRuleBasedRenderer, QgsMessageLog, Qgis, QgsWkbTypes
)

try:
    from .layer_select import layer_candidates, populate_layer_combo, combo_current_layer
except ImportError:
    from layer_select import layer_candidates, populate_layer_combo, combo_current_layer

# Reuse the photo panel's dependency-free EXIF orientation reader so portrait photos can be
# rotated upright in the map tip (QtWebKit ignores EXIF orientation).
try:
    from .photo_panel.loader import read_exif_orientation
except ImportError:
    try:
        from photo_panel.loader import read_exif_orientation
    except ImportError:
        def read_exif_orientation(path):
            return 1
from qgis.PyQt.QtCore import QVariant, QUrl
try:
    from qgis.PyQt.QtCore import QMetaType
except ImportError:
    QMetaType = None
from qgis.PyQt.QtGui import QColor, QImageReader
import sys


def create_compatible_field(name, field_type):
    """Create QgsField with QGIS version compatibility"""
    try:
        # Try QGIS 3.34+ syntax first
        if QMetaType and hasattr(QMetaType, 'Type'):
            if field_type == 'string':
                return QgsField(name, QMetaType.Type.QString)
            elif field_type == 'double':
                return QgsField(name, QMetaType.Type.Double)
            elif field_type == 'int':
                return QgsField(name, QMetaType.Type.Int)
        # Fallback for older versions
        if field_type == 'string':
            return QgsField(name, QVariant.String)
        elif field_type == 'double':
            return QgsField(name, QVariant.Double)
        elif field_type == 'int':
            return QgsField(name, QVariant.Int)
    except Exception:
        # Final fallback to QGIS 3.4 syntax
        if field_type == 'string':
            return QgsField(name, QVariant.String)
        elif field_type == 'double':
            return QgsField(name, QVariant.Double)
        elif field_type == 'int':
            return QgsField(name, QVariant.Int)
    
    # Default fallback
    return QgsField(name, QVariant.String)


# Function to retrieve active geologists with entries in the point layer
def get_active_geologists(point_layer, geologist_name_map):
    """Retrieve active geologists in the point layer who have an entry and are present in geologist_name_map."""
    active_geologists = set()
    for feature in point_layer.getFeatures():
        geologist_value = feature['Geologist']
        if geologist_value is not None:
            # Normalize value to string and strip whitespace
            geologist_value = str(geologist_value).strip()
            active_geologists.add(geologist_value)

    # Ensure geologist_name_map keys are also normalized
    return {str(code).strip(): name for code, name in geologist_name_map.items() if
            str(code).strip() in active_geologists}


# Function to retrieve geologist descriptions from the selected codes layer
def get_geologist_name_map(codes_layer):
    geologist_name_map = {}
    if codes_layer is None:
        QgsMessageLog.logMessage("Geologist codes layer not selected.", 'Linear Geoscience', Qgis.Warning)
        return geologist_name_map

    for feature in codes_layer.getFeatures():
        # Normalize Code to string and strip whitespace
        code = str(feature['Code']).strip()
        description = feature['Description']
        geologist_name_map[code] = description
    return geologist_name_map


class GeoreferenceLayerDialog(QDialog):
    """Select the field notebook layer and geologist codes table to use."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Georeference Field Photos - Select Layers")
        self.setMinimumWidth(500)

        layout = QVBoxLayout()
        form = QFormLayout()

        self.point_combo = QComboBox()
        point_layers = layer_candidates(geometry=QgsWkbTypes.PointGeometry,
                                        required_fields=['Geologist', 'PhotoID'])
        populate_layer_combo(self.point_combo, point_layers,
                             target_name='1 - FieldNotebook')
        form.addRow("Field Notebook layer:", self.point_combo)

        self.codes_combo = QComboBox()
        codes_layers = layer_candidates(required_fields=['Code', 'Description'])
        populate_layer_combo(self.codes_combo, codes_layers,
                             target_name='GeologistCodes')
        form.addRow("Geologist Codes table:", self.codes_combo)

        layout.addLayout(form)

        if not point_layers:
            warn = QLabel("⚠️ No point layer with 'Geologist' and 'PhotoID' fields found.")
            warn.setStyleSheet("color: red;")
            layout.addWidget(warn)
        if not codes_layers:
            warn = QLabel("⚠️ No table with 'Code' and 'Description' fields found.")
            warn.setStyleSheet("color: red;")
            layout.addWidget(warn)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def get_selected_layers(self):
        """Return (point_layer, codes_layer) — either may be None."""
        return (combo_current_layer(self.point_combo),
                combo_current_layer(self.codes_combo))


class GeologistFolderDialog(QDialog):
    def __init__(self, geologist_name_map, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Photo Folders for Geologists")
        self.geologist_folders = {}
        self.layout = QVBoxLayout()

        # Create a layout and file selection for each geologist
        for code, name in geologist_name_map.items():
            h_layout = QHBoxLayout()
            label = QLabel(name)
            folder_input = QLineEdit()
            folder_input.setReadOnly(True)
            browse_button = QPushButton("Browse")
            browse_button.clicked.connect(
                lambda checked, key=code, input_field=folder_input: self.select_folder(key, input_field))

            h_layout.addWidget(label)
            h_layout.addWidget(folder_input)
            h_layout.addWidget(browse_button)

            self.layout.addLayout(h_layout)

        # Next button
        next_button = QPushButton("Next")
        next_button.clicked.connect(self.accept)
        self.layout.addWidget(next_button)

        self.setLayout(self.layout)

    def select_folder(self, geologist_code, input_field):
        # Open a file dialog to select the folder
        folder = QFileDialog.getExistingDirectory(self, "Select Photo Folder")
        if folder:
            input_field.setText(folder)
            self.geologist_folders[geologist_code] = folder


def select_geologist_folders(geologist_name_map):
    """Displays a dialog to select folders for each geologist and returns a map of geologist codes to folder paths."""
    app = QApplication.instance() or QApplication(sys.argv)
    dialog = GeologistFolderDialog(geologist_name_map)
    if dialog.exec() == QDialog.Accepted:
        return dialog.geologist_folders
    else:
        return {}


def expand_photo_ids(photo_id_str):
    """Expands photo IDs from strings like '3344/7' into a list of IDs ['3344', '3345', '3346', '3347']."""
    if photo_id_str == 'NULL' or not photo_id_str.strip():
        return []

    photo_ids = []
    components = photo_id_str.split(',')

    for component in components:
        if '/' in component:
            try:
                start, end = component.split('/')
                start, end = int(start), int(end)
                start_str = str(start).zfill(4)

                if len(str(end)) == 1:
                    end = int(start_str[:3] + str(end))
                elif len(str(end)) == 2:
                    end = int(start_str[:2] + str(end))
                elif len(str(end)) == 3:
                    end = int(start_str[:1] + str(end))

                if end < start:
                    end += 10 ** (4 - len(str(end)))

                expanded_range = list(range(start, end + 1))
                expanded_range = [str(i).zfill(4) for i in expanded_range]
                photo_ids.extend(expanded_range)
            except ValueError as e:
                QgsMessageLog.logMessage(f"Error parsing range {component}: {e}", 'Linear Geoscience', Qgis.Warning)
        else:
            try:
                single_id = str(int(component)).zfill(4)
                photo_ids.append(single_id)
            except ValueError as e:
                QgsMessageLog.logMessage(f"Error parsing single ID {component}: {e}", 'Linear Geoscience', Qgis.Warning)

    return photo_ids


# EXIF orientation (1-8) -> CSS transform applied to the <img>, mirroring
# photo_panel.loader.get_exif_transform. QtWebKit ignores EXIF, so we rotate in CSS.
# Orientations 5-8 also swap width/height (90/270 degree rotations).
_EXIF_CSS_TRANSFORM = {
    1: '',
    2: 'scaleX(-1)',
    3: 'rotate(180deg)',
    4: 'scaleY(-1)',
    5: 'rotate(90deg) scaleX(-1)',
    6: 'rotate(90deg)',
    7: 'rotate(-90deg) scaleX(-1)',
    8: 'rotate(-90deg)',
}
_EXIF_SWAP = (5, 6, 7, 8)   # orientations that rotate 90/270 and so swap w/h
_MAPTIP_MAXW, _MAPTIP_MAXH = 480, 460   # cap for the upright on-screen photo


def match_photos(point_layer, geologist_folders, codes_layer):
    """Matches photos based on PhotoID in the point_layer and plots them on a new 'Photo Points' layer, separated by Geologist."""
    # Summary tracking
    photo_summary = {}
    missing_photos = {}

    # Check required fields
    field_names = point_layer.fields().names()
    if 'Geologist' not in field_names or 'PhotoID' not in field_names:
        QgsMessageLog.logMessage("Required fields 'Geologist' or 'PhotoID' are missing in the layer.", 'Linear Geoscience', Qgis.Warning)
        return

    # Check for optional fields and log their status
    has_type_field = 'Type' in field_names
    has_favourite_field = 'Favourite' in field_names
    has_comments_field = 'Comments' in field_names
    has_sampleid_field = 'SampleID' in field_names

    QgsMessageLog.logMessage(f"Field status - Type: {'Found' if has_type_field else 'Missing'}, "
          f"Favourite: {'Found' if has_favourite_field else 'Missing'}, "
          f"Comments: {'Found' if has_comments_field else 'Missing'}, "
          f"SampleID: {'Found' if has_sampleid_field else 'Missing'}", 'Linear Geoscience', Qgis.Info)

    # Retrieve geologist name map from the selected codes layer
    geologist_name_map = get_geologist_name_map(codes_layer)

    project_crs = QgsProject.instance().crs()
    crs_name = project_crs.authid()

    # Create layers for photos and photo table, including all required fields
    photo_layer = QgsVectorLayer(f'Point?crs={project_crs.authid()}', 'Photo Points', 'memory')
    provider = photo_layer.dataProvider()
    provider.addAttributes([
        create_compatible_field('Geologist', 'string'),
        create_compatible_field('PhotoID', 'string'),
        create_compatible_field('PhotoPath', 'string'),
        create_compatible_field('FullPhotoName', 'string'),
        create_compatible_field('PhotoName', 'string'),
        create_compatible_field('Easting', 'double'),
        create_compatible_field('Northing', 'double'),
        create_compatible_field('CRS', 'string'),
        create_compatible_field('PhotoHTML', 'string'),
        create_compatible_field('Comments', 'string'),
        create_compatible_field('PhotoCount', 'int'),
        create_compatible_field('PhotoFiles', 'string'),
        create_compatible_field('Type', 'string'),        # Added for export functionality
        create_compatible_field('Favourite', 'string'),   # Added for export functionality
        create_compatible_field('SampleID', 'string')     # Added for sample tracking
    ])
    photo_layer.updateFields()

    table_layer = QgsVectorLayer(f'NoGeometry?crs={project_crs.authid()}', 'Photo Table', 'memory')
    table_provider = table_layer.dataProvider()
    table_provider.addAttributes([
        create_compatible_field('Geologist', 'string'),
        create_compatible_field('PhotoID', 'string'),
        create_compatible_field('FullPhotoName', 'string'),
        create_compatible_field('PhotoPath', 'string'),
        create_compatible_field('Easting', 'double'),
        create_compatible_field('Northing', 'double'),
        create_compatible_field('CRS', 'string'),
        create_compatible_field('Comments', 'string'),
        create_compatible_field('Type', 'string'),        # Added for export functionality
        create_compatible_field('Favourite', 'string'),   # Added for export functionality
        create_compatible_field('SampleID', 'string')     # Added for sample tracking
    ])
    table_layer.updateFields()

    # Process each feature in point layer by geologist
    for feature in point_layer.getFeatures():
        geologist = feature['Geologist']
        geologist_name = geologist_name_map.get(str(geologist).strip(), f"Geologist {geologist}")
        photo_id_str = str(feature['PhotoID'])

        # Extract optional fields gracefully
        comment = feature['Comments'] if has_comments_field and feature['Comments'] is not None else ''
        type_value = feature['Type'] if has_type_field and feature['Type'] is not None else ''
        favourite_value = feature['Favourite'] if has_favourite_field and feature['Favourite'] is not None else ''
        sampleid_value = feature['SampleID'] if has_sampleid_field and feature['SampleID'] is not None else ''

        if geologist not in geologist_folders:
            QgsMessageLog.logMessage(f"Skipping feature ID {feature.id()} for geologist {geologist_name} - No folder selected.", 'Linear Geoscience', Qgis.Info)
            continue

        if photo_id_str == 'NULL' or not photo_id_str.strip():
            continue  # Skip NULL or empty PhotoID entries

        photo_folder = geologist_folders[geologist]
        photo_dict = {}
        for root, dirs, files in os.walk(photo_folder):
            for file in files:
                if file.lower().endswith(('.jpg', '.jpeg', '.png')):
                    photo_id = file[-8:-4]
                    # Store the FULL path (root may be a subfolder). Storing only the
                    # bare filename and rebuilding from photo_folder broke nested layouts:
                    # the photo matched but the path pointed at the wrong place.
                    photo_dict[photo_id] = os.path.join(root, file)

        try:
            expanded_photo_ids = expand_photo_ids(photo_id_str)
        except Exception as e:
            QgsMessageLog.logMessage(f"Error expanding PhotoID for {geologist_name}:{photo_id_str} - {e}", 'Linear Geoscience', Qgis.Warning)
            continue

        photo_html = ""
        photo_files = []
        first_photo_path = None
        x, y = feature.geometry().asPoint().x(), feature.geometry().asPoint().y()

        # First pass: match files, build the photo table, and work out each photo's upright
        # (EXIF-corrected) on-screen size so the slides can share one stable frame.
        slides = []
        for full_photo_id in expanded_photo_ids:
            photo_path = photo_dict.get(full_photo_id)
            if not photo_path:
                # Track missing photo ID
                missing_photos.setdefault(geologist_name, []).append(full_photo_id)
                continue

            full_photo_name = os.path.basename(photo_path)
            # photo_files holds bare filenames — the PhotoFiles field and the export
            # script's path reconstruction both rely on basenames.
            photo_files.append(full_photo_name)
            if first_photo_path is None:
                first_photo_path = photo_path

            # Canonical file URL: forward slashes + percent-encoded spaces/specials so
            # QtWebKit reliably loads paths like '...\Field Photos - May\...'.
            photo_url = QUrl.fromLocalFile(photo_path).toString()

            # Add to Photo Table with Type, Favourite, and SampleID fields
            table_feature = QgsFeature()
            table_feature.setAttributes([
                geologist_name, full_photo_id, full_photo_name, photo_path,
                x, y, crs_name, comment, str(type_value), str(favourite_value), str(sampleid_value)
            ])
            table_provider.addFeature(table_feature)

            # EXIF orientation -> upright display size + CSS transform (QtWebKit ignores EXIF).
            orient = read_exif_orientation(photo_path)
            if orient not in _EXIF_CSS_TRANSFORM:
                orient = 1
            size = QImageReader(photo_path).size()
            sw, sh = size.width(), size.height()
            swap = orient in _EXIF_SWAP
            if sw > 0 and sh > 0:
                disp_w, disp_h = (sh, sw) if swap else (sw, sh)   # upright pixel dims
                scale = min(_MAPTIP_MAXW / disp_w, _MAPTIP_MAXH / disp_h, 1.0)
                f_w, f_h = max(1, round(disp_w * scale)), max(1, round(disp_h * scale))
                slides.append({'url': photo_url, 'name': full_photo_name, 'swap': swap,
                               'fw': f_w, 'fh': f_h, 'tcss': _EXIF_CSS_TRANSFORM[orient]})
            else:
                # Unreadable dimensions: fall back to plain object-fit (no rotation).
                slides.append({'url': photo_url, 'name': full_photo_name, 'fallback': True})

        # Envelope: one frame size for every slide of this point so the popup doesn't resize
        # as you flip between photos. Portrait points get a tall/narrow frame, landscape wide.
        sized = [s for s in slides if not s.get('fallback')]
        env_w = max((s['fw'] for s in sized), default=_MAPTIP_MAXW)
        env_h = max((s['fh'] for s in sized), default=_MAPTIP_MAXH)

        # Second pass: emit one slide per photo. The image is centred in the envelope frame
        # and rotated upright via CSS. src="..." is unchanged so script_exportphotos.py can
        # still rewrite the QUrl-encoded paths to portable {{GPKG_FOLDER}} placeholders.
        for s in slides:
            if s.get('fallback'):
                photo_html += (
                    f'<div class="mySlides">'
                    f'<a href="{s["url"]}" target="_blank">'
                    f'<img src="{s["url"]}" style="max-width:{env_w}px;max-height:{env_h}px;object-fit:contain;"></a>'
                    f'<div class="lgs-cap">{s["name"]}</div>'
                    f'</div>'
                )
                continue
            # For swapped (90/270) orientations the <img> is sized with width/height swapped
            # so its footprint after rotation becomes f_w x f_h, matching the frame.
            iw, ih = (s['fh'], s['fw']) if s['swap'] else (s['fw'], s['fh'])
            photo_html += (
                f'<div class="mySlides">'
                f'<div class="lgs-stage" style="width:{env_w}px;height:{env_h}px;position:relative;margin:auto;">'
                f'<a href="{s["url"]}" target="_blank"><img src="{s["url"]}" '
                f'style="position:absolute;top:50%;left:50%;width:{iw}px;height:{ih}px;max-width:none;'
                f'transform:translate(-50%,-50%) {s["tcss"]};"></a>'
                f'</div>'
                f'<div class="lgs-cap">{s["name"]}</div>'
                f'</div>'
            )

        if len(photo_files) > 1:
            photo_html += """
            <a class="prev" onclick="plusSlides(-1)">&#10094;</a>
            <a class="next" onclick="plusSlides(1)">&#10095;</a>
            """

        if photo_files:
            photo_files_str = ', '.join(photo_files)
            photo_feature = QgsFeature()
            photo_feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            photo_feature.setAttributes([
                geologist_name, photo_id_str, first_photo_path,
                photo_files[0], photo_files[0], x, y, crs_name, photo_html, comment,
                len(photo_files), photo_files_str, str(type_value), str(favourite_value), str(sampleid_value)
            ])
            provider.addFeature(photo_feature)
        else:
            QgsMessageLog.logMessage(f"No matching photo files found for Geologist:PhotoID {geologist_name}:{photo_id_str}", 'Linear Geoscience', Qgis.Warning)

        # Update summary
        photo_summary[geologist_name] = photo_summary.get(geologist_name, 0) + len(photo_files)

    # Create group in QGIS and add layers
    group = QgsProject.instance().layerTreeRoot().insertGroup(0, 'Georeferenced Photos')
    QgsProject.instance().addMapLayer(photo_layer, False)
    QgsProject.instance().addMapLayer(table_layer, False)
    group.addLayer(photo_layer)
    group.addLayer(table_layer)

    apply_html_map_tip(photo_layer)
    apply_symbol_renderer(photo_layer)
    apply_labels(photo_layer)
    QgsMessageLog.logMessage("Photo points and Photo Table have been plotted in QGIS with Type, Favourite, and SampleID fields included.", 'Linear Geoscience', Qgis.Info)

    # Show summary popup
    summary_message = "Georeferencing Summary:\n"
    for geologist_name, count in photo_summary.items():
        summary_message += f"{geologist_name}: {count} photos georeferenced\n"

    # Add field status to summary
    summary_message += f"\nField Status:\n"
    summary_message += f"Type field: {'Included' if has_type_field else 'Not found (using empty values)'}\n"
    summary_message += f"Favourite field: {'Included' if has_favourite_field else 'Not found (using empty values)'}\n"
    summary_message += f"SampleID field: {'Included' if has_sampleid_field else 'Not found (using empty values)'}\n"

    if missing_photos:
        summary_message += "\nMissing Photos:\n"
        for geologist_name, missing_ids in missing_photos.items():
            summary_message += f"{geologist_name}: {', '.join(missing_ids)}\n"

    QMessageBox.information(None, "Georeferencing Summary", summary_message)


# HTML Map Tip
#
# NOTE: The styling/markup below is intentionally kept in sync with
# script_exportphotos.py :: PhotoExporter._apply_map_tips, which renders the same
# popup for exported GeoPackages. If you change the header/footer/JS here, mirror it
# there. The only deliberate difference is the slideshow expression: this layer reads
# the raw PhotoHTML field, while the export swaps {{GPKG_FOLDER}} placeholders for the
# package location.
def apply_html_map_tip(layer):
    html = """
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
      <div class="slideshow-container">[% PhotoHTML %]</div>
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
    layer.triggerRepaint()


# Symbol Renderer (single clean monochrome dot)
def apply_symbol_renderer(layer):
    """Style every photo point as one simple, clean dot: white fill with a thin charcoal
    ring. Monochrome and uniform — no per-geologist colours and no favourite symbology."""
    from qgis.core import QgsSymbol, QgsSimpleMarkerSymbolLayer, QgsSingleSymbolRenderer
    from qgis.PyQt.QtGui import QColor

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
    layer.triggerRepaint()

    QgsMessageLog.logMessage(
        "Applied clean monochrome point markers (white fill, charcoal ring).",
        'Linear Geoscience', Qgis.Info)


# Labeling
def apply_labels(layer):
    from qgis.core import QgsTextBufferSettings

    label_settings = QgsPalLayerSettings()
    # Only label points that bundle more than one photo — a lone "1" on every
    # single-photo point is just clutter.
    label_settings.fieldName = 'if("PhotoCount" > 1, to_string("PhotoCount"), \'\')'
    label_settings.isExpression = True
    label_settings.placement = QgsPalLayerSettings.Placement.OverPoint
    label_format = label_settings.format()
    label_format.setSize(7)
    label_format.setColor(QColor('#333333'))   # charcoal, matches the ring
    label_format.setForcedBold(True)

    # Thin white halo so a 2-digit count that spills past the white dot stays crisp
    # where it overlaps the imagery.
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(0.5)
    buffer.setColor(QColor('white'))
    label_format.setBuffer(buffer)

    label_settings.setFormat(label_format)
    labeling = QgsVectorLayerSimpleLabeling(label_settings)
    layer.setLabelsEnabled(True)
    layer.setLabeling(labeling)
    layer.triggerRepaint()


def main():
    # Let the user pick the layers (pre-matched to the standard names)
    dialog = GeoreferenceLayerDialog()
    if dialog.exec() != QDialog.Accepted:
        QgsMessageLog.logMessage("Georeferencing cancelled.", 'Linear Geoscience', Qgis.Info)
        return

    point_layer, codes_layer = dialog.get_selected_layers()
    if point_layer is None:
        QMessageBox.warning(None, "Georeference Field Photos",
                            "No field notebook layer selected. The layer needs "
                            "'Geologist' and 'PhotoID' fields.")
        return
    if codes_layer is None:
        QMessageBox.warning(None, "Georeference Field Photos",
                            "No geologist codes table selected. The table needs "
                            "'Code' and 'Description' fields.")
        return

    QgsMessageLog.logMessage(f"Using point layer '{point_layer.name()}'.", 'Linear Geoscience', Qgis.Info)

    # Debugging: List fields in the layer
    field_names = [field.name() for field in point_layer.fields()]
    QgsMessageLog.logMessage(f"Fields in '{point_layer.name()}': {field_names}", 'Linear Geoscience', Qgis.Info)

    # Debugging: Check the data source of the layer
    data_source = point_layer.dataProvider().dataSourceUri()
    QgsMessageLog.logMessage(f"Data source of '{point_layer.name()}': {data_source}", 'Linear Geoscience', Qgis.Info)

    # Load the geologist name map from the selected codes layer
    geologist_name_map = get_geologist_name_map(codes_layer)
    QgsMessageLog.logMessage(f"Geologist Name Map: {geologist_name_map}", 'Linear Geoscience', Qgis.Info)
    if not geologist_name_map:
        QgsMessageLog.logMessage(f"Could not load geologist names from '{codes_layer.name()}'. Ensure this table is correctly set up.", 'Linear Geoscience', Qgis.Warning)
        return

    # Filter geologists to only those found in the point layer
    active_geologist_map = get_active_geologists(point_layer, geologist_name_map)
    QgsMessageLog.logMessage(f"Active Geologist Map: {active_geologist_map}", 'Linear Geoscience', Qgis.Info)
    if not active_geologist_map:
        QgsMessageLog.logMessage("No active geologists found in '1 - FieldNotebook' layer.", 'Linear Geoscience', Qgis.Warning)
        return

    # Display the dialog to select photo folders for each active geologist
    geologist_folders = select_geologist_folders(active_geologist_map)
    if not geologist_folders:
        QgsMessageLog.logMessage("No photo folders selected for any geologist.", 'Linear Geoscience', Qgis.Warning)
        return

    # Pass the geologist folder map to match_photos
    match_photos(point_layer, geologist_folders, codes_layer)
    QgsMessageLog.logMessage("Photo points and Photo Table have been plotted in QGIS with Type, Favourite, and SampleID fields included.", 'Linear Geoscience', Qgis.Info)


def run(iface):
    """Entry point called from mainplugin.py."""
    main()