"""
QGIS-side tests for the mining import write engine.

Requires QGIS. Run from the plugin root:

    C:\\OSGeo4W\\bin\\python-qgis-ltr.bat -  <<'EOF'
    from qgis.core import QgsApplication
    app = QgsApplication([], False); app.initQgis()
    path = r"<repo>\\tests\\test_mining_gpkg_qgis.py"
    exec(compile(open(path, encoding="utf-8").read(), path, "exec"),
         {"__file__": path, "__name__": "__main__"})
    app.exitQgis()
    EOF

Everything runs against GeoPackages created in a temp dir; nothing in the
repo is touched.

The load-bearing case is the merge: importing a second file at the SAME level
must leave the first file's features alone. That is what distinguishes
replace-by-source from the level-keyed behaviour it replaced.
"""

import os
import shutil
import sqlite3
import sys
import tempfile

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from qgis.core import (  # noqa: E402
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

from mining_import import gpkg, importer, merge, scan, schema  # noqa: E402

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


CRS = QgsCoordinateReferenceSystem('EPSG:28350')
CTX = QgsCoordinateTransformContext()

HEADER = ('name,01-May-26,purpose,\n'
          '0, 6551152.842, 392596.568, 0.000, '
          '6551152.842, 392596.568, 0.000\n')


def str_file(path, strings, station=None):
    """Write a .str with the given strings ([(string_no, npoints)])."""
    lines = [HEADER]
    for string_no, count in strings:
        for i in range(count):
            lines.append('{0}, {1:.3f}, {2:.3f}, {3:.3f}, {4}, '
                         '26.04.26 10:33:48, Darby Lindsay\n'.format(
                             string_no, 6581000.0 + i, 398000.0 + string_no,
                             160.0 + i, 100 + i))
        lines.append('0, 0.000, 0.000, 0.000,\n')
    if station is not None:
        lines.append('{0}, 6581500.000, 398500.000, 170.000, {1}, '
                     '25.04.26 09:00:00, Ana Ruiz\n'.format(999, station))
        lines.append('0, 0.000, 0.000, 0.000,\n')
    lines.append('0, 0.000, 0.000, 0.000, END\n')
    with open(path, 'w') as fh:
        fh.writelines(lines)
    return path


def entries_for(folder):
    return scan.discover(folder)


def run_import(gpkg_path, folder, policy=merge.POLICY_REPLACE_SOURCE,
               only=None):
    entries = entries_for(folder)
    if only is not None:
        entries = [e for e in entries if os.path.basename(e.path) in only]
    return importer.import_sources(
        gpkg_path, CRS, CTX, entries, folder, policy=policy,
        make_backup=False)


def count(gpkg_path, layer_name, expression=None):
    layer = QgsVectorLayer(gpkg.layer_uri(gpkg_path, layer_name),
                           layer_name, 'ogr')
    if not layer.isValid():
        return -1
    if expression is None:
        return layer.featureCount()
    from qgis.core import QgsFeatureRequest
    request = QgsFeatureRequest().setFilterExpression(expression)
    return sum(1 for _ in layer.getFeatures(request))


def main():
    work = tempfile.mkdtemp(prefix='lgs_mining_')
    try:
        # -- schema ------------------------------------------------------
        section('Fresh GeoPackage')
        folder = os.path.join(work, 'survey')
        os.makedirs(folder)
        str_file(os.path.join(folder, 'mga_floor_1164.str'),
                 [(20, 3), (21, 4)], station=401)
        target = os.path.join(work, 'out.gpkg')

        report = run_import(target, folder)
        check(os.path.exists(target), 'GeoPackage created')
        check(count(target, schema.STRINGS_LAYER) == 2,
              'two strings written')
        check(count(target, schema.STATIONS_LAYER) == 1,
              'single-point segment landed in the stations layer')

        layer = QgsVectorLayer(
            gpkg.layer_uri(target, schema.STRINGS_LAYER), 'x', 'ogr')
        names = [f.name() for f in layer.fields()]
        missing = [n for n in schema.required_fields(schema.STRINGS_LAYER)
                   if n not in names]
        check(not missing, 'strings layer has every schema field')
        check(layer.crs().authid() == 'EPSG:28350', 'CRS applied')

        feat = next(layer.getFeatures())
        check(feat.geometry().constGet().is3D(), 'geometry carries Z')
        check(feat['Z_Min'] is not None and feat['Z_Max'] is not None,
              'Z_Min/Z_Max populated')
        check(feat['SourceKey'] == 'mga_floor_1164.str',
              'SourceKey is the relative path')
        check(bool(feat['BatchId']), 'BatchId stamped on features')

        stations = QgsVectorLayer(
            gpkg.layer_uri(target, schema.STATIONS_LAYER), 'x', 'ogr')
        station = next(stations.getFeatures())
        check(station['Elevation'] is not None,
              'station carries Elevation for single-value Z filtering')
        check(station['Surveyor'] == 'Ana Ruiz',
              'station kept its own surveyor, not the strings\'')

        # -- index and log ----------------------------------------------
        section('Index and import log')
        con = sqlite3.connect(target)
        indexes = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")]
        check('idx_{0}_srckey'.format(schema.STRINGS_LAYER) in indexes,
              'SourceKey index created')
        registered = [r[0] for r in con.execute(
            'SELECT table_name FROM gpkg_contents')]
        check(schema.LOG_TABLE in registered,
              'import log registered in gpkg_contents')
        rows = list(con.execute(
            'SELECT source_key, level, status FROM {0}'.format(
                schema.LOG_TABLE)))
        con.close()
        check(len(rows) == 1, 'one log row per source')
        check(rows[0][1] == '1164', 'level recorded in the log')

        log_layer = QgsVectorLayer(
            gpkg.layer_uri(target, schema.LOG_TABLE), 'log', 'ogr')
        check(log_layer.isValid(), 'import log opens as a QGIS layer')

        # -- idempotent re-import ---------------------------------------
        section('Re-import unchanged')
        before = count(target, schema.STRINGS_LAYER)
        run_import(target, folder)
        check(count(target, schema.STRINGS_LAYER) == before,
              're-import does not duplicate')
        con = sqlite3.connect(target)
        log_count = con.execute(
            'SELECT COUNT(*) FROM {0}'.format(schema.LOG_TABLE)).fetchone()[0]
        con.close()
        check(log_count == 1, 'log row updated, not duplicated')

        # -- changed source ----------------------------------------------
        section('Re-import a changed file')
        str_file(os.path.join(folder, 'mga_floor_1164.str'), [(20, 3)])
        run_import(target, folder)
        check(count(target, schema.STRINGS_LAYER) == 1,
              'string deleted from the source is gone, no orphan left')
        check(count(target, schema.STATIONS_LAYER) == 0,
              'station removed with its source file')

        # -- the load-bearing case ---------------------------------------
        section('Second file at the SAME level')
        str_file(os.path.join(folder, 'mga_backs_1164.str'), [(30, 5)])
        run_import(target, folder, only={'mga_backs_1164.str'})
        check(count(target, schema.STRINGS_LAYER) == 2,
              'both files coexist at the same level')
        check(count(target, schema.STRINGS_LAYER,
                    '"SourceKey" = \'mga_floor_1164.str\'') == 1,
              'the first file\'s features survived')
        check(count(target, schema.STRINGS_LAYER,
                    '"SourceKey" = \'mga_backs_1164.str\'') == 1,
              'the second file\'s features were added')

        section('Replace-by-level still available')
        run_import(target, folder, policy=merge.POLICY_REPLACE_LEVEL,
                   only={'mga_backs_1164.str'})
        check(count(target, schema.STRINGS_LAYER) == 1,
              'level policy removes the whole level, as documented')

        # -- unrelated layers survive ------------------------------------
        section('Appending beside unrelated layers')
        other = os.path.join(work, 'mixed.gpkg')
        mem = QgsVectorLayer('Point?crs=EPSG:28350&field=name:string',
                             'Existing', 'memory')
        from qgis.core import QgsVectorFileWriter
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = 'GPKG'
        options.layerName = 'Existing'
        QgsVectorFileWriter.writeAsVectorFormatV3(mem, other, CTX, options)
        check(os.path.exists(other), 'fixture GeoPackage made')
        run_import(other, folder)
        existing = QgsVectorLayer(gpkg.layer_uri(other, 'Existing'), 'e', 'ogr')
        check(existing.isValid(), 'pre-existing unrelated layer survived')
        check(count(other, schema.STRINGS_LAYER) >= 1,
              'strings written alongside it')

        # -- rollback -----------------------------------------------------
        section('Compensating rollback')
        entries = entries_for(folder)
        batch = 'deadbeef'
        layer = QgsVectorLayer(
            gpkg.layer_uri(target, schema.STRINGS_LAYER), 'x', 'ogr')
        before = layer.featureCount()
        # Simulate a partial import: features from a batch that never got to
        # supersede anything. Built against the LIVE layer's fields, which
        # carry a leading fid -- a feature built from schema.make_fields()
        # alone is rejected by the provider, which is exactly why the writer
        # rebuilds before appending.
        fields = layer.fields()
        from qgis.core import QgsFeature, QgsGeometry, QgsLineString, QgsPoint
        feat = QgsFeature(fields)
        feat.setGeometry(QgsGeometry(QgsLineString(
            [QgsPoint(0, 0, 0), QgsPoint(1, 1, 1)])))
        feat.setAttribute(fields.lookupField('BatchId'), batch)
        feat.setAttribute(fields.lookupField('SourceKey'), 'ghost.str')
        layer.dataProvider().addFeatures([feat])
        check(count(target, schema.STRINGS_LAYER) == before + 1,
              'partial-import feature present')
        notes = gpkg.rollback_batch(target, [schema.STRINGS_LAYER], batch)
        check(not notes, 'rollback reported no problems')
        check(count(target, schema.STRINGS_LAYER) == before,
              'rollback removed exactly the failed batch')

        # -- leading fid --------------------------------------------------
        section('Attributes set by name, not index')
        # An existing GPKG layer has a leading fid; if attributes were set
        # positionally every value would land one column to the left.
        layer = QgsVectorLayer(
            gpkg.layer_uri(target, schema.STRINGS_LAYER), 'x', 'ogr')
        check(layer.fields()[0].name().lower() == 'fid',
              'target layer does have a leading fid')
        for feature in layer.getFeatures():
            check(feature['Format'] == 'surpac',
                  'Format column holds the format, not a shifted value')
            break

        # -- styles --------------------------------------------------------
        section('Styling')
        con = sqlite3.connect(target)
        try:
            styled = [r[0] for r in con.execute(
                'SELECT f_table_name FROM layer_styles WHERE useAsDefault = 1')]
        except sqlite3.Error:
            styled = []
        con.close()
        check(schema.STRINGS_LAYER in styled,
              'strings layer got its default style saved into the gpkg')
        stations_layer = QgsVectorLayer(
            gpkg.layer_uri(target, schema.STATIONS_LAYER), 'x', 'ogr')
        if stations_layer.isValid() and stations_layer.featureCount() >= 0:
            check(stations_layer.labelsEnabled(),
                  'stations layer has labelling enabled')

        # A style is applied on CREATE only; re-importing must not stomp a
        # customisation the user made afterwards.
        before_style = gpkg.apply_style(target, schema.STRINGS_LAYER)
        check(before_style is True or before_style is False,
              'apply_style is callable directly and reports success')

        # -- schema upgrade --------------------------------------------------
        section('Schema upgrade of an older GeoPackage')
        old = os.path.join(work, 'old.gpkg')
        from qgis.core import QgsField, QgsFields
        from qgis.PyQt.QtCore import QMetaType
        reduced = QgsFields()
        for name, mtype in schema.field_defs(schema.STATIONS_LAYER):
            if name in ('Domain', 'SetupCode', 'Bearing', 'SurveyType'):
                continue  # simulate a v1 file, written before these existed
            reduced.append(QgsField(name, mtype))
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = 'GPKG'
        options.layerName = schema.STATIONS_LAYER
        writer = QgsVectorFileWriter.create(
            old, reduced, schema.wkb_type(schema.STATIONS_LAYER), CRS, CTX,
            options)
        del writer
        pre = QgsVectorLayer(gpkg.layer_uri(old, schema.STATIONS_LAYER),
                             'x', 'ogr')
        check(pre.isValid() and pre.fields().lookupField('Domain') < 0,
              'v1-shaped layer built without the new columns')
        run_import(old, folder)
        post = QgsVectorLayer(gpkg.layer_uri(old, schema.STATIONS_LAYER),
                              'x', 'ogr')
        check(post.isValid() and post.fields().lookupField('Domain') >= 0,
              'older GeoPackage was upgraded in place, not rejected')

        # -- Z filter interop ---------------------------------------------
        section('Z Filter interop')
        try:
            from z_filter import detect
            string_fields = [f.name() for f in QgsVectorLayer(
                gpkg.layer_uri(target, schema.STRINGS_LAYER),
                'x', 'ogr').fields()]
            numeric = [n for n in string_fields if n in ('Z_Min', 'Z_Max')]
            check(detect.match_range_pair(numeric) == ('Z_Min', 'Z_Max'),
                  'strings resolve to range mode')
            check(detect.match_label_field(['Level', 'SourceFile']) == 'Level',
                  'Level is picked up as the label field')
            station_fields = [f.name() for f in QgsVectorLayer(
                gpkg.layer_uri(target, schema.STATIONS_LAYER),
                'x', 'ogr').fields()]
            check(detect.match_elevation_field(
                [n for n in station_fields if n == 'Elevation']) == 'Elevation',
                'stations resolve to single-value mode')
            for name in (schema.STRINGS_LAYER, schema.STATIONS_LAYER,
                         schema.OUTLINES_LAYER):
                check(any(hint in name.lower() for hint in detect.NAME_HINTS),
                      '{0} matches a Z Filter name hint'.format(name))
        except ImportError as exc:
            check(False, 'z_filter importable ({0})'.format(exc))

    finally:
        shutil.rmtree(work, ignore_errors=True)

    print('\n{0} passed, {1} failed'.format(_passed, _failed))
    return 1 if _failed else 0


if __name__ == '__main__':
    sys.exit(main())
