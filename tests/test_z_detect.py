"""
Unit tests for z_filter/detect.py (pure python, no QGIS).

Run from the plugin root:
    python -m unittest discover tests
"""

import importlib.util
import os
import unittest

# Load detect.py directly — importing the z_filter package would pull in
# qgis, which isn't available outside QGIS.
_path = os.path.join(os.path.dirname(__file__), '..', 'z_filter', 'detect.py')
_spec = importlib.util.spec_from_file_location('z_detect', _path)
z_detect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(z_detect)

match_elevation_field = z_detect.match_elevation_field
match_range_pair = z_detect.match_range_pair
name_hint = z_detect.name_hint
candidate_specs = z_detect.candidate_specs
detect_spec = z_detect.detect_spec
READ_ONLY_REASON = z_detect.READ_ONLY_REASON


class TestFieldMatching(unittest.TestCase):

    def test_case_insensitive_returns_original_casing(self):
        self.assertEqual(match_elevation_field(['Easting', 'rl']), 'rl')
        self.assertEqual(match_elevation_field(['Easting', 'RL']), 'RL')

    def test_candidate_priority_order(self):
        # Elevation beats RL beats Z.
        self.assertEqual(
            match_elevation_field(['Z', 'RL', 'Elevation']), 'Elevation')
        self.assertEqual(match_elevation_field(['Z', 'RL']), 'RL')

    def test_no_match(self):
        self.assertIsNone(match_elevation_field(['Easting', 'Northing']))
        self.assertIsNone(match_elevation_field([]))
        self.assertIsNone(match_elevation_field(None))

    def test_range_pair_both_fields_required(self):
        self.assertEqual(match_range_pair(['Z_Min', 'Z_Max']),
                         ('Z_Min', 'Z_Max'))
        self.assertIsNone(match_range_pair(['Z_Min']))

    def test_range_pair_original_casing(self):
        self.assertEqual(match_range_pair(['z_min', 'z_MAX']),
                         ('z_min', 'z_MAX'))

    def test_range_pair_priority(self):
        self.assertEqual(
            match_range_pair(['RL_Min', 'RL_Max', 'Z_Min', 'Z_Max']),
            ('Z_Min', 'Z_Max'))


class TestNameHint(unittest.TestCase):

    def test_hits(self):
        for name in ('UG Survey Points', 'floor_strings', '365 Level Pickup',
                     'Bench toes', 'Station pegs'):
            self.assertTrue(name_hint(name), name)

    def test_misses(self):
        for name in ('Geology', 'Faults', ''):
            self.assertFalse(name_hint(name), name)
        self.assertFalse(name_hint(None))


class TestDetectSpec(unittest.TestCase):

    def test_range_pair_beats_single_beats_geometry(self):
        spec = detect_spec('Strings', ['RL', 'Z_Min', 'Z_Max'], True, 'line',
                           True)
        self.assertEqual(spec['mode'], 'range')
        self.assertEqual((spec['field_min'], spec['field_max']),
                         ('Z_Min', 'Z_Max'))
        self.assertEqual(spec['source'], 'attr')

        spec = detect_spec('Strings', ['RL'], True, 'line', True)
        self.assertEqual((spec['mode'], spec['field']), ('single', 'RL'))
        self.assertEqual(spec['source'], 'attr')

    def test_attribute_specs_auto_check_regardless_of_name(self):
        spec = detect_spec('Geology', ['RL'], False, 'point', True)
        self.assertTrue(spec['auto_check'])
        self.assertFalse(spec['needs_fields'])
        self.assertIsNone(spec['disabled_reason'])

    def test_geometry_z_point_gets_single_elevation(self):
        spec = detect_spec('UG Survey Points', [], True, 'point', True)
        self.assertEqual((spec['mode'], spec['field']),
                         ('single', 'Elevation'))
        self.assertEqual(spec['source'], 'geom')
        self.assertTrue(spec['needs_fields'])

    def test_geometry_z_line_gets_range(self):
        spec = detect_spec('Floor Strings', [], True, 'line', True)
        self.assertEqual(spec['mode'], 'range')
        self.assertEqual((spec['field_min'], spec['field_max']),
                         ('Z_Min', 'Z_Max'))

    def test_geometry_z_polygon_gets_range(self):
        spec = detect_spec('Stope outlines', [], True, 'polygon', True)
        self.assertEqual(spec['mode'], 'range')

    def test_geometry_auto_check_needs_name_hint(self):
        self.assertTrue(
            detect_spec('UG Survey Points', [], True, 'point',
                        True)['auto_check'])
        self.assertFalse(
            detect_spec('Mystery CAD', [], True, 'point', True)['auto_check'])

    def test_geometry_read_only_disabled(self):
        spec = detect_spec('Floor Strings', [], True, 'line', False)
        self.assertEqual(spec['disabled_reason'], READ_ONLY_REASON)
        self.assertFalse(spec['auto_check'])

    def test_attribute_layer_can_be_read_only(self):
        # Filtering needs no write access when the fields already exist.
        spec = detect_spec('Survey', ['RL'], False, 'point', False)
        self.assertIsNone(spec['disabled_reason'])
        self.assertTrue(spec['auto_check'])

    def test_nothing_elevation_like(self):
        self.assertIsNone(detect_spec('Geology', ['Easting'], False, 'point',
                                      True))

    def test_candidates_expose_alternatives_in_priority_order(self):
        specs = candidate_specs('UG Survey', ['RL'], True, 'point', True)
        self.assertEqual([s['source'] for s in specs], ['attr', 'geom'])
        self.assertEqual(specs[0]['field'], 'RL')
        self.assertEqual(specs[1]['field'], 'Elevation')


if __name__ == '__main__':
    unittest.main()
