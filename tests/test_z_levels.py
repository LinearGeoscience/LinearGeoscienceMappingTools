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
label_elevation = z_levels.label_elevation
range_vote = z_levels.range_vote
suggest_tolerance = z_levels.suggest_tolerance
top_suggestions = z_levels.top_suggestions
value_range = z_levels.value_range
MIN_TOL = z_levels.MIN_TOL
MAX_SUGGESTIONS = z_levels.MAX_SUGGESTIONS
DEFAULT_TOLERANCE = z_levels.DEFAULT_TOLERANCE

_COVER_EPS = 1e-9


def assert_full_coverage(testcase, value_counts, suggestions):
    """Every scanned value must fall inside at least one suggestion window."""
    for value, count in value_counts.items():
        if count <= 0:
            continue
        covered = any(
            s['level'] - s['suggested_tol'] - _COVER_EPS <= value
            <= s['level'] + s['suggested_tol'] + _COVER_EPS
            for s in suggestions)
        testcase.assertTrue(
            covered, "%r (x%d) not covered by any suggestion window: %r"
            % (value, count, suggestions))


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
        # Half the 10 m step; a bin whose level sits at the range edge may
        # be trimmed to the midpoint toward its neighbour (never below
        # what covers its own values).
        self.assertTrue(all(4.5 <= c['suggested_tol'] <= 5.0 for c in result),
                        result)
        assert_full_coverage(self, counts, result)


class TestDiscreteFastPath(unittest.TestCase):
    """Few distinct values, all > MIN_TOL apart: each value is its own level."""

    # RB UG strings.shp (Red Bird): 8 typed mine levels in an RL field.
    RB_COUNTS = {1419.5220453189381: 5, 1433.0369193011243: 4,
                 1435.0369193011243: 10, 1437.1999999934155: 1,
                 1439.2: 8, 1448.9914748780934: 1,
                 1450.0: 5, 1452.0: 1}

    def test_rb_ug_strings_regression(self):
        result = cluster_levels(self.RB_COUNTS)
        self.assertEqual([c['level'] for c in result],
                         sorted(self.RB_COUNTS))
        self.assertEqual([c['count'] for c in result],
                         [self.RB_COUNTS[v] for v in sorted(self.RB_COUNTS)])
        self.assertTrue(all(c['suggested_tol'] == MIN_TOL for c in result))
        assert_full_coverage(self, self.RB_COUNTS, result)
        # Selective: no window captures a neighbouring level.
        for suggestion in result:
            inside = [v for v in self.RB_COUNTS
                      if abs(v - suggestion['level']) <= suggestion['suggested_tol']]
            self.assertEqual(inside, [suggestion['level']])

    def test_auto_tolerance_on_fast_path(self):
        self.assertEqual(suggest_tolerance(cluster_levels(self.RB_COUNTS)),
                         MIN_TOL)

    def test_float_noise_does_not_change_levels(self):
        noisy = {v + 3e-9: c for v, c in self.RB_COUNTS.items()}
        result = cluster_levels(noisy)
        self.assertEqual(len(result), len(self.RB_COUNTS))
        for suggestion, clean in zip(result, sorted(self.RB_COUNTS)):
            self.assertAlmostEqual(suggestion['level'], clean, places=6)
            self.assertEqual(suggestion['suggested_tol'], MIN_TOL)

    def test_wide_span_discrete_not_binned(self):
        counts = {0.0: 5, 100.0: 7, 250.0: 3}   # span >> continuous cutoff
        result = cluster_levels(counts)
        self.assertEqual([c['level'] for c in result], [0.0, 100.0, 250.0])
        self.assertTrue(all(c['suggested_tol'] == MIN_TOL for c in result))

    def test_sub_metre_scatter_still_clusters(self):
        # min gap 0.1 <= MIN_TOL: the noisy-bench path must still merge.
        counts = {365.8: 3, 366.0: 40, 366.2: 5,
                  375.9: 2, 376.0: 30, 376.1: 4}
        result = cluster_levels(counts)
        self.assertEqual([c['level'] for c in result], [366.0, 376.0])

    def test_thirteen_distinct_levels_fall_through(self):
        # One over MAX_SUGGESTIONS: clustering runs, but every feature must
        # still be covered by some window (the coverage guarantee).
        counts = {1400.0 + 2.0 * i: 3 for i in range(13)}
        result = cluster_levels(counts)
        self.assertLess(len(result), 13)
        assert_full_coverage(self, counts, result)


class TestSuggestStep(unittest.TestCase):

    def test_rb_dataset_suggests_two_metres(self):
        clusters = cluster_levels(TestDiscreteFastPath.RB_COUNTS)
        self.assertEqual(z_levels.suggest_step(clusters), 2.0)

    def test_continuous_survey_suggests_bin_step(self):
        clusters = cluster_levels({float(v): 1 for v in range(320, 411)})
        self.assertEqual(z_levels.suggest_step(clusters), 10.0)

    def test_too_few_suggestions_default(self):
        self.assertEqual(z_levels.suggest_step([]), z_levels.DEFAULT_STEP)
        self.assertEqual(z_levels.suggest_step(cluster_levels({366.0: 5})),
                         z_levels.DEFAULT_STEP)

    def test_nice_step_nearest(self):
        nearest = z_levels._nice_step_nearest
        self.assertEqual(nearest(3.0), 2.0)
        self.assertEqual(nearest(4.0), 5.0)
        self.assertEqual(nearest(1.5), 1.0)   # tie -> smaller
        self.assertEqual(nearest(7.0), 5.0)
        self.assertEqual(nearest(8.0), 10.0)
        self.assertEqual(nearest(0.3), 0.2)
        self.assertEqual(nearest(0.0), 1.0)
        self.assertEqual(nearest(-2.0), 1.0)

    def test_step_floor(self):
        # Adjacent suggestion levels ~0.3 m apart would suggest 0.2; the
        # floor keeps the sweep at a usable 0.5 m.
        clusters = [{'level': 100.0}, {'level': 100.3}, {'level': 100.6}]
        self.assertEqual(z_levels.suggest_step(clusters), z_levels.STEP_FLOOR)


class TestAttachLabels(unittest.TestCase):

    def test_modal_label_per_level(self):
        counts = {1450.0: 5, 1448.991: 1, 1433.04: 4}
        suggestions = cluster_levels(counts)
        labels = {1450.0: {'000 Level': 1}, 1448.991: {'CaveTun 00': 1},
                  1433.04: {'17/57': 3, '13/42': 1}}
        z_levels.attach_labels(suggestions, labels)
        by_level = {s['level']: s.get('label') for s in suggestions}
        self.assertEqual(by_level[1450.0], '000 Level')
        self.assertEqual(by_level[1448.991], 'CaveTun 00')
        self.assertEqual(by_level[1433.04], '17/57')

    def test_blank_labels_excluded_and_key_absent(self):
        suggestions = cluster_levels({100.0: 3, 200.0: 2})
        z_levels.attach_labels(suggestions, {100.0: {'  ': 3, '': 1}})
        for s in suggestions:
            self.assertNotIn('label', s)

    def test_tie_breaks_lexicographically(self):
        suggestions = cluster_levels({100.0: 4})
        z_levels.attach_labels(suggestions, {100.0: {'B lvl': 2, 'A lvl': 2}})
        self.assertEqual(suggestions[0]['label'], 'A lvl')

    def test_cluster_range_aggregates_labels(self):
        # Sub-metre scatter clusters; labels of ALL member values count.
        counts = {365.8: 3, 366.0: 40, 366.2: 5}
        suggestions = cluster_levels(counts)
        self.assertEqual(len(suggestions), 1)
        z_levels.attach_labels(suggestions, {
            365.8: {'Bench A': 3}, 366.0: {'Bench A': 30, 'Bench B': 10},
            366.2: {'Bench B': 5}})
        self.assertEqual(suggestions[0]['label'], 'Bench A')

    def test_inclusive_at_exact_bounds(self):
        suggestions = [{'level': 100.0, 'count': 1, 'lo': 100.0,
                        'hi': 102.0, 'suggested_tol': 1.5}]
        z_levels.attach_labels(suggestions, {102.0: {'Edge': 1}})
        self.assertEqual(suggestions[0]['label'], 'Edge')

    def test_none_and_garbage_value_labels(self):
        suggestions = cluster_levels({100.0: 1})
        z_levels.attach_labels(suggestions, None)
        z_levels.attach_labels(suggestions, {'abc': {'X': 1}})
        self.assertNotIn('label', suggestions[0])


class TestGapEpsilon(unittest.TestCase):

    def test_noise_at_threshold_is_deterministic(self):
        # 13 values exactly 2.0 m apart merge (gap == GAP_FLOOR); a 5e-9
        # perturbation of one gap must not flip that decision.
        clean = {1400.0 + 2.0 * i: 3 for i in range(13)}
        perturbed = dict(clean)
        del perturbed[1412.0]
        perturbed[1412.0 + 5e-9] = 3
        self.assertEqual([c['level'] for c in cluster_levels(clean)],
                         [c['level'] for c in cluster_levels(perturbed)])


class TestCoverageGuarantee(unittest.TestCase):

    def test_off_centre_mode_keeps_own_members(self):
        # Cluster {100.0, 100.4, 102.0} has a dominant mode at its top edge;
        # the neighbour clamp must not cut 100.0 out of the window.
        counts = {100.0: 1, 100.4: 1, 102.0: 10, 105.0: 5}
        result = cluster_levels(counts)
        self.assertEqual(len(result), 2)
        chip = result[0]
        self.assertEqual(chip['level'], 102.0)
        self.assertLessEqual(chip['level'] - chip['suggested_tol'],
                             100.0 + _COVER_EPS)
        # ...while still excluding the neighbouring cluster.
        self.assertLess(chip['level'] + chip['suggested_tol'], 105.0)
        assert_full_coverage(self, counts, result)


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


class TestLabelElevation(unittest.TestCase):

    def test_plain_and_embedded_numbers(self):
        for text, want in (('205', 205.0), ('205 Level', 205.0),
                           ('RL205', 205.0), ('  1450.5  ', 1450.5),
                           ('000 Level', 0.0), ('-30 Level', -30.0)):
            self.assertEqual(label_elevation(text), want, text)

    def test_ambiguous_or_absent_numbers_rejected(self):
        # Two numbers is a level *name* ('13/42'), not an RL — guessing 13
        # would plant a rung far from the data.
        for text in ('13/42', '17/57', 'Decline', '', '   ', None,
                     'Level 5 East 2'):
            self.assertIsNone(label_elevation(text), text)


class TestRangeVote(unittest.TestCase):

    def test_flat_features_vote_their_midpoint(self):
        self.assertEqual(range_vote(366.0, 366.0), 366.0)
        self.assertEqual(range_vote(204.0, 205.5), 204.75)
        # The FLAT_SPAN boundary is inclusive, and the label is ignored.
        self.assertEqual(range_vote(204.0, 206.0, '205'), 205.0)

    def test_named_level_wins_for_undulating_strings(self):
        # The Surpac case: a level's floor strings undulate, but the level
        # name pins them all to one rung.
        self.assertEqual(range_vote(203.1, 207.4, '205'), 205.0)
        self.assertEqual(range_vote(207.4, 203.1, '205 Level'), 205.0)
        # Slack lets a level's RL sit just outside its own envelope.
        self.assertEqual(range_vote(206.0, 210.0, '205'), 205.0)

    def test_unusable_label_falls_back_to_midpoint(self):
        # Label far from the envelope (stale/foreign RL) is not trusted.
        self.assertEqual(range_vote(203.0, 207.0, '1450'), 205.0)
        self.assertEqual(range_vote(201.8, 209.2, '13/42'), 205.5)
        self.assertEqual(range_vote(200.0, 210.0, 'DECLINE'), 205.0)
        self.assertEqual(range_vote(200.0, 210.0), 205.0)

    def test_declines_abstain(self):
        self.assertIsNone(range_vote(180.0, 260.0, 'DECLINE'))
        self.assertIsNone(range_vote(200.0, 220.5))
        # ...unless the string is filed under a level inside its envelope.
        self.assertEqual(range_vote(180.0, 260.0, '205'), 205.0)

    def test_span_cap_boundary_and_bad_input(self):
        self.assertEqual(range_vote(200.0, 220.0), 210.0)
        for bad in ((None, 205.0), (205.0, None), ('x', 205.0)):
            self.assertIsNone(range_vote(*bad), bad)

    def test_votes_stay_inside_the_feature_envelope(self):
        """A vote a feature's own window cannot reach is unreachable from
        the ladder — the label path must never leave [lo, hi] by more than
        the slack it was granted."""
        for lo, hi, label in ((203.1, 207.4, '205'), (206.0, 210.0, '205'),
                              (180.0, 260.0, '205'), (200.0, 210.0, None)):
            vote = range_vote(lo, hi, label)
            self.assertIsNotNone(vote)
            self.assertGreaterEqual(vote, lo - z_levels.LABEL_SLACK)
            self.assertLessEqual(vote, hi + z_levels.LABEL_SLACK)


if __name__ == '__main__':
    unittest.main()
