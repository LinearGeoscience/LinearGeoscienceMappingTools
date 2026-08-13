# -*- coding: utf-8 -*-
"""
Level-ladder widget for the Z Filter dock: detected levels drawn top-to-
bottom by elevation with feature counts, the current slice as a band.

Geometry math lives in ladder_math.py (pure python, unit-tested); this file
is Qt painting and mouse handling only.
"""

from qgis.PyQt.QtCore import QEvent, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFontMetrics, QPainter, QPen
from qgis.PyQt.QtWidgets import QSizePolicy, QToolTip, QWidget

from . import ladder_math
from .expression import format_number
from .levels import top_suggestions

ACCENT = '#2196F3'
PAD = 14           # px above the top rung / below the bottom one
AXIS_X = 24        # px of the vertical axis line
RUNG_HIT_PX = 8.0  # click-within distance that selects a rung
MIN_COUNT_SPACING = 12  # px between rungs below which counts are hidden


class LevelLadder(QWidget):
    """Clickable elevation ladder; emits, never applies, filter changes."""

    rungClicked = pyqtSignal(object)     # the suggestion/cluster dict
    elevationPicked = pyqtSignal(float)  # background click / drag sweep
    stepRequested = pyqtSignal(int)      # mouse wheel: +1 up, -1 down

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rungs = []          # top_suggestions() of the last scan
        self._range = None        # (lo, hi) elevation range of the scan
        self._tooltips = []
        self._level = None        # current level (may be off-rung)
        self._width = 0.0         # slice half-height (tolerance)
        self._active = False      # filter toggle state
        self._step = 0.0          # snap grid for background picks
        self._dragging = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def set_suggestions(self, clusters, scan_range):
        """clusters: suggestion dicts; scan_range: (lo, hi) or None."""
        self._rungs = top_suggestions(clusters or [])
        self._range = None
        if scan_range is not None and scan_range[1] >= scan_range[0]:
            self._range = (float(scan_range[0]), float(scan_range[1]))
        self._tooltips = [
            "%s m%s — %d feature%s (%s–%s m, suggested ±%s m)" % (
                format_number(c['level']),
                '  ' + c['label'] if c.get('label') else '',
                c['count'],
                '' if c['count'] == 1 else 's',
                format_number(c['lo']), format_number(c['hi']),
                format_number(c['suggested_tol']))
            for c in self._rungs]
        self.updateGeometry()
        self.update()

    def set_current(self, level, width, active):
        self._level = level
        self._width = float(width or 0.0)
        self._active = bool(active)
        self.update()

    def set_step(self, step):
        self._step = float(step or 0.0)

    def has_data(self):
        return self._range is not None and bool(self._rungs)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------
    def sizeHint(self):
        return QSize(160, ladder_math.preferred_height(len(self._rungs)))

    def minimumSizeHint(self):
        return QSize(120, ladder_math.preferred_height(len(self._rungs)))

    def _rung_ys(self):
        lo, hi = self._range
        return ladder_math.rung_ys([c['level'] for c in self._rungs],
                                   lo, hi, self.height(), PAD)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        if not self.has_data():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        mid = palette.mid().color()
        text_color = palette.text().color()
        lo, hi = self._range
        height = self.height()
        width_px = self.width()

        # Slice band first, under everything.
        if self._level is not None and self._width > 0:
            y_top, y_bottom = ladder_math.band_rect_y(
                self._level, self._width, lo, hi, height, PAD)
            if y_bottom > y_top:
                band = QColor(ACCENT) if self._active else QColor(mid)
                band.setAlpha(45 if self._active else 60)
                painter.fillRect(0, int(y_top), width_px,
                                 int(y_bottom - y_top), band)
                edge = QColor(ACCENT) if self._active else QColor(mid)
                edge.setAlpha(160)
                painter.setPen(QPen(edge, 1))
                painter.drawLine(0, int(y_top), width_px, int(y_top))
                painter.drawLine(0, int(y_bottom), width_px, int(y_bottom))

        # Axis.
        painter.setPen(QPen(mid, 1))
        painter.drawLine(AXIS_X, PAD, AXIS_X, height - PAD)

        # Rungs. Ticks sit at their true elevations; label text dodges
        # vertically so crowded levels stay readable, with a small leader
        # line pointing back to the tick.
        ys = self._rung_ys()
        spacing = min((abs(b - a) for a, b in zip(ys, ys[1:])),
                      default=1000.0)
        show_counts = spacing >= MIN_COUNT_SPACING
        metrics = QFontMetrics(self.font())
        # ys descend (highest level at top); the solver wants ascending.
        label_ys = list(reversed(ladder_math.dodge_labels(
            list(reversed(ys)), metrics.height() + 2,
            PAD, height - PAD)))
        for cluster, y, label_y in zip(self._rungs, ys, label_ys):
            is_active = (self._level is not None
                         and abs(cluster['level'] - self._level) < 1e-9)
            yi = int(y)
            ly = int(label_y)
            if is_active:
                painter.setPen(QPen(QColor(ACCENT), 2))
            else:
                painter.setPen(QPen(mid, 1))
            painter.drawLine(AXIS_X - 5, yi, AXIS_X + 9, yi)
            if abs(label_y - y) > 1.5:
                painter.setPen(QPen(mid, 1))
                painter.drawLine(AXIS_X + 9, yi, AXIS_X + 12, ly)

            font = painter.font()
            font.setBold(is_active)
            painter.setFont(font)
            painter.setPen(QPen(text_color, 1))
            label = format_number(cluster['level'])
            baseline = ly + metrics.ascent() // 2 - 1
            painter.drawText(AXIS_X + 14, baseline, label)

            count = "(%d)" % cluster['count']
            count_w = metrics.horizontalAdvance(count) if show_counts else 0

            # Level-name text ("000 Level"), dimmed, elided to the space
            # left between the elevation and the count.
            name = cluster.get('label')
            if name:
                name_x = AXIS_X + 14 + metrics.horizontalAdvance(label) + 8
                avail = width_px - name_x - 6 - (count_w + 6 if count_w
                                                 else 0)
                if avail > metrics.horizontalAdvance("…"):
                    painter.setPen(QPen(mid, 1))
                    painter.drawText(
                        name_x, baseline,
                        metrics.elidedText(
                            name, Qt.TextElideMode.ElideRight, avail))

            if show_counts:
                painter.setPen(QPen(mid, 1))
                painter.drawText(width_px - 6 - count_w, baseline, count)
            font.setBold(False)
            painter.setFont(font)
        painter.end()

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------
    def _pick(self, y):
        lo, hi = self._range
        value = ladder_math.y_to_elev(y, lo, hi, self.height(), PAD)
        return ladder_math.snap_elevation(value, self._step)

    def mousePressEvent(self, event):
        if not self.has_data():
            return
        y = event.position().y() if hasattr(event, 'position') else event.y()
        index = ladder_math.hit_rung(y, self._rung_ys(), RUNG_HIT_PX)
        if index is not None:
            self.rungClicked.emit(self._rungs[index])
            return
        self._dragging = True
        self.elevationPicked.emit(self._pick(y))

    def mouseMoveEvent(self, event):
        if self._dragging and self.has_data():
            y = (event.position().y() if hasattr(event, 'position')
                 else event.y())
            self.elevationPicked.emit(self._pick(y))

    def mouseReleaseEvent(self, event):
        if self._dragging and self.has_data():
            self._dragging = False
            y = (event.position().y() if hasattr(event, 'position')
                 else event.y())
            self.elevationPicked.emit(self._pick(y))

    def wheelEvent(self, event):
        if not self.has_data():
            return
        delta = event.angleDelta().y()
        if delta:
            self.stepRequested.emit(1 if delta > 0 else -1)
        event.accept()

    def event(self, ev):
        if ev.type() == QEvent.Type.ToolTip and self.has_data():
            index = ladder_math.hit_rung(ev.pos().y(), self._rung_ys(),
                                         RUNG_HIT_PX)
            if index is not None and index < len(self._tooltips):
                QToolTip.showText(ev.globalPos(), self._tooltips[index], self)
            else:
                QToolTip.hideText()
            return True
        return super().event(ev)
