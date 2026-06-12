# -*- coding: utf-8 -*-
"""
Preview System for Polygon Clipper
Handles preview layer creation and confirmation dialog
"""
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsField,
    QgsFillSymbol,
    QgsProject,
    QgsRendererCategory,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import pyqtSignal, Qt, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class PreviewDialog(QDialog):
    """
    Dialog for confirming clip operation after preview.
    Shows operation details and allows user to confirm or cancel.
    Non-blocking to allow map interaction during preview inspection.
    """

    # Signals for non-blocking operation
    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, result, parent=None):
        """
        Initialize preview dialog.

        Args:
            result: ClippingResult object
            parent: parent widget
        """
        super(PreviewDialog, self).__init__(parent)
        self.result = result
        self.setup_ui()

    def setup_ui(self):
        """Build the dialog UI"""
        self.setWindowTitle("Clip Preview")
        self.setMinimumWidth(500)
        self.setMinimumHeight(300)

        # Make dialog non-modal and stay on top to allow map interaction (zoom/pan) during preview inspection
        self.setModal(False)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout()

        # Title
        title = QLabel("<h3>Clip Operation Preview</h3>")
        layout.addWidget(title)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        # Operation details
        details_group = QGroupBox("Operation Details")
        details_layout = QVBoxLayout()

        # Cutter info
        cutter_text = f"<b>Cutter(s):</b> {len(self.result.cutter_ids)} feature(s)"
        if len(self.result.cutter_ids) <= 5:
            cutter_text += f" (IDs: {', '.join(map(str, self.result.cutter_ids))})"
        cutter_label = QLabel(cutter_text)
        details_layout.addWidget(cutter_label)

        # Target info
        target_text = f"<b>Target(s):</b> {len(self.result.target_ids)} feature(s)"
        if len(self.result.target_ids) <= 5:
            target_text += f" (IDs: {', '.join(map(str, self.result.target_ids))})"
        elif len(self.result.target_ids) <= 20:
            target_text += f" (IDs: {', '.join(map(str, self.result.target_ids))})"
        else:
            target_text += f" (First 5 IDs: {', '.join(map(str, self.result.target_ids[:5]))}...)"
        target_label = QLabel(target_text)
        details_layout.addWidget(target_label)

        # Results
        result_label = QLabel(
            f"<b>Will clip:</b> {self.result.clipped_count} polygon(s)<br>"
            f"<b>Unchanged:</b> {self.result.unchanged_count} polygon(s)"
        )
        details_layout.addWidget(result_label)

        # Snapping info
        if self.result.snapped_count > 0:
            snap_label = QLabel(f"<b>Snapping:</b> Applied ({self.result.snapped_count} feature(s))")
            snap_label.setStyleSheet("color: green;")
            details_layout.addWidget(snap_label)

        details_group.setLayout(details_layout)
        layout.addWidget(details_group)

        # Warning/Info message
        info_box = QGroupBox("Important")
        info_layout = QVBoxLayout()
        info_text = QLabel(
            "Review the preview layer on the map (shown in cyan/magenta).\n"
            "Only the listed target polygons will be modified.\n"
            "All other features will remain unchanged.\n\n"
            "Click 'Confirm' to apply changes or 'Cancel' to abort."
        )
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)
        info_box.setLayout(info_layout)
        layout.addWidget(info_box)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.confirm_button = QPushButton("Confirm Clip")
        self.confirm_button.setDefault(True)
        self.confirm_button.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "padding: 8px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #45a049; }"
        )
        self.confirm_button.clicked.connect(self.on_confirm)
        button_layout.addWidget(self.confirm_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet(
            "QPushButton { padding: 8px 16px; }"
        )
        self.cancel_button.clicked.connect(self.on_cancel)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def on_confirm(self):
        """Handle confirm button click"""
        self.confirmed.emit()
        self.close()

    def on_cancel(self):
        """Handle cancel button click"""
        self.cancelled.emit()
        self.close()


class PreviewManager:
    """
    Manages preview layer creation and application of changes.
    Handles non-blocking preview dialog for map interaction during inspection.
    """

    def __init__(self, iface):
        self.iface = iface
        self.preview_layer = None
        self.flash_timer = None
        self.preview_dialog = None
        self.current_layer = None
        self.current_result = None
        self.status_callback = None  # Callback for status updates
        self.clear_callback = None  # Callback to clear selections after success

    def create_preview(self, source_layer, result, style_mode='clip'):
        """
        Create temporary preview layer showing clipping result or overlaps.

        Args:
            source_layer: QgsVectorLayer - original layer
            result: ClippingResult object
            style_mode: str - 'clip' for clipping (cyan/magenta) or 'overlap' for overlaps (red/orange)

        Returns:
            QgsVectorLayer - preview layer
        """
        # Remove any existing preview
        self.remove_preview()

        # CRITICAL: Clear selection to avoid color conflicts with QGIS highlighting
        source_layer.removeSelection()

        # Determine geometry type
        if source_layer.wkbType() == QgsWkbTypes.MultiPolygon:
            geom_type = "MultiPolygon"
        else:
            geom_type = "Polygon"

        # Create memory layer
        crs = source_layer.crs().authid()
        self.preview_layer = QgsVectorLayer(
            f"{geom_type}?crs={crs}",
            "Clip Preview",
            "memory"
        )

        # Copy field structure from source, plus _type for overlap classification
        provider = self.preview_layer.dataProvider()
        source_fields = list(source_layer.fields())
        provider.addAttributes(source_fields)
        if style_mode in ('overlap', 'sliver'):
            # Add _type field if not already present from overlap/sliver features
            if '_type' not in [f.name() for f in source_fields]:
                provider.addAttributes([QgsField('_type', QVariant.String)])
        self.preview_layer.updateFields()

        # Add clipped features
        provider.addFeatures(result.clipped_features)

        # Style based on mode
        if style_mode == 'overlap':
            # Categorized renderer: simple (red/orange) vs bisecting (yellow/red)
            simple_symbol = QgsFillSymbol.createSimple({})
            simple_symbol.setColor(QColor(255, 0, 0, 120))
            simple_symbol.symbolLayer(0).setStrokeColor(QColor(255, 140, 0))
            simple_symbol.symbolLayer(0).setStrokeWidth(0.8)

            bisecting_symbol = QgsFillSymbol.createSimple({})
            bisecting_symbol.setColor(QColor(255, 255, 0, 150))
            bisecting_symbol.symbolLayer(0).setStrokeColor(QColor(255, 0, 0))
            bisecting_symbol.symbolLayer(0).setStrokeWidth(0.8)

            categories = [
                QgsRendererCategory('simple', simple_symbol, 'Simple Overlap'),
                QgsRendererCategory('bisecting', bisecting_symbol, 'Bisecting Overlap'),
            ]
            renderer = QgsCategorizedSymbolRenderer('_type', categories)
            self.preview_layer.setRenderer(renderer)
        elif style_mode == 'sliver':
            sliver_symbol = QgsFillSymbol.createSimple({})
            sliver_symbol.setColor(QColor(255, 20, 147, 200))
            sliver_symbol.symbolLayer(0).setStrokeColor(QColor(199, 21, 133))
            sliver_symbol.symbolLayer(0).setStrokeWidth(0.8)

            categories = [
                QgsRendererCategory('sliver', sliver_symbol, 'Sliver Gap'),
            ]
            renderer = QgsCategorizedSymbolRenderer('_type', categories)
            self.preview_layer.setRenderer(renderer)
        else:
            # CYAN/MAGENTA for clipping (default)
            symbol = self.preview_layer.renderer().symbol()
            symbol.setColor(QColor(0, 255, 255, 150))  # Cyan fill with transparency
            if symbol.symbolLayerCount() > 0:
                symbol.symbolLayer(0).setStrokeColor(QColor(255, 0, 255))  # Magenta outline
                symbol.symbolLayer(0).setStrokeWidth(0.5)  # Very thin stroke for visibility

        # Add to map WITH legend (True) so it's visible in layers panel
        # This makes the preview layer immediately visible
        QgsProject.instance().addMapLayer(self.preview_layer, True)

        # Get layer tree and move preview to top
        root = QgsProject.instance().layerTreeRoot()
        layer_tree_layer = root.findLayer(self.preview_layer.id())
        if layer_tree_layer:
            # Move to top of layer tree
            clone = layer_tree_layer.clone()
            parent = layer_tree_layer.parent()
            parent.insertChildNode(0, clone)
            parent.removeChildNode(layer_tree_layer)

            # Ensure it's visible and expanded
            layer_tree_layer = root.findLayer(self.preview_layer.id())
            if layer_tree_layer:
                layer_tree_layer.setItemVisibilityChecked(True)
                layer_tree_layer.setExpanded(True)

        # Keep source layer selected in layers panel (not the preview)
        source_tree_layer = root.findLayer(source_layer.id())
        if source_tree_layer:
            self.iface.layerTreeView().setCurrentLayer(source_layer)

        # Trigger layer rendering
        self.preview_layer.triggerRepaint()

        # Zoom to preview extent for better visibility
        if result.clipped_count > 0:
            extent = self.preview_layer.extent()
            extent.scale(1.2)  # Add 20% buffer around features
            self.iface.mapCanvas().setExtent(extent)

        # Force canvas refresh
        self.iface.mapCanvas().refresh()
        self.iface.mapCanvas().refreshAllLayers()

        # Flash the preview layer to draw attention
        self.flash_layer(self.preview_layer)

        return self.preview_layer

    def flash_layer(self, layer, flash_count=3, duration_ms=150):
        """
        Flash the preview layer to draw user attention.

        Args:
            layer: QgsVectorLayer to flash
            flash_count: number of times to flash (default 3)
            duration_ms: milliseconds per flash (default 150)
        """
        from qgis.PyQt.QtCore import QTimer

        if not layer:
            return

        # Store layer ID instead of layer reference to avoid deleted C++ object issues
        try:
            layer_id = layer.id()
        except RuntimeError:
            # Layer already deleted
            return

        # Create a timer for flashing effect
        self.flash_state = {'count': 0, 'visible': True, 'max_count': flash_count * 2}
        self.flash_timer = QTimer()

        def toggle_visibility():
            if self.flash_state['count'] >= self.flash_state['max_count']:
                # Ensure layer is visible at the end
                try:
                    root = QgsProject.instance().layerTreeRoot()
                    layer_tree_layer = root.findLayer(layer_id)
                    if layer_tree_layer:
                        layer_tree_layer.setItemVisibilityChecked(True)
                    self.flash_timer.stop()
                    self.iface.mapCanvas().refresh()
                except RuntimeError:
                    # Layer was deleted, just stop the timer
                    self.flash_timer.stop()
                return

            # Toggle visibility - use layer_id instead of layer reference
            try:
                root = QgsProject.instance().layerTreeRoot()
                layer_tree_layer = root.findLayer(layer_id)
                if layer_tree_layer:
                    self.flash_state['visible'] = not self.flash_state['visible']
                    layer_tree_layer.setItemVisibilityChecked(self.flash_state['visible'])
                    self.iface.mapCanvas().refresh()
                    self.flash_state['count'] += 1
                else:
                    # Layer no longer exists, stop flashing
                    self.flash_timer.stop()
            except RuntimeError:
                # Layer was deleted, stop the timer
                self.flash_timer.stop()

        self.flash_timer.timeout.connect(toggle_visibility)
        self.flash_timer.start(duration_ms)

    def apply_changes(self, layer, result):
        """
        Apply clipping changes to the actual layer.

        Args:
            layer: QgsVectorLayer - layer to modify
            result: ClippingResult object

        Returns:
            bool: success
        """
        if not layer:
            return False

        # Start editing if not already
        was_editing = layer.isEditable()
        if not was_editing:
            layer.startEditing()

        try:
            # Delete old features
            layer.deleteFeatures(result.deleted_ids)

            # Add new clipped features
            layer.addFeatures(result.clipped_features)

            # Commit if we started editing
            if not was_editing:
                if not layer.commitChanges():
                    commit_errors = layer.commitErrors()
                    error_msg = "; ".join(commit_errors) if commit_errors else "Unknown error"
                    layer.rollBack()
                    if self.status_callback:
                        self.status_callback(f"Commit failed: {error_msg}", 'error')
                    return False

            # Repaint to show updated geometries
            layer.triggerRepaint()

            # Ensure the layer stays selected in layers panel
            self.iface.layerTreeView().setCurrentLayer(layer)

            self.iface.mapCanvas().refresh()

            return True

        except Exception as e:
            # Rollback on error
            if not was_editing:
                layer.rollBack()
            return False

    def remove_preview(self):
        """Remove preview layer from map"""
        # Stop any running flash timer first
        if self.flash_timer and self.flash_timer.isActive():
            self.flash_timer.stop()
            self.flash_timer = None

        if self.preview_layer:
            try:
                layer_id = self.preview_layer.id()
            except RuntimeError:
                layer_id = None

            try:
                if layer_id:
                    QgsProject.instance().removeMapLayer(layer_id)
            except RuntimeError:
                pass

            self.preview_layer = None

            try:
                self.iface.mapCanvas().refresh()
            except RuntimeError:
                pass

    def show_preview_dialog(self, layer, result, status_callback=None, clear_callback=None):
        """
        Show preview confirmation dialog (non-blocking).
        Allows map interaction (zoom/pan) while dialog is open.

        Args:
            layer: QgsVectorLayer - layer to modify
            result: ClippingResult object
            status_callback: function(message, level) - optional callback for status updates
            clear_callback: function() - optional callback to clear selections after success
        """
        # Store references for async handling
        self.current_layer = layer
        self.current_result = result
        self.status_callback = status_callback
        self.clear_callback = clear_callback

        # Close any existing dialog
        if self.preview_dialog:
            try:
                self.preview_dialog.close()
            except RuntimeError:
                pass

        # Create new dialog
        self.preview_dialog = PreviewDialog(result, self.iface.mainWindow())

        # Connect signals for async handling
        self.preview_dialog.confirmed.connect(self.on_preview_confirmed)
        self.preview_dialog.cancelled.connect(self.on_preview_cancelled)

        # Show non-blocking (allows map interaction)
        self.preview_dialog.show()
        self.preview_dialog.raise_()
        self.preview_dialog.activateWindow()

    def on_preview_confirmed(self):
        """Handle preview confirmation (apply changes)"""
        if self.status_callback:
            self.status_callback(f"Applying changes to {self.current_result.clipped_count} features...", 'info')

        success = self.apply_changes(self.current_layer, self.current_result)

        if success:
            if self.status_callback:
                self.status_callback(f"Success! Clipped {self.current_result.clipped_count} features", 'success')
            if self.clear_callback:
                self.clear_callback()
        else:
            if self.status_callback:
                self.status_callback("Error: Failed to apply changes", 'error')

        # Clean up
        self.current_layer = None
        self.current_result = None

    def on_preview_cancelled(self):
        """Handle preview cancellation (remove preview)"""
        self.remove_preview()

        if self.status_callback:
            self.status_callback("Operation cancelled", 'info')

        # Clean up
        self.current_layer = None
        self.current_result = None
