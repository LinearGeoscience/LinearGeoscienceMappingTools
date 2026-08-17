"""
Z Filter — elevation-based level filtering for pit and underground mapping.

Public entry points:
    run_z_filter_panel(iface)      — open (or raise) the dock panel
    run_add_elevation_field(iface) — standalone Elevation-field injection
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDockWidget, QMessageBox


def run_z_filter_panel(iface):
    """Create and show the Z Filter panel (lazy singleton, photo_panel
    pattern). Returns the dock instance."""
    from .dockwidget import ZFilterDockWidget

    for dock in iface.mainWindow().findChildren(QDockWidget):
        if isinstance(dock, ZFilterDockWidget):
            dock.show()
            dock.raise_()
            dock.activateWindow()
            return dock

    panel = ZFilterDockWidget(iface)
    iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, panel)
    panel.show()
    panel.raise_()
    panel.activateWindow()
    return panel


def run_add_elevation_field(iface):
    """Standalone flow: add the Elevation field to the standard layers.

    Works on every project layer whose name matches a canonical LGS layer
    name (all copies are listed in the confirmation so nothing is touched
    silently). The panel's enable flow does the same for its own selection.
    """
    from qgis.core import QgsProject
    from . import field_setup
    from .expression import ELEVATION_FIELD, Z_LAYERS, is_canonical

    try:
        from ..layer_select import layer_display_name
    except ImportError:
        from layer_select import layer_display_name

    parent = iface.mainWindow()
    # is_canonical, not `in Z_LAYERS`: projects built from a pre-Aug-2026
    # template number Linework/Overlay the other way round and must still match.
    targets = [lyr for lyr in QgsProject.instance().mapLayers().values()
               if is_canonical(lyr.name())]
    if not targets:
        QMessageBox.warning(
            parent, "Add Elevation Field",
            "No standard mapping layers found in this project "
            "(expected: " + ", ".join(Z_LAYERS) + ").")
        return

    missing = field_setup.layers_missing_elevation(targets)
    if not missing:
        QMessageBox.information(
            parent, "Add Elevation Field",
            f"All standard layers already have the '{ELEVATION_FIELD}' field.")
        return

    names = "\n".join(f"  • {layer_display_name(lyr)}" for lyr in missing)
    answer = QMessageBox.question(
        parent, "Add Elevation Field",
        f"Add a numeric '{ELEVATION_FIELD}' field to these layers?\n\n{names}",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Yes)
    if answer != QMessageBox.StandardButton.Yes:
        return

    report = field_setup.ensure_elevation_fields(missing)
    lines = []
    if report['added']:
        lines.append("Added to:\n" +
                     "\n".join(f"  • {n}" for n in report['added']))
    for name, reason in report['skipped'] + report['errors']:
        lines.append(f"Skipped {name}: {reason}")
    if report['custom_form']:
        lines.append(
            "Note — these layers use a custom feature form; add the new "
            "field to the form manually:\n" +
            "\n".join(f"  • {n}" for n in report['custom_form']))
    QMessageBox.information(parent, "Add Elevation Field",
                            "\n\n".join(lines) or "Nothing to do.")
