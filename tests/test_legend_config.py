"""
Unit tests for recode_workflow/legend_config.py (pure python, no QGIS).

Run from the plugin root:
    python -m unittest discover tests
"""

import importlib.util
import os
import unittest

# Load legend_config.py directly — importing the recode_workflow package
# would pull in qgis, which isn't available outside QGIS.
_path = os.path.join(os.path.dirname(__file__), '..',
                     'recode_workflow', 'legend_config.py')
_spec = importlib.util.spec_from_file_location('legend_config', _path)
legend_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(legend_config)

CONFIG_VERSION = legend_config.CONFIG_VERSION
EM_DASH = legend_config.EM_DASH
is_valid_value = legend_config.is_valid_value
normalize_section = legend_config.normalize_section
normalize_config = legend_config.normalize_config
migrate_legacy_config = legend_config.migrate_legacy_config
serialize_config = legend_config.serialize_config
deserialize_config = legend_config.deserialize_config
format_entries = legend_config.format_entries
format_text_sections = legend_config.format_text_sections
strip_table_suffix = legend_config.strip_table_suffix
strip_family_suffix = legend_config.strip_family_suffix
group_fields_into_families = legend_config.group_fields_into_families
DEFAULT_EXCLUDED_FIELDS = legend_config.DEFAULT_EXCLUDED_FIELDS


class TestIsValidValue(unittest.TestCase):

    def test_none_is_invalid(self):
        self.assertFalse(is_valid_value(None))

    def test_null_string_is_invalid(self):
        self.assertFalse(is_valid_value('NULL'))

    def test_empty_and_whitespace_invalid(self):
        self.assertFalse(is_valid_value(''))
        self.assertFalse(is_valid_value('   '))

    def test_zero_is_valid(self):
        # Falsy codes must survive (bug fix: `if feat[key]` dropped 0)
        self.assertTrue(is_valid_value(0))
        self.assertTrue(is_valid_value('0'))

    def test_normal_values_valid(self):
        self.assertTrue(is_valid_value('Qz'))
        self.assertTrue(is_valid_value(42))


class TestNormalizeSection(unittest.TestCase):

    def test_defaults_filled(self):
        s = normalize_section({'title': 'Minerals'})
        self.assertTrue(s['id'])
        self.assertEqual(s['title'], 'Minerals')
        self.assertIsNone(s['layer'])
        self.assertEqual(s['fields'], [])
        self.assertIsNone(s['subdivide_by'])
        self.assertEqual(s['display'], 'auto')
        self.assertIsNone(s['lookup'])

    def test_invalid_display_coerced(self):
        s = normalize_section({'display': 'bogus'})
        self.assertEqual(s['display'], 'auto')

    def test_id_preserved(self):
        s = normalize_section({'id': 'abc'})
        self.assertEqual(s['id'], 'abc')

    def test_string_layer_ref_becomes_dual_ref(self):
        s = normalize_section({'layer': 'Lithology'})
        self.assertEqual(s['layer'], {'id': 'Lithology', 'name': 'Lithology'})

    def test_blank_fields_dropped(self):
        s = normalize_section({'fields': ['A', ' ', '', 'B']})
        self.assertEqual(s['fields'], ['A', 'B'])

    def test_lookup_normalised(self):
        s = normalize_section({'lookup': {
            'table': {'id': 't1', 'name': 'MineralCodes'},
            'key_column': 'Code', 'value_column': 'Description'}})
        self.assertEqual(s['lookup']['table']['name'], 'MineralCodes')
        self.assertEqual(s['lookup']['key_column'], 'Code')

    def test_lookup_without_table_dropped(self):
        s = normalize_section({'lookup': {'key_column': 'Code'}})
        self.assertIsNone(s['lookup'])


class TestMigration(unittest.TestCase):

    def test_v1_field_groups_become_auto_sections(self):
        config = migrate_legacy_config(
            field_configs={'layer_abc': [
                ('Geology', ['RockType1', 'RockType2'], 'Type'),
                {'name': 'Veins', 'fields': ['Vein1'], 'subdivide_by': None},
            ]})
        self.assertEqual(config['version'], CONFIG_VERSION)
        self.assertEqual(len(config['sections']), 2)
        geo, veins = config['sections']
        self.assertEqual(geo['title'], 'Geology')
        self.assertEqual(geo['layer'], {'id': 'layer_abc', 'name': 'layer_abc'})
        self.assertEqual(geo['subdivide_by'], 'Type')
        self.assertEqual(geo['display'], 'auto')
        self.assertEqual(veins['fields'], ['Vein1'])

    def test_v1_vr_sections_become_text_sections(self):
        config = migrate_legacy_config(vr_sections=[{
            'name': 'Grain Size', 'lookup_table': 'GrainSizeCodes',
            'key_column': 'Code', 'value_column': 'Description',
            'scan_fields': ['Grain', 'Grain2']}])
        (section,) = config['sections']
        self.assertEqual(section['display'], 'text')
        self.assertIsNone(section['layer'])
        self.assertEqual(section['fields'], ['Grain', 'Grain2'])
        self.assertEqual(section['lookup']['table']['name'], 'GrainSizeCodes')

    def test_v1_text_mappings_keep_name(self):
        config = migrate_legacy_config(text_mappings={
            'Lithology': {'display_name': 'Geology',
                          'features': {'gr': 'Granite'}}})
        entry = config['text_mappings']['Lithology']
        self.assertEqual(entry['name'], 'Lithology')
        self.assertEqual(entry['display_name'], 'Geology')


class TestSerializeRoundTrip(unittest.TestCase):

    def test_round_trip(self):
        original = normalize_config({
            'sections': [{'title': 'Minerals', 'layer': {'id': 'x', 'name': 'Alt'},
                          'fields': ['Mineral1'], 'display': 'text'}],
            'text_mappings': {'x': {'name': 'Alt', 'display_name': 'Alteration'}},
            'legend_unchecked_layers': [{'id': 'y', 'name': 'Topo'}],
            'code_table_text_manual': 'extra',
            'options': {'per_sheet_scan': False, 'filter_legend_by_map': True},
        })
        round_tripped = deserialize_config(serialize_config(original))
        self.assertEqual(original, round_tripped)

    def test_deserialize_none_and_empty(self):
        self.assertEqual(deserialize_config(None)['sections'], [])

    def test_deserialize_v1_file_payload(self):
        v1 = {
            'legend_field_configs': {
                'Lithology': [{'name': 'Geology', 'fields': ['Rock1'],
                               'subdivide_by': None}]},
            'value_relation_sections': [{
                'name': 'Textures', 'lookup_table': 'TextureCodes',
                'key_column': 'Code', 'value_column': 'Description',
                'scan_fields': []}],
        }
        config = deserialize_config(v1)
        self.assertEqual(config['version'], CONFIG_VERSION)
        self.assertEqual(len(config['sections']), 2)
        self.assertEqual(config['sections'][1]['display'], 'text')

    def test_unknown_keys_tolerated(self):
        config = deserialize_config(
            '{"version": 2, "sections": [], "future_key": 1}')
        self.assertEqual(config['sections'], [])


class TestFormatting(unittest.TestCase):

    def test_entries_with_lookup(self):
        text = format_entries(['Ser', 'Qz'], {'Qz': 'Quartz', 'Ser': 'Sericite'})
        self.assertEqual(text, f"Qz {EM_DASH} Quartz, Ser {EM_DASH} Sericite")

    def test_entries_bare_codes_and_zero(self):
        self.assertEqual(format_entries(['0', 'B']), "0, B")

    def test_entry_desc_equal_to_code_collapses(self):
        self.assertEqual(format_entries(['Qz'], {'Qz': 'Qz'}), "Qz")

    def _sections(self):
        return [
            normalize_section({'id': 's1', 'title': 'Minerals / Alteration',
                               'display': 'text'}),
            normalize_section({'id': 's2', 'title': 'Geology',
                               'display': 'auto'}),
            normalize_section({'id': 's3', 'title': 'Symbols Only',
                               'display': 'symbols'}),
        ]

    def test_text_section_with_lookup(self):
        out = format_text_sections(
            self._sections(),
            {'s1': ['Qz', 'Ser']},
            {'s1': {'Qz': 'Quartz', 'Ser': 'Sericite'}})
        self.assertEqual(
            out,
            "MINERALS / ALTERATION\n"
            f"Qz {EM_DASH} Quartz, Ser {EM_DASH} Sericite")

    def test_auto_overflow_appended_under_heading(self):
        out = format_text_sections(
            self._sections(), {'s2': ['gr', 'bas', 'qzv']},
            extra_unmatched={'s2': ['qzv']})
        self.assertEqual(out, "GEOLOGY\nqzv")

    def test_symbols_sections_never_emit_text(self):
        out = format_text_sections(self._sections(), {'s3': ['a', 'b']})
        self.assertEqual(out, "")

    def test_empty_sections_omitted(self):
        out = format_text_sections(self._sections(), {'s1': []})
        self.assertEqual(out, "")

    def test_subdivided_section(self):
        out = format_text_sections(
            self._sections(),
            {'s1': {'Granite': ['Kf', 'Qz'], 'Basalt': ['Ol']}},
            {'s1': {'Qz': 'Quartz'}})
        self.assertEqual(
            out,
            "MINERALS / ALTERATION\n"
            "Basalt: Ol\n"
            f"Granite: Kf, Qz {EM_DASH} Quartz")

    def test_multiple_sections_blank_line_separated(self):
        out = format_text_sections(
            self._sections(),
            {'s1': ['Qz']},
            extra_unmatched={'s2': ['x']})
        self.assertEqual(out, "MINERALS / ALTERATION\nQz\n\nGEOLOGY\nx")


class TestFamilyGrouping(unittest.TestCase):

    def test_strip_table_suffix(self):
        self.assertEqual(strip_table_suffix('MineralCodes'), 'Mineral')
        self.assertEqual(strip_table_suffix('OverlayCategories'), 'Overlay')
        self.assertEqual(strip_table_suffix('LookupTable'), 'Lookup')
        self.assertEqual(strip_table_suffix('Mineral'), 'Mineral')
        # A bare suffix name is left alone, not stripped to ''
        self.assertEqual(strip_table_suffix('Codes'), 'Codes')

    def test_strip_family_suffix(self):
        self.assertEqual(strip_family_suffix('Mineral3'), 'Mineral')
        self.assertEqual(strip_family_suffix('SubType1'), 'SubType')
        self.assertEqual(strip_family_suffix('Dip'), 'Dip')
        # All-digit names survive
        self.assertEqual(strip_family_suffix('123'), '123')

    def test_group_fields_into_families(self):
        families = group_fields_into_families(
            ['Mineral', 'Mineral2', 'Mineral3', 'Intensity', 'SubType1'])
        self.assertEqual(families, {
            'Mineral': ['Mineral', 'Mineral2', 'Mineral3'],
            'Intensity': ['Intensity'],
            'SubType': ['SubType1'],
        })

    def test_group_dedupes_members(self):
        families = group_fields_into_families(['Texture1', 'Texture1'])
        self.assertEqual(families, {'Texture': ['Texture1']})

    def test_excluded_fields_lowercase(self):
        self.assertIn('fid', DEFAULT_EXCLUDED_FIELDS)
        self.assertIn('projectid', DEFAULT_EXCLUDED_FIELDS)
        self.assertIn('notes', DEFAULT_EXCLUDED_FIELDS)
        # Skip-list is matched case-insensitively via lowercase keys
        self.assertTrue(all(f == f.lower()
                            for f in DEFAULT_EXCLUDED_FIELDS))


if __name__ == '__main__':
    unittest.main()
