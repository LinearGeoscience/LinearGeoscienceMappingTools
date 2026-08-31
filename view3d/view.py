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
  - QGIS 3.40: the flat Qgs3DMapSettings setters (setTerrainVerticalScale,
    setMapTileResolution, ...).

Nothing here may call Qgs3DMapSettings.writeXml(): it SEGFAULTS on
3.40.9, taking QGIS with it. See _ensure_dem_terrain.
"""

from qgis.core import Qgis, QgsMessageLog, QgsProject

try:
    from . import terrain
except ImportError:
    from view3d import terrain

VIEW_NAME = "LGS 3D"

# Render quality. QGIS draws the 2D map into square terrain tiles and
# stretches each over its patch of ground, so the DRAPE sharpness is
# mapTileResolution (QGIS default 512 px per tile) and how eagerly those
# tiles subdivide is maxTerrainScreenError (default 3 px). At the
# defaults, pit-scale linework and contours arrive visibly smeared —
# there simply are not enough texture pixels per metre of bench.
#
# Terrain GEOMETRY detail is a separate number: the DEM terrain tile
# resolution, i.e. how many elevation samples make each tile's mesh
# (QGIS default 16 -> a 16x16 grid per tile). At 16 a bench crest gets
# averaged away no matter how good the DEM is. Reachable only on 4.x
# (QgsDemTerrainSettings.setResolution); on 3.40 the terrain generator
# is not exposed to Python at all — see terrain_resolution_reachable().
#
# drape tile px, screen error, terrain sample grid.
QUALITY_LEVELS = {
    'standard': (512, 3.0, 16),    # QGIS defaults
    'high': (1024, 1.5, 64),
    'ultra': (2048, 1.0, 128),
}
DEFAULT_QUALITY = 'high'

# Never let terrain geometry subdivide coarser than QGIS would by
# default; go finer only where the DEM actually holds finer data.
DEFAULT_GROUND_ERROR = 1.0

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


def dem_pixel_size(dem_layer):
    """Ground size of one DEM pixel in map units, or None."""
    try:
        x = abs(dem_layer.rasterUnitsPerPixelX())
        y = abs(dem_layer.rasterUnitsPerPixelY())
        size = max(x, y)
        return size if size > 0 else None
    except Exception:
        return None


def apply_quality(settings, quality=DEFAULT_QUALITY, dem_layer=None):
    """Set drape texture resolution and terrain subdivision.

    On 4.x these live on the terrain settings object; the old
    Qgs3DMapSettings setters still work but are deprecated, so prefer the
    new home when it exists.
    """
    tile_px, screen_error, terrain_res = QUALITY_LEVELS.get(
        quality, QUALITY_LEVELS[DEFAULT_QUALITY])
    ground_error = DEFAULT_GROUND_ERROR
    pixel = dem_pixel_size(dem_layer) if dem_layer is not None else None
    if pixel:
        # Subdividing past the DEM's own resolution only interpolates.
        ground_error = min(DEFAULT_GROUND_ERROR, pixel)

    if hasattr(settings, 'setTerrainSettings'):  # QGIS 4.x
        try:
            ts = settings.terrainSettings()
            ts = ts.clone() if hasattr(ts, 'clone') else ts
            ts.setMapTileResolution(tile_px)
            ts.setMaximumScreenError(screen_error)
            ts.setMaximumGroundError(ground_error)
            if hasattr(ts, 'setResolution'):
                ts.setResolution(terrain_res)
            settings.setTerrainSettings(ts)
            return
        except Exception as exc:
            _log(f"3D view: terrainSettings quality failed ({exc}); "
                 "falling back to legacy setters",
                 Qgis.MessageLevel.Warning)
    settings.setMapTileResolution(tile_px)
    settings.setMaxTerrainScreenError(screen_error)
    settings.setMaxTerrainGroundError(ground_error)


def terrain_resolution_reachable(settings):
    """Can we set the terrain mesh sample grid from Python?

    Only on 4.x. On 3.40 QgsDemTerrainGenerator is not wrapped and
    Qgs3DMapSettings.setTerrainGenerator is SIP_SKIP, so the 16 px
    default can only be raised by hand in 3D Configuration ▸ Terrain ▸
    Tile resolution.
    """
    if not hasattr(settings, 'terrainSettings'):
        return False
    try:
        return hasattr(settings.terrainSettings(), 'setResolution')
    except Exception:
        return False


def apply_lighting(settings, eye_dome=True):
    """Eye dome lighting: darkens creases and slope breaks.

    Off in QGIS by default, and without it a pale minimal basemap draped
    on terrain reads as a flat white sheet — the relief is rendered but
    invisible, because nothing shades it. QField enables the same effect
    on its own 3D view for exactly this reason.
    """
    try:
        settings.setEyeDomeLightingEnabled(bool(eye_dome))
    except Exception as exc:
        _log(f"3D view: eye dome lighting unavailable: {exc}",
             Qgis.MessageLevel.Warning)


def open_view(iface, dem_layer, z_factor=1.0, extent=None,
              terrain_enabled=True, quality=DEFAULT_QUALITY,
              eye_dome=True):
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

    # Order matters on 4.x: _ensure_dem_terrain may install a fresh
    # terrain-settings object, which would discard quality set before it.
    _ensure_dem_terrain(settings, dem_layer, project)
    apply_quality(settings, quality, dem_layer)
    apply_lighting(settings, eye_dome)
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
    """Make sure the view's terrain is the DEM.

    On 4.x we set it outright through the terrain-settings API.

    On 3.40 we deliberately do NOTHING, and rely on the app having called
    configureTerrainFromProject() when it created the view — which is why
    terrain.ensure_project_terrain() must run first. There is no safe way
    to check or correct it from Python on 3.40:

      * no terrain generator/settings class is exposed at all, and
      * Qgs3DMapSettings.writeXml() SEGFAULTS on 3.40.9 (verified: it
        crashes on a freshly constructed settings object, before any of
        our calls), so the obvious introspect-and-patch route takes the
        whole of QGIS down with it.

    The failure mode without a fallback is flat terrain, which is
    visible and harmless. Do not reintroduce an XML round-trip here.
    """
    if hasattr(settings, 'setTerrainSettings'):
        _ensure_dem_terrain_4x(settings, dem_layer)


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
