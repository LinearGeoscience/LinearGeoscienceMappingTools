# script_domainclassification.py
# -----------------------------------------------------------
# This PyQGIS script transfers values from the 'Domain' field of a polygon layer
# to the 'StructuralDomain' field of a point layer. For each point,
# the script checks if it lies within a polygon and, if so, copies the polygon's 'Domain'
# value to the corresponding point's 'StructuralDomain' field.
#
# Key Features:
# - Uses a GUI dialog for layer selection
# - Uses a spatial index for efficient spatial operations.
# - Automatically handles multiple points and polygons.
# - Commits updates directly to the point layer.
# -----------------------------------------------------------

from qgis.core import (
    QgsProject,
    QgsSpatialIndex,
    Qgis,
    QgsWkbTypes
)
from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QMessageBox
)

try:
    from .layer_select import layer_candidates, populate_layer_combo, combo_current_layer
except ImportError:
    from layer_select import layer_candidates, populate_layer_combo, combo_current_layer


class DomainTransferDialog(QDialog):
    """Dialog for selecting layers for domain transfer"""

    def __init__(self, iface, parent=None):
        """Initialize the dialog

        :param iface: QGIS interface object
        :param parent: Parent widget
        """
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Domain Transfer Tool")
        self.setup_ui()

    def setup_ui(self):
        """Create the dialog UI"""
        # Main layout
        layout = QVBoxLayout()

        # Polygon layer selection — prefer layers that have the 'Domain' field,
        # fall back to all polygon layers so the downstream field check still reports
        polygon_layout = QHBoxLayout()
        polygon_label = QLabel("Domain Polygon Layer:")
        self.polygon_combo = QComboBox()
        polygons = layer_candidates(geometry=QgsWkbTypes.PolygonGeometry,
                                    required_fields=['Domain'])
        if not polygons:
            polygons = layer_candidates(geometry=QgsWkbTypes.PolygonGeometry)
        populate_layer_combo(self.polygon_combo, polygons, target_name="Domain")
        polygon_layout.addWidget(polygon_label)
        polygon_layout.addWidget(self.polygon_combo)
        layout.addLayout(polygon_layout)

        # Point layer selection
        point_layout = QHBoxLayout()
        point_label = QLabel("Field Notebook Point Layer:")
        self.point_combo = QComboBox()
        points = layer_candidates(geometry=QgsWkbTypes.PointGeometry,
                                  required_fields=['StructuralDomain'])
        if not points:
            points = layer_candidates(geometry=QgsWkbTypes.PointGeometry)
        populate_layer_combo(self.point_combo, points, target_name="1 - FieldNotebook")
        point_layout.addWidget(point_label)
        point_layout.addWidget(self.point_combo)
        layout.addLayout(point_layout)

        # Button layout
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Cancel")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def get_selected_layers(self):
        """Get the selected layers from the combo boxes

        :return: Tuple of (polygon_layer, point_layer)
        """
        return combo_current_layer(self.polygon_combo), combo_current_layer(self.point_combo)


def transfer_domain_to_structural(iface):
    """
    Shows a dialog for layer selection and transfers 'Domain' values from
    selected polygon layer to 'StructuralDomain' in selected point layer.

    :param iface: QGIS interface object (from qgis.utils.iface)
    """
    # Show the layer selection dialog
    dialog = DomainTransferDialog(iface)
    result = dialog.exec()

    # If the dialog was cancelled, return
    if not result:
        iface.messageBar().pushMessage("Info", "Domain transfer cancelled.", level=Qgis.Info)
        return

    # Get the selected layers
    polygon_layer, point_layer = dialog.get_selected_layers()

    try:
        # Check if layers were selected
        if not polygon_layer:
            iface.messageBar().pushMessage("Error", "No polygon layer selected.", level=Qgis.Critical)
            return
        if not point_layer:
            iface.messageBar().pushMessage("Error", "No point layer selected.", level=Qgis.Critical)
            return

        iface.messageBar().pushMessage("Info",
                                       f"Using polygon layer: '{polygon_layer.name()}' and point layer: '{point_layer.name()}'",
                                       level=Qgis.Info)

        # Check if the layers are valid
        if not point_layer.isValid():
            iface.messageBar().pushMessage("Error", f"Point layer '{point_layer.name()}' is invalid.",
                                           level=Qgis.Critical)
            return
        if not polygon_layer.isValid():
            iface.messageBar().pushMessage("Error", f"Polygon layer '{polygon_layer.name()}' is invalid.",
                                           level=Qgis.Critical)
            return

        # Check if 'StructuralDomain' field exists in point layer
        if 'StructuralDomain' not in [field.name() for field in point_layer.fields()]:
            iface.messageBar().pushMessage("Error",
                                           f"'StructuralDomain' field not found in point layer '{point_layer.name()}'.",
                                           level=Qgis.Critical)
            return

        # Check if 'Domain' field exists in polygon layer
        if 'Domain' not in [field.name() for field in polygon_layer.fields()]:
            iface.messageBar().pushMessage("Error",
                                           f"'Domain' field not found in polygon layer '{polygon_layer.name()}'.",
                                           level=Qgis.Critical)
            return

        # Start an edit session for the point layer
        if not point_layer.isEditable():
            point_layer.startEditing()
            iface.messageBar().pushMessage("Info", f"Started editing session for '{point_layer.name()}'.",
                                           level=Qgis.Info)

        # Create a spatial index for the polygon layer for efficient spatial queries
        iface.messageBar().pushMessage("Info", "Creating spatial index for polygon layer...", level=Qgis.Info)
        polygon_index = QgsSpatialIndex(polygon_layer.getFeatures())
        iface.messageBar().pushMessage("Info", "Spatial index created.", level=Qgis.Info)

        # Inform the user that the transfer is starting
        iface.messageBar().pushMessage("Info", "Starting Domain to StructuralDomain transfer...", level=Qgis.Info)

        # Iterate through each point feature
        total_points = point_layer.featureCount()
        iface.messageBar().pushMessage("Info", f"Processing {total_points} point features...", level=Qgis.Info)

        processed_points = 0
        updated_points = 0

        for point_feature in point_layer.getFeatures():
            processed_points += 1
            point_geom = point_feature.geometry()

            # Get candidate polygons from the spatial index
            candidate_ids = polygon_index.intersects(point_geom.boundingBox())

            # Check which polygon contains the point
            for polygon_feature_id in candidate_ids:
                polygon_feature = polygon_layer.getFeature(polygon_feature_id)
                polygon_geom = polygon_feature.geometry()

                if polygon_geom.contains(point_geom):
                    # Get the 'Domain' value from the polygon
                    domain_value = polygon_feature['Domain']

                    # Update the point feature's 'StructuralDomain' field
                    point_feature['StructuralDomain'] = domain_value

                    # Commit the change to the point layer
                    point_layer.updateFeature(point_feature)
                    updated_points += 1
                    break  # Exit after finding the first containing polygon

            # Optionally, provide periodic updates
            if processed_points % 100 == 0:
                iface.messageBar().pushMessage("Info", f"Processed {processed_points}/{total_points} points...",
                                               level=Qgis.Info)

        # Save the edits and commit
        iface.messageBar().pushMessage("Info", "Saving changes to point layer...", level=Qgis.Info)
        if point_layer.commitChanges():
            iface.messageBar().pushMessage("Success",
                                           f"StructuralDomain field updated successfully! Updated {updated_points} points.",
                                           level=Qgis.Success)
        else:
            iface.messageBar().pushMessage("Error", "Failed to commit changes to the point layer.", level=Qgis.Critical)

    except Exception as e:
        iface.messageBar().pushMessage("Error", f"An unexpected error occurred: {e}", level=Qgis.Critical)
        # If we're in an edit session, roll back changes
        if point_layer and point_layer.isEditable():
            point_layer.rollBack()
            iface.messageBar().pushMessage("Info", "Changes rolled back due to error.", level=Qgis.Info)


def run(iface):
    """Entry point called from mainplugin.py."""
    transfer_domain_to_structural(iface)