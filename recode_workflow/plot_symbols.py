"""
Page 2: Plot Symbol Features – wizard page widget.

Refactored from script_plotsymbols.py. Core grid-creation logic moved verbatim;
UI rewritten as QWidget page that fits inside RecodeWorkflowWizard.
"""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QComboBox, QMessageBox, QAbstractItemView, QDialog, QScrollArea,
    QFrame,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
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

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Layer", "Code Table", "Key Field", "Layer Field"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 4):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
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

        btn_remove_row = QPushButton("Remove Selected")
        btn_remove_row.setStyleSheet(theme.action_button_style(primary=False))
        btn_remove_row.clicked.connect(self._on_remove_mapping)

        btn_refresh = QPushButton("Refresh Defaults")
        btn_refresh.setStyleSheet(theme.action_button_style(primary=False))
        btn_refresh.clicked.connect(self._on_refresh_defaults)

        mapping_btn_layout.addWidget(btn_add)
        mapping_btn_layout.addWidget(btn_remove_row)
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
                # First match per name; the display suffix makes the chosen
                # geopackage visible so the user can correct via Add Mapping
                self._add_table_row(found[0], tables[0], key_field, layer_field)

    def _add_table_row(self, layer, table_layer, key_field, layer_field):
        """Add a mapping row. Layer IDs in Qt.UserRole are the source of truth;
        the visible text is just the display name."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        layer_item = QTableWidgetItem(layer_display_name(layer))
        layer_item.setData(Qt.UserRole, layer.id())
        self.table.setItem(row, 0, layer_item)
        table_item = QTableWidgetItem(layer_display_name(table_layer))
        table_item.setData(Qt.UserRole, table_layer.id())
        self.table.setItem(row, 1, table_item)
        self.table.setItem(row, 2, QTableWidgetItem(key_field))
        self.table.setItem(row, 3, QTableWidgetItem(layer_field))

    def _on_add_mapping(self):
        project = QgsProject.instance()
        all_layers = project.mapLayers()
        geom_layers = []
        table_layers = []
        for layer_id, layer in all_layers.items():
            if hasattr(layer, 'geometryType'):
                if layer.geometryType() == QgsWkbTypes.NullGeometry:
                    table_layers.append(layer)
                else:
                    geom_layers.append(layer)

        if not geom_layers:
            QMessageBox.information(self, "No Layers",
                                   "No geometry layers found in the current project.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Add Layer Mapping")
        dlg.setMinimumWidth(self.scale.dimension(400))
        dlg.setStyleSheet(theme.dialog_style())
        dlg_layout = QVBoxLayout(dlg)

        dlg_layout.addWidget(QLabel("Target Layer:"))
        combo_layer = QComboBox()
        for lyr in sorted(geom_layers, key=lambda l: l.name()):
            combo_layer.addItem(layer_display_name(lyr), lyr.id())
        dlg_layout.addWidget(combo_layer)

        dlg_layout.addWidget(QLabel("Code Table:"))
        combo_table = QComboBox()
        for lyr in sorted(table_layers, key=lambda l: l.name()):
            combo_table.addItem(layer_display_name(lyr), lyr.id())
        for lyr in sorted(geom_layers, key=lambda l: l.name()):
            combo_table.addItem(layer_display_name(lyr), lyr.id())
        dlg_layout.addWidget(combo_table)

        dlg_layout.addWidget(QLabel("Key Field (in Code Table):"))
        combo_key = QComboBox()
        dlg_layout.addWidget(combo_key)

        dlg_layout.addWidget(QLabel("Layer Field (on Target Layer):"))
        combo_field = QComboBox()
        dlg_layout.addWidget(combo_field)

        def update_key_fields():
            combo_key.clear()
            table_id = combo_table.currentData()
            if table_id:
                lyr = project.mapLayer(table_id)
                if lyr:
                    for field in lyr.fields():
                        combo_key.addItem(field.name())

        def update_layer_fields():
            combo_field.clear()
            layer_id = combo_layer.currentData()
            if layer_id:
                lyr = project.mapLayer(layer_id)
                if lyr:
                    for field in lyr.fields():
                        combo_field.addItem(field.name())

        combo_table.currentIndexChanged.connect(update_key_fields)
        combo_layer.currentIndexChanged.connect(update_layer_fields)
        update_key_fields()
        update_layer_fields()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_ok = QPushButton("Add")
        btn_ok.setStyleSheet(theme.action_button_style(primary=True))
        btn_ok.clicked.connect(dlg.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet(theme.action_button_style(primary=False))
        btn_cancel.clicked.connect(dlg.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        dlg_layout.addLayout(btn_layout)

        if dlg.exec() == QDialog.Accepted:
            layer = project.mapLayer(combo_layer.currentData())
            table_layer = project.mapLayer(combo_table.currentData())
            if layer and table_layer:
                self._add_table_row(
                    layer,
                    table_layer,
                    combo_key.currentText(),
                    combo_field.currentText(),
                )

    def _on_refresh_defaults(self):
        self.table.setRowCount(0)
        self._populate_default_mappings()
        self.log_message.emit(f"Refreshed default mappings ({self.table.rowCount()} rows)")

    def _on_remove_mapping(self):
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self.table.removeRow(rows[0].row())

    def _get_mappings(self):
        mappings = []
        for row in range(self.table.rowCount()):
            layer_item = self.table.item(row, 0)
            table_item = self.table.item(row, 1)
            key_field = self.table.item(row, 2)
            layer_field = self.table.item(row, 3)
            if all([layer_item, table_item, key_field, layer_field]):
                mappings.append({
                    'layer_id': layer_item.data(Qt.UserRole),
                    'layer_display': layer_item.text().strip(),
                    'table_id': table_item.data(Qt.UserRole),
                    'table_display': table_item.text().strip(),
                    'key_field': key_field.text().strip(),
                    'layer_field': layer_field.text().strip(),
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
