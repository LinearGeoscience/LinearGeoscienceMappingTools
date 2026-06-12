# script_adddomainlayer.py
# -----------------------------------------------------------
# A helper script that creates a memory polygon layer named
# 'Domain' with a single text attribute called 'Domain'.
# The CRS of the 'Domain' layer is set to match the project's CRS.
# -----------------------------------------------------------

from qgis.PyQt.QtCore import QVariant
try:
    from qgis.PyQt.QtCore import QMetaType
except ImportError:
    QMetaType = None
from qgis.core import (
    QgsField,
    QgsVectorLayer,
    QgsProject,
    Qgis,
    QgsMessageLog,
    QgsCoordinateReferenceSystem
)

def create_compatible_field(name, field_type):
    """Create QgsField with QGIS version compatibility"""
    try:
        # Try QGIS 3.34+ syntax first
        if QMetaType and hasattr(QMetaType, 'Type'):
            if field_type == 'string':
                return QgsField(name, QMetaType.Type.QString)
        # Fallback for older versions
        if field_type == 'string':
            return QgsField(name, QVariant.String)
    except Exception:
        # Final fallback to QGIS 3.4 syntax
        if field_type == 'string':
            return QgsField(name, QVariant.String)
    
    # Default fallback
    return QgsField(name, QVariant.String)


def create_domain_polygon_layer(iface):
    """
    Creates an in-memory polygon layer named 'Domain' with
    a single text field called 'Domain', sets its CRS to match
    the current project CRS, and adds it to the QGIS project.

    :param iface: QGIS interface object (from qgis.utils.iface)
    """
    try:
        # Inform the user that the layer creation has started
        iface.messageBar().pushMessage("Info", "Creating 'Domain' layer...", level=Qgis.Info)

        # 1) Retrieve the current project CRS
        project = QgsProject.instance()
        project_crs = project.crs()

        # Log the project's CRS
        QgsMessageLog.logMessage(f"Project CRS: {project_crs.authid()}", 'Linear Geoscience', Qgis.Info)
        iface.messageBar().pushMessage("Info", f"Project CRS: {project_crs.authid()}", level=Qgis.Info)

        # 2) Memory layer URI with dynamic CRS based on project CRS
        layer_uri = f"Polygon?crs={project_crs.authid()}"

        # 3) Create the memory layer
        layer = QgsVectorLayer(layer_uri, "Domain", "memory")
        if not layer.isValid():
            raise RuntimeError("Failed to create the in-memory 'Domain' layer.")

        # 4) Add the 'Domain' string field
        layer.dataProvider().addAttributes([
            create_compatible_field("Domain", 'string')
        ])
        layer.updateFields()

        # 5) Add the layer to the QGIS project
        QgsProject.instance().addMapLayer(layer)

        # Inform the user of successful creation
        iface.messageBar().pushMessage("Success", f"Layer '{layer.name()}' successfully added with CRS {project_crs.authid()}.", level=Qgis.Success)
        QgsMessageLog.logMessage(f"Layer '{layer.name()}' successfully added with CRS {project_crs.authid()}.", 'Linear Geoscience', Qgis.Info)

    except Exception as e:
        # Inform the user of any errors encountered
        error_msg = f"Failed to create 'Domain' layer: {e}"
        iface.messageBar().pushMessage("Error", error_msg, level=Qgis.Critical)
        QgsMessageLog.logMessage(error_msg, 'Linear Geoscience', Qgis.Warning)

def run(iface):
    """Entry point called from mainplugin.py."""
    create_domain_polygon_layer(iface)
