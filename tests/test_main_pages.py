"""
The main dialog's page wiring is a positional contract: PAGE_DEFS[N] must
line up with the Nth stacked.addWidget(self._build_page_*()) call. Nothing
enforces that at runtime — a page added to one list and not the other puts
every later page under the wrong nav button, silently.

mainplugin.py cannot be imported (it needs a live iface), so the source is
parsed with ast — the same qgis-free approach as test_qfield_sidecar.py.

Run from the plugin root:
    python -m unittest discover tests
"""

import ast
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAIN = os.path.join(_ROOT, 'mainplugin.py')


def _read():
    with open(_MAIN, encoding='utf-8') as fh:
        return fh.read()


def _tree():
    return ast.parse(_read(), filename=_MAIN)


def _page_defs(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'PAGE_DEFS'
                for t in node.targets):
            return [ast.literal_eval(e) for e in node.value.elts]
    raise AssertionError('PAGE_DEFS not found')


def _stacked_builders(tree):
    """Builder names in the order they are added to the stack."""
    names = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and getattr(node.func, 'attr', '') == 'addWidget'
                and node.args
                and isinstance(node.args[0], ast.Call)
                and getattr(node.args[0].func, 'attr', '').startswith(
                    '_build_page')):
            names.append(node.args[0].func.attr)
    return names


def _defined_methods(tree):
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


class TestPageWiring(unittest.TestCase):

    def setUp(self):
        self.tree = _tree()
        self.pages = _page_defs(self.tree)
        self.builders = _stacked_builders(self.tree)
        self.methods = _defined_methods(self.tree)

    def test_one_builder_per_page(self):
        self.assertEqual(
            len(self.builders), len(self.pages),
            "PAGE_DEFS and the stacked widget must stay the same length, "
            "or pages land under the wrong nav button")

    def test_every_builder_exists(self):
        for name in self.builders:
            self.assertIn(name, self.methods, name)

    def test_no_orphan_page_builders(self):
        defined = {m for m in self.methods if m.startswith('_build_page')}
        self.assertEqual(defined - set(self.builders), set(),
                         "a page builder exists but is never added")

    def test_page_tuples_are_well_formed(self):
        for page in self.pages:
            self.assertEqual(len(page), 4, page)
            nav, icon, tooltip, title = page
            self.assertTrue(nav and nav.strip(), page)
            self.assertIsNone(icon, "no page ships an icon today")
            self.assertTrue(tooltip and tooltip.strip(), page)
            self.assertTrue(title and title.strip(), page)

    def test_nav_labels_are_unique(self):
        labels = [p[0] for p in self.pages]
        self.assertEqual(len(labels), len(set(labels)), labels)


class TestFieldPage(unittest.TestCase):
    """The Field / Pit / UG page gathers the pit and underground tools."""

    def setUp(self):
        self.source = _read()
        self.tree = _tree()
        self.pages = _page_defs(self.tree)

    def test_the_page_exists_and_is_named_consistently(self):
        labels = [p[0] for p in self.pages]
        self.assertIn("Field / Pit / UG", labels)
        page = self.pages[labels.index("Field / Pit / UG")]
        self.assertEqual(page[0], page[3],
                         "nav label and page title must agree — they used "
                         "to say 'Pit / Underground' and 'Z Filtering'")

    def _field_page_source(self):
        for node in ast.walk(self.tree):
            if (isinstance(node, ast.FunctionDef)
                    and node.name == '_build_page_field'):
                return ast.get_source_segment(self.source, node)
        raise AssertionError('_build_page_field not found')

    def test_it_carries_every_moved_tool(self):
        body = self._field_page_source()
        for handler in ('self.run_pit_surface_dem',
                        'self.run_generate_contours',
                        'self.run_optimise_imagery',
                        'self.run_mining_import',
                        'self.toggle_z_filter_panel',
                        'self.run_add_elevation_field'):
            self.assertIn(handler, body, handler)

    def test_the_moved_tools_left_their_old_pages(self):
        """One home per tool — no duplicate entries."""
        for name in ('_build_page_layouts', '_build_page_data'):
            for node in ast.walk(self.tree):
                if isinstance(node, ast.FunctionDef) and node.name == name:
                    body = ast.get_source_segment(self.source, node)
                    for handler in ('run_pit_surface_dem',
                                    'run_generate_contours',
                                    'run_mining_import'):
                        self.assertNotIn(handler, body,
                                         '{0} still in {1}'.format(handler,
                                                                   name))

    def test_every_handler_it_calls_is_defined(self):
        methods = _defined_methods(self.tree)
        body = self._field_page_source()
        for node in ast.walk(ast.parse(body.strip())):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == 'self'
                    and (node.attr.startswith('run_')
                         or node.attr.startswith('toggle_'))):
                self.assertIn(node.attr, methods, node.attr)


class TestOptimiseImageryWiring(unittest.TestCase):

    def test_handler_and_help_text_exist(self):
        source = _read()
        self.assertIn('def run_optimise_imagery', source)
        self.assertIn('feature_info.INFO_OPTIMISE_IMAGERY', source)
        info = os.path.join(_ROOT, 'feature_info.py')
        with open(info, encoding='utf-8') as fh:
            self.assertIn('INFO_OPTIMISE_IMAGERY', fh.read())

    def test_handler_imports_lazily_and_reports_failure(self):
        tree = _tree()
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and node.name == 'run_optimise_imagery'):
                body = ast.get_source_segment(_read(), node)
                self.assertIn('from .raster_optimise.dialog import run',
                              body, 'lazy import keeps QGIS startup cheap')
                self.assertIn('pushCritical', body,
                              'a failure must reach the user')
                return
        self.fail('run_optimise_imagery not found')


if __name__ == '__main__':
    unittest.main()
