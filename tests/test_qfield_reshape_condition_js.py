"""
Tests for the pure-JS reshape line conditioning pipeline inside the
QField companion sidecar (reshapeDedupe / reshapeForce2DPolicy /
reshapeRemoveLoops / reshapeExtendEnds / reshapeConditionSequence in
z_filter/qfield/lgs_companion.qml, v32).

The functions are extracted verbatim from the QML and executed with
Node.js by tests/reshape_condition_harness.js. Skipped when node is
absent.

Run from the plugin root:
    python -m unittest discover tests
"""

import os
import shutil
import subprocess
import unittest

_TESTS_DIR = os.path.dirname(__file__)
_HARNESS = os.path.join(_TESTS_DIR, 'reshape_condition_harness.js')
_QML = os.path.join(_TESTS_DIR, '..', 'z_filter', 'qfield',
                    'lgs_companion.qml')

_NODE = shutil.which('node')


@unittest.skipUnless(_NODE, 'node not available')
class TestReshapeConditionJs(unittest.TestCase):

    def test_harness_passes(self):
        result = subprocess.run(
            [_NODE, _HARNESS, _QML],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0,
                         result.stdout + result.stderr)
        self.assertIn('PASS', result.stdout)
        self.assertNotIn('FAIL', result.stdout)


if __name__ == '__main__':
    unittest.main()
