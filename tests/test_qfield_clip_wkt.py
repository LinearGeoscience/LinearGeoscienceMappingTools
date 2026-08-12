"""
Tests for the pure-JS WKT splitter inside the QField companion sidecar
(splitMultiPolygonWkt and helpers in z_filter/qfield/lgs_companion.qml).

The functions are extracted verbatim from the QML and executed with
Node.js by tests/wkt_splitter_harness.js — a drift tripwire for the
clip feature's only hand-rolled parser. Skipped when node is absent.

Run from the plugin root:
    python -m unittest discover tests
"""

import os
import shutil
import subprocess
import unittest

_TESTS_DIR = os.path.dirname(__file__)
_HARNESS = os.path.join(_TESTS_DIR, 'wkt_splitter_harness.js')
_QML = os.path.join(_TESTS_DIR, '..', 'z_filter', 'qfield',
                    'lgs_companion.qml')

_NODE = shutil.which('node')


@unittest.skipUnless(_NODE, 'node not available')
class TestClipWktSplitter(unittest.TestCase):

    def test_harness_passes(self):
        result = subprocess.run(
            [_NODE, _HARNESS, _QML],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(
            result.returncode, 0,
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        # Every case reports PASS; a FAIL line means a regression even
        # if the exit code lies.
        self.assertNotIn('FAIL', result.stdout, result.stdout)


if __name__ == '__main__':
    unittest.main()
