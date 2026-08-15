from qgis.core import (
    QgsProject, QgsSnappingConfig, QgsVectorLayer,
    QgsPalLayerSettings, QgsProperty, QgsVectorLayerSimpleLabeling,
    QgsExpressionContext, QgsExpressionContextUtils, QgsPropertyCollection,
    QgsTextFormat, QgsSimpleLineCallout, QgsLineSymbol,
    QgsRuleBasedLabeling, QgsMessageLog, Qgis
)
from qgis.PyQt.QtWidgets import (
    QDialog, QWidget, QFormLayout, QComboBox, QDialogButtonBox,
    QCheckBox, QVBoxLayout, QLabel, QGroupBox, QProgressBar,
    QHBoxLayout, QSizePolicy, QSpacerItem
)
from qgis.PyQt.QtGui import QFont, QColor
from qgis.PyQt.QtCore import Qt, QTimer
import os.path

try:
    from .layer_select import layer_candidates, populate_layer_combo
except ImportError:
    from layer_select import layer_candidates, populate_layer_combo


def get_over_point_placement():
    """OverPoint label placement (Qgis.LabelPlacement; QGIS 3.26+ and 4.x)."""
    return Qgis.LabelPlacement.OverPoint


class ModernLayerConfigDialog(QDialog):
    """Modern unified dialog for layer selection and configuration options"""

    def __init__(self, parent=None):
        super(ModernLayerConfigDialog, self).__init__(parent)
        self.setWindowTitle("Layer Configuration")
        self.resize(550, 600)

        # Main layout
        mainLayout = QVBoxLayout(self)
        mainLayout.setSpacing(10)

        # Add layer selection section
        self.setupLayerSelectionSection(mainLayout)

        # Add options section
        self.setupOptionsSection(mainLayout)

        # Add scale selection section
        self.setupScaleSection(mainLayout)

        # Add progress section
        self.setupProgressSection(mainLayout)

        # Add standard dialog buttons
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttonBox.accepted.connect(self.onAccepted)
        self.buttonBox.rejected.connect(self.reject)
        mainLayout.addWidget(self.buttonBox)

        # Initialize progress variables
        self.current_progress = 0
        self.configuration_complete = False
        self.progress_timer = QTimer()
        self.progress_timer.timeout.connect(self.updateProgressBar)

    def setupLayerSelectionSection(self, mainLayout):
        """Setup the layer selection section"""
        layerGroup = QGroupBox("Layer Selection")
        layerLayout = QVBoxLayout(layerGroup)

        # Create and populate layer dropdowns in a form layout
        formLayout = QFormLayout()
        formLayout.setSpacing(10)

        self.layerCombos = {}
        layerTypes = {
            "FieldNotebook": "Field Notebook Layer:",
            "Overlay": "Overlay Layer:",
            "Linework": "Linework Layer:",
            "Basemap": "Basemap Layer:"
        }

        for key, label in layerTypes.items():
            combo = QComboBox()
            combo.setMinimumWidth(350)
            combo.addItem("")  # Empty option
            self.layerCombos[key] = combo

            # Add a label
            layerLabel = QLabel(label)
            layerLabel.setMinimumWidth(120)

            formLayout.addRow(layerLabel, combo)

        layerLayout.addLayout(formLayout)

        # Populate dropdowns with layers from project
        self.populateLayerDropdowns()

        mainLayout.addWidget(layerGroup)

    def setupOptionsSection(self, mainLayout):
        """Setup the options section"""
        optionsGroup = QGroupBox("Options")
        optionsLayout = QVBoxLayout(optionsGroup)

        # Create option checkboxes
        options = [
            ("apply_crs", "Align layer CRS with project CRS"),
            ("apply_snapping", "Configure advanced snapping settings"),
            ("apply_labeling", "Apply scale-dependent labeling to Field Notebook and Overlay")
        ]

        self.option_checkboxes = {}

        for option_id, title in options:
            checkbox = QCheckBox(title)
            checkbox.setChecked(True)
            self.option_checkboxes[option_id] = checkbox
            optionsLayout.addWidget(checkbox)

        mainLayout.addWidget(optionsGroup)

    def setupScaleSection(self, mainLayout):
        """Setup the scale selection section"""
        scaleGroup = QGroupBox("Reference Scale")
        scaleLayout = QVBoxLayout(scaleGroup)

        # Scale options
        formLayout = QFormLayout()
        self.scaleCombo = QComboBox()

        # Add scale options
        scale_options = [
            "1:50", "1:100", "1:200", "1:250", "1:500", "1:1000",
            "1:2000", "1:2500", "1:5000", "1:10000", "1:20000",
            "1:25000", "1:50000", "1:100000", "1:250000"
        ]
        self.scaleCombo.addItems(scale_options)

        # Default to 1:1000 (or closest available)
        default_index = scale_options.index("1:1000") if "1:1000" in scale_options else 0
        self.scaleCombo.setCurrentIndex(default_index)

        formLayout.addRow("Scale:", self.scaleCombo)
        scaleLayout.addLayout(formLayout)

        mainLayout.addWidget(scaleGroup)

    def setupProgressSection(self, mainLayout):
        """Setup the progress indicators section"""
        self.progressGroup = QGroupBox("Progress")
        progressLayout = QVBoxLayout(self.progressGroup)

        # Create progress bar
        self.progressBar = QProgressBar()
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)
        self.progressBar.setTextVisible(True)
        progressLayout.addWidget(self.progressBar)

        # Create status label
        self.statusLabel = QLabel("Ready")
        self.statusLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progressLayout.addWidget(self.statusLabel)

        mainLayout.addWidget(self.progressGroup)

        # Initially hide progress section - will show during configuration
        self.progressGroup.hide()

    def populateLayerDropdowns(self):
        """Populate all layer dropdowns and auto-select the best name match."""
        target_names = {
            "FieldNotebook": "1 - FieldNotebook",
            "Overlay": "2 - Overlay",
            "Linework": "3 - Linework",
            "Basemap": "4 - Basemap"
        }

        layers = layer_candidates()
        for role, combo in self.layerCombos.items():
            matched = populate_layer_combo(
                combo, layers, placeholder="",
                target_name=target_names.get(role))
            if matched is None:
                QgsMessageLog.logMessage(
                    f"[Match] No match found for {role}, target name: {target_names.get(role)}",
                    'Linear Geoscience', Qgis.MessageLevel.Warning)

    def getSelectedLayers(self):
        """Get dictionary of selected layer IDs by role.

        Returns layer IDs (not names) to ensure correct layer identification
        even when multiple layers share the same name.
        """
        return {key: combo.currentData() or None
                for key, combo in self.layerCombos.items()}

    def getOptions(self):
        """Get dictionary of selected options"""
        return {
            "apply_crs": self.option_checkboxes["apply_crs"].isChecked(),
            "apply_snapping": self.option_checkboxes["apply_snapping"].isChecked(),
            "apply_labeling": self.option_checkboxes["apply_labeling"].isChecked()
        }

    def getScale(self):
        """Get the selected scale value"""
        scale_text = self.scaleCombo.currentText()
        return int(scale_text.split(":")[1])

    def updateProgressBar(self):
        """Update the progress bar and status during configuration"""
        if self.current_progress < 100:
            self.current_progress += 5
            self.progressBar.setValue(self.current_progress)
        else:
            self.progress_timer.stop()
            self.statusLabel.setText("Completed")
            # Enable the OK button again
            self.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def startProgress(self, status_text):
        """Start the progress display with the given status text"""
        # Show progress group
        self.progressGroup.show()

        # Update status
        self.statusLabel.setText(status_text)

        # Reset progress
        self.current_progress = 0
        self.progressBar.setValue(0)

        # Disable buttons during progress
        self.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.buttonBox.button(QDialogButtonBox.StandardButton.Cancel).setEnabled(False)

        # Process events to update UI
        from qgis.PyQt.QtWidgets import QApplication
        QApplication.processEvents()

    def setProgress(self, value, status_text=None):
        """Set progress bar value and optionally update status text"""
        self.progressBar.setValue(value)
        if status_text:
            self.statusLabel.setText(status_text)
        # Process events to update UI immediately
        from qgis.PyQt.QtWidgets import QApplication
        QApplication.processEvents()

    def onAccepted(self):
        """Handle OK button - run configuration then close"""
        # Run the configuration
        self.runConfiguration()

        # Close the dialog after a short delay to show completion
        QTimer.singleShot(500, self.accept)

    def runConfiguration(self):
        """Run the layer configuration with progress updates"""
        # Get user selections
        selected_layers = self.getSelectedLayers()
        options = self.getOptions()
        scale_value = self.getScale()

        # Start progress display
        self.startProgress("Starting configuration...")

        # Create configurator
        configurator = LayerConfigurator()

        # Count enabled options for progress calculation
        total_steps = 1  # Always set reference scale
        if options.get("apply_crs"):
            total_steps += 1
        if options.get("apply_snapping"):
            total_steps += 1
        if options.get("apply_labeling"):
            total_steps += 1

        current_step = 0

        # Process CRS updates if enabled
        if options.get("apply_crs"):
            current_step += 1
            progress = int((current_step / total_steps) * 100)
            self.setProgress(progress, "Updating CRS...")
            configurator.update_layer_crs(selected_layers)

        # Set reference scale
        current_step += 1
        progress = int((current_step / total_steps) * 100)
        self.setProgress(progress, "Setting reference scale...")
        configurator.set_reference_scale(selected_layers, scale_value)

        # Configure snapping if enabled
        if options.get("apply_snapping"):
            current_step += 1
            progress = int((current_step / total_steps) * 100)
            self.setProgress(progress, "Configuring snapping...")
            configurator.configure_snapping(selected_layers)

        # Configure labeling if enabled
        if options.get("apply_labeling"):
            current_step += 1
            progress = int((current_step / total_steps) * 100)
            self.setProgress(progress, "Configuring labeling...")
            configurator.configure_labeling(selected_layers, scale_value)

        # Mark complete
        self.setProgress(100, "Configuration complete!")
        self.configuration_complete = True

        QgsMessageLog.logMessage("Configuration completed successfully!", 'Linear Geoscience', Qgis.MessageLevel.Info)


class LayerConfigurator:
    """Class to handle all layer configuration operations"""

    # Scale to offset mapping for labeling
    SCALE_TO_OFFSET = {
        50: 0.3, 100: 0.6, 200: 1.2, 250: 1.5, 500: 3.0,
        1000: 6.0, 2000: 12.0, 2500: 15.0, 5000: 30.0,
        10000: 60.0, 20000: 120.0, 25000: 150.0,
        50000: 300.0, 100000: 600.0, 250000: 1500.0
    }

    def __init__(self):
        self.project = QgsProject.instance()
        self.project_crs = self.project.crs()

    def get_layer(self, layer_id):
        """Get a layer by its unique ID from the project.

        Uses layer ID for unambiguous lookup, ensuring the correct layer
        is returned even when multiple layers share the same name.
        """
        if not layer_id:
            return None
        return self.project.mapLayer(layer_id)

    def update_layer_crs(self, layers_dict):
        """Update CRS for all selected layers"""
        updated = 0
        for role, layer_id in layers_dict.items():
            layer = self.get_layer(layer_id)
            if layer:
                layer.setCrs(self.project_crs)
                updated += 1
                QgsMessageLog.logMessage(f"[CRS] Updated CRS for {layer.name()} (ID: {layer_id[:8]})", 'Linear Geoscience', Qgis.MessageLevel.Info)

        if updated:
            QgsMessageLog.logMessage(f"[CRS] Updated {updated} layers to match project CRS", 'Linear Geoscience', Qgis.MessageLevel.Info)
        else:
            QgsMessageLog.logMessage("[CRS] No layers selected for CRS update", 'Linear Geoscience', Qgis.MessageLevel.Warning)

    def set_reference_scale(self, layers_dict, scale_value):
        """Set reference scale for selected layers"""
        updated = 0
        for role, layer_id in layers_dict.items():
            layer = self.get_layer(layer_id)
            if layer:
                renderer = layer.renderer()
                if renderer:
                    renderer.setReferenceScale(scale_value)
                    updated += 1

        if updated:
            QgsMessageLog.logMessage(f"[Scale] Set reference scale 1:{scale_value} for {updated} layers", 'Linear Geoscience', Qgis.MessageLevel.Info)
        else:
            QgsMessageLog.logMessage("[Scale] No layers selected for reference scale", 'Linear Geoscience', Qgis.MessageLevel.Warning)

    def configure_snapping(self, layers_dict):
        """Configure snapping for relevant layers"""
        # Get the current project snapping configuration
        snapping_config = self.project.snappingConfig()

        # Ensure snapping is enabled globally
        snapping_config.setEnabled(True)

        # Force advanced configuration mode
        snapping_config.setMode(Qgis.SnappingMode.AdvancedConfiguration)

        # Enable intersection snapping to allow snapping on overlapping geometries
        snapping_config.setIntersectionSnapping(True)

        # Configure snapping for Linework and Basemap layers
        layers_configured = 0
        for role in ["Linework", "Basemap"]:
            layer_id = layers_dict.get(role)
            layer = self.get_layer(layer_id)
            if layer:
                # Configure individual layer settings with both vertex and segment flags
                settings = QgsSnappingConfig.IndividualLayerSettings()

                # Enable the settings
                settings.setEnabled(True)

                # Set type to both vertex and segment flags
                # (setTypeFlag replaces the deprecated setType removed in QGIS 4)
                settings.setTypeFlag(Qgis.SnappingType.Vertex |
                                     Qgis.SnappingType.Segment)

                # Set tolerance and units
                settings.setTolerance(20)
                settings.setUnits(Qgis.MapToolUnit.Pixels)

                snapping_config.setIndividualLayerSettings(layer, settings)
                QgsMessageLog.logMessage(f"[Snap] Configured snapping for {layer.name()} (vertex & segment)", 'Linear Geoscience', Qgis.MessageLevel.Info)
                layers_configured += 1

        # Apply the updated configuration back to the project
        self.project.setSnappingConfig(snapping_config)

        # Enable topological editing
        self.project.setTopologicalEditing(True)

        if layers_configured > 0:
            QgsMessageLog.logMessage(f"[Snap] Advanced snapping configuration applied to {layers_configured} layers", 'Linear Geoscience', Qgis.MessageLevel.Info)
        else:
            QgsMessageLog.logMessage("[Snap] No layers selected for snapping configuration", 'Linear Geoscience', Qgis.MessageLevel.Warning)

    def create_standard_text_format(self):
        """Create standard text format for Dip labels"""
        text_format = QgsTextFormat()
        font = QFont("Arial", 8)
        font.setStyleName("Narrow")
        text_format.setFont(font)
        text_format.setSize(8)
        return text_format

    def create_suffix_text_format(self):
        """Create smaller, italicized text format for SymbolSuffix"""
        text_format = QgsTextFormat()
        font = QFont("Arial", 6)  # Smaller size
        font.setItalic(True)  # Italicized
        font.setStyleName("Narrow")
        text_format.setFont(font)
        text_format.setSize(6)  # Smaller size
        return text_format

    def create_fallback_text_format(self):
        """Create text format for fallback labels (same as original)"""
        text_format = QgsTextFormat()
        font = QFont("Arial", 8)
        font.setStyleName("Narrow")
        text_format.setFont(font)
        text_format.setSize(8)
        return text_format

    def create_regolith_note_text_format(self):
        """Create text format for Regolith Note labels (Arial, Italic, 4.0pt, gray)"""
        text_format = QgsTextFormat()
        font = QFont("Arial", 4)
        font.setItalic(True)
        text_format.setFont(font)
        text_format.setSize(4)
        text_format.setColor(QColor(128, 128, 128))  # Medium gray #808080
        return text_format

    def set_overlap_handling(self, settings, handling):
        """Set label overlap handling so it actually takes effect.

        Plain `settings.overlapHandling = ...` is a silent no-op in PyQGIS
        (sip stores a Python-side attribute; the real setting lives in
        QgsLabelPlacementSettings).
        """
        placement_settings = settings.placementSettings()
        placement_settings.setOverlapHandling(handling)
        settings.setPlacementSettings(placement_settings)

    def create_comment_callout(self):
        """Grey dashed leader line for the comment rules (Regolith/Fallback)."""
        callout = QgsSimpleLineCallout()
        line_symbol = QgsLineSymbol.createSimple({
            'line_color': '#808080',  # Medium grey
            'line_style': 'dash',
            'width': '0.15'  # Thinner line
        })
        callout.setLineSymbol(line_symbol)
        callout.setEnabled(True)
        callout.setOffsetFromAnchor(0.5)  # MM gap at the feature end
        callout.setOffsetFromLabel(1)  # MM gap at the label end
        callout.setMinimumLength(1)  # MM; no stub when label sits at its ring
        return callout

    def apply_dynamic_comment_placement(self, settings, x_value):
        """Engine-arranged placement for comment labels: 8 candidate
        orientations around the point, pushed further out (up to 5x the
        nominal ring) only when closer spots are taken, drawn even when
        overlap is truly unavoidable - so comments never silently vanish.
        Callout length/direction follows wherever the label lands."""
        settings.placement = Qgis.LabelPlacement.OrderedPositionsAroundPoint
        settings.offsetType = Qgis.LabelOffsetType.FromSymbolBounds
        settings.dist = x_value
        settings.distUnits = Qgis.RenderUnit.MapUnits
        point_settings = settings.pointSettings()
        point_settings.setMaximumDistance(5 * x_value)
        point_settings.setMaximumDistanceUnit(Qgis.RenderUnit.MapUnits)
        settings.setPointSettings(point_settings)
        self.set_overlap_handling(
            settings, Qgis.LabelOverlapHandling.AllowOverlapIfRequired)
        settings.setCallout(self.create_comment_callout())

    def create_dip_rule(self, x_value):
        """Create rule for Dip field labels (above symbol, no callouts)"""
        settings = QgsPalLayerSettings()
        # Queried structures label as e.g. '75?' (Confidence system - keep in
        # step with scripts/inject_confidence_system.py)
        settings.fieldName = (
            '"Dip" || CASE WHEN "Confidence" = \'Queried\' '
            'THEN \'?\' ELSE \'\' END')
        settings.isExpression = True
        settings.enabled = True

        # Standard text formatting - NO callouts
        settings.setFormat(self.create_standard_text_format())

        # Placement settings - using version-compatible placement
        settings.placement = get_over_point_placement()
        settings.isOffsetFromPoint = True
        settings.offsetUnits = Qgis.RenderUnit.MapUnits
        settings.autoWrapLength = 35

        # Allow overlaps without penalty
        self.set_overlap_handling(
            settings, Qgis.LabelOverlapHandling.AllowOverlapAtNoCost)

        # Data-defined placement (original expression)
        placement_expression = (
            f'CASE WHEN "Type" = \'Structure\' THEN '
            f'to_string(({x_value} * cos(radians("DipDirection" - 90)))) || \',\' || '
            f'to_string(({x_value} * sin(radians("DipDirection" - 90)))) '
            f'ELSE \'4,-4\' END'
        )

        props = QgsPropertyCollection()
        props.setProperty(QgsPalLayerSettings.Property.OffsetXY,
                          QgsProperty.fromExpression(placement_expression))
        settings.setDataDefinedProperties(props)

        # Create rule
        rule = QgsRuleBasedLabeling.Rule(settings)
        rule.setDescription('Dip Labels')
        rule.setFilterExpression(
            '"Dip" IS NOT NULL AND "Dip" != \'\' AND ("HidePoint" IS NULL OR "HidePoint" != \'X\')')

        return rule

    def create_suffix_rule(self, x_value):
        """Create rule for SymbolSuffix field labels (bottom-right, small, italic, no callouts)"""
        settings = QgsPalLayerSettings()
        settings.fieldName = '"SymbolSuffix"'
        settings.isExpression = True
        settings.enabled = True

        # Smaller, italicized text formatting - NO callouts
        settings.setFormat(self.create_suffix_text_format())

        # Placement settings - using version-compatible placement
        settings.placement = get_over_point_placement()
        settings.isOffsetFromPoint = True
        settings.offsetUnits = Qgis.RenderUnit.MapUnits

        # Suffixes are decluttered rather than drawn on top of each other
        # (matches the hand-tuned template style)
        self.set_overlap_handling(
            settings, Qgis.LabelOverlapHandling.PreventOverlap)

        # Data-defined properties
        props = QgsPropertyCollection()

        # Bottom-right placement with rotation
        placement_expression = (
            f'CASE WHEN "Type" = \'Structure\' THEN '
            f'to_string(({x_value} * cos(radians("DipDirection" - 90 + 135)))) || \',\' || '
            f'to_string(({x_value} * sin(radians("DipDirection" - 90 + 135)))) '
            f'ELSE \'15,15\' END'
        )
        props.setProperty(QgsPalLayerSettings.Property.OffsetXY,
                          QgsProperty.fromExpression(placement_expression))

        # Text rotation to match symbol orientation
        rotation_expression = (
            'CASE WHEN "Type" = \'Structure\' THEN "DipDirection" - 90 ELSE 0 END'
        )
        props.setProperty(QgsPalLayerSettings.Property.LabelRotation,
                          QgsProperty.fromExpression(rotation_expression))

        settings.setDataDefinedProperties(props)

        # Create rule
        rule = QgsRuleBasedLabeling.Rule(settings)
        rule.setDescription('SymbolSuffix Labels')
        rule.setFilterExpression(
            '"SymbolSuffix" IS NOT NULL AND "SymbolSuffix" != \'\' AND ("HidePoint" IS NULL OR "HidePoint" != \'X\')')

        return rule

    def create_regolith_note_rule(self, x_value):
        """Create rule for Regolith Note labels (dynamic placement + callout)"""
        settings = QgsPalLayerSettings()
        settings.fieldName = '"Comments"'
        settings.isExpression = True
        settings.enabled = True

        # Regolith Note text formatting
        settings.setFormat(self.create_regolith_note_text_format())

        # Prioritize closer labels (cartographic placement setting)
        settings.priority = 5  # Medium-high priority

        # Dynamic engine-arranged placement with callout
        self.apply_dynamic_comment_placement(settings, x_value)

        # Create rule
        rule = QgsRuleBasedLabeling.Rule(settings)
        rule.setDescription('Regolith Note')
        rule.setFilterExpression(
            '"Subtype1" = \'RegolithNote\' AND ("Comments" IS NOT NULL AND "Comments" != \'\') AND ("HidePoint" IS NULL OR "HidePoint" != \'X\')')

        return rule

    def create_fallback_rule(self, x_value):
        """Create fallback rule for Comments/Labels when no Dip data (with callouts)"""
        settings = QgsPalLayerSettings()

        # Label/Comments expression (the rule filter already excludes Dip points)
        label_expression = (
            'CASE '
            'WHEN "Label" IS NOT NULL AND "Label" != \'\' THEN "Label" '
            'WHEN "Comments" IS NOT NULL AND "Comments" != \'\' THEN "Comments" '
            'ELSE \'\' '
            'END'
        )

        settings.fieldName = label_expression
        settings.isExpression = True
        settings.enabled = True

        # Standard text formatting WITH callouts
        settings.setFormat(self.create_fallback_text_format())
        settings.autoWrapLength = 35

        # Dynamic engine-arranged placement with callout
        self.apply_dynamic_comment_placement(settings, x_value)

        # Create rule - triggers when no Dip available but other fields have data
        # Excludes RegolithNote items which are handled by the dedicated Regolith Note rule
        rule = QgsRuleBasedLabeling.Rule(settings)
        rule.setDescription('Fallback Labels (Comments/Labels)')
        rule.setFilterExpression(
            '("Dip" IS NULL OR "Dip" = \'\') AND '
            '(("Label" IS NOT NULL AND "Label" != \'\') OR '
            '("Comments" IS NOT NULL AND "Comments" != \'\')) AND '
            '("Subtype1" != \'RegolithNote\' OR "Subtype1" IS NULL) AND '
            '("HidePoint" IS NULL OR "HidePoint" != \'X\')'
        )

        return rule

    def configure_labeling(self, layers_dict, scale_value):
        """Configure scale-dependent labeling: rebuild the Field Notebook
        rule-based labeling, rescale the Overlay label distances in place."""
        layer = self.get_layer(layers_dict.get("FieldNotebook"))
        if layer:
            layer.setLabeling(build_structural_labeling(scale_value))
            layer.setLabelsEnabled(True)
            layer.triggerRepaint()

            QgsMessageLog.logMessage(f"[Label] Applied rule-based labeling with 4 rules to {layer.name()}", 'Linear Geoscience', Qgis.MessageLevel.Info)
            QgsMessageLog.logMessage(f"[Label] Rules: 1-Dip, 2-SymbolSuffix, 3-RegolithNote, 4-Fallback", 'Linear Geoscience', Qgis.MessageLevel.Info)
            QgsMessageLog.logMessage(f"[Label] Comment rules use dynamic callouts (engine-arranged, always visible)", 'Linear Geoscience', Qgis.MessageLevel.Info)
        else:
            QgsMessageLog.logMessage("[Label] No Field Notebook layer selected, skipping labeling", 'Linear Geoscience', Qgis.MessageLevel.Warning)

        overlay = self.get_layer(layers_dict.get("Overlay"))
        if overlay:
            if is_lgs_overlay_labeling(overlay.labeling()):
                rescale_overlay_label_distance(overlay, scale_value)
                QgsMessageLog.logMessage(f"[Label] Rescaled Overlay label distance to {callout_dist_for_scale(scale_value)} map units (1:{scale_value})", 'Linear Geoscience', Qgis.MessageLevel.Info)
            else:
                QgsMessageLog.logMessage(f"[Label] {overlay.name()} labeling is not the LGS Overlay style, leaving untouched", 'Linear Geoscience', Qgis.MessageLevel.Warning)


def offset_for_scale(scale_value):
    """Map-unit label offset distance for a mapping scale.

    Every SCALE_TO_OFFSET entry is exactly 0.006 * scale, so unlisted
    scales fall back to the same linear fit. Drives the Dip/SymbolSuffix
    data-defined offsets; the callout comment rings use
    callout_dist_for_scale instead.
    """
    return LayerConfigurator.SCALE_TO_OFFSET.get(scale_value, scale_value * 0.006)


# Nominal ring distance for callout-bearing labels (FieldNotebook comment
# rules + Overlay outside-polygon labels), deliberately a touch wider than
# the structural offset unit so leader lines read clearly. Mirrored by the
# baked template values in scripts/inject_dynamic_callouts.py and
# scripts/inject_overlay_label_placement.py (U = 5000 * this).
CALLOUT_DIST_FACTOR = 0.0075


def callout_dist_for_scale(scale_value):
    """Map-unit callout ring distance for a mapping scale."""
    return scale_value * CALLOUT_DIST_FACTOR


def is_lgs_overlay_labeling(labeling):
    """True if labeling is the LGS Overlay simple labeling shaped by
    scripts/inject_overlay_label_placement.py (Horizontal placement with a
    callout) — the guard that keeps rescaling off hand-customized styles."""
    if not isinstance(labeling, QgsVectorLayerSimpleLabeling):
        return False
    settings = labeling.settings()
    if settings.placement != Qgis.LabelPlacement.Horizontal:
        return False
    callout = settings.callout()
    return callout is not None and callout.enabled()


def rescale_overlay_label_distance(layer, scale_value):
    """Rescale the Overlay outside-label distance to a mapping scale.

    Edits the existing simple labeling by copy — never rebuilds — so the
    auxiliary-storage dd bindings (manual label moves), fonts, expression
    and callout all survive. dist is the only knob PAL uses for outside
    placement on polygons; maximumDistance is kept mirrored at 5x purely
    for consistency with the injector (it is inert for polygon placement).
    """
    settings = QgsPalLayerSettings(layer.labeling().settings())
    x_value = callout_dist_for_scale(scale_value)
    settings.dist = x_value
    settings.distUnits = Qgis.RenderUnit.MapUnits
    point_settings = settings.pointSettings()
    point_settings.setMaximumDistance(5 * x_value)
    point_settings.setMaximumDistanceUnit(Qgis.RenderUnit.MapUnits)
    settings.setPointSettings(point_settings)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()


def build_structural_labeling(scale_value):
    """Return the canonical LGS rule-based structural labeling with label
    offsets baked for scale_value.

    Shared by Set Mapping Scale and the static mapping export, so exported
    layers can get offsets regenerated to match their export scale.
    """
    configurator = LayerConfigurator()
    x_value = offset_for_scale(scale_value)
    callout_x = callout_dist_for_scale(scale_value)

    # Root rule (overlap handling is set on each individual rule)
    root = QgsRuleBasedLabeling.Rule(QgsPalLayerSettings())
    # Rule 1: Dip field (no callouts)
    root.appendChild(configurator.create_dip_rule(x_value))
    # Rule 2: SymbolSuffix field (small, italic, no callouts)
    root.appendChild(configurator.create_suffix_rule(x_value))
    # Rule 3: Regolith Note (dynamic placement, callout — wider ring unit)
    root.appendChild(configurator.create_regolith_note_rule(callout_x))
    # Rule 4: Fallback rule (dynamic placement, callout — wider ring unit)
    root.appendChild(configurator.create_fallback_rule(callout_x))
    return QgsRuleBasedLabeling(root)


def is_lgs_structural_labeling(labeling):
    """True if labeling is the LGS rule-based structural labeling built by
    this module, detected by the rule descriptions it generates."""
    if not isinstance(labeling, QgsRuleBasedLabeling):
        return False
    descriptions = {rule.description() for rule in labeling.rootRule().children()}
    return {'Dip Labels', 'SymbolSuffix Labels'} <= descriptions


def run_configuration():
    """Main function to run the configuration.

    Creates the dialog and shows it. Configuration is run when the user
    clicks OK, with progress shown in the dialog before it closes.
    """
    dialog = ModernLayerConfigDialog()
    result = dialog.exec()

    if result != QDialog.DialogCode.Accepted:
        QgsMessageLog.logMessage("User cancelled. No changes made.", 'Linear Geoscience', Qgis.MessageLevel.Info)


def run(iface):
    """Entry point called from mainplugin.py."""
    run_configuration()