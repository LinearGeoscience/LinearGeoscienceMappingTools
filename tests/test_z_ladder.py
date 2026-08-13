"""
Unit tests for z_filter/ladder_math.py (pure python, no QGIS/Qt).

Run from the plugin root:
    python -m unittest discover tests
"""

import importlib.util
import os
import unittest

# Load ladder_math.py directly — importing the z_filter package would pull
# in qgis.
_path = os.path.join(os.path.dirname(__file__), '..', 'z_filter',
                     'ladder_math.py')
_spec = importlib.util.spec_from_file_location('z_ladder_math', _path)
lm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lm)

HEIGHT = 200.0
PAD = 14.0


class TestElevationMapping(unittest.TestCase):

    def test_highest_at_top(self):
        y_high = lm.elev_to_y(1450.0, 1400.0, 1450.0, HEIGHT, PAD)
        y_low = lm.elev_to_y(1400.0, 1400.0, 1450.0, HEIGHT, PAD)
        self.assertEqual(y_high, PAD)
        self.assertEqual(y_low, HEIGHT - PAD)
        self.assertLess(y_high, y_low)

    def test_round_trip(self):
        for value in (1400.0, 1412.5, 1437.2, 1450.0):
            y = lm.elev_to_y(value, 1400.0, 1450.0, HEIGHT, PAD)
            self.assertAlmostEqual(
                lm.y_to_elev(y, 1400.0, 1450.0, HEIGHT, PAD), value)

    def test_degenerate_range(self):
        self.assertEqual(lm.elev_to_y(366.0, 366.0, 366.0, HEIGHT, PAD),
                         HEIGHT / 2.0)
        self.assertEqual(lm.y_to_elev(50.0, 366.0, 366.0, HEIGHT, PAD), 366.0)

    def test_y_to_elev_clamped(self):
        self.assertEqual(lm.y_to_elev(-100.0, 1400.0, 1450.0, HEIGHT, PAD),
                         1450.0)
        self.assertEqual(lm.y_to_elev(HEIGHT + 100.0, 1400.0, 1450.0,
                                      HEIGHT, PAD), 1400.0)


class TestHitRung(unittest.TestCase):

    def test_nearest_within_tolerance(self):
        ys = [20.0, 60.0, 100.0]
        self.assertEqual(lm.hit_rung(58.0, ys), 1)
        self.assertEqual(lm.hit_rung(22.0, ys), 0)

    def test_miss(self):
        ys = [20.0, 60.0, 100.0]
        self.assertIsNone(lm.hit_rung(40.0, ys))
        self.assertIsNone(lm.hit_rung(40.0, []))

    def test_nearest_of_two_close_rungs(self):
        ys = [50.0, 58.0]
        self.assertEqual(lm.hit_rung(53.0, ys), 0)
        self.assertEqual(lm.hit_rung(55.5, ys), 1)


class TestSnapElevation(unittest.TestCase):

    def test_snap_to_step(self):
        self.assertEqual(lm.snap_elevation(1435.7, 2.0), 1436.0)
        self.assertEqual(lm.snap_elevation(1434.9, 2.0), 1434.0)

    def test_no_step_rounds_to_decimetre(self):
        self.assertEqual(lm.snap_elevation(1435.678, 0), 1435.7)
        self.assertEqual(lm.snap_elevation(1435.678, None), 1435.7)
        self.assertEqual(lm.snap_elevation(1435.678, -1), 1435.7)


class TestSizing(unittest.TestCase):

    def test_preferred_height_clamps(self):
        self.assertEqual(lm.preferred_height(1), 120)
        self.assertEqual(lm.preferred_height(8), 208)
        self.assertEqual(lm.preferred_height(50), 400)


class TestDodgeLabels(unittest.TestCase):

    GAP = 16.0

    def _assert_valid(self, ys, out, gap, lo, hi):
        self.assertEqual(len(out), len(ys))
        for a, b in zip(out, out[1:]):
            self.assertGreaterEqual(b - a, gap - 1e-9)
        for y in out:
            self.assertGreaterEqual(y, lo - 1e-9)
            self.assertLessEqual(y, hi + 1e-9)

    def test_identity_when_already_spaced(self):
        ys = [20.0, 60.0, 100.0]
        self.assertEqual(lm.dodge_labels(ys, self.GAP, 0.0, 200.0), ys)

    def test_crowded_pair_pushed_apart(self):
        ys = [50.0, 52.0]
        out = lm.dodge_labels(ys, self.GAP, 0.0, 200.0)
        self._assert_valid(ys, out, self.GAP, 0.0, 200.0)

    def test_clamped_at_top(self):
        ys = [2.0, 4.0, 6.0]
        out = lm.dodge_labels(ys, self.GAP, 0.0, 200.0)
        self._assert_valid(ys, out, self.GAP, 0.0, 200.0)
        self.assertGreaterEqual(out[0], 0.0)

    def test_clamped_at_bottom(self):
        ys = [194.0, 196.0, 198.0]
        out = lm.dodge_labels(ys, self.GAP, 0.0, 200.0)
        self._assert_valid(ys, out, self.GAP, 0.0, 200.0)
        self.assertLessEqual(out[-1], 200.0)

    def test_gap_shrinks_when_labels_cannot_fit(self):
        # 12 coincident ticks in a 100 px window: 11 gaps of 16 px would
        # need 176 px, so the gap shrinks to 100/11.
        ys = [50.0] * 12
        out = lm.dodge_labels(ys, self.GAP, 0.0, 100.0)
        shrunk = 100.0 / 11
        self._assert_valid(ys, out, shrunk, 0.0, 100.0)

    def test_order_preserved(self):
        ys = [10.0, 11.0, 12.0, 90.0, 91.0]
        out = lm.dodge_labels(ys, self.GAP, 0.0, 200.0)
        self.assertEqual(out, sorted(out))
        self._assert_valid(ys, out, self.GAP, 0.0, 200.0)

    def test_degenerates(self):
        self.assertEqual(lm.dodge_labels([], self.GAP, 0.0, 200.0), [])
        self.assertEqual(lm.dodge_labels([300.0], self.GAP, 0.0, 200.0),
                         [200.0])
        # hi <= lo: passthrough, never divides by zero.
        self.assertEqual(lm.dodge_labels([1.0, 2.0], self.GAP, 50.0, 50.0),
                         [1.0, 2.0])


class TestBand(unittest.TestCase):

    def test_band_inside(self):
        top, bottom = lm.band_rect_y(1425.0, 5.0, 1400.0, 1450.0, HEIGHT, PAD)
        self.assertLess(top, bottom)
        self.assertAlmostEqual(
            top, lm.elev_to_y(1430.0, 1400.0, 1450.0, HEIGHT, PAD))
        self.assertAlmostEqual(
            bottom, lm.elev_to_y(1420.0, 1400.0, 1450.0, HEIGHT, PAD))

    def test_band_clamped_at_edges(self):
        top, bottom = lm.band_rect_y(1450.0, 500.0, 1400.0, 1450.0,
                                     HEIGHT, PAD)
        self.assertEqual(top, 0.0)
        self.assertEqual(bottom, HEIGHT)


if __name__ == '__main__':
    unittest.main()
