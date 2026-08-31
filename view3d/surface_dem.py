"""
Pit Surface to DEM — rasterize a triangulated mining surface to GeoTIFF.

Surpac .dtm and DXF 3DFACE pit shells are already fully parsed into
ir.Surface(vertices, triangles) by the mining importer's pure readers;
the vector import then flattens them to 2D outlines. This module taps the
mesh instead: plane-interpolated Z per pixel -> a DEM that can be the
project terrain, so mapping drapes onto bench faces in the desktop 3D
view and in QField 4.1+.

The math half (suggest_cell_size / rasterize_surfaces) is numpy-only and
runs headless for tests; the GDAL half writes bytes via WriteRaster —
never gdal_array/WriteArray, which is compiled against numpy 1.x in some
OSGeo4W installs and explodes under numpy 2 (same rule as contours/core).

Overlap semantics: triangles are painted in order and later surfaces win
(painter's order). Pit shells are heightfields in practice; a per-pixel
z-max option is deliberately deferred until a real surface needs it.
"""

import math
import os
import statistics

import numpy as np

NODATA = -9999.0
MAX_PIXELS = 60_000_000  # ~240 MB float32; past this, ask for a bigger cell
_DEGENERATE_EPS = 1e-12
_EDGE_SAMPLE_CAP = 30_000

METADATA_ROLE_KEY = "LGS_DEM_ROLE"
METADATA_ROLE_PIT = "pit"


def default_output_path(source_path):
    stem, _ext = os.path.splitext(source_path)
    return stem + "_dem.tif"


# ------------------------------------------------------------- pure math

def suggest_cell_size(surfaces):
    """Half the median 2D edge length, clamped to [0.1, 10] m."""
    lengths = []
    for surface in surfaces:
        vertices = surface.vertices
        for tri in surface.triangles:
            for a, b in ((0, 1), (1, 2), (2, 0)):
                va, vb = vertices[tri[a]], vertices[tri[b]]
                lengths.append(math.hypot(vb[0] - va[0], vb[1] - va[1]))
                if len(lengths) >= _EDGE_SAMPLE_CAP:
                    break
            if len(lengths) >= _EDGE_SAMPLE_CAP:
                break
        if len(lengths) >= _EDGE_SAMPLE_CAP:
            break
    if not lengths:
        return 1.0
    return min(10.0, max(0.1, statistics.median(lengths) / 2.0))


def rasterize_surfaces(surfaces, cell_size, nodata=NODATA,
                       progress_cb=None):
    """Rasterize ir.Surface meshes onto one grid.

    Returns (grid, geotransform, stats): grid is a float32 (rows, cols)
    array (row 0 = north), geotransform the GDAL 6-tuple, stats a dict
    with triangle counts. Raises ValueError for empty input or a grid
    over MAX_PIXELS.
    """
    cell = float(cell_size)
    if cell <= 0:
        raise ValueError("Cell size must be positive")
    xs, ys = [], []
    total_triangles = 0
    for surface in surfaces:
        total_triangles += len(surface.triangles)
        for x, y, _z in surface.vertices:
            xs.append(x)
            ys.append(y)
    if not xs or not total_triangles:
        raise ValueError("No triangulated surface found in the source")
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    cols = max(1, int(math.ceil((xmax - xmin) / cell)) + 1)
    rows = max(1, int(math.ceil((ymax - ymin) / cell)) + 1)
    if cols * rows > MAX_PIXELS:
        raise ValueError(
            "Grid would be {0} x {1} pixels at {2:g} m — increase the "
            "cell size".format(cols, rows, cell))
    geotransform = (xmin, cell, 0.0, ymax, 0.0, -cell)

    grid = np.full((rows, cols), nodata, dtype=np.float32)
    # Pixel-center coordinates per axis, precomputed once.
    px_x = xmin + (np.arange(cols) + 0.5) * cell
    px_y = ymax - (np.arange(rows) + 0.5) * cell

    done = 0
    degenerate = 0
    for surface in surfaces:
        vertices = surface.vertices
        for tri in surface.triangles:
            (x1, y1, z1) = vertices[tri[0]]
            (x2, y2, z2) = vertices[tri[1]]
            (x3, y3, z3) = vertices[tri[2]]
            denom = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
            if abs(denom) < _DEGENERATE_EPS:
                degenerate += 1
                done += 1
                continue
            c0 = max(0, int((min(x1, x2, x3) - xmin) / cell))
            c1 = min(cols - 1, int((max(x1, x2, x3) - xmin) / cell) + 1)
            r0 = max(0, int((ymax - max(y1, y2, y3)) / cell))
            r1 = min(rows - 1, int((ymax - min(y1, y2, y3)) / cell) + 1)
            if c1 < c0 or r1 < r0:
                done += 1
                continue
            gx = px_x[c0:c1 + 1][np.newaxis, :]
            gy = px_y[r0:r1 + 1][:, np.newaxis]
            w1 = ((y2 - y3) * (gx - x3) + (x3 - x2) * (gy - y3)) / denom
            w2 = ((y3 - y1) * (gx - x3) + (x1 - x3) * (gy - y3)) / denom
            w3 = 1.0 - w1 - w2
            inside = (w1 >= -1e-9) & (w2 >= -1e-9) & (w3 >= -1e-9)
            if inside.any():
                z = w1 * z1 + w2 * z2 + w3 * z3
                window = grid[r0:r1 + 1, c0:c1 + 1]
                window[inside] = z[inside].astype(np.float32)
            done += 1
            if progress_cb and done % 2000 == 0:
                progress_cb(int(90 * done / total_triangles),
                            "Rasterizing triangles ({0}/{1})".format(
                                done, total_triangles))

    stats = {
        'triangles': total_triangles,
        'degenerate': degenerate,
        'rows': rows,
        'cols': cols,
        'cell_size': cell,
        'filled': int((grid != nodata).sum()),
    }
    return grid, geotransform, stats


# ------------------------------------------------------------ file layer

def read_surfaces(source_path):
    """Parse the source standalone through the mining importer's pure
    readers; returns (surfaces, warnings). Nothing in mining_import is
    modified — readers never flatten, only build.build_outlines does."""
    try:
        from ..mining_import import registry
    except ImportError:
        from mining_import import registry
    formats = registry.formats_for_path(source_path)
    if not formats:
        raise ValueError(
            "Unsupported file type: " + os.path.basename(source_path))
    fmt = formats[0]
    reader = registry.reader_for(fmt)
    companions = _find_companions(source_path, fmt)
    parsed = reader(source_path, companions=companions)
    return list(parsed.surfaces), list(parsed.warnings)


def _find_companions(source_path, fmt):
    """{'.dtm': path} for same-stem companions, as scan.discover() builds
    it — the shape the readers expect. Case-insensitive."""
    stem, _ext = os.path.splitext(source_path)
    folder = os.path.dirname(source_path) or "."
    wanted = {ext.lower() for ext in fmt.companion_exts}
    if not wanted:
        return {}
    found = {}
    try:
        base = os.path.basename(stem).lower()
        for name in os.listdir(folder):
            root, ext = os.path.splitext(name)
            ext = ext.lower()
            if root.lower() == base and ext in wanted:
                found[ext] = os.path.join(folder, name)
    except OSError:
        pass
    return found


def write_geotiff(out_path, grid, geotransform, crs_wkt="",
                  nodata=NODATA):
    """Write the grid as a tagged, compressed GeoTIFF (bytes write)."""
    from osgeo import gdal
    gdal.UseExceptions()
    rows, cols = grid.shape
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(out_path, cols, rows, 1, gdal.GDT_Float32,
                       options=["COMPRESS=LZW", "TILED=YES"])
    ds.SetGeoTransform(geotransform)
    if crs_wkt:
        ds.SetProjection(crs_wkt)
    ds.SetMetadataItem(METADATA_ROLE_KEY, METADATA_ROLE_PIT)
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    band.WriteRaster(0, 0, cols, rows,
                     grid.astype(np.float32).tobytes(),
                     buf_type=gdal.GDT_Float32)
    band.FlushCache()
    ds.FlushCache()
    ds = None


def rasterize_to_geotiff(source_path, out_path, cell_size=None,
                         crs_wkt="", progress_cb=None):
    """Full pipeline for the task runner: parse -> rasterize -> write.

    Pure compute plus file IO only — safe on the task pool. Returns a
    result dict for the dialog.
    """
    if progress_cb:
        progress_cb(1, "Reading " + os.path.basename(source_path))
    surfaces, warnings = read_surfaces(source_path)
    if not surfaces:
        raise ValueError(
            "No triangulated surface in " + os.path.basename(source_path)
            + " — pit strings alone cannot make a DEM (a .dtm/.dxf "
            "surface is needed)")
    if cell_size is None:
        cell_size = suggest_cell_size(surfaces)
    grid, geotransform, stats = rasterize_surfaces(
        surfaces, cell_size, progress_cb=progress_cb)
    if progress_cb:
        progress_cb(95, "Writing GeoTIFF")
    write_geotiff(out_path, grid, geotransform, crs_wkt=crs_wkt)
    if progress_cb:
        progress_cb(100, "Done")
    stats['path'] = out_path
    stats['warnings'] = warnings
    return stats
