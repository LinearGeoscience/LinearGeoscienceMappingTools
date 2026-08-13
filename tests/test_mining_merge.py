"""
Unit tests for mining_import/merge.py (pure python, no QGIS).

The empty-set case is the one that matters most: an `IN ()` clause is a
syntax error on some backends and matches everything on others, so an import
with nothing to supersede would silently empty the layer.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pure_loader  # noqa: E402

merge = pure_loader.load('merge.py')


class TestQuote(unittest.TestCase):

    def test_plain_value(self):
        self.assertEqual(merge.quote('floor.str'), "'floor.str'")

    def test_embedded_single_quote_is_doubled(self):
        # Mirrors QgsExpression.quotedValue; a raw quote would end the
        # literal and turn the rest of the key into SQL.
        self.assertEqual(merge.quote("o'brien.str"), "'o''brien.str'")

    def test_none_is_null(self):
        self.assertEqual(merge.quote(None), 'NULL')

    def test_non_string_coerced(self):
        self.assertEqual(merge.quote(1164), "'1164'")


class TestDeleteExpression(unittest.TestCase):

    def test_replace_source(self):
        expr = merge.delete_expression(
            merge.POLICY_REPLACE_SOURCE, source_keys=['a.str', 'b/c.str'])
        self.assertEqual(expr, '"SourceKey" IN (\'a.str\', \'b/c.str\')')

    def test_replace_level(self):
        expr = merge.delete_expression(
            merge.POLICY_REPLACE_LEVEL, levels=['1164', '1218'])
        self.assertEqual(expr, '"Level" IN (\'1164\', \'1218\')')

    def test_replace_all(self):
        self.assertEqual(
            merge.delete_expression(merge.POLICY_REPLACE_ALL), 'TRUE')

    def test_append_never_deletes(self):
        self.assertIsNone(merge.delete_expression(
            merge.POLICY_APPEND, source_keys=['a.str'], levels=['1164']))

    def test_empty_source_keys_return_none_not_in_nothing(self):
        self.assertIsNone(merge.delete_expression(
            merge.POLICY_REPLACE_SOURCE, source_keys=[]))

    def test_empty_levels_return_none(self):
        self.assertIsNone(merge.delete_expression(
            merge.POLICY_REPLACE_LEVEL, levels=[]))

    def test_no_expression_ever_contains_an_empty_in_clause(self):
        for policy in merge.POLICIES:
            expr = merge.delete_expression(policy, source_keys=[], levels=[])
            if expr is not None:
                self.assertNotIn('IN ()', expr)

    def test_duplicate_keys_collapsed_in_order(self):
        expr = merge.delete_expression(
            merge.POLICY_REPLACE_SOURCE, source_keys=['a', 'b', 'a'])
        self.assertEqual(expr, '"SourceKey" IN (\'a\', \'b\')')

    def test_batch_guard_protects_the_rows_just_written(self):
        expr = merge.delete_expression(
            merge.POLICY_REPLACE_SOURCE, source_keys=['a.str'],
            exclude_batch='B1')
        self.assertEqual(
            expr,
            '("SourceKey" IN (\'a.str\')) AND '
            '("BatchId" IS NULL OR "BatchId" <> \'B1\')')

    def test_batch_guard_covers_null_batch_ids(self):
        # Features written before BatchId existed, or by another tool, have
        # NULL there and must still be superseded.
        expr = merge.delete_expression(
            merge.POLICY_REPLACE_ALL, exclude_batch='B1')
        self.assertIn('"BatchId" IS NULL', expr)

    def test_batch_guard_skipped_when_no_batch_given(self):
        expr = merge.delete_expression(
            merge.POLICY_REPLACE_SOURCE, source_keys=['a.str'])
        self.assertNotIn('BatchId', expr)

    def test_quoting_applies_inside_the_in_clause(self):
        expr = merge.delete_expression(
            merge.POLICY_REPLACE_SOURCE, source_keys=["o'k.str"])
        self.assertEqual(expr, '"SourceKey" IN (\'o\'\'k.str\')')

    def test_unknown_policy_raises(self):
        with self.assertRaises(ValueError):
            merge.delete_expression('nonsense', source_keys=['a'])


class TestBatchExpression(unittest.TestCase):

    def test_selects_one_batch(self):
        self.assertEqual(merge.batch_expression('B1'), '"BatchId" = \'B1\'')


class TestPolicyMetadata(unittest.TestCase):

    def test_every_policy_has_a_label_and_hint(self):
        for policy in merge.POLICIES:
            self.assertIn(policy, merge.POLICY_LABELS)
            self.assertIn(policy, merge.POLICY_HINTS)

    def test_default_is_replace_source(self):
        self.assertEqual(merge.POLICIES[0], merge.POLICY_REPLACE_SOURCE)


if __name__ == '__main__':
    unittest.main()
