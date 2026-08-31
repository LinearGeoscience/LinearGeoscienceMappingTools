"""
Unit tests for view3d/surface_dem.py's math half (pure python + numpy).

Run from the plugin root:
    python -m unittest discover tests
"""

import importlib.util
import os
import unittest
from collections import namedtuple

# Load surface_dem.py directly — importing the view3d package would pull
# in qgis. The gdal-touching functions are not exercised here (see
# tests/test_surface_dem_qgis.py).
_path = os.path.join(os.path.dirname(__file__), '..', 'view3d',
                     'surface_dem.py')
_spec = importlib.util.spec_from_file_location('view3d_surface_dem', _path)
surface_dem = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(surface_dem)

# Mirrors mining_import.ir.Surface without importing it.
Surface = namedtuple('Surface', 'vertices triangles attrs',
                     defaults=({},))


def plane_z(x, y):
    """The synthetic plane z = 2x + 3y + 5 used across these tests."""
    return 2.0 * x + 3.0 * y + 5.0


def square_surface(size=10.0):
    """Two triangles tiling [0, size]^2, vertices on the test plane."""
    corners = [(0.0, 0.0), (size, 0.0), (size, size), (0.0, size)]
    vertices = [(x, y, plane_z(x, y)) for x, y in corners]
    return Surface(vertices=vertices, triangles=[(0, 1, 2), (0, 2, 3)])


class TestRasterizeSurfaces(unittest.TestCase):
    def test_plane_interpolated_exactly(self):
        grid, gt, stats = surface_dem.rasterize_surfaces(
            [square_surface()], cell_size=1.0)
        self.assertEqual(stats['triangles'], 2)
        self.assertEqual(stats['degenerate'], 0)
        x0, cell, _r0, y0, _r1, neg_cell = gt
        self.assertEqual((x0, y0), (0.0, 10.0))
        self.assertEqual(cell, 1.0)
        self.assertEqual(neg_cell, -1.0)
        rows, cols = grid.shape
        for r in (0, rows // 2, rows - 1):
            for c in (0, cols // 2, cols - 1):
                px = x0 + (c + 0.5) * cell
                py = y0 - (r + 0.5) * cell
                if 0 <= px <= 10 and 0 <= py <= 10:
                    self.assertAlmostEqual(
                        float(grid[r, c]), plane_z(px, py), places=3,
                        msg=f"pixel ({r},{c}) center ({px},{py})")

    def test_nodata_outside_triangulation(self):
        # One triangle only: the far corner of its bbox is outside.
        vertices = [(0.0, 0.0, 1.0), (10.0, 0.0, 1.0), (0.0, 10.0, 1.0)]
        surface = Surface(vertices=vertices, triangles=[(0, 1, 2)])
        grid, _gt, stats = surface_dem.rasterize_surfaces(
            [surface], cell_size=1.0)
        # Pixel centered near (9.5, 9.5) is well outside the triangle.
        self.assertEqual(float(grid[0, -1]), surface_dem.NODATA)
        self.assertGreater(stats['filled'], 0)
        self.assertLess(stats['filled'], grid.size)

    def test_degenerate_triangle_skipped(self):
        vertices = [(0.0, 0.0, 1.0), (5.0, 5.0, 2.0), (10.0, 10.0, 3.0)]
        surface = Surface(vertices=vertices, triangles=[(0, 1, 2)])
        grid, _gt, stats = surface_dem.rasterize_surfaces(
            [surface], cell_size=1.0)
        self.assertEqual(stats['degenerate'], 1)
        self.assertEqual(stats['filled'], 0)

    def test_later_surface_wins(self):
        low = square_surface()
        high_vertices = [(x, y, 100.0) for x, y, _z in low.vertices]
        high = Surface(vertices=high_vertices, triangles=low.triangles)
        grid, _gt, _stats = surface_dem.rasterize_surfaces(
            [low, high], cell_size=1.0)
        self.assertAlmostEqual(float(grid[5, 5]), 100.0, places=3)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            surface_dem.rasterize_surfaces([], cell_size=1.0)
        with self.assertRaises(ValueError):
            surface_dem.rasterize_surfaces(
                [Surface(vertices=[], triangles=[])], cell_size=1.0)

    def test_grid_cap(self):
        surface = square_surface(size=100000.0)
        with self.assertRaises(ValueError):
            surface_dem.rasterize_surfaces([surface], cell_size=0.1)


class TestSuggestCellSize(unittest.TestCase):
    def test_half_median_edge(self):
        # Edges of the 10 m square triangles: 10, 10, ~14.14 (x2 shared).
        value = surface_dem.suggest_cell_size([square_surface()])
        self.assertEqual(value, 5.0)

    def test_clamped_low(self):
        surface = square_surface(size=0.1)
        self.assertEqual(surface_dem.suggest_cell_size([surface]), 0.1)

    def test_clamped_high(self):
        surface = square_surface(size=1000.0)
        self.assertEqual(surface_dem.suggest_cell_size([surface]), 10.0)

    def test_empty_defaults(self):
        self.assertEqual(surface_dem.suggest_cell_size([]), 1.0)


class TestDefaultOutputPath(unittest.TestCase):
    def test_beside_source(self):
        self.assertEqual(
            surface_dem.default_output_path(os.path.join('x', 'pit.str')),
            os.path.join('x', 'pit_dem.tif'))


if __name__ == '__main__':
    unittest.main()
