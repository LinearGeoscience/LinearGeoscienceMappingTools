"""
Unit tests for mining_import/ir.py (pure python, no QGIS).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pure_loader  # noqa: E402

ir = pure_loader.load('ir.py')


class TestDefaults(unittest.TestCase):

    def test_polyline_defaults(self):
        poly = ir.Polyline([(0, 0, 0), (1, 1, 1)])
        self.assertEqual(poly.attrs, {})
        self.assertFalse(poly.closed)

    def test_station_defaults(self):
        self.assertEqual(ir.Station((0, 0, 0)).attrs, {})

    def test_parsed_file_defaults(self):
        parsed = ir.ParsedFile('/tmp/a.str', 'a.str', 'surpac')
        self.assertEqual(parsed.polylines, ())
        self.assertEqual(parsed.stations, ())
        self.assertEqual(parsed.surfaces, ())
        self.assertEqual(parsed.annotations, ())
        self.assertEqual(parsed.attrs, {})
        self.assertEqual(parsed.warnings, ())


class TestZRange(unittest.TestCase):

    def test_min_and_max(self):
        self.assertEqual(ir.z_range([(0, 0, 5.0), (1, 1, 2.0), (2, 2, 9.0)]),
                         (2.0, 9.0))

    def test_none_elevations_ignored(self):
        self.assertEqual(ir.z_range([(0, 0, None), (1, 1, 3.0)]), (3.0, 3.0))

    def test_all_none_gives_none_not_zero(self):
        # NULL Z_Min/Z_Max means the Z Filter range clause never matches;
        # a 0.0 default would silently pin the feature to sea level.
        self.assertEqual(ir.z_range([(0, 0, None), (1, 1, None)]),
                         (None, None))

    def test_empty(self):
        self.assertEqual(ir.z_range([]), (None, None))

    def test_two_tuples_tolerated(self):
        self.assertEqual(ir.z_range([(0, 0), (1, 1)]), (None, None))


class TestMergeAttrs(unittest.TestCase):

    def test_later_wins(self):
        self.assertEqual(ir.merge_attrs({'a': 1}, {'a': 2}), {'a': 2})

    def test_none_values_do_not_overwrite(self):
        self.assertEqual(ir.merge_attrs({'a': 1}, {'a': None}), {'a': 1})

    def test_none_dicts_tolerated(self):
        self.assertEqual(ir.merge_attrs(None, {'a': 1}, {}), {'a': 1})

    def test_returns_a_fresh_dict_each_time(self):
        # Handing the same dict to two features means editing one silently
        # edits the other -- the classic mutable-default trap.
        source = {'a': 1}
        first = ir.merge_attrs(source)
        second = ir.merge_attrs(source)
        self.assertIsNot(first, source)
        self.assertIsNot(first, second)
        first['a'] = 99
        self.assertEqual(source['a'], 1)
        self.assertEqual(second['a'], 1)


class TestIsClosed(unittest.TestCase):

    def test_closed_ring(self):
        self.assertTrue(ir.is_closed(
            [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 0, 0)]))

    def test_open_string(self):
        self.assertFalse(ir.is_closed([(0, 0, 0), (1, 0, 0), (1, 1, 0)]))

    def test_z_ignored(self):
        # A ramp that climbs back over its own start is closed in plan, which
        # is what a surveyor means by closed.
        self.assertTrue(ir.is_closed(
            [(0, 0, 0), (1, 0, 5), (1, 1, 8), (0, 0, 12)]))

    def test_too_few_points(self):
        self.assertFalse(ir.is_closed([(0, 0, 0), (0, 0, 0)]))


class TestSplitByZSpan(unittest.TestCase):

    def test_flat_string_unchanged(self):
        points = [(0, 0, 100.0), (1, 0, 100.5), (2, 0, 101.0)]
        self.assertEqual(ir.split_by_z_span(points), [points])

    def test_span_exactly_at_cap_stays_whole(self):
        # Strictly greater-than: a 2.0 span is still one flat feature.
        points = [(0, 0, 100.0), (1, 0, 101.0), (2, 0, 102.0)]
        self.assertEqual(ir.split_by_z_span(points), [points])

    def test_all_none_z_unchanged(self):
        points = [(0, 0, None), (1, 0, None), (2, 0, None)]
        self.assertEqual(ir.split_by_z_span(points), [points])

    def test_two_point_steep_string_unchanged(self):
        points = [(0, 0, 100.0), (1, 0, 110.0)]
        self.assertEqual(ir.split_by_z_span(points), [points])

    def test_inclined_string_splits_with_shared_boundaries(self):
        points = [(i, 0, 100.0 + i) for i in range(7)]  # 6 m rise
        sections = ir.split_by_z_span(points)
        self.assertGreater(len(sections), 1)
        for a, b in zip(sections, sections[1:]):
            self.assertEqual(a[-1], b[0])
        # Reassembling (dropping each repeated boundary vertex) restores the
        # original vertex sequence exactly -- no gaps, no invented points.
        rebuilt = list(sections[0])
        for sec in sections[1:]:
            rebuilt.extend(sec[1:])
        self.assertEqual(rebuilt, points)

    def test_sections_respect_span_and_size(self):
        points = [(i, 0, 100.0 + i * 0.7) for i in range(40)]
        sections = ir.split_by_z_span(points)
        for sec in sections:
            self.assertGreaterEqual(len(sec), 2)
            lo, hi = ir.z_range(sec)
            self.assertLessEqual(hi - lo, ir.Z_SECTION_SPAN + 1e-9)

    def test_single_steep_segment_left_intact(self):
        # One leg drops 5 m on its own: kept as a section rather than
        # interpolated, so its span may exceed the cap.
        points = [(0, 0, 100.0), (1, 0, 100.5), (2, 0, 105.5),
                  (3, 0, 106.0)]
        sections = ir.split_by_z_span(points)
        for sec in sections:
            self.assertGreaterEqual(len(sec), 2)
        rebuilt = list(sections[0])
        for sec in sections[1:]:
            rebuilt.extend(sec[1:])
        self.assertEqual(rebuilt, points)

    def test_none_z_vertices_never_trigger_a_split(self):
        points = [(0, 0, 100.0), (1, 0, None), (2, 0, 101.0),
                  (3, 0, None), (4, 0, 102.5), (5, 0, 103.5)]
        sections = ir.split_by_z_span(points)
        rebuilt = list(sections[0])
        for sec in sections[1:]:
            rebuilt.extend(sec[1:])
        self.assertEqual(rebuilt, points)
        for sec in sections:
            self.assertGreaterEqual(len(sec), 2)

    def test_closed_inclined_ring_reassembles(self):
        points = [(0, 0, 100.0), (10, 0, 103.0), (10, 10, 106.0),
                  (0, 10, 103.0), (0, 0, 100.0)]
        sections = ir.split_by_z_span(points)
        self.assertGreater(len(sections), 1)
        rebuilt = list(sections[0])
        for sec in sections[1:]:
            rebuilt.extend(sec[1:])
        self.assertEqual(rebuilt, points)


class TestLength3D(unittest.TestCase):

    def test_simple_run(self):
        self.assertAlmostEqual(
            ir.polyline_length_3d([(0, 0, 0), (3, 4, 0)]), 5.0)

    def test_includes_the_z_component(self):
        self.assertAlmostEqual(
            ir.polyline_length_3d([(0, 0, 0), (0, 3, 4)]), 5.0)

    def test_missing_z_falls_back_to_2d_for_that_segment(self):
        self.assertAlmostEqual(
            ir.polyline_length_3d([(0, 0, None), (3, 4, 0)]), 5.0)

    def test_single_point(self):
        self.assertEqual(ir.polyline_length_3d([(0, 0, 0)]), 0.0)


if __name__ == '__main__':
    unittest.main()
