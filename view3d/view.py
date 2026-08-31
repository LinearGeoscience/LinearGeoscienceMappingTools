"""
Opening and driving the native QGIS 3D map view.

Approach (and why): a self-built Qgs3DMapCanvas cannot get DEM terrain on
QGIS 3.40 — the terrain-generator classes are not Python-exposed there.
The native view created through iface.createNewMapCanvas3D() gets its
terrain configured from the project's elevation properties by the app
itself (C++ configureTerrainFromProject), which maps the provider's
layer/offset/scale onto the view. So: set the project terrain provider
first (view3d/terrain.py), then create the native view.

API branching is by feature detection, never version strings:
  - QGIS 4.x: Qgs3DMapSettings.terrainSettings()/setTerrainSettings()
    (QgsDemTerrainSettings et al.)
  - QGIS 3.40: Qgs3DMapSettings.setTerrainVerticalScale() plus a
    writeXml/readXml verify-and-patch fallback should the app not have
    configured DEM terrain (app behaviour, not API contract).
"""

from qgis.core import Qgis, QgsMessageLog, QgsProject, QgsReadWriteContext
from qgis.PyQt.QtXml import QDomDocument

try:
    from . import terrain
except ImportError:
    from view3d import terrain

VIEW_NAME = "LGS 3D"

# The canvas we opened, so a second click focuses instead of duplicating.
# Qt owns the widget; treat this as a hint and re-validate on every use.
_open_canvas = None


def _log(msg, level=None):
    QgsMessageLog.logMessage(msg, 'Linear Geoscience',
                             level or Qgis.MessageLevel.Info)


def _map_settings(canvas):
    # Qgs3DMapCanvas.mapSettings() on both target versions.
    return canvas.mapSettings()


def find_lgs_canvas(iface):
    """The already-open LGS 3D view, or None."""
    global _open_canvas
    try:
        canvases = list(iface.mapCanvases3D())
    except Exception:
        canvases = []
    for canvas in canvases:
        try:
            if canvas is _open_canvas or canvas.objectName() == VIEW_NAME:
                return canvas
        except RuntimeError:  # wrapped C++ object deleted
            continue
    _open_canvas = None
    return None


def open_view(iface, dem_layer, z_factor=1.0, extent=None,
              terrain_enabled=True):
    """Open (or refocus) the LGS 3D view over dem_layer.

    Sets the project terrain provider, creates the native 3D view, drapes
    the 2D canvas layers, frames `extent` (default: current 2D extent)
    and applies the vertical scale. Returns the Qgs3DMapCanvas.
    """
    global _open_canvas
    project = QgsProject.instance()
    terrain.ensure_project_terrain(dem_layer, project)

    canvas = find_lgs_canvas(iface)
    created = canvas is None
    if created:
        canvas = _create_canvas(iface)
        _open_canvas = canvas
    settings = _map_settings(canvas)

    if extent is None:
        extent = iface.mapCanvas().extent()
    try:
        settings.setLayers(iface.mapCanvas().layers())
    except Exception as exc:
        _log(f"3D view: could not set draped layers: {exc}",
             Qgis.MessageLevel.Warning)
    if created:
        try:
            settings.setExtent(extent)
        except Exception as exc:
            _log(f"3D view: could not set extent: {exc}",
                 Qgis.MessageLevel.Warning)

    _ensure_dem_terrain(settings, dem_layer, project)
    apply_z_factor(settings, z_factor)
    set_terrain_enabled(settings, terrain_enabled)

    if not created:
        _focus(canvas)
    return canvas


def close_view(iface):
    global _open_canvas
    canvas = find_lgs_canvas(iface)
    if canvas is None:
        return False
    try:
        iface.closeMapCanvas3D(canvas.objectName() or VIEW_NAME)
    except Exception:
        try:
            canvas.close()
        except Exception:
            pass
    _open_canvas = None
    return True


def _create_canvas(iface):
    # 4.x takes (name, sceneMode); globe mode without an ellipsoid renders
    # black (qgis#66931), so pass Local explicitly. 3.40 takes (name).
    try:
        return iface.createNewMapCanvas3D(VIEW_NAME, Qgis.SceneMode.Local)
    except (TypeError, AttributeError):
        return iface.createNewMapCanvas3D(VIEW_NAME)


def _focus(canvas):
    for attr in ('requestActivate', 'raise_', 'show'):
        try:
            getattr(canvas, attr)()
            return
        except Exception:
            continue


# ---------------------------------------------------------- z / terrain

def apply_z_factor(settings, factor):
    """Live vertical exaggeration; 1.0 = true scale."""
    factor = max(0.1, float(factor))
    if hasattr(settings, 'setTerrainSettings'):  # QGIS 4.x path
        try:
            ts = settings.terrainSettings()
            ts = ts.clone() if hasattr(ts, 'clone') else ts
            ts.setVerticalScale(factor)
            settings.setTerrainSettings(ts)
            return
        except Exception as exc:
            _log(f"3D view: terrainSettings z-factor failed ({exc}); "
                 "falling back to legacy setter",
                 Qgis.MessageLevel.Warning)
    settings.setTerrainVerticalScale(factor)


def current_z_factor(settings):
    if hasattr(settings, 'terrainSettings'):
        try:
            return settings.terrainSettings().verticalScale()
        except Exception:
            pass
    return settings.terrainVerticalScale()


def set_terrain_enabled(settings, enabled):
    try:
        settings.setTerrainRenderingEnabled(bool(enabled))
    except Exception as exc:
        _log(f"3D view: terrain toggle failed: {exc}",
             Qgis.MessageLevel.Warning)


# --------------------------------------- 3.40 verify-and-patch fallback

def _ensure_dem_terrain(settings, dem_layer, project):
    """On 3.40 the app should have built DEM terrain from the project
    provider; verify via the settings XML and patch the DOM if it stayed
    flat. On 4.x the terrainSettings API is authoritative instead."""
    if hasattr(settings, 'setTerrainSettings'):
        _ensure_dem_terrain_4x(settings, dem_layer)
        return
    try:
        doc = QDomDocument()
        context = QgsReadWriteContext()
        elem = settings.writeXml(doc, context)
        if patch_terrain_element(elem, dem_layer.id()):
            settings.readXml(elem, context)
            if hasattr(settings, 'resolveReferences'):
                settings.resolveReferences(project)
            _log("3D view: patched settings XML to DEM terrain (3.40 "
                 "fallback)")
    except Exception as exc:
        _log(f"3D view: DEM terrain verify/patch failed: {exc}",
             Qgis.MessageLevel.Warning)


def _ensure_dem_terrain_4x(settings, dem_layer):
    try:
        ts = settings.terrainSettings()
        layer = ts.layer() if hasattr(ts, 'layer') else None
        if layer is not None and layer.id() == dem_layer.id():
            return
        from qgis._3d import QgsDemTerrainSettings
        dem = QgsDemTerrainSettings()
        dem.setLayer(dem_layer)
        settings.setTerrainSettings(dem)
    except Exception as exc:
        _log(f"3D view: 4.x DEM terrain setup failed: {exc}",
             Qgis.MessageLevel.Warning)


def patch_terrain_element(elem, dem_layer_id):
    """Point a <terrain><generator> DOM at the DEM layer if it isn't a
    DEM generator already. Returns True when a patch was applied.
    Split out (QDomElement in, QDomElement out) so the qgis-bound test
    can exercise it against a captured fragment."""
    terrain_elem = elem.firstChildElement('terrain')
    if terrain_elem.isNull():
        return False
    generator = terrain_elem.firstChildElement('generator')
    if generator.isNull():
        generator = elem.ownerDocument().createElement('generator')
        terrain_elem.appendChild(generator)
    if generator.attribute('type') == 'dem' and \
            generator.attribute('layer') == dem_layer_id:
        return False
    generator.setAttribute('type', 'dem')
    generator.setAttribute('layer', dem_layer_id)
    if not generator.hasAttribute('resolution'):
        generator.setAttribute('resolution', '16')
    if not generator.hasAttribute('skirt-height'):
        generator.setAttribute('skirt-height', '10')
    return True
