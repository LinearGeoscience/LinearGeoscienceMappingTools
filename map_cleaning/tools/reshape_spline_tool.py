"""
/***************************************************************************
    Reshape features with spline tool
    Based on Spline digitizer by Radim Blazek
                              -------------------
        begin                : 2025-10-25
        copyright            : (C) 2025
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
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QCursor, QPixmap, QColor
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsGeometry,
    QgsLineString,
    QgsMessageLog,
    QgsPoint,
    QgsPointXY,
    QgsProject,
    QgsSettings,
    QgsWkbTypes,
    Qgis,
)
from qgis.gui import QgsRubberBand, QgsMapToolEdit, QgsVertexMarker

from ..core.spline_interp import interpolate


class ReshapeSplineTool(QgsMapToolEdit):
    """Map tool for reshaping features using spline curves."""

    def __init__(self, iface):
        """Initialize the reshape spline tool.

        Args:
            iface: QGIS interface object
        """
        super(ReshapeSplineTool, self).__init__(iface.mapCanvas())
        self.iface = iface
        self.canvas = self.iface.mapCanvas()

        # Rubber band for preview. Style is set here as the default, and is
        # re-applied in set_rubber_band_points() on every preview update —
        # some QGIS builds drop stroke styling across QgsRubberBand.reset().
        self.rb = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.rb.setColor(QColor(30, 144, 255, 200))  # Dodger blue
        self.rb.setWidth(2)
        self.rb.setFillColor(QColor(30, 144, 255, 0))  # Transparent fill
        self.rb.show()

        self.snap_marker = None  # Created on demand in update_snap_marker()
        self.snapping_utils = self.canvas.snappingUtils()

        # Digitized control points (not yet interpolated)
        self.points = []

        # Custom cursor for reshape tool
        self.cursor = QCursor(
            QPixmap(
                [
                    "16 16 3 1",
                    "      c None",
                    ".     c #1E90FF",  # Dodger blue for reshape
                    "+     c #FFFFFF",
                    "                ",
                    "       +.+      ",
                    "      ++.++     ",
                    "     +.....+    ",
                    "    +.     .+   ",
                    "   +.   .   .+  ",
                    "  +.    .    .+ ",
                    " ++.    .    .++",
                    " ... ...+... ...",
                    " ++.    .    .++",
                    "  +.    .    .+ ",
                    "   +.   .   .+  ",
                    "   ++.     .+   ",
                    "    ++.....+    ",
                    "      ++.++     ",
                    "       +.+      ",
                ]
            )
        )

        # Get snap color from QGIS settings
        s = QgsSettings()
        self.snap_col = s.value("/qgis/digitizing/snap_color", QColor("#ff00ff"))

    def canvasMoveEvent(self, event):
        """Handle mouse move events - show preview of spline.

        Args:
            event: Mouse move event
        """
        # An uncaught exception here would silently stop preview updates for
        # the rest of the session, so log instead of dying.
        try:
            point = self.toMapCoordinates(event.pos())

            # Try to snap to a feature
            result = self.snapping_utils.snapToMap(point)
            if result.isValid():
                point = result.point()
                self.update_snap_marker(snapped_pt=point)
            else:
                self.update_snap_marker()

            # Show preview with current mouse position
            points = list(self.points)
            points.append(QgsPoint(point))

            # Interpolate to spline and show preview
            if len(points) >= 2:
                spline_points = interpolate(points)
                self.set_rubber_band_points(spline_points)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Reshape preview update failed: {e}",
                'Map Cleaning Toolkit', Qgis.Warning
            )

    def canvasReleaseEvent(self, event):
        """Handle mouse click events.

        Args:
            event: Mouse release event
        """
        point = self.toMapCoordinates(event.pos())

        if event.button() == Qt.LeftButton:
            # Left click - add control point
            result = self.snapping_utils.snapToMap(point)
            if result.isValid():
                point = result.point()
            self.points.append(QgsPoint(point))

            # Update preview
            if len(self.points) >= 2:
                try:
                    spline_points = interpolate(self.points)
                    self.set_rubber_band_points(spline_points)
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f"Reshape preview update failed: {e}",
                        'Map Cleaning Toolkit', Qgis.Warning
                    )
        else:
            # Right click - finish and perform reshape
            if len(self.points) >= 2:
                self.perform_reshape()
            self.reset_points()
            self.reset_rubber_band()
            self.canvas.refresh()

    def keyPressEvent(self, e):
        """Handle keyboard events.

        Args:
            e: Key press event
        """
        if e.key() == Qt.Key_Escape:
            # ESC - cancel current operation
            self.reset_points()
            self.reset_rubber_band()
            self.canvas.refresh()
        elif e.key() == Qt.Key_Backspace:
            # Backspace - remove last point
            if self.points:
                self.points.pop()
            if len(self.points) >= 2:
                spline_points = interpolate(self.points)
                self.set_rubber_band_points(spline_points)
            else:
                self.reset_rubber_band()
            self.canvas.refresh()

    def perform_reshape(self):
        """Perform the actual reshape operation on intersecting features.

        If features are selected, only those selected features will be reshaped.
        If no features are selected, all intersecting features will be reshaped.
        """
        layer = self.iface.activeLayer()
        if not layer:
            self.show_message("No active layer", Qgis.Warning)
            return

        if not layer.isEditable():
            self.show_message("Layer is not in edit mode", Qgis.Warning)
            return

        # Convert control points to smooth spline (in project / canvas CRS)
        spline_points = interpolate(self.points)

        # Transform spline points from project CRS to layer CRS if they differ.
        # Without this the intersection check below silently fails whenever
        # on-the-fly reprojection is in use (layer CRS != project CRS), which
        # is the most common cause of "no features to modify".
        proj = QgsProject.instance()
        if layer.crs() != proj.crs():
            transf = QgsCoordinateTransform(proj.crs(), layer.crs(), proj.transformContext())
            transformed = []
            for pt in spline_points:
                try:
                    transformed.append(transf.transform(pt))
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f"CRS transform failed for reshape point: {e}",
                        'Map Cleaning Toolkit', Qgis.Warning
                    )
                    self.show_message(
                        "Could not transform spline to layer CRS — aborting reshape",
                        Qgis.Critical
                    )
                    return
            spline_points = transformed

        # Create geometry from spline points (now in layer CRS)
        reshape_line = QgsGeometry.fromPolylineXY(spline_points)

        # Pre-build the QgsLineString once — reshapeGeometry takes a QgsLineString,
        # and the same line is used for every feature in this operation.
        reshape_line_geom = QgsLineString(
            [QgsPoint(pt.x(), pt.y()) for pt in spline_points]
        )

        # Check if there are selected features
        selected_ids = layer.selectedFeatureIds()

        # Find features to reshape based on selection state
        features_to_reshape = []

        if selected_ids:
            # If features are selected, only reshape those that intersect
            for fid in selected_ids:
                feature = layer.getFeature(fid)
                if feature.geometry() and feature.geometry().intersects(reshape_line):
                    features_to_reshape.append(feature)

            if not features_to_reshape:
                self.show_message(
                    "None of the selected features intersect with the reshape line",
                    Qgis.Warning
                )
                return
        else:
            # No selection - reshape all intersecting features. Use a bbox
            # spatial filter so we don't scan every feature on large layers.
            request = QgsFeatureRequest(reshape_line.boundingBox())
            for feature in layer.getFeatures(request):
                if feature.geometry() and feature.geometry().intersects(reshape_line):
                    features_to_reshape.append(feature)

            if not features_to_reshape:
                self.show_message(
                    "No features intersect with the reshape line",
                    Qgis.Warning
                )
                return

        # Perform reshape on all intersecting features
        reshape_count = 0
        error_count = 0
        no_change_count = 0

        layer.beginEditCommand("Reshape features with spline")

        try:
            for feature in features_to_reshape:
                geom = feature.geometry()

                # reshapeGeometry returns:
                # 0 = success
                # 1 = error
                # 2 = no change
                result = geom.reshapeGeometry(reshape_line_geom)

                if result == 0:  # Success
                    if geom.isGeosValid():
                        layer.changeGeometry(feature.id(), geom)
                        reshape_count += 1
                    else:
                        error_count += 1
                        QgsMessageLog.logMessage(
                            f"Reshape created invalid geometry for feature {feature.id()}",
                            'Map Cleaning Toolkit', Qgis.Warning
                        )
                elif result == 1:  # Error
                    error_count += 1
                    QgsMessageLog.logMessage(
                        f"reshapeGeometry returned error for feature {feature.id()}",
                        'Map Cleaning Toolkit', Qgis.Warning
                    )
                else:  # 2 = no change
                    no_change_count += 1

            layer.endEditCommand()
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Reshape error: {e}", 'Map Cleaning Toolkit', Qgis.Warning
            )
            self.show_message(f"Reshape failed: {e}", Qgis.Critical)
            try:
                layer.destroyEditCommand()
            except Exception:
                pass

        # Show results with context about selection state
        selection_note = " (from selection)" if selected_ids else ""
        if reshape_count > 0:
            self.show_message(
                f"Successfully reshaped {reshape_count} feature(s){selection_note}",
                Qgis.Success
            )
        if error_count > 0:
            self.show_message(
                f"Failed to reshape {error_count} feature(s)",
                Qgis.Warning
            )
        if reshape_count == 0 and no_change_count > 0:
            self.show_message(
                "Reshape line did not modify the geometry — the spline must "
                "cross each polygon's boundary at two points, or have both "
                "endpoints outside the polygon",
                Qgis.Warning
            )

        self.canvas.refresh()

    def show_message(self, message, level=Qgis.Info):
        """Show a message in the QGIS message bar.

        Args:
            message: Message text to display
            level: Message level (Info, Warning, Critical, Success)
        """
        self.iface.messageBar().pushMessage(
            "Reshape with Spline",
            message,
            level=level,
            duration=3
        )

    def reset_points(self):
        """Clear all control points."""
        self.points = []

    def refresh(self):
        """Refresh the preview with current points."""
        if self.points and len(self.points) >= 2:
            spline_points = interpolate(self.points)
            self.set_rubber_band_points(spline_points)

    def canvasPressEvent(self, event):
        """Handle canvas press events (not used)."""
        pass

    def activate(self):
        """Activate the tool."""
        self.canvas.setCursor(self.cursor)

        # A rubber band whose item left the canvas scene can never paint
        # again — recreate it so the tool self-heals instead of staying
        # invisible. scene() raises RuntimeError if the underlying C++
        # object was deleted, which equally requires recreation.
        try:
            rb_usable = self.rb is not None and self.rb.scene() is not None
        except RuntimeError:
            rb_usable = False
        if not rb_usable:
            self.rb = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
            self.rb.setColor(QColor(30, 144, 255, 200))
            self.rb.setWidth(2)
            self.rb.setFillColor(QColor(30, 144, 255, 0))

        # Start from a clean, visible rubber band each activation so that
        # re-entering the tool never leaves a stale geometry or hidden state.
        self.rb.reset(QgsWkbTypes.LineGeometry)
        self.rb.show()

    def reset_rubber_band(self):
        """Reset the rubber band."""
        # rb is None after cleanup() — QGIS can still call deactivate() on
        # the active tool during unload, after cleanup has already run.
        if self.rb is None:
            return
        self.rb.reset(QgsWkbTypes.LineGeometry)

    def set_rubber_band_points(self, points):
        """Set rubber band points for preview.

        Args:
            points: List of QgsPoint or QgsPointXY objects
        """
        if self.rb is None:
            return
        self.reset_rubber_band()
        if not points:
            return

        for point in points:
            update = point is points[-1]
            if isinstance(point, QgsPoint):
                point = QgsPointXY(point)
            self.rb.addPoint(point, update)

        # Re-apply style after every geometry update. Some QGIS builds drop
        # styling state across reset(); without re-applying, the rubber band
        # can render with zero-width stroke and appear invisible.
        self.rb.setColor(QColor(30, 144, 255, 200))
        self.rb.setWidth(2)
        self.rb.setFillColor(QColor(30, 144, 255, 0))

        # Force the rubber band to show and the canvas to redraw. Without
        # these the preview is intermittently invisible under load.
        self.rb.show()
        self.canvas.update()
        self.rb.update()

    def update_snap_marker(self, snapped_pt=None):
        """Update the snap marker position.

        Reuses a single QgsVertexMarker — creating and destroying one per
        mouse move dirties the canvas scene 60+ times/sec and was causing
        the rubber-band preview to disappear while snapping was active.
        Scene-level teardown is handled in cleanup().

        Args:
            snapped_pt: Snapped point position, or None to hide marker
        """
        if snapped_pt is None:
            if self.snap_marker is not None:
                self.snap_marker.hide()
            return

        if self.snap_marker is None:
            self.snap_marker = QgsVertexMarker(self.canvas)
            # Hide until positioned: the constructor adds the marker to the
            # scene visible at the default (0,0) map coord, which would flash
            # there briefly on first creation before setCenter() runs.
            self.snap_marker.hide()
            self.snap_marker.setIconSize(16)
            self.snap_marker.setIconType(QgsVertexMarker.ICON_BOX)
            self.snap_marker.setPenWidth(3)
            self.snap_marker.setColor(self.snap_col)

        self.snap_marker.setCenter(snapped_pt)
        self.snap_marker.show()

    def cleanup_rubber_band(self):
        """Remove rubber band from the canvas scene."""
        try:
            if self.rb is not None:
                self.rb.reset(QgsWkbTypes.LineGeometry)
                self.canvas.scene().removeItem(self.rb)
        except Exception:
            pass

    def cleanup(self):
        """Thorough cleanup of all tool resources. Called by plugin unload.

        deactivate() runs first so QGIS is notified the tool is leaving
        (via QgsMapToolEdit.deactivate) in case the tool is still active.
        """
        self.deactivate()
        self.cleanup_rubber_band()

        if self.snap_marker is not None:
            try:
                self.canvas.scene().removeItem(self.snap_marker)
                del self.snap_marker
            except Exception:
                pass
            self.snap_marker = None

        if self.rb is not None:
            try:
                self.canvas.scene().removeItem(self.rb)
            except Exception:
                pass
            self.rb = None

    def deactivate(self):
        """Deactivate the tool.

        Hides the snap marker and resets the rubber band geometry, but
        leaves both items in the canvas scene so the tool can be re-activated
        without recreating them. Scene-level removal happens in cleanup() at
        plugin unload — QgsRubberBand re-shown after a scene removal does
        not render.
        """
        self.reset_points()
        self.update_snap_marker()  # hides existing marker
        self.reset_rubber_band()
        QgsMapToolEdit.deactivate(self)

    def isZoomTool(self):
        """Check if this is a zoom tool."""
        return False

    def isTransient(self):
        """Check if this is a transient tool."""
        return False

    def isEditTool(self):
        """Check if this is an edit tool."""
        return True
