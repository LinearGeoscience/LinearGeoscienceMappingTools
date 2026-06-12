"""
Page 3: Remove Unused Symbology – wizard page widget.

For each selected categorized layer, removes renderer categories that have
no matching features in the layer data.
"""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QMessageBox, QScrollArea, QFrame,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.core import (
    QgsProject, QgsExpression, QgsExpressionContext,
    QgsExpressionContextUtils, QgsCategorizedSymbolRenderer,
    QgsMessageLog, Qgis,
)

from .widgets import CollapsibleSection, LayerCheckList

try:
    from ..ui_scaling import get_scale_manager
except ImportError:
    from ui_scaling import get_scale_manager

try:
    from .. import plugin_theme as theme
except ImportError:
    import plugin_theme as theme

from .constants import LOG_TAG


def _log(msg, level=Qgis.Info):
    QgsMessageLog.logMessage(msg, LOG_TAG, level)


def get_existing_values(layer, class_attr, log=None):
    """Get the set of unique values for the renderer's classAttribute.

    Handles both simple field names and expressions.

    Args:
        layer: QgsVectorLayer to scan
        class_attr: Field name or expression string
        log: Optional single-argument logging callable

    Returns:
        set of unique values, or None on expression parse error
    """
    # Check if it's a simple field first
    field_idx = layer.fields().indexOf(class_attr)
    if field_idx >= 0:
        return set(layer.uniqueValues(field_idx))

    # Treat as expression
    expr = QgsExpression(class_attr)
    if expr.hasParserError():
        if log:
            log(f"Expression parse error for '{class_attr}': "
                f"{expr.parserErrorString()}")
        return None

    ctx = QgsExpressionContext()
    ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))

    values = set()
    for feat in layer.getFeatures():
        ctx.setFeature(feat)
        values.add(expr.evaluate(ctx))

    return values


def remove_unused_categories(layer, log=None, dry_run=False):
    """Remove unused symbology categories from a categorized layer.

    Args:
        layer: QgsVectorLayer with a categorized renderer
        log: Optional single-argument logging callable
        dry_run: If True, only count without modifying the renderer

    Returns:
        tuple: (removed_count, kept_count); (0, 0) if the layer's renderer
        is not categorized or the class attribute can't be evaluated
    """
    renderer = layer.renderer()
    if not isinstance(renderer, QgsCategorizedSymbolRenderer):
        return 0, 0

    class_attr = renderer.classAttribute()
    existing_values = get_existing_values(layer, class_attr, log=log)
    if existing_values is None:
        return 0, 0

    # Category values may be stored as strings even when the field is
    # numeric, so match on both native and stringified forms
    existing_strs = {str(v) for v in existing_values if v is not None}

    kept = []
    removed = 0
    for cat in renderer.categories():
        val = cat.value()
        # Keep the catch-all (empty value) and categories with matching data
        if val == '' or val in existing_values or str(val) in existing_strs:
            kept.append(cat)
        else:
            removed += 1

    if removed > 0 and not dry_run:
        new_renderer = QgsCategorizedSymbolRenderer(class_attr, kept)
        # Carry over the reference scale - building a fresh renderer would
        # otherwise silently drop it
        new_renderer.setReferenceScale(renderer.referenceScale())
        layer.setRenderer(new_renderer)
        layer.triggerRepaint()

    return removed, len(kept)


# ── RemoveUnusedPage ─────────────────────────────────────────────

class RemoveUnusedPage(QWidget):
    """Wizard page for removing unused symbology categories."""

    status_changed = pyqtSignal(str)
    log_message = pyqtSignal(str)

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.scale = get_scale_manager()
        self._preview_results = {}
        self._init_ui()

    def _init_ui(self):
        s = self.scale

        page_lay = QVBoxLayout(self)
        page_lay.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, s.dimension(8), 0)
        layout.setSpacing(s.dimension(8))

        # --- Layer Selection Section ---
        layer_section = CollapsibleSection("Layer Selection", expanded=True)
        ll = layer_section.content_layout()

        self._layer_list = LayerCheckList()
        ll.addWidget(self._layer_list)

        refresh_btn = QPushButton("Refresh Layers")
        refresh_btn.setStyleSheet(theme.action_button_style(primary=False))
        refresh_btn.clicked.connect(self._refresh_layers)
        ll.addWidget(refresh_btn)

        layout.addWidget(layer_section)

        # --- Preview Section ---
        preview_section = CollapsibleSection("Preview Changes", expanded=False)
        pl = preview_section.content_layout()

        btn_preview = QPushButton("Preview Changes")
        btn_preview.setStyleSheet(theme.action_button_style(primary=False))
        btn_preview.clicked.connect(self._on_preview)
        pl.addWidget(btn_preview)

        self._preview_text = QLabel("Click 'Preview Changes' to scan layers.")
        self._preview_text.setWordWrap(True)
        self._preview_text.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {s.font_size(11)}px; "
            f"font-family: {theme.FONT_FAMILY}; padding: {s.dimension(4)}px;"
        )
        pl.addWidget(self._preview_text)

        layout.addWidget(preview_section)

        # --- Processing Section ---
        process_section = CollapsibleSection("Processing", expanded=True)
        pcl = process_section.content_layout()

        self._process_log = QTextEdit()
        self._process_log.setReadOnly(True)
        self._process_log.setMaximumHeight(s.dimension(150))
        self._process_log.setStyleSheet(
            f"font-size: {s.font_size(10)}px; font-family: monospace; "
            f"background-color: {theme.BG_CARD}; border: 1px solid {theme.BORDER}; "
            f"border-radius: {s.dimension(4)}px;"
        )
        self._process_log.setVisible(False)
        pcl.addWidget(self._process_log)

        layout.addWidget(process_section)

        layout.addStretch()

        # --- Action button ---
        action_layout = QHBoxLayout()
        action_layout.addStretch()
        self.btn_process = QPushButton("Process Selected Layers")
        self.btn_process.setStyleSheet(theme.action_button_style(primary=True))
        self.btn_process.clicked.connect(self._on_process)
        action_layout.addWidget(self.btn_process)
        layout.addLayout(action_layout)

        scroll.setWidget(content)
        page_lay.addWidget(scroll)

        # Initial population
        self._refresh_layers()

    def _refresh_layers(self):
        """Scan project for categorized vector layers."""
        project = QgsProject.instance()
        categorized = []
        for layer_id, layer in project.mapLayers().items():
            if hasattr(layer, 'renderer') and layer.renderer():
                if isinstance(layer.renderer(), QgsCategorizedSymbolRenderer):
                    categorized.append(layer)
        categorized.sort(key=lambda l: l.name())
        self._layer_list.set_layers(categorized)

    def _on_preview(self):
        """Scan selected layers and show counts of categories to remove."""
        project = QgsProject.instance()
        layer_ids = self._layer_list.checked_layer_ids()

        if not layer_ids:
            QMessageBox.information(self, "No Layers", "No layers selected.")
            return

        self._preview_results = {}
        lines = []
        for lid in layer_ids:
            layer = project.mapLayer(lid)
            if not layer:
                continue
            if not isinstance(layer.renderer(), QgsCategorizedSymbolRenderer):
                lines.append(f"<b>{layer.name()}</b>: not categorized, skipping")
                continue
            result = remove_unused_categories(layer, dry_run=True)
            to_remove, to_keep = result
            self._preview_results[lid] = result
            lines.append(
                f"<b>{layer.name()}</b>: {to_remove} to remove, {to_keep} to keep")

        self._preview_text.setText("<br>".join(lines) if lines else "No results.")

    def _on_process(self):
        """Remove unused categories from all selected layers."""
        project = QgsProject.instance()
        layer_ids = self._layer_list.checked_layer_ids()

        if not layer_ids:
            QMessageBox.information(self, "No Layers", "No layers selected.")
            return

        reply = QMessageBox.question(
            self, "Confirm",
            f"Remove unused symbology from {len(layer_ids)} layer(s)?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.status_changed.emit("in_progress")
        self._process_log.setVisible(True)
        self._process_log.clear()

        total_removed = 0
        total_kept = 0
        processed = 0

        for lid in layer_ids:
            layer = project.mapLayer(lid)
            if not layer:
                continue

            if not isinstance(layer.renderer(), QgsCategorizedSymbolRenderer):
                msg = f"{layer.name()}: not categorized, skipped"
                self._process_log.append(msg)
                self.log_message.emit(msg)
                continue

            removed, kept = remove_unused_categories(layer, log=_log)
            total_removed += removed
            total_kept += kept
            processed += 1
            msg = f"{layer.name()}: removed {removed}, kept {kept}"
            self._process_log.append(msg)
            self.log_message.emit(msg)
            _log(msg)

        summary = (f"Done: processed {processed} layer(s), "
                   f"removed {total_removed} categories, kept {total_kept}")
        self._process_log.append(f"\n{summary}")
        self.log_message.emit(summary)
        _log(summary)

        QMessageBox.information(self, "Complete", summary)
        self.status_changed.emit("complete")

        # Refresh preview text
        self._on_preview()
