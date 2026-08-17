"""
The code-translation ladder (pure python, no QGIS).

Run against the shipped template's real code domains, with the values that
actually appear in old mapping data. Two kinds of assertion matter here and
they pull in opposite directions:

  * the automatic tiers must catch the cases they were built for, so a
    migration is not 140 manual decisions; and
  * fuzzy matching must NEVER decide anything, because the closest string to
    'Fault - Minor' in the current list is 'Fault - Normal' and writing that
    would put the wrong structure on the map with nothing to show for it.
"""

import os
import sys
import unittest
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import import_loader  # noqa: E402

domain = import_loader.load('domain.py')
match_values = import_loader.load('match_values.py')
derive = import_loader.load('derive.py')
scan = import_loader.load('scan.py')


class LadderTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.template = import_loader.template_model()
        cls.basemap = cls.template.layers['4 - Basemap']
        cls.linework = cls.template.layers['2 - Linework']
        cls.overlay = cls.template.layers['3 - Overlay']
        cls.notebook = cls.template.layers['1 - FieldNotebook']

    def resolve(self, layer, field, value, describe=None):
        return match_values.resolve_value(
            value, layer.domain(field), layer_spec=layer,
            source_describe=describe)


class TestExactAndSpelling(LadderTestCase):

    def test_a_current_code_matches(self):
        status, code, extras, _note = self.resolve(
            self.basemap, 'Lithology1', 'FGR')
        self.assertEqual((status, code, extras),
                         (match_values.EXACT, 'FGR', {}))

    def test_case_only_difference_is_still_exact(self):
        status, code, _extras, _note = self.resolve(
            self.basemap, 'Lithology1', 'fgr')
        self.assertEqual((status, code), (match_values.EXACT, 'FGR'))

    def test_trailing_space_from_an_old_code_list_is_trimmed(self):
        status, code, _extras, _note = self.resolve(
            self.linework, 'Type', 'Fault - Normal ')
        self.assertEqual((status, code), (match_values.EXACT, 'Fault - Normal'))

    def test_spacing_and_punctuation_are_ignored_when_unambiguous(self):
        for value in ('Rockchip', 'ROCKCHIP'):
            status, code, _extras, _note = self.resolve(
                self.notebook, 'SampleType', value)
            self.assertEqual((status, code),
                             (match_values.SPELLING, 'Rock Chip'), value)

    def test_punctuation_difference_resolves(self):
        status, code, _extras, _note = self.resolve(
            self.notebook, 'SampleType', 'Chip Channel')
        self.assertEqual((status, code),
                         (match_values.SPELLING, 'Chip-Channel'))


class TestDescriptionTier(LadderTestCase):
    """Old data that used the mineral's name where a code was expected."""

    def test_full_names_resolve_to_their_codes(self):
        expected = {'Hematite': 'Hem', 'Illite': 'Ilt', 'Manganese': 'Mn',
                    'Silica': 'Sil'}
        for value, code in expected.items():
            status, resolved, _extras, _note = self.resolve(
                self.overlay, 'SubType1', value)
            self.assertEqual((status, resolved),
                             (match_values.DESCRIPTION, code), value)


class TestSplitTier(LadderTestCase):
    """The retired '- Major'/'- Minor' suffix now lives on Weight.

    The rule reads the sibling ValueMap off the destination rather than naming
    Weight, so it keeps working if the template grows another such field.
    """

    def test_linework_minor_splits_into_weight(self):
        status, code, extras, _note = self.resolve(
            self.linework, 'Type', 'Fault - Minor')
        self.assertEqual(status, match_values.SPLIT)
        self.assertEqual(code, 'Fault')
        self.assertEqual(extras, {'Weight': 'Minor'})

    def test_a_compound_code_keeps_its_stem(self):
        status, code, extras, _note = self.resolve(
            self.linework, 'Type', 'Shear - Sinistral - Minor')
        self.assertEqual((status, code, extras),
                         (match_values.SPLIT, 'Shear - Sinistral',
                          {'Weight': 'Minor'}))

    def test_overlay_major_splits_too(self):
        status, code, extras, _note = self.resolve(
            self.overlay, 'SubType1', 'Breccia Zone - Major')
        self.assertEqual((status, code, extras),
                         (match_values.SPLIT, 'Breccia Zone',
                          {'Weight': 'Major'}))

    def test_a_code_that_merely_ends_in_a_word_is_not_split(self):
        status, code, _extras, _note = self.resolve(
            self.linework, 'Type', 'Fault - Normal')
        self.assertEqual((status, code), (match_values.EXACT, 'Fault - Normal'))


class TestRenameAndMeaningChange(LadderTestCase):
    """Bridging through the SOURCE's own code table.

    An old LGS project carries its own *Codes tables. When its description of a
    code equals the destination's description of a differently-spelled one,
    that is a rename and can be applied. When the spelling survived but the
    description changed, the value is accepted and flagged.
    """

    def describe_old(self, code):
        # The pre-audit descriptions, as the old template shipped them.
        return {
            'FAP': 'FAP - Aplite',
            'SAS': 'SAS - Andalusite Schist',
            'HSPG': 'HSPG - Semi-Pelitic Gneiss',
            'IAC': 'IAC - Intermediate Volcaniclastic',
        }.get(code, '')

    def test_renamed_codes_resolve_through_their_description(self):
        for value, expected in (('FAP', 'FAPL'), ('SAS', 'ZSAS'),
                                ('HSPG', 'HPPG')):
            status, code, _extras, _note = self.resolve(
                self.basemap, 'Lithology1', value, describe=self.describe_old)
            self.assertEqual((status, code), (match_values.RENAMED, expected),
                             value)

    def test_a_repurposed_code_is_flagged_not_swallowed(self):
        status, code, _extras, note = self.resolve(
            self.basemap, 'Lithology1', 'IAC', describe=self.describe_old)
        self.assertEqual((status, code), (match_values.MEANING_CHANGED, 'IAC'))
        self.assertIn('Intermediate Volcaniclastic', note)
        self.assertIn('Andesitic Volcaniclastic', note)

    def test_without_the_bridge_a_rename_is_only_a_suggestion(self):
        """A source with no code tables cannot prove a rename.

        HSPG then goes to the user, and the closest string ('HPG', Paragneiss)
        is NOT the right answer — which is the whole argument for the bridge.
        """
        status, code, _extras, _note = self.resolve(
            self.basemap, 'Lithology1', 'HSPG')
        self.assertEqual(status, match_values.UNRESOLVED)
        self.assertIsNone(code)
        suggestions = [suggestion[0] for suggestion
                       in match_values.suggest('HSPG',
                                               self.basemap.domain('Lithology1'))]
        self.assertIn('HPG', suggestions)


class TestFuzzyNeverDecides(LadderTestCase):

    def test_formline_fine_is_left_for_the_user(self):
        status, code, _extras, _note = self.resolve(
            self.linework, 'Type', 'Formline - Fine')
        self.assertEqual(status, match_values.UNRESOLVED)
        self.assertIsNone(code)

    def test_resolve_field_offers_but_does_not_apply_a_suggestion(self):
        counts = scan.ValueCounts('Type',
                                  OrderedDict([('Formline - Fine', 15)]),
                                  total=15)
        resolved = match_values.resolve_field(
            'Type', counts, self.linework.domain('Type'),
            layer_spec=self.linework)
        entry = resolved['Formline - Fine']
        self.assertEqual(entry.status, match_values.SUGGESTED)
        self.assertIsNone(entry.code)
        self.assertFalse(entry.decided)
        self.assertTrue(entry.suggestions)

    def test_a_minor_fault_never_silently_becomes_a_normal_one(self):
        """The regression this whole design exists to prevent."""
        for value in ('Fault - Minor', 'Shear - Minor'):
            status, code, extras, _note = self.resolve(self.linework, 'Type',
                                                       value)
            self.assertEqual(status, match_values.SPLIT, value)
            self.assertNotIn('Normal', code or '', value)
            self.assertEqual(extras.get('Weight'), 'Minor', value)


class TestDecisionsAndParents(LadderTestCase):

    def test_user_decisions_mark_a_value_decided(self):
        resolution = match_values.ValueResolution('Type', 'Whatever', 3)
        self.assertFalse(resolution.decided)
        resolution.choose('Fault')
        self.assertTrue(resolution.decided)
        self.assertEqual(resolution.code, 'Fault')

        resolution = match_values.ValueResolution('Type', 'Whatever', 3)
        resolution.add_as_new_code(parent='Structural', description='A thing')
        self.assertEqual(resolution.status, match_values.ADD_CODE)
        self.assertEqual(resolution.code, 'Whatever')
        self.assertTrue(resolution.decided)

        resolution = match_values.ValueResolution('Type', 'Whatever', 3)
        resolution.leave_blank(to_comments=True)
        self.assertTrue(resolution.decided)
        self.assertIsNone(resolution.code)
        self.assertTrue(resolution.to_comments)

    def test_parent_is_recoverable_from_the_code(self):
        self.assertEqual(
            match_values.derive_parent(self.linework.domain('Type'), 'Fault'),
            'Structural')
        self.assertEqual(
            match_values.derive_parent(self.basemap.domain('Lithology1'),
                                       'FGR'),
            'Lithology')

    def test_fill_parents_sets_category_from_type(self):
        attributes = {'Type': 'Fault'}
        fills = derive.fill_parents(self.linework, attributes)
        self.assertEqual(attributes['Category'], 'Structural')
        self.assertEqual(len(fills), 1)
        self.assertFalse(fills[0].is_conflict)

    def test_fill_parents_overrides_a_disagreeing_source_value_and_says_so(self):
        attributes = {'Type': 'Fault', 'Category': 'Veins'}
        fills = derive.fill_parents(self.linework, attributes)
        self.assertEqual(attributes['Category'], 'Structural')
        self.assertTrue(fills[0].is_conflict)

    def test_a_new_code_becomes_backfillable_once_registered(self):
        domain_ = self.linework.domain('Type')
        self.assertEqual(domain_.parent_of('Formline - Fine'), '')
        try:
            domain_.add_entry('Formline - Fine', 'Formline - Fine', 'Formlines')
            self.assertEqual(domain_.parent_of('Formline - Fine'), 'Formlines')
            attributes = {'Type': 'Formline - Fine'}
            derive.fill_parents(self.linework, attributes)
            self.assertEqual(attributes['Category'], 'Formlines')
        finally:
            # Leave the shared template model as it was found.
            domain_.entries = tuple(
                entry for entry in domain_.entries
                if entry[0] != 'Formline - Fine')
            domain_._index()


class TestCoercion(unittest.TestCase):

    def test_text_into_a_number(self):
        field = domain.FieldSpec('Percent', 'MEDIUMINT')
        self.assertEqual(derive.coerce('40', field), (40, ''))
        self.assertEqual(derive.coerce('40%', field), (40, ''))
        self.assertEqual(derive.coerce('40.6', field), (41, ''))
        value, error = derive.coerce('about forty', field)
        self.assertIsNone(value)
        self.assertIn('not a whole number', error)

    def test_blank_leaves_the_default_its_chance(self):
        field = domain.FieldSpec('Confidence', 'TEXT(20)')
        self.assertEqual(derive.coerce('NULL', field), (None, ''))
        self.assertEqual(derive.coerce('', field), (None, ''))

    def test_comment_suffix_skips_empties(self):
        text = derive.comment_suffix(
            {'Float': 'NULL', 'Lith1Feature': 'Chl-k altered'},
            ['Float', 'Lith1Feature'])
        self.assertEqual(text, 'Lith1Feature: Chl-k altered')

    def test_merge_comments_does_not_duplicate(self):
        merged = derive.merge_comments('Seen from the road', 'Float: yes')
        self.assertEqual(merged, 'Seen from the road | Float: yes')
        self.assertEqual(derive.merge_comments(merged, 'Float: yes'), merged)


if __name__ == '__main__':
    unittest.main()
