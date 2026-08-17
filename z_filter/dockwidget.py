# -*- coding: utf-8 -*-
"""
Z Filter dock panel — filter the mapping layers to one bench/level.

Pure-code QDockWidget (ClipperDockWidget pattern). All subset-string work is
delegated to ZFilterController; this file is UI, state restore and prompts.
"""

from qgis.core import Qgis, QgsProject
from qgis.gui import QgsCollapsibleGroupBox
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QDoubleValidator
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
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

from .controller import ZFilterController, suspended_filters
from .expression import DEFAULT_TOLERANCE, ELEVATION_FIELD, format_number

try:
    from ..lgs_layers import BASEMAP, FIELDNOTEBOOK, LINEWORK, OVERLAY
except ImportError:
    from lgs_layers import BASEMAP, FIELDNOTEBOOK, LINEWORK, OVERLAY
from .ladder import LevelLadder
from .levels import (
    DEFAULT_STEP,
    TOL_PRESETS,
    attach_labels,
    cluster_levels,
    suggest_step,
    suggest_tolerance,
    value_range,
)
from . import auto_layers, detect, field_setup

# Auto-scans (panel open, layer change) skip layers bigger than this;
# the manual "Rescan data" button scans everything.
AUTO_SCAN_FEATURE_CAP = 250_000

_CHIP_STYLE = (
    "QToolButton { border: 1px solid palette(mid); border-radius: 2px;"
    " padding: 2px 8px; background: palette(base); }"
    "QToolButton:hover { background: palette(midlight); }")


class ZFilterDockWidget(QDockWidget):
    """Dock panel driving the elevation (Z) filter across the mapping layers."""

    # (canonical layer name, geometry to offer in the combo). Row order follows
    # the layer tree, so it tracks CANONICAL_LAYERS rather than being spelled
    # out again — Linework and Overlay swapped numbers in Aug 2026.
    LAYER_SLOTS = [
        (FIELDNOTEBOOK, Qgis.GeometryType.Point),
        (LINEWORK, Qgis.GeometryType.Line),
        (OVERLAY, Qgis.GeometryType.Polygon),
        (BASEMAP, Qgis.GeometryType.Polygon),
    ]

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.controller = ZFilterController(iface, parent=self)
        self._user_levels = []     # persisted — levels the user typed
        self._suggestions = []     # cluster dicts from the last data scan
        self._auto_tol = None      # suggest_tolerance() of the last scan
        self._scan = None          # last scan_elevations() report
        self._scanned = False      # auto-scan once per session
        self._restoring = False    # suppress auto-apply during state restore
        self._extra_rows = []      # auto-detected survey/string layer rows
        self._persisted_extra = []  # extra-layer entries from the project
        self._raster_rows = []     # elevation-tied raster rows
        self._persisted_rasters = []  # raster entries from the project
        self._step_persisted = False  # z_filter/step exists in the project
        self._tol_persisted = False   # z_filter/tolerance exists (sticky)
        self._transient_level = None  # swept level — never persisted

        # Debounce automatic rescans when layer selections change.
        self._rescan_timer = QTimer(self)
        self._rescan_timer.setSingleShot(True)
        self._rescan_timer.setInterval(400)
        self._rescan_timer.timeout.connect(lambda: self._on_rescan(manual=False))

        # Coalesce ladder drag sweeps so subsets aren't rewritten per pixel.
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(150)
        self._live_timer.timeout.connect(self._apply_or_enable)

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

        # --- Filter toggle (the panel's primary control, so it leads) ---
        self.toggle_btn = QPushButton("Filter: OFF")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setToolTip("Apply / remove the elevation filter")
        self.toggle_btn.setStyleSheet(
            "QPushButton { font-weight: bold; padding: 6px; }"
            "QPushButton:checked { background-color: #2196F3; color: white; }")
        self.toggle_btn.toggled.connect(self._on_toggled)
        main_layout.addWidget(self.toggle_btn)

        # What the data holds: "320–410 m · 1240 with elevation · 56 blank"
        self.summary_label = QLabel("Not scanned yet.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("color: palette(mid); font-size: 8pt;")
        main_layout.addWidget(self.summary_label)

        # --- Level ladder (detected levels, highest at top) ---
        self.ladder = LevelLadder()
        self.ladder.setToolTip(
            "Detected levels — click a rung to filter to it, click or drag "
            "elsewhere to sweep, scroll to step")
        self.ladder.rungClicked.connect(self._on_rung_clicked)
        self.ladder.elevationPicked.connect(self._on_ladder_picked)
        self.ladder.stepRequested.connect(self._step_level)
        self.ladder.setVisible(False)
        main_layout.addWidget(self.ladder)

        self.ladder_placeholder = QLabel(
            "Scan the data to see the level ladder.")
        self.ladder_placeholder.setStyleSheet(
            "color: palette(mid); font-size: 8pt;")
        main_layout.addWidget(self.ladder_placeholder)

        # --- Stepper: ▼ [level] ▲ + step size ---
        level_row = QHBoxLayout()
        level_row.setSpacing(4)
        self.down_btn = QToolButton()
        self.down_btn.setText("▼")
        self.down_btn.setToolTip("Move the level down by the step size")
        self.down_btn.clicked.connect(lambda: self._step_level(-1))
        level_row.addWidget(self.down_btn)

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

        self.up_btn = QToolButton()
        self.up_btn.setText("▲")
        self.up_btn.setToolTip("Move the level up by the step size")
        self.up_btn.clicked.connect(lambda: self._step_level(+1))
        level_row.addWidget(self.up_btn)

        level_row.addSpacing(6)
        level_row.addWidget(QLabel("Step"))
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.01, 1000.0)
        self.step_spin.setDecimals(2)
        self.step_spin.setSingleStep(0.5)
        self.step_spin.setValue(DEFAULT_STEP)
        self.step_spin.setSuffix(" m")
        self.step_spin.setToolTip("How far ▼/▲ move the level each press "
                                  "(auto-set from the data on first scan)")
        self.step_spin.valueChanged.connect(self._on_step_changed)
        level_row.addWidget(self.step_spin)
        main_layout.addLayout(level_row)

        # --- Slice width + presets ---
        tol_row = QHBoxLayout()
        tol_row.setSpacing(4)
        tol_row.addWidget(QLabel("Width ±"))
        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setRange(0.0, 10000.0)
        self.tolerance_spin.setDecimals(1)
        self.tolerance_spin.setSingleStep(1.0)
        self.tolerance_spin.setValue(5.0)
        self.tolerance_spin.setSuffix(" m")
        self.tolerance_spin.setToolTip(
            "Half-height of the visible slice around the level. Yours once "
            "set — rung clicks never change it (auto-set once from the "
            "first scan)")
        self.tolerance_spin.valueChanged.connect(self._on_tolerance_changed)
        tol_row.addWidget(self.tolerance_spin)

        # Quick-set ± presets + the data-derived "Auto" suggestion.
        for preset in TOL_PRESETS:
            btn = QToolButton()
            btn.setText(f"±{format_number(preset)}")
            btn.setStyleSheet(_CHIP_STYLE)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _checked, v=preset: self._set_tolerance(v))
            tol_row.addWidget(btn)
        self.auto_tol_btn = QToolButton()
        self.auto_tol_btn.setText("Auto")
        self.auto_tol_btn.setStyleSheet(_CHIP_STYLE)
        self.auto_tol_btn.setEnabled(False)
        self.auto_tol_btn.setToolTip("Suggested width from the data "
                                     "(scan first)")
        self.auto_tol_btn.clicked.connect(self._on_auto_tolerance)
        tol_row.addWidget(self.auto_tol_btn)
        tol_row.addStretch()
        main_layout.addLayout(tol_row)

        self.show_null_check = QCheckBox("Always show features with no Elevation")
        self.show_null_check.setChecked(True)
        self.show_null_check.setToolTip(
            "Keep features whose Elevation is empty visible at every level "
            "(values are entered manually, so blanks are common)")
        self.show_null_check.toggled.connect(self._on_settings_changed)
        main_layout.addWidget(self.show_null_check)

        self.rescan_btn = QPushButton("Rescan data")
        self.rescan_btn.setToolTip(
            "Scan the selected layers for elevation values and refresh the "
            "suggested levels (large layers are always included on a manual "
            "rescan)")
        self.rescan_btn.clicked.connect(lambda: self._on_rescan(manual=True))
        main_layout.addWidget(self.rescan_btn)

        # --- Layers (set-and-forget, so collapsed by default) ---
        self.layers_box = QgsCollapsibleGroupBox("Layers")
        self.layers_box.setObjectName("LGSZFilterLayersBox")
        self.layers_box.setSaveCollapsedState(True)
        self.layers_box.setStyleSheet(
            "QgsCollapsibleGroupBox { font-weight: bold;"
            " padding-top: 8px; margin-top: 6px; }")
        layers_layout = QVBoxLayout()
        layers_layout.setSpacing(4)
        layers_layout.setContentsMargins(6, 6, 6, 6)

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
            layers_layout.addLayout(row)
            self.layer_checks.append(check)
            self.layer_combos.append(combo)

        # A plain combo does not auto-track the project, so refresh when
        # layers are added/removed (clipper pattern).
        # (connections made in _connect_project_signals)

        # Additional layers (auto-detected survey points / strings) —
        # hidden entirely when the project has none, so open-pit projects
        # never see it. Rows are rebuilt by _refresh_extra_layers().
        self.extra_group = QGroupBox("Additional Layers")
        self.extra_group.setStyleSheet(
            "QGroupBox { font-weight: bold; padding-top: 8px; margin-top: 6px; }")
        self.extra_layout = QVBoxLayout()
        self.extra_layout.setSpacing(4)
        self.extra_layout.setContentsMargins(6, 6, 6, 6)
        self.extra_group.setLayout(self.extra_layout)
        self.extra_group.setVisible(False)
        layers_layout.addWidget(self.extra_group)

        # Rasters (per-level basemaps) — tie a raster to one elevation so
        # it only shows while the filter window covers it. Hidden when the
        # project has no local rasters. Rows rebuilt by
        # _refresh_raster_rows().
        self.raster_group = QGroupBox("Rasters")
        self.raster_group.setStyleSheet(
            "QGroupBox { font-weight: bold; padding-top: 8px; margin-top: 6px; }")
        self.raster_layout = QVBoxLayout()
        self.raster_layout.setSpacing(4)
        self.raster_layout.setContentsMargins(6, 6, 6, 6)
        self.raster_group.setLayout(self.raster_layout)
        self.raster_group.setVisible(False)
        layers_layout.addWidget(self.raster_group)

        self.layers_box.setLayout(layers_layout)
        self.layers_box.setCollapsed(True)
        main_layout.addWidget(self.layers_box)

        # --- Actions ---
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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(main_widget)
        self.setWidget(scroll)

    def _connect_project_signals(self):
        project = QgsProject.instance()
        project.layersAdded.connect(self._on_project_layers_changed)
        project.layersRemoved.connect(self._on_project_layers_changed)
        self.iface.projectRead.connect(self.sync_from_project)

    def _on_project_layers_changed(self, *_args):
        # layersAdded passes layer objects and layersRemoved passes id
        # strings — neither is a slot-selection list, so drop the payload
        # and refresh keeping the current combo picks.
        self.refresh_layer_combos()

    def shutdown(self):
        """Disconnect project-level signals (called from plugin unload)."""
        project = QgsProject.instance()
        for signal, slot in (
                (project.layersAdded, self._on_project_layers_changed),
                (project.layersRemoved, self._on_project_layers_changed),
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
                # Without a placeholder an unmatched slot silently keeps the
                # first candidate, so a project with no Basemap would filter
                # (and scan) some other polygon layer twice.
                placeholder="— none —",
                target_name=target_name,
                select_layer_id=keep_id)
        self._refresh_extra_layers()
        self._refresh_raster_rows()

    def _refresh_extra_layers(self):
        """Rebuild the auto-detected extra-layer rows (survey/strings)."""
        slot_ids = [c.currentData() for c in self.layer_combos
                    if c.currentData()]
        rows = auto_layers.detect_extra_layers(exclude_ids=slot_ids)
        auto_layers.merge_with_persisted(rows, self._persisted_extra)

        while self.extra_layout.count():
            item = self.extra_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._extra_rows = rows

        for row in rows:
            self.extra_layout.addWidget(self._build_extra_row(row))
        self.extra_group.setVisible(bool(rows))
        # Deliberately no persist here: refresh runs on project-load and
        # layer signals, and writing detection defaults from those paths
        # would clobber the user's saved choices. Persistence happens on
        # explicit user actions (_on_extra_changed) and on apply.

    def _build_extra_row(self, row):
        spec = row['spec']
        widget = QWidget()
        box = QHBoxLayout(widget)
        box.setSpacing(4)
        box.setContentsMargins(0, 0, 0, 0)

        check = QCheckBox()
        check.setChecked(row['checked'])
        check.setToolTip(f"Include '{row['layer'].name()}' in the Z filter")
        check.toggled.connect(lambda on, r=row: self._on_extra_toggled(r, on))
        row['check'] = check
        box.addWidget(check)

        name_label = QLabel(row['layer'].name())
        box.addWidget(name_label)

        usable = [s for s in row['specs'] if not s['disabled_reason']]
        if spec['disabled_reason']:
            widget.setEnabled(False)
            check.setChecked(False)
            detail = QLabel(f"— {spec['disabled_reason']}")
            detail.setStyleSheet("color: palette(mid); font-size: 8pt;")
            box.addWidget(detail)
        elif len(usable) > 1:
            # More than one Z source — offer the choice (auto pick first).
            combo = QComboBox()
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToContents)
            for candidate in usable:
                combo.addItem(self._spec_text(candidate), candidate)
                if candidate is spec:
                    combo.setCurrentIndex(combo.count() - 1)
            combo.currentIndexChanged.connect(
                lambda _i, r=row, c=combo: self._on_extra_source_changed(r, c))
            box.addWidget(combo)
        else:
            detail = QLabel(f"— {self._spec_text(spec)}")
            detail.setStyleSheet("color: palette(mid); font-size: 8pt;")
            detail.setToolTip(
                "Where this layer's level elevation comes from")
            box.addWidget(detail)
        if not spec['disabled_reason']:
            text_fields = auto_layers.string_field_names(row['layer'])
            if text_fields:
                label_combo = QComboBox()
                label_combo.setSizeAdjustPolicy(
                    QComboBox.SizeAdjustPolicy.AdjustToContents)
                label_combo.setToolTip(
                    "Text field naming the level (labels the ladder rungs)")
                label_combo.addItem("(none)", '')
                for name in text_fields:
                    label_combo.addItem(name, name)
                current = spec.get('label_field') or ''
                index = label_combo.findData(current)
                label_combo.setCurrentIndex(index if index >= 0 else 0)
                label_combo.currentIndexChanged.connect(
                    lambda _i, r=row, c=label_combo:
                        self._on_extra_label_changed(r, c))
                box.addWidget(label_combo)
        box.addStretch()
        return widget

    def _refresh_raster_rows(self):
        """Rebuild the elevation-tied raster rows."""
        rows = auto_layers.detect_raster_layers()
        by_id = {e['id']: e for e in self._persisted_rasters if e.get('id')}
        for row in rows:
            entry = by_id.get(row['layer'].id())
            row['checked'] = bool(entry and entry['checked'])
            row['elevation'] = entry['elevation'] if entry else None

        while self.raster_layout.count():
            item = self.raster_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._raster_rows = rows

        for row in rows:
            self.raster_layout.addWidget(self._build_raster_row(row))
        self.raster_group.setVisible(bool(rows))
        # Same no-persist rule as _refresh_extra_layers: this runs on
        # project-load and layer signals; persistence happens on explicit
        # user actions only (_on_raster_changed).

    def _build_raster_row(self, row):
        widget = QWidget()
        box = QHBoxLayout(widget)
        box.setSpacing(4)
        box.setContentsMargins(0, 0, 0, 0)

        check = QCheckBox()
        check.setChecked(row['checked'])
        check.setToolTip(
            f"Show '{row['layer'].name()}' only when the filter window "
            "covers its elevation")
        box.addWidget(check)

        name_label = QLabel(row['layer'].name())
        box.addWidget(name_label)
        box.addStretch()

        spin = QDoubleSpinBox()
        spin.setRange(-10000.0, 10000.0)
        spin.setDecimals(1)
        spin.setSuffix(" m")
        spin.setValue(row['elevation'] if row['elevation'] is not None
                      else 0.0)
        spin.setEnabled(row['checked'])
        spin.setToolTip("This raster's level elevation")
        box.addWidget(spin)

        check.toggled.connect(
            lambda on, r=row, s=spin: self._on_raster_toggled(r, s, on))
        spin.valueChanged.connect(
            lambda value, r=row: self._on_raster_value_changed(r, value))
        return widget

    def _on_raster_toggled(self, row, spin, checked):
        row['checked'] = checked
        spin.setEnabled(checked)
        if checked and row['elevation'] is None:
            # First tie: start from the currently selected level — usually
            # the level the user is looking at when they reach for this.
            level = self.current_level()
            if level is not None:
                blocked = spin.blockSignals(True)
                spin.setValue(level)
                spin.blockSignals(blocked)
            row['elevation'] = spin.value()
        self._on_raster_changed()

    def _on_raster_value_changed(self, row, value):
        row['elevation'] = value
        self._on_raster_changed()

    def _on_raster_changed(self):
        if self._restoring:
            return
        self._persist_rasters()
        self.controller.sync_rasters_now()

    def _persist_rasters(self):
        entries = [{
            'id': row['layer'].id(),
            'name': row['layer'].name(),
            'elevation': row['elevation'],
            'checked': bool(row['checked']),
        } for row in self._raster_rows if row['elevation'] is not None]
        current_ids = {e['id'] for e in entries}
        # Keep ties for rasters not currently in the project (temporarily
        # removed) so assignments survive a round trip out of the list.
        entries += [e for e in self._persisted_rasters
                    if e.get('id') and e['id'] not in current_ids]
        self._persisted_rasters = entries
        self.controller.persist_rasters(entries)

    @staticmethod
    def _spec_text(spec):
        if spec['source'] == 'geom':
            return "Z from geometry"
        if spec['mode'] == 'range':
            return f"{spec['field_min']}/{spec['field_max']}"
        return spec['field']

    def _on_extra_toggled(self, row, checked):
        row['checked'] = checked
        self._on_extra_changed()

    def _on_extra_source_changed(self, row, combo):
        spec = combo.currentData()
        if spec is not None:
            row['spec'] = spec
        self._on_extra_changed()

    def _on_extra_label_changed(self, row, combo):
        # Stamp every candidate so switching the Z source keeps the choice;
        # mark it user-made so rescans stop re-detecting over it.
        row['label_user'] = True
        detect.apply_label_choice(row['specs'], combo.currentData())
        self._on_extra_changed()

    def _on_extra_changed(self):
        if self._restoring:
            return
        self._persist_extra_layers()
        self._rescan_timer.start()
        self._maybe_apply()

    def _persist_extra_layers(self):
        entries = auto_layers.to_persist_entries(self._extra_rows)
        current_ids = {e['id'] for e in entries}
        # Keep saved choices for layers not currently detected (claimed by a
        # slot combo, temporarily removed) so unchecks and source overrides
        # survive a round trip out of the list.
        entries += [e for e in self._persisted_extra
                    if e.get('id') and e['id'] not in current_ids]
        self._persisted_extra = entries
        self.controller.persist_extra_layers(entries)

    def sync_from_project(self):
        """Restore panel state from the (re)loaded project."""
        self._restoring = True
        try:
            state = self.controller.persisted_state()
            self._persisted_extra = state['extra_layers']
            self._persisted_rasters = state['rasters']
            self.refresh_layer_combos(select_ids=state['layer_ids'] or None)
            for i, check in enumerate(self.layer_checks):
                flags = state['layer_checked']
                check.setChecked(flags[i] if i < len(flags) else True)
            self._user_levels = state['levels']
            self._suggestions = []
            self._scan = None
            self._auto_tol = None
            self._repopulate_level_combo(current=state['level'])
            self.tolerance_spin.setValue(
                state['tolerance'] if state['tolerance'] is not None
                else DEFAULT_TOLERANCE)
            # Pre-width project: first scan suggests one (mirror of step).
            self._tol_persisted = state['tolerance'] is not None
            if state['step'] is not None:
                self.step_spin.setValue(state['step'])
                self._step_persisted = True
            else:
                # Pre-step project: leave the default and let the first
                # scan suggest one (never write DEFAULT_STEP blindly, or
                # the auto-init would be frozen forever).
                self._step_persisted = False
            self.show_null_check.setChecked(state['show_null'])
            self.toggle_btn.setChecked(state['enabled'])
            self._update_toggle_text()
            self._sync_ladder()
            if state['enabled']:
                self._set_status("Filter restored from project.")
            else:
                self._set_status("")
        finally:
            self._restoring = False
        # Repopulate the summary + level ladder for the loaded project.
        if self.isVisible():
            QTimer.singleShot(0, lambda: self._on_rescan(manual=False))
        else:
            self._scanned = False  # showEvent will scan when next opened

    def showEvent(self, event):
        super().showEvent(event)
        if not self._scanned:
            QTimer.singleShot(0, lambda: self._on_rescan(manual=False))

    # ------------------------------------------------------------------
    # Level list handling
    # ------------------------------------------------------------------
    def _merged_levels(self):
        """User-typed levels plus current data suggestions, sorted."""
        return sorted(set(self._user_levels) |
                      {c['level'] for c in self._suggestions})

    def _repopulate_level_combo(self, current=None):
        blocked = self.level_combo.blockSignals(True)
        try:
            self.level_combo.clear()
            for value in self._merged_levels():
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
        """Remember a level the user typed. Suggestion levels are already in
        the combo and are recomputed per scan, so they are never persisted."""
        if value in self._merged_levels():
            self._repopulate_level_combo(current=value)
            return
        self._user_levels = sorted(set(self._user_levels) | {value})
        self.controller.persist_levels(self._user_levels)
        self._repopulate_level_combo(current=value)

    def _on_level_entered(self):
        value = self.current_level()
        if value is None:
            return
        self._add_level(value)
        self._update_toggle_text()
        self._maybe_apply()
        self._sync_ladder()

    def _on_level_activated(self, _index):
        self._update_toggle_text()
        self._maybe_apply()
        self._sync_ladder()

    def _step_level(self, direction):
        """Move the level down/up by the step size (numeric sweep)."""
        step = self.step_spin.value()
        current = self.current_level()
        if current is None:
            # Enter the data from the end the user is heading away from:
            # ▼ starts the sweep at the top, ▲ at the bottom.
            levels = [c['level'] for c in self._suggestions]
            if not levels:
                self._set_status("Scan data or type a level first.")
                return
            target = max(levels) if direction < 0 else min(levels)
        else:
            target = current + direction * step
            span = (value_range(self._scan['value_counts'])
                    if self._scan else None)
            if span:
                lo, hi = span[0] - step, span[1] + step
                clamped = min(max(target, lo), hi)
                if clamped != target:
                    self._set_status("Top of data." if direction > 0
                                     else "Bottom of data.")
                target = clamped
        self._repopulate_level_combo(current=target)
        self._transient_level = target
        self._update_toggle_text()
        self._apply_or_enable()
        self._sync_ladder()

    # ------------------------------------------------------------------
    # Data scan + suggestions
    # ------------------------------------------------------------------
    def _on_rescan(self, manual=False):
        targets = [combo_current_layer(c) for c in self.layer_combos]
        targets += [(row['layer'], row['spec']) for row in self._extra_rows
                    if row.get('checked')]
        self._scan = self.controller.scan_elevations(
            targets, feature_cap=None if manual else AUTO_SCAN_FEATURE_CAP)
        self._scanned = True
        self._suggestions = cluster_levels(self._scan['value_counts'])
        attach_labels(self._suggestions,
                      self._scan.get('value_labels') or {})
        # Bake for QField: the device ladder renders from this even when
        # the device-side scan cannot see the data.
        self.controller.persist_suggestions(self._suggestions, self._scan)
        self._auto_tol = (suggest_tolerance(self._suggestions)
                          if self._suggestions else None)
        self.auto_tol_btn.setEnabled(self._auto_tol is not None)
        if self._auto_tol is not None:
            self.auto_tol_btn.setToolTip(
                f"Suggested from the data: ±{format_number(self._auto_tol)} m")
        # Auto-set the sweep step from the data, once — a step the user (or
        # an earlier scan) already chose is never clobbered.
        if not self._step_persisted and self._suggestions:
            step = suggest_step(self._suggestions)
            blocked = self.step_spin.blockSignals(True)
            self.step_spin.setValue(step)
            self.step_spin.blockSignals(blocked)
            self.controller.persist_step(step)
            self._step_persisted = True
        # Same once-only rule for the slice width: a sensible default from
        # the data, then it's the user's until they change it themselves.
        if not self._tol_persisted and self._auto_tol is not None:
            blocked = self.tolerance_spin.blockSignals(True)
            self.tolerance_spin.setValue(self._auto_tol)
            self.tolerance_spin.blockSignals(blocked)
            self.controller.persist_tolerance(self._auto_tol)
            self._tol_persisted = True
        self._update_summary_label()
        self._repopulate_level_combo(current=self.current_level())
        self._sync_ladder()
        if self._suggestions:
            self._set_status(f"{len(self._suggestions)} suggested level(s) "
                             f"from {self._scan['with_elev']} features.")

    def _update_summary_label(self):
        scan = self._scan
        if scan is None:
            self.summary_label.setText("Not scanned yet.")
            return
        parts = []
        span = value_range(scan['value_counts'])
        if span:
            lo, hi, _count = span
            parts.append(f"{format_number(lo)}–{format_number(hi)} m"
                         if lo != hi else f"{format_number(lo)} m")
            parts.append(f"{scan['with_elev']} with elevation")
            if scan['blank']:
                parts.append(f"{scan['blank']} blank")
            if scan.get('spanning'):
                parts.append(f"{scan['spanning']} spanning levels")
        elif scan['total']:
            # Nothing to cluster: say why, or the panel reads as "no data"
            # when the data is there but every feature abstained.
            parts.append(f"No elevation values yet "
                         f"({scan['blank']} blank features)")
            if scan.get('spanning'):
                parts.append(f"{scan['spanning']} spanning levels")
        else:
            parts.append("No features in the selected layers")
        for entry in scan.get('skipped') or []:
            parts.append(f"{entry['name']}: {entry['reason']}")
        if scan['truncated']:
            parts.append("skipped (large): " + ", ".join(scan['truncated']) +
                         " — press Rescan data")
        self.summary_label.setText("  ·  ".join(parts))

    def _sync_ladder(self):
        """Push the current scan/level/width/toggle state into the ladder."""
        self.ladder.set_step(self.step_spin.value())
        scan_range = None
        if self._scan is not None:
            span = value_range(self._scan['value_counts'])
            if span:
                scan_range = (span[0], span[1])
        self.ladder.set_suggestions(self._suggestions, scan_range)
        self.ladder.set_current(self.current_level(),
                                self.tolerance_spin.value(),
                                self.toggle_btn.isChecked())
        has_data = self.ladder.has_data()
        self.ladder.setVisible(has_data)
        self.ladder_placeholder.setVisible(not has_data)

    def _on_rung_clicked(self, cluster):
        """One click: set the level and filter. The width is the user's
        choice and is never touched here."""
        self._repopulate_level_combo(current=cluster['level'])
        self._update_toggle_text()
        self._apply_or_enable()
        self._sync_ladder()

    def _on_ladder_picked(self, value):
        """Background click / drag sweep on the ladder (coalesced apply)."""
        self._repopulate_level_combo(current=value)
        self._transient_level = value
        self._update_toggle_text()
        self._live_timer.start()
        self._sync_ladder()

    def _on_step_changed(self, value):
        if self._restoring:
            return
        self.controller.persist_step(value)
        self._step_persisted = True
        self.ladder.set_step(value)

    def _on_tolerance_changed(self, value):
        """Direct spinbox edits — the width is now the user's choice."""
        if self._restoring:
            return
        self._tol_persisted = True
        self.controller.persist_tolerance(value)
        self._update_toggle_text()
        self._maybe_apply()
        self._sync_ladder()

    def _set_tolerance(self, value):
        blocked = self.tolerance_spin.blockSignals(True)
        self.tolerance_spin.setValue(value)
        self.tolerance_spin.blockSignals(blocked)
        # Presets/Auto are explicit user choices too — persist so they
        # stick across rung clicks and project reloads.
        self._tol_persisted = True
        self.controller.persist_tolerance(value)
        self._update_toggle_text()
        self._maybe_apply()
        self._sync_ladder()

    def _on_auto_tolerance(self):
        if self._auto_tol is not None:
            self._set_tolerance(self._auto_tol)

    # ------------------------------------------------------------------
    # Filter application
    # ------------------------------------------------------------------
    def selected_layers(self):
        """Checked canonical layers resolved from the combos."""
        layers = []
        for check, combo in zip(self.layer_checks, self.layer_combos):
            if check.isChecked():
                layers.append(combo_current_layer(combo))
        return [lyr for lyr in layers if lyr is not None]

    def selected_extra_targets(self):
        """Checked extra-layer rows as (layer, spec) targets."""
        return [(row['layer'], row['spec']) for row in self._extra_rows
                if row.get('checked') and not row['spec']['disabled_reason']]

    def _persist_selection(self):
        self.controller.persist_layer_selection(
            [combo.currentData() or "" for combo in self.layer_combos],
            [check.isChecked() for check in self.layer_checks])

    def _on_selection_changed(self, *_args):
        if self._restoring:
            return
        self._persist_selection()
        # A layer newly claimed by (or released from) a slot combo moves out
        # of / back into the auto-detected extras list.
        self._refresh_extra_layers()
        self._rescan_timer.start()  # debounced summary/suggestion refresh
        self._maybe_apply()

    def _on_settings_changed(self, *_args):
        if self._restoring:
            return
        self._update_toggle_text()
        self._maybe_apply()
        self._sync_ladder()

    def _maybe_apply(self):
        if self.toggle_btn.isChecked() and not self._restoring:
            self._apply()

    def _apply_or_enable(self):
        """Apply now, turning the filter on first if it is off. Used by the
        explicit filtering gestures (steppers, ladder) — the map must
        respond even when the toggle was off."""
        if self._restoring:
            return
        if self.toggle_btn.isChecked():
            self._apply()
        else:
            self.toggle_btn.setChecked(True)   # fires _on_toggled → _apply

    def _on_toggled(self, checked):
        self._update_toggle_text()
        if self._restoring:
            return
        if checked:
            self._apply()
        else:
            self._on_clear()
        self._sync_ladder()

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
        self._sync_ladder()

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
        extra_targets = self.selected_extra_targets()
        if not layers and not extra_targets:
            self._set_status("No layers selected.")
            return

        if not self._ensure_elevation_fields(layers):
            blocked = self.toggle_btn.blockSignals(True)
            self.toggle_btn.setChecked(False)
            self.toggle_btn.blockSignals(blocked)
            self._update_toggle_text()
            return

        extra_targets = self._prepare_extra_targets(extra_targets)

        # Swept levels are transient — persisting every ▼/▲ increment would
        # fill z_filter/levels with noise. Typed/rung levels persist as before.
        if self._transient_level is not None and level == self._transient_level:
            self._transient_level = None
        else:
            self._add_level(level)
        report = self.controller.apply_filter(
            list(layers) + extra_targets, level, self.tolerance_spin.value(),
            self.show_null_check.isChecked())
        self._persist_selection()
        # Re-detect before persisting: materialization just added real
        # Z fields, so geom-source specs re-resolve as attr-source — the
        # QField sidecar ignores 'geom' entries (their fields may not
        # exist on a project exported before the first Apply).
        self._refresh_extra_layers()
        self._persist_extra_layers()
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
        self._sync_ladder()

    def _prepare_extra_targets(self, extra_targets):
        """Materialize geometry-Z fields for extra layers that need them.

        Zero-config: fields are added and populated (NULLs only) on first
        apply, provider-direct, and the outcome lands in the message bar.
        A layer whose fields can't be created is dropped from this apply
        (reported), never blocking the canonical layers.
        """
        ready = []
        notes = []
        problems = []
        for layer, spec in extra_targets:
            if spec['source'] != 'geom':
                ready.append((layer, spec))
                continue
            field_report = field_setup.ensure_spec_fields(layer, spec)
            issue = field_report['skipped'] or field_report['error']
            if issue:
                problems.append(f"{layer.name()}: {issue}")
                continue
            with suspended_filters():
                # An active filter would hide not-yet-populated features
                # from the fill pass on a re-apply.
                fill = field_setup.populate_z_from_geometry(layer, spec,
                                                            only_null=True)
            if fill['failed']:
                # Filtering an unpopulated layer would blank it from the
                # map — leave it out of this apply.
                problems.append(
                    f"{layer.name()}: provider refused to write "
                    f"{fill['failed']} elevation value(s)")
                continue
            if fill['updated']:
                added = (" added " + "/".join(field_report['added']) + ","
                         if field_report['added'] else "")
                notes.append(f"{layer.name()}:{added} filled "
                             f"{fill['updated']} of {fill['total']} "
                             f"from geometry")
            if fill['skipped_no_z']:
                notes.append(f"{layer.name()}: {fill['skipped_no_z']} "
                             f"feature(s) have no Z in their geometry")
            ready.append((layer, spec))
        if notes:
            self.iface.messageBar().pushMessage(
                "Z Filter", "; ".join(notes),
                level=Qgis.MessageLevel.Info, duration=6)
        if problems:
            self.iface.messageBar().pushMessage(
                "Z Filter", "; ".join(problems),
                level=Qgis.MessageLevel.Warning, duration=6)
        return ready

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
