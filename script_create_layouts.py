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
                       QgsCategorizedSymbolRenderer, QgsUnitTypes)
from qgis.utils import iface

try:
    from .recode_workflow.widgets import LayerCheckList, FieldGroupManager
except ImportError:
    from recode_workflow.widgets import LayerCheckList, FieldGroupManager

try:
    from .recode_workflow.legend_builder import (
        resolve_layer_ref, find_fields_for_table, load_lookup_map,
        detect_lookup_columns, scan_sections_for_sheet,
        build_renderer_value_index, field_has_data,
        discover_section_candidates, auto_sections_from_candidates,
    )
    from .recode_workflow.legend_config import (
        normalize_section, normalize_config,
        serialize_config, deserialize_config, format_text_sections,
    )
except ImportError:
    from recode_workflow.legend_builder import (
        resolve_layer_ref, find_fields_for_table, load_lookup_map,
        detect_lookup_columns, scan_sections_for_sheet,
        build_renderer_value_index, field_has_data,
        discover_section_candidates, auto_sections_from_candidates,
    )
    from recode_workflow.legend_config import (
        normalize_section, normalize_config,
        serialize_config, deserialize_config, format_text_sections,
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

    @staticmethod
    def _mapping_for_layer(mappings, layer):
        """Find a layer's mapping entry: id key first, then by stored name."""
        entry = mappings.get(layer.id())
        if entry:
            return entry
        for key, candidate in mappings.items():
            if (candidate.get('name') == layer.name()
                    or key == layer.name()):
                return candidate
        return {}

    def _populate_tree(self, mappings):
        """Build tree from all project layers, applying saved mappings."""
        self.tree.clear()
        layers = QgsProject.instance().mapLayers().values()

        for layer in sorted(layers, key=lambda l: l.name()):
            layer_name = layer.name()
            layer_mapping = self._mapping_for_layer(mappings, layer)
            display_name = layer_mapping.get('display_name', layer_name)

            # Layer node
            layer_item = QTreeWidgetItem([layer_name, display_name])
            layer_item.setFlags(layer_item.flags() | Qt.ItemIsEditable)
            layer_item.setData(0, Qt.UserRole, 'layer')
            layer_item.setData(0, Qt.UserRole + 1, layer.id())
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
        """Extract the current mappings dict from the tree.

        Keyed by layer id; each entry records the layer name so a mapping
        survives the layer being removed and re-added (name fallback).
        """
        mappings = {}
        for i in range(self.tree.topLevelItemCount()):
            layer_item = self.tree.topLevelItem(i)
            original_name = layer_item.text(self.COL_ORIGINAL)
            display_name = layer_item.text(self.COL_DISPLAY)
            layer_id = layer_item.data(0, Qt.UserRole + 1) or original_name

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
                entry['name'] = original_name
                mappings[layer_id] = entry

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
    """Dialog for configuring legend sections (field groups) per layer.

    Works on v2 section dicts (see legend_config.py).  Per-layer sections
    are edited via the FieldGroupManager; project-wide text sections
    (layer=None, scanned across all spatial layers) via the bottom list.
    """

    def __init__(self, sections=None, mapsheet_layer_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Legend Sections")
        self.setMinimumSize(650, 550)
        self.resize(750, 650)

        self._sections = [normalize_section(s) for s in (sections or [])]
        self._mapsheet_layer_id = mapsheet_layer_id
        self._current_layer_id = None

        # No sections configured yet: pre-fill with auto-detected defaults
        # (lookup-matched field families with data) so the standard template
        # columns are covered without manual setup.
        if not self._sections:
            self._sections = auto_sections_from_candidates(
                discover_section_candidates(QgsProject.instance()))
            if self._sections:
                QgsMessageLog.logMessage(
                    f"Pre-filled {len(self._sections)} auto-detected legend "
                    f"section(s).", LOG_TAG, Qgis.Info)

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

        # Preview (optionally against a single mapsheet)
        preview_row = QHBoxLayout()
        btn_preview = QPushButton("Preview")
        btn_preview.setMaximumWidth(100)
        btn_preview.clicked.connect(self._on_preview)
        preview_row.addWidget(btn_preview)
        preview_row.addWidget(QLabel("Sheet:"))
        self._sheet_combo = QComboBox()
        self._sheet_combo.addItem("(Whole project)", None)
        self._populate_sheet_combo()
        preview_row.addWidget(self._sheet_combo, 1)
        layout.addLayout(preview_row)

        self._preview_label = QLabel("")
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet(
            "color: #333; font-size: 10px; padding: 4px; "
            "background-color: #f5f5f5; border: 1px solid #ddd; "
            "border-radius: 3px;")
        self._preview_label.setMaximumHeight(200)
        layout.addWidget(self._preview_label)

        # ── Project-wide Text Sections ──
        vr_group = QGroupBox("Project-wide Text Sections")
        vr_layout = QVBoxLayout(vr_group)
        vr_info = QLabel(
            "Text-only legend sections scanned across ALL spatial layers "
            "(e.g. codes used by several layers). Optionally backed by a "
            "lookup table for code descriptions; fields auto-detected from "
            "the table name if left blank."
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

        # Save/Load/Reset + OK/Cancel.  Config auto-persists in the QGIS
        # project; Save/Load JSON is for sharing between projects.
        btn_row = QHBoxLayout()
        auto_btn = QPushButton("Auto-detect...")
        auto_btn.setToolTip(
            "Scan all layers for populated code columns (Mineral, Texture, "
            "SubType...) and propose legend sections, with lookup tables "
            "matched by name.")
        auto_btn.clicked.connect(self._auto_detect)
        btn_row.addWidget(auto_btn)
        save_btn = QPushButton("Export JSON...")
        save_btn.clicked.connect(self._save_configs)
        btn_row.addWidget(save_btn)
        load_btn = QPushButton("Import JSON...")
        load_btn.clicked.connect(self._load_configs)
        btn_row.addWidget(load_btn)
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

    def _populate_sheet_combo(self):
        """Fill the preview-sheet combo from the panel's mapsheet layer."""
        if not self._mapsheet_layer_id:
            return
        layer = QgsProject.instance().mapLayer(self._mapsheet_layer_id)
        if not layer:
            return
        name_idx = layer.fields().indexOf('name')
        for feat in layer.getFeatures():
            label = (str(feat[name_idx]) if name_idx >= 0
                     else f"Feature {feat.id()}")
            self._sheet_combo.addItem(label, feat.id())

    def _layer_sections(self, layer_id):
        """Sections targeting a specific layer (id or current name match)."""
        layer = QgsProject.instance().mapLayer(layer_id)
        matched = []
        for section in self._sections:
            ref = section.get('layer')
            if not ref:
                continue
            if ref.get('id') == layer_id or (
                    layer and ref.get('name') == layer.name()
                    and not QgsProject.instance().mapLayer(ref.get('id', ''))):
                matched.append(section)
        return matched

    def _store_current_layer_groups(self):
        """Write the group manager's state back into self._sections."""
        if self._current_layer_id is None:
            return
        layer = QgsProject.instance().mapLayer(self._current_layer_id)
        if not layer:
            return

        old = self._layer_sections(self._current_layer_id)
        insert_at = (self._sections.index(old[0]) if old
                     else len(self._sections))
        for section in old:
            self._sections.remove(section)

        new_sections = []
        for group in self._group_manager.get_field_groups():
            if not group['fields']:
                continue
            new_sections.append(normalize_section({
                'id': group.get('id'),
                'title': group['name'],
                'layer': {'id': layer.id(), 'name': layer.name()},
                'fields': group['fields'],
                'subdivide_by': group['subdivide_by'],
                'display': group.get('display', 'auto'),
                'lookup': group.get('lookup'),
            }))
        self._sections[insert_at:insert_at] = new_sections

    def _on_layer_changed(self, index):
        """Save current layer's sections, load sections for the new layer."""
        self._store_current_layer_groups()

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

        # Load fields (clears existing groups), then restore this layer's
        # sections as group rows.  Fields with data are marked so the
        # picker can hide empty columns.
        field_names = [f.name() for f in layer.fields()]
        self._group_manager.set_available_fields(field_names)
        try:
            populated = {f.name() for i, f in enumerate(layer.fields())
                         if field_has_data(layer, i)}
            self._group_manager.set_populated_fields(populated)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Could not scan populated fields for '{layer.name()}': {e}",
                LOG_TAG, Qgis.Warning)

        groups = []
        for section in self._layer_sections(layer_id):
            groups.append({
                'id': section['id'],
                'name': section['title'],
                'fields': section['fields'],
                'subdivide_by': section['subdivide_by'],
                'display': section['display'],
                'lookup': section['lookup'],
            })
        if groups:
            self._group_manager.restore_groups(groups)

        self._preview_label.setText("")

    def _preview_sheet_geometry(self):
        """Return (geom, crs) for the selected preview sheet, or (None, None)."""
        feat_id = self._sheet_combo.currentData()
        if feat_id is None or not self._mapsheet_layer_id:
            return None, None
        layer = QgsProject.instance().mapLayer(self._mapsheet_layer_id)
        if not layer:
            return None, None
        feat = layer.getFeature(feat_id)
        if not feat.isValid() or feat.geometry().isEmpty():
            return None, None
        return feat.geometry(), layer.crs()

    def _on_preview(self):
        """Dry-run scan of all sections, optionally against one sheet."""
        self._store_current_layer_groups()
        sections = self.get_sections()
        if not sections:
            self._preview_label.setText("No legend sections configured.")
            return

        sheet_geom, sheet_crs = self._preview_sheet_geometry()
        results = scan_sections_for_sheet(
            QgsProject.instance(), sections,
            sheet_geom=sheet_geom, sheet_crs=sheet_crs)

        lines = []
        total = 0
        for section in sections:
            data = results.get(section['id'])
            title = section['title'] or '(untitled)'
            mode = section['display']
            if isinstance(data, dict):
                count = sum(len(v) for v in data.values())
                total += count
                lines.append(
                    f"<b>{title}</b> [{mode}] ({count} values "
                    f"in {len(data)} sub-groups):")
                for type_val, values in data.items():
                    lines.append(
                        f"&nbsp;&nbsp;<b>{type_val}</b> ({len(values)}): "
                        f"{', '.join(values[:8])}"
                        f"{'...' if len(values) > 8 else ''}")
            elif data:
                total += len(data)
                lines.append(
                    f"<b>{title}</b> [{mode}] ({len(data)} values): "
                    f"{', '.join(data[:10])}"
                    f"{'...' if len(data) > 10 else ''}")
            else:
                lines.append(f"<b>{title}</b> [{mode}]: no values found")
            lines.append("")

        scope = (self._sheet_combo.currentText()
                 if sheet_geom is not None else "whole project")
        lines.append(f"<b>Total: {total} legend entries ({scope})</b>")
        self._preview_label.setText("<br>".join(lines))

    def get_sections(self):
        """Return all configured sections (per-layer + project-wide)."""
        self._store_current_layer_groups()
        return [dict(s) for s in self._sections]

    def _auto_detect(self):
        """Discover populated code columns and let the user pick sections."""
        candidates = discover_section_candidates(QgsProject.instance())
        if not candidates:
            QMessageBox.information(
                self, "Auto-detect",
                "No populated code columns found in the project layers.")
            return

        # Skip candidates whose field set is already covered by a section
        existing_field_sets = [frozenset(f.lower() for f in s['fields'])
                               for s in self._sections if s.get('fields')]
        fresh = [c for c in candidates
                 if frozenset(f.lower() for f in c['fields'])
                 not in existing_field_sets]
        if not fresh:
            QMessageBox.information(
                self, "Auto-detect",
                "All detected column families are already configured.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Auto-detected Legend Sections")
        dlg.setMinimumWidth(480)
        dlg.resize(520, 420)
        lay = QVBoxLayout(dlg)
        info = QLabel(
            "Columns containing data, grouped by family. Families matching "
            "a lookup table are pre-ticked (codes get descriptions); others "
            "show bare codes. Tick the sections to add:")
        info.setWordWrap(True)
        lay.addWidget(info)

        lst = QListWidget()
        for cand in fresh:
            if cand['lookup']:
                detail = cand['lookup']['table']['name']
            else:
                detail = "no lookup table"
            label = (f"{cand['title']}  —  {', '.join(cand['fields'])}"
                     f"  ({detail})")
            item = QListWidgetItem(label)
            item.setToolTip("Layers: " + ", ".join(cand['layers']))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if cand['matched'] else Qt.Unchecked)
            item.setData(Qt.UserRole, cand)
            lst.addItem(item)
        lay.addWidget(lst, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)

        if dlg.exec() != QDialog.Accepted:
            return

        added = 0
        for i in range(lst.count()):
            item = lst.item(i)
            if item.checkState() != Qt.Checked:
                continue
            cand = item.data(Qt.UserRole)
            self._sections.append(normalize_section({
                'title': cand['title'],
                'layer': None,
                'fields': cand['fields'],
                'display': 'text',
                'lookup': cand['lookup'],
            }))
            added += 1

        if added:
            self._refresh_vr_list()
            QgsMessageLog.logMessage(
                f"Auto-detect added {added} legend section(s).",
                LOG_TAG, Qgis.Info)

    def _save_configs(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Legend Sections", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(serialize_config({'sections': self.get_sections()}))
            QMessageBox.information(self, "Saved",
                                   f"Legend sections saved to:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to save: {e}")

    def _load_configs(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Legend Sections", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                config = deserialize_config(f.read())  # migrates v1 files
            self._sections = config['sections']
            self._refresh_vr_list()
            # Reload current layer view from the imported sections
            self._current_layer_id = None
            self._on_layer_changed(self._layer_combo.currentIndex())
            QMessageBox.information(self, "Loaded",
                                   f"Legend sections loaded from:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load: {e}")

    def _project_wide_sections(self):
        """Sections with no target layer (scanned across all spatial layers)."""
        return [s for s in self._sections if not s.get('layer')]

    def _refresh_vr_list(self):
        """Rebuild the project-wide text sections list widget."""
        self._vr_list.clear()
        for sec in self._project_wide_sections():
            lookup = sec.get('lookup')
            table_name = (lookup['table'].get('name', '?')
                          if lookup else 'no lookup')
            fields = sec.get('fields', [])
            if fields:
                fields_str = ", ".join(fields[:4])
                if len(fields) > 4:
                    fields_str += "..."
                self._vr_list.addItem(
                    f"{sec['title']}  ({table_name} → {fields_str})")
            else:
                self._vr_list.addItem(
                    f"{sec['title']}  ({table_name} → auto-detect)")

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
            auto_key, auto_val = detect_lookup_columns(tbl)
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
            matched = find_fields_for_table(QgsProject.instance(), tname)
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
                self._sections.append(normalize_section({
                    'title': name_edit.text() or tbl.name(),
                    'layer': None,
                    'fields': scan_fields,
                    'display': 'text',
                    'lookup': {
                        'table': {'id': tbl.id(), 'name': tbl.name()},
                        'key_column': key_combo.currentText(),
                        'value_column': val_combo.currentText(),
                    },
                }))
                self._refresh_vr_list()

    def _remove_vr_section(self):
        """Remove the selected project-wide text section."""
        row = self._vr_list.currentRow()
        project_wide = self._project_wide_sections()
        if 0 <= row < len(project_wide):
            self._sections.remove(project_wide[row])
            self._refresh_vr_list()

    def _reset(self):
        self._sections.clear()
        self._current_layer_id = None
        fields = []
        layer_id = self._layer_combo.currentData()
        if layer_id:
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer:
                fields = [f.name() for f in layer.fields()]
                self._current_layer_id = layer_id
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

        # Restore persisted legend config, then start auto-saving changes
        self._restore_legend_state()
        self._connect_project_signals()

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

        # Storage for legend text mappings and sections (v2 config)
        self.legend_text_mappings = {}  # {layer_id: {name, display_name, features}}
        self._sections = []  # v2 section dicts (see legend_config.py)
        self._restoring_state = False
        self._last_preview_text = ''

        # Per-sheet options
        self.perSheetCheckbox = QCheckBox(
            "Per-sheet legend content (scan only features on each sheet)")
        self.perSheetCheckbox.setChecked(True)
        self.perSheetCheckbox.toggled.connect(
            lambda _checked: self._save_legend_state())
        layout.addWidget(self.perSheetCheckbox)

        self.filterByMapCheckbox = QCheckBox(
            "Filter legend symbols by map content")
        self.filterByMapCheckbox.setChecked(True)
        self.filterByMapCheckbox.toggled.connect(
            lambda _checked: self._save_legend_state())
        layout.addWidget(self.filterByMapCheckbox)

        # Additional manual legend text (appended after generated sections).
        # Text sections themselves are regenerated per sheet at generate time.
        codeTableLabel = QLabel(
            "Legend text preview / additional manual text "
            "(placed below legend in each layout):")
        codeTableLabel.setStyleSheet("color: #5F6368; font-size: 10px;")
        layout.addWidget(codeTableLabel)

        scanBtn = QPushButton("Preview Text Sections")
        scanBtn.setMaximumWidth(160)
        scanBtn.setToolTip(
            "Generate a project-wide preview of the text sections. "
            "At generate time the text is rebuilt per sheet.")
        scanBtn.clicked.connect(self._scan_code_table_text)
        layout.addWidget(scanBtn)

        self.codeTableText = QPlainTextEdit()
        self.codeTableText.setMaximumHeight(100)
        self.codeTableText.setPlaceholderText(
            "Configure sections via 'Configure Legend Sections...', then "
            "click 'Preview Text Sections'. Anything you type here is "
            "appended to each layout's legend text.")
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
        """Refresh the legend layer check list, preserving check state.

        Layers not previously listed default to checked (included), so a
        layer added mid-session is never silently dropped from the legend.
        """
        unchecked = set(self.legendLayerList.unchecked_layer_ids())
        all_layers = list(QgsProject.instance().mapLayers().values())
        self.legendLayerList.set_layers(all_layers, unchecked_ids=unchecked)

    # ── Legend config persistence (stored in the QGIS project) ───────

    LEGEND_SCOPE = 'LinearGeoscience'
    LEGEND_KEY = 'layout_legend_config'

    def _current_legend_config(self):
        """Assemble the v2 config dict from the panel's state."""
        unchecked = []
        for layer_id in self.legendLayerList.unchecked_layer_ids():
            layer = QgsProject.instance().mapLayer(layer_id)
            unchecked.append({'id': layer_id,
                              'name': layer.name() if layer else ''})
        box_text = self.codeTableText.toPlainText().strip()
        manual = '' if box_text == self._last_preview_text.strip() else box_text
        return normalize_config({
            'sections': self._sections,
            'text_mappings': self.legend_text_mappings,
            'legend_unchecked_layers': unchecked,
            'code_table_text_manual': manual,
            'options': {
                'per_sheet_scan': self.perSheetCheckbox.isChecked(),
                'filter_legend_by_map': self.filterByMapCheckbox.isChecked(),
            },
        })

    def _save_legend_state(self):
        """Persist legend config into the project file (auto-save)."""
        if self._restoring_state:
            return
        try:
            QgsProject.instance().writeEntry(
                self.LEGEND_SCOPE, self.LEGEND_KEY,
                serialize_config(self._current_legend_config()))
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Failed to save legend config: {e}", LOG_TAG, Qgis.Warning)

    def _restore_legend_state(self):
        """Restore legend config from the project file."""
        raw, ok = QgsProject.instance().readEntry(
            self.LEGEND_SCOPE, self.LEGEND_KEY, "")
        if not ok or not raw.strip():
            return
        self._restoring_state = True
        try:
            config = deserialize_config(raw)
            self._sections = config['sections']
            self.legend_text_mappings = config['text_mappings']
            unchecked = [r['id'] for r in config['legend_unchecked_layers']]
            # Re-resolve unchecked refs whose id no longer exists by name
            for ref in config['legend_unchecked_layers']:
                if not QgsProject.instance().mapLayer(ref['id']):
                    for lyr in QgsProject.instance().mapLayersByName(
                            ref.get('name', '')):
                        unchecked.append(lyr.id())
            all_layers = list(QgsProject.instance().mapLayers().values())
            self.legendLayerList.set_layers(all_layers,
                                            unchecked_ids=unchecked)
            self.perSheetCheckbox.setChecked(
                config['options']['per_sheet_scan'])
            self.filterByMapCheckbox.setChecked(
                config['options']['filter_legend_by_map'])
            manual = config['code_table_text_manual']
            if manual:
                self.codeTableText.setPlainText(manual)
            QgsMessageLog.logMessage(
                f"Legend config restored from project "
                f"({len(self._sections)} section(s)).", LOG_TAG, Qgis.Info)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Failed to restore legend config: {e}", LOG_TAG, Qgis.Warning)
        finally:
            self._restoring_state = False

    def _connect_project_signals(self):
        """Keep the checklist fresh and reload config on project change."""
        project = QgsProject.instance()
        project.layersAdded.connect(self._on_project_layers_changed)
        project.layersRemoved.connect(self._on_project_layers_changed)
        project.readProject.connect(self._on_project_read)
        self.legendLayerList.checks_changed.connect(self._save_legend_state)
        self.destroyed.connect(self._disconnect_project_signals)

    def _disconnect_project_signals(self):
        project = QgsProject.instance()
        for signal, slot in (
                (project.layersAdded, self._on_project_layers_changed),
                (project.layersRemoved, self._on_project_layers_changed),
                (project.readProject, self._on_project_read)):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    def _on_project_layers_changed(self, *args):
        self.populateLegendLayers()
        self.populateLayerComboBox()

    def _on_project_read(self, *args):
        self.populateLayerComboBox()
        self.populateLegendLayers()
        self._restore_legend_state()

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
        self.perSheetCheckbox.setEnabled(checked)
        self.filterByMapCheckbox.setEnabled(checked)

    def openLegendTextEditor(self):
        """Open the legend text editor dialog."""
        dlg = LegendTextEditorDialog(self.legend_text_mappings, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.legend_text_mappings = dlg.get_mappings()
            self._save_legend_state()
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
        """Open the legend sections configuration dialog."""
        dlg = LegendFieldConfigDialog(
            self._sections,
            mapsheet_layer_id=self.layerCombo.currentData(),
            parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._sections = dlg.get_sections()
            self._save_legend_state()
            QgsMessageLog.logMessage(
                f"Legend sections updated: {len(self._sections)} section(s).",
                LOG_TAG, Qgis.Info)

            # Refresh the text preview when text sections exist
            if any(s['display'] in ('text', 'auto') for s in self._sections):
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

    def _populate_labels(self, layout, feature_number, total_count,
                         title_text=None):
        """Find labels by Item ID and set their text."""
        author = self.authorEdit.text().strip()
        drafter = self.drafterEdit.text().strip()

        label_map = {
            'title': title_text or layout.name(),
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

    def _place_text_block(self, layout, plain_text):
        """Place the legend text block in the layout.

        Reuses a template label with Item ID 'code_table' if present
        (keeping its position/size); otherwise creates a label directly
        below the finalised legend.  Uses ModeFont (native vector
        rendering) for text quality matching the legend — HTML mode would
        rasterise on export.
        """
        from qgis.core import QgsLayoutPoint, QgsLayoutSize
        from qgis.PyQt.QtGui import QFont

        # Prefer an existing template item so users control placement
        for item in layout.items():
            if (isinstance(item, QgsLayoutItemLabel)
                    and item.id() == 'code_table'):
                item.setMode(QgsLayoutItemLabel.ModeFont)
                item.setText(plain_text)
                QgsMessageLog.logMessage(
                    "Legend text placed in template 'code_table' item.",
                    LOG_TAG, Qgis.Info)
                return

        label = QgsLayoutItemLabel(layout)
        label.setMode(QgsLayoutItemLabel.ModeFont)
        label.setText(plain_text)
        label.setId('code_table')
        label.setFont(QFont("MS Shell Dlg 2", 8))

        # Position below the finalized legend.  Convert the legend's
        # position/size to layout units rather than assuming millimetres.
        legends = [i for i in layout.items()
                   if isinstance(i, QgsLayoutItemLegend)]
        page = layout.pageCollection().page(0)
        page_size = (layout.convertToLayoutUnits(page.pageSize())
                     if page else None)
        if legends:
            legend = legends[0]
            pos = layout.convertToLayoutUnits(legend.positionWithUnits())
            size = layout.convertToLayoutUnits(legend.sizeWithUnits())
            x = pos.x()
            y = pos.y() + size.height() + 3
            width = max(size.width(), 80)
        elif page_size is not None:
            x = 10
            y = page_size.height() * 0.6
            width = max(page_size.width() * 0.25, 80)
        else:
            x, y, width = 10, 250, 120

        label.attemptMove(QgsLayoutPoint(x, y, layout.units()))
        label.attemptResize(QgsLayoutSize(width, 50, layout.units()))
        label.adjustSizeToText()

        if page_size is not None:
            bottom = (layout.convertToLayoutUnits(label.positionWithUnits()).y()
                      + layout.convertToLayoutUnits(label.sizeWithUnits()).height())
            if bottom > page_size.height():
                QgsMessageLog.logMessage(
                    "Legend text block overflows the page. Consider adding "
                    "a 'code_table' label item to the template to control "
                    "its placement.", LOG_TAG, Qgis.Warning)

        layout.addLayoutItem(label)
        QgsMessageLog.logMessage(
            "Legend text block created below legend.", LOG_TAG, Qgis.Info)

    # ── Legend automation ─────────────────────────────────────────────

    def _configure_legend(self, layout, excluded_layer_ids, text_mappings=None,
                          main_map=None, filter_by_map=False):
        """Refresh legend, freeze it, remove excluded layers, and apply text overrides."""
        legends = [item for item in layout.items()
                   if isinstance(item, QgsLayoutItemLegend)]
        if not legends:
            QgsMessageLog.logMessage(
                "No legend item found in template - skipping legend automation.",
                LOG_TAG, Qgis.Warning)
            return

        legend = legends[0]

        # Force a clean resync to the current project layer tree: disconnect
        # first so the reconnect is never a no-op (templates with auto-update
        # already True would skip it).  This intentionally discards any
        # legend customisation saved in the template — templates go stale
        # against evolving projects, so the project tree is authoritative.
        legend.setAutoUpdateModel(False)
        legend.setAutoUpdateModel(True)
        legend.setAutoUpdateModel(False)

        # Filter legend symbology by what the linked map actually renders.
        # Filtering happens at render time, so it composes with the frozen
        # model and with the per-section node clones added later.
        if filter_by_map and main_map is not None:
            if legend.linkedMap() is None:
                legend.setLinkedMap(main_map)
            legend.setLegendFilterByMapEnabled(True)

        # Remove excluded layers from the frozen legend.  removeChildNode
        # only works on the node's direct parent, so nodes nested inside
        # layer-tree groups must be removed via node.parent().
        root = legend.model().rootGroup()

        removed_count = 0
        for layer_id in excluded_layer_ids:
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer:
                node = root.findLayer(layer)
                if node:
                    parent = node.parent() or root
                    parent.removeChildNode(node)
                    removed_count += 1

        if removed_count:
            QgsMessageLog.logMessage(
                f"Removed {removed_count} layer(s) from legend.",
                LOG_TAG, Qgis.Info)

        # Apply legend text overrides
        if text_mappings:
            self._apply_legend_text(legend, text_mappings)

        legend.updateLegend()

    def _apply_legend_text(self, legend, text_mappings):
        """Apply custom display names to legend layer titles and feature labels.

        Mappings are keyed by layer id, with the layer name recorded in
        each entry as a fallback (and for legacy name-keyed configs).
        """
        root = legend.model().rootGroup()
        renamed_count = 0

        for layer_node in root.findLayers():
            layer = layer_node.layer()
            if layer is None:
                continue
            mapping = text_mappings.get(layer.id())
            if not mapping:
                for key, candidate in text_mappings.items():
                    if (candidate.get('name') == layer.name()
                            or key == layer.name()):
                        mapping = candidate
                        break
            if not mapping:
                continue

            # Rename the layer title in the legend
            display_name = mapping.get('display_name')
            if display_name:
                layer_node.setCustomProperty("legend/title-label", display_name)
                renamed_count += 1

            # Rename individual feature/symbol labels
            feature_mappings = mapping.get('features', {})
            if (feature_mappings
                    and layer.type() == QgsMapLayerType.VectorLayer
                    and layer.renderer()):
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
                        f"Error applying legend text for '{layer.name()}': {e}",
                        LOG_TAG, Qgis.Warning)

        if renamed_count:
            QgsMessageLog.logMessage(
                f"Applied {renamed_count} legend text override(s).",
                LOG_TAG, Qgis.Info)

    def _apply_symbol_sections(self, layout, sections, scan_results):
        """Apply symbol-backed sections as grouped legend node clones.

        Replaces each configured layer's single legend node with multiple
        clones, each filtered by setLegendNodeOrder to show only its
        section's entries.  Uses QgsLayerTreeGroup for sub-divided headings.

        Returns {section_id: unmatched values} for 'auto' sections whose
        values have no renderer symbol — these overflow into the text
        block instead of being dropped.
        """
        unmatched_by_section = {}

        legends = [i for i in layout.items()
                   if isinstance(i, QgsLayoutItemLegend)]
        if not legends:
            return unmatched_by_section
        legend = legends[0]
        root = legend.model().rootGroup()

        # Group symbol-backed sections by target layer, preserving order
        by_layer = {}
        for section in sections:
            if section['display'] not in ('symbols', 'auto'):
                continue
            if not section.get('layer') or not section.get('fields'):
                continue
            layer = resolve_layer_ref(QgsProject.instance(), section['layer'])
            if layer is None:
                continue
            by_layer.setdefault(layer.id(), (layer, []))[1].append(section)

        for layer, layer_sections in by_layer.values():
            if not layer.renderer():
                # No symbology at all: auto sections overflow entirely to text
                for section in layer_sections:
                    if section['display'] == 'auto':
                        unmatched_by_section[section['id']] = \
                            scan_results.get(section['id'])
                continue

            layer_node = root.findLayer(layer)
            if not layer_node:
                continue

            value_to_idx, symbol_count = build_renderer_value_index(layer)

            QgsMessageLog.logMessage(
                f"Legend expansion '{layer.name()}': "
                f"{symbol_count} legend items, "
                f"{len(value_to_idx)} mappable values, "
                f"{len(layer_sections)} section(s).",
                LOG_TAG, Qgis.Info)

            # Clone before removing — removeChildNode deletes the C++ object
            layer_node_template = layer_node.clone()

            # Get position in parent for reinsertion
            parent = layer_node.parent()
            siblings = parent.children()
            position = (siblings.index(layer_node)
                        if layer_node in siblings else len(siblings))

            # Remove original node (clones replace it)
            parent.removeChildNode(layer_node)

            used_indices = set()

            for section in layer_sections:
                sid = section['id']
                title = section['title']
                is_auto = section['display'] == 'auto'
                data = scan_results.get(sid)
                if not data:
                    continue

                if isinstance(data, dict):
                    # Subdivided: group heading + sub-group clones
                    group_tree = QgsLayerTreeGroup(title)
                    sub_unmatched = {}

                    for type_val, subtype_values in data.items():
                        indices = [value_to_idx[v] for v in subtype_values
                                   if v in value_to_idx]
                        missed = [v for v in subtype_values
                                  if v not in value_to_idx]
                        if missed:
                            if is_auto:
                                sub_unmatched[type_val] = missed
                            else:
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
                    if sub_unmatched:
                        unmatched_by_section[sid] = sub_unmatched
                else:
                    # Flat: single clone with filtered indices
                    indices = [value_to_idx[v] for v in data
                               if v in value_to_idx]
                    missed = [v for v in data if v not in value_to_idx]
                    if missed:
                        if is_auto:
                            unmatched_by_section[sid] = missed
                        else:
                            QgsMessageLog.logMessage(
                                f"  '{title}': {len(missed)} value(s) "
                                f"not in renderer: {missed[:5]}",
                                LOG_TAG, Qgis.Warning)
                    if indices:
                        used_indices.update(indices)
                        clone = layer_node_template.clone()
                        clone.setCustomProperty("legend/title-label", title)
                        QgsMapLayerLegendUtils.setLegendNodeOrder(
                            clone, indices)
                        parent.insertChildNode(position, clone)
                        position += 1

            QgsMessageLog.logMessage(
                f"  '{layer.name()}': {len(used_indices)} of "
                f"{symbol_count} entries assigned to sections.",
                LOG_TAG, Qgis.Info)

        legend.updateLegend()
        legend.adjustBoxSize()
        return unmatched_by_section

    def _load_lookup_maps(self, sections):
        """Load {section_id: {code: description}} for sections with lookups."""
        maps = {}
        for section in sections:
            lookup = section.get('lookup')
            if not lookup:
                continue
            table = resolve_layer_ref(QgsProject.instance(), lookup['table'])
            if table is None:
                QgsMessageLog.logMessage(
                    f"Lookup table '{lookup['table'].get('name')}' not found "
                    f"for section '{section['title']}'.", LOG_TAG, Qgis.Warning)
                continue
            maps[section['id']] = load_lookup_map(
                table, lookup['key_column'], lookup['value_column'])
        return maps

    def _scan_code_table_text(self):
        """Project-wide preview of the legend text sections.

        At generate time the text is rebuilt per sheet; this preview shows
        the whole-project result.  If the user edits the box afterwards,
        their edited text is used verbatim instead (WYSIWYG override).
        """
        sections = [normalize_section(s) for s in self._sections]
        if not sections:
            # Same fallback as generate time: auto-detected defaults
            sections = auto_sections_from_candidates(
                discover_section_candidates(QgsProject.instance()))
            if sections:
                QgsMessageLog.logMessage(
                    f"Preview using {len(sections)} auto-detected "
                    f"section(s).", LOG_TAG, Qgis.Info)
        text_like = [s for s in sections if s['display'] in ('text', 'auto')]
        if not text_like:
            QMessageBox.information(
                self, "No Text Sections",
                "No sections configured and no populated code columns "
                "found to auto-detect. Use 'Configure Legend Sections...' "
                "to set them up manually.")
            return

        scan_results = scan_sections_for_sheet(QgsProject.instance(), sections)
        lookup_maps = self._load_lookup_maps(sections)

        # For 'auto' sections the preview shows what would overflow to text
        # (values with no renderer symbol).
        extra_unmatched = {}
        for section in sections:
            if section['display'] != 'auto' or not section.get('layer'):
                continue
            layer = resolve_layer_ref(QgsProject.instance(), section['layer'])
            value_to_idx, _count = build_renderer_value_index(layer)
            data = scan_results.get(section['id'])
            if isinstance(data, dict):
                missed = {sub: [v for v in vals if v not in value_to_idx]
                          for sub, vals in data.items()}
                missed = {sub: vals for sub, vals in missed.items() if vals}
                if missed:
                    extra_unmatched[section['id']] = missed
            elif data:
                missed = [v for v in data if v not in value_to_idx]
                if missed:
                    extra_unmatched[section['id']] = missed

        text = format_text_sections(
            sections, scan_results, lookup_maps, extra_unmatched)
        self.codeTableText.setPlainText(text)
        self._last_preview_text = text
        self._save_legend_state()
        QgsMessageLog.logMessage(
            f"Legend text preview generated for {len(text_like)} section(s).",
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
                ok = True
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
                        ok = False
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
                        ok = False
                        QgsMessageLog.logMessage(
                            f"GeoTIFF export failed for '{name}': error code {result}",
                            LOG_TAG, Qgis.Warning)

                if do_png:
                    png_settings = QgsLayoutExporter.ImageExportSettings()
                    png_settings.dpi = dpi
                    result = exporter.exportToImage(
                        os.path.join(out_dir, f"{safe_name}.png"), png_settings)
                    if result != QgsLayoutExporter.Success:
                        ok = False
                        QgsMessageLog.logMessage(
                            f"PNG export failed for '{name}': error code {result}",
                            LOG_TAG, Qgis.Warning)

                if ok:
                    export_success += 1
                    self.statusLabel.setText(f"Exported: {name}")
                else:
                    export_fail += 1
                    self.statusLabel.setText(f"Export failed: {name}")

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

            # Persist the current legend config with the project
            self._save_legend_state()

            # Compute legend exclusion list.  Only explicitly unchecked
            # layers are excluded — layers added since the checklist was
            # populated stay in the legend by default.
            legend_enabled = self.legendCheckbox.isChecked()
            excluded_layer_ids = []
            if legend_enabled:
                current_ids = set(QgsProject.instance().mapLayers().keys())
                excluded_layer_ids = [
                    lid for lid in self.legendLayerList.unchecked_layer_ids()
                    if lid in current_ids]

            # Legend sections: scan per sheet (or once, project-wide).
            # With nothing configured, fall back to auto-detected defaults
            # (lookup-matched field families with data) — ephemeral, not
            # persisted, so template changes keep flowing through.
            sections = [normalize_section(s) for s in self._sections]
            if legend_enabled and not sections:
                sections = auto_sections_from_candidates(
                    discover_section_candidates(QgsProject.instance()))
                if sections:
                    QgsMessageLog.logMessage(
                        f"No legend sections configured — using "
                        f"{len(sections)} auto-detected section(s): "
                        f"{', '.join(s['title'] for s in sections)}.",
                        LOG_TAG, Qgis.Info)
            lookup_maps = (self._load_lookup_maps(sections)
                           if sections else {})
            per_sheet = self.perSheetCheckbox.isChecked()
            filter_by_map = self.filterByMapCheckbox.isChecked()
            sheet_crs = polygon_layer.crs()
            project_wide_results = None
            if sections and not per_sheet:
                project_wide_results = scan_sections_for_sheet(
                    QgsProject.instance(), sections)

            # Manual legend text: used verbatim if the user edited the box,
            # otherwise the text is regenerated (per sheet) from sections.
            box_text = self.codeTableText.toPlainText().strip()
            manual_text = (box_text
                           if box_text != self._last_preview_text.strip()
                           else '')

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
                    # Manager name must be single-line; the template title
                    # label still gets the two-line form via _populate_labels.
                    layout_name = f"{project_name} - {polygon_name}"
                    title_text = f"{project_name}\n{polygon_name}"

                    # Remove existing layout if it exists (also checks the
                    # pre-v3.4 newline-separated name form)
                    manager = QgsProject.instance().layoutManager()
                    for old_name in (layout_name,
                                     f"{project_name}\n{polygon_name}"):
                        existing = manager.layoutByName(old_name)
                        if existing:
                            manager.removeLayout(existing)
                            self.statusLabel.setText(
                                f"Replacing existing layout: {layout_name}")

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

                    # Auto-set grid X/Y interval based on selected scale (or
                    # override).  The interval is metres, so skip non-metre
                    # CRSes rather than writing metres into degree units.
                    grid_interval = self.getGridInterval()
                    if grid_interval is not None:
                        map_units = main_map.crs().mapUnits()
                        if map_units != QgsUnitTypes.DistanceMeters:
                            QgsMessageLog.logMessage(
                                f"Map CRS for '{layout_name}' is not in "
                                f"metres; skipping grid spacing.",
                                LOG_TAG, Qgis.Warning)
                        else:
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
                    self._populate_labels(layout, feature_number,
                                          feature_count, title_text)

                    # Per-sheet legend content
                    scan_results = {}
                    if sections:
                        if per_sheet:
                            scan_results = scan_sections_for_sheet(
                                QgsProject.instance(), sections,
                                sheet_geom=geom, sheet_crs=sheet_crs)
                        else:
                            scan_results = project_wide_results or {}

                    # Automate legend
                    unmatched = {}
                    if legend_enabled:
                        self._configure_legend(
                            layout, excluded_layer_ids,
                            self.legend_text_mappings,
                            main_map=main_map, filter_by_map=filter_by_map)

                        # Expand configured layers into grouped legend
                        # entries; values without symbols overflow to text
                        if sections:
                            unmatched = self._apply_symbol_sections(
                                layout, sections, scan_results)

                    # Build and place the legend text block.  An edited text
                    # box overrides the generated text verbatim.
                    if manual_text:
                        text_block = manual_text
                    else:
                        text_block = format_text_sections(
                            sections, scan_results, lookup_maps, unmatched)
                    if text_block:
                        self._place_text_block(layout, text_block)

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
