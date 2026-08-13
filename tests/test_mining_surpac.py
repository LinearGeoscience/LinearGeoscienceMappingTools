"""
Unit tests for mining_import/formats/surpac.py (pure python, no QGIS).

Ports every test from the previous tests/test_surpac_parser.py, and adds the
station routing that replaced the old "single-point segments are counted and
discarded" behaviour.

Run from the plugin root:
    python -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pure_loader  # noqa: E402

surpac = pure_loader.load('formats/surpac.py')
scan = pure_loader.load('scan.py')

parse_str_lines = surpac.parse_str_lines
parse_dtm_lines = surpac.parse_dtm_lines
parse_level_from_filename = scan.parse_level_from_filename


# Trimmed from a real survey export: header, axis record, two drawn strings
# and one lone station record between them.
STR_SAMPLE = """mga_floor_1164,01-May-26,2D transformation of,·
0,     6551152.842,      392596.568,           0.000,     6551152.842,      392596.568,           0.000
20, 6581330.366, 398672.474, 167.739, 288, 26.04.26 10:33:48, Darby Lindsay, TS16 A 3 R500, 3217085, 260426-1164
20, 6581326.834, 398672.402, 167.184, 289, 26.04.26 10:33:48, Darby Lindsay, TS16 A 3 R500, 3217085, 260426-1164
0, 0.000, 0.000, 0.000,
7, 6581300.100, 398600.200, 160.500, 401, 25.04.26 09:00:00, Ana Ruiz, TS15 B 1 R400, 9911002, 260425-STN
0, 0.000, 0.000, 0.000,
4, 6581328.306, 398672.983, 167.429, 297, 25.04.26 14:07:52, Darby Lindsay, TS16 A 3 R500, 3217085, 260425-1164
4, 6581331.262, 398673.752, 167.845, 298, 25.04.26 14:07:52, Darby Lindsay, TS16 A 3 R500, 3217085, 260425-1164
4, 6581336.280, 398670.986, 168.636, 299, 25.04.26 14:07:52, Darby Lindsay, TS16 A 3 R500, 3217085, 260425-1164
0, 0.000, 0.000, 0.000,
0, 0.000, 0.000, 0.000, END
""".replace('·', ' ').splitlines()

DTM_SAMPLE = """mga_mj_1164.str,1643895000;algorithm=standard;fields=x,y
0, 0.000, 0.000, 0.000, END
OBJECT, 1,·
TRISOLATION, 1, neighbours=yes,validated=true,closed=yes,direction=solid,algorithm=retriangulation
1, 768, 997, 998, 2, 3, 8,·
2, 768, 769, 997, 2907, 62, 1,·
3, 998, 997, 1091, 1, 7, 6,·
END
""".replace('·', ' ').splitlines()


class TestLevelParsing(unittest.TestCase):

    def test_trailing_digits(self):
        self.assertEqual(parse_level_from_filename('mga_floor_1164.str'),
                         '1164')
        self.assertEqual(parse_level_from_filename('mga_mj_1218.str'), '1218')
        self.assertEqual(parse_level_from_filename('stn1244.str'), '1244')

    def test_no_trailing_digits_falls_back_to_stem(self):
        self.assertEqual(parse_level_from_filename('notes.str'), 'notes')

    def test_full_path_uses_basename(self):
        self.assertEqual(
            parse_level_from_filename(r'C:\survey\2026\mga_floor_1164.str'),
            '1164')


class TestParseStr(unittest.TestCase):

    def setUp(self):
        (self.polylines, self.stations, self.flat, self.warnings,
         self.info) = parse_str_lines(STR_SAMPLE, name='sample.str')

    def test_segments_split_on_separators(self):
        self.assertEqual(len(self.polylines), 2)
        self.assertEqual(len(self.polylines[0].points), 2)
        self.assertEqual(len(self.polylines[1].points), 3)

    def test_northing_easting_swapped(self):
        x, y, z = self.polylines[0].points[0]
        self.assertAlmostEqual(x, 398672.474)
        self.assertAlmostEqual(y, 6581330.366)
        self.assertAlmostEqual(z, 167.739)

    def test_axis_record_excluded_despite_leading_zero(self):
        # The axis record starts with 0 but carries real coordinates; if it
        # were treated as data its easting would show up in the points.
        for point in self.flat:
            self.assertNotAlmostEqual(point[0], 392596.568, places=3)

    def test_string_number_and_metadata_from_first_point(self):
        attrs = self.polylines[0].attrs
        self.assertEqual(attrs['StringNo'], 20)
        self.assertEqual(attrs['PointId'], '288')
        self.assertEqual(attrs['SurveyDate'], '26.04.26 10:33:48')
        self.assertEqual(attrs['Surveyor'], 'Darby Lindsay')
        self.assertEqual(attrs['Instrument'], 'TS16 A 3 R500')
        self.assertEqual(attrs['InstrSerial'], '3217085')
        self.assertEqual(attrs['JobCode'], '260426-1164')

    def test_point_count_recorded(self):
        self.assertEqual(self.polylines[1].attrs['PointCount'], 3)

    def test_flat_points_in_file_order_and_include_stations(self):
        # The .dtm indexes into every real point record in file order, so a
        # point routed to a station must still occupy its slot.
        self.assertEqual(len(self.flat), 6)
        self.assertEqual(self.flat[0], self.polylines[0].points[0])
        self.assertAlmostEqual(self.flat[2][0], 398600.200)

    def test_end_terminates_parsing(self):
        lines = list(STR_SAMPLE) + [
            '9, 6581400.000, 398700.000, 170.000, 500']
        polylines, _stations, flat, _warnings, _info = parse_str_lines(
            lines)
        self.assertEqual(len(polylines), 2)
        self.assertEqual(len(flat), 6)

    def test_unterminated_file_flushes_last_segment(self):
        lines = [line for line in STR_SAMPLE if 'END' not in line]
        polylines, _stations, _flat, _warnings, _info = parse_str_lines(
            lines)
        self.assertEqual(len(polylines), 2)

    def test_malformed_lines_skipped_and_reported(self):
        lines = list(STR_SAMPLE)
        lines.insert(4, 'garbage line')
        lines.insert(5, '20, not_a_number, 1.0, 2.0')
        polylines, _stations, _flat, warnings, _info = parse_str_lines(
            lines, name='sample.str')
        self.assertEqual(len(polylines), 2)
        self.assertTrue(any('malformed' in w for w in warnings))

    def test_consecutive_separators_are_harmless(self):
        lines = list(STR_SAMPLE)
        lines.insert(5, '0, 0.000, 0.000, 0.000,')
        polylines, _stations, _flat, _warnings, _info = parse_str_lines(
            lines)
        self.assertEqual(len(polylines), 2)


class TestStationRouting(unittest.TestCase):
    """Single-point segments used to be counted and thrown away."""

    def setUp(self):
        (self.polylines, self.stations, _flat, _warnings,
         self.info) = parse_str_lines(STR_SAMPLE, name='sample.str')

    def test_single_point_segment_becomes_a_station(self):
        self.assertEqual(len(self.stations), 1)
        x, y, z = self.stations[0].point
        self.assertAlmostEqual(x, 398600.200)
        self.assertAlmostEqual(y, 6581300.100)
        self.assertAlmostEqual(z, 160.500)

    def test_station_keeps_its_own_metadata(self):
        # Not the surrounding strings' surveyor -- this is the whole point of
        # per-point attrs rather than one sample per segment.
        attrs = self.stations[0].attrs
        self.assertEqual(attrs['Surveyor'], 'Ana Ruiz')
        self.assertEqual(attrs['PointId'], '401')
        self.assertEqual(attrs['Instrument'], 'TS15 B 1 R400')
        self.assertEqual(attrs['JobCode'], '260425-STN')
        self.assertEqual(attrs['StringNo'], 7)

    def test_station_is_not_also_a_polyline(self):
        for poly in self.polylines:
            self.assertGreaterEqual(len(poly.points), 2)

    def test_station_file_routes_every_segment_to_stations(self):
        polylines, stations, _flat, _warnings, _info = parse_str_lines(
            STR_SAMPLE, name='stn1244.str', kind=surpac.KIND_STATIONS)
        self.assertEqual(polylines, [])
        self.assertEqual(len(stations), 6)

    def test_station_names_matched_as_substrings_not_prefixes(self):
        # The prefix-only test that shipped first missed the real file,
        # 'mga_all_stations.str', and sent 102 stations down the linework
        # path as six level-spanning polylines.
        self.assertTrue(surpac.name_suggests_stations('stn1244.str'))
        self.assertTrue(surpac.name_suggests_stations(r'C:\x\STATION_1244.str'))
        self.assertTrue(surpac.name_suggests_stations('pickup_365.str'))
        self.assertTrue(
            surpac.name_suggests_stations('mga_all_stations.str'))
        self.assertFalse(surpac.name_suggests_stations('mga_floor_1164.str'))

    def test_parent_folder_name_counts_too(self):
        self.assertTrue(surpac.name_suggests_stations(
            os.path.join('C:', 'survey', 'StationsGDA', 'mga_all.str')))
        self.assertFalse(surpac.name_suggests_stations(
            os.path.join('C:', 'survey', 'FloorStringsGDA', 'mga_all.str')))

    def test_per_point_metadata_preserved_across_a_station_file(self):
        _polylines, stations, _flat, _warnings, _info = parse_str_lines(
            STR_SAMPLE, kind=surpac.KIND_STATIONS)
        surveyors = [s.attrs.get('Surveyor') for s in stations]
        self.assertIn('Ana Ruiz', surveyors)
        self.assertIn('Darby Lindsay', surveyors)
        point_ids = [s.attrs.get('PointId') for s in stations]
        self.assertEqual(len(set(point_ids)), 6)


class TestDFields(unittest.TestCase):

    def test_named_positions(self):
        attrs = surpac.parse_d_fields(
            ['288', '26.04.26 10:33:48', 'Darby Lindsay', 'TS16', '3217085',
             '260426-1164'])
        self.assertEqual(attrs['PointId'], '288')
        self.assertEqual(attrs['JobCode'], '260426-1164')

    def test_extra_fields_kept_positionally(self):
        attrs = surpac.parse_d_fields(['1', '2', '3', '4', '5', '6', 'extra'])
        self.assertEqual(attrs['D7'], 'extra')

    def test_empty_fields_dropped(self):
        attrs = surpac.parse_d_fields(['288', '', '  ', 'TS16'])
        self.assertNotIn('SurveyDate', attrs)
        self.assertNotIn('Surveyor', attrs)
        self.assertEqual(attrs['PointId'], '288')
        self.assertEqual(attrs['Instrument'], 'TS16')

    def test_every_field_also_kept_positionally(self):
        # A mis-detected profile must never lose data: D1..Dn always carry
        # the raw export into the Attributes JSON column.
        attrs = surpac.parse_d_fields(['288', '2026-01-18', 'Ana'])
        self.assertEqual(attrs['D1'], '288')
        self.assertEqual(attrs['D2'], '2026-01-18')
        self.assertEqual(attrs['D3'], 'Ana')


class TestParseDtm(unittest.TestCase):

    def test_triangles_converted_to_zero_based(self):
        # Surpac stores 1-based indices; converting in the reader means the
        # QGIS side never has to know which format a surface came from.
        self.assertEqual(parse_dtm_lines(DTM_SAMPLE),
                         [(767, 996, 997), (767, 768, 996), (997, 996, 1090)])

    def test_preamble_not_mistaken_for_triangles(self):
        self.assertEqual(len(parse_dtm_lines(DTM_SAMPLE)), 3)

    def test_no_trisolation_yields_nothing(self):
        self.assertEqual(parse_dtm_lines(['header', '0, 0, 0, 0, END']), [])


class TestReadFile(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.str_path = os.path.join(self.dir, 'mga_floor_1164.str')
        with open(self.str_path, 'w') as fh:
            fh.write('\n'.join(STR_SAMPLE) + '\n')

    def test_read_file_shape(self):
        parsed = surpac.read_file(self.str_path, level='1164')
        self.assertEqual(parsed.format_key, 'surpac')
        self.assertEqual(parsed.name, 'mga_floor_1164.str')
        self.assertEqual(len(parsed.polylines), 2)
        self.assertEqual(len(parsed.stations), 1)
        self.assertEqual(parsed.surfaces, ())

    def test_level_stamped_on_every_feature(self):
        parsed = surpac.read_file(self.str_path, level='1164')
        self.assertTrue(all(p.attrs['Level'] == '1164'
                            for p in parsed.polylines))
        self.assertTrue(all(s.attrs['Level'] == '1164'
                            for s in parsed.stations))

    def test_dtm_companion_produces_a_surface(self):
        dtm_path = os.path.join(self.dir, 'mga_floor_1164.dtm')
        with open(dtm_path, 'w') as fh:
            fh.write('header\nOBJECT, 1,\nTRISOLATION, 1,\n'
                     '1, 1, 2, 3, 0, 0, 0,\n'
                     '2, 4, 5, 6, 0, 0, 0,\n0, 0, 0, 0\n')
        parsed = surpac.read_file(
            self.str_path, companions={'.dtm': dtm_path}, level='1164')
        self.assertEqual(len(parsed.surfaces), 1)
        surface = parsed.surfaces[0]
        self.assertEqual(surface.triangles, [(0, 1, 2), (3, 4, 5)])
        self.assertEqual(len(surface.vertices), 6)
        self.assertEqual(surface.attrs['TriangleCount'], 2)

    def test_out_of_range_triangles_dropped_with_a_warning(self):
        dtm_path = os.path.join(self.dir, 'mga_floor_1164.dtm')
        with open(dtm_path, 'w') as fh:
            fh.write('header\nTRISOLATION, 1,\n'
                     '1, 1, 2, 3, 0, 0, 0,\n'
                     '2, 900, 901, 902, 0, 0, 0,\n0, 0, 0, 0\n')
        parsed = surpac.read_file(
            self.str_path, companions={'.dtm': dtm_path})
        self.assertEqual(parsed.surfaces[0].triangles, [(0, 1, 2)])
        self.assertTrue(any('referenced missing points' in w
                            for w in parsed.warnings))

    def test_sniff_recognises_a_str_file(self):
        self.assertGreater(surpac.sniff(self.str_path), 0.5)

    def test_sniff_rejects_unrelated_text(self):
        other = os.path.join(self.dir, 'notes.str')
        with open(other, 'w') as fh:
            fh.write('this is not\na surpac file\nat all\n')
        self.assertEqual(surpac.sniff(other), 0.0)


if __name__ == '__main__':
    unittest.main()
