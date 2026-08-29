"""
Every LGS code the GSWA transposition emits, checked against the real template.

This is the test that matters for scripts/prepare_gswa_import.py, because the
failure it catches is silent. A GeoPackage enforces no foreign key on
Lithology1 or Type: a mistyped code writes cleanly, survives the import, and
then draws in the renderer's no-category symbol with nothing anywhere saying
why. Nobody notices until they look at the map and count the greys.

So the assertions run against the shipped template's own domains - the same
CodeDomain objects the import wizard resolves against - rather than a copy of
the code lists kept here, which would drift.

The second thing checked is which SIDE of the cover-vs-bedrock gate each unit
lands on. GSWA prefix their Cainozoic units with '_', and those have to come
out as Transported Cover or Regolith; their bedrock units must come out as
Lithology. That is decided by BasemapCodes.Type through derive.fill_parents(),
so it is a property of the code chosen here, and getting it wrong would put
sheetwash in the bedrock palette without erroring.

Run:  python tests\\test_gswa_mapping.py
"""

import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import import_loader  # noqa: E402


def _load_script():
    """scripts/prepare_gswa_import.py, without GDAL."""
    path = os.path.join(import_loader.PLUGIN_ROOT, 'scripts',
                        'prepare_gswa_import.py')
    spec = importlib.util.spec_from_file_location('prepare_gswa_import', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gswa = _load_script()


# The full unit vocabulary of the sheet this was built against. Pinned so that
# editing GSWA_POLY cannot quietly drop a unit and leave its polygons unmapped.
MULGUL_POLY_CODES = frozenset({
    '_Ad', '_S', '_A1', '_A1-k', '_A2', '_A3', '_A3-f',
    '_C1', '_C1-f', '_C2', '_C2-f', '_C3', '_C3-f', '_C3-f-n',
    '_W', '_Wt', '_W-f', '_R-f', '_R-f-n', '_R-k',
    'P_-MEi-kd', 'P_-MEi-sl', 'P_-MEi-sf', 'P_-MEi-ss', 'P_-MEiw-st',
    'P_-MEk-kd', 'P_-MEk-sl', 'P_-MEk-sli', 'P_-MEk-sf', 'P_-MEk-ss',
    'P_-MEk-st', 'P_-MEk-stq', 'P_-MEk-sp',
    'P_-MEl-sl', 'P_-MEl-ss', 'P_-MEv-kd', 'P_-MEv-sl', 'P_-MEd-cl',
    'P_-MEy-st', 'P_-MEy-mts', 'P_-MCb-st', 'P_-_nr-od', 'P_-MO-gmeb',
})

MULGUL_LINE_KEYS = frozenset({
    ('fault', 'exposed'),
    ('fault', 'concealed'),
    ('fold, showing axial trace', 'anticline, exposed'),
    ('fold, showing axial trace', 'anticline, concealed'),
    ('fold, showing axial trace', 'syncline, exposed'),
    ('fold, showing axial trace', 'syncline, concealed'),
})

COVER_SIDE = ('Transported Cover', 'Regolith')


class GswaMappingTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        model = import_loader.template_model()
        cls.basemap = model.layers['4 - Basemap']
        cls.linework = model.layers['2 - Linework']

    def assertInDomain(self, layer, field, value, where):
        domain = layer.domain(field)
        self.assertIsNotNone(
            domain, '{0}.{1} has no code domain'.format(layer.name, field))
        self.assertIsNotNone(
            domain.canonical_code(value),
            '{0}: {1!r} is not a {2}.{3} code'.format(
                where, value, layer.name, field))

    # ── the codes exist ─────────────────────────────────────────────

    def test_every_polygon_lithology_is_a_real_basemap_code(self):
        for code, (lith1, lith2, _, _, _) in gswa.GSWA_POLY.items():
            self.assertInDomain(self.basemap, 'Lithology1', lith1, code)
            if lith2:
                self.assertInDomain(self.basemap, 'Lithology2', lith2, code)

    def test_every_fallback_lithology_is_a_real_basemap_code(self):
        for name, (lith1, lith2) in gswa.LITH_BY_NAME.items():
            self.assertInDomain(self.basemap, 'Lithology1', lith1, name)
            if lith2:
                self.assertInDomain(self.basemap, 'Lithology2', lith2, name)
        for family, lith1 in gswa.REGOLITH_BY_FAMILY.items():
            self.assertInDomain(self.basemap, 'Lithology1', lith1, family)

    def test_every_mineral_is_a_real_mineral_code(self):
        # MineralCodes keys on Value, not Code - the domain knows that, which
        # is exactly why this asks the domain rather than the table.
        minerals = {row[3] for row in gswa.GSWA_POLY.values() if row[3]}
        minerals.update(m for _, m in gswa.SUFFIX_MINERAL)
        for mineral in sorted(minerals):
            self.assertInDomain(self.basemap, 'Lith1Mineral1', mineral, 'suffix')

    def test_every_texture_is_a_real_texture_code(self):
        textures = {row[4] for row in gswa.GSWA_POLY.values() if row[4]}
        for texture in sorted(textures):
            self.assertInDomain(self.basemap, 'Lith1Texture1', texture, 'texture')

    def test_every_line_type_is_a_real_linework_code(self):
        types = {row[0] for row in gswa.GSWA_LINE.values()}
        types.update(gswa.DYKE_BY_LITHNAME.values())
        types.update(gswa.DYKE_BY_ROCKTYPE.values())
        types.update({'Fold Axial Trace - Inferred', 'Shear', 'Section Line'})
        for code in sorted(types):
            self.assertInDomain(self.linework, 'Type', code, 'linework')

    def test_confidence_weight_and_contact_are_real_values(self):
        for _, confidence, weight in gswa.GSWA_LINE.values():
            self.assertInDomain(self.linework, 'Confidence', confidence, 'line')
            self.assertInDomain(self.linework, 'Weight', weight, 'line')
        self.assertInDomain(self.basemap, 'ContactType', 'Solid', 'polygon')
        for value in ('Observed', 'Inferred'):
            self.assertInDomain(self.basemap, 'Confidence', value, 'polygon')

    # ── the cover gate ──────────────────────────────────────────────

    def test_cainozoic_units_land_on_the_cover_side(self):
        domain = self.basemap.domain('Lithology1')
        for code, (lith1, _, _, _, _) in gswa.GSWA_POLY.items():
            if not code.startswith('_'):
                continue
            self.assertIn(
                domain.parent_of(lith1), COVER_SIDE,
                '{0} -> {1} would style as bedrock'.format(code, lith1))

    def test_bedrock_units_land_on_the_bedrock_side(self):
        domain = self.basemap.domain('Lithology1')
        for code, (lith1, _, _, _, _) in gswa.GSWA_POLY.items():
            if code.startswith('_'):
                continue
            self.assertEqual(
                'Lithology', domain.parent_of(lith1),
                '{0} -> {1} would style as cover'.format(code, lith1))

    def test_transported_and_in_situ_regolith_are_told_apart(self):
        domain = self.basemap.domain('Lithology1')
        # GSWA's residual/relict units are weathered in place; everything else
        # with a '_' has been moved by water, gravity or wind.
        for code in ('_R-f', '_R-f-n', '_R-k'):
            self.assertEqual('Regolith',
                             domain.parent_of(gswa.GSWA_POLY[code][0]), code)
        for code in ('_A1', '_C1', '_W', '_S', '_Ad', '_C1-f'):
            self.assertEqual('Transported Cover',
                             domain.parent_of(gswa.GSWA_POLY[code][0]), code)

    # ── nothing on the sheet is missed ──────────────────────────────

    def test_the_whole_mulgul_unit_vocabulary_is_covered(self):
        self.assertEqual(MULGUL_POLY_CODES, set(gswa.GSWA_POLY))

    def test_the_whole_mulgul_line_vocabulary_is_covered(self):
        self.assertEqual(MULGUL_LINE_KEYS, set(gswa.GSWA_LINE))

    def test_every_unit_carries_a_prefix(self):
        # The prefix is the only thing separating three generations of
        # alluvium that all become TALL, so a blank one loses information.
        for code, row in gswa.GSWA_POLY.items():
            self.assertTrue(row[2], '{0} has no LithologyPrefix'.format(code))
            self.assertLessEqual(len(row[2]), 4, code)

    def test_paired_lithologies_are_marked_interbedded(self):
        for code, (_, lith2, _, _, texture) in gswa.GSWA_POLY.items():
            if lith2 and lith2 not in ('MG',):  # nr dolerite/gabbro is a suite
                self.assertEqual('Interbedded', texture, code)

    # ── the fallbacks behave ────────────────────────────────────────

    def test_an_unknown_regolith_unit_still_lands_on_the_cover_side(self):
        row = {'REGOLITH': 'Alluvial units, fourth generation'}
        lith1, _, prefix, mineral, _, how = gswa.polygon_codes('_A4-f', row)
        self.assertEqual('TALL', lith1)
        self.assertEqual('regolith', how)
        self.assertEqual('Gth', mineral)
        self.assertEqual('A4', prefix)

    def test_an_unknown_bedrock_unit_falls_back_to_its_lithname(self):
        row = {'LITHNAME1': 'sandstone + siltstone'}
        lith1, lith2, _, _, _, how = gswa.polygon_codes('P_-MXx-ss', row)
        self.assertEqual(('SST', 'SSL'), (lith1, lith2))
        self.assertEqual('lithname', how)

    def test_an_unrecognisable_unit_is_reported_not_guessed(self):
        lith1, _, _, _, _, how = gswa.polygon_codes('P_-ZZ-qq', {})
        self.assertIsNone(lith1)
        self.assertEqual('unmapped', how)

    def test_a_concealed_structure_is_inferred(self):
        code, confidence, _, how = gswa.line_codes('Fault', 'concealed')
        self.assertEqual(('Fault - Concealed', 'Inferred', 'table'),
                         (code, confidence, how))
        code, confidence, _, how = gswa.line_codes('Thrust fault', 'concealed')
        self.assertEqual(('Fault - Concealed', 'Inferred', 'keyword'),
                         (code, confidence, how))

    def test_comments_never_exceed_the_column(self):
        row = {'UNITNAME': 'A' * 300, 'DESCRIPTN': 'B' * 400,
               'GROUP_': 'C' * 200}
        self.assertLessEqual(len(gswa.comment_for('X', row)),
                             gswa.COMMENT_LIMIT)

    def test_the_same_feature_gets_the_same_uuid_every_run(self):
        # Without this a second import duplicates the sheet rather than being
        # recognised as already present.
        first = gswa.stable_uuid('2548', 'basemap', 17)
        self.assertEqual(first, gswa.stable_uuid('2548', 'basemap', 17))
        self.assertNotEqual(first, gswa.stable_uuid('2548', 'linear', 17))
        self.assertNotEqual(first, gswa.stable_uuid('2549', 'basemap', 17))

    # ── the output shape the wizard relies on ───────────────────────

    def test_output_columns_all_exist_on_the_destination(self):
        # Identical names are what make match_fields tier 1 claim every
        # column; a typo here becomes a manual fix in the wizard.
        for field in gswa.BASEMAP_FIELDS:
            self.assertIn(field, self.basemap.fields, field)
        for field in gswa.LINEWORK_FIELDS:
            self.assertIn(field, self.linework.fields, field)

    def test_the_parent_fields_are_left_to_the_cascade(self):
        for field in ('TypeLith1', 'TypeLith2', 'Description'):
            self.assertNotIn(field, gswa.BASEMAP_FIELDS, field)
        self.assertNotIn('Category', gswa.LINEWORK_FIELDS)

    def test_layer_names_are_the_canonical_ones(self):
        self.assertIn(gswa.BASEMAP_LAYER, import_loader.template_model().layers)
        self.assertIn(gswa.LINEWORK_LAYER, import_loader.template_model().layers)


if __name__ == '__main__':
    unittest.main()
