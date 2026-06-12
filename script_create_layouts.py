import os
import json
from qgis.PyQt.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QComboBox, QPushButton,
                             QFileDialog, QProgressBar, QMessageBox, QGroupBox,
                             QApplication, QCheckBox, QSpinBox, QScrollArea,
                             QDialog, QDialogButtonBox, QTreeWidget,
                             QTreeWidgetItem, QHeaderView, QListWidget,
                             QListWidgetItem, QPlainTextEdit)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QDoubleValidator
from qgis.PyQt.QtXml import QDomDocument
from qgis.core import (QgsProject, QgsPrintLayout, QgsReadWriteContext,
                       QgsLayoutItemMap, QgsLayoutItemMapGrid, QgsRectangle,
                       QgsLayoutItemLabel,
                       QgsLayoutItemLegend, QgsLayoutExporter,
                       QgsWkbTypes, QgsMapLayerType, QgsMessageLog, Qgis,
                       QgsMapLayerLegendUtils, QgsLayerTreeGroup,
                       QgsCategorizedSymbolRenderer)
from qgis.utils import iface

try:
    from .recode_workflow.widgets import LayerCheckList, FieldGroupManager
except ImportError:
    from recode_workflow.widgets import LayerCheckList, FieldGroupManager

try:
    from .recode_workflow.legend_builder import (
        preview_legend_groups, scan_field_group, scan_field_group_subdivided,
    )
except ImportError:
    from recode_workflow.legend_builder import (
        preview_legend_groups, scan_field_group, scan_field_group_subdivided,
    )

try:
    from .layer_select import layer_display_name, find_best_match
except ImportError:
    from layer_select import layer_display_name, find_best_match

LOG_TAG = 'Linear Geoscience'


class LegendTextEditorDialog(QDialog):
    """Dialog for editing legend layer names and feature/symbol labels."""

    COL_ORIGINAL = 0
    COL_DISPLAY = 1

    def __init__(self, legend_mappings=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Legend Text")
        self.setMinimumSize(600, 500)
        self.resize(700, 550)

        layout = QVBoxLayout(self)

        info = QLabel(
            "Edit the Display Text column to customise how layers and features "
            "appear in the legend. Leave unchanged to keep the original text."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #5F6368; font-size: 10px; font-style: italic;")
        layout.addWidget(info)

        # Tree widget: Original Text | Display Text
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Original Text", "Display Text"])
        self.tree.setColumnCount(2)
        header = self.tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.setAlternatingRowColors(True)
        layout.addWidget(self.tree)

        # Buttons row: Save / Load / Reset
        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save Mappings...")
        save_btn.clicked.connect(self._save_mappings)
        btn_row.addWidget(save_btn)

        load_btn = QPushButton("Load Mappings...")
        load_btn.clicked.connect(self._load_mappings)
        btn_row.addWidget(load_btn)

        reset_btn = QPushButton("Reset All")
        reset_btn.clicked.connect(self._reset_all)
        btn_row.addWidget(reset_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # OK / Cancel
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Populate tree from project layers
        self._populate_tree(legend_mappings or {})

    def _populate_tree(self, mappings):
        """Build tree from all project layers, applying saved mappings."""
        self.tree.clear()
        layers = QgsProject.instance().mapLayers().values()

        for layer in sorted(layers, key=lambda l: l.name()):
            layer_name = layer.name()
            layer_mapping = mappings.get(layer_name, {})
            display_name = layer_mapping.get('display_name', layer_name)

            # Layer node
            layer_item = QTreeWidgetItem([layer_name, display_name])
            layer_item.setFlags(layer_item.flags() | Qt.ItemIsEditable)
            layer_item.setData(0, Qt.UserRole, 'layer')
            self.tree.addTopLevelItem(layer_item)

            # Feature/symbol children (vector layers only)
            if layer.type() == QgsMapLayerType.VectorLayer and layer.renderer():
                feature_mappings = layer_mapping.get('features', {})
                try:
                    symbol_items = layer.renderer().legendSymbolItems()
                    for sym_item in symbol_items:
                        original_label = sym_item.label()
                        if not original_label:
                            continue
                        custom_label = feature_mappings.get(original_label, original_label)
                        child = QTreeWidgetItem([original_label, custom_label])
                        child.setFlags(child.flags() | Qt.ItemIsEditable)
                        child.setData(0, Qt.UserRole, 'feature')
                        layer_item.addChild(child)
                except Exception:
                    pass

            layer_item.setExpanded(True)

    def get_mappings(self):
        """Extract the current mappings dict from the tree."""
        mappings = {}
        for i in range(self.tree.topLevelItemCount()):
            layer_item = self.tree.topLevelItem(i)
            original_name = layer_item.text(self.COL_ORIGINAL)
            display_name = layer_item.text(self.COL_DISPLAY)

            features = {}
            for j in range(layer_item.childCount()):
                child = layer_item.child(j)
                orig = child.text(self.COL_ORIGINAL)
                disp = child.text(self.COL_DISPLAY)
                if disp != orig:
                    features[orig] = disp

            entry = {}
            if display_name != original_name:
                entry['display_name'] = display_name
            if features:
                entry['features'] = features

            if entry:
                mappings[original_name] = entry

        return mappings

    def _save_mappings(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Legend Mappings", "", "JSON Files (*.json)")
        if not path:
            return
        mappings = self.get_mappings()
        try:
            with open(path, 'w') as f:
                json.dump({'legend_mappings': mappings}, f, indent=2)
            QMessageBox.information(self, "Saved",
                                   f"Legend mappings saved to:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to save: {e}")

    def _load_mappings(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Legend Mappings", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            mappings = data.get('legend_mappings', {})
            self._populate_tree(mappings)
            QMessageBox.information(self, "Loaded",
                                   f"Legend mappings loaded from:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load: {e}")

    def _reset_all(self):
        """Reset all display text back to original values."""
        for i in range(self.tree.topLevelItemCount()):
            layer_item = self.tree.topLevelItem(i)
            layer_item.setText(self.COL_DISPLAY,
                               layer_item.text(self.COL_ORIGINAL))
            for j in range(layer_item.childCount()):
                child = layer_item.child(j)
                child.setText(self.COL_DISPLAY, child.text(self.COL_ORIGINAL))


class LegendFieldConfigDialog(QDialog):
    """Dialog for configuring which fields contribute to legend expansion per layer."""

    def __init__(self, legend_field_configs=None, vr_sections=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Legend Fields")
        self.setMinimumSize(650, 550)
        self.resize(750, 650)

        self._configs = dict(legend_field_configs or {})
        self._vr_sections = list(vr_sections or [])
        self._current_layer_id = None

        layout = QVBoxLayout(self)

        info = QLabel(
            "Select a layer and configure field groups. All unique values "
            "across the grouped fields will appear in the print layout legend, "
            "optionally subdivided by a parent field (e.g., Type)."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #5F6368; font-size: 10px; font-style: italic;")
        layout.addWidget(info)

        # Layer selector
        layer_row = QHBoxLayout()
        layer_row.addWidget(QLabel("Layer:"))
        self._layer_combo = QComboBox()
        self._layer_combo.currentIndexChanged.connect(self._on_layer_changed)
        layer_row.addWidget(self._layer_combo, 1)
        layout.addLayout(layer_row)

        self._renderer_label = QLabel("")
        self._renderer_label.setStyleSheet(
            "color: #5F6368; font-size: 10px; padding: 2px;")
        layout.addWidget(self._renderer_label)

        # Field group manager
        self._group_manager = FieldGroupManager()
        layout.addWidget(self._group_manager, 1)

        # Preview
        preview_row = QHBoxLayout()
        btn_preview = QPushButton("Preview")
        btn_preview.setMaximumWidth(100)
        btn_preview.clicked.connect(self._on_preview)
        preview_row.addWidget(btn_preview)
        preview_row.addStretch()
        layout.addLayout(preview_row)

        self._preview_label = QLabel("")
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet(
            "color: #333; font-size: 10px; padding: 4px; "
            "background-color: #f5f5f5; border: 1px solid #ddd; "
            "border-radius: 3px;")
        self._preview_label.setMaximumHeight(200)
        layout.addWidget(self._preview_label)

        # ── Lookup Table Sections ──
        vr_group = QGroupBox("Lookup Table Sections (Value Relations)")
        vr_layout = QVBoxLayout(vr_group)
        vr_info = QLabel(
            "Add lookup tables to include as text-only legend sections. "
            "Fields using each table are auto-detected."
        )
        vr_info.setWordWrap(True)
        vr_info.setStyleSheet("color: #5F6368; font-size: 10px; font-style: italic;")
        vr_layout.addWidget(vr_info)

        self._vr_list = QListWidget()
        self._vr_list.setMaximumHeight(100)
        vr_layout.addWidget(self._vr_list)

        vr_btn_row = QHBoxLayout()
        add_vr_btn = QPushButton("Add...")
        add_vr_btn.clicked.connect(self._add_vr_section)
        vr_btn_row.addWidget(add_vr_btn)
        remove_vr_btn = QPushButton("Remove")
        remove_vr_btn.clicked.connect(self._remove_vr_section)
        vr_btn_row.addWidget(remove_vr_btn)
        vr_btn_row.addStretch()
        vr_layout.addLayout(vr_btn_row)

        layout.addWidget(vr_group)
        self._refresh_vr_list()

        # Save/Load/Reset + OK/Cancel
        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save...")
        save_btn.clicked.connect(self._save_configs)
        btn_row.addWidget(save_btn)
        load_btn = QPushButton("Load...")
        load_btn.clicked.connect(self._load_configs)
        btn_row.addWidget(load_btn)
        load_defaults_btn = QPushButton("Load Defaults")
        load_defaults_btn.clicked.connect(self._load_defaults)
        btn_row.addWidget(load_defaults_btn)
        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self._reset)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._populate_layers()

    def _populate_layers(self):
        """Fill combo with spatial vector layers from the project."""
        self._layer_combo.blockSignals(True)
        self._layer_combo.clear()
        for layer in sorted(QgsProject.instance().mapLayers().values(),
                            key=lambda l: l.name()):
            if (layer.type() == QgsMapLayerType.VectorLayer
                    and layer.isSpatial()):
                self._layer_combo.addItem(layer_display_name(layer), layer.id())
        self._layer_combo.blockSignals(False)
        if self._layer_combo.count() > 0:
            self._on_layer_changed(0)

    def _on_layer_changed(self, index):
        """Save current config, load config for newly selected layer."""
        # Save current
        if self._current_layer_id is not None:
            groups = self._group_manager.get_field_groups()
            if any(fields for _, fields, _ in groups):
                self._configs[self._current_layer_id] = groups
            elif self._current_layer_id in self._configs:
                del self._configs[self._current_layer_id]

        layer_id = self._layer_combo.currentData()
        if not layer_id:
            self._current_layer_id = None
            return

        self._current_layer_id = layer_id
        layer = QgsProject.instance().mapLayer(layer_id)
        if not layer:
            return

        # Show renderer info
        renderer = layer.renderer()
        if renderer:
            if isinstance(renderer, QgsCategorizedSymbolRenderer):
                self._renderer_label.setText(
                    f"Renderer: categorized on '{renderer.classAttribute()}' "
                    f"({len(renderer.categories())} categories)")
            else:
                self._renderer_label.setText(
                    f"Renderer: {type(renderer).__name__}")
        else:
            self._renderer_label.setText("Renderer: none")

        # Load fields
        field_names = [f.name() for f in layer.fields()]
        self._group_manager.set_available_fields(field_names)

        # Restore cached config
        if layer_id in self._configs:
            self._group_manager.restore_groups(self._configs[layer_id])

        self._preview_label.setText("")

    def _on_preview(self):
        layer_id = self._layer_combo.currentData()
        if not layer_id:
            return
        layer = QgsProject.instance().mapLayer(layer_id)
        if not layer:
            return

        groups = self._group_manager.get_field_groups()
        non_empty = [(n, f, s) for n, f, s in groups if f]
        if not non_empty:
            self._preview_label.setText("No field groups configured.")
            return

        result = preview_legend_groups(layer, non_empty)

        lines = []
        total = 0
        for group_name, data in result.items():
            if isinstance(data, dict):
                count = sum(len(v) for v in data.values())
                total += count
                lines.append(
                    f"<b>{group_name}</b> ({count} values "
                    f"in {len(data)} sub-groups):")
                for type_val, values in data.items():
                    lines.append(
                        f"&nbsp;&nbsp;<b>{type_val}</b> ({len(values)}): "
                        f"{', '.join(values[:8])}"
                        f"{'...' if len(values) > 8 else ''}")
            else:
                total += len(data)
                lines.append(
                    f"<b>{group_name}</b> ({len(data)} values): "
                    f"{', '.join(data[:10])}"
                    f"{'...' if len(data) > 10 else ''}")
            lines.append("")

        lines.append(f"<b>Total: {total} legend entries</b>")
        self._preview_label.setText("<br>".join(lines))

    def get_configs(self):
        """Return the full config dict: {layer_id: [(name, fields, sub), ...]}."""
        # Save current layer before returning
        if self._current_layer_id is not None:
            groups = self._group_manager.get_field_groups()
            if any(fields for _, fields, _ in groups):
                self._configs[self._current_layer_id] = groups
            elif self._current_layer_id in self._configs:
                del self._configs[self._current_layer_id]
        return dict(self._configs)

    def _save_configs(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Legend Field Config", "", "JSON Files (*.json)")
        if not path:
            return
        configs = self.get_configs()
        # Convert to serializable form (layer names instead of IDs)
        serializable = {}
        for lid, groups in configs.items():
            layer = QgsProject.instance().mapLayer(lid)
            if layer:
                serializable[layer.name()] = [
                    {'name': n, 'fields': f, 'subdivide_by': s}
                    for n, f, s in groups]
        try:
            out = {'legend_field_configs': serializable}
            if self._vr_sections:
                out['value_relation_sections'] = self._vr_sections
            with open(path, 'w') as f:
                json.dump(out, f, indent=2)
            QMessageBox.information(self, "Saved",
                                   f"Legend field config saved to:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to save: {e}")

    DEFAULT_LEGEND_CONFIG_PATH = ""

    def _load_configs(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Legend Field Config", "", "JSON Files (*.json)")
        if not path:
            return
        self._load_from_path(path)

    def _load_defaults(self):
        path = self.DEFAULT_LEGEND_CONFIG_PATH
        if not path or not os.path.exists(path):
            QMessageBox.warning(
                self, "Defaults Not Found",
                "No default legend config is configured.\n"
                "Use Load to select a saved config file.")
            return
        self._load_from_path(path)

    def _load_from_path(self, path):
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            raw = data.get('legend_field_configs', {})
            # Convert layer names back to IDs
            self._configs.clear()
            for layer_name, groups_data in raw.items():
                layers = QgsProject.instance().mapLayersByName(layer_name)
                if layers:
                    self._configs[layers[0].id()] = [
                        (g['name'], g['fields'], g.get('subdivide_by'))
                        for g in groups_data]
            # Load VR sections
            self._vr_sections = data.get('value_relation_sections', [])
            self._refresh_vr_list()
            # Reload current layer view
            if self._current_layer_id:
                if self._current_layer_id in self._configs:
                    self._group_manager.restore_groups(
                        self._configs[self._current_layer_id])
                else:
                    # Current layer has no config in file — clear the widget
                    layer = QgsProject.instance().mapLayer(self._current_layer_id)
                    if layer:
                        self._group_manager.set_available_fields(
                            [f.name() for f in layer.fields()])
            QMessageBox.information(self, "Loaded",
                                   f"Legend field config loaded from:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load: {e}")

    # ── Value Relation section helpers ──

    @staticmethod
    def _detect_vr_columns(table_layer):
        """Guess key and value columns from a lookup table."""
        fields = table_layer.fields()
        key_names = ['Code', 'code', 'KEY', 'Key', 'ID', 'id']
        val_names = ['Description', 'Desciption', 'description',
                     'Name', 'name', 'Label', 'Value', 'value']
        key_col = next((k for k in key_names if fields.indexOf(k) >= 0),
                       fields[0].name() if fields.count() > 0 else '')
        val_col = next((v for v in val_names if fields.indexOf(v) >= 0),
                       fields[1].name() if fields.count() > 1 else key_col)
        return key_col, val_col

    @staticmethod
    def _find_fields_for_table(table_name):
        """Find fields across spatial layers that correspond to a lookup table.

        Uses name-pattern matching: 'TextureCodes' → fields starting with
        'Texture' (e.g. Texture, Texture2, Texture3).
        Returns list of (layer, field_name) tuples.
        """
        # Derive field name prefix from table name
        prefix = table_name
        for suffix in ('Codes', 'codes', 'Code', 'code',
                        'Categories', 'categories', 'Table', 'table'):
            if prefix.endswith(suffix) and len(prefix) > len(suffix):
                prefix = prefix[:-len(suffix)]
                break

        results = []
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.type() != QgsMapLayerType.VectorLayer or not lyr.isSpatial():
                continue
            for field in lyr.fields():
                if field.name().lower().startswith(prefix.lower()):
                    results.append((lyr, field.name()))
        return results

    def _refresh_vr_list(self):
        """Rebuild the VR sections list widget."""
        self._vr_list.clear()
        for sec in self._vr_sections:
            scan = sec.get('scan_fields', [])
            if scan:
                fields_str = ", ".join(scan[:4])
                if len(scan) > 4:
                    fields_str += "..."
                self._vr_list.addItem(
                    f"{sec['name']}  ({sec['lookup_table']} → {fields_str})")
            else:
                self._vr_list.addItem(
                    f"{sec['name']}  ({sec['lookup_table']} → auto-detect)")

    def _add_vr_section(self):
        """Show dialog to add a lookup table section."""
        # Find non-spatial tables
        tables = []
        for lyr in sorted(QgsProject.instance().mapLayers().values(),
                          key=lambda l: l.name()):
            if (lyr.type() == QgsMapLayerType.VectorLayer
                    and not lyr.isSpatial()):
                tables.append(lyr)
        if not tables:
            QMessageBox.information(self, "No Tables",
                                   "No non-spatial lookup tables found in project.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Add Lookup Table Section")
        dlg.setMinimumWidth(400)
        form = QVBoxLayout(dlg)

        form.addWidget(QLabel("Lookup Table:"))
        table_combo = QComboBox()
        for t in tables:
            table_combo.addItem(t.name(), t.id())
        form.addWidget(table_combo)

        form.addWidget(QLabel("Key Column:"))
        key_combo = QComboBox()
        form.addWidget(key_combo)

        form.addWidget(QLabel("Value/Description Column:"))
        val_combo = QComboBox()
        form.addWidget(val_combo)

        form.addWidget(QLabel("Section Name:"))
        name_edit = QLineEdit()
        form.addWidget(name_edit)

        form.addWidget(QLabel("Fields to scan (comma-separated):"))
        fields_edit = QLineEdit()
        fields_edit.setPlaceholderText(
            "e.g. SubType1, SubType2, SubType3")
        form.addWidget(fields_edit)

        info_label = QLabel("")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #5F6368; font-size: 10px;")
        form.addWidget(info_label)

        def on_table_changed():
            tid = table_combo.currentData()
            tbl = QgsProject.instance().mapLayer(tid)
            if not tbl:
                return
            key_combo.clear()
            val_combo.clear()
            for f in tbl.fields():
                key_combo.addItem(f.name())
                val_combo.addItem(f.name())
            auto_key, auto_val = self._detect_vr_columns(tbl)
            ki = key_combo.findText(auto_key)
            if ki >= 0:
                key_combo.setCurrentIndex(ki)
            vi = val_combo.findText(auto_val)
            if vi >= 0:
                val_combo.setCurrentIndex(vi)
            tname = tbl.name()
            # Auto-generate section name: strip "Codes" suffix
            sname = tname
            for suffix in ('Codes', 'codes', 'Code', 'code'):
                if sname.endswith(suffix):
                    sname = sname[:-len(suffix)]
                    break
            if not sname:
                sname = tname
            name_edit.setText(sname)
            # Auto-detect fields by name pattern
            matched = self._find_fields_for_table(tname)
            field_names = sorted(set(fn for _, fn in matched))
            fields_edit.setText(", ".join(field_names))
            if field_names:
                n_layers = len(set(l.id() for l, _ in matched))
                info_label.setText(
                    f"Auto-detected {len(matched)} field(s) across "
                    f"{n_layers} layer(s). Edit the list above if needed.")
            else:
                info_label.setText(
                    "No fields auto-detected. Enter the field names "
                    "to scan (e.g. SubType1, SubType2).")

        table_combo.currentIndexChanged.connect(lambda: on_table_changed())
        on_table_changed()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addWidget(buttons)

        if dlg.exec() == QDialog.Accepted:
            tbl = QgsProject.instance().mapLayer(table_combo.currentData())
            if tbl:
                # Parse comma-separated field names
                raw_fields = fields_edit.text()
                scan_fields = [f.strip() for f in raw_fields.split(',')
                               if f.strip()]
                self._vr_sections.append({
                    'name': name_edit.text() or tbl.name(),
                    'lookup_table': tbl.name(),
                    'key_column': key_combo.currentText(),
                    'value_column': val_combo.currentText(),
                    'scan_fields': scan_fields,
                })
                self._refresh_vr_list()

    def _remove_vr_section(self):
        """Remove the selected VR section."""
        row = self._vr_list.currentRow()
        if row >= 0 and row < len(self._vr_sections):
            del self._vr_sections[row]
            self._refresh_vr_list()

    def get_vr_sections(self):
        """Return the VR section configs."""
        return list(self._vr_sections)

    def _reset(self):
        self._configs.clear()
        self._vr_sections.clear()
        fields = []
        if self._current_layer_id:
            layer = QgsProject.instance().mapLayer(self._current_layer_id)
            if layer:
                fields = [f.name() for f in layer.fields()]
        self._group_manager.set_available_fields(fields)
        self._preview_label.setText("")
        self._refresh_vr_list()


class MapLayoutGeneratorPanel(QDockWidget):
    def __init__(self, parent=None):
        super(MapLayoutGeneratorPanel, self).__init__(parent)
        self.setWindowTitle("Map Layout Generator")
        self.setMinimumWidth(400)

        # Scroll area wrapper so the dock remains usable at smaller heights
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self.setWidget(scroll)

        self.mainWidget = QWidget()
        self.mainLayout = QVBoxLayout(self.mainWidget)
        scroll.setWidget(self.mainWidget)

        # Layer selection group
        self.createLayerSelectionGroup()

        # Project info group
        self.createProjectInfoGroup()

        # Template selection group
        self.createTemplateSelectionGroup()

        # Map settings group
        self.createMapSettingsGroup()

        # Legend settings group
        self.createLegendSettingsGroup()

        # Selective generation group
        self.createSelectiveGenerationGroup()

        # Export settings group
        self.createExportSettingsGroup()

        # Generate button and progress bar
        self.createGenerationControls()

        # Status label
        self.statusLabel = QLabel("Ready to generate map layouts")
        self.mainLayout.addWidget(self.statusLabel)

        # Spacer at the bottom
        self.mainLayout.addStretch()

        # Populate layer dropdowns
        self.populateLayerComboBox()
        self.populateLegendLayers()

    def createLayerSelectionGroup(self):
        groupBox = QGroupBox("Polygon Layer")
        layout = QVBoxLayout()

        # Layer selection
        self.layerCombo = QComboBox()
        self.refreshLayersBtn = QPushButton("Refresh")
        self.refreshLayersBtn.setMaximumWidth(100)
        self.refreshLayersBtn.clicked.connect(self.populateLayerComboBox)

        layerLayout = QHBoxLayout()
        layerLayout.addWidget(QLabel("Select Layer:"))
        layerLayout.addWidget(self.layerCombo)
        layerLayout.addWidget(self.refreshLayersBtn)

        layout.addLayout(layerLayout)
        groupBox.setLayout(layout)
        self.mainLayout.addWidget(groupBox)

    def createProjectInfoGroup(self):
        groupBox = QGroupBox("Project Information")
        layout = QVBoxLayout()

        # Project name
        projectLayout = QHBoxLayout()
        projectLayout.addWidget(QLabel("Project Name:"))
        self.projectNameEdit = QLineEdit()
        projectLayout.addWidget(self.projectNameEdit)
        layout.addLayout(projectLayout)

        # Author
        authorLayout = QHBoxLayout()
        authorLayout.addWidget(QLabel("Author:"))
        self.authorEdit = QLineEdit()
        self.authorEdit.setPlaceholderText("e.g. HW (maps to template id='author')")
        authorLayout.addWidget(self.authorEdit)
        layout.addLayout(authorLayout)

        # Drafter
        drafterLayout = QHBoxLayout()
        drafterLayout.addWidget(QLabel("Drafter:"))
        self.drafterEdit = QLineEdit()
        self.drafterEdit.setPlaceholderText("e.g. Harry West (maps to template id='drafter')")
        drafterLayout.addWidget(self.drafterEdit)
        layout.addLayout(drafterLayout)

        groupBox.setLayout(layout)
        self.mainLayout.addWidget(groupBox)

    def createTemplateSelectionGroup(self):
        groupBox = QGroupBox("Layout Templates")
        layout = QVBoxLayout()

        # Portrait template
        portraitLayout = QHBoxLayout()
        portraitLayout.addWidget(QLabel("Portrait Template:"))
        self.portraitTemplateEdit = QLineEdit()
        self.portraitTemplateEdit.setReadOnly(True)
        portraitLayout.addWidget(self.portraitTemplateEdit)
        self.portraitBrowseBtn = QPushButton("Browse...")
        self.portraitBrowseBtn.clicked.connect(self.browsePortraitTemplate)
        portraitLayout.addWidget(self.portraitBrowseBtn)

        # Landscape template
        landscapeLayout = QHBoxLayout()
        landscapeLayout.addWidget(QLabel("Landscape Template:"))
        self.landscapeTemplateEdit = QLineEdit()
        self.landscapeTemplateEdit.setReadOnly(True)
        landscapeLayout.addWidget(self.landscapeTemplateEdit)
        self.landscapeBrowseBtn = QPushButton("Browse...")
        self.landscapeBrowseBtn.clicked.connect(self.browseLandscapeTemplate)
        landscapeLayout.addWidget(self.landscapeBrowseBtn)

        layout.addLayout(portraitLayout)
        layout.addLayout(landscapeLayout)

        # Info label about template IDs
        infoLabel = QLabel(
            "Tip: Set Item IDs in your templates (Layout Designer → Item Properties → Item ID) "
            "to enable auto-population. Supported IDs: title, author, drafter, map_number"
        )
        infoLabel.setWordWrap(True)
        infoLabel.setStyleSheet("color: #5F6368; font-size: 10px; font-style: italic;")
        layout.addWidget(infoLabel)

        groupBox.setLayout(layout)
        self.mainLayout.addWidget(groupBox)

    def createMapSettingsGroup(self):
        groupBox = QGroupBox("Map Settings")
        layout = QVBoxLayout()

        # Scale settings
        scaleLayout = QHBoxLayout()
        scaleLayout.addWidget(QLabel("Map Scale:"))

        # Scale dropdown
        self.scaleCombo = QComboBox()
        self.populateScaleComboBox()
        scaleLayout.addWidget(self.scaleCombo)

        # Option to override template scale
        self.useScaleCheckbox = QCheckBox("Override template scale")
        self.useScaleCheckbox.setChecked(True)

        # Grid spacing (auto = scale / 10)
        gridLayout = QHBoxLayout()
        gridLayout.addWidget(QLabel("Grid spacing (m):"))
        self.gridIntervalEdit = QLineEdit()
        self.gridIntervalEdit.setReadOnly(True)
        self.gridIntervalEdit.setValidator(QDoubleValidator(0.0, 1e9, 4))
        gridLayout.addWidget(self.gridIntervalEdit)
        self.overrideGridCheckbox = QCheckBox("Override")
        self.overrideGridCheckbox.toggled.connect(self._on_override_grid_toggled)
        gridLayout.addWidget(self.overrideGridCheckbox)

        # Add layouts to the group
        layout.addLayout(scaleLayout)
        layout.addWidget(self.useScaleCheckbox)
        layout.addLayout(gridLayout)

        # Auto-update grid display when scale changes
        self.scaleCombo.currentIndexChanged.connect(self._refresh_grid_interval)
        self._refresh_grid_interval()

        groupBox.setLayout(layout)
        self.mainLayout.addWidget(groupBox)

    def createLegendSettingsGroup(self):
        groupBox = QGroupBox("Legend Settings")
        layout = QVBoxLayout()

        # Enable legend automation
        self.legendCheckbox = QCheckBox("Automate legend (refresh and filter layers)")
        self.legendCheckbox.setChecked(True)
        self.legendCheckbox.toggled.connect(self.toggleLegendControls)
        layout.addWidget(self.legendCheckbox)

        # Layer check list for legend inclusion
        legendLabel = QLabel("Layers to include in legend (unchecked = excluded):")
        legendLabel.setStyleSheet("color: #5F6368; font-size: 10px;")
        layout.addWidget(legendLabel)
        self.legendLayerList = LayerCheckList()
        self.legendLayerList.setMaximumHeight(200)
        layout.addWidget(self.legendLayerList)

        # Button row: Refresh + Edit Legend Text
        legendBtnLayout = QHBoxLayout()

        self.legendRefreshBtn = QPushButton("Refresh Layer List")
        self.legendRefreshBtn.setMaximumWidth(150)
        self.legendRefreshBtn.clicked.connect(self.populateLegendLayers)
        legendBtnLayout.addWidget(self.legendRefreshBtn)

        self.editLegendTextBtn = QPushButton("Edit Legend Text...")
        self.editLegendTextBtn.setMaximumWidth(150)
        self.editLegendTextBtn.clicked.connect(self.openLegendTextEditor)
        legendBtnLayout.addWidget(self.editLegendTextBtn)

        self.configLegendFieldsBtn = QPushButton("Configure Legend Fields...")
        self.configLegendFieldsBtn.setMaximumWidth(180)
        self.configLegendFieldsBtn.clicked.connect(self.openLegendFieldConfig)
        legendBtnLayout.addWidget(self.configLegendFieldsBtn)

        legendBtnLayout.addStretch()
        layout.addLayout(legendBtnLayout)

        # Storage for legend text mappings and field configs
        self.legend_text_mappings = {}
        self._legend_field_configs = {}  # {layer_id: [(name, fields, sub), ...]}
        self._vr_sections = []  # [{name, lookup_table, key_column, value_column}, ...]

        # Code Table text (added to template label with ID 'code_table')
        codeTableLabel = QLabel(
            "Code Table (auto-placed below legend in each layout):")
        codeTableLabel.setStyleSheet("color: #5F6368; font-size: 10px;")
        layout.addWidget(codeTableLabel)

        scanBtn = QPushButton("Scan Codes")
        scanBtn.setMaximumWidth(120)
        scanBtn.clicked.connect(self._scan_code_table_text)
        layout.addWidget(scanBtn)

        self.codeTableText = QPlainTextEdit()
        self.codeTableText.setMaximumHeight(100)
        self.codeTableText.setPlaceholderText(
            "Configure lookup tables via 'Configure Legend Fields...', "
            "then click 'Scan Codes' to generate text.")
        layout.addWidget(self.codeTableText)

        groupBox.setLayout(layout)
        self.mainLayout.addWidget(groupBox)

    def createSelectiveGenerationGroup(self):
        groupBox = QGroupBox("Selective Generation")
        layout = QVBoxLayout()

        # Checkbox to enable selective generation
        self.selectiveCheckbox = QCheckBox("Generate specific layouts only")
        self.selectiveCheckbox.setChecked(False)
        self.selectiveCheckbox.toggled.connect(self.toggleSelectiveControls)
        layout.addWidget(self.selectiveCheckbox)

        # Range selection
        rangeLayout = QHBoxLayout()
        rangeLayout.addWidget(QLabel("From:"))
        self.fromSpin = QSpinBox()
        self.fromSpin.setRange(1, 9999)
        self.fromSpin.setValue(1)
        self.fromSpin.setEnabled(False)
        rangeLayout.addWidget(self.fromSpin)

        rangeLayout.addWidget(QLabel("To:"))
        self.toSpin = QSpinBox()
        self.toSpin.setRange(1, 9999)
        self.toSpin.setValue(1)
        self.toSpin.setEnabled(False)
        rangeLayout.addWidget(self.toSpin)

        layout.addLayout(rangeLayout)
        groupBox.setLayout(layout)
        self.mainLayout.addWidget(groupBox)

    def createExportSettingsGroup(self):
        groupBox = QGroupBox("Export Settings")
        layout = QVBoxLayout()

        # Auto-export after generation
        self.exportCheckbox = QCheckBox("Auto-export after generation")
        self.exportCheckbox.setChecked(False)
        layout.addWidget(self.exportCheckbox)

        # Format checkboxes
        formatLayout = QHBoxLayout()
        self.exportPdfCheckbox = QCheckBox("PDF (Georeferenced)")
        self.exportPdfCheckbox.setChecked(True)
        formatLayout.addWidget(self.exportPdfCheckbox)

        self.exportTiffCheckbox = QCheckBox("GeoTIFF")
        self.exportTiffCheckbox.setChecked(False)
        formatLayout.addWidget(self.exportTiffCheckbox)

        self.exportPngCheckbox = QCheckBox("PNG")
        self.exportPngCheckbox.setChecked(False)
        formatLayout.addWidget(self.exportPngCheckbox)

        layout.addLayout(formatLayout)

        # DPI setting
        dpiLayout = QHBoxLayout()
        dpiLayout.addWidget(QLabel("DPI:"))
        self.dpiSpin = QSpinBox()
        self.dpiSpin.setRange(72, 600)
        self.dpiSpin.setValue(300)
        dpiLayout.addWidget(self.dpiSpin)
        dpiLayout.addStretch()
        layout.addLayout(dpiLayout)

        # Output directory
        dirLayout = QHBoxLayout()
        dirLayout.addWidget(QLabel("Output Directory:"))
        self.outputDirEdit = QLineEdit()
        self.outputDirEdit.setReadOnly(True)
        dirLayout.addWidget(self.outputDirEdit)
        self.outputDirBrowseBtn = QPushButton("Browse...")
        self.outputDirBrowseBtn.clicked.connect(self.browseOutputDir)
        dirLayout.addWidget(self.outputDirBrowseBtn)
        layout.addLayout(dirLayout)

        groupBox.setLayout(layout)
        self.mainLayout.addWidget(groupBox)

    def createGenerationControls(self):
        # Generate button
        self.generateBtn = QPushButton("Generate Map Layouts")
        self.generateBtn.setStyleSheet("font-weight: bold; background-color: #4CAF50; color: white;")
        self.generateBtn.setMinimumHeight(40)
        self.generateBtn.clicked.connect(self.generateLayouts)
        self.mainLayout.addWidget(self.generateBtn)

        # Export existing layouts button
        self.exportExistingBtn = QPushButton("Export Existing Layouts")
        self.exportExistingBtn.setStyleSheet("font-weight: bold; background-color: #2196F3; color: white;")
        self.exportExistingBtn.setMinimumHeight(40)
        self.exportExistingBtn.clicked.connect(self.exportExistingLayouts)
        self.mainLayout.addWidget(self.exportExistingBtn)

        # Progress bar
        self.progressBar = QProgressBar()
        self.progressBar.setTextVisible(True)
        self.progressBar.setAlignment(Qt.AlignCenter)
        self.progressBar.setValue(0)
        self.mainLayout.addWidget(self.progressBar)

    # ── Populate helpers ──────────────────────────────────────────────

    def populateLayerComboBox(self):
        self.layerCombo.clear()

        layers = QgsProject.instance().mapLayers().values()

        polygon_layers = []
        for layer in layers:
            if layer.type() == QgsMapLayerType.VectorLayer:
                if layer.geometryType() == QgsWkbTypes.PolygonGeometry:
                    polygon_layers.append(layer)

        for layer in polygon_layers:
            self.layerCombo.addItem(layer_display_name(layer), layer.id())

        index, score = find_best_match(
            "mapsheets", [l.name() for l in polygon_layers])
        if index is not None and score >= 80:
            self.layerCombo.setCurrentIndex(index)

        if self.layerCombo.count() == 0:
            self.statusLabel.setText("No polygon layers found.")
            self.generateBtn.setEnabled(False)
        else:
            self.statusLabel.setText("Ready to generate map layouts")
            self.generateBtn.setEnabled(True)

    def populateScaleComboBox(self):
        standard_scales = [
            "1:50", "1:100", "1:200", "1:250", "1:500",
            "1:1,000", "1:2,000", "1:2,500", "1:5,000",
            "1:10,000", "1:20,000", "1:25,000", "1:50,000", "1:100,000"
        ]
        self.scaleCombo.clear()
        for scale in standard_scales:
            self.scaleCombo.addItem(scale)

    def populateLegendLayers(self):
        """Refresh the legend layer check list with all project layers."""
        all_layers = list(QgsProject.instance().mapLayers().values())
        self.legendLayerList.set_layers(all_layers)

    # ── Toggle helpers ────────────────────────────────────────────────

    def toggleSelectiveControls(self, checked):
        self.fromSpin.setEnabled(checked)
        self.toSpin.setEnabled(checked)

    def toggleLegendControls(self, checked):
        self.legendLayerList.setEnabled(checked)
        self.legendRefreshBtn.setEnabled(checked)
        self.editLegendTextBtn.setEnabled(checked)
        self.configLegendFieldsBtn.setEnabled(checked)
        self.codeTableText.setEnabled(checked)

    def openLegendTextEditor(self):
        """Open the legend text editor dialog."""
        dlg = LegendTextEditorDialog(self.legend_text_mappings, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.legend_text_mappings = dlg.get_mappings()
            count = len(self.legend_text_mappings)
            if count:
                QgsMessageLog.logMessage(
                    f"Legend text mappings updated for {count} layer(s).",
                    LOG_TAG, Qgis.Info)
            else:
                QgsMessageLog.logMessage(
                    "Legend text mappings cleared (all set to original).",
                    LOG_TAG, Qgis.Info)

    def openLegendFieldConfig(self):
        """Open the legend field configuration dialog."""
        dlg = LegendFieldConfigDialog(
            self._legend_field_configs,
            vr_sections=self._vr_sections,
            parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._legend_field_configs = dlg.get_configs()
            self._vr_sections = dlg.get_vr_sections()
            count = len(self._legend_field_configs)
            vr_count = len(self._vr_sections)
            parts = []
            if count:
                parts.append(f"{count} layer(s)")
            if vr_count:
                parts.append(f"{vr_count} lookup table(s)")
            if parts:
                QgsMessageLog.logMessage(
                    f"Legend field configs set for {', '.join(parts)}.",
                    LOG_TAG, Qgis.Info)
            else:
                QgsMessageLog.logMessage(
                    "Legend field configs cleared.", LOG_TAG, Qgis.Info)

            # Auto-scan code table text if lookup tables are configured
            if self._vr_sections:
                self._scan_code_table_text()

    # ── Browse helpers ────────────────────────────────────────────────

    def browsePortraitTemplate(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Portrait Layout Template",
                                                   "", "QGIS Templates (*.qpt)")
        if file_path:
            self.portraitTemplateEdit.setText(file_path)

    def browseLandscapeTemplate(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Landscape Layout Template",
                                                   "", "QGIS Templates (*.qpt)")
        if file_path:
            self.landscapeTemplateEdit.setText(file_path)

    def browseOutputDir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.outputDirEdit.setText(dir_path)

    # ── Scale helpers ─────────────────────────────────────────────────

    def getSelectedScale(self):
        """Extract the scale denominator from the selected scale text."""
        scale_text = self.scaleCombo.currentText()
        if scale_text:
            scale_value = scale_text.replace(",", "").split(":")[1]
            return int(scale_value)
        return None

    # ── Grid spacing helpers ──────────────────────────────────────────

    def _refresh_grid_interval(self):
        """Update the auto-grid display from the current scale, unless overridden."""
        if self.overrideGridCheckbox.isChecked():
            return
        scale = self.getSelectedScale()
        if scale:
            self.gridIntervalEdit.setText(self._format_interval(scale / 10.0))
        else:
            self.gridIntervalEdit.clear()

    def _on_override_grid_toggled(self, checked):
        self.gridIntervalEdit.setReadOnly(not checked)
        if not checked:
            self._refresh_grid_interval()

    @staticmethod
    def _format_interval(value):
        if value == int(value):
            return str(int(value))
        return f"{value:g}"

    def getGridInterval(self):
        """Return the grid interval in map units, or None if unavailable."""
        if self.overrideGridCheckbox.isChecked():
            try:
                v = float(self.gridIntervalEdit.text().strip())
                return v if v > 0 else None
            except ValueError:
                return None
        scale = self.getSelectedScale()
        return (scale / 10.0) if scale else None

    # ── Validation ────────────────────────────────────────────────────

    def validateInputs(self):
        if self.layerCombo.count() == 0:
            QMessageBox.warning(self, "Error", "No polygon layer selected.")
            return False

        layer_id = self.layerCombo.currentData()
        layer = QgsProject.instance().mapLayer(layer_id)
        if not layer:
            QMessageBox.warning(self, "Error", "Selected layer no longer exists. Try refreshing.")
            return False

        fields = layer.fields()
        field_names = [field.name() for field in fields]

        if 'orientation' not in field_names:
            QMessageBox.warning(self, "Error", "The selected layer does not have an 'orientation' field.")
            return False

        if 'name' not in field_names:
            QMessageBox.warning(self, "Error", "The selected layer does not have a 'name' field.")
            return False

        if not self.projectNameEdit.text().strip():
            QMessageBox.warning(self, "Error", "Project name is required.")
            return False

        portrait_path = self.portraitTemplateEdit.text()
        if not portrait_path or not os.path.isfile(portrait_path):
            QMessageBox.warning(self, "Error", "Portrait layout template file not selected.")
            return False

        landscape_path = self.landscapeTemplateEdit.text()
        if not landscape_path or not os.path.isfile(landscape_path):
            QMessageBox.warning(self, "Error", "Landscape layout template file not selected.")
            return False

        if self.overrideGridCheckbox.isChecked():
            try:
                v = float(self.gridIntervalEdit.text().strip())
                if v <= 0:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(self, "Error",
                                    "Grid spacing override is enabled but the value "
                                    "is empty or invalid. Enter a positive number.")
                return False

        # Validate export settings if export is enabled
        if self.exportCheckbox.isChecked():
            if not any([self.exportPdfCheckbox.isChecked(),
                       self.exportTiffCheckbox.isChecked(),
                       self.exportPngCheckbox.isChecked()]):
                QMessageBox.warning(self, "Error", "Export is enabled but no format is selected.")
                return False
            out_dir = self.outputDirEdit.text()
            if not out_dir or not os.path.isdir(out_dir):
                QMessageBox.warning(self, "Error", "Please select a valid output directory for export.")
                return False

        return True

    # ── Label auto-population ─────────────────────────────────────────

    def _populate_labels(self, layout, feature_number, total_count):
        """Find labels by Item ID and set their text."""
        author = self.authorEdit.text().strip()
        drafter = self.drafterEdit.text().strip()

        label_map = {
            'title': layout.name(),
            'map_number': f"Map#: {feature_number} of {total_count}",
        }
        if author:
            label_map['author'] = f"Author: {author}"
        if drafter:
            label_map['drafter'] = f"Drafted: {drafter}"

        found_ids = set()
        for item in layout.items():
            if isinstance(item, QgsLayoutItemLabel):
                item_id = item.id()
                if item_id and item_id in label_map:
                    item.setText(label_map[item_id])
                    found_ids.add(item_id)
                    QgsMessageLog.logMessage(
                        f"Label '{item_id}' set to: {label_map[item_id]}",
                        LOG_TAG, Qgis.Info)

        # Log any expected IDs that weren't found in the template
        missing = set(label_map.keys()) - found_ids
        if missing:
            QgsMessageLog.logMessage(
                f"Template label IDs not found: {', '.join(sorted(missing))}. "
                f"Set Item IDs in Layout Designer to enable auto-population.",
                LOG_TAG, Qgis.Warning)

    def _create_code_table_label(self, layout, plain_text):
        """Create a code table label and position it below the legend.

        Uses ModeFont (native vector rendering) for text quality matching
        the legend.  The plain text from the editable text area is used
        directly — what you see in the panel is what appears in the layout.
        """
        from qgis.core import QgsLayoutPoint, QgsLayoutSize, QgsUnitTypes
        from qgis.PyQt.QtGui import QFont

        label = QgsLayoutItemLabel(layout)
        label.setMode(QgsLayoutItemLabel.ModeFont)
        label.setText(plain_text)
        label.setId('code_table')
        label.setFont(QFont("MS Shell Dlg 2", 8))

        # Position below the finalized legend
        legends = [i for i in layout.items()
                   if isinstance(i, QgsLayoutItemLegend)]
        if legends:
            legend = legends[0]
            pos = legend.positionWithUnits()
            size = legend.sizeWithUnits()
            x = pos.x()
            y = pos.y() + size.height() + 3
            width = max(size.width(), 80)
        else:
            x, y, width = 10, 250, 120

        label.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
        label.attemptResize(QgsLayoutSize(
            width, 50, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(label)
        QgsMessageLog.logMessage(
            "Code table label created below legend.", LOG_TAG, Qgis.Info)

    # ── Legend automation ─────────────────────────────────────────────

    def _configure_legend(self, layout, excluded_layer_ids, text_mappings=None):
        """Refresh legend, freeze it, remove excluded layers, and apply text overrides."""
        legends = [item for item in layout.items()
                   if isinstance(item, QgsLayoutItemLegend)]
        if not legends:
            QgsMessageLog.logMessage(
                "No legend item found in template - skipping legend automation.",
                LOG_TAG, Qgis.Warning)
            return

        legend = legends[0]

        # Force a clean resync: disconnect first so the reconnect is never
        # a no-op (templates with auto-update already True would skip it).
        legend.setAutoUpdateModel(False)
        legend.setAutoUpdateModel(True)
        legend.setAutoUpdateModel(False)

        # Remove excluded layers from the frozen legend
        root = legend.model().rootGroup()

        removed_count = 0
        for layer_id in excluded_layer_ids:
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer:
                node = root.findLayer(layer)
                if node:
                    root.removeChildNode(node)
                    removed_count += 1

        if removed_count:
            QgsMessageLog.logMessage(
                f"Removed {removed_count} layer(s) from legend.",
                LOG_TAG, Qgis.Info)

        # Apply legend text overrides
        if text_mappings:
            self._apply_legend_text(legend, text_mappings)

    def _apply_legend_text(self, legend, text_mappings):
        """Apply custom display names to legend layer titles and feature labels."""
        root = legend.model().rootGroup()
        renamed_count = 0

        for layer in QgsProject.instance().mapLayers().values():
            layer_name = layer.name()
            mapping = text_mappings.get(layer_name)
            if not mapping:
                continue

            layer_node = root.findLayer(layer)
            if not layer_node:
                continue

            # Rename the layer title in the legend
            display_name = mapping.get('display_name')
            if display_name:
                layer_node.setCustomProperty("legend/title-label", display_name)
                renamed_count += 1

            # Rename individual feature/symbol labels
            feature_mappings = mapping.get('features', {})
            if feature_mappings and layer.type() == QgsMapLayerType.VectorLayer:
                try:
                    symbol_items = layer.renderer().legendSymbolItems()
                    for idx, sym_item in enumerate(symbol_items):
                        original_label = sym_item.label()
                        if original_label in feature_mappings:
                            QgsMapLayerLegendUtils.setLegendNodeUserLabel(
                                layer_node, idx, feature_mappings[original_label])
                            renamed_count += 1
                    # Refresh this layer's legend nodes
                    legend.model().refreshLayerLegend(layer_node)
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f"Error applying legend text for '{layer_name}': {e}",
                        LOG_TAG, Qgis.Warning)

        if renamed_count:
            legend.updateLegend()
            QgsMessageLog.logMessage(
                f"Applied {renamed_count} legend text override(s).",
                LOG_TAG, Qgis.Info)

    def _expand_legend_fields(self, layout, legend_field_configs):
        """Expand configured layers into grouped legend entries.

        Replaces each configured layer's single legend node with multiple
        clones, each filtered by setLegendNodeOrder to show only its
        group's entries.  Uses QgsLayerTreeGroup for sub-divided headings.
        """
        legends = [i for i in layout.items()
                   if isinstance(i, QgsLayoutItemLegend)]
        if not legends:
            return
        legend = legends[0]
        root = legend.model().rootGroup()

        for layer_id, groups in legend_field_configs.items():
            layer = QgsProject.instance().mapLayer(layer_id)
            if not layer or not layer.renderer():
                continue
            layer_node = root.findLayer(layer)
            if not layer_node:
                continue

            # Build value → index map from the renderer's legend items.
            # For categorized renderers, map BOTH the category value (raw data)
            # AND the display label, since scan_field_group returns raw values
            # but legendSymbolItems may return display labels.
            renderer = layer.renderer()
            symbol_items = renderer.legendSymbolItems()
            value_to_idx = {}

            if isinstance(renderer, QgsCategorizedSymbolRenderer):
                for idx, cat in enumerate(renderer.categories()):
                    val = cat.value()
                    if val is not None and str(val).strip():
                        value_to_idx[str(val)] = idx
                    label = cat.label()
                    if label and label not in value_to_idx:
                        value_to_idx[label] = idx
            else:
                for idx, item in enumerate(symbol_items):
                    if item.label():
                        value_to_idx[item.label()] = idx

            QgsMessageLog.logMessage(
                f"Legend expansion '{layer.name()}': "
                f"{len(symbol_items)} legend items, "
                f"{len(value_to_idx)} mappable values, "
                f"{len(groups)} group(s).",
                LOG_TAG, Qgis.Info)

            # Clone before removing — removeChildNode deletes the C++ object
            layer_node_template = layer_node.clone()

            # Get position in parent for reinsertion
            parent = layer_node.parent()
            siblings = parent.children()
            position = siblings.index(layer_node) if layer_node in siblings else len(siblings)

            # Remove original node (clones replace it)
            parent.removeChildNode(layer_node)

            used_indices = set()

            for group_name, field_names, subdivide_by in groups:
                if not field_names:
                    continue

                if subdivide_by:
                    # Subdivided: group heading + sub-group clones
                    subdivided = scan_field_group_subdivided(
                        layer, field_names, subdivide_by)
                    if not subdivided:
                        continue
                    group_tree = QgsLayerTreeGroup(group_name)

                    for type_val, subtype_values in subdivided.items():
                        indices = [value_to_idx[v] for v in subtype_values
                                   if v in value_to_idx]
                        missed = [v for v in subtype_values
                                  if v not in value_to_idx]
                        if missed:
                            QgsMessageLog.logMessage(
                                f"  '{type_val}': {len(missed)} value(s) "
                                f"not in renderer: {missed[:5]}",
                                LOG_TAG, Qgis.Warning)
                        if not indices:
                            continue
                        used_indices.update(indices)

                        clone = layer_node_template.clone()
                        clone.setCustomProperty("legend/title-label", type_val)
                        QgsMapLayerLegendUtils.setLegendNodeOrder(
                            clone, indices)
                        group_tree.addChildNode(clone)

                    if group_tree.children():
                        parent.insertChildNode(position, group_tree)
                        position += 1
                else:
                    # Flat: single clone with filtered indices
                    unique_values = scan_field_group(layer, field_names)
                    indices = [value_to_idx[v] for v in unique_values
                               if v in value_to_idx]
                    missed = [v for v in unique_values
                              if v not in value_to_idx]
                    if missed:
                        QgsMessageLog.logMessage(
                            f"  '{group_name}': {len(missed)} value(s) "
                            f"not in renderer: {missed[:5]}",
                            LOG_TAG, Qgis.Warning)
                    if not indices:
                        continue
                    used_indices.update(indices)

                    clone = layer_node_template.clone()
                    clone.setCustomProperty("legend/title-label", group_name)
                    QgsMapLayerLegendUtils.setLegendNodeOrder(
                        clone, indices)
                    parent.insertChildNode(position, clone)
                    position += 1

            QgsMessageLog.logMessage(
                f"  '{layer.name()}': {len(used_indices)} of "
                f"{len(symbol_items)} entries assigned to groups.",
                LOG_TAG, Qgis.Info)

        legend.updateLegend()
        legend.adjustBoxSize()

    def _scan_code_table_text(self):
        """Scan configured lookup tables and generate formatted code table text."""
        if not self._vr_sections:
            QMessageBox.information(self, "No Tables",
                "Configure lookup tables first via 'Configure Legend Fields...'")
            return

        lines = []
        for section in self._vr_sections:
            lookup_name = section['lookup_table']
            key_col = section['key_column']
            val_col = section['value_column']
            section_name = section['name']

            # Use explicit field names if configured, else auto-detect
            explicit_fields = section.get('scan_fields', [])
            used_codes = set()
            if explicit_fields:
                for lyr in QgsProject.instance().mapLayers().values():
                    if (lyr.type() != QgsMapLayerType.VectorLayer
                            or not lyr.isSpatial()):
                        continue
                    for fname in explicit_fields:
                        idx = lyr.fields().indexOf(fname)
                        if idx >= 0:
                            for val in lyr.uniqueValues(idx):
                                if (val is not None
                                        and str(val).strip()
                                        and str(val) != 'NULL'):
                                    used_codes.add(str(val))
            else:
                scan_fields = LegendFieldConfigDialog._find_fields_for_table(
                    lookup_name)
                for lyr, fname in scan_fields:
                    idx = lyr.fields().indexOf(fname)
                    if idx >= 0:
                        for val in lyr.uniqueValues(idx):
                            if val is not None and str(val).strip():
                                used_codes.add(str(val))

            lookup_layers = QgsProject.instance().mapLayersByName(lookup_name)
            if not lookup_layers:
                continue
            lookup = lookup_layers[0]
            entries = []
            for feat in lookup.getFeatures():
                code = str(feat[key_col]) if feat[key_col] else ""
                desc = str(feat[val_col]) if feat[val_col] else ""
                if code in used_codes:
                    entry = (f"{code} — {desc}"
                             if desc and desc != code else code)
                    entries.append(entry)

            if entries:
                lines.append(section_name.upper())
                lines.append(", ".join(sorted(entries)))
                lines.append("")

        self.codeTableText.setPlainText("\n".join(lines))
        QgsMessageLog.logMessage(
            f"Code table scanned: {len(self._vr_sections)} section(s).",
            LOG_TAG, Qgis.Info)

    # ── Export existing layouts ─────────────────────────────────────

    def _validate_export_settings(self):
        """Validate export settings are configured. Returns True if valid."""
        if not (self.exportPdfCheckbox.isChecked() or
                self.exportTiffCheckbox.isChecked() or
                self.exportPngCheckbox.isChecked()):
            QMessageBox.warning(self, "Export Settings",
                                "Please select at least one export format.")
            return False
        out_dir = self.outputDirEdit.text()
        if not out_dir or not os.path.isdir(out_dir):
            QMessageBox.warning(self, "Export Settings",
                                "Please select a valid output directory.")
            return False
        return True

    def exportExistingLayouts(self):
        """Open a layout picker and export selected layouts."""
        if not self._validate_export_settings():
            return

        # Get all layouts from the project
        manager = QgsProject.instance().layoutManager()
        layouts = manager.printLayouts()
        if not layouts:
            QMessageBox.information(self, "Export Layouts",
                                    "No layouts found in the current project.")
            return

        # Build picker dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Select Layouts to Export")
        dlg.setMinimumWidth(400)
        dlg.resize(450, 350)
        dlg_layout = QVBoxLayout(dlg)

        dlg_layout.addWidget(QLabel("Select which layouts to export:"))

        list_widget = QListWidget()
        for lay in sorted(layouts, key=lambda l: l.name()):
            item = QListWidgetItem(lay.name())
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            list_widget.addItem(item)
        dlg_layout.addWidget(list_widget)

        # Select All / Deselect All
        sel_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        deselect_all_btn = QPushButton("Deselect All")
        select_all_btn.clicked.connect(
            lambda: [list_widget.item(i).setCheckState(Qt.Checked)
                     for i in range(list_widget.count())])
        deselect_all_btn.clicked.connect(
            lambda: [list_widget.item(i).setCheckState(Qt.Unchecked)
                     for i in range(list_widget.count())])
        sel_row.addWidget(select_all_btn)
        sel_row.addWidget(deselect_all_btn)
        sel_row.addStretch()
        dlg_layout.addLayout(sel_row)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dlg.accept)
        button_box.rejected.connect(dlg.reject)
        dlg_layout.addWidget(button_box)

        if dlg.exec() != QDialog.Accepted:
            return

        # Collect selected layout names
        selected = []
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.text())

        if not selected:
            QMessageBox.information(self, "Export Layouts",
                                    "No layouts were selected.")
            return

        # Run export
        self.setEnabled(False)
        try:
            success, fail = self._export_layouts(selected)
            lines = [f"Exported: {success} layout(s)"]
            if fail:
                lines.append(f"Failed: {fail} layout(s)")
            lines.append(f"Output: {self.outputDirEdit.text()}")
            QMessageBox.information(self, "Export Complete", "\n".join(lines))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Export error: {e}")
        finally:
            self.setEnabled(True)
            self.statusLabel.setText("Ready to generate map layouts")
            self.progressBar.setValue(0)

    # ── Batch export ──────────────────────────────────────────────────

    def _export_layouts(self, layout_names):
        """Export layouts to selected formats."""
        out_dir = self.outputDirEdit.text()
        dpi = self.dpiSpin.value()
        do_pdf = self.exportPdfCheckbox.isChecked()
        do_tiff = self.exportTiffCheckbox.isChecked()
        do_png = self.exportPngCheckbox.isChecked()

        self.statusLabel.setText("Exporting layouts...")
        self.progressBar.setMaximum(len(layout_names))
        self.progressBar.setValue(0)

        export_success = 0
        export_fail = 0

        for idx, name in enumerate(layout_names):
            self.progressBar.setValue(idx + 1)
            QApplication.processEvents()

            layout = QgsProject.instance().layoutManager().layoutByName(name)
            if not layout:
                QgsMessageLog.logMessage(
                    f"Layout '{name}' not found for export.", LOG_TAG, Qgis.Warning)
                export_fail += 1
                continue

            exporter = QgsLayoutExporter(layout)
            safe_name = (name.replace('\n', '_').replace(' ', '_')
                         .replace('/', '-').replace('\\', '-'))

            try:
                if do_pdf:
                    pdf_settings = QgsLayoutExporter.PdfExportSettings()
                    pdf_settings.dpi = dpi
                    try:
                        pdf_settings.writeGeoPdf = True
                    except AttributeError:
                        pass
                    result = exporter.exportToPdf(
                        os.path.join(out_dir, f"{safe_name}.pdf"), pdf_settings)
                    if result != QgsLayoutExporter.Success:
                        QgsMessageLog.logMessage(
                            f"PDF export failed for '{name}': error code {result}",
                            LOG_TAG, Qgis.Warning)

                if do_tiff:
                    tiff_settings = QgsLayoutExporter.ImageExportSettings()
                    tiff_settings.dpi = dpi
                    tiff_settings.generateWorldFile = True
                    result = exporter.exportToImage(
                        os.path.join(out_dir, f"{safe_name}.tif"), tiff_settings)
                    if result != QgsLayoutExporter.Success:
                        QgsMessageLog.logMessage(
                            f"GeoTIFF export failed for '{name}': error code {result}",
                            LOG_TAG, Qgis.Warning)

                if do_png:
                    png_settings = QgsLayoutExporter.ImageExportSettings()
                    png_settings.dpi = dpi
                    result = exporter.exportToImage(
                        os.path.join(out_dir, f"{safe_name}.png"), png_settings)
                    if result != QgsLayoutExporter.Success:
                        QgsMessageLog.logMessage(
                            f"PNG export failed for '{name}': error code {result}",
                            LOG_TAG, Qgis.Warning)

                export_success += 1
                self.statusLabel.setText(f"Exported: {name}")

            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Export error for '{name}': {e}", LOG_TAG, Qgis.Warning)
                export_fail += 1

        return export_success, export_fail

    # ── Main generation ───────────────────────────────────────────────

    def generateLayouts(self):
        if not self.validateInputs():
            return

        self.setEnabled(False)
        self.statusLabel.setText("Generating map layouts...")

        try:
            layer_id = self.layerCombo.currentData()
            polygon_layer = QgsProject.instance().mapLayer(layer_id)

            project_name = self.projectNameEdit.text().strip()

            portrait_template_path = self.portraitTemplateEdit.text()
            landscape_template_path = self.landscapeTemplateEdit.text()

            use_custom_scale = self.useScaleCheckbox.isChecked()
            scale_denominator = None
            if use_custom_scale:
                scale_denominator = self.getSelectedScale()

            buffer_percentage = 0

            feature_count = polygon_layer.featureCount()
            created_count = 0
            skipped_count = 0
            created_layout_names = []

            # Compute legend exclusion list
            legend_enabled = self.legendCheckbox.isChecked()
            excluded_layer_ids = []
            if legend_enabled:
                included_ids = set(self.legendLayerList.checked_layer_ids())
                all_ids = set(QgsProject.instance().mapLayers().keys())
                excluded_layer_ids = list(all_ids - included_ids)

            # Selective generation range
            selective_enabled = self.selectiveCheckbox.isChecked()
            from_number = self.fromSpin.value()
            to_number = self.toSpin.value()

            self.fromSpin.setMaximum(feature_count)
            self.toSpin.setMaximum(feature_count)

            if selective_enabled:
                if from_number > to_number:
                    QMessageBox.warning(self, "Invalid Range",
                                      f"'From' value ({from_number}) cannot be greater than 'To' value ({to_number}).")
                    return

                if from_number < 1:
                    QMessageBox.warning(self, "Invalid Range",
                                      "'From' value must be at least 1.")
                    return

                if to_number > feature_count:
                    QMessageBox.warning(self, "Invalid Range",
                                      f"'To' value ({to_number}) exceeds the total number of features ({feature_count}).\n\n"
                                      f"Please enter a value between {from_number} and {feature_count}.")
                    return

                self.progressBar.setMaximum(to_number - from_number + 1)
                self.statusLabel.setText(f"Generating layouts {from_number} to {to_number}...")
            else:
                self.progressBar.setMaximum(feature_count)

            self.progressBar.setValue(0)

            # Process features
            progress_counter = 0
            for i, feature in enumerate(polygon_layer.getFeatures()):
                feature_number = i + 1

                if selective_enabled:
                    if feature_number < from_number or feature_number > to_number:
                        continue

                progress_counter += 1
                self.progressBar.setValue(progress_counter)
                QApplication.processEvents()

                try:
                    orientation = feature['orientation']
                    polygon_name = feature['name']
                    layout_name = f"{project_name}\n{polygon_name}"

                    # Remove existing layout if it exists
                    existing = QgsProject.instance().layoutManager().layoutByName(layout_name)
                    if existing:
                        QgsProject.instance().layoutManager().removeLayout(existing)
                        self.statusLabel.setText(f"Replacing existing layout: {layout_name}")

                    if orientation not in ['Portrait', 'Landscape']:
                        self.statusLabel.setText(
                            f"Warning: Feature {polygon_name} has invalid orientation. Using Portrait.")
                        orientation = 'Portrait'

                    geom = feature.geometry()
                    if geom.isEmpty():
                        self.statusLabel.setText(f"Warning: Feature {polygon_name} has empty geometry. Skipping.")
                        skipped_count += 1
                        continue

                    bbox = geom.boundingBox()

                    # Calculate buffer
                    width = bbox.width()
                    height = bbox.height()
                    buffer_x = width * (buffer_percentage / 100)
                    buffer_y = height * (buffer_percentage / 100)
                    bbox_buffered = QgsRectangle(
                        bbox.xMinimum() - buffer_x,
                        bbox.yMinimum() - buffer_y,
                        bbox.xMaximum() + buffer_x,
                        bbox.yMaximum() + buffer_y
                    )

                    # Choose template based on orientation
                    is_landscape = (orientation == 'Landscape')
                    template_path = landscape_template_path if is_landscape else portrait_template_path

                    # Load the template
                    layout = QgsPrintLayout(QgsProject.instance())
                    with open(template_path, 'r') as template_file:
                        template_content = template_file.read()

                    doc = QDomDocument()
                    doc.setContent(template_content)

                    layout.loadFromTemplate(doc, QgsReadWriteContext())
                    layout.setName(layout_name)

                    # Get main map from template
                    maps = [item for item in layout.items() if isinstance(item, QgsLayoutItemMap)]
                    if not maps:
                        self.statusLabel.setText(f"No map found in template for {layout_name}. Skipping.")
                        skipped_count += 1
                        continue

                    main_map = maps[0]

                    # Set map extent / scale
                    if use_custom_scale and scale_denominator:
                        center_x = (bbox.xMinimum() + bbox.xMaximum()) / 2
                        center_y = (bbox.yMinimum() + bbox.yMaximum()) / 2

                        map_width_mm = main_map.rect().width()
                        map_height_mm = main_map.rect().height()

                        map_width_mapunits = (map_width_mm * scale_denominator) / 1000
                        map_height_mapunits = (map_height_mm * scale_denominator) / 1000

                        new_extent = QgsRectangle(
                            center_x - map_width_mapunits / 2,
                            center_y - map_height_mapunits / 2,
                            center_x + map_width_mapunits / 2,
                            center_y + map_height_mapunits / 2
                        )

                        main_map.setExtent(new_extent)
                        main_map.setScale(scale_denominator)
                    else:
                        main_map.setExtent(bbox_buffered)

                    # Auto-set grid X/Y interval based on selected scale (or override)
                    grid_interval = self.getGridInterval()
                    if grid_interval is not None:
                        grids = main_map.grids()
                        if grids.size() > 0:
                            grid = grids.grid(0)
                            grid.setIntervalX(grid_interval)
                            grid.setIntervalY(grid_interval)
                            grid.setUnits(QgsLayoutItemMapGrid.MapUnit)
                        else:
                            QgsMessageLog.logMessage(
                                f"Template for '{layout_name}' has no map grid; "
                                f"skipping grid spacing.", LOG_TAG, Qgis.Warning)

                    # Auto-populate labels by Item ID
                    self._populate_labels(layout, feature_number, feature_count)

                    # Automate legend
                    if legend_enabled:
                        self._configure_legend(layout, excluded_layer_ids,
                                               self.legend_text_mappings)

                        # Expand configured layers into grouped legend entries
                        if self._legend_field_configs:
                            self._expand_legend_fields(
                                layout, self._legend_field_configs)

                    # Add code table below the finalized legend
                    code_text = self.codeTableText.toPlainText().strip()
                    if code_text:
                        self._create_code_table_label(layout, code_text)

                    # Add layout to project
                    QgsProject.instance().layoutManager().addLayout(layout)
                    created_count += 1
                    created_layout_names.append(layout_name)
                    self.statusLabel.setText(f"Created map layout: {layout_name}")

                except Exception as e:
                    QgsMessageLog.logMessage(
                        f"Error processing feature {i}: {e}", LOG_TAG, Qgis.Warning)
                    self.statusLabel.setText(f"Error processing feature {i}: {str(e)}")
                    skipped_count += 1

            # Batch export (if auto-export is enabled)
            export_success, export_fail = 0, 0
            if self.exportCheckbox.isChecked():
                export_success, export_fail = self._export_layouts(created_layout_names)

            # Summary message
            summary_lines = ["Process complete."]
            if selective_enabled:
                summary_lines.append(f"Range: {from_number} to {to_number}")
            summary_lines.append(f"Created: {created_count} map layouts")
            if skipped_count:
                summary_lines.append(f"Skipped: {skipped_count} layouts")
            if self.exportCheckbox.isChecked():
                summary_lines.append(f"\nExported: {export_success} layouts")
                if export_fail:
                    summary_lines.append(f"Export failures: {export_fail}")
                summary_lines.append(f"Output: {self.outputDirEdit.text()}")

            QMessageBox.information(self, "Map Layout Generator", "\n".join(summary_lines))

        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")

        finally:
            self.setEnabled(True)
            self.statusLabel.setText("Ready to generate map layouts")
            self.progressBar.setValue(0)


# Create and show the panel
def create_map_layout_generator_panel():
    panel = MapLayoutGeneratorPanel()
    iface.addDockWidget(Qt.RightDockWidgetArea, panel)
    return panel


def run(iface):
    """Entry point called from mainplugin.py."""
    # Singleton: reuse existing panel if still alive
    if hasattr(iface, '_layout_panel') and iface._layout_panel is not None:
        try:
            if iface._layout_panel.isVisible():
                iface._layout_panel.raise_()
                iface._layout_panel.activateWindow()
                return
        except RuntimeError:
            iface._layout_panel = None

    panel = create_map_layout_generator_panel()
    iface._layout_panel = panel
    panel.destroyed.connect(lambda: setattr(iface, '_layout_panel', None))
