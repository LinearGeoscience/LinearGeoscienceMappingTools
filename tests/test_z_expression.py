"""
Unit tests for z_filter/expression.py (pure python, no QGIS).

Run from the plugin root:
    python -m unittest discover tests
"""

import importlib.util
import os
import unittest

# Load expression.py directly — importing the z_filter package would pull in
# qgis, which isn't available outside QGIS.
_path = os.path.join(os.path.dirname(__file__), '..', 'z_filter', 'expression.py')
_spec = importlib.util.spec_from_file_location('z_expression', _path)
z_expression = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(z_expression)

z_clause = z_expression.z_clause
combine = z_expression.combine
strip_z_subset = z_expression.strip_z_subset
parse_levels = z_expression.parse_levels
format_levels = z_expression.format_levels
format_number = z_expression.format_number


class TestFormatNumber(unittest.TestCase):

    def test_integers_have_no_decimal(self):
        self.assertEqual(format_number(1250.0), '1250')

    def test_decimals_preserved(self):
        self.assertEqual(format_number(1247.5), '1247.5')

    def test_negative(self):
        self.assertEqual(format_number(-120.0), '-120')


class TestZClause(unittest.TestCase):

    def test_basic_window(self):
        self.assertEqual(
            z_clause(1250, 5, show_null=False),
            '("Elevation" >= 1245 AND "Elevation" <= 1255)')

    def test_show_null_wraps_with_is_null(self):
        self.assertEqual(
            z_clause(1250, 5, show_null=True),
            '("Elevation" IS NULL OR ("Elevation" >= 1245 AND "Elevation" <= 1255))')

    def test_zero_tolerance(self):
        self.assertEqual(
            z_clause(1250, 0, show_null=False),
            '("Elevation" >= 1250 AND "Elevation" <= 1250)')

    def test_fractional_level_and_tolerance(self):
        self.assertEqual(
            z_clause(1247.5, 2.5, show_null=False),
            '("Elevation" >= 1245 AND "Elevation" <= 1250)')

    def test_negative_levels_for_underground(self):
        self.assertEqual(
            z_clause(-100, 10, show_null=False),
            '("Elevation" >= -110 AND "Elevation" <= -90)')

    def test_custom_field(self):
        clause = z_clause(10, 1, show_null=False, field='RL')
        self.assertEqual(clause, '("RL" >= 9 AND "RL" <= 11)')


class TestCombine(unittest.TestCase):

    def test_no_original(self):
        self.assertEqual(combine('', 'Z'), 'Z')
        self.assertEqual(combine(None, 'Z'), 'Z')
        self.assertEqual(combine('   ', 'Z'), 'Z')

    def test_with_original(self):
        self.assertEqual(combine('"Type" = \'fault\'', 'Z'),
                         '("Type" = \'fault\') AND Z')


class TestStripZSubset(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(strip_z_subset(''), '')
        self.assertEqual(strip_z_subset(None), '')

    def test_pure_z_clause_removed(self):
        for show_null in (True, False):
            subset = z_clause(1250, 5, show_null=show_null)
            self.assertEqual(strip_z_subset(subset), '', subset)

    def test_combined_returns_original(self):
        orig = '"Type" = \'fault\''
        for show_null in (True, False):
            subset = combine(orig, z_clause(1250, 5, show_null=show_null))
            self.assertEqual(strip_z_subset(subset), orig, subset)

    def test_unrelated_subset_unchanged(self):
        self.assertEqual(strip_z_subset('"Type" = \'fault\''), '"Type" = \'fault\'')

    def test_unrelated_elevation_mention_unchanged(self):
        subset = '"Elevation" > 100'
        self.assertEqual(strip_z_subset(subset), subset)

    def test_fractional_and_negative_bounds(self):
        subset = z_clause(-97.5, 2.5, show_null=True)
        self.assertEqual(strip_z_subset(subset), '')

    def test_roundtrip_after_level_change(self):
        # Controller rebuilds from the stored original each time; the exporter
        # may still meet a saved combined string — strip must recover orig.
        orig = '("Geologist" = \'HW\')'
        subset = combine(orig, z_clause(1300, 10))
        self.assertEqual(strip_z_subset(subset), orig)


class TestLevelListPersistence(unittest.TestCase):

    def test_parse_sorted_unique(self):
        self.assertEqual(parse_levels('1250, 1240,1250,1260'), [1240.0, 1250.0, 1260.0])

    def test_parse_tolerates_junk(self):
        self.assertEqual(parse_levels('1250, abc, ,1240'), [1240.0, 1250.0])

    def test_parse_empty(self):
        self.assertEqual(parse_levels(''), [])
        self.assertEqual(parse_levels(None), [])

    def test_format_roundtrip(self):
        levels = [1260.0, 1240.0, 1250.0, 1250.0]
        self.assertEqual(format_levels(levels), '1240,1250,1260')
        self.assertEqual(parse_levels(format_levels(levels)), [1240.0, 1250.0, 1260.0])


if __name__ == '__main__':
    unittest.main()
