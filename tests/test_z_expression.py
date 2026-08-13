"""
Unit tests for z_filter/expression.py (pure python, no QGIS).

Run from the plugin root:
    python -m unittest discover tests
"""

import importlib.util
import os
import unittest

# Load expression.py directly — importing the z_filter package would pull in
# qgis, which isn't available outside QGIS.
_path = os.path.join(os.path.dirname(__file__), '..', 'z_filter', 'expression.py')
_spec = importlib.util.spec_from_file_location('z_expression', _path)
z_expression = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(z_expression)

z_clause = z_expression.z_clause
z_range_clause = z_expression.z_range_clause
clause_for_spec = z_expression.clause_for_spec
spec_field_names = z_expression.spec_field_names
combine = z_expression.combine
strip_z_subset = z_expression.strip_z_subset
strip_z_subset_any = z_expression.strip_z_subset_any
parse_levels = z_expression.parse_levels
format_levels = z_expression.format_levels
format_number = z_expression.format_number
parse_extra_layers = z_expression.parse_extra_layers
format_extra_layers = z_expression.format_extra_layers
parse_rasters = z_expression.parse_rasters
format_rasters = z_expression.format_rasters
raster_in_windows = z_expression.raster_in_windows
format_suggestions = z_expression.format_suggestions
parse_suggestions = z_expression.parse_suggestions


class TestFormatNumber(unittest.TestCase):

    def test_integers_have_no_decimal(self):
        self.assertEqual(format_number(1250.0), '1250')

    def test_decimals_preserved(self):
        self.assertEqual(format_number(1247.5), '1247.5')

    def test_negative(self):
        self.assertEqual(format_number(-120.0), '-120')


class TestZClause(unittest.TestCase):

    def test_basic_window(self):
        self.assertEqual(
            z_clause(1250, 5, show_null=False),
            '("Elevation" >= 1245 AND "Elevation" <= 1255)')

    def test_show_null_wraps_with_is_null(self):
        self.assertEqual(
            z_clause(1250, 5, show_null=True),
            '("Elevation" IS NULL OR ("Elevation" >= 1245 AND "Elevation" <= 1255))')

    def test_zero_tolerance(self):
        self.assertEqual(
            z_clause(1250, 0, show_null=False),
            '("Elevation" >= 1250 AND "Elevation" <= 1250)')

    def test_fractional_level_and_tolerance(self):
        self.assertEqual(
            z_clause(1247.5, 2.5, show_null=False),
            '("Elevation" >= 1245 AND "Elevation" <= 1250)')

    def test_negative_levels_for_underground(self):
        self.assertEqual(
            z_clause(-100, 10, show_null=False),
            '("Elevation" >= -110 AND "Elevation" <= -90)')

    def test_custom_field(self):
        clause = z_clause(10, 1, show_null=False, field='RL')
        self.assertEqual(clause, '("RL" >= 9 AND "RL" <= 11)')


class TestZRangeClause(unittest.TestCase):

    def test_overlap_window(self):
        self.assertEqual(
            z_range_clause(365, 5, show_null=False),
            '("Z_Max" >= 360 AND "Z_Min" <= 370)')

    def test_show_null_guards_max_field_only(self):
        self.assertEqual(
            z_range_clause(365, 5, show_null=True),
            '("Z_Max" IS NULL OR ("Z_Max" >= 360 AND "Z_Min" <= 370))')

    def test_zero_tolerance(self):
        self.assertEqual(
            z_range_clause(365, 0, show_null=False),
            '("Z_Max" >= 365 AND "Z_Min" <= 365)')

    def test_negative_fractional(self):
        self.assertEqual(
            z_range_clause(-97.5, 2.5, show_null=False),
            '("Z_Max" >= -100 AND "Z_Min" <= -95)')

    def test_custom_fields(self):
        self.assertEqual(
            z_range_clause(10, 1, show_null=False,
                           field_min='RL_Min', field_max='RL_Max'),
            '("RL_Max" >= 9 AND "RL_Min" <= 11)')

    def test_degenerates_to_z_clause_with_equal_fields(self):
        # One strip-pattern generator covers both modes because the range
        # clause with min == max IS the single-field clause.
        for show_null in (True, False):
            for level, tol in ((1250, 5), (-97.5, 2.5), (0, 0)):
                self.assertEqual(
                    z_range_clause(level, tol, show_null=show_null,
                                   field_min='RL', field_max='RL'),
                    z_clause(level, tol, show_null=show_null, field='RL'))


class TestClauseForSpec(unittest.TestCase):

    def test_single_spec(self):
        spec = {'mode': 'single', 'field': 'RL'}
        self.assertEqual(clause_for_spec(spec, 10, 1, show_null=False),
                         z_clause(10, 1, show_null=False, field='RL'))

    def test_range_spec(self):
        spec = {'mode': 'range', 'field_min': 'Z_Min', 'field_max': 'Z_Max'}
        self.assertEqual(clause_for_spec(spec, 10, 1, show_null=False),
                         z_range_clause(10, 1, show_null=False))

    def test_defaults_to_elevation(self):
        self.assertEqual(clause_for_spec({}, 10, 1, show_null=False),
                         z_clause(10, 1, show_null=False))

    def test_spec_field_names(self):
        self.assertEqual(spec_field_names({'mode': 'single', 'field': 'RL'}),
                         ['RL'])
        self.assertEqual(
            spec_field_names({'mode': 'range', 'field_min': 'a',
                              'field_max': 'b'}),
            ['a', 'b'])
        self.assertEqual(spec_field_names({}), ['Elevation'])


class TestCombine(unittest.TestCase):

    def test_no_original(self):
        self.assertEqual(combine('', 'Z'), 'Z')
        self.assertEqual(combine(None, 'Z'), 'Z')
        self.assertEqual(combine('   ', 'Z'), 'Z')

    def test_with_original(self):
        self.assertEqual(combine('"Type" = \'fault\'', 'Z'),
                         '("Type" = \'fault\') AND Z')


class TestStripZSubset(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(strip_z_subset(''), '')
        self.assertEqual(strip_z_subset(None), '')

    def test_pure_z_clause_removed(self):
        for show_null in (True, False):
            subset = z_clause(1250, 5, show_null=show_null)
            self.assertEqual(strip_z_subset(subset), '', subset)

    def test_combined_returns_original(self):
        orig = '"Type" = \'fault\''
        for show_null in (True, False):
            subset = combine(orig, z_clause(1250, 5, show_null=show_null))
            self.assertEqual(strip_z_subset(subset), orig, subset)

    def test_unrelated_subset_unchanged(self):
        self.assertEqual(strip_z_subset('"Type" = \'fault\''), '"Type" = \'fault\'')

    def test_unrelated_elevation_mention_unchanged(self):
        subset = '"Elevation" > 100'
        self.assertEqual(strip_z_subset(subset), subset)

    def test_fractional_and_negative_bounds(self):
        subset = z_clause(-97.5, 2.5, show_null=True)
        self.assertEqual(strip_z_subset(subset), '')

    def test_roundtrip_after_level_change(self):
        # Controller rebuilds from the stored original each time; the exporter
        # may still meet a saved combined string — strip must recover orig.
        orig = '("Geologist" = \'HW\')'
        subset = combine(orig, z_clause(1300, 10))
        self.assertEqual(strip_z_subset(subset), orig)

    def test_scientific_notation_bounds(self):
        # %g emits exponent forms near zero (5.00001 - 5 -> '1e-05'); a
        # missed strip permanently filters the exported device copy.
        subset = z_clause(5.00001, 5, show_null=False)
        self.assertIn('e-05', subset)
        self.assertEqual(strip_z_subset(subset), '')
        subset = z_range_clause(1e-05, 2e-06, show_null=True)
        self.assertEqual(strip_z_subset_any(subset), '')


class TestStripZSubsetAny(unittest.TestCase):
    """The QField exporter's sanitizer — a missed strip permanently filters
    the device copy, so every clause shape must round-trip."""

    RL_SPEC = {'mode': 'single', 'field': 'RL'}
    PAIR_SPEC = {'mode': 'range', 'field_min': 'RL_Min',
                 'field_max': 'RL_Max'}

    def test_empty(self):
        self.assertEqual(strip_z_subset_any(''), '')
        self.assertEqual(strip_z_subset_any(None), '')

    def test_elevation_clause_without_specs(self):
        for show_null in (True, False):
            self.assertEqual(
                strip_z_subset_any(z_clause(1250, 5, show_null=show_null)),
                '')

    def test_conventional_range_clause_without_specs(self):
        # Belt-and-braces: Z_Min/Z_Max strips even when the persisted spec
        # list is stale or missing.
        for show_null in (True, False):
            self.assertEqual(
                strip_z_subset_any(
                    z_range_clause(365, 5, show_null=show_null)),
                '')

    def test_custom_single_field_needs_spec(self):
        subset = z_clause(365, 5, field='RL')
        self.assertEqual(strip_z_subset_any(subset), subset)
        self.assertEqual(strip_z_subset_any(subset, [self.RL_SPEC]), '')

    def test_custom_range_pair_needs_spec(self):
        subset = z_range_clause(365, 5, field_min='RL_Min',
                                field_max='RL_Max')
        self.assertEqual(strip_z_subset_any(subset), subset)
        self.assertEqual(strip_z_subset_any(subset, [self.PAIR_SPEC]), '')

    def test_combined_returns_original(self):
        orig = '"Type" = \'fault\''
        subset = combine(orig, z_range_clause(365, 5))
        self.assertEqual(strip_z_subset_any(subset), orig)

    def test_unrelated_range_mention_unchanged(self):
        subset = '"Z_Max" > 100'
        self.assertEqual(strip_z_subset_any(subset), subset)

    def test_roundtrip_after_level_change(self):
        orig = '("Geologist" = \'HW\')'
        subset = combine(orig, z_range_clause(420, 10, field_min='RL_Min',
                                              field_max='RL_Max'))
        self.assertEqual(strip_z_subset_any(subset, [self.PAIR_SPEC]), orig)

    def test_malformed_specs_are_ignored(self):
        subset = z_clause(1250, 5)
        specs = [{'mode': 'range'}, {'mode': 'single'}, {}]
        self.assertEqual(strip_z_subset_any(subset, specs), '')


class TestExtraLayerPersistence(unittest.TestCase):

    ENTRIES = [
        {'id': 'lyr1', 'name': 'UG_Survey_Points', 'mode': 'single',
         'field': 'RL', 'source': 'attr', 'checked': True},
        {'id': 'lyr2', 'name': 'Floor_Strings', 'mode': 'range',
         'field_min': 'Z_Min', 'field_max': 'Z_Max', 'source': 'geom',
         'checked': False},
    ]

    def test_roundtrip(self):
        self.assertEqual(
            parse_extra_layers(format_extra_layers(self.ENTRIES)),
            self.ENTRIES)

    def test_malformed_json(self):
        self.assertEqual(parse_extra_layers(''), [])
        self.assertEqual(parse_extra_layers(None), [])
        self.assertEqual(parse_extra_layers('not json'), [])
        self.assertEqual(parse_extra_layers('[1,2]'), [])
        self.assertEqual(parse_extra_layers('{"layers": "nope"}'), [])

    def test_invalid_entries_dropped(self):
        payload = format_extra_layers([
            self.ENTRIES[0],
            {'name': 'NoMode'},
            {'name': 'BadMode', 'mode': 'both', 'field': 'Z'},
            {'name': 'RangeMissingMax', 'mode': 'range', 'field_min': 'a'},
            {'mode': 'single', 'field': 'Z'},  # no name
        ])
        self.assertEqual(parse_extra_layers(payload), [self.ENTRIES[0]])

    def test_checked_defaults_true(self):
        parsed = parse_extra_layers(
            '{"layers":[{"name":"X","mode":"single","field":"RL"}]}')
        self.assertEqual(len(parsed), 1)
        self.assertTrue(parsed[0]['checked'])

    def test_label_field_roundtrip(self):
        entry = {'id': 'lyr3', 'name': 'RB UG strings', 'mode': 'single',
                 'field': 'RL', 'source': 'attr', 'checked': True,
                 'label_field': 'Level'}
        self.assertEqual(parse_extra_layers(format_extra_layers([entry])),
                         [entry])

    def test_label_field_absent_stays_absent(self):
        parsed = parse_extra_layers(format_extra_layers(self.ENTRIES))
        for entry in parsed:
            self.assertNotIn('label_field', entry)

    def test_label_user_with_field_roundtrip(self):
        entry = {'id': 'lyr3', 'name': 'RB UG strings', 'mode': 'single',
                 'field': 'RL', 'source': 'attr', 'checked': True,
                 'label_field': 'Zone', 'label_user': True}
        self.assertEqual(parse_extra_layers(format_extra_layers([entry])),
                         [entry])

    def test_label_user_explicit_none_roundtrip(self):
        # "(none)" persists as label_user without a label_field.
        entry = {'id': 'lyr3', 'name': 'RB UG strings', 'mode': 'single',
                 'field': 'RL', 'source': 'attr', 'checked': True,
                 'label_user': True}
        parsed = parse_extra_layers(format_extra_layers([entry]))
        self.assertEqual(parsed, [entry])
        self.assertNotIn('label_field', parsed[0])

    def test_label_user_absent_stays_absent(self):
        parsed = parse_extra_layers(format_extra_layers(self.ENTRIES))
        for entry in parsed:
            self.assertNotIn('label_user', entry)


class TestRasterPersistence(unittest.TestCase):
    """lgs_z_rasters: elevation-tied per-level basemap rasters."""

    ENTRIES = [
        {'id': 'ras1', 'name': 'Level plan 1420', 'elevation': 1420.0,
         'checked': True},
        {'id': 'ras2', 'name': 'Face scan 1395', 'elevation': 1395.5,
         'checked': False},
    ]

    def test_roundtrip(self):
        self.assertEqual(parse_rasters(format_rasters(self.ENTRIES)),
                         self.ENTRIES)

    def test_roundtrip_is_byte_stable(self):
        payload = format_rasters(self.ENTRIES)
        self.assertEqual(format_rasters(parse_rasters(payload)), payload)

    def test_malformed_json(self):
        self.assertEqual(parse_rasters(''), [])
        self.assertEqual(parse_rasters(None), [])
        self.assertEqual(parse_rasters('not json'), [])
        self.assertEqual(parse_rasters('[1,2]'), [])
        self.assertEqual(parse_rasters('{"rasters": "nope"}'), [])

    def test_invalid_entries_dropped(self):
        payload = format_rasters([
            self.ENTRIES[0],
            {'name': 'NoElevation'},
            {'name': 'BadElevation', 'elevation': 'high'},
            {'elevation': 1200},  # no name
        ])
        self.assertEqual(parse_rasters(payload), [self.ENTRIES[0]])

    def test_non_finite_elevations_dropped(self):
        parsed = parse_rasters(
            '{"rasters":[{"name":"A","elevation":"NaN"},'
            '{"name":"B","elevation":"Infinity"}]}')
        self.assertEqual(parsed, [])

    def test_checked_defaults_true(self):
        parsed = parse_rasters(
            '{"rasters":[{"name":"X","elevation":1200}]}')
        self.assertEqual(len(parsed), 1)
        self.assertTrue(parsed[0]['checked'])

    def test_id_defaults_empty(self):
        parsed = parse_rasters(
            '{"rasters":[{"name":"X","elevation":1200}]}')
        self.assertEqual(parsed[0]['id'], '')


class TestRasterInWindows(unittest.TestCase):
    """Mirrored in JS (lgs_companion.qml rasterInWindows) — keep in sync."""

    def test_inside_window(self):
        self.assertTrue(raster_in_windows(1420, [(1420, 5)]))

    def test_inclusive_edges(self):
        self.assertTrue(raster_in_windows(1415, [(1420, 5)]))
        self.assertTrue(raster_in_windows(1425, [(1420, 5)]))

    def test_outside_window(self):
        self.assertFalse(raster_in_windows(1414.9, [(1420, 5)]))
        self.assertFalse(raster_in_windows(1425.1, [(1420, 5)]))

    def test_multiple_windows_any_match(self):
        windows = [(1400, 5), (1420, 5)]
        self.assertTrue(raster_in_windows(1402, windows))
        self.assertTrue(raster_in_windows(1418, windows))
        self.assertFalse(raster_in_windows(1410, windows))

    def test_negative_underground_levels(self):
        self.assertTrue(raster_in_windows(-105, [(-100, 10)]))
        self.assertFalse(raster_in_windows(-111, [(-100, 10)]))

    def test_empty_windows(self):
        self.assertFalse(raster_in_windows(1420, []))
        self.assertFalse(raster_in_windows(1420, None))


class TestSuggestionPersistence(unittest.TestCase):
    """lgs_z_suggest: the desktop scan baked for the QField ladder."""

    SUGGESTIONS = [
        {'level': 1450.0, 'count': 5, 'lo': 1450.0, 'hi': 1450.0,
         'suggested_tol': 1.0, 'label': '000 Level'},
        {'level': 1448.9914748780934, 'count': 1, 'lo': 1448.9914748780934,
         'hi': 1448.9914748780934, 'suggested_tol': 1.0},
    ]
    SUMMARY = {'min': 1419.52, 'max': 1452.0, 'with_elev': 35,
               'blank': 276, 'spanning': 0}

    def test_roundtrip(self):
        parsed = parse_suggestions(
            format_suggestions(self.SUGGESTIONS, self.SUMMARY))
        self.assertEqual(parsed['with_elev'], 35)
        self.assertEqual(parsed['blank'], 276)
        self.assertEqual(parsed['spanning'], 0)
        self.assertEqual(parsed['min'], 1419.52)
        self.assertEqual(parsed['max'], 1452.0)
        self.assertEqual(len(parsed['suggestions']), 2)
        first, second = parsed['suggestions']
        self.assertEqual(first['label'], '000 Level')
        self.assertEqual(first['suggested_tol'], 1.0)
        self.assertNotIn('label', second)
        # Levels quantized to %g 6 sig figs, like every persisted level.
        self.assertEqual(second['level'], 1448.99)

    def test_empty_suggestions(self):
        self.assertEqual(format_suggestions([], self.SUMMARY), '')

    def test_deterministic_and_compact(self):
        a = format_suggestions(self.SUGGESTIONS, self.SUMMARY)
        b = format_suggestions(self.SUGGESTIONS, self.SUMMARY)
        self.assertEqual(a, b)
        # Compact separators (spaces may still appear inside label text).
        self.assertNotIn(': ', a)
        self.assertNotIn(', ', a)

    def test_format_idempotent_after_parse(self):
        # The persist-only-on-change compare relies on this.
        parsed = parse_suggestions(
            format_suggestions(self.SUGGESTIONS, self.SUMMARY))
        summary = {'min': parsed['min'], 'max': parsed['max'],
                   'with_elev': parsed['with_elev'],
                   'blank': parsed['blank'],
                   'spanning': parsed['spanning']}
        self.assertEqual(
            format_suggestions(parsed['suggestions'], summary),
            format_suggestions(self.SUGGESTIONS, self.SUMMARY))

    def test_defensive_parse(self):
        for bad in ('', None, 'not json', '[1,2]', '{"v":2,"levels":[]}',
                    '{"v":1}', '{"v":1,"levels":"nope"}',
                    '{"v":1,"levels":[]}',
                    '{"v":1,"levels":[{"level":"abc","count":1,'
                    '"lo":1,"hi":1,"tol":1}]}',
                    '{"v":1,"levels":[{"count":1,"lo":1,"hi":1,"tol":1}]}'):
            self.assertIsNone(parse_suggestions(bad), bad)

    def test_bad_entries_dropped_good_kept(self):
        payload = ('{"v":1,"min":1,"max":2,"withElev":3,"blank":0,'
                   '"spanning":0,"levels":[{"level":1450,"count":5,'
                   '"lo":1450,"hi":1450,"tol":1},'
                   '{"level":"junk","count":1,"lo":1,"hi":1,"tol":1}]}')
        parsed = parse_suggestions(payload)
        self.assertEqual(len(parsed['suggestions']), 1)
        self.assertEqual(parsed['suggestions'][0]['level'], 1450.0)


class TestLevelListPersistence(unittest.TestCase):

    def test_parse_sorted_unique(self):
        self.assertEqual(parse_levels('1250, 1240,1250,1260'), [1240.0, 1250.0, 1260.0])

    def test_parse_tolerates_junk(self):
        self.assertEqual(parse_levels('1250, abc, ,1240'), [1240.0, 1250.0])

    def test_parse_empty(self):
        self.assertEqual(parse_levels(''), [])
        self.assertEqual(parse_levels(None), [])

    def test_format_roundtrip(self):
        levels = [1260.0, 1240.0, 1250.0, 1250.0]
        self.assertEqual(format_levels(levels), '1240,1250,1260')
        self.assertEqual(parse_levels(format_levels(levels)), [1240.0, 1250.0, 1260.0])


if __name__ == '__main__':
    unittest.main()
