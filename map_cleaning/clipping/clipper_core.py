# -*- coding: utf-8 -*-
"""
Core Clipping Logic for Polygon Clipper
Pure geometry operations with no UI dependencies
Enhanced with multipart splitting option and UUID regeneration
"""
from qgis.core import (
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsSpatialIndex,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant
from qgis.analysis import QgsGeometrySnapper
import uuid as uuid_module

from ..core.utils import MIN_AREA_THRESHOLD

class ClippingResult:
    """Container for clipping operation results"""
    def __init__(self):
        self.success = False
        self.cutter_ids = []
        self.target_ids = []
        self.clipped_features = []  # New features after clipping
        self.deleted_ids = []  # IDs of features to delete
        self.clipped_count = 0
        self.unchanged_count = 0
        self.snapped_count = 0
        self.split_count = 0  # Number of features split into multiple
        self.bisecting_count = 0  # Number of bisecting overlaps
        self.error = None


def copy_attributes_without_fid(source_feature, target_feature, layer, uuid_field_name=None):
    """
    Copy attributes from source feature to target feature, excluding fid/id fields.
    Optionally regenerates UUID fields to ensure uniqueness when splitting features.

    This prevents UNIQUE constraint errors when adding new features to GeoPackage layers,
    which have an 'fid' primary key field that should not be copied.

    Args:
        source_feature: QgsFeature - feature to copy attributes from
        target_feature: QgsFeature - feature to copy attributes to
        layer: QgsVectorLayer - the layer (to get field names)
        uuid_field_name: str or None - if provided, generate new UUID for this field
    """
    source_attrs = source_feature.attributes()
    fields = layer.fields()

    # Create a list of attributes, setting fid/id fields to None
    new_attrs = []
    for idx, field in enumerate(fields):
        field_name_lower = field.name().lower()
        field_name_actual = field.name()

        if field_name_lower in ['fid', 'id', 'ogc_fid']:
            # Skip primary key fields - let the database assign these
            new_attrs.append(None)
        elif uuid_field_name and field_name_actual == uuid_field_name:
            # Generate new UUID for this field to avoid duplicates when splitting
            new_attrs.append(str(uuid_module.uuid4()))
        else:
            new_attrs.append(source_attrs[idx] if idx < len(source_attrs) else None)

    target_feature.setAttributes(new_attrs)


def extract_polygon_parts_from_geometry(geom, min_area=MIN_AREA_THRESHOLD):
    """
    Extract all valid polygon parts from any geometry type.
    Handles GeometryCollection, MultiPolygon, MultiSurface, and Polygon types.

    Args:
        geom: QgsGeometry - geometry to extract polygons from
        min_area: float - minimum area threshold for valid polygons

    Returns:
        list of QgsGeometry - valid polygon geometries
    """
    if not geom or geom.isEmpty():
        return []

    polygon_parts = []
    geom_type = geom.wkbType()

    # First, try to fix invalid geometry
    if not geom.isGeosValid():
        try:
            fixed = geom.makeValid()
            if fixed and fixed.isGeosValid() and not fixed.isEmpty():
                geom = fixed
                geom_type = geom.wkbType()
        except Exception:
            pass

    # Handle GeometryCollection and similar multi-geometry types
    # This includes GeometryCollection, Unknown, and other mixed types
    if geom_type in [QgsWkbTypes.GeometryCollection, QgsWkbTypes.Unknown] or \
       geom.type() == QgsWkbTypes.UnknownGeometry:
        try:
            for part in geom.asGeometryCollection():
                if part and part.type() == QgsWkbTypes.PolygonGeometry:
                    # Recursively extract from each part in case it's also multi
                    if part.isMultipart():
                        sub_parts = extract_polygon_parts_from_geometry(QgsGeometry(part), min_area)
                        polygon_parts.extend(sub_parts)
                    elif part.isGeosValid() and not part.isEmpty():
                        area = part.area()
                        if area > min_area:
                            polygon_parts.append(QgsGeometry(part))
        except Exception:
            pass
        # Don't return early - if we got nothing, try other methods below
        if polygon_parts:
            return polygon_parts

    # Handle MultiPolygon explicitly by WKB type first
    if geom_type == QgsWkbTypes.MultiPolygon:
        try:
            parts = geom.asMultiPolygon()
            if parts:
                for part in parts:
                    part_geom = QgsGeometry.fromPolygonXY(part)
                    if part_geom and part_geom.isGeosValid() and not part_geom.isEmpty():
                        area = part_geom.area()
                        if area > min_area:
                            polygon_parts.append(part_geom)
                if polygon_parts:
                    return polygon_parts
        except Exception:
            pass

    # Handle geometry that reports as multipart but might be Polygon type
    # This can happen after certain geometry operations
    if geom.isMultipart() and geom.type() == QgsWkbTypes.PolygonGeometry:
        try:
            # Try asMultiPolygon first
            parts = geom.asMultiPolygon()
            if parts:
                for part in parts:
                    part_geom = QgsGeometry.fromPolygonXY(part)
                    if part_geom and part_geom.isGeosValid() and not part_geom.isEmpty():
                        area = part_geom.area()
                        if area > min_area:
                            polygon_parts.append(part_geom)
                if polygon_parts:
                    return polygon_parts
        except Exception:
            pass

        # Fallback: try asGeometryCollection
        try:
            for part in geom.asGeometryCollection():
                if part and not part.isEmpty():
                    if part.type() == QgsWkbTypes.PolygonGeometry:
                        if part.isGeosValid():
                            area = part.area()
                            if area > min_area:
                                polygon_parts.append(QgsGeometry(part))
            if polygon_parts:
                return polygon_parts
        except Exception:
            pass

    # Handle single Polygon
    if geom_type == QgsWkbTypes.Polygon or \
       (geom.type() == QgsWkbTypes.PolygonGeometry and not geom.isMultipart()):
        if geom.isGeosValid() and not geom.isEmpty():
            area = geom.area()
            if area > min_area:
                return [QgsGeometry(geom)]

    # Last resort: if geometry is polygon type but we haven't extracted anything,
    # try to get it as a single polygon
    if geom.type() == QgsWkbTypes.PolygonGeometry and not polygon_parts:
        try:
            # Try to convert to single polygon
            if geom.isGeosValid() and not geom.isEmpty():
                area = geom.area()
                if area > min_area:
                    return [QgsGeometry(geom)]
        except Exception:
            pass

    return polygon_parts


def convert_geometry_to_layer_type(geom, layer_wkb_type, split_multipart=False, original_feature=None):
    """
    Convert geometry to match the layer's expected geometry type.

    Enhanced version that can split multipart geometries into separate features
    instead of keeping only the largest part. Handles edge cases like
    GeometryCollections and invalid geometries.

    Args:
        geom: QgsGeometry - the geometry to convert
        layer_wkb_type: QgsWkbTypes - the layer's WKB type
        split_multipart: bool - if True, split multipart into multiple features
        original_feature: QgsFeature - original feature for attribute copying

    Returns:
        If split_multipart=False: QgsGeometry - converted geometry matching layer type
        If split_multipart=True: list of QgsGeometry - all parts as separate geometries (ALWAYS a list)
    """
    if not geom or geom.isEmpty():
        return [] if split_multipart else geom

    # Get the geometry type of the result
    geom_type = geom.wkbType()

    # Handle invalid geometry - try to fix it first
    if not geom.isGeosValid():
        try:
            fixed_geom = geom.makeValid()
            if fixed_geom and fixed_geom.isGeosValid() and not fixed_geom.isEmpty():
                geom = fixed_geom
                geom_type = geom.wkbType()
            else:
                # Try buffer(0) as fallback
                buffered = geom.buffer(0.0, 8)
                if buffered and buffered.isGeosValid() and not buffered.isEmpty():
                    geom = buffered
                    geom_type = geom.wkbType()
        except Exception:
            pass

    # CRITICAL: When split_multipart is True, we MUST extract all polygon parts
    # regardless of other conditions. This ensures bisected polygons are always split.
    if split_multipart:
        # Always extract polygon parts when splitting is requested
        polygon_parts = extract_polygon_parts_from_geometry(geom)

        if not polygon_parts:
            # If extraction failed, try to return the geometry as a single-item list
            if geom and not geom.isEmpty() and geom.isGeosValid():
                # Ensure it's a proper polygon for the layer type
                if layer_wkb_type == QgsWkbTypes.Polygon and geom_type == QgsWkbTypes.MultiPolygon:
                    # Force extraction using asMultiPolygon
                    try:
                        parts = geom.asMultiPolygon()
                        if parts:
                            result = []
                            for part in parts:
                                part_geom = QgsGeometry.fromPolygonXY(part)
                                if part_geom and not part_geom.isEmpty():
                                    result.append(part_geom)
                            if result:
                                return result
                    except Exception:
                        pass
                return [geom]
            return []

        # Return all extracted parts as separate geometries
        return polygon_parts

    # Non-splitting mode below...

    # Handle GeometryCollection (can occur from difference operations)
    if geom_type in [QgsWkbTypes.GeometryCollection, QgsWkbTypes.Unknown] or \
       geom.type() == QgsWkbTypes.UnknownGeometry:
        polygon_parts = extract_polygon_parts_from_geometry(geom)

        if not polygon_parts:
            return None

        if len(polygon_parts) == 1:
            geom = polygon_parts[0]
            geom_type = geom.wkbType()
        else:
            # Multiple parts - find largest or combine based on layer type
            if layer_wkb_type == QgsWkbTypes.Polygon:
                # Keep only largest part
                largest_part = max(polygon_parts, key=lambda p: p.area())
                geom = largest_part
                geom_type = geom.wkbType()
            else:
                # Combine into MultiPolygon
                geom = QgsGeometry.unaryUnion(polygon_parts)
                geom_type = geom.wkbType()

    # If types already match, return as-is
    if geom_type == layer_wkb_type:
        return geom

    # Convert MultiPolygon to Polygon if layer expects Polygon (non-splitting mode)
    if layer_wkb_type == QgsWkbTypes.Polygon and (geom_type == QgsWkbTypes.MultiPolygon or geom.isMultipart()):
        polygon_parts = extract_polygon_parts_from_geometry(geom)

        if not polygon_parts:
            return None

        if len(polygon_parts) == 1:
            # Convert to single polygon
            return polygon_parts[0]
        else:
            # Multiple parts but not splitting - keep only the largest part
            largest_part = max(polygon_parts, key=lambda p: p.area())
            return largest_part

    # Convert Polygon to MultiPolygon if layer expects MultiPolygon
    if layer_wkb_type == QgsWkbTypes.MultiPolygon and geom_type == QgsWkbTypes.Polygon:
        try:
            # Convert single to multi
            multi_geom = QgsGeometry.fromMultiPolygonXY([geom.asPolygon()])
            return multi_geom
        except Exception:
            return geom

    return geom


def _is_layer_singlepart(layer):
    """Check if layer expects singlepart polygon geometries."""
    return layer.wkbType() in [
        QgsWkbTypes.Polygon, QgsWkbTypes.PolygonZ,
        QgsWkbTypes.PolygonM, QgsWkbTypes.PolygonZM,
        QgsWkbTypes.Polygon25D
    ]


def _create_split_features(clipped_geom, source_feature, layer, split_multipart,
                           uuid_field_name, result, total_splits):
    """
    Convert a clipped geometry into one or more features, optionally splitting
    multipart results into separate features.

    Args:
        clipped_geom: QgsGeometry - geometry after clipping
        source_feature: QgsFeature - original feature (for attribute copying)
        layer: QgsVectorLayer - target layer
        split_multipart: bool - whether to split multipart results
        uuid_field_name: str or None - UUID field for regeneration
        result: ClippingResult - result object to append features to
        total_splits: int - running total of splits

    Returns:
        tuple: (features_added: int, total_splits: int)
    """
    layer_is_singlepart = _is_layer_singlepart(layer)
    features_added = 0

    if split_multipart and layer_is_singlepart:
        converted_result = convert_geometry_to_layer_type(
            clipped_geom, layer.wkbType(), split_multipart=True, original_feature=source_feature
        )

        if converted_result:
            effective_uuid_field = uuid_field_name if len(converted_result) > 1 else None
            for geom_part in converted_result:
                if geom_part and not geom_part.isEmpty():
                    new_feature = QgsFeature(layer.fields())
                    copy_attributes_without_fid(source_feature, new_feature, layer, effective_uuid_field)
                    new_feature.setGeometry(geom_part)
                    result.clipped_features.append(new_feature)
                    features_added += 1

            if len(converted_result) > 1:
                total_splits += 1

        result.deleted_ids.append(source_feature.id())
    else:
        clipped_geom = convert_geometry_to_layer_type(clipped_geom, layer.wkbType())

        if clipped_geom and not clipped_geom.isEmpty():
            new_feature = QgsFeature(layer.fields())
            copy_attributes_without_fid(source_feature, new_feature, layer)
            new_feature.setGeometry(clipped_geom)
            result.clipped_features.append(new_feature)
            result.deleted_ids.append(source_feature.id())
            features_added += 1

    return features_added, total_splits


def auto_snap_geometry(target_geom, reference_geom, tolerance):
    """
    Automatically snap target geometry to reference geometry.

    Args:
        target_geom: QgsGeometry to be snapped
        reference_geom: QgsGeometry to snap to
        tolerance: float - snap distance in map units

    Returns:
        tuple: (snapped_geometry, was_snapped: bool)
    """
    if not target_geom or not reference_geom:
        return target_geom, False

    # Use QGIS geometry snapper (static method)
    snapped = QgsGeometrySnapper.snapGeometry(
        target_geom,
        tolerance,
        [reference_geom],
        QgsGeometrySnapper.PreferNodes
    )

    # Check if snapping actually changed the geometry
    was_snapped = not snapped.equals(target_geom)

    return snapped, was_snapped


def validate_layer_edit_mode(layer):
    """
    Check if layer is in edit mode and start edit mode if not.

    Args:
        layer: QgsVectorLayer

    Returns:
        tuple: (success, message)
    """
    if not layer:
        return False, "No layer provided"

    if not layer.isEditable():
        # Try to start edit mode
        if not layer.startEditing():
            return False, "Could not start edit mode. Layer may be read-only."

    return True, "Layer is in edit mode"


def validate_clip_all_selection(layer, selected_ids):
    """
    Validate selection for Clip All mode.

    Args:
        layer: QgsVectorLayer
        selected_ids: list of feature IDs

    Returns:
        tuple: (is_valid, error_message)
    """
    if not layer:
        return False, "No layer provided"

    if not selected_ids or len(selected_ids) == 0:
        return False, "Please select exactly 1 polygon as cutter"

    if len(selected_ids) > 1:
        return False, f"Too many selected ({len(selected_ids)}). Please select exactly 1 polygon"

    # Check if feature exists and has geometry
    feature = layer.getFeature(selected_ids[0])
    if not feature or not feature.hasGeometry():
        return False, f"Feature ID {selected_ids[0]} has no valid geometry"

    return True, None


def validate_clip_isolated_selection(cutter_ids, target_ids):
    """
    Validate selections for Clip Isolated mode.

    Args:
        cutter_ids: list of cutter feature IDs
        target_ids: list of target feature IDs

    Returns:
        tuple: (is_valid, error_message)
    """
    if not cutter_ids or len(cutter_ids) == 0:
        return False, "Please select at least 1 cutter polygon"

    if not target_ids or len(target_ids) == 0:
        return False, "Please select at least 1 target polygon"

    # Check for overlap between cutters and targets
    overlap = set(cutter_ids).intersection(set(target_ids))
    if overlap:
        return False, f"Features cannot be both cutter and target: {overlap}"

    return True, None


def clip_all_intersecting(layer, cutter_id, snap_tolerance=0.001, split_multipart=False, uuid_field_name=None):
    """
    Clip all features intersecting with a single cutter polygon.

    Args:
        layer: QgsVectorLayer
        cutter_id: int - feature ID of cutter
        snap_tolerance: float - snapping tolerance in map units
        split_multipart: bool - if True, split multipart results into separate features
        uuid_field_name: str or None - field name for UUID regeneration when splitting

    Returns:
        ClippingResult object
    """
    result = ClippingResult()

    # Ensure layer is in edit mode
    edit_ok, edit_msg = validate_layer_edit_mode(layer)
    if not edit_ok:
        result.error = edit_msg
        return result

    # Validate
    is_valid, error = validate_clip_all_selection(layer, [cutter_id])
    if not is_valid:
        result.error = error
        return result

    # Get cutter feature
    cutter = layer.getFeature(cutter_id)
    if not cutter or not cutter.hasGeometry():
        result.error = f"Cutter feature {cutter_id} has no geometry"
        return result

    cutter_geom = cutter.geometry()
    result.cutter_ids = [cutter_id]

    # Get bounding box for spatial filtering
    bbox = cutter_geom.boundingBox()
    request = QgsFeatureRequest(bbox)

    # Find all intersecting features
    snapped_feature_count = 0
    total_splits = 0

    for feature in layer.getFeatures(request):
        # Skip the cutter itself
        if feature.id() == cutter_id:
            continue

        # Check if feature has valid geometry
        if not feature.geometry():
            continue

        # Check if intersects
        if feature.geometry().intersects(cutter_geom):
            result.target_ids.append(feature.id())

            # Apply snapping to target
            target_geom = feature.geometry()
            snapped_geom, was_snapped = auto_snap_geometry(
                target_geom,
                cutter_geom,
                snap_tolerance
            )
            if was_snapped:
                snapped_feature_count += 1

            # Validate geometry before difference operation
            if not snapped_geom.isGeosValid():
                snapped_geom = snapped_geom.makeValid()

            # Calculate difference (clip operation)
            clipped_geom = snapped_geom.difference(cutter_geom)

            # Skip if the difference result is empty or invalid
            if not clipped_geom or clipped_geom.isEmpty():
                result.deleted_ids.append(feature.id())
                continue

            # Validate result - difference can produce self-intersecting geometries
            if not clipped_geom.isGeosValid():
                clipped_geom = clipped_geom.makeValid()

            added, total_splits = _create_split_features(
                clipped_geom, feature, layer, split_multipart,
                uuid_field_name, result, total_splits
            )
            result.clipped_count += added

    # Count unchanged features
    result.unchanged_count = layer.featureCount() - len(result.deleted_ids) - 1  # -1 for cutter
    result.snapped_count = snapped_feature_count
    result.split_count = total_splits
    result.success = True

    return result


def clip_isolated(layer, cutter_ids, target_ids, snap_tolerance=0.001, split_multipart=False, uuid_field_name=None):
    """
    Clip only specified target features against cutter features.
    All other features remain unchanged.

    Args:
        layer: QgsVectorLayer
        cutter_ids: list of int - cutter feature IDs
        target_ids: list of int - target feature IDs
        snap_tolerance: float - snapping tolerance in map units
        split_multipart: bool - if True, split multipart results into separate features
        uuid_field_name: str or None - field name for UUID regeneration when splitting

    Returns:
        ClippingResult object
    """
    result = ClippingResult()

    # Ensure layer is in edit mode
    edit_ok, edit_msg = validate_layer_edit_mode(layer)
    if not edit_ok:
        result.error = edit_msg
        return result

    # Validate
    is_valid, error = validate_clip_isolated_selection(cutter_ids, target_ids)
    if not is_valid:
        result.error = error
        return result

    result.cutter_ids = list(cutter_ids)
    result.target_ids = list(target_ids)

    # Get all cutter geometries and combine them
    cutter_geoms = []
    for cutter_id in cutter_ids:
        cutter = layer.getFeature(cutter_id)
        if cutter and cutter.hasGeometry():
            cutter_geoms.append(cutter.geometry())

    if not cutter_geoms:
        result.error = "No valid cutter geometries found"
        return result

    # Combine all cutter geometries into one using unaryUnion for efficiency
    combined_cutter = QgsGeometry.unaryUnion(cutter_geoms)

    # Process each target
    snapped_feature_count = 0
    total_splits = 0

    for target_id in target_ids:
        target = layer.getFeature(target_id)
        if not target or not target.hasGeometry():
            continue

        target_geom = target.geometry()

        # Check if target intersects combined cutter
        if not target_geom.intersects(combined_cutter):
            continue

        # Apply snapping
        snapped_geom, was_snapped = auto_snap_geometry(
            target_geom,
            combined_cutter,
            snap_tolerance
        )
        if was_snapped:
            snapped_feature_count += 1

        # Validate geometry before difference operation
        if not snapped_geom.isGeosValid():
            snapped_geom = snapped_geom.makeValid()

        # Calculate difference (clip operation)
        clipped_geom = snapped_geom.difference(combined_cutter)

        # Skip if the difference result is empty or invalid
        if not clipped_geom or clipped_geom.isEmpty():
            result.deleted_ids.append(target_id)
            continue

        # Validate result - difference can produce self-intersecting geometries
        if not clipped_geom.isGeosValid():
            clipped_geom = clipped_geom.makeValid()

        added, total_splits = _create_split_features(
            clipped_geom, target, layer, split_multipart,
            uuid_field_name, result, total_splits
        )
        result.clipped_count += added

    # Count unchanged features (total - deleted - cutters)
    result.unchanged_count = layer.featureCount() - len(result.deleted_ids) - len(cutter_ids)
    result.snapped_count = snapped_feature_count
    result.split_count = total_splits
    result.success = True

    return result


def clip_small_into_large(layer, selected_ids, snap_tolerance=0.001, split_multipart=False, uuid_field_name=None):
    """
    Automatically clip smaller polygons into larger polygons they intersect.
    Perfect for geological mapping where small features sit on top of larger units.

    Algorithm:
    1. Calculate area for all selected polygons
    2. Sort by area (smallest to largest)
    3. For each small polygon, find larger polygons it intersects
    4. Clip the small polygon out of each larger polygon

    Args:
        layer: QgsVectorLayer
        selected_ids: list of int - all selected feature IDs
        snap_tolerance: float - snapping tolerance in map units
        split_multipart: bool - if True, split multipart results into separate features
        uuid_field_name: str or None - field name for UUID regeneration when splitting

    Returns:
        ClippingResult object
    """
    result = ClippingResult()

    # Ensure layer is in edit mode
    edit_ok, edit_msg = validate_layer_edit_mode(layer)
    if not edit_ok:
        result.error = edit_msg
        return result

    # Validate
    if not layer:
        result.error = "No layer provided"
        return result

    if not selected_ids or len(selected_ids) < 2:
        result.error = "Please select at least 2 polygons (needs both small and large)"
        return result

    # Get all selected features with their areas
    features_with_area = []
    for fid in selected_ids:
        feature = layer.getFeature(fid)
        if not feature or not feature.hasGeometry():
            continue

        area = feature.geometry().area()
        features_with_area.append({
            'id': fid,
            'feature': feature,
            'area': area,
            'geometry': feature.geometry()
        })

    if len(features_with_area) < 2:
        result.error = "Need at least 2 valid polygon features"
        return result

    # Sort by area (smallest first)
    features_with_area.sort(key=lambda x: x['area'])

    # Build spatial index for efficient bbox pre-filtering
    spatial_index = QgsSpatialIndex()
    feature_lookup = {}
    for item in features_with_area:
        feat = item['feature']
        spatial_index.addFeature(feat)
        feature_lookup[item['id']] = item

    # Track modifications to each feature
    # Key: feature ID, Value: list of modified geometries (for splitting support)
    # IMPORTANT: Now always stores lists to handle multiple geometries consistently
    modified_geometries = {}

    # Track which features are clippers (small) vs clipped (large)
    small_polygon_ids = []
    large_polygon_ids = []

    snapped_feature_count = 0
    total_clip_operations = 0
    total_splits = 0

    # Process each polygon from smallest to largest
    for i, small_poly in enumerate(features_with_area):
        small_id = small_poly['id']
        small_geom = small_poly['geometry']
        small_area = small_poly['area']

        # Check if this polygon clips any larger polygons
        clipped_any = False

        # Use spatial index to find candidate larger polygons by bounding box
        candidate_ids = set(spatial_index.intersects(small_geom.boundingBox()))

        # Check against all larger polygons
        for j in range(i + 1, len(features_with_area)):
            large_poly = features_with_area[j]
            large_id = large_poly['id']
            large_area = large_poly['area']

            # Skip if bounding boxes don't intersect (spatial index pre-filter)
            if large_id not in candidate_ids:
                continue

            # Skip if areas are too similar (within 1%)
            # This prevents clipping when polygons are similar size
            if small_area > large_area * 0.99:
                continue

            # Get the current geometries of the large polygon
            # IMPORTANT: Process ALL parts if the polygon has been split
            if large_id in modified_geometries:
                current_geometries = modified_geometries[large_id]
            else:
                # Initialize with original geometry as a list
                current_geometries = [large_poly['geometry']]

            # Process each part of the large polygon
            new_geometries = []
            any_intersection = False

            for large_geom in current_geometries:
                # Check if they intersect
                if not small_geom.intersects(large_geom):
                    # No intersection, keep this part unchanged
                    new_geometries.append(large_geom)
                    continue

                # Apply snapping to small polygon against large polygon
                snapped_small_geom, was_snapped = auto_snap_geometry(
                    small_geom,
                    large_geom,
                    snap_tolerance
                )
                if was_snapped:
                    snapped_feature_count += 1

                # Validate geometry before difference operation
                if not large_geom.isGeosValid():
                    large_geom = large_geom.makeValid()

                # Clip small polygon out of large polygon (difference operation)
                clipped_large_geom = large_geom.difference(snapped_small_geom)

                # Skip if the difference result is empty
                if not clipped_large_geom or clipped_large_geom.isEmpty():
                    any_intersection = True  # Still counts as intersection even if nothing remains
                    continue

                # Validate result - difference can produce self-intersecting geometries
                if not clipped_large_geom.isGeosValid():
                    clipped_large_geom = clipped_large_geom.makeValid()

                if split_multipart and _is_layer_singlepart(layer):
                    # Always use split mode to extract all polygon parts
                    converted_result = convert_geometry_to_layer_type(
                        clipped_large_geom,
                        layer.wkbType(),
                        split_multipart=True,
                        original_feature=large_poly['feature']
                    )

                    # converted_result is ALWAYS a list when split_multipart=True
                    if converted_result:
                        for geom_part in converted_result:
                            if geom_part and not geom_part.isEmpty():
                                new_geometries.append(geom_part)
                        if len(converted_result) > 1:
                            total_splits += 1

                    any_intersection = True
                else:
                    # Original behavior - keep largest part or combine
                    clipped_large_geom = convert_geometry_to_layer_type(
                        clipped_large_geom,
                        layer.wkbType()
                    )

                    # Store the modified geometry
                    if clipped_large_geom and not clipped_large_geom.isEmpty():
                        new_geometries.append(clipped_large_geom)
                    any_intersection = True

            # Update the modified geometries for this large polygon
            if any_intersection:
                modified_geometries[large_id] = new_geometries
                clipped_any = True
                total_clip_operations += 1

                # Track this as a large polygon being clipped
                if large_id not in large_polygon_ids:
                    large_polygon_ids.append(large_id)

        # Track if this polygon clipped anything
        if clipped_any:
            small_polygon_ids.append(small_id)

    # Build result
    if not modified_geometries:
        result.error = "No intersections found. No small polygons overlap larger ones."
        return result

    # Create new features for modified polygons
    for large_id, geometries in modified_geometries.items():
        original_feature = layer.getFeature(large_id)

        # Only regenerate UUID if we're splitting into multiple parts
        effective_uuid_field = uuid_field_name if len(geometries) > 1 else None

        # Create a feature for each geometry
        for geom_part in geometries:
            if geom_part and not geom_part.isEmpty():
                new_feature = QgsFeature(layer.fields())
                copy_attributes_without_fid(original_feature, new_feature, layer, effective_uuid_field)
                new_feature.setGeometry(geom_part)
                result.clipped_features.append(new_feature)

        result.deleted_ids.append(large_id)

    # Set result metadata
    result.cutter_ids = small_polygon_ids  # Small polygons doing the clipping
    result.target_ids = large_polygon_ids  # Large polygons being clipped
    result.clipped_count = len(result.clipped_features)
    result.unchanged_count = layer.featureCount() - len(result.deleted_ids)
    result.snapped_count = snapped_feature_count
    result.split_count = total_splits
    result.success = True

    return result


def get_layer_polygon_count(layer):
    """
    Get count of polygon features in layer.

    Args:
        layer: QgsVectorLayer

    Returns:
        int: feature count
    """
    if not layer:
        return 0

    # Check if layer is polygon type
    if layer.wkbType() not in [QgsWkbTypes.Polygon, QgsWkbTypes.MultiPolygon]:
        return 0

    return layer.featureCount()


def find_polygon_overlaps(layer, progress_dialog=None):
    """
    Find all overlapping areas between polygons in a layer.
    Returns only the intersection geometries (overlapping regions).

    Uses a spatial index for efficient bounding-box pre-filtering to avoid
    O(n^2) brute-force comparison.

    Args:
        layer: QgsVectorLayer - polygon layer to analyze
        progress_dialog: QProgressDialog or None - for cancellation support

    Returns:
        ClippingResult object with overlap geometries in clipped_features
    """
    result = ClippingResult()

    if not layer:
        result.error = "No layer provided"
        return result

    # Build spatial index and feature lookup
    features = {}
    spatial_index = QgsSpatialIndex()
    for feature in layer.getFeatures():
        if feature.hasGeometry():
            spatial_index.addFeature(feature)
            features[feature.id()] = feature

    total_features = len(features)

    if total_features < 2:
        result.error = "Layer must have at least 2 polygons to check for overlaps"
        return result

    # Build fields for overlap features (source fields + _type classification)
    overlap_fields = QgsFields()
    for field in layer.fields():
        overlap_fields.append(field)
    overlap_fields.append(QgsField('_type', QVariant.String))

    overlap_features = []
    overlap_count = 0
    bisecting_count = 0
    checked_pairs = set()

    # Use spatial index to find candidate pairs efficiently
    for idx, (fid_a, feature_a) in enumerate(features.items()):
        if progress_dialog:
            progress_dialog.setValue(idx)
            if progress_dialog.wasCanceled():
                break

        geom_a = feature_a.geometry()
        bbox_a = geom_a.boundingBox()

        # Find candidate features whose bounding boxes intersect
        candidate_ids = spatial_index.intersects(bbox_a)

        for fid_b in candidate_ids:
            # Skip self and already-checked pairs
            if fid_b <= fid_a:
                continue

            pair_key = (fid_a, fid_b)
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)

            feature_b = features[fid_b]
            geom_b = feature_b.geometry()

            # Check actual geometric intersection
            if geom_a.intersects(geom_b):
                intersection = geom_a.intersection(geom_b)

                # Only keep polygon intersections (ignore line/point touches)
                if not intersection.isEmpty() and intersection.type() == QgsWkbTypes.PolygonGeometry:
                    intersection = convert_geometry_to_layer_type(intersection, layer.wkbType())

                    # Classify: check if clipping would bisect either polygon
                    is_bisecting = False
                    try:
                        diff_a = geom_a.difference(geom_b)
                        diff_b = geom_b.difference(geom_a)
                        if (diff_a and not diff_a.isEmpty() and diff_a.isMultipart()) or \
                           (diff_b and not diff_b.isEmpty() and diff_b.isMultipart()):
                            is_bisecting = True
                    except Exception:
                        pass

                    overlap_type = "bisecting" if is_bisecting else "simple"

                    overlap_feature = QgsFeature(overlap_fields)
                    overlap_feature.setGeometry(intersection)
                    # Set _type as the last attribute
                    attrs = [None] * (overlap_fields.count() - 1) + [overlap_type]
                    overlap_feature.setAttributes(attrs)

                    overlap_features.append(overlap_feature)
                    overlap_count += 1
                    if is_bisecting:
                        bisecting_count += 1

    # Build result
    if overlap_count == 0:
        result.error = "No overlaps found. All polygons are non-overlapping."
        return result

    result.clipped_features = overlap_features
    result.clipped_count = overlap_count
    result.bisecting_count = bisecting_count
    result.success = True

    return result


def find_polygon_slivers(layer, max_area, min_area=0.0, snap_tolerance=0.001, progress_dialog=None):
    """
    Find small enclosed gaps (slivers) between polygons in a layer.

    Unions all polygon features; any interior ring of the union whose area
    is in [min_area, max_area] is returned as a sliver polygon.

    Args:
        layer: QgsVectorLayer - polygon layer to analyze
        max_area: float - maximum gap area (in layer units) to flag as sliver
        min_area: float - minimum gap area (in layer units); smaller gaps are
            ignored. 0 includes the very smallest gaps.
        snap_tolerance: float - grid-snap distance applied before union to
            suppress micro-gaps from floating-point noise on shared edges.
            0 disables snapping.
        progress_dialog: QProgressDialog or None - for cancellation support

    Returns:
        ClippingResult object with sliver geometries in clipped_features
    """
    result = ClippingResult()

    if not layer:
        result.error = "No layer provided"
        return result

    if layer.wkbType() not in (QgsWkbTypes.Polygon, QgsWkbTypes.MultiPolygon):
        result.error = "Layer must be a polygon layer"
        return result

    geoms = []
    for f in layer.getFeatures():
        if not f.hasGeometry():
            continue
        g = f.geometry()
        if g.isEmpty():
            continue
        if snap_tolerance and snap_tolerance > 0:
            snapped = g.snappedToGrid(snap_tolerance, snap_tolerance)
            if snapped is not None and not snapped.isEmpty():
                g = snapped
        geoms.append(g)

    if len(geoms) < 2:
        result.error = "Layer must have at least 2 polygons to check for slivers"
        return result

    union = QgsGeometry.unaryUnion(geoms)
    if union is None or union.isEmpty():
        result.error = "Union produced no geometry"
        return result

    sliver_fields = QgsFields()
    for field in layer.fields():
        sliver_fields.append(field)
    sliver_fields.append(QgsField('_type', QVariant.String))

    sliver_features = []
    for part in union.asGeometryCollection():
        rings = part.asPolygon()
        if not rings or len(rings) < 2:
            continue
        for hole_ring in rings[1:]:
            hole_geom = QgsGeometry.fromPolygonXY([hole_ring])
            if hole_geom.isEmpty():
                continue
            area = hole_geom.area()
            if area < MIN_AREA_THRESHOLD or area < min_area or area > max_area:
                continue
            if layer.wkbType() == QgsWkbTypes.MultiPolygon:
                hole_geom.convertToMultiType()
            feat = QgsFeature(sliver_fields)
            feat.setGeometry(hole_geom)
            attrs = [None] * (sliver_fields.count() - 1) + ['sliver']
            feat.setAttributes(attrs)
            sliver_features.append(feat)

    if not sliver_features:
        result.error = f"No slivers found in area range [{min_area}, {max_area}]."
        return result

    result.clipped_features = sliver_features
    result.clipped_count = len(sliver_features)
    result.success = True

    return result