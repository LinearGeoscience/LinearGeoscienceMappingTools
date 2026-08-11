"""
Unit tests for z_filter/levels.py (pure python, no QGIS).

Run from the plugin root:
    python -m unittest discover tests
"""

import importlib.util
import os
import random
import unittest

# Load levels.py directly — importing the z_filter package would pull in qgis.
_path = os.path.join(os.path.dirname(__file__), '..', 'z_filter', 'levels.py')
_spec = importlib.util.spec_from_file_location('z_levels', _path)
z_levels = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(z_levels)

cluster_levels = z_levels.cluster_levels
suggest_tolerance = z_levels.suggest_tolerance
top_suggestions = z_levels.top_suggestions
value_range = z_levels.value_range
MIN_TOL = z_levels.MIN_TOL
MAX_SUGGESTIONS = z_levels.MAX_SUGGESTIONS
DEFAULT_TOLERANCE = z_levels.DEFAULT_TOLERANCE


class TestClusterLevelsBasics(unittest.TestCase):

    def test_empty_inputs(self):
        self.assertEqual(cluster_levels({}), [])
        self.assertEqual(cluster_levels(None), [])
        self.assertEqual(cluster_levels([]), [])

    def test_garbage_filtered(self):
        self.assertEqual(cluster_levels({'abc': 3, 366: 0, None: 2}), [])

    def test_single_value(self):
        result = cluster_levels({366.0: 1})
        self.assertEqual(len(result), 1)
        cluster = result[0]
        self.assertEqual(cluster['level'], 366.0)
        self.assertEqual(cluster['lo'], 366.0)
        self.assertEqual(cluster['hi'], 366.0)
        self.assertEqual(cluster['count'], 1)
        self.assertEqual(cluster['suggested_tol'], MIN_TOL)

    def test_all_identical(self):
        result = cluster_levels({366.0: 500})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['count'], 500)
        self.assertEqual(result[0]['suggested_tol'], MIN_TOL)


class TestCleanBenches(unittest.TestCase):

    def test_typed_rls(self):
        result = cluster_levels({366: 214, 376: 180, 386: 90})
        self.assertEqual([c['level'] for c in result], [366.0, 376.0, 386.0])
        self.assertEqual([c['count'] for c in result], [214, 180, 90])
        for cluster in result:
            self.assertEqual(cluster['suggested_tol'], MIN_TOL)


class TestNoisyBenches(unittest.TestCase):

    def test_dominant_mode_snaps_to_typed_value(self):
        counts = {365.8: 3, 366.0: 40, 366.2: 5,
                  375.9: 2, 376.0: 30, 376.1: 4}
        result = cluster_levels(counts)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['level'], 366.0)
        self.assertEqual(result[1]['level'], 376.0)
        self.assertEqual(result[0]['count'], 48)
        self.assertEqual(result[0]['lo'], 365.8)
        self.assertEqual(result[0]['hi'], 366.2)
        # Scatter fits inside the MIN_TOL floor.
        self.assertEqual(result[0]['suggested_tol'], MIN_TOL)

    def test_no_dominant_mode_uses_weighted_mean(self):
        counts = {365.7: 10, 366.1: 10, 366.5: 10}
        result = cluster_levels(counts)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['level'], 366.1)  # mean rounded to 0.1

    def test_mixed_clean_and_noisy(self):
        counts = {320: 50,                       # clean typed bench
                  365.8: 3, 366.0: 40, 366.2: 5}  # noisy bench
        result = cluster_levels(counts)
        self.assertEqual([c['level'] for c in result], [320.0, 366.0])
        self.assertEqual([c['count'] for c in result], [50, 48])


class TestContinuousData(unittest.TestCase):

    def test_uniform_survey_bins_on_nice_step(self):
        counts = {float(v): 1 for v in range(320, 411)}   # every metre
        result = cluster_levels(counts)
        # Nice step for 90/12 = 7.5 -> 10 m bins.
        self.assertTrue(all(c['level'] % 10 == 0 for c in result), result)
        self.assertEqual(sum(c['count'] for c in result), 91)
        self.assertLessEqual(len(result), MAX_SUGGESTIONS + 1)
        self.assertTrue(all(c['suggested_tol'] == 5.0 for c in result))


class TestNeighbourClamp(unittest.TestCase):

    def test_close_clusters_never_overlap(self):
        # Two tight noisy clusters ~4 m apart; raw tol would be ~1.5 m.
        counts = {365.0: 5, 366.0: 5, 367.0: 5,
                  371.0: 5, 372.0: 5, 373.0: 5}
        result = cluster_levels(counts)
        self.assertEqual(len(result), 2)
        gap = result[1]['level'] - result[0]['level']
        for cluster in result:
            self.assertLessEqual(cluster['suggested_tol'], gap / 2.0)
            self.assertGreaterEqual(cluster['suggested_tol'], MIN_TOL)


class TestDeterminism(unittest.TestCase):

    def test_dict_vs_shuffled_pairs(self):
        counts = {365.8: 3, 366.0: 40, 376.0: 30, 386.0: 12, 390.0: 2}
        pairs = list(counts.items())
        random.Random(42).shuffle(pairs)
        self.assertEqual(cluster_levels(counts), cluster_levels(pairs))

    def test_duplicate_pairs_accumulate(self):
        result = cluster_levels([(366.0, 10), (366.0, 5)])
        self.assertEqual(result[0]['count'], 15)


class TestHelpers(unittest.TestCase):

    def test_top_suggestions_caps_and_sorts(self):
        clusters = cluster_levels({float(v * 10): v for v in range(1, 21)})
        top = top_suggestions(clusters, n=MAX_SUGGESTIONS)
        self.assertEqual(len(top), MAX_SUGGESTIONS)
        # Highest counts kept (largest v), re-sorted ascending by level.
        self.assertEqual([c['level'] for c in top],
                         sorted(c['level'] for c in top))
        self.assertEqual(min(c['count'] for c in top), 9)

    def test_suggest_tolerance_median(self):
        clusters = [{'suggested_tol': 1.0}, {'suggested_tol': 5.0},
                    {'suggested_tol': 2.0}]
        self.assertEqual(suggest_tolerance(clusters), 2.0)

    def test_suggest_tolerance_empty(self):
        self.assertEqual(suggest_tolerance([]), DEFAULT_TOLERANCE)

    def test_value_range(self):
        self.assertIsNone(value_range({}))
        self.assertEqual(value_range({320.0: 2, 410.0: 3, 366.0: 5}),
                         (320.0, 410.0, 10))


if __name__ == '__main__':
    unittest.main()
