"""
Static Mapping Export.

Exports selected layers from a geological mapping geopackage to a
client-ready geopackage with ONLY symbology and labelling styles applied.
Optionally removes unused symbology categories and empty fields, and bakes
a fixed reference scale into each exported layer's style.
"""

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsVectorFileWriter,
    QgsCoordinateTransformContext, Qgis, QgsReadWriteContext,
    QgsRenderContext, QgsCategorizedSymbolRenderer, NULL
)
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QTableWidget, QTableWidgetItem, QTextEdit,
    QHeaderView, QMessageBox, QLineEdit, QGroupBox, QCheckBox,
    QScrollArea, QWidget, QSplitter, QFrame, QComboBox
)
from qgis.PyQt.QtCore import Qt, QDateTime
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtXml import QDomDocument
import os
import re
import sqlite3
import traceback

from ..recode_workflow.remove_unused import remove_unused_categories
from .graphics_check import find_unembedded_graphics

try:
    from .. import plugin_theme as theme
except ImportError:
    theme = None


SCALE_OPTIONS = [
    "1:50", "1:100", "1:200", "1:250", "1:500", "1:1000",
    "1:2000", "1:2500", "1:5000", "1:10000", "1:20000",
    "1:25000", "1:50000", "1:100000", "1:250000"
]
DEFAULT_SCALE = "1:1000"
SCALE_NO_CHANGE = "(no change)"


class StyleFilter:
    """Extracts ONLY symbology (renderer-v2) and labeling from QGIS styles."""

    @staticmethod
    def filter_style(source_layer, log_callback=None):
        """
        Extract only renderer-v2 and labeling elements from a layer's style.

        Args:
            source_layer: QgsVectorLayer with styling to extract
            log_callback: Optional logging function for debug output

        Returns:
            tuple: (filtered_qml_string, has_renderer, has_labeling)
        """
        def debug(msg):
            if log_callback:
                log_callback(f"    [DEBUG] {msg}", "INFO")

        # Export the full style as QDomDocument
        doc = QDomDocument()
        debug(f"Exporting style from layer: {source_layer.name()}")

        # Use the correct API - exportNamedStyle returns error string
        # The document is modified in place
        try:
            error_msg = source_layer.exportNamedStyle(doc)
            debug(f"exportNamedStyle returned: {type(error_msg)} = '{error_msg}'")
        except Exception as e:
            debug(f"exportNamedStyle exception: {e}")
            return None, False, False

        # Check if we got valid content
        root = doc.documentElement()
        if root.isNull():
            debug("Root element is null - no style found")
            return None, False, False

        debug(f"Got style document, root tag: {root.tagName()}")

        # Create new filtered document
        filtered_doc = QDomDocument()

        # Create new root with same attributes
        new_root = filtered_doc.createElement("qgis")

        # Copy essential attributes from original root
        attrs = root.attributes()
        for i in range(attrs.count()):
            attr = attrs.item(i).toAttr()
            new_root.setAttribute(attr.name(), attr.value())

        filtered_doc.appendChild(new_root)

        has_renderer = False
        has_labeling = False

        # Extract renderer-v2 (symbology)
        renderer_nodes = root.elementsByTagName("renderer-v2")
        debug(f"Found {renderer_nodes.count()} renderer-v2 nodes")
        if renderer_nodes.count() > 0:
            renderer = renderer_nodes.at(0).cloneNode(True)
            new_root.appendChild(renderer)
            has_renderer = True

        # Extract labeling
        labeling_nodes = root.elementsByTagName("labeling")
        debug(f"Found {labeling_nodes.count()} labeling nodes")
        if labeling_nodes.count() > 0:
            labeling = labeling_nodes.at(0).cloneNode(True)
            new_root.appendChild(labeling)
            has_labeling = True

        result_xml = filtered_doc.toString(2)
        debug(f"Filtered style length: {len(result_xml)} chars")

        return result_xml, has_renderer, has_labeling


class LayerNameParser:
    """Parses layer names to extract meaningful descriptive parts."""

    @staticmethod
    def extract_base_name(layer_name):
        """
        Extract the descriptive part from a layer name.

        Handles formats like:
        - "1 - FieldNotebook" -> "FieldNotebook"
        - "2 - Overlay" -> "Overlay"
        - "Layer_Name" -> "Layer_Name"
        - "SomeLayer" -> "SomeLayer"

        Args:
            layer_name: Original layer name string

        Returns:
            str: Extracted descriptive name
        """
        # Pattern: number followed by separator (-, _, or space) then the name
        patterns = [
            r'^\d+\s*[-_]\s*(.+)$',      # "1 - Name" or "1_Name" or "1- Name"
            r'^\d+\s+(.+)$',              # "1 Name"
            r'^[A-Za-z]?\d+\s*[-_]\s*(.+)$',  # "A1 - Name"
        ]

        for pattern in patterns:
            match = re.match(pattern, layer_name.strip())
            if match:
                return match.group(1).strip()

        # No pattern matched, return original name
        return layer_name.strip()


class LayerExporter:
    """Handles exporting layers and their filtered styles to a new geopackage."""

    def __init__(self, log_callback):
        self.log = log_callback

    def get_layers_from_gpkg(self, gpkg_path):
        """Get list of vector layer names from a geopackage."""
        layers = []
        try:
            conn = sqlite3.connect(gpkg_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT table_name FROM gpkg_contents
                WHERE data_type = 'features'
                ORDER BY table_name
            """)
            layers = [row[0] for row in cursor.fetchall()]
            conn.close()
        except Exception as e:
            self.log(f"Error reading geopackage: {e}", "ERROR")
        return layers

    def export_layer(self, source_gpkg, layer_name, output_gpkg, new_name,
                     remove_unused=False, reference_scale=None,
                     remove_empty_fields=False):
        """
        Export a single layer to the output geopackage with filtered style.

        Args:
            source_gpkg: Path to source geopackage
            layer_name: Layer name in the source geopackage
            output_gpkg: Path to output geopackage
            new_name: Layer name in the output geopackage
            remove_unused: Prune unused categories from categorized renderers
            reference_scale: int scale denominator to set on the renderer,
                or None to leave the reference scale unchanged
            remove_empty_fields: Delete fields where every value is NULL/blank

        Returns:
            bool: True if successful, False otherwise
        """
        # Load source layer
        uri = f"{source_gpkg}|layername={layer_name}"
        source_layer = QgsVectorLayer(uri, layer_name, "ogr")

        if not source_layer.isValid():
            self.log(f"Failed to load layer: {layer_name}", "ERROR")
            return False

        self.log(f"Exporting layer: {layer_name} -> {new_name}", "INFO")

        # Determine if output gpkg exists (for append mode)
        file_exists = os.path.exists(output_gpkg)

        # Export layer geometry and attributes
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = new_name
        options.fileEncoding = "UTF-8"

        if file_exists:
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        else:
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

        transform_context = QgsCoordinateTransformContext()

        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            source_layer,
            output_gpkg,
            transform_context,
            options
        )

        if error[0] != QgsVectorFileWriter.NoError:
            self.log(f"Failed to export layer data: {error[1]}", "ERROR")
            return False

        self.log(f"  Layer data exported successfully", "SUCCESS")

        # Post-processing pipeline on the exported layer
        try:
            self._post_process_layer(
                source_layer, output_gpkg, new_name,
                remove_unused, reference_scale, remove_empty_fields
            )
        except Exception as e:
            self.log(f"  Post-processing exception: {e}", "ERROR")
            self.log(f"  Traceback: {traceback.format_exc()}", "ERROR")
            # Continue - layer data was exported successfully
            return True

        return True

    def _post_process_layer(self, source_layer, output_gpkg, new_name,
                            remove_unused, reference_scale, remove_empty_fields):
        """
        Run the post-export pipeline on the exported layer:
        remove empty fields -> import filtered style -> prune unused
        categories -> set reference scale -> save style to geopackage.
        """
        # Load the exported layer once; all steps share this instance so the
        # style is saved exactly once at the end
        uri = f"{output_gpkg}|layername={new_name}"
        self.log(f"  Loading exported layer: {uri}", "INFO")
        target_layer = QgsVectorLayer(uri, new_name, "ogr")

        if not target_layer.isValid():
            self.log(f"  Failed to load exported layer for post-processing", "ERROR")
            return

        # Remove empty fields before importing the style, so the style XML
        # never references a field that disappears afterwards
        if remove_empty_fields:
            protected = set()
            if source_layer.renderer():
                protected = set(source_layer.renderer().usedAttributes(QgsRenderContext()))
            self._remove_empty_fields(target_layer, protected,
                                      has_labeling=source_layer.labeling() is not None)

        has_renderer, has_labeling = self._import_filtered_style(source_layer, target_layer)

        if not has_renderer and not has_labeling:
            return

        if remove_unused and has_renderer:
            if not isinstance(target_layer.renderer(), QgsCategorizedSymbolRenderer):
                self.log(f"  Category pruning skipped - renderer is not categorized", "INFO")
            else:
                removed, remaining = remove_unused_categories(
                    target_layer, log=lambda m: self.log(m, "INFO"))
                if removed > 0:
                    self.log(f"  Removed {removed} unused categories, {remaining} remaining", "SUCCESS")
                else:
                    self.log(f"  No unused categories found", "INFO")

        if reference_scale is not None:
            # Re-fetch the renderer - pruning may have replaced it
            renderer = target_layer.renderer()
            if renderer:
                renderer.setReferenceScale(float(reference_scale))
                self.log(f"  Reference scale set to 1:{reference_scale}", "SUCCESS")
            else:
                self.log(f"  No renderer - reference scale skipped", "INFO")

        self._save_style_to_database(target_layer, has_renderer, has_labeling)

    def _remove_empty_fields(self, target_layer, protected_names, has_labeling=False):
        """
        Delete fields where every feature's value is NULL or an
        empty/whitespace string. Never deletes the primary key (fid) or
        fields used by the renderer (protected_names).

        Returns:
            list: Names of removed fields
        """
        self.log(f"  Checking for empty fields...", "INFO")

        provider = target_layer.dataProvider()
        pk_indexes = set(provider.pkAttributeIndexes())
        protected_lower = {name.lower() for name in protected_names}

        fields = target_layer.fields()
        candidates = set()
        protected_skipped = []
        for idx in range(fields.count()):
            if idx in pk_indexes:
                continue
            if fields.at(idx).name().lower() in protected_lower:
                protected_skipped.append(idx)
                continue
            candidates.add(idx)

        if not candidates and not protected_skipped:
            self.log(f"  No removable fields to check", "INFO")
            return []

        # Single scan: drop a field from the empty set once a real value is seen
        still_empty = set(candidates) | set(protected_skipped)
        for feature in target_layer.getFeatures():
            for idx in list(still_empty):
                value = feature.attribute(idx)
                if value is None or value == NULL:
                    continue
                if isinstance(value, str) and not value.strip():
                    continue
                still_empty.discard(idx)
            if not still_empty:
                break

        # Warn about empty-but-protected fields (kept because symbology uses them)
        for idx in protected_skipped:
            if idx in still_empty:
                self.log(f"  Field '{fields.at(idx).name()}' is empty but kept "
                         f"(used by symbology)", "WARNING")
        still_empty -= set(protected_skipped)

        if not still_empty:
            self.log(f"  No empty fields found", "INFO")
            return []

        removed_names = [fields.at(idx).name() for idx in sorted(still_empty)]

        # PyQGIS binding requires a list; descending order so earlier
        # deletions can't shift later indexes
        if not provider.deleteAttributes(sorted(still_empty, reverse=True)):
            self.log(f"  Failed to delete empty fields: {', '.join(removed_names)}", "ERROR")
            return []

        target_layer.updateFields()
        self.log(f"  Removed {len(removed_names)} empty field(s): "
                 f"{', '.join(removed_names)}", "SUCCESS")

        if has_labeling:
            self.log(f"  Layer has labelling - removed fields were all empty, "
                     f"so any labels referencing them were blank anyway", "WARNING")

        return removed_names

    def _import_filtered_style(self, source_layer, target_layer):
        """
        Import the filtered style (renderer + labeling only) from the source
        layer onto the target layer. Does NOT save to the database.

        Returns:
            tuple: (has_renderer, has_labeling); (False, False) on failure
        """
        self.log(f"  Extracting filtered style...", "INFO")

        # Get filtered style with debug logging
        filtered_qml, has_renderer, has_labeling = StyleFilter.filter_style(source_layer, self.log)

        if filtered_qml is None or (not has_renderer and not has_labeling):
            self.log(f"  No symbology or labeling found - layer exported without style", "WARNING")
            return False, False

        self.log(f"  Found: renderer={has_renderer}, labeling={has_labeling}", "INFO")

        # Apply the filtered style via temporary QML
        temp_doc = QDomDocument()
        set_result = temp_doc.setContent(filtered_qml)
        self.log(f"  QDomDocument.setContent result: {set_result}", "INFO")

        # Import the filtered style
        self.log(f"  Importing filtered style to target layer...", "INFO")
        try:
            result = target_layer.importNamedStyle(temp_doc)
            self.log(f"  importNamedStyle returned: {type(result)} = {result}", "INFO")

            # Handle various return types
            if isinstance(result, tuple):
                success = result[0] if result else False
            elif isinstance(result, bool):
                success = result
            elif isinstance(result, str):
                # Empty string typically means success
                success = True
            else:
                success = True  # Assume success if no error
        except Exception as e:
            self.log(f"  importNamedStyle exception: {e}", "ERROR")
            return False, False

        if not success:
            self.log(f"  Failed to import filtered style", "ERROR")
            return False, False

        self.log(f"  Style imported successfully", "INFO")
        return has_renderer, has_labeling

    def _save_style_to_database(self, target_layer, has_renderer, has_labeling):
        """Save the target layer's style to the geopackage layer_styles table."""
        style_name = "default"
        style_desc = "Static mapping export - symbology and labeling only"

        self.log(f"  Saving style to database...", "INFO")
        try:
            result = target_layer.saveStyleToDatabase(
                style_name,
                style_desc,
                True,  # useAsDefault
                ""     # uiFileContent (empty)
            )
            self.log(f"  saveStyleToDatabase returned: {type(result)} = {result}", "INFO")

            # Handle various return types
            if isinstance(result, tuple) and len(result) >= 2:
                msg, saved = result[0], result[1]
            elif isinstance(result, tuple) and len(result) == 1:
                msg, saved = "", result[0]
            elif isinstance(result, bool):
                msg, saved = "", result
            elif isinstance(result, str):
                # String return typically is error message (empty = success)
                msg, saved = result, (result == "" or result is None)
            else:
                msg, saved = str(result), False
                self.log(f"  Unexpected return type: {type(result)}", "WARNING")

        except Exception as e:
            self.log(f"  saveStyleToDatabase exception: {e}", "ERROR")
            return

        if saved:
            style_parts = []
            if has_renderer:
                style_parts.append("symbology")
            if has_labeling:
                style_parts.append("labeling")
            self.log(f"  Style saved to database: {', '.join(style_parts)}", "SUCCESS")
        else:
            self.log(f"  Failed to save style to database: {msg}", "ERROR")


class StaticMappingExportDialog(QDialog):
    """Main GUI dialog for the Static Mapping Export tool."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Static Mapping Export")
        self.setMinimumSize(800, 700)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        if theme:
            self.setStyleSheet(theme.dialog_style() + theme.group_box_style())

        self.source_gpkg = ""
        self.layer_checkboxes = {}       # {original_name: checkbox}
        self.layer_rename_inputs = {}    # {original_name: line_edit}
        self.layer_base_names = {}       # {original_name: extracted_base_name}
        self.layer_order = []            # Preserves original order of layers
        self.layer_scale_combos = {}     # {original_name: scale_combo}
        self.layer_scale_overridden = {} # {original_name: bool, True if user changed scale}

        self._setup_ui()
        self._connect_signals()

        self.log("Static Mapping Export initialized", "INFO")
        self.log("Select a source geopackage to begin", "INFO")

    def _setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Source geopackage selection
        source_group = QGroupBox("Source Geopackage")
        source_layout = QHBoxLayout(source_group)

        self.source_path_edit = QLineEdit()
        self.source_path_edit.setReadOnly(True)
        self.source_path_edit.setPlaceholderText("Select source geopackage...")
        source_layout.addWidget(self.source_path_edit)

        self.browse_source_btn = QPushButton("Browse...")
        self.browse_source_btn.setFixedWidth(100)
        source_layout.addWidget(self.browse_source_btn)

        layout.addWidget(source_group)

        # Layer selection and renaming
        layers_group = QGroupBox("Layer Selection and Renaming")
        layers_layout = QVBoxLayout(layers_group)

        layers_header = QHBoxLayout()
        layers_header.addWidget(QLabel("Select layers to export (auto-numbered based on selection):"))
        layers_header.addStretch()

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.setFixedWidth(80)
        layers_header.addWidget(self.select_all_btn)

        self.select_none_btn = QPushButton("Select None")
        self.select_none_btn.setFixedWidth(80)
        layers_header.addWidget(self.select_none_btn)

        layers_layout.addLayout(layers_header)

        # Scrollable layer list
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumHeight(200)
        scroll_area.setMaximumHeight(300)

        self.layers_container = QWidget()
        self.layers_layout = QVBoxLayout(self.layers_container)
        self.layers_layout.setAlignment(Qt.AlignTop)
        scroll_area.setWidget(self.layers_container)

        layers_layout.addWidget(scroll_area)
        layout.addWidget(layers_group)

        # Post-processing options
        post_group = QGroupBox("Post-Processing")
        post_layout = QVBoxLayout(post_group)

        self.remove_unused_cb = QCheckBox(
            "Remove unused symbology categories from exported layers")
        self.remove_unused_cb.setChecked(True)
        post_layout.addWidget(self.remove_unused_cb)

        self.remove_empty_fields_cb = QCheckBox(
            "Remove empty fields (all values NULL or blank)")
        self.remove_empty_fields_cb.setChecked(True)
        post_layout.addWidget(self.remove_empty_fields_cb)

        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("Reference scale (all layers):"))
        self.global_scale_combo = QComboBox()
        self.global_scale_combo.addItems(SCALE_OPTIONS)
        self.global_scale_combo.setCurrentText(DEFAULT_SCALE)
        self.global_scale_combo.setFixedWidth(110)
        self.global_scale_combo.setToolTip(
            "Reference scale applied to every exported layer.\n"
            "Override or skip individual layers using the dropdown in the layer list.")
        scale_layout.addWidget(self.global_scale_combo)
        scale_layout.addStretch()
        post_layout.addLayout(scale_layout)

        layout.addWidget(post_group)

        # Output geopackage selection
        output_group = QGroupBox("Output Geopackage")
        output_layout = QHBoxLayout(output_group)

        self.output_path_edit = QLineEdit()
        self.output_path_edit.setReadOnly(True)
        self.output_path_edit.setPlaceholderText("Select output geopackage location...")
        output_layout.addWidget(self.output_path_edit)

        self.browse_output_btn = QPushButton("Browse...")
        self.browse_output_btn.setFixedWidth(100)
        output_layout.addWidget(self.browse_output_btn)

        layout.addWidget(output_group)

        # Export button
        export_layout = QHBoxLayout()
        export_layout.addStretch()

        self.export_btn = QPushButton("Export Selected Layers")
        self.export_btn.setFixedWidth(200)
        self.export_btn.setFixedHeight(40)
        font = self.export_btn.font()
        font.setBold(True)
        self.export_btn.setFont(font)
        self.export_btn.setEnabled(False)
        if theme:
            self.export_btn.setStyleSheet(theme.action_button_style(True))
        export_layout.addWidget(self.export_btn)

        export_layout.addStretch()
        layout.addLayout(export_layout)

        # Log panel
        log_group = QGroupBox("Export Log")
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(150)
        font = QFont("Consolas", 9)
        self.log_text.setFont(font)
        log_layout.addWidget(self.log_text)

        clear_log_layout = QHBoxLayout()
        clear_log_layout.addStretch()
        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.setFixedWidth(80)
        clear_log_layout.addWidget(self.clear_log_btn)
        log_layout.addLayout(clear_log_layout)

        layout.addWidget(log_group)

    def _connect_signals(self):
        """Connect UI signals to slots."""
        self.browse_source_btn.clicked.connect(self._browse_source)
        self.browse_output_btn.clicked.connect(self._browse_output)
        self.export_btn.clicked.connect(self._do_export)
        self.select_all_btn.clicked.connect(self._select_all_layers)
        self.select_none_btn.clicked.connect(self._select_none_layers)
        self.clear_log_btn.clicked.connect(self._clear_log)
        self.global_scale_combo.currentTextChanged.connect(self._on_global_scale_changed)

    def log(self, message, level="INFO"):
        """Add a log message with color coding."""
        timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")

        colors = {
            "INFO": "#000000",
            "SUCCESS": "#2e7d32",
            "WARNING": "#f57c00",
            "ERROR": "#c62828"
        }

        color = colors.get(level, "#000000")
        formatted = f'<span style="color:{color}">[{timestamp}] [{level}] {message}</span>'
        self.log_text.append(formatted)

        # Auto-scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _clear_log(self):
        """Clear the log panel."""
        self.log_text.clear()
        self.log("Log cleared", "INFO")

    def _browse_source(self):
        """Open file dialog to select source geopackage."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Source Geopackage",
            "",
            "Geopackage (*.gpkg);;All Files (*)"
        )

        if path:
            self.source_gpkg = path
            self.source_path_edit.setText(path)
            self.log(f"Source selected: {os.path.basename(path)}", "INFO")
            self._load_layers()
            self._update_export_button()

    def _browse_output(self):
        """Open file dialog to select output geopackage location."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Select Output Geopackage",
            "",
            "Geopackage (*.gpkg)"
        )

        if path:
            if not path.lower().endswith('.gpkg'):
                path += '.gpkg'
            self.output_path_edit.setText(path)
            self.log(f"Output selected: {os.path.basename(path)}", "INFO")
            self._update_export_button()

    def _load_layers(self):
        """Load layers from the source geopackage into the layer list."""
        # Clear existing layer widgets
        for checkbox in self.layer_checkboxes.values():
            checkbox.deleteLater()
        for widget in self.layer_rename_inputs.values():
            widget.deleteLater()
        for combo in self.layer_scale_combos.values():
            combo.deleteLater()

        # Clear the layout
        while self.layers_layout.count():
            item = self.layers_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.layer_checkboxes = {}
        self.layer_rename_inputs = {}
        self.layer_base_names = {}
        self.layer_order = []
        self.layer_scale_combos = {}
        self.layer_scale_overridden = {}

        # Get layers from geopackage
        exporter = LayerExporter(self.log)
        layers = exporter.get_layers_from_gpkg(self.source_gpkg)

        if not layers:
            self.log("No vector layers found in geopackage", "WARNING")
            return

        self.log(f"Found {len(layers)} layers", "SUCCESS")

        # Create row for each layer
        for layer_name in layers:
            self.layer_order.append(layer_name)

            # Extract base name for auto-naming
            base_name = LayerNameParser.extract_base_name(layer_name)
            self.layer_base_names[layer_name] = base_name

            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(5, 2, 5, 2)

            # Checkbox with original name
            checkbox = QCheckBox(layer_name)
            checkbox.setMinimumWidth(250)
            checkbox.stateChanged.connect(self._on_selection_changed)
            row_layout.addWidget(checkbox)

            # Arrow label
            arrow_label = QLabel("->")
            row_layout.addWidget(arrow_label)

            # New name input (will be auto-populated)
            name_input = QLineEdit()
            name_input.setPlaceholderText("Select layer to auto-generate name...")
            name_input.textChanged.connect(self._update_export_button)
            row_layout.addWidget(name_input)

            # Per-layer reference scale (tracks global until manually changed)
            scale_combo = QComboBox()
            scale_combo.addItem(SCALE_NO_CHANGE)
            scale_combo.addItems(SCALE_OPTIONS)
            scale_combo.setCurrentText(self.global_scale_combo.currentText())
            scale_combo.setFixedWidth(110)
            scale_combo.setToolTip(
                "Reference scale for this layer.\n"
                f"'{SCALE_NO_CHANGE}' keeps the layer's existing reference scale.")
            # 'activated' fires only on user interaction, never on setCurrentText
            scale_combo.activated.connect(
                lambda _, name=layer_name: self._on_layer_scale_changed(name))
            row_layout.addWidget(scale_combo)

            self.layers_layout.addWidget(row_widget)
            self.layer_checkboxes[layer_name] = checkbox
            self.layer_rename_inputs[layer_name] = name_input
            self.layer_scale_combos[layer_name] = scale_combo
            self.layer_scale_overridden[layer_name] = False

        self.log("Layer names auto-detected. Select layers to see numbered names.", "INFO")

    def _on_selection_changed(self):
        """Handle layer selection change - update auto-numbering."""
        self._update_auto_names()
        self._update_export_button()

    def _on_layer_scale_changed(self, layer_name):
        """Mark a layer's scale as manually overridden (stops global tracking)."""
        self.layer_scale_overridden[layer_name] = True

    def _on_global_scale_changed(self, text):
        """Apply the global scale to all layers not manually overridden."""
        for layer_name, combo in self.layer_scale_combos.items():
            if not self.layer_scale_overridden.get(layer_name, False):
                combo.setCurrentText(text)

    def _update_auto_names(self):
        """Update the auto-generated names based on current selection."""
        # Get selected layers in original order
        selected_in_order = []
        for layer_name in self.layer_order:
            if layer_name in self.layer_checkboxes:
                if self.layer_checkboxes[layer_name].isChecked():
                    selected_in_order.append(layer_name)

        # Update names with sequential numbering
        for i, layer_name in enumerate(selected_in_order, start=1):
            base_name = self.layer_base_names.get(layer_name, layer_name)
            new_name = f"{i}_{base_name}"

            # Only update if not manually edited (check if current matches expected pattern)
            current_text = self.layer_rename_inputs[layer_name].text()
            # Update if empty or if it looks like an auto-generated name
            if not current_text or re.match(r'^\d+_', current_text):
                self.layer_rename_inputs[layer_name].blockSignals(True)
                self.layer_rename_inputs[layer_name].setText(new_name)
                self.layer_rename_inputs[layer_name].blockSignals(False)

        # Clear names for unselected layers
        for layer_name in self.layer_order:
            if layer_name in self.layer_checkboxes:
                if not self.layer_checkboxes[layer_name].isChecked():
                    self.layer_rename_inputs[layer_name].blockSignals(True)
                    self.layer_rename_inputs[layer_name].clear()
                    self.layer_rename_inputs[layer_name].blockSignals(False)

    def _select_all_layers(self):
        """Select all layer checkboxes."""
        for checkbox in self.layer_checkboxes.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(True)
            checkbox.blockSignals(False)
        self._on_selection_changed()

    def _select_none_layers(self):
        """Deselect all layer checkboxes."""
        for checkbox in self.layer_checkboxes.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(False)
            checkbox.blockSignals(False)
        self._on_selection_changed()

    def _update_export_button(self):
        """Enable/disable export button based on current state."""
        has_source = bool(self.source_gpkg)
        has_output = bool(self.output_path_edit.text())
        has_selection = any(cb.isChecked() for cb in self.layer_checkboxes.values())

        # Check for valid new names on selected layers
        valid_names = True
        if has_selection:
            for layer_name, checkbox in self.layer_checkboxes.items():
                if checkbox.isChecked():
                    new_name = self.layer_rename_inputs[layer_name].text().strip()
                    if not new_name:
                        valid_names = False
                        break

        self.export_btn.setEnabled(has_source and has_output and has_selection and valid_names)

    def _get_selected_layers(self):
        """Get ordered dictionary of selected layers with their new names."""
        selected = {}
        for layer_name in self.layer_order:
            if layer_name in self.layer_checkboxes:
                if self.layer_checkboxes[layer_name].isChecked():
                    new_name = self.layer_rename_inputs[layer_name].text().strip()
                    selected[layer_name] = new_name
        return selected

    def _check_embedded_graphics(self, selected):
        """
        Pre-export scan of every selected source layer for file-based symbol
        graphics (custom SVGs, raster images) that won't resolve on a client
        machine. Logs findings; if any are found, shows a warning dialog.

        Args:
            selected: {original_name: new_name} from _get_selected_layers()

        Returns:
            bool: True to proceed with the export, False if cancelled.
        """
        self.log("Checking symbol graphics are embedded or built-in...", "INFO")

        findings_by_layer = {}  # {new_name: [finding dicts]}
        for layer_name, new_name in selected.items():
            uri = f"{self.source_gpkg}|layername={layer_name}"
            layer = QgsVectorLayer(uri, layer_name, "ogr")
            if not layer.isValid():
                self.log(f"  {layer_name}: could not load for graphics check - skipped", "WARNING")
                continue

            try:
                findings = find_unembedded_graphics(layer)
            except Exception as e:
                self.log(f"  {layer_name}: graphics check failed ({e}) - skipped", "WARNING")
                continue

            if not findings:
                self.log(f"  {layer_name}: OK", "INFO")
                continue

            findings_by_layer[new_name] = findings
            for f in findings:
                self.log(f"  {layer_name}: {f['path']} "
                         f"({f['kind']}, {f['context']}) - {f['reason']}", "WARNING")

        if not findings_by_layer:
            self.log("All symbol graphics are embedded or built-in", "SUCCESS")
            return True

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Unembedded Symbol Graphics")
        box.setText(self._format_graphics_warning(findings_by_layer))
        continue_btn = box.addButton("Continue Anyway", QMessageBox.AcceptRole)
        cancel_btn = box.addButton("Cancel Export", QMessageBox.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.exec()
        return box.clickedButton() is continue_btn

    @staticmethod
    def _format_graphics_warning(findings_by_layer):
        """Build the warning dialog text, capped so it stays readable."""
        max_layers = 6
        max_files = 4

        lines = [
            "Some layers reference symbol graphics by file path. These will",
            "NOT display on the client's machine because the files are not",
            "embedded in the style:",
            "",
        ]
        for i, (new_name, findings) in enumerate(findings_by_layer.items()):
            if i >= max_layers:
                lines.append(f"... and {len(findings_by_layer) - max_layers} more layer(s)")
                break
            lines.append(f"{new_name}:")
            for f in findings[:max_files]:
                lines.append(f"  - {f['basename']} ({f['kind']}, {f['context']}) - {f['reason']}")
            if len(findings) > max_files:
                lines.append(f"  ... and {len(findings) - max_files} more file(s)")
        lines += [
            "",
            "To fix: in Layer Properties > Symbology, open each symbol's",
            "SVG/image source and set it to 'Embedded', save the style to",
            "the geopackage, then re-run the export. Full paths are in the",
            "export log.",
            "",
            "Continue with the export anyway?",
        ]
        return "\n".join(lines)

    def _do_export(self):
        """Perform the export operation."""
        selected = self._get_selected_layers()
        output_path = self.output_path_edit.text()

        # Check for duplicate new names
        new_names = list(selected.values())
        if len(new_names) != len(set(new_names)):
            QMessageBox.warning(
                self,
                "Duplicate Names",
                "Each layer must have a unique new name."
            )
            return

        # Pre-export check: flag symbol graphics that won't resolve on a
        # client's machine (custom SVG paths, raster image paths). Must run
        # before the overwrite confirmation, which deletes the existing file.
        if not self._check_embedded_graphics(selected):
            self.log("Export cancelled - unembedded symbol graphics", "WARNING")
            return

        # Confirm if output exists
        if os.path.exists(output_path):
            reply = QMessageBox.question(
                self,
                "Confirm Overwrite",
                f"Output file already exists:\n{output_path}\n\nOverwrite?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
            # Delete existing file to start fresh
            try:
                os.remove(output_path)
            except Exception as e:
                self.log(f"Failed to remove existing file: {e}", "ERROR")
                return

        remove_unused = self.remove_unused_cb.isChecked()
        remove_empty = self.remove_empty_fields_cb.isChecked()

        self.log("=" * 50, "INFO")
        self.log("STARTING EXPORT", "INFO")
        self.log(f"Exporting {len(selected)} layers", "INFO")
        self.log(f"Remove unused symbology: {'ON' if remove_unused else 'OFF'}", "INFO")
        self.log(f"Remove empty fields: {'ON' if remove_empty else 'OFF'}", "INFO")
        self.log(f"Reference scale (global): {self.global_scale_combo.currentText()}", "INFO")
        self.log("=" * 50, "INFO")

        exporter = LayerExporter(self.log)

        success_count = 0
        fail_count = 0

        for layer_name, new_name in selected.items():
            scale_text = self.layer_scale_combos[layer_name].currentText()
            ref_scale = None if scale_text == SCALE_NO_CHANGE else int(scale_text.split(":")[1])

            try:
                if exporter.export_layer(self.source_gpkg, layer_name, output_path, new_name,
                                         remove_unused=remove_unused,
                                         reference_scale=ref_scale,
                                         remove_empty_fields=remove_empty):
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                self.log(f"Exception exporting {layer_name}: {e}", "ERROR")
                fail_count += 1

        self.log("=" * 50, "INFO")
        self.log("EXPORT COMPLETE", "INFO")
        self.log(f"Successful: {success_count} | Failed: {fail_count}",
                 "SUCCESS" if fail_count == 0 else "WARNING")
        self.log(f"Output: {output_path}", "INFO")
        self.log("=" * 50, "INFO")

        if fail_count == 0:
            QMessageBox.information(
                self,
                "Export Complete",
                f"Successfully exported {success_count} layers to:\n{output_path}"
            )
        else:
            QMessageBox.warning(
                self,
                "Export Complete with Errors",
                f"Exported {success_count} layers.\n{fail_count} layer(s) failed.\n\nCheck the log for details."
            )


def run_static_mapping_export(iface):
    """Launch the Static Mapping Export dialog."""
    dialog = StaticMappingExportDialog(iface.mainWindow())
    dialog.exec()
    return dialog
