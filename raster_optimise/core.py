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

# Tiles this big are comfortable on QField (measured in the field). Only
# sources whose optimised output would exceed it get split at all.
DEFAULT_TILE_MB = 100.0

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
    for suffix in ('.ovr', '.aux.xml', '.tfw', '.prj', '.msk'):
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


def estimate_output_bytes(info, profile=DEFAULT_PROFILE):
    """Roughly how big the optimised copy will be. Preview only.

    Works from the UNCOMPRESSED size and a per-codec ratio, rather than
    from the source file size, so it is right whether the input arrived
    compressed or raw.
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
    pixels = (info.get('width') or 0) * (info.get('height') or 0)
    uncompressed = pixels * bands * sample
    return int(uncompressed * _COMPRESSION_RATIO[key] * 1.33)  # +overviews


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


def default_output_dir(src_path):
    return os.path.dirname(os.path.abspath(src_path)) or os.getcwd()


def output_stem(src_path):
    stem = os.path.splitext(os.path.basename(src_path))[0]
    return stem + "_qfield"


def group_name(src_path, tile_count):
    stem = os.path.splitext(os.path.basename(src_path))[0]
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


def optimise_raster(src_path, out_dir=None, profile=DEFAULT_PROFILE,
                    tile_mb=DEFAULT_TILE_MB, tiling=True,
                    progress_cb=None):
    """Write an optimised (and possibly tiled) copy of src_path.

    Pure file work — safe on the task pool. Returns a result dict for the
    dialog: outputs, grid shape, sizes and the source info.
    """
    from osgeo import gdal
    gdal.UseExceptions()

    if progress_cb:
        progress_cb(1, "Reading " + os.path.basename(src_path))
    info = raster_info(src_path)
    out_dir = out_dir or default_output_dir(src_path)
    if not os.path.isdir(out_dir):
        raise ValueError("Output folder does not exist: " + out_dir)

    rows, cols = tile_grid(info, profile, tile_mb, tiling)
    windows = tile_windows(info['width'], info['height'], rows, cols)
    driver, options = creation_options(profile, info['bands'])
    keep_bands = bands_to_keep(profile, info['bands'])
    stem = output_stem(src_path)

    src = gdal.Open(src_path, gdal.GA_ReadOnly)
    if src is None:
        raise ValueError("Could not open raster: " + src_path)
    outputs = []
    try:
        span = 94.0 / max(1, len(windows))
        for index, (r, c, xoff, yoff, xsize, ysize) in enumerate(windows):
            name = tile_name(stem, r, c, rows, cols)
            out_path = os.path.join(out_dir, name + ".tif")
            base = 3.0 + span * index
            label = ("Writing {0}".format(name) if len(windows) == 1
                     else "Writing tile {0} of {1}".format(
                         index + 1, len(windows)))
            callback, state = _progress_bridge(progress_cb, base, span,
                                               label)
            kwargs = dict(format=driver, creationOptions=options,
                          callback=callback,
                          metadataOptions=_stamp_options(
                              src_path, r, c, rows, cols))
            if keep_bands:
                kwargs['bandList'] = keep_bands
            if len(windows) > 1:
                kwargs['srcWin'] = [xoff, yoff, xsize, ysize]
            gdal.Translate(out_path, src, **kwargs)
            _raise_if_cancelled(state)

            if driver != 'COG':
                _build_overviews(out_path, progress_cb, base, span)
            outputs.append({
                'path': out_path,
                'name': name,
                'row': r,
                'col': c,
                'bytes': _source_bytes(out_path),
            })
    finally:
        src = None

    if progress_cb:
        progress_cb(100, "Done")

    total_out = sum(o['bytes'] for o in outputs)
    return {
        'source': src_path,
        'source_info': info,
        'profile': profile,
        'rows': rows,
        'cols': cols,
        'outputs': outputs,
        'out_dir': out_dir,
        'source_bytes': info['bytes'],
        'output_bytes': total_out,
        'group_name': group_name(src_path, len(outputs)),
    }


def _stamp_options(src_path, row, col, rows, cols):
    """Provenance metadata, applied AT CREATION.

    It cannot be added afterwards: reopening a COG for update destroys
    the very layout that makes it a COG, and GDAL refuses outright
    without IGNORE_COG_LAYOUT_BREAK.
    """
    opts = ["{0}={1}".format(META_SOURCE, os.path.basename(src_path))]
    if rows > 1 or cols > 1:
        opts.append("{0}=r{1}c{2}".format(META_TILE, row + 1, col + 1))
        opts.append("{0}={1}x{2}".format(META_GRID, rows, cols))
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
        ds.BuildOverviews("AVERAGE", OVERVIEW_LEVELS, callback=callback)
        _raise_if_cancelled(state)
    finally:
        ds = None
