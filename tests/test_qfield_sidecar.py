"""
Unit tests for z_filter/qfield/__init__.py write_sidecar (pure python).

Run from the plugin root:
    python -m unittest discover tests
"""

import importlib.util
import os
import re
import tempfile
import unittest

# Load the module directly — importing the z_filter package would pull in qgis
# (the qfield submodule itself is qgis-free by design).
_path = os.path.join(os.path.dirname(__file__), '..',
                     'z_filter', 'qfield', '__init__.py')
_spec = importlib.util.spec_from_file_location('z_qfield', _path)
z_qfield = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(z_qfield)

write_sidecar = z_qfield.write_sidecar
SIDECAR_SOURCE = z_qfield.SIDECAR_SOURCE


def _flag_values(text):
    """Extract {marker_name: 'true'/'false'} from a sidecar's flag lines."""
    values = {}
    for match in re.finditer(
            r'^\s*readonly property bool \w+: (true|false) '
            r'// LGS-EXPORT-FLAG:(\w+)$', text, re.MULTILINE):
        values[match.group(2)] = match.group(1)
    return values


class TestWriteSidecar(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _write(self, **kwargs):
        path = write_sidecar(self.tmp.name, "proj", **kwargs)
        with open(path, encoding="utf-8") as fh:
            return path, fh.read()

    def test_source_has_both_markers_true(self):
        with open(SIDECAR_SOURCE, encoding="utf-8") as fh:
            flags = _flag_values(fh.read())
        self.assertEqual(flags, {'zfilter': 'true', 'scale': 'true'})

    def test_all_flag_combinations(self):
        for zfilter in (True, False):
            for scale in (True, False):
                path, text = self._write(zfilter=zfilter, scale=scale)
                flags = _flag_values(text)
                self.assertEqual(flags['zfilter'], str(zfilter).lower(),
                                 (zfilter, scale))
                self.assertEqual(flags['scale'], str(scale).lower(),
                                 (zfilter, scale))

    def test_output_path_uses_project_stem(self):
        path, _text = self._write()
        self.assertEqual(os.path.basename(path), "proj.qml")

    def test_only_flag_lines_differ_from_source(self):
        _path, text = self._write(zfilter=False, scale=False)
        with open(SIDECAR_SOURCE, encoding="utf-8") as fh:
            source = fh.read()
        diff = [(a, b) for a, b in zip(source.splitlines(), text.splitlines())
                if a != b]
        self.assertEqual(len(diff), 2, diff)
        self.assertTrue(all('LGS-EXPORT-FLAG' in a for a, _b in diff), diff)

    def test_missing_marker_raises(self):
        broken = os.path.join(self.tmp.name, "broken.qml")
        with open(broken, "w", encoding="utf-8") as fh:
            fh.write("Item {}\n")
        original = z_qfield.SIDECAR_SOURCE
        z_qfield.SIDECAR_SOURCE = broken
        try:
            with self.assertRaises(ValueError):
                write_sidecar(self.tmp.name, "proj")
        finally:
            z_qfield.SIDECAR_SOURCE = original

    def test_qml_braces_balanced(self):
        # Cheap parse smoke test on the shipped QML.
        with open(SIDECAR_SOURCE, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text.count('{'), text.count('}'))

    def test_qml_mirrors_extra_layer_support(self):
        # Drift tripwires for the hand-synced JS mirror of expression.py:
        # extra layers arrive via lgs_z_extra and range layers need the
        # range clause. If these disappear, the desktop panel and the
        # device disagree about what gets filtered.
        with open(SIDECAR_SOURCE, encoding="utf-8") as fh:
            text = fh.read()
        for needle in ('lgs_z_extra', 'zRangeClause', 'clauseForTarget',
                       'flatSpan', 'lgs_z_orig_x_'):
            self.assertIn(needle, text, needle)


if __name__ == '__main__':
    unittest.main()
