"""Dialog for rasterizing a Surpac/DXF pit surface into a DEM GeoTIFF."""

import os

from qgis.PyQt.QtWidgets import (
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
    from . import surface_dem, terrain
    from ..lgs_tasks import run_in_task
    from ..mining_import import settings_store
except ImportError:  # loaded outside the plugin package
    from view3d import surface_dem, terrain
    from lgs_tasks import run_in_task
    from mining_import import settings_store

try:
    from .. import plugin_theme as theme
except ImportError:
    import plugin_theme as theme

SETTINGS_PREFIX = "LinearGeosciencePlugin/View3D/"
SETTING_SURF_GEOMETRY = SETTINGS_PREFIX + "surfaceDialogGeometry"

SOURCE_FILTER = ("Pit surfaces (*.str *.dxf);;Surpac strings (*.str);;"
                 "AutoCAD DXF (*.dxf);;All files (*.*)")


class SurfaceDemDialog(QDialog):
    def __init__(self, parent=None, iface=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Pit Surface to DEM")
        self.setMinimumWidth(560)

        self._task = None
        self._output_touched = False

        layout = QVBoxLayout()

        header = QLabel(
            "<b>Rasterize a triangulated pit surface into a DEM</b><br>"
            "Surpac .str/.dtm and DXF pit shells become a GeoTIFF that "
            "QField's 3D map view drapes your mapping onto in the field.")
        header.setWordWrap(True)
        layout.addWidget(header)

        src_group = QGroupBox("Pit Surface")
        src_group.setStyleSheet(theme.group_box_style())
        src_layout = QHBoxLayout()
        self.source_edit = QLineEdit()
        self.source_edit.textChanged.connect(self._source_changed)
        src_layout.addWidget(self.source_edit, 1)
        browse_src = QPushButton("Browse...")
        browse_src.clicked.connect(self._browse_source)
        src_layout.addWidget(browse_src)
        src_group.setLayout(src_layout)
        layout.addWidget(src_group)

        cell_group = QGroupBox("Grid")
        cell_group.setStyleSheet(theme.group_box_style())
        cell_layout = QHBoxLayout()
        cell_layout.addWidget(QLabel("Cell size:"))
        self.cell_spin = QDoubleSpinBox()
        self.cell_spin.setRange(0.0, 100.0)
        self.cell_spin.setDecimals(2)
        self.cell_spin.setValue(0.0)
        self.cell_spin.setSuffix(" m")
        self.cell_spin.setSpecialValueText("Auto")
        cell_layout.addWidget(self.cell_spin)
        note = QLabel("Auto = half the median triangle edge")
        note.setStyleSheet("color: #666; padding: 2px;")
        cell_layout.addWidget(note)
        cell_layout.addStretch()
        cell_group.setLayout(cell_layout)
        layout.addWidget(cell_group)

        out_group = QGroupBox("Output GeoTIFF")
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

        button_row = QHBoxLayout()
        self.run_button = QPushButton("Create DEM")
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

        settings = QgsSettings()
        geometry = settings.value(SETTING_SURF_GEOMETRY)
        if geometry is not None:
            self.restoreGeometry(geometry)

    def closeEvent(self, event):
        QgsSettings().setValue(SETTING_SURF_GEOMETRY, self.saveGeometry())
        super().closeEvent(event)

    # ------------------------------------------------------------ inputs

    def _browse_source(self):
        start = settings_store.get(settings_store.KEY_LAST_FOLDER, "")
        path, _filter = QFileDialog.getOpenFileName(
            self, "Select pit surface", start, SOURCE_FILTER)
        if path:
            self.source_edit.setText(path)
            settings_store.put(settings_store.KEY_LAST_FOLDER,
                               os.path.dirname(path))

    def _source_changed(self, text):
        path = text.strip()
        if path and not self._output_touched:
            self.output_edit.setText(surface_dem.default_output_path(path))

    def _output_edited(self, _text):
        self._output_touched = True

    def _browse_output(self):
        start = self.output_edit.text() or ""
        path, _filter = QFileDialog.getSaveFileName(
            self, "Save DEM as", start, "GeoTIFF (*.tif)")
        if not path:
            return
        if not path.lower().endswith((".tif", ".tiff")):
            path += ".tif"
        self.output_edit.setText(path)
        self._output_touched = True

    # --------------------------------------------------------------- run

    def _set_running(self, running):
        for widget in (self.source_edit, self.cell_spin, self.output_edit,
                       self.run_button):
            widget.setEnabled(not running)
        self.cancel_button.setEnabled(running)

    def _run(self):
        source = self.source_edit.text().strip()
        if not source or not os.path.isfile(source):
            QMessageBox.warning(self, "Pit Surface to DEM",
                                "Select a Surpac .str or DXF file first.")
            return
        out_path = self.output_edit.text().strip()
        if not out_path:
            QMessageBox.warning(self, "Pit Surface to DEM",
                                "Choose an output GeoTIFF path.")
            return
        out_dir = os.path.dirname(out_path)
        if out_dir and not os.path.isdir(out_dir):
            QMessageBox.warning(self, "Pit Surface to DEM",
                                "Output folder does not exist:\n" + out_dir)
            return

        cell = self.cell_spin.value() or None  # 0 = Auto
        # Surpac/DXF carry no CRS; assume the project CRS, the same
        # assumption the mining importer makes.
        crs_wkt = QgsProject.instance().crs().toWkt()

        self._set_running(True)
        self.status_label.setText("Starting...")
        self._task = run_in_task(
            "Rasterizing pit surface",
            lambda cb: surface_dem.rasterize_to_geotiff(
                source, out_path, cell_size=cell, crs_wkt=crs_wkt,
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

        layer = QgsRasterLayer(result['path'],
                               os.path.basename(result['path']))
        if not layer.isValid():
            self.status_label.setText(
                "DEM written, but the layer failed to load: "
                + result['path'])
            return
        # The role stamp is what makes the 3D view auto-prefer this DEM.
        layer.setCustomProperty(terrain.ROLE_PROPERTY,
                                surface_dem.METADATA_ROLE_PIT)
        QgsProject.instance().addMapLayer(layer)

        self.status_label.setText(
            "{0} x {1} cells at {2:g} m from {3} triangles"
            " ({4} filled) — added to the project".format(
                result['cols'], result['rows'], result['cell_size'],
                result['triangles'], result['filled']))
        for warning in result.get('warnings', []):
            QgsMessageLog.logMessage(
                "Pit Surface to DEM: " + warning,
                'Linear Geoscience', Qgis.MessageLevel.Warning)

    def _on_error(self, exc, tb_str):
        self._task = None
        self._set_running(False)
        self.status_label.setText("Failed: {0}".format(exc))
        QgsMessageLog.logMessage(
            "Pit surface rasterization failed:\n" + tb_str,
            'Linear Geoscience', Qgis.MessageLevel.Critical)
        QMessageBox.critical(self, "Pit Surface to DEM",
                             "Rasterization failed:\n{0}".format(exc))

    def _on_cancelled(self):
        self._task = None
        self._set_running(False)
        self.status_label.setText("Cancelled")


def run(iface):
    dialog = SurfaceDemDialog(iface.mainWindow(), iface)
    dialog.exec()
