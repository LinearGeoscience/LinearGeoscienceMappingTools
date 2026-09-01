"""
QGIS-side tests for raster_optimise: real GDAL output, real overviews.

Requires QGIS. Run from the plugin root:

    C:\\OSGeo4W\\bin\\python-qgis-ltr.bat -  <<'EOF'
    from qgis.core import QgsApplication
    app = QgsApplication([], False); app.initQgis()
    path = r"<repo>\\tests\\test_raster_optimise_qgis.py"
    exec(compile(open(path, encoding="utf-8").read(), path, "exec"),
         {"__file__": path, "__name__": "__main__"})
    app.exitQgis()
    EOF

Everything runs against a synthetic raster in a temp dir. The real drone
ortho is used as well when it happens to be present, but is optional so
the suite runs anywhere.
"""

import os
import struct
import sys
import tempfile

import numpy as np

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from osgeo import gdal, osr  # noqa: E402

from raster_optimise import core  # noqa: E402

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


TMP = tempfile.mkdtemp(prefix='lgs_optimise_test_')
REAL_ORTHO = (r"C:\Users\harry\OneDrive\2 - Work\Model Earth\Projects\BC8"
              r"\Fingals\GISData\BasemapJune"
              r"\260606_FF_Pit_transparent_mosaic_group1.tif")


def build_rgba(path, size=1400):
    """An RGBA image with a transparent border, like a drone ortho."""
    ds = gdal.GetDriverByName('GTiff').Create(
        path, size, size, 4, gdal.GDT_Byte,
        options=['COMPRESS=LZW', 'TILED=YES'])
    ds.SetGeoTransform((394000, 0.1, 0, 6573000, 0, -0.1))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(28351)
    ds.SetProjection(srs.ExportToWkt())
    ramp = np.linspace(0, 255, size, dtype=np.uint8)
    for band in (1, 2, 3):
        arr = np.tile(ramp, (size, 1)) if band != 2 else np.tile(
            ramp.reshape(-1, 1), (1, size))
        ds.GetRasterBand(band).WriteRaster(
            0, 0, size, size, arr.astype(np.uint8).tobytes(),
            buf_type=gdal.GDT_Byte)
    alpha = np.full((size, size), 255, dtype=np.uint8)
    alpha[:80, :] = 0
    alpha[-80:, :] = 0
    alpha[:, :80] = 0
    alpha[:, -80:] = 0
    ds.GetRasterBand(4).WriteRaster(
        0, 0, size, size, alpha.tobytes(), buf_type=gdal.GDT_Byte)
    ds.FlushCache()
    ds = None


section('reading a raster')
src = os.path.join(TMP, 'synthetic_ortho.tif')
build_rgba(src)
info = core.raster_info(src)
check(info['width'] == 1400 and info['height'] == 1400, 'dimensions read')
check(info['bands'] == 4, 'band count read')
check(info['dtype'] == 'Byte', 'data type read')
check(info['overviews'] == 0, 'source has no overviews (that is the point)')
check(info['bytes'] > 0, 'file size read')

section('optimising, single file')
out_dir = os.path.join(TMP, 'out_single')
os.makedirs(out_dir)
res = core.optimise_raster(src, out_dir, profile='cog_jpeg_alpha',
                           tiling=False)
check(len(res['outputs']) == 1, 'one output when tiling is off')
check(res['rows'] == 1 and res['cols'] == 1, 'grid is 1x1')
out_path = res['outputs'][0]['path']
check(os.path.isfile(out_path), 'output written')
check(out_path.endswith('_qfield.tif'),
      'single output keeps the plain name (no _r01c01)')

ds = gdal.Open(out_path)
band = ds.GetRasterBand(1)
check(band.GetOverviewCount() > 0,
      'OVERVIEWS BUILT ({0} levels)'.format(band.GetOverviewCount()))
check(ds.RasterXSize == 1400 and ds.RasterYSize == 1400,
      'resolution unchanged - the whole point')
check(bool(ds.GetProjection()), 'CRS carried through')
src_ds = gdal.Open(src)
check(all(abs(a - b) < 1e-9 for a, b in
          zip(ds.GetGeoTransform(), src_ds.GetGeoTransform())),
      'geotransform preserved exactly')
src_ds = None
check(ds.GetMetadataItem(core.META_SOURCE) == os.path.basename(src),
      'provenance metadata stamped')
comp = (ds.GetMetadata('IMAGE_STRUCTURE') or {}).get('COMPRESSION', '')
check('JPEG' in comp.upper(), 'JPEG compression applied ({0})'.format(comp))

# Transparency must survive as a per-dataset mask, not be silently lost.
flags = band.GetMaskFlags()
check(bool(flags & gdal.GMF_PER_DATASET),
      'transparency kept as an internal mask')
mask = band.GetMaskBand()
corner = struct.unpack('B', mask.ReadRaster(5, 5, 1, 1,
                                            buf_type=gdal.GDT_Byte))[0]
centre = struct.unpack('B', mask.ReadRaster(700, 700, 1, 1,
                                            buf_type=gdal.GDT_Byte))[0]
check(corner == 0, 'the clear border is still transparent')
check(centre == 255, 'the middle is still opaque')
ds = None

section('dropping transparency writes three bands')
out_dir2 = os.path.join(TMP, 'out_rgb')
os.makedirs(out_dir2)
res2 = core.optimise_raster(src, out_dir2, profile='cog_jpeg', tiling=False)
ds = gdal.Open(res2['outputs'][0]['path'])
check(ds.RasterCount == 3, 'three bands, alpha dropped as asked')
ds = None

section('lossless profile keeps the pixels')
out_dir3 = os.path.join(TMP, 'out_lossless')
os.makedirs(out_dir3)
res3 = core.optimise_raster(src, out_dir3, profile='tiff_lzw', tiling=False)
ds = gdal.Open(res3['outputs'][0]['path'])
check(ds.GetRasterBand(1).GetOverviewCount() > 0,
      'plain GeoTIFF profile still gets overviews')
raw_out = ds.GetRasterBand(1).ReadRaster(100, 100, 8, 1,
                                         buf_type=gdal.GDT_Byte)
ds = None
sds = gdal.Open(src)
raw_src = sds.GetRasterBand(1).ReadRaster(100, 100, 8, 1,
                                          buf_type=gdal.GDT_Byte)
sds = None
check(raw_out == raw_src, 'lossless output is bit-identical to the source')

section('tiling')
out_dir4 = os.path.join(TMP, 'out_tiles')
os.makedirs(out_dir4)
res4 = core.optimise_raster(src, out_dir4, profile='tiff_lzw',
                            tile_mb=0.4, tiling=True)
tiles = res4['outputs']
check(len(tiles) > 1, 'a small budget produces tiles ({0})'.format(
    len(tiles)))
names = [t['name'] for t in tiles]
check(names == sorted(names), 'names sort into grid order')
check(all('_r' in n and 'c' in n for n in names), 'tiles are named r__c__')
check(len(set(names)) == len(names), 'tile names are unique')

# The tiles must cover the source exactly: no gap, no overlap.
total_pixels = 0
xs, ys, xe, ye = [], [], [], []
for t in tiles:
    tds = gdal.Open(t['path'])
    total_pixels += tds.RasterXSize * tds.RasterYSize
    gt = tds.GetGeoTransform()
    xs.append(gt[0])
    ys.append(gt[3])
    xe.append(gt[0] + gt[1] * tds.RasterXSize)
    ye.append(gt[3] + gt[5] * tds.RasterYSize)
    check_tag = tds.GetMetadataItem(core.META_TILE)
    tds = None
check(total_pixels == 1400 * 1400,
      'tiles cover every pixel exactly once ({0})'.format(total_pixels))
sds = gdal.Open(src)
sgt = sds.GetGeoTransform()
check(abs(min(xs) - sgt[0]) < 1e-6
      and abs(max(ys) - sgt[3]) < 1e-6
      and abs(max(xe) - (sgt[0] + sgt[1] * sds.RasterXSize)) < 1e-6
      and abs(min(ye) - (sgt[3] + sgt[5] * sds.RasterYSize)) < 1e-6,
      'the mosaic of tiles matches the source extent')
sds = None
check(check_tag is not None, 'tiles carry their grid index in metadata')
check('tiles' in res4['group_name'], 'a tiled run gets a group name')

section('cancellation')
try:
    from lgs_tasks import TaskCancelled
except ImportError:
    from LinearGeoscienceMappingTools.lgs_tasks import TaskCancelled

state = {'n': 0}


def cancel_after_a_moment(pct, msg=None):
    state['n'] += 1
    if state['n'] > 2:
        raise TaskCancelled()


out_dir5 = os.path.join(TMP, 'out_cancel')
os.makedirs(out_dir5)
try:
    core.optimise_raster(src, out_dir5, profile='tiff_lzw', tiling=False,
                         progress_cb=cancel_after_a_moment)
    check(False, 'cancelling actually stops the run')
except TaskCancelled:
    check(True, 'cancelling actually stops the run')
except Exception as exc:
    check(False, 'cancelling raised {0} instead'.format(type(exc).__name__))

section('the real drone ortho')
if os.path.isfile(REAL_ORTHO):
    real = core.raster_info(REAL_ORTHO)
    print('  source: {0}, {1}x{2}, {3} bands, {4} overviews'.format(
        core.human_mb(real['bytes']), real['width'], real['height'],
        real['bands'], real['overviews']))
    out_dir6 = os.path.join(TMP, 'out_real')
    os.makedirs(out_dir6)
    rres = core.optimise_raster(REAL_ORTHO, out_dir6,
                                profile='cog_jpeg_alpha')
    factor = rres['source_bytes'] / float(rres['output_bytes'])
    print('  {0} -> {1} ({2:.1f}x smaller) as {3} file(s)'.format(
        core.human_mb(rres['source_bytes']),
        core.human_mb(rres['output_bytes']), factor, len(rres['outputs'])))
    check(factor > 2.0, 'the real ortho shrinks materially')
    rds = gdal.Open(rres['outputs'][0]['path'])
    check(rds.GetRasterBand(1).GetOverviewCount() > 0,
          'the real ortho gains overviews')
    check(rds.RasterXSize == real['width'],
          'the real ortho keeps full resolution')
    rds = None
else:
    print('  skip real ortho not present on this machine')

print('\n{0} passed, {1} failed'.format(_passed, _failed))
if _failed:
    sys.exit(1)
