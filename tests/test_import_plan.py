"""
Plan assembly, validation and saved profiles (pure python, no QGIS).

The invariant worth a test of its own: a plan contains no way to alter the
destination's schema. There is no add-column operation to construct, and a
source column with no home is dropped or folded into Comments. Adding unmatched
columns to the target is what put data_added_timestamp on two of the shipped
template's four layers and nowhere else, and it left imported projects with
forms and styling that quietly no longer matched their data.
"""

import os
import sys
import unittest
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import import_loader  # noqa: E402
import test_import_match  # noqa: E402  (reuses the legacy-source fixture)

domain = import_loader.load('domain.py')
plan_module = import_loader.load('plan.py')
match_values = import_loader.load('match_values.py')
scan = import_loader.load('scan.py')


# Values these fixture layers hold, standing in for a real source scan.
FIXTURE_VALUES = {
    ('3_Linework', 'Type'): OrderedDict([
        ('Fault', 40), ('Fault - Minor', 12), ('Formline - Fine', 15),
        ('Vein', 3)]),
    ('2_Alteration', 'SubType1'): OrderedDict([
        ('Hem', 20), ('Hematite', 12), ('Shear Zone - Major', 4)]),
    ('2_Alteration', 'Type'): OrderedDict([('Alteration', 32), ('Structure', 4)]),
    ('4_Lithology', 'Lithology1'): OrderedDict([('FGR', 50), ('SST', 20)]),
    ('4_Lithology', 'TypeLith1'): OrderedDict([('Lithology', 70)]),
    ('1_Structures', 'Subtype1'): OrderedDict([('FAP', 9), ('S0', 30)]),
    ('1_Structures', 'Type'): OrderedDict([('Structure', 39)]),
}


def counts_for(table, fields):
    result = OrderedDict()
    for field in fields:
        counts = FIXTURE_VALUES.get((table, field), OrderedDict())
        result[field] = scan.ValueCounts(field, OrderedDict(counts),
                                         total=sum(counts.values()))
    return result


def build(profile=None):
    template = import_loader.template_model()
    source = test_import_match.legacy_source()
    destination = plan_module.DestinationRef('gpkg', 'C:/nowhere/dest.gpkg',
                                             'dest.gpkg')
    return plan_module.build_plan(source, template, destination, counts_for,
                                  profile=profile or {})


class TestPlanShape(unittest.TestCase):

    def setUp(self):
        self.plan = build()

    def test_all_four_layers_are_included(self):
        self.assertEqual(len(self.plan.included()), 4)
        self.assertEqual(
            sorted(item.target_layer for item in self.plan.included()),
            ['1 - FieldNotebook', '2 - Linework', '3 - Overlay', '4 - Basemap'])

    def test_there_is_no_way_to_alter_the_destination_schema(self):
        """Every mapped target must already exist on the destination."""
        for item in self.plan.included():
            target_spec = self.plan.target_spec(item)
            for source_field, target_field in item.mapping().items():
                self.assertIn(target_field, target_spec.fields,
                              '{0} -> {1}'.format(source_field, target_field))

    def test_unmatched_columns_are_dropped_or_kept_in_comments(self):
        for item in self.plan.included():
            for match in item.field_plan.matches.values():
                if match.is_mapped or match.status == 'ignored':
                    continue
                self.assertIn(match.unmatched_action, ('drop', 'comments'))

    def test_options_default_to_the_safe_choice(self):
        options = self.plan.options
        self.assertTrue(options.backup)
        self.assertTrue(options.skip_duplicate_uuids)
        self.assertTrue(options.generate_missing_uuids)


class TestValidation(unittest.TestCase):

    def setUp(self):
        self.plan = build()

    def _undecided(self):
        return [resolution for item in self.plan.included()
                for resolution in item.undecided()]

    def test_undecided_codes_block_the_import(self):
        report = self.plan.validate()
        self.assertFalse(report.ok)
        self.assertTrue(any('decision' in finding.title
                            for finding in report.errors))

    def test_resolving_everything_clears_the_block(self):
        for resolution in self._undecided():
            resolution.leave_blank()
        report = self.plan.validate()
        self.assertTrue(report.ok, [f.title for f in report.errors])

    def test_splits_and_renames_are_reported_as_notes_not_warnings(self):
        for resolution in self._undecided():
            resolution.leave_blank()
        report = self.plan.validate()
        titles = ' '.join(finding.title for finding in report.notes)
        self.assertIn('split into Weight', titles)

    def test_dropped_columns_are_warned_about(self):
        for resolution in self._undecided():
            resolution.leave_blank()
        report = self.plan.validate()
        titles = ' '.join(finding.title for finding in report.warnings)
        self.assertIn('will not be imported', titles)

    def test_an_empty_selection_blocks(self):
        for item in self.plan.layer_imports:
            item.include = False
        report = self.plan.validate()
        self.assertFalse(report.ok)
        self.assertIn('Nothing selected', report.errors[0].title)

    def test_source_and_destination_being_one_file_blocks(self):
        self.plan.source_model.path = self.plan.destination.path
        report = self.plan.validate()
        self.assertTrue(any('same file' in finding.title
                            for finding in report.errors))


class TestRepeatedSourceUuids(unittest.TestCase):
    """Features duplicated in the field share the original's UUID.

    They are real features, so the importer must say so plainly rather than
    fold them in with "already there" — that wording sent them silently to the
    floor before.
    """

    def _plan(self, repeated=0, raises=False, import_repeats=True):
        template = import_loader.template_model()
        source = test_import_match.legacy_source()

        def source_uuids(table, _n=repeated):
            if raises:
                raise IOError('the source moved')
            return {'a', 'b', 'c'}, 0, _n

        def destination_uuids(layer_name):
            return set()

        built = plan_module.build_plan(
            source, template,
            plan_module.DestinationRef('gpkg', 'C:/nowhere/dest.gpkg', 'dest'),
            counts_for, source_uuids_for=source_uuids,
            destination_uuids_for=destination_uuids)
        built.options.import_repeated_uuids = import_repeats
        for item in built.included():
            for resolution in item.undecided():
                resolution.leave_blank()
        return built

    def test_repeats_are_counted_per_layer_and_in_total(self):
        built = self._plan(repeated=2)
        self.assertTrue(all(item.repeated_in_source == 2
                            for item in built.included()))
        self.assertEqual(built.summary()['repeated_in_source'],
                         2 * len(built.included()))

    def test_they_are_flagged_as_a_warning_before_the_import_runs(self):
        report = self._plan(repeated=2).validate()
        titles = ' '.join(finding.title for finding in report.warnings)
        self.assertIn('share a UUID with another feature in the source', titles)
        details = ' '.join(finding.detail for finding in report.warnings)
        self.assertIn('under a new UUID', details)

    def test_turning_the_option_off_says_only_the_first_lands(self):
        built = self._plan(repeated=2, import_repeats=False)
        details = ' '.join(finding.detail
                           for finding in built.validate().warnings)
        self.assertIn('Only the first of each will be imported', details)
        # ...and the count drops back out of the estimate.
        for item in built.included():
            self.assertEqual(built.expected_new_for(item),
                             item.expected_new - 2)

    def test_no_repeats_means_no_warning(self):
        report = self._plan(repeated=0).validate()
        titles = ' '.join(finding.title for finding in report.warnings)
        self.assertNotIn('share a UUID', titles)

    def test_a_failed_check_is_admitted_not_passed_off_as_clean(self):
        built = self._plan(raises=True)
        self.assertTrue(all(item.estimate_failed for item in built.included()))
        titles = ' '.join(finding.title for finding in built.validate().notes)
        self.assertIn('Could not check', titles)


class TestProjectDestination(unittest.TestCase):
    """Project mode resolves to a real file and gets the same guards.

    The guards used to be gated on kind == 'gpkg', which let a project-mode
    import silently target its own source file — or nothing at all.
    """

    def _plan(self, destination, source_path=''):
        template = import_loader.template_model()
        source = test_import_match.legacy_source()
        source.path = source_path
        return plan_module.build_plan(source, template, destination,
                                      counts_for, profile={})

    def _validate(self, plan):
        for item in plan.included():
            for resolution in item.undecided():
                resolution.leave_blank()
        return plan.validate()

    def test_importing_a_file_into_itself_blocks_in_project_mode(self):
        path = 'C:/somewhere/Mapping.gpkg'
        destination = plan_module.DestinationRef('project', path,
                                                 'this project (Mapping.gpkg)')
        report = self._validate(self._plan(destination, source_path=path))
        self.assertTrue(any('same file' in finding.title
                            for finding in report.errors))

    def test_an_unresolved_destination_path_blocks(self):
        destination = plan_module.DestinationRef('project', '', 'this project')
        report = self._validate(self._plan(destination))
        self.assertTrue(any('which GeoPackage to write to' in finding.title
                            for finding in report.errors))


class TestNewCodes(unittest.TestCase):

    def setUp(self):
        self.plan = build()
        self.resolution = None
        for item in self.plan.included():
            for resolutions in item.resolutions.values():
                for resolution in resolutions.values():
                    if resolution.value == 'Formline - Fine':
                        self.resolution = resolution
        self.assertIsNotNone(self.resolution)

    def test_adding_a_code_appears_in_the_plan(self):
        self.resolution.add_as_new_code(parent='Formlines',
                                        description='Formline - Fine')
        codes = self.plan.new_codes()
        self.assertEqual(len(codes), 1)
        self.assertEqual(codes[0].table, 'LineworkCodes')
        self.assertEqual(codes[0].code, 'Formline - Fine')
        self.assertEqual(codes[0].parent, 'Formlines')

    def test_registering_it_makes_the_parent_backfillable(self):
        self.resolution.add_as_new_code(parent='Formlines',
                                        description='Formline - Fine')
        template = self.plan.target_model
        domain_ = template.layers['2 - Linework'].domain('Type')
        try:
            self.plan.register_new_codes()
            self.assertEqual(domain_.parent_of('Formline - Fine'), 'Formlines')
        finally:
            domain_.entries = tuple(entry for entry in domain_.entries
                                    if entry[0] != 'Formline - Fine')
            domain_._index()

    def test_summary_counts_what_was_automatic(self):
        for item in self.plan.included():
            for resolution in item.undecided():
                resolution.leave_blank()
        summary = self.plan.summary()
        self.assertEqual(summary['layers'], 4)
        self.assertGreater(summary['codes_auto'], 0)
        self.assertEqual(summary['undecided'], 0)


class TestProfiles(unittest.TestCase):
    """Capture and replay, without touching QgsSettings."""

    def setUp(self):
        self.profile_module = import_loader.load('profile.py')
        self.plan = build()
        for item in self.plan.included():
            for resolution in item.undecided():
                if resolution.value == 'Formline - Fine':
                    resolution.add_as_new_code(parent='Formlines')
                else:
                    resolution.choose('Slp')

    def test_capture_records_decisions_but_not_identity_matches(self):
        captured = self.profile_module.capture(self.plan, name='test')
        self.assertEqual(captured['layers']['3_Linework'], '2 - Linework')
        linework_values = captured['values']['3_Linework']['Type']
        self.assertIn('Formline - Fine', linework_values)
        # 'Fault' matched outright; storing it would bloat the profile for
        # nothing and is deliberately skipped.
        self.assertNotIn('Fault', linework_values)

    def test_a_captured_profile_replays_onto_a_fresh_plan(self):
        captured = self.profile_module.capture(self.plan, name='test')
        replayed = build(profile=captured)
        decisions = {}
        for item in replayed.included():
            for resolutions in item.resolutions.values():
                for value, resolution in resolutions.items():
                    decisions[value] = resolution
        self.assertEqual(decisions['Formline - Fine'].status,
                         match_values.ADD_CODE)
        self.assertEqual(decisions['Formline - Fine'].note,
                         'from saved profile')
        self.assertEqual(replayed.undecided_count(), 0)

    def test_signature_is_shape_based_not_name_based(self):
        template = import_loader.template_model()
        first = test_import_match.legacy_source()
        second = test_import_match.legacy_source()
        self.assertEqual(self.profile_module.signature(first),
                         self.profile_module.signature(second))
        self.assertNotEqual(self.profile_module.signature(first),
                            self.profile_module.signature(template))

    def test_a_profile_for_another_shape_is_rejected(self):
        captured = self.profile_module.capture(self.plan, name='test')
        template = import_loader.template_model()
        self.assertTrue(self.profile_module.is_compatible(
            captured, test_import_match.legacy_source(), template))
        self.assertFalse(self.profile_module.is_compatible(
            captured, template, template))


if __name__ == '__main__':
    unittest.main()
