"""
Project-mode destination resolution. Requires QGIS.

Run from the plugin root:

    C:\\OSGeo4W\\bin\\python-qgis-ltr.bat -  <<'EOF'
    from qgis.core import QgsApplication
    app = QgsApplication([], False); app.initQgis()
    path = r"<repo>\\tests\\test_import_project_destination_qgis.py"
    exec(compile(open(path, encoding="utf-8").read(), path, "exec"),
         {"__file__": path, "__name__": "__main__"})
    app.exitQgis()
    EOF

The scenario under test is the one reported from the field: a mapping export
loaded into the project for a look-around carries the same four canonical
table names as the real project GeoPackage, and the importer used to send the
whole import — backup included — into whichever file happened to be met first.
"""

import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

from qgis.core import QgsProject, QgsVectorLayer  # noqa: E402

from data_import import domain, execute, plan as plan_module, scan  # noqa: E402
from lgs_layers import CANONICAL_LAYERS  # noqa: E402
import test_import_qgis as tiq  # noqa: E402  (fixture writer + template path)

# The legacy fixture, re-badged with canonical layer names: exactly what an
# export of a mapping project looks like when it is loaded back into QGIS.
_CANONICAL_NAME = {
    '1_Structures': '1 - FieldNotebook',
    '3_Linework': '2 - Linework',
    '2_Alteration': '3 - Overlay',
    '4_Lithology': '4 - Basemap',
}


def _write_canonical_export(path):
    renamed = [dict(spec, name=_CANONICAL_NAME[spec['name']])
               for spec in tiq.LAYER_FIXTURES]
    original = tiq.LAYER_FIXTURES
    tiq.LAYER_FIXTURES = renamed
    try:
        tiq._write_fixture(path)
    finally:
        tiq.LAYER_FIXTURES = original


def _load_mapping_layers(project, gpkg_path):
    for name in CANONICAL_LAYERS:
        layer = QgsVectorLayer('{0}|layername={1}'.format(gpkg_path, name),
                               name, 'ogr')
        assert layer.isValid(), '{0} missing from {1}'.format(name, gpkg_path)
        project.addMapLayer(layer)


class ProjectDestinationCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix='lgs_import_projdest_')
        cls.real_path = os.path.join(cls.work, 'LGS_Project.gpkg')
        cls.export_path = os.path.join(cls.work, 'ME_Export_AllMapping.gpkg')
        shutil.copy2(tiq.TEMPLATE, cls.real_path)
        _write_canonical_export(cls.export_path)
        cls.projects = []

    @classmethod
    def tearDownClass(cls):
        for project in cls.projects:
            project.removeAllMapLayers()
        cls.projects = []
        shutil.rmtree(cls.work, ignore_errors=True)

    @classmethod
    def _project(cls, *gpkg_paths):
        """A standalone project holding each file's mapping layers, in order.

        The export always loads FIRST where present, reproducing the
        first-gpkg-wins ordering that caused the field failure.
        """
        project = QgsProject()
        for path in gpkg_paths:
            _load_mapping_layers(project, path)
        cls.projects.append(project)
        return project


class TestResolver(ProjectDestinationCase):

    def test_excluding_the_source_resolves_the_real_file(self):
        project = self._project(self.export_path, self.real_path)
        resolved, problem = domain.resolve_project_destination(
            project, [self.export_path])
        self.assertEqual(problem, '')
        self.assertEqual(os.path.normcase(resolved),
                         os.path.normcase(self.real_path))

    def test_two_candidates_are_refused_not_guessed(self):
        project = self._project(self.export_path, self.real_path)
        resolved, problem = domain.resolve_project_destination(project)
        self.assertEqual(resolved, '')
        self.assertIn('more than one GeoPackage', problem)
        self.assertIn(os.path.basename(self.real_path), problem)
        self.assertIn(os.path.basename(self.export_path), problem)

    def test_a_project_with_no_mapping_layers_is_refused(self):
        project = QgsProject()
        self.projects.append(project)
        resolved, problem = domain.resolve_project_destination(project)
        self.assertEqual(resolved, '')
        self.assertIn('No GeoPackage-backed mapping layers', problem)


class TestEndToEnd(ProjectDestinationCase):
    """The reported failure, end to end: export loaded first, then imported."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls._project(cls.export_path, cls.real_path)
        cls.export_mtime = os.path.getmtime(cls.export_path)
        cls.export_size = os.path.getsize(cls.export_path)
        cls.counts_before = {name: tiq._query(
            cls.real_path, 'SELECT COUNT(*) FROM "{0}"'.format(name))[0][0]
            for name in CANONICAL_LAYERS}

        cls.resolved, problem = domain.resolve_project_destination(
            cls.project, [cls.export_path])
        assert not problem, problem

        # Mirrors page_source._capture_main_thread_inputs: the target model is
        # read from the resolved file's layers only.
        def _same(path):
            return path and (os.path.normcase(os.path.abspath(path))
                             == os.path.normcase(os.path.abspath(cls.resolved)))

        target = domain.read_project_model(cls.project, layers=[
            layer for layer in cls.project.mapLayers().values()
            if _same(domain.gpkg_path_of(layer))])
        source = domain.read_gpkg_model(cls.export_path)
        destination = plan_module.DestinationRef(
            'project', cls.resolved,
            'this project ({0})'.format(os.path.basename(cls.resolved)))
        built = plan_module.build_plan(
            source, target, destination,
            lambda table, fields: scan.gpkg_value_counts(cls.export_path,
                                                         table, fields))
        for item in built.included():
            for resolutions in item.resolutions.values():
                for resolution in resolutions.values():
                    if not resolution.decided:
                        resolution.leave_blank(to_comments=True)
        report = built.validate()
        assert report.ok, [finding.title for finding in report.errors]
        snapshots = execute.prepare_sources(built, project=cls.project)
        cls.result = execute.run_import(built, snapshots)

    def test_the_target_model_comes_from_the_resolved_file(self):
        self.assertEqual(os.path.normcase(self.resolved),
                         os.path.normcase(self.real_path))

    def test_features_land_in_the_real_project_file(self):
        self.assertFalse(self.result.failed, self.result.message)
        self.assertEqual(self.result.total_added, 8)
        added = {name: tiq._query(
            self.real_path, 'SELECT COUNT(*) FROM "{0}"'.format(name))[0][0]
            - self.counts_before[name] for name in CANONICAL_LAYERS}
        self.assertEqual(added, {name: 2 for name in CANONICAL_LAYERS})

    def test_the_export_was_not_touched(self):
        self.assertEqual(os.path.getmtime(self.export_path), self.export_mtime)
        self.assertEqual(os.path.getsize(self.export_path), self.export_size)
        self.assertEqual(tiq._query(
            self.export_path,
            'SELECT COUNT(*) FROM "1 - FieldNotebook"')[0][0], 2)

    def test_the_backup_sits_beside_the_real_file_only(self):
        self.assertTrue(self.result.backup_path)
        self.assertEqual(
            os.path.normcase(os.path.dirname(
                os.path.dirname(self.result.backup_path))),
            os.path.normcase(os.path.dirname(self.real_path)))


class TestPreflightRefusal(ProjectDestinationCase):
    """A destination without the target tables is refused before any backup."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A real gpkg that is NOT a mapping file: the legacy-named fixture.
        cls.wrong_path = os.path.join(cls.work, 'legacy_mapping.gpkg')
        tiq._write_fixture(cls.wrong_path)

        target = domain.read_gpkg_model(cls.real_path)
        source = domain.read_gpkg_model(cls.export_path)
        destination = plan_module.DestinationRef('project', cls.wrong_path,
                                                 'this project')
        built = plan_module.build_plan(
            source, target, destination,
            lambda table, fields: scan.gpkg_value_counts(cls.export_path,
                                                         table, fields))
        for item in built.included():
            for resolutions in item.resolutions.values():
                for resolution in resolutions.values():
                    if not resolution.decided:
                        resolution.leave_blank(to_comments=True)
        snapshots = execute.prepare_sources(built)
        cls.result = execute.run_import(built, snapshots)

    def test_the_run_fails_naming_the_wrong_file(self):
        self.assertTrue(self.result.failed)
        self.assertIn(self.wrong_path, self.result.message)
        self.assertIn('does not contain', self.result.message)

    def test_no_backup_was_made(self):
        self.assertFalse(self.result.backup_path)
        self.assertFalse(os.path.exists(
            os.path.join(os.path.dirname(self.wrong_path),
                         'lgs_import_backup')))


def _suite():
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
