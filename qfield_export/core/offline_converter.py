"""
Offline converter for exporting QGIS projects to QField format.
Simplified version focused only on cable export functionality.
"""

import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any
from qgis.core import (
    QgsProject,
    QgsMapLayer,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsMessageLog,
    Qgis,
    QgsLayerTreeLayer
)
from qgis.PyQt.QtCore import QObject, pyqtSignal

from ..utils.path_utils import normalize_project_file_paths, ensure_relative_to_project, clean_csv_uri_to_path
from ..utils.qgis_utils import (
    convert_to_geopackage,
    copy_raster_layer,
    convert_raster_to_geotiff,
    get_raster_format_warning,
    is_layer_exportable,
    log_message
)


class OfflineConverter(QObject):
    """
    Handles the conversion of QGIS projects for offline use in QField.
    """

    # Signals
    progress_updated = pyqtSignal(int, int, str)  # current, total, message
    warning = pyqtSignal(str)
    finished = pyqtSignal(bool)  # success
    log_message = pyqtSignal(str)  # detailed log messages

    def __init__(self, project: QgsProject, export_dir: Path, selected_layers: List[str],
                 convert_unsupported: bool = True):
        """
        Initialize the offline converter.

        Args:
            project: QGIS project to export
            export_dir: Directory to export the project to
            selected_layers: List of layer IDs to export
            convert_unsupported: If True, convert unsupported raster formats to GeoTIFF
        """
        super().__init__()
        self.project = project
        self.export_dir = Path(export_dir)
        self.selected_layers = selected_layers
        self.convert_unsupported = convert_unsupported
        self.exported_layers = {}
        self.failed_layers = []  # Track failed layer exports with reasons
        self.converted_layers = []  # Track rasters converted from unsupported formats
        self._cancelled = False

    def cancel(self):
        """Cancel the export process."""
        self._cancelled = True

    def export(self) -> bool:
        """
        Export the project for QField.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Create export directory if it doesn't exist
            self.export_dir.mkdir(parents=True, exist_ok=True)

            # Check if directory is empty
            if any(self.export_dir.iterdir()):
                self.warning.emit(
                    "Export directory is not empty. Files may be overwritten."
                )

            # Get layers to export
            layers_to_export = self._get_layers_to_export()
            if not layers_to_export:
                self.warning.emit("No valid layers selected for export.")
                return False

            total_layers = len(layers_to_export)

            # Export each layer
            for i, layer in enumerate(layers_to_export):
                if self._cancelled:
                    log_message("Export cancelled by user", Qgis.Warning)
                    return False

                self.progress_updated.emit(
                    i + 1,
                    total_layers,
                    f"Exporting layer: {layer.name()}"
                )

                success = self._export_layer(layer)
                if not success:
                    self.warning.emit(f"Failed to export layer: {layer.name()}")

            # Save the project file
            self.progress_updated.emit(
                total_layers,
                total_layers,
                "Saving project file..."
            )

            project_file = self._save_project()
            if not project_file:
                self.warning.emit("Failed to save project file.")
                return False

            # Normalize paths in the project file for mobile compatibility
            self.progress_updated.emit(
                total_layers,
                total_layers,
                "Normalizing paths for mobile devices..."
            )
            normalize_project_file_paths(project_file)

            # Copy attachment folders if they exist
            self._copy_attachment_folders()

            # Display export summary with any failures
            self._display_export_summary(total_layers)

            self.finished.emit(True)
            return True

        except Exception as e:
            log_message(f"Export failed: {e}", Qgis.Critical)
            self.finished.emit(False)
            return False

    def _get_layers_to_export(self) -> List[QgsMapLayer]:
        """
        Get the list of layers to export based on selection.

        Returns:
            List of QgsMapLayer objects
        """
        all_layers = self.project.mapLayers()
        layers_to_export = []

        for layer_id in self.selected_layers:
            if layer_id in all_layers:
                layer = all_layers[layer_id]
                if is_layer_exportable(layer):
                    layers_to_export.append(layer)
                else:
                    self.warning.emit(f"Layer '{layer.name()}' cannot be exported (unsupported type)")

        return layers_to_export

    def _needs_conversion(self, layer: QgsVectorLayer) -> bool:
        """
        Check if a vector layer needs to be converted to GeoPackage.

        Layers that need conversion:
        - Database layers (PostGIS, SpatiaLite connections)
        - Memory layers
        - Remote services
        - Delimited text layers (CSV with geometry from X/Y fields)

        Layers that DON'T need conversion:
        - Local files (Shapefile, GeoPackage, GeoJSON, etc.)

        Args:
            layer: Vector layer to check

        Returns:
            True if layer needs conversion, False if it can be copied as-is
        """
        if not isinstance(layer, QgsVectorLayer):
            return False

        provider_type = layer.providerType().lower()
        source = layer.source()

        # Database providers - need conversion
        if provider_type in ['postgres', 'spatialite', 'mssql', 'oracle']:
            return True

        # Memory layers - need conversion
        if provider_type == 'memory':
            return True

        # Web services - need conversion
        if provider_type in ['wfs', 'arcgisfeatureserver']:
            return True

        # Delimited text layers (CSV with X/Y geometry) - need conversion
        # These are CSV files that QGIS converts to points based on coordinate fields
        # We need to convert them to GeoPackage to preserve the geometry
        if provider_type == 'delimitedtext':
            return True

        # Check if source is a local file path
        if provider_type == 'ogr':
            # Extract file path from source (it might have layer name appended)
            source_path = source.split('|')[0] if '|' in source else source
            source_file = Path(source_path)

            # If it's a local file that exists, no conversion needed
            if source_file.exists() and source_file.is_file():
                return False

        return False  # Default: don't convert

    def _get_layer_info(self, layer: QgsVectorLayer) -> str:
        """
        Get detailed information about a layer for logging purposes.

        Args:
            layer: Vector layer to inspect

        Returns:
            Formatted string with layer details
        """
        provider_type = layer.providerType().lower()
        info_parts = []

        # Geometry type
        geom_type_map = {
            0: 'Point',
            1: 'LineString',
            2: 'Polygon',
            3: 'Unknown',
            4: 'NoGeometry'
        }
        geom_type = geom_type_map.get(layer.geometryType(), 'Unknown')
        info_parts.append(f"Type: {geom_type}")

        # CRS
        if layer.crs().isValid():
            crs_auth = layer.crs().authid()  # e.g., "EPSG:3719"
            info_parts.append(f"CRS: {crs_auth}")

        # Feature count
        feature_count = layer.featureCount()
        info_parts.append(f"Features: {feature_count}")

        # Special info for delimited text layers
        if provider_type == 'delimitedtext':
            source = layer.source()
            # Try to extract X/Y field names from the URI
            if 'xField=' in source and 'yField=' in source:
                try:
                    x_field = source.split('xField=')[1].split('&')[0]
                    y_field = source.split('yField=')[1].split('&')[0]
                    # URL decode field names
                    import urllib.parse
                    x_field = urllib.parse.unquote(x_field)
                    y_field = urllib.parse.unquote(y_field)
                    info_parts.append(f"X/Y: {x_field}, {y_field}")
                except Exception:
                    pass

        return " | ".join(info_parts)

    def _export_layer(self, layer: QgsMapLayer) -> bool:
        """
        Export a single layer.

        Args:
            layer: Layer to export

        Returns:
            True if successful, False otherwise
        """
        try:
            provider_type = layer.providerType().lower() if hasattr(layer, 'providerType') else ''

            # Handle web service layers (WMS, WMTS, WFS, ArcGIS services)
            # These should be kept as references for online use in QField
            web_service_providers = ['wms', 'wmts', 'wfs', 'arcgisfeatureserver', 'arcgismapserver']
            if provider_type in web_service_providers:
                self.log_message.emit(f"  → Keeping '{layer.name()}' as web service reference ({provider_type.upper()})")
                # Add to exported_layers with original source unchanged
                # This prevents the layer from being removed when saving the project
                self.exported_layers[layer.id()] = {
                    'original_source': layer.source(),
                    'new_source': layer.source(),  # Same as original - no change needed
                    'provider': layer.providerType(),
                    'is_web_service': True  # Flag to skip datasource update
                }
                self.log_message.emit(f"  ✓ Web service layer preserved (requires internet connection)")
                return True

            if isinstance(layer, QgsVectorLayer):
                # Check if layer needs conversion or can be copied as-is
                if self._needs_conversion(layer):
                    # Convert to GeoPackage
                    provider_type_check = layer.providerType().lower()

                    # Determine conversion reason
                    if provider_type_check == 'delimitedtext':
                        reason = "delimited text layer with geometry"
                    elif provider_type_check == 'memory':
                        reason = "memory layer"
                    elif provider_type_check in ['postgres', 'spatialite', 'mssql', 'oracle']:
                        reason = "database layer"
                    elif provider_type_check in ['wfs', 'arcgisfeatureserver']:
                        reason = "web service layer"
                    else:
                        reason = "requires conversion"

                    # Get detailed layer info
                    layer_info = self._get_layer_info(layer)

                    self.log_message.emit(f"  → Converting '{layer.name()}' to GeoPackage ({reason})")
                    self.log_message.emit(f"     {layer_info}")
                    new_path = convert_to_geopackage(layer, self.export_dir)
                    if new_path:
                        self.exported_layers[layer.id()] = {
                            'original_source': layer.source(),
                            'new_source': str(new_path),
                            'provider': 'ogr'
                        }
                        self.log_message.emit(f"  ✓ Converted to: {new_path.name}")
                        return True
                    else:
                        self.log_message.emit(f"  ✗ Conversion failed")
                        self.failed_layers.append({
                            'name': layer.name(),
                            'reason': 'GeoPackage conversion failed'
                        })
                        return False
                else:
                    # Copy the file in its original format
                    try:
                        source_path = layer.source().split('|')[0] if '|' in layer.source() else layer.source()
                        source_info = Path(source_path).name if source_path else "unknown"
                    except Exception:
                        source_info = "unknown"

                    layer_info = self._get_layer_info(layer)
                    self.log_message.emit(f"  → Copying '{layer.name()}' ({source_info})")
                    self.log_message.emit(f"     {layer_info}")
                    new_path = self._copy_vector_layer(layer)
                    if new_path:
                        self.exported_layers[layer.id()] = {
                            'original_source': layer.source(),
                            'new_source': str(new_path),
                            'provider': layer.providerType()
                        }
                        self.log_message.emit(f"  ✓ Copied to: {new_path.name}")
                        return True
                    else:
                        self.log_message.emit(f"  ✗ Copy failed - file not found or inaccessible")
                        self.failed_layers.append({
                            'name': layer.name(),
                            'reason': 'File not found or inaccessible'
                        })
                        return False

            elif isinstance(layer, QgsRasterLayer):
                # Check if it's a web raster service
                if provider_type in ['wms', 'wmts']:
                    self.log_message.emit(f"  → Keeping '{layer.name()}' as web raster reference ({provider_type.upper()})")
                    # Add to exported_layers with original source unchanged
                    self.exported_layers[layer.id()] = {
                        'original_source': layer.source(),
                        'new_source': layer.source(),
                        'provider': layer.providerType(),
                        'is_web_service': True
                    }
                    self.log_message.emit(f"  ✓ Web raster layer preserved (requires internet connection)")
                    return True

                # Check for unsupported raster formats
                format_warning = get_raster_format_warning(layer)
                if format_warning:
                    if self.convert_unsupported:
                        self.log_message.emit(f"  → Converting '{layer.name()}' to GeoTIFF - {format_warning}")
                        new_path = convert_raster_to_geotiff(layer, self.export_dir)
                        if new_path:
                            self.exported_layers[layer.id()] = {
                                'original_source': layer.source(),
                                'new_source': str(new_path),
                                'provider': layer.providerType()
                            }
                            self.converted_layers.append({
                                'name': layer.name(),
                                'from_format': format_warning,
                                'to_file': new_path.name
                            })
                            self.log_message.emit(f"  ✓ Converted to: {new_path.name}")
                            return True
                        else:
                            # Conversion failed - fall back to copying as-is
                            self.log_message.emit(f"  ⚠ Conversion failed, copying original file instead")
                            self.warning.emit(
                                f"Could not convert '{layer.name()}' ({format_warning}) to GeoTIFF - "
                                f"copied as-is, may not work in QField"
                            )
                    else:
                        self.warning.emit(
                            f"Layer '{layer.name()}' uses unsupported format ({format_warning}) - "
                            f"may not work in QField"
                        )

                # Copy/extract local raster layers (normal path or fallback)
                try:
                    source = layer.source()
                    # Check if raster is in a GeoPackage
                    if ':' in source and '.gpkg:' in source.lower():
                        source_info = source.split('/')[-1] if '/' in source else source.split('\\')[-1] if '\\' in source else source
                        action = "Extracting"
                    else:
                        source_info = Path(source).name if source else "unknown"
                        action = "Copying"
                except Exception:
                    source_info = "unknown"
                    action = "Copying"

                self.log_message.emit(f"  → {action} raster '{layer.name()}' ({source_info})")
                new_path = copy_raster_layer(layer, self.export_dir)
                if new_path:
                    self.exported_layers[layer.id()] = {
                        'original_source': layer.source(),
                        'new_source': str(new_path),
                        'provider': layer.providerType()
                    }
                    action_past = "Extracted" if action == "Extracting" else "Copied"
                    self.log_message.emit(f"  ✓ {action_past} to: {new_path.name}")
                    return True
                else:
                    self.log_message.emit(f"  ✗ {action} failed")
                    self.failed_layers.append({
                        'name': layer.name(),
                        'reason': f'Raster {action.lower()} failed'
                    })
                    return False

            # Unknown layer type
            self.failed_layers.append({
                'name': layer.name(),
                'reason': 'Unsupported layer type'
            })
            return False

        except Exception as e:
            self.log_message.emit(f"  ✗ ERROR: {str(e)}")
            log_message(f"Failed to export layer {layer.name()}: {e}", Qgis.Critical)
            self.failed_layers.append({
                'name': layer.name(),
                'reason': f'Error: {str(e)}'
            })
            return False

    def _copy_vector_layer(self, layer: QgsVectorLayer) -> Optional[Path]:
        """
        Copy a vector layer file to the export directory, preserving its format.

        Args:
            layer: Vector layer to copy

        Returns:
            Path to the copied file, or None if failed
        """
        if self._cancelled:
            return None

        try:
            # Get the source path
            source = layer.source()

            # Check if this is a CSV/delimited text layer with query parameters
            # These layers have URIs like: file:\path\file.csv?type=csv&maxFields=...
            provider_type = layer.providerType().lower() if hasattr(layer, 'providerType') else ''

            if provider_type == 'delimitedtext' or ('?' in source and '.csv' in source.lower()):
                # This is a CSV layer with URI parameters
                # Extract the clean file path
                clean_path = clean_csv_uri_to_path(source)
                if clean_path:
                    source_path = clean_path
                else:
                    # Fallback: strip query params manually
                    source_path = source.split('?')[0]
                    # Remove file protocol if present
                    if source_path.startswith('file:'):
                        source_path = source_path.replace('file:\\', '').replace('file:///', '').replace('file:/', '')
            else:
                # Normal layer (shapefile, geopackage, etc.)
                # Extract file path from source (it might have layer name appended with |)
                source_path = source.split('|')[0] if '|' in source else source

            source_file = Path(source_path)

            # Log the actual path we're trying to access
            self.log_message.emit(f"     Source path: {source_file}")

            if not source_file.exists():
                self.log_message.emit(f"     File does not exist at: {source_file}")
                log_message(f"Source file not found: {source_file}", Qgis.Warning)
                return None

            if not source_file.is_file():
                self.log_message.emit(f"     Path exists but is not a file: {source_file}")
                return None

            # Determine output path
            output_file = self.export_dir / source_file.name

            # Copy the main file
            shutil.copy2(str(source_file), str(output_file))

            # For shapefiles, also copy auxiliary files (.shx, .dbf, .prj, .cpg, .qix, etc.)
            if source_file.suffix.lower() == '.shp':
                base_name = source_file.stem
                for aux_ext in ['.shx', '.dbf', '.prj', '.cpg', '.qix', '.sbn', '.sbx']:
                    aux_file = source_file.parent / (base_name + aux_ext)
                    if aux_file.exists():
                        shutil.copy2(str(aux_file), str(self.export_dir / aux_file.name))

            # For GeoPackage, check for -wal and -shm files
            elif source_file.suffix.lower() == '.gpkg':
                for aux_ext in ['-wal', '-shm']:
                    aux_file = source_file.parent / (source_file.name + aux_ext)
                    if aux_file.exists():
                        shutil.copy2(str(aux_file), str(self.export_dir / aux_file.name))

            # Build the new source string
            new_source = str(output_file)
            if '|' in source:
                # Preserve layer name for multi-layer formats
                layer_part = source.split('|', 1)[1]
                new_source = f"{new_source}|{layer_part}"

            return Path(new_source.split('|')[0])

        except Exception as e:
            log_message(f"Failed to copy vector layer {layer.name()}: {e}", Qgis.Critical)
            return None

    def _save_project(self) -> Optional[Path]:
        """
        Save the project file with updated layer sources.

        This method preserves ALL project properties including:
        - Layer tree structure and order
        - Layer visibility settings
        - Symbology and styles
        - Layer groups
        - Map themes
        - Print layouts
        - All custom properties

        Handles both .qgs (XML) and .qgz (compressed) project formats.

        Returns:
            Path to the saved project file, or None if failed
        """
        if self._cancelled:
            return None

        try:
            import xml.etree.ElementTree as ET
            import zipfile
            import tempfile

            # Get the original project file
            original_file = Path(self.project.fileName())
            if not original_file.exists():
                log_message("Original project file not found", Qgis.Critical)
                return None

            project_name = original_file.stem
            is_qgz = original_file.suffix.lower() == '.qgz'

            # Destination project file (always save as .qgs for QField)
            project_file = self.export_dir / f"{project_name}.qgs"

            # If original is .qgz, extract the .qgs file from it
            if is_qgz:
                log_message("Detected compressed project (.qgz), extracting...", Qgis.Info)
                try:
                    with zipfile.ZipFile(str(original_file), 'r') as zip_ref:
                        # The .qgs file inside has the same base name
                        qgs_filename = f"{project_name}.qgs"
                        if qgs_filename in zip_ref.namelist():
                            # Extract to temporary location first
                            with tempfile.TemporaryDirectory() as temp_dir:
                                zip_ref.extract(qgs_filename, temp_dir)
                                temp_qgs = Path(temp_dir) / qgs_filename
                                shutil.copy2(str(temp_qgs), str(project_file))
                        else:
                            log_message(f"Could not find {qgs_filename} in .qgz archive", Qgis.Critical)
                            return None
                except Exception as e:
                    log_message(f"Failed to extract .qgz file: {e}", Qgis.Critical)
                    return None
            else:
                # Copy the .qgs file directly
                shutil.copy2(str(original_file), str(project_file))

            # Now modify the datasources in the copied project file
            tree = ET.parse(str(project_file))
            root = tree.getroot()

            # Get IDs of layers that were NOT exported (to remove them)
            exported_layer_ids = set(self.exported_layers.keys())
            all_layer_ids = set(self.project.mapLayers().keys())
            layers_to_remove = all_layer_ids - exported_layer_ids

            # Update datasources for exported layers
            for maplayer in root.iter('maplayer'):
                layer_id = maplayer.find('id')
                if layer_id is not None and layer_id.text and layer_id.text in self.exported_layers:
                    layer_info = self.exported_layers[layer_id.text]

                    # Skip datasource update for web service layers (WMS, WMTS, etc.)
                    # They should keep their original online URLs
                    if layer_info.get('is_web_service', False):
                        continue

                    # Update the datasource element for file-based layers
                    datasource = maplayer.find('datasource')
                    if datasource is not None:
                        # Get just the filename for the new source
                        new_source_path = Path(layer_info['new_source'])

                        # If the original source had layer specification (e.g., for GPKG)
                        # preserve it
                        if '|' in layer_info['original_source']:
                            original_parts = layer_info['original_source'].split('|', 1)
                            if len(original_parts) > 1:
                                layer_spec = original_parts[1]
                                datasource.text = f"./{new_source_path.name}|{layer_spec}"
                            else:
                                datasource.text = f"./{new_source_path.name}"
                        else:
                            # Use relative path
                            datasource.text = f"./{new_source_path.name}"

            # Remove layers that were not exported
            layers_parent = root.find('.//projectlayers')
            if layers_parent is not None:
                for maplayer in list(layers_parent.findall('maplayer')):
                    layer_id_elem = maplayer.find('id')
                    if layer_id_elem is not None and layer_id_elem.text in layers_to_remove:
                        layers_parent.remove(maplayer)

            # Remove from layer tree as well
            layer_tree = root.find('.//layer-tree-group')
            if layer_tree is not None:
                self._remove_layers_from_tree(layer_tree, layers_to_remove)

            # Update project title
            title_elem = root.find('.//title')
            if title_elem is not None:
                current_title = title_elem.text or project_name
                if not current_title.endswith('(QField)'):
                    title_elem.text = f"{current_title} (QField)"

            # Make project paths relative
            properties = root.find('.//properties')
            if properties is not None:
                paths_elem = properties.find('.//Paths')
                if paths_elem is not None:
                    absolute_elem = paths_elem.find('absolute')
                    if absolute_elem is not None:
                        absolute_elem.set('type', 'bool')
                        absolute_elem.text = 'false'

            # Save the modified project atomically (write to temp, then rename)
            temp_fd, temp_path = tempfile.mkstemp(
                suffix='.qgs', dir=str(self.export_dir)
            )
            try:
                import os
                os.close(temp_fd)
                tree.write(temp_path, encoding='UTF-8', xml_declaration=True)
                # Replace destination with the temp file
                temp_file = Path(temp_path)
                temp_file.replace(project_file)
            except Exception:
                # Clean up temp file on failure
                Path(temp_path).unlink(missing_ok=True)
                raise

            return project_file

        except Exception as e:
            log_message(f"Failed to save project: {e}", Qgis.Critical)
            import traceback
            log_message(f"Traceback: {traceback.format_exc()}", Qgis.Critical)
            return None

    def _remove_layers_from_tree(self, tree_group, layer_ids_to_remove):
        """
        Recursively remove layers from the layer tree.

        Args:
            tree_group: XML element representing a layer tree group
            layer_ids_to_remove: Set of layer IDs to remove
        """
        # Remove layer-tree-layer elements
        for layer_elem in list(tree_group.findall('layer-tree-layer')):
            layer_id = layer_elem.get('id')
            if layer_id and layer_id in layer_ids_to_remove:
                tree_group.remove(layer_elem)

        # Recursively process nested groups
        for group_elem in tree_group.findall('layer-tree-group'):
            self._remove_layers_from_tree(group_elem, layer_ids_to_remove)

    def _copy_attachment_folders(self):
        """
        Copy standard attachment folders if they exist in the project directory.
        """
        attachment_dirs = ['DCIM', 'audio', 'video', 'files', 'photos']

        if not self.project.fileName():
            return

        project_dir = Path(self.project.fileName()).parent

        for dir_name in attachment_dirs:
            source_dir = project_dir / dir_name
            if source_dir.exists() and source_dir.is_dir():
                dest_dir = self.export_dir / dir_name
                try:
                    shutil.copytree(str(source_dir), str(dest_dir), dirs_exist_ok=True)
                    log_message(f"Copied attachment folder: {dir_name}")
                except Exception as e:
                    log_message(f"Failed to copy attachment folder {dir_name}: {e}", Qgis.Warning)

    def _display_export_summary(self, total_layers: int):
        """
        Display a summary of the export process, including any failed layers.

        Args:
            total_layers: Total number of layers attempted to export
        """
        # Calculate success metrics
        successful_count = len(self.exported_layers)
        failed_count = len(self.failed_layers)

        # Emit blank line for readability
        self.log_message.emit("")

        # Display summary header
        self.log_message.emit("=" * 60)
        self.log_message.emit("EXPORT SUMMARY")
        self.log_message.emit("=" * 60)
        self.log_message.emit(f"Total layers processed: {total_layers}")
        self.log_message.emit(f"Successfully exported: {successful_count}")
        if self.converted_layers:
            self.log_message.emit(f"Converted to GeoTIFF: {len(self.converted_layers)}")
        self.log_message.emit(f"Failed to export: {failed_count}")

        # If there are converted layers, list them
        if self.converted_layers:
            self.log_message.emit("")
            self.log_message.emit("CONVERTED RASTERS:")
            self.log_message.emit("-" * 60)
            for conv in self.converted_layers:
                self.log_message.emit(f"  {conv['name']}: {conv['from_format']} → {conv['to_file']}")
            self.log_message.emit("-" * 60)

        # If there are failures, list them with reasons
        if failed_count > 0:
            self.log_message.emit("")
            self.log_message.emit("FAILED LAYERS:")
            self.log_message.emit("-" * 60)
            for i, failure in enumerate(self.failed_layers, 1):
                self.log_message.emit(f"{i}. {failure['name']}")
                self.log_message.emit(f"   Reason: {failure['reason']}")
            self.log_message.emit("-" * 60)
        else:
            self.log_message.emit("")
            self.log_message.emit("All layers exported successfully!")

        self.log_message.emit("=" * 60)