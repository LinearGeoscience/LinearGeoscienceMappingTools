import os
import math
import traceback
import time
from qgis.PyQt.QtWidgets import (QWidget, QDockWidget, QComboBox, QVBoxLayout, QHBoxLayout,
                                 QPushButton, QLabel, QSpinBox, QGroupBox,
                                 QRadioButton, QButtonGroup, QGridLayout,
                                 QMessageBox, QTabWidget, QListWidget,
                                 QDialog, QDialogButtonBox)
from qgis.PyQt.QtCore import Qt, QVariant, pyqtSignal
from qgis.core import (QgsProject, QgsFeature, QgsGeometry, QgsPointXY,
                       QgsField, QgsFields, QgsVectorLayer, QgsRectangle,
                       QgsWkbTypes, QgsMapLayerType, QgsSymbol, QgsRendererCategory,
                       QgsCategorizedSymbolRenderer, QgsPalLayerSettings,
                       QgsTextFormat, QgsTextBufferSettings, QgsVectorLayerSimpleLabeling,
                       Qgis, QgsMessageLog)
from qgis.PyQt.QtGui import QColor
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.utils import iface
try:
    from qgis.PyQt.QtCore import QMetaType
except ImportError:
    QMetaType = None

try:
    from .layer_select import layer_display_name
except ImportError:
    from layer_select import layer_display_name


def create_compatible_field(name, field_type):
    """Create QgsField with QGIS version compatibility"""
    try:
        # Try QGIS 3.34+ syntax first
        if QMetaType and hasattr(QMetaType, 'Type'):
            if field_type == 'string':
                return QgsField(name, QMetaType.Type.QString)
            elif field_type == 'double':
                return QgsField(name, QMetaType.Type.Double)
            elif field_type == 'int':
                return QgsField(name, QMetaType.Type.Int)
        # Fallback for older versions
        if field_type == 'string':
            return QgsField(name, QVariant.String)
        elif field_type == 'double':
            return QgsField(name, QVariant.Double)
        elif field_type == 'int':
            return QgsField(name, QVariant.Int)
    except Exception:
        # Final fallback to QGIS 3.4 syntax
        if field_type == 'string':
            return QgsField(name, QVariant.String)
        elif field_type == 'double':
            return QgsField(name, QVariant.Double)
        elif field_type == 'int':
            return QgsField(name, QVariant.Int)

    # Default fallback
    return QgsField(name, QVariant.String)


class PolygonDrawMapTool(QgsMapTool):
    """Custom map tool for drawing polygons by clicking points on the canvas."""
    polygon_completed = pyqtSignal(QgsGeometry)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.rubber_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self.rubber_band.setColor(QColor(255, 0, 0, 100))
        self.rubber_band.setWidth(2)
        self.points = []

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            point = self.toMapCoordinates(event.pos())
            self.points.append(point)
            self._update_rubber_band()
        elif event.button() == Qt.RightButton:
            if len(self.points) >= 3:
                ring = list(self.points)
                ring.append(ring[0])  # Close the ring
                polygon = QgsGeometry.fromPolygonXY([ring])
                self.polygon_completed.emit(polygon)
            self.points = []
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)

    def canvasMoveEvent(self, event):
        if self.points:
            point = self.toMapCoordinates(event.pos())
            self._update_rubber_band(point)

    def _update_rubber_band(self, current_point=None):
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        points = list(self.points)
        if current_point:
            points.append(current_point)
        for i, pt in enumerate(points):
            self.rubber_band.addPoint(pt, i == len(points) - 1)

    def deactivate(self):
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        self.points = []
        super().deactivate()


class FinalMapSheetPanel(QDockWidget):

    def __init__(self, parent=None):
        try:
            super(FinalMapSheetPanel, self).__init__("MapSheet Generator", parent)
            self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

            # Dictionary of sheet sizes with their dimensions in cm (usable area with 2.5cm margins)
            # Note: These dimensions are in portrait orientation by default (width < height)
            self.sheet_sizes = {
                'A0 (2.5cm margins)': (79.1, 113.9),
                'A1 (2.5cm margins)': (54.4, 79.1),
                'A2 (2.5cm margins)': (37, 54.4),
                'A3 (2.5cm margins)': (24.7, 37),
                'A4 (2.5cm margins)': (16, 24.7)
            }

            # Dictionary of scales and dimensions for each sheet size
            self.dimensions = {}
            self.calculate_dimensions()

            self.preview_layer = None
            self.preview_layer_id = None

            # Cache variables for performance
            self.combined_input_geometry = None
            self.input_layer_id = None

            # Draw tool state
            self.draw_tool = None
            self.drawn_polygons = []  # list of {'geometry': QgsGeometry, 'orientation': str}
            self.previous_map_tool = None

            # Connect to project layer signals
            QgsProject.instance().layersRemoved.connect(self.on_layers_removed)
            QgsProject.instance().layersAdded.connect(self._on_layers_changed)
            QgsProject.instance().layersRemoved.connect(self._on_layers_changed)

            self.setup_ui()
            QgsMessageLog.logMessage("Panel initialized", 'Linear Geoscience', Qgis.Info)

        except Exception as e:
            QgsMessageLog.logMessage(f"Error initializing panel: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)

    def on_layers_removed(self, layer_ids):
        """Handle event when layers are removed from the project"""
        try:
            if self.preview_layer_id in layer_ids:
                QgsMessageLog.logMessage(f"Preview layer was removed externally (ID: {self.preview_layer_id})", 'Linear Geoscience', Qgis.Info)
                self.preview_layer = None
                self.preview_layer_id = None
                self._disable_preview_buttons()
        except Exception as e:
            QgsMessageLog.logMessage(f"Error in layers removed handler: {str(e)}", 'Linear Geoscience', Qgis.Warning)

    def _on_layers_changed(self, *args):
        """Refresh all layer combos when project layers change."""
        try:
            self.populate_layers()
            self.populate_existing_mapsheet_layers()
            self.populate_reference_layers()
            self.populate_merge_layers()
        except Exception as e:
            QgsMessageLog.logMessage(f"Error refreshing layer combos: {str(e)}", 'Linear Geoscience', Qgis.Warning)

    def calculate_dimensions(self):
        """Calculate real-world dimensions for each scale and sheet size"""
        try:
            scales = [
                '1:50', '1:100', '1:250', '1:500', '1:1000',
                '1:2500', '1:5000', '1:10000', '1:25000', '1:100000'
            ]

            for sheet_name, (width_cm, height_cm) in self.sheet_sizes.items():
                self.dimensions[sheet_name] = {}

                for scale in scales:
                    scale_factor = int(scale.split(':')[1])
                    width_m = (width_cm / 100) * scale_factor
                    height_m = (height_cm / 100) * scale_factor
                    self.dimensions[sheet_name][scale] = (width_m, height_m)

            QgsMessageLog.logMessage("Mapsheet dimensions calculated for all scales and sizes", 'Linear Geoscience', Qgis.Info)
        except Exception as e:
            QgsMessageLog.logMessage(f"Error calculating dimensions: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)

    def setup_ui(self):
        """Create the panel UI with tabbed layout"""
        try:
            main_widget = QWidget()
            layout = QVBoxLayout(main_widget)

            # Shared sheet configuration
            self._setup_sheet_config(layout)

            # Tab widget for three modes
            self.tab_widget = QTabWidget()
            self.setup_generate_tab()
            self.setup_draw_tab()
            self.setup_modify_tab()
            layout.addWidget(self.tab_widget)

            # Shared coverage metrics
            self.setup_metrics_section(layout)

            # Shared action buttons
            self.setup_action_buttons(layout)

            # Shared merge section
            self.setup_merge_section(layout)

            self.setWidget(main_widget)
            QgsMessageLog.logMessage("UI setup complete", 'Linear Geoscience', Qgis.Info)

        except Exception as e:
            QgsMessageLog.logMessage(f"Error setting up UI: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)

    def _setup_sheet_config(self, layout):
        """Set up shared sheet configuration controls above tabs."""
        config_group = QGroupBox('Sheet Configuration')
        config_layout = QVBoxLayout()

        # Sheet size
        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel('Sheet Size:'))
        self.size_combo = QComboBox()
        for sheet_size in ['A0 (2.5cm margins)', 'A1 (2.5cm margins)',
                           'A2 (2.5cm margins)', 'A3 (2.5cm margins)',
                           'A4 (2.5cm margins)']:
            self.size_combo.addItem(sheet_size)
        self.size_combo.currentIndexChanged.connect(self.update_scale_combo)
        size_layout.addWidget(self.size_combo)
        config_layout.addLayout(size_layout)

        # Scale
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel('Mapping Scale:'))
        self.scale_combo = QComboBox()
        self.update_scale_combo()
        scale_layout.addWidget(self.scale_combo)
        config_layout.addLayout(scale_layout)

        # Overlap
        overlap_layout = QHBoxLayout()
        overlap_layout.addWidget(QLabel('Overlap (%):'))
        self.overlap_spin = QSpinBox()
        self.overlap_spin.setRange(0, 50)
        self.overlap_spin.setValue(10)
        overlap_layout.addWidget(self.overlap_spin)
        config_layout.addLayout(overlap_layout)

        config_group.setLayout(config_layout)
        layout.addWidget(config_group)

    def setup_generate_tab(self):
        """Tab 1: Generate from Input Layer"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Input layer selection
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel('Input Layer:'))
        self.layer_combo = QComboBox()
        self.populate_layers()
        input_layout.addWidget(self.layer_combo)
        layout.addLayout(input_layout)

        # Orientation radio buttons
        orient_group = QGroupBox('Orientation')
        orient_layout = QVBoxLayout()
        self.orientation_group = QButtonGroup()

        self.landscape_radio = QRadioButton('Landscape (Width > Height)')
        self.landscape_radio.setChecked(True)
        self.orientation_group.addButton(self.landscape_radio, 1)
        orient_layout.addWidget(self.landscape_radio)

        self.portrait_radio = QRadioButton('Portrait (Height > Width)')
        self.orientation_group.addButton(self.portrait_radio, 2)
        orient_layout.addWidget(self.portrait_radio)

        orient_group.setLayout(orient_layout)
        layout.addWidget(orient_group)

        # Generate button
        self.preview_button = QPushButton('Generate Preview')
        self.preview_button.clicked.connect(self.generate_preview)
        layout.addWidget(self.preview_button)

        layout.addStretch()
        self.tab_widget.addTab(tab, "From Input Layer")

    def setup_draw_tab(self):
        """Tab 2: Draw Base Polygons"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Orientation for next polygon
        orient_layout = QHBoxLayout()
        orient_layout.addWidget(QLabel('Next polygon orientation:'))
        self.draw_orientation_combo = QComboBox()
        self.draw_orientation_combo.addItem('Landscape')
        self.draw_orientation_combo.addItem('Portrait')
        orient_layout.addWidget(self.draw_orientation_combo)
        layout.addLayout(orient_layout)

        # Draw toggle button
        self.draw_button = QPushButton('Draw Polygon on Map')
        self.draw_button.setCheckable(True)
        self.draw_button.toggled.connect(self.toggle_draw_mode)
        layout.addWidget(self.draw_button)

        # Status label
        self.draw_status_label = QLabel('')
        self.draw_status_label.setWordWrap(True)
        layout.addWidget(self.draw_status_label)

        # Drawn polygons list
        layout.addWidget(QLabel('Drawn polygons:'))
        self.drawn_list = QListWidget()
        layout.addWidget(self.drawn_list)

        # Remove / Clear buttons
        list_btn_layout = QHBoxLayout()
        remove_btn = QPushButton('Remove Selected')
        remove_btn.clicked.connect(self.remove_drawn_polygon)
        list_btn_layout.addWidget(remove_btn)

        clear_btn = QPushButton('Clear All')
        clear_btn.clicked.connect(self.clear_drawn_polygons)
        list_btn_layout.addWidget(clear_btn)
        layout.addLayout(list_btn_layout)

        # Generate from drawn
        self.draw_preview_button = QPushButton('Generate Preview from Drawn Polygons')
        self.draw_preview_button.clicked.connect(self.generate_preview_from_drawn)
        layout.addWidget(self.draw_preview_button)

        layout.addStretch()
        self.tab_widget.addTab(tab, "Draw Base Polygons")

    def setup_modify_tab(self):
        """Tab 3: Modify Existing Mapsheet Layer"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Mapsheet layer selection
        ms_layout = QHBoxLayout()
        ms_layout.addWidget(QLabel('Mapsheet Layer:'))
        self.existing_layer_combo = QComboBox()
        self.populate_existing_mapsheet_layers()
        ms_layout.addWidget(self.existing_layer_combo)
        layout.addLayout(ms_layout)

        # Reference layer (optional)
        ref_layout = QHBoxLayout()
        ref_layout.addWidget(QLabel('Reference Layer (optional):'))
        self.reference_layer_combo = QComboBox()
        self.populate_reference_layers()
        ref_layout.addWidget(self.reference_layer_combo)
        layout.addLayout(ref_layout)

        # Load button
        self.load_existing_button = QPushButton('Load as Editable Preview')
        self.load_existing_button.clicked.connect(self.load_existing_layer)
        layout.addWidget(self.load_existing_button)

        # Info text
        info_label = QLabel(
            "Load an existing mapsheet layer to edit it.\n"
            "Select a reference polygon layer to compute coverage metrics.\n"
            "After editing, click 'Finalize Mapsheets' to create the final layer."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        layout.addStretch()
        self.tab_widget.addTab(tab, "Modify Existing")

    def setup_metrics_section(self, layout):
        """Set up shared coverage metrics display."""
        preview_box = QGroupBox("Coverage Metrics")
        preview_layout = QGridLayout()

        # Row 0
        preview_layout.addWidget(QLabel('Total Mapsheets:'), 0, 0)
        self.sheet_count_label = QLabel('-')
        self.sheet_count_label.setStyleSheet("font-weight: bold;")
        preview_layout.addWidget(self.sheet_count_label, 0, 1)

        preview_layout.addWidget(QLabel('Effective Sheets:'), 0, 2)
        self.effective_sheets_label = QLabel('-')
        self.effective_sheets_label.setStyleSheet("font-weight: bold;")
        preview_layout.addWidget(self.effective_sheets_label, 0, 3)

        # Row 1
        preview_layout.addWidget(QLabel('Coverage Efficiency:'), 1, 0)
        self.optimization_label = QLabel('-')
        self.optimization_label.setStyleSheet("font-weight: bold;")
        preview_layout.addWidget(self.optimization_label, 1, 1)

        preview_layout.addWidget(QLabel('Polygon Coverage:'), 1, 2)
        self.coverage_label = QLabel('-')
        self.coverage_label.setStyleSheet("font-weight: bold;")
        preview_layout.addWidget(self.coverage_label, 1, 3)

        # Row 2
        preview_layout.addWidget(QLabel('Outside Area:'), 2, 0)
        self.wasted_area_label = QLabel('-')
        self.wasted_area_label.setStyleSheet("font-weight: bold;")
        preview_layout.addWidget(self.wasted_area_label, 2, 1)

        # Status message
        self.status_label = QLabel('No preview generated')
        self.status_label.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(self.status_label, 3, 0, 1, 4)

        preview_box.setLayout(preview_layout)
        layout.addWidget(preview_box)

    def setup_action_buttons(self, layout):
        """Set up shared action buttons."""
        # Brief instruction label
        instruction = QLabel(
            "Edit the preview layer with QGIS tools, then Update Metrics or Finalize."
        )
        instruction.setWordWrap(True)
        layout.addWidget(instruction)

        button_layout = QHBoxLayout()

        self.add_sheet_button = QPushButton('Add Sheet...')
        self.add_sheet_button.clicked.connect(self.add_mapsheet_dialog)
        self.add_sheet_button.setEnabled(False)
        self.add_sheet_button.setToolTip('Add a new mapsheet at the center of the current map view')
        button_layout.addWidget(self.add_sheet_button)

        self.update_button = QPushButton('Update Metrics')
        self.update_button.clicked.connect(self.update_metrics)
        self.update_button.setEnabled(False)
        button_layout.addWidget(self.update_button)

        self.generate_button = QPushButton('Finalize Mapsheets')
        self.generate_button.clicked.connect(self.create_mapsheets)
        self.generate_button.setEnabled(False)
        button_layout.addWidget(self.generate_button)

        layout.addLayout(button_layout)

    def setup_merge_section(self, layout):
        """Set up merge mapsheet layers section."""
        merge_group = QGroupBox('Merge Mapsheet Layers')
        merge_layout = QVBoxLayout()

        # Master layer
        master_layout = QHBoxLayout()
        master_layout.addWidget(QLabel('Master Layer:'))
        self.master_layer_combo = QComboBox()
        self.master_layer_combo.setToolTip('The existing mapsheet layer (numbering will continue from this)')
        master_layout.addWidget(self.master_layer_combo)
        merge_layout.addLayout(master_layout)

        # Source layer
        source_layout = QHBoxLayout()
        source_layout.addWidget(QLabel('Source Layer:'))
        self.source_layer_combo = QComboBox()
        self.source_layer_combo.setToolTip('The new mapsheet layer to add to master')
        source_layout.addWidget(self.source_layer_combo)
        merge_layout.addLayout(source_layout)

        # Buttons
        merge_button_layout = QHBoxLayout()
        self.refresh_merge_button = QPushButton('Refresh Layers')
        self.refresh_merge_button.clicked.connect(self.populate_merge_layers)
        self.refresh_merge_button.setToolTip('Refresh the list of available mapsheet layers')
        merge_button_layout.addWidget(self.refresh_merge_button)

        self.merge_layers_button = QPushButton('Merge Layers')
        self.merge_layers_button.clicked.connect(self.merge_mapsheet_layers)
        self.merge_layers_button.setToolTip('Merge source layer into master layer with sequential numbering')
        merge_button_layout.addWidget(self.merge_layers_button)
        merge_layout.addLayout(merge_button_layout)

        merge_group.setLayout(merge_layout)
        layout.addWidget(merge_group)

        # Populate merge layer dropdowns
        self.populate_merge_layers()

    # ---- Layer population helpers ----

    def _populate_polygon_combo(self, combo, require_mapsheet_fields=False, add_placeholder=None):
        """Generic helper to populate a combo with polygon layers."""
        current_text = combo.currentText()
        combo.clear()
        if add_placeholder:
            combo.addItem(add_placeholder, None)

        required_fields = ['name', 'sheet_size', 'scale'] if require_mapsheet_fields else []

        for layer in QgsProject.instance().mapLayers().values():
            if layer.type() == QgsMapLayerType.VectorLayer:
                if layer.geometryType() == QgsWkbTypes.PolygonGeometry:
                    if require_mapsheet_fields:
                        layer_fields = [f.name() for f in layer.fields()]
                        if not all(f in layer_fields for f in required_fields):
                            continue
                    combo.addItem(layer_display_name(layer), layer.id())

        # Restore previous selection
        if current_text:
            idx = combo.findText(current_text)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _combo_layer(self, combo, index=None):
        """Resolve a combo item's stored layer id back to the layer (or None)."""
        idx = combo.currentIndex() if index is None else index
        if idx < 0:
            return None
        layer_id = combo.itemData(idx)
        if not layer_id:
            return None
        return QgsProject.instance().mapLayer(layer_id)

    def populate_layers(self, *args):
        """Populate the input layer combo with polygon layers"""
        try:
            self._populate_polygon_combo(self.layer_combo)
        except Exception as e:
            QgsMessageLog.logMessage(f"Error populating layers: {str(e)}", 'Linear Geoscience', Qgis.Warning)

    def populate_existing_mapsheet_layers(self, *args):
        """Populate the existing mapsheet layer combo (layers with mapsheet fields)"""
        try:
            self._populate_polygon_combo(
                self.existing_layer_combo,
                require_mapsheet_fields=True,
                add_placeholder="-- Select Mapsheet Layer --"
            )
        except Exception as e:
            QgsMessageLog.logMessage(f"Error populating existing mapsheet layers: {str(e)}", 'Linear Geoscience', Qgis.Warning)

    def populate_reference_layers(self, *args):
        """Populate the reference layer combo with polygon layers"""
        try:
            self._populate_polygon_combo(
                self.reference_layer_combo,
                add_placeholder="-- None (optional) --"
            )
        except Exception as e:
            QgsMessageLog.logMessage(f"Error populating reference layers: {str(e)}", 'Linear Geoscience', Qgis.Warning)

    def populate_merge_layers(self, *args):
        """Populate the master and source layer combos for merging"""
        try:
            self._populate_polygon_combo(
                self.master_layer_combo,
                require_mapsheet_fields=True,
                add_placeholder="-- Select Master Layer --"
            )
            self._populate_polygon_combo(
                self.source_layer_combo,
                require_mapsheet_fields=True,
                add_placeholder="-- Select Source Layer --"
            )
        except Exception as e:
            QgsMessageLog.logMessage(f"Error populating merge layers: {str(e)}", 'Linear Geoscience', Qgis.Warning)

    # ---- Getters ----

    def get_combined_input_geometry(self, input_layer):
        """Get combined geometry with caching for performance"""
        try:
            if (self.input_layer_id != input_layer.id() or
                    self.combined_input_geometry is None):

                QgsMessageLog.logMessage("Calculating combined input geometry...", 'Linear Geoscience', Qgis.Info)
                start_time = time.time()

                geometries = []
                for feature in input_layer.getFeatures():
                    if feature.geometry() and not feature.geometry().isEmpty():
                        geometries.append(feature.geometry())

                if not geometries:
                    self.combined_input_geometry = None
                    return None

                if len(geometries) == 1:
                    self.combined_input_geometry = QgsGeometry(geometries[0])
                else:
                    batch_size = 50
                    combined = None
                    for i in range(0, len(geometries), batch_size):
                        batch = geometries[i:i + batch_size]
                        batch_combined = batch[0]
                        for geom in batch[1:]:
                            batch_combined = batch_combined.combine(geom)
                        if combined is None:
                            combined = batch_combined
                        else:
                            combined = combined.combine(batch_combined)
                    self.combined_input_geometry = combined

                self.input_layer_id = input_layer.id()
                QgsMessageLog.logMessage(f"Combined geometry calculated in {time.time() - start_time:.2f}s", 'Linear Geoscience', Qgis.Info)

            return self.combined_input_geometry

        except Exception as e:
            QgsMessageLog.logMessage(f"Error getting combined geometry: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)
            return None

    def update_scale_combo(self):
        """Update scale combo box based on selected sheet size"""
        try:
            current_scale = self.scale_combo.currentText() if self.scale_combo.currentIndex() >= 0 else None
            self.scale_combo.clear()
            self.scale_combo.addItem("-- Select Scale --", None)

            sheet_size = self.size_combo.currentText()
            if sheet_size in self.dimensions:
                for scale in sorted(self.dimensions[sheet_size].keys(),
                                    key=lambda x: int(x.split(':')[1])):
                    self.scale_combo.addItem(scale)

            if current_scale:
                index = self.scale_combo.findText(current_scale)
                if index >= 0:
                    self.scale_combo.setCurrentIndex(index)
                else:
                    self.scale_combo.setCurrentIndex(0)

        except Exception as e:
            QgsMessageLog.logMessage(f"Error updating scale combo: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)

    def get_selected_layer(self):
        """Get the selected input layer"""
        try:
            return self._combo_layer(self.layer_combo)
        except Exception as e:
            QgsMessageLog.logMessage(f"Error getting selected layer: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            return None

    def get_selected_sheet_size(self):
        """Get the selected sheet size"""
        try:
            return self.size_combo.currentText()
        except Exception as e:
            QgsMessageLog.logMessage(f"Error getting selected sheet size: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            return None

    def get_selected_scale(self):
        """Get the selected scale"""
        try:
            index = self.scale_combo.currentIndex()
            if index <= 0:
                return None
            return self.scale_combo.currentText()
        except Exception as e:
            QgsMessageLog.logMessage(f"Error getting selected scale: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            return None

    def get_orientation_is_landscape(self):
        """Get whether landscape orientation is selected (Tab 1)"""
        return self.landscape_radio.isChecked()

    def check_preview_layer_exists(self):
        """Check if the preview layer still exists in the project"""
        if self.preview_layer_id:
            if QgsProject.instance().mapLayer(self.preview_layer_id):
                if not self.preview_layer:
                    self.preview_layer = QgsProject.instance().mapLayer(self.preview_layer_id)
                return True
            else:
                self.preview_layer = None
                self.preview_layer_id = None
                return False
        else:
            self.preview_layer = None
            return False

    # ---- Helper methods ----

    def _create_preview_fields(self):
        """Create the standard fields for a mapsheet preview/final layer."""
        fields = QgsFields()
        fields.append(create_compatible_field('name', 'string'))
        fields.append(create_compatible_field('sheet_size', 'string'))
        fields.append(create_compatible_field('scale', 'string'))
        fields.append(create_compatible_field('orientation', 'string'))
        fields.append(create_compatible_field('dimensions', 'string'))
        fields.append(create_compatible_field('area_m2', 'double'))
        fields.append(create_compatible_field('inside_pct', 'double'))
        fields.append(create_compatible_field('group', 'int'))
        return fields

    def _create_preview_layer(self, crs_authid, name='Mapsheet Preview'):
        """Create a new memory layer with standard mapsheet fields."""
        fields = self._create_preview_fields()
        layer = QgsVectorLayer(f'Polygon?crs={crs_authid}', name, 'memory')
        provider = layer.dataProvider()
        provider.addAttributes(fields)
        layer.updateFields()
        return layer

    def _get_reference_polygon(self):
        """Get the reference polygon for coverage metrics based on current tab."""
        current_tab = self.tab_widget.currentIndex()

        if current_tab == 0:  # From Input Layer
            input_layer = self.get_selected_layer()
            if input_layer:
                return self.get_combined_input_geometry(input_layer)
        elif current_tab == 1:  # Draw Base Polygons
            if self.drawn_polygons:
                combined = None
                for item in self.drawn_polygons:
                    if combined is None:
                        combined = QgsGeometry(item['geometry'])
                    else:
                        combined = combined.combine(item['geometry'])
                return combined
        elif current_tab == 2:  # Modify Existing
            ref_idx = self.reference_layer_combo.currentIndex()
            if ref_idx > 0:
                ref_layer = self._combo_layer(self.reference_layer_combo, ref_idx)
                if ref_layer:
                    return self.get_combined_input_geometry(ref_layer)
        return None

    def _disable_preview_buttons(self):
        """Disable buttons that depend on a preview layer."""
        self.update_button.setEnabled(False)
        self.add_sheet_button.setEnabled(False)
        self.generate_button.setEnabled(False)

    def _enable_preview_buttons(self):
        """Enable buttons that depend on a preview layer."""
        self.update_button.setEnabled(True)
        self.add_sheet_button.setEnabled(True)
        self.generate_button.setEnabled(True)

    def _remove_previous_preview(self):
        """Remove existing preview layer if present."""
        if self.check_preview_layer_exists():
            QgsMessageLog.logMessage(f"Removing previous preview layer (ID: {self.preview_layer_id})", 'Linear Geoscience', Qgis.Info)
            QgsProject.instance().removeMapLayer(self.preview_layer_id)
            self.preview_layer = None
            self.preview_layer_id = None

    def _add_mapsheets_to_preview(self, mapsheets, preview_layer):
        """Add mapsheet dicts as features to a preview layer."""
        features = []
        for mapsheet in mapsheets:
            feature = QgsFeature()
            feature.setGeometry(mapsheet['geometry'])
            feature.setAttributes([
                mapsheet['attributes']['name'],
                mapsheet['attributes']['sheet_size'],
                mapsheet['attributes']['scale'],
                mapsheet['attributes'].get('orientation', 'N/A'),
                mapsheet['attributes']['dimensions'],
                mapsheet['attributes']['area'],
                mapsheet['attributes'].get('inside_pct', 0),
                mapsheet['attributes'].get('group', 1)
            ])
            features.append(feature)
        preview_layer.dataProvider().addFeatures(features)
        return len(features)

    # ---- Styling ----

    def style_mapsheet_layer(self, layer):
        """Apply styling to the mapsheet layer"""
        try:
            categories = []
            group_values = set()
            for feature in layer.getFeatures():
                if 'group' in feature.fields().names():
                    group_values.add(feature['group'])

            for i, group_id in enumerate(sorted(group_values)):
                symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.PolygonGeometry)
                symbol.symbolLayer(0).setStrokeColor(QColor(80, 80, 80))
                symbol.symbolLayer(0).setFillColor(QColor(0, 0, 0, 0))
                symbol.symbolLayer(0).setStrokeWidth(0.15)
                symbol.symbolLayer(0).setStrokeStyle(Qt.DashLine)
                category = QgsRendererCategory(group_id, symbol, f"Group {group_id}")
                categories.append(category)

            if categories:
                renderer = QgsCategorizedSymbolRenderer('group', categories)
                layer.setRenderer(renderer)
            else:
                symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.PolygonGeometry)
                symbol.symbolLayer(0).setStrokeColor(QColor(80, 80, 80))
                symbol.symbolLayer(0).setFillColor(QColor(0, 0, 0, 0))
                symbol.symbolLayer(0).setStrokeWidth(0.15)
                symbol.symbolLayer(0).setStrokeStyle(Qt.DashLine)
                layer.renderer().setSymbol(symbol)

            label_settings = QgsPalLayerSettings()
            label_settings.fieldName = 'name'

            try:
                label_settings.placement = QgsPalLayerSettings.Placement.OverPoint
            except AttributeError:
                try:
                    label_settings.placement = QgsPalLayerSettings.OverPoint
                except AttributeError:
                    label_settings.placement = QgsPalLayerSettings.AroundPoint

            label_settings.xOffset = 0
            label_settings.yOffset = 0
            try:
                label_settings.offsetType = QgsPalLayerSettings.OffsetType.FromPoint
            except AttributeError:
                label_settings.offsetType = QgsPalLayerSettings.FromPoint

            label_format = QgsTextFormat()
            font = label_format.font()
            font.setFamily('Calibri Light')
            font.setItalic(True)
            font.setPointSize(10)
            label_format.setFont(font)
            label_format.setColor(QColor(80, 80, 80))
            label_settings.setFormat(label_format)

            label_buffer = QgsTextBufferSettings()
            label_buffer.setEnabled(True)
            label_buffer.setSize(0.8)
            label_buffer.setColor(QColor(255, 255, 255))
            label_format.setBuffer(label_buffer)

            layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
            layer.setLabelsEnabled(True)
            layer.triggerRepaint()

        except Exception as e:
            QgsMessageLog.logMessage(f"Error applying styling: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)

    # ---- Add Sheet ----

    def add_mapsheet_dialog(self):
        """Show orientation dialog then add a mapsheet."""
        QgsMessageLog.logMessage("========== ADD MAPSHEET CLICKED ==========", 'Linear Geoscience', Qgis.Info)
        try:
            if not self.check_preview_layer_exists():
                self.status_label.setText("Error: Preview layer not found")
                self._disable_preview_buttons()
                return

            dialog = QDialog(self)
            dialog.setWindowTitle("Add Mapsheet")
            dlg_layout = QVBoxLayout(dialog)

            dlg_layout.addWidget(QLabel("Select orientation for the new sheet:"))

            landscape_radio = QRadioButton("Landscape")
            landscape_radio.setChecked(True)
            portrait_radio = QRadioButton("Portrait")
            dlg_layout.addWidget(landscape_radio)
            dlg_layout.addWidget(portrait_radio)

            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            dlg_layout.addWidget(buttons)

            if dialog.exec() == QDialog.Accepted:
                self.add_mapsheet(landscape=landscape_radio.isChecked())

        except Exception as e:
            QgsMessageLog.logMessage(f"Error in add mapsheet dialog: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)

    def add_mapsheet(self, landscape=True):
        """Add a new mapsheet to the preview layer at the center of the current map view."""
        try:
            if not self.check_preview_layer_exists():
                self.status_label.setText("Error: Preview layer not found")
                self._disable_preview_buttons()
                return

            # Get dimensions from current UI settings
            sheet_size = self.get_selected_sheet_size()
            scale = self.get_selected_scale()
            if not sheet_size or not scale:
                self.status_label.setText("Error: Select sheet size and scale first")
                return

            width, height = self.dimensions[sheet_size][scale]
            if landscape:
                width, height = height, width

            orientation_text = 'Landscape' if landscape else 'Portrait'

            canvas = iface.mapCanvas()
            center_point = canvas.center()

            # Get the highest sheet number
            last_number = 0
            for feature in self.preview_layer.getFeatures():
                if 'name' in feature.fields().names():
                    try:
                        num = int(str(feature['name']).split()[-1])
                        last_number = max(last_number, num)
                    except (ValueError, IndexError):
                        pass

            # Create rectangle centered on map center
            min_x = center_point.x() - (width / 2)
            min_y = center_point.y() - (height / 2)
            max_x = min_x + width
            max_y = min_y + height

            rect = QgsRectangle(min_x, min_y, max_x, max_y)
            geometry = QgsGeometry.fromRect(rect)

            feature = QgsFeature(self.preview_layer.fields())
            feature.setGeometry(geometry)
            feature['name'] = f'Mapsheet {last_number + 1}'
            feature['sheet_size'] = sheet_size
            feature['scale'] = scale
            feature['orientation'] = orientation_text
            feature['dimensions'] = f'{width}m x {height}m'
            feature['area_m2'] = width * height

            # Calculate inside percentage using cached geometry
            combined_polygon = self._get_reference_polygon()
            if combined_polygon:
                intersection = geometry.intersection(combined_polygon)
                if not intersection.isEmpty():
                    inside_pct = round((intersection.area() / geometry.area()) * 100, 2)
                    feature['inside_pct'] = inside_pct

            # Use the nearest feature's group
            nearest_group = 1
            min_distance = float('inf')
            for existing in self.preview_layer.getFeatures():
                dist = existing.geometry().distance(geometry)
                if dist < min_distance:
                    min_distance = dist
                    if 'group' in existing.fields().names():
                        nearest_group = existing['group']
            feature['group'] = nearest_group

            self.preview_layer.startEditing()
            self.preview_layer.addFeature(feature)
            self.preview_layer.commitChanges()

            self.update_metrics()
            iface.mapCanvas().refresh()
            self.status_label.setText(f"Added {orientation_text.lower()} mapsheet at center of view")

        except Exception as e:
            QgsMessageLog.logMessage(f"Error adding mapsheet: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)
            self.status_label.setText(f"Error adding mapsheet: {str(e)}")

    # ---- Tab 1: Generate from Input Layer ----

    def generate_preview(self):
        """Generate a preview of mapsheets from the input layer."""
        QgsMessageLog.logMessage("========== GENERATE PREVIEW CLICKED ==========", 'Linear Geoscience', Qgis.Info)
        try:
            input_layer = self.get_selected_layer()
            if not input_layer:
                self.status_label.setText("Error: No input layer selected")
                return

            sheet_size = self.get_selected_sheet_size()
            if not sheet_size:
                self.status_label.setText("Error: No sheet size selected")
                return

            scale = self.get_selected_scale()
            if not scale:
                self.status_label.setText("Error: No scale selected")
                return

            overlap_percent = self.overlap_spin.value()
            landscape = self.get_orientation_is_landscape()

            QgsMessageLog.logMessage(f"Generating preview: Layer={input_layer.name()}, Size={sheet_size}, Scale={scale}, Overlap={overlap_percent}%, Orientation={'Landscape' if landscape else 'Portrait'}", 'Linear Geoscience', Qgis.Info)
            self.status_label.setText("Generating preview...")

            # Clear geometry cache if layer changed
            if self.input_layer_id != input_layer.id():
                self.combined_input_geometry = None
                self.input_layer_id = None

            start_time = time.time()

            self._remove_previous_preview()

            # Create preview layer with CRS in URI
            preview_layer = self._create_preview_layer(input_layer.crs().authid())

            # Generate mapsheets
            mapsheets = self.calculate_mapsheets_uniform(
                input_layer, sheet_size, scale, overlap_percent, landscape
            )

            count = self._add_mapsheets_to_preview(mapsheets, preview_layer)

            QgsProject.instance().addMapLayer(preview_layer)
            self.preview_layer = preview_layer
            self.preview_layer_id = preview_layer.id()

            self.style_mapsheet_layer(preview_layer)

            # Calculate and display metrics
            combined_polygon = self.get_combined_input_geometry(input_layer)
            self._calculate_and_display_metrics(combined_polygon)

            self._enable_preview_buttons()

            processing_time = time.time() - start_time
            self.status_label.setText(
                f"Preview generated: {count} mapsheets ({processing_time:.2f}s)"
            )
            QgsMessageLog.logMessage(f"Preview generated with {count} mapsheets in {processing_time:.2f}s", 'Linear Geoscience', Qgis.Info)

        except Exception as e:
            QgsMessageLog.logMessage(f"Error generating preview: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)
            self.status_label.setText(f"Error: {str(e)}")

    # ---- Tab 2: Draw Base Polygons ----

    def toggle_draw_mode(self, checked):
        """Activate/deactivate polygon drawing mode."""
        try:
            if checked:
                self.previous_map_tool = iface.mapCanvas().mapTool()
                if not self.draw_tool:
                    self.draw_tool = PolygonDrawMapTool(iface.mapCanvas())
                    self.draw_tool.polygon_completed.connect(self.on_polygon_drawn)
                iface.mapCanvas().setMapTool(self.draw_tool)
                self.draw_button.setText('Stop Drawing')
                self.draw_status_label.setText(
                    "Left-click to add vertices, right-click to complete polygon"
                )
            else:
                if self.previous_map_tool:
                    iface.mapCanvas().setMapTool(self.previous_map_tool)
                    self.previous_map_tool = None
                self.draw_button.setText('Draw Polygon on Map')
                self.draw_status_label.setText('')
        except Exception as e:
            QgsMessageLog.logMessage(f"Error toggling draw mode: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)

    def on_polygon_drawn(self, geometry):
        """Handle a completed drawn polygon."""
        try:
            orientation = self.draw_orientation_combo.currentText()
            self.drawn_polygons.append({
                'geometry': geometry,
                'orientation': orientation
            })
            idx = len(self.drawn_polygons)
            self.drawn_list.addItem(f"Polygon {idx} ({orientation})")
            self.draw_status_label.setText(
                f"Polygon {idx} added. Continue drawing or stop."
            )
        except Exception as e:
            QgsMessageLog.logMessage(f"Error handling drawn polygon: {str(e)}", 'Linear Geoscience', Qgis.Warning)

    def remove_drawn_polygon(self):
        """Remove the selected polygon from the drawn list."""
        try:
            row = self.drawn_list.currentRow()
            if row >= 0:
                self.drawn_list.takeItem(row)
                self.drawn_polygons.pop(row)
                # Renumber list items
                for i in range(self.drawn_list.count()):
                    item = self.drawn_list.item(i)
                    orient = self.drawn_polygons[i]['orientation']
                    item.setText(f"Polygon {i + 1} ({orient})")
        except Exception as e:
            QgsMessageLog.logMessage(f"Error removing drawn polygon: {str(e)}", 'Linear Geoscience', Qgis.Warning)

    def clear_drawn_polygons(self):
        """Clear all drawn polygons."""
        self.drawn_polygons = []
        self.drawn_list.clear()
        self.draw_status_label.setText('All polygons cleared')

    def generate_preview_from_drawn(self):
        """Generate mapsheet preview from drawn base polygons."""
        QgsMessageLog.logMessage("========== GENERATE FROM DRAWN POLYGONS ==========", 'Linear Geoscience', Qgis.Info)
        try:
            if not self.drawn_polygons:
                self.draw_status_label.setText("No polygons drawn yet")
                return

            sheet_size = self.get_selected_sheet_size()
            if not sheet_size:
                self.status_label.setText("Error: No sheet size selected")
                return

            scale = self.get_selected_scale()
            if not scale:
                self.status_label.setText("Error: No scale selected")
                return

            overlap_percent = self.overlap_spin.value()
            self.status_label.setText("Generating preview from drawn polygons...")

            start_time = time.time()
            self._remove_previous_preview()

            # Use project CRS for drawn polygons
            crs_authid = QgsProject.instance().crs().authid()
            preview_layer = self._create_preview_layer(crs_authid)

            all_mapsheets = []
            next_number = 1

            for i, item in enumerate(self.drawn_polygons):
                geom = item['geometry']
                landscape = item['orientation'] == 'Landscape'

                mapsheets, next_number = self._generate_grid_for_geometry(
                    geom, sheet_size, scale, overlap_percent, landscape,
                    start_number=next_number, group_id=i + 1
                )
                all_mapsheets.extend(mapsheets)

            count = self._add_mapsheets_to_preview(all_mapsheets, preview_layer)

            QgsProject.instance().addMapLayer(preview_layer)
            self.preview_layer = preview_layer
            self.preview_layer_id = preview_layer.id()

            self.style_mapsheet_layer(preview_layer)

            # Use combined drawn polygons as reference for metrics
            combined_drawn = self._get_reference_polygon()
            self._calculate_and_display_metrics(combined_drawn)

            self._enable_preview_buttons()

            processing_time = time.time() - start_time
            self.status_label.setText(
                f"Preview generated: {count} mapsheets from {len(self.drawn_polygons)} "
                f"polygons ({processing_time:.2f}s)"
            )
            QgsMessageLog.logMessage(f"Generated {count} mapsheets from drawn polygons in {processing_time:.2f}s", 'Linear Geoscience', Qgis.Info)

        except Exception as e:
            QgsMessageLog.logMessage(f"Error generating preview from drawn polygons: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)
            self.status_label.setText(f"Error: {str(e)}")

    # ---- Tab 3: Modify Existing ----

    def load_existing_layer(self):
        """Load an existing mapsheet layer as an editable preview."""
        QgsMessageLog.logMessage("========== LOAD EXISTING LAYER ==========", 'Linear Geoscience', Qgis.Info)
        try:
            idx = self.existing_layer_combo.currentIndex()
            if idx <= 0:
                self.status_label.setText("Error: No mapsheet layer selected")
                return

            source_layer = self._combo_layer(self.existing_layer_combo, idx)
            if not source_layer:
                self.status_label.setText("Error: Selected layer not found")
                return

            self._remove_previous_preview()

            # Create new memory preview layer matching source fields
            crs_authid = source_layer.crs().authid()
            preview_layer = self._create_preview_layer(crs_authid)

            # Copy features from source layer
            preview_fields = preview_layer.fields()
            features_to_add = []
            for src_feature in source_layer.getFeatures():
                new_feature = QgsFeature(preview_fields)
                new_feature.setGeometry(src_feature.geometry())

                for field in preview_fields:
                    fname = field.name()
                    src_field_names = [f.name() for f in source_layer.fields()]
                    if fname in src_field_names:
                        src_idx = source_layer.fields().indexFromName(fname)
                        new_feature[fname] = src_feature.attributes()[src_idx]

                features_to_add.append(new_feature)

            preview_layer.dataProvider().addFeatures(features_to_add)

            QgsProject.instance().addMapLayer(preview_layer)
            self.preview_layer = preview_layer
            self.preview_layer_id = preview_layer.id()

            self.style_mapsheet_layer(preview_layer)
            self._enable_preview_buttons()

            # Calculate metrics with optional reference layer
            combined_polygon = self._get_reference_polygon()
            self._calculate_and_display_metrics(combined_polygon)

            self.status_label.setText(
                f"Loaded {len(features_to_add)} mapsheets from '{source_layer.name()}'"
            )
            QgsMessageLog.logMessage(f"Loaded {len(features_to_add)} features from '{source_layer.name()}'", 'Linear Geoscience', Qgis.Info)

        except Exception as e:
            QgsMessageLog.logMessage(f"Error loading existing layer: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)
            self.status_label.setText(f"Error: {str(e)}")

    # ---- Core grid generation ----

    def _generate_grid_for_geometry(self, geometry, sheet_size, scale, overlap_percent,
                                    landscape, start_number=1, group_id=1):
        """Generate mapsheet grid covering a given geometry.

        Returns:
            tuple: (list of mapsheet dicts, next_sheet_number)
        """
        width, height = self.dimensions[sheet_size][scale]
        if landscape:
            width, height = height, width

        orientation_text = 'Landscape' if landscape else 'Portrait'

        overlap_factor = overlap_percent / 100.0
        effective_width = width * (1 - overlap_factor)
        effective_height = height * (1 - overlap_factor)

        extent = geometry.boundingBox()
        # +2 buffer to ensure edge coverage (Bug fix: grid can miss edges)
        x_sheets = math.ceil(extent.width() / effective_width) + 2
        y_sheets = math.ceil(extent.height() / effective_height) + 2

        center_x = extent.center().x()
        center_y = extent.center().y()
        start_x = center_x - (x_sheets * effective_width / 2)
        start_y = center_y + (y_sheets * effective_height / 2)

        mapsheets = []
        kept_count = 0  # Bug fix: only count sheets that pass intersection test

        for i in range(y_sheets):
            for j in range(x_sheets):
                min_x = start_x + (j * effective_width)
                max_y = start_y - (i * effective_height)
                max_x = min_x + width
                min_y = max_y - height

                rect = QgsRectangle(min_x, min_y, max_x, max_y)
                geom = QgsGeometry.fromRect(rect)

                if geom.boundingBox().intersects(geometry.boundingBox()):
                    intersection = geom.intersection(geometry)
                    if not intersection.isEmpty():
                        kept_count += 1

                        inside_area = intersection.area()
                        total_area = geom.area()
                        inside_pct = round((inside_area / total_area) * 100, 2)

                        mapsheets.append({
                            'geometry': geom,
                            'attributes': {
                                'name': f'Mapsheet {start_number + kept_count - 1}',
                                'sheet_size': sheet_size,
                                'scale': scale,
                                'orientation': orientation_text,
                                'dimensions': f'{width}m x {height}m',
                                'area': width * height,
                                'inside_pct': inside_pct,
                                'group': group_id
                            }
                        })

        return mapsheets, start_number + kept_count

    def calculate_mapsheets_uniform(self, input_layer, sheet_size, scale,
                                    overlap_percent=10, landscape=True):
        """Calculate mapsheet arrangement using a uniform grid."""
        try:
            QgsMessageLog.logMessage(f"Calculating uniform mapsheets ({'landscape' if landscape else 'portrait'})", 'Linear Geoscience', Qgis.Info)
            start_time = time.time()

            combined_geometry = self.get_combined_input_geometry(input_layer)
            if not combined_geometry:
                QgsMessageLog.logMessage("Could not get combined input geometry", 'Linear Geoscience', Qgis.Warning)
                return []

            mapsheets, _ = self._generate_grid_for_geometry(
                combined_geometry, sheet_size, scale, overlap_percent, landscape
            )

            QgsMessageLog.logMessage(f"Generated {len(mapsheets)} uniform mapsheets in {time.time() - start_time:.2f}s", 'Linear Geoscience', Qgis.Info)
            return mapsheets

        except Exception as e:
            QgsMessageLog.logMessage(f"Error calculating uniform mapsheets: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)
            raise

    # ---- Metrics ----

    def _calculate_and_display_metrics(self, combined_polygon=None):
        """Calculate and display coverage metrics from the current preview layer.

        Args:
            combined_polygon: Reference polygon for coverage. None shows 'N/A'.
        """
        try:
            if not self.check_preview_layer_exists():
                return

            features = list(self.preview_layer.getFeatures())
            sheet_count = len(features)
            self.sheet_count_label.setText(str(sheet_count))

            if combined_polygon is None or sheet_count == 0:
                self.effective_sheets_label.setText('N/A')
                self.optimization_label.setText('N/A')
                self.optimization_label.setStyleSheet("font-weight: bold;")
                self.coverage_label.setText('N/A')
                self.coverage_label.setStyleSheet("font-weight: bold;")
                self.wasted_area_label.setText('N/A')
                self.wasted_area_label.setStyleSheet("font-weight: bold;")
                return

            input_area = combined_polygon.area()
            if input_area <= 0:
                return

            # Calculate effective sheets from UI settings or preview layer
            effective_sheets_text = 'N/A'
            sheet_size = self.get_selected_sheet_size()
            scale = self.get_selected_scale()

            if (sheet_size and scale and sheet_size in self.dimensions
                    and scale in self.dimensions.get(sheet_size, {})):
                w, h = self.dimensions[sheet_size][scale]
                effective_sheets = input_area / (w * h)
                effective_sheets_text = str(round(effective_sheets, 2))
            else:
                # Try from preview layer features
                for f in features:
                    fnames = f.fields().names()
                    if 'sheet_size' in fnames and 'scale' in fnames:
                        ss, sc = f['sheet_size'], f['scale']
                        if ss in self.dimensions and sc in self.dimensions.get(ss, {}):
                            w, h = self.dimensions[ss][sc]
                            effective_sheets = input_area / (w * h)
                            effective_sheets_text = str(round(effective_sheets, 2))
                            break

            self.effective_sheets_label.setText(effective_sheets_text)

            # Calculate coverage areas
            total_mapsheet_area = 0
            total_inside_area = 0
            for f in features:
                geom = f.geometry()
                total_mapsheet_area += geom.area()
                intersection = geom.intersection(combined_polygon)
                if not intersection.isEmpty():
                    total_inside_area += intersection.area()

            optimization_pct = (input_area / total_mapsheet_area * 100) if total_mapsheet_area > 0 else 0
            inside_coverage_pct = min(100, (total_inside_area / input_area * 100) if input_area > 0 else 0)
            wasted_area_pct = ((total_mapsheet_area - total_inside_area) / total_mapsheet_area * 100) if total_mapsheet_area > 0 else 0

            self.optimization_label.setText(f"{round(optimization_pct, 2)}%")
            self.coverage_label.setText(f"{round(inside_coverage_pct, 2)}%")
            self.wasted_area_label.setText(f"{round(wasted_area_pct, 2)}%")

            self._color_metric_label(self.optimization_label, optimization_pct, 80, 60, True)
            self._color_metric_label(self.coverage_label, inside_coverage_pct, 95, 85, True)
            self._color_metric_label(self.wasted_area_label, wasted_area_pct, 20, 40, False)

        except Exception as e:
            QgsMessageLog.logMessage(f"Error calculating metrics: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)

    def _color_metric_label(self, label, value, good_threshold, medium_threshold, higher_is_better):
        """Apply color coding to a metric label."""
        if higher_is_better:
            if value >= good_threshold:
                color = "green"
            elif value >= medium_threshold:
                color = "orange"
            else:
                color = "red"
        else:
            if value <= good_threshold:
                color = "green"
            elif value <= medium_threshold:
                color = "orange"
            else:
                color = "red"
        label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def update_metrics(self):
        """Update metrics after manual edits."""
        QgsMessageLog.logMessage("========== UPDATE METRICS CLICKED ==========", 'Linear Geoscience', Qgis.Info)
        try:
            if not self.check_preview_layer_exists():
                self.status_label.setText("Error: Preview layer not found")
                self._disable_preview_buttons()
                return

            start_time = time.time()

            combined_polygon = self._get_reference_polygon()
            self._calculate_and_display_metrics(combined_polygon)

            processing_time = time.time() - start_time
            sheet_count = self.preview_layer.featureCount()
            self.status_label.setText(
                f"Metrics updated: {sheet_count} mapsheets ({processing_time:.2f}s)"
            )
            QgsMessageLog.logMessage(f"Metrics updated for {sheet_count} mapsheets in {processing_time:.2f}s", 'Linear Geoscience', Qgis.Info)

        except Exception as e:
            QgsMessageLog.logMessage(f"Error updating metrics: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)
            self.status_label.setText(f"Error updating metrics: {str(e)}")

    # ---- Merge ----

    def get_highest_mapsheet_number(self, layer):
        """Get the highest mapsheet number from a layer"""
        try:
            import re
            highest_number = 0
            field_names = [field.name() for field in layer.fields()]

            if 'name' not in field_names:
                return 0

            for feature in layer.getFeatures():
                name = feature['name']
                if name:
                    try:
                        name_str = str(name).strip()
                        numbers = re.findall(r'\d+', name_str)
                        if numbers:
                            num = int(numbers[-1])
                            highest_number = max(highest_number, num)
                    except (ValueError, IndexError):
                        pass

            return highest_number

        except Exception as e:
            QgsMessageLog.logMessage(f"Error getting highest mapsheet number: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)
            return 0

    def merge_mapsheet_layers(self):
        """Merge source layer into master layer with sequential numbering"""
        QgsMessageLog.logMessage("========== MERGE MAPSHEET LAYERS ==========", 'Linear Geoscience', Qgis.Info)
        try:
            master_index = self.master_layer_combo.currentIndex()
            source_index = self.source_layer_combo.currentIndex()

            if master_index <= 0:
                QMessageBox.warning(self, "No Master Layer", "Please select a master layer.")
                return

            if source_index <= 0:
                QMessageBox.warning(self, "No Source Layer", "Please select a source layer.")
                return

            master_layer = self._combo_layer(self.master_layer_combo, master_index)
            source_layer = self._combo_layer(self.source_layer_combo, source_index)

            if master_layer is None or source_layer is None:
                QMessageBox.warning(self, "Layer Not Found",
                                    "A selected layer is no longer in the project.")
                return

            if master_layer.id() == source_layer.id():
                QMessageBox.warning(self, "Same Layer", "Master and Source layers cannot be the same.")
                return

            highest_number = self.get_highest_mapsheet_number(master_layer)
            QgsMessageLog.logMessage(f"Starting numbering from: {highest_number + 1}", 'Linear Geoscience', Qgis.Info)

            source_features = list(source_layer.getFeatures())
            if not source_features:
                QMessageBox.information(self, "No Features", "Source layer has no features to merge.")
                return

            reply = QMessageBox.question(
                self, "Confirm Merge",
                f"Merge {len(source_features)} mapsheets from '{source_layer.name()}' "
                f"to '{master_layer.name()}'?\n\n"
                f"New mapsheets will be numbered from {highest_number + 1} "
                f"to {highest_number + len(source_features)}.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply != QMessageBox.Yes:
                return

            master_layer.startEditing()

            features_to_add = []
            for i, source_feature in enumerate(source_features):
                new_feature = QgsFeature(master_layer.fields())
                new_feature.setGeometry(source_feature.geometry())

                attributes = []
                for field in master_layer.fields():
                    field_name = field.name()
                    if field_name == 'name':
                        attributes.append(f'Mapsheet {highest_number + 1 + i}')
                    elif field_name in [f.name() for f in source_layer.fields()]:
                        source_idx = source_layer.fields().indexFromName(field_name)
                        attributes.append(source_feature.attributes()[source_idx])
                    else:
                        attributes.append(None)

                new_feature.setAttributes(attributes)
                features_to_add.append(new_feature)

            master_layer.addFeatures(features_to_add)
            master_layer.commitChanges()

            master_layer.triggerRepaint()
            iface.mapCanvas().refresh()

            QMessageBox.information(
                self, "Merge Complete",
                f"Successfully merged {len(features_to_add)} mapsheets!\n\n"
                f"New mapsheets numbered: {highest_number + 1} to "
                f"{highest_number + len(features_to_add)}\n\n"
                f"You can now delete the source layer '{source_layer.name()}' if no longer needed."
            )

            QgsMessageLog.logMessage(f"Merged {len(features_to_add)} features to master layer", 'Linear Geoscience', Qgis.Info)

        except Exception as e:
            QgsMessageLog.logMessage(f"Error merging layers: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)
            QMessageBox.critical(self, "Error", f"Failed to merge layers: {str(e)}")

    # ---- Finalize ----

    def create_mapsheets(self):
        """Create the final mapsheet layer with properly sequenced names."""
        QgsMessageLog.logMessage("========== FINALIZE MAPSHEETS CLICKED ==========", 'Linear Geoscience', Qgis.Info)
        try:
            if not self.check_preview_layer_exists():
                self.status_label.setText("Error: Preview layer not found")
                self._disable_preview_buttons()
                return

            # Create final layer with CRS from preview layer
            crs_authid = self.preview_layer.crs().authid()
            final_layer = self._create_preview_layer(crs_authid, 'Mapsheets')

            # Get all features from preview layer
            preview_features = list(self.preview_layer.getFeatures())
            if not preview_features:
                self.status_label.setText("No features to add to final layer")
                return

            # Sort by top-left corner: top to bottom (decreasing Y), left to right (increasing X)
            feature_positions = []
            for i, feature in enumerate(preview_features):
                bbox = feature.geometry().boundingBox()
                feature_positions.append((i, bbox.xMinimum(), bbox.yMaximum()))

            sorted_positions = sorted(feature_positions, key=lambda p: (-p[2], p[1]))

            # Create final features with sequential naming
            final_features = []
            for seq_num, position in enumerate(sorted_positions):
                feature_index = position[0]
                feature = preview_features[feature_index]

                new_feature = QgsFeature()
                new_feature.setGeometry(feature.geometry())

                attributes = []
                for field in final_layer.fields():
                    if field.name() == 'name':
                        attributes.append(f'Mapsheet {seq_num + 1}')
                    elif field.name() in feature.fields().names():
                        source_idx = feature.fields().indexFromName(field.name())
                        attributes.append(feature.attributes()[source_idx])
                    else:
                        attributes.append(None)

                new_feature.setAttributes(attributes)
                final_features.append(new_feature)

            final_layer.dataProvider().addFeatures(final_features)
            QgsProject.instance().addMapLayer(final_layer)

            self.style_mapsheet_layer(final_layer)

            # Remove preview layer
            QgsProject.instance().removeMapLayer(self.preview_layer_id)
            self.preview_layer = None
            self.preview_layer_id = None

            # Reset UI
            self.sheet_count_label.setText("-")
            self.effective_sheets_label.setText("-")
            self.optimization_label.setText("-")
            self.optimization_label.setStyleSheet("font-weight: bold;")
            self.coverage_label.setText("-")
            self.coverage_label.setStyleSheet("font-weight: bold;")
            self.wasted_area_label.setText("-")
            self.wasted_area_label.setStyleSheet("font-weight: bold;")
            self.status_label.setText("No preview generated")
            self._disable_preview_buttons()

            try:
                success_level = Qgis.Success
            except AttributeError:
                success_level = 3

            iface.messageBar().pushMessage(
                "Success",
                f"Mapsheets created with {len(final_features)} sheets "
                f"(sorted by top-left corner position)",
                level=success_level
            )
            QgsMessageLog.logMessage(f"Created final mapsheet layer with {len(final_features)} sheets", 'Linear Geoscience', Qgis.Info)

        except Exception as e:
            QgsMessageLog.logMessage(f"Error creating mapsheets: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)
            self.status_label.setText(f"Error creating mapsheets: {str(e)}")

    def closeEvent(self, event):
        """Clean up when panel is closed."""
        try:
            if self.draw_tool:
                self.draw_tool.deactivate()
            if hasattr(self, 'draw_button') and self.draw_button.isChecked():
                self.draw_button.setChecked(False)
            self.drawn_polygons = []
        except Exception:
            pass
        super().closeEvent(event)


# Function to run the panel
def run_final_mapsheet_panel():
    try:
        QgsMessageLog.logMessage("Starting Final MapSheet Generator", 'Linear Geoscience', Qgis.Info)

        # Check if panel already exists, close it
        for dock in iface.mainWindow().findChildren(QDockWidget, "MapSheet Generator"):
            QgsMessageLog.logMessage("Removing existing panel", 'Linear Geoscience', Qgis.Info)
            iface.removeDockWidget(dock)
            dock.deleteLater()

        # Create and show the panel
        QgsMessageLog.logMessage("Creating new panel", 'Linear Geoscience', Qgis.Info)
        panel = FinalMapSheetPanel(iface.mainWindow())
        iface.addDockWidget(Qt.RightDockWidgetArea, panel)
        panel.show()

        QgsMessageLog.logMessage("Final MapSheet Generator panel created", 'Linear Geoscience', Qgis.Info)

        # Store persistent reference on iface to prevent GC; clean up on close
        panel.destroyed.connect(lambda: setattr(iface, "_mapsheet_panel", None))
        iface._mapsheet_panel = panel

        return panel

    except Exception as e:
        QgsMessageLog.logMessage(f"Failed to create panel: {str(e)}", 'Linear Geoscience', Qgis.Warning)
        QgsMessageLog.logMessage(traceback.format_exc(), 'Linear Geoscience', Qgis.Warning)
        return None


def run(iface):
    """Entry point called from mainplugin.py."""
    run_final_mapsheet_panel()
