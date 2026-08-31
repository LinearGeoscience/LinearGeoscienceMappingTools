"""
Unit tests for view3d/detect.py (pure python, no QGIS).

Run from the plugin root:
    python -m unittest discover tests
"""

import importlib.util
import os
import unittest

# Load detect.py directly — importing the view3d package would pull in qgis.
_path = os.path.join(os.path.dirname(__file__), '..', 'view3d', 'detect.py')
_spec = importlib.util.spec_from_file_location('view3d_detect', _path)
detect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(detect)


def row(rid, name, role='', tied=False):
    return {'id': rid, 'name': name, 'role': role, 'tied': tied}


class TestClassify(unittest.TestCase):
    def test_role_stamp_is_pit(self):
        self.assertEqual(detect.classify(row('a', 'whatever', role='pit')),
                         'pit')

    def test_tie_is_pit(self):
        self.assertEqual(detect.classify(row('a', 'ortho', tied=True)),
                         'pit')

    def test_name_tokens(self):
        for name in ('Pit_Shell_2026', 'bench_1180', 'EOM_July',
                     'drone_ortho', 'AsBuilt Jan', 'as_built_v2'):
            self.assertEqual(detect.classify(row('a', name)), 'pit', name)

    def test_plain_names_are_regional(self):
        for name in ('SRTM_30m', 'topo', 'DEM_regional', 'hillshade'):
            self.assertEqual(detect.classify(row('a', name)), 'regional',
                             name)

    def test_case_insensitive(self):
        self.assertEqual(detect.classify(row('a', 'PIT_SURFACE')), 'pit')


class TestChooseDem(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(detect.choose_dem([]), (None, 'none'))

    def test_pinned_wins_over_everything(self):
        rows = [row('a', 'pit_dem', role='pit'), row('b', 'topo')]
        chosen, reason = detect.choose_dem(rows, pinned_id='b')
        self.assertEqual(chosen['id'], 'b')
        self.assertEqual(reason, 'pinned')

    def test_vanished_pin_falls_through(self):
        rows = [row('a', 'pit_dem', role='pit'), row('b', 'topo')]
        chosen, reason = detect.choose_dem(rows, pinned_id='gone')
        self.assertEqual(chosen['id'], 'a')
        self.assertEqual(reason, 'role')

    def test_single_role_stamp_wins(self):
        rows = [row('a', 'x_dem', role='pit'), row('b', 'bench_1180'),
                row('c', 'topo')]
        chosen, reason = detect.choose_dem(rows)
        self.assertEqual(chosen['id'], 'a')
        self.assertEqual(reason, 'role')

    def test_two_role_stamps_ambiguous(self):
        rows = [row('a', 'x', role='pit'), row('b', 'y', role='pit')]
        self.assertEqual(detect.choose_dem(rows), (None, 'ambiguous'))

    def test_single_pit_classified_wins_over_regional(self):
        rows = [row('a', 'topo'), row('b', 'srtm'),
                row('c', 'pit_july')]
        chosen, reason = detect.choose_dem(rows)
        self.assertEqual(chosen['id'], 'c')
        self.assertEqual(reason, 'pit')

    def test_two_pit_classified_ambiguous(self):
        rows = [row('a', 'pit_june'), row('b', 'pit_july')]
        self.assertEqual(detect.choose_dem(rows), (None, 'ambiguous'))

    def test_only_raster_auto_selects(self):
        rows = [row('a', 'topo')]
        chosen, reason = detect.choose_dem(rows)
        self.assertEqual(chosen['id'], 'a')
        self.assertEqual(reason, 'single')

    def test_two_regional_ambiguous(self):
        rows = [row('a', 'topo'), row('b', 'srtm')]
        self.assertEqual(detect.choose_dem(rows), (None, 'ambiguous'))


class TestDefaultMode(unittest.TestCase):
    def test_pit_dem_opens_in_pit(self):
        self.assertEqual(detect.default_mode(row('a', 'x', role='pit')),
                         'pit')

    def test_regional_opens_in_surface(self):
        self.assertEqual(detect.default_mode(row('a', 'topo')), 'surface')

    def test_none_opens_in_surface(self):
        self.assertEqual(detect.default_mode(None), 'surface')


if __name__ == '__main__':
    unittest.main()
