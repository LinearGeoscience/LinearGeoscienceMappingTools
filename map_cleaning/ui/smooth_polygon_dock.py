"""
/***************************************************************************
    Smooth Polygon Dock Widget
                              -------------------
        begin                : 2024
        copyright            : (C) 2024
        email                :
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
import os
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QDockWidget

from qgis.core import (
    QgsMapLayerProxyModel,
    QgsWkbTypes,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
)
from qgis.gui import QgsRubberBand, QgsMapToolIdentifyFeature

from ..core.spline_interp import interpolate_closed_ring

# Load the UI file
base_dir = os.path.dirname(__file__)
uicls, basecls = uic.loadUiType(os.path.join(base_dir, "ui_smooth_polygon_dock.ui"))


class SmoothPolygonDock(uicls, basecls):

    closingPlugin = pyqtSignal()

    def __init__(self, iface, parent=None):
        super(SmoothPolygonDock, self).__init__(parent)
        self.setupUi(self)

        self.iface = iface
        self.canvas = iface.mapCanvas()

        # Current state
        self.current_layer = None
        self.current_feature = None
        self.original_geometry = None
        self.smoothed_geometry = None

        # Rubber band for preview
        self.preview_rb = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        self.preview_rb.setColor(QColor(255, 0, 0, 100))
        self.preview_rb.setWidth(2)

        # Selection tool
        self.select_tool = None
        self.previous_tool = None

        # Setup UI
        self.setup_ui()
        self.connect_signals()

    def setup_ui(self):
        """Initialize UI components"""
        # Configure layer combo box to show only polygon layers
        self.layerComboBox.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.layerComboBox.setAllowEmptyLayer(False)

        # Set initial state
        self.update_feature_info()
        self.update_buttons_state()

    def connect_signals(self):
        """Connect UI signals to slots"""
        # Layer selection
        self.layerComboBox.layerChanged.connect(self.on_layer_changed)

        # Feature selection
        self.selectFeatureButton.clicked.connect(self.activate_select_tool)

        # Parameter changes - sync sliders and spinboxes
        self.tensionSlider.valueChanged.connect(self.on_tension_slider_changed)
        self.tensionSpinBox.valueChanged.connect(self.on_tension_spinbox_changed)

        self.toleranceSlider.valueChanged.connect(self.on_tolerance_slider_changed)
        self.toleranceSpinBox.valueChanged.connect(self.on_tolerance_spinbox_changed)

        # Action buttons
        self.previewButton.clicked.connect(self.preview_smoothing)
        self.applyButton.clicked.connect(self.apply_smoothing)
        self.clearButton.clicked.connect(self.clear_preview)

    def on_layer_changed(self, layer):
        """Handle layer change"""
        self.current_layer = layer
        self.current_feature = None
        self.original_geometry = None
        self.clear_preview()
        self.update_feature_info()
        self.update_buttons_state()

        if layer:
            self.set_status(f"Layer changed to: {layer.name()}")
        else:
            self.set_status("No layer selected")

    def activate_select_tool(self):
        """Activate feature selection tool"""
        if not self.current_layer:
            self.set_status("Please select a polygon layer first", error=True)
            return

        # Create selection tool
        self.select_tool = QgsMapToolIdentifyFeature(self.canvas, self.current_layer)
        self.select_tool.featureIdentified.connect(self.on_feature_identified)

        # Remember previous tool
        self.previous_tool = self.canvas.mapTool()

        # Activate selection tool
        self.canvas.setMapTool(self.select_tool)
        self.set_status("Click on a polygon feature to select it")

    def on_feature_identified(self, feature):
        """Handle feature identification"""
        self.current_feature = feature
        self.original_geometry = QgsGeometry(feature.geometry())

        # Restore previous tool
        if self.previous_tool:
            self.canvas.setMapTool(self.previous_tool)

        self.update_feature_info()
        self.update_buttons_state()
        self.clear_preview()
        self.set_status(f"Feature {feature.id()} selected. Adjust parameters and preview.")

    def on_tension_slider_changed(self, value):
        """Sync slider to spinbox"""
        self.tensionSpinBox.setValue(value / 100.0)

    def on_tension_spinbox_changed(self, value):
        """Sync spinbox to slider"""
        self.tensionSlider.setValue(int(value * 100))

    def on_tolerance_slider_changed(self, value):
        """Sync slider to spinbox"""
        self.toleranceSpinBox.setValue(value / 10.0)

    def on_tolerance_spinbox_changed(self, value):
        """Sync spinbox to slider"""
        self.toleranceSlider.setValue(int(value * 10))

    def preview_smoothing(self):
        """Generate and display preview of smoothed polygon"""
        if not self.current_feature or not self.original_geometry:
            self.set_status("No feature selected", error=True)
            return

        try:
            # Get parameters
            tension = self.tensionSpinBox.value()
            tolerance = self.toleranceSpinBox.value()
            max_segments = self.maxSegmentsSpinBox.value()

            self.set_status(f"Generating preview (tension={tension}, tolerance={tolerance})...")

            # Clear previous preview
            self.preview_rb.reset(QgsWkbTypes.PolygonGeometry)

            # Get polygon geometry
            geom = QgsGeometry(self.original_geometry)

            if geom.isMultipart():
                polygons = geom.asMultiPolygon()
                if not polygons:
                    self.set_status("Empty geometry", error=True)
                    return
            else:
                polygon = geom.asPolygon()
                if not polygon:
                    self.set_status("Empty geometry", error=True)
                    return
                polygons = [polygon]

            def _smooth_polygon(polygon):
                """Smooth a single polygon (exterior + interior rings)."""
                if not polygon or len(polygon[0]) < 4:
                    return polygon

                exterior_ring = polygon[0]
                smoothed_exterior = interpolate_closed_ring(
                    exterior_ring,
                    tolerance=tolerance,
                    tightness=tension,
                    max_segments=max_segments
                )

                smoothed_interiors = []
                if len(polygon) > 1:
                    for interior_ring in polygon[1:]:
                        if len(interior_ring) >= 4:
                            smoothed_interior = interpolate_closed_ring(
                                interior_ring,
                                tolerance=tolerance,
                                tightness=tension,
                                max_segments=max_segments
                            )
                            smoothed_interiors.append(smoothed_interior)
                        else:
                            smoothed_interiors.append(interior_ring)

                return [smoothed_exterior] + smoothed_interiors

            # Smooth all polygon parts
            smoothed_polygons = [_smooth_polygon(p) for p in polygons]

            # Create smoothed geometry
            if geom.isMultipart():
                self.smoothed_geometry = QgsGeometry.fromMultiPolygonXY(smoothed_polygons)
            else:
                self.smoothed_geometry = QgsGeometry.fromPolygonXY(smoothed_polygons[0])

            # Validate
            if not self.smoothed_geometry.isGeosValid():
                self.set_status("Generated invalid geometry - try different parameters", error=True)
                return

            # Display preview with rubber band
            self.preview_rb.setToGeometry(self.smoothed_geometry, self.current_layer)

            orig_count = sum(len(p[0]) for p in polygons)
            smooth_count = sum(len(p[0]) for p in smoothed_polygons)
            parts_msg = f" ({len(polygons)} parts)" if len(polygons) > 1 else ""
            self.set_status(
                f"Preview generated{parts_msg}: {orig_count} → {smooth_count} vertices",
                success=True
            )

        except Exception as e:
            self.set_status(f"Error generating preview: {str(e)}", error=True)

    def apply_smoothing(self):
        """Apply smoothing to the actual feature"""
        if not self.current_feature or not self.smoothed_geometry:
            self.set_status("No preview to apply. Generate preview first.", error=True)
            return

        if not self.current_layer:
            self.set_status("No layer available", error=True)
            return

        try:
            # Start editing if not already
            if not self.current_layer.isEditable():
                if not self.current_layer.startEditing():
                    self.set_status("Cannot start editing layer", error=True)
                    return

            # Update feature geometry
            self.current_layer.beginEditCommand("Smooth polygon")

            success = self.current_layer.changeGeometry(
                self.current_feature.id(),
                self.smoothed_geometry
            )

            if success:
                self.current_layer.endEditCommand()
                self.current_layer.triggerRepaint()

                # Update state
                self.original_geometry = QgsGeometry(self.smoothed_geometry)
                self.clear_preview()

                self.set_status("Smoothing applied successfully!", success=True)
            else:
                self.current_layer.destroyEditCommand()
                self.set_status("Failed to update feature geometry", error=True)

        except Exception as e:
            try:
                self.current_layer.destroyEditCommand()
            except Exception:
                pass
            self.set_status(f"Error applying smoothing: {str(e)}", error=True)

    def clear_preview(self):
        """Clear the preview rubber band"""
        rb = getattr(self, "preview_rb", None)
        if rb:
            rb.reset(QgsWkbTypes.PolygonGeometry)
        self.smoothed_geometry = None
        if self.current_feature:
            self.set_status("Preview cleared")
        else:
            self.set_status("Select a polygon feature to begin")

    def update_feature_info(self):
        """Update the feature info label"""
        if self.current_feature and self.original_geometry:
            geom = self.original_geometry

            # Count vertices
            if geom.isMultipart():
                polygons = geom.asMultiPolygon()
                if polygons:
                    vertex_count = len(polygons[0][0]) if polygons[0] else 0
                else:
                    vertex_count = 0
            else:
                polygon = geom.asPolygon()
                vertex_count = len(polygon[0]) if polygon else 0

            info_text = f"<b>Feature ID:</b> {self.current_feature.id()}<br>"
            info_text += f"<b>Vertices:</b> {vertex_count}<br>"
            info_text += f"<b>Layer:</b> {self.current_layer.name() if self.current_layer else 'None'}"

            self.featureInfoLabel.setText(info_text)
        else:
            self.featureInfoLabel.setText("No feature selected")

    def update_buttons_state(self):
        """Enable/disable buttons based on state"""
        has_feature = self.current_feature is not None

        self.previewButton.setEnabled(has_feature)
        self.applyButton.setEnabled(has_feature and self.smoothed_geometry is not None)

    def set_status(self, message, error=False, success=False):
        """Update status label"""
        if error:
            style = "background-color: #ffcccc; border: 1px solid #cc0000;"
        elif success:
            style = "background-color: #ccffcc; border: 1px solid #00cc00;"
        else:
            style = "background-color: #f0f0f0; border: 1px solid #ccc;"

        self.statusLabel.setText(message)
        self.statusLabel.setStyleSheet(
            f"QLabel {{ padding: 5px; {style} border-radius: 3px; }}"
        )

    def cleanup(self):
        """Clean up resources"""
        self.clear_preview()

        # Remove rubber band
        rb = getattr(self, "preview_rb", None)
        if rb:
            try:
                self.canvas.scene().removeItem(rb)
            except Exception:
                pass
            self.preview_rb = None

        # Restore previous tool if needed
        if self.select_tool and self.canvas.mapTool() == self.select_tool:
            if self.previous_tool:
                self.canvas.setMapTool(self.previous_tool)

    def closeEvent(self, event):
        """Handle dock widget close"""
        self.cleanup()
        self.closingPlugin.emit()
        event.accept()
