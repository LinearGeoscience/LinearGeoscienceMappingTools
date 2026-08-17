"""
End-to-end import into a copy of the shipped template. Requires QGIS.

Run from the plugin root:

    C:\\OSGeo4W\\bin\\python-qgis-ltr.bat -  <<'EOF'
    from qgis.core import QgsApplication
    app = QgsApplication([], False); app.initQgis()
    path = r"<repo>\\tests\\test_import_qgis.py"
    exec(compile(open(path, encoding="utf-8").read(), path, "exec"),
         {"__file__": path, "__name__": "__main__"})
    app.exitQgis()
    EOF

Everything happens in a temp dir; Template/LGS_MappingTemplate.gpkg is copied,
never opened for writing, and the test asserts that.

The load-bearing cases are the ones no unit test can reach, because they are
about what QGIS itself does on write: the template's default-value expressions
firing (including Basemap's Description, which reads BasemapCodes through
get_feature and needs the lookup tables in the expression context), Z landing in
Elevation, reprojection, and the destination's schema coming out byte-identical.
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from qgis.core import (  # noqa: E402
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QMetaType  # noqa: E402

from data_import import domain, execute, plan as plan_module, scan  # noqa: E402

TEMPLATE = os.path.join(REPO_ROOT, 'Template', 'LGS_MappingTemplate.gpkg')

SOURCE_CRS = 'EPSG:7850'          # the destination copy stays on the
DESTINATION_CRS = 'EPSG:7851'     # template's own CRS, so this reprojects

# Deliberately shaped like ME_AbraMapping_April26.gpkg: client layer names, the
# pre-audit column set, and values that exercise each rung of the ladder.
LAYER_FIXTURES = [
    {
        'name': '1_Structures',
        'wkb': 'Point',
        'fields': ['Type', 'Subtype1', 'Geologist', 'UUID', 'Comments',
                   'SubType1Code', 'StructureLegend'],
        'rows': [
            (['Structure', 'S0', '1', 'aaaaaaaa-0000-0000-0000-000000000001',
              'first', 'S0', 'Bedding'], (100.0, 200.0)),
            (['Structure', 'FAP', '1', 'aaaaaaaa-0000-0000-0000-000000000002',
              'NULL', 'NULL', 'NULL'], (110.0, 210.0)),
        ],
    },
    {
        'name': '3_Linework',
        'wkb': 'LineString',
        'fields': ['Type', 'Geologist', 'UUID', 'Label', 'Comments'],
        'rows': [
            (['Fault', '1', 'bbbbbbbb-0000-0000-0000-000000000001', 'F1', ''],
             [(0.0, 0.0), (10.0, 10.0)]),
            (['Fault - Minor', '1', 'bbbbbbbb-0000-0000-0000-000000000002',
              'F2', ''], [(0.0, 5.0), (10.0, 15.0)]),
        ],
    },
    {
        'name': '2_Alteration',
        'wkb': 'Polygon',
        'fields': ['Type', 'SubType1', 'SubType2', 'Geologist', 'UUID',
                   'Comments'],
        'rows': [
            (['Alteration', 'Hematite', 'NULL', '1',
              'cccccccc-0000-0000-0000-000000000001', ''], 0.0),
            (['Structure', 'Shear Zone - Major', 'NULL', '1',
              'cccccccc-0000-0000-0000-000000000002', ''], 100.0),
        ],
    },
    {
        'name': '4_Lithology',
        'wkb': 'PolygonZ',
        'fields': ['TypeLith1', 'Lithology1', 'Lithology1Code', 'Geologist',
                   'UUID', 'Comments', 'Float', 'Lith1Feature'],
        'rows': [
            (['Lithology', 'FGR', 'FGR', '1',
              'dddddddd-0000-0000-0000-000000000001', '', 'NULL',
              'Chl-k altered'], (0.0, 137.5)),
            (['Lithology', 'SST', 'SST', '1',
              'dddddddd-0000-0000-0000-000000000002', '', 'yes', 'NULL'],
             (200.0, 96.25)),
        ],
    },
]


def _write_fixture(path):
    """Build the legacy-shaped source GeoPackage."""
    transform_context = QgsCoordinateTransformContext()
    crs = QgsCoordinateReferenceSystem(SOURCE_CRS)
    first = True
    for spec in LAYER_FIXTURES:
        fields = QgsFields()
        for name in spec['fields']:
            fields.append(QgsField(name, QMetaType.Type.QString))

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = 'GPKG'
        options.layerName = spec['name']
        options.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
            if first else
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer)
        first = False

        from qgis.core import QgsWkbTypes
        wkb = {'Point': QgsWkbTypes.Type.Point,
               'LineString': QgsWkbTypes.Type.LineString,
               'Polygon': QgsWkbTypes.Type.Polygon,
               'PolygonZ': QgsWkbTypes.Type.PolygonZ}[spec['wkb']]

        writer = QgsVectorFileWriter.create(path, fields, wkb, crs,
                                            transform_context, options)
        assert writer is not None and \
            writer.hasError() == QgsVectorFileWriter.WriterError.NoError, \
            'could not create {0}: {1}'.format(spec['name'],
                                               writer and writer.errorMessage())
        for attributes, shape in spec['rows']:
            feature = QgsFeature(fields)
            feature.setAttributes(list(attributes))
            feature.setGeometry(_geometry(spec['wkb'], shape))
            writer.addFeature(feature)
        del writer


def _geometry(kind, shape):
    if kind == 'Point':
        return QgsGeometry.fromWkt('POINT({0} {1})'.format(*shape))
    if kind == 'LineString':
        return QgsGeometry.fromWkt('LINESTRING({0})'.format(
            ', '.join('{0} {1}'.format(x, y) for x, y in shape)))
    if kind == 'Polygon':
        offset = shape
        return QgsGeometry.fromWkt(
            'POLYGON(({0} 0, {1} 0, {1} 10, {0} 10, {0} 0))'.format(
                offset, offset + 10))
    offset, z = shape
    return QgsGeometry.fromWkt(
        'POLYGON Z(({0} 0 {2}, {1} 0 {2}, {1} 10 {2}, {0} 10 {2}, '
        '{0} 0 {2}))'.format(offset, offset + 10, z))


def _schema(path):
    connection = sqlite3.connect(path)
    try:
        return {name: [row[1] for row in connection.execute(
                    'PRAGMA table_info("{0}")'.format(name))]
                for (name,) in connection.execute(
                    'SELECT table_name FROM gpkg_contents ORDER BY table_name')}
    finally:
        connection.close()


def _query(path, sql):
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


class ImportTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix='lgs_import_test_')
        cls.source_path = os.path.join(cls.work, 'legacy_mapping.gpkg')
        cls.destination_path = os.path.join(cls.work, 'LGS_Test_7851.gpkg')
        _write_fixture(cls.source_path)
        shutil.copy2(TEMPLATE, cls.destination_path)
        cls.template_mtime = os.path.getmtime(TEMPLATE)
        cls.template_size = os.path.getsize(TEMPLATE)
        cls.schema_before = _schema(cls.destination_path)

        cls.result = cls._run_import()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    @classmethod
    def _build_plan(cls):
        target = domain.read_gpkg_model(cls.destination_path)
        source = domain.read_gpkg_model(cls.source_path)
        destination = plan_module.DestinationRef(
            'gpkg', cls.destination_path, 'LGS_Test_7851.gpkg')
        built = plan_module.build_plan(
            source, target, destination,
            lambda table, fields: scan.gpkg_value_counts(cls.source_path,
                                                         table, fields))
        # The one decision the ladder deliberately refuses to make on its own.
        for item in built.included():
            for resolutions in item.resolutions.values():
                for value, resolution in resolutions.items():
                    if resolution.decided:
                        continue
                    if value == 'Formline - Fine':
                        resolution.add_as_new_code(parent='Formlines')
                    else:
                        resolution.leave_blank(to_comments=True)
        return built

    @classmethod
    def _run_import(cls):
        built = cls._build_plan()
        report = built.validate()
        assert report.ok, [finding.title for finding in report.errors]
        snapshots = execute.prepare_sources(built)
        return execute.run_import(built, snapshots)


class TestFeaturesLand(ImportTestCase):

    def test_every_feature_arrived(self):
        self.assertEqual(self.result.total_added, 8)
        self.assertEqual(self.result.total_skipped, 0)
        for layer_result in self.result.layers:
            self.assertEqual(layer_result.errors, [], layer_result.target_layer)

    def test_layers_were_matched_across_the_renumbering(self):
        pairs = {(result.source_label, result.target_layer)
                 for result in self.result.layers}
        self.assertEqual(pairs, {
            ('1_Structures', '1 - FieldNotebook'),
            ('3_Linework', '2 - Linework'),
            ('2_Alteration', '3 - Overlay'),
            ('4_Lithology', '4 - Basemap'),
        })


class TestSchemaIsUntouched(ImportTestCase):

    def test_destination_schema_is_identical(self):
        self.assertEqual(_schema(self.destination_path), self.schema_before)

    def test_shipped_template_was_not_written_to(self):
        self.assertEqual(os.path.getmtime(TEMPLATE), self.template_mtime)
        self.assertEqual(os.path.getsize(TEMPLATE), self.template_size)

    def test_a_backup_was_taken(self):
        self.assertTrue(self.result.backup_path)
        self.assertTrue(os.path.exists(self.result.backup_path))


class TestTemplateDefaultsFire(ImportTestCase):
    """provider.addFeatures() bypasses these; the writer evaluates them."""

    def test_confidence_defaults_on_every_layer(self):
        for table in ('1 - FieldNotebook', '2 - Linework', '3 - Overlay',
                      '4 - Basemap'):
            rows = _query(self.destination_path,
                          'SELECT DISTINCT Confidence FROM "{0}"'.format(table))
            self.assertEqual(rows, [('Observed',)], table)

    def test_linework_weight_defaults_where_the_source_said_nothing(self):
        """Keyed on UUID: after the split both rows are Type 'Fault'."""
        rows = dict(_query(
            self.destination_path,
            'SELECT UUID, Weight FROM "2 - Linework"'))
        self.assertEqual(rows['bbbbbbbb-0000-0000-0000-000000000001'],
                         'Moderate')          # template default
        self.assertEqual(rows['bbbbbbbb-0000-0000-0000-000000000002'],
                         'Minor')             # from '- Minor'

    def test_a_retired_suffix_became_a_weight(self):
        rows = _query(self.destination_path,
                      'SELECT Type, Weight, Category FROM "2 - Linework" '
                      "WHERE Weight = 'Minor'")
        self.assertEqual(rows, [('Fault', 'Minor', 'Structural')])

    def test_overlay_intensity_is_scoped_to_alteration(self):
        rows = dict(_query(self.destination_path,
                           'SELECT Type, Intensity FROM "3 - Overlay"'))
        self.assertEqual(rows['Alteration'], 3)
        self.assertIsNone(rows['Structure'])

    def test_overlay_weight_is_scoped_to_structure(self):
        rows = dict(_query(self.destination_path,
                           'SELECT Type, Weight FROM "3 - Overlay"'))
        self.assertEqual(rows['Structure'], 'Major')  # from the split
        self.assertIsNone(rows['Alteration'])

    def test_basemap_description_is_looked_up_across_tables(self):
        """Description's default reads BasemapCodes through get_feature().

        It only evaluates when the lookup tables are in the expression
        context's layer store, which is why execute builds one.
        """
        rows = dict(_query(self.destination_path,
                           'SELECT Lithology1, Description FROM "4 - Basemap"'))
        self.assertEqual(rows['FGR'], 'FGR - Granite')
        self.assertTrue(rows['SST'])

    def test_a_shadowed_column_is_filled_from_its_own_expression(self):
        """Lithology1Code is a real column AND a QML expression field.

        The form shows the expression's value while the stored column can sit
        empty — and the column is flagged not-null. The expression is the
        template stating what the column should hold, so it is honoured.
        """
        rows = dict(_query(self.destination_path,
                           'SELECT Lithology1, Lithology1Code '
                           'FROM "4 - Basemap"'))
        self.assertEqual(rows['FGR'], 'FGR')
        self.assertEqual(rows['SST'], 'SST')

    def test_overlay_code_is_shadowed_from_subtype1(self):
        rows = dict(_query(self.destination_path,
                           'SELECT SubType1, Code FROM "3 - Overlay"'))
        self.assertEqual(rows['Hem'], 'Hem')
        self.assertEqual(rows['Shear Zone'], 'Shear Zone')

    def test_uuid_and_coordinates_are_filled(self):
        rows = _query(self.destination_path,
                      'SELECT UUID, Easting, Northing, "Date&Time" '
                      'FROM "1 - FieldNotebook"')
        for uuid_value, easting, northing, stamp in rows:
            self.assertTrue(uuid_value)
            self.assertIsNotNone(easting)
            self.assertIsNotNone(northing)
            self.assertTrue(stamp)


class TestDerivedValues(ImportTestCase):

    def test_cascade_parents_are_backfilled(self):
        rows = _query(self.destination_path,
                      'SELECT Category, Type FROM "2 - Linework"')
        for category, code in rows:
            self.assertEqual(category, 'Structural', code)

    def test_the_description_tier_translated_a_name_into_a_code(self):
        rows = _query(self.destination_path,
                      'SELECT SubType1 FROM "3 - Overlay" '
                      "WHERE Type = 'Alteration'")
        self.assertEqual(rows, [('Hem',)])

    def test_z_became_elevation_and_geometry_kept_it(self):
        rows = dict(_query(self.destination_path,
                           'SELECT Lithology1, Elevation FROM "4 - Basemap"'))
        self.assertAlmostEqual(rows['FGR'], 137.5, places=3)
        self.assertAlmostEqual(rows['SST'], 96.25, places=3)

    def test_retired_freetext_columns_were_kept_in_comments(self):
        rows = _query(self.destination_path,
                      'SELECT Lithology1, Comments FROM "4 - Basemap"')
        comments = dict(rows)
        self.assertIn('Lith1Feature: Chl-k altered', comments['FGR'])
        self.assertIn('Float: yes', comments['SST'])

    def test_the_literal_string_null_was_treated_as_empty(self):
        """Old exports write 'NULL' into empty text columns.

        Read as a value it becomes an unrecognised code and the feature is
        dropped, which is exactly what happened before is_blank() was shared.
        """
        rows = _query(self.destination_path,
                      'SELECT Comments FROM "3 - Overlay"')
        for (comment,) in rows:
            self.assertNotIn('NULL', (comment or ''))
        rows = _query(self.destination_path,
                      'SELECT SubType2 FROM "3 - Overlay"')
        self.assertEqual([value for (value,) in rows], [None, None])


class TestReprojection(ImportTestCase):

    def test_coordinates_moved(self):
        """7850 -> 7851 is a zone change, so the easting shifts a long way."""
        layer = QgsVectorLayer(
            '{0}|layername=1 - FieldNotebook'.format(self.destination_path),
            'fn', 'ogr')
        self.assertTrue(layer.isValid())
        point = next(layer.getFeatures()).geometry().asPoint()
        self.assertNotAlmostEqual(point.x(), 100.0, places=1)


class TestNewCodes(ImportTestCase):

    def test_no_new_code_was_needed_here(self):
        """The fixture resolves cleanly; the add path is covered below."""
        self.assertEqual(self.result.new_codes, [])


class TestReRunIsIdempotent(ImportTestCase):

    def test_a_second_run_adds_nothing(self):
        before = _query(self.destination_path,
                        'SELECT COUNT(*) FROM "1 - FieldNotebook"')[0][0]
        second = self._run_import()
        after = _query(self.destination_path,
                       'SELECT COUNT(*) FROM "1 - FieldNotebook"')[0][0]
        self.assertEqual(after, before)
        self.assertEqual(second.total_added, 0)
        self.assertEqual(second.total_skipped, 8)


class TestAddingACode(unittest.TestCase):
    """The 'add this code to the project' path, end to end."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='lgs_import_addcode_')
        self.source_path = os.path.join(self.work, 'legacy.gpkg')
        self.destination_path = os.path.join(self.work, 'LGS_AddCode.gpkg')
        _write_fixture(self.source_path)
        shutil.copy2(TEMPLATE, self.destination_path)

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def test_a_new_code_lands_in_the_projects_table_and_backfills(self):
        target = domain.read_gpkg_model(self.destination_path)
        source = domain.read_gpkg_model(self.source_path)
        built = plan_module.build_plan(
            source, target,
            plan_module.DestinationRef('gpkg', self.destination_path, 'dest'),
            lambda table, fields: scan.gpkg_value_counts(self.source_path,
                                                         table, fields))
        # Force the case: pretend 'Fault' is unknown and must be added.
        linework = [item for item in built.included()
                    if item.target_layer == '2 - Linework'][0]
        resolution = linework.resolutions['Type']['Fault']
        resolution.add_as_new_code(parent='Formlines',
                                   description='Fault - test')
        resolution.code = 'Fault - test'

        self.assertTrue(built.validate().ok)
        result = execute.run_import(built, execute.prepare_sources(built))

        added = _query(self.destination_path,
                       "SELECT Type, Code, Description FROM LineworkCodes "
                       "WHERE Code = 'Fault - test'")
        self.assertEqual(added, [('Formlines', 'Fault - test', 'Fault - test')])
        self.assertEqual(len(result.new_codes), 1)

        # Registered in the domain, so the parent back-fill knows it too.
        rows = _query(self.destination_path,
                      'SELECT Category FROM "2 - Linework" '
                      "WHERE Type = 'Fault - test'")
        self.assertEqual(rows, [('Formlines',)])

        # The shipped template is untouched.
        untouched = _query(TEMPLATE,
                           "SELECT COUNT(*) FROM LineworkCodes "
                           "WHERE Code = 'Fault - test'")
        self.assertEqual(untouched, [(0,)])


class TestAppendWorkflow(unittest.TestCase):
    """The other half of what this tool is for: topping up a local master.

    Mapping accumulates on a master GeoPackage and each new field export
    repeats most of what is already there. Only the genuinely new features may
    land, matched on UUID, optionally narrowed by date.
    """

    FIELDS = ['Type', 'Subtype1', 'Geologist', 'UUID', 'Comments', 'Date&Time']

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='lgs_import_append_')
        self.master = os.path.join(self.work, 'LGS_Master.gpkg')
        shutil.copy2(TEMPLATE, self.master)

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def _export(self, name, rows):
        """A QField-shaped FieldNotebook export. rows: [(uuid, day_offset)]."""
        from qgis.core import QgsWkbTypes

        path = os.path.join(self.work, name)
        fields = QgsFields()
        for field_name in self.FIELDS:
            fields.append(QgsField(field_name, QMetaType.Type.QString))
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = 'GPKG'
        options.layerName = '1 - FieldNotebook'
        options.actionOnExistingFile = \
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
        writer = QgsVectorFileWriter.create(
            path, fields, QgsWkbTypes.Type.Point,
            QgsCoordinateReferenceSystem(DESTINATION_CRS),
            QgsCoordinateTransformContext(), options)
        for index, (uuid_value, day) in enumerate(rows):
            feature = QgsFeature(fields)
            feature.setAttributes(
                ['Structure', 'S0', '1', uuid_value, '',
                 '2026-08-{0:02d} 09:00:00'.format(1 + day)])
            feature.setGeometry(QgsGeometry.fromWkt(
                'POINT({0} {1})'.format(500000 + index, 7000000 + index)))
            writer.addFeature(feature)
        del writer
        return path

    def _import(self, source, date_filter=None):
        target = domain.read_gpkg_model(self.master)
        source_model = domain.read_gpkg_model(source)

        def counts(table, fields, _f=date_filter):
            names = scan.gpkg_column_names(source, table)
            return scan.gpkg_value_counts(
                source, table, fields,
                where=scan.date_filter_expression(_f, names))

        def source_uuids(table, _f=date_filter):
            names = scan.gpkg_column_names(source, table)
            where = scan.date_filter_expression(_f, names)
            counted = scan.gpkg_value_counts(source, table, ['UUID'],
                                             where=where)['UUID']
            return set(counted.counts), counted.empty

        def destination_uuids(layer_name):
            return scan.gpkg_column_set(self.master, layer_name, 'UUID')

        built = plan_module.build_plan(
            source_model, target,
            plan_module.DestinationRef('gpkg', self.master, 'master'),
            counts, source_uuids_for=source_uuids,
            destination_uuids_for=destination_uuids)
        built.options.backup = False
        built.options.date_filter = date_filter
        for item in built.included():
            for resolutions in item.resolutions.values():
                for resolution in resolutions.values():
                    if not resolution.decided:
                        resolution.leave_blank()
        self.assertTrue(built.validate().ok)
        return built, execute.run_import(built, execute.prepare_sources(built))

    def _uuids(self):
        return sorted(value for (value,) in _query(
            self.master, 'SELECT UUID FROM "1 - FieldNotebook"'))

    def test_only_the_new_features_land_on_a_second_import(self):
        first = self._export('week1.gpkg',
                             [('uuid-001', 0), ('uuid-002', 1)])
        _plan, result = self._import(first)
        self.assertEqual((result.total_added, result.total_skipped), (2, 0))

        second = self._export('week2.gpkg',
                              [('uuid-001', 0), ('uuid-002', 1),
                               ('uuid-003', 8)])
        built, result = self._import(second)
        self.assertEqual((result.total_added, result.total_skipped), (1, 2))
        self.assertEqual(self._uuids(), ['uuid-001', 'uuid-002', 'uuid-003'])

    def test_the_review_page_predicts_that_before_running(self):
        first = self._export('week1.gpkg',
                             [('uuid-001', 0), ('uuid-002', 1)])
        self._import(first)
        second = self._export('week2.gpkg',
                              [('uuid-001', 0), ('uuid-002', 1),
                               ('uuid-003', 8)])
        built, result = self._import(second)
        summary = built.summary()
        self.assertEqual(summary['expected_new'], result.total_added)
        self.assertEqual(summary['already_present'], result.total_skipped)

    def test_a_date_filter_narrows_what_is_considered(self):
        source = self._export('all.gpkg',
                              [('uuid-001', 0), ('uuid-002', 1),
                               ('uuid-003', 8), ('uuid-004', 9)])
        after_day_five = {'enabled': True,
                          'type': scan.FILTER_TYPE_AFTER,
                          'start_datetime': datetime(2026, 8, 6, 9, 0, 0),
                          'end_datetime': None}
        _plan, result = self._import(source, date_filter=after_day_five)
        self.assertEqual(result.total_added, 2)
        self.assertEqual(self._uuids(), ['uuid-003', 'uuid-004'])

    def test_a_between_filter_takes_a_window(self):
        source = self._export('all.gpkg',
                              [('uuid-001', 0), ('uuid-002', 1),
                               ('uuid-003', 8), ('uuid-004', 9)])
        window = {'enabled': True,
                  'type': scan.FILTER_TYPE_BETWEEN,
                  'start_datetime': datetime(2026, 8, 2, 0, 0, 0),
                  'end_datetime': datetime(2026, 8, 9, 23, 59, 59)}
        _plan, result = self._import(source, date_filter=window)
        self.assertEqual(self._uuids(), ['uuid-002', 'uuid-003'])
        self.assertEqual(result.total_added, 2)

    def test_a_feature_deleted_on_purpose_does_not_come_back(self):
        source = self._export('week1.gpkg',
                              [('uuid-001', 0), ('uuid-002', 1)])
        self._import(source)
        connection = sqlite3.connect(self.master)
        connection.execute('DELETE FROM "1 - FieldNotebook" WHERE UUID = ?',
                           ('uuid-002',))
        connection.commit()
        connection.close()
        self.assertEqual(self._uuids(), ['uuid-001'])

        _plan, result = self._import(source)
        self.assertEqual(result.total_added, 0)
        self.assertEqual(self._uuids(), ['uuid-001'])

    def test_features_without_a_uuid_get_one_and_are_flagged(self):
        source = self._export('nouuid.gpkg', [('', 0), ('uuid-002', 1)])
        built, result = self._import(source)
        self.assertEqual(result.total_added, 2)
        self.assertTrue(all(self._uuids()))
        warnings = ' '.join(f.title for f in built.validate().warnings)
        self.assertIn('have no UUID', warnings)


def _suite():
    """Collect from this namespace directly.

    The file is exec'd inside a runner's __main__, so unittest.main() would
    read the runner's argv and find no module to load from.
    """
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for obj in list(globals().values()):
        if (isinstance(obj, type) and issubclass(obj, unittest.TestCase)
                and obj is not unittest.TestCase):
            suite.addTests(loader.loadTestsFromTestCase(obj))
    return suite


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(_suite())
    if not result.wasSuccessful():
        raise SystemExit(1)
