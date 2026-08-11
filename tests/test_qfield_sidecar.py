"""
Unit tests for z_filter/qfield/__init__.py write_sidecar (pure python).

Run from the plugin root:
    python -m unittest discover tests
"""

import importlib.util
import json
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


def _data_values(text):
    """Extract {marker_name: json_text} from a sidecar's data lines."""
    values = {}
    for match in re.finditer(
            r'^\s*readonly property var \w+: (\[.*\]) '
            r'// LGS-EXPORT-DATA:(\w+)$', text, re.MULTILINE):
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

    def test_source_has_all_markers_true(self):
        with open(SIDECAR_SOURCE, encoding="utf-8") as fh:
            source = fh.read()
        self.assertEqual(_flag_values(source),
                         {'zfilter': 'true', 'scale': 'true',
                          'opacity': 'true'})
        # Data lines ship empty in source; the exporter fills them.
        self.assertEqual(_data_values(source), {'opacitylayers': '[]'})

    def test_all_flag_combinations(self):
        for zfilter in (True, False):
            for scale in (True, False):
                for opacity in (True, False):
                    path, text = self._write(zfilter=zfilter, scale=scale,
                                             opacity=opacity)
                    flags = _flag_values(text)
                    combo = (zfilter, scale, opacity)
                    self.assertEqual(flags['zfilter'], str(zfilter).lower(),
                                     combo)
                    self.assertEqual(flags['scale'], str(scale).lower(),
                                     combo)
                    self.assertEqual(flags['opacity'], str(opacity).lower(),
                                     combo)

    def test_output_path_uses_project_stem(self):
        path, _text = self._write()
        self.assertEqual(os.path.basename(path), "proj.qml")

    def test_only_flag_lines_differ_from_source(self):
        # opacity_layers=None rewrites the data line to [] — identical to
        # source — so only the three flag lines may differ.
        _path, text = self._write(zfilter=False, scale=False, opacity=False)
        with open(SIDECAR_SOURCE, encoding="utf-8") as fh:
            source = fh.read()
        diff = [(a, b) for a, b in zip(source.splitlines(), text.splitlines())
                if a != b]
        self.assertEqual(len(diff), 3, diff)
        self.assertTrue(all('LGS-EXPORT-FLAG' in a for a, _b in diff), diff)

    def test_opacity_layers_data_line(self):
        names = ['Ortho 2024', 'Say "hi"']
        _path, text = self._write(opacity_layers=names)
        data = _data_values(text)
        self.assertEqual(data['opacitylayers'], json.dumps(names))
        # Round-trips through JSON despite the embedded quote.
        self.assertEqual(json.loads(data['opacitylayers']), names)

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
                       'flatSpan', 'lgs_z_orig_x_',
                       # Adjacent-levels, opacity toggle and level stepping:
                       'lgs_z_adjacent', 'clauseForTargetMulti',
                       'lgs_opacity', 'opacityLayers', 'stepLevel'):
            self.assertIn(needle, text, needle)


if __name__ == '__main__':
    unittest.main()
