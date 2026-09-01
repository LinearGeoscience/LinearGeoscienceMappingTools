"""
Unit tests for raster_optimise/core.py's pure half (no QGIS, no GDAL).

Run from the plugin root:
    python -m unittest discover tests
"""

import importlib.util
import os
import unittest

# Load core.py directly — the package would drag in qgis via the dialog.
_path = os.path.join(os.path.dirname(__file__), '..', 'raster_optimise',
                     'core.py')
_spec = importlib.util.spec_from_file_location('raster_optimise_core',
                                               _path)
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)


def info(width=9177, height=10224, bands=4, size_mb=211.0, overviews=0):
    return {'width': width, 'height': height, 'bands': bands,
            'bytes': int(size_mb * 1e6), 'overviews': overviews}


class TestTileWindows(unittest.TestCase):

    def test_single_tile_covers_everything(self):
        wins = core.tile_windows(100, 80, 1, 1)
        self.assertEqual(wins, [(0, 0, 0, 0, 100, 80)])

    def test_windows_tile_exactly_with_no_gaps_or_overlap(self):
        w, h, rows, cols = 1000, 700, 3, 4
        wins = core.tile_windows(w, h, rows, cols)
        self.assertEqual(len(wins), rows * cols)
        covered = 0
        seen = set()
        for r, c, x, y, xs, ys in wins:
            self.assertGreater(xs, 0)
            self.assertGreater(ys, 0)
            self.assertLessEqual(x + xs, w)
            self.assertLessEqual(y + ys, h)
            seen.add((r, c))
            covered += xs * ys
        self.assertEqual(covered, w * h, "windows must tile the raster")
        self.assertEqual(len(seen), rows * cols, "no duplicate cells")

    def test_remainder_goes_to_the_last_row_and_column(self):
        # 10 wide over 3 columns: 3, 3, 4
        wins = core.tile_windows(10, 10, 1, 3)
        widths = [w[4] for w in wins]
        self.assertEqual(widths, [3, 3, 4])

    def test_awkward_sizes_still_cover(self):
        for w, h, rows, cols in ((7, 5, 2, 3), (1, 1, 1, 1),
                                 (9177, 10224, 4, 3)):
            wins = core.tile_windows(w, h, rows, cols)
            self.assertEqual(sum(x[4] * x[5] for x in wins), w * h,
                             (w, h, rows, cols))

    def test_degenerate_inputs_refused(self):
        with self.assertRaises(ValueError):
            core.tile_windows(100, 100, 0, 1)
        with self.assertRaises(ValueError):
            core.tile_windows(0, 100, 1, 1)
        with self.assertRaises(ValueError):
            core.tile_windows(10, 10, 20, 20)  # finer than the pixels


class TestTileGrid(unittest.TestCase):

    def test_small_raster_is_not_tiled(self):
        self.assertEqual(
            core.tile_grid(info(width=800, height=600, bands=3)), (1, 1))

    def test_tiling_can_be_switched_off(self):
        self.assertEqual(core.tile_grid(info(), enabled=False), (1, 1))

    def test_big_ortho_is_split(self):
        rows, cols = core.tile_grid(info())
        self.assertGreaterEqual(rows * cols, 1)
        self.assertTrue(rows >= 1 and cols >= 1)

    def test_a_smaller_tile_budget_makes_more_tiles(self):
        few = core.tile_grid(info(), tile_mb=100.0)
        many = core.tile_grid(info(), tile_mb=10.0)
        self.assertGreater(many[0] * many[1], few[0] * few[1])

    def test_grid_is_square_ish_not_a_strip(self):
        rows, cols = core.tile_grid(info(width=20000, height=20000,
                                         bands=3), tile_mb=10.0)
        self.assertLessEqual(max(rows, cols) / float(min(rows, cols)), 2.0)

    def test_never_finer_than_the_pixels(self):
        rows, cols = core.tile_grid(info(width=4, height=4, bands=3),
                                    tile_mb=0.000001)
        self.assertLessEqual(rows, 4)
        self.assertLessEqual(cols, 4)


class TestTileNaming(unittest.TestCase):

    def test_single_tile_keeps_the_plain_stem(self):
        self.assertEqual(core.tile_name("ortho_qfield", 0, 0, 1, 1),
                         "ortho_qfield")

    def test_zero_padded_so_name_order_is_grid_order(self):
        names = [core.tile_name("o", r, c, 12, 3)
                 for r in range(12) for c in range(3)]
        self.assertEqual(names[0], "o_r01c1")
        self.assertEqual(names[-1], "o_r12c3")
        self.assertEqual(names, sorted(names),
                         "sorted order must equal grid order")

    def test_padding_widens_with_the_grid(self):
        self.assertEqual(core.tile_name("o", 0, 0, 9, 9), "o_r1c1")
        self.assertEqual(core.tile_name("o", 0, 0, 10, 10), "o_r01c01")
        self.assertEqual(core.tile_name("o", 0, 0, 100, 100),
                         "o_r001c001")

    def test_output_stem_and_group_name(self):
        src = os.path.join("x", "260606_FF_Pit_ortho.tif")
        self.assertEqual(core.output_stem(src), "260606_FF_Pit_ortho_qfield")
        self.assertEqual(core.group_name(src, 1), "260606_FF_Pit_ortho")
        self.assertEqual(core.group_name(src, 12),
                         "260606_FF_Pit_ortho (12 tiles)")


class TestProfiles(unittest.TestCase):

    def test_every_ordered_profile_exists_and_is_described(self):
        self.assertEqual(set(core.PROFILE_ORDER), set(core.PROFILES))
        for name in core.PROFILE_ORDER:
            self.assertTrue(core.profile_label(name))
            self.assertTrue(core.profile_note(name).strip(), name)

    def test_default_is_jpeg_keeping_alpha(self):
        self.assertEqual(core.DEFAULT_PROFILE, 'cog_jpeg_alpha')
        driver, opts = core.creation_options('cog_jpeg_alpha', 4)
        self.assertEqual(driver, 'COG')
        self.assertIn('COMPRESS=JPEG', opts)
        self.assertIn('ADD_ALPHA=YES', opts)
        self.assertIsNone(core.bands_to_keep('cog_jpeg_alpha', 4))

    def test_dropping_alpha_writes_three_bands_and_no_add_alpha(self):
        driver, opts = core.creation_options('cog_jpeg', 4)
        self.assertNotIn('ADD_ALPHA=YES', opts)
        self.assertEqual(core.bands_to_keep('cog_jpeg', 4), [1, 2, 3])

    def test_three_band_source_never_gets_add_alpha(self):
        _driver, opts = core.creation_options('cog_jpeg_alpha', 3)
        self.assertNotIn('ADD_ALPHA=YES', opts)
        self.assertIsNone(core.bands_to_keep('cog_jpeg_alpha', 3))

    def test_lossless_profiles_keep_every_band(self):
        for name in ('cog_deflate', 'tiff_lzw'):
            self.assertIsNone(core.bands_to_keep(name, 4), name)

    def test_plain_tiff_profile_uses_the_gtiff_driver(self):
        driver, opts = core.creation_options('tiff_lzw', 3)
        self.assertEqual(driver, 'GTiff')
        self.assertIn('TILED=YES', opts)

    def test_common_options_on_every_profile(self):
        for name in core.PROFILE_ORDER:
            _driver, opts = core.creation_options(name, 3)
            self.assertIn('BIGTIFF=IF_SAFER', opts, name)
            self.assertIn('NUM_THREADS=ALL_CPUS', opts, name)

    def test_unknown_profile_falls_back_rather_than_raising(self):
        driver, opts = core.creation_options('nonsense', 3)
        self.assertEqual(driver, 'COG')
        self.assertTrue(opts)


class TestEstimate(unittest.TestCase):

    def test_lossy_beats_lossless(self):
        jpeg = core.estimate_output_bytes(info(), 'cog_jpeg_alpha')
        deflate = core.estimate_output_bytes(info(), 'cog_deflate')
        self.assertLess(jpeg, deflate)

    def test_a_big_ortho_shrinks_a_lot(self):
        est = core.estimate_output_bytes(info(), 'cog_jpeg_alpha')
        self.assertLess(est, info()['bytes'])

    def test_human_mb(self):
        self.assertEqual(core.human_mb(211_000_000), "211 MB")
        self.assertEqual(core.human_mb(0), "0 MB")
        self.assertEqual(core.human_mb(None), "0 MB")


if __name__ == '__main__':
    unittest.main()
