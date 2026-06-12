from qgis.core import (
    QgsProject, QgsSnappingConfig, QgsTolerance, QgsVectorLayer,
    QgsPalLayerSettings, QgsProperty, QgsVectorLayerSimpleLabeling,
    QgsExpressionContext, QgsExpressionContextUtils, QgsPropertyCollection,
    QgsUnitTypes, QgsTextFormat, QgsSimpleLineCallout, QgsLineSymbol,
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
    """Get the correct OverPoint placement enum for the current QGIS version"""
    try:
        # Try the newer enum structure (QGIS 3.40+)
        return QgsPalLayerSettings.Placement.OverPoint
    except AttributeError:
        try:
            # Try the older direct enum (QGIS 3.34 and earlier)
            return QgsPalLayerSettings.OverPoint
        except AttributeError:
            # Fallback to the most basic point placement
            return QgsPalLayerSettings.AroundPoint


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
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
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
            ("apply_labeling", "Apply scale-dependent labeling to Field Notebook")
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
        self.statusLabel.setAlignment(Qt.AlignCenter)
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
                    'Linear Geoscience', Qgis.Warning)

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
            self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(True)

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
        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.buttonBox.button(QDialogButtonBox.Cancel).setEnabled(False)

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

        QgsMessageLog.logMessage("Configuration completed successfully!", 'Linear Geoscience', Qgis.Info)


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
                QgsMessageLog.logMessage(f"[CRS] Updated CRS for {layer.name()} (ID: {layer_id[:8]})", 'Linear Geoscience', Qgis.Info)

        if updated:
            QgsMessageLog.logMessage(f"[CRS] Updated {updated} layers to match project CRS", 'Linear Geoscience', Qgis.Info)
        else:
            QgsMessageLog.logMessage("[CRS] No layers selected for CRS update", 'Linear Geoscience', Qgis.Warning)

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
            QgsMessageLog.logMessage(f"[Scale] Set reference scale 1:{scale_value} for {updated} layers", 'Linear Geoscience', Qgis.Info)
        else:
            QgsMessageLog.logMessage("[Scale] No layers selected for reference scale", 'Linear Geoscience', Qgis.Warning)

    def configure_snapping(self, layers_dict):
        """Configure snapping for relevant layers"""
        # Get the current project snapping configuration
        snapping_config = self.project.snappingConfig()

        # Ensure snapping is enabled globally
        snapping_config.setEnabled(True)

        # Force advanced configuration mode
        snapping_config.setMode(QgsSnappingConfig.AdvancedConfiguration)

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
                settings.setType(QgsSnappingConfig.SnappingType.Vertex |
                                 QgsSnappingConfig.SnappingType.Segment)

                # Set tolerance and units
                settings.setTolerance(20)
                settings.setUnits(QgsTolerance.Pixels)

                snapping_config.setIndividualLayerSettings(layer, settings)
                QgsMessageLog.logMessage(f"[Snap] Configured snapping for {layer.name()} (vertex & segment)", 'Linear Geoscience', Qgis.Info)
                layers_configured += 1

        # Apply the updated configuration back to the project
        self.project.setSnappingConfig(snapping_config)

        # Enable topological editing
        self.project.setTopologicalEditing(True)

        if layers_configured > 0:
            QgsMessageLog.logMessage(f"[Snap] Advanced snapping configuration applied to {layers_configured} layers", 'Linear Geoscience', Qgis.Info)
        else:
            QgsMessageLog.logMessage("[Snap] No layers selected for snapping configuration", 'Linear Geoscience', Qgis.Warning)

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

    def create_dip_rule(self, x_value):
        """Create rule for Dip field labels (above symbol, no callouts)"""
        settings = QgsPalLayerSettings()
        settings.fieldName = '"Dip"'
        settings.isExpression = True
        settings.enabled = True

        # Standard text formatting - NO callouts
        settings.setFormat(self.create_standard_text_format())

        # Placement settings - using version-compatible placement
        settings.placement = get_over_point_placement()
        settings.isOffsetFromPoint = True
        settings.offsetUnits = QgsUnitTypes.RenderMapUnits
        settings.autoWrapLength = 35

        # Allow overlaps without penalty
        try:
            from qgis.core import Qgis
            settings.overlapHandling = Qgis.LabelOverlapHandling.AllowOverlapAtNoCost
        except (AttributeError, ImportError):
            pass  # Older QGIS versions

        # Data-defined placement (original expression)
        placement_expression = (
            f'CASE WHEN "Type" = \'Structure\' THEN '
            f'to_string(({x_value} * cos(radians("DipDirection" - 90)))) || \',\' || '
            f'to_string(({x_value} * sin(radians("DipDirection" - 90)))) '
            f'ELSE \'4,-4\' END'
        )

        props = QgsPropertyCollection()
        props.setProperty(QgsPalLayerSettings.OffsetXY,
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
        settings.offsetUnits = QgsUnitTypes.RenderMapUnits

        # Allow overlaps without penalty
        try:
            from qgis.core import Qgis
            settings.overlapHandling = Qgis.LabelOverlapHandling.AllowOverlapAtNoCost
        except (AttributeError, ImportError):
            pass  # Older QGIS versions

        # Data-defined properties
        props = QgsPropertyCollection()

        # Bottom-right placement with rotation
        placement_expression = (
            f'CASE WHEN "Type" = \'Structure\' THEN '
            f'to_string(({x_value} * cos(radians("DipDirection" - 90 + 135)))) || \',\' || '
            f'to_string(({x_value} * sin(radians("DipDirection" - 90 + 135)))) '
            f'ELSE \'15,15\' END'
        )
        props.setProperty(QgsPalLayerSettings.OffsetXY,
                          QgsProperty.fromExpression(placement_expression))

        # Text rotation to match symbol orientation
        rotation_expression = (
            'CASE WHEN "Type" = \'Structure\' THEN "DipDirection" - 90 ELSE 0 END'
        )
        props.setProperty(QgsPalLayerSettings.LabelRotation,
                          QgsProperty.fromExpression(rotation_expression))

        settings.setDataDefinedProperties(props)

        # Create rule
        rule = QgsRuleBasedLabeling.Rule(settings)
        rule.setDescription('SymbolSuffix Labels')
        rule.setFilterExpression(
            '"SymbolSuffix" IS NOT NULL AND "SymbolSuffix" != \'\' AND ("HidePoint" IS NULL OR "HidePoint" != \'X\')')

        return rule

    def create_regolith_note_rule(self):
        """Create rule for Regolith Note labels (Cartographic placement, no callouts)"""
        settings = QgsPalLayerSettings()
        settings.fieldName = '"Comments"'
        settings.isExpression = True
        settings.enabled = True

        # Regolith Note text formatting - NO callouts
        settings.setFormat(self.create_regolith_note_text_format())

        # Placement settings - Cartographic (AroundPoint)
        try:
            # Try newer enum structure first
            settings.placement = QgsPalLayerSettings.Placement.AroundPoint
        except AttributeError:
            # Fallback to older enum
            settings.placement = QgsPalLayerSettings.AroundPoint

        settings.dist = 0.0  # Distance from feature
        settings.distUnits = QgsUnitTypes.RenderMillimeters

        # Prioritize closer labels (cartographic placement setting)
        settings.priority = 5  # Medium-high priority

        # Allow overlaps without penalty
        try:
            from qgis.core import Qgis
            settings.overlapHandling = Qgis.LabelOverlapHandling.AllowOverlapAtNoCost
        except (AttributeError, ImportError):
            pass  # Older QGIS versions

        # Create rule
        rule = QgsRuleBasedLabeling.Rule(settings)
        rule.setDescription('Regolith Note')
        rule.setFilterExpression(
            '"Subtype1" = \'RegolithNote\' AND ("Comments" IS NOT NULL AND "Comments" != \'\') AND ("HidePoint" IS NULL OR "HidePoint" != \'X\')')

        return rule

    def create_fallback_rule(self, x_value):
        """Create fallback rule for Comments/Labels when no Dip data (with callouts)"""
        settings = QgsPalLayerSettings()

        # Original complex expression for fallback
        label_expression = (
            'CASE '
            'WHEN "Dip" IS NOT NULL AND "Dip" != \'\' THEN "Dip" '
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

        # Placement settings - using version-compatible placement
        settings.placement = get_over_point_placement()
        settings.isOffsetFromPoint = True
        settings.offsetUnits = QgsUnitTypes.RenderMapUnits
        settings.autoWrapLength = 35

        # Allow overlaps without penalty
        try:
            from qgis.core import Qgis
            settings.overlapHandling = Qgis.LabelOverlapHandling.AllowOverlapAtNoCost
        except (AttributeError, ImportError):
            pass  # Older QGIS versions

        # Improved placement expression - handle invalid DipDirection and moderate offset
        placement_expression = (
            f'CASE '
            f'WHEN "Type" = \'Structure\' AND "DipDirection" IS NOT NULL AND "DipDirection" != \'\' THEN '
            f'to_string(({x_value} * cos(radians("DipDirection" - 90)))) || \',\' || '
            f'to_string(({x_value} * sin(radians("DipDirection" - 90)))) '
            f'ELSE \'{int(x_value * 4)},-{int(x_value * 2)}\' END'
        )

        props = QgsPropertyCollection()
        props.setProperty(QgsPalLayerSettings.OffsetXY,
                          QgsProperty.fromExpression(placement_expression))
        settings.setDataDefinedProperties(props)

        # Create callout line (ONLY for fallback rule)
        callout = QgsSimpleLineCallout()
        line_symbol = QgsLineSymbol.createSimple({
            'line_color': '#808080',  # Medium grey
            'line_style': 'dash',
            'width': '0.15'  # Thinner line
        })
        callout.setLineSymbol(line_symbol)
        callout.setEnabled(True)
        callout.setOffsetFromLabel(1)  # Short callout offset
        settings.setCallout(callout)

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
        """Configure rule-based labeling for the Field Notebook layer"""
        layer = self.get_layer(layers_dict.get("FieldNotebook"))
        if not layer:
            QgsMessageLog.logMessage("[Label] No Field Notebook layer selected, skipping labeling", 'Linear Geoscience', Qgis.Warning)
            return

        # Get scale-appropriate offset value
        x_value = self.SCALE_TO_OFFSET.get(scale_value, 1)

        # Create root rule (overlap handling is set on each individual rule)
        root = QgsRuleBasedLabeling.Rule(QgsPalLayerSettings())

        # Rule 1: Dip field (no callouts)
        dip_rule = self.create_dip_rule(x_value)
        root.appendChild(dip_rule)

        # Rule 2: SymbolSuffix field (small, italic, no callouts)
        suffix_rule = self.create_suffix_rule(x_value)
        root.appendChild(suffix_rule)

        # Rule 3: Regolith Note (Cartographic placement, no callouts)
        regolith_rule = self.create_regolith_note_rule()
        root.appendChild(regolith_rule)

        # Rule 4: Fallback rule (with callouts)
        fallback_rule = self.create_fallback_rule(x_value)
        root.appendChild(fallback_rule)

        # Apply rule-based labeling
        rules = QgsRuleBasedLabeling(root)
        layer.setLabeling(rules)
        layer.setLabelsEnabled(True)
        layer.triggerRepaint()

        QgsMessageLog.logMessage(f"[Label] Applied rule-based labeling with 4 rules to {layer.name()}", 'Linear Geoscience', Qgis.Info)
        QgsMessageLog.logMessage(f"[Label] Rules: 1-Dip, 2-SymbolSuffix, 3-RegolithNote, 4-Fallback", 'Linear Geoscience', Qgis.Info)
        QgsMessageLog.logMessage(f"[Label] All rules have 'Allow Overlaps without Penalty' enabled", 'Linear Geoscience', Qgis.Info)


def run_configuration():
    """Main function to run the configuration.

    Creates the dialog and shows it. Configuration is run when the user
    clicks OK, with progress shown in the dialog before it closes.
    """
    dialog = ModernLayerConfigDialog()
    result = dialog.exec()

    if result != QDialog.Accepted:
        QgsMessageLog.logMessage("User cancelled. No changes made.", 'Linear Geoscience', Qgis.Info)


def run(iface):
    """Entry point called from mainplugin.py."""
    run_configuration()