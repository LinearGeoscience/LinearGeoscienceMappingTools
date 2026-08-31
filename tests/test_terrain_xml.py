"""
Unit tests for qfield_export/core/terrain_xml.py (pure stdlib).

Run from the plugin root:
    python -m unittest discover tests
"""

import importlib.util
import os
import unittest
import xml.etree.ElementTree as ET

_path = os.path.join(os.path.dirname(__file__), '..', 'qfield_export',
                     'core', 'terrain_xml.py')
_spec = importlib.util.spec_from_file_location('terrain_xml', _path)
terrain_xml = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(terrain_xml)

MINIMAL_QGS = (
    '<qgis version="3.40.0" projectname="">'
    '<projectCrs/><layer-tree-group/><projectlayers/>'
    '</qgis>')


class TestInjectTerrain(unittest.TestCase):
    def _root(self):
        return ET.fromstring(MINIMAL_QGS)

    def test_injects_provider(self):
        root = self._root()
        terrain_xml.inject_terrain(
            root, 'dem_layer_id_123', './pit_dem.tif',
            dem_layer_name='Pit DEM', scale=2.0)
        elems = root.findall('ElevationProperties')
        self.assertEqual(len(elems), 1)
        provider = elems[0].find('terrainProvider')
        self.assertIsNotNone(provider)
        self.assertEqual(provider.get('type'), 'raster')
        self.assertEqual(provider.get('layer'), 'dem_layer_id_123')
        self.assertEqual(provider.get('layerName'), 'Pit DEM')
        self.assertEqual(provider.get('layerSource'), './pit_dem.tif')
        self.assertEqual(provider.get('layerProvider'), 'gdal')
        self.assertEqual(provider.get('scale'), '2')
        self.assertEqual(provider.get('offset'), '0')

    def test_replaces_not_duplicates(self):
        root = self._root()
        terrain_xml.inject_terrain(root, 'a', './a.tif', scale=1.0)
        terrain_xml.inject_terrain(root, 'b', './b.tif', scale=1.5)
        elems = root.findall('ElevationProperties')
        self.assertEqual(len(elems), 1)
        provider = elems[0].find('terrainProvider')
        self.assertEqual(provider.get('layer'), 'b')
        self.assertEqual(provider.get('scale'), '1.5')

    def test_replaces_existing_project_terrain(self):
        root = self._root()
        existing = ET.SubElement(root, 'ElevationProperties')
        ET.SubElement(existing, 'terrainProvider', {'type': 'flat'})
        terrain_xml.inject_terrain(root, 'dem', './dem.tif')
        elems = root.findall('ElevationProperties')
        self.assertEqual(len(elems), 1)
        self.assertEqual(
            elems[0].find('terrainProvider').get('type'), 'raster')

    def test_survives_serialization(self):
        root = self._root()
        terrain_xml.inject_terrain(root, 'dem', './dem.tif', scale=3.0)
        text = ET.tostring(root, encoding='unicode')
        reparsed = ET.fromstring(text)
        provider = reparsed.find('ElevationProperties/terrainProvider')
        self.assertEqual(provider.get('scale'), '3')

    def test_number_formatting(self):
        self.assertEqual(terrain_xml._num(1.0), '1')
        self.assertEqual(terrain_xml._num(1.5), '1.5')
        self.assertEqual(terrain_xml._num(0), '0')


if __name__ == '__main__':
    unittest.main()
