"""
Page 2: Plot Symbol Features – wizard page widget.

Refactored from script_plotsymbols.py. Core grid-creation logic moved verbatim;
UI rewritten as QWidget page that fits inside RecodeWorkflowWizard.
"""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QHeaderView, QCheckBox,
    QComboBox, QMessageBox, QAbstractItemView, QScrollArea,
    QFrame,
)
from qgis.PyQt.QtCore import pyqtSignal
from qgis.core import (
    QgsProject, QgsFeature, QgsGeometry, QgsPointXY,
    QgsRectangle, QgsWkbTypes, QgsMessageLog, Qgis,
    QgsCoordinateTransform,
)

from .widgets import CollapsibleSection

try:
    from ..ui_scaling import get_scale_manager
except ImportError:
    from ui_scaling import get_scale_manager

try:
    from .. import plugin_theme as theme
except ImportError:
    import plugin_theme as theme

from .constants import (
    LAYER_CONFIG, FEATURE_SIZE, SPACING, BLOCK_GAP, ROW_WRAP_COUNT, LOG_TAG,
)

try:
    from ..layer_select import layer_display_name
except ImportError:
    from layer_select import layer_display_name


# ── Module-level helpers (moved verbatim from script_plotsymbols.py) ──

_plotted_features = {}  # {layer_id: [fid, ...]}


def _log(msg, level=Qgis.Info):
    QgsMessageLog.logMessage(msg, LOG_TAG, level)


def get_unique_categories(table_layer, key_field):
    """Gather unique non-null values from *key_field* in the table layer."""
    if table_layer is None:
        _log("Code table not found in project", Qgis.Warning)
        return []
    if key_field not in table_layer.fields().names():
        _log(f"Field '{key_field}' not found in table '{table_layer.name()}'", Qgis.Warning)
        return []
    categories = set()
    for feat in table_layer.getFeatures():
        val = feat[key_field]
        if val is not None and str(val).strip():
            categories.add(val)
    _log(f"Found {len(categories)} unique categories in '{table_layer.name()}'.'{key_field}'")
    return sorted(categories)


def create_grid_features(layer, origin_x, origin_y, categories, code_field,
                         geom_type, feature_size, spacing, vertical=False):
    """Create features for each category in a grid layout."""
    features = []
    x, y = origin_x, origin_y
    for cat in categories:
        if geom_type == QgsWkbTypes.PointGeometry:
            geom = QgsGeometry.fromPointXY(QgsPointXY(x, y))
        elif geom_type == QgsWkbTypes.LineGeometry:
            geom = QgsGeometry.fromPolylineXY([
                QgsPointXY(x, y),
                QgsPointXY(x + feature_size, y),
            ])
        else:
            rect = QgsRectangle(x, y, x + feature_size, y + feature_size)
            geom = QgsGeometry.fromRect(rect)

        feat = QgsFeature(layer.fields())
        feat.setGeometry(geom)
        if code_field in layer.fields().names():
            feat.setAttribute(code_field, cat)
        features.append(feat)

        if vertical:
            y -= spacing
        else:
            x += spacing
            col = len(features) % ROW_WRAP_COUNT
            if col == 0:
                x = origin_x
                y -= spacing
    return features


# ── PlotSymbolsPage ──────────────────────────────────────────────

class PlotSymbolsPage(QWidget):
    """Wizard page for plotting sample features per code category."""

    status_changed = pyqtSignal(str)
    log_message = pyqtSignal(str)

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.scale = get_scale_manager()
        self._init_ui()
        self._populate_default_mappings()

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

        # --- Remove previous banner (hidden by default) ---
        self.btn_remove = QPushButton()
        self.btn_remove.setStyleSheet(f"""
            QPushButton {{
                background-color: #FFF3E0;
                color: #E65100;
                border: 1px solid #FFB74D;
                border-radius: {s.dimension(4)}px;
                padding: {s.dimension(8)}px {s.dimension(12)}px;
                font-size: {s.font_size(12)}px;
                font-family: {theme.FONT_FAMILY};
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: #FFE0B2;
                border-color: #FF9800;
            }}
        """)
        self.btn_remove.clicked.connect(self._on_remove_previous)
        self.btn_remove.setVisible(False)
        layout.addWidget(self.btn_remove)

        # --- Layer Mappings Section ---
        mappings_section = CollapsibleSection("Layer Mappings", expanded=True)
        ml = mappings_section.content_layout()

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Layer", "Code Table", "Key Field", "Layer Field", ""])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 5):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {theme.BG_CARD};
                border: 1px solid {theme.BORDER};
                border-radius: {s.dimension(4)}px;
                font-size: {s.font_size(12)}px;
                font-family: {theme.FONT_FAMILY};
                gridline-color: {theme.BORDER};
            }}
            QHeaderView::section {{
                background-color: {theme.BG_PRIMARY};
                color: {theme.TEXT_SECONDARY};
                font-weight: bold;
                font-size: {s.font_size(11)}px;
                border: none;
                border-bottom: 1px solid {theme.BORDER};
                padding: {s.dimension(4)}px {s.dimension(8)}px;
            }}
            QTableWidget::item {{
                padding: {s.dimension(4)}px {s.dimension(6)}px;
            }}
            QTableWidget::item:selected {{
                background-color: #E8F5E9;
                color: {theme.TEXT_PRIMARY};
            }}
        """)
        ml.addWidget(self.table)

        mapping_btn_layout = QHBoxLayout()
        mapping_btn_layout.setSpacing(s.spacing(6))

        btn_add = QPushButton("Add Mapping")
        btn_add.setStyleSheet(theme.action_button_style(primary=False))
        btn_add.clicked.connect(self._on_add_mapping)

        btn_refresh = QPushButton("Refresh Defaults")
        btn_refresh.setStyleSheet(theme.action_button_style(primary=False))
        btn_refresh.clicked.connect(self._on_refresh_defaults)

        mapping_btn_layout.addWidget(btn_add)
        mapping_btn_layout.addWidget(btn_refresh)
        mapping_btn_layout.addStretch()
        ml.addLayout(mapping_btn_layout)

        layout.addWidget(mappings_section)

        # --- Options Section ---
        options_section = CollapsibleSection("Options", expanded=True)
        ol = options_section.content_layout()

        self.chk_zoom = QCheckBox("Zoom to plotted features")
        self.chk_zoom.setChecked(True)
        self.chk_zoom.setStyleSheet(
            f"font-size: {s.font_size(12)}px; font-family: {theme.FONT_FAMILY};"
        )
        ol.addWidget(self.chk_zoom)

        self.chk_select_all = QCheckBox("Select all mapped layers")
        self.chk_select_all.setChecked(True)
        self.chk_select_all.setStyleSheet(
            f"font-size: {s.font_size(12)}px; font-family: {theme.FONT_FAMILY};"
        )
        ol.addWidget(self.chk_select_all)

        layout.addWidget(options_section)
        layout.addStretch()

        # --- Action button ---
        action_layout = QHBoxLayout()
        action_layout.addStretch()
        self.btn_plot = QPushButton("Plot Features")
        self.btn_plot.setStyleSheet(theme.action_button_style(primary=True))
        self.btn_plot.clicked.connect(self._on_plot)
        action_layout.addWidget(self.btn_plot)
        layout.addLayout(action_layout)

        scroll.setWidget(content)
        page_lay.addWidget(scroll)

        self._update_remove_button()

    # ─── mapping helpers ──────────────────────────────────────────

    def _populate_default_mappings(self):
        project = QgsProject.instance()
        for layer_name, (table_name, key_field, layer_field) in LAYER_CONFIG.items():
            found = project.mapLayersByName(layer_name)
            tables = project.mapLayersByName(table_name)
            if found and tables:
                # First match per name; the row's Layer dropdown lists every
                # candidate (with file-path suffix) so the user can switch to
                # the correct one when duplicate-named layers exist.
                self._add_table_row(found[0], tables[0], key_field, layer_field)

    def _combo_style(self):
        s = self.scale
        return (
            f"QComboBox {{ font-size: {s.font_size(11)}px; "
            f"font-family: {theme.FONT_FAMILY}; color: {theme.TEXT_PRIMARY}; "
            f"background-color: {theme.BG_CARD}; "
            f"border: 1px solid {theme.BORDER}; "
            f"border-radius: {s.dimension(3)}px; padding: {s.dimension(2)}px; }}"
        )

    def _collect_layers(self):
        """Split project layers into geometry layers and non-spatial tables."""
        project = QgsProject.instance()
        geom_layers = []
        table_layers = []
        for layer in project.mapLayers().values():
            if hasattr(layer, 'geometryType'):
                if layer.geometryType() == QgsWkbTypes.NullGeometry:
                    table_layers.append(layer)
                else:
                    geom_layers.append(layer)
        return geom_layers, table_layers

    def _populate_field_combo(self, combo, layer_id, preferred=None):
        """Fill a field-name combo from *layer_id*, keeping the current
        selection (or *preferred*) when that field still exists."""
        keep = preferred if preferred is not None else combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        layer = QgsProject.instance().mapLayer(layer_id) if layer_id else None
        if layer is not None:
            for field in layer.fields():
                combo.addItem(field.name())
        if keep:
            ki = combo.findText(keep)
            if ki >= 0:
                combo.setCurrentIndex(ki)
        combo.blockSignals(False)

    def _add_table_row(self, layer, table_layer, key_field, layer_field):
        """Add a fully editable mapping row. Every cell is a dropdown so layers
        with duplicate/similar names can be disambiguated by the file-path
        suffix in their display name; currentData holds the layer id."""
        geom_layers, table_layers = self._collect_layers()
        combo_style = self._combo_style()

        row = self.table.rowCount()
        self.table.insertRow(row)

        # Col 0: target geometry layer
        layer_combo = QComboBox()
        layer_combo.setStyleSheet(combo_style)
        for lyr in sorted(geom_layers, key=lambda l: l.name()):
            layer_combo.addItem(layer_display_name(lyr), lyr.id())
        if layer is not None:
            li = layer_combo.findData(layer.id())
            if li >= 0:
                layer_combo.setCurrentIndex(li)
        self.table.setCellWidget(row, 0, layer_combo)

        # Col 1: code table (non-spatial tables first, then geometry layers)
        table_combo = QComboBox()
        table_combo.setStyleSheet(combo_style)
        for lyr in sorted(table_layers, key=lambda l: l.name()):
            table_combo.addItem(layer_display_name(lyr), lyr.id())
        for lyr in sorted(geom_layers, key=lambda l: l.name()):
            table_combo.addItem(layer_display_name(lyr), lyr.id())
        if table_layer is not None:
            ti = table_combo.findData(table_layer.id())
            if ti >= 0:
                table_combo.setCurrentIndex(ti)
        self.table.setCellWidget(row, 1, table_combo)

        # Col 2: key field (from code table), Col 3: layer field (from target)
        key_combo = QComboBox()
        key_combo.setStyleSheet(combo_style)
        self.table.setCellWidget(row, 2, key_combo)

        field_combo = QComboBox()
        field_combo.setStyleSheet(combo_style)
        self.table.setCellWidget(row, 3, field_combo)

        self._populate_field_combo(key_combo, table_combo.currentData(), key_field)
        self._populate_field_combo(field_combo, layer_combo.currentData(), layer_field)

        # Switching a layer/table re-derives the available fields for that row
        table_combo.currentIndexChanged.connect(
            lambda _i: self._populate_field_combo(key_combo, table_combo.currentData()))
        layer_combo.currentIndexChanged.connect(
            lambda _i: self._populate_field_combo(field_combo, layer_combo.currentData()))

        # Col 4: per-row remove button (cells are dropdowns, so row-selection
        # based removal isn't reliable — give each row its own button)
        btn_remove = QPushButton("✕")
        btn_remove.setToolTip("Remove this mapping")
        btn_remove.setStyleSheet(theme.action_button_style(primary=False))
        btn_remove.clicked.connect(lambda _c, b=btn_remove: self._remove_row_for_button(b))
        self.table.setCellWidget(row, 4, btn_remove)

    def _on_add_mapping(self):
        """Add a new editable row. The row's dropdowns let the user pick the
        exact layer/table and fields inline, so no separate dialog is needed."""
        geom_layers, table_layers = self._collect_layers()
        if not geom_layers:
            QMessageBox.information(self, "No Layers",
                                   "No geometry layers found in the current project.")
            return
        layer = sorted(geom_layers, key=lambda l: l.name())[0]
        table_pool = table_layers or geom_layers
        table_layer = sorted(table_pool, key=lambda l: l.name())[0]
        self._add_table_row(layer, table_layer, "", "")

    def _on_refresh_defaults(self):
        self.table.setRowCount(0)
        self._populate_default_mappings()
        self.log_message.emit(f"Refreshed default mappings ({self.table.rowCount()} rows)")

    def _remove_row_for_button(self, btn):
        """Remove the row whose remove-button is *btn* (rows shift on delete,
        so resolve the current index by widget identity)."""
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 4) is btn:
                self.table.removeRow(row)
                return

    def _get_mappings(self):
        mappings = []
        for row in range(self.table.rowCount()):
            layer_combo = self.table.cellWidget(row, 0)
            table_combo = self.table.cellWidget(row, 1)
            key_combo = self.table.cellWidget(row, 2)
            field_combo = self.table.cellWidget(row, 3)
            if not all([layer_combo, table_combo, key_combo, field_combo]):
                continue
            mappings.append({
                'layer_id': layer_combo.currentData(),
                'layer_display': layer_combo.currentText().strip(),
                'table_id': table_combo.currentData(),
                'table_display': table_combo.currentText().strip(),
                'key_field': key_combo.currentText().strip(),
                'layer_field': field_combo.currentText().strip(),
            })
        return mappings

    # ─── plot logic (verbatim from script_plotsymbols.py) ─────────

    def _on_plot(self):
        global _plotted_features

        self.status_changed.emit("in_progress")
        self.log_message.emit("--- Plot Features started ---")

        canvas = self.iface.mapCanvas()
        extent = canvas.extent()

        if extent.isEmpty() or extent.width() < 1e-6:
            QMessageBox.warning(self, "No Map Extent",
                                "The map canvas has no valid extent. "
                                "Please open a project with visible layers first.")
            self.status_changed.emit("not_started")
            return

        mappings = self._get_mappings()
        if not mappings:
            QMessageBox.warning(self, "No Mappings",
                                "No valid layer mappings configured. "
                                "Add at least one mapping before plotting.")
            self.status_changed.emit("not_started")
            return

        project = QgsProject.instance()
        project_crs = project.crs()
        canvas_center = extent.center()

        resolved = []
        for m in mappings:
            layer = project.mapLayer(m['layer_id']) if m['layer_id'] else None
            if layer is None:
                self.log_message.emit(f"Layer '{m['layer_display']}' no longer in project, skipping")
                continue
            layer_crs = layer.crs()

            if m['layer_field'] not in layer.fields().names():
                self.log_message.emit(
                    f"Field '{m['layer_field']}' not found on '{layer.name()}', skipping")
                continue

            table_layer = project.mapLayer(m['table_id']) if m['table_id'] else None
            categories = get_unique_categories(table_layer, m['key_field'])
            if not categories:
                self.log_message.emit(f"No categories for '{m['table_display']}', skipping")
                continue

            if layer_crs != project_crs:
                xform = QgsCoordinateTransform(project_crs, layer_crs, project)
                layer_center = xform.transform(canvas_center)
            else:
                layer_center = canvas_center

            is_line = layer.geometryType() == QgsWkbTypes.LineGeometry
            if is_line:
                block_width = SPACING
            else:
                cols = min(len(categories), ROW_WRAP_COUNT)
                block_width = cols * SPACING

            resolved.append({
                'layer': layer,
                'categories': categories,
                'field': m['layer_field'],
                'is_line': is_line,
                'block_width': block_width,
                'center': layer_center,
            })

        if not resolved:
            QMessageBox.warning(self, "No Valid Mappings",
                                "None of the configured mappings could be resolved.")
            self.status_changed.emit("not_started")
            return

        total_width = (sum(r['block_width'] for r in resolved)
                       + BLOCK_GAP * (len(resolved) - 1))
        ref_center = resolved[0]['center']
        start_x = ref_center.x() - total_width / 2.0

        total_features = 0
        total_layers = 0
        errors = []
        all_bounds = QgsRectangle()
        current_x = start_x

        for r in resolved:
            layer = r['layer']
            geom_type = layer.geometryType()
            layer_center = r['center']
            count_before = layer.featureCount()

            feats = create_grid_features(
                layer, current_x, layer_center.y(),
                r['categories'], r['field'],
                geom_type, FEATURE_SIZE, SPACING,
                vertical=r['is_line'],
            )

            if feats:
                layer.startEditing()
                ok = layer.addFeatures(feats)
                if ok:
                    commit_ok = layer.commitChanges()
                    if commit_ok:
                        layer.updateExtents()
                        count_after = layer.featureCount()
                        num_added = count_after - count_before

                        new_fids = [f.id() for f in feats if f.id() >= 0]
                        if not new_fids:
                            placed_rect = QgsRectangle()
                            for f in feats:
                                if f.hasGeometry():
                                    placed_rect.combineExtentWith(f.geometry().boundingBox())
                            if not placed_rect.isEmpty():
                                placed_rect.grow(SPACING * 0.1)
                                for f in layer.getFeatures():
                                    if (f.hasGeometry()
                                            and placed_rect.contains(f.geometry().boundingBox())):
                                        if f.id() not in new_fids:
                                            new_fids.append(f.id())

                        if layer.id() not in _plotted_features:
                            _plotted_features[layer.id()] = []
                        _plotted_features[layer.id()].extend(new_fids)

                        total_features += num_added
                        total_layers += 1

                        for f in feats:
                            if f.hasGeometry():
                                all_bounds.combineExtentWith(f.geometry().boundingBox())
                    else:
                        layer.rollBack()
                        errors.append(f"Commit failed for '{layer.name()}'")
                else:
                    layer.rollBack()
                    errors.append(f"Failed to add features to '{layer.name()}'")

            current_x += r['block_width'] + BLOCK_GAP

        canvas.refresh()

        if self.chk_zoom.isChecked() and not all_bounds.isEmpty():
            zoom_extent = all_bounds
            first_layer_crs = resolved[0]['layer'].crs()
            if first_layer_crs != project_crs:
                xform_back = QgsCoordinateTransform(first_layer_crs, project_crs, project)
                zoom_extent = xform_back.transformBoundingBox(all_bounds)
            zoom_extent.grow(zoom_extent.width() * 0.1)
            canvas.setExtent(zoom_extent)
            canvas.refresh()

        self._update_remove_button()

        self.log_message.emit(
            f"Plot complete: {total_features} features in {total_layers} layers, "
            f"{len(errors)} errors")

        if errors:
            QMessageBox.warning(self, "Partial Success",
                                f"Added {total_features} features to {total_layers} layer(s).\n\n"
                                f"Errors:\n" + "\n".join(errors))
        elif total_features > 0:
            QMessageBox.information(self, "Plot Complete",
                                    f"Added {total_features} features to {total_layers} layer(s).")
        else:
            QMessageBox.information(self, "Nothing Plotted",
                                    "No features were created. Check the QGIS log for details.")

        self.status_changed.emit("complete" if total_features > 0 else "not_started")

    # ─── remove previously plotted features ───────────────────────

    def _on_remove_previous(self):
        global _plotted_features

        if not _plotted_features:
            return

        total = sum(len(fids) for fids in _plotted_features.values())
        reply = QMessageBox.question(
            self, "Remove Features",
            f"Remove {total} previously plotted feature(s)?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.log_message.emit(f"Removing {total} previously plotted features...")
        project = QgsProject.instance()
        removed = 0
        errors = []

        for layer_id, fids in list(_plotted_features.items()):
            layer = project.mapLayer(layer_id)
            if layer is None:
                del _plotted_features[layer_id]
                continue

            layer.startEditing()
            ok = layer.deleteFeatures(fids)
            if ok:
                commit_ok = layer.commitChanges()
                if commit_ok:
                    layer.updateExtents()
                    removed += len(fids)
                    del _plotted_features[layer_id]
                else:
                    layer.rollBack()
                    errors.append(f"Commit failed for '{layer.name()}'")
            else:
                layer.rollBack()
                errors.append(f"Failed to remove from '{layer.name()}'")

        self.iface.mapCanvas().refresh()
        self._update_remove_button()

        self.log_message.emit(f"Removal complete: {removed} removed, {len(errors)} errors")

        if errors:
            QMessageBox.warning(self, "Partial Removal",
                                f"Removed {removed} features.\n\nErrors:\n" + "\n".join(errors))
        else:
            QMessageBox.information(self, "Removal Complete",
                                    f"Removed {removed} features.")

    def _update_remove_button(self):
        total = sum(len(fids) for fids in _plotted_features.values())
        if total > 0:
            self.btn_remove.setText(f"Remove {total} previously plotted feature(s)")
            self.btn_remove.setVisible(True)
        else:
            self.btn_remove.setVisible(False)
