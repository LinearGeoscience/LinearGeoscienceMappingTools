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

from qgis.core import Qgis, QgsMessageLog, QgsProject, QgsRectangle

# Import the 3D module up front so SIP has the Qgs3DMapCanvas wrapper
# registered before anything hands us one back. Guarded: a QGIS built
# without 3D has no module, and that must not break importing this file.
try:
    import qgis._3d  # noqa: F401
    HAVE_3D = True
except ImportError:
    HAVE_3D = False

try:
    from . import terrain
except ImportError:
    from view3d import terrain

# QGIS names the view itself ("3D Map N") — see _create_canvas for why we
# no longer supply one.

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
    """Our 3D view if it is still open, else None.

    Identified by object identity against the live list, not by name: the
    view name belongs to the Qgs3DMapCanvasWidget, never to the canvas
    (canvas.objectName() is empty), so matching on it always failed and
    every click built another view.
    """
    global _open_canvas
    if _open_canvas is None:
        return None
    try:
        canvases = list(iface.mapCanvases3D())
    except Exception:
        canvases = []
    for canvas in canvases:
        try:
            if canvas is _open_canvas:
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

    Sets the project terrain provider, then lets QGIS build the view and
    drape/frame it exactly as its own menu action would, and only then
    applies our quality, lighting and vertical scale on top.

    `extent` frames the view (default: whatever the 2D canvas shows).
    Returns the Qgs3DMapCanvas.
    """
    global _open_canvas
    project = QgsProject.instance()
    terrain.ensure_project_terrain(dem_layer, project)

    canvas = find_lgs_canvas(iface)
    created = canvas is None
    if created:
        # QGIS frames a new 3D view on the 2D canvas extent as it builds
        # it, and that is the ONLY safe moment to choose the framing:
        # Qgs3DMapSettings.setExtent() afterwards recomputes the scene
        # origin and slides the world out from under the placed camera,
        # leaving an empty view. So aim the 2D canvas first, then put it
        # back — the 3D view has already taken its copy.
        restore_2d = None
        if extent is not None and not extent.isEmpty():
            try:
                map_canvas = iface.mapCanvas()
                restore_2d = map_canvas.extent()
                map_canvas.setExtent(extent)
            except Exception as exc:
                _log(f"3D view: could not aim the 2D canvas: {exc}",
                     Qgis.MessageLevel.Warning)
                restore_2d = None
        # Terrain is built over the PROJECT full extent, which a web
        # basemap inflates to continental size — see
        # _TerrainExtentOverride. Hold it to the DEM while QGIS builds.
        terrain_extent = extent_in_project_crs(dem_layer, project)
        try:
            with _TerrainExtentOverride(project, terrain_extent,
                                        project.crs()):
                canvas = _create_canvas(iface)
        finally:
            if restore_2d is not None:
                try:
                    iface.mapCanvas().setExtent(restore_2d)
                    iface.mapCanvas().refresh()
                except Exception:
                    pass
        if canvas is None:
            # QGIS refuses and shows its own warning when the project
            # extent is empty or non-finite.
            raise RuntimeError(
                "QGIS would not open a 3D view. This usually means the "
                "project extent is not valid — add or turn on a layer "
                "with real extent, then try again.")
        _open_canvas = canvas
    settings = _map_settings(canvas)
    if settings is None:
        raise RuntimeError("The 3D view opened without map settings.")

    if not created:
        # Refresh the drape for an already-open view; on a new one QGIS
        # has just set the layers itself (including the annotation layer).
        try:
            settings.setLayers(iface.mapCanvas().layers())
        except Exception as exc:
            _log(f"3D view: could not set draped layers: {exc}",
                 Qgis.MessageLevel.Warning)
        if extent is not None:
            frame_extent(canvas, extent)

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


TERRAIN_MARGIN = 0.15  # a little ground around the DEM, for context


class _TerrainExtentOverride:
    """Constrain the scene extent QGIS builds terrain over, for one call.

    QGIS sizes a new 3D scene from the PROJECT's full extent — which a web
    basemap or a regional raster stretches to continental size. Terrain is
    then a quadtree over that whole area, so the tiles around a pit get
    sampled kilometres apart, land on the DEM's nodata, and render as
    nothing: a correctly aimed camera over an empty world. (Measured on
    the Fingals project: a 1745 x 2434 km scene for a 911 x 1015 m DEM.)

    Terrain outside the DEM has no data anyway, so the DEM's own extent
    plus a margin is the honest scene size. Set as the project's preset
    full extent, which is what QGIS reads, and restored afterwards.
    """

    def __init__(self, project, extent, crs):
        self._project = project
        self._extent = extent
        self._crs = crs
        self._previous = None
        self._applied = False

    def __enter__(self):
        if self._extent is None or self._extent.isEmpty():
            return self
        try:
            from qgis.core import QgsReferencedRectangle
            settings = self._project.viewSettings()
            self._previous = QgsReferencedRectangle(
                settings.presetFullExtent())
            padded = QgsRectangle(self._extent)
            padded.grow(max(self._extent.width(),
                            self._extent.height()) * TERRAIN_MARGIN)
            settings.setPresetFullExtent(
                QgsReferencedRectangle(padded, self._crs))
            self._applied = True
        except Exception as exc:
            _log(f"3D view: could not constrain the scene extent: {exc}",
                 Qgis.MessageLevel.Warning)
        return self

    def __exit__(self, *_exc):
        if not self._applied:
            return False
        try:
            # An invalid previous preset means "no preset"; setting that
            # back is how QGIS itself clears one.
            self._project.viewSettings().setPresetFullExtent(self._previous)
        except Exception as exc:
            _log(f"3D view: could not restore the project full extent: "
                 f"{exc}", Qgis.MessageLevel.Warning)
        return False


def extent_in_project_crs(layer, project=None):
    """A layer's extent in the PROJECT's CRS.

    QgsMapLayer.extent() is in the LAYER's own CRS. Aiming the map canvas
    or the 3D camera with it unprojected puts the view in the wrong place
    whenever they differ — here the pit DEM is GDA94 / MGA51 while the
    mapping is GDA2020 / MGA51.
    """
    from qgis.core import QgsCoordinateTransform
    project = project or QgsProject.instance()
    extent = layer.extent()
    try:
        if layer.crs() == project.crs() or not layer.crs().isValid():
            return extent
        transform = QgsCoordinateTransform(layer.crs(), project.crs(),
                                           project)
        return transform.transformBoundingBox(extent)
    except Exception as exc:
        _log(f"3D view: extent reprojection failed, using raw extent: "
             f"{exc}", Qgis.MessageLevel.Warning)
        return extent


def frame_extent(canvas, extent):
    """Point an already-open view's camera at `extent`, top-down.

    Moves the CAMERA, never the scene extent — see open_view for why
    setExtent() after creation empties the view. QGIS itself frames with
    distance = the larger extent dimension.
    """
    if extent is None or extent.isEmpty():
        return False
    try:
        controller = canvas.cameraController()
    except Exception:
        controller = None
    if controller is None:
        return False
    centre = extent.center()
    distance = max(extent.width(), extent.height())
    try:
        from qgis.core import QgsVector3D
        # 4.x: takes MAP coordinates, so no origin arithmetic to get wrong.
        if hasattr(controller, 'setLookingAtMapPoint'):
            controller.setLookingAtMapPoint(
                QgsVector3D(centre.x(), centre.y(), 0.0), distance, 0.0,
                0.0)
            return True
        # 3.40: world coordinates, i.e. map coordinates less the origin.
        origin = canvas.mapSettings().origin()
        controller.setViewFromTop(centre.x() - origin.x(),
                                  centre.y() - origin.y(), distance)
        return True
    except Exception as exc:
        _log(f"3D view: could not aim the camera: {exc}",
             Qgis.MessageLevel.Warning)
        return False


def describe(iface, dem_layer=None):
    """Everything worth knowing about the open 3D view, as text.

    An empty 3D window looks the same whether the camera is in the wrong
    place, the terrain never built, or nothing is draped on it. This
    reports which, into the Linear Geoscience log panel.
    """
    project = QgsProject.instance()
    out = []

    def add(label, value):
        out.append("  {0:<26} {1}".format(label, value))

    out.append("=== View in 3D diagnostics ===")
    add("QGIS", Qgis.QGIS_VERSION)
    add("project CRS", project.crs().authid())
    canvas2d = iface.mapCanvas()
    add("2D canvas CRS", canvas2d.mapSettings().destinationCrs().authid())
    add("2D canvas extent", canvas2d.extent().toString(1))
    add("2D visible layers", len(canvas2d.layers()))

    provider = project.elevationProperties().terrainProvider()
    add("project terrain type", provider.type() if provider else "NONE")
    tlayer = terrain.current_terrain_layer(project)
    add("terrain layer", tlayer.name() if tlayer else "NONE")
    if tlayer is not None:
        add("terrain CRS", tlayer.crs().authid())
        add("terrain extent (own CRS)", tlayer.extent().toString(1))
        add("terrain extent (proj CRS)",
            extent_in_project_crs(tlayer, project).toString(1))
        add("terrain visible in 2D", tlayer in canvas2d.layers())

    canvas = find_lgs_canvas(iface)
    if canvas is None:
        try:
            others = len(list(iface.mapCanvases3D()))
        except Exception:
            others = "?"
        add("our 3D canvas", "NOT OPEN (3D views existing: {0})".format(
            others))
        return "\n".join(out)

    add("our 3D canvas", "open")
    settings = canvas.mapSettings()
    if settings is None:
        add("3D map settings", "NONE")
        return "\n".join(out)
    add("3D CRS", settings.crs().authid())
    try:
        add("3D extent", settings.extent().toString(1))
    except Exception:
        pass
    try:
        add("3D origin", settings.origin().toString())
    except Exception:
        pass
    add("3D layers draped", len(settings.layers()))
    add("terrain rendering", settings.terrainRenderingEnabled())
    add("vertical scale", current_z_factor(settings))
    add("eye dome lighting", settings.eyeDomeLightingEnabled())
    if hasattr(settings, 'terrainSettings'):
        ts = settings.terrainSettings()
        add("terrain settings class", type(ts).__name__)
        for attr in ('resolution', 'mapTileResolution', 'verticalScale'):
            if hasattr(ts, attr):
                add("  ts." + attr, getattr(ts, attr)())

    controller = canvas.cameraController()
    if controller is None:
        add("camera controller", "NONE")
    else:
        for attr in ('distance', 'pitch', 'yaw'):
            if hasattr(controller, attr):
                add("camera " + attr, getattr(controller, attr)())
        for attr in ('lookingAtMapPoint', 'lookingAtPoint'):
            if hasattr(controller, attr):
                try:
                    add("camera " + attr, getattr(controller, attr)()
                        .toString())
                except Exception:
                    pass

    scene = None
    try:
        scene = canvas.scene()
    except Exception:
        pass
    add("scene", "present" if scene is not None else "NONE")
    return "\n".join(out)


def log_diagnostics(iface, dem_layer=None):
    text = describe(iface, dem_layer)
    QgsMessageLog.logMessage(text, 'Linear Geoscience',
                             Qgis.MessageLevel.Info)
    return text


def close_view(iface):
    """Close our 3D view.

    QGIS closes these by view NAME, which it assigned and we never learn,
    so close the dock widget the canvas lives in instead.
    """
    global _open_canvas
    canvas = find_lgs_canvas(iface)
    if canvas is None:
        return False
    closed = False
    try:
        from qgis.PyQt.QtWidgets import QDockWidget
        parent = canvas.parent()
        hops = 0
        while parent is not None and hops < 8:
            if isinstance(parent, QDockWidget):
                parent.close()
                closed = True
                break
            parent = parent.parent()
            hops += 1
    except Exception as exc:
        _log(f"3D view: close by dock failed: {exc}",
             Qgis.MessageLevel.Warning)
    if not closed:
        try:
            canvas.close()
            closed = True
        except Exception:
            pass
    _open_canvas = None
    return closed


def _create_canvas(iface):
    """Create a 3D view exactly the way QGIS's own menu action does.

    Pass an EMPTY name on purpose. QGIS then picks "3D Map N", checking it
    against the project's registered view names. Supplying our own name
    took a different path: createNew3DMapCanvasDock() returns nullptr when
    a canvas of that name is already open, and the name uniquifier only
    consults the project's SAVED views, so a still-open unsaved "LGS 3D"
    would collide and hand back None.

    4.x takes (name, sceneMode); globe mode without an ellipsoid renders
    black (qgis#66931), so pass Local explicitly. 3.40 takes (name) only.
    """
    if not HAVE_3D:
        raise RuntimeError(
            "This QGIS was built without 3D support, so no 3D view can "
            "be opened.")
    try:
        return iface.createNewMapCanvas3D("", Qgis.SceneMode.Local)
    except (TypeError, AttributeError):
        return iface.createNewMapCanvas3D("")


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
