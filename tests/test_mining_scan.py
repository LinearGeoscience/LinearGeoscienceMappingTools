"""
Unit tests for mining_import/scan.py (pure python, no QGIS).

The source-key tests are the important ones: the key is what the merge engine
deletes by, so a key that collides across folders makes one file's import
destroy another's data.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pure_loader  # noqa: E402

scan = pure_loader.load('scan.py')

STR_BODY = """name,01-May-26,purpose,
0, 6551152.842, 392596.568, 0.000, 6551152.842, 392596.568, 0.000
20, 6581330.366, 398672.474, 167.739, 288
20, 6581326.834, 398672.402, 167.184, 289
0, 0.000, 0.000, 0.000,
0, 0.000, 0.000, 0.000, END
"""


def write(path, body=STR_BODY):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        fh.write(body)
    return path


class TestSourceKey(unittest.TestCase):

    def test_relative_to_root_with_forward_slashes(self):
        key = scan.source_key(r'C:\survey\1164\floor.str', r'C:\survey')
        self.assertEqual(key, '1164/floor.str')

    def test_case_folded(self):
        key = scan.source_key(r'C:\survey\1164\FLOOR.STR', r'C:\survey')
        self.assertEqual(key, '1164/floor.str')

    def test_same_basename_in_two_folders_keeps_distinct_keys(self):
        # A basename key would conflate these, and importing one would delete
        # the other's features.
        a = scan.source_key(r'C:\survey\1164\floor.str', r'C:\survey')
        b = scan.source_key(r'C:\survey\1218\floor.str', r'C:\survey')
        self.assertNotEqual(a, b)

    def test_key_survives_the_whole_tree_moving(self):
        a = scan.source_key(r'C:\survey\1164\floor.str', r'C:\survey')
        b = scan.source_key(r'D:\archive\2026\survey\1164\floor.str',
                            r'D:\archive\2026\survey')
        self.assertEqual(a, b)

    def test_file_at_root_keys_by_name(self):
        self.assertEqual(
            scan.source_key(r'C:\survey\floor.str', r'C:\survey'),
            'floor.str')

    def test_path_outside_root_falls_back_to_basename(self):
        key = scan.source_key(r'C:\elsewhere\floor.str', r'C:\survey')
        self.assertEqual(key, 'floor.str')


class TestDeriveRoot(unittest.TestCase):

    def test_single_file_uses_its_folder(self):
        root = scan.derive_root([os.path.join('a', 'b', 'c.str')])
        self.assertTrue(root.endswith(os.path.join('a', 'b')))

    def test_several_files_use_their_common_folder(self):
        base = tempfile.mkdtemp()
        paths = [write(os.path.join(base, '1164', 'floor.str')),
                 write(os.path.join(base, '1218', 'floor.str'))]
        self.assertEqual(os.path.normcase(scan.derive_root(paths)),
                         os.path.normcase(base))
        shutil.rmtree(base, ignore_errors=True)

    def test_empty_list(self):
        self.assertEqual(scan.derive_root([]), '')


class TestDiscover(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        write(os.path.join(self.base, 'mga_floor_1164.str'))
        write(os.path.join(self.base, 'sub', 'mga_floor_1218.str'))
        write(os.path.join(self.base, 'readme.txt'), 'not a survey file')

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def test_recurses_and_ignores_unknown_extensions(self):
        entries = scan.discover(self.base)
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(e.fmt_key == 'surpac' for e in entries))

    def test_levels_parsed_and_sorted(self):
        entries = scan.discover(self.base)
        self.assertEqual([e.level for e in entries], ['1164', '1218'])

    def test_keys_are_relative_to_the_scan_root(self):
        entries = scan.discover(self.base)
        self.assertEqual(sorted(e.key for e in entries),
                         ['mga_floor_1164.str', 'sub/mga_floor_1218.str'])

    def test_dtm_paired_as_a_companion_not_a_separate_row(self):
        write(os.path.join(self.base, 'mga_floor_1164.dtm'), 'TRISOLATION, 1,')
        entries = scan.discover(self.base)
        self.assertEqual(len(entries), 2)
        paired = [e for e in entries if e.level == '1164'][0]
        self.assertIn('.dtm', paired.companions)

    def test_dtm_pairing_is_case_insensitive(self):
        write(os.path.join(self.base, 'sub', 'MGA_FLOOR_1218.DTM'),
              'TRISOLATION, 1,')
        entries = scan.discover(self.base)
        paired = [e for e in entries if e.level == '1218'][0]
        self.assertIn('.dtm', paired.companions)

    def test_dtm_in_another_folder_is_not_paired(self):
        # Pairing is per-directory: a same-stem file elsewhere in the tree
        # belongs to a different survey, not to this one.
        write(os.path.join(self.base, 'mga_floor_1218.dtm'), 'TRISOLATION, 1,')
        entries = scan.discover(self.base)
        paired = [e for e in entries if e.level == '1218'][0]
        self.assertEqual(paired.companions, {})

    def test_size_and_mtime_captured(self):
        entries = scan.discover(self.base)
        for entry in entries:
            self.assertGreater(entry.size, 0)
            self.assertTrue(entry.mtime_utc)

    def test_discover_paths_returns_entries_and_root(self):
        paths = [os.path.join(self.base, 'mga_floor_1164.str')]
        entries, root = scan.discover_paths(paths)
        self.assertEqual(len(entries), 1)
        self.assertEqual(os.path.normcase(root), os.path.normcase(self.base))


class TestDuplicateKeys(unittest.TestCase):

    def _entry(self, key, path):
        return scan.Entry(path=path, key=key, fmt_key='surpac',
                          companions={}, level='1', size=1, mtime_utc='t')

    def test_none_when_unique(self):
        entries = [self._entry('a.str', 'a'), self._entry('b.str', 'b')]
        self.assertEqual(scan.duplicate_keys(entries), [])

    def test_reports_collisions(self):
        entries = [self._entry('a.str', 'x/a'), self._entry('a.str', 'y/a')]
        self.assertEqual(scan.duplicate_keys(entries), ['a.str'])


class TestClassify(unittest.TestCase):

    def _entry(self, key='a.str', size=100, mtime='2026-01-01T00:00:00+00:00'):
        return scan.Entry(path='/tmp/' + key, key=key, fmt_key='surpac',
                          companions={}, level='1', size=size,
                          mtime_utc=mtime)

    def test_new_when_absent_from_the_log(self):
        result = scan.classify([self._entry()], {})
        self.assertEqual(result[0].status, scan.STATUS_NEW)

    def test_unchanged_when_size_and_mtime_match(self):
        entry = self._entry()
        log = {'a.str': {'file_size': entry.size,
                         'file_mtime_utc': entry.mtime_utc,
                         'imported_at_utc': '2026-02-02T00:00:00+00:00'}}
        result = scan.classify([entry], log)
        self.assertEqual(result[0].status, scan.STATUS_UNCHANGED)
        self.assertIn('2026-02-02', result[0].note)

    def test_changed_when_size_differs(self):
        entry = self._entry()
        log = {'a.str': {'file_size': 999, 'file_mtime_utc': entry.mtime_utc}}
        result = scan.classify([entry], log)
        self.assertEqual(result[0].status, scan.STATUS_CHANGED)
        self.assertIn('Size', result[0].note)

    def test_changed_when_mtime_differs(self):
        entry = self._entry()
        log = {'a.str': {'file_size': entry.size,
                         'file_mtime_utc': '1999-01-01T00:00:00+00:00'}}
        result = scan.classify([entry], log)
        self.assertEqual(result[0].status, scan.STATUS_CHANGED)
        self.assertIn('Modified', result[0].note)

    def test_missing_sources_are_log_keys_with_no_file(self):
        log = {'a.str': {}, 'gone.str': {}}
        missing = scan.missing_sources([self._entry('a.str')], log)
        self.assertEqual(missing, ['gone.str'])


class TestFingerprint(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.path = write(os.path.join(self.base, 'a.str'))

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def test_shallow_skips_the_hash(self):
        size, mtime, digest = scan.file_fingerprint(self.path)
        self.assertGreater(size, 0)
        self.assertTrue(mtime)
        self.assertIsNone(digest)

    def test_deep_produces_a_hash(self):
        _size, _mtime, digest = scan.file_fingerprint(self.path, deep=True)
        self.assertTrue(digest)

    def test_hash_is_stable_and_content_sensitive(self):
        first = scan.content_hash(self.path)
        self.assertEqual(first, scan.content_hash(self.path))
        write(self.path, STR_BODY + '20, 1.0, 2.0, 3.0, 999\n')
        self.assertNotEqual(first, scan.content_hash(self.path))

    def test_partial_and_full_hashes_are_not_comparable(self):
        # A partial digest covers head+tail only; comparing it as equal to a
        # full digest over the same file would call a changed file unchanged.
        self.assertFalse(scan.hashes_comparable('p:abc', 'abc'))
        self.assertTrue(scan.hashes_comparable('p:abc', 'p:def'))
        self.assertTrue(scan.hashes_comparable('abc', 'def'))
        self.assertFalse(scan.hashes_comparable('', 'abc'))


class TestRelink(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.path = write(os.path.join(self.base, '1164', 'floor.str'))

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def test_matches_a_moved_file_by_content_hash(self):
        entries = scan.discover(self.base)
        digest = scan.content_hash(self.path)
        log = {'old/root/1164/floor.str': {
            'content_hash': digest, 'source_file': 'floor.str',
            'file_size': os.path.getsize(self.path)}}
        mapping = scan.relink_candidates(entries, log)
        self.assertEqual(mapping, {'old/root/1164/floor.str':
                                   '1164/floor.str'})

    def test_falls_back_to_basename_and_size(self):
        entries = scan.discover(self.base)
        log = {'old/floor.str': {
            'content_hash': None, 'source_file': 'floor.str',
            'file_size': os.path.getsize(self.path)}}
        mapping = scan.relink_candidates(entries, log)
        self.assertEqual(mapping, {'old/floor.str': '1164/floor.str'})

    def test_nothing_to_relink_when_keys_already_match(self):
        entries = scan.discover(self.base)
        log = {'1164/floor.str': {'source_file': 'floor.str'}}
        self.assertEqual(scan.relink_candidates(entries, log), {})


if __name__ == '__main__':
    unittest.main()
