"""
Unit tests for the transported-cover subset helpers in
z_filter/expression.py (pure python, no QGIS).

Run from the plugin root:
    python -m unittest discover tests
"""

import importlib.util
import os
import unittest

# Load expression.py directly — importing the z_filter package would pull in
# qgis, which isn't available outside QGIS.
_path = os.path.join(os.path.dirname(__file__), '..', 'z_filter', 'expression.py')
_spec = importlib.util.spec_from_file_location('z_expression_cover', _path)
z_expression = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(z_expression)

cover_hide_clause = z_expression.cover_hide_clause
cover_opacity_expression = z_expression.cover_opacity_expression
strip_cover_subset = z_expression.strip_cover_subset
apply_cover_to_subset = z_expression.apply_cover_to_subset
combine = z_expression.combine
z_clause = z_expression.z_clause
strip_z_subset_any = z_expression.strip_z_subset_any

# The QML sidecar hardcodes this exact string — test_qfield_cover_js.py
# asserts byte-parity against the same constant.
EXPECTED_CLAUSE = '("TypeLith1" IS NULL OR "TypeLith1" <> \'Transported Cover\')'


class TestCoverClause(unittest.TestCase):

    def test_exact_text(self):
        self.assertEqual(cover_hide_clause(), EXPECTED_CLAUSE)


class TestCoverOpacityExpression(unittest.TestCase):
    """The data-defined symbol opacity that fades cover short of hiding it.

    Baked onto the Basemap renderer by cover_toggle and driven from both
    sides by the lgs_cover_opacity project variable, so the text has to
    stay a valid QGIS expression in percent.
    """

    def test_exact_text(self):
        self.assertEqual(
            cover_opacity_expression(),
            "if(coalesce(\"TypeLith1\", '') = 'Transported Cover', "
            "coalesce(@lgs_cover_opacity, 100), 100)")

    def test_reads_the_shared_variable_name(self):
        self.assertIn('@' + z_expression.VAR_COVER_OPACITY,
                      cover_opacity_expression())

    def test_defaults_to_fully_opaque(self):
        # An export whose project never set the variable must render
        # cover unchanged, not invisible.
        self.assertIn('coalesce(@lgs_cover_opacity, 100)',
                      cover_opacity_expression())

    def test_steps_ladder(self):
        # The desktop button cycles this list; 0 is the subset-string
        # hide, which is why it must stay last.
        self.assertEqual(z_expression.COVER_STEPS, [100, 50, 25, 0])


class TestStripCoverSubset(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(strip_cover_subset(''), '')
        self.assertEqual(strip_cover_subset(None), '')

    def test_whole_string_is_clause(self):
        self.assertEqual(strip_cover_subset(cover_hide_clause()), '')

    def test_combined_returns_original(self):
        subset = combine('"Geologist" = \'HW\'', cover_hide_clause())
        self.assertEqual(strip_cover_subset(subset), '"Geologist" = \'HW\'')

    def test_unrecognized_unchanged(self):
        self.assertEqual(strip_cover_subset('"Elevation" > 5'),
                         '"Elevation" > 5')

    def test_case_and_whitespace_tolerant(self):
        variant = '(  "TypeLith1"  is  null  OR "TypeLith1" <>' \
                  " 'Transported Cover' )"
        self.assertEqual(strip_cover_subset(variant), '')


class TestApplyCoverToSubset(unittest.TestCase):

    def test_hide_on_empty(self):
        self.assertEqual(apply_cover_to_subset('', True), cover_hide_clause())

    def test_show_on_empty(self):
        self.assertEqual(apply_cover_to_subset('', False), '')

    def test_round_trip(self):
        base = '"Geologist" = \'HW\''
        hidden = apply_cover_to_subset(base, True)
        self.assertEqual(apply_cover_to_subset(hidden, False), base)

    def test_idempotent(self):
        base = '"Geologist" = \'HW\''
        once = apply_cover_to_subset(base, True)
        self.assertEqual(apply_cover_to_subset(once, True), once)


class TestZInterplay(unittest.TestCase):
    """The cover clause lives in the baseline, beneath the z clause."""

    def test_strip_z_recovers_cover_bearing_baseline(self):
        baseline = apply_cover_to_subset('"Geologist" = \'HW\'', True)
        live = combine(baseline, z_clause(1250, 5))
        self.assertEqual(strip_z_subset_any(live), baseline)
        self.assertEqual(strip_cover_subset(baseline), '"Geologist" = \'HW\'')

    def test_cover_only_baseline_under_z(self):
        baseline = apply_cover_to_subset('', True)
        live = combine(baseline, z_clause(1250, 5))
        self.assertEqual(strip_z_subset_any(live), baseline)
        self.assertEqual(strip_cover_subset(baseline), '')

    def test_toggle_off_under_z_shape(self):
        # What set_cover_hidden does while the z filter owns the layer.
        baseline = apply_cover_to_subset('', True)
        z_text = z_clause(1250, 5)
        new_baseline = apply_cover_to_subset(baseline, False)
        self.assertEqual(new_baseline, '')
        self.assertEqual(combine(new_baseline, z_text), z_text)


if __name__ == '__main__':
    unittest.main()
