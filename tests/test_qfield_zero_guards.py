"""
Tests for the zero-value guards baked into the mapping template.

A numeric field of 0 must render exactly like a field that was never
filled in.  Without the guard a stray 0 lands in the EXTREME end of every
ramp - Width_cm = 0 draws the 0.55x hairline stroke and labels '0mm',
Percent = 0 draws the sparsest Overlay stipple - which is how a lost NULL
turns into a visibly wrong map.  scripts/inject_zero_value_guards.py bakes
the guard in; these tests make sure it stays baked and that the injector
constants that would re-bake it agree.

Reads the GeoPackage with sqlite3 only, no QGIS import, in the style of
tests/test_qfield_sidecar.py.

Run from the plugin root:
    python -m unittest discover tests
"""

import html
import importlib.util
import os
import sqlite3
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GPKG = os.path.join(_ROOT, 'Template', 'LGS_MappingTemplate.gpkg')
_SCRIPTS = os.path.join(_ROOT, 'scripts')

# Expressions are stored XML-escaped inside styleQML.
_Q = '&quot;'
_GT = '&gt;'
_LE = '&lt;='

# layer -> [(what, unguarded form that must be GONE, guarded form, min count)]
_EXPECTED = {
    '2 - Linework': [
        ('Width_cm ramp gate',
         'AND {q}Width_cm{q} IS NOT NULL THEN'.format(q=_Q),
         'AND coalesce({q}Width_cm{q}, 0) {gt} 0 THEN'.format(q=_Q, gt=_GT),
         240),
        ('Width_cm label text',
         'CASE WHEN {q}Width_cm{q} IS NULL THEN'.format(q=_Q),
         'CASE WHEN coalesce({q}Width_cm{q}, 0) {le} 0 THEN'.format(
             q=_Q, le=_LE),
         1),
        ('Mineral1Pct label gate',
         'AND {q}Mineral1Pct{q} IS NOT NULL THEN'.format(q=_Q),
         'AND coalesce({q}Mineral1Pct{q}, 0) {gt} 0 THEN'.format(q=_Q, gt=_GT),
         1),
        ('Mineral2Pct label gate',
         'AND {q}Mineral2Pct{q} IS NOT NULL THEN'.format(q=_Q),
         'AND coalesce({q}Mineral2Pct{q}, 0) {gt} 0 THEN'.format(q=_Q, gt=_GT),
         1),
        ('Mineral3Pct label gate',
         'AND {q}Mineral3Pct{q} IS NOT NULL THEN'.format(q=_Q),
         'AND coalesce({q}Mineral3Pct{q}, 0) {gt} 0 THEN'.format(q=_Q, gt=_GT),
         1),
    ],
    '3 - Overlay': [
        ('Percent density ramp',
         'CASE WHEN {q}Percent{q} IS NULL THEN 1'.format(q=_Q),
         'CASE WHEN coalesce({q}Percent{q}, 0) {le} 0 THEN 1'.format(
             q=_Q, le=_LE),
         8),
        ('Percent label branch',
         'CASE WHEN {q}Percent{q} IS NOT NULL THEN'.format(q=_Q),
         'CASE WHEN coalesce({q}Percent{q}, 0) {gt} 0 THEN'.format(
             q=_Q, gt=_GT),
         1),
    ],
}


def _style_qml(layer):
    con = sqlite3.connect('file:%s?mode=ro' % _GPKG.replace('\\', '/'),
                          uri=True)
    try:
        row = con.execute(
            'SELECT styleQML FROM layer_styles WHERE f_table_name=?',
            (layer,)).fetchone()
    finally:
        con.close()
    return row[0] if row else None


@unittest.skipUnless(os.path.exists(_GPKG), 'template gpkg not present')
class TestTemplateZeroGuards(unittest.TestCase):

    def test_guarded_form_is_baked(self):
        for layer, checks in _EXPECTED.items():
            qml = _style_qml(layer)
            self.assertIsNotNone(qml, layer)
            for what, _bare, guarded, count in checks:
                self.assertGreaterEqual(
                    qml.count(guarded), count,
                    '%s / %s: expected >=%d guarded expressions, found %d'
                    % (layer, what, count, qml.count(guarded)))

    def test_unguarded_form_is_gone(self):
        for layer, checks in _EXPECTED.items():
            qml = _style_qml(layer)
            for what, bare, _guarded, _count in checks:
                self.assertEqual(
                    qml.count(bare), 0,
                    '%s / %s: %d unguarded expression(s) remain - a 0 there '
                    'still renders as an extreme value'
                    % (layer, what, qml.count(bare)))


def _load(name):
    """Import an injector for its constants (main() is __main__-guarded)."""
    path = os.path.join(_SCRIPTS, name)
    spec = importlib.util.spec_from_file_location(
        'lgs_' + name[:-3], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(os.path.exists(_GPKG), 'template gpkg not present')
class TestInjectorConstantsAgree(unittest.TestCase):
    """The scripts that would RE-BAKE these expressions must generate
    exactly what is baked, or the next restyle silently undoes the guard.

    Comparing the generated expression against the template is stricter
    than grepping the source: it catches a constant that was guarded but
    drifted in any other way too.
    """

    @classmethod
    def setUpClass(cls):
        cls.linework = html.unescape(_style_qml('2 - Linework'))
        cls.overlay = html.unescape(_style_qml('3 - Overlay'))

    def _assert_baked(self, expr, blob, what, count):
        self.assertEqual(
            blob.count(expr), count,
            '%s: the injector would generate an expression that appears %d '
            'time(s) in the template (expected %d) - a re-run would change '
            'the baked styling.\n%s'
            % (what, blob.count(expr), count, expr))

    def test_weight_scaling_gate(self):
        # 239 stroke/marker overrides, plus 33 from the vein selvedge: the
        # 11 halo strokes each carry the ramp on their width, and each of
        # the 11 halo generators spends it twice more sizing its two offset
        # curves (inject_vein_generation_selvedge.lw_expression).
        module = _load('inject_weight_scaling.py')
        self._assert_baked(module.DETAIL_WIDTH_FACTOR, self.linework,
                           'inject_weight_scaling.DETAIL_WIDTH_FACTOR', 272)

    def test_label_size_scaling_gate(self):
        module = _load('inject_label_size_scaling.py')
        self._assert_baked(module.WIDTH_F, self.linework,
                           'inject_label_size_scaling.WIDTH_F', 1)

    def test_vein_fields_label_text(self):
        module = _load('inject_linework_vein_fields.py')
        self._assert_baked(module.WIDTH_TEXT, self.linework,
                           'inject_linework_vein_fields.WIDTH_TEXT', 1)

    def test_mineral_pct_label(self):
        module = _load('inject_linework_mineral_pcts.py')
        for n in (1, 2, 3):
            self._assert_baked(module.mineral_piece(n), self.linework,
                               'inject_linework_mineral_pcts.mineral_piece'
                               '(%d)' % n, 1)

    def test_overlay_percent(self):
        module = _load('inject_overlay_mineralisation.py')
        self._assert_baked(module.PCT_FACTOR, self.overlay,
                           'inject_overlay_mineralisation.PCT_FACTOR', 8)
        self._assert_baked(module.NEW_LABEL_BRANCH, self.overlay,
                           'inject_overlay_mineralisation.NEW_LABEL_BRANCH', 1)


if __name__ == '__main__':
    unittest.main()
