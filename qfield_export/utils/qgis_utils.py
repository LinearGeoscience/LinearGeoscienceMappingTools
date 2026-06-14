"""
QGIS-specific utilities for the LGS QField Exporter plugin.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
from qgis.core import (
    QgsProject,
    QgsMapLayer,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsMessageLog,
    Qgis,
    QgsVectorFileWriter,
)

import shutil


# Raster formats not supported by QField on mobile
UNSUPPORTED_RASTER_EXTENSIONS = {
    '.ecw': 'ECW (proprietary codec not available on mobile)',
    '.sid': 'MrSID (proprietary codec not available on mobile)',
    '.ers': 'ER Mapper (not supported on mobile)',

    '.hdf': 'HDF (not supported on mobile)',
    '.hdf5': 'HDF5 (not supported on mobile)',
    '.he5': 'HDF-EOS5 (not supported on mobile)',
    '.nc': 'NetCDF (not supported on mobile)',
    '.grib': 'GRIB (not supported on mobile)',
    '.grib2': 'GRIB2 (not supported on mobile)',
}


def clean_layer_name(name: str) -> str:
    """
    Clean a layer name for use as a filename/table name.

    Removes special characters, replaces spaces with underscores,
    and truncates to 200 characters for GeoPackage table name safety.

    Args:
        name: Raw layer name

    Returns:
        Cleaned name safe for filenames and GeoPackage table names
    """
    clean = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).rstrip()
    clean = clean.replace(' ', '_')
    return clean[:200]


def get_project_layers() -> List[QgsMapLayer]:
    """
    Get all layers from the current QGIS project.

    Returns:
        List of QgsMapLayer objects
    """
    return list(QgsProject.instance().mapLayers().values())


def get_layer_info(layer: QgsMapLayer) -> Dict[str, Any]:
    """
    Get information about a layer for display in the UI.

    Args:
        layer: QgsMapLayer to get info from

    Returns:
        Dictionary containing layer information
    """
    info = {
        'id': layer.id(),
        'name': layer.name(),
        'type': 'Unknown',
        'geometry': None,
        'source': layer.source(),
        'is_valid': layer.isValid(),
        'crs': layer.crs().authid() if layer.crs() else 'Unknown'
    }

    if isinstance(layer, QgsVectorLayer):
        info['type'] = 'Vector'
        geom_type = layer.geometryType()
        geom_names = {
            0: 'Point',
            1: 'Line',
            2: 'Polygon',
            3: 'Unknown',
            4: 'Null'
        }
        info['geometry'] = geom_names.get(geom_type, 'Unknown')
        info['feature_count'] = layer.featureCount()
    elif isinstance(layer, QgsRasterLayer):
        info['type'] = 'Raster'
        info['width'] = layer.width()
        info['height'] = layer.height()

    return info


def is_layer_exportable(layer: QgsMapLayer) -> bool:
    """
    Check if a layer can be exported to QField.

    Args:
        layer: Layer to check

    Returns:
        True if the layer can be exported
    """
    if not layer.isValid():
        return False

    # Check for unsupported layer types
    # Note: WMS/WMTS are supported - QField can use them when online
    # WFS needs conversion to vector, ArcGIS services have limited support
    unsupported_providers = ['wcs', 'ows']
    if hasattr(layer, 'providerType'):
        if layer.providerType().lower() in unsupported_providers:
            return False

    return True


def convert_to_geopackage(layer: QgsVectorLayer, output_dir: Path, layer_name: str = None) -> Optional[Path]:
    """
    Convert a vector layer to GeoPackage format, preserving styling.

    Args:
        layer: Vector layer to convert
        output_dir: Directory to save the GeoPackage
        layer_name: Optional custom name for the output

    Returns:
        Path to the created GeoPackage, or None if failed
    """
    if not isinstance(layer, QgsVectorLayer):
        return None

    if layer_name is None:
        layer_name = layer.name()

    clean_name = clean_layer_name(layer_name)

    output_path = output_dir / f"{clean_name}.gpkg"

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = 'GPKG'
    options.fileEncoding = 'UTF-8'

    # Write the layer data and geometry to GeoPackage
    # Use project transform context to respect project-level datum transforms
    error = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer,
        str(output_path),
        QgsProject.instance().transformContext(),
        options
    )

    if error[0] != QgsVectorFileWriter.NoError:
        QgsMessageLog.logMessage(
            f"Failed to convert layer {layer.name()} to GeoPackage: {error[1]}",
            "LGS QField Exporter",
            Qgis.Critical
        )
        return None

    # Now save the layer's style/symbology to the GeoPackage
    # This preserves colors, symbols, labels, etc.
    try:
        # Load the newly created GeoPackage layer to save style to it
        gpkg_uri = f"{output_path}|layername={clean_name}"
        temp_layer = QgsVectorLayer(gpkg_uri, clean_name, "ogr")

        if temp_layer.isValid():
            # Copy the style from original layer to the new GeoPackage layer
            # This includes symbology, labels, diagrams, etc.
            temp_layer.importNamedStyle(layer)

            # Save the style directly into the GeoPackage database
            # This embeds the style in the .gpkg file itself
            success, msg = temp_layer.saveStyleToDatabase(
                clean_name,  # Style name
                "",  # Description
                True,  # Use as default
                ""  # UI file path (not needed)
            )

            if not success:
                QgsMessageLog.logMessage(
                    f"Warning: Could not save style to GeoPackage for {layer.name()}: {msg}",
                    "LGS QField Exporter",
                    Qgis.Warning
                )
            else:
                QgsMessageLog.logMessage(
                    f"Successfully saved style to GeoPackage for {layer.name()}",
                    "LGS QField Exporter",
                    Qgis.Info
                )
        else:
            QgsMessageLog.logMessage(
                f"Warning: Could not load GeoPackage layer to save style: {temp_layer.error().message()}",
                "LGS QField Exporter",
                Qgis.Warning
            )
    except Exception as e:
        # Don't fail the entire export if style saving fails
        QgsMessageLog.logMessage(
            f"Warning: Failed to save style for {layer.name()}: {e}",
            "LGS QField Exporter",
            Qgis.Warning
        )

    return output_path


def _extract_gpkg_raster(layer: QgsRasterLayer, output_dir: Path, clean_name: str) -> Optional[Path]:
    """
    Extract a raster layer from a GeoPackage and save as GeoTIFF.

    Args:
        layer: Raster layer stored in GeoPackage
        output_dir: Directory to save the extracted raster
        clean_name: Cleaned name for the output file

    Returns:
        Path to the extracted raster, or None if failed
    """
    try:
        from osgeo import gdal
    except ImportError:
        QgsMessageLog.logMessage(
            f"GDAL Python bindings not available - cannot extract raster from GeoPackage for {layer.name()}",
            "LGS QField Exporter",
            Qgis.Warning
        )
        return None

    src_ds = None
    dst_ds = None
    try:
        # Enable GDAL exceptions for better error reporting
        gdal.UseExceptions()

        # Read the raster data using GDAL
        source = layer.source()

        # GDAL expects format: GPKG:path/to/file.gpkg:tablename
        # QGIS source might be: path/to/file.gpkg:tablename or GPKG:path/to/file.gpkg:tablename
        if not source.startswith('GPKG:'):
            gdal_source = f"GPKG:{source}"
        else:
            gdal_source = source

        QgsMessageLog.logMessage(
            f"Attempting to open GPKG raster: {gdal_source}",
            "LGS QField Exporter",
            Qgis.Info
        )

        # Open the raster
        src_ds = gdal.Open(gdal_source, gdal.GA_ReadOnly)
        if src_ds is None:
            # Try without GPKG prefix
            QgsMessageLog.logMessage(
                f"Failed with GPKG prefix, trying direct: {source}",
                "LGS QField Exporter",
                Qgis.Info
            )
            src_ds = gdal.Open(source, gdal.GA_ReadOnly)

        if src_ds is None:
            last_error = gdal.GetLastErrorMsg()
            QgsMessageLog.logMessage(
                f"Failed to open GPKG raster. GDAL error: {last_error}",
                "LGS QField Exporter",
                Qgis.Warning
            )
            return None

        # Output as GeoTIFF
        output_path = output_dir / f"{clean_name}.tif"

        QgsMessageLog.logMessage(
            f"Extracting GPKG raster to: {output_path}",
            "LGS QField Exporter",
            Qgis.Info
        )

        # Use gdal.Translate instead of CreateCopy for better handling of large/complex rasters
        # Translate is more robust and handles memory better
        translate_options = gdal.TranslateOptions(
            format='GTiff',
            creationOptions=['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=IF_SAFER'],
            callback=None  # No progress callback to avoid overhead
        )

        dst_ds = gdal.Translate(str(output_path), src_ds, options=translate_options)

        if dst_ds is None:
            last_error = gdal.GetLastErrorMsg()
            QgsMessageLog.logMessage(
                f"GDAL Translate failed. Error: {last_error}",
                "LGS QField Exporter",
                Qgis.Critical
            )
            return None

        # Close datasets explicitly before checking output
        dst_ds = None
        src_ds = None

        if output_path.exists():
            QgsMessageLog.logMessage(
                f"Successfully extracted GPKG raster to: {output_path}",
                "LGS QField Exporter",
                Qgis.Info
            )
            return output_path
        else:
            QgsMessageLog.logMessage(
                f"Output file was not created: {output_path}",
                "LGS QField Exporter",
                Qgis.Warning
            )
            return None

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        QgsMessageLog.logMessage(
            f"Failed to extract GPKG raster {layer.name()}: {e}\n{error_details}",
            "LGS QField Exporter",
            Qgis.Critical
        )
        return None
    finally:
        # Ensure GDAL datasets are always cleaned up
        dst_ds = None
        src_ds = None


def copy_raster_layer(layer: QgsRasterLayer, output_dir: Path) -> Optional[Path]:
    """
    Copy a raster layer to the output directory.
    Handles both standalone raster files and rasters stored in GeoPackages.

    Args:
        layer: Raster layer to copy
        output_dir: Directory to copy the raster to

    Returns:
        Path to the copied raster, or None if failed
    """
    if not isinstance(layer, QgsRasterLayer):
        return None

    source = layer.source()

    clean_name = clean_layer_name(layer.name())

    # Check if raster is stored in a GeoPackage (format: path.gpkg:layername)
    if ':' in source and '.gpkg:' in source.lower():
        # Raster is stored in a GeoPackage - need to extract it using GDAL
        return _extract_gpkg_raster(layer, output_dir, clean_name)

    # Regular raster file - copy as-is
    source_path = Path(source)
    if not source_path.exists():
        return None

    # Keep original extension
    extension = source_path.suffix
    output_path = output_dir / f"{clean_name}{extension}"

    try:
        shutil.copy2(str(source_path), str(output_path))

        # Also copy auxiliary files (.tfw, .prj, etc.)
        for aux_suffix in ['.tfw', '.prj', '.wld', '.aux.xml']:
            aux_file = source_path.parent / (source_path.stem + aux_suffix)
            if aux_file.exists():
                aux_dest = output_dir / (clean_name + aux_suffix)
                shutil.copy2(str(aux_file), str(aux_dest))

        return output_path
    except Exception as e:
        QgsMessageLog.logMessage(
            f"Failed to copy raster layer {layer.name()}: {e}",
            "LGS QField Exporter",
            Qgis.Critical
        )
        return None


def get_raster_format_warning(layer: QgsRasterLayer) -> Optional[str]:
    """
    Check if a raster layer uses a format unsupported by QField.

    Args:
        layer: Raster layer to check

    Returns:
        Warning string describing the issue, or None if format is supported
    """
    if not isinstance(layer, QgsRasterLayer):
        return None

    source = layer.source()

    # Skip web service rasters and GPKG-embedded rasters
    provider = layer.providerType().lower() if hasattr(layer, 'providerType') else ''
    if provider in ('wms', 'wmts'):
        return None
    if ':' in source and '.gpkg:' in source.lower():
        return None

    source_path = Path(source)
    ext = source_path.suffix.lower()

    return UNSUPPORTED_RASTER_EXTENSIONS.get(ext)


def convert_raster_to_geotiff(layer: QgsRasterLayer, output_dir: Path) -> Optional[Path]:
    """
    Convert a raster layer to GeoTIFF format with LZW compression.

    Args:
        layer: Raster layer to convert
        output_dir: Directory to save the converted raster

    Returns:
        Path to the created GeoTIFF, or None if failed
    """
    if not isinstance(layer, QgsRasterLayer):
        return None

    try:
        from osgeo import gdal
    except ImportError:
        QgsMessageLog.logMessage(
            f"GDAL Python bindings not available - cannot convert raster {layer.name()}",
            "LGS QField Exporter",
            Qgis.Warning
        )
        return None

    clean_name = clean_layer_name(layer.name())
    output_path = output_dir / f"{clean_name}.tif"

    src_ds = None
    dst_ds = None
    try:
        gdal.UseExceptions()

        src_ds = gdal.Open(layer.source(), gdal.GA_ReadOnly)
        if src_ds is None:
            last_error = gdal.GetLastErrorMsg()
            QgsMessageLog.logMessage(
                f"Failed to open raster for conversion. GDAL error: {last_error}",
                "LGS QField Exporter",
                Qgis.Warning
            )
            return None

        translate_options = gdal.TranslateOptions(
            format='GTiff',
            creationOptions=['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=IF_SAFER'],
            callback=None
        )

        dst_ds = gdal.Translate(str(output_path), src_ds, options=translate_options)

        if dst_ds is None:
            last_error = gdal.GetLastErrorMsg()
            QgsMessageLog.logMessage(
                f"GDAL Translate failed for {layer.name()}. Error: {last_error}",
                "LGS QField Exporter",
                Qgis.Critical
            )
            return None

        # Close datasets
        dst_ds = None
        src_ds = None

        if output_path.exists():
            QgsMessageLog.logMessage(
                f"Successfully converted {layer.name()} to GeoTIFF: {output_path}",
                "LGS QField Exporter",
                Qgis.Info
            )
            return output_path
        else:
            QgsMessageLog.logMessage(
                f"Output file was not created: {output_path}",
                "LGS QField Exporter",
                Qgis.Warning
            )
            return None

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        QgsMessageLog.logMessage(
            f"Failed to convert raster {layer.name()}: {e}\n{error_details}",
            "LGS QField Exporter",
            Qgis.Critical
        )
        return None
    finally:
        dst_ds = None
        src_ds = None


def log_message(message: str, level: Qgis.MessageLevel = Qgis.Info):
    """
    Log a message to the QGIS message log.

    Args:
        message: Message to log
        level: Message level (Info, Warning, Critical)
    """
    QgsMessageLog.logMessage(message, "LGS QField Exporter", level)