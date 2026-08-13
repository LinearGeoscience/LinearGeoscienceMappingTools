"""
Parity tests for the level-clustering JS mirror inside the QField
companion sidecar (clusterLevels/suggestTolerance/suggestStep and helpers
in z_filter/qfield/lgs_companion.qml).

The functions AND their constants are extracted verbatim from the QML and
executed with Node.js by tests/z_levels_harness.js; this test generates
fixtures from z_filter/levels.py and asserts the JS port matches to 1e-9.
Skipped when node is absent.

Run from the plugin root:
    python -m unittest discover tests
"""

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(__file__)
_HARNESS = os.path.join(_TESTS_DIR, 'z_levels_harness.js')
_QML = os.path.join(_TESTS_DIR, '..', 'z_filter', 'qfield',
                    'lgs_companion.qml')

_NODE = shutil.which('node')

_levels_path = os.path.join(_TESTS_DIR, '..', 'z_filter', 'levels.py')
_spec = importlib.util.spec_from_file_location('z_levels_parity',
                                               _levels_path)
z_levels = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(z_levels)

_expr_path = os.path.join(_TESTS_DIR, '..', 'z_filter', 'expression.py')
_espec = importlib.util.spec_from_file_location('z_expression_parity',
                                                _expr_path)
z_expression = importlib.util.module_from_spec(_espec)
_espec.loader.exec_module(z_expression)


CASES = {
    # RB UG strings.shp (Red Bird) — the discrete-fast-path regression.
    'rb_ug_strings': {1419.5220453189381: 5, 1433.0369193011243: 4,
                      1435.0369193011243: 10, 1437.1999999934155: 1,
                      1439.2: 8, 1448.9914748780934: 1,
                      1450.0: 5, 1452.0: 1},
    'single_value': {366.0: 500},
    'typed_rls': {366.0: 214, 376.0: 180, 386.0: 90},
    'noisy_benches': {365.8: 3, 366.0: 40, 366.2: 5,
                      375.9: 2, 376.0: 30, 376.1: 4},
    'no_dominant_mode': {365.7: 10, 366.1: 10, 366.5: 10},
    'mixed_clean_noisy': {320.0: 50, 365.8: 3, 366.0: 40, 366.2: 5},
    'close_clusters': {365.0: 5, 366.0: 5, 367.0: 5,
                       371.0: 5, 372.0: 5, 373.0: 5},
    'off_centre_mode': {100.0: 1, 100.4: 1, 102.0: 10, 105.0: 5},
    'wide_span_discrete': {0.0: 5, 100.0: 7, 250.0: 3},
    'thirteen_levels': {1400.0 + 2.0 * i: 3 for i in range(13)},
    'continuous_survey': {float(v): 1 for v in range(320, 411)},
}

# Level-name texts seen at each elevation (attach_labels input) for the
# cases that exercise the label mirror; other cases run with none.
CASE_LABELS = {
    'rb_ug_strings': {1450.0: {'000 Level': 1},
                      1448.9914748780934: {'CaveTun 00': 1},
                      1433.0369193011243: {'17/57': 3, '13/42': 1},
                      1419.5220453189381: {'30/100': 1, '13/42': 4}},
    'noisy_benches': {365.8: {'Bench A': 3},
                      366.0: {'Bench A': 30, 'Bench B': 10},
                      366.2: {'Bench B': 5},
                      376.0: {'  ': 2}},   # blank — must not label 376
    'off_centre_mode': {100.0: {'Tie B': 2}, 100.4: {'Tie A': 2}},
}


# (z_min, z_max, label) inputs for the range_vote/rangeVote mirror — the
# rule that decides which elevation a survey string votes for.
VOTE_CASES = {
    'flat_single': (366.0, 366.0, None),
    'flat_range': (204.0, 205.5, None),
    'named_level': (203.1, 207.4, '205'),
    'named_level_text': (203.1, 207.4, '205 Level'),
    'named_rl_prefix': (203.1, 207.4, 'RL205'),
    'label_within_slack': (206.0, 210.0, '205'),
    'label_outside_envelope': (203.1, 207.4, '1450'),
    'ambiguous_label': (201.8, 209.2, '13/42'),
    'zero_level': (-1.0, 1.5, '000 Level'),
    'unlabelled_undulating': (200.0, 210.0, None),
    'non_numeric_label': (200.0, 210.0, 'DECLINE'),
    'decline_abstains': (180.0, 260.0, 'DECLINE'),
    'decline_named_inside': (180.0, 260.0, '205'),
    'reversed_bounds': (207.4, 203.1, '205'),
    'exactly_flat_span': (204.0, 206.0, '205'),
    'just_over_cap': (200.0, 220.5, None),
}


@unittest.skipIf(_NODE is None, 'node.exe not on PATH — JS parity skipped')
class TestZLevelsJsParity(unittest.TestCase):

    def test_mirror_matches_python(self):
        cases = []
        for name, counts in CASES.items():
            value_labels = CASE_LABELS.get(name, {})
            clusters = z_levels.attach_labels(
                z_levels.cluster_levels(counts), value_labels)
            cases.append({
                'name': name,
                'counts': counts,
                'value_labels': value_labels,
                'clusters': [{key: c[key] for key in
                              ('level', 'count', 'lo', 'hi',
                               'suggested_tol', 'label') if key in c}
                             for c in clusters],
                'auto': z_levels.suggest_tolerance(clusters),
                'step': z_levels.suggest_step(clusters),
            })
        # Baked lgs_z_suggest payload parity: python format → JS parse must
        # equal python parse. Real cluster shapes plus malformed inputs.
        baked = []
        for name in ('rb_ug_strings', 'noisy_benches', 'continuous_survey'):
            clusters = z_levels.attach_labels(
                z_levels.cluster_levels(CASES[name]),
                CASE_LABELS.get(name, {}))
            span = z_levels.value_range(CASES[name])
            payload = z_expression.format_suggestions(clusters, {
                'min': span[0], 'max': span[1], 'with_elev': span[2],
                'blank': 7, 'spanning': 1})
            baked.append({'name': name, 'payload': payload,
                          'want': z_expression.parse_suggestions(payload)})
        for name, bad in (('malformed', 'not json'), ('empty', ''),
                          ('wrong_version', '{"v":2,"levels":[]}'),
                          ('no_levels', '{"v":1,"levels":[]}')):
            self.assertIsNone(z_expression.parse_suggestions(bad))
            baked.append({'name': name, 'payload': bad, 'want': None})

        votes = [{'name': name, 'z_min': z_min, 'z_max': z_max,
                  'label': label,
                  'want': z_levels.range_vote(z_min, z_max, label)}
                 for name, (z_min, z_max, label) in VOTE_CASES.items()]

        handle, fixture_path = tempfile.mkstemp(suffix='.json')
        try:
            with os.fdopen(handle, 'w') as fh:
                json.dump({'cases': cases, 'baked': baked, 'votes': votes},
                          fh)
            result = subprocess.run(
                [_NODE, _HARNESS, _QML, fixture_path],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(
                result.returncode, 0,
                "JS/python mirror drift:\n%s%s" % (result.stdout,
                                                   result.stderr))
        finally:
            os.unlink(fixture_path)


if __name__ == '__main__':
    unittest.main()
