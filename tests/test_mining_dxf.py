"""
Unit tests for mining_import/formats/dxf.py (pure python, no QGIS).

Fixtures are hand-written minimal DXF. The block-expansion cases matter most:
mine-package exports routinely wrap an entire drawing in one block and INSERT
it once at the origin, so a reader that treats an INSERT as a point silently
discards the whole file.
"""

import io
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pure_loader  # noqa: E402

dxf = pure_loader.load('formats/dxf.py')


def pairs(*items):
    """Build DXF text from (code, value) pairs."""
    out = []
    for code, value in items:
        out.append(str(code))
        out.append(str(value))
    return '\n'.join(out) + '\n'


def entities(body):
    return pairs((0, 'SECTION'), (2, 'ENTITIES')) + body + \
        pairs((0, 'ENDSEC'), (0, 'EOF'))


def parse(text, **kwargs):
    collector, truncated = dxf.parse_stream(io.StringIO(text), **kwargs)
    return collector


LWPOLY = pairs(
    (0, 'LWPOLYLINE'), (8, 'floor_1164'), (90, 3), (70, 0),
    (10, '398600.0'), (20, '6581300.0'),
    (10, '398610.0'), (20, '6581310.0'),
    (10, '398620.0'), (20, '6581320.0'),
    (38, '167.5'))

POLY3D = pairs(
    (0, 'POLYLINE'), (8, 'backs_1182'), (66, 1), (70, 8),
    (0, 'VERTEX'), (8, 'backs_1182'),
    (10, '398600.0'), (20, '6581300.0'), (30, '178.1'),
    (0, 'VERTEX'), (8, 'backs_1182'),
    (10, '398610.0'), (20, '6581310.0'), (30, '178.9'),
    (0, 'VERTEX'), (8, 'backs_1182'),
    (10, '398620.0'), (20, '6581320.0'), (30, '179.4'),
    (0, 'SEQEND'), (8, 'backs_1182'))

POLYFACE = pairs(
    (0, 'POLYLINE'), (8, 'solid_1200'), (66, 1), (70, 64),
    (0, 'VERTEX'), (8, 'solid_1200'), (70, 192),
    (10, '0.0'), (20, '0.0'), (30, '0.0'),
    (0, 'VERTEX'), (8, 'solid_1200'), (70, 192),
    (10, '10.0'), (20, '0.0'), (30, '0.0'),
    (0, 'VERTEX'), (8, 'solid_1200'), (70, 192),
    (10, '10.0'), (20, '10.0'), (30, '0.0'),
    (0, 'VERTEX'), (8, 'solid_1200'), (70, 192),
    (10, '0.0'), (20, '10.0'), (30, '0.0'),
    (0, 'VERTEX'), (8, 'solid_1200'), (70, 128),
    (10, '0.0'), (20, '0.0'), (30, '0.0'),
    (71, 1), (72, 2), (73, 3), (74, 4),
    (0, 'SEQEND'), (8, 'solid_1200'))


class TestLwPolyline(unittest.TestCase):

    def test_points_and_layer(self):
        c = parse(entities(LWPOLY))
        self.assertEqual(len(c.polylines), 1)
        poly = c.polylines[0]
        self.assertEqual(len(poly.points), 3)
        self.assertAlmostEqual(poly.points[0][0], 398600.0)
        self.assertAlmostEqual(poly.points[0][1], 6581300.0)
        self.assertEqual(poly.attrs['SrcLayer'], 'floor_1164')

    def test_code_38_elevation_applied_to_every_vertex(self):
        c = parse(entities(LWPOLY))
        for point in c.polylines[0].points:
            self.assertAlmostEqual(point[2], 167.5)

    def test_level_inferred_from_layer_name(self):
        c = parse(entities(LWPOLY))
        self.assertEqual(c.polylines[0].attrs['Level'], '1164')

    def test_closed_flag(self):
        body = LWPOLY.replace('70\n0\n', '70\n1\n')
        c = parse(entities(body))
        self.assertTrue(c.polylines[0].closed)

    def test_open_by_default(self):
        self.assertFalse(parse(entities(LWPOLY)).polylines[0].closed)

    def test_without_elevation_z_is_none(self):
        body = LWPOLY.replace('38\n167.5\n', '')
        c = parse(entities(body))
        self.assertIsNone(c.polylines[0].points[0][2])


class TestPolyline(unittest.TestCase):

    def test_vertices_with_per_point_z(self):
        c = parse(entities(POLY3D))
        self.assertEqual(len(c.polylines), 1)
        points = c.polylines[0].points
        self.assertEqual(len(points), 3)
        self.assertAlmostEqual(points[0][2], 178.1)
        self.assertAlmostEqual(points[2][2], 179.4)

    def test_layer_inherited_from_vertices_when_header_is_bare(self):
        # Some exporters put the layer only on the vertices; without this the
        # whole string loses its category.
        body = POLY3D.replace("0\nPOLYLINE\n8\nbacks_1182\n",
                              "0\nPOLYLINE\n")
        c = parse(entities(body))
        self.assertEqual(c.polylines[0].attrs['SrcLayer'], 'backs_1182')

    def test_missing_seqend_still_closes_the_polyline(self):
        body = POLY3D.replace(pairs((0, 'SEQEND'), (8, 'backs_1182')), '')
        c = parse(entities(body + LWPOLY))
        self.assertEqual(len(c.polylines), 2)


class TestPolyface(unittest.TestCase):

    def test_mesh_becomes_a_surface(self):
        c = parse(entities(POLYFACE))
        self.assertEqual(len(c.surfaces), 1)
        self.assertEqual(len(c.surfaces[0].vertices), 4)

    def test_quad_face_split_into_two_triangles(self):
        surface = parse(entities(POLYFACE)).surfaces[0]
        self.assertEqual(surface.triangles, [(0, 1, 2), (0, 2, 3)])

    def test_face_indices_are_one_based_in_the_file(self):
        surface = parse(entities(POLYFACE)).surfaces[0]
        for tri in surface.triangles:
            for index in tri:
                self.assertTrue(0 <= index < len(surface.vertices))

    def test_negative_indices_mark_invisible_edges_not_missing_vertices(self):
        body = POLYFACE.replace('72\n2\n', '72\n-2\n')
        surface = parse(entities(body)).surfaces[0]
        self.assertEqual(surface.triangles, [(0, 1, 2), (0, 2, 3)])

    def test_mesh_is_not_also_emitted_as_a_polyline(self):
        c = parse(entities(POLYFACE))
        self.assertEqual(len(c.polylines), 0)


class TestSimpleEntities(unittest.TestCase):

    def test_line(self):
        body = pairs((0, 'LINE'), (8, 'drive'),
                     (10, '1.0'), (20, '2.0'), (30, '3.0'),
                     (11, '4.0'), (21, '5.0'), (31, '6.0'))
        c = parse(entities(body))
        self.assertEqual(len(c.polylines), 1)
        self.assertEqual(len(c.polylines[0].points), 2)
        self.assertAlmostEqual(c.polylines[0].points[1][0], 4.0)

    def test_point_becomes_a_station(self):
        body = pairs((0, 'POINT'), (8, 'pegs'),
                     (10, '398600.0'), (20, '6581300.0'), (30, '167.0'))
        c = parse(entities(body))
        self.assertEqual(len(c.stations), 1)
        self.assertAlmostEqual(c.stations[0].point[2], 167.0)

    def test_3dface(self):
        body = pairs((0, '3DFACE'), (8, 'topo'),
                     (10, '0.0'), (20, '0.0'), (30, '1.0'),
                     (11, '1.0'), (21, '0.0'), (31, '1.0'),
                     (12, '1.0'), (22, '1.0'), (32, '1.0'),
                     (13, '0.0'), (23, '1.0'), (33, '1.0'))
        c = parse(entities(body))
        self.assertEqual(len(c.surfaces), 1)
        self.assertEqual(c.surfaces[0].triangles, [(0, 1, 2), (0, 2, 3)])

    def test_text_becomes_an_annotation(self):
        body = pairs((0, 'TEXT'), (8, 'labels'),
                     (10, '10.0'), (20, '20.0'), (30, '5.0'),
                     (40, '2.5'), (1, '1164 Level'))
        c = parse(entities(body))
        self.assertEqual(len(c.annotations), 1)
        self.assertEqual(c.annotations[0].text, '1164 Level')
        self.assertAlmostEqual(c.annotations[0].attrs['Height'], 2.5)

    def test_mtext_formatting_codes_stripped(self):
        body = pairs((0, 'MTEXT'), (8, 'labels'),
                     (10, '0.0'), (20, '0.0'),
                     (1, '\\pxqc;{\\fArial|b0;1200 Level}'))
        c = parse(entities(body))
        self.assertIn('1200 Level', c.annotations[0].text)

    def test_unknown_entity_counted_not_crashed(self):
        body = pairs((0, 'HELIX'), (8, 'x'), (10, '1.0'), (20, '2.0'))
        c = parse(entities(body + LWPOLY))
        self.assertEqual(c.skipped.get('HELIX'), 1)
        self.assertEqual(len(c.polylines), 1)


BLOCK_FILE = (
    pairs((0, 'SECTION'), (2, 'BLOCKS'),
          (0, 'BLOCK'), (2, 'DRIVES'), (10, '0.0'), (20, '0.0'), (30, '0.0'))
    + LWPOLY
    + pairs((0, 'ENDBLK'), (0, 'ENDSEC'))
    + pairs((0, 'SECTION'), (2, 'ENTITIES'),
            (0, 'INSERT'), (2, 'DRIVES'), (8, 'all_drives'),
            (10, '1000.0'), (20, '2000.0'), (30, '0.0'))
    + pairs((0, 'ENDSEC'), (0, 'EOF')))


class TestBlocks(unittest.TestCase):

    def test_insert_expands_the_block(self):
        # MP_All Drives.DXF is 5 MB of geometry inside one block referenced by
        # a single INSERT; treating that INSERT as a point loses the file.
        c = parse(BLOCK_FILE)
        self.assertEqual(len(c.polylines), 1)
        self.assertEqual(len(c.polylines[0].points), 3)

    def test_block_geometry_is_translated_to_the_insertion_point(self):
        c = parse(BLOCK_FILE)
        point = c.polylines[0].points[0]
        self.assertAlmostEqual(point[0], 398600.0 + 1000.0)
        self.assertAlmostEqual(point[1], 6581300.0 + 2000.0)

    def test_base_point_is_subtracted(self):
        shifted = BLOCK_FILE.replace(
            pairs((0, 'BLOCK'), (2, 'DRIVES'), (10, '0.0'), (20, '0.0'),
                  (30, '0.0')),
            pairs((0, 'BLOCK'), (2, 'DRIVES'), (10, '398600.0'),
                  (20, '6581300.0'), (30, '0.0')))
        c = parse(shifted)
        point = c.polylines[0].points[0]
        self.assertAlmostEqual(point[0], 1000.0)
        self.assertAlmostEqual(point[1], 2000.0)

    def test_rotation_applied(self):
        rotated = BLOCK_FILE.replace(
            pairs((10, '1000.0'), (20, '2000.0'), (30, '0.0')),
            pairs((10, '0.0'), (20, '0.0'), (30, '0.0'), (50, '90')))
        c = parse(rotated)
        point = c.polylines[0].points[0]
        # (398600, 6581300) rotated 90 deg about the origin.
        self.assertAlmostEqual(point[0], -6581300.0, places=3)
        self.assertAlmostEqual(point[1], 398600.0, places=3)

    def test_scale_applied(self):
        scaled = BLOCK_FILE.replace(
            pairs((10, '1000.0'), (20, '2000.0'), (30, '0.0')),
            pairs((10, '0.0'), (20, '0.0'), (30, '0.0'),
                  (41, '2.0'), (42, '2.0'), (43, '2.0')))
        c = parse(scaled)
        self.assertAlmostEqual(c.polylines[0].points[0][0], 398600.0 * 2)

    def test_insert_of_an_empty_block_becomes_a_station(self):
        # A survey peg symbol: the reference IS the surveyed position.
        text = (pairs((0, 'SECTION'), (2, 'BLOCKS'),
                      (0, 'BLOCK'), (2, 'PEG'), (10, '0.0'), (20, '0.0'))
                + pairs((0, 'ENDBLK'), (0, 'ENDSEC'))
                + pairs((0, 'SECTION'), (2, 'ENTITIES'),
                        (0, 'INSERT'), (2, 'PEG'), (8, 'ClipPegs'),
                        (10, '398600.0'), (20, '6581300.0'), (30, '167.0'))
                + pairs((0, 'ENDSEC'), (0, 'EOF')))
        c = parse(text)
        self.assertEqual(len(c.stations), 1)
        self.assertAlmostEqual(c.stations[0].point[0], 398600.0)
        self.assertEqual(c.stations[0].attrs['Code'], 'PEG')

    def test_insert_of_an_unknown_block_becomes_a_station(self):
        text = entities(pairs(
            (0, 'INSERT'), (2, 'NOT_DEFINED'), (8, 'x'),
            (10, '5.0'), (20, '6.0')))
        c = parse(text)
        self.assertEqual(len(c.stations), 1)

    def test_nested_insert_keeps_its_scale(self):
        # An INSERT inside an expanded block carries its own 41/42/43; the
        # clone taken during expansion must keep them or the inner geometry
        # silently imports unscaled.
        text = (pairs((0, 'SECTION'), (2, 'BLOCKS'),
                      (0, 'BLOCK'), (2, 'INNER'), (10, '0.0'), (20, '0.0'))
                + pairs((0, 'LINE'), (8, 'd'),
                        (10, '0.0'), (20, '0.0'), (11, '10.0'), (21, '0.0'))
                + pairs((0, 'ENDBLK'),
                        (0, 'BLOCK'), (2, 'OUTER'), (10, '0.0'), (20, '0.0'),
                        (0, 'INSERT'), (2, 'INNER'), (8, 'd'),
                        (10, '0.0'), (20, '0.0'),
                        (41, '2.0'), (42, '2.0'), (43, '2.0'),
                        (0, 'ENDBLK'), (0, 'ENDSEC'))
                + pairs((0, 'SECTION'), (2, 'ENTITIES'),
                        (0, 'INSERT'), (2, 'OUTER'), (8, 'd'),
                        (10, '0.0'), (20, '0.0'),
                        (0, 'ENDSEC'), (0, 'EOF')))
        c = parse(text)
        self.assertEqual(len(c.polylines), 1)
        self.assertAlmostEqual(c.polylines[0].points[1][0], 20.0)

    def test_block_entities_are_not_imported_at_the_origin(self):
        # Without the BLOCKS section being kept separate from ENTITIES, the
        # block body would be imported twice: once at 0,0 and once in place.
        c = parse(BLOCK_FILE)
        self.assertEqual(len(c.polylines), 1)


class TestLayerRouting(unittest.TestCase):

    def test_peg_layer_routes_a_polyline_to_stations(self):
        body = LWPOLY.replace('floor_1164', 'survey_pegs')
        c = parse(entities(body))
        self.assertEqual(len(c.polylines), 0)
        self.assertEqual(len(c.stations), 3)

    def test_text_layer_token(self):
        kind, _level = dxf.apply_layer_rules('drive_annotation')
        self.assertEqual(kind, 'text')

    def test_custom_rule_wins(self):
        kind, level = dxf.apply_layer_rules(
            'ODD_NAME', [(r'ODD', 'stations', '1200')])
        self.assertEqual((kind, level), ('stations', '1200'))

    def test_level_from_layer_name(self):
        self.assertEqual(dxf.level_from_layer('mga_mj_1238'), '1238')
        self.assertIsNone(dxf.level_from_layer('drives'))


class TestFileLevelBehaviour(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, text, name='sample.dxf', mode='w'):
        path = os.path.join(self.dir, name)
        # newline='' so a CRLF fixture stays CRLF instead of becoming CRCRLF
        # under Windows text-mode translation.
        kwargs = {} if 'b' in mode else {'newline': ''}
        with open(path, mode, **kwargs) as fh:
            fh.write(text)
        return path

    def test_read_file_end_to_end(self):
        parsed = dxf.read_file(self._write(entities(LWPOLY)))
        self.assertEqual(parsed.format_key, 'dxf')
        self.assertEqual(len(parsed.polylines), 1)
        self.assertIn('floor_1164', parsed.attrs['layers'])

    def test_layer_level_beats_the_filename_level(self):
        parsed = dxf.read_file(self._write(entities(LWPOLY)), level='9999')
        self.assertEqual(parsed.polylines[0].attrs['Level'], '1164')

    def test_filename_level_used_when_the_layer_has_none(self):
        body = LWPOLY.replace('floor_1164', 'drives')
        parsed = dxf.read_file(self._write(entities(body)), level='9999')
        self.assertEqual(parsed.polylines[0].attrs['Level'], '9999')

    def test_binary_dxf_is_refused_with_a_useful_message(self):
        path = self._write(b'AutoCAD Binary DXF\r\n\x1a\x00rest',
                           name='bin.dxf', mode='wb')
        self.assertTrue(dxf.is_binary(path))
        with self.assertRaises(RuntimeError) as caught:
            dxf.read_file(path)
        self.assertIn('binary', str(caught.exception).lower())

    def test_truncated_file_yields_what_it_has(self):
        text = entities(LWPOLY)[:-20]
        parsed = dxf.read_file(self._write(text))
        self.assertEqual(len(parsed.polylines), 1)

    def test_max_entities_guard_reports_rather_than_silently_truncating(self):
        parsed = dxf.read_file(
            self._write(entities(LWPOLY * 5)), max_entities=2)
        self.assertTrue(any('import limit' in w for w in parsed.warnings))

    def test_crlf_and_padded_group_codes(self):
        text = entities(LWPOLY).replace('\n', '\r\n')
        text = text.replace('\r\n8\r\n', '\r\n  8\r\n')
        parsed = dxf.read_file(self._write(text))
        self.assertEqual(parsed.polylines[0].attrs['SrcLayer'], 'floor_1164')

    def test_sniff(self):
        self.assertGreater(dxf.sniff(self._write(entities(LWPOLY))), 0.5)

    def test_empty_file_warns(self):
        parsed = dxf.read_file(self._write(entities('')))
        self.assertTrue(any('no drawable' in w for w in parsed.warnings))


if __name__ == '__main__':
    unittest.main()
