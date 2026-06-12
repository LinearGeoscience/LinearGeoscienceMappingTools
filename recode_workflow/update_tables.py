"""
Page 1: Update Code Tables – wizard page widget.

New CSV-based tool for modifying non-spatial code/lookup tables in the project.
Users can export a template CSV, import a CSV, and apply append/replace operations.
"""

import os

import pandas as pd
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QRadioButton, QButtonGroup, QMessageBox,
    QFileDialog, QScrollArea, QFrame,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal, QVariant
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsWkbTypes, QgsFeature,
    QgsMessageLog, Qgis,
)

from .widgets import CollapsibleSection, DataPreviewTable, TableComparisonWidget

try:
    from ..ui_scaling import get_scale_manager
except ImportError:
    from ui_scaling import get_scale_manager

try:
    from .. import plugin_theme as theme
except ImportError:
    import plugin_theme as theme

from .constants import LOG_TAG

try:
    from ..layer_select import layer_display_name
except ImportError:
    from layer_select import layer_display_name


def _log(msg, level=Qgis.Info):
    QgsMessageLog.logMessage(msg, LOG_TAG, level)


def _layer_to_df(layer):
    """Convert a QgsVectorLayer's features to a pandas DataFrame."""
    field_names = [f.name() for f in layer.fields()]
    rows = []
    for feat in layer.getFeatures():
        row = {}
        for name in field_names:
            val = feat[name]
            # Convert QVariant NULL to None
            if isinstance(val, QVariant) and val.isNull():
                val = None
            row[name] = val
        rows.append(row)
    return pd.DataFrame(rows, columns=field_names)


def _get_non_spatial_layers():
    """Return a list of non-spatial (NullGeometry) vector layers in the project."""
    project = QgsProject.instance()
    result = []
    for layer_id, layer in project.mapLayers().items():
        if (isinstance(layer, QgsVectorLayer)
                and layer.geometryType() == QgsWkbTypes.NullGeometry):
            result.append(layer)
    result.sort(key=lambda l: l.name())
    return result


# ── UpdateTablesPage ─────────────────────────────────────────────

class UpdateTablesPage(QWidget):
    """Wizard page for CSV-based code table updates."""

    status_changed = pyqtSignal(str)
    log_message = pyqtSignal(str)

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.scale = get_scale_manager()
        self._target_layer = None
        self._current_df = None
        self._incoming_df = None
        self._preview_df = None
        self._csv_path = None
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

        # ── Target Table Section ──────────────────────────────────
        target_section = CollapsibleSection("Target Table", expanded=True)
        tl = target_section.content_layout()

        combo_row = QHBoxLayout()
        combo_row.setSpacing(s.dimension(8))

        self._table_combo = QComboBox()
        self._table_combo.setMinimumWidth(s.dimension(200))
        self._table_combo.setStyleSheet(
            f"QComboBox {{ font-size: {s.font_size(11)}px; font-family: {theme.FONT_FAMILY}; "
            f"padding: {s.dimension(4)}px; border: 1px solid {theme.BORDER}; "
            f"border-radius: {s.dimension(4)}px; background-color: {theme.BG_CARD}; }}"
        )
        self._table_combo.currentTextChanged.connect(self._on_table_selected)
        combo_row.addWidget(self._table_combo, 1)

        btn_refresh = QPushButton("Refresh")
        btn_refresh.setStyleSheet(theme.action_button_style(primary=False))
        btn_refresh.clicked.connect(self._populate_table_combo)
        combo_row.addWidget(btn_refresh)

        btn_export = QPushButton("Export Template CSV")
        btn_export.setStyleSheet(theme.action_button_style(primary=False))
        btn_export.clicked.connect(self._on_export_template)
        combo_row.addWidget(btn_export)

        tl.addLayout(combo_row)
        layout.addWidget(target_section)

        # ── CSV Import Section ────────────────────────────────────
        csv_section = CollapsibleSection("CSV Import", expanded=True)
        cl = csv_section.content_layout()

        file_row = QHBoxLayout()
        file_row.setSpacing(s.dimension(8))

        self._csv_label = QLabel("No file selected")
        self._csv_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {s.font_size(11)}px; "
            f"font-family: {theme.FONT_FAMILY};"
        )
        file_row.addWidget(self._csv_label, 1)

        btn_browse = QPushButton("Browse...")
        btn_browse.setStyleSheet(theme.action_button_style(primary=False))
        btn_browse.clicked.connect(self._on_browse_csv)
        file_row.addWidget(btn_browse)

        cl.addLayout(file_row)

        # Operation mode
        mode_row = QHBoxLayout()
        mode_row.setSpacing(s.dimension(12))

        mode_label = QLabel("Operation:")
        mode_label.setStyleSheet(
            f"font-weight: bold; font-size: {s.font_size(11)}px; "
            f"font-family: {theme.FONT_FAMILY}; color: {theme.TEXT_PRIMARY};"
        )
        mode_row.addWidget(mode_label)

        self._radio_append = QRadioButton("Append (add new rows, skip duplicates by key)")
        self._radio_append.setChecked(True)
        self._radio_append.setStyleSheet(
            f"font-size: {s.font_size(11)}px; font-family: {theme.FONT_FAMILY};"
        )
        self._radio_replace = QRadioButton("Replace (clear all, replace with CSV)")
        self._radio_replace.setStyleSheet(
            f"font-size: {s.font_size(11)}px; font-family: {theme.FONT_FAMILY};"
        )

        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._radio_append, 0)
        self._mode_group.addButton(self._radio_replace, 1)

        mode_row.addWidget(self._radio_append)
        mode_row.addWidget(self._radio_replace)
        mode_row.addStretch()
        cl.addLayout(mode_row)

        # Warning label
        self._warn_label = QLabel("")
        self._warn_label.setWordWrap(True)
        self._warn_label.setVisible(False)
        self._warn_label.setStyleSheet(
            f"color: #E65100; background-color: #FFF3E0; "
            f"padding: {s.dimension(6)}px; border: 1px solid #FFB74D; "
            f"border-radius: {s.dimension(4)}px; font-size: {s.font_size(11)}px; "
            f"font-family: {theme.FONT_FAMILY};"
        )
        cl.addWidget(self._warn_label)

        layout.addWidget(csv_section)

        # ── Comparison & Preview Section ──────────────────────────
        preview_section = CollapsibleSection("Comparison & Preview", expanded=True)
        pvl = preview_section.content_layout()

        self._comparison = TableComparisonWidget()
        pvl.addWidget(self._comparison)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_refresh_preview = QPushButton("Refresh Preview")
        btn_refresh_preview.setStyleSheet(theme.action_button_style(primary=False))
        btn_refresh_preview.clicked.connect(self._generate_preview)
        btn_row.addWidget(btn_refresh_preview)
        pvl.addLayout(btn_row)

        layout.addWidget(preview_section)

        layout.addStretch()

        # ── Actions ───────────────────────────────────────────────
        action_layout = QHBoxLayout()
        action_layout.addStretch()
        self.btn_apply = QPushButton("Apply Changes")
        self.btn_apply.setStyleSheet(theme.action_button_style(primary=True))
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._on_apply)
        action_layout.addWidget(self.btn_apply)
        layout.addLayout(action_layout)

        scroll.setWidget(content)
        page_lay.addWidget(scroll)

        # Initial population
        self._populate_table_combo()

    # ─── combo population ─────────────────────────────────────────

    def _populate_table_combo(self):
        self._table_combo.blockSignals(True)
        prev = self._table_combo.currentText()
        self._table_combo.clear()
        for layer in _get_non_spatial_layers():
            self._table_combo.addItem(layer_display_name(layer), layer.id())
        # Restore selection if still present
        idx = self._table_combo.findText(prev)
        if idx >= 0:
            self._table_combo.setCurrentIndex(idx)
        self._table_combo.blockSignals(False)
        # Trigger load for current selection
        if self._table_combo.count() > 0:
            self._on_table_selected(self._table_combo.currentText())

    def _on_table_selected(self, name):
        if not name:
            self._target_layer = None
            self._current_df = None
            self._comparison.clear_all()
            return

        layer_id = self._table_combo.currentData()
        project = QgsProject.instance()
        layer = project.mapLayer(layer_id)
        if not layer:
            return

        self._target_layer = layer
        self._current_df = _layer_to_df(layer)
        self._comparison.set_current(self._current_df)
        self.log_message.emit(f"Loaded table '{name}': {len(self._current_df)} rows")

        # Auto-refresh preview if incoming CSV is loaded
        if self._incoming_df is not None:
            self._generate_preview()

    # ─── export template ──────────────────────────────────────────

    def _on_export_template(self):
        if self._current_df is None or self._target_layer is None:
            QMessageBox.information(self, "No Table", "Select a table first.")
            return

        default_name = f"{self._target_layer.name()}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Template CSV", default_name,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        self._current_df.to_csv(path, index=False)
        self.log_message.emit(f"Exported template CSV to: {path}")
        QMessageBox.information(self, "Exported",
                                f"Saved {len(self._current_df)} rows to:\n{path}")

    # ─── browse CSV ───────────────────────────────────────────────

    def _on_browse_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV File", "",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        try:
            df = pd.read_csv(path, dtype=str, keep_default_na=False)
        except Exception as e:
            QMessageBox.warning(self, "CSV Error", f"Failed to read CSV:\n{e}")
            return

        self._csv_path = path
        self._incoming_df = df
        self._csv_label.setText(os.path.basename(path))
        self._comparison.set_incoming(df)
        self.log_message.emit(f"Loaded CSV: {path} ({len(df)} rows)")

        # Validate columns against target
        self._validate_columns()
        self._generate_preview()

    def _validate_columns(self):
        """Check incoming CSV columns against target table schema."""
        if self._current_df is None or self._incoming_df is None:
            self._warn_label.setVisible(False)
            return

        target_cols = set(self._current_df.columns)
        incoming_cols = set(self._incoming_df.columns)

        missing = target_cols - incoming_cols
        extra = incoming_cols - target_cols

        warnings = []
        if missing:
            warnings.append(f"Missing columns (will be NULL): {', '.join(sorted(missing))}")
        if extra:
            warnings.append(f"Extra columns (will be ignored): {', '.join(sorted(extra))}")

        if warnings:
            self._warn_label.setText("\n".join(warnings))
            self._warn_label.setVisible(True)
        else:
            self._warn_label.setVisible(False)

    # ─── preview generation ───────────────────────────────────────

    def _generate_preview(self):
        if self._current_df is None or self._incoming_df is None:
            self.btn_apply.setEnabled(False)
            return

        target_cols = list(self._current_df.columns)
        is_replace = self._radio_replace.isChecked()

        if is_replace:
            # Replace mode: final = incoming, aligned to target columns
            preview = self._incoming_df.reindex(columns=target_cols)
            self._preview_df = preview
        else:
            # Append mode: add rows from incoming that are new (by first column as key)
            if not target_cols:
                self._preview_df = self._current_df.copy()
            else:
                key_col = target_cols[0]  # Use first column as dedup key
                if key_col in self._incoming_df.columns:
                    existing_keys = set(self._current_df[key_col].astype(str))
                    new_rows = self._incoming_df[
                        ~self._incoming_df[key_col].astype(str).isin(existing_keys)
                    ]
                    if len(new_rows) > 0:
                        new_aligned = new_rows.reindex(columns=target_cols)
                        preview = pd.concat(
                            [self._current_df, new_aligned], ignore_index=True)
                    else:
                        preview = self._current_df.copy()
                else:
                    # Can't deduplicate without key column; just append all
                    new_aligned = self._incoming_df.reindex(columns=target_cols)
                    preview = pd.concat(
                        [self._current_df, new_aligned], ignore_index=True)
                self._preview_df = preview

        self._comparison.set_preview(self._preview_df)
        self.btn_apply.setEnabled(True)
        self.log_message.emit(
            f"Preview: {len(self._preview_df)} rows "
            f"({'replace' if is_replace else 'append'} mode)")

    # ─── apply changes ────────────────────────────────────────────

    def _on_apply(self):
        if self._target_layer is None or self._preview_df is None:
            return

        reply = QMessageBox.question(
            self, "Confirm Changes",
            f"Apply changes to '{self._target_layer.name()}'?\n\n"
            f"This will write {len(self._preview_df)} rows to the table.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.status_changed.emit("in_progress")
        layer = self._target_layer

        try:
            layer.startEditing()

            # Delete all existing features
            existing_ids = [f.id() for f in layer.getFeatures()]
            if existing_ids:
                layer.deleteFeatures(existing_ids)

            # Add new features from preview dataframe
            field_names = [f.name() for f in layer.fields()]
            new_features = []
            for _, row in self._preview_df.iterrows():
                feat = QgsFeature(layer.fields())
                for col in field_names:
                    if col in self._preview_df.columns:
                        val = row[col]
                        if pd.isna(val) or val == '':
                            val = None
                        feat.setAttribute(col, val)
                new_features.append(feat)

            if new_features:
                layer.addFeatures(new_features)

            if layer.commitChanges():
                self.log_message.emit(
                    f"Applied {len(new_features)} rows to '{layer.name()}'")
                _log(f"Updated table '{layer.name()}': {len(new_features)} rows")

                # Refresh current view
                self._current_df = _layer_to_df(layer)
                self._comparison.set_current(self._current_df)
                self.btn_apply.setEnabled(False)

                QMessageBox.information(
                    self, "Success",
                    f"Successfully wrote {len(new_features)} rows to '{layer.name()}'.")
                self.status_changed.emit("complete")
            else:
                errors = layer.commitErrors()
                layer.rollBack()
                err_msg = "; ".join(errors) if errors else "Unknown error"
                self.log_message.emit(f"Commit failed: {err_msg}")
                _log(f"Commit failed for '{layer.name()}': {err_msg}", Qgis.Critical)
                QMessageBox.warning(self, "Error",
                                    f"Failed to commit changes:\n{err_msg}")
                self.status_changed.emit("not_started")

        except Exception as e:
            if layer.isEditable():
                layer.rollBack()
            self.log_message.emit(f"Error: {e}")
            _log(f"Error updating '{layer.name()}': {e}", Qgis.Critical)
            QMessageBox.warning(self, "Error", f"An error occurred:\n{e}")
            self.status_changed.emit("not_started")
