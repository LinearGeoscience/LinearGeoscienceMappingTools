"""
Glue for the unified Mapping Export.

Composes existing plugin functionality - the photo export workers, the GDAL
raster-to-geopackage approach, the finalised mapsheet layer, and the Stereonet
Export tab - into one workflow WITHOUT duplicating any of their logic. Every
function here is UI-free and takes a ``log(msg, level)`` callback so output
flows into the Mapping Export dialog's shared log panel.

Reuse anchors:
- Photo workers: ``script_exportphotos.PhotoPackageWorker`` / ``PhotoExportWorker``
- Sample filter: mirrors ``script_exportphotos.get_filtered_features``
- Raster -> GPKG: same GDAL calls as ``script_reprojectgeopackage.process_raster_layer``
- Mapsheet schema: ``script_mapsheet_generator._create_preview_fields``
- Stereonet export: ``stereonet.core`` dock / Export tab widgets
"""

import os
import re

from qgis.core import (
    QgsProject, QgsVectorFileWriter, QgsCoordinateTransformContext,
    QgsMapLayerType, QgsWkbTypes,
)


# Field schema of a finalised mapsheet layer
# (script_mapsheet_generator.py:696 _create_preview_fields).
MAPSHEET_FIELDS = {
    'name', 'sheet_size', 'scale', 'orientation',
    'dimensions', 'area_m2', 'inside_pct', 'group',
}

# Photo layer field names (script_exportphotos.py:586-589).
PHOTO_PATH_FIELD = "PhotoPath"
TYPE_FIELD = "Type"
SAMPLEID_FIELD = "SampleID"

# Export tab position in the Stereonet dock's tab widget
# (Plot/Categories/Datasets/Coding/Colors/Export - stereonet/core.py:492-537).
STEREONET_EXPORT_TAB_INDEX = 5


def _noop(msg, level="INFO"):
    pass


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------
def project_name(fallback=None):
    """Best-effort project name for use as a file/folder prefix.

    Uses the saved project file name; falls back to ``fallback`` (e.g. the
    source geopackage) and finally to 'Mapping' when the project is unsaved.
    """
    project_path = QgsProject.instance().fileName()
    if project_path:
        return os.path.splitext(os.path.basename(project_path))[0]
    if fallback:
        return os.path.splitext(os.path.basename(fallback))[0]
    return "Mapping"


def default_export_folder_name(fallback=None):
    """Return '<ProjectName>_Export' for the default output folder name."""
    return f"{project_name(fallback)}_Export"


# ---------------------------------------------------------------------------
# Mapsheet grid -> geopackage
# ---------------------------------------------------------------------------
def find_mapsheet_layer():
    """Auto-detect a finalised mapsheet layer in the current project.

    Prefers a polygon layer named 'Mapsheets' (the name the Mapsheet
    Generator gives its final layer, script_mapsheet_generator.py:1582);
    otherwise the first polygon layer carrying the mapsheet field schema.
    Returns the ``QgsVectorLayer`` or None.
    """
    polygons = []
    for layer in QgsProject.instance().mapLayers().values():
        if layer.type() != QgsMapLayerType.VectorLayer:
            continue
        if layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            continue
        polygons.append(layer)

    for layer in polygons:
        if layer.name().strip().lower() == 'mapsheets':
            return layer
    for layer in polygons:
        names = {f.name() for f in layer.fields()}
        if MAPSHEET_FIELDS.issubset(names):
            return layer
    return None


def export_mapsheet_to_gpkg(layer, output_gpkg, log=_noop):
    """Write a mapsheet layer to its own geopackage. Returns True on success.

    Uses the same ``writeAsVectorFormatV3`` pattern as the core layer export
    (static_mapping_export/main.py:230).
    """
    if layer is None:
        log("Mapsheet export skipped - no mapsheet layer", "WARNING")
        return False
    if not layer.isValid():
        log(f"Mapsheet layer '{layer.name()}' is not valid", "ERROR")
        return False

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = "Mapsheets"
    options.fileEncoding = "UTF-8"
    options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

    error = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, output_gpkg, QgsCoordinateTransformContext(), options)

    if error[0] != QgsVectorFileWriter.NoError:
        log(f"Failed to export mapsheet grid: {error[1]}", "ERROR")
        return False

    log(f"Mapsheet grid exported ({layer.featureCount()} sheets)", "SUCCESS")
    return True


# ---------------------------------------------------------------------------
# Rasters -> geopackage (net-new; same GDAL tools as
# script_reprojectgeopackage.process_raster_layer at :808)
# ---------------------------------------------------------------------------
def list_project_rasters():
    """Return the project's raster layers, sorted by name."""
    rasters = [layer for layer in QgsProject.instance().mapLayers().values()
               if layer.type() == QgsMapLayerType.RasterLayer]
    rasters.sort(key=lambda l: l.name().lower())
    return rasters


def _safe_table_name(name, used):
    """Sanitise a raster name into a unique GPKG table name."""
    base = re.sub(r'[^0-9A-Za-z_]', '_', (name or 'raster').strip()) or 'raster'
    if base[0].isdigit():
        base = f"r_{base}"
    candidate = base
    n = 1
    while candidate.lower() in used:
        candidate = f"{base}_{n}"
        n += 1
    used.add(candidate.lower())
    return candidate


def export_rasters_to_gpkg(raster_sources, output_gpkg, target_crs=None, log=_noop):
    """Write each raster source into one geopackage as a RASTER_TABLE.

    raster_sources: list of ``(name, source_uri)`` tuples. ``name`` becomes the
    RASTER_TABLE; ``source_uri`` is any GDAL-readable raster (a project layer's
    source or a file path on disk).
    target_crs: optional ``QgsCoordinateReferenceSystem`` to reproject into.

    Returns ``(ok_count, fail_count)``. A failure on one raster never aborts
    the rest. The first raster creates the file; subsequent rasters append a
    new RASTER_TABLE via ``APPEND_SUBDATASET``. Rasters get their own gpkg
    because GDAL cannot mix raster and vector tables in a single geopackage.
    """
    try:
        from processing.core.Processing import Processing
        from processing.tools import general
        Processing.initialize()
    except Exception as e:
        log(f"Could not initialise Processing for raster export: {e}", "ERROR")
        return 0, len(raster_sources)

    ok, fail = 0, 0
    used_names = set()
    for name, source in raster_sources:
        table = _safe_table_name(name, used_names)
        append = " -co APPEND_SUBDATASET=YES" if os.path.exists(output_gpkg) else ""
        extra = f"-of GPKG -co RASTER_TABLE={table}{append}"
        try:
            if target_crs is not None and target_crs.isValid():
                params = {
                    'INPUT': source,
                    'SOURCE_CRS': None,
                    'TARGET_CRS': target_crs.authid(),
                    'RESAMPLING': 0,
                    'NODATA': None,
                    'TARGET_RESOLUTION': None,
                    'OPTIONS': '',
                    'DATA_TYPE': 0,
                    'TARGET_EXTENT': None,
                    'TARGET_EXTENT_CRS': None,
                    'MULTITHREADING': False,
                    'EXTRA': extra,
                    'OUTPUT': output_gpkg,
                }
                general.run("gdal:warpreproject", params)
            else:
                params = {
                    'INPUT': source,
                    'EXTRA': extra,
                    'OUTPUT': output_gpkg,
                }
                general.run("gdal:translate", params)
            log(f"Raster exported: {name} -> {table}", "SUCCESS")
            ok += 1
        except Exception as e:
            log(f"Failed to export raster '{name}': {e}", "ERROR")
            fail += 1
    return ok, fail


# ---------------------------------------------------------------------------
# Photos / samples (reuse the existing script_exportphotos workers)
# ---------------------------------------------------------------------------
def select_photo_features(layer, sample_only=False):
    """Return a layer's features, optionally only those with Type='Sample'.

    Mirrors ``script_exportphotos.get_filtered_features`` (:904).
    """
    if layer is None:
        return []
    features = list(layer.getFeatures())
    if not sample_only:
        return features
    return [f for f in features
            if f.fields().indexOf(TYPE_FIELD) != -1 and f[TYPE_FIELD] == 'Sample']


def build_field_photo_worker(layer, features, export_root):
    """A ``PhotoPackageWorker`` that writes a portable 'Photos/' package."""
    from ..script_exportphotos import PhotoPackageWorker
    return PhotoPackageWorker(
        layer, features, export_root, PHOTO_PATH_FIELD,
        folder_name="Photos", gpkg_name="Photo Points")


def build_sample_photo_worker(layer, features, export_root, rename_by_sampleid=False):
    """Worker for sample photos.

    Default: a portable 'Samples/' package (``PhotoPackageWorker``). When
    ``rename_by_sampleid`` is set, a copy+CSV export renamed by SampleID
    (``PhotoExportWorker``) into 'Samples/' instead - both reuse the existing
    workers unchanged.
    """
    if rename_by_sampleid:
        from ..script_exportphotos import PhotoExportWorker
        samples_dir = os.path.join(export_root, "Samples")
        os.makedirs(samples_dir, exist_ok=True)
        return PhotoExportWorker(
            features, samples_dir, "Samples", PHOTO_PATH_FIELD,
            rename_by_sampleid=True, sampleid_field=SAMPLEID_FIELD)

    from ..script_exportphotos import PhotoPackageWorker
    return PhotoPackageWorker(
        layer, features, export_root, PHOTO_PATH_FIELD,
        folder_name="Samples", gpkg_name="Sample Points")


# ---------------------------------------------------------------------------
# Print layouts -> PDF / GeoTIFF / PNG (reuse the Create Layouts helper)
# ---------------------------------------------------------------------------
def list_project_layouts():
    """Names of the print layouts in the current project, sorted."""
    manager = QgsProject.instance().layoutManager()
    return sorted(layout.name() for layout in manager.printLayouts())


def export_layouts(layout_names, out_dir, dpi=300, do_pdf=True, do_tiff=False,
                   do_png=False, log=_noop):
    """Export selected print layouts to ``out_dir``.

    Reuses ``script_create_layouts.export_layouts_to_formats`` so the export
    logic (georeferenced PDF, GeoTIFF/PNG with worldfiles) is not duplicated.
    Returns ``(ok_count, fail_count)``.
    """
    if not layout_names:
        log("Layout export skipped - no layouts selected", "WARNING")
        return 0, 0
    os.makedirs(out_dir, exist_ok=True)
    try:
        from ..script_create_layouts import export_layouts_to_formats
    except Exception as e:
        log(f"Layout export unavailable: {e}", "ERROR")
        return 0, len(layout_names)
    return export_layouts_to_formats(
        layout_names, out_dir, dpi=dpi,
        do_pdf=do_pdf, do_tiff=do_tiff, do_png=do_png,
        log=lambda m: log(m, "INFO"))


# ---------------------------------------------------------------------------
# Structural export (launch the existing Stereonet Export tab)
# ---------------------------------------------------------------------------
def launch_stereonet_export(stereonet_core, output_dir, prefix, log=_noop):
    """Reveal the Stereonet dock and switch to its Export tab, pre-filling the
    output directory and file prefix. The user picks a format (Leapfrog /
    Stereonet11) and clicks Export there. Returns True if the tab was surfaced.
    """
    if stereonet_core is None:
        log("Structural export skipped - Stereonet plugin not available", "WARNING")
        return False

    dock = getattr(stereonet_core, 'dock', None)
    tabs = getattr(stereonet_core, 'tab_widget', None)
    if dock is None or tabs is None:
        log("Structural export skipped - Stereonet dock not initialised", "ERROR")
        return False

    try:
        os.makedirs(output_dir, exist_ok=True)
        dock.setVisible(True)
        dock.raise_()
        tabs.setCurrentIndex(STEREONET_EXPORT_TAB_INDEX)

        dir_widget = getattr(stereonet_core, 'export_dir_widget', None)
        if dir_widget is not None:
            dir_widget.setFilePath(output_dir)
        prefix_edit = getattr(stereonet_core, 'export_prefix', None)
        if prefix_edit is not None and prefix:
            prefix_edit.setText(prefix)

        log("Stereonet Export tab opened - choose Leapfrog or Stereonet11 and "
            "click 'Export Files' to write the structural data", "INFO")
        return True
    except Exception as e:
        log(f"Could not open Stereonet Export tab: {e}", "ERROR")
        return False
