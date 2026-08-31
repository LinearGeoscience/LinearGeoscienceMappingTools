"""
QGIS-side tests for view3d: project terrain wiring and the 3.40 settings
XML patch helper.

Requires QGIS. Run from the plugin root:

    C:\\OSGeo4W\\bin\\python-qgis-ltr.bat -  <<'EOF'
    from qgis.core import QgsApplication
    app = QgsApplication([], False); app.initQgis()
    path = r"<repo>\\tests\\test_view3d_qgis.py"
    exec(compile(open(path, encoding="utf-8").read(), path, "exec"),
         {"__file__": path, "__name__": "__main__"})
    app.exitQgis()
    EOF

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
from qgis.PyQt.QtXml import QDomDocument  # noqa: E402

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

section('3.40 settings XML patch helper')
doc = QDomDocument()
elem = doc.createElement('qgis3d')
terrain_elem = doc.createElement('terrain')
terrain_elem.setAttribute('exaggeration', '1')
generator = doc.createElement('generator')
generator.setAttribute('type', 'flat')
terrain_elem.appendChild(generator)
elem.appendChild(terrain_elem)
doc.appendChild(elem)

check(view.patch_terrain_element(elem, 'dem_id_1') is True,
      'flat generator gets patched')
check(generator.attribute('type') == 'dem'
      and generator.attribute('layer') == 'dem_id_1',
      'patched to DEM with the layer id')
check(generator.attribute('resolution') != ''
      and generator.attribute('skirt-height') != '',
      'sane generator defaults filled in')
check(view.patch_terrain_element(elem, 'dem_id_1') is False,
      'already-correct generator is left alone')
check(view.patch_terrain_element(elem, 'dem_id_2') is True,
      'different DEM id re-patches')

no_terrain = doc.createElement('qgis3d')
check(view.patch_terrain_element(no_terrain, 'x') is False,
      'element without <terrain> is a no-op')

project.clear()
print('\n{0} passed, {1} failed'.format(_passed, _failed))
if _failed:
    sys.exit(1)
