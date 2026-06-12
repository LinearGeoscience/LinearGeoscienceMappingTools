"""
QGIS-console verification script for per-sheet legend scanning.

Paste into the QGIS Python console (or run via Plugins → Python Console →
Show Editor) from the plugin directory.  Builds memory layers and checks
scan_layer_values / scan_sections_for_sheet / load_lookup_map behaviour:
spatial filtering (inside / outside / crossing features), CRS transforms,
and NULL/zero-code safety.  Prints PASS/FAIL per check.
"""

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
)

from LinearGeoscienceMappingTools.recode_workflow.legend_builder import (
    scan_layer_values, scan_sections_for_sheet, load_lookup_map,
)
from LinearGeoscienceMappingTools.recode_workflow.legend_config import (
    normalize_section,
)

results = []


def check(name, condition):
    results.append((name, condition))
    print(f"{'PASS' if condition else 'FAIL'}: {name}")


def square(x0, y0, size=10):
    return QgsGeometry.fromPolygonXY([[
        QgsPointXY(x0, y0), QgsPointXY(x0 + size, y0),
        QgsPointXY(x0 + size, y0 + size), QgsPointXY(x0, y0 + size),
        QgsPointXY(x0, y0)]])


# ── Data layer (EPSG:28350, three polygons) ──────────────────────────
data = QgsVectorLayer(
    "Polygon?crs=EPSG:28350&field=Mineral1:string&field=Mineral2:string"
    "&field=Type:string", "verify_data", "memory")
provider = data.dataProvider()

# Feature inside the sheet, one outside, one crossing the boundary
for geom, m1, m2, typ in [
        (square(0, 0), 'Qz', 'Ser', 'Granite'),       # inside sheet
        (square(100, 100), 'Ol', None, 'Basalt'),     # outside sheet
        (square(15, 0), 'Kf', '0', 'Granite')]:       # crosses boundary
    f = QgsFeature(data.fields())
    f.setGeometry(geom)
    f.setAttributes([m1, m2, typ])
    provider.addFeature(f)
data.updateExtents()
QgsProject.instance().addMapLayer(data, False)

# Sheet polygon covering x:0-20 (catches features 1 and 3, not 2)
sheet_geom = square(0, 0, 20)
sheet_crs = data.crs()

# ── scan_layer_values: unfiltered vs filtered ────────────────────────
all_vals = scan_layer_values(data, ['Mineral1', 'Mineral2'])
check("unfiltered scan finds all values (incl. '0')",
      all_vals == ['0', 'Kf', 'Ol', 'Qz', 'Ser'])

sheet_vals = scan_layer_values(data, ['Mineral1', 'Mineral2'],
                               filter_geom=sheet_geom)
check("sheet scan excludes outside feature, keeps crossing feature",
      sheet_vals == ['0', 'Kf', 'Qz', 'Ser'])

sub = scan_layer_values(data, ['Mineral1', 'Mineral2'],
                        filter_geom=sheet_geom, subdivide_by='Type')
check("subdivided sheet scan groups by Type",
      sub == {'Granite': ['0', 'Kf', 'Qz', 'Ser']})

# ── CRS transform: sheet geometry in EPSG:4326 ───────────────────────
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform
wgs = QgsCoordinateReferenceSystem('EPSG:4326')
to_wgs = QgsCoordinateTransform(sheet_crs, wgs, QgsProject.instance())
sheet_wgs = QgsGeometry(sheet_geom)
sheet_wgs.transform(to_wgs)
section = normalize_section({
    'id': 'crs-test', 'title': 'Minerals',
    'layer': {'id': data.id(), 'name': data.name()},
    'fields': ['Mineral1', 'Mineral2'], 'display': 'text'})
crs_results = scan_sections_for_sheet(
    QgsProject.instance(), [section],
    sheet_geom=sheet_wgs, sheet_crs=wgs)
check("scan_sections_for_sheet transforms sheet CRS to layer CRS",
      crs_results.get('crs-test') == ['0', 'Kf', 'Qz', 'Ser'])

# ── load_lookup_map: NULL and zero keys ──────────────────────────────
lookup = QgsVectorLayer(
    "None?field=Code:string&field=Description:string",
    "verify_lookup", "memory")
lp = lookup.dataProvider()
for code, desc in [('Qz', 'Quartz'), ('0', 'Zero code'), (None, 'No key')]:
    f = QgsFeature(lookup.fields())
    f.setAttributes([code, desc])
    lp.addFeature(f)
QgsProject.instance().addMapLayer(lookup, False)

lmap = load_lookup_map(lookup, 'Code', 'Description')
check("lookup keeps zero code, drops NULL key",
      lmap == {'Qz': 'Quartz', '0': 'Zero code'})

# ── Cleanup + summary ────────────────────────────────────────────────
QgsProject.instance().removeMapLayer(data.id())
QgsProject.instance().removeMapLayer(lookup.id())

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed."
      + (f"  FAILED: {failed}" if failed else ""))
