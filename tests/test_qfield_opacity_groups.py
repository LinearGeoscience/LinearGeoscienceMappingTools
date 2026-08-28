"""
Tests for the exporter's layer-tree folder walk
(OfflineConverter._collect_opacity_groups in
qfield_export/core/offline_converter.py).

The folder rows of the sidecar's Layer Opacity panel are resolved here
and baked into the QML, because QML cannot walk the project layer tree.
Getting the walk wrong ships folders that set the wrong layers, or none.

The converter cannot be imported (it pulls in qgis), so the method's
source is extracted with ast and executed against stub tree nodes - the
same qgis-free approach as tests/test_qfield_export_dialog.py.

Run from the plugin root:
    python -m unittest discover tests
"""

import ast
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONVERTER = os.path.join(_ROOT, 'qfield_export', 'core',
                          'offline_converter.py')


class _Layer:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _TreeLayer:
    """Stand-in for QgsLayerTreeLayer."""

    def __init__(self, name, missing=False):
        self._layer = None if missing else _Layer(name)

    def layer(self):
        return self._layer


class _TreeGroup:
    """Stand-in for QgsLayerTreeGroup."""

    def __init__(self, name, children=()):
        self._name = name
        self._children = list(children)

    def name(self):
        return self._name

    def children(self):
        return self._children


def _load_collect():
    """-> the _collect_opacity_groups function, wired to the stubs."""
    with open(_CONVERTER, encoding='utf-8') as fh:
        tree = ast.parse(fh.read(), filename=_CONVERTER)
    for node in ast.walk(tree):
        if (isinstance(node, ast.FunctionDef)
                and node.name == '_collect_opacity_groups'):
            module = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(module)
            namespace = {'QgsLayerTreeLayer': _TreeLayer,
                         'QgsLayerTreeGroup': _TreeGroup}
            exec(compile(module, _CONVERTER, 'exec'), namespace)
            return namespace['_collect_opacity_groups']
    raise AssertionError('_collect_opacity_groups not found')


class _Converter:
    """Just the attributes the method touches."""

    def __init__(self, root, rasters=(), vectors=()):
        self._raster_layer_names = list(rasters)
        self._vector_layer_names = list(vectors)

        class _Project:
            def layerTreeRoot(self_inner):
                return root

        self.project = _Project()


class TestCollectOpacityGroups(unittest.TestCase):

    def setUp(self):
        self.collect = _load_collect()

    def test_no_exported_layers(self):
        root = _TreeGroup('', [_TreeGroup('Imagery', [_TreeLayer('Ortho')])])
        self.assertEqual(self.collect(_Converter(root)), [])

    def test_group_of_two_is_kept(self):
        root = _TreeGroup('', [
            _TreeGroup('Imagery', [_TreeLayer('Ortho'), _TreeLayer('Hill')])])
        groups = self.collect(
            _Converter(root, rasters=['Ortho', 'Hill']))
        self.assertEqual(groups, [{'name': 'Imagery',
                                   'layers': ['Ortho', 'Hill']}])

    def test_single_member_group_is_dropped(self):
        # The layer's own row already covers it.
        root = _TreeGroup('', [_TreeGroup('Imagery', [_TreeLayer('Ortho')])])
        self.assertEqual(self.collect(_Converter(root, rasters=['Ortho'])), [])

    def test_unexported_layers_are_ignored(self):
        root = _TreeGroup('', [
            _TreeGroup('Imagery', [_TreeLayer('Ortho'), _TreeLayer('Secret'),
                                   _TreeLayer('Hill')])])
        groups = self.collect(_Converter(root, rasters=['Ortho', 'Hill']))
        self.assertEqual(groups[0]['layers'], ['Ortho', 'Hill'])

    def test_layer_with_no_layer_object_is_skipped(self):
        # A broken/unresolved tree node must not crash the walk.
        root = _TreeGroup('', [
            _TreeGroup('Imagery', [_TreeLayer('Ortho'),
                                   _TreeLayer('Gone', missing=True),
                                   _TreeLayer('Hill')])])
        groups = self.collect(_Converter(root, rasters=['Ortho', 'Hill']))
        self.assertEqual(groups[0]['layers'], ['Ortho', 'Hill'])

    def test_root_level_layers_make_no_group(self):
        root = _TreeGroup('', [_TreeLayer('Ortho'), _TreeLayer('Hill')])
        self.assertEqual(self.collect(
            _Converter(root, rasters=['Ortho', 'Hill'])), [])

    def test_mixed_raster_and_vector_membership(self):
        root = _TreeGroup('', [
            _TreeGroup('Site', [_TreeLayer('Ortho'), _TreeLayer('Mapping')])])
        groups = self.collect(_Converter(root, rasters=['Ortho'],
                                         vectors=['Mapping']))
        self.assertEqual(groups[0]['layers'], ['Ortho', 'Mapping'])

    def test_nested_group_carries_descendants_and_reads_top_down(self):
        # A parent folder sets everything beneath it, and the rows come
        # out in legend reading order (parent before child).
        root = _TreeGroup('', [
            _TreeGroup('Imagery', [
                _TreeLayer('Ortho'),
                _TreeGroup('Historic', [_TreeLayer('1998'),
                                        _TreeLayer('2004')])])])
        groups = self.collect(_Converter(
            root, rasters=['Ortho', '1998', '2004']))
        self.assertEqual([g['name'] for g in groups],
                         ['Imagery', 'Imagery / Historic'])
        self.assertEqual(groups[0]['layers'], ['Ortho', '1998', '2004'])
        self.assertEqual(groups[1]['layers'], ['1998', '2004'])

    def test_sibling_groups_keep_legend_order(self):
        root = _TreeGroup('', [
            _TreeGroup('Alpha', [_TreeLayer('a1'), _TreeLayer('a2')]),
            _TreeGroup('Beta', [_TreeLayer('b1'), _TreeLayer('b2')])])
        groups = self.collect(_Converter(
            root, rasters=['a1', 'a2', 'b1', 'b2']))
        self.assertEqual([g['name'] for g in groups], ['Alpha', 'Beta'])

    def test_same_named_groups_stay_distinct_by_path(self):
        root = _TreeGroup('', [
            _TreeGroup('Pit', [
                _TreeGroup('Imagery', [_TreeLayer('p1'), _TreeLayer('p2')])]),
            _TreeGroup('UG', [
                _TreeGroup('Imagery', [_TreeLayer('u1'), _TreeLayer('u2')])])])
        groups = self.collect(_Converter(
            root, rasters=['p1', 'p2', 'u1', 'u2']))
        names = [g['name'] for g in groups]
        self.assertIn('Pit / Imagery', names)
        self.assertIn('UG / Imagery', names)
        self.assertEqual(len(set(names)), len(names))

    def test_unnamed_group_gets_a_label(self):
        root = _TreeGroup('', [
            _TreeGroup('', [_TreeLayer('a'), _TreeLayer('b')])])
        groups = self.collect(_Converter(root, rasters=['a', 'b']))
        self.assertEqual(groups[0]['name'], 'Group')

    def test_broken_tree_returns_empty(self):
        class _Boom:
            def children(self):
                raise RuntimeError('no tree')

        self.assertEqual(self.collect(_Converter(_Boom(), rasters=['a'])), [])


if __name__ == '__main__':
    unittest.main()
