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


def row(rid, name, role='', tied=False, bands=1):
    return {'id': rid, 'name': name, 'role': role, 'tied': tied,
            'bands': bands}


class TestIsDemCandidate(unittest.TestCase):
    def test_single_band_elevation_is_a_candidate(self):
        self.assertTrue(detect.is_dem_candidate(row('a', 'pit_dem')))

    def test_multiband_imagery_rejected(self):
        # The Fingals drone mosaic: 4-band RGBA, and named "..._Pit_..."
        # so the name alone would have made it a pit candidate.
        self.assertFalse(detect.is_dem_candidate(
            row('a', '260606_FF_Pit_transparent_mosaic_group1', bands=4)))

    def test_derived_products_rejected(self):
        for name in ('pit_dem_hillshade', 'dem_slope', 'aspect_map',
                     'Shaded_Relief', 'roughness'):
            self.assertFalse(detect.is_dem_candidate(row('a', name)), name)

    def test_role_stamp_overrides_both(self):
        self.assertTrue(detect.is_dem_candidate(
            row('a', 'weird_hillshade_name', role='pit', bands=3)))

    def test_ortho_and_hillshade_leave_one_clear_winner(self):
        # The real Fingals raster set: DEM + ortho + hillshade + slope.
        rows = [
            row('d', '260606_ff_pit_ss_dem'),
            row('o', '260606_FF_Pit_transparent_mosaic_group1', bands=4),
            row('h', '260606_ff_pit_ss_dem_hillshade'),
            row('s', '260606_ff_pit_ss_dem_slope'),
        ]
        chosen, reason = detect.choose_dem(rows)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen['id'], 'd')
        self.assertEqual(reason, 'pit')

    def test_pinned_survives_filtering(self):
        rows = [row('o', 'ortho', bands=4)]
        chosen, reason = detect.choose_dem(rows, pinned_id='o')
        self.assertEqual(chosen['id'], 'o')
        self.assertEqual(reason, 'pinned')

    def test_only_imagery_reads_as_none(self):
        rows = [row('o', 'ortho', bands=4), row('h', 'dem_hillshade')]
        self.assertEqual(detect.choose_dem(rows), (None, 'none'))


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


if __name__ == '__main__':
    unittest.main()
