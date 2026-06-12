"""
Hardcode Data & Update Legends — combined dialog.

Replaces the separate "Hardcode Data (Backup Fields)" and "Update Legend
Columns" tools. One Generate Preview pass per layer produces a data-quality
table covering every column, a unified change list (standard fields, field
copies, legend lookups, UUID fills) and a UUID duplicate report. Commit
applies exactly the previewed changes.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QLineEdit, QRadioButton, QButtonGroup, QComboBox, QGroupBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QSplitter,
    QProgressBar, QMessageBox, QApplication, QWidget, QHeaderView,
)
from qgis.core import QgsProject

try:
    from ..layer_select import (layer_candidates, populate_layer_combo,
                                combo_current_layer)
except ImportError:
    from layer_select import (layer_candidates, populate_layer_combo,
                              combo_current_layer)

try:
    from .. import plugin_theme as theme
except ImportError:
    import plugin_theme as theme

try:
    from ..ui_scaling import get_scale_manager
except ImportError:
    from ui_scaling import get_scale_manager

try:
    from ..recode_workflow.widgets import CollapsibleSection
except ImportError:
    from recode_workflow.widgets import CollapsibleSection

from .analysis import (
    LAYER_CONFIGS, MODE_EMPTY_ONLY, MODE_OVERWRITE_ALL, MODE_SELECTED_ONLY,
    SOURCE_STANDARD, SOURCE_COPY, SOURCE_GEOMETRY, SOURCE_LEGEND, SOURCE_UUID,
    analyze_layer, apply_layer_report, is_empty,
)

SKIP_LAYER_TEXT = "— skip this layer —"
NO_LOOKUP_TEXT = "— none —"
CHANGES_DISPLAY_CAP = 200

QUALITY_HEADERS = ["Field", "Type", "Filled", "Missing", "% Complete",
                   "Distinct", "Sample Values", "Notes"]
CHANGES_HEADERS = ["Field", "Feature ID", "Current", "New", "Source"]

# Lookup tables the legend configs reference (combo key -> auto-match name)
LOOKUP_TABLES = ['FieldNotebookCodes', 'BasemapCodes']


def _display(value):
    return '' if is_empty(value) else str(value)


class HardcodeDataDialog(QDialog):
    """Tabbed preview-and-commit dialog for the combined tool."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scale = get_scale_manager()
        self.setWindowTitle("Hardcode Data & Update Legends")
        self.setMinimumSize(*self.scale.dialog_size(1100, 760))

        # Snapshot state captured at preview time, applied at commit time
        self._reports = {}          # config key -> LayerReport
        self._snapshot_layers = {}  # config key -> QgsVectorLayer

        self._setup_ui()

    # ── UI construction ────────────────────────────────────────────

    def _setup_ui(self):
        s = self.scale
        layout = QVBoxLayout(self)
        layout.setSpacing(s.spacing(8))

        setup_row = QHBoxLayout()
        setup_row.setSpacing(s.spacing(8))

        left_col = QVBoxLayout()
        left_col.addWidget(self._create_layers_group())
        left_col.addWidget(self._create_lookup_group())
        setup_row.addLayout(left_col, 1)

        right_col = QVBoxLayout()
        right_col.addWidget(self._create_metadata_group())
        right_col.addWidget(self._create_mode_group())
        right_col.addStretch()
        setup_row.addLayout(right_col, 1)

        layout.addLayout(setup_row)

        self.preview_btn = QPushButton("Generate Preview")
        self.preview_btn.setStyleSheet(theme.action_button_style(primary=True))
        self.preview_btn.clicked.connect(self._generate_preview)
        layout.addWidget(self.preview_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget, 1)

        button_row = QHBoxLayout()
        self.commit_btn = QPushButton("Commit Changes")
        self.commit_btn.setStyleSheet(theme.action_button_style(primary=True))
        self.commit_btn.setEnabled(False)
        self.commit_btn.clicked.connect(self._commit_changes)
        cancel_btn = QPushButton("Close")
        cancel_btn.setStyleSheet(theme.action_button_style(primary=False))
        cancel_btn.clicked.connect(self.reject)
        button_row.addStretch()
        button_row.addWidget(self.commit_btn)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)

    def _create_layers_group(self):
        group = QGroupBox("Target Layers")
        group.setStyleSheet(theme.group_box_style())
        grid = QGridLayout(group)

        self.layer_combos = {}
        candidates = layer_candidates()
        for row, layer_name in enumerate(LAYER_CONFIGS):
            grid.addWidget(QLabel(f"{layer_name}:"), row, 0)
            combo = QComboBox()
            populate_layer_combo(combo, candidates,
                                 placeholder=SKIP_LAYER_TEXT,
                                 target_name=layer_name)
            combo.currentIndexChanged.connect(self._invalidate_preview)
            grid.addWidget(combo, row, 1)
            self.layer_combos[layer_name] = combo
        grid.setColumnStretch(1, 1)
        return group

    def _create_lookup_group(self):
        group = QGroupBox("Lookup Tables (for legend codes)")
        group.setStyleSheet(theme.group_box_style())
        grid = QGridLayout(group)

        self.lookup_combos = {}
        lookup_layers = layer_candidates(required_fields=["Code", "Description"])
        for row, table_name in enumerate(LOOKUP_TABLES):
            grid.addWidget(QLabel(f"{table_name}:"), row, 0)
            combo = QComboBox()
            populate_layer_combo(combo, lookup_layers,
                                 placeholder=NO_LOOKUP_TEXT,
                                 target_name=table_name)
            combo.currentIndexChanged.connect(self._invalidate_preview)
            grid.addWidget(combo, row, 1)
            self.lookup_combos[table_name] = combo
        grid.setColumnStretch(1, 1)

        hint = QLabel("Tables need 'Code' and 'Description' fields. "
                      "Legend/Description values are filled from these.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; "
                           f"font-size: {self.scale.font_size(10)}px;")
        grid.addWidget(hint, len(LOOKUP_TABLES), 0, 1, 2)
        return group

    def _create_metadata_group(self):
        group = QGroupBox("Project Metadata")
        group.setStyleSheet(theme.group_box_style())
        grid = QGridLayout(group)

        grid.addWidget(QLabel("Project ID:"), 0, 0)
        self.project_id_edit = QLineEdit()
        self.project_id_edit.textChanged.connect(self._invalidate_preview)
        grid.addWidget(self.project_id_edit, 0, 1)

        grid.addWidget(QLabel("Mapped Scale:"), 1, 0)
        self.mapped_scale_edit = QLineEdit()
        self.mapped_scale_edit.setPlaceholderText("e.g., 1:2500")
        self.mapped_scale_edit.textChanged.connect(self._invalidate_preview)
        grid.addWidget(self.mapped_scale_edit, 1, 1)

        grid.addWidget(QLabel("Project CRS:"), 2, 0)
        self.crs_label = QLabel(QgsProject.instance().crs().authid())
        self.crs_label.setStyleSheet(
            f"font-weight: bold; color: {theme.PRIMARY_DARKER};")
        grid.addWidget(self.crs_label, 2, 1)

        crs_note = QLabel("MappedCRS records each layer's own CRS — the CRS "
                          "its geometry and coordinates are stored in. A "
                          "warning is shown if it differs from the project "
                          "CRS.")
        crs_note.setWordWrap(True)
        crs_note.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; "
                               f"font-size: {self.scale.font_size(10)}px;")
        grid.addWidget(crs_note, 3, 0, 1, 2)
        grid.setColumnStretch(1, 1)
        return group

    def _create_mode_group(self):
        group = QGroupBox("Update Mode")
        group.setStyleSheet(theme.group_box_style())
        vbox = QVBoxLayout(group)

        self.mode_group = QButtonGroup(self)
        rb_empty = QRadioButton("Update empty cells only (preserves existing data)")
        rb_empty.setChecked(True)
        rb_all = QRadioButton("Overwrite all cells (replaces existing data)")
        rb_selected = QRadioButton("Update selected features only (empty cells)")
        for rb, mode in ((rb_empty, MODE_EMPTY_ONLY),
                         (rb_all, MODE_OVERWRITE_ALL),
                         (rb_selected, MODE_SELECTED_ONLY)):
            self.mode_group.addButton(rb, mode)
            rb.toggled.connect(self._invalidate_preview)
            vbox.addWidget(rb)

        note = QLabel("UUIDs are only ever filled where missing — existing "
                      "UUIDs are never overwritten. Duplicate UUIDs are "
                      "reported but not changed.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; "
                           f"font-size: {self.scale.font_size(10)}px;")
        vbox.addWidget(note)
        return group

    # ── Preview ────────────────────────────────────────────────────

    def _invalidate_preview(self, *_args):
        """Any input change makes the current preview stale."""
        if self._reports:
            self._reports = {}
            self._snapshot_layers = {}
            self.tab_widget.clear()
        self.commit_btn.setEnabled(False)

    def _generate_preview(self):
        if not self.project_id_edit.text().strip():
            QMessageBox.warning(self, "Validation Error",
                                "Project ID is required.")
            return
        if not self.mapped_scale_edit.text().strip():
            QMessageBox.warning(self, "Validation Error",
                                "Mapped Scale is required.")
            return

        selected = {name: combo_current_layer(combo)
                    for name, combo in self.layer_combos.items()}
        selected = {name: lyr for name, lyr in selected.items()
                    if lyr is not None}
        if not selected:
            QMessageBox.warning(self, "No Layers Selected",
                                "Select at least one target layer.")
            return

        lookups = {name: combo_current_layer(combo)
                   for name, combo in self.lookup_combos.items()}
        mode = self.mode_group.checkedId()
        project_id = self.project_id_edit.text().strip()
        mapped_scale = self.mapped_scale_edit.text().strip()
        project_crs = QgsProject.instance().crs().authid()

        self.tab_widget.clear()
        self._reports = {}
        self._snapshot_layers = dict(selected)

        total_features = sum(lyr.featureCount() for lyr in selected.values())
        self.progress_bar.setRange(0, max(total_features, 1))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.preview_btn.setEnabled(False)
        try:
            offset = 0
            for layer_name, layer in selected.items():
                config = LAYER_CONFIGS[layer_name]
                lookup_layer = None
                if config.get('legend'):
                    lookup_layer = lookups.get(config['legend']['lookup_table'])

                def on_progress(done, base=offset):
                    self.progress_bar.setValue(base + done)
                    QApplication.processEvents()

                report = analyze_layer(
                    layer, config,
                    project_id=project_id, mapped_scale=mapped_scale,
                    project_crs=project_crs, mode=mode,
                    lookup_layer=lookup_layer, progress_cb=on_progress)
                self._reports[layer_name] = report
                offset += layer.featureCount()

                tab = self._build_layer_tab(layer_name, report, mode)
                short_name = layer_name.split(' - ')[-1]
                self.tab_widget.addTab(tab, short_name)
        except Exception as exc:
            QMessageBox.critical(self, "Preview Error",
                                 f"Error generating preview:\n{exc}")
            self._invalidate_preview()
            return
        finally:
            self.progress_bar.setVisible(False)
            self.preview_btn.setEnabled(True)

        total_changes = sum(len(r.changes) for r in self._reports.values())
        self.commit_btn.setEnabled(total_changes > 0)
        if total_changes == 0:
            self._show_no_changes_message()

    def _show_no_changes_message(self):
        msg = "No changes are needed — all values are already up to date.\n"
        missing_lines = []
        for layer_name, report in self._reports.items():
            if report.missing_codes:
                lookup = LAYER_CONFIGS[layer_name]['legend']['lookup_table']
                codes = ', '.join(report.missing_codes[:10])
                extra = (f" … and {len(report.missing_codes) - 10} more"
                         if len(report.missing_codes) > 10 else "")
                missing_lines.append(
                    f"• {layer_name}: codes missing from '{lookup}': "
                    f"{codes}{extra}")
        if missing_lines:
            msg += ("\nSome codes were not found in the lookup tables — add "
                    "them and re-preview:\n" + "\n".join(missing_lines))
        QMessageBox.information(self, "No Changes", msg)

    # ── Per-layer tab ──────────────────────────────────────────────

    def _build_layer_tab(self, layer_name, report, mode):
        s = self.scale
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setSpacing(s.spacing(6))

        vbox.addWidget(self._build_summary_label(report, mode))

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._build_quality_table(report))

        bottom = QWidget()
        bottom_lay = QVBoxLayout(bottom)
        bottom_lay.setContentsMargins(0, 0, 0, 0)
        bottom_lay.setSpacing(s.spacing(4))

        shown = min(len(report.changes), CHANGES_DISPLAY_CAP)
        if len(report.changes) > CHANGES_DISPLAY_CAP:
            cap_text = (f"Changes — showing first {shown} of "
                        f"{len(report.changes)} (all will be applied)")
        elif report.changes:
            cap_text = f"Changes — {len(report.changes)}"
        else:
            cap_text = "Changes — none"
        cap_label = QLabel(cap_text)
        cap_label.setStyleSheet(
            f"font-weight: bold; color: {theme.TEXT_PRIMARY};")
        bottom_lay.addWidget(cap_label)
        bottom_lay.addWidget(self._build_changes_table(report), 1)

        if report.uuid_report and report.uuid_report.duplicates:
            bottom_lay.addWidget(self._build_duplicates_section(report))
        if report.missing_codes:
            bottom_lay.addWidget(self._build_missing_codes_section(
                layer_name, report))

        splitter.addWidget(bottom)
        splitter.setSizes([s.dimension(300), s.dimension(320)])
        vbox.addWidget(splitter, 1)
        return container

    def _build_summary_label(self, report, mode):
        scope = {MODE_EMPTY_ONLY: "all features, empty cells",
                 MODE_OVERWRITE_ALL: "all features, overwrite",
                 MODE_SELECTED_ONLY:
                     f"{report.scoped_feature_count} selected features"
                 }.get(mode, "")
        counts = report.counts_by_source()
        parts = [f"<b>{report.feature_count}</b> features (scope: {scope})"]
        for source in (SOURCE_STANDARD, SOURCE_COPY, SOURCE_GEOMETRY,
                       SOURCE_LEGEND, SOURCE_UUID):
            if counts.get(source):
                parts.append(f"<b>{counts[source]}</b> {source.lower()}")
        if not report.changes:
            parts.append("no changes")

        uuid_rep = report.uuid_report
        if uuid_rep and uuid_rep.duplicates:
            parts.append(
                f"<span style='color: {theme.ACCENT_PRESSED};'><b>"
                f"{len(uuid_rep.duplicates)}</b> duplicate UUID values "
                "(report only)</span>")
        if report.missing_codes:
            parts.append(
                f"<span style='color: {theme.ACCENT_PRESSED};'><b>"
                f"{len(report.missing_codes)}</b> missing legend codes</span>")

        text = " · ".join(parts)
        for note in report.notes + (
                [report.legend_skipped_reason] if report.legend_skipped_reason
                else []):
            text += (f"<br><span style='color: {theme.TEXT_SECONDARY};'>"
                     f"⚠ {note}</span>")

        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        label.setStyleSheet(
            f"background-color: {theme.BG_PRIMARY}; "
            f"border: 1px solid {theme.BORDER}; "
            f"border-radius: {self.scale.dimension(4)}px; "
            f"padding: {self.scale.dimension(6)}px;")
        return label

    def _build_quality_table(self, report):
        table = QTableWidget(len(report.column_stats), len(QUALITY_HEADERS))
        table.setHorizontalHeaderLabels(QUALITY_HEADERS)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)

        highlight = QColor(theme.SELECTED_BG)
        warn_colour = QColor(theme.ACCENT_PRESSED)
        for row, stats in enumerate(report.column_stats):
            distinct = (f"{stats.distinct_count}+" if stats.distinct_capped
                        else str(stats.distinct_count))
            values = [stats.name, stats.type_name, str(stats.filled),
                      str(stats.missing), f"{stats.pct_complete:.0f}%",
                      distinct, ", ".join(stats.sample_values),
                      "  |  ".join(stats.notes)]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if stats.will_modify or stats.is_new:
                    item.setBackground(highlight)
                if col == len(values) - 1 and "duplicate" in value:
                    item.setForeground(warn_colour)
                if stats.missing and col == 3:
                    item.setForeground(warn_colour)
                table.setItem(row, col, item)

        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.Interactive)
        return table

    def _build_changes_table(self, report):
        shown = report.changes[:CHANGES_DISPLAY_CAP]
        table = QTableWidget(len(shown), len(CHANGES_HEADERS))
        table.setHorizontalHeaderLabels(CHANGES_HEADERS)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)

        highlight = QColor(theme.SELECTED_BG)
        for row, change in enumerate(shown):
            cells = [change.field_name, str(change.feature_id),
                     _display(change.current_value),
                     _display(change.new_value), change.source]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if col == 3:
                    item.setBackground(highlight)
                table.setItem(row, col, item)

        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _build_duplicates_section(self, report):
        uuid_rep = report.uuid_report
        section = CollapsibleSection(
            f"Duplicate UUIDs in '{uuid_rep.field_name}' (report only — "
            "not modified)", expanded=False)
        section.set_status("warning",
                           f"{len(uuid_rep.duplicates)} values")
        text = QTextEdit()
        text.setReadOnly(True)
        lines = [f"{value}  —  feature ids: "
                 f"{', '.join(str(fid) for fid in fids)}"
                 for value, fids in sorted(uuid_rep.duplicates.items())]
        text.setPlainText("\n".join(lines))
        text.setMaximumHeight(self.scale.dimension(120))
        section.content_layout().addWidget(text)
        return section

    def _build_missing_codes_section(self, layer_name, report):
        lookup = LAYER_CONFIGS[layer_name]['legend']['lookup_table']
        section = CollapsibleSection(
            f"Missing legend codes (not in '{lookup}')", expanded=False)
        section.set_status("warning", f"{len(report.missing_codes)} codes")
        label = QLabel(
            "These codes were found in the data but have no entry in the "
            f"lookup table, so their legend cannot be filled:\n\n"
            f"{', '.join(report.missing_codes)}\n\n"
            "Add them to the lookup table and re-generate the preview.")
        label.setWordWrap(True)
        section.content_layout().addWidget(label)
        return section

    # ── Commit ─────────────────────────────────────────────────────

    def _commit_changes(self):
        reports = {name: r for name, r in self._reports.items() if r.changes}
        if not reports:
            QMessageBox.warning(self, "No Preview",
                                "Generate a preview first.")
            return

        lines = [f"• {name}: {len(r.changes)} changes"
                 + (f" ({len(r.fields_to_create)} new fields)"
                    if r.fields_to_create else "")
                 for name, r in reports.items()]
        reply = QMessageBox.question(
            self, "Confirm Changes",
            "Apply all previewed changes?\n\n" + "\n".join(lines)
            + "\n\nThis modifies your data and cannot be easily undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        total_changes = sum(len(r.changes) for r in reports.values())
        self.progress_bar.setRange(0, max(total_changes, 1))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.commit_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)

        results = []
        total_applied = 0
        try:
            offset = 0
            for layer_name, report in reports.items():
                layer = self._snapshot_layers.get(layer_name)
                if (layer is None or
                        QgsProject.instance().mapLayer(report.layer_id) is None):
                    results.append(f"❌ {layer_name}: layer no longer in "
                                   "project — skipped")
                    continue

                def on_progress(done, base=offset):
                    self.progress_bar.setValue(base + done)
                    QApplication.processEvents()

                applied, errors = apply_layer_report(layer, report,
                                                     progress_cb=on_progress)
                offset += len(report.changes)
                total_applied += applied
                if errors:
                    results.append(f"❌ {layer_name}: {applied} applied; "
                                   + "; ".join(errors))
                else:
                    results.append(f"✅ {layer_name}: {applied} changes "
                                   "committed")
        finally:
            self.progress_bar.setVisible(False)
            self.preview_btn.setEnabled(True)

        QMessageBox.information(
            self, "Commit Complete",
            f"Total changes applied: {total_applied}\n\n" + "\n".join(results))
        # Force a fresh preview before any further commit
        self._invalidate_preview()
