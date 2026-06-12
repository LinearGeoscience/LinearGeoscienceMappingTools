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
from qgis.PyQt.QtCore import QVariant
try:
    from qgis.PyQt.QtCore import QMetaType
except ImportError:
    QMetaType = None
from qgis.PyQt.QtGui import QColor
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
                    photo_dict[photo_id] = file

        try:
            expanded_photo_ids = expand_photo_ids(photo_id_str)
        except Exception as e:
            QgsMessageLog.logMessage(f"Error expanding PhotoID for {geologist_name}:{photo_id_str} - {e}", 'Linear Geoscience', Qgis.Warning)
            continue

        photo_html = ""
        photo_files = []
        x, y = feature.geometry().asPoint().x(), feature.geometry().asPoint().y()

        for full_photo_id in expanded_photo_ids:
            photo_file = photo_dict.get(full_photo_id)
            if photo_file:
                photo_files.append(photo_file)
                photo_path = os.path.join(photo_folder, photo_file)
                full_photo_name = os.path.basename(photo_file)

                # Add to Photo Table with Type, Favourite, and SampleID fields
                table_feature = QgsFeature()
                table_feature.setAttributes([
                    geologist_name, full_photo_id, full_photo_name, photo_path,
                    x, y, crs_name, comment, str(type_value), str(favourite_value), str(sampleid_value)
                ])
                table_provider.addFeature(table_feature)

                # Add to HTML
                if comment:
                    photo_html += f'<div class="mySlides"><h3>{comment}</h3><a href="file:///{photo_path}" target="_blank"><img src="file:///{photo_path}" style="max-width:100%;max-height:1000px;object-fit:contain;"></a></div>'
                else:
                    photo_html += f'<div class="mySlides"><a href="file:///{photo_path}" target="_blank"><img src="file:///{photo_path}" style="max-width:100%;max-height:500px;object-fit:contain;"></a></div>'
            else:
                # Track missing photo ID
                missing_photos.setdefault(geologist_name, []).append(full_photo_id)

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
                geologist_name, photo_id_str, os.path.join(photo_folder, photo_files[0]),
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
def apply_html_map_tip(layer):
    html = """
    <style>
    .slideshow-container {max-width: 500px; position: relative; margin: auto;}
    .mySlides {display: none;}
    .prev, .next {cursor: pointer; position: absolute; top: 50%; width: auto; padding: 16px; margin-top: -22px; color: white; font-weight: bold; font-size: 18px; transition: 0.6s ease; border-radius: 0 3px 3px 0; user-select: none;}
    .next {right: 0; border-radius: 3px 0 0 3px;}
    .prev:hover, .next:hover {background-color: rgba(0,0,0,0.8);}
    </style>
    <div class="slideshow-container">[% PhotoHTML %]</div>
    <script>
    var slideIndex = 1; showSlides(slideIndex);
    function plusSlides(n) { showSlides(slideIndex += n); }
    function showSlides(n) {
      var i; var slides = document.getElementsByClassName("mySlides");
      if (n > slides.length) {slideIndex = 1}
      if (n < 1) {slideIndex = slides.length}
      for (i = 0; i < slides.length; i++) { slides[i].style.display = "none"; }
      slides[slideIndex-1].style.display = "block";
    }
    </script>
    """
    layer.setMapTipTemplate(html)
    layer.triggerRepaint()


# Symbol Renderer (Categorized by Geologist with Star symbols for Favourites)
def apply_symbol_renderer(layer):
    """Apply symbols with stars for favourites (x/X) and circles for regular photos, colored by geologist."""
    from qgis.core import (
        QgsSymbol, QgsCategorizedSymbolRenderer, QgsRendererCategory,
        QgsSimpleMarkerSymbolLayer, QgsRuleBasedRenderer
    )
    from qgis.PyQt.QtGui import QColor

    # Get unique geologists
    unique_geologists = layer.uniqueValues(layer.fields().indexFromName('Geologist'))

    # Define colors for different geologists (you can expand this list)
    colors = [
        QColor(255, 0, 0),  # Red
        QColor(0, 255, 0),  # Green
        QColor(0, 0, 255),  # Blue
        QColor(255, 255, 0),  # Yellow
        QColor(255, 0, 255),  # Magenta
        QColor(0, 255, 255),  # Cyan
        QColor(255, 165, 0),  # Orange
        QColor(128, 0, 128),  # Purple
        QColor(255, 192, 203),  # Pink
        QColor(165, 42, 42),  # Brown
    ]

    # Create rule-based renderer
    root_rule = QgsRuleBasedRenderer.Rule(None)

    geologist_color_map = {}
    for i, geologist in enumerate(unique_geologists):
        dark_color = colors[i % len(colors)]
        # Create lighter version for non-favourites (increase lightness by 60%)
        light_color = QColor(dark_color)
        light_color = light_color.lighter(160)  # 160% = 60% lighter
        geologist_color_map[geologist] = {'dark': dark_color, 'light': light_color}

        # Rule for favourite photos (case-insensitive 'true') - use star symbol (darker, larger)
        favourite_filter = f'"Geologist" = \'{geologist}\' AND upper("Favourite") = \'TRUE\''
        star_symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        star_symbol.setSize(4.0)  # Larger for favourites
        star_symbol.setColor(dark_color)  # Darker color

        # Change symbol to star
        star_marker = QgsSimpleMarkerSymbolLayer()
        star_marker.setShape(QgsSimpleMarkerSymbolLayer.Star)
        star_marker.setSize(8.0)
        star_marker.setColor(dark_color)
        star_symbol.changeSymbolLayer(0, star_marker)

        star_rule = QgsRuleBasedRenderer.Rule(star_symbol)
        star_rule.setFilterExpression(favourite_filter)
        star_rule.setLabel(f'{geologist} (Favourite)')
        root_rule.appendChild(star_rule)

        # Rule for regular photos - use circle symbol (lighter, smaller)
        regular_filter = f'"Geologist" = \'{geologist}\' AND (upper("Favourite") != \'TRUE\' OR "Favourite" IS NULL)'
        circle_symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        circle_symbol.setSize(2.5)  # Slightly smaller for regular
        circle_symbol.setColor(light_color)  # Lighter color

        # Ensure it's a circle (default marker)
        circle_marker = QgsSimpleMarkerSymbolLayer()
        circle_marker.setShape(QgsSimpleMarkerSymbolLayer.Circle)
        circle_marker.setSize(2.5)
        circle_marker.setColor(light_color)
        circle_symbol.changeSymbolLayer(0, circle_marker)

        circle_rule = QgsRuleBasedRenderer.Rule(circle_symbol)
        circle_rule.setFilterExpression(regular_filter)
        circle_rule.setLabel(f'{geologist} (Regular)')
        root_rule.appendChild(circle_rule)

    # Apply the rule-based renderer
    renderer = QgsRuleBasedRenderer(root_rule)
    layer.setRenderer(renderer)
    layer.triggerRepaint()

    QgsMessageLog.logMessage(
        f"Applied star symbols for favourites (case-insensitive 'true') and circle symbols for regular photos across {len(unique_geologists)} geologists.", 'Linear Geoscience', Qgis.Info)


# Labeling
def apply_labels(layer):
    label_settings = QgsPalLayerSettings()
    label_settings.fieldName = 'PhotoCount'
    label_settings.placement = QgsPalLayerSettings.Placement.OverPoint
    label_format = label_settings.format()
    label_format.setSize(6)
    label_format.setColor(QColor('white'))
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