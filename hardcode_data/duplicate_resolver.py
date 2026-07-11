"""
Interactive duplicate-UUID resolver.

Steps through each group of features that share a UUID value, zooms the canvas to
them and outlines them with persistent QgsHighlights, and lets the user either
regenerate the UUID (a fresh uuid.uuid4()) on one feature or delete one. Edits
are applied live to the layer.

Reuses:
- zoom + CRS-transform maths from script_adddata/reconcile/dialog.py
- QgsHighlight lifecycle from map_cleaning/core/geometry_issues_dialog.py
- edit-session/commit pattern from hardcode_data/analysis.py:apply_layer_report
"""

import uuid

from qgis.gui import QgsHighlight
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame, QMessageBox,
)
from qgis.core import (
    QgsRectangle, QgsCoordinateTransform, QgsProject,
    QgsCoordinateReferenceSystem, QgsMessageLog, Qgis,
)

try:
    from .. import plugin_theme as theme
except ImportError:
    import plugin_theme as theme

try:
    from ..ui_scaling import get_scale_manager
except ImportError:
    from ui_scaling import get_scale_manager

from .analysis import is_empty

LOG_TAG = "HardcodeData"

# Monochrome outline (matches the plugin's minimal aesthetic).
_OUTLINE = QColor(50, 50, 50)
_FILL = QColor(120, 120, 120, 60)


class DuplicateUuidResolverDialog(QDialog):
    """Walk through duplicate-UUID groups and resolve them one feature at a time."""

    def __init__(self, iface, layer, uuid_field, duplicates, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.layer = layer
        self.uuid_field = uuid_field
        self.scale = get_scale_manager()
        self._highlights = []
        self.resolved_count = 0

        # Build a working list of groups: [{'value': uuid, 'fids': [...]}, ...].
        # Only values that are still duplicated (>1 feature) are actionable.
        self._groups = [
            {'value': value, 'fids': list(fids)}
            for value, fids in sorted(duplicates.items())
            if len(fids) > 1
        ]
        self._index = 0

        self.setWindowTitle("Resolve Duplicate UUIDs")
        self.setMinimumSize(*self.scale.dialog_size(560, 460))
        try:
            self.setStyleSheet(theme.dialog_style())
        except Exception:
            pass
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._setup_ui()
        self._show_group()

    # ── UI construction ────────────────────────────────────────────

    def _setup_ui(self):
        s = self.scale
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*s.margins(12, 12, 12, 12))
        layout.setSpacing(s.dimension(8))

        intro = QLabel(
            f"Field <b>{self.uuid_field}</b> has features sharing the same UUID. "
            "For each group, regenerate the UUID on a feature or delete one so "
            "every feature is unique.")
        intro.setWordWrap(True)
        intro.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {s.font_size(11)}px; "
            f"font-family: {theme.FONT_FAMILY};")
        layout.addWidget(intro)

        self._header = QLabel()
        self._header.setStyleSheet(
            f"font-weight: bold; font-size: {s.font_size(13)}px; "
            f"font-family: {theme.FONT_FAMILY}; color: {theme.TEXT_PRIMARY};")
        layout.addWidget(self._header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        try:
            sep.setStyleSheet(theme.separator_style())
        except Exception:
            pass
        layout.addWidget(sep)

        # Scrollable list of feature rows for the current group.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._rows_host = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, s.dimension(6), 0)
        self._rows_layout.setSpacing(s.dimension(6))
        self._rows_layout.addStretch()
        scroll.setWidget(self._rows_host)
        layout.addWidget(scroll, 1)

        # Navigation / actions
        nav = QHBoxLayout()
        nav.setSpacing(s.dimension(8))
        self._prev_btn = QPushButton("← Previous")
        self._prev_btn.setStyleSheet(theme.action_button_style(primary=False))
        self._prev_btn.clicked.connect(self._on_prev)
        self._next_btn = QPushButton("Next →")
        self._next_btn.setStyleSheet(theme.action_button_style(primary=False))
        self._next_btn.clicked.connect(self._on_next)
        nav.addWidget(self._prev_btn)
        nav.addWidget(self._next_btn)
        nav.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(theme.action_button_style(primary=True))
        close_btn.clicked.connect(self.accept)
        nav.addWidget(close_btn)
        layout.addLayout(nav)

    # ── group rendering ────────────────────────────────────────────

    def _clear_rows(self):
        while self._rows_layout.count() > 1:  # keep the trailing stretch
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _show_group(self):
        self._clear_highlights()
        self._clear_rows()

        if not self._groups:
            self._header.setText("All duplicate UUIDs resolved ✓")
            self._prev_btn.setEnabled(False)
            self._next_btn.setEnabled(False)
            empty = QLabel("Nothing left to resolve. You can close this window.")
            empty.setWordWrap(True)
            empty.setStyleSheet(
                f"color: {theme.TEXT_SECONDARY}; "
                f"font-family: {theme.FONT_FAMILY};")
            self._rows_layout.insertWidget(0, empty)
            return

        self._index = max(0, min(self._index, len(self._groups) - 1))
        group = self._groups[self._index]
        self._header.setText(
            f"Duplicate {self._index + 1} of {len(self._groups)} — "
            f"UUID {group['value']} — {len(group['fids'])} features")
        self._prev_btn.setEnabled(self._index > 0)
        self._next_btn.setEnabled(self._index < len(self._groups) - 1)

        for fid in group['fids']:
            self._rows_layout.insertWidget(
                self._rows_layout.count() - 1, self._build_row(fid))

        self._zoom_and_highlight(group['fids'])

    def _build_row(self, fid):
        s = self.scale
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background-color: {theme.BG_CARD}; "
            f"border: 1px solid {theme.BORDER}; "
            f"border-radius: {s.dimension(4)}px; }}")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(*s.margins(8, 6, 8, 6))
        rl.setSpacing(s.dimension(8))

        label = QLabel(f"<b>Feature {fid}</b>  {self._attr_summary(fid)}")
        label.setStyleSheet(
            f"font-size: {s.font_size(11)}px; "
            f"font-family: {theme.FONT_FAMILY}; color: {theme.TEXT_PRIMARY}; "
            "border: none;")
        rl.addWidget(label, 1)

        btn_regen = QPushButton("Regenerate UUID")
        btn_regen.setStyleSheet(theme.action_button_style(primary=False))
        btn_regen.clicked.connect(lambda _c, f=fid: self._on_regenerate(f))
        rl.addWidget(btn_regen)

        btn_del = QPushButton("Delete")
        btn_del.setStyleSheet(theme.action_button_style(primary=False))
        btn_del.clicked.connect(lambda _c, f=fid: self._on_delete(f))
        rl.addWidget(btn_del)
        return row

    def _attr_summary(self, fid, max_fields=3):
        """A few populated, identifying field values for the feature (or '')."""
        feat = self.layer.getFeature(fid)
        if feat is None or not feat.isValid():
            return ""
        parts = []
        for field in self.layer.fields():
            name = field.name()
            if name == self.uuid_field:
                continue
            val = feat[name]
            if not is_empty(val):
                parts.append(f"{name}={val}")
            if len(parts) >= max_fields:
                break
        return " · ".join(parts)

    # ── map zoom + highlight ───────────────────────────────────────

    def _clear_highlights(self):
        for h in self._highlights:
            try:
                h.hide()
            except RuntimeError:
                pass
        self._highlights = []

    def _zoom_and_highlight(self, fids):
        if self.iface is None:
            return
        canvas = self.iface.mapCanvas()
        if canvas is None:
            return

        geoms = []
        for fid in fids:
            feat = self.layer.getFeature(fid)
            if feat is None or not feat.isValid():
                continue
            geom = feat.geometry()
            if geom is not None and not geom.isNull() and not geom.isEmpty():
                geoms.append(geom)

        if not geoms:
            return  # non-spatial / empty geometry — nothing to show on the map

        src_crs = self.layer.crs() or QgsCoordinateReferenceSystem()
        dst_crs = canvas.mapSettings().destinationCrs()

        rect = QgsRectangle()
        rect.setMinimal()
        for g in geoms:
            rect.combineExtentWith(g.boundingBox())
        try:
            if src_crs.isValid() and dst_crs.isValid() and src_crs != dst_crs:
                xform = QgsCoordinateTransform(
                    src_crs, dst_crs, QgsProject.instance())
                rect = xform.transformBoundingBox(rect)
        except Exception:
            pass
        if not rect.isEmpty():
            rect.scale(1.6)  # breathing room around the features
            canvas.setExtent(rect)
            canvas.refresh()

        # Persistent outline per feature until the group changes or we close.
        for g in geoms:
            try:
                h = QgsHighlight(canvas, g, self.layer)
                h.setColor(_OUTLINE)
                h.setFillColor(_FILL)
                h.setWidth(3)
                h.show()
                self._highlights.append(h)
            except Exception as exc:  # pragma: no cover - canvas edge cases
                QgsMessageLog.logMessage(
                    f"duplicate-resolver highlight failed: {exc}",
                    LOG_TAG, Qgis.Warning)

    # ── navigation ─────────────────────────────────────────────────

    def _on_prev(self):
        if self._index > 0:
            self._index -= 1
            self._show_group()

    def _on_next(self):
        if self._index < len(self._groups) - 1:
            self._index += 1
            self._show_group()

    # ── edit operations ────────────────────────────────────────────

    def _ensure_editable(self):
        if self.layer.isEditable():
            return True
        if not self.layer.startEditing():
            QMessageBox.warning(
                self, "Cannot Edit",
                f"Could not start editing '{self.layer.name()}'.")
            return False
        return True

    def _on_regenerate(self, fid):
        uuid_idx = self.layer.fields().indexOf(self.uuid_field)
        if uuid_idx == -1:
            QMessageBox.warning(
                self, "Field Missing",
                f"Field '{self.uuid_field}' no longer exists on the layer.")
            return
        if not self._ensure_editable():
            return

        new_value = str(uuid.uuid4())
        ok = self.layer.changeAttributeValue(fid, uuid_idx, new_value)
        if ok and self.layer.commitChanges():
            self.layer.triggerRepaint()
            self.resolved_count += 1
            self._after_resolution(fid, f"UUID regenerated on feature {fid}")
        else:
            self.layer.rollBack()
            QMessageBox.warning(
                self, "Failed",
                f"Could not update the UUID on feature {fid}.")

    def _on_delete(self, fid):
        reply = QMessageBox.question(
            self, "Delete Feature",
            f"Delete feature {fid} from '{self.layer.name()}'?\n\n"
            "This permanently removes the feature.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not self._ensure_editable():
            return

        if self.layer.deleteFeature(fid) and self.layer.commitChanges():
            self.layer.updateExtents()
            self.layer.triggerRepaint()
            self.resolved_count += 1
            self._after_resolution(fid, f"Feature {fid} deleted")
        else:
            self.layer.rollBack()
            QMessageBox.warning(
                self, "Failed", f"Could not delete feature {fid}.")

    def _after_resolution(self, fid, _msg):
        """Drop the feature from the current group; resolved groups disappear."""
        if not self._groups:
            return
        group = self._groups[self._index]
        if fid in group['fids']:
            group['fids'].remove(fid)
        # A group with one (or zero) remaining feature is no longer a duplicate.
        if len(group['fids']) <= 1:
            self._groups.pop(self._index)
        self._show_group()

    # ── cleanup ────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._clear_highlights()
        super().closeEvent(event)

    def reject(self):
        self._clear_highlights()
        super().reject()

    def accept(self):
        self._clear_highlights()
        super().accept()
