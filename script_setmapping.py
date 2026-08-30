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
import re

from qgis.PyQt.QtXml import QDomDocument

try:
    from .layer_select import layer_candidates, populate_layer_combo
except ImportError:
    from layer_select import layer_candidates, populate_layer_combo

try:
    from .renderer_compat import PATTERN_RULE_LABEL, SCALE_GATE_RATIO
except ImportError:
    from renderer_compat import PATTERN_RULE_LABEL, SCALE_GATE_RATIO

try:
    from .lgs_layers import BASEMAP, FIELDNOTEBOOK, LINEWORK, OVERLAY
except ImportError:
    from lgs_layers import BASEMAP, FIELDNOTEBOOK, LINEWORK, OVERLAY


#: Project variable carrying the reference scale into label expressions.
#: The data-defined label Size baked by scripts/inject_label_size_scaling.py
#: divides by it to cancel QGIS' referenceScale/mapScale multiplier, so
#: lettering keeps its authored point size at every zoom while symbols go on
#: scaling with the ground. QGIS has no such variable of its own - @map_scale
#: is the only scale in a render expression context - so the plugin publishes
#: one. Kept in step with inject_label_size_scaling.REF_SCALE, whose fallback
#: covers projects predating this.
REFERENCE_SCALE_VAR = "lgs_reference_scale"


#: The literal every style falls back to when the variable is not there.
#: Written as `coalesce(to_real(@lgs_reference_scale), NNNN)` so one pattern
#: finds it wherever it appears - the data-defined label Size baked by
#: scripts/inject_label_size_scaling.py, the Shear Zone Boundary wave's
#: geometry generator, and anything added later that needs the reference
#: scale. Baked as 0 (meaning "unknown, behave as before") and rewritten in
#: the live styles by bake_reference_scale_into_styles() below.
#:
#: Keep in step with inject_label_size_scaling.REF_SCALE;
#: tests/test_label_size_invariance_qgis.py asserts the two still agree.
REFERENCE_SCALE_LITERAL_RE = re.compile(
    r"(coalesce\(\s*to_real\(\s*@lgs_reference_scale\s*\)\s*,\s*)([0-9.]+)(\s*\))")


def set_project_variable(project, scale_value):
    """Publish the reference scale for the label size expressions to read."""
    if project is None:
        return
    QgsExpressionContextUtils.setProjectVariable(
        project, REFERENCE_SCALE_VAR, int(scale_value))


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
        # Row order follows the layer tree (Linework now sits above Overlay).
        layerTypes = {
            "FieldNotebook": "Field Notebook Layer:",
            "Linework": "Linework Layer:",
            "Overlay": "Overlay Layer:",
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
        # find_best_match scores an ordinal-insensitive hit at 95, so these
        # still bind a project built from a pre-Aug-2026 template where
        # Linework/Overlay carried the other numbers.
        target_names = {
            "FieldNotebook": FIELDNOTEBOOK,
            "Overlay": OVERLAY,
            "Linework": LINEWORK,
            "Basemap": BASEMAP,
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


# One family for every label the plugin builds. MUST STAY IN STEP with the
# family baked into the template by scripts/inject_label_cartography.py -
# Set Mapping Scale rebuilds this layer's labeling from the code below.
LABEL_FONT = "Leelawadee UI Semilight"

# Structural label offsets, quoted as POINT distances on the 30 pt marker
# (whose canvas spans 52.9 design units) and converted to ground distances
# at build time. Linear codes carry plunge arrows and need clearance past
# the arrowhead; planar codes hug the dip tick.
#
# Why the conversion rather than Point units on the label: QGIS multiplies
# paper-unit SYMBOL sizes by referenceScale/mapScale, so a 30 pt marker
# keeps a constant GROUND footprint as you zoom. Label offsets get no such
# treatment - measured, a 21.5 pt offset stays ~28 px while its symbol goes
# 40 -> 400 px between 1:5000 and 1:500, i.e. the label slides right across
# the symbol. Ground-fixed symbols need ground-fixed offsets;
# tests/test_label_offset_invariance_qgis.py holds the line.
#
# MUST STAY IN STEP with scripts/inject_fieldnotebook_dip_label_offsets.py,
# which bakes these same values into the template. Set Mapping Scale
# regenerates the whole labeling block from the code below, so a drift here
# silently reverts the template on the next run.
LINEAR_STRUCTURE_CODES = (
    "BAX", "FAX", "FAX1", "FAX1M", "FAX1S", "FAX1Z",
    "FAX2", "FAX2M", "FAX2S", "FAX2Z", "FAX3", "FAX3M", "FAX3S",
    "FAX3Z", "FAX4", "FAX4M", "FAX4S", "FAX4Z", "FAX5", "FAX5M",
    "FAX5S", "FAX5Z", "FAXCR", "FAXK", "FAXSZ", "LME", "LNI",
    "LNI1", "LNI2", "LNI3", "LNI4", "LNI5", "LNISC", "LNS",
    "SLF", "SLK", "STR")
DIP_OFFSET_LINEAR_PT = 21.5
DIP_OFFSET_PLANAR_PT = 9.6
DIP_OFFSET_FALLBACK_PT = 2.3
SUFFIX_OFFSET_PT = 17.0
SUFFIX_OFFSET_FALLBACK_PT = 8.5

# Regolith Notes sit beside their point with no leader (user decision
# 2026-08-17). Point units again, so the note holds its distance from the
# symbol at any reference scale.
REGOLITH_RING = 3.0


POINTS_PER_INCH = 72.0
METRES_PER_INCH = 0.0254


def pt_to_map_units(points, scale):
    """A paper distance at 1:scale, expressed as ground distance.

    Rounded to 2 dp so the expression text the builder emits is identical
    to what the injector bakes - the code/template consistency test compares
    those strings, and unbounded float tails would fail it on formatting
    alone. At 1:5000 this gives 37.92 / 16.93 / 29.99 - which is exactly the
    38 / 17 / 30 map units the template carried before commit 55eaeed
    converted them to paper units.
    """
    return round(points * METRES_PER_INCH / POINTS_PER_INCH * scale, 2)


def _mu(points, scale):
    return "%g" % pt_to_map_units(points, scale)


def dip_offset_expression(scale):
    """Family-aware OffsetXY for the Dip rule, in map units."""
    codes = ",".join("'%s'" % c for c in LINEAR_STRUCTURE_CODES)
    fallback = _mu(DIP_OFFSET_FALLBACK_PT, scale)
    return (
        f'CASE WHEN "Type" = \'Structure\' THEN with_variable(\'lgs_d\', '
        f'CASE WHEN "Subtype1" IN ({codes}) '
        f'THEN {_mu(DIP_OFFSET_LINEAR_PT, scale)} '
        f'ELSE {_mu(DIP_OFFSET_PLANAR_PT, scale)} END, '
        f'to_string((@lgs_d * cos(radians("DipDirection" - 90)))) || \',\' || '
        f'to_string((@lgs_d * sin(radians("DipDirection" - 90))))) '
        f'ELSE \'{fallback},-{fallback}\' END')


def suffix_offset_expression(scale):
    """OffsetXY for the SymbolSuffix rule (dip direction + 135), map units."""
    dist = _mu(SUFFIX_OFFSET_PT, scale)
    fallback = _mu(SUFFIX_OFFSET_FALLBACK_PT, scale)
    return (
        f'CASE WHEN "Type" = \'Structure\' THEN '
        f'to_string(({dist} * cos(radians("DipDirection" - 90 + 135)))) '
        f'|| \',\' || '
        f'to_string(({dist} * sin(radians("DipDirection" - 90 + 135)))) '
        f'ELSE \'{fallback},{fallback}\' END')


class LayerConfigurator:
    """Class to handle all layer configuration operations"""

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
        """Set reference scale for selected layers, and move the gates with it.

        QGIS multiplies paper-unit symbol sizes by referenceScale/mapScale,
        so where an ornament goes sub-pixel is LINEAR in the reference
        scale. Two gates therefore have to move whenever it changes, or
        they stay pinned to whatever the template happened to be baked at:

        The one that matters is the Basemap 'Lithology texture' rule: its
        cutoff is a plain number on the rule, not an expression, so nothing
        else can move it when the mapping scale changes.

        The second is everything whose expression needs to KNOW the reference
        scale. QGIS publishes no reference-scale expression variable, so the
        plugin supplies it twice over: as @lgs_reference_scale here, and as a
        literal baked into the styles themselves (see
        bake_reference_scale_into_styles). Two things read it today and they
        pull opposite ways, both correctly - the label lettering divides by it
        to cancel the multiplier and hold a fixed point size, while the Shear
        Zone Boundary wave wants the multiplier and only needs a stable ground
        size, so it takes the reference scale with no @map_scale term at all.
        """
        set_project_variable(self.project, scale_value)
        baked = self.bake_reference_scale_into_styles(layers_dict, scale_value)
        if baked:
            QgsMessageLog.logMessage(
                f"[Scale] Baked reference scale 1:{scale_value} into "
                f"{baked} layer style(s)", 'Linear Geoscience',
                Qgis.MessageLevel.Info)

        updated = 0
        gates = 0
        for role, layer_id in layers_dict.items():
            layer = self.get_layer(layer_id)
            if layer:
                renderer = layer.renderer()
                if renderer:
                    renderer.setReferenceScale(scale_value)
                    updated += 1
                    gates += self.rescale_pattern_rule(renderer, scale_value)

        if updated:
            QgsMessageLog.logMessage(f"[Scale] Set reference scale 1:{scale_value} for {updated} layers", 'Linear Geoscience', Qgis.MessageLevel.Info)
        else:
            QgsMessageLog.logMessage("[Scale] No layers selected for reference scale", 'Linear Geoscience', Qgis.MessageLevel.Warning)
        QgsMessageLog.logMessage(f"[Scale] Texture cutoff 1:{round(scale_value * SCALE_GATE_RATIO)} ({SCALE_GATE_RATIO}x); retuned {gates} rule(s)", 'Linear Geoscience', Qgis.MessageLevel.Info)

    def bake_reference_scale_into_styles(self, layers_dict, scale_value):
        """Write the reference scale into the styles. Returns layers changed.

        The project variable is the primary source, but it only exists while
        the plugin is loaded to publish it. A project opened without the
        plugin, or handed to someone who does not have it, would fall back to
        "unknown" and lose the compensation. The literal lives in the layer's
        own style, so it travels inside the .qgz.

        Done on the serialised style rather than by walking properties: one
        pattern then catches every consumer - the data-defined label Size, the
        Shear Zone Boundary wave's geometry generator, and anything added
        later - instead of each needing its own hook here.
        """
        changed = 0
        for role, layer_id in layers_dict.items():
            layer = self.get_layer(layer_id)
            if layer is None:
                continue
            document = QDomDocument()
            try:
                layer.exportNamedStyle(document)
            except Exception:
                continue
            style = document.toString()
            if not REFERENCE_SCALE_LITERAL_RE.search(style):
                continue        # nothing in this layer reads the reference scale
            rewritten, count = REFERENCE_SCALE_LITERAL_RE.subn(
                lambda m: m.group(1) + str(int(scale_value)) + m.group(3),
                style)
            if not count:
                continue
            replacement = QDomDocument()
            if not replacement.setContent(rewritten):
                QgsMessageLog.logMessage(
                    f"[Scale] Rewritten style for {layer.name()} did not parse; "
                    "left unchanged", 'Linear Geoscience',
                    Qgis.MessageLevel.Warning)
                continue
            ok, message = layer.importNamedStyle(replacement)
            if not ok:
                QgsMessageLog.logMessage(
                    f"[Scale] Could not apply rewritten style to "
                    f"{layer.name()}: {message}", 'Linear Geoscience',
                    Qgis.MessageLevel.Warning)
                continue
            layer.triggerRepaint()
            changed += 1
        return changed

    def rescale_pattern_rule(self, renderer, scale_value):
        """Retune the lithology texture rule's cutoff. Returns rules changed.

        Matched by label via renderer_compat.PATTERN_RULE_LABEL, never by
        index - the rule is appended last today, but the bake rebuilds the
        whole renderer and position is not a contract.

        setMinimumScale, NOT setMaximumScale. QGIS names these for the view,
        not the denominator: "minimum scale" is the most zoomed-OUT view the
        rule survives, and is stored as the LARGER denominator. The shipped
        rule reads minimumScale 6000 / maximumScale 0, and writing the
        cutoff to maximumScale instead would leave the rule alive only
        between 1:25000 and 1:6000 - an empty range, i.e. no textures ever.
        """
        root = getattr(renderer, "rootRule", None)
        if root is None:          # categorized template: no texture rule
            return 0
        changed = 0
        for rule in root().children():
            if rule.label() == PATTERN_RULE_LABEL:
                rule.setMinimumScale(scale_value * SCALE_GATE_RATIO)
                changed += 1
        return changed

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
        font = QFont(LABEL_FONT, 8)
        text_format.setFont(font)
        text_format.setSize(8)
        return text_format

    def create_suffix_text_format(self):
        """Create smaller, italicized text format for SymbolSuffix"""
        text_format = QgsTextFormat()
        font = QFont(LABEL_FONT, 6)  # Smaller size
        font.setItalic(True)  # Italicized
        text_format.setFont(font)
        text_format.setSize(6)  # Smaller size
        return text_format

    def create_fallback_text_format(self):
        """Create text format for the Comments/Labels fallback rule.

        Annotation, not measurement: smaller and italic, like every other
        free-text label on the sheet."""
        text_format = QgsTextFormat()
        font = QFont(LABEL_FONT, 6)
        font.setItalic(True)
        text_format.setFont(font)
        text_format.setSize(6)
        return text_format

    def create_regolith_note_text_format(self):
        """Create text format for Regolith Note labels (Arial, Italic, 4.0pt, gray)"""
        text_format = QgsTextFormat()
        font = QFont(LABEL_FONT, 4)
        font.setItalic(True)
        text_format.setFont(font)
        text_format.setSize(4)
        text_format.setColor(QColor(144, 144, 144))  # Mid grey, as authored
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

    def set_obstacle_factor(self, settings, factor):
        """Set the labels-as-obstacles weight so it actually takes effect.

        Same sip trap as set_overlap_handling: plain
        `settings.obstacleFactor = ...` stores a Python-side attribute;
        the real setting lives in QgsLabelObstacleSettings.
        """
        obstacle_settings = settings.obstacleSettings()
        obstacle_settings.setFactor(factor)
        settings.setObstacleSettings(obstacle_settings)

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

    def apply_around_point_placement(self, settings, dist, units,
                                     max_dist=None):
        """Engine-arranged placement: 8 candidate orientations around the
        point, drawn even when overlap is truly unavoidable - so a comment
        never silently vanishes. max_dist defaults to dist, i.e. the label
        stays on its nominal ring instead of being pushed further out."""
        settings.placement = Qgis.LabelPlacement.OrderedPositionsAroundPoint
        settings.offsetType = Qgis.LabelOffsetType.FromSymbolBounds
        settings.dist = dist
        settings.distUnits = units
        settings.offsetUnits = units
        point_settings = settings.pointSettings()
        point_settings.setMaximumDistance(
            dist if max_dist is None else max_dist)
        point_settings.setMaximumDistanceUnit(units)
        settings.setPointSettings(point_settings)
        self.set_overlap_handling(
            settings, Qgis.LabelOverlapHandling.AllowOverlapIfRequired)

    def apply_dynamic_comment_placement(self, settings, x_value):
        """Placement for the Fallback comment labels: around the point,
        pushed further out (up to 5x the nominal ring) only when closer
        spots are taken, with a leader that follows wherever the label
        lands. Regolith Notes deliberately do NOT get this - see
        create_regolith_note_rule."""
        self.apply_around_point_placement(
            settings, x_value, Qgis.RenderUnit.MapUnits, 5 * x_value)
        settings.setCallout(self.create_comment_callout())

    def create_dip_rule(self, scale_value):
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

        # Dip readings outrank the annotation around them for placement
        settings.priority = 10

        # Allow overlaps without penalty
        self.set_overlap_handling(
            settings, Qgis.LabelOverlapHandling.AllowOverlapAtNoCost)
        # Structure lettering repels other layers' movable text harder than
        # a default obstacle - the dip number itself never moves or hides,
        # so everything else must make way for it.
        self.set_obstacle_factor(settings, OBSTACLE_FACTOR)

        props = QgsPropertyCollection()
        props.setProperty(
            QgsPalLayerSettings.Property.OffsetXY,
            QgsProperty.fromExpression(dip_offset_expression(scale_value)))
        settings.setDataDefinedProperties(props)

        # Create rule
        rule = QgsRuleBasedLabeling.Rule(settings)
        rule.setDescription('Dip Labels')
        rule.setFilterExpression(
            '"Dip" IS NOT NULL AND "Dip" != \'\' AND ("HidePoint" IS NULL OR "HidePoint" != \'X\')')

        return rule

    def create_suffix_rule(self, scale_value):
        """Create rule for SymbolSuffix field labels (bottom-right, small, italic, no callouts)"""
        settings = QgsPalLayerSettings()
        # A bare field, not an expression - matches what the template holds
        settings.fieldName = "SymbolSuffix"
        settings.isExpression = False
        settings.enabled = True

        # Smaller, italicized text formatting - NO callouts
        settings.setFormat(self.create_suffix_text_format())

        # Placement settings - using version-compatible placement
        settings.placement = get_over_point_placement()
        settings.isOffsetFromPoint = True
        settings.offsetUnits = Qgis.RenderUnit.MapUnits

        # Suffixes yield only to the dip numbers in the placement ladder
        settings.priority = 8

        # Suffixes are decluttered rather than drawn on top of each other
        # (matches the hand-tuned template style)
        self.set_overlap_handling(
            settings, Qgis.LabelOverlapHandling.PreventOverlap)
        self.set_obstacle_factor(settings, OBSTACLE_FACTOR)

        # Data-defined properties
        props = QgsPropertyCollection()

        # Bottom-right placement with rotation
        props.setProperty(
            QgsPalLayerSettings.Property.OffsetXY,
            QgsProperty.fromExpression(suffix_offset_expression(scale_value)))

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

    def create_regolith_note_rule(self):
        """Create rule for Regolith Note labels (beside the point, no leader).

        A regolith note annotates the ground at the point, not a feature you
        need to trace a line back to, so it gets no callout and no push-out
        (user decision 2026-08-17; the leader arrived as collateral when both
        comment rules were routed through one placement helper). The label
        still declutters around the point and is drawn even when overlap is
        unavoidable, so a note never silently vanishes."""
        settings = QgsPalLayerSettings()
        # A bare field, not an expression - matches what the template holds
        settings.fieldName = "Comments"
        settings.isExpression = False
        settings.enabled = True

        # Regolith Note text formatting
        settings.setFormat(self.create_regolith_note_text_format())

        # Bottom of the placement ladder: a regolith note is background
        # annotation and gives way to every other kind of lettering.
        settings.priority = 2

        self.apply_around_point_placement(
            settings, REGOLITH_RING, Qgis.RenderUnit.Points)
        self.set_obstacle_factor(settings, OBSTACLE_FACTOR)

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

        # Comments ride a leader line, so they give way to the map
        # lettering above them in the placement ladder.
        settings.priority = 3

        # Dynamic engine-arranged placement with callout
        self.apply_dynamic_comment_placement(settings, x_value)
        self.set_obstacle_factor(settings, OBSTACLE_FACTOR)

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
        rule-based labeling, rescale the Linework label repeat and the Overlay
        label distances in place."""
        layer = self.get_layer(layers_dict.get("FieldNotebook"))
        if layer:
            layer.setLabeling(build_structural_labeling(scale_value))
            layer.setLabelsEnabled(True)
            layer.triggerRepaint()

            QgsMessageLog.logMessage(f"[Label] Applied rule-based labeling with 4 rules to {layer.name()}", 'Linear Geoscience', Qgis.MessageLevel.Info)
            QgsMessageLog.logMessage(f"[Label] Rules: 1-Dip, 2-SymbolSuffix, 3-RegolithNote, 4-Fallback", 'Linear Geoscience', Qgis.MessageLevel.Info)
            QgsMessageLog.logMessage(f"[Label] Regolith Notes sit beside their point; only the Fallback rule draws a leader", 'Linear Geoscience', Qgis.MessageLevel.Info)
        else:
            QgsMessageLog.logMessage("[Label] No Field Notebook layer selected, skipping labeling", 'Linear Geoscience', Qgis.MessageLevel.Warning)

        linework = self.get_layer(layers_dict.get("Linework"))
        if linework:
            if is_lgs_linework_labeling(linework.labeling()):
                rescale_linework_label_repeat(linework, scale_value)
                QgsMessageLog.logMessage(f"[Label] Rescaled Linework label repeat to {linework_repeat_for_scale(scale_value)} map units (1:{scale_value})", 'Linear Geoscience', Qgis.MessageLevel.Info)
            else:
                QgsMessageLog.logMessage(f"[Label] {linework.name()} labeling is not the LGS Linework style, leaving untouched", 'Linear Geoscience', Qgis.MessageLevel.Warning)

        overlay = self.get_layer(layers_dict.get("Overlay"))
        if overlay:
            if is_lgs_overlay_labeling(overlay.labeling()):
                rescale_overlay_label_distance(overlay, scale_value)
                QgsMessageLog.logMessage(f"[Label] Rescaled Overlay label distance to {callout_dist_for_scale(scale_value)} map units (1:{scale_value})", 'Linear Geoscience', Qgis.MessageLevel.Info)
            else:
                QgsMessageLog.logMessage(f"[Label] {overlay.name()} labeling is not the LGS Overlay style, leaving untouched", 'Linear Geoscience', Qgis.MessageLevel.Warning)

        basemap = self.get_layer(layers_dict.get("Basemap"))
        if basemap:
            # Same labeling shape as the Overlay (Horizontal + callout),
            # scaled by BASEMAP_DIST_FACTOR so the leaders stay short.
            if is_lgs_overlay_labeling(basemap.labeling()):
                rescale_overlay_label_distance(basemap, scale_value,
                                               factor=BASEMAP_DIST_FACTOR)
                QgsMessageLog.logMessage(f"[Label] Rescaled Basemap label distance to {BASEMAP_DIST_FACTOR * callout_dist_for_scale(scale_value)} map units (1:{scale_value})", 'Linear Geoscience', Qgis.MessageLevel.Info)
            else:
                QgsMessageLog.logMessage(f"[Label] {basemap.name()} labeling is not the LGS polygon-callout style, leaving untouched", 'Linear Geoscience', Qgis.MessageLevel.Warning)


# Nominal ring distance for the callout-bearing labels that are left -
# the FieldNotebook Fallback rule and the Overlay outside-polygon labels.
# The structural and Regolith offsets are Point units and no longer depend
# on the mapping scale at all. Mirrored by the baked template values in
# scripts/inject_dynamic_callouts.py and
# scripts/inject_overlay_label_placement.py (U = 5000 * this).
CALLOUT_DIST_FACTOR = 0.0075

# Basemap lithology labels use half the Overlay ring so their manhattan
# leaders stay short (user decision 2026-08-29); most labels fit inside
# their polygon and draw no leader at all. Mirrored by the baked values
# in scripts/inject_basemap_label_placement.py.
BASEMAP_DIST_FACTOR = 0.5

# Labels-as-obstacles weight for every FieldNotebook rule: structure
# lettering repels other layers' movable text harder than a default
# obstacle. Mirrored by scripts/inject_label_priority_ladder.py.
OBSTACLE_FACTOR = 2.0


def callout_dist_for_scale(scale_value):
    """Map-unit callout ring distance for a mapping scale."""
    return scale_value * CALLOUT_DIST_FACTOR


# How far a long line runs before it repeats its label: 200 mm on the page,
# in ground metres per unit of scale denominator. 1000 m at 1:5000, 200 m at
# 1:1000, 20 m at 1:100 - roughly two thirds of an A4 landscape sheet at any
# mapping scale.
#
# The point of expressing it in GROUND units is that QGIS does NOT scale a
# repeatDistance given in millimetres by the renderer's reference scale: it
# is paper-at-the-current-render-scale, so zooming in makes more labels
# appear and a short vein sprouts repeats. In map units the count depends on
# how long the line actually is, which is the thing a geologist means.
#
# Mirrored by the baked template value in scripts/inject_label_cartography.py
# (REPEAT_MU = 5000 * this).
LINEWORK_REPEAT_FACTOR = 0.2


def linework_repeat_for_scale(scale_value):
    """Map-unit label repeat distance for a mapping scale."""
    return scale_value * LINEWORK_REPEAT_FACTOR


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


def is_lgs_linework_labeling(labeling):
    """True if labeling is the LGS Linework simple labeling shaped by
    scripts/inject_label_cartography.py (Curved placement over the vein/detail
    label expression) - the guard that keeps rescaling off hand-customized
    styles, same role as is_lgs_overlay_labeling."""
    if not isinstance(labeling, QgsVectorLayerSimpleLabeling):
        return False
    settings = labeling.settings()
    if settings.placement != Qgis.LabelPlacement.Curved:
        return False
    return bool(settings.isExpression)


def rescale_linework_label_repeat(layer, scale_value):
    """Rescale the Linework label repeat distance to a mapping scale.

    Edits the existing simple labeling by copy - never rebuilds - so the
    auxiliary-storage dd bindings (manual label moves), fonts, the label
    expression and the placement flags all survive.
    """
    settings = QgsPalLayerSettings(layer.labeling().settings())
    settings.repeatDistance = linework_repeat_for_scale(scale_value)
    settings.repeatDistanceUnit = Qgis.RenderUnit.MapUnits
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()


def rescale_overlay_label_distance(layer, scale_value, factor=1.0):
    """Rescale a polygon layer's outside-label distance to a mapping scale.

    Edits the existing simple labeling by copy — never rebuilds — so the
    auxiliary-storage dd bindings (manual label moves), fonts, expression
    and callout all survive. dist is the only knob PAL uses for outside
    placement on polygons; maximumDistance is kept mirrored at 5x purely
    for consistency with the injector (it is inert for polygon placement).

    factor shrinks the ring per layer: Overlay uses the full ring (1.0),
    Basemap passes BASEMAP_DIST_FACTOR so its leaders stay short.
    """
    settings = QgsPalLayerSettings(layer.labeling().settings())
    x_value = factor * callout_dist_for_scale(scale_value)
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
    """Return the canonical LGS rule-based structural labeling.

    Shared by Set Mapping Scale and the static mapping export. The dip,
    suffix and callout distances are all ground distances derived from
    scale_value - the same value set_reference_scale() gives the renderer
    moments earlier, which is what keeps the labels welded to symbols whose
    footprint that reference scale fixes. Only the Regolith ring is a paper
    distance, because its point symbol is invisible and there is nothing
    for it to stay welded to.
    """
    configurator = LayerConfigurator()
    callout_x = callout_dist_for_scale(scale_value)

    # Root rule (overlap handling is set on each individual rule)
    root = QgsRuleBasedLabeling.Rule(QgsPalLayerSettings())
    # Rule 1: Dip field (no callouts)
    root.appendChild(configurator.create_dip_rule(scale_value))
    # Rule 2: SymbolSuffix field (small, italic, no callouts)
    root.appendChild(configurator.create_suffix_rule(scale_value))
    # Rule 3: Regolith Note (beside the point, no leader)
    root.appendChild(configurator.create_regolith_note_rule())
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