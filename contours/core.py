"""Contour generation pipeline: DEM in, smooth contour GeoPackage out.

Pure compute — no iface/project access, so generate_contours() is safe to run
on a worker thread via lgs_tasks.run_in_task.

The smoothing happens in three places, in order of importance:
1. A nodata-aware Gaussian blur of the DEM at native resolution, so the
   contoured surface itself is smooth rather than pixel-stepped.
2. A cubic-spline upsample (gdal.Warp) so GDAL's marching squares lands its
   crossings on a smooth surface at several times the native density.
3. Douglas-Peucker anchor thinning followed by the MapCleaning Hermite spline
   on each contour line, ring-aware for closed loops.

osgeo.gdal_array is compiled against numpy 1.x in some OSGeo4W installs and
raises ImportError under numpy 2, so all raster I/O here goes through
ReadRaster()/WriteRaster() bytes rather than ReadAsArray()/WriteArray().
"""

import math
import os

import numpy as np

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsVectorFileWriter,
)
from qgis.PyQt.QtCore import QMetaType

try:
    from ..map_cleaning.core.spline_interp import (
        interpolate, interpolate_closed_ring)
except ImportError:  # headless tests import the package as top-level
    from map_cleaning.core.spline_interp import (
        interpolate, interpolate_closed_ring)

LAYER_NAME = "contours"

UPSAMPLE_FACTOR = 3
MAX_UPSAMPLED_CELLS = 150_000_000  # clamp the factor to 2 (then 1) above this

# Blur sigma in native pixels per user-facing smoothing level.
SMOOTHING_SIGMA = {"off": 0.0, "light": 0.8, "medium": 1.5, "strong": 2.5}

NICE_STEPS = [0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]

# Vector-space smoothing tolerances, as multiples of the native pixel size so
# the pipeline is CRS-unit agnostic (metres and degrees both work).
DP_PRE_FACTOR = 0.40
SPLINE_TOL_FACTOR = 0.05
SPLINE_TIGHTNESS = 0.5
SPLINE_MAX_SEGMENTS = 16


def suggest_intervals(zmin, zmax, target_max_minors=60):
    """Pick a (minor_interval, major_every) pair for an elevation range.

    Smallest nice step that keeps the minor contour count at or under
    target_max_minors; index contour every 5th.
    """
    zrange = float(zmax) - float(zmin)
    if not math.isfinite(zrange) or zrange <= 0:
        return 10.0, 5
    for step in NICE_STEPS:
        if zrange / step <= target_max_minors:
            return float(step), 5
    return float(NICE_STEPS[-1]), 5


def raster_stats(dem_path, band=1):
    """Approximate band statistics plus georeferencing facts, via GDAL.

    Fast enough for the dialog's main thread (approx_ok statistics).
    """
    from osgeo import gdal, osr

    gdal.UseExceptions()
    ds = gdal.Open(dem_path, gdal.GA_ReadOnly)
    b = ds.GetRasterBand(band)
    stats = b.ComputeStatistics(True)  # approx_ok
    gt = ds.GetGeoTransform()
    wkt = ds.GetProjection()
    is_geographic = False
    if wkt:
        srs = osr.SpatialReference()
        srs.ImportFromWkt(wkt)
        is_geographic = bool(srs.IsGeographic())
    return {
        "min": stats[0],
        "max": stats[1],
        "pixel_x": abs(gt[1]),
        "pixel_y": abs(gt[5]),
        "crs_wkt": wkt,
        "is_geographic": is_geographic,
        "nodata": b.GetNoDataValue(),
        "width": ds.RasterXSize,
        "height": ds.RasterYSize,
    }


def default_output_path(dem_source):
    """<dem_dir>/<dem_stem>_contours.gpkg for plain file sources.

    Sources GDAL spells with a prefix (GPKG:..., /vsizip/...) have no usable
    directory; fall back to the user's Documents folder.
    """
    source = str(dem_source or "")
    plain = os.path.isfile(source) and not source.lower().startswith(("/vsi", "gpkg:"))
    if plain:
        folder = os.path.dirname(os.path.abspath(source))
        stem = os.path.splitext(os.path.basename(source))[0]
    else:
        folder = os.path.join(os.path.expanduser("~"), "Documents")
        stem = "dem"
    return os.path.join(folder, stem + "_contours.gpkg")


def generate_contours(dem_path, minor_interval, major_every, smoothing,
                      out_gpkg, band=1, layer_name=LAYER_NAME,
                      progress_cb=None):
    """Run the full pipeline; safe on a worker thread.

    progress_cb(pct, msg) follows the lgs_tasks contract: it raises
    TaskCancelled when the user cancels, which propagates out of here.
    """
    from osgeo import gdal

    gdal.UseExceptions()

    def tick(pct, msg=None):
        if progress_cb is not None:
            progress_cb(pct, msg)

    minor_interval = float(minor_interval)
    major_every = max(1, int(major_every))
    if minor_interval <= 0:
        raise ValueError("Contour interval must be positive")

    tick(0, "Reading DEM...")
    src = gdal.Open(dem_path, gdal.GA_ReadOnly)
    gt = src.GetGeoTransform()
    crs_wkt = src.GetProjection()
    native_pixel = min(abs(gt[1]), abs(gt[5]))
    arr, nodata = _read_band(src, band)
    tick(5, "Smoothing surface...")

    valid = np.isfinite(arr) & (arr != nodata)
    if not valid.any():
        raise ValueError("DEM has no valid elevation cells")
    zmin = float(arr[valid].min())
    zmax = float(arr[valid].max())

    sigma = SMOOTHING_SIGMA.get(smoothing, SMOOTHING_SIGMA["medium"])
    if sigma > 0:
        arr = _gaussian_blur_nodata_aware(arr, valid, sigma, nodata)
    tick(20, "Resampling surface...")

    warped = _smoothed_mem_dataset(src, arr, nodata, gt, crs_wkt,
                                   _upsample_factor(src))
    tick(35, "Tracing contours...")

    start = math.ceil(zmin / minor_interval) * minor_interval
    levels = []
    level = start
    while level <= zmax:
        levels.append(round(level, 6))
        level += minor_interval
    if not levels:
        raise ValueError(
            "No contour levels fall inside the elevation range "
            "{0:.1f}-{1:.1f} at a {2:g} interval".format(zmin, zmax, minor_interval))

    contour_ds, contour_lyr = _extract_contours(warped, levels, nodata,
                                                progress_cb)

    tick(65, "Smoothing contour lines...")
    dp_tol = DP_PRE_FACTOR * native_pixel
    spl_tol = SPLINE_TOL_FACTOR * native_pixel
    major_interval = minor_interval * major_every

    feats = []
    majors = 0
    total = contour_lyr.GetFeatureCount()
    contour_lyr.ResetReading()
    for i, ogr_feat in enumerate(contour_lyr):
        geom_ref = ogr_feat.GetGeometryRef()
        if geom_ref is None:
            continue
        pts = [QgsPointXY(x, y) for x, y, *_ in geom_ref.GetPoints()]
        if len(pts) < 2:
            continue
        smooth = _smooth_line(pts, dp_tol, spl_tol)
        elev = float(ogr_feat.GetField(1))
        is_major = round(elev / minor_interval) % major_every == 0
        majors += 1 if is_major else 0

        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPolylineXY(smooth))
        feat.setAttributes([elev, "major" if is_major else "minor"])
        feats.append(feat)
        if i % 50 == 0 and total:
            tick(65 + 25.0 * i / total, "Smoothing contour lines...")

    tick(90, "Writing GeoPackage...")
    _write_gpkg(out_gpkg, layer_name, feats, crs_wkt)
    tick(100, "Done")

    del contour_ds, warped, src
    return {
        "gpkg": out_gpkg,
        "layer": layer_name,
        "count": len(feats),
        "majors": majors,
        "levels": levels,
        "minor_interval": minor_interval,
        "major_interval": major_interval,
        "crs_wkt": crs_wkt,
    }


# ---------------------------------------------------------------- internals


def _read_band(ds, band):
    """Band as float32 array + a guaranteed-finite nodata value."""
    from osgeo import gdal

    xs, ys = ds.RasterXSize, ds.RasterYSize
    b = ds.GetRasterBand(band)
    buf = b.ReadRaster(0, 0, xs, ys, buf_type=gdal.GDT_Float32)
    arr = np.frombuffer(buf, dtype=np.float32).reshape(ys, xs).copy()
    nodata = b.GetNoDataValue()
    if nodata is None or not math.isfinite(nodata):
        # Substitute a finite sentinel well outside any plausible elevation
        # so the mask/warp/contour steps all agree on one value.
        sentinel = np.float32(-9.0e30)
        if nodata is not None:
            arr[~np.isfinite(arr)] = sentinel
            arr[arr == np.float32(nodata)] = sentinel
        else:
            arr[~np.isfinite(arr)] = sentinel
        nodata = float(sentinel)
    return arr, float(np.float32(nodata))


def _blur(data, sigma):
    """Gaussian blur, scipy when present, numpy separable convolution else."""
    try:
        from scipy.ndimage import gaussian_filter
        return gaussian_filter(data, sigma, mode="nearest")
    except ImportError:
        pass
    radius = int(math.ceil(3 * sigma))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-(x * x) / (2.0 * sigma * sigma))
    kernel /= kernel.sum()
    kernel = kernel.astype(np.float32)

    out = data.astype(np.float32)
    for axis in (0, 1):
        padded = np.pad(out, [(radius, radius) if a == axis else (0, 0)
                              for a in (0, 1)], mode="edge")
        windows = np.lib.stride_tricks.sliding_window_view(
            padded, 2 * radius + 1, axis=axis)
        out = np.einsum("...k,k->...", windows, kernel).astype(np.float32)
    return out


def _gaussian_blur_nodata_aware(arr, valid, sigma, nodata):
    """Blur without letting the nodata fill value bleed into real terrain."""
    filled = np.where(valid, arr, 0).astype(np.float32)
    weights = valid.astype(np.float32)
    num = _blur(filled, sigma)
    den = _blur(weights, sigma)
    out = num / np.maximum(den, 1e-6)
    out = out.astype(np.float32)
    out[~valid] = np.float32(nodata)
    return out


def _upsample_factor(ds):
    cells = ds.RasterXSize * ds.RasterYSize
    for factor in (UPSAMPLE_FACTOR, 2, 1):
        if cells * factor * factor <= MAX_UPSAMPLED_CELLS:
            return factor
    return 1


def _smoothed_mem_dataset(src, arr, nodata, gt, crs_wkt, upsample):
    """Blurred array -> in-memory dataset, cubic-spline upsampled."""
    from osgeo import gdal

    ys, xs = arr.shape
    mem = gdal.GetDriverByName("MEM").Create("", xs, ys, 1, gdal.GDT_Float32)
    mem.SetGeoTransform(gt)
    mem.SetProjection(crs_wkt)
    b = mem.GetRasterBand(1)
    b.SetNoDataValue(nodata)
    b.WriteRaster(0, 0, xs, ys, arr.astype(np.float32).tobytes())
    if upsample <= 1:
        return mem
    warped = gdal.Warp(
        "", mem, format="MEM",
        width=xs * upsample, height=ys * upsample,
        resampleAlg="cubicspline",
        srcNodata=nodata, dstNodata=nodata)
    del mem
    return warped


def _extract_contours(warped, levels, nodata, progress_cb):
    """gdal.ContourGenerate at fixed levels into an in-memory OGR layer."""
    from osgeo import gdal, ogr, osr

    try:
        from ..lgs_tasks import TaskCancelled
    except ImportError:
        from lgs_tasks import TaskCancelled

    mem_ds = ogr.GetDriverByName("Memory").CreateDataSource("contours")
    srs = None
    wkt = warped.GetProjection()
    if wkt:
        srs = osr.SpatialReference()
        srs.ImportFromWkt(wkt)
    lyr = mem_ds.CreateLayer("contours", srs, ogr.wkbLineString)
    lyr.CreateField(ogr.FieldDefn("ID", ogr.OFTInteger))
    lyr.CreateField(ogr.FieldDefn("elev", ogr.OFTReal))

    cancelled = []

    def _gdal_progress(fraction, _msg, _data):
        if progress_cb is not None:
            try:
                progress_cb(35 + 30.0 * fraction, "Tracing contours...")
            except TaskCancelled:
                cancelled.append(True)
                return 0  # tells GDAL to abort
        return 1

    gdal.ContourGenerate(
        warped.GetRasterBand(1),
        0, 0,             # contourInterval, contourBase: 0 -> use fixedLevels
        list(levels),
        1, nodata,        # useNoData, noDataValue
        lyr, 0, 1,        # idField, elevField indexes
        callback=_gdal_progress)
    if cancelled:
        raise TaskCancelled()
    return mem_ds, lyr


def _smooth_line(pts, dp_tol, spl_tol):
    """DP-thin to shape anchors, then Hermite-spline back to a smooth curve.

    Tolerance/tightness/segments are always passed explicitly: the spline
    module reads the user's MapCleaning tool settings when handed None, and
    contours must not inherit those.
    """
    closed = len(pts) >= 4 and pts[0].distance(pts[-1]) < 1e-9
    simplified = QgsGeometry.fromPolylineXY(pts).simplify(dp_tol)
    anchors = [QgsPointXY(p) for p in simplified.asPolyline()] or pts
    if closed:
        if len(anchors) < 4:
            return pts
        return interpolate_closed_ring(
            anchors, tolerance=spl_tol, tightness=SPLINE_TIGHTNESS,
            max_segments=SPLINE_MAX_SEGMENTS)
    if len(anchors) < 3:
        return anchors
    return interpolate(
        anchors, tolerance=spl_tol, tightness=SPLINE_TIGHTNESS,
        max_segments=SPLINE_MAX_SEGMENTS)


def _write_gpkg(out_gpkg, layer_name, feats, crs_wkt):
    """Write the contour layer, preserving sibling layers in an existing file."""
    fields = QgsFields()
    fields.append(QgsField("elev", QMetaType.Type.Double))
    fields.append(QgsField("type", QMetaType.Type.QString, len=8))

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = layer_name
    if os.path.exists(out_gpkg):
        # CreateOrOverwriteLayer opens the file in update mode, so it only
        # works when the file already exists; it leaves sibling layers alone.
        options.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer)
    else:
        options.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile)

    crs = QgsCoordinateReferenceSystem.fromWkt(crs_wkt) if crs_wkt else \
        QgsCoordinateReferenceSystem()
    # NOTE: the 5th argument is the coordinate transform context, NOT the
    # driver name.
    writer = QgsVectorFileWriter.create(
        out_gpkg, fields, Qgis.WkbType.LineString, crs,
        QgsCoordinateTransformContext(), options)
    failed = (writer is None or
              writer.hasError() != QgsVectorFileWriter.WriterError.NoError)
    message = writer.errorMessage() if writer is not None else "writer not created"
    if not failed:
        for feat in feats:
            writer.addFeature(feat)
        failed = writer.hasError() != QgsVectorFileWriter.WriterError.NoError
        if failed:
            message = writer.errorMessage()
    del writer  # flush and close before anything reopens the file
    if failed:
        raise RuntimeError("Could not write {0}: {1}".format(out_gpkg, message))
