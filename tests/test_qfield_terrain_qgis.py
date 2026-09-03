"""
QGIS-side tests for the QField terrain path: project terrain wiring, DEM
candidacy/preference ladder, and the exported-project terrain XML.

Requires QGIS. Run from the plugin root:

    C:\\OSGeo4W\\bin\\python-qgis-ltr.bat -  <<'EOF'
    from qgis.core import QgsApplication
    app = QgsApplication([], False); app.initQgis()
    path = r"<repo>\\tests\\test_qfield_terrain_qgis.py"
    exec(compile(open(path, encoding="utf-8").read(), path, "exec"),
         {"__file__": path, "__name__": "__main__"})
    app.exitQgis()
    EOF

Do NOT run this file directly with python-qgis: without initQgis a
QgsProject.read() never returns (it spins resolving providers), so the
suite hangs at the round-trip section with no output. Use the wrapper.

Everything runs against a temp project + synthetic DEM; nothing in the
repo or the user's profile is touched.
"""

import os
import sys
import tempfile

import numpy as np

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from qgis.core import QgsProject, QgsRasterLayer  # noqa: E402

from view3d import detect, terrain  # noqa: E402
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


TMP = tempfile.mkdtemp(prefix='lgs_qfield_terrain_test_')


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

# Standalone QgsProject instances, NOT QgsProject.instance(): clearing
# the shared project out from under live machinery has hung this suite
# before (found the hard way in the desktop-3D era).
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
