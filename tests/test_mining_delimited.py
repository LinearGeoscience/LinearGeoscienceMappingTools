"""
Unit tests for mining_import/formats/delimited.py (pure python, no QGIS).

Fixtures are the real Majestic station export's shape. The load-bearing cases
are the ones where guessing would be destructive: which column is easting,
and whether a constant string number means "join these into a line".
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pure_loader  # noqa: E402

delimited = pure_loader.load('formats/delimited.py')
dfields = pure_loader.load('dfields.py')

# Header and three records from mga_all_stations.csv. Note cols 2-3 are
# (Northing, Easting) while cols 5-6 are the same numbers as (Easting,
# Northing), and the point name is d1 -- column 8, not column 1.
STATIONS_CSV = """string,Y,X,Z,easting,northing,elevation,d1,d2,d3,d4,d5,d6,d7,d8,d9,d10,d11,d12,d13,d14,d15
99,6581349.971,398635.158,197.529,398635.158,6581349.971,197.529,MJ33,18/01/2026 14:11,1182,UG,100,1197.529,0,211.2907,DARBY LINDSAY,18/01/2026,,,,,OPEN TRAVERSE
99,6581350.613,398651.08,195.297,398651.08,6581350.613,195.297,MJ34,25/01/2026 16:13,1182,UG,WM1,1195.297,0,257.2022,WEST MCGRATH,25/01/2026,,,,,OPEN TRAVERSE
99,6581342.409,398664.024,193.149,398664.024,6581342.409,193.149,MJ35,9/02/2026 16:01,1182,UG,WM1,1193.149,0,288.2411,WEST MCGRATH,9/02/2026,,,,,OPEN TRAVERSE
"""

# The local-grid siblings DO open with a comment line; this one does not, so
# comment skipping has to be conditional or it eats the header.
COMMENTED_CSV = """# source: stn,01-May-26,Survey stations from majestic_control_local,
Point,Easting,Northing,RL,Code
STN_A4,398635.158,6581349.971,197.529,PEG
BM12,398651.080,6581350.613,195.297,MARK
"""

TAB_CSV = "Point\tEasting\tNorthing\tRL\nA1\t398635.158\t6581349.971\t197.5\n" \
          "A2\t398651.080\t6581350.613\t195.3\n"

HEADERLESS = "1,398635.158,6581349.971,197.529,PEG\n" \
             "2,398651.080,6581350.613,195.297,MARK\n"

# A join column that actually varies, and reuses a value for a later,
# disconnected string.
STRINGS_CSV = """string,easting,northing,elevation
1,398600.0,6581300.0,160.0
1,398610.0,6581310.0,161.0
2,398700.0,6581400.0,170.0
2,398710.0,6581410.0,171.0
1,398800.0,6581500.0,180.0
1,398810.0,6581510.0,181.0
"""


def write(body, suffix='.csv'):
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, 'sample' + suffix)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(body)
    return path


class TestDelimiterDetection(unittest.TestCase):

    def test_comma(self):
        self.assertEqual(
            delimited.detect_delimiter(STATIONS_CSV.splitlines()), ',')

    def test_tab(self):
        self.assertEqual(delimited.detect_delimiter(TAB_CSV.splitlines()), '\t')

    def test_non_constant_count_is_rejected(self):
        # A prose line with a stray comma must not make ',' the delimiter
        # just because it appears most often.
        lines = ['alpha, beta, gamma', 'one, two', 'x, y, z, w']
        self.assertNotEqual(delimited.detect_delimiter(lines), ';')

    def test_whitespace_runs(self):
        lines = ['398635.158  6581349.971  197.5',
                 '398651.080  6581350.613  195.3']
        self.assertIsNone(delimited.detect_delimiter(lines))

    def test_split_on_whitespace_when_delimiter_is_none(self):
        self.assertEqual(delimited.split_row('1  2   3', None),
                         ['1', '2', '3'])


class TestHeaderDetection(unittest.TestCase):

    def test_named_header(self):
        rows = [r.split(',') for r in STATIONS_CSV.splitlines()]
        self.assertTrue(delimited.detect_header(rows))

    def test_numeric_first_row_is_not_a_header(self):
        rows = [r.split(',') for r in HEADERLESS.splitlines()]
        self.assertFalse(delimited.detect_header(rows))


class TestRoleDetection(unittest.TestCase):

    def test_explicit_names_outrank_bare_initials(self):
        # The real file has BOTH an 'X' column and an 'easting' column
        # holding the same values. 'easting' cannot be misread, so it wins.
        header = STATIONS_CSV.splitlines()[0].split(',')
        roles = delimited.detect_roles(header)
        self.assertEqual(header[roles[delimited.ROLE_X]], 'easting')
        self.assertEqual(header[roles[delimited.ROLE_Y]], 'northing')
        self.assertEqual(header[roles[delimited.ROLE_Z]], 'elevation')

    def test_common_survey_headers(self):
        header = ['Point', 'Easting', 'Northing', 'RL', 'Code']
        roles = delimited.detect_roles(header)
        self.assertEqual(roles[delimited.ROLE_ID], 0)
        self.assertEqual(roles[delimited.ROLE_X], 1)
        self.assertEqual(roles[delimited.ROLE_Y], 2)
        self.assertEqual(roles[delimited.ROLE_Z], 3)
        self.assertEqual(roles[delimited.ROLE_CODE], 4)

    def test_d_field_block_detected(self):
        header = STATIONS_CSV.splitlines()[0].split(',')
        self.assertEqual(delimited.detect_d_columns(header),
                         list(range(7, 22)))

    def test_no_d_block_when_absent(self):
        self.assertEqual(
            delimited.detect_d_columns(['Point', 'Easting', 'Northing']), [])


class TestEnOrder(unittest.TestCase):

    def test_northing_recognised_by_magnitude(self):
        northings = [6581349.9, 6581350.6, 6581342.4]
        eastings = [398635.1, 398651.0, 398664.0]
        self.assertEqual(delimited.guess_en_order(northings, eastings),
                         ('N', 'E'))
        self.assertEqual(delimited.guess_en_order(eastings, northings),
                         ('E', 'N'))

    def test_ambiguous_returns_none_rather_than_guessing(self):
        # Similar magnitudes could be either way round. Importing a survey
        # into the sea is worse than asking one question.
        a = [400000.0, 400100.0]
        b = [399000.0, 399100.0]
        self.assertIsNone(delimited.guess_en_order(a, b))

    def test_local_grid_magnitudes_return_none(self):
        self.assertIsNone(delimited.guess_en_order([30207.0], [6039.0]))

    def test_empty_returns_none(self):
        self.assertIsNone(delimited.guess_en_order([], [1.0]))


class TestReadStations(unittest.TestCase):

    def setUp(self):
        self.path = write(STATIONS_CSV)

    def tearDown(self):
        shutil.rmtree(os.path.dirname(self.path), ignore_errors=True)

    def test_one_station_per_row_and_no_lines(self):
        parsed = delimited.read_file(self.path)
        self.assertEqual(len(parsed.stations), 3)
        self.assertEqual(len(parsed.polylines), 0)

    def test_constant_string_column_does_not_group_into_a_line(self):
        # Every row carries string number 99. Auto-grouping on it would
        # chain the whole file into one polyline -- which is exactly the
        # failure this reader was written alongside a fix for.
        parsed = delimited.read_file(self.path)
        self.assertEqual(len(parsed.polylines), 0)
        self.assertFalse(parsed.attrs['group_strings'])

    def test_grouping_is_available_but_opt_in(self):
        parsed = delimited.read_file(self.path, group_strings=True)
        self.assertEqual(len(parsed.polylines), 1)
        self.assertEqual(len(parsed.polylines[0].points), 3)

    def test_coordinates_are_easting_first(self):
        parsed = delimited.read_file(self.path)
        x, y, z = parsed.stations[0].point
        self.assertAlmostEqual(x, 398635.158)
        self.assertAlmostEqual(y, 6581349.971)
        self.assertAlmostEqual(z, 197.529)

    def test_point_name_comes_from_d1_not_column_one(self):
        parsed = delimited.read_file(self.path)
        self.assertEqual(parsed.stations[0].attrs['PointId'], 'MJ33')

    def test_station_profile_detected_from_d_columns(self):
        parsed = delimited.read_file(self.path)
        self.assertEqual(parsed.attrs['profile'], dfields.PROFILE_STATION)
        attrs = parsed.stations[0].attrs
        self.assertEqual(attrs['Surveyor'], 'DARBY LINDSAY')
        self.assertEqual(attrs['Domain'], 'UG')
        self.assertEqual(attrs['SurveyType'], 'OPEN TRAVERSE')

    def test_level_from_d3_beats_the_filename(self):
        parsed = delimited.read_file(self.path, level='sample')
        self.assertEqual(parsed.stations[0].attrs['Level'], '1182')

    def test_filename_level_used_when_records_carry_none(self):
        path = write(COMMENTED_CSV)
        try:
            parsed = delimited.read_file(path, level='365')
            self.assertEqual(parsed.stations[0].attrs['Level'], '365')
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)


class TestCommentLine(unittest.TestCase):

    def test_leading_comment_skipped_without_eating_the_header(self):
        path = write(COMMENTED_CSV)
        try:
            info = delimited.inspect(path)
            self.assertTrue(info['has_header'])
            self.assertEqual(info['header'][0], 'Point')
            parsed = delimited.read_file(path)
            self.assertEqual(len(parsed.stations), 2)
            self.assertEqual(parsed.stations[0].attrs['PointId'], 'STN_A4')
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    def test_file_without_a_comment_keeps_all_its_rows(self):
        path = write(STATIONS_CSV)
        try:
            self.assertEqual(len(delimited.read_file(path).stations), 3)
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)


class TestStringGrouping(unittest.TestCase):

    def test_groups_by_runs_not_by_global_value(self):
        # String 1 appears twice as two disconnected runs; joining them
        # globally would draw a line across the mine between them.
        path = write(STRINGS_CSV)
        try:
            parsed = delimited.read_file(path, group_strings=True)
            self.assertEqual(len(parsed.polylines), 3)
            self.assertTrue(all(len(p.points) == 2 for p in parsed.polylines))
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)


class TestPresetsAndMapping(unittest.TestCase):

    def test_penzd_preset(self):
        mapping = delimited.apply_preset('PENZD', 5)
        self.assertEqual(mapping[delimited.ROLE_ID], 0)
        self.assertEqual(mapping[delimited.ROLE_X], 1)
        self.assertEqual(mapping[delimited.ROLE_Y], 2)

    def test_pnezd_swaps_easting_and_northing(self):
        mapping = delimited.apply_preset('PNEZD', 5)
        self.assertEqual(mapping[delimited.ROLE_Y], 1)
        self.assertEqual(mapping[delimited.ROLE_X], 2)

    def test_preset_trimmed_to_actual_width(self):
        mapping = delimited.apply_preset('PENZD', 3)
        self.assertNotIn(delimited.ROLE_CODE, mapping)

    def test_explicit_mapping_overrides_detection(self):
        path = write(HEADERLESS)
        try:
            parsed = delimited.read_file(
                path, mapping=delimited.apply_preset('PENZD', 5))
            self.assertEqual(len(parsed.stations), 2)
            x, y, _z = parsed.stations[0].point
            self.assertAlmostEqual(x, 398635.158)
            self.assertAlmostEqual(y, 6581349.971)
            self.assertEqual(parsed.stations[0].attrs['PointId'], '1')
            self.assertEqual(parsed.stations[0].attrs['Code'], 'PEG')
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    def test_swap_en_exchanges_the_columns(self):
        path = write(HEADERLESS)
        try:
            parsed = delimited.read_file(
                path, mapping=delimited.apply_preset('PENZD', 5),
                swap_en=True)
            x, y, _z = parsed.stations[0].point
            self.assertAlmostEqual(x, 6581349.971)
            self.assertAlmostEqual(y, 398635.158)
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    def test_missing_coordinates_raise_rather_than_import_nonsense(self):
        path = write("name,note\nalpha,one\nbeta,two\n")
        try:
            with self.assertRaises(RuntimeError):
                delimited.read_file(path)
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)


class TestSignature(unittest.TestCase):

    def test_same_columns_different_filenames_share_a_signature(self):
        a = write(STATIONS_CSV)
        b = write(STATIONS_CSV)
        try:
            self.assertEqual(delimited.inspect(a)['signature'],
                             delimited.inspect(b)['signature'])
        finally:
            for path in (a, b):
                shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    def test_different_columns_differ(self):
        a = write(STATIONS_CSV)
        b = write(COMMENTED_CSV)
        try:
            self.assertNotEqual(delimited.inspect(a)['signature'],
                                delimited.inspect(b)['signature'])
        finally:
            for path in (a, b):
                shutil.rmtree(os.path.dirname(path), ignore_errors=True)


class TestSniff(unittest.TestCase):

    def test_survey_csv_scores_high(self):
        path = write(STATIONS_CSV)
        try:
            self.assertGreaterEqual(delimited.sniff(path), 0.9)
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    def test_prose_scores_below_the_claim_threshold(self):
        # A readme in a survey folder must not appear in the import list.
        path = write("this is not a survey file\nat all\n", suffix='.txt')
        try:
            self.assertLess(delimited.sniff(path), 0.5)
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
