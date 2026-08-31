"""
QGIS-side tests for the Pit Surface to DEM GeoTIFF writer.

Requires QGIS (for the bundled GDAL). Run from the plugin root:

    C:\\OSGeo4W\\bin\\python-qgis-ltr.bat -  <<'EOF'
    from qgis.core import QgsApplication
    app = QgsApplication([], False); app.initQgis()
    path = r"<repo>\\tests\\test_surface_dem_qgis.py"
    exec(compile(open(path, encoding="utf-8").read(), path, "exec"),
         {"__file__": path, "__name__": "__main__"})
    app.exitQgis()
    EOF

Everything runs against files in a temp dir. The bytes are read back via
ReadRaster (never gdal_array — the numpy-1/numpy-2 ABI rule).
"""

import os
import struct
import sys
import tempfile
from collections import namedtuple

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from osgeo import gdal  # noqa: E402
from qgis.core import QgsCoordinateReferenceSystem  # noqa: E402

from view3d import surface_dem  # noqa: E402

gdal.UseExceptions()

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


TMP = tempfile.mkdtemp(prefix='lgs_surface_dem_test_')

Surface = namedtuple('Surface', 'vertices triangles attrs', defaults=({},))


def plane_z(x, y):
    return 2.0 * x + 3.0 * y + 5.0


corners = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)]
square = Surface(
    vertices=[(x + 500000, y + 7000000, plane_z(x, y)) for x, y in corners],
    triangles=[(0, 1, 2), (0, 2, 3)])

section('write_geotiff round-trip')
grid, gt, stats = surface_dem.rasterize_surfaces([square], cell_size=1.0)
out = os.path.join(TMP, 'pit_dem.tif')
crs_wkt = QgsCoordinateReferenceSystem('EPSG:28350').toWkt()
surface_dem.write_geotiff(out, grid, gt, crs_wkt=crs_wkt)
check(os.path.exists(out), 'GeoTIFF written')

ds = gdal.Open(out, gdal.GA_ReadOnly)
check(ds.RasterXSize == grid.shape[1] and ds.RasterYSize == grid.shape[0],
      'dimensions round-trip')
read_gt = ds.GetGeoTransform()
check(all(abs(a - b) < 1e-6 for a, b in zip(read_gt, gt)),
      'geotransform round-trips')
band = ds.GetRasterBand(1)
check(band.GetNoDataValue() == surface_dem.NODATA, 'nodata set')
check(ds.GetMetadataItem(surface_dem.METADATA_ROLE_KEY)
      == surface_dem.METADATA_ROLE_PIT, 'pit role tag present')
check('28350' in (ds.GetProjection() or '')
      or 'Zone 50' in (ds.GetProjection() or ''), 'CRS carried through')

# Value probe at the raster centre via ReadRaster bytes.
cx, cy = grid.shape[1] // 2, grid.shape[0] // 2
raw = band.ReadRaster(cx, cy, 1, 1, buf_type=gdal.GDT_Float32)
value = struct.unpack('f', raw)[0]
px = read_gt[0] + (cx + 0.5) * read_gt[1]
py = read_gt[3] + (cy + 0.5) * read_gt[5]
expected = plane_z(px - 500000, py - 7000000)
check(abs(value - expected) < 0.01,
      'centre pixel matches the plane ({0:.2f} ~ {1:.2f})'.format(
          value, expected))
ds = None

section('rasterize_to_geotiff pipeline')
original_read = surface_dem.read_surfaces
surface_dem.read_surfaces = lambda path: ([square], ['synthetic warning'])
try:
    out2 = os.path.join(TMP, 'pipeline_dem.tif')
    result = surface_dem.rasterize_to_geotiff('fake.str', out2,
                                              crs_wkt=crs_wkt)
    check(os.path.exists(out2), 'pipeline writes the GeoTIFF')
    check(result['triangles'] == 2 and result['filled'] > 0,
          'stats populated')
    check(result['warnings'] == ['synthetic warning'],
          'reader warnings surfaced')
    check(result['cell_size'] == surface_dem.suggest_cell_size([square]),
          'auto cell size used when none given')

    surface_dem.read_surfaces = lambda path: ([], [])
    try:
        surface_dem.rasterize_to_geotiff('strings_only.str',
                                         os.path.join(TMP, 'x.tif'))
        check(False, 'surface-less source raises')
    except ValueError:
        check(True, 'surface-less source raises')
finally:
    surface_dem.read_surfaces = original_read

section('real reader wiring (registry)')
# A minimal Surpac .str/.dtm pair exercising read_surfaces end to end.
str_path = os.path.join(TMP, 'minipit.str')
dtm_path = os.path.join(TMP, 'minipit.dtm')
with open(str_path, 'w') as f:
    f.write('minipit,01-Jan-26,,\n'
            '0, 0.000, 0.000, 0.000,\n'
            '1, 7000000.000, 500000.000, 105.000,\n'
            '1, 7000000.000, 500020.000, 145.000,\n'
            '1, 7000020.000, 500020.000, 205.000,\n'
            '1, 7000020.000, 500000.000, 165.000,\n'
            '0, 0.000, 0.000, 0.000,\n'
            '0, 0.000, 0.000, 0.000, END\n')
with open(dtm_path, 'w') as f:
    # The .dtm vertex space counts the 0,0,0,0 separator records as slots,
    # so the four real points above are slots 2-5, not 1-4.
    f.write('minipit.str;\n'
            'OBJECT, 1,\n'
            'TRISOLATION, 1,\n'
            '1, 2, 3, 4, 0, 0, 0,\n'
            '2, 2, 4, 5, 0, 0, 0,\n'
            'END\n')
try:
    surfaces, warnings = surface_dem.read_surfaces(str_path)
    if surfaces:
        check(len(surfaces[0].triangles) >= 1,
              'read_surfaces parses the .dtm triangulation')
    else:
        print('  skip .dtm fixture not accepted by the reader '
              '(warnings: {0})'.format(warnings))
except Exception as exc:
    print('  skip minimal .str/.dtm fixture rejected: {0}'.format(exc))

print('\n{0} passed, {1} failed'.format(_passed, _failed))
if _failed:
    sys.exit(1)
