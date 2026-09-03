"""
QGIS-side tests for view3d: project terrain wiring, DEM candidacy and
3D render-quality settings.

Requires QGIS. Run from the plugin root:

    C:\\OSGeo4W\\bin\\python-qgis-ltr.bat -  <<'EOF'
    from qgis.core import QgsApplication
    app = QgsApplication([], False); app.initQgis()
    path = r"<repo>\\tests\\test_view3d_qgis.py"
    exec(compile(open(path, encoding="utf-8").read(), path, "exec"),
         {"__file__": path, "__name__": "__main__"})
    app.exitQgis()
    EOF

Do NOT run this file directly with python-qgis: without initQgis a
QgsProject.read() never returns (it spins resolving providers), so the
suite hangs at the round-trip section with no output. Use the wrapper.

Everything runs against a temp project + synthetic DEM; nothing in the
repo or the user's profile is touched. The 3D view itself needs the full
app (iface), so open_view is exercised manually — see the branch memory's
verification checklist.
"""

import os
import sys
import tempfile

import numpy as np

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from qgis.core import QgsProject, QgsRasterLayer  # noqa: E402

from view3d import detect, terrain, view  # noqa: E402
from z_filter.expression import (  # noqa: E402
    SCOPE, ENTRY_RASTERS, format_rasters)

_passed = 0
_failed = 0


def check(condition, label):
    global _passed, _failed
    if condition:
        _passed += 1
        print('  ok   {0}'.format(label))
    else:
        _failed += 1
        print('  FAIL {0}'.format(label))


def section(title):
    print('\n=== {0} ==='.format(title))


TMP = tempfile.mkdtemp(prefix='lgs_view3d_test_')


def build_dem(path, size=50):
    from osgeo import gdal, osr
    gdal.UseExceptions()
    ds = gdal.GetDriverByName('GTiff').Create(path, size, size, 1,
                                              gdal.GDT_Float32)
    ds.SetGeoTransform((500000, 10, 0, 7000000, 0, -10))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(28350)
    ds.SetProjection(srs.ExportToWkt())
    arr = np.fromfunction(lambda r, c: 100 + r + c, (size, size),
                          dtype=float)
    ds.GetRasterBand(1).WriteRaster(
        0, 0, size, size, arr.astype(np.float32).tobytes(),
        buf_type=gdal.GDT_Float32)
    ds.FlushCache()
    ds = None


section('project terrain provider')
project = QgsProject.instance()
project.clear()

dem_path = os.path.join(TMP, 'topo_dem.tif')
build_dem(dem_path)
dem = QgsRasterLayer(dem_path, 'topo_dem')
check(dem.isValid(), 'synthetic DEM loads')
project.addMapLayer(dem)

changed = terrain.ensure_project_terrain(dem, project)
check(changed, 'ensure_project_terrain reports a change')
provider = project.elevationProperties().terrainProvider()
check(provider is not None and provider.type() == 'raster',
      'provider type is raster')
check(provider.layer() is not None
      and provider.layer().id() == dem.id(), 'provider points at the DEM')
check(provider.scale() == 1.0 and provider.offset() == 0.0,
      'live project stays at true scale')
check(terrain.current_terrain_layer(project).id() == dem.id(),
      'current_terrain_layer round-trips')
check(terrain.ensure_project_terrain(dem, project) is False,
      'second call is a no-op')

section('DEM rows and preference ladder')
pit_path = os.path.join(TMP, 'stage2_shell.tif')
build_dem(pit_path)
pit = QgsRasterLayer(pit_path, 'stage2_shell')
project.addMapLayer(pit)

rows = terrain.dem_rows(project)
check(len(rows) == 2, 'two local rasters detected')
chosen, reason = detect.choose_dem(rows, terrain.pinned_dem_id(project))
check(chosen is None and reason == 'ambiguous',
      'two unclassified rasters are ambiguous')

pit.setCustomProperty(terrain.ROLE_PROPERTY, 'pit')
rows = terrain.dem_rows(project)
chosen, reason = detect.choose_dem(rows, None)
check(chosen is not None and chosen['id'] == pit.id()
      and reason == 'role', 'role stamp wins')

pit.setCustomProperty(terrain.ROLE_PROPERTY, '')
project.writeEntry(SCOPE, ENTRY_RASTERS, format_rasters(
    [{'id': pit.id(), 'name': pit.name(), 'elevation': 1180.0,
      'checked': True}]))
rows = terrain.dem_rows(project)
tied = [r for r in rows if r['tied']]
check(len(tied) == 1 and tied[0]['id'] == pit.id(),
      'Z-filter tie surfaces as pit signal')
project.removeEntry(SCOPE, ENTRY_RASTERS)

terrain.pin_dem_layer(dem, project)
chosen, reason = detect.choose_dem(terrain.dem_rows(project),
                                   terrain.pinned_dem_id(project))
check(chosen is not None and chosen['id'] == dem.id()
      and reason == 'pinned', 'pinned choice persists and wins')

section('imagery and derivatives are not terrain')
# The shape of a real pit folder: DEM + RGBA ortho + hillshade + slope.
# Only the DEM may be offered as terrain, and it must win outright.
ortho_path = os.path.join(TMP, 'FF_Pit_transparent_mosaic.tif')
build_dem(ortho_path)  # geometry only; band count is forced below
from osgeo import gdal  # noqa: E402
gdal.UseExceptions()
rgba = gdal.GetDriverByName('GTiff').Create(
    os.path.join(TMP, 'ortho_rgba.tif'), 20, 20, 4, gdal.GDT_Byte)
rgba.SetGeoTransform((500000, 10, 0, 7000000, 0, -10))
rgba = None
project.clear()
project.addMapLayer(QgsRasterLayer(dem_path, 'pit_ss_dem'))
project.addMapLayer(QgsRasterLayer(os.path.join(TMP, 'ortho_rgba.tif'),
                                   'FF_Pit_transparent_mosaic_group1'))
hill_path = os.path.join(TMP, 'pit_ss_dem_hillshade.tif')
build_dem(hill_path)
project.addMapLayer(QgsRasterLayer(hill_path, 'pit_ss_dem_hillshade'))

rows = terrain.dem_rows(project)
by_name = {r['name']: r for r in rows}
check(by_name['FF_Pit_transparent_mosaic_group1']['bands'] == 4,
      'band count read off the layer')
check(detect.is_dem_candidate(by_name['pit_ss_dem']),
      'the DEM is a candidate')
check(not detect.is_dem_candidate(
    by_name['FF_Pit_transparent_mosaic_group1']),
    'the 4-band ortho is rejected despite its pit-ish name')
check(not detect.is_dem_candidate(by_name['pit_ss_dem_hillshade']),
      'the hillshade is rejected')
chosen, reason = detect.choose_dem(rows, terrain.pinned_dem_id(project))
check(chosen is not None and chosen['name'] == 'pit_ss_dem',
      'the DEM wins outright ({0})'.format(reason))
project.clear()

section('quality settings')
# project.clear() deleted the layers above, so reload the DEM.
dem = QgsRasterLayer(dem_path, 'topo_dem')
project.addMapLayer(dem)
from qgis._3d import Qgs3DMapSettings  # noqa: E402


def read_quality(s):
    if hasattr(s, 'terrainSettings'):
        try:
            ts = s.terrainSettings()
            return (ts.mapTileResolution(), ts.maximumScreenError(),
                    ts.maximumGroundError())
        except Exception:
            pass
    return (s.mapTileResolution(), s.maxTerrainScreenError(),
            s.maxTerrainGroundError())


qs = Qgs3DMapSettings()
base_tile = read_quality(qs)[0]
check(base_tile == 512, 'QGIS still defaults to 512 px tiles')

view.apply_quality(qs, 'high', dem)
tile, screen, ground = read_quality(qs)
check(tile == 1024, 'high raises the drape texture to 1024 px')
check(screen < 3.0, 'high tightens the screen error ({0})'.format(screen))

qs2 = Qgs3DMapSettings()
view.apply_quality(qs2, 'ultra', dem)
check(read_quality(qs2)[0] == 2048, 'ultra reaches 2048 px')

# Ground error tracks the DEM pixel in BOTH directions: a mesh denser
# than the pixels renders each pixel as a flat-topped column close up
# (nearest-neighbour heightmap sampling - the 1-second-DEM blockiness).
px = view.dem_pixel_size(dem)
check(px is not None and abs(px - 10.0) < 0.01,
      'DEM pixel size read back ({0})'.format(px))
check(abs(read_quality(qs)[2] - 10.0) < 1e-6,
      'a coarse DEM coarsens the ground error to its pixel size')

# Terrain MESH resolution lives on the DEM terrain settings, so it is
# only reachable once DEM terrain is installed (4.x) — a bare settings
# object still carries FLAT terrain, which has no resolution at all.
def dem_settings(q):
    st = Qgs3DMapSettings()
    view._ensure_dem_terrain(st, dem, project)
    view.apply_quality(st, q, dem)
    return st


bare = Qgs3DMapSettings()
check(view.terrain_resolution_reachable(bare) is False,
      'flat terrain reports no mesh resolution')

with_dem = dem_settings('high')
if view.terrain_resolution_reachable(with_dem):
    check(with_dem.terrainSettings().resolution() == 64,
          'high raises the terrain mesh grid to 64 px')
    check(dem_settings('ultra').terrainSettings().resolution() == 128,
          'ultra reaches a 128 px terrain mesh grid')
    check(dem_settings('standard').terrainSettings().resolution() == 16,
          'standard leaves the QGIS 16 px mesh grid alone')
    check(with_dem.terrainSettings().mapTileResolution() == 1024,
          'drape and mesh resolution coexist')
else:
    print('  note terrain mesh resolution is not settable from Python on '
          'this QGIS (expected on 3.40); the panel says so')

section('framing must not touch the scene extent')
# Qgs3DMapSettings.setExtent() on a LIVE view recomputes the scene origin
# and slides the world out from under the camera -> empty view. open_view
# must therefore never call it; framing goes through the camera instead.
import inspect  # noqa: E402
src = inspect.getsource(view.open_view)
check('settings.setExtent' not in src,
      'open_view never calls setExtent on the 3D map settings')
# Aiming the 2D canvas before creation IS the supported way to frame a
# new view, so map_canvas.setExtent is expected and must stay.
check('map_canvas.setExtent' in src,
      'open_view frames a new view by aiming the 2D canvas first')
check(hasattr(view, 'frame_extent'), 'frame_extent exists')

frame_src = inspect.getsource(view.frame_extent)
check('cameraController' in frame_src,
      'frame_extent drives the camera controller')
check('setLookingAtMapPoint' in frame_src and 'setViewFromTop' in frame_src,
      'frame_extent covers both the 4.x and 3.40 camera APIs')

# Degenerate inputs must be refused, not passed to Qt.
from qgis.core import QgsRectangle  # noqa: E402


class _NoController:
    def cameraController(self):
        return None


check(view.frame_extent(_NoController(), QgsRectangle(0, 0, 10, 10))
      is False, 'no camera controller -> refuses')
check(view.frame_extent(_NoController(), None) is False,
      'no extent -> refuses')
check(view.frame_extent(_NoController(), QgsRectangle()) is False,
      'empty extent -> refuses')

section('the panel must never open a view by itself')
# run() used to auto-open the 3D view on every press of "View in 3D".
# With a crash inside QGIS's 3D creation on some setups (seen on 3.40),
# that meant pressing the feature button at all took QGIS down, with no
# way to decline. The view now opens ONLY from the Open 3D View button.
import inspect  # noqa: E402

from view3d import dialog as v3d_dialog  # noqa: E402

run_src = inspect.getsource(v3d_dialog.run)
check('panel = existing' in run_src,
      're-show path falls through instead of returning early')
check('find_lgs_canvas' in run_src,
      'run still reports when a view is already open')
check('_open_view' not in run_src,
      'run never opens a view — auto-open must stay dead')
check('QTimer.singleShot' not in run_src,
      'run schedules no deferred open either')
check('pushWarning' in run_src,
      'a previous crashed attempt is reported where it cannot be missed')

clicked_src = inspect.getsource(v3d_dialog.View3DPanel._open_clicked)
check('QTimer.singleShot' in clicked_src,
      'the explicit open stays deferred out of the click dispatch')

open_src = inspect.getsource(v3d_dialog.View3DPanel._open_view)
check('SETTING_OPENING' in open_src, 'the crash breadcrumb is still set')
check('finally' in open_src, 'and always dealt with')
check('REFRAME_TRIES' in open_src,
      'the breadcrumb outlives the deferred re-aim window: a crash in '
      'the settling scene must be caught, not cleared away in advance')
check('probe_scene=False' in open_src,
      'the automatic post-open log does not interrogate the fresh scene')
check('3D view open' in open_src,
      'success is stated, never left on "Opening..."')

section('terrain extent must be held to the DEM')
# QGIS sizes a new 3D scene from the PROJECT full extent, which a web
# basemap inflates to continental size. Terrain tiles are then sampled
# kilometres apart, land on the DEM's nodata and render as nothing.
# Measured on the real pit project: a 1745 x 2434 km scene for a
# 911 x 1015 m DEM.
from qgis.core import QgsReferencedRectangle, QgsRectangle  # noqa: E402

vs = project.viewSettings()
dem_extent = view.extent_in_project_crs(dem, project)

with view._TerrainExtentOverride(project, dem_extent, project.crs()):
    inside = vs.fullExtent()
    check(inside.width() < dem_extent.width() * 2,
          'scene extent is held near the DEM, not the project')
    check(inside.width() > dem_extent.width(),
          'a margin of ground is kept around the DEM')
check(vs.presetFullExtent().isNull() or vs.presetFullExtent().isEmpty(),
      'a project with no preset is left with none')

# A user's own preset must survive the round trip untouched.
mine = QgsReferencedRectangle(QgsRectangle(1, 2, 3, 4), project.crs())
vs.setPresetFullExtent(mine)
with view._TerrainExtentOverride(project, dem_extent, project.crs()):
    check(vs.fullExtent().width() > dem_extent.width() * 0.5,
          'our override wins while it is in force')
back = vs.presetFullExtent()
check(abs(back.xMinimum() - 1) < 1e-6 and abs(back.yMaximum() - 4) < 1e-6,
      "the user's own preset extent is restored exactly")

# A degenerate extent must be a no-op rather than an exception.
with view._TerrainExtentOverride(project, QgsRectangle(), project.crs()):
    pass
check(abs(vs.presetFullExtent().xMinimum() - 1) < 1e-6,
      'an empty extent leaves the project untouched')
vs.setPresetFullExtent(QgsReferencedRectangle())

open_src = inspect.getsource(view.open_view)
check('_TerrainExtentOverride' in open_src,
      'open_view constrains the extent while QGIS builds the view')

section('the camera must be aimed at the ground, close in')
# Left to itself QGIS parked the camera 101 km above a 1.2 km pit, so
# the pit was a sub-pixel dot in an apparently empty window. We now aim
# it ourselves for new views as well as reused ones.
mid = view.mid_elevation(dem)
check(90.0 < mid < 250.0,
      'mid_elevation reads the synthetic DEM range ({0:.1f})'.format(mid))
check(view.mid_elevation(None) == 0.0,
      'mid_elevation degrades to 0 rather than raising')

ext = view.extent_in_project_crs(dem, project)


class _RecordingController:
    def __init__(self):
        self.called = None

    def setLookingAtMapPoint(self, point, distance, pitch, yaw):
        self.called = (point.x(), point.y(), point.z(), distance, pitch)


class _RecordingCanvas:
    def __init__(self, controller):
        self._c = controller

    def cameraController(self):
        return self._c


rc = _RecordingController()
check(view.frame_extent(_RecordingCanvas(rc), ext, mid) is True,
      'frame_extent aims the camera')
x, y, z, dist, pitch = rc.called
check(abs(x - ext.center().x()) < 0.01 and abs(y - ext.center().y()) < 0.01,
      'aimed at the extent centre')
check(abs(z - mid) < 0.01, 'aimed at the ground, not at Z=0')
check(abs(dist - max(ext.width(), ext.height())) < 0.01,
      'distance is the larger extent dimension, not a scene-sized number')
check(pitch == 0.0, 'top-down')

open_src = inspect.getsource(view.open_view)
check('frame_extent' in open_src, 'open_view aims the camera itself')
check(open_src.index('apply_z_factor') < open_src.index('frame_extent'),
      'framing happens after the vertical scale is applied')

section('terrain must be built the way QGIS builds it')
# Hand-rolling a QgsDemTerrainSettings sets only the layer, so a project
# terrain provider carrying an offset or scale silently lost both.
from qgis.core import QgsRasterDemTerrainProvider  # noqa: E402

if hasattr(Qgs3DMapSettings(), 'setTerrainSettings'):
    prov = QgsRasterDemTerrainProvider()
    prov.setLayer(dem)
    prov.setOffset(12.0)
    prov.setScale(3.0)
    project.elevationProperties().setTerrainProvider(prov)
    st = Qgs3DMapSettings()
    st.setCrs(project.crs())
    view._ensure_dem_terrain(st, dem, project)
    ts = st.terrainSettings()
    check(type(ts).__name__ == 'QgsDemTerrainSettings',
          'DEM terrain installed')
    check(abs(ts.elevationOffset() - 12.0) < 1e-6,
          'a project terrain offset survives')
    check(abs(ts.verticalScale() - 3.0) < 1e-6,
          'a project terrain scale survives')
    # put the plain provider back for the rest of the run
    terrain.ensure_project_terrain(dem, project)
else:
    print('  note terrain settings are not reachable on this QGIS (3.40); '
          '_ensure_dem_terrain is a no-op there by design')

section('framing must be retried once the scene exists')
# On 4.x the Qt3D engine is not built until the view is first shown, so
# the first aim always misses scene.setViewFrom2DExtent. That is how the
# camera ended up 101 km up with a scene-sized distance.
check(hasattr(view, '_reframe_when_ready'),
      'a deferred re-aim exists')
open_src2 = inspect.getsource(view.open_view)
check('_reframe_when_ready' in open_src2,
      'open_view schedules the re-aim for a new view')
check(open_src2.index('frame_extent') < open_src2.index(
    '_reframe_when_ready'),
    'it aims once immediately, then again when the scene is ready')
check('scene_ready' in open_src2,
      'the re-aim is skipped when the scene already exists (3.40): the '
      'first aim went through it, and a second poke at a settling scene '
      'is a crash risk')

reframe_src = inspect.getsource(view._reframe_when_ready)
check('canvas.scene()' in reframe_src,
      'the retry waits on the scene, not on a fixed delay')
check('RuntimeError' in reframe_src,
      'a view closed while waiting does not raise')
check('remaining' in reframe_src, 'the retry gives up rather than looping')

section('terrain changes must wait for a quiet scene (3.40 crash)')
# On 3.40 every terrain-affecting setter deletes and rebuilds the
# terrain generator; a heightmap future still running inside the deleted
# generation fires QFutureWatcher::finished into freed memory — the
# access violation of 2026-09-03 (crash stack: QFutureWatcherBase::event
# -> terrain generator -> QObject::connectImpl). So terrain changes on a
# live 3.40 view go through view.apply_when_quiet, one per quiet scene.

open_src3 = inspect.getsource(view.open_view)
check('apply_when_quiet' in open_src3,
      'open_view routes 3.40 terrain config through the quiet queue')
check('_flat_quality_steps' in open_src3,
      'the 3.40 branch builds diff-steps, never calls the setters direct')
close_src = inspect.getsource(view.close_view)
check('_cancel_quiet_queue' in close_src,
      'closing the view abandons the queue instead of poking a dying '
      'scene')

q_src = inspect.getsource(v3d_dialog.View3DPanel._quality_changed)
check('request_quality' in q_src,
      'a live detail change goes through the version-aware request')
z_src = inspect.getsource(v3d_dialog.View3DPanel._z_changed)
check('request_z_factor' in z_src,
      'a live exaggeration change does too')

# Diff-only steps: a value already in place must NOT be re-set, because
# even a no-change set rebuilds the terrain.
fq = Qgs3DMapSettings()
check(view._flat_quality_steps(fq, 'standard', None) == [],
      'standard quality on default settings needs no terrain rebuilds')
steps = view._flat_quality_steps(fq, 'high', dem)
check(len(steps) == 3,
      'high quality on default settings changes tile, screen and '
      'ground error ({0} steps)'.format(len(steps)))
check(view._flat_z_steps(fq, 1.0) == [],
      'exaggeration 1.0 on default settings is a no-op')
zsteps = view._flat_z_steps(fq, 2.0)
check(len(zsteps) == 1, 'a real exaggeration is one step')
zsteps[0][2]()
check(abs(fq.terrainVerticalScale() - 2.0) < 1e-6,
      'the step applies the value')
check(view._flat_z_steps(fq, 2.0) == [],
      'and asking again is then a no-op')
check(view._flat_terrain_steps(fq, True) == [],
      'terrain already on is a no-op')
check(len(view._flat_terrain_steps(fq, False)) == 1,
      'turning terrain off is one step')


class _SceneLessCanvas:
    def scene(self):
        return None


applied = []
now = view.apply_when_quiet(_SceneLessCanvas(), [
    ('a', 'step a', lambda: applied.append('a')),
    ('b', 'step b', lambda: applied.append('b'))])
check(now is True and applied == ['a', 'b'],
      'with no scene to race, steps run immediately')


class _CountdownScene:
    """Busy for the first few polls, then quiet forever."""

    def __init__(self, busy_polls):
        self._left = busy_polls

    def totalPendingJobsCount(self):
        self._left -= 1
        return max(0, self._left)


class _FakeCanvas:
    def __init__(self, scene):
        self._scene = scene

    def scene(self):
        return self._scene


busy = _FakeCanvas(_CountdownScene(100000))
applied2 = []
now = view.apply_when_quiet(busy, [
    ('a', 'step a', lambda: applied2.append('a'))])
check(now is False and applied2 == [],
      'a busy scene defers the change instead of racing it')
check(view.quiet_queue_active(), 'the queue is live')
view.apply_when_quiet(busy, [
    ('a', 'step a2', lambda: applied2.append('a2'))])
check(view._quiet_state is not None
      and [s[0] for s in view._quiet_state['steps']] == ['a'],
      'a same-key request replaces the queued one, never duplicates')
view._cancel_quiet_queue()
check(not view.quiet_queue_active(), 'cancel stops the queue')

# End-to-end drain against a scene that goes quiet, on the real event
# loop, holding a crash-guard flag for the duration.
from qgis.core import QgsApplication, QgsSettings  # noqa: E402
import time  # noqa: E402

saved_pace = (view.QUIET_POLL_MS, view.QUIET_CONSECUTIVE,
              view.QUIET_TRIES)
view.QUIET_POLL_MS, view.QUIET_CONSECUTIVE, view.QUIET_TRIES = 5, 2, 400
guard = 'LGSTest/view3dQuietGuard'
order = []
try:
    qcanvas = _FakeCanvas(_CountdownScene(4))
    view.apply_when_quiet(qcanvas, [
        ('a', 'step a', lambda: order.append('a')),
        ('b', 'step b', lambda: order.append('b'))], guard_key=guard)
    check(bool(QgsSettings().value(guard, False, bool)),
          'the crash guard is held while the queue works')
    deadline = time.time() + 10
    while view.quiet_queue_active() and time.time() < deadline:
        QgsApplication.instance().processEvents()
        time.sleep(0.002)
    check(order == ['a', 'b'],
          'steps drain in order once the scene is quiet')
    check(not view.quiet_queue_active(), 'the queue retires itself')
    check(not QgsSettings().value(guard, False, bool),
          'and releases the crash guard')
finally:
    (view.QUIET_POLL_MS, view.QUIET_CONSECUTIVE,
     view.QUIET_TRIES) = saved_pace
    QgsSettings().remove(guard)
    view._cancel_quiet_queue()

section('diagnostics can see the 4.2 sky')
desc_src = inspect.getsource(view.describe)
check('backgroundSettings' in desc_src,
      'Diagnose reports the background settings, not just the colour')

dlg_src = inspect.getsource(v3d_dialog.View3DPanel._apply_mode)
check('mid_elevation' in dlg_src,
      'pit-mode reframing aims at the ground, not Z=0')

section('lighting')
qe = Qgs3DMapSettings()
check(qe.eyeDomeLightingEnabled() is False,
      'QGIS still ships with eye dome lighting off')
view.apply_lighting(qe, True)
check(qe.eyeDomeLightingEnabled() is True, 'apply_lighting turns EDL on')

# QGIS copies the 2D canvas colour, so a white-background project gets a
# white sky — and our pale cartography on it is invisible.
from qgis.PyQt.QtGui import QColor  # noqa: E402

qb = Qgs3DMapSettings()
qb.setBackgroundColor(QColor('#ffffff'))
view.apply_lighting(qb, True)
check(qb.backgroundColor().lightness() < 240,
      'a white background is replaced with something terrain shows against')
view.apply_lighting(qb, True, background='#101010')
check(qb.backgroundColor().name() == '#101010',
      'an explicit background is honoured')
view.apply_lighting(qb, True, background=None)
check(qb.backgroundColor().name() == '#101010',
      'background=None leaves the colour alone')
view.apply_lighting(qe, False)
check(qe.eyeDomeLightingEnabled() is False, 'apply_lighting turns EDL off')

qe2 = Qgs3DMapSettings()
view._ensure_dem_terrain(qe2, dem, project)
view.apply_quality(qe2, 'high', dem)
view.apply_lighting(qe2, True)
view.apply_z_factor(qe2, 2.0)
check(qe2.eyeDomeLightingEnabled() is True,
      'EDL survives the full open chain')
check(read_quality(qe2)[0] == 1024,
      'drape quality survives alongside EDL')

qs3 = Qgs3DMapSettings()
view.apply_quality(qs3, 'high', None)
check(abs(read_quality(qs3)[2] - 1.0) < 1e-6,
      'no DEM falls back to the default ground error')

# Quality must survive the rest of the chain (4.x replaces the terrain
# settings object in _ensure_dem_terrain, so order is load-bearing).
qs4 = Qgs3DMapSettings()
view._ensure_dem_terrain(qs4, dem, project)
view.apply_quality(qs4, 'high', dem)
view.apply_z_factor(qs4, 2.0)
check(read_quality(qs4)[0] == 1024, 'quality survives the full open chain')
check(abs(view.current_z_factor(qs4) - 2.0) < 1e-6,
      'z factor survives the full open chain')

section('injected terrain XML must round-trip through the QGIS reader')
# The exported .qgs gets its terrain provider from terrain_xml.py, but
# it is QGIS/QField's OWN reader that consumes it. If the injected shape
# drifts from what QgsProject.write() produces, the reader parses an
# empty provider and the tablet silently shows FLAT terrain (the
# 1-second-DEM field failure of 2026-09-02). So: inject, then read back
# with QgsProject and demand a resolved raster provider and a real
# height.
import xml.etree.ElementTree as ET
from qfield_export.core.terrain_xml import inject_terrain

# Standalone QgsProject instances, NOT QgsProject.instance(): earlier
# sections leave Qgs3DMapSettings objects wired to the shared project,
# and clearing it out from under a live terrain generator spins forever
# on 3.40 (found the hard way - this section hung the whole suite).
rt_dem_path = os.path.join(TMP, 'roundtrip_dem.tif')
build_dem(rt_dem_path)
rt_writer = QgsProject()
rt_dem = QgsRasterLayer(rt_dem_path, 'roundtrip_dem')
rt_writer.addMapLayer(rt_dem)
rt_dem_id = rt_dem.id()
rt_qgs = os.path.join(TMP, 'roundtrip.qgs')
rt_writer.write(rt_qgs)
rt_writer.clear()
del rt_writer, rt_dem

rt_tree = ET.parse(rt_qgs)
inject_terrain(rt_tree.getroot(), rt_dem_id, './roundtrip_dem.tif',
               dem_layer_name='roundtrip_dem', scale=1.5, offset=2.0)
rt_tree.write(rt_qgs, encoding='UTF-8', xml_declaration=True)

rt_reader = QgsProject()
check(rt_reader.read(rt_qgs), 'injected project reads back')
rt_prov = rt_reader.elevationProperties().terrainProvider()
check(rt_prov is not None and rt_prov.type() == 'raster',
      'reader sees a raster terrain provider (not flat)')
rt_layer = rt_prov.layer() if rt_prov and hasattr(rt_prov, 'layer') else None
check(rt_layer is not None and rt_layer.isValid(),
      'the DEM layer reference resolves')
check(rt_prov is not None and abs(rt_prov.scale() - 1.5) < 1e-6,
      'injected scale survives the reader')
check(rt_prov is not None and abs(rt_prov.offset() - 2.0) < 1e-6,
      'injected offset survives the reader')
if rt_layer is not None:
    centre = rt_layer.extent().center()
    rt_h = rt_prov.heightAt(centre.x(), centre.y())
    check(rt_h == rt_h and rt_h > 0,
          'terrain provider samples a real height ({0:.1f})'.format(rt_h))
else:
    check(False, 'terrain provider samples a real height')

project.clear()
print('\n{0} passed, {1} failed'.format(_passed, _failed))
if _failed:
    sys.exit(1)
