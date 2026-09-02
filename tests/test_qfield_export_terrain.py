"""
Tests for the 3D-terrain baking path of the QField exporter.

Two halves, both qgis-free:

1. The dialog -> converter wiring contract (ast-parsed, like
   tests/test_qfield_export_dialog.py). If bake_terrain / terrain_layer_id
   / terrain_scale stop being passed, exports would silently ship without
   terrain and QField would fall back to online Mapzen tiles - useless at
   pit scale, and nothing else in the suite would catch it.
2. The injection applied to a fixture .qgs on disk, exercising the same
   parse -> inject -> write round-trip _inject_terrain performs (its own
   body needs qgis, so the pure helper is driven directly here).

Run from the plugin root:
    python -m unittest discover tests
"""

import ast
import importlib.util
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIALOG = os.path.join(_ROOT, 'qfield_export', 'gui', 'export_dialog.py')
_CONVERTER = os.path.join(_ROOT, 'qfield_export', 'core',
                          'offline_converter.py')

_TERRAIN_KWARGS = ('bake_terrain', 'terrain_layer_id', 'terrain_scale')

_spec = importlib.util.spec_from_file_location(
    'terrain_xml',
    os.path.join(_ROOT, 'qfield_export', 'core', 'terrain_xml.py'))
terrain_xml = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(terrain_xml)

FIXTURE_QGS = """<?xml version="1.0" encoding="UTF-8"?>
<qgis version="3.40.0" projectname="Site">
  <projectCrs><spatialrefsys><authid>EPSG:28350</authid></spatialrefsys>
  </projectCrs>
  <layer-tree-group/>
  <projectlayers>
    <maplayer><id>dem_abc123</id><layername>Pit DEM</layername></maplayer>
  </projectlayers>
  <properties/>
</qgis>
"""


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _parse(path):
    return ast.parse(_read(path), filename=path)


def _converter_kwargs():
    for node in ast.walk(_parse(_CONVERTER)):
        if isinstance(node, ast.FunctionDef) and node.name == '__init__':
            args = node.args.args + node.args.kwonlyargs
            return [a.arg for a in args]
    raise AssertionError('OfflineConverter.__init__ not found')


def _converter_call_kwargs():
    """-> set of kwarg names passed to OfflineConverter(...) in the dialog."""
    for node in ast.walk(_parse(_DIALOG)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == 'OfflineConverter'):
            return {kw.arg for kw in node.keywords}
    raise AssertionError('OfflineConverter call not found in the dialog')


class TestTerrainWiring(unittest.TestCase):

    def test_converter_accepts_terrain_kwargs(self):
        kwargs = _converter_kwargs()
        for name in _TERRAIN_KWARGS:
            self.assertIn(name, kwargs)

    def test_dialog_passes_terrain_kwargs(self):
        passed = _converter_call_kwargs()
        for name in _TERRAIN_KWARGS:
            self.assertIn(name, passed,
                          '%s never reaches the converter' % name)

    def test_dialog_declares_terrain_widgets(self):
        source = _read(_DIALOG)
        for token in ('bake_terrain_check', 'terrain_z_spin',
                      '_terrain_layer_id', '_setup_terrain_row'):
            self.assertIn(token, source, token)

    def test_converter_injects_after_path_normalization(self):
        """Order matters: normalize_project_file_paths would rewrite the
        relative layerSource we inject."""
        source = _read(_CONVERTER)
        normalize_at = source.index('normalize_project_file_paths(project_file)')
        inject_at = source.index('self._inject_terrain(project_file)')
        self.assertLess(normalize_at, inject_at)

    def test_converter_auto_includes_the_dem(self):
        source = _read(_CONVERTER)
        self.assertIn('self.terrain_layer_id not in self.selected_layers',
                      source)


class TestInjectionOnFixtureProject(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='lgs_terrain_test_')
        self.path = os.path.join(self.tmp, 'Site.qgs')
        with open(self.path, 'w', encoding='utf-8') as fh:
            fh.write(FIXTURE_QGS)

    def _inject(self, **kwargs):
        tree = ET.parse(self.path)
        terrain_xml.inject_terrain(tree.getroot(), **kwargs)
        tree.write(self.path, encoding='UTF-8', xml_declaration=True)
        return ET.parse(self.path).getroot()

    def test_round_trip_through_a_project_file(self):
        root = self._inject(dem_layer_id='dem_abc123',
                            dem_source='./Pit_DEM.tif',
                            dem_layer_name='Pit DEM', scale=2.0)
        provider = root.find('ElevationProperties/terrainProvider')
        self.assertIsNotNone(provider)
        self.assertEqual(provider.get('type'), 'raster')
        inner = provider.find('TerrainProvider')
        self.assertIsNotNone(inner)
        self.assertEqual(inner.get('layer'), 'dem_abc123')
        self.assertEqual(inner.get('layerSource'), './Pit_DEM.tif')
        self.assertEqual(inner.get('scale'), '2')

    def test_source_stays_relative(self):
        root = self._inject(dem_layer_id='dem_abc123',
                            dem_source='./Pit_DEM.tif')
        source = root.find(
            'ElevationProperties/terrainProvider/TerrainProvider'
        ).get('layerSource')
        self.assertTrue(source.startswith('./'), source)
        self.assertNotIn(':', source)  # no drive letter leaked in

    def test_rerun_replaces(self):
        self._inject(dem_layer_id='a', dem_source='./a.tif')
        root = self._inject(dem_layer_id='b', dem_source='./b.tif')
        self.assertEqual(len(root.findall('ElevationProperties')), 1)
        self.assertEqual(
            root.find(
                'ElevationProperties/terrainProvider/TerrainProvider'
            ).get('layer'),
            'b')

    def test_project_content_survives(self):
        root = self._inject(dem_layer_id='dem_abc123',
                            dem_source='./Pit_DEM.tif')
        self.assertIsNotNone(root.find('projectlayers/maplayer'))
        self.assertIsNotNone(root.find('layer-tree-group'))
        self.assertEqual(root.get('projectname'), 'Site')


if __name__ == '__main__':
    unittest.main()
