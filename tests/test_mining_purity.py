"""
Guards the test strategy itself.

Every module in mining_import's pure layer must stay importable without QGIS,
because that is the only reason parsers can be unit-tested at all. A stray
`from qgis.core import ...` at module scope in a reader would silently take
the whole suite with it, so it is asserted rather than assumed.

Also checks the registry's lazy loader still resolves readers when this
package has been loaded by file path (__package__ is None), which is exactly
the situation the tests run in.
"""

import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pure_loader  # noqa: E402


def _module_scope_imports(path):
    """Modules imported at module scope — imports inside functions are fine."""
    with open(path, 'r', encoding='utf-8') as fh:
        tree = ast.parse(fh.read(), path)
    names = set()
    for node in tree.body:  # top level only
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                names.add(node.module)
        elif isinstance(node, ast.Try):
            # The dual-import idiom lives in a try/except at module scope.
            for sub in node.body + [h for handler in node.handlers
                                    for h in handler.body]:
                if isinstance(sub, ast.Import):
                    names.update(alias.name for alias in sub.names)
                elif isinstance(sub, ast.ImportFrom) and sub.module \
                        and sub.level == 0:
                    names.add(sub.module)
    return names


class TestPureLayerHasNoQgisImports(unittest.TestCase):

    def test_no_module_scope_qgis_import(self):
        offenders = []
        for relative in pure_loader.pure_module_paths():
            path = os.path.join(pure_loader.PACKAGE_ROOT,
                                relative.replace('/', os.sep))
            for name in _module_scope_imports(path):
                if name == 'qgis' or name.startswith('qgis.'):
                    offenders.append('{0} imports {1}'.format(relative, name))
        self.assertEqual(
            offenders, [],
            'Pure modules must not import qgis at module scope — doing so '
            'makes them untestable outside QGIS:\n' + '\n'.join(offenders))

    def test_every_pure_module_actually_loads(self):
        for relative in pure_loader.pure_module_paths():
            with self.subTest(module=relative):
                self.assertIsNotNone(pure_loader.load(relative))


class TestRegistryLazyLoading(unittest.TestCase):

    def setUp(self):
        self.registry = pure_loader.load('registry.py')

    def test_str_resolves_to_surpac(self):
        specs = self.registry.formats_for_extension('.str')
        self.assertEqual([s.key for s in specs], ['surpac'])

    def test_extension_lookup_is_case_and_dot_insensitive(self):
        self.assertEqual(
            [s.key for s in self.registry.formats_for_extension('STR')],
            ['surpac'])
        self.assertEqual(
            [s.key for s in self.registry.formats_for_extension('.STR')],
            ['surpac'])

    def test_reader_loads_with_no_qgis_present(self):
        # The whole point of the string-based registry: this must work when
        # registry.py itself was loaded by file path.
        self.assertNotIn('qgis', sys.modules)
        reader = self.registry.reader_for(self.registry.spec('surpac'))
        self.assertTrue(callable(reader))
        self.assertEqual(reader.__name__, 'read_file')

    def test_sniffer_loads_too(self):
        sniffer = self.registry.sniffer_for(self.registry.spec('surpac'))
        self.assertTrue(callable(sniffer))

    def test_unknown_key_raises(self):
        with self.assertRaises(self.registry.UnknownFormat):
            self.registry.spec('nonsense')

    def test_companion_extensions_do_not_appear_as_sources(self):
        # A .dtm is consumed alongside its .str, never scanned as a source in
        # its own right -- otherwise every level would import twice.
        self.assertIn('.dtm', self.registry.companion_extensions())
        self.assertNotIn('.dtm', self.registry.source_extensions())

    def test_planned_formats_are_named_not_silently_ignored(self):
        self.assertEqual(self.registry.planned_label('x.dxf'), 'AutoCAD DXF')
        self.assertIsNone(self.registry.planned_label('x.str'))
        self.assertIsNone(self.registry.planned_label('x.docx'))


if __name__ == '__main__':
    unittest.main()
