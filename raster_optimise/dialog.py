"""Dialog for repacking large imagery so it performs in the field."""

import os
import shutil

from qgis.PyQt.QtGui import QColor
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
    QRadioButton,
    QVBoxLayout,
)
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsMessageLog,
    QgsProject,
    QgsRasterLayer,
    QgsSettings,
)
from qgis.gui import QgsRubberBand

try:
    from . import core
    from .aoi_draw import AoiDrawTool
    from ..lgs_tasks import run_in_task
except ImportError:  # loaded outside the plugin package
    from raster_optimise import core
    from raster_optimise.aoi_draw import AoiDrawTool
    from lgs_tasks import run_in_task

try:
    from .. import plugin_theme as theme
except ImportError:
    import plugin_theme as theme

SETTINGS_PREFIX = "LinearGeosciencePlugin/RasterOptimise/"
SETTING_PROFILE = SETTINGS_PREFIX + "profile"
SETTING_TILING = SETTINGS_PREFIX + "tiling"
SETTING_TILE_MB = SETTINGS_PREFIX + "tileMb"
SETTING_COVERAGE = SETTINGS_PREFIX + "coverage"
SETTING_GEOMETRY = SETTINGS_PREFIX + "dialogGeometry"

# The user's stated device budget; the estimate turns amber past this.
BUDGET_WARN_BYTES = 30e9

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
        self._aoi_geoms = []      # QgsGeometry, in canvas CRS at draw time
        self._aoi_band = None     # persistent band showing finished areas
        self._draw_tool = None
        self._prev_tool = None

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

        # --- coverage ------------------------------------------------
        cov_group = QGroupBox("Coverage")
        cov_group.setStyleSheet(theme.group_box_style())
        cov_layout = QVBoxLayout()
        self.whole_radio = QRadioButton("Whole image")
        self.whole_radio.setChecked(True)
        self.whole_radio.toggled.connect(self._coverage_changed)
        cov_layout.addWidget(self.whole_radio)
        self.aoi_radio = QRadioButton(
            "Full detail inside drawn areas + whole-image context")
        self.aoi_radio.setToolTip(
            "Draw one or more polygons on the map. Those areas keep full "
            "resolution; the rest of the image travels as one small "
            "downsampled context layer, so zoomed-out views still show "
            "imagery everywhere.")
        cov_layout.addWidget(self.aoi_radio)
        aoi_row = QHBoxLayout()
        self.draw_button = QPushButton("Draw areas on map")
        self.draw_button.clicked.connect(self._toggle_drawing)
        aoi_row.addWidget(self.draw_button)
        self.clear_aoi_button = QPushButton("Clear")
        self.clear_aoi_button.clicked.connect(self._clear_aoi)
        aoi_row.addWidget(self.clear_aoi_button)
        aoi_row.addStretch()
        cov_layout.addLayout(aoi_row)
        self.aoi_caption = QLabel("")
        self.aoi_caption.setWordWrap(True)
        self.aoi_caption.setStyleSheet("color: #666; padding: 2px;")
        cov_layout.addWidget(self.aoi_caption)
        cov_group.setLayout(cov_layout)
        layout.addWidget(cov_group)

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
        self._coverage_changed()

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
        if settings.value(SETTING_COVERAGE, 'whole', str) == 'aoi':
            self.aoi_radio.blockSignals(True)
            self.aoi_radio.setChecked(True)
            self.aoi_radio.blockSignals(False)

    def _save_settings(self):
        settings = QgsSettings()
        settings.setValue(SETTING_GEOMETRY, self.saveGeometry())
        settings.setValue(SETTING_PROFILE, self.profile_combo.currentData())
        settings.setValue(SETTING_TILING, self.tile_check.isChecked())
        settings.setValue(SETTING_TILE_MB, self.tile_spin.value())
        settings.setValue(
            SETTING_COVERAGE,
            'aoi' if self.aoi_radio.isChecked() else 'whole')

    def closeEvent(self, event):
        # The dialog survives close() (non-modal, re-shown on reopen),
        # so drop the drawn areas too — a hidden dialog must not leave
        # rubber bands on the canvas or claim areas it no longer shows.
        self._stop_drawing()
        self._clear_aoi()
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
            message = "Could not read: {0}".format(exc)
            ext = os.path.splitext(self._source)[1].lower()
            if ext in ('.ecw', '.sid'):
                message += (
                    "  This QGIS install may have no {0} driver — open "
                    "the file in a build that includes it (the OSGeo4W "
                    "LTR install does).".format(
                        "ECW" if ext == '.ecw' else "MrSID"))
            self.source_caption.setText(message)
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
        self._refresh_aoi_caption()
        self._update_preview()

    # ---------------------------------------------------------- AOI

    def _canvas(self):
        return self.iface.mapCanvas() if self.iface else None

    def _coverage_changed(self, _checked=None):
        aoi = self.aoi_radio.isChecked()
        for widget in (self.draw_button, self.clear_aoi_button,
                       self.aoi_caption):
            widget.setEnabled(aoi)
        if not aoi:
            self._stop_drawing()
        self._refresh_aoi_caption()
        self._update_preview()

    def _toggle_drawing(self):
        if self._draw_tool is not None:
            self._stop_drawing()
        else:
            self._start_drawing()

    def _start_drawing(self):
        canvas = self._canvas()
        if canvas is None:
            return
        self._prev_tool = canvas.mapTool()
        self._draw_tool = AoiDrawTool(canvas)
        self._draw_tool.polygon_completed.connect(self._polygon_drawn)
        self._draw_tool.finished.connect(self._stop_drawing)
        canvas.setMapTool(self._draw_tool)
        self.draw_button.setText("Finish drawing")
        self.aoi_caption.setText(
            "Left-click to add points, right-click to close each area; "
            "Esc or Finish when done.")

    def _stop_drawing(self):
        canvas = self._canvas()
        if self._draw_tool is not None and canvas is not None:
            if canvas.mapTool() is self._draw_tool:
                if self._prev_tool is not None:
                    canvas.setMapTool(self._prev_tool)
                else:
                    canvas.unsetMapTool(self._draw_tool)
            self._draw_tool.deactivate()
        self._draw_tool = None
        self._prev_tool = None
        self.draw_button.setText("Draw areas on map")
        self._refresh_aoi_caption()

    def _polygon_drawn(self, geometry):
        canvas = self._canvas()
        if canvas is None:
            return
        self._aoi_geoms.append(geometry)
        if self._aoi_band is None:
            self._aoi_band = QgsRubberBand(canvas,
                                           Qgis.GeometryType.Polygon)
            self._aoi_band.setFillColor(QColor(207, 157, 40, 40))
            self._aoi_band.setStrokeColor(QColor(207, 157, 40, 200))
            self._aoi_band.setWidth(2)
        self._aoi_band.addGeometry(geometry)
        self._refresh_aoi_caption()
        self._update_preview()

    def _clear_aoi(self):
        self._aoi_geoms = []
        self._discard_aoi_band()
        self._refresh_aoi_caption()
        self._update_preview()

    def _discard_aoi_band(self):
        if self._aoi_band is not None:
            # Reset before discarding: a band removed while holding
            # geometry can reappear on the next canvas refresh.
            self._aoi_band.reset(Qgis.GeometryType.Polygon)
            canvas = self._canvas()
            if canvas is not None:
                canvas.scene().removeItem(self._aoi_band)
            self._aoi_band = None

    def _refresh_aoi_caption(self):
        if self._draw_tool is not None:
            return  # the drawing hint is showing
        if not self.aoi_radio.isChecked():
            self.aoi_caption.setText("")
            return
        count = len(self._aoi_geoms)
        if not count:
            self.aoi_caption.setText("No areas drawn yet.")
            return
        text = "{0} area{1} drawn".format(count, "" if count == 1 else "s")
        if self._info:
            _w, _h, factor = core.context_shape(
                self._info, self.profile_combo.currentData())
            pixel = abs(self._info['geotransform'][1]) * factor
            text += " · context pixel ≈ {0:.2g} m".format(pixel)
        self.aoi_caption.setText(text)

    def _aoi_rings(self):
        """Drawn polygons as plain ring lists in the raster's CRS."""
        if not self._info or not self._aoi_geoms:
            return []
        canvas = self._canvas()
        rings = []
        transform = None
        if canvas is not None and self._info.get('crs_wkt'):
            src_crs = canvas.mapSettings().destinationCrs()
            dst_crs = QgsCoordinateReferenceSystem.fromWkt(
                self._info['crs_wkt'])
            if (src_crs.isValid() and dst_crs.isValid()
                    and src_crs != dst_crs):
                transform = QgsCoordinateTransform(
                    src_crs, dst_crs, QgsProject.instance())
        for geometry in self._aoi_geoms:
            geom = QgsGeometry(geometry)
            if transform is not None:
                # 0 on older QGIS, a Qgis.GeometryOperationResult on
                # newer; never int() a Qt6 enum (it raises).
                result = geom.transform(transform)
                if result not in (0, Qgis.GeometryOperationResult.Success):
                    continue
            for part in geom.asMultiPolygon() or [geom.asPolygon()]:
                if part and part[0]:
                    rings.append([(p.x(), p.y()) for p in part[0]])
        return rings

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
        if self.aoi_radio.isChecked():
            self._update_aoi_preview(profile)
            return
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
        self._set_preview(
            "Estimate: about {0} as {1}{2}".format(
                core.human_mb(estimate), shape, factor),
            over_budget=estimate > BUDGET_WARN_BYTES)

    def _update_aoi_preview(self, profile):
        rings = self._aoi_rings()
        if not rings:
            self._set_preview("Draw at least one area on the map to see "
                              "an estimate.", over_budget=False)
            return
        try:
            windows, tile_bytes, context_bytes = (
                core.estimate_aoi_output_bytes(
                    self._info, rings, profile, self.tile_spin.value(),
                    self.tile_check.isChecked()))
        except ValueError as exc:
            self._set_preview(str(exc), over_budget=True)
            return
        total = tile_bytes + context_bytes
        text = ("Estimate: {0} full-res tile{1} ≈ {2} + context ≈ {3} "
                "(total ≈ {4})".format(
                    len(windows), "" if len(windows) == 1 else "s",
                    core.human_mb(tile_bytes),
                    core.human_mb(context_bytes), core.human_mb(total)))
        if total > BUDGET_WARN_BYTES:
            text += " — over the 30 GB device budget; draw smaller areas"
        self._set_preview(text, over_budget=total > BUDGET_WARN_BYTES)

    def _set_preview(self, text, over_budget=False):
        self.preview_label.setStyleSheet(
            "color: {0}; padding: 4px; font-weight: bold;".format(
                "#a15c00" if over_budget else "#1a6b3c"))
        self.preview_label.setText(text)

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
                       self.run_button, self.whole_radio, self.aoi_radio,
                       self.draw_button, self.clear_aoi_button):
            widget.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        if not running:
            self._coverage_changed()  # re-apply the AOI enable states

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

        aoi_rings = None
        estimate = core.estimate_output_bytes(self._info, profile)
        if self.aoi_radio.isChecked():
            self._stop_drawing()
            aoi_rings = self._aoi_rings()
            if not aoi_rings:
                QMessageBox.warning(
                    self, "Optimise Imagery",
                    "Draw at least one area on the map first.")
                return
            try:
                _w, tile_bytes, context_bytes = (
                    core.estimate_aoi_output_bytes(
                        self._info, aoi_rings, profile, tile_mb, tiling))
                estimate = tile_bytes + context_bytes
            except ValueError as exc:
                QMessageBox.warning(self, "Optimise Imagery", str(exc))
                return

        if not self._enough_disk(out_dir, estimate, tile_mb):
            return

        self._set_running(True)
        self.status_label.setText("Starting...")
        self._task = run_in_task(
            "Optimising imagery",
            lambda cb: core.optimise_raster(
                src, out_dir, profile=profile, tile_mb=tile_mb,
                tiling=tiling, progress_cb=cb, aoi_polygons=aoi_rings,
                context_target_mb=core.CONTEXT_TARGET_MB),
            on_finished=self._on_done,
            on_error=self._on_error,
            on_cancelled=self._on_cancelled,
            owner=self, bar=self.progress_bar, label=self.status_label)

    def _enough_disk(self, out_dir, estimate, tile_mb):
        """Warn (not block) when the output folder looks too small.

        The COG driver writes a temporary copy per file, so the peak is
        roughly the running total plus two of the largest tile.
        """
        try:
            free = shutil.disk_usage(out_dir).free
        except OSError:
            return True
        needed = estimate * 1.2 + tile_mb * 2e6
        if free >= needed:
            return True
        answer = QMessageBox.question(
            self, "Optimise Imagery",
            "The output folder has {0} free but this run may need about "
            "{1}. Continue anyway?".format(
                core.human_mb(free), core.human_mb(needed)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

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


_dialog = None


def run(iface):
    # Non-modal, so the canvas still takes clicks while the user draws
    # areas of interest (a modal exec() would swallow them).
    global _dialog
    if _dialog is not None:
        try:
            _dialog.show()
            _dialog.raise_()
            _dialog.activateWindow()
            return
        except RuntimeError:  # underlying C++ object deleted
            _dialog = None
    _dialog = OptimiseImageryDialog(iface.mainWindow(), iface)
    _dialog.destroyed.connect(_forget_dialog)
    _dialog.show()


def _forget_dialog(*_args):
    global _dialog
    _dialog = None
