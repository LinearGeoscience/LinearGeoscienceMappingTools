"""
/***************************************************************************
    Digitize spline, based on CircularArcDigitizer (Stefan Ziegler)
    and Generalizer plugin (Piotr Pociask) which is based on GRASS v.generalize
                              -------------------
        begin                : February 2014
        copyright            : (C) 2014 by Radim Blazek
        email                : radim.blazek@gmail.com
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
    Qgis,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsMessageLog,
    QgsPoint,
    QgsPointXY,
    QgsProject,
    QgsSettings,
    QgsWkbTypes,
)
from qgis.gui import QgsRubberBand, QgsMapToolEdit, QgsVertexMarker

from ..core.spline_interp import interpolate


class SplineTool(QgsMapToolEdit):
    def __init__(self, iface):
        super(SplineTool, self).__init__(iface.mapCanvas())
        self.iface = iface
        self.canvas = self.iface.mapCanvas()

        self.rb = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.rb.setColor(QColor(255, 0, 0, 200))  # Default-style red
        self.rb.setWidth(1)
        self.rb.setFillColor(QColor(255, 0, 0, 0))  # Transparent fill for line previews
        self.rb.show()

        self.snap_marker = None  # Initialize as None, created on demand
        self.snapping_utils = self.canvas.snappingUtils()

        self.points = []  # digitized, not yet interpolated points
        self.type = QgsWkbTypes.LineGeometry  # layer geometry type
        self.tolerance = None
        self.tightness = None
        self.is_polygon = None

        self.cursor = QCursor(
            QPixmap(
                [
                    "16 16 3 1",
                    "      c None",
                    ".     c #FF0000",
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

        s = QgsSettings()
        self.snap_col = s.value("/qgis/digitizing/snap_color", QColor("#ff00ff"))

    def canvasMoveEvent(self, event):
        """Handle mouse move to show spline preview"""
        # An uncaught exception here would silently stop preview updates for
        # the rest of the session, so log instead of dying.
        try:
            point = self.toMapCoordinates(event.pos())

            # try to snap to a feature
            result = self.snapping_utils.snapToMap(point)
            if result.isValid():
                point = result.point()
                self.update_snap_marker(snapped_pt=point)
            else:
                self.update_snap_marker()

            # Show preview with current cursor position
            points = list(self.points)
            points.append(QgsPoint(point))

            # Interpolate and display the preview
            if len(points) >= 1:
                interpolated_points = interpolate(points)
                self.set_rubber_band_points(interpolated_points)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Spline preview update failed: {e}",
                'Map Cleaning Toolkit', Qgis.Warning
            )

    def canvasReleaseEvent(self, event):
        """Handle mouse click to add/finish digitizing points"""
        point = self.toMapCoordinates(event.pos())

        if event.button() == Qt.LeftButton:
            # try to snap to a feature
            result = self.snapping_utils.snapToMap(point)
            if result.isValid():
                point = result.point()
            self.points.append(QgsPoint(point))

            # Update preview after adding point
            try:
                points = interpolate(self.points)
                self.set_rubber_band_points(points)
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Spline preview update failed: {e}",
                    'Map Cleaning Toolkit', Qgis.Warning
                )
        else:
            if len(self.points) >= 2:
                # refresh without last point
                self.refresh()
                self.create_feature()
            self.reset_points()
            self.reset_rubber_band()
            self.canvas.refresh()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            # Cancel the current digitizing session without a deactivate()/
            # activate() round-trip — tearing the tool down just to cancel
            # risks leaving the rubber band in a broken state.
            self.reset_points()
            self.reset_rubber_band()
            self.canvas.refresh()
        elif e.key() == Qt.Key_Backspace:
            if self.points:
                self.points.pop()

            # Update preview after removing point
            if self.points:
                points = interpolate(self.points)
                self.set_rubber_band_points(points)  # Automatically applies styling
            else:
                # Clear rubber band if no points left
                self.reset_rubber_band()

            self.canvas.refresh()

    def reset_points(self):
        self.points = []

    # Create feature from digitized points, i.e. without the last moving point
    # where right click happened. This the same way how core QGIS Add Feature works.
    def create_feature(self):
        """Create feature from digitized points with proper error handling"""
        layer = self.iface.activeLayer()
        provider = layer.dataProvider()
        fields = provider.fields()
        f = QgsFeature(fields)

        try:
            coords = [QgsPointXY(pt) for pt in interpolate(self.points)]

            proj = QgsProject.instance()
            if layer.crs() != proj.crs():
                trans_context = proj.transformContext()
                transf = QgsCoordinateTransform(proj.crs(), layer.crs(), trans_context)
                coords_tmp = coords[:]
                coords = []
                for point in coords_tmp:
                    try:
                        transformed_pt = transf.transform(point)
                        coords.append(transformed_pt)
                    except Exception as e:
                        QgsMessageLog.logMessage(
                            f"CRS transformation failed for point, using untransformed coordinates: {e}",
                            'Map Cleaning Toolkit', Qgis.Warning
                        )
                        coords.append(point)  # Use untransformed point

            # Validate we have enough points
            if len(coords) < 2:
                return

            # Add geometry to feature
            if self.is_polygon:
                g = QgsGeometry.fromPolygonXY([coords])
            else:
                g = QgsGeometry.fromPolylineXY(coords)

            # Validate geometry
            if g.isNull() or not g.isGeosValid():
                return

            f.setGeometry(g)

            # Add attribute fields to feature
            for field in fields.toList():
                ix = fields.indexFromName(field.name())
                f[field.name()] = provider.defaultValue(ix)

            layer.beginEditCommand("Feature added")

            settings = QSettings()
            disable_attributes = settings.value("/qgis/digitizing/disable_enter_attribute_values_dialog", False, type=bool)

            # Check if feature was added successfully
            if not layer.addFeature(f):
                layer.destroyEditCommand()
                return

            if disable_attributes:
                layer.endEditCommand()
            else:
                dlg = self.iface.getFeatureForm(layer, f)
                if dlg.exec_():
                    layer.endEditCommand()
                else:
                    layer.destroyEditCommand()

        except Exception as e:
            # Ensure edit command is cleaned up on any error
            QgsMessageLog.logMessage(
                f"Error creating feature: {e}", 'Map Cleaning Toolkit', Qgis.Warning
            )
            try:
                layer.destroyEditCommand()
            except Exception:
                pass

    def refresh(self):
        if self.points:
            points = interpolate(self.points)
            self.set_rubber_band_points(points)

    def canvasPressEvent(self, event):
        pass

    def showSettingsWarning(self):
        pass

    def activate(self):
        """Activate tool and refresh layer type"""
        self.canvas.setCursor(self.cursor)
        layer = self.iface.activeLayer()

        # Always refresh type when activating
        if layer is not None and hasattr(layer, 'geometryType'):
            self.type = layer.geometryType()
        else:
            self.type = QgsWkbTypes.LineGeometry
        self.is_polygon = (self.type == QgsWkbTypes.PolygonGeometry)

        # A rubber band whose item left the canvas scene can never paint
        # again — recreate it so the tool self-heals instead of staying
        # invisible. scene() raises RuntimeError if the underlying C++
        # object was deleted, which equally requires recreation.
        try:
            rb_usable = self.rb is not None and self.rb.scene() is not None
        except RuntimeError:
            rb_usable = False
        if not rb_usable:
            self.rb = QgsRubberBand(self.canvas, self.type)

        # Initialize rubber band with correct type and styling
        self.rb.reset(self.type)
        self.apply_rubber_band_style()  # Ensure visible styling
        self.rb.show()  # Make sure it's shown

    def reset_rubber_band(self):
        # rb is None after cleanup() — QGIS can still call deactivate() on
        # the active tool during unload, after cleanup has already run.
        if self.rb is None:
            return
        self.rb.reset(self.type)

    def apply_rubber_band_style(self):
        """Apply a default-style thin red rubber band"""
        if self.rb is None:
            return
        self.rb.setColor(QColor(255, 0, 0, 200))
        self.rb.setWidth(1)
        if self.type == QgsWkbTypes.PolygonGeometry:
            self.rb.setFillColor(QColor(255, 0, 0, 40))
        else:
            self.rb.setFillColor(QColor(255, 0, 0, 0))
        self.rb.show()

    def set_rubber_band_points(self, points):
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

        # Apply styling after setting points for maximum visibility
        self.apply_rubber_band_style()

        # Force canvas update to show the rubber band
        self.canvas.update()
        self.rb.update()

    def cleanup_rubber_band(self):
        """Completely remove rubber band from canvas"""
        try:
            if self.rb is not None:
                self.rb.reset(self.type)
                self.canvas.scene().removeItem(self.rb)
        except Exception:
            pass

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

    def cleanup(self):
        """Thorough cleanup of all tool resources"""
        self.deactivate()
        self.cleanup_rubber_band()

        # Clean up snap marker
        if self.snap_marker is not None:
            try:
                self.canvas.scene().removeItem(self.snap_marker)
                del self.snap_marker
            except Exception:
                pass
            self.snap_marker = None

        # Clean up rubber band
        if self.rb is not None:
            try:
                self.canvas.scene().removeItem(self.rb)
            except Exception:
                pass
            self.rb = None

    def isZoomTool(self):
        return False

    def isTransient(self):
        return False

    def isEditTool(self):
        return True
