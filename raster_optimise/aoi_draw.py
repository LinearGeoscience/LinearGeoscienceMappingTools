"""Canvas tool for drawing the areas of interest, one polygon at a time.

Adapted from script_mapsheet_generator.PolygonDrawMapTool rather than
imported from it — that module drags in the whole mapsheet panel at
import time. Interaction is identical: left-click adds a vertex,
right-click closes the polygon (with three or more points) and emits it;
Esc, or a right-click with nothing drawn, says the user is finished.

The tool's own rubber band only shows the polygon IN PROGRESS; the
dialog keeps completed areas visible in a band of its own. Bands are
always reset() before being discarded — a band removed from the scene
while still holding geometry can reappear on the next canvas refresh
(see map_cleaning/tools/spline_tool.py).
"""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.core import Qgis, QgsGeometry
from qgis.gui import QgsMapTool, QgsRubberBand

FILL = QColor(207, 157, 40, 60)
OUTLINE = QColor(207, 157, 40, 220)


class AoiDrawTool(QgsMapTool):
    """Draw one or more polygons; each finished one is handed back."""

    polygon_completed = pyqtSignal(QgsGeometry)
    finished = pyqtSignal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self.rubber_band = QgsRubberBand(canvas, Qgis.GeometryType.Polygon)
        self.rubber_band.setFillColor(FILL)
        self.rubber_band.setStrokeColor(OUTLINE)
        self.rubber_band.setWidth(2)
        self.points = []

    def canvasPressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.points.append(self.toMapCoordinates(event.pos()))
            self._update_rubber_band()
        elif event.button() == Qt.MouseButton.RightButton:
            if len(self.points) >= 3:
                ring = list(self.points)
                ring.append(ring[0])
                self.polygon_completed.emit(
                    QgsGeometry.fromPolygonXY([ring]))
                self._clear()
            elif not self.points:
                self.finished.emit()
            else:
                self._clear()

    def canvasMoveEvent(self, event):
        if self.points:
            self._update_rubber_band(self.toMapCoordinates(event.pos()))

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._clear()
            self.finished.emit()

    def _update_rubber_band(self, current_point=None):
        self.rubber_band.reset(Qgis.GeometryType.Polygon)
        points = list(self.points)
        if current_point:
            points.append(current_point)
        for i, pt in enumerate(points):
            self.rubber_band.addPoint(pt, i == len(points) - 1)

    def _clear(self):
        self.points = []
        self.rubber_band.reset(Qgis.GeometryType.Polygon)

    def deactivate(self):
        self._clear()
        super().deactivate()
