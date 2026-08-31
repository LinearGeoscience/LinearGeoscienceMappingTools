"""
View in 3D — control panel.

Non-modal so the 2D canvas and the 3D view stay usable while it is open.
One-click path: run() auto-picks the DEM (view3d/detect.py ladder), opens
the native 3D view immediately and shows this panel for overrides. Only
an ambiguous DEM choice makes the user pick first (fuzzy-never-decides).
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
        if canvas is not None:
            view.apply_z_factor(canvas.mapSettings(), self._z_factor())

    def _quality_changed(self, _index):
        canvas = view.find_lgs_canvas(self.iface)
        if canvas is None:
            return
        settings = canvas.mapSettings()
        view.apply_quality(settings, self.quality_combo.currentData(),
                           self._selected_dem_layer())
        self.status_label.setText(
            "Detail set to {0}.".format(self.quality_combo.currentText()))
        self._update_terrain_note(settings)
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
            self._underground.enter(settings)
            self.status_label.setText(
                "Underground: terrain hidden, mine survey layers at true "
                "RL. Exaggeration applies to terrain only.")
        else:
            self._exit_underground_if_active()
            if mode == 'pit':
                layer = self._selected_dem_layer()
                # Move the camera, never the scene extent: setExtent on a
                # live view shifts the origin and empties it.
                if layer is not None and view.frame_extent(canvas,
                                                           layer.extent()):
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
            self._underground.exit(canvas.mapSettings())
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
        extent = layer.extent() if mode == 'pit' else None
        # A crash inside QGIS's 3D creation cannot be caught from Python,
        # so leave a breadcrumb instead: if we never get to clear it, the
        # next session knows not to walk into the same wall unasked.
        settings_store = QgsSettings()
        settings_store.setValue(SETTING_OPENING, True)
        try:
            canvas = view.open_view(
                self.iface, layer, z_factor=self._z_factor(),
                extent=extent,
                terrain_enabled=(mode != 'underground'),
                quality=self.quality_combo.currentData(),
                eye_dome=self.edl_check.isChecked())
        except Exception as exc:
            import traceback
            QgsMessageLog.logMessage(
                "View in 3D failed:\n" + traceback.format_exc(),
                'Linear Geoscience', Qgis.MessageLevel.Critical)
            self.status_label.setText(f"Could not open 3D view: {exc}")
            return
        finally:
            settings_store.setValue(SETTING_OPENING, False)
        self._apply_mode(canvas)
        self._update_terrain_note(canvas.mapSettings())
        if not self.status_label.text():
            self.status_label.setText(
                "3D view open — mapping is draped on the terrain.")
        self._save_settings()

    def _close_view(self):
        self._exit_underground_if_active()
        if view.close_view(self.iface):
            self.status_label.setText("3D view closed.")


class _NullSettings:
    """Terrain toggle target when the 3D view is already gone."""

    def setTerrainRenderingEnabled(self, _enabled):
        pass


def run(iface, owner=None):
    """One-click: open the 3D view with all defaults and show the panel."""
    existing = getattr(owner, 'view3d_panel', None) if owner else None
    if existing is not None:
        try:
            existing.refresh()
            existing.show()
            existing.raise_()
            return existing
        except RuntimeError:  # wrapped C++ object deleted
            pass
    panel = View3DPanel(iface.mainWindow(), iface)
    if owner is not None:
        owner.view3d_panel = panel
    panel.show()

    settings = QgsSettings()
    if settings.value(SETTING_OPENING, False, bool):
        # Last attempt never returned — almost certainly it crashed QGIS.
        # Show the panel and let the user decide, rather than repeating it.
        settings.setValue(SETTING_OPENING, False)
        panel.status_label.setText(
            "The last attempt to open a 3D view did not complete — QGIS "
            "may have closed. Nothing was opened automatically this time. "
            "Try Standard detail, or QGIS's own View ▸ 3D Map Views to "
            "check whether 3D works at all here.")
        return panel

    if panel._selected_dem_layer() is not None:
        # Same reason as _open_clicked: this whole call is still inside
        # the main dialog button's click dispatch.
        panel.status_label.setText("Opening 3D view...")
        QTimer.singleShot(0, panel._open_view)
    return panel
