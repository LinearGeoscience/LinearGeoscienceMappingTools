"""
Unit tests for mining_import/formats/ogrvector.py (shapefile + GeoPackage).

The sniffer tests are pure stdlib — fixtures are built with struct and
sqlite3, so they run anywhere. The reader tests need GDAL's python bindings
to generate real shapefile/GeoPackage fixtures at test time (no binary
fixtures live in the repo) and are skipped where osgeo is unavailable.
"""

import importlib.util
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pure_loader  # noqa: E402

ogrvector = pure_loader.load('formats/ogrvector.py')
registry = pure_loader.load('registry.py')
scan = pure_loader.load('scan.py')

HAVE_OSGEO = importlib.util.find_spec('osgeo') is not None


def write_shp_magic(path):
    with open(path, 'wb') as fh:
        fh.write(struct.pack('>i', 9994) + b'\x00' * 96)
    return path


def write_gpkg(path, with_log_table=False):
    """A real SQLite file with the GeoPackage application id."""
    con = sqlite3.connect(path)
    con.execute('PRAGMA application_id = {0}'.format(0x47504B47))
    con.execute('CREATE TABLE gpkg_contents (table_name TEXT)')
    if with_log_table:
        con.execute('CREATE TABLE lgs_mining_import_log (source_key TEXT)')
    con.commit()
    con.close()
    return path


class TestSniffShp(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def test_magic_number_is_accepted(self):
        path = write_shp_magic(os.path.join(self.base, 'a.shp'))
        self.assertGreaterEqual(ogrvector.sniff_shp(path), 0.9)

    def test_not_a_shapefile_is_rejected(self):
        path = os.path.join(self.base, 'b.shp')
        with open(path, 'wb') as fh:
            fh.write(b'not a shapefile at all')
        self.assertEqual(ogrvector.sniff_shp(path), 0.0)

    def test_missing_file_is_rejected(self):
        self.assertEqual(
            ogrvector.sniff_shp(os.path.join(self.base, 'gone.shp')), 0.0)


class TestSniffGpkg(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def test_plain_geopackage_is_accepted(self):
        path = write_gpkg(os.path.join(self.base, 'survey.gpkg'))
        self.assertGreaterEqual(ogrvector.sniff_gpkg(path), 0.9)

    def test_own_output_is_vetoed(self):
        # A GeoPackage containing the import log IS this importer's product;
        # scanning it back in would loop the output into the input.
        path = write_gpkg(os.path.join(self.base, 'mine_data.gpkg'),
                          with_log_table=True)
        self.assertEqual(ogrvector.sniff_gpkg(path), 0.0)

    def test_non_sqlite_is_rejected(self):
        path = os.path.join(self.base, 'fake.gpkg')
        with open(path, 'wb') as fh:
            fh.write(b'x' * 100)
        self.assertEqual(ogrvector.sniff_gpkg(path), 0.0)

    def test_resolve_format_does_not_claim_own_output(self):
        # Pins the veto mechanism end to end: sniff_gpkg scores 0.0 and the
        # spec's min_confidence floor (0.2) stops the unique-extension
        # fallback from claiming the file anyway.
        own = write_gpkg(os.path.join(self.base, 'mine_data.gpkg'),
                         with_log_table=True)
        candidates = registry.formats_for_extension('.gpkg')
        self.assertIsNone(scan._resolve_format(own, candidates))

    def test_resolve_format_claims_a_real_geopackage(self):
        other = write_gpkg(os.path.join(self.base, 'contractor.gpkg'))
        candidates = registry.formats_for_extension('.gpkg')
        self.assertEqual(scan._resolve_format(other, candidates),
                         'geopackage')


@unittest.skipUnless(HAVE_OSGEO, 'GDAL python bindings not available')
class OgrFixtureCase(unittest.TestCase):
    """Base: builds OGR datasets into a per-test temp folder."""

    def setUp(self):
        from osgeo import ogr
        self.ogr = ogr
        self.base = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def make_layer(self, ds, name, geom_type, fields=(), srs=None):
        ogr = self.ogr
        layer = ds.CreateLayer(name, srs, geom_type)
        for fname, ftype in fields:
            layer.CreateField(ogr.FieldDefn(fname, ftype))
        return layer

    def add_feature(self, layer, wkt, **field_values):
        ogr = self.ogr
        feat = ogr.Feature(layer.GetLayerDefn())
        feat.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
        for fname, value in field_values.items():
            feat.SetField(fname, value)
        layer.CreateFeature(feat)
        feat = None

    def create_shp(self, name):
        path = os.path.join(self.base, name)
        drv = self.ogr.GetDriverByName('ESRI Shapefile')
        return path, drv.CreateDataSource(path)

    def create_gpkg(self, name):
        path = os.path.join(self.base, name)
        drv = self.ogr.GetDriverByName('GPKG')
        return path, drv.CreateDataSource(path)


class TestShapefileStrings(OgrFixtureCase):

    def build(self, **read_kwargs):
        ogr = self.ogr
        path, ds = self.create_shp('dev_strings_1164.shp')
        layer = self.make_layer(
            ds, 'dev_strings_1164', ogr.wkbLineString25D,
            fields=[('Level', ogr.OFTString), ('StringNo', ogr.OFTInteger),
                    ('Surveyor', ogr.OFTString),
                    ('SourceFile', ogr.OFTString),
                    ('Comment', ogr.OFTString)])
        self.add_feature(
            layer, 'LINESTRING Z (100 200 50, 110 200 51, 120 200 52)',
            Level='1164', StringNo=2, Surveyor='Zane',
            SourceFile='mga_mj_1164.str', Comment='floor pickup')
        ds = None
        return ogrvector.read_file(path, **read_kwargs)

    def test_line_becomes_a_polyline_with_z(self):
        parsed = self.build()
        self.assertEqual(parsed.format_key, 'shapefile')
        self.assertEqual(len(parsed.polylines), 1)
        self.assertEqual(len(parsed.stations), 0)
        poly = parsed.polylines[0]
        self.assertEqual(poly.points[0], (100.0, 200.0, 50.0))
        self.assertEqual(poly.points[-1], (120.0, 200.0, 52.0))
        self.assertFalse(poly.closed)

    def test_schema_fields_map_and_extras_stay_free_form(self):
        poly = self.build().polylines[0]
        self.assertEqual(poly.attrs['Level'], '1164')
        self.assertEqual(poly.attrs['StringNo'], 2)
        self.assertEqual(poly.attrs['Surveyor'], 'Zane')
        self.assertEqual(poly.attrs['Comment'], 'floor pickup')

    def test_provenance_columns_can_never_be_shadowed(self):
        # A SourceFile column in the data (typical of a re-exported survey)
        # must not override the provenance build.py stamps.
        poly = self.build().polylines[0]
        self.assertNotIn('SourceFile', poly.attrs)
        self.assertEqual(poly.attrs['sourcefile'], 'mga_mj_1164.str')

    def test_srclayer_and_level_come_from_the_file_name(self):
        poly = self.build().polylines[0]
        self.assertEqual(poly.attrs['SrcLayer'], 'dev_strings_1164')

    def test_field_level_beats_the_level_argument(self):
        poly = self.build(level='9999').polylines[0]
        self.assertEqual(poly.attrs['Level'], '1164')

    def test_kind_stations_flattens_the_line_to_its_vertices(self):
        parsed = self.build(kind='stations')
        self.assertEqual(len(parsed.polylines), 0)
        self.assertEqual(len(parsed.stations), 3)
        self.assertEqual(parsed.stations[0].point, (100.0, 200.0, 50.0))


class TestShapefileStations(OgrFixtureCase):

    def build(self):
        ogr = self.ogr
        path, ds = self.create_shp('pickups.shp')
        layer = self.make_layer(
            ds, 'pickups', ogr.wkbPoint,
            fields=[('NAME', ogr.OFTString), ('RL', ogr.OFTReal),
                    ('CODE', ogr.OFTString)])
        self.add_feature(layer, 'POINT (398663 6581316)',
                         NAME='MJ33', RL=42.5, CODE='PEG')
        ds = None
        return ogrvector.read_file(path)

    def test_point_becomes_a_station(self):
        parsed = self.build()
        self.assertEqual(len(parsed.stations), 1)
        self.assertEqual(len(parsed.polylines), 0)

    def test_aliases_map_and_elevation_field_supplies_z(self):
        station = self.build().stations[0]
        self.assertEqual(station.attrs['PointId'], 'MJ33')
        self.assertEqual(station.attrs['Code'], 'PEG')
        self.assertEqual(station.point[2], 42.5)


class TestPolygonsAndTokens(OgrFixtureCase):

    def test_polygon_rings_become_closed_polylines(self):
        ogr = self.ogr
        path, ds = self.create_shp('outline_1200.shp')
        layer = self.make_layer(ds, 'outline_1200', ogr.wkbPolygon)
        self.add_feature(
            layer, 'POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))')
        ds = None
        parsed = ogrvector.read_file(path)
        self.assertEqual(len(parsed.polylines), 1)
        self.assertTrue(parsed.polylines[0].closed)
        self.assertEqual(len(parsed.polylines[0].points), 5)

    def test_peg_token_in_the_name_routes_lines_to_stations(self):
        ogr = self.ogr
        path, ds = self.create_shp('pegs_1164.shp')
        layer = self.make_layer(ds, 'pegs_1164', ogr.wkbLineString25D)
        self.add_feature(layer, 'LINESTRING Z (0 0 5, 1 0 5)')
        ds = None
        parsed = ogrvector.read_file(path)
        self.assertEqual(len(parsed.polylines), 0)
        self.assertEqual(len(parsed.stations), 2)

    def test_kind_strings_overrides_the_token_routing(self):
        ogr = self.ogr
        path, ds = self.create_shp('pegs_1218.shp')
        layer = self.make_layer(ds, 'pegs_1218', ogr.wkbLineString25D)
        self.add_feature(layer, 'LINESTRING Z (0 0 5, 1 0 5)')
        ds = None
        parsed = ogrvector.read_file(path, kind='strings')
        self.assertEqual(len(parsed.polylines), 1)
        self.assertEqual(len(parsed.stations), 0)


class TestGeoPackage(OgrFixtureCase):

    def test_all_layers_fold_into_one_parsed_file(self):
        ogr = self.ogr
        path, ds = self.create_gpkg('survey.gpkg')
        lines = self.make_layer(ds, 'dev_1164', ogr.wkbLineString25D)
        self.add_feature(lines, 'LINESTRING Z (0 0 10, 5 0 10)')
        points = self.make_layer(ds, 'control', ogr.wkbPoint25D)
        self.add_feature(points, 'POINT Z (2 2 12)')
        self.make_layer(ds, 'notes_table', ogr.wkbNone)  # attribute table
        ds = None

        parsed = ogrvector.read_file(path)
        self.assertEqual(parsed.format_key, 'geopackage')
        self.assertEqual(len(parsed.polylines), 1)
        self.assertEqual(len(parsed.stations), 1)
        self.assertEqual(parsed.polylines[0].attrs['SrcLayer'], 'dev_1164')
        self.assertEqual(parsed.polylines[0].attrs['Level'], '1164')
        self.assertEqual(parsed.stations[0].attrs['SrcLayer'], 'control')
        self.assertIn('notes_table', parsed.attrs['skipped_layers'])

    def test_geographic_crs_warns_but_still_imports(self):
        ogr = self.ogr
        from osgeo import osr
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        path, ds = self.create_gpkg('latlon.gpkg')
        layer = self.make_layer(ds, 'points', ogr.wkbPoint, srs=srs)
        self.add_feature(layer, 'POINT (121.5 -30.7)')
        ds = None

        parsed = ogrvector.read_file(path)
        self.assertEqual(len(parsed.stations), 1)
        self.assertTrue(any('geographic' in w for w in parsed.warnings))

    def test_empty_dataset_warns(self):
        ogr = self.ogr
        path, ds = self.create_gpkg('empty.gpkg')
        self.make_layer(ds, 'nothing', ogr.wkbLineString)
        ds = None
        parsed = ogrvector.read_file(path)
        self.assertTrue(
            any('no drawable' in w for w in parsed.warnings))


if __name__ == '__main__':
    unittest.main()
