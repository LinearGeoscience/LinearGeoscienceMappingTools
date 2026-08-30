"""Dialog for generating cartographically styled contours from a DEM."""

import os

from qgis.PyQt.QtWidgets import (
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
    QSpinBox,
    QVBoxLayout,
)
from qgis.core import Qgis, QgsMessageLog, QgsProject, QgsSettings, QgsVectorLayer

try:
    from . import core, styling
    from ..lgs_tasks import run_in_task
except ImportError:  # loaded outside the plugin package
    from contours import core, styling
    from lgs_tasks import run_in_task

try:
    from .. import plugin_theme as theme
except ImportError:
    import plugin_theme as theme

SETTINGS_PREFIX = "LinearGeosciencePlugin/Contours/"
SETTING_SCHEME = SETTINGS_PREFIX + "scheme"
SETTING_SMOOTHING = SETTINGS_PREFIX + "smoothing"
SETTING_MAJOR_EVERY = SETTINGS_PREFIX + "majorEvery"
SETTING_GEOMETRY = SETTINGS_PREFIX + "dialogGeometry"

SMOOTHING_LEVELS = [
    ("off", "Off"),
    ("light", "Light"),
    ("medium", "Medium"),
    ("strong", "Strong"),
]


class ContoursDialog(QDialog):
    def __init__(self, parent=None, iface=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Generate Contours")
        self.setMinimumWidth(560)

        self._task = None
        self._stats = None
        self._dem_path = None
        self._intervals_touched = False
        self._output_touched = False

        layout = QVBoxLayout()

        header = QLabel(
            "<b>Generate smooth, styled contours from a DEM</b><br>"
            "Contours are written to their own GeoPackage and added to the "
            "project, styled and labelled.")
        header.setWordWrap(True)
        layout.addWidget(header)

        # --- DEM source -------------------------------------------------
        dem_group = QGroupBox("Elevation Model")
        dem_group.setStyleSheet(theme.group_box_style())
        dem_layout = QVBoxLayout()

        dem_row = QHBoxLayout()
        self.dem_combo = QComboBox()
        self.dem_combo.currentIndexChanged.connect(self._dem_changed)
        dem_row.addWidget(self.dem_combo, 1)
        browse_dem = QPushButton("Browse...")
        browse_dem.clicked.connect(self._browse_dem)
        dem_row.addWidget(browse_dem)
        dem_layout.addLayout(dem_row)

        self.dem_caption = QLabel("Select a DEM raster")
        self.dem_caption.setStyleSheet("color: #666; padding: 2px;")
        dem_layout.addWidget(self.dem_caption)

        self.crs_note = QLabel(
            "DEM is in geographic degrees — intervals are still vertical "
            "metres; the output stays in the DEM's CRS.")
        self.crs_note.setWordWrap(True)
        self.crs_note.setStyleSheet("color: #b8860b; padding: 2px;")
        self.crs_note.hide()
        dem_layout.addWidget(self.crs_note)

        dem_group.setLayout(dem_layout)
        layout.addWidget(dem_group)

        # --- Intervals --------------------------------------------------
        int_group = QGroupBox("Contour Intervals")
        int_group.setStyleSheet(theme.group_box_style())
        int_layout = QVBoxLayout()

        spin_row = QHBoxLayout()
        spin_row.addWidget(QLabel("Minor interval:"))
        self.minor_spin = QDoubleSpinBox()
        self.minor_spin.setRange(0.1, 1000.0)
        self.minor_spin.setDecimals(1)
        self.minor_spin.setValue(10.0)
        self.minor_spin.setSuffix(" m")
        self.minor_spin.valueChanged.connect(self._intervals_edited)
        spin_row.addWidget(self.minor_spin)
        spin_row.addSpacing(16)
        spin_row.addWidget(QLabel("Major every:"))
        self.major_spin = QSpinBox()
        self.major_spin.setRange(2, 10)
        self.major_spin.setValue(5)
        self.major_spin.setSuffix("th")
        self.major_spin.valueChanged.connect(self._intervals_edited)
        spin_row.addWidget(self.major_spin)
        spin_row.addStretch()
        int_layout.addLayout(spin_row)

        self.interval_caption = QLabel("")
        self.interval_caption.setStyleSheet("color: #666; padding: 2px;")
        int_layout.addWidget(self.interval_caption)

        int_group.setLayout(int_layout)
        layout.addWidget(int_group)

        # --- Appearance -------------------------------------------------
        app_group = QGroupBox("Appearance")
        app_group.setStyleSheet(theme.group_box_style())
        app_layout = QHBoxLayout()

        app_layout.addWidget(QLabel("Smoothing:"))
        self.smoothing_combo = QComboBox()
        for key, label in SMOOTHING_LEVELS:
            self.smoothing_combo.addItem(label, key)
        app_layout.addWidget(self.smoothing_combo)
        app_layout.addSpacing(16)
        app_layout.addWidget(QLabel("Style:"))
        self.scheme_combo = QComboBox()
        for key, scheme in styling.SCHEMES.items():
            self.scheme_combo.addItem(scheme["label"], key)
        app_layout.addWidget(self.scheme_combo)
        app_layout.addStretch()

        app_group.setLayout(app_layout)
        layout.addWidget(app_group)

        # --- Output -----------------------------------------------------
        out_group = QGroupBox("Output GeoPackage")
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

        # --- Progress ---------------------------------------------------
        progress_group = QGroupBox("Progress")
        progress_group.setStyleSheet(theme.group_box_style())
        progress_layout = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        progress_layout.addWidget(self.progress_bar)
        self.status_label = QLabel("Ready")
        progress_layout.addWidget(self.status_label)
        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)

        # --- Buttons ----------------------------------------------------
        button_row = QHBoxLayout()
        self.generate_button = QPushButton("Generate Contours")
        self.generate_button.clicked.connect(self._generate)
        button_row.addWidget(self.generate_button, 1)
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
        self._populate_dem_combo()
        self._update_interval_caption()

    # ------------------------------------------------------------ settings

    def _restore_settings(self):
        settings = QgsSettings()
        geometry = settings.value(SETTING_GEOMETRY)
        if geometry is not None:
            self.restoreGeometry(geometry)
        smoothing = settings.value(SETTING_SMOOTHING, "medium", str)
        idx = self.smoothing_combo.findData(smoothing)
        self.smoothing_combo.setCurrentIndex(idx if idx >= 0 else 2)
        scheme = settings.value(SETTING_SCHEME, styling.DEFAULT_SCHEME, str)
        idx = self.scheme_combo.findData(scheme)
        if idx >= 0:
            self.scheme_combo.setCurrentIndex(idx)
        self.major_spin.blockSignals(True)
        self.major_spin.setValue(settings.value(SETTING_MAJOR_EVERY, 5, int))
        self.major_spin.blockSignals(False)

    def _save_settings(self):
        settings = QgsSettings()
        settings.setValue(SETTING_GEOMETRY, self.saveGeometry())
        settings.setValue(SETTING_SMOOTHING, self.smoothing_combo.currentData())
        settings.setValue(SETTING_SCHEME, self.scheme_combo.currentData())
        settings.setValue(SETTING_MAJOR_EVERY, self.major_spin.value())

    def closeEvent(self, event):
        self._save_settings()
        super().closeEvent(event)

    # ------------------------------------------------------------- DEM side

    def _populate_dem_combo(self):
        try:
            from ..z_filter.auto_layers import detect_raster_layers
        except ImportError:
            from z_filter.auto_layers import detect_raster_layers
        self.dem_combo.blockSignals(True)
        self.dem_combo.clear()
        self.dem_combo.addItem("Select a DEM...", None)
        for row in detect_raster_layers(QgsProject.instance()):
            layer = row["layer"]
            self.dem_combo.addItem(layer.name(),
                                   self._gdal_source(layer.source()))
        self.dem_combo.blockSignals(False)
        if self.dem_combo.count() == 2:
            # exactly one candidate: preselect it
            self.dem_combo.setCurrentIndex(1)

    @staticmethod
    def _gdal_source(source):
        # GDAL wants GPKG:path:table for GeoPackage rasters; QGIS may hand
        # back the bare path:table form.
        if ".gpkg" in source.lower() and not source.upper().startswith("GPKG:"):
            return "GPKG:" + source
        return source

    def _browse_dem(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, "Select DEM raster", "",
            "Rasters (*.tif *.tiff *.img *.vrt *.asc);;All files (*.*)")
        if not path:
            return
        idx = self.dem_combo.findData(path)
        if idx < 0:
            self.dem_combo.addItem(os.path.basename(path), path)
            idx = self.dem_combo.count() - 1
        self.dem_combo.setCurrentIndex(idx)

    def _dem_changed(self, _index):
        self._dem_path = self.dem_combo.currentData()
        self._stats = None
        if not self._dem_path:
            self.dem_caption.setText("Select a DEM raster")
            self.crs_note.hide()
            return
        try:
            stats = core.raster_stats(self._dem_path)
        except Exception as exc:  # unreadable/corrupt raster
            self.dem_caption.setText("Could not read raster: {0}".format(exc))
            self.crs_note.hide()
            return
        self._stats = stats
        unit = "°" if stats["is_geographic"] else "m"
        self.dem_caption.setText(
            "Elevation {0:.0f}–{1:.0f} m (range {2:.0f} m) · "
            "pixel ~{3:.4g} {4}".format(
                stats["min"], stats["max"], stats["max"] - stats["min"],
                stats["pixel_x"], unit))
        self.crs_note.setVisible(bool(stats["is_geographic"]))

        if not self._intervals_touched:
            minor, major_every = core.suggest_intervals(stats["min"],
                                                        stats["max"])
            self.minor_spin.blockSignals(True)
            self.minor_spin.setValue(minor)
            self.minor_spin.blockSignals(False)
            self.major_spin.blockSignals(True)
            self.major_spin.setValue(major_every)
            self.major_spin.blockSignals(False)
        if not self._output_touched:
            self.output_edit.setText(core.default_output_path(self._dem_path))
        self._update_interval_caption()

    # ------------------------------------------------------- interval side

    def _intervals_edited(self, _value):
        self._intervals_touched = True
        self._update_interval_caption()

    def _update_interval_caption(self):
        minor = self.minor_spin.value()
        major = minor * self.major_spin.value()
        text = "Major contour every {0:g} m".format(major)
        if self._stats:
            zrange = self._stats["max"] - self._stats["min"]
            if minor > 0 and zrange > 0:
                text += " · ~{0:.0f} minor contours".format(zrange / minor)
        self.interval_caption.setText(text)

    # --------------------------------------------------------- output side

    def _output_edited(self, _text):
        self._output_touched = True

    def _browse_output(self):
        start = self.output_edit.text() or ""
        path, _filter = QFileDialog.getSaveFileName(
            self, "Save contours as", start, "GeoPackage (*.gpkg)")
        if not path:
            return
        if not path.lower().endswith(".gpkg"):
            path += ".gpkg"
        self.output_edit.setText(path)
        self._output_touched = True

    # ---------------------------------------------------------------- run

    def _set_running(self, running):
        for widget in (self.dem_combo, self.minor_spin, self.major_spin,
                       self.smoothing_combo, self.scheme_combo,
                       self.output_edit, self.generate_button):
            widget.setEnabled(not running)
        self.cancel_button.setEnabled(running)

    def _generate(self):
        if not self._dem_path:
            QMessageBox.warning(self, "Generate Contours",
                                "Select a DEM raster first.")
            return
        out_path = self.output_edit.text().strip()
        if not out_path:
            QMessageBox.warning(self, "Generate Contours",
                                "Choose an output GeoPackage path.")
            return
        out_dir = os.path.dirname(out_path)
        if out_dir and not os.path.isdir(out_dir):
            QMessageBox.warning(self, "Generate Contours",
                                "Output folder does not exist:\n" + out_dir)
            return

        dem_path = self._dem_path
        minor = self.minor_spin.value()
        major_every = self.major_spin.value()
        smoothing = self.smoothing_combo.currentData()

        self._set_running(True)
        self.status_label.setText("Starting...")
        self._task = run_in_task(
            "Generating contours",
            lambda cb: core.generate_contours(
                dem_path, minor, major_every, smoothing, out_path,
                progress_cb=cb),
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

        layer = QgsVectorLayer(
            "{0}|layername={1}".format(result["gpkg"], result["layer"]),
            "Contours", "ogr")
        if not layer.isValid():
            self.status_label.setText(
                "Contours written, but the layer failed to load: "
                + result["gpkg"])
            return
        scheme_key = self.scheme_combo.currentData()
        try:
            styling.apply_contour_style(layer, scheme_key)
            styling.persist_style(layer, result["layer"])
        except Exception as exc:  # styling is cosmetic; the data is written
            QgsMessageLog.logMessage(
                "Contour styling failed: {0}".format(exc),
                "Linear Geoscience", Qgis.MessageLevel.Warning)
        QgsProject.instance().addMapLayer(layer)

        self.status_label.setText(
            "{0} contours ({1} major, every {2:g} m) written to {3}".format(
                result["count"], result["majors"],
                result["major_interval"], result["gpkg"]))
        self._save_settings()

    def _on_error(self, exc, tb_str):
        self._task = None
        self._set_running(False)
        self.status_label.setText("Failed: {0}".format(exc))
        QgsMessageLog.logMessage(
            "Contour generation failed:\n" + tb_str,
            "Linear Geoscience", Qgis.MessageLevel.Critical)
        QMessageBox.critical(self, "Generate Contours",
                             "Contour generation failed:\n{0}".format(exc))

    def _on_cancelled(self):
        self._task = None
        self._set_running(False)
        self.status_label.setText("Cancelled")


def run(iface):
    dialog = ContoursDialog(iface.mainWindow(), iface)
    dialog.exec()
