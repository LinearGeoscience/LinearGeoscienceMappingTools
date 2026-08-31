"""
Underground mode: terrain off, imported mine survey data at true RL.

Desktop-only — QField's 3D view is a terrain heightfield and cannot show
below-surface workings. MineStrings/MineStations/MineSurveyText from the
mining importer carry real Z in their geometry (LineStringZ/PointZ), so
they render with absolute clamping; the four mapping layers stay draped
(they are 2D and only meaningful against a surface).

Z-less imports are the trap: sources without elevations get geometry
Z=0 with NULL Z_Min/Z_Max, which would plaster them at sea level. When
no Z filter is active we add a temporary "Z_Max" IS NOT NULL subset and
restore the original on exit; an active Z filter already excludes them.

Everything this mode touches is recorded and restored on exit: previous
subset strings and any pre-existing 3D renderers. State is held on the
controller object only — never persisted.
"""

from qgis.core import Qgis, QgsMessageLog, QgsProject

try:
    from . import view
except ImportError:
    from view3d import view

# GPKG layer names written by mining_import/schema.py.
MINE_LAYER_NAMES = ('MineStrings', 'MineStations', 'MineSurveyText')

Z_GUARD_SUBSET = '"Z_Max" IS NOT NULL'


def _log(msg, level=None):
    QgsMessageLog.logMessage(msg, 'Linear Geoscience',
                             level or Qgis.MessageLevel.Info)


def mine_layers(project=None):
    project = project or QgsProject.instance()
    layers = []
    for name in MINE_LAYER_NAMES:
        for layer in project.mapLayersByName(name):
            if layer.isValid():
                layers.append(layer)
    return layers


def has_mine_data(project=None):
    return bool(mine_layers(project))


def _absolute_symbol_for(layer):
    """A 3D symbol rendering the layer's own vertex Z, or None."""
    from qgis._3d import QgsLine3DSymbol, QgsPoint3DSymbol
    geom = layer.geometryType()
    if geom == Qgis.GeometryType.Line:
        symbol = QgsLine3DSymbol()
        symbol.setWidth(2)
        if hasattr(symbol, 'setRenderAsSimpleLines'):
            symbol.setRenderAsSimpleLines(True)
    elif geom == Qgis.GeometryType.Point:
        symbol = QgsPoint3DSymbol()
    else:
        return None
    symbol.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
    try:
        symbol.setAltitudeBinding(Qgis.AltitudeBinding.Vertex)
    except AttributeError:
        pass  # points have no binding
    return symbol


class UndergroundController:
    """Enter/exit underground mode against one open 3D view."""

    def __init__(self):
        self._saved = []  # [(layer_id, subset, renderer3D clone or None)]
        self.active = False

    def enter(self, settings, project=None):
        from qgis._3d import QgsVectorLayer3DRenderer
        if self.active:
            return
        project = project or QgsProject.instance()
        view.set_terrain_enabled(settings, False)
        for layer in mine_layers(project):
            previous_subset = layer.subsetString() or ""
            previous_renderer = None
            try:
                existing = layer.renderer3D()
                if existing is not None:
                    previous_renderer = existing.clone()
            except Exception:
                previous_renderer = None
            symbol = _absolute_symbol_for(layer)
            if symbol is None:
                continue
            if not previous_subset:
                # Keep Z-less imports (geometry Z forced to 0) out of the
                # scene; an existing subset (e.g. the Z filter) stays as
                # the user's own filtering.
                try:
                    layer.setSubsetString(Z_GUARD_SUBSET)
                except Exception as exc:
                    _log(f"Underground: subset guard failed on "
                         f"{layer.name()}: {exc}",
                         Qgis.MessageLevel.Warning)
            renderer = QgsVectorLayer3DRenderer(symbol)
            renderer.setLayer(layer)
            layer.setRenderer3D(renderer)
            self._saved.append((layer.id(), previous_subset,
                                previous_renderer))
        self.active = True

    def exit(self, settings, project=None):
        if not self.active:
            return
        project = project or QgsProject.instance()
        view.set_terrain_enabled(settings, True)
        for layer_id, subset, renderer in self._saved:
            layer = project.mapLayer(layer_id)
            if layer is None:
                continue
            try:
                if (layer.subsetString() or "") == Z_GUARD_SUBSET:
                    layer.setSubsetString(subset)
                layer.setRenderer3D(renderer)  # None clears ours
            except Exception as exc:
                _log(f"Underground: restore failed on {layer.name()}: "
                     f"{exc}", Qgis.MessageLevel.Warning)
        self._saved = []
        self.active = False
