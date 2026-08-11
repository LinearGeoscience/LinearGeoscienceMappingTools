# -*- coding: utf-8 -*-
"""
Z Filter dock panel — filter the mapping layers to one bench/level.

Pure-code QDockWidget (ClipperDockWidget pattern). All subset-string work is
delegated to ZFilterController; this file is UI, state restore and prompts.
"""

from qgis.core import Qgis, QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QDoubleValidator
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    from ..layer_select import (
        layer_candidates, populate_layer_combo, combo_current_layer)
except ImportError:
    from layer_select import (
        layer_candidates, populate_layer_combo, combo_current_layer)

from .controller import ZFilterController
from .expression import ELEVATION_FIELD, format_number
from . import field_setup


class ZFilterDockWidget(QDockWidget):
    """Dock panel driving the elevation (Z) filter across the mapping layers."""

    # (canonical layer name, geometry to offer in the combo)
    LAYER_SLOTS = [
        ('1 - FieldNotebook', Qgis.GeometryType.Point),
        ('2 - Overlay', Qgis.GeometryType.Polygon),
        ('3 - Linework', Qgis.GeometryType.Line),
        ('4 - Basemap', Qgis.GeometryType.Polygon),
    ]

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.controller = ZFilterController(iface, parent=self)
        self._levels = []          # sorted known levels
        self._restoring = False    # suppress auto-apply during state restore

        self.setup_ui()
        self._connect_project_signals()
        self.sync_from_project()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def setup_ui(self):
        self.setWindowTitle("Z Filter")
        self.setObjectName("LinearGeoscienceZFilterDock")

        # Paint the dock title explicitly — works around a QGIS/Qt repaint
        # glitch where the native title bar can render partly blank
        self.setStyleSheet(
            "QDockWidget::title {"
            " background: palette(window);"
            " padding: 4px 4px 4px 6px;"
            "}"
        )

        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(8, 8, 8, 8)

        title_label = QLabel("<b>Z Filter — Level Mapping</b>")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 11pt; padding: 4px; color: #2196F3;")
        main_layout.addWidget(title_label)

        # --- Layers ---
        layer_group = QGroupBox("Layers to Filter")
        layer_group.setStyleSheet(
            "QGroupBox { font-weight: bold; padding-top: 8px; margin-top: 6px; }")
        layer_layout = QVBoxLayout()
        layer_layout.setSpacing(4)
        layer_layout.setContentsMargins(6, 6, 6, 6)

        self.layer_checks = []
        self.layer_combos = []
        for target_name, _geometry in self.LAYER_SLOTS:
            row = QHBoxLayout()
            row.setSpacing(4)
            check = QCheckBox()
            check.setChecked(True)
            check.setToolTip(f"Include '{target_name}' in the Z filter")
            check.toggled.connect(self._on_selection_changed)
            combo = QComboBox()
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(18)
            combo.currentIndexChanged.connect(self._on_selection_changed)
            row.addWidget(check)
            row.addWidget(combo, 1)
            layer_layout.addLayout(row)
            self.layer_checks.append(check)
            self.layer_combos.append(combo)

        layer_group.setLayout(layer_layout)
        main_layout.addWidget(layer_group)

        # A plain combo does not auto-track the project, so refresh when
        # layers are added/removed (clipper pattern).
        # (connections made in _connect_project_signals)

        # --- Level ---
        level_group = QGroupBox("Current Level (elevation)")
        level_group.setStyleSheet(
            "QGroupBox { font-weight: bold; padding-top: 8px; margin-top: 6px; }")
        level_layout = QVBoxLayout()
        level_layout.setSpacing(4)
        level_layout.setContentsMargins(6, 6, 6, 6)

        level_row = QHBoxLayout()
        level_row.setSpacing(4)
        self.level_combo = QComboBox()
        self.level_combo.setEditable(True)
        validator = QDoubleValidator()
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.level_combo.lineEdit().setValidator(validator)
        self.level_combo.setToolTip(
            "Pick a level, or type a new one (e.g. a fresh bench RL) and "
            "press Enter to add it")
        self.level_combo.lineEdit().returnPressed.connect(self._on_level_entered)
        self.level_combo.activated.connect(self._on_level_activated)
        level_row.addWidget(self.level_combo, 1)

        self.down_btn = QToolButton()
        self.down_btn.setText("▼")
        self.down_btn.setToolTip("Step down to the next level below")
        self.down_btn.clicked.connect(lambda: self._step_level(-1))
        self.up_btn = QToolButton()
        self.up_btn.setText("▲")
        self.up_btn.setToolTip("Step up to the next level above")
        self.up_btn.clicked.connect(lambda: self._step_level(+1))
        level_row.addWidget(self.down_btn)
        level_row.addWidget(self.up_btn)
        level_layout.addLayout(level_row)

        self.harvest_btn = QPushButton("Refresh levels from data")
        self.harvest_btn.setToolTip(
            "Scan the selected layers for distinct Elevation values")
        self.harvest_btn.clicked.connect(self._on_harvest)
        level_layout.addWidget(self.harvest_btn)

        level_group.setLayout(level_layout)
        main_layout.addWidget(level_group)

        # --- Options ---
        options_group = QGroupBox("Options")
        options_group.setStyleSheet(
            "QGroupBox { font-weight: bold; padding-top: 8px; margin-top: 6px; }")
        options_layout = QVBoxLayout()
        options_layout.setSpacing(4)
        options_layout.setContentsMargins(6, 6, 6, 6)

        tol_row = QHBoxLayout()
        tol_row.addWidget(QLabel("Tolerance ±"))
        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setRange(0.0, 10000.0)
        self.tolerance_spin.setDecimals(1)
        self.tolerance_spin.setSingleStep(1.0)
        self.tolerance_spin.setValue(5.0)
        self.tolerance_spin.setSuffix(" m")
        self.tolerance_spin.setToolTip(
            "Half-height of the visible elevation window around the level")
        self.tolerance_spin.valueChanged.connect(self._on_settings_changed)
        tol_row.addWidget(self.tolerance_spin)
        tol_row.addStretch()
        options_layout.addLayout(tol_row)

        self.show_null_check = QCheckBox("Always show features with no Elevation")
        self.show_null_check.setChecked(True)
        self.show_null_check.setToolTip(
            "Keep features whose Elevation is empty visible at every level "
            "(values are entered manually, so blanks are common)")
        self.show_null_check.toggled.connect(self._on_settings_changed)
        options_layout.addWidget(self.show_null_check)

        options_group.setLayout(options_layout)
        main_layout.addWidget(options_group)

        # --- Actions ---
        self.toggle_btn = QPushButton("Filter: OFF")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setToolTip("Apply / remove the elevation filter")
        self.toggle_btn.setStyleSheet(
            "QPushButton { font-weight: bold; padding: 6px; }"
            "QPushButton:checked { background-color: #2196F3; color: white; }")
        self.toggle_btn.toggled.connect(self._on_toggled)
        main_layout.addWidget(self.toggle_btn)

        self.clear_btn = QPushButton("Clear all filters")
        self.clear_btn.setToolTip(
            "Restore every layer to its pre-filter state")
        self.clear_btn.clicked.connect(self._on_clear)
        main_layout.addWidget(self.clear_btn)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: palette(mid); font-size: 8pt;")
        main_layout.addWidget(self.status_label)

        main_layout.addStretch()
        main_widget.setLayout(main_layout)
        self.setWidget(main_widget)

    def _connect_project_signals(self):
        project = QgsProject.instance()
        project.layersAdded.connect(self.refresh_layer_combos)
        project.layersRemoved.connect(self.refresh_layer_combos)
        self.iface.projectRead.connect(self.sync_from_project)

    def shutdown(self):
        """Disconnect project-level signals (called from plugin unload)."""
        project = QgsProject.instance()
        for signal, slot in ((project.layersAdded, self.refresh_layer_combos),
                             (project.layersRemoved, self.refresh_layer_combos),
                             (self.iface.projectRead, self.sync_from_project)):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    # ------------------------------------------------------------------
    # State restore / project tracking
    # ------------------------------------------------------------------
    def refresh_layer_combos(self, select_ids=None):
        """Repopulate the four layer combos, keeping current picks."""
        for i, (target_name, geometry) in enumerate(self.LAYER_SLOTS):
            combo = self.layer_combos[i]
            keep_id = None
            if select_ids and i < len(select_ids):
                keep_id = select_ids[i] or None
            if keep_id is None:
                keep_id = combo.currentData()
            populate_layer_combo(
                combo,
                layer_candidates(geometry=geometry),
                target_name=target_name,
                select_layer_id=keep_id)

    def sync_from_project(self):
        """Restore panel state from the (re)loaded project."""
        self._restoring = True
        try:
            state = self.controller.persisted_state()
            self.refresh_layer_combos(select_ids=state['layer_ids'] or None)
            for i, check in enumerate(self.layer_checks):
                flags = state['layer_checked']
                check.setChecked(flags[i] if i < len(flags) else True)
            self._levels = state['levels']
            self._repopulate_level_combo(current=state['level'])
            self.tolerance_spin.setValue(state['tolerance'])
            self.show_null_check.setChecked(state['show_null'])
            self.toggle_btn.setChecked(state['enabled'])
            self._update_toggle_text()
            if state['enabled']:
                self._set_status("Filter restored from project.")
            else:
                self._set_status("")
        finally:
            self._restoring = False

    # ------------------------------------------------------------------
    # Level list handling
    # ------------------------------------------------------------------
    def _repopulate_level_combo(self, current=None):
        blocked = self.level_combo.blockSignals(True)
        try:
            self.level_combo.clear()
            for value in self._levels:
                self.level_combo.addItem(format_number(value), value)
            if current is not None:
                text = format_number(current)
                index = self.level_combo.findText(text)
                if index == -1:
                    self.level_combo.addItem(text, float(current))
                    index = self.level_combo.count() - 1
                self.level_combo.setCurrentIndex(index)
        finally:
            self.level_combo.blockSignals(blocked)

    def current_level(self):
        text = self.level_combo.currentText().strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def _add_level(self, value):
        if value not in self._levels:
            self._levels = sorted(set(self._levels) | {value})
            self.controller.persist_levels(self._levels)
            self._repopulate_level_combo(current=value)

    def _on_level_entered(self):
        value = self.current_level()
        if value is None:
            return
        self._add_level(value)
        self._maybe_apply()

    def _on_level_activated(self, _index):
        self._maybe_apply()

    def _step_level(self, direction):
        if not self._levels:
            return
        current = self.current_level()
        if current is None:
            target = self._levels[0] if direction > 0 else self._levels[-1]
        else:
            if direction > 0:
                higher = [v for v in self._levels if v > current]
                if not higher:
                    return
                target = higher[0]
            else:
                lower = [v for v in self._levels if v < current]
                if not lower:
                    return
                target = lower[-1]
        self._repopulate_level_combo(current=target)
        self._maybe_apply()

    def _on_harvest(self):
        layers = [combo_current_layer(c) for c in self.layer_combos]
        harvested = self.controller.harvest_levels(layers)
        self._levels = sorted(set(self._levels) | set(harvested))
        self.controller.persist_levels(self._levels)
        self._repopulate_level_combo(current=self.current_level())
        self._set_status(f"{len(self._levels)} level(s) known "
                         f"({len(harvested)} found in data).")

    # ------------------------------------------------------------------
    # Filter application
    # ------------------------------------------------------------------
    def selected_layers(self):
        """Checked layers resolved from the combos (may contain None)."""
        layers = []
        for check, combo in zip(self.layer_checks, self.layer_combos):
            if check.isChecked():
                layers.append(combo_current_layer(combo))
        return [lyr for lyr in layers if lyr is not None]

    def _persist_selection(self):
        self.controller.persist_layer_selection(
            [combo.currentData() or "" for combo in self.layer_combos],
            [check.isChecked() for check in self.layer_checks])

    def _on_selection_changed(self, *_args):
        if self._restoring:
            return
        self._persist_selection()
        self._maybe_apply()

    def _on_settings_changed(self, *_args):
        if self._restoring:
            return
        self._maybe_apply()

    def _maybe_apply(self):
        if self.toggle_btn.isChecked() and not self._restoring:
            self._apply()

    def _on_toggled(self, checked):
        self._update_toggle_text()
        if self._restoring:
            return
        if checked:
            self._apply()
        else:
            self._on_clear()

    def _on_clear(self):
        restored = self.controller.clear_filters()
        if self.toggle_btn.isChecked():
            blocked = self.toggle_btn.blockSignals(True)
            self.toggle_btn.setChecked(False)
            self.toggle_btn.blockSignals(blocked)
        self._update_toggle_text()
        self._set_status(
            f"Filters cleared ({len(restored)} layer(s) restored)."
            if restored else "No filters to clear.")

    def _apply(self):
        level = self.current_level()
        if level is None:
            self._set_status("Set a level first (pick or type an elevation).")
            blocked = self.toggle_btn.blockSignals(True)
            self.toggle_btn.setChecked(False)
            self.toggle_btn.blockSignals(blocked)
            self._update_toggle_text()
            return

        layers = self.selected_layers()
        if not layers:
            self._set_status("No layers selected.")
            return

        if not self._ensure_elevation_fields(layers):
            blocked = self.toggle_btn.blockSignals(True)
            self.toggle_btn.setChecked(False)
            self.toggle_btn.blockSignals(blocked)
            self._update_toggle_text()
            return

        self._add_level(level)
        report = self.controller.apply_filter(
            layers, level, self.tolerance_spin.value(),
            self.show_null_check.isChecked())
        self._persist_selection()
        self._update_toggle_text()

        parts = []
        if report['applied']:
            parts.append(f"Filtering {len(report['applied'])} layer(s) to "
                         f"{format_number(level)} ± "
                         f"{format_number(self.tolerance_spin.value())} m.")
        for name, reason in report['skipped'] + report['errors']:
            parts.append(f"Skipped {name}: {reason}")
        self._set_status(" ".join(parts))
        if report['skipped'] or report['errors']:
            self.iface.messageBar().pushMessage(
                "Z Filter",
                "; ".join(f"{n}: {r}" for n, r in
                          report['skipped'] + report['errors']),
                level=Qgis.MessageLevel.Warning, duration=6)

    def _ensure_elevation_fields(self, layers):
        """Offer to add the Elevation field where missing. False = user
        cancelled (filter should not engage)."""
        missing = field_setup.layers_missing_elevation(layers)
        if not missing:
            return True
        names = "\n".join(f"  • {lyr.name()}" for lyr in missing)
        answer = QMessageBox.question(
            self,
            "Add Elevation field?",
            f"These layers have no '{ELEVATION_FIELD}' field yet:\n\n{names}\n\n"
            f"Add a numeric '{ELEVATION_FIELD}' field to them now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes)
        if answer != QMessageBox.StandardButton.Yes:
            return False
        report = field_setup.ensure_elevation_fields(missing)
        problems = report['skipped'] + report['errors']
        if problems:
            QMessageBox.warning(
                self, "Elevation field",
                "Could not add the field everywhere:\n\n" +
                "\n".join(f"  • {n}: {r}" for n, r in problems))
        if report['custom_form']:
            QMessageBox.information(
                self, "Elevation field",
                "These layers use a custom (drag-and-drop) feature form — add "
                "the new Elevation field to the form manually so it can be "
                "edited:\n\n" +
                "\n".join(f"  • {n}" for n in report['custom_form']))
        return not report['skipped'] and not report['errors']

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------
    def _update_toggle_text(self):
        if self.toggle_btn.isChecked():
            level = self.current_level()
            if level is not None:
                self.toggle_btn.setText(
                    f"Filter: ON  ({format_number(level)} ± "
                    f"{format_number(self.tolerance_spin.value())} m)")
                return
            self.toggle_btn.setText("Filter: ON")
        else:
            self.toggle_btn.setText("Filter: OFF")

    def _set_status(self, text):
        self.status_label.setText(text)
