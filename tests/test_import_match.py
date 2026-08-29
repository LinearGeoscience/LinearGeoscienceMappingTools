"""
Layer and column matching (pure python, no QGIS).

The fixtures are built by taking the shipped template apart: renaming its
layers the way a real client export renames them, and removing the columns the
Aug-2026 work added. That produces a source with the exact shape of
ME_AbraMapping_April26.gpkg without needing the file, and it stays honest as the
template changes because it is derived from the template.
"""

import copy
import os
import sys
import unittest
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import import_loader  # noqa: E402

domain = import_loader.load('domain.py')
match_layers = import_loader.load('match_layers.py')
match_fields = import_loader.load('match_fields.py')


# Column names the Aug-2026 template gained. A project mapped before that has
# none of them, which is exactly what makes layer matching interesting: the
# column sets overlap heavily but not completely.
_ADDED_SINCE = {
    'Confidence', 'Elevation', 'MineralPct', 'Mineral2Pct', 'Mineral3Pct',
    'Category', 'Weight', 'Width_cm', 'Mineral1', 'Mineral2', 'Mineral3',
    'VeinTexture', 'Percent', 'Mineral1Pct', 'Intensity',
    'Lith1Mineral1', 'Lith1Mineral2', 'Lith1Mineral3', 'Lith1Texture1',
    'Lith1Texture2', 'Lith2Mineral1', 'Lith2Mineral2', 'Lith2Mineral3',
    'Lith2Texture1', 'Lith2Texture2', 'Lith1Mineral1Pct', 'Lith1Mineral2Pct',
    'Lith1Mineral3Pct', 'Lith2Mineral1Pct', 'Lith2Mineral2Pct',
    'Lith2Mineral3Pct',
    'VeinGen', 'Selvedge_cm', 'SelvedgeMineral',
    'LithologySuffix',
}

# What a client export calls each layer, and what the pre-Aug-2026 template did.
_EXPORT_NAMES = {
    '1 - FieldNotebook': '1_Structures',
    '2 - Linework': '3_Linework',
    '3 - Overlay': '2_Alteration',
    '4 - Basemap': '4_Lithology',
}
_PRE_SWAP_NAMES = {
    '1 - FieldNotebook': '1 - FieldNotebook',
    '2 - Linework': '3 - Linework',
    '3 - Overlay': '2 - Overlay',
    '4 - Basemap': '4 - Basemap',
}

# Retired columns the old data still carries.
_LEGACY_EXTRAS = {
    '1_Structures': ['SubType1Code', 'StructureLegend', 'data_added_timestamp',
                     'data_added_batch_id',
                     'auxiliary_storage_labeling_positionx'],
    '4_Lithology': ['Float', 'Lith1Feature', 'Lith2Feature', 'Type',
                    'data_added_timestamp', 'data_added_batch_id'],
}


def legacy_source(names=None):
    """A source model shaped like an old export of the shipped template."""
    names = names or _EXPORT_NAMES
    template = import_loader.template_model()
    layers = OrderedDict()
    for canonical, spec in template.layers.items():
        export_name = names[canonical]
        fields = OrderedDict(
            (name, field) for name, field in spec.fields.items()
            if name not in _ADDED_SINCE)
        for extra in _LEGACY_EXTRAS.get(export_name, []):
            fields[extra] = domain.FieldSpec(extra, 'TEXT(100)')
        layers[export_name] = domain.LayerSpec(
            name=export_name, geometry_type=spec.geometry_type,
            has_z=spec.has_z, fields=fields, code_domains=OrderedDict(),
            feature_count=100)
    return domain.MappingModel(path='', layers=layers, tables=OrderedDict(),
                               label='legacy export')


class TestLayerMatching(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.template = import_loader.template_model()

    def test_client_export_names_all_resolve(self):
        matches = match_layers.match_layers(legacy_source(), self.template)
        resolved = {name: match.target_name for name, match in matches.items()}
        self.assertEqual(resolved, {
            '1_Structures': '1 - FieldNotebook',
            '2_Alteration': '3 - Overlay',
            '3_Linework': '2 - Linework',
            '4_Lithology': '4 - Basemap',
        })

    def test_linework_does_not_follow_its_ordinal_into_overlay(self):
        """`3_Linework` against a post-swap template: the 3 means nothing.

        Matching on the number would put line features in a polygon layer.
        """
        matches = match_layers.match_layers(legacy_source(), self.template)
        self.assertEqual(matches['3_Linework'].target_name, '2 - Linework')

    def test_every_match_is_confident_enough_to_apply(self):
        matches = match_layers.match_layers(legacy_source(), self.template)
        for name, match in matches.items():
            self.assertEqual(match.confidence, match_layers.AUTO, name)

    def test_pre_swap_project_resolves_through_the_renumbering(self):
        source = legacy_source(_PRE_SWAP_NAMES)
        matches = match_layers.match_layers(source, self.template)
        self.assertEqual(matches['3 - Linework'].target_name, '2 - Linework')
        self.assertEqual(matches['2 - Overlay'].target_name, '3 - Overlay')

    def test_geometry_gate_blocks_an_impossible_pairing(self):
        source = legacy_source()
        # A source layer whose geometry nothing in the template can hold.
        source.layers['5_Grid'] = domain.LayerSpec(
            name='5_Grid', geometry_type='MULTIPOINT',
            fields=OrderedDict([('UUID', domain.FieldSpec('UUID', 'TEXT'))]))
        matches = match_layers.match_layers(source, self.template)
        # MULTIPOINT is still the point family, so it lands on FieldNotebook —
        # the gate is about family, not exact WKB type.
        self.assertEqual(matches['5_Grid'].target_name, '1 - FieldNotebook')

    def test_geometry_families(self):
        self.assertTrue(match_layers.geometry_compatible(
            domain.LayerSpec('a', 'MULTIPOLYGON'),
            domain.LayerSpec('b', 'POLYGON')))
        self.assertFalse(match_layers.geometry_compatible(
            domain.LayerSpec('a', 'LINESTRING'),
            domain.LayerSpec('b', 'POLYGON')))

    def test_seeded_pairing_from_a_saved_profile_wins(self):
        matches = match_layers.match_layers(
            legacy_source(), self.template,
            seeded={'4_Lithology': '3 - Overlay'})
        self.assertEqual(matches['4_Lithology'].target_name, '3 - Overlay')
        self.assertEqual(matches['4_Lithology'].reason, 'from saved profile')


class TestFieldMatching(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.template = import_loader.template_model()
        cls.source = legacy_source()

    def _plan(self, source_layer, target_layer):
        return match_fields.match_fields(self.source.layers[source_layer],
                                         self.template.layers[target_layer])

    def test_identical_names_pair_themselves(self):
        plan = self._plan('4_Lithology', '4 - Basemap')
        mapping = plan.mapping()
        self.assertEqual(mapping.get('Lithology1'), 'Lithology1')
        self.assertEqual(mapping.get('TypeLith1'), 'TypeLith1')
        self.assertEqual(mapping.get('UUID'), 'UUID')

    def test_bookkeeping_columns_never_travel(self):
        plan = self._plan('1_Structures', '1 - FieldNotebook')
        self.assertEqual(
            plan.matches['fid'].status, match_fields.IGNORED)
        self.assertEqual(
            plan.matches['auxiliary_storage_labeling_positionx'].status,
            match_fields.IGNORED)

    def test_a_target_is_claimed_only_once(self):
        """SubType1Code aliases to MappedSubType1 — unless that is taken.

        The old data carries both columns, so the alias must lose to the exact
        match rather than overwrite it.
        """
        plan = self._plan('1_Structures', '1 - FieldNotebook')
        self.assertEqual(plan.mapping().get('MappedSubType1'),
                         'MappedSubType1')
        self.assertIsNone(plan.matches['SubType1Code'].target_name)

    def test_known_rename_applies_when_the_target_is_free(self):
        source_spec = copy.deepcopy(self.source.layers['1_Structures'])
        del source_spec.fields['MappedSubType1']
        plan = match_fields.match_fields(
            source_spec, self.template.layers['1 - FieldNotebook'])
        self.assertEqual(plan.mapping().get('SubType1Code'), 'MappedSubType1')
        self.assertEqual(plan.matches['SubType1Code'].status,
                         match_fields.ALIAS)

    def test_retired_freetext_columns_default_to_comments(self):
        plan = self._plan('4_Lithology', '4 - Basemap')
        self.assertEqual(sorted(plan.to_comments()),
                         ['Float', 'Lith1Feature', 'Lith2Feature'])

    def test_legacy_type_column_is_dropped_not_forced_into_typelith1(self):
        plan = self._plan('4_Lithology', '4 - Basemap')
        self.assertIn('Type', plan.dropped())

    def test_destination_only_columns_are_explained(self):
        plan = self._plan('2_Alteration', '3 - Overlay')
        notes = plan.target_notes
        self.assertEqual(notes['Confidence'].how, 'default')
        self.assertIn('Observed', notes['Confidence'].detail)
        self.assertEqual(notes['Elevation'].how, 'derived')

    def test_cascade_parent_is_reported_as_derived(self):
        plan = self._plan('3_Linework', '2 - Linework')
        self.assertEqual(plan.target_notes['Category'].how, 'derived')
        self.assertIn('Type', plan.target_notes['Category'].detail)

    def test_type_compatibility(self):
        text = domain.FieldSpec('a', 'TEXT(50)')
        number = domain.FieldSpec('b', 'MEDIUMINT')
        self.assertEqual(match_fields.types_compatible(number, text),
                         (True, ''))
        ok, note = match_fields.types_compatible(text, number)
        self.assertTrue(ok)
        self.assertIn('converted', note)

    def test_compare_key_folds_the_awkward_template_names(self):
        self.assertEqual(match_fields.compare_key('Date&Time'), 'datetime')
        self.assertEqual(match_fields.compare_key('date_time'), 'datetime')
        self.assertEqual(match_fields.compare_key('Vein %'), 'vein')


if __name__ == '__main__':
    unittest.main()
