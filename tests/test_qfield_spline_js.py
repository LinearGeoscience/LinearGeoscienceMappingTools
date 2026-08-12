"""
Tests for the pure-JS spline math inside the QField companion sidecar
(splineHermiteOpen/splineHermiteClosed and helpers in
z_filter/qfield/lgs_companion.qml).

The functions are extracted verbatim from the QML and executed with
Node.js by tests/spline_harness.js. Beyond the harness's structural
checks, this test generates numeric parity fixtures from a pure-Python
re-implementation of the desktop Hermite algorithm
(map_cleaning/core/spline_interp.py, minus the qgis-only simplify step,
so fixtures use tolerance=0 where both sides skip simplification) and
asserts the JS port matches to 1e-9. Skipped when node is absent.

Run from the plugin root:
    python -m unittest discover tests
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(__file__)
_HARNESS = os.path.join(_TESTS_DIR, 'spline_harness.js')
_QML = os.path.join(_TESTS_DIR, '..', 'z_filter', 'qfield',
                    'lgs_companion.qml')

_NODE = shutil.which('node')


# ---------------------------------------------------------------------
# Pure-Python mirror of the desktop Hermite math. Operation order copies
# spline_interp.py exactly (same IEEE ops in the same grouping) so the
# JS port must agree bit-for-bit at tolerance=0.
# ---------------------------------------------------------------------
def _tangent(p1, p2, k):
    return ((p2[0] - p1[0]) * k, (p2[1] - p1[1]) * k)


def _sample(p0, p1, t0, t1, s):
    h1 = (2 * (s ** 3)) - (3 * (s ** 2)) + 1
    h2 = 3 * (s ** 2) - 2 * (s ** 3)
    h3 = (s ** 3) - (2 * (s ** 2)) + s
    h4 = (s ** 3) - (s ** 2)
    x = (p0[0] * h1 + p1[0] * h2) + (t0[0] * h3 + t1[0] * h4)
    y = (p0[1] * h1 + p1[1] * h2) + (t0[1] * h3 + t1[1] * h4)
    return (x, y)


def hermite_open(points, tightness, max_segments):
    n = len(points)
    if n < 3:
        return list(points)
    tangents = [_tangent(points[0], points[1], tightness)]
    for i in range(1, n - 1):
        tangents.append(_tangent(points[i - 1], points[i + 1], tightness))
    tangents.append(_tangent(points[-2], points[-1], tightness))

    result = []
    for i in range(n - 1):
        result.append(points[i])
        t = 1.0 / float(max_segments)
        s = t
        while s < 1:
            result.append(_sample(points[i], points[i + 1],
                                  tangents[i], tangents[i + 1], s))
            s = s + t
    result.append(points[n - 1])
    return result


def hermite_closed_unclosed(points, tightness, max_segments):
    """Desktop hermite_closed on an UNCLOSED unique ring, without the
    closing duplicate the desktop appends — the rubberband model shape."""
    n = len(points)
    if n < 3:
        return list(points)
    tangents = []
    for i in range(n):
        tangents.append(_tangent(points[(i - 1) % n], points[(i + 1) % n],
                                 tightness))
    result = []
    for i in range(n):
        p1 = points[(i + 1) % n]
        result.append(points[i])
        t = 1.0 / float(max_segments)
        s = t
        while s < 1:
            result.append(_sample(points[i], p1,
                                  tangents[i], tangents[(i + 1) % n], s))
            s = s + t
    return result


@unittest.skipUnless(_NODE, 'node not available')
class TestSplineJs(unittest.TestCase):

    def _run_harness(self, fixture_path=None):
        cmd = [_NODE, _HARNESS, _QML]
        if fixture_path:
            cmd.append(fixture_path)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    def test_structural_harness_passes(self):
        result = self._run_harness()
        self.assertEqual(
            result.returncode, 0,
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        self.assertNotIn('FAIL', result.stdout, result.stdout)

    def test_numeric_parity_with_desktop_algorithm(self):
        wiggle = [(0.0, 0.0), (12.5, 7.3), (25.0, -4.1), (40.0, 2.2),
                  (55.5, -1.0)]
        ring = [(0.0, 0.0), (30.0, 5.0), (35.0, 28.0), (12.0, 40.0),
                (-6.0, 22.0)]
        cases = []
        for max_segments in (8, 200):
            for tightness in (0.5, 0.8):
                cases.append({
                    'name': f'open t={tightness} seg={max_segments}',
                    'points': [list(p) for p in wiggle],
                    'tightness': tightness,
                    'tolerance': 0,
                    'maxSegments': max_segments,
                    'closed': False,
                    'expected': [list(p) for p in hermite_open(
                        wiggle, tightness, max_segments)],
                })
                cases.append({
                    'name': f'closed t={tightness} seg={max_segments}',
                    'points': [list(p) for p in ring],
                    'tightness': tightness,
                    'tolerance': 0,
                    'maxSegments': max_segments,
                    'closed': True,
                    'expected': [list(p) for p in hermite_closed_unclosed(
                        ring, tightness, max_segments)],
                })

        with tempfile.TemporaryDirectory() as tmp:
            fixture_path = os.path.join(tmp, 'spline_fixture.json')
            with open(fixture_path, 'w', encoding='utf-8') as handle:
                json.dump({'cases': cases}, handle)
            result = self._run_harness(fixture_path)

        self.assertEqual(
            result.returncode, 0,
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        self.assertNotIn('FAIL', result.stdout, result.stdout)
        # All eight parity cases must actually have run.
        self.assertEqual(result.stdout.count('PASS parity:'), 8,
                         result.stdout)


if __name__ == '__main__':
    unittest.main()
