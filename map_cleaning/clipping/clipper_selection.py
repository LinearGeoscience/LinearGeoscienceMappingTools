# -*- coding: utf-8 -*-
"""
Selection Management for Polygon Clipper
Handles visual feedback and selection tracking
"""
from qgis.gui import QgsHighlight
from qgis.PyQt.QtGui import QColor

class SelectionManager:
    """
    Manages cutter and target selections with visual feedback.
    Provides color-coded highlighting for predictable clipping.
    """

    def __init__(self, iface):
        self.iface = iface
        self.cutter_ids = []
        self.target_ids = []
        self.cutter_highlights = []
        self.target_highlights = []

        # Colors for visual feedback
        self.cutter_color = QColor(0, 120, 255, 100)  # Blue with transparency
        self.target_color = QColor(255, 50, 50, 100)   # Red with transparency

    def set_cutters(self, layer, feature_ids):
        """
        Lock cutter selection and highlight in blue.

        Args:
            layer: QgsVectorLayer
            feature_ids: list of int (feature IDs)
        """
        # Clear any existing cutter highlights
        self.clear_cutter_highlights()

        # Store cutter IDs
        self.cutter_ids = list(feature_ids)

        # Create highlights
        for fid in feature_ids:
            feature = layer.getFeature(fid)
            if feature and feature.hasGeometry():
                highlight = QgsHighlight(
                    self.iface.mapCanvas(),
                    feature.geometry(),
                    layer
                )
                highlight.setColor(self.cutter_color)
                highlight.setFillColor(self.cutter_color)
                highlight.setWidth(2)
                highlight.show()
                self.cutter_highlights.append(highlight)

    def set_targets(self, layer, feature_ids):
        """
        Set target selection and highlight in red.

        Args:
            layer: QgsVectorLayer
            feature_ids: list of int (feature IDs)
        """
        # Clear any existing target highlights
        self.clear_target_highlights()

        # Store target IDs
        self.target_ids = list(feature_ids)

        # Create highlights
        for fid in feature_ids:
            feature = layer.getFeature(fid)
            if feature and feature.hasGeometry():
                highlight = QgsHighlight(
                    self.iface.mapCanvas(),
                    feature.geometry(),
                    layer
                )
                highlight.setColor(self.target_color)
                highlight.setFillColor(self.target_color)
                highlight.setWidth(2)
                highlight.show()
                self.target_highlights.append(highlight)

    def _dispose_highlights(self, highlight_list):
        """
        Safely hide and delete highlight overlays.

        QgsHighlight objects are QgsMapCanvasItems, not QObjects, so they don't
        have deleteLater(). Simply hiding them and clearing the list is sufficient.
        Python's garbage collector will handle deletion.
        """
        for highlight in highlight_list:
            try:
                highlight.hide()
            except RuntimeError:
                # C++ object may already be destroyed during plugin teardown
                pass

    def clear_cutter_highlights(self):
        """Remove all cutter highlights from map"""
        self._dispose_highlights(self.cutter_highlights)
        self.cutter_highlights = []

    def clear_target_highlights(self):
        """Remove all target highlights from map"""
        self._dispose_highlights(self.target_highlights)
        self.target_highlights = []

    def clear_all(self):
        """Clear all selections and highlights"""
        self.clear_cutter_highlights()
        self.clear_target_highlights()
        self.cutter_ids = []
        self.target_ids = []

    def get_counts(self):
        """
        Return selection counts.

        Returns:
            tuple: (cutter_count, target_count)
        """
        return (len(self.cutter_ids), len(self.target_ids))

    def has_cutters(self):
        """Check if cutters are selected"""
        return len(self.cutter_ids) > 0

    def has_targets(self):
        """Check if targets are selected"""
        return len(self.target_ids) > 0

    def get_cutter_ids(self):
        """Get list of cutter feature IDs"""
        return list(self.cutter_ids)

    def get_target_ids(self):
        """Get list of target feature IDs"""
        return list(self.target_ids)
