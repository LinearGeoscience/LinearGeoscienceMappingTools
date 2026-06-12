# -*- coding: utf-8 -*-
"""
/***************************************************************************
                  Map Cleaning Toolkit - Geometry Fixer Engine
                              -------------------
        begin                : 2025-10-31
        copyright            : (C) 2025 Linear Geoscience

        Based on QGIS Geometry Fixer Plugin
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from qgis.core import QgsGeometry, QgsWkbTypes, Qgis, QgsPointXY, QgsRectangle
import math

from .utils import MIN_AREA_THRESHOLD


class GeometryIssue:
    """Container for geometry issue information"""
    def __init__(self, fid, issue_type, description, geometry):
        self.fid = fid
        self.issue_type = issue_type  # 'invalid', 'multipart', 'empty', etc.
        self.description = description
        self.geometry = geometry  # QgsGeometry for highlighting


class GeometryFixerEngine:
    """
    Engine class with SAFE geometry fixing logic.
    PRIORITY: Data integrity - never corrupt or lose data.
    Enhanced to handle collapsed geometries and delete unrecoverable zero-area features.
    """

    def __init__(self, layer, log_func, delete_zero_area=True, zero_area_threshold=MIN_AREA_THRESHOLD):
        """
        Initialize the engine.

        Args:
            layer: QgsVectorLayer to work on
            log_func: Function to log messages
            delete_zero_area: If True, delete features that have zero area and can't be recovered
            zero_area_threshold: Area below this is considered zero (default 1e-10)
        """
        self.layer = layer
        self.log = log_func
        self.delete_zero_area = delete_zero_area
        self.zero_area_threshold = zero_area_threshold
        self.original_geometries = {}  # Store original geometries for recovery
        self.features_to_delete = []  # Track features that should be deleted

    def fix_all_geometries(self, progress_dialog=None):
        """
        Fix all geometries in the layer safely.

        Returns:
            dict with statistics about the operation
        """
        results = {
            'processed': 0,
            'fixed': 0,
            'converted': 0,
            'duplicates_removed': 0,
            'recovered': 0,
            'deleted': 0,
            'already_valid': 0,
            'failed': 0,
            'failed_fids': [],
            'deleted_fids': []
        }

        features = list(self.layer.getFeatures())
        total = len(features)

        # Store original geometries for recovery attempts
        for feature in features:
            self.original_geometries[feature.id()] = QgsGeometry(feature.geometry())

        # Clear the deletion list
        self.features_to_delete = []

        for idx, feature in enumerate(features):
            # Update progress
            if progress_dialog:
                progress_dialog.setValue(idx)
                if progress_dialog.wasCanceled():
                    self.log("Operation cancelled by user", Qgis.Warning)
                    break

            fid = feature.id()
            geom = feature.geometry()

            results['processed'] += 1

            # Process this feature with enhanced recovery
            success, was_fixed, was_converted, duplicates_removed, was_recovered, should_delete = \
                self.fix_single_feature_enhanced(fid, geom)

            if should_delete:
                self.features_to_delete.append(fid)
                results['deleted'] += 1
                results['deleted_fids'].append(fid)
                self.log(f"Feature {fid}: Marked for deletion (zero area, unrecoverable)", Qgis.Warning)
            elif success:
                if was_fixed:
                    results['fixed'] += 1
                if was_converted:
                    results['converted'] += 1
                if duplicates_removed:
                    results['duplicates_removed'] += 1
                if was_recovered:
                    results['recovered'] += 1
                if not was_fixed and not was_converted and not duplicates_removed and not was_recovered:
                    results['already_valid'] += 1
            else:
                results['failed'] += 1
                results['failed_fids'].append(fid)

        # Delete features marked for deletion
        if self.features_to_delete and self.delete_zero_area:
            self.log(f"Deleting {len(self.features_to_delete)} zero-area features", Qgis.Warning)
            self.layer.deleteFeatures(self.features_to_delete)

        if progress_dialog:
            progress_dialog.setValue(total)

        return results

    def fix_single_feature_enhanced(self, fid, original_geom):
        """
        Enhanced feature fixing with better recovery strategies and deletion option.

        Returns:
            Tuple (success, was_fixed, was_converted, duplicates_removed, was_recovered, should_delete)
        """
        # Skip truly null/empty geometries first
        if not original_geom or original_geom.isNull():
            # Try to recover from backup
            recovered_geom = self.recover_null_geometry(fid)
            if recovered_geom:
                success = self.layer.changeGeometry(fid, recovered_geom)
                if success:
                    self.log(f"Feature {fid}: Recovered null geometry using bounding box")
                    return True, False, False, False, True, False
            else:
                # Can't recover null geometry - mark for deletion if enabled
                if self.delete_zero_area:
                    return False, False, False, False, False, True
                else:
                    self.log(f"Feature {fid}: Null geometry, cannot recover", Qgis.Warning)
                    return False, False, False, False, False, False

        # Work on a copy to preserve original
        geom = QgsGeometry(original_geom)
        backup_geom = QgsGeometry(original_geom)  # Keep a backup
        was_fixed = False
        was_converted = False
        duplicates_removed = False
        was_recovered = False

        # Step 1: Fix invalid geometry (if needed)
        if not geom.isGeosValid():
            fixed_geom = self.make_geometry_valid_aggressive(geom, fid)
            if not fixed_geom:
                # Try recovery from original
                fixed_geom = self.recover_geometry(backup_geom, fid)
                if fixed_geom:
                    was_recovered = True
                else:
                    # Can't fix - check if we should delete
                    if self.should_delete_feature(geom, fid):
                        return False, False, False, False, False, True
                    return False, False, False, False, False, False
            geom = fixed_geom
            was_fixed = True

        # Step 2: Convert multipart to singlepart
        if geom.isMultipart():
            converted_geom = self.convert_to_singlepart_safe(geom, fid)
            if converted_geom:
                geom = converted_geom
                was_converted = True

        # Step 3: Carefully remove duplicate vertices
        geom_after_duplicates = self.remove_duplicates_safe(geom, fid, backup_geom)
        if geom_after_duplicates:
            if geom_after_duplicates != geom:
                duplicates_removed = True
                geom = geom_after_duplicates
        else:
            # Duplicate removal failed, try to recover
            geom = self.recover_geometry(backup_geom, fid)
            if geom:
                was_recovered = True
            else:
                # Can't recover - check if we should delete
                if self.should_delete_feature(backup_geom, fid):
                    return False, False, False, False, False, True
                return False, False, False, False, False, False

        # Step 4: Final validation with deletion check
        if not self.validate_geometry_strict(geom, fid):
            # Check if it's a zero-area feature that should be deleted
            if self.should_delete_feature(geom, fid):
                return False, False, False, False, False, True

            # Try to recover the geometry
            recovered_geom = self.recover_geometry(backup_geom, fid)
            if recovered_geom and self.validate_geometry_strict(recovered_geom, fid):
                geom = recovered_geom
                was_recovered = True
                self.log(f"Feature {fid}: Recovered geometry after validation failure")
            else:
                # Final check - should we delete?
                if self.should_delete_feature(backup_geom, fid):
                    return False, False, False, False, False, True
                self.log(f"Feature {fid}: Final validation failed, cannot recover", Qgis.Critical)
                return False, False, False, False, False, False

        # Step 5: Apply the changes
        if was_fixed or was_converted or duplicates_removed or was_recovered:
            success = self.layer.changeGeometry(fid, geom)
            if not success:
                self.log(f"Feature {fid}: Failed to apply geometry changes", Qgis.Critical)
                return False, False, False, False, False, False

            # Log what was actually changed
            changes = []
            if was_fixed:
                changes.append("made valid")
            if was_converted:
                changes.append("converted to singlepart")
            if duplicates_removed:
                changes.append("removed duplicates")
            if was_recovered:
                changes.append("recovered")

            if changes:
                self.log(f"Feature {fid}: {', '.join(changes)}")

        return True, was_fixed, was_converted, duplicates_removed, was_recovered, False

    def should_delete_feature(self, geom, fid):
        """
        Determine if a feature should be deleted based on its geometry.

        Returns:
            True if feature should be deleted, False otherwise
        """
        if not self.delete_zero_area:
            return False

        if not geom or geom.isNull() or geom.isEmpty():
            return True

        # Check for zero area polygons
        if geom.type() == QgsWkbTypes.PolygonGeometry:
            try:
                area = geom.area()
                if area <= self.zero_area_threshold:
                    self.log(f"Feature {fid}: Zero area ({area}), marking for deletion", Qgis.Warning)
                    return True
            except Exception:
                pass

        return False

    def remove_duplicates_safe(self, geom, fid, backup_geom):
        """
        Safely remove duplicate vertices with collapse prevention.

        Returns:
            QgsGeometry if successful, None if failed
        """
        try:
            # Make a copy to test
            test_geom = QgsGeometry(geom)

            # Count vertices before
            vertex_count_before = len(list(test_geom.vertices()))

            # Try different epsilon values starting with smallest
            epsilons = [0.00001, 0.0001, 0.001, 0.01]

            for epsilon in epsilons:
                test_geom = QgsGeometry(geom)  # Reset for each attempt
                test_geom.removeDuplicateNodes(epsilon=epsilon, useZValues=False)

                vertex_count_after = len(list(test_geom.vertices()))

                if vertex_count_after < vertex_count_before:
                    # Check if the geometry is still valid after removal
                    if test_geom.isGeosValid() and not test_geom.isEmpty():
                        # Check area hasn't collapsed to zero
                        if test_geom.type() == QgsWkbTypes.PolygonGeometry:
                            area = test_geom.area()
                            if area > self.zero_area_threshold:
                                duplicate_count = vertex_count_before - vertex_count_after
                                self.log(f"Feature {fid}: Removed {duplicate_count} duplicate vertices (epsilon={epsilon})")
                                return test_geom
                            else:
                                # Try to recover from collapse
                                recovered = self.recover_collapsed_polygon(test_geom, backup_geom, fid)
                                if recovered:
                                    return recovered
                                # If we can't recover and delete_zero_area is True,
                                # return None to trigger deletion
                                if self.delete_zero_area:
                                    return None
                        else:
                            return test_geom

            # No duplicates found or removal would cause issues
            return geom

        except Exception as e:
            self.log(f"Feature {fid}: Error removing duplicate nodes: {str(e)}", Qgis.Warning)
            return None

    def recover_collapsed_polygon(self, collapsed_geom, original_geom, fid):
        """
        Try to recover a polygon that collapsed during duplicate removal.
        Improved to avoid creating new duplicate vertices.

        Returns:
            QgsGeometry if successful, None if failed
        """
        self.log(f"Feature {fid}: Attempting to recover collapsed polygon")

        # Method 1: Small buffer to recreate area (with simplification to avoid duplicates)
        try:
            # Use a very small buffer
            buffered = collapsed_geom.buffer(0.0001, 8)  # More segments for smoother result
            if buffered and not buffered.isEmpty() and buffered.isGeosValid():
                # Simplify to remove any duplicate vertices created by buffering
                simplified = buffered.simplify(0.00005)  # Half the buffer distance
                if simplified and not simplified.isEmpty() and simplified.isGeosValid():
                    area = simplified.area()
                    if area > self.zero_area_threshold:
                        self.log(f"Feature {fid}: Recovered collapsed polygon with small buffer and simplification")
                        return simplified
        except Exception as e:
            pass

        # Method 2: Use convex hull of original
        try:
            convex = original_geom.convexHull()
            if convex and not convex.isEmpty() and convex.isGeosValid():
                area = convex.area()
                if area > self.zero_area_threshold:
                    self.log(f"Feature {fid}: Recovered using convex hull")
                    return convex
        except Exception as e:
            pass

        # Method 3: Use bounding box
        try:
            bbox = original_geom.boundingBox()
            if not bbox.isEmpty():
                bbox_geom = QgsGeometry.fromRect(bbox)
                if bbox_geom and bbox_geom.isGeosValid():
                    area = bbox_geom.area()
                    if area > self.zero_area_threshold:
                        self.log(f"Feature {fid}: Recovered using bounding box")
                        return bbox_geom
        except Exception as e:
            pass

        return None

    def make_geometry_valid_aggressive(self, geom, fid):
        """
        Aggressively try to make an invalid geometry valid using multiple methods.
        Handles various geometry errors including:
        - Self-intersections
        - Ring not in exterior (holes extending outside polygon boundary)
        - Duplicate vertices
        - Invalid ring order

        Returns:
            QgsGeometry if successful, None if failed
        """
        # First, check what type of error we're dealing with
        validation_errors = geom.validateGeometry()
        error_type = validation_errors[0].what() if validation_errors else ""

        # Method 1: Try makeValid() - this handles most issues including ring problems
        try:
            valid_geom = geom.makeValid()
            if valid_geom and not valid_geom.isEmpty() and valid_geom.isGeosValid():
                area = valid_geom.area() if valid_geom.type() == QgsWkbTypes.PolygonGeometry else 1
                if area > self.zero_area_threshold:
                    self.log(f"Feature {fid}: Fixed using makeValid()")
                    return valid_geom
        except Exception as e:
            self.log(f"Feature {fid}: makeValid() failed: {str(e)}", Qgis.Warning)

        # Method 2: For "ring not in exterior" errors - remove interior rings entirely
        if "ring" in error_type.lower() and "exterior" in error_type.lower():
            try:
                fixed_geom = self.fix_ring_not_in_exterior(geom, fid)
                if fixed_geom and fixed_geom.isGeosValid():
                    area = fixed_geom.area() if fixed_geom.type() == QgsWkbTypes.PolygonGeometry else 1
                    if area > self.zero_area_threshold:
                        self.log(f"Feature {fid}: Fixed ring-in-exterior issue by removing problematic holes")
                        return fixed_geom
            except Exception as e:
                self.log(f"Feature {fid}: Ring fix failed: {str(e)}", Qgis.Warning)

        # Method 3: Buffer(0) - classic fix for self-intersections
        try:
            buffered = geom.buffer(0.0, 8)
            if buffered and not buffered.isEmpty() and buffered.isGeosValid():
                area = buffered.area() if buffered.type() == QgsWkbTypes.PolygonGeometry else 1
                if area > self.zero_area_threshold:
                    self.log(f"Feature {fid}: Fixed using buffer(0)")
                    return buffered
        except Exception as e:
            pass

        # Method 4: Small positive buffer with simplification
        buffer_sizes = [0.00001, 0.0001, 0.001, 0.01]
        for buffer_size in buffer_sizes:
            try:
                buffered = geom.buffer(buffer_size, 8)
                if buffered and not buffered.isEmpty() and buffered.isGeosValid():
                    # Try to shrink back and simplify
                    shrunk = buffered.buffer(-buffer_size * 0.9, 8)
                    if shrunk and not shrunk.isEmpty() and shrunk.isGeosValid():
                        simplified = shrunk.simplify(buffer_size * 0.5)
                        if simplified and simplified.isGeosValid():
                            area = simplified.area() if simplified.type() == QgsWkbTypes.PolygonGeometry else 1
                            if area > self.zero_area_threshold:
                                self.log(f"Feature {fid}: Fixed using buffer {buffer_size} with simplification")
                                return simplified
            except Exception as e:
                pass

        # Method 5: Simplify geometry
        try:
            simplified = geom.simplify(0.0001)
            if simplified and not simplified.isEmpty() and simplified.isGeosValid():
                area = simplified.area() if simplified.type() == QgsWkbTypes.PolygonGeometry else 1
                if area > self.zero_area_threshold:
                    self.log(f"Feature {fid}: Fixed using simplification")
                    return simplified
        except Exception as e:
            pass

        # Method 6: Extract exterior ring only (removes all holes) - last resort for polygons
        if geom.type() == QgsWkbTypes.PolygonGeometry:
            try:
                exterior_only = self.extract_exterior_ring_as_polygon(geom, fid)
                if exterior_only and exterior_only.isGeosValid():
                    area = exterior_only.area()
                    if area > self.zero_area_threshold:
                        self.log(f"Feature {fid}: Fixed by extracting exterior ring only (holes removed)")
                        return exterior_only
            except Exception as e:
                pass

        self.log(f"Feature {fid}: Could not make geometry valid with any method", Qgis.Critical)
        return None

    def fix_ring_not_in_exterior(self, geom, fid):
        """
        Fix 'ring not in exterior' errors by validating each interior ring
        and keeping only those that are properly contained within the exterior.

        Returns:
            QgsGeometry if successful, None if failed
        """
        try:
            from qgis.core import QgsPolygon, QgsMultiPolygon

            # Handle multipart geometries
            if geom.isMultipart():
                parts = geom.asMultiPolygon()
                fixed_parts = []
                for part in parts:
                    fixed_part = self.fix_single_polygon_rings(part, fid)
                    if fixed_part:
                        fixed_parts.append(fixed_part)
                if fixed_parts:
                    return QgsGeometry.fromMultiPolygonXY(fixed_parts)
                return None
            else:
                # Single polygon
                polygon = geom.asPolygon()
                fixed_polygon = self.fix_single_polygon_rings(polygon, fid)
                if fixed_polygon:
                    return QgsGeometry.fromPolygonXY(fixed_polygon)
                return None
        except Exception as e:
            self.log(f"Feature {fid}: Error fixing ring: {str(e)}", Qgis.Warning)
            return None

    def fix_single_polygon_rings(self, polygon_rings, fid):
        """
        Fix a single polygon's rings by removing invalid interior rings.

        Args:
            polygon_rings: List of rings [exterior, interior1, interior2, ...]
            fid: Feature ID for logging

        Returns:
            Fixed polygon rings list, or None if failed
        """
        if not polygon_rings or len(polygon_rings) == 0:
            return None

        exterior_ring = polygon_rings[0]
        if not exterior_ring or len(exterior_ring) < 4:
            return None

        # Create exterior polygon for containment testing
        exterior_geom = QgsGeometry.fromPolygonXY([exterior_ring])
        if not exterior_geom or not exterior_geom.isGeosValid():
            # Try to fix exterior ring itself
            exterior_geom = exterior_geom.makeValid() if exterior_geom else None
            if not exterior_geom or not exterior_geom.isGeosValid():
                return None

        # Start with just the exterior ring
        fixed_rings = [exterior_ring]

        # Check each interior ring (hole)
        for i, interior_ring in enumerate(polygon_rings[1:], 1):
            if not interior_ring or len(interior_ring) < 4:
                self.log(f"Feature {fid}: Skipping invalid interior ring {i} (too few points)")
                continue

            # Create geometry for this interior ring
            interior_geom = QgsGeometry.fromPolygonXY([interior_ring])

            if not interior_geom:
                continue

            # Check if the interior ring is entirely within the exterior
            try:
                if exterior_geom.contains(interior_geom):
                    # Interior ring is valid - keep it
                    fixed_rings.append(interior_ring)
                else:
                    # Try to clip the interior ring to the exterior
                    clipped = interior_geom.intersection(exterior_geom)
                    if clipped and not clipped.isEmpty() and clipped.isGeosValid():
                        # Check if the clipped result is still a valid hole
                        if clipped.type() == QgsWkbTypes.PolygonGeometry:
                            clipped_polygon = clipped.asPolygon()
                            if clipped_polygon and len(clipped_polygon) > 0:
                                clipped_ring = clipped_polygon[0]
                                if len(clipped_ring) >= 4:
                                    fixed_rings.append(clipped_ring)
                                    self.log(f"Feature {fid}: Clipped interior ring {i} to fit exterior")
                                    continue
                    # If clipping didn't work, just skip this hole
                    self.log(f"Feature {fid}: Removed interior ring {i} (not contained in exterior)")
            except Exception as e:
                self.log(f"Feature {fid}: Error checking interior ring {i}: {str(e)}")
                continue

        return fixed_rings if len(fixed_rings) > 0 else None

    def extract_exterior_ring_as_polygon(self, geom, fid):
        """
        Extract just the exterior ring as a polygon, removing all holes.

        Returns:
            QgsGeometry (polygon without holes) if successful, None if failed
        """
        try:
            if geom.isMultipart():
                parts = geom.asMultiPolygon()
                exterior_parts = []
                for part in parts:
                    if part and len(part) > 0:
                        exterior_ring = part[0]  # First ring is exterior
                        if exterior_ring and len(exterior_ring) >= 4:
                            exterior_parts.append([exterior_ring])
                if exterior_parts:
                    return QgsGeometry.fromMultiPolygonXY(exterior_parts)
            else:
                polygon = geom.asPolygon()
                if polygon and len(polygon) > 0:
                    exterior_ring = polygon[0]
                    if exterior_ring and len(exterior_ring) >= 4:
                        return QgsGeometry.fromPolygonXY([exterior_ring])
        except Exception as e:
            self.log(f"Feature {fid}: Error extracting exterior: {str(e)}", Qgis.Warning)

        return None

    def recover_geometry(self, original_geom, fid):
        """
        Try to recover a problematic geometry using various fallback methods.

        Returns:
            QgsGeometry if successful, None if failed
        """
        self.log(f"Feature {fid}: Attempting geometry recovery")

        # Check if the original geometry has zero area - if so, don't try to recover
        if original_geom and original_geom.type() == QgsWkbTypes.PolygonGeometry:
            try:
                area = original_geom.area()
                if area <= self.zero_area_threshold:
                    self.log(f"Feature {fid}: Original geometry has zero area, cannot recover")
                    return None
            except Exception:
                pass

        # Method 1: Convex hull
        try:
            convex = original_geom.convexHull()
            if convex and not convex.isEmpty() and convex.isGeosValid():
                area = convex.area() if convex.type() == QgsWkbTypes.PolygonGeometry else 1
                if area > self.zero_area_threshold:
                    self.log(f"Feature {fid}: Recovered using convex hull")
                    return convex
        except Exception as e:
            pass

        # Method 2: Oriented minimum bounding box
        try:
            obb = original_geom.orientedMinimumBoundingBox()
            if obb[0] and not obb[0].isEmpty() and obb[0].isGeosValid():
                area = obb[0].area() if obb[0].type() == QgsWkbTypes.PolygonGeometry else 1
                if area > self.zero_area_threshold:
                    self.log(f"Feature {fid}: Recovered using oriented bounding box")
                    return obb[0]
        except Exception as e:
            pass

        # Method 3: Regular bounding box
        try:
            bbox = original_geom.boundingBox()
            if not bbox.isEmpty():
                # Check if bounding box has area
                if bbox.width() > 0 and bbox.height() > 0:
                    bbox_geom = QgsGeometry.fromRect(bbox)
                    if bbox_geom and bbox_geom.isGeosValid():
                        self.log(f"Feature {fid}: Recovered using bounding box")
                        return bbox_geom
        except Exception as e:
            pass

        # Method 4: Create from vertices
        try:
            vertices = list(original_geom.vertices())
            if len(vertices) >= 3:
                # Create a simple polygon from vertices
                polygon = QgsGeometry.fromPolygonXY([[QgsPointXY(v) for v in vertices]])
                if polygon and polygon.isGeosValid():
                    area = polygon.area()
                    if area > self.zero_area_threshold:
                        self.log(f"Feature {fid}: Recovered by recreating from vertices")
                        return polygon
        except Exception as e:
            pass

        return None

    def recover_null_geometry(self, fid):
        """
        Try to recover a null geometry using neighbor analysis or default shapes.

        Returns:
            QgsGeometry if successful, None if failed
        """
        # If we have the original stored, try to use its bounding box
        if fid in self.original_geometries:
            original = self.original_geometries[fid]
            if original and not original.isNull():
                try:
                    bbox = original.boundingBox()
                    if not bbox.isEmpty() and bbox.width() > 0 and bbox.height() > 0:
                        return QgsGeometry.fromRect(bbox)
                except Exception:
                    pass

        # Don't create default geometries - null should remain null or be deleted
        return None

    def convert_to_singlepart_safe(self, geom, fid):
        """
        Safely convert multipart to singlepart (keeps largest part).

        Returns:
            QgsGeometry if successful, None if failed
        """
        if not geom.isMultipart():
            return geom

        try:
            parts = geom.asGeometryCollection()
            if not parts or len(parts) == 0:
                self.log(f"Feature {fid}: Multipart but no parts found", Qgis.Warning)
                return None

            # Find largest valid part by area
            largest_part = None
            largest_area = 0.0

            for part in parts:
                if part.isGeosValid():
                    if part.type() == QgsWkbTypes.PolygonGeometry:
                        area = part.area()
                        if area > largest_area and area > self.zero_area_threshold:
                            largest_area = area
                            largest_part = part
                    elif not largest_part:
                        # Keep non-polygon parts if no polygon found yet
                        largest_part = part

            if largest_part:
                # Log discarded parts so users can verify nothing important was dropped
                discarded = [p for p in parts if p is not largest_part
                             and p.type() == QgsWkbTypes.PolygonGeometry]
                if discarded:
                    discarded_areas = [f"{p.area():.6f}" for p in discarded]
                    self.log(
                        f"Feature {fid}: Converted from {len(parts)} parts to singlepart "
                        f"(kept area={largest_area:.6f}, discarded {len(discarded)} part(s) "
                        f"with areas: {', '.join(discarded_areas)})"
                    )
                else:
                    self.log(f"Feature {fid}: Converted from {len(parts)} parts to singlepart")
                return largest_part
            else:
                self.log(f"Feature {fid}: Could not find valid part in multipart geometry", Qgis.Warning)
                return None

        except Exception as e:
            self.log(f"Feature {fid}: Multipart conversion failed: {str(e)}", Qgis.Critical)
            return None

    def validate_geometry_strict(self, geom, fid):
        """
        Strict validation that rejects zero-area polygons.

        Returns:
            True if acceptable, False otherwise
        """
        # Check 1: Not null
        if not geom or geom.isNull():
            self.log(f"Feature {fid}: Validation failed - null geometry", Qgis.Warning)
            return False

        # Check 2: Not empty
        if geom.isEmpty():
            self.log(f"Feature {fid}: Validation failed - empty geometry", Qgis.Warning)
            return False

        # Check 3: GEOS validity
        if not geom.isGeosValid():
            self.log(f"Feature {fid}: Validation warning - not GEOS valid", Qgis.Warning)
            # Don't immediately fail, might still be usable

        # Check 4: For polygons, check area strictly
        if geom.type() == QgsWkbTypes.PolygonGeometry:
            try:
                area = geom.area()
                if area <= self.zero_area_threshold:
                    self.log(f"Feature {fid}: Validation warning - very small area: {area}", Qgis.Warning)
                    # This is a strict validation - reject zero area
                    return False
                # Area is good
                return True
            except Exception:
                self.log(f"Feature {fid}: Validation failed - could not compute area", Qgis.Critical)
                return False

        # Check 5: Has vertices
        try:
            vertex_count = len(list(geom.vertices()))
            if vertex_count == 0:
                self.log(f"Feature {fid}: Validation failed - no vertices", Qgis.Critical)
                return False
        except Exception:
            pass

        # For non-polygon geometries, if we got here, it's acceptable
        return True

    def detect_geometry_issues(self, progress_dialog=None):
        """
        Detect all geometry issues in the layer without fixing them.

        Returns:
            List of GeometryIssue objects
        """
        issues = []

        features = list(self.layer.getFeatures())
        total = len(features)

        for idx, feature in enumerate(features):
            # Update progress
            if progress_dialog:
                progress_dialog.setValue(idx)
                if progress_dialog.wasCanceled():
                    self.log("Detection cancelled by user", Qgis.Warning)
                    break

            fid = feature.id()
            geom = feature.geometry()

            # Check 1: Null/Empty geometry
            if not geom or geom.isEmpty() or geom.isNull():
                issues.append(GeometryIssue(
                    fid=fid,
                    issue_type='empty',
                    description='Empty or null geometry',
                    geometry=None
                ))
                continue

            # Check 2: Invalid geometry
            if not geom.isGeosValid():
                # Get validation error details
                errors = geom.validateGeometry()
                error_desc = errors[0].what() if errors else 'Invalid geometry (GEOS validation failed)'

                # Categorize the error type for better reporting
                error_lower = error_desc.lower()
                if 'ring' in error_lower and 'exterior' in error_lower:
                    issue_type = 'ring_not_in_exterior'
                    description = f'Invalid: Interior ring (hole) extends outside polygon boundary - {error_desc}'
                elif 'self-intersection' in error_lower or 'self intersection' in error_lower:
                    issue_type = 'self_intersection'
                    description = f'Invalid: {error_desc}'
                elif 'duplicate' in error_lower:
                    issue_type = 'invalid_duplicate'
                    description = f'Invalid: {error_desc}'
                else:
                    issue_type = 'invalid'
                    description = f'Invalid: {error_desc}'

                issues.append(GeometryIssue(
                    fid=fid,
                    issue_type=issue_type,
                    description=description,
                    geometry=QgsGeometry(geom)
                ))

            # Check 3: Zero area polygons
            if geom.type() == QgsWkbTypes.PolygonGeometry:
                try:
                    area = geom.area()
                    if area <= self.zero_area_threshold:
                        issues.append(GeometryIssue(
                            fid=fid,
                            issue_type='zero_area',
                            description=f'Zero or near-zero area: {area:.2e}',
                            geometry=QgsGeometry(geom)
                        ))
                except Exception:
                    pass

            # Check 4: Multipart geometry
            if geom.isMultipart():
                parts = geom.asGeometryCollection()
                num_parts = len(parts) if parts else 0
                issues.append(GeometryIssue(
                    fid=fid,
                    issue_type='multipart',
                    description=f'Multipart geometry ({num_parts} parts)',
                    geometry=QgsGeometry(geom)
                ))

            # Check 5: Duplicate vertices
            geom_copy = QgsGeometry(geom)
            vertex_count_before = len(list(geom_copy.vertices()))
            geom_copy.removeDuplicateNodes(epsilon=0.0001, useZValues=False)
            vertex_count_after = len(list(geom_copy.vertices()))

            if vertex_count_after < vertex_count_before:
                duplicate_count = vertex_count_before - vertex_count_after
                # Check if removal would cause collapse
                if geom.type() == QgsWkbTypes.PolygonGeometry:
                    if geom_copy.area() <= self.zero_area_threshold and geom.area() > self.zero_area_threshold:
                        issues.append(GeometryIssue(
                            fid=fid,
                            issue_type='duplicate_vertices_collapse',
                            description=f'Has {duplicate_count} duplicate vertices (removal causes collapse)',
                            geometry=QgsGeometry(geom)
                        ))
                    else:
                        issues.append(GeometryIssue(
                            fid=fid,
                            issue_type='duplicate_vertices',
                            description=f'Has {duplicate_count} duplicate vertices',
                            geometry=QgsGeometry(geom)
                        ))
                else:
                    issues.append(GeometryIssue(
                        fid=fid,
                        issue_type='duplicate_vertices',
                        description=f'Has {duplicate_count} duplicate vertices',
                        geometry=QgsGeometry(geom)
                    ))

        if progress_dialog:
            progress_dialog.setValue(total)

        return issues