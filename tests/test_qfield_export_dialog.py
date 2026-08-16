"""
Tests for the QField exporter dialog's plugin-tool spec table.

The nine "Include ..." checkboxes are built from the _PLUGIN_TOOLS table in
qfield_export/gui/export_dialog.py and read back one-for-one into
OfflineConverter's include_*_plugin kwargs.  A table entry that is dropped,
misnamed or added without a matching kwarg would silently ship the wrong
feature set to the device, and nothing else in the suite would notice.

The dialog cannot be imported here (it pulls in qgis), so the source is
parsed with ast instead - the same qgis-free approach as
tests/test_qfield_sidecar.py.

Run from the plugin root:
    python -m unittest discover tests
"""

import ast
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIALOG = os.path.join(_ROOT, 'qfield_export', 'gui', 'export_dialog.py')
_CONVERTER = os.path.join(_ROOT, 'qfield_export', 'core',
                          'offline_converter.py')

# attribute suffix -> converter kwarg suffix, e.g.
# include_zfilter_check -> include_zfilter_plugin
_ATTR_PREFIX = 'include_'
_ATTR_SUFFIX = '_check'
_KWARG_SUFFIX = '_plugin'


def _parse(path):
    with open(path, encoding='utf-8') as fh:
        return ast.parse(fh.read(), filename=path)


def _plugin_tools():
    """-> [(attr, label, tooltip)] from the dialog's _PLUGIN_TOOLS literal."""
    for node in ast.walk(_parse(_DIALOG)):
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if '_PLUGIN_TOOLS' not in names:
            continue
        return [tuple(ast.literal_eval(e) for e in entry.elts)
                for entry in node.value.elts]
    raise AssertionError('_PLUGIN_TOOLS not found in %s' % _DIALOG)


def _converter_plugin_kwargs():
    """-> [include_*_plugin] kwarg names of OfflineConverter.__init__."""
    for node in ast.walk(_parse(_CONVERTER)):
        if isinstance(node, ast.FunctionDef) and node.name == '__init__':
            args = node.args.args + node.args.kwonlyargs
            return [a.arg for a in args
                    if a.arg.startswith(_ATTR_PREFIX)
                    and a.arg.endswith(_KWARG_SUFFIX)]
    raise AssertionError('OfflineConverter.__init__ not found')


def _start_export_kwargs():
    """-> {kwarg: attribute} read back in start_export's converter call."""
    reads = {}
    for node in ast.walk(_parse(_DIALOG)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == 'OfflineConverter'):
            continue
        for kw in node.keywords:
            # self.<attr>.isChecked()
            value = kw.value
            if not (isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and value.func.attr == 'isChecked'):
                continue
            inner = value.func.value
            if isinstance(inner, ast.Attribute):
                reads[kw.arg] = inner.attr
    return reads


class TestPluginToolSpec(unittest.TestCase):

    def test_spec_table_is_well_formed(self):
        tools = _plugin_tools()
        self.assertEqual(len(tools), 9, tools)
        for attr, label, tooltip in tools:
            self.assertTrue(attr.startswith(_ATTR_PREFIX), attr)
            self.assertTrue(attr.endswith(_ATTR_SUFFIX), attr)
            self.assertTrue(label.startswith('Include '), label)
            self.assertTrue(tooltip.strip(), attr)
        attrs = [t[0] for t in tools]
        self.assertEqual(len(attrs), len(set(attrs)), attrs)

    def test_labels_drop_the_redundant_suffix(self):
        # The collapsed section header says "QField Plugin Tools" once, so
        # the per-row "(QField plugin)" suffix was retired.
        for attr, label, _tooltip in _plugin_tools():
            self.assertNotIn('(QField plugin)', label, attr)

    def test_every_tool_has_a_converter_kwarg(self):
        expected = set(_converter_plugin_kwargs())
        actual = set(
            attr[:-len(_ATTR_SUFFIX)] + _KWARG_SUFFIX
            for attr, _label, _tooltip in _plugin_tools()
        )
        self.assertEqual(actual, expected)

    def test_start_export_reads_every_tool(self):
        reads = _start_export_kwargs()
        for attr, _label, _tooltip in _plugin_tools():
            kwarg = attr[:-len(_ATTR_SUFFIX)] + _KWARG_SUFFIX
            self.assertIn(kwarg, reads,
                          '%s is never read back into the converter' % attr)
            self.assertEqual(reads[kwarg], attr)


if __name__ == '__main__':
    unittest.main()
