"""
QGIS-side tests for the contour generation pipeline.

Requires QGIS. Run from the plugin root:

    C:\\OSGeo4W\\bin\\python-qgis-ltr.bat -  <<'EOF'
    from qgis.core import QgsApplication
    app = QgsApplication([], False); app.initQgis()
    path = r"<repo>\\tests\\test_contours_qgis.py"
    exec(compile(open(path, encoding="utf-8").read(), path, "exec"),
         {"__file__": path, "__name__": "__main__"})
    app.exitQgis()
    EOF

Everything runs against files created in a temp dir; nothing in the repo is
touched. The load-bearing case is smoothness: the pipeline's contours must
have a materially lower mean deflection angle than raw gdal.ContourGenerate
on the same DEM.
"""

import math
import os
import sqlite3
import sys
import tempfile

import numpy as np

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from qgis.core import (  # noqa: E402
    Qgis,
    QgsRuleBasedRenderer,
    QgsRuleBasedLabeling,
    QgsVectorLayer,
)

from contours import core, styling  # noqa: E402

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


TMP = tempfile.mkdtemp(prefix='lgs_contours_test_')
REAL_DEM = ('/vsizip/C:/Users/harry/Downloads/'
            '1_Second_DEM_Smoothed_2346798.zip/1_Second_DEM_Smoothed.tif')
REAL_DEM_ZIP = r'C:\Users\harry\Downloads\1_Second_DEM_Smoothed_2346798.zip'


def build_synthetic_dem(path):
    """200x200 Gaussian hill, 10 m pixels, EPSG:28350, nodata border strip."""
    from osgeo import gdal, osr
    gdal.UseExceptions()
    n = 200
    y, x = np.mgrid[0:n, 0:n]
    arr = 100.0 + 250.0 * np.exp(-(((x - 100) ** 2 + (y - 100) ** 2)
                                   / (2 * 45.0 ** 2)))
    # a pinch of deterministic pixel noise so raw contours are jagged
    rng = np.random.default_rng(42)
    arr += rng.normal(0.0, 1.2, arr.shape)
    arr = arr.astype(np.float32)
    nodata = np.float32(-9999.0)
    arr[:, :4] = nodata

    drv = gdal.GetDriverByName('GTiff')
    ds = drv.Create(path, n, n, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((392000.0, 10.0, 0.0, 6552000.0, 0.0, -10.0))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(28350)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(float(nodata))
    band.WriteRaster(0, 0, n, n, arr.tobytes())
    del band, ds


def mean_deflection_deg(lines):
    """Mean absolute deflection angle per interior vertex, in degrees."""
    total = 0.0
    count = 0
    for pts in lines:
        for i in range(1, len(pts) - 1):
            ax, ay = pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]
            bx, by = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
            na, nb = math.hypot(ax, ay), math.hypot(bx, by)
            if na < 1e-12 or nb < 1e-12:
                continue
            dot = max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb)))
            total += math.degrees(math.acos(dot))
            count += 1
    return total / count if count else 0.0


def raw_contour_lines(dem_path, levels, nodata):
    """gdal.ContourGenerate straight on the DEM, no smoothing anywhere."""
    from osgeo import gdal, ogr
    gdal.UseExceptions()
    src = gdal.Open(dem_path)
    mem = ogr.GetDriverByName('Memory').CreateDataSource('raw')
    lyr = mem.CreateLayer('raw', None, ogr.wkbLineString)
    lyr.CreateField(ogr.FieldDefn('ID', ogr.OFTInteger))
    lyr.CreateField(ogr.FieldDefn('elev', ogr.OFTReal))
    gdal.ContourGenerate(src.GetRasterBand(1), 0, 0, list(levels), 1,
                         nodata, lyr, 0, 1)
    lines = []
    for feat in lyr:
        geom = feat.GetGeometryRef()
        if geom is not None:
            lines.append([(p[0], p[1]) for p in geom.GetPoints()])
    return lines


def layer_lines(layer):
    lines = []
    for feat in layer.getFeatures():
        lines.append([(p.x(), p.y()) for p in feat.geometry().asPolyline()])
    return lines


section('suggest_intervals')
check(core.suggest_intervals(0, 254) == (5.0, 5), '254 m range -> 5 m / 5th')
# 30/0.5 is exactly the 60-minor target, so 0.5 is the smallest nice step
check(core.suggest_intervals(0, 30) == (0.5, 5), '30 m range -> 0.5 m / 5th')
check(core.suggest_intervals(0, 3000) == (50.0, 5), '3000 m range -> 50 m / 5th')
check(core.suggest_intervals(100, 100) == (10.0, 5), 'flat range -> sane fallback')
check(core.suggest_intervals(0, float('nan')) == (10.0, 5), 'nan range -> sane fallback')

section('synthetic DEM pipeline')
dem_path = os.path.join(TMP, 'hill.tif')
build_synthetic_dem(dem_path)
stats = core.raster_stats(dem_path)
check(abs(stats['pixel_x'] - 10.0) < 1e-9, 'pixel size read back')
check(not stats['is_geographic'], 'projected CRS detected')

out_gpkg = os.path.join(TMP, 'hill_contours.gpkg')
minor, major_every = core.suggest_intervals(stats['min'], stats['max'])
progress = []
result = core.generate_contours(
    dem_path, minor, major_every, 'medium', out_gpkg,
    progress_cb=lambda pct, msg=None: progress.append(pct))
check(os.path.exists(out_gpkg), 'gpkg written')
check(result['count'] > 0, 'contours generated ({0})'.format(result['count']))
check(progress and progress[-1] == 100, 'progress reached 100')

layer = QgsVectorLayer('{0}|layername={1}'.format(out_gpkg, result['layer']),
                       'contours', 'ogr')
check(layer.isValid(), 'layer loads')
check([f.name() for f in layer.fields()][1:3] == ['elev', 'type'],
      'fields elev/type present')

major_interval = minor * major_every
all_ok = True
type_ok = True
closed_ok = True
for feat in layer.getFeatures():
    elev = feat['elev']
    if abs(elev / minor - round(elev / minor)) > 1e-6:
        all_ok = False
    is_major = round(elev / minor) % major_every == 0
    if feat['type'] != ('major' if is_major else 'minor'):
        type_ok = False
    pts = feat.geometry().asPolyline()
    # any ring that came off ContourGenerate closed must survive closed
    if len(pts) >= 4:
        d_ends = math.hypot(pts[0].x() - pts[-1].x(), pts[0].y() - pts[-1].y())
        if 1e-9 < d_ends < 1e-6:
            closed_ok = False
check(all_ok, 'every elev is a multiple of the minor interval')
check(type_ok, 'major/minor typing matches elev % major interval')
check(closed_ok, 'closed contours stayed closed')

raw = raw_contour_lines(dem_path, result['levels'], stats['nodata'])
smooth_angle = mean_deflection_deg(layer_lines(layer))
raw_angle = mean_deflection_deg(raw)
print('  raw deflection {0:.2f} deg, pipeline {1:.2f} deg'.format(
    raw_angle, smooth_angle))
check(smooth_angle < 0.6 * raw_angle,
      'pipeline contours materially smoother than raw ContourGenerate')

section('re-run overwrites layer, not file')
result2 = core.generate_contours(dem_path, minor * 2, major_every, 'light',
                                 out_gpkg)
check(result2['count'] > 0, 're-run into same gpkg succeeds')
layer2 = QgsVectorLayer('{0}|layername=contours'.format(out_gpkg), 'c', 'ogr')
elevs = {f['elev'] for f in layer2.getFeatures()}
check(all(abs(e / (minor * 2) - round(e / (minor * 2))) < 1e-6 for e in elevs),
      'second run replaced the first layer contents')

section('styling')
styling.apply_contour_style(layer2, 'subtle_grey')
renderer = layer2.renderer()
check(isinstance(renderer, QgsRuleBasedRenderer), 'renderer is rule-based')
rules = renderer.rootRule().children()
check(len(rules) == 2, 'two renderer rules')
check({r.filterExpression() for r in rules} ==
      {'"type" = \'minor\'', '"type" = \'major\''}, 'rules filter on type')
labeling = layer2.labeling()
check(isinstance(labeling, QgsRuleBasedLabeling), 'labeling is rule-based')
label_rules = labeling.rootRule().children()
check(len(label_rules) == 1 and
      label_rules[0].filterExpression() == '"type" = \'major\'',
      'single label rule on majors')
lbl = label_rules[0].settings()
check(lbl.placement == Qgis.LabelPlacement.Curved, 'curved placement')
check(abs(lbl.repeatDistance - 150.0) < 1e-9, 'repeat distance 150 mm')
check(styling.persist_style(layer2, 'contours'), 'style saved to gpkg')
conn = sqlite3.connect(out_gpkg)
has_styles = conn.execute(
    "SELECT count(*) FROM sqlite_master WHERE name='layer_styles'"
).fetchone()[0]
conn.close()
check(has_styles == 1, 'layer_styles table present in gpkg')

section('real DEM (skipped if zip absent)')
if os.path.exists(REAL_DEM_ZIP):
    rstats = core.raster_stats(REAL_DEM)
    riv, rmaj = core.suggest_intervals(rstats['min'], rstats['max'])
    check((riv, rmaj) == (5.0, 5), 'real DEM suggests 5 m / every 5th')
    real_out = os.path.join(TMP, 'real_contours.gpkg')
    rres = core.generate_contours(REAL_DEM, riv, rmaj, 'medium', real_out)
    check(rres['count'] > 0, 'real DEM contours generated ({0})'.format(
        rres['count']))
    check(all(490 <= lv <= 745 for lv in rres['levels']),
          'levels inside the elevation range')
    rlayer = QgsVectorLayer('{0}|layername=contours'.format(real_out),
                            'c', 'ogr')
    check(rlayer.crs().authid() in ('EPSG:7850', 'EPSG:28350'),
          'CRS carried through ({0})'.format(rlayer.crs().authid()))
else:
    print('  skip real DEM zip not found')

print('\n{0} passed, {1} failed'.format(_passed, _failed))
if _failed:
    sys.exit(1)
