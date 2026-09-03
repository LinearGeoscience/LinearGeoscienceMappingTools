"""
View in 3D — control panel.

Non-modal so the 2D canvas and the 3D view stay usable while it is open.
run() auto-picks the DEM (view3d/detect.py ladder) and shows this panel;
the 3D view itself opens only from the Open 3D View button. It used to
open automatically, which meant a crash inside QGIS's 3D creation was
walked into on every press with no way to decline — never reintroduce
the auto-open.
"""

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)
from qgis.core import Qgis, QgsMessageLog, QgsProject, QgsSettings

try:
    from . import detect, terrain, underground, view
except ImportError:  # loaded outside the plugin package
    from view3d import detect, terrain, underground, view

try:
    from .. import plugin_theme as theme
except ImportError:
    import plugin_theme as theme

SETTINGS_PREFIX = "LinearGeosciencePlugin/View3D/"
SETTING_Z_ENABLED = SETTINGS_PREFIX + "zEnabled"
SETTING_Z_FACTOR = SETTINGS_PREFIX + "zFactor"
SETTING_QUALITY = SETTINGS_PREFIX + "quality"
SETTING_EDL = SETTINGS_PREFIX + "eyeDomeLighting"
# Set immediately before asking QGIS for a 3D view and cleared once it
# comes back. Still set at startup => the last attempt took QGIS down
# with it, so do not auto-open into the same crash.
SETTING_OPENING = SETTINGS_PREFIX + "openAttemptInProgress"
SETTING_GEOMETRY = SETTINGS_PREFIX + "dialogGeometry"

QUALITY_CHOICES = [
    ("standard", "Standard — QGIS default"),
    ("high", "High — sharp linework (default)"),
    ("ultra", "Ultra — slowest, needs a good GPU"),
]

MODES = [
    ("surface", "Surface — topography"),
    ("pit", "Pit — frame the pit surface"),
    ("underground", "Underground — terrain off, mine data at RL"),
]


class View3DPanel(QDialog):
    def __init__(self, parent=None, iface=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("View in 3D")
        self.setMinimumWidth(420)
        self.setModal(False)

        self._underground = underground.UndergroundController()
        self._rows = []

        layout = QVBoxLayout()

        header = QLabel(
            "<b>3D terrain with your mapping draped on top</b><br>"
            "The chosen DEM also becomes the project's terrain, so QField "
            "4.1+ shows the same 3D view in the field.")
        header.setWordWrap(True)
        layout.addWidget(header)

        dem_group = QGroupBox("Terrain DEM")
        dem_group.setStyleSheet(theme.group_box_style())
        dem_layout = QVBoxLayout()
        self.dem_combo = QComboBox()
        self.dem_combo.currentIndexChanged.connect(self._dem_changed)
        dem_layout.addWidget(self.dem_combo)
        self.dem_caption = QLabel("")
        self.dem_caption.setStyleSheet("color: #666; padding: 2px;")
        self.dem_caption.setWordWrap(True)
        dem_layout.addWidget(self.dem_caption)
        dem_group.setLayout(dem_layout)
        layout.addWidget(dem_group)

        view_group = QGroupBox("View")
        view_group.setStyleSheet(theme.group_box_style())
        view_layout = QVBoxLayout()

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        for key, label in MODES:
            self.mode_combo.addItem(label, key)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        mode_row.addWidget(self.mode_combo, 1)
        view_layout.addLayout(mode_row)

        z_row = QHBoxLayout()
        self.z_check = QCheckBox("Vertical exaggeration")
        self.z_check.toggled.connect(self._z_changed)
        z_row.addWidget(self.z_check)
        self.z_spin = QDoubleSpinBox()
        self.z_spin.setRange(1.1, 10.0)
        self.z_spin.setDecimals(1)
        self.z_spin.setSingleStep(0.5)
        self.z_spin.setValue(2.0)
        self.z_spin.setSuffix("x")
        self.z_spin.valueChanged.connect(self._z_changed)
        z_row.addWidget(self.z_spin)
        z_row.addStretch()
        view_layout.addLayout(z_row)

        qual_row = QHBoxLayout()
        qual_row.addWidget(QLabel("Detail:"))
        self.quality_combo = QComboBox()
        for key, label in QUALITY_CHOICES:
            self.quality_combo.addItem(label, key)
        self.quality_combo.setToolTip(
            "How sharply the map is drawn onto the terrain. Raise this if "
            "linework or contours look smeared; lower it if the view is "
            "slow.")
        self.quality_combo.currentIndexChanged.connect(self._quality_changed)
        qual_row.addWidget(self.quality_combo, 1)
        view_layout.addLayout(qual_row)

        self.edl_check = QCheckBox("Shade relief (eye dome lighting)")
        self.edl_check.setToolTip(
            "Darkens slope breaks so bench crests and toes read as shape. "
            "Without it a pale basemap draped on terrain looks flat, "
            "because nothing shades the relief.")
        self.edl_check.toggled.connect(self._edl_changed)
        view_layout.addWidget(self.edl_check)

        self.terrain_note = QLabel("")
        self.terrain_note.setWordWrap(True)
        self.terrain_note.setStyleSheet("color: #b8860b; padding: 2px;")
        self.terrain_note.hide()
        view_layout.addWidget(self.terrain_note)

        view_group.setLayout(view_layout)
        layout.addWidget(view_group)

        button_row = QHBoxLayout()
        self.open_button = QPushButton("Open 3D View")
        self.open_button.clicked.connect(self._open_clicked)
        button_row.addWidget(self.open_button, 1)
        self.close_view_button = QPushButton("Close 3D View")
        self.close_view_button.clicked.connect(self._close_view)
        button_row.addWidget(self.close_view_button)
        self.zoom_button = QPushButton("Zoom to Terrain")
        self.zoom_button.setToolTip(
            "Fit the whole 3D scene in view — use it if the camera has "
            "ended up somewhere that shows nothing.")
        self.zoom_button.clicked.connect(self._zoom_full)
        button_row.addWidget(self.zoom_button)
        self.diagnose_button = QPushButton("Diagnose")
        self.diagnose_button.setToolTip(
            "Write what the 3D view actually contains — camera, terrain, "
            "layers, CRSs — to the Linear Geoscience log panel.")
        self.diagnose_button.clicked.connect(self._diagnose)
        button_row.addWidget(self.diagnose_button)
        layout.addLayout(button_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; padding: 2px;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.setLayout(layout)
        self._restore_settings()
        self.refresh()

    # -------------------------------------------------------- persistence

    def _restore_settings(self):
        settings = QgsSettings()
        geometry = settings.value(SETTING_GEOMETRY)
        if geometry is not None:
            self.restoreGeometry(geometry)
        self.z_check.setChecked(
            settings.value(SETTING_Z_ENABLED, False, bool))
        self.z_spin.setValue(settings.value(SETTING_Z_FACTOR, 2.0, float))
        quality = settings.value(SETTING_QUALITY, view.DEFAULT_QUALITY, str)
        idx = self.quality_combo.findData(quality)
        if idx < 0:
            idx = self.quality_combo.findData(view.DEFAULT_QUALITY)
        self.quality_combo.blockSignals(True)
        self.quality_combo.setCurrentIndex(max(0, idx))
        self.quality_combo.blockSignals(False)
        self.edl_check.blockSignals(True)
        self.edl_check.setChecked(settings.value(SETTING_EDL, True, bool))
        self.edl_check.blockSignals(False)

    def _save_settings(self):
        settings = QgsSettings()
        settings.setValue(SETTING_GEOMETRY, self.saveGeometry())
        settings.setValue(SETTING_Z_ENABLED, self.z_check.isChecked())
        settings.setValue(SETTING_Z_FACTOR, self.z_spin.value())
        settings.setValue(SETTING_QUALITY, self.quality_combo.currentData())
        settings.setValue(SETTING_EDL, self.edl_check.isChecked())

    def closeEvent(self, event):
        # Leaving temporary subsets/renderers behind with no panel to undo
        # them would be a trap; restore underground state on the way out.
        self._exit_underground_if_active()
        self._save_settings()
        super().closeEvent(event)

    # ---------------------------------------------------------- DEM combo

    def refresh(self):
        project = QgsProject.instance()
        all_rows = terrain.dem_rows(project)
        pinned = terrain.pinned_dem_id(project)
        chosen, reason = detect.choose_dem(all_rows, pinned)
        # Orthophotos and hillshades are not elevation; keep them out of the
        # list entirely rather than inviting the wrong pick.
        self._rows = [r for r in all_rows
                      if detect.is_dem_candidate(r) or r['id'] == pinned]
        self.dem_combo.blockSignals(True)
        self.dem_combo.clear()
        if not self._rows:
            self.dem_combo.addItem("No DEM raster in project", None)
            self.dem_caption.setText(
                "Load a DEM (or run Pit Surface to DEM on a Surpac/DXF "
                "pit shell) first. Imagery and hillshades are not "
                "elevation and are not listed.")
        else:
            self.dem_combo.addItem("Select a DEM...", None)
            for row in self._rows:
                tag = " (pit)" if detect.classify(row) == 'pit' else ""
                self.dem_combo.addItem(row['name'] + tag, row['id'])
            if chosen is not None:
                idx = self.dem_combo.findData(chosen['id'])
                if idx > 0:
                    self.dem_combo.setCurrentIndex(idx)
                self.dem_caption.setText(
                    {'pinned': "Your saved choice for this project.",
                     'role': "Pit surface DEM (auto-selected).",
                     'pit': "Pit-classified DEM (auto-selected).",
                     'single': "Only local raster in the project."}
                    .get(reason, ""))
            else:
                self.dem_caption.setText(
                    "Several plausible DEMs — pick the terrain surface.")
        self.dem_combo.blockSignals(False)

        mode = detect.default_mode(chosen)
        idx = self.mode_combo.findData(mode)
        if idx >= 0:
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(idx)
            self.mode_combo.blockSignals(False)
        self._gate_modes()

    def _gate_modes(self):
        model = self.mode_combo.model()
        ug_idx = self.mode_combo.findData('underground')
        if ug_idx >= 0:
            item = model.item(ug_idx)
            enabled = underground.has_mine_data()
            item.setEnabled(enabled)
            if not enabled and self.mode_combo.currentIndex() == ug_idx:
                self.mode_combo.setCurrentIndex(0)

    def _selected_dem_layer(self):
        layer_id = self.dem_combo.currentData()
        if not layer_id:
            return None
        return QgsProject.instance().mapLayer(layer_id)

    def _dem_changed(self, _index):
        layer = self._selected_dem_layer()
        if layer is None:
            return
        terrain.pin_dem_layer(layer)
        self.dem_caption.setText("Saved as this project's terrain DEM.")
        if view.find_lgs_canvas(self.iface) is not None:
            self._open_view()  # re-point the open view live

    # ------------------------------------------------------------ actions

    def _z_factor(self):
        return self.z_spin.value() if self.z_check.isChecked() else 1.0

    def _z_changed(self, _value=None):
        canvas = view.find_lgs_canvas(self.iface)
        if canvas is None:
            return
        # On 3.40 a terrain setter fired while the scene is loading
        # deletes the generator under its own heightmap jobs — access
        # violation. request_* queues the change for a quiet scene there.
        if not view.request_z_factor(canvas, self._z_factor(),
                                     guard_key=SETTING_OPENING):
            self.status_label.setText(
                "Exaggeration queued — it applies once the 3D view "
                "finishes its current loading.")

    def _quality_changed(self, _index):
        canvas = view.find_lgs_canvas(self.iface)
        if canvas is None:
            return
        applied = view.request_quality(
            canvas, self.quality_combo.currentData(),
            self._selected_dem_layer(), guard_key=SETTING_OPENING)
        self.status_label.setText(
            "Detail set to {0}.".format(self.quality_combo.currentText())
            if applied else
            "Detail queued — it applies once the 3D view finishes its "
            "current loading.")
        self._update_terrain_note(canvas.mapSettings())
        self._save_settings()

    def _edl_changed(self, checked):
        canvas = view.find_lgs_canvas(self.iface)
        if canvas is not None:
            view.apply_lighting(canvas.mapSettings(), checked)
        self._save_settings()

    def _update_terrain_note(self, settings):
        """On 3.40 the terrain mesh resolution cannot be set from Python,
        and its 16 px default is what makes bench faces look mushy. Say so
        once, with the exact field to change, rather than silently
        under-delivering."""
        if settings is None or view.terrain_resolution_reachable(settings):
            self.terrain_note.hide()
            return
        wanted = view.QUALITY_LEVELS.get(
            self.quality_combo.currentData(),
            view.QUALITY_LEVELS[view.DEFAULT_QUALITY])[2]
        self.terrain_note.setText(
            "This QGIS cannot set terrain mesh detail from a plugin. For "
            "crisper bench faces, open the 3D view's <b>3D Configuration "
            "▸ Terrain</b> and raise <b>Tile resolution</b> from 16 px "
            "to {0} px (once per view).".format(wanted))
        self.terrain_note.show()

    def _mode_changed(self, _index):
        canvas = view.find_lgs_canvas(self.iface)
        if canvas is None:
            return
        self._apply_mode(canvas)

    def _apply_mode(self, canvas):
        mode = self.mode_combo.currentData()
        settings = canvas.mapSettings()
        if mode == 'underground':
            self._underground.enter(settings, canvas=canvas)
            self.status_label.setText(
                "Underground: terrain hidden, mine survey layers at true "
                "RL. Exaggeration applies to terrain only.")
        else:
            self._exit_underground_if_active()
            if mode == 'pit':
                layer = self._selected_dem_layer()
                # Move the camera, never the scene extent: setExtent on a
                # live view shifts the origin and empties it.
                # ...and aim at the ground, not Z=0: a pit near 381 m RL
                # would otherwise be framed a pit-depth below itself.
                if layer is not None and view.frame_extent(
                        canvas, view.extent_in_project_crs(layer),
                        view.mid_elevation(layer) * self._z_factor()):
                    self.status_label.setText(
                        "Framed to the pit surface DEM.")
                else:
                    self.status_label.setText(
                        "Pit mode — reopen the view to reframe it.")
            else:
                self.status_label.setText("")

    def _exit_underground_if_active(self):
        if not self._underground.active:
            return
        canvas = view.find_lgs_canvas(self.iface)
        if canvas is not None:
            self._underground.exit(canvas.mapSettings(), canvas=canvas)
        else:
            # View already gone; still restore subsets/renderers.
            self._underground.exit(_NullSettings())

    def _open_clicked(self):
        # Never build the 3D view inside the button's own click handler:
        # it adds a dock to the main window while Qt is still dispatching
        # the mouse release on this dialog. Hand it to the next turn of
        # the event loop instead.
        self.status_label.setText("Opening 3D view...")
        QTimer.singleShot(0, self._open_view)

    def _open_view(self):
        layer = self._selected_dem_layer()
        if layer is None:
            self.status_label.setText("Select a DEM first.")
            return
        mode = self.mode_combo.currentData()
        extent = (view.extent_in_project_crs(layer)
                  if mode == 'pit' else None)
        # A crash inside QGIS's 3D creation cannot be caught from Python,
        # so leave a breadcrumb instead: if we never get to clear it, the
        # next session knows not to walk into the same wall unasked.
        settings_store = QgsSettings()
        settings_store.setValue(SETTING_OPENING, True)
        QgsMessageLog.logMessage(
            "View in 3D: creating a view - DEM '{0}', mode {1}, detail {2}, "
            "z {3}, EDL {4}".format(
                layer.name(), mode, self.quality_combo.currentData(),
                self._z_factor(), self.edl_check.isChecked()),
            'Linear Geoscience', Qgis.MessageLevel.Info)
        try:
            canvas = view.open_view(
                self.iface, layer, z_factor=self._z_factor(),
                extent=extent,
                terrain_enabled=(mode != 'underground'),
                quality=self.quality_combo.currentData(),
                eye_dome=self.edl_check.isChecked(),
                guard_key=SETTING_OPENING)
        except Exception as exc:
            import traceback
            QgsMessageLog.logMessage(
                "View in 3D failed:\n" + traceback.format_exc(),
                'Linear Geoscience', Qgis.MessageLevel.Critical)
            self.status_label.setText(f"Could not open 3D view: {exc}")
            try:
                self.iface.messageBar().pushWarning(
                    "View in 3D", f"Could not open 3D view: {exc}")
            except Exception:
                pass
            settings_store.setValue(SETTING_OPENING, False)
            return
        # _apply_mode leaves a mode-specific note (or clears it for
        # Surface); keep that and say plainly that a view now exists —
        # a stale "Opening..." is how a view that never appeared went
        # unnoticed.
        try:
            self._apply_mode(canvas)
            self._update_terrain_note(canvas.mapSettings())
            mode_note = self.status_label.text()
            message = (("3D view open. " + mode_note).strip() if mode_note
                       else "3D view open — mapping is draped on the "
                            "terrain.")
            if view.quiet_queue_active():
                # 3.40 opens at QGIS-default detail and sharpens once
                # the first terrain load settles; say so or the first
                # look reads as a regression.
                message += (" Detail settings apply as the terrain "
                            "finishes loading.")
            self.status_label.setText(message)
            QgsMessageLog.logMessage(
                "View in 3D: view created. "
                + view.describe(self.iface, layer, probe_scene=False),
                'Linear Geoscience', Qgis.MessageLevel.Info)
            self._save_settings()
        finally:
            # A crash used to escape the breadcrumb: it was cleared the
            # moment open_view returned, but the deferred re-aim
            # (view._reframe_when_ready) can still poke the scene for a
            # couple of seconds after this method exits, and that is
            # exactly where a settling scene can take QGIS down. Keep the
            # flag set until that window has passed. When the 3.40
            # quiet-scene queue is still applying terrain changes, the
            # flag is ITS crash guard — it clears it when it drains, so
            # keep hands off here.
            grace = (view.REFRAME_TRIES * view.REFRAME_INTERVAL_MS) + 1000

            def _clear_guard():
                if view.quiet_queue_active():
                    return
                QgsSettings().setValue(SETTING_OPENING, False)

            QTimer.singleShot(grace, _clear_guard)

    def _zoom_full(self):
        canvas = view.find_lgs_canvas(self.iface)
        if canvas is None:
            self.status_label.setText("No 3D view open.")
            return
        if view.zoom_full(canvas):
            self.status_label.setText("Zoomed to the whole 3D scene.")
        else:
            self.status_label.setText("Could not zoom the 3D scene.")

    def _panel_state(self):
        """What the panel itself would do, in words — the half of the
        picture view.describe() cannot see."""
        settings = QgsSettings()
        layer = self._selected_dem_layer()
        return "\n".join([
            "  panel DEM selected       {0}".format(
                layer.name() if layer else "NONE  <-- nothing will open"),
            "  panel DEM candidates     {0}".format(len(self._rows)),
            "  panel mode               {0}".format(
                self.mode_combo.currentData()),
            "  panel detail             {0}".format(
                self.quality_combo.currentData()),
            "  crash guard set          {0}{1}".format(
                settings.value(SETTING_OPENING, False, bool),
                "  <-- auto-open is suppressed once"
                if settings.value(SETTING_OPENING, False, bool) else ""),
        ])

    def _diagnose(self):
        try:
            QgsMessageLog.logMessage(
                "=== View in 3D panel state ===\n" + self._panel_state(),
                'Linear Geoscience', Qgis.MessageLevel.Info)
            view.log_diagnostics(self.iface, self._selected_dem_layer())
        except Exception as exc:
            QgsMessageLog.logMessage(
                "Diagnostics failed: {0}".format(exc),
                'Linear Geoscience', Qgis.MessageLevel.Warning)
            self.status_label.setText("Diagnostics failed: {0}".format(exc))
            return
        self.iface.messageBar().pushInfo(
            "Linear Geoscience",
            "3D diagnostics written to the log (View ▸ Panels ▸ Log "
            "Messages ▸ Linear Geoscience).")
        self.status_label.setText(
            "Diagnostics written to the Log Messages panel.")

    def _close_view(self):
        self._exit_underground_if_active()
        if view.close_view(self.iface):
            self.status_label.setText("3D view closed.")


class _NullSettings:
    """Terrain toggle target when the 3D view is already gone."""

    def setTerrainRenderingEnabled(self, _enabled):
        pass


def run(iface, owner=None):
    """Show the panel. The 3D view opens ONLY from Open 3D View.

    The panel is cached on the plugin, so most presses of "View in 3D"
    land on an existing one; both paths end in the same state hints.
    Opening the view here used to be automatic — with a crash inside
    QGIS's 3D creation on some setups, that meant pressing the feature
    button at all took QGIS down. The user decides when to open.
    """
    panel = None
    existing = getattr(owner, 'view3d_panel', None) if owner else None
    if existing is not None:
        try:
            existing.refresh()
            existing.show()
            existing.raise_()
            panel = existing
        except RuntimeError:  # wrapped C++ object deleted
            panel = None
    if panel is None:
        panel = View3DPanel(iface.mainWindow(), iface)
        if owner is not None:
            owner.view3d_panel = panel
        panel.show()

    # Every path out of here is logged. "Nothing happened" has now cost
    # several rounds of guessing precisely because the reason lived only
    # in a status label, which is not what gets sent to anyone.
    def _decided(reason):
        QgsMessageLog.logMessage("View in 3D: " + reason,
                                 'Linear Geoscience', Qgis.MessageLevel.Info)

    if view.find_lgs_canvas(iface) is not None:
        panel.status_label.setText("3D view is already open.")
        _decided("panel shown; a view is already open")
        return panel

    settings = QgsSettings()
    if settings.value(SETTING_OPENING, False, bool):
        # The last attempt never finished — almost certainly it took QGIS
        # down. Say so where it cannot be missed.
        settings.setValue(SETTING_OPENING, False)
        message = ("The last attempt to open a 3D view did not finish — "
                   "it probably crashed QGIS. Press Open 3D View to try "
                   "again (Standard detail is the safest).")
        panel.status_label.setText(message)
        _decided("panel shown; the previous open attempt never returned "
                 "(crash guard). The flag is now cleared.")
        try:
            iface.messageBar().pushWarning("View in 3D", message)
        except Exception:
            pass
        return panel

    if panel._selected_dem_layer() is None:
        panel.status_label.setText(
            "Choose a terrain DEM, then press Open 3D View.")
        _decided("panel shown; no DEM selected "
                 "({0} candidate rows)".format(len(panel._rows)))
        return panel

    panel.status_label.setText(
        "Press Open 3D View to open the view over '{0}'.".format(
            panel._selected_dem_layer().name()))
    _decided("panel shown; DEM '{0}' ready, waiting for Open 3D View".format(
        panel._selected_dem_layer().name()))
    return panel
