"""
Repack a large raster so it performs in the field, at full resolution.

A drone ortho out of the processing software is typically hundreds of MB
with NO overview pyramids, which forces a full-resolution decode at every
zoom — the single biggest cause of a sluggish map on a tablet. Two things
fix that, and neither reduces resolution:

  * overviews, always, on every output; and
  * splitting a very large image into a grid of same-resolution tiles,
    which QField handles far better than one enormous file.

Raster I/O follows the house rule set in contours/core.py: `from osgeo
import gdal` INSIDE the functions (so this module imports headless), and
never `gdal_array`/`ReadAsArray` — it is compiled against numpy 1.x in
some OSGeo4W installs and raises ImportError under numpy 2. Nothing here
reads pixels into Python anyway; GDAL does the copying.

Every long GDAL call takes a progress callback that returns 0 to abort,
so a 200 MB conversion stays cancellable (contours/core.py:339).
"""

import math
import os

# Metadata stamped on outputs so a stray tile can be traced home.
META_SOURCE = "LGS_RASTER_SOURCE"
META_TILE = "LGS_TILE_INDEX"
META_GRID = "LGS_TILE_GRID"
META_ROLE = "LGS_ROLE"

# Tiles this big are comfortable on QField (measured in the field). Only
# sources whose optimised output would exceed it get split at all.
DEFAULT_TILE_MB = 100.0

# The whole-extent context copy written alongside AOI tiles aims for about
# this much on disk; its pixel size is derived from the target, not chosen.
CONTEXT_TARGET_MB = 500.0

# Fraction of the UNCOMPRESSED size each codec typically lands at on
# aerial imagery. Used only to size the tile grid and preview the result.
# Estimating per band would badly overstate the lossy codecs, which
# compress across bands (JPEG works in YCbCr, not three grey planes) —
# measured against the Fingals ortho, a per-band model was ~9x too high.
_COMPRESSION_RATIO = {
    'jpeg': 0.07,   # measured 0.074 on the Fingals ortho, overviews aside
    'webp': 0.05,
    'deflate': 0.55,
    'lzw': 0.60,
}

# name -> (label, driver, creation options, keeps_alpha, note)
PROFILES = {
    'cog_jpeg_alpha': (
        "COG + JPEG, keep transparency",
        'COG',
        ['COMPRESS=JPEG', 'QUALITY=85', 'OVERVIEWS=AUTO'],
        True,
        "Best all-round. Big saving, and the clear margin around the "
        "survey stays clear.",
    ),
    'cog_jpeg': (
        "COG + JPEG, drop transparency",
        'COG',
        ['COMPRESS=JPEG', 'QUALITY=85', 'OVERVIEWS=AUTO'],
        False,
        "Smallest file. Anything transparent turns black — only use it "
        "when the image edge does not matter.",
    ),
    'cog_webp': (
        "COG + WEBP",
        'COG',
        ['COMPRESS=WEBP', 'QUALITY=85', 'OVERVIEWS=AUTO'],
        True,
        "Smaller than JPEG at the same visual quality.",
    ),
    'cog_deflate': (
        "COG + DEFLATE (lossless)",
        'COG',
        ['COMPRESS=DEFLATE', 'PREDICTOR=2', 'OVERVIEWS=AUTO'],
        True,
        "No quality loss at all, so it stays evidential — but only about "
        "half to a quarter the size, not a tenth.",
    ),
    'tiff_lzw': (
        "Plain GeoTIFF + overviews (lossless)",
        'GTiff',
        ['COMPRESS=LZW', 'PREDICTOR=2', 'TILED=YES', 'BLOCKXSIZE=256',
         'BLOCKYSIZE=256'],
        True,
        "For anything that must stay an ordinary GeoTIFF. Overviews are "
        "still added.",
    ),
}
DEFAULT_PROFILE = 'cog_jpeg_alpha'
PROFILE_ORDER = ['cog_jpeg_alpha', 'cog_jpeg', 'cog_webp', 'cog_deflate',
                 'tiff_lzw']

COMMON_OPTIONS = ['BIGTIFF=IF_SAFER', 'NUM_THREADS=ALL_CPUS']
OVERVIEW_LEVELS = [2, 4, 8, 16, 32]


def profile_label(name):
    return PROFILES.get(name, PROFILES[DEFAULT_PROFILE])[0]


def profile_note(name):
    return PROFILES.get(name, PROFILES[DEFAULT_PROFILE])[4]


def creation_options(name, band_count):
    """GDAL creation options for a profile, given the source band count.

    JPEG cannot carry a 4th band, so a 4-band RGBA source keeps its
    transparency through ADD_ALPHA, which writes 3 colour bands plus a
    per-dataset internal mask. Verified on the real drone ortho: the
    output reports RasterCount 3 with GMF_PER_DATASET, and the mask
    matches the source alpha (0 in the clear margin, 255 over the pit).
    So "bands: 3" on such an output is correct, not a loss.
    """
    _label, driver, opts, keeps_alpha, _note = PROFILES.get(
        name, PROFILES[DEFAULT_PROFILE])
    opts = list(opts) + list(COMMON_OPTIONS)
    if driver == 'COG':
        opts.append('BLOCKSIZE=256')
        if keeps_alpha and band_count and band_count >= 4:
            opts.append('ADD_ALPHA=YES')
    return driver, opts


def bands_to_keep(name, band_count):
    """Which source bands to write, or None for all of them."""
    _label, _driver, _opts, keeps_alpha, _note = PROFILES.get(
        name, PROFILES[DEFAULT_PROFILE])
    if not keeps_alpha and band_count and band_count >= 4:
        return [1, 2, 3]
    return None


# ------------------------------------------------------------ inspection

def raster_info(path):
    """Size, shape and — crucially — overview count of a raster.

    Sibling of contours.core.raster_stats, but about the things that
    decide field performance rather than elevation.
    """
    from osgeo import gdal
    gdal.UseExceptions()

    ds = gdal.Open(path, gdal.GA_ReadOnly)
    if ds is None:
        raise ValueError("Could not open raster: " + str(path))
    try:
        band = ds.GetRasterBand(1)
        structure = ds.GetMetadata('IMAGE_STRUCTURE') or {}
        info = {
            'path': path,
            'width': ds.RasterXSize,
            'height': ds.RasterYSize,
            'bands': ds.RasterCount,
            'dtype': gdal.GetDataTypeName(band.DataType),
            'overviews': band.GetOverviewCount(),
            'compression': structure.get('COMPRESSION', 'NONE'),
            'interleave': structure.get('INTERLEAVE', ''),
            'crs_wkt': ds.GetProjection() or '',
            'geotransform': ds.GetGeoTransform(),
            'block': band.GetBlockSize(),
        }
    finally:
        ds = None
    info['bytes'] = _source_bytes(path)
    return info


def _source_bytes(path):
    total = 0
    try:
        total = os.path.getsize(path)
    except OSError:
        return 0
    # A .tif rarely travels alone.
    stem, _ext = os.path.splitext(path)
    for suffix in ('.ovr', '.aux.xml', '.tfw', '.prj', '.msk', '.ers',
                   '.eww'):
        for candidate in (path + suffix, stem + suffix):
            try:
                if os.path.isfile(candidate):
                    total += os.path.getsize(candidate)
            except OSError:
                pass
    return total


def human_mb(num_bytes):
    """Bytes as MB, matching the mining importer's phrasing."""
    return "{0:.0f} MB".format((num_bytes or 0) / 1e6)


# ------------------------------------------------------- tiling geometry

_BYTES_PER_SAMPLE = {
    'Byte': 1, 'Int8': 1, 'UInt16': 2, 'Int16': 2,
    'UInt32': 4, 'Int32': 4, 'Float32': 4, 'Float64': 8,
}


def _estimate_bytes_for_pixels(pixels, info, profile=DEFAULT_PROFILE):
    """Estimated on-disk bytes for `pixels` source pixels under a profile.

    Works from the UNCOMPRESSED size and a per-codec ratio, rather than
    from the source file size, so it is right whether the input arrived
    compressed or raw — which matters most for wavelet formats like ECW,
    whose on-disk size says nothing about the pixel count.
    """
    _label, _driver, opts, keeps_alpha, _note = PROFILES.get(
        profile, PROFILES[DEFAULT_PROFILE])
    key = 'lzw'
    for candidate in ('jpeg', 'webp', 'deflate', 'lzw'):
        if any(('COMPRESS=' + candidate.upper()) == o for o in opts):
            key = candidate
            break
    bands = info.get('bands') or 1
    if not keeps_alpha and bands >= 4:
        bands = 3
    sample = _BYTES_PER_SAMPLE.get(info.get('dtype', 'Byte'), 1)
    uncompressed = pixels * bands * sample
    return int(uncompressed * _COMPRESSION_RATIO[key] * 1.33)  # +overviews


def estimate_output_bytes(info, profile=DEFAULT_PROFILE):
    """Roughly how big the optimised copy will be. Preview only."""
    pixels = (info.get('width') or 0) * (info.get('height') or 0)
    return _estimate_bytes_for_pixels(pixels, info, profile)


def tile_grid(info, profile=DEFAULT_PROFILE, tile_mb=DEFAULT_TILE_MB,
              enabled=True):
    """(rows, cols) for the output grid; (1, 1) means a single file.

    Sized so each tile lands near `tile_mb`. Square-ish tiles are chosen
    over a long strip so no single tile spans the whole image.
    """
    if not enabled or not tile_mb or tile_mb <= 0:
        return 1, 1
    estimated = estimate_output_bytes(info, profile)
    budget = tile_mb * 1e6
    if estimated <= budget:
        return 1, 1
    parts = int(math.ceil(estimated / budget))
    side = int(math.ceil(math.sqrt(parts)))
    rows = side
    cols = int(math.ceil(parts / float(rows)))
    # Never cut more finely than the pixels allow.
    rows = max(1, min(rows, info.get('height') or 1))
    cols = max(1, min(cols, info.get('width') or 1))
    return rows, cols


def tile_windows(width, height, rows, cols):
    """[(row, col, xoff, yoff, xsize, ysize)] covering the raster exactly.

    Integer division leftovers go to the last row/column, so the windows
    tile the image with no gap and no overlap.
    """
    if rows < 1 or cols < 1:
        raise ValueError("Tile grid must be at least 1x1")
    if width < 1 or height < 1:
        raise ValueError("Raster has no pixels")
    base_w = width // cols
    base_h = height // rows
    if base_w < 1 or base_h < 1:
        raise ValueError("Too many tiles for a raster this size")
    windows = []
    for r in range(rows):
        yoff = r * base_h
        ysize = height - yoff if r == rows - 1 else base_h
        for c in range(cols):
            xoff = c * base_w
            xsize = width - xoff if c == cols - 1 else base_w
            windows.append((r, c, xoff, yoff, xsize, ysize))
    return windows


def tile_name(stem, row, col, rows, cols):
    """`stem_r01c02` — zero-padded so name order is grid order.

    A one-tile job keeps the plain stem: no misleading _r01c01.
    """
    if rows <= 1 and cols <= 1:
        return stem
    rw = len(str(rows))
    cw = len(str(cols))
    return "{0}_r{1:0{2}d}c{3:0{4}d}".format(stem, row + 1, rw, col + 1, cw)


# ------------------------------------------------------- AOI coverage
#
# The user draws one or more polygons on the map; only the tiles those
# polygons touch are written at full resolution, and one downsampled
# copy of the WHOLE extent is added underneath for zoomed-out context.
# Polygons arrive as plain ring coordinate lists [[(x, y), ...], ...]
# in the raster's own CRS — the dialog does the CRS work, this module
# stays importable without QGIS.

def invert_geotransform(gt):
    """Inverse of a 6-element GDAL geotransform.

    Full 2x2 inverse, so rotated/sheared geotransforms work too — never
    assume north-up here.
    """
    det = gt[1] * gt[5] - gt[2] * gt[4]
    if det == 0:
        raise ValueError("Geotransform is not invertible")
    inv1 = gt[5] / det
    inv2 = -gt[2] / det
    inv4 = -gt[4] / det
    inv5 = gt[1] / det
    inv0 = -(inv1 * gt[0] + inv2 * gt[3])
    inv3 = -(inv4 * gt[0] + inv5 * gt[3])
    return (inv0, inv1, inv2, inv3, inv4, inv5)


def geo_to_pixel(gt_inv, x, y):
    """Map coordinates -> fractional (px, py) via an inverted geotransform."""
    return (gt_inv[0] + gt_inv[1] * x + gt_inv[2] * y,
            gt_inv[3] + gt_inv[4] * x + gt_inv[5] * y)


def _point_in_ring(x, y, ring):
    """Even-odd ray cast; the ring need not repeat its first point."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            if x < xi + (y - yi) * (xj - xi) / (yj - yi):
                inside = not inside
        j = i
    return inside


def _orient(ax, ay, bx, by, cx, cy):
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _on_segment(a, b, p):
    return (min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]))


def _segments_intersect(p1, p2, p3, p4):
    d1 = _orient(p3[0], p3[1], p4[0], p4[1], p1[0], p1[1])
    d2 = _orient(p3[0], p3[1], p4[0], p4[1], p2[0], p2[1])
    d3 = _orient(p1[0], p1[1], p2[0], p2[1], p3[0], p3[1])
    d4 = _orient(p1[0], p1[1], p2[0], p2[1], p4[0], p4[1])
    if (((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0))
            and ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0))):
        return True
    if d1 == 0 and _on_segment(p3, p4, p1):
        return True
    if d2 == 0 and _on_segment(p3, p4, p2):
        return True
    if d3 == 0 and _on_segment(p1, p2, p3):
        return True
    if d4 == 0 and _on_segment(p1, p2, p4):
        return True
    return False


def rect_intersects_ring(xmin, ymin, xmax, ymax, ring):
    """Does an axis-aligned rect touch a polygon ring at all?

    Three cases cover every overlap: a ring vertex inside the rect, a
    rect corner inside the ring (rect entirely within the polygon), or
    an edge of one crossing an edge of the other.
    """
    rx = [p[0] for p in ring]
    ry = [p[1] for p in ring]
    if max(rx) < xmin or min(rx) > xmax or max(ry) < ymin or min(ry) > ymax:
        return False
    for px, py in ring:
        if xmin <= px <= xmax and ymin <= py <= ymax:
            return True
    corners = ((xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax))
    for corner in corners:
        if _point_in_ring(corner[0], corner[1], ring):
            return True
    edges = tuple(zip(corners, corners[1:] + (corners[0],)))
    for i in range(len(ring)):
        a1 = ring[i]
        a2 = ring[(i + 1) % len(ring)]
        for e1, e2 in edges:
            if _segments_intersect(a1, a2, e1, e2):
                return True
    return False


def polygons_to_pixel(info, polygons):
    """Rings in the raster's CRS -> rings in fractional pixel coords.

    Once here, every tile test is an axis-aligned rectangle — any
    rotation in the geotransform has already been folded in.
    """
    gt_inv = invert_geotransform(info['geotransform'])
    rings = []
    for ring in polygons:
        if len(ring) < 3:
            continue
        rings.append([geo_to_pixel(gt_inv, x, y) for x, y in ring])
    if not rings:
        raise ValueError("No drawn areas to work from")
    return rings


def aoi_pixel_window(width, height, pixel_rings):
    """(xoff, yoff, xsize, ysize): union bbox of the rings, clipped."""
    xmin = min(min(p[0] for p in r) for r in pixel_rings)
    xmax = max(max(p[0] for p in r) for r in pixel_rings)
    ymin = min(min(p[1] for p in r) for r in pixel_rings)
    ymax = max(max(p[1] for p in r) for r in pixel_rings)
    xoff = int(math.floor(max(0.0, xmin)))
    yoff = int(math.floor(max(0.0, ymin)))
    xend = int(math.ceil(min(float(width), xmax)))
    yend = int(math.ceil(min(float(height), ymax)))
    if xend <= xoff or yend <= yoff:
        raise ValueError("Drawn areas do not overlap the raster")
    return xoff, yoff, xend - xoff, yend - yoff


def aoi_tile_plan(info, polygons, profile=DEFAULT_PROFILE,
                  tile_mb=DEFAULT_TILE_MB, tiling=True):
    """Windows covering the drawn areas at full resolution.

    The grid is sized from the AOI window's pixel count, not the whole
    image, then tiles that touch none of the polygons are dropped. Kept
    edge tiles stay full rectangles — no cutline masking — so the output
    overshoots the drawn shape by at most one ring of ~tile_mb tiles;
    simpler and more robust than warping through a cutline.

    Returns (windows, rows, cols) with windows in whole-image pixel
    coordinates, same shape as tile_windows() rows.
    """
    rings = polygons_to_pixel(info, polygons)
    xoff, yoff, xsize, ysize = aoi_pixel_window(
        info['width'], info['height'], rings)
    sub = dict(info)
    sub['width'] = xsize
    sub['height'] = ysize
    rows, cols = tile_grid(sub, profile, tile_mb, tiling)
    windows = []
    for r, c, wx, wy, ww, wh in tile_windows(xsize, ysize, rows, cols):
        gx = xoff + wx
        gy = yoff + wy
        if any(rect_intersects_ring(gx, gy, gx + ww, gy + wh, ring)
               for ring in rings):
            windows.append((r, c, gx, gy, ww, wh))
    if not windows:
        raise ValueError("Drawn areas do not overlap the raster")
    return windows, rows, cols


def context_shape(info, profile=DEFAULT_PROFILE,
                  target_mb=CONTEXT_TARGET_MB):
    """(out_w, out_h, factor) for the whole-extent context copy.

    The downsample factor is solved from the size target rather than
    chosen: bytes scale with pixel count, so sqrt(estimate / target)
    per axis lands the context near target_mb. A source already under
    the target keeps 1:1 (factor clamps at 1.0).
    """
    estimated = estimate_output_bytes(info, profile)
    target = float(target_mb or CONTEXT_TARGET_MB) * 1e6
    if target <= 0:
        target = CONTEXT_TARGET_MB * 1e6
    factor = max(1.0, math.sqrt(estimated / target))
    out_w = max(1, int(round((info.get('width') or 1) / factor)))
    out_h = max(1, int(round((info.get('height') or 1) / factor)))
    return out_w, out_h, factor


def estimate_aoi_output_bytes(info, polygons, profile=DEFAULT_PROFILE,
                              tile_mb=DEFAULT_TILE_MB, tiling=True,
                              context_target_mb=CONTEXT_TARGET_MB):
    """(windows, tile_bytes, context_bytes) for the dialog preview."""
    windows, _rows, _cols = aoi_tile_plan(info, polygons, profile,
                                          tile_mb, tiling)
    tile_bytes = sum(_estimate_bytes_for_pixels(w[4] * w[5], info, profile)
                     for w in windows)
    out_w, out_h, _factor = context_shape(info, profile, context_target_mb)
    context_bytes = _estimate_bytes_for_pixels(out_w * out_h, info, profile)
    return windows, tile_bytes, context_bytes


def context_name(stem):
    return stem + "_context"


def default_output_dir(src_path):
    return os.path.dirname(os.path.abspath(src_path)) or os.getcwd()


def output_stem(src_path):
    stem = os.path.splitext(os.path.basename(src_path))[0]
    return stem + "_qfield"


def group_name(src_path, tile_count, has_context=False):
    stem = os.path.splitext(os.path.basename(src_path))[0]
    if has_context:
        return "{0} ({1} tile{2} + context)".format(
            stem, tile_count, "" if tile_count == 1 else "s")
    if tile_count <= 1:
        return stem
    return "{0} ({1} tiles)".format(stem, tile_count)


# ------------------------------------------------------------- the work

def _progress_bridge(progress_cb, base, span, message):
    """A GDAL callback that reports progress and can abort the run."""
    try:
        from ..lgs_tasks import TaskCancelled
    except ImportError:
        from lgs_tasks import TaskCancelled

    state = {'cancelled': False}

    def callback(fraction, _msg, _data):
        if progress_cb is None:
            return 1
        try:
            progress_cb(base + span * float(fraction), message)
        except TaskCancelled:
            state['cancelled'] = True
            return 0  # tells GDAL to stop
        return 1

    return callback, state


def _raise_if_cancelled(state):
    if state.get('cancelled'):
        try:
            from ..lgs_tasks import TaskCancelled
        except ImportError:
            from lgs_tasks import TaskCancelled
        raise TaskCancelled()


def _run_cancellable(state, fn, partial_path=None):
    """Run a GDAL call whose callback may have aborted it.

    With gdal.UseExceptions() an aborted call raises RuntimeError("User
    terminated") BEFORE control returns here, so the cancel must win
    over that error — and the half-written file goes with it.
    """
    try:
        result = fn()
    except Exception:
        if state.get('cancelled'):
            _remove_quietly(partial_path)
            _raise_if_cancelled(state)
        raise
    if state.get('cancelled'):
        _remove_quietly(partial_path)
        _raise_if_cancelled(state)
    return result


def _remove_quietly(path):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def optimise_raster(src_path, out_dir=None, profile=DEFAULT_PROFILE,
                    tile_mb=DEFAULT_TILE_MB, tiling=True,
                    progress_cb=None, aoi_polygons=None,
                    context_target_mb=None):
    """Write an optimised (and possibly tiled) copy of src_path.

    Pure file work — safe on the task pool. Returns a result dict for the
    dialog: outputs, grid shape, sizes and the source info.

    With `aoi_polygons` (ring coordinate lists in the raster's CRS) only
    the full-resolution tiles those polygons touch are written, plus one
    downsampled whole-extent context copy sized near `context_target_mb`.
    The context item goes LAST in outputs so the dialog stacks it at the
    bottom of the group, under the full-res tiles.
    """
    from osgeo import gdal
    gdal.UseExceptions()

    if progress_cb:
        progress_cb(1, "Reading " + os.path.basename(src_path))
    info = raster_info(src_path)
    out_dir = out_dir or default_output_dir(src_path)
    if not os.path.isdir(out_dir):
        raise ValueError("Output folder does not exist: " + out_dir)

    aoi_mode = bool(aoi_polygons)
    context_shape_wh = None
    context_factor = None
    if aoi_mode:
        windows, rows, cols = aoi_tile_plan(info, aoi_polygons, profile,
                                            tile_mb, tiling)
        ctx_w, ctx_h, context_factor = context_shape(
            info, profile, context_target_mb or CONTEXT_TARGET_MB)
        context_shape_wh = (ctx_w, ctx_h)
    else:
        rows, cols = tile_grid(info, profile, tile_mb, tiling)
        windows = tile_windows(info['width'], info['height'], rows, cols)

    driver, options = creation_options(profile, info['bands'])
    keep_bands = bands_to_keep(profile, info['bands'])
    stem = output_stem(src_path)

    # Progress shares out by output pixels, so a run of many tiles plus
    # one small context copy still moves smoothly.
    weights = [float(w[4]) * w[5] for w in windows]
    if context_shape_wh:
        weights.append(float(context_shape_wh[0]) * context_shape_wh[1])
    total_weight = sum(weights) or 1.0

    src = gdal.Open(src_path, gdal.GA_ReadOnly)
    if src is None:
        raise ValueError("Could not open raster: " + src_path)
    outputs = []
    try:
        base = 3.0
        for index, (r, c, xoff, yoff, xsize, ysize) in enumerate(windows):
            span = 94.0 * weights[index] / total_weight
            name = tile_name(stem, r, c, rows, cols)
            out_path = os.path.join(out_dir, name + ".tif")
            label = ("Writing {0}".format(name) if len(windows) == 1
                     else "Writing tile {0} of {1}".format(
                         index + 1, len(windows)))
            callback, state = _progress_bridge(progress_cb, base, span,
                                               label)
            kwargs = dict(format=driver, creationOptions=options,
                          callback=callback,
                          metadataOptions=_stamp_options(
                              src_path, r, c, rows, cols,
                              role='aoi_tile' if aoi_mode else None))
            if keep_bands:
                kwargs['bandList'] = keep_bands
            if aoi_mode or len(windows) > 1:
                kwargs['srcWin'] = [xoff, yoff, xsize, ysize]
            _run_cancellable(
                state, lambda: gdal.Translate(out_path, src, **kwargs),
                partial_path=out_path)

            if driver != 'COG':
                _build_overviews(out_path, progress_cb, base, span)
            outputs.append({
                'path': out_path,
                'name': name,
                'row': r,
                'col': c,
                'bytes': _source_bytes(out_path),
            })
            base += span

        context = None
        if context_shape_wh:
            name = context_name(stem)
            out_path = os.path.join(out_dir, name + ".tif")
            span = 94.0 * weights[-1] / total_weight
            callback, state = _progress_bridge(progress_cb, base, span,
                                               "Writing context layer")
            kwargs = dict(format=driver, creationOptions=options,
                          width=context_shape_wh[0],
                          height=context_shape_wh[1],
                          resampleAlg='average',
                          callback=callback,
                          metadataOptions=_stamp_options(
                              src_path, 0, 0, 1, 1, role='context'))
            if keep_bands:
                kwargs['bandList'] = keep_bands
            _run_cancellable(
                state, lambda: gdal.Translate(out_path, src, **kwargs),
                partial_path=out_path)
            if driver != 'COG':
                _build_overviews(out_path, progress_cb, base, span)
            context = {
                'path': out_path,
                'name': name,
                'row': None,
                'col': None,
                'bytes': _source_bytes(out_path),
            }
            outputs.append(context)
    finally:
        src = None

    if progress_cb:
        progress_cb(100, "Done")

    tile_count = len(outputs) - (1 if context_shape_wh else 0)
    total_out = sum(o['bytes'] for o in outputs)
    return {
        'source': src_path,
        'source_info': info,
        'profile': profile,
        'mode': 'aoi' if aoi_mode else 'whole',
        'rows': rows,
        'cols': cols,
        'outputs': outputs,
        'context': context if aoi_mode else None,
        'context_factor': context_factor,
        'out_dir': out_dir,
        'source_bytes': info['bytes'],
        'output_bytes': total_out,
        'group_name': group_name(src_path, tile_count,
                                 has_context=aoi_mode),
    }


def _stamp_options(src_path, row, col, rows, cols, role=None):
    """Provenance metadata, applied AT CREATION.

    It cannot be added afterwards: reopening a COG for update destroys
    the very layout that makes it a COG, and GDAL refuses outright
    without IGNORE_COG_LAYOUT_BREAK.
    """
    opts = ["{0}={1}".format(META_SOURCE, os.path.basename(src_path))]
    if rows > 1 or cols > 1:
        opts.append("{0}=r{1}c{2}".format(META_TILE, row + 1, col + 1))
        opts.append("{0}={1}x{2}".format(META_GRID, rows, cols))
    if role:
        opts.append("{0}={1}".format(META_ROLE, role))
    return opts


def _build_overviews(path, progress_cb, base, span):
    """Pyramids for the non-COG profiles; COG builds its own."""
    from osgeo import gdal
    gdal.UseExceptions()
    ds = gdal.Open(path, gdal.GA_Update)
    if ds is None:
        return
    try:
        callback, state = _progress_bridge(progress_cb, base, span,
                                           "Building overviews")
        _run_cancellable(
            state, lambda: ds.BuildOverviews("AVERAGE", OVERVIEW_LEVELS,
                                             callback=callback))
    finally:
        ds = None
