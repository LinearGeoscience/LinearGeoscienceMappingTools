"""
The destination model, read from the SHIPPED template (pure python, no QGIS).

These run against Template/LGS_MappingTemplate.gpkg rather than a fixture on
purpose. The importer's whole design is that it learns the schema from the
template at run time, so the thing worth testing is that the template still says
what the importer assumes — and the assertions here are the early warning when
the next injector script changes it.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import import_loader  # noqa: E402

domain = import_loader.load('domain.py')


class TestPurity(unittest.TestCase):

    def test_pure_modules_import_without_qgis(self):
        for path in import_loader.pure_module_paths():
            import_loader.load(path)
        self.assertNotIn('qgis.core', sys.modules)


class TestTemplateShape(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.model = import_loader.template_model()

    def test_four_mapping_layers(self):
        self.assertEqual(
            list(self.model.layers),
            ['1 - FieldNotebook', '2 - Linework', '3 - Overlay', '4 - Basemap'])

    def test_geometry_types(self):
        self.assertEqual(
            [spec.geometry_type for spec in self.model.layers.values()],
            ['POINT', 'LINESTRING', 'POLYGON', 'POLYGON'])

    def test_only_basemap_declares_z(self):
        """Z is prohibited on three of the four, so the writer has to drop it."""
        with_z = [name for name, spec in self.model.layers.items() if spec.has_z]
        self.assertEqual(with_z, ['4 - Basemap'])

    def test_is_recognised_as_a_template(self):
        self.assertTrue(self.model.is_lgs_template)
        self.assertEqual(self.model.template_summary(),
                         'LGS template, current (Aug 2026)')

    def test_fingerprint_flags(self):
        flags = self.model.fingerprint()
        for expected in ('layer_order_swapped', 'linework_categories',
                         'linework_category_field', 'confidence', 'elevation',
                         'sample_type_codes', 'overlay_intensity'):
            self.assertIn(expected, flags)
        self.assertNotIn('pre_audit_basemap', flags)


class TestCodeDomains(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.model = import_loader.template_model()

    def test_lookup_tables_present(self):
        for table in ('BasemapCodes', 'OverlayCodes', 'LineworkCodes',
                      'FieldNotebookCodes', 'MineralCodes', 'TextureCodes',
                      'SampleTypeCodes', 'LineworkCategories'):
            self.assertIn(table, self.model.tables, table)

    def test_mineral_codes_key_is_value_not_code(self):
        """MineralCodes is keyed on `Value`. Reads like a bug; is not."""
        domain_ = self.model.layers['2 - Linework'].domain('Mineral1')
        self.assertEqual(domain_.table, 'MineralCodes')
        self.assertEqual(domain_.key_column, 'Value')

    def test_texture_codes_description_column_is_misspelled(self):
        """TextureCodes describes with `Desciption`, and the QML says so."""
        domain_ = self.model.layers['2 - Linework'].domain('VeinTexture')
        self.assertEqual(domain_.table, 'TextureCodes')
        self.assertEqual(domain_.desc_column, 'Desciption')

    def test_five_cascades(self):
        found = set()
        for layer_name, spec in self.model.layers.items():
            for field, domain_ in spec.code_domains.items():
                if domain_.parent_field:
                    found.add((layer_name, domain_.parent_field, field))
        self.assertEqual(found, {
            ('1 - FieldNotebook', 'Type', 'Subtype1'),
            ('2 - Linework', 'Category', 'Type'),
            ('3 - Overlay', 'Type', 'SubType1'),
            ('3 - Overlay', 'Type', 'SubType2'),
            ('3 - Overlay', 'Type', 'SubType3'),
            ('4 - Basemap', 'TypeLith1', 'Lithology1'),
            ('4 - Basemap', 'TypeLith2', 'Lithology2'),
        })

    def test_linework_parent_is_category_not_type(self):
        """The child is called Type and the parent Category. Easy to invert."""
        domain_ = self.model.layers['2 - Linework'].domain('Type')
        self.assertEqual(domain_.parent_field, 'Category')
        self.assertEqual(domain_.parent_column, 'Type')

    def test_alteration_uses_a_fixed_subset(self):
        domain_ = self.model.layers['1 - FieldNotebook'].domain('Alteration')
        self.assertEqual(set(domain_.allowed_parents),
                         {'Alteration', 'Weathering'})
        self.assertTrue(all(
            parent in ('Alteration', 'Weathering')
            for _code, _desc, parent in domain_.entries))

    def test_value_maps(self):
        confidence = self.model.layers['4 - Basemap'].domain('Confidence')
        self.assertEqual(confidence.source_kind, 'ValueMap')
        self.assertEqual(confidence.codes, ['Observed', 'Inferred', 'Queried'])
        weight = self.model.layers['2 - Linework'].domain('Weight')
        self.assertEqual(weight.codes,
                         ['Regional', 'Major', 'Moderate', 'Minor', 'Very Minor'])


class TestParentBackfillIsSafe(unittest.TestCase):
    """derive.fill_parents sets the parent without asking anyone.

    That is only defensible while every code belongs to exactly one parent. The
    day a code appears under two types, back-fill has to start asking, and this
    test is what says so.
    """

    @classmethod
    def setUpClass(cls):
        cls.model = import_loader.template_model()

    def test_every_code_has_exactly_one_parent(self):
        for table in ('BasemapCodes', 'OverlayCodes', 'LineworkCodes',
                      'FieldNotebookCodes'):
            parents = {}
            for code, _description, parent in self.model.table_entries(table):
                parents.setdefault(domain.fold(code), set()).add(parent)
            ambiguous = {code: sorted(values)
                         for code, values in parents.items() if len(values) > 1}
            self.assertEqual(ambiguous, {},
                             '{0} has codes under more than one type'.format(table))


class TestSquashTierIsSafe(unittest.TestCase):
    """The spelling tier only fires where a squashed key is unique.

    CodeDomain drops colliding keys, so this is really a check that the code
    tables have not grown a pair like 'Rock Chip' and 'rockchip' that would
    quietly stop matching.
    """

    @classmethod
    def setUpClass(cls):
        cls.model = import_loader.template_model()

    def test_no_squash_collisions_in_any_code_table(self):
        for table, rows in self.model.tables.items():
            squashed = {}
            for code, _description, _parent in rows:
                key = domain.squash(code)
                if key:
                    squashed.setdefault(key, set()).add(code)
            collisions = {key: sorted(values)
                          for key, values in squashed.items()
                          if len(values) > 1}
            self.assertEqual(collisions, {}, table)


class TestHelpers(unittest.TestCase):

    def test_is_blank_covers_the_literal_null(self):
        for value in (None, '', '   ', 'NULL', 'null', ' Null '):
            self.assertTrue(domain.is_blank(value), repr(value))
        for value in ('0', 0, 'Fault', ' x '):
            self.assertFalse(domain.is_blank(value), repr(value))

    def test_description_tail_strips_the_code_prefix(self):
        self.assertEqual(domain.description_tail('Hem', 'Hem - Hematite'),
                         'Hematite')
        self.assertEqual(domain.description_tail('Fresh', 'Fresh'), 'Fresh')
        self.assertEqual(
            domain.description_tail('TRSLM', 'TRSLM - Residual Soil, Loam'),
            'Residual Soil, Loam')

    def test_normalise_trims_the_trailing_spaces_old_code_lists_carry(self):
        self.assertEqual(domain.normalise('Fault - Normal '), 'Fault - Normal')
        self.assertEqual(domain.normalise('Shear  -  Dextral'),
                         'Shear - Dextral')

    def test_field_copyability(self):
        self.assertFalse(domain.is_copyable_field('fid'))
        self.assertFalse(domain.is_copyable_field(
            'auxiliary_storage_labeling_positionx'))
        self.assertTrue(domain.is_copyable_field('Lithology1'))


if __name__ == '__main__':
    unittest.main()
