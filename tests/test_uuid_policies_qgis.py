r"""
UUID survives an edit, but never a duplicate. Requires QGIS.

Run from the plugin root:

    C:\OSGeo4W\bin\python-qgis-ltr.bat -  <<'EOF'
    from qgis.core import QgsApplication
    app = QgsApplication([], False); app.initQgis()
    path = r"<repo>\tests\test_uuid_policies_qgis.py"
    exec(compile(open(path, encoding="utf-8").read(), path, "exec"),
         {"__file__": path, "__name__": "__main__"})
    app.exitQgis()
    EOF

Duplicating a line or polygon is how a geologist adds a feature that shares
most of its attributes with one already mapped. QGIS copies every attribute
verbatim unless the field says otherwise, so the copy used to arrive wearing
the original's UUID - and UUID is the identity the importer and the reconcile
merge both key on, so the copy was silently dropped by one and skipped by the
other.

scripts/inject_uuid_duplicate_policy.py points the UUID field's duplicate and
split policies at its own uuid('WithoutBraces') default. These tests pin that
in the shipped template, and check QGIS actually honours it.
"""

import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from qgis.core import (  # noqa: E402
    Qgis,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
    QgsVectorLayerUtils,
)

from lgs_layers import CANONICAL_LAYERS  # noqa: E402

TEMPLATE = os.path.join(REPO_ROOT, 'Template', 'LGS_MappingTemplate.gpkg')

GEOMETRY = {
    '1 - FieldNotebook': 'POINT(500000 7000000)',
    '2 - Linework': 'LINESTRING(500000 7000000, 500010 7000010)',
    '3 - Overlay': 'POLYGON((500000 7000000, 500010 7000000, '
                   '500010 7000010, 500000 7000010, 500000 7000000))',
    '4 - Basemap': 'POLYGON((500000 7000000, 500010 7000000, '
                   '500010 7000010, 500000 7000010, 500000 7000000))',
}


class PolicyTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix='lgs_uuid_policy_')
        cls.gpkg = os.path.join(cls.work, 'LGS_Policy.gpkg')
        shutil.copy2(TEMPLATE, cls.gpkg)
        cls.layers = []

    @classmethod
    def tearDownClass(cls):
        cls.layers = []
        shutil.rmtree(cls.work, ignore_errors=True)

    @classmethod
    def _layer(cls, name):
        layer = QgsVectorLayer('{0}|layername={1}'.format(cls.gpkg, name),
                               name, 'ogr')
        assert layer.isValid(), name
        layer.loadDefaultStyle()
        cls.layers.append(layer)
        return layer


class TestPolicies(PolicyTestCase):
    """Every mapping layer's UUID leans on its own default, not the old value."""

    def test_duplicating_asks_for_a_fresh_uuid(self):
        for name in CANONICAL_LAYERS:
            field = self._layer(name).fields().field('UUID')
            self.assertEqual(field.duplicatePolicy(),
                             Qgis.FieldDuplicatePolicy.DefaultValue, name)

    def test_splitting_asks_for_a_fresh_uuid(self):
        for name in CANONICAL_LAYERS:
            field = self._layer(name).fields().field('UUID')
            self.assertEqual(field.splitPolicy(),
                             Qgis.FieldDomainSplitPolicy.DefaultValue, name)

    def test_the_default_they_lean_on_is_still_there(self):
        for name in CANONICAL_LAYERS:
            layer = self._layer(name)
            index = layer.fields().indexOf('UUID')
            expression = layer.defaultValueDefinition(index).expression() or ''
            self.assertIn('uuid(', expression, name)
            # applyOnUpdate would rewrite the UUID on every edit, which is the
            # opposite of an identity.
            self.assertFalse(layer.defaultValueDefinition(index).applyOnUpdate(),
                             name)


class TestQgisHonoursThem(PolicyTestCase):
    """The policy is only worth having if the duplicate really gets a new one."""

    def _seeded(self, name):
        layer = self._layer(name)
        layer.startEditing()
        feature = QgsFeature(layer.fields())
        feature.setAttribute('UUID', 'seed-0000-0000')
        feature.setGeometry(QgsGeometry.fromWkt(GEOMETRY[name]))
        self.assertTrue(layer.addFeature(feature), name)
        self.assertTrue(layer.commitChanges(), layer.commitErrors())
        return layer

    def test_a_duplicate_does_not_carry_the_original_uuid(self):
        for name in CANONICAL_LAYERS:
            layer = self._seeded(name)
            project = QgsProject()
            project.addMapLayer(layer, False)
            original = next(layer.getFeatures())
            self.assertEqual(original['UUID'], 'seed-0000-0000', name)

            layer.startEditing()
            # duplicateFeature(layer, feature, project, maxDepth) -> (feature,
            # context); the context comes back rather than going in.
            copy, _context = QgsVectorLayerUtils.duplicateFeature(
                layer, original, project, 0)
            self.assertTrue(layer.commitChanges(), layer.commitErrors())

            value = copy['UUID']
            self.assertTrue(value, '{0}: the copy has no UUID'.format(name))
            self.assertNotEqual(
                value, 'seed-0000-0000',
                '{0}: the copy kept the original UUID'.format(name))
            project.removeAllMapLayers()


def _suite():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for obj in list(globals().values()):
        if (isinstance(obj, type) and issubclass(obj, unittest.TestCase)
                and obj is not unittest.TestCase
                and obj is not PolicyTestCase):
            suite.addTests(loader.loadTestsFromTestCase(obj))
    return suite


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(_suite())
    if not result.wasSuccessful():
        raise SystemExit(1)
