"""Dialog for repacking large imagery so it performs in the field."""

import os

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)
from qgis.core import (
    Qgis,
    QgsMessageLog,
    QgsProject,
    QgsRasterLayer,
    QgsSettings,
)

try:
    from . import core
    from ..lgs_tasks import run_in_task
except ImportError:  # loaded outside the plugin package
    from raster_optimise import core
    from lgs_tasks import run_in_task

try:
    from .. import plugin_theme as theme
except ImportError:
    import plugin_theme as theme

SETTINGS_PREFIX = "LinearGeosciencePlugin/RasterOptimise/"
SETTING_PROFILE = SETTINGS_PREFIX + "profile"
SETTING_TILING = SETTINGS_PREFIX + "tiling"
SETTING_TILE_MB = SETTINGS_PREFIX + "tileMb"
SETTING_GEOMETRY = SETTINGS_PREFIX + "dialogGeometry"

SOURCE_FILTER = ("Rasters (*.tif *.tiff *.img *.vrt *.jp2 *.png *.ecw "
                 "*.sid);;All files (*.*)")


class OptimiseImageryDialog(QDialog):
    def __init__(self, parent=None, iface=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Optimise Imagery for Field")
        self.setMinimumWidth(600)

        self._task = None
        self._info = None
        self._source = None
        self._output_touched = False

        layout = QVBoxLayout()

        header = QLabel(
            "<b>Repack large imagery for the field &mdash; without losing "
            "resolution</b><br>"
            "Overview pyramids are always added; very large images are "
            "split into same-resolution tiles, which QField handles far "
            "better than one enormous file.")
        header.setWordWrap(True)
        layout.addWidget(header)

        # --- source --------------------------------------------------
        src_group = QGroupBox("Imagery")
        src_group.setStyleSheet(theme.group_box_style())
        src_layout = QVBoxLayout()
        row = QHBoxLayout()
        self.source_combo = QComboBox()
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        row.addWidget(self.source_combo, 1)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_source)
        row.addWidget(browse)
        src_layout.addLayout(row)
        self.source_caption = QLabel("Select a raster")
        self.source_caption.setStyleSheet("color: #666; padding: 2px;")
        self.source_caption.setWordWrap(True)
        src_layout.addWidget(self.source_caption)
        src_group.setLayout(src_layout)
        layout.addWidget(src_group)

        # --- how -----------------------------------------------------
        opt_group = QGroupBox("Compression")
        opt_group.setStyleSheet(theme.group_box_style())
        opt_layout = QVBoxLayout()
        prof_row = QHBoxLayout()
        prof_row.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        for key in core.PROFILE_ORDER:
            self.profile_combo.addItem(core.profile_label(key), key)
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        prof_row.addWidget(self.profile_combo, 1)
        opt_layout.addLayout(prof_row)
        self.profile_note = QLabel("")
        self.profile_note.setWordWrap(True)
        self.profile_note.setStyleSheet("color: #666; padding: 2px;")
        opt_layout.addWidget(self.profile_note)
        opt_group.setLayout(opt_layout)
        layout.addWidget(opt_group)

        tile_group = QGroupBox("Tiling")
        tile_group.setStyleSheet(theme.group_box_style())
        tile_layout = QVBoxLayout()
        tile_row = QHBoxLayout()
        self.tile_check = QCheckBox("Split large images into tiles")
        self.tile_check.setToolTip(
            "QField pans and zooms more smoothly across several moderate "
            "tiles than one very large image. Resolution is unchanged.")
        self.tile_check.toggled.connect(self._update_preview)
        tile_row.addWidget(self.tile_check)
        tile_row.addWidget(QLabel("Aim for about"))
        self.tile_spin = QDoubleSpinBox()
        self.tile_spin.setRange(5.0, 2000.0)
        self.tile_spin.setDecimals(0)
        self.tile_spin.setSingleStep(25.0)
        self.tile_spin.setValue(core.DEFAULT_TILE_MB)
        self.tile_spin.setSuffix(" MB per tile")
        self.tile_spin.valueChanged.connect(self._update_preview)
        tile_row.addWidget(self.tile_spin)
        tile_row.addStretch()
        tile_layout.addLayout(tile_row)
        tile_group.setLayout(tile_layout)
        layout.addWidget(tile_group)

        # --- output --------------------------------------------------
        out_group = QGroupBox("Output Folder")
        out_group.setStyleSheet(theme.group_box_style())
        out_layout = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.textEdited.connect(self._output_edited)
        out_layout.addWidget(self.output_edit, 1)
        browse_out = QPushButton("Browse...")
        browse_out.clicked.connect(self._browse_output)
        out_layout.addWidget(browse_out)
        out_group.setLayout(out_layout)
        layout.addWidget(out_group)

        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet(
            "color: #1a6b3c; padding: 4px; font-weight: bold;")
        layout.addWidget(self.preview_label)

        # --- progress ------------------------------------------------
        prog_group = QGroupBox("Progress")
        prog_group.setStyleSheet(theme.group_box_style())
        prog_layout = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        prog_layout.addWidget(self.progress_bar)
        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        prog_layout.addWidget(self.status_label)
        prog_group.setLayout(prog_layout)
        layout.addWidget(prog_group)

        button_row = QHBoxLayout()
        self.run_button = QPushButton("Optimise")
        self.run_button.clicked.connect(self._run)
        button_row.addWidget(self.run_button, 1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        button_row.addWidget(self.cancel_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self.setLayout(layout)
        self._restore_settings()
        self._populate_sources()
        self._profile_changed()

    # -------------------------------------------------------- settings

    def _restore_settings(self):
        settings = QgsSettings()
        geometry = settings.value(SETTING_GEOMETRY)
        if geometry is not None:
            self.restoreGeometry(geometry)
        profile = settings.value(SETTING_PROFILE, core.DEFAULT_PROFILE, str)
        idx = self.profile_combo.findData(profile)
        if idx < 0:
            idx = self.profile_combo.findData(core.DEFAULT_PROFILE)
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentIndex(max(0, idx))
        self.profile_combo.blockSignals(False)
        self.tile_check.blockSignals(True)
        self.tile_check.setChecked(settings.value(SETTING_TILING, True, bool))
        self.tile_check.blockSignals(False)
        self.tile_spin.blockSignals(True)
        self.tile_spin.setValue(
            settings.value(SETTING_TILE_MB, core.DEFAULT_TILE_MB, float))
        self.tile_spin.blockSignals(False)

    def _save_settings(self):
        settings = QgsSettings()
        settings.setValue(SETTING_GEOMETRY, self.saveGeometry())
        settings.setValue(SETTING_PROFILE, self.profile_combo.currentData())
        settings.setValue(SETTING_TILING, self.tile_check.isChecked())
        settings.setValue(SETTING_TILE_MB, self.tile_spin.value())

    def closeEvent(self, event):
        self._save_settings()
        super().closeEvent(event)

    # ---------------------------------------------------------- source

    def _populate_sources(self):
        try:
            from ..z_filter.auto_layers import detect_raster_layers
        except ImportError:
            from z_filter.auto_layers import detect_raster_layers
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItem("Select imagery...", None)
        for row in detect_raster_layers(QgsProject.instance()):
            layer = row['layer']
            path = self._layer_path(layer)
            if path:
                self.source_combo.addItem(layer.name(), path)
        self.source_combo.blockSignals(False)
        if self.source_combo.count() == 2:
            self.source_combo.setCurrentIndex(1)

    @staticmethod
    def _layer_path(layer):
        """A plain file path for a raster layer, or None if it has none."""
        source = layer.source()
        if not source:
            return None
        # Drop any provider suffix (|option=value) and reject non-files.
        path = source.split('|')[0]
        return path if os.path.isfile(path) else None

    def _browse_source(self):
        path, _f = QFileDialog.getOpenFileName(
            self, "Select imagery", self.output_edit.text() or "",
            SOURCE_FILTER)
        if not path:
            return
        idx = self.source_combo.findData(path)
        if idx < 0:
            self.source_combo.addItem(os.path.basename(path), path)
            idx = self.source_combo.count() - 1
        self.source_combo.setCurrentIndex(idx)

    def _source_changed(self, _index):
        self._source = self.source_combo.currentData()
        self._info = None
        if not self._source:
            self.source_caption.setText("Select a raster")
            self.preview_label.setText("")
            return
        try:
            self._info = core.raster_info(self._source)
        except Exception as exc:
            self.source_caption.setText("Could not read: {0}".format(exc))
            self.preview_label.setText("")
            return
        info = self._info
        warn = ("  ⚠ no overview pyramids"
                if not info['overviews'] else "")
        self.source_caption.setText(
            "{0} · {1} × {2} · {3} band{4} · {5} "
            "· {6} overviews{7}".format(
                core.human_mb(info['bytes']), info['width'], info['height'],
                info['bands'], "" if info['bands'] == 1 else "s",
                info['compression'], info['overviews'], warn))
        if not self._output_touched:
            self.output_edit.setText(core.default_output_dir(self._source))
        self._update_preview()

    # ------------------------------------------------------- preview

    def _profile_changed(self, _index=None):
        self.profile_note.setText(
            core.profile_note(self.profile_combo.currentData()))
        self._update_preview()

    def _update_preview(self, *_args):
        if not self._info:
            self.preview_label.setText("")
            return
        profile = self.profile_combo.currentData()
        rows, cols = core.tile_grid(
            self._info, profile, self.tile_spin.value(),
            self.tile_check.isChecked())
        estimate = core.estimate_output_bytes(self._info, profile)
        count = rows * cols
        shape = ("a single file" if count == 1
                 else "{0} tiles ({1}×{2})".format(count, rows, cols))
        source_bytes = self._info['bytes'] or 0
        factor = (" · about {0:.0f}× smaller".format(
            source_bytes / float(estimate))
            if estimate and source_bytes > estimate else "")
        self.preview_label.setText(
            "Estimate: about {0} as {1}{2}".format(
                core.human_mb(estimate), shape, factor))

    def _output_edited(self, _text):
        self._output_touched = True

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(
            self, "Output folder", self.output_edit.text() or "")
        if path:
            self.output_edit.setText(path)
            self._output_touched = True

    # ------------------------------------------------------------ run

    def _set_running(self, running):
        for widget in (self.source_combo, self.profile_combo,
                       self.tile_check, self.tile_spin, self.output_edit,
                       self.run_button):
            widget.setEnabled(not running)
        self.cancel_button.setEnabled(running)

    def _run(self):
        if not self._source or not os.path.isfile(self._source):
            QMessageBox.warning(self, "Optimise Imagery",
                                "Select a raster first.")
            return
        out_dir = self.output_edit.text().strip()
        if not out_dir or not os.path.isdir(out_dir):
            QMessageBox.warning(self, "Optimise Imagery",
                                "Choose an existing output folder.")
            return

        src = self._source
        profile = self.profile_combo.currentData()
        tile_mb = self.tile_spin.value()
        tiling = self.tile_check.isChecked()

        self._set_running(True)
        self.status_label.setText("Starting...")
        self._task = run_in_task(
            "Optimising imagery",
            lambda cb: core.optimise_raster(
                src, out_dir, profile=profile, tile_mb=tile_mb,
                tiling=tiling, progress_cb=cb),
            on_finished=self._on_done,
            on_error=self._on_error,
            on_cancelled=self._on_cancelled,
            owner=self, bar=self.progress_bar, label=self.status_label)

    def _cancel(self):
        if self._task is not None:
            self._task.cancel()

    def _on_done(self, result):
        self._task = None
        self._set_running(False)

        outputs = result['outputs']
        added = self._add_to_project(result)
        saved = result['source_bytes'] - result['output_bytes']
        factor = (result['source_bytes'] / float(result['output_bytes'])
                  if result['output_bytes'] else 0)
        self.status_label.setText(
            "{0} → {1} ({2:.1f}× smaller, {3} saved) as {4} "
            "file{5}; {6} added to the project.".format(
                core.human_mb(result['source_bytes']),
                core.human_mb(result['output_bytes']), factor,
                core.human_mb(saved), len(outputs),
                "" if len(outputs) == 1 else "s", added))
        self._save_settings()

    def _add_to_project(self, result):
        """Load the outputs, tiles inside one group so the QField export
        treats them as a single imagery layer rather than N of them."""
        project = QgsProject.instance()
        outputs = result['outputs']
        layers = []
        for item in outputs:
            layer = QgsRasterLayer(item['path'], item['name'])
            if layer.isValid():
                layers.append(layer)
            else:
                QgsMessageLog.logMessage(
                    "Optimised raster would not load: " + item['path'],
                    'Linear Geoscience', Qgis.MessageLevel.Warning)
        if not layers:
            return 0
        if len(layers) == 1:
            project.addMapLayer(layers[0])
            return 1
        group = project.layerTreeRoot().insertGroup(0, result['group_name'])
        for layer in layers:
            project.addMapLayer(layer, False)
            group.addLayer(layer)
        return len(layers)

    def _on_error(self, exc, tb_str):
        self._task = None
        self._set_running(False)
        self.status_label.setText("Failed: {0}".format(exc))
        QgsMessageLog.logMessage(
            "Imagery optimisation failed:\n" + tb_str,
            'Linear Geoscience', Qgis.MessageLevel.Critical)
        QMessageBox.critical(self, "Optimise Imagery",
                             "Optimisation failed:\n{0}".format(exc))

    def _on_cancelled(self):
        self._task = None
        self._set_running(False)
        self.status_label.setText("Cancelled")


def run(iface):
    dialog = OptimiseImageryDialog(iface.mainWindow(), iface)
    dialog.exec()
