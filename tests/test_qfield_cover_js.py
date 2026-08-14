"""
Tests for the transported-cover subset helpers inside the QField
companion sidecar (coverClause/stripCoverSubset/applyCoverToSubset in
z_filter/qfield/lgs_companion.qml — JS mirrors of the cover_* helpers
in z_filter/expression.py).

The functions are extracted verbatim from the QML and executed with
Node.js by tests/cover_harness.js. Skipped when node is absent.

Run from the plugin root:
    python -m unittest discover tests
"""

import os
import shutil
import subprocess
import unittest

_TESTS_DIR = os.path.dirname(__file__)
_HARNESS = os.path.join(_TESTS_DIR, 'cover_harness.js')
_QML = os.path.join(_TESTS_DIR, '..', 'z_filter', 'qfield',
                    'lgs_companion.qml')

_NODE = shutil.which('node')


@unittest.skipUnless(_NODE, 'node not available')
class TestCoverJs(unittest.TestCase):

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
