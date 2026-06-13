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
format_entry_list = legend_config.format_entry_list
group_values_by_lookup = legend_config.group_values_by_lookup
text_from_section_lines = legend_config.text_from_section_lines
derive_text_overrides = legend_config.derive_text_overrides
apply_text_overrides = legend_config.apply_text_overrides
format_text_sections = legend_config.format_text_sections
build_text_section_lines = legend_config.build_text_section_lines
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

    def test_inline_map_lookup(self):
        s = normalize_section({'lookup': {'map': {'si': 'Silica', 0: 1}}})
        self.assertEqual(s['lookup'], {'map': {'si': 'Silica', '0': '1'}})

    def test_table_lookup_group_column(self):
        s = normalize_section({'lookup': {
            'table': {'id': 't', 'name': 'BasemapCategories'},
            'key_column': 'Code', 'value_column': 'Description',
            'group_column': 'Type'}})
        self.assertEqual(s['lookup']['group_column'], 'Type')
        # Absent/empty group column normalises to None
        s2 = normalize_section({'lookup': {
            'table': {'id': 't', 'name': 'T'},
            'key_column': 'Code', 'value_column': 'Description'}})
        self.assertIsNone(s2['lookup']['group_column'])

    def test_pairs_lookup(self):
        s = normalize_section({'lookup': {'pairs': {}}})
        self.assertEqual(s['lookup'], {'pairs': {'suffix': 'Description'}})
        s2 = normalize_section({'lookup': {'pairs': {'suffix': '_Desc'}}})
        self.assertEqual(s2['lookup']['pairs']['suffix'], '_Desc')

    def test_field_targets_normalised(self):
        s = normalize_section({'field_targets': [
            {'layer': {'id': 'a', 'name': 'Overlay'},
             'fields': ['SubType1', ' ', 'SubType2']},
            {'layer': None, 'fields': ['X']},      # no layer → dropped
            {'layer': {'id': 'b', 'name': 'B'}, 'fields': []},  # no fields
        ]})
        self.assertEqual(s['field_targets'], [
            {'layer': {'id': 'a', 'name': 'Overlay'},
             'fields': ['SubType1', 'SubType2']},
        ])
        # Display union derived from targets when fields not given
        self.assertEqual(s['fields'], ['SubType1', 'SubType2'])

    def test_field_targets_absent_is_none(self):
        self.assertIsNone(normalize_section({})['field_targets'])

    def test_field_targets_round_trip(self):
        config = normalize_config({'sections': [{
            'title': 'Overlay', 'field_targets': [
                {'layer': {'id': 'a', 'name': 'Overlay'},
                 'fields': ['SubType1']}],
            'subdivide_by': 'Type', 'display': 'text',
            'lookup': {'pairs': {'suffix': 'Description'}}}]})
        round_tripped = deserialize_config(serialize_config(config))
        self.assertEqual(config, round_tripped)

    def test_text_columns_clamped(self):
        self.assertEqual(
            normalize_config({'options': {'text_columns': 9}})
            ['options']['text_columns'], 4)
        self.assertEqual(
            normalize_config({'options': {'text_columns': 0}})
            ['options']['text_columns'], 1)
        self.assertEqual(
            normalize_config({'options': {'text_columns': 'x'}})
            ['options']['text_columns'], 2)
        self.assertEqual(
            normalize_config({})['options']['text_columns'], 2)


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
        # Unmatched codes display lowercase (matching the map labels)
        self.assertEqual(format_entries(['0', 'B']), "0, b")

    def test_entry_desc_equal_to_code_collapses(self):
        self.assertEqual(format_entries(['Qz'], {'Qz': 'Qz'}), "Qz")

    def test_case_variants_merged_lookup_casing_wins(self):
        entries = format_entry_list(
            ['CY', 'cy', 'Cy', 'si', 'SI'], {'Cy': 'Chalcopyrite'})
        self.assertEqual(entries, [f"Cy {EM_DASH} Chalcopyrite", "si"])

    def test_lookup_matched_case_insensitively(self):
        entries = format_entry_list(['SI'], {'si': 'Silica'})
        self.assertEqual(entries, [f"si {EM_DASH} Silica"])

    def test_description_embedding_code_not_doubled(self):
        # Description already starts with the code → show it alone
        entries = format_entry_list(['chl'], {'Chl': 'Chl - Chlorite'})
        self.assertEqual(entries, ["Chl - Chlorite"])

    def test_unmatched_multiword_value_keeps_casing(self):
        # Client deliverables: the value IS the description
        entries = format_entry_list(['Hem - Hematite', 'CY'])
        self.assertEqual(entries, ["cy", "Hem - Hematite"])

    def test_multiword_case_variants_merge_first_seen(self):
        entries = format_entry_list(['Breccia Zone - Major',
                                     'BRECCIA ZONE - MAJOR'])
        self.assertEqual(entries, ["Breccia Zone - Major"])


class TestGroupValuesByLookup(unittest.TestCase):

    GROUPS = {'Ab': 'Alteration', 'Fresh': 'Weathering',
              'Bt': 'Alteration'}

    def test_groups_split_and_sorted(self):
        result = group_values_by_lookup(['Fresh', 'ab', 'bt'], self.GROUPS)
        self.assertEqual(result, {
            'Alteration': ['ab', 'bt'],
            'Weathering': ['Fresh'],
        })

    def test_ungrouped_under_other(self):
        result = group_values_by_lookup(['ab', 'xx'], self.GROUPS)
        self.assertEqual(result, {'Alteration': ['ab'], 'Other': ['xx']})

    def test_no_other_when_all_grouped(self):
        result = group_values_by_lookup(['ab'], self.GROUPS)
        self.assertNotIn('Other', result)

    def test_empty_group_map(self):
        result = group_values_by_lookup(['a'], {})
        self.assertEqual(result, {'Other': ['a']})

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
            f"Qz {EM_DASH} Quartz\n"
            f"Ser {EM_DASH} Sericite")

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
            "Basalt:\n"
            "  ol\n"
            "Granite:\n"
            "  kf\n"
            f"  Qz {EM_DASH} Quartz")

    def test_multiple_sections_blank_line_separated(self):
        out = format_text_sections(
            self._sections(),
            {'s1': ['Qz']},
            extra_unmatched={'s2': ['x']})
        self.assertEqual(out, "MINERALS / ALTERATION\nqz\n\nGEOLOGY\nx")

    def test_section_lines_structure(self):
        lines = build_text_section_lines(
            self._sections(),
            {'s1': ['si', 'cy']},
            {'s1': {'Si': 'Silica', 'Cy': 'Chalcopyrite'}})
        self.assertEqual(lines, [
            ('MINERALS / ALTERATION',
             [f"Cy {EM_DASH} Chalcopyrite", f"Si {EM_DASH} Silica"]),
        ])


EM = legend_config.EM_DASH


class TestTextOverrides(unittest.TestCase):

    BASE = (f"ALTERATION\nCy {EM} Chalcopyrite\nSi {EM} Silica\n\n"
            f"TEXTURES\nBx {EM} Breccia")
    HEADINGS = ['ALTERATION', 'TEXTURES']

    def test_no_edit_no_overrides(self):
        self.assertEqual(
            derive_text_overrides(self.BASE, self.BASE, self.HEADINGS), {})

    def test_deleted_line_removed_everywhere(self):
        edited = self.BASE.replace(f"Si {EM} Silica\n", "")
        ov = derive_text_overrides(self.BASE, edited, self.HEADINGS)
        self.assertEqual(ov['removed'], [f"Si {EM} Silica"])
        out = apply_text_overrides(
            [('ALTERATION', [f"Si {EM} Silica", f"Cy {EM} Chalcopyrite"])],
            ov)
        self.assertEqual(out, [('ALTERATION', [f"Cy {EM} Chalcopyrite"])])

    def test_reworded_line_is_replacement(self):
        edited = self.BASE.replace(
            f"Si {EM} Silica", f"Si {EM} Silica flooding")
        ov = derive_text_overrides(self.BASE, edited, self.HEADINGS)
        self.assertEqual(ov['replaced'],
                         {f"Si {EM} Silica": f"Si {EM} Silica flooding"})
        self.assertEqual(ov['removed'], [])
        out = apply_text_overrides(
            [('ALTERATION', [f"  Si {EM} Silica"])], ov)
        # Indentation of the original line is preserved
        self.assertEqual(out, [('ALTERATION',
                                [f"  Si {EM} Silica flooding"])])

    def test_added_line_under_heading(self):
        edited = self.BASE.replace(
            "TEXTURES\n", "TEXTURES\nVn — Veined\n").replace(
            '—', EM)
        ov = derive_text_overrides(self.BASE, edited, self.HEADINGS)
        self.assertEqual(ov['added'], {'TEXTURES': [f"Vn {EM} Veined"]})
        out = apply_text_overrides([('TEXTURES', [f"Bx {EM} Breccia"])], ov)
        self.assertEqual(out, [('TEXTURES',
                                [f"Bx {EM} Breccia", f"Vn {EM} Veined"])])

    def test_deleted_heading_suppresses_section(self):
        edited = self.BASE.split("\n\n")[0]  # TEXTURES block deleted
        ov = derive_text_overrides(self.BASE, edited, self.HEADINGS)
        self.assertIn('TEXTURES', ov['removed_headings'])
        out = apply_text_overrides(
            [('ALTERATION', ['x']), ('TEXTURES', ['y'])], ov)
        self.assertEqual([t for t, _ in out], ['ALTERATION'])

    def test_typed_without_preview_appends(self):
        ov = derive_text_overrides('', "custom note", [])
        self.assertEqual(ov['added_top'], ["custom note"])
        out = apply_text_overrides([('A', ['x'])], ov)
        self.assertEqual(out, [('A', ['x']), ('', ['custom note'])])

    def test_cleared_box_suppresses_everything(self):
        ov = derive_text_overrides(self.BASE, '', self.HEADINGS)
        out = apply_text_overrides(
            [('ALTERATION', [f"Cy {EM} Chalcopyrite", f"Si {EM} Silica"]),
             ('TEXTURES', [f"Bx {EM} Breccia"])], ov)
        self.assertEqual(out, [])

    def test_text_from_section_lines_untitled(self):
        text = text_from_section_lines([('A', ['x']), ('', ['note'])])
        self.assertEqual(text, "A\nx\n\nnote")


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
