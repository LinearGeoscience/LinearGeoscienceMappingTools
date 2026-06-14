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
                       QgsLayoutItemLabel, QgsLayoutItemScaleBar,
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
        resolve_layer_ref, find_fields_for_table,
        load_lookup_table, detect_lookup_columns, scan_sections_for_sheet,
        build_renderer_value_index, field_has_data,
        discover_section_candidates, auto_sections_from_candidates,
        collect_widget_lookups, collect_paired_lookups, paired_base_field,
        find_paired_description_field,
    )
    from .recode_workflow.legend_config import (
        normalize_section, normalize_config,
        serialize_config, deserialize_config,
        build_text_section_lines,
        group_values_by_lookup, text_from_section_lines,
        derive_text_overrides, apply_text_overrides,
    )
except ImportError:
    from recode_workflow.legend_builder import (
        resolve_layer_ref, find_fields_for_table,
        load_lookup_table, detect_lookup_columns, scan_sections_for_sheet,
        build_renderer_value_index, field_has_data,
        discover_section_candidates, auto_sections_from_candidates,
        collect_widget_lookups, collect_paired_lookups, paired_base_field,
        find_paired_description_field,
    )
    from recode_workflow.legend_config import (
        normalize_section, normalize_config,
        serialize_config, deserialize_config,
        build_text_section_lines,
        group_values_by_lookup, text_from_section_lines,
        derive_text_overrides, apply_text_overrides,
    )

try:
    from .layer_select import layer_display_name, find_best_match
except ImportError:
    from layer_select import layer_display_name, find_best_match

LOG_TAG = 'Linear Geoscience'


def export_layouts_to_formats(layout_names, out_dir, dpi=300, do_pdf=True,
                              do_tiff=False, do_png=False, log=None, progress=None):
    """Export named print layouts from the current project to disk.

    UI-free and reusable: driven by both the Create Layouts dock and the unified
    Mapping Export. PDF is georeferenced (GeoPDF where supported); GeoTIFF and
    PNG are written with a worldfile so they stay georeferenced.

    Args:
        layout_names: layout names present in the current project.
        out_dir: existing output directory.
        dpi: export resolution.
        do_pdf / do_tiff / do_png: which formats to write.
        log: optional callable(message) for status/error text.
        progress: optional callable(done, total) for progress reporting.

    Returns:
        tuple: (success_count, fail_count)
    """
    def _log(msg):
        if log:
            log(msg)
        QgsMessageLog.logMessage(msg, LOG_TAG, Qgis.Info)

    total = len(layout_names)
    export_success = 0
    export_fail = 0

    for idx, name in enumerate(layout_names):
        if progress:
            progress(idx + 1, total)

        layout = QgsProject.instance().layoutManager().layoutByName(name)
        if not layout:
            _log(f"Layout '{name}' not found for export.")
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
                    _log(f"PDF export failed for '{name}': error code {result}")

            if do_tiff:
                tiff_settings = QgsLayoutExporter.ImageExportSettings()
                tiff_settings.dpi = dpi
                tiff_settings.generateWorldFile = True
                result = exporter.exportToImage(
                    os.path.join(out_dir, f"{safe_name}.tif"), tiff_settings)
                if result != QgsLayoutExporter.Success:
                    ok = False
                    _log(f"GeoTIFF export failed for '{name}': error code {result}")

            if do_png:
                png_settings = QgsLayoutExporter.ImageExportSettings()
                png_settings.dpi = dpi
                png_settings.generateWorldFile = True
                result = exporter.exportToImage(
                    os.path.join(out_dir, f"{safe_name}.png"), png_settings)
                if result != QgsLayoutExporter.Success:
                    ok = False
                    _log(f"PNG export failed for '{name}': error code {result}")

            if ok:
                export_success += 1
                _log(f"Exported: {name}")
            else:
                export_fail += 1

        except Exception as e:
            _log(f"Export error for '{name}': {e}")
            export_fail += 1

    return export_success, export_fail


def parse_scale_text(value):
    """Parse a scale attribute ('1:10,000', '10000', 10000.0) into an
    integer denominator, or None when empty/invalid."""
    if value is None:
        return None
    s = str(value).strip().replace(',', '').replace(' ', '')
    if not s or s.upper() == 'NULL':
        return None
    if ':' in s:
        s = s.split(':', 1)[1]
    try:
        denominator = int(float(s))
    except ValueError:
        return None
    return denominator if denominator > 0 else None


# Nice mantissas for scalebar segment sizes (x 10^k metres).
_SCALEBAR_NICE_MANTISSAS = (1.0, 2.0, 2.5, 5.0)


def compute_nice_scalebar(scale, target_bar_mm, max_bar_mm,
                          min_segments=3, max_segments=8,
                          pref_lo=4, pref_hi=6, km_threshold_m=1000.0):
    """Choose nice-round scalebar segments that fill a fixed paper frame.

    Pure function (no QGIS dependencies) so it can be unit-tested.

    Given a map ``scale`` denominator (e.g. 500 for 1:500), a desired drawn
    bar length ``target_bar_mm`` and a hard ceiling ``max_bar_mm`` (both in
    millimetres on the page), pick a nice segment size (mantissa 1/2/2.5/5 x
    10^k metres) and a segment count so the drawn bars fill the target as
    closely as possible without ever exceeding the ceiling.

    Candidates are scored lexicographically (smaller is better):
      1) fractional shortfall/overshoot from the target fill -- a perfect fill
         always wins, which is what reproduces 5 x 25 m at 1:500;
      2) distance outside the preferred segment-count band [pref_lo, pref_hi];
      3) prefer round mantissas (1/2/5) over 2.5;
      4) more segments as a final tiebreak.

    Switches the label to kilometres once the segment size reaches
    ``km_threshold_m`` metres.

    Returns a dict with keys ``units_per_segment`` (in the chosen display
    unit), ``n_segments``, ``unit_label`` ('m'/'km'), ``map_units_per_bar_unit``
    (1.0/1000.0), ``drawn_mm``, ``segment_m`` and ``total_m``; or ``None`` when
    ``scale`` is not a positive number (caller should skip).
    """
    if not scale or scale <= 0:
        return None

    best = None  # (score_tuple, drawn_mm, seg_m, n)
    for k in range(-3, 12):                 # 0.001 m .. 5e9 m segment sizes
        base = 10.0 ** k
        for mant in _SCALEBAR_NICE_MANTISSAS:
            seg_m = mant * base             # metres per segment
            for n in range(min_segments, max_segments + 1):
                drawn_mm = (seg_m * n) / scale * 1000.0
                if drawn_mm > max_bar_mm + 1e-9:
                    continue                # never overflow the frame
                fill_err = abs(drawn_mm - target_bar_mm) / target_bar_mm
                if n < pref_lo:
                    seg_pen = pref_lo - n
                elif n > pref_hi:
                    seg_pen = n - pref_hi
                else:
                    seg_pen = 0
                mant_pen = 0.0 if mant in (1.0, 2.0, 5.0) else 1.0
                score = (fill_err, seg_pen, mant_pen, -n)
                if best is None or score < best[0]:
                    best = (score, drawn_mm, seg_m, n)

    if best is None:                        # target/max impossibly small
        return None

    _, drawn_mm, seg_m, n = best
    if seg_m >= km_threshold_m:
        unit_label = 'km'
        map_units_per_bar_unit = 1000.0
        units_per_segment = seg_m / 1000.0
    else:
        unit_label = 'm'
        map_units_per_bar_unit = 1.0
        units_per_segment = seg_m

    return {
        'units_per_segment': units_per_segment,
        'n_segments': n,
        'unit_label': unit_label,
        'map_units_per_bar_unit': map_units_per_bar_unit,
        'drawn_mm': drawn_mm,
        'segment_m': seg_m,
        'total_m': seg_m * n,
    }


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

        # ── Text Sections ──
        vr_group = QGroupBox("Text Sections")
        vr_layout = QVBoxLayout(vr_group)
        vr_info = QLabel(
            "Text-only legend sections. 'Add Lookup Section' scans chosen "
            "data columns and describes codes via a lookup table. "
            "'Add Layer Section' builds a code table straight from a "
            "layer's own columns (code + paired Description columns), "
            "optionally split by a Type field. Double-click to edit."
        )
        vr_info.setWordWrap(True)
        vr_info.setStyleSheet("color: #5F6368; font-size: 10px; font-style: italic;")
        vr_layout.addWidget(vr_info)

        self._vr_list = QListWidget()
        self._vr_list.setMaximumHeight(100)
        self._vr_list.itemDoubleClicked.connect(
            lambda _item: self._edit_selected_section())
        vr_layout.addWidget(self._vr_list)

        vr_btn_row = QHBoxLayout()
        add_vr_btn = QPushButton("Add Lookup Section...")
        add_vr_btn.clicked.connect(lambda: self._edit_lookup_section())
        vr_btn_row.addWidget(add_vr_btn)
        add_layer_btn = QPushButton("Add Layer Section...")
        add_layer_btn.clicked.connect(lambda: self._edit_layer_section())
        vr_btn_row.addWidget(add_layer_btn)
        edit_vr_btn = QPushButton("Edit...")
        edit_vr_btn.clicked.connect(self._edit_selected_section)
        vr_btn_row.addWidget(edit_vr_btn)
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

    @staticmethod
    def _section_detail(sec):
        """One-line description of a text section for the list widget."""
        lookup = sec.get('lookup') or {}
        targets = sec.get('field_targets')
        if targets:
            parts = []
            for target in targets:
                fields = target.get('fields', [])
                fields_str = ", ".join(fields[:3])
                if len(fields) > 3:
                    fields_str += "..."
                parts.append(
                    f"{target['layer'].get('name', '?')}: {fields_str}")
            detail = "; ".join(parts)
        elif lookup.get('table'):
            fields = sec.get('fields', [])
            if fields:
                fields_str = ", ".join(fields[:4])
                if len(fields) > 4:
                    fields_str += "..."
            else:
                fields_str = "auto-detect"
            detail = f"{lookup['table'].get('name', '?')} → {fields_str}"
        else:
            detail = ", ".join(sec.get('fields', [])[:4]) or "no fields"
        if sec.get('subdivide_by'):
            detail += f", split by {sec['subdivide_by']}"
        elif lookup.get('group_column'):
            detail += f", grouped by {lookup['group_column']}"
        return detail

    def _refresh_vr_list(self):
        """Rebuild the text sections list widget."""
        self._vr_list.clear()
        for sec in self._project_wide_sections():
            self._vr_list.addItem(
                f"{sec['title']}  ({self._section_detail(sec)})")

    @staticmethod
    def _spatial_layers():
        return sorted(
            (lyr for lyr in QgsProject.instance().mapLayers().values()
             if lyr.type() == QgsMapLayerType.VectorLayer and lyr.isSpatial()),
            key=lambda l: l.name())

    @staticmethod
    def _populated_string_fields(layer, skip_paired=True):
        """Populated string field names of a layer, in field order."""
        from qgis.PyQt.QtCore import QVariant
        names = []
        for i, field in enumerate(layer.fields()):
            try:
                if field.type() != QVariant.String:
                    continue
                if skip_paired and paired_base_field(layer, field.name()):
                    continue
                if field_has_data(layer, i):
                    names.append(field.name())
            except Exception:
                continue
        return names

    def _build_field_tree(self, section=None):
        """Checkbox tree of populated string fields, grouped by layer.

        Same-named fields under different layers are separate items, so
        the selection is layer-explicit.  Returns (tree, checked_targets)
        where checked_targets() yields field_targets dicts.
        """
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setMaximumHeight(180)

        pre_by_layer = {}   # layer id → set of lowercase field names
        pre_names = set()   # legacy name-only pre-check (all layers)
        if section:
            for target in section.get('field_targets') or []:
                pre_by_layer[target['layer'].get('id', '')] = {
                    f.lower() for f in target.get('fields', [])}
            if not pre_by_layer:
                pre_names = {f.lower() for f in section.get('fields', [])}

        for layer in self._spatial_layers():
            fields = self._populated_string_fields(layer)
            if not fields:
                continue
            parent = QTreeWidgetItem([layer.name()])
            parent.setFlags(parent.flags() & ~Qt.ItemIsUserCheckable)
            tree.addTopLevelItem(parent)
            wanted = pre_by_layer.get(layer.id(), pre_names)
            for fname in fields:
                child = QTreeWidgetItem([fname])
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(
                    0, Qt.Checked if fname.lower() in wanted
                    else Qt.Unchecked)
                child.setData(0, Qt.UserRole, layer.id())
                parent.addChild(child)
            parent.setExpanded(True)

        def checked_targets():
            targets = []
            for i in range(tree.topLevelItemCount()):
                parent = tree.topLevelItem(i)
                fields = [parent.child(j).text(0)
                          for j in range(parent.childCount())
                          if parent.child(j).checkState(0) == Qt.Checked]
                if fields:
                    layer_id = parent.child(0).data(0, Qt.UserRole)
                    layer = QgsProject.instance().mapLayer(layer_id)
                    targets.append({
                        'layer': {'id': layer_id,
                                  'name': layer.name() if layer
                                  else parent.text(0)},
                        'fields': fields,
                    })
            return targets

        def set_checked_names(names):
            wanted = {n.lower() for n in names}
            for i in range(tree.topLevelItemCount()):
                parent = tree.topLevelItem(i)
                for j in range(parent.childCount()):
                    child = parent.child(j)
                    child.setCheckState(
                        0, Qt.Checked if child.text(0).lower() in wanted
                        else Qt.Unchecked)

        return tree, checked_targets, set_checked_names

    def _upsert_section(self, new_section, existing=None):
        """Replace an existing section in place, or append."""
        if existing is not None and existing in self._sections:
            self._sections[self._sections.index(existing)] = new_section
        else:
            self._sections.append(new_section)
        self._refresh_vr_list()

    def _edit_lookup_section(self, section=None):
        """Create or edit a lookup-table-backed text section."""
        editing = section is not None
        lookup = (section.get('lookup') or {}) if editing else {}

        tables = [lyr for lyr in
                  sorted(QgsProject.instance().mapLayers().values(),
                         key=lambda l: l.name())
                  if (lyr.type() == QgsMapLayerType.VectorLayer
                      and not lyr.isSpatial())]
        if not tables:
            QMessageBox.information(self, "No Tables",
                                   "No non-spatial lookup tables found in project.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Edit Lookup Section" if editing
                           else "Add Lookup Section")
        dlg.setMinimumWidth(450)
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

        form.addWidget(QLabel("Group by column (optional, e.g. Type):"))
        group_combo = QComboBox()
        form.addWidget(group_combo)

        form.addWidget(QLabel("Section Name:"))
        name_edit = QLineEdit()
        form.addWidget(name_edit)

        form.addWidget(QLabel("Fields to scan (grouped by layer):"))
        tree, checked_targets, set_checked_names = \
            self._build_field_tree(section)
        form.addWidget(tree)

        info_label = QLabel("")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #5F6368; font-size: 10px;")
        form.addWidget(info_label)

        def populate_columns(tbl, preselect=None):
            preselect = preselect or {}
            key_combo.clear()
            val_combo.clear()
            group_combo.clear()
            group_combo.addItem("(None)", None)
            for f in tbl.fields():
                key_combo.addItem(f.name())
                val_combo.addItem(f.name())
                group_combo.addItem(f.name(), f.name())
            auto_key, auto_val = detect_lookup_columns(tbl)
            ki = key_combo.findText(preselect.get('key_column') or auto_key)
            if ki >= 0:
                key_combo.setCurrentIndex(ki)
            vi = val_combo.findText(preselect.get('value_column') or auto_val)
            if vi >= 0:
                val_combo.setCurrentIndex(vi)
            group_pick = preselect.get('group_column')
            if not group_pick and 'group_column' not in preselect:
                # A column named 'Type' is the usual discriminator
                group_pick = next((f.name() for f in tbl.fields()
                                   if f.name().lower() == 'type'), None)
            if group_pick:
                gi = group_combo.findData(group_pick)
                if gi >= 0:
                    group_combo.setCurrentIndex(gi)

        def on_table_changed():
            tbl = QgsProject.instance().mapLayer(table_combo.currentData())
            if not tbl:
                return
            populate_columns(tbl)
            tname = tbl.name()
            # Auto-generate section name: strip "Codes" suffix
            sname = tname
            for suffix in ('Codes', 'codes', 'Code', 'code'):
                if sname.endswith(suffix):
                    sname = sname[:-len(suffix)]
                    break
            name_edit.setText(sname or tname)
            # Auto-check fields matching the table-name pattern
            matched = find_fields_for_table(QgsProject.instance(), tname)
            field_names = sorted(set(fn for _, fn in matched))
            set_checked_names(field_names)
            if field_names:
                info_label.setText(
                    f"Auto-detected {len(matched)} field(s). Adjust the "
                    f"checkboxes — each layer's fields are separate.")
            else:
                info_label.setText(
                    "No fields auto-detected from the table name. "
                    "Check the data columns to scan above.")

        if editing and lookup.get('table'):
            # Prefill from the section; don't auto-overwrite its choices
            table = resolve_layer_ref(QgsProject.instance(), lookup['table'])
            if table is not None:
                ti = table_combo.findData(table.id())
                if ti >= 0:
                    table_combo.setCurrentIndex(ti)
                populate_columns(table, preselect=lookup)
            name_edit.setText(section.get('title', ''))
            table_combo.currentIndexChanged.connect(
                lambda: on_table_changed())
        else:
            table_combo.currentIndexChanged.connect(
                lambda: on_table_changed())
            on_table_changed()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addWidget(buttons)

        if dlg.exec() != QDialog.Accepted:
            return
        tbl = QgsProject.instance().mapLayer(table_combo.currentData())
        if not tbl:
            return
        new_section = normalize_section({
            'id': section.get('id') if editing else None,
            'title': name_edit.text() or tbl.name(),
            'layer': None,
            'field_targets': checked_targets(),
            'display': 'text',
            'lookup': {
                'table': {'id': tbl.id(), 'name': tbl.name()},
                'key_column': key_combo.currentText(),
                'value_column': val_combo.currentText(),
                'group_column': group_combo.currentData(),
            },
        })
        self._upsert_section(new_section, existing=section)

    def _edit_layer_section(self, section=None):
        """Create or edit a section sourced from a layer's own columns.

        For layers whose lookup table is gone (client deliverables): code
        columns are scanned directly, descriptions come from paired
        '<Field>Description' columns, optionally split by a Type field.
        """
        editing = section is not None
        layers = self._spatial_layers()
        if not layers:
            QMessageBox.information(self, "No Layers",
                                   "No spatial vector layers in project.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Edit Layer Section" if editing
                           else "Add Layer Section")
        dlg.setMinimumWidth(450)
        form = QVBoxLayout(dlg)

        form.addWidget(QLabel("Layer:"))
        layer_combo = QComboBox()
        for lyr in layers:
            layer_combo.addItem(layer_display_name(lyr), lyr.id())
        form.addWidget(layer_combo)

        form.addWidget(QLabel(
            "Code fields to scan (↔ shows the paired description column):"))
        fields_list = QListWidget()
        fields_list.setMaximumHeight(150)
        form.addWidget(fields_list)

        form.addWidget(QLabel("Split by field (optional, e.g. Type):"))
        split_combo = QComboBox()
        form.addWidget(split_combo)

        form.addWidget(QLabel("Section Name:"))
        name_edit = QLineEdit()
        form.addWidget(name_edit)

        info_label = QLabel(
            "Descriptions are read from '<Field>Description' columns when "
            "present; otherwise the field values themselves are shown "
            "(useful when values are already 'Code - Description').")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #5F6368; font-size: 10px;")
        form.addWidget(info_label)

        pre_target = None
        if editing and section.get('field_targets'):
            pre_target = section['field_targets'][0]

        def on_layer_changed():
            layer = QgsProject.instance().mapLayer(layer_combo.currentData())
            if not layer:
                return
            fields_list.clear()
            split_combo.clear()
            split_combo.addItem("(None)", None)
            pre_fields = set()
            if pre_target and pre_target['layer'].get('id') == layer.id():
                pre_fields = {f.lower() for f in pre_target['fields']}
            for fname in self._populated_string_fields(layer):
                desc_field = find_paired_description_field(layer, fname)
                label = (f"{fname}  (↔ {desc_field})" if desc_field
                         else fname)
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, fname)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.Checked if fname.lower() in pre_fields
                    else Qt.Unchecked)
                fields_list.addItem(item)
            for field in layer.fields():
                split_combo.addItem(field.name(), field.name())
            if editing and section.get('subdivide_by'):
                si = split_combo.findData(section['subdivide_by'])
                if si >= 0:
                    split_combo.setCurrentIndex(si)
            else:
                type_col = next((f.name() for f in layer.fields()
                                 if f.name().lower() == 'type'), None)
                if type_col:
                    si = split_combo.findData(type_col)
                    if si >= 0:
                        split_combo.setCurrentIndex(si)
            if not editing or not name_edit.text():
                name_edit.setText(layer.name())

        layer_combo.currentIndexChanged.connect(lambda: on_layer_changed())
        if editing:
            name_edit.setText(section.get('title', ''))
            if pre_target:
                li = layer_combo.findData(pre_target['layer'].get('id', ''))
                if li >= 0:
                    layer_combo.setCurrentIndex(li)
        on_layer_changed()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addWidget(buttons)

        if dlg.exec() != QDialog.Accepted:
            return
        layer = QgsProject.instance().mapLayer(layer_combo.currentData())
        if not layer:
            return
        fields = [fields_list.item(i).data(Qt.UserRole)
                  for i in range(fields_list.count())
                  if fields_list.item(i).checkState() == Qt.Checked]
        if not fields:
            QMessageBox.warning(self, "No Fields",
                                "Check at least one code field to scan.")
            return
        new_section = normalize_section({
            'id': section.get('id') if editing else None,
            'title': name_edit.text() or layer.name(),
            'layer': None,
            'field_targets': [{
                'layer': {'id': layer.id(), 'name': layer.name()},
                'fields': fields,
            }],
            'subdivide_by': split_combo.currentData(),
            'display': 'text',
            'lookup': {'pairs': {'suffix': 'Description'}},
        })
        self._upsert_section(new_section, existing=section)

    def _edit_selected_section(self):
        """Open the right editor for the selected text section."""
        row = self._vr_list.currentRow()
        project_wide = self._project_wide_sections()
        if not (0 <= row < len(project_wide)):
            return
        section = project_wide[row]
        lookup = section.get('lookup') or {}
        if lookup.get('table'):
            self._edit_lookup_section(section)
        else:
            self._edit_layer_section(section)

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

        # Per-sheet scale from the mapsheets layer — the mapsheet
        # generator stores it, so layouts shouldn't ask for it again.
        self.useLayerScaleCheckbox = QCheckBox(
            "Use per-sheet scale from the mapsheets layer ('scale' field)")
        self.useLayerScaleCheckbox.setChecked(True)
        self.useLayerScaleCheckbox.setToolTip(
            "Each sheet uses the scale stored in its polygon's 'scale' "
            "attribute (set by the Mapsheet Generator); grid spacing "
            "follows automatically. Sheets without a valid scale fall "
            "back to the manual scale below.")
        self.useLayerScaleCheckbox.toggled.connect(
            self._on_layer_scale_toggled)
        layout.addWidget(self.useLayerScaleCheckbox)

        # Scale settings (manual fallback)
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
        self._on_layer_scale_toggled(self.useLayerScaleCheckbox.isChecked())

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
            "Legend text (placed below legend, styled to match it). "
            "Edit lines to correct it: deletions and rewording apply "
            "to every sheet; added lines are appended.")
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
        preview = self._last_preview_text
        return normalize_config({
            'sections': self._sections,
            'text_mappings': self.legend_text_mappings,
            'legend_unchecked_layers': unchecked,
            'code_table_text_manual': manual,
            'code_table_preview': preview,
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
            self._last_preview_text = config['code_table_preview']
            manual = config['code_table_text_manual']
            box = manual or self._last_preview_text
            if box:
                self.codeTableText.setPlainText(box)
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

    def _on_layer_scale_toggled(self, checked):
        """Per-sheet layer scale supersedes the manual scale combo."""
        self.scaleCombo.setEnabled(not checked)
        self.useScaleCheckbox.setEnabled(not checked)
        self._refresh_grid_interval()

    def _refresh_grid_interval(self):
        """Update the auto-grid display from the current scale, unless overridden."""
        if self.overrideGridCheckbox.isChecked():
            return
        if self.useLayerScaleCheckbox.isChecked():
            self.gridIntervalEdit.setText("auto (per sheet)")
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

        # At least one template is required; a missing orientation falls
        # back to the other template at generate time.
        portrait_path = self.portraitTemplateEdit.text()
        landscape_path = self.landscapeTemplateEdit.text()
        if portrait_path and not os.path.isfile(portrait_path):
            QMessageBox.warning(self, "Error",
                                "Portrait template file does not exist.")
            return False
        if landscape_path and not os.path.isfile(landscape_path):
            QMessageBox.warning(self, "Error",
                                "Landscape template file does not exist.")
            return False
        if not portrait_path and not landscape_path:
            QMessageBox.warning(self, "Error",
                                "Select at least one layout template "
                                "(portrait or landscape).")
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

    # ── Scalebar auto-resize ──────────────────────────────────────────

    # Fallbacks if the template's scalebar box can't be measured sensibly.
    _SCALEBAR_DEFAULT_TARGET_MM = 250.0
    _SCALEBAR_DEFAULT_MAX_MM = 262.0
    _SCALEBAR_LABEL_ALLOWANCE_MM = 12.0   # right-hand label overhang
    _SCALEBAR_SAFETY_MM = 8.0
    _SCALEBAR_MIN_BOX_MM = 20.0           # below this, treat box as untrustworthy

    def _configure_scalebar(self, layout, main_map, effective_scale):
        """Resize the template scalebar's nice-number bars to fill its fixed
        frame at the current map scale, preserving its position and styling.

        No-ops gracefully when there is no scale, no scalebar item, or the
        map CRS is not in metres.
        """
        # Need a numeric scale to compute ground distances.
        if not effective_scale:
            return

        # Locate the scalebar: prefer Item ID, fall back to first instance.
        scalebar = layout.itemById('scalebar')
        if not isinstance(scalebar, QgsLayoutItemScaleBar):
            bars = [i for i in layout.items()
                    if isinstance(i, QgsLayoutItemScaleBar)]
            if not bars:
                QgsMessageLog.logMessage(
                    f"No scalebar item found in template for "
                    f"'{layout.name()}' (set Item ID 'scalebar' in Layout "
                    f"Designer to enable auto-resize); skipping scalebar.",
                    LOG_TAG, Qgis.Warning)
                return
            scalebar = bars[0]

        # The metres maths only holds for a metre-based map CRS, matching the
        # grid block's guard.
        if main_map.crs().mapUnits() != QgsUnitTypes.DistanceMeters:
            QgsMessageLog.logMessage(
                f"Map CRS for '{layout.name()}' is not in metres; "
                f"skipping scalebar auto-resize.", LOG_TAG, Qgis.Warning)
            return

        # Derive target / max drawn lengths from the AUTHORED box width, read
        # now (before any mutation) so it reflects the template, not a
        # previously auto-fitted size.  rect() is in layout mm.
        box_mm = scalebar.rect().width()
        if box_mm is None or box_mm < self._SCALEBAR_MIN_BOX_MM:
            target_bar_mm = self._SCALEBAR_DEFAULT_TARGET_MM
            max_bar_mm = self._SCALEBAR_DEFAULT_MAX_MM
            QgsMessageLog.logMessage(
                f"Scalebar box width for '{layout.name()}' looks invalid "
                f"({box_mm}); using default {target_bar_mm} mm target.",
                LOG_TAG, Qgis.Warning)
        else:
            max_bar_mm = box_mm - self._SCALEBAR_SAFETY_MM
            target_bar_mm = box_mm - self._SCALEBAR_LABEL_ALLOWANCE_MM
            # Clamp into a sane band and below max.
            target_bar_mm = min(max(target_bar_mm, 40.0), max_bar_mm)

        # Compute the nice-number layout (pure, testable).
        result = compute_nice_scalebar(
            int(effective_scale), target_bar_mm, max_bar_mm)
        if result is None:
            QgsMessageLog.logMessage(
                f"Could not compute a nice scalebar for '{layout.name()}' "
                f"at 1:{effective_scale}; leaving template scalebar as-is.",
                LOG_TAG, Qgis.Warning)
            return

        # Apply, units-first then magnitudes then counts, then one update().
        if result['unit_label'] == 'km':
            distance_unit = QgsUnitTypes.DistanceKilometers
        else:
            distance_unit = QgsUnitTypes.DistanceMeters

        scalebar.setLinkedMap(main_map)
        scalebar.setUnits(distance_unit)
        scalebar.setUnitLabel(result['unit_label'])
        scalebar.setMapUnitsPerScaleBarUnit(result['map_units_per_bar_unit'])
        scalebar.setUnitsPerSegment(result['units_per_segment'])
        scalebar.setNumberOfSegments(result['n_segments'])
        scalebar.setNumberOfSegmentsLeft(0)
        scalebar.update()

        QgsMessageLog.logMessage(
            f"Scalebar for '{layout.name()}' at 1:{effective_scale}: "
            f"{result['n_segments']} x {result['units_per_segment']:g} "
            f"{result['unit_label']} (~{result['drawn_mm']:.1f} mm drawn).",
            LOG_TAG, Qgis.Info)

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

    @staticmethod
    def _text_block_font(layout):
        """Font for the text block: the legend's symbol-label font in
        italic (headings stay distinct via UPPERCASE).  Falls back to
        MS Shell Dlg 2 8pt."""
        from qgis.core import QgsLegendStyle
        from qgis.PyQt.QtGui import QFont

        font = None
        legends = [i for i in layout.items()
                   if isinstance(i, QgsLayoutItemLegend)]
        if legends:
            try:
                font = legends[0].style(
                    QgsLegendStyle.SymbolLabel).textFormat().toQFont()
            except Exception:
                font = None

        if font is None:
            font = QFont("MS Shell Dlg 2")
        if font.pointSizeF() <= 0:
            font.setPointSizeF(8)
        font = QFont(font)
        font.setItalic(True)
        font.setBold(False)
        return font

    def _place_text_block(self, layout, section_lines):
        """Place the legend text as one single-column label.

        ModeFont keeps the text vector on export; the whole block uses
        the legend-matched italic font with UPPERCASE headings.  A
        template 'code_table' label, when present, is reused in place;
        otherwise the label sits below the finalised legend.
        """
        from qgis.core import QgsLayoutPoint, QgsLayoutSize

        text = text_from_section_lines(section_lines)
        if not text:
            return

        font = self._text_block_font(layout)
        n_lines = text.count('\n') + 1
        pt = font.pointSizeF() if font.pointSizeF() > 0 else 8
        height = n_lines * pt * 1.35 * (25.4 / 72.0) + 2

        # Reuse the template item so users control placement
        for item in layout.items():
            if (isinstance(item, QgsLayoutItemLabel)
                    and item.id() == 'code_table'):
                item.setMode(QgsLayoutItemLabel.ModeFont)
                item.setFont(font)
                item.setText(text)
                QgsMessageLog.logMessage(
                    "Legend text placed in template 'code_table' item.",
                    LOG_TAG, Qgis.Info)
                return

        label = QgsLayoutItemLabel(layout)
        label.setMode(QgsLayoutItemLabel.ModeFont)
        label.setId('code_table')
        label.setFont(font)
        label.setText(text)

        page = layout.pageCollection().page(0)
        page_size = (layout.convertToLayoutUnits(page.pageSize())
                     if page else None)
        legends = [i for i in layout.items()
                   if isinstance(i, QgsLayoutItemLegend)]
        if legends:
            legend = legends[0]
            lpos = layout.convertToLayoutUnits(legend.positionWithUnits())
            lsize = layout.convertToLayoutUnits(legend.sizeWithUnits())
            x = lpos.x()
            y = lpos.y() + lsize.height() + 3
            width = max(lsize.width(), 80)
        elif page_size is not None:
            x = 10
            y = page_size.height() * 0.6
            width = max(page_size.width() * 0.25, 80)
        else:
            x, y, width = 10, 250, 120

        label.attemptMove(QgsLayoutPoint(x, y, layout.units()))
        label.attemptResize(QgsLayoutSize(width, height, layout.units()))
        layout.addLayoutItem(label)

        if page_size is not None and y + height > page_size.height():
            QgsMessageLog.logMessage(
                "Legend text block overflows the page. Add a 'code_table' "
                "label item to the template to control placement.",
                LOG_TAG, Qgis.Warning)

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
        """Load lookups for each section: (desc_maps, group_maps).

        desc_maps: {section_id: {code: description}}.  Sources in
        increasing precedence: the section's configured lookup (named
        table / inline map), code→description mappings from the fields'
        editor widgets (ValueRelation/ValueMap dropdowns), then paired
        '<Field>Description' columns on the data layers themselves.
        group_maps: {section_id: {code: group}} from the lookup table's
        discriminator column (e.g. 'Type'), when configured.
        """
        project = QgsProject.instance()
        desc_maps = {}
        group_maps = {}
        for section in sections:
            base = {}
            groups = {}
            lookup = section.get('lookup')
            if lookup and lookup.get('map'):
                base = dict(lookup['map'])
            elif lookup and lookup.get('table'):
                table = resolve_layer_ref(project, lookup['table'])
                if table is None:
                    QgsMessageLog.logMessage(
                        f"Lookup table '{lookup['table'].get('name')}' not "
                        f"found for section '{section['title']}'.",
                        LOG_TAG, Qgis.Warning)
                else:
                    base, groups = load_lookup_table(
                        table, lookup['key_column'], lookup['value_column'],
                        lookup.get('group_column'))

            merged = dict(base)
            merged.update(collect_widget_lookups(project, section))
            merged.update(collect_paired_lookups(project, section))
            if merged:
                desc_maps[section['id']] = merged
            if groups:
                group_maps[section['id']] = groups
        return desc_maps, group_maps

    @staticmethod
    def _apply_lookup_grouping(sections, scan_results, group_maps):
        """Split flat scan results into {group: [values]} for sections
        whose lookup has a discriminator column.  The dict form renders
        with per-group sub-headers (e.g. Alteration: / Weathering:)."""
        if not group_maps:
            return scan_results
        grouped_results = dict(scan_results)
        for section in sections:
            sid = section['id']
            groups = group_maps.get(sid)
            data = grouped_results.get(sid)
            if groups and isinstance(data, list) and data:
                grouped_results[sid] = group_values_by_lookup(data, groups)
        return grouped_results

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
        lookup_maps, group_maps = self._load_lookup_maps(sections)
        scan_results = self._apply_lookup_grouping(
            sections, scan_results, group_maps)

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

        # Carry the user's pending edits (corrections) across re-previews:
        # derive them against the old snapshot, re-apply to the new text.
        headings = [(s['title'].upper() or 'LEGEND') for s in sections]
        old_overrides = derive_text_overrides(
            self._last_preview_text,
            self.codeTableText.toPlainText().strip(), headings)

        section_lines = build_text_section_lines(
            sections, scan_results, lookup_maps, extra_unmatched)
        snapshot = text_from_section_lines(section_lines)
        displayed = text_from_section_lines(
            apply_text_overrides(section_lines, old_overrides))

        self.codeTableText.setPlainText(displayed)
        self._last_preview_text = snapshot
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
        """Export layouts to selected formats (delegates to the shared helper)."""
        self.statusLabel.setText("Exporting layouts...")
        self.progressBar.setMaximum(len(layout_names))
        self.progressBar.setValue(0)

        def _progress(done, total):
            self.progressBar.setValue(done)
            QApplication.processEvents()

        return export_layouts_to_formats(
            layout_names,
            self.outputDirEdit.text(),
            dpi=self.dpiSpin.value(),
            do_pdf=self.exportPdfCheckbox.isChecked(),
            do_tiff=self.exportTiffCheckbox.isChecked(),
            do_png=self.exportPngCheckbox.isChecked(),
            log=lambda m: self.statusLabel.setText(m),
            progress=_progress)

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

            # Per-sheet scale from the mapsheets layer's 'scale' attribute
            # (written by the Mapsheet Generator) — supersedes the combo.
            use_layer_scale = (
                self.useLayerScaleCheckbox.isChecked()
                and polygon_layer.fields().indexOf('scale') >= 0)
            if (self.useLayerScaleCheckbox.isChecked()
                    and not use_layer_scale):
                QgsMessageLog.logMessage(
                    "Mapsheets layer has no 'scale' field — using the "
                    "manual scale setting instead.", LOG_TAG, Qgis.Warning)

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
            lookup_maps, group_maps = (self._load_lookup_maps(sections)
                                       if sections else ({}, {}))
            per_sheet = self.perSheetCheckbox.isChecked()
            filter_by_map = self.filterByMapCheckbox.isChecked()
            sheet_crs = polygon_layer.crs()
            project_wide_results = None
            if sections and not per_sheet:
                project_wide_results = scan_sections_for_sheet(
                    QgsProject.instance(), sections)

            # Edits to the preview box are read as per-entry corrections
            # applied on every sheet: deleted lines exclude that entry,
            # reworded lines relabel it, added lines are appended — while
            # each sheet still shows only its own codes.
            box_text = self.codeTableText.toPlainText().strip()
            section_headings = [(s['title'].upper() or 'LEGEND')
                                for s in sections]
            text_overrides = derive_text_overrides(
                self._last_preview_text, box_text, section_headings)

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

                    # Choose template based on orientation; fall back to
                    # the other template when only one is provided.
                    is_landscape = (orientation == 'Landscape')
                    template_path = (landscape_template_path if is_landscape
                                     else portrait_template_path)
                    if not template_path:
                        template_path = (portrait_template_path
                                         or landscape_template_path)
                        QgsMessageLog.logMessage(
                            f"No {orientation.lower()} template set for "
                            f"'{polygon_name}' — using the "
                            f"{'portrait' if is_landscape else 'landscape'} "
                            f"template instead.", LOG_TAG, Qgis.Warning)

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

                    # Set map extent / scale.  The sheet's own 'scale'
                    # attribute wins; the manual combo is the fallback.
                    feature_scale = None
                    if use_layer_scale:
                        feature_scale = parse_scale_text(feature['scale'])
                        if feature_scale is None:
                            QgsMessageLog.logMessage(
                                f"Sheet '{polygon_name}' has no valid "
                                f"'scale' value — using the manual scale "
                                f"setting.", LOG_TAG, Qgis.Warning)
                    effective_scale = feature_scale or (
                        scale_denominator if use_custom_scale else None)

                    if effective_scale:
                        center_x = (bbox.xMinimum() + bbox.xMaximum()) / 2
                        center_y = (bbox.yMinimum() + bbox.yMaximum()) / 2

                        map_width_mm = main_map.rect().width()
                        map_height_mm = main_map.rect().height()

                        map_width_mapunits = (map_width_mm * effective_scale) / 1000
                        map_height_mapunits = (map_height_mm * effective_scale) / 1000

                        new_extent = QgsRectangle(
                            center_x - map_width_mapunits / 2,
                            center_y - map_height_mapunits / 2,
                            center_x + map_width_mapunits / 2,
                            center_y + map_height_mapunits / 2
                        )

                        main_map.setExtent(new_extent)
                        main_map.setScale(effective_scale)
                    else:
                        main_map.setExtent(bbox_buffered)

                    # Auto-set grid X/Y interval from the sheet's scale (or
                    # override).  The interval is metres, so skip non-metre
                    # CRSes rather than writing metres into degree units.
                    if self.overrideGridCheckbox.isChecked():
                        grid_interval = self.getGridInterval()
                    elif feature_scale:
                        grid_interval = feature_scale / 10.0
                    else:
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

                    # Auto-resize the scalebar's nice-number bars to the
                    # template frame at this map's scale.
                    self._configure_scalebar(layout, main_map, effective_scale)

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
                        scan_results = self._apply_lookup_grouping(
                            sections, scan_results, group_maps)

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

                    # Build the legend text block, apply the user's
                    # corrections, and place it as a single label.
                    section_lines = apply_text_overrides(
                        build_text_section_lines(
                            sections, scan_results, lookup_maps, unmatched),
                        text_overrides)
                    if section_lines:
                        self._place_text_block(layout, section_lines)

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
    # Singleton: reuse the existing panel only when it is alive, visible
    # AND built from this module.  After a plugin reload the old panel's
    # class is a different class object — keeping it would show stale UI,
    # so tear it down and build a fresh one from the reloaded code.
    panel = getattr(iface, '_layout_panel', None)
    if panel is not None:
        try:
            if (type(panel) is MapLayoutGeneratorPanel
                    and panel.isVisible()):
                panel.raise_()
                panel.activateWindow()
                return
            iface.removeDockWidget(panel)
            panel.close()
            panel.deleteLater()
        except RuntimeError:
            pass  # C++ object already deleted
        iface._layout_panel = None

    panel = create_map_layout_generator_panel()
    iface._layout_panel = panel
    panel.destroyed.connect(lambda: setattr(iface, '_layout_panel', None))
