# -*- coding: utf-8 -*-
"""
/***************************************************************************
                        Map Cleaning Toolkit
                              -------------------
        begin                : 2025-10-28
        copyright            : (C) 2025 Linear Geoscience

        Based on code from:
        - Polygon Clipper by Giuseppe De Marco
        - Spline Plugin by Radim Blazek
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
import os.path

from qgis.PyQt.QtCore import QSettings, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QProgressDialog, QDialog
from qgis.core import QgsApplication, QgsWkbTypes, QgsMapLayerType, QgsVectorLayer, QgsMessageLog, Qgis

# Import clipping components
from .clipping.clipper_dockwidget import ClipperDockWidget
from .clipping.clipper_selection import SelectionManager
from .clipping.clipper_preview import PreviewManager
from .clipping.clipper_core import clip_all_intersecting, clip_isolated, clip_small_into_large

# Import tools
from .tools.reshape_spline_tool import ReshapeSplineTool
from .tools.spline_tool import SplineTool

# Import Processing provider
from .processing_provider.provider import Provider as ProcessingProvider

# Import utils
from .core.utils import get_icon_from_subdir

# Import geometry fixer engine
from .core.geometry_fixer_engine import GeometryFixerEngine


class MapCleaningToolkit(object):
    """
    Map Cleaning toolkit, embedded in the Linear Geoscience plugin.

    Provides:
    - 3 toolbar buttons on the host toolbar (Reshape Spline, Add Feature Spline, Map Cleaning Panel)
    - Map Cleaning panel with tabs (Clip All, Clip Isolated, Smart Clip, Find Overlaps,
      Find Slivers, Fix Geometry, Spline Settings)
    - Processing algorithms for batch operations
    """

    def __init__(self, iface):
        """Initialize the toolkit"""
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.plugin_dir = os.path.dirname(__file__)

        # Plugin components
        self.dockwidget = None
        self.selection_manager = None
        self.preview_manager = None
        self.reshape_tool = None
        self.spline_tool = None
        self.proc_provider = None

        # Host plugin toolbar (not owned by this toolkit)
        self.toolbar = None
        self.toolbar_separator = None

        # Actions
        self.action_reshape = None
        self.action_add_feature = None
        self.action_panel = None

        # Current layer
        self.current_layer = None
        self.connected_layer = None  # For spline tools

        # Track plugin state
        self.is_active = False
        self.settings_key = "LinearGeosciencePlugin/MapCleaning"

        # Geometry issues tracking
        self.geometry_issues = []
        self.geometry_issues_layer = None
        self.geometry_fixer_engine = None

    def initGui(self, toolbar=None):
        """Initialize the toolkit GUI.

        Args:
            toolbar: host plugin QToolBar to append this toolkit's actions to.
        """

        # Initialize Processing provider
        self.initProcessing()

        # Create dock widget (starts hidden)
        self.dockwidget = ClipperDockWidget()
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dockwidget)
        self.dockwidget.setVisible(False)

        # Create managers for clipping
        self.selection_manager = SelectionManager(self.iface)
        self.preview_manager = PreviewManager(self.iface)

        # Create tools
        self.reshape_tool = ReshapeSplineTool(self.iface)
        self.spline_tool = SplineTool(self.iface)

        # Connect dock widget signals
        self.dockwidget.executeClicked.connect(self.execute_preview)
        self.dockwidget.lockCuttersClicked.connect(self.lock_cutters)
        self.dockwidget.clearClicked.connect(self.clear_all)
        self.dockwidget.resetClicked.connect(self.deactivate_plugin)
        self.dockwidget.modeChanged.connect(self.on_mode_changed)
        self.dockwidget.layerChanged.connect(self.on_layer_changed)
        self.dockwidget.closingPanel.connect(self.on_panel_closing)
        self.dockwidget.visibilityChanged.connect(self.on_panel_visibility_changed)
        self.dockwidget.splineSettingsChanged.connect(self.on_spline_settings_changed)
        self.dockwidget.findOverlapsClicked.connect(self.execute_find_overlaps)
        self.dockwidget.findSliversClicked.connect(self.execute_find_slivers)
        self.dockwidget.detectGeometryIssuesClicked.connect(self.detect_geometry_issues_from_tab)
        self.dockwidget.viewGeometryIssuesClicked.connect(self.view_geometry_issues)
        self.dockwidget.fixGeometryIssuesClicked.connect(self.fix_geometry_issues)

        # Load spline settings into dock widget
        self.dockwidget.load_spline_settings()

        # Create toolbar actions on the host toolbar
        self.create_actions(toolbar)

        # Connect to layer changes
        self.iface.currentLayerChanged.connect(self.layer_changed_for_tools)
        self.layer_changed_for_tools()  # Enable/disable based on current layer

        # Connect canvas tool changes
        self.canvas.mapToolSet.connect(self.deactivate_tools)

        # Set initial layer
        self.on_layer_changed(self.dockwidget.get_current_layer())

        # Restore panel state
        self.restore_panel_state()

    def initProcessing(self):
        """Initialize Processing provider"""
        self.proc_provider = ProcessingProvider()
        QgsApplication.processingRegistry().addProvider(self.proc_provider)

    def create_actions(self, toolbar):
        """Create toolkit actions and add them to the host plugin toolbar"""

        # Keep a reference to the host toolbar (owned by the host plugin)
        self.toolbar = toolbar

        # 1. Reshape with Spline
        icon_reshape = QIcon(get_icon_from_subdir('icons', 'reshape_spline.svg'))
        self.action_reshape = QAction(
            icon_reshape,
            "Reshape with Spline",
            self.iface.mainWindow()
        )
        self.action_reshape.setObjectName("actionReshapeSpline")
        self.action_reshape.setEnabled(False)
        self.action_reshape.setCheckable(True)
        self.action_reshape.triggered.connect(self.activate_reshape_tool)
        self.action_reshape.setStatusTip("Reshape features using smooth spline curves")

        # 2. Add Feature with Spline
        icon_add = QIcon(get_icon_from_subdir('icons', 'add_feature_spline.svg'))
        self.action_add_feature = QAction(
            icon_add,
            "Add Feature with Spline",
            self.iface.mainWindow()
        )
        self.action_add_feature.setObjectName("actionAddFeatureSpline")
        self.action_add_feature.setEnabled(False)
        self.action_add_feature.setCheckable(True)
        self.action_add_feature.triggered.connect(self.activate_add_feature_tool)
        self.action_add_feature.setStatusTip("Digitize new features with spline curves")

        # 3. Map Cleaning Panel (Smart Clip and Fix Geometry live in the panel's tabs)
        icon_panel = QIcon(get_icon_from_subdir('icons', 'clipping_panel.svg'))
        self.action_panel = QAction(
            icon_panel,
            "Map Cleaning Panel",
            self.iface.mainWindow()
        )
        self.action_panel.setObjectName("actionMapCleaningPanel")
        self.action_panel.setCheckable(True)
        self.action_panel.triggered.connect(self.toggle_panel)
        self.action_panel.setStatusTip("Toggle the Map Cleaning panel (clip, fix geometry, spline settings)")

        # Add actions to the host toolbar, after its existing buttons
        self.toolbar_separator = self.toolbar.addSeparator()
        self.toolbar.addAction(self.action_reshape)
        self.toolbar.addAction(self.action_add_feature)
        self.toolbar.addAction(self.action_panel)

    def unload(self):
        """Cleanup when plugin is unloaded"""

        # Save panel state
        self.save_panel_state()

        # Disconnect layer selection signal (protect against deleted layers)
        try:
            if self.current_layer:
                try:
                    self.current_layer.selectionChanged.disconnect(self.on_selection_changed)
                except (RuntimeError, TypeError):
                    pass
        except RuntimeError:
            pass

        # Disconnect connected_layer editing signals
        try:
            if self.connected_layer:
                try:
                    self.connected_layer.editingStarted.disconnect(self.layer_changed_for_tools)
                    self.connected_layer.editingStopped.disconnect(self.layer_changed_for_tools)
                except (RuntimeError, TypeError):
                    pass
        except RuntimeError:
            pass
        self.connected_layer = None

        # Disconnect iface/canvas signals
        try:
            self.iface.currentLayerChanged.disconnect(self.layer_changed_for_tools)
        except (RuntimeError, TypeError):
            pass
        try:
            self.canvas.mapToolSet.disconnect(self.deactivate_tools)
        except (RuntimeError, TypeError):
            pass

        # Clean up map tools (remove rubber bands and snap markers from canvas)
        if self.reshape_tool:
            try:
                self.reshape_tool.cleanup()
            except RuntimeError:
                pass

        if self.spline_tool:
            try:
                self.spline_tool.cleanup()
            except RuntimeError:
                pass

        # Disconnect dock widget signals before deleting
        if self.dockwidget:
            try:
                self.dockwidget.executeClicked.disconnect(self.execute_preview)
                self.dockwidget.lockCuttersClicked.disconnect(self.lock_cutters)
                self.dockwidget.clearClicked.disconnect(self.clear_all)
                self.dockwidget.resetClicked.disconnect(self.deactivate_plugin)
                self.dockwidget.modeChanged.disconnect(self.on_mode_changed)
                self.dockwidget.layerChanged.disconnect(self.on_layer_changed)
                self.dockwidget.closingPanel.disconnect(self.on_panel_closing)
                self.dockwidget.visibilityChanged.disconnect(self.on_panel_visibility_changed)
                self.dockwidget.splineSettingsChanged.disconnect(self.on_spline_settings_changed)
                self.dockwidget.findOverlapsClicked.disconnect(self.execute_find_overlaps)
                self.dockwidget.findSliversClicked.disconnect(self.execute_find_slivers)
                self.dockwidget.detectGeometryIssuesClicked.disconnect(self.detect_geometry_issues_from_tab)
                self.dockwidget.viewGeometryIssuesClicked.disconnect(self.view_geometry_issues)
                self.dockwidget.fixGeometryIssuesClicked.disconnect(self.fix_geometry_issues)
            except (RuntimeError, TypeError):
                pass

        # Remove this toolkit's actions from the host toolbar (toolbar itself is owned
        # and removed by the host plugin)
        if self.toolbar:
            try:
                for action in (self.toolbar_separator, self.action_reshape,
                               self.action_add_feature, self.action_panel):
                    if action is not None:
                        self.toolbar.removeAction(action)
            except RuntimeError:
                # Toolbar already deleted on the C++ side
                pass
            self.toolbar = None
        self.toolbar_separator = None
        self.action_reshape = None
        self.action_add_feature = None
        self.action_panel = None

        # Remove dock widget
        if self.dockwidget:
            self.iface.removeDockWidget(self.dockwidget)
            self.dockwidget.deleteLater()
            self.dockwidget = None

        # Clean up managers
        if self.selection_manager:
            try:
                self.selection_manager.clear_all()
            except RuntimeError:
                # Highlights may already be cleaned up during QGIS shutdown
                pass
            self.selection_manager = None

        if self.preview_manager:
            try:
                self.preview_manager.remove_preview()
            except RuntimeError:
                pass
            self.preview_manager = None

        # Remove Processing provider
        if self.proc_provider:
            try:
                QgsApplication.processingRegistry().removeProvider(self.proc_provider)
            except RuntimeError:
                # Provider already freed on the C++ side during shutdown
                pass
            self.proc_provider = None

    # ===== TOOL ACTIVATION =====

    def activate_reshape_tool(self):
        """Activate reshape with spline tool"""
        if self.action_reshape.isChecked():
            self.canvas.setMapTool(self.reshape_tool)
        else:
            self.canvas.unsetMapTool(self.reshape_tool)

    def activate_add_feature_tool(self):
        """Activate add feature with spline tool"""
        if self.action_add_feature.isChecked():
            self.canvas.setMapTool(self.spline_tool)
        else:
            self.canvas.unsetMapTool(self.spline_tool)

    def deactivate_tools(self, tool):
        """Deactivate tool buttons when map tool changes"""
        if tool != self.reshape_tool:
            self.action_reshape.setChecked(False)
        if tool != self.spline_tool:
            self.action_add_feature.setChecked(False)

    def layer_changed_for_tools(self):
        """Enable/disable tool buttons based on current layer"""
        layer = self.iface.activeLayer()

        # Disconnect from old layer (with proper error handling for deleted layers)
        # Must wrap the entire check because even testing truthiness can raise RuntimeError
        try:
            if self.connected_layer:
                try:
                    self.connected_layer.editingStarted.disconnect(self.layer_changed_for_tools)
                    self.connected_layer.editingStopped.disconnect(self.layer_changed_for_tools)
                except (RuntimeError, TypeError):
                    # Layer was deleted or connection doesn't exist
                    pass
        except RuntimeError:
            # Layer was deleted, even the truthiness check failed
            pass

        # Clear the reference
        self.connected_layer = None

        # Enable reshape and add feature tools only for polygon/line layers in edit mode
        enable_tools = False
        if layer and layer.type() == QgsMapLayerType.VectorLayer:
            try:
                if layer.geometryType() in [QgsWkbTypes.PolygonGeometry, QgsWkbTypes.LineGeometry]:
                    enable_tools = layer.isEditable()

                    # Connect to editing signals
                    self.connected_layer = layer
                    layer.editingStarted.connect(self.layer_changed_for_tools)
                    layer.editingStopped.connect(self.layer_changed_for_tools)
            except RuntimeError:
                # Layer was deleted while we were checking it
                enable_tools = False
                self.connected_layer = None

        self.action_reshape.setEnabled(enable_tools)
        self.action_add_feature.setEnabled(enable_tools)

    def execute_smart_clip_direct(self):
        """Execute smart clip directly from toolbar button"""
        # Activate panel, switch to smart clip tab, and execute
        if not self.dockwidget.isVisible():
            self.dockwidget.setVisible(True)
            self.dockwidget.raise_()

        # Switch to smart clip tab (index 2)
        self.dockwidget.tab_widget.setCurrentIndex(2)

    def execute_geometry_fixer(self):
        """Execute geometry fixer directly from toolbar button"""
        layer = self.iface.activeLayer()

        # Validate layer suitability
        is_valid, error_msg = self.validate_layer_for_geometry_fixer(layer)
        if not is_valid:
            QMessageBox.warning(
                self.iface.mainWindow(),
                'Cannot Fix Geometries',
                error_msg
            )
            return

        # Get layer info
        total_features = layer.featureCount()

        # Step 1: Detect geometry issues first
        progress = QProgressDialog(
            'Detecting geometry issues...',
            'Cancel',
            0,
            total_features,
            self.iface.mainWindow()
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setWindowTitle('Geometry Checker')

        # Create engine with delete_zero_area enabled
        engine = GeometryFixerEngine(layer, self.log_geometry_fixer, delete_zero_area=True)
        issues = engine.detect_geometry_issues(progress)

        progress.close()

        # Check if any issues found
        if not issues or len(issues) == 0:
            QMessageBox.information(
                self.iface.mainWindow(),
                'No Geometry Issues',
                f'No geometry issues found in layer "{layer.name()}".\n\n'
                f'All {total_features} features have valid geometries.'
            )
            return

        # Step 2: Show issues dialog
        from .core.geometry_issues_dialog import GeometryIssuesDialog
        issues_dialog = GeometryIssuesDialog(layer, issues, self.iface, self.iface.mainWindow())

        # Show dialog and wait for user decision
        result = issues_dialog.exec_()

        # If user clicked "Fix All", proceed with fixing
        if result == QDialog.Accepted:
            # Create progress dialog for fixing
            progress = QProgressDialog(
                'Fixing geometries...',
                'Cancel',
                0,
                total_features,
                self.iface.mainWindow()
            )
            progress.setWindowModality(Qt.WindowModal)
            progress.setWindowTitle('Geometry Fixer')

            # Run the fixing engine
            fix_results = engine.fix_all_geometries(progress)

            progress.close()

            # Show results
            self.show_geometry_fixer_results(layer, fix_results)
        else:
            # User cancelled - just log it
            self.log_geometry_fixer("Geometry fixing cancelled by user", Qgis.Info)

    def validate_layer_for_geometry_fixer(self, layer):
        """
        Validate that the layer is suitable for geometry fixing.
        Returns: Tuple (is_valid, error_message)
        """
        if not layer:
            return False, "No active layer selected"

        if not isinstance(layer, QgsVectorLayer):
            return False, "Selected layer is not a vector layer"

        if not layer.isEditable():
            return False, "Layer is not in editing mode.\n\nPlease start editing first (Toggle Editing button)."

        geom_type = layer.geometryType()
        if geom_type != QgsWkbTypes.PolygonGeometry:
            return False, "This tool only works with polygon layers"

        return True, None

    def log_geometry_fixer(self, message, level=Qgis.Info):
        """Log message to QGIS message log for geometry fixer."""
        QgsMessageLog.logMessage(message, 'Map Cleaning Toolkit - Geometry Fixer', level)

    def show_geometry_fixer_results(self, layer, results):
        """Display geometry fixer results to user."""
        message = (
            f'Geometry Fixing Complete\n\n'
            f'Features processed: {results["processed"]}\n'
            f'Geometries fixed: {results["fixed"]}\n'
            f'Geometries recovered: {results.get("recovered", 0)}\n'
            f'Zero-area features deleted: {results.get("deleted", 0)}\n'
            f'Multipart converted: {results["converted"]}\n'
            f'Duplicate vertices removed: {results["duplicates_removed"]}\n'
            f'Already perfect: {results["already_valid"]}\n'
            f'Failed to fix: {results["failed"]}\n\n'
        )

        if results.get('deleted', 0) > 0:
            message += f'NOTE: {results["deleted"]} zero-area features were permanently deleted.\n'
            if results.get('deleted_fids'):
                message += f'Deleted feature IDs: {", ".join(map(str, results["deleted_fids"][:10]))}'
                if len(results['deleted_fids']) > 10:
                    message += f' (and {len(results["deleted_fids"]) - 10} more)'
                message += '\n\n'

        if results['failed'] > 0:
            message += f'WARNING: {results["failed"]} features could not be fixed safely.\n'
            message += 'Check the QGIS log for details.\n\n'

        message += (
            f'Layer "{layer.name()}" remains in EDIT MODE.\n'
            f'Review changes and Save when ready.\n'
            f'Use Ctrl+Z to undo if needed.'
        )

        msg_type = QMessageBox.Information if results['failed'] == 0 else QMessageBox.Warning

        QMessageBox(
            msg_type,
            'Geometry Fixing Results',
            message,
            QMessageBox.Ok,
            self.iface.mainWindow()
        ).exec_()

        self.log_geometry_fixer(
            f"Completed: {results['fixed']} fixed, {results.get('recovered', 0)} recovered, "
            f"{results.get('deleted', 0)} deleted, {results['converted']} converted, "
            f"{results['duplicates_removed']} duplicates removed, {results['failed']} failed"
        )
        layer.triggerRepaint()

    def detect_geometry_issues_from_tab(self):
        """Detect geometry issues from the Fix Geometry tab"""
        layer = self.dockwidget.get_current_layer()

        # Validate layer suitability
        is_valid, error_msg = self.validate_layer_for_geometry_fixer(layer)
        if not is_valid:
            QMessageBox.warning(
                self.iface.mainWindow(),
                'Cannot Detect Issues',
                error_msg
            )
            return

        # Get layer info
        total_features = layer.featureCount()

        # Detect geometry issues
        progress = QProgressDialog(
            'Detecting geometry issues...',
            'Cancel',
            0,
            total_features,
            self.iface.mainWindow()
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setWindowTitle('Geometry Checker')

        # Create engine with delete_zero_area enabled and store for reuse in fix step
        self.geometry_fixer_engine = GeometryFixerEngine(layer, self.log_geometry_fixer, delete_zero_area=True)
        issues = self.geometry_fixer_engine.detect_geometry_issues(progress)

        progress.close()

        # Store issues for later
        self.geometry_issues = issues
        self.geometry_issues_layer = layer

        # Calculate statistics
        issue_stats = {}
        for issue in issues:
            issue_type = issue.issue_type
            issue_stats[issue_type] = issue_stats.get(issue_type, 0) + 1

        # Update the UI
        self.dockwidget.update_geometry_issues(len(issues), issue_stats)

        # Update status
        if len(issues) == 0:
            self.dockwidget.update_status(
                f"No geometry issues found in {total_features} features",
                'success'
            )
        else:
            self.dockwidget.update_status(
                f"Found {len(issues)} geometry issues. Click 'View Issues List' to inspect or 'Fix All Issues' to fix them.",
                'warning'
            )

    def view_geometry_issues(self):
        """Show the geometry issues dialog"""
        if not self.geometry_issues or not self.geometry_issues_layer:
            QMessageBox.information(
                self.iface.mainWindow(),
                'No Issues Detected',
                'Please click "Detect Geometry Issues" first.'
            )
            return

        # Show issues dialog
        from .core.geometry_issues_dialog import GeometryIssuesDialog
        issues_dialog = GeometryIssuesDialog(
            self.geometry_issues_layer,
            self.geometry_issues,
            self.iface,
            self.iface.mainWindow()
        )

        # Show dialog (user can inspect and zoom)
        result = issues_dialog.exec_()

        # If user clicked "Fix All", proceed with fixing
        if result == QDialog.Accepted:
            self.fix_geometry_issues()

    def fix_geometry_issues(self):
        """Fix all detected geometry issues"""
        if not self.geometry_issues or not self.geometry_issues_layer:
            QMessageBox.information(
                self.iface.mainWindow(),
                'No Issues Detected',
                'Please click "Detect Geometry Issues" first.'
            )
            return

        layer = self.geometry_issues_layer
        total_features = layer.featureCount()

        # Confirm with user
        reply = QMessageBox.question(
            self.iface.mainWindow(),
            'Fix All Geometry Issues',
            f'This will fix all {len(self.geometry_issues)} detected issues in layer "{layer.name()}".\n\n'
            f'The layer will remain in edit mode so you can undo if needed.\n\n'
            f'Proceed?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply != QMessageBox.Yes:
            return

        # Create progress dialog for fixing
        progress = QProgressDialog(
            'Fixing geometries...',
            'Cancel',
            0,
            total_features,
            self.iface.mainWindow()
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setWindowTitle('Geometry Fixer')

        # Reuse stored engine if available and layer matches, otherwise create new
        if self.geometry_fixer_engine and self.geometry_issues_layer == layer:
            engine = self.geometry_fixer_engine
        else:
            engine = GeometryFixerEngine(layer, self.log_geometry_fixer, delete_zero_area=True)
        fix_results = engine.fix_all_geometries(progress)

        progress.close()

        # Show results
        self.show_geometry_fixer_results(layer, fix_results)

        # Clear stored issues, engine, and re-detect
        self.geometry_issues = []
        self.geometry_issues_layer = None
        self.geometry_fixer_engine = None

        # Update UI
        self.dockwidget.update_geometry_issues(0, {})
        status_msg = f"Fixed {fix_results['fixed']} geometries, recovered {fix_results.get('recovered', 0)}"
        if fix_results.get('deleted', 0) > 0:
            status_msg += f", deleted {fix_results['deleted']} zero-area features"
        status_msg += ". Click 'Detect Geometry Issues' to check again."

        self.dockwidget.update_status(status_msg, 'success')

    # ===== CLIPPING PANEL HANDLERS =====

    def on_layer_changed(self, layer):
        """Handle layer selection change in dock widget"""
        # Disconnect from old layer (protect against deleted layers)
        try:
            if self.current_layer:
                try:
                    self.current_layer.selectionChanged.disconnect(self.on_selection_changed)
                except (RuntimeError, TypeError):
                    pass
        except RuntimeError:
            pass

        # Clear selections
        self.clear_all()

        # Set new layer
        self.current_layer = layer

        # Connect to new layer
        if self.current_layer:
            self.current_layer.selectionChanged.connect(self.on_selection_changed)

    def on_mode_changed(self, mode):
        """Handle mode change"""
        if not self.is_active:
            self.activate_plugin()
        else:
            self.clear_all()

    def on_selection_changed(self):
        """Handle selection change in current layer"""
        if not self.is_active or not self.current_layer:
            return

        mode = self.dockwidget.get_mode()
        selected_ids = self.current_layer.selectedFeatureIds()

        if mode == 'clip_smart':
            selected_count = len(selected_ids)
            self.dockwidget.update_selection_counts(selected_count, 0)
            self.dockwidget.update_button_states(selected_count, 0)

        elif mode == 'clip_all':
            cutter_count = len(selected_ids)
            self.dockwidget.update_selection_counts(cutter_count, 0)
            self.dockwidget.update_button_states(cutter_count, 0)

            if cutter_count == 1:
                self.selection_manager.set_cutters(self.current_layer, selected_ids)

        elif mode == 'clip_isolated':
            if self.dockwidget.isolated_step == 2:
                target_count = len(selected_ids)
                cutter_count = len(self.selection_manager.get_cutter_ids())

                if target_count > 0:
                    self.selection_manager.set_targets(self.current_layer, selected_ids)

                self.dockwidget.update_selection_counts(cutter_count, target_count)
                self.dockwidget.update_button_states(cutter_count, target_count)
            else:
                cutter_count = len(selected_ids)
                self.dockwidget.update_selection_counts(cutter_count, 0)
                self.dockwidget.update_button_states(cutter_count, 0)

    def lock_cutters(self):
        """Lock cutter selection and advance to step 2"""
        if not self.is_active:
            self.activate_plugin()

        if not self.current_layer:
            return

        selected_ids = self.current_layer.selectedFeatureIds()
        if not selected_ids:
            return

        self.selection_manager.set_cutters(self.current_layer, selected_ids)
        self.current_layer.removeSelection()
        self.dockwidget.advance_to_step_2()

    def execute_preview(self):
        """Execute clipping preview based on current mode"""
        if not self.is_active:
            self.activate_plugin()

        if not self.current_layer:
            return

        mode = self.dockwidget.get_mode()
        snap_tolerance = self.dockwidget.get_snap_tolerance()

        try:
            if mode == 'clip_all':
                result = self.execute_clip_all(snap_tolerance)
            elif mode == 'clip_isolated':
                result = self.execute_clip_isolated(snap_tolerance)
            else:  # clip_smart
                result = self.execute_clip_smart(snap_tolerance)

            if result and result.success:
                self.show_preview_and_confirm(result)
            elif result and result.error:
                self.dockwidget.update_status(result.error, 'error')

        except Exception as e:
            self.dockwidget.update_status(f"Error: {str(e)}", 'error')

    def execute_clip_all(self, snap_tolerance):
        """Execute clip all intersecting"""
        selected_ids = self.selection_manager.get_cutter_ids()
        if not selected_ids or len(selected_ids) != 1:
            return None

        # Get split multipart setting from UI
        split_multipart = False
        if self.dockwidget and hasattr(self.dockwidget, 'split_multipart_checkbox_all'):
            split_multipart = self.dockwidget.split_multipart_checkbox_all.isChecked()

        # Get UUID field setting for regeneration when splitting
        uuid_field_name = None
        if self.dockwidget and hasattr(self.dockwidget, 'get_uuid_field'):
            uuid_field_name = self.dockwidget.get_uuid_field()

        result = clip_all_intersecting(self.current_layer, selected_ids[0], snap_tolerance, split_multipart, uuid_field_name)
        return result

    def execute_clip_isolated(self, snap_tolerance):
        """Execute clip isolated"""
        cutter_ids = self.selection_manager.get_cutter_ids()
        target_ids = self.selection_manager.get_target_ids()

        if not cutter_ids or not target_ids:
            return None

        # Get split multipart setting from UI
        split_multipart = False
        if self.dockwidget and hasattr(self.dockwidget, 'split_multipart_checkbox_isolated'):
            split_multipart = self.dockwidget.split_multipart_checkbox_isolated.isChecked()

        # Get UUID field setting for regeneration when splitting
        uuid_field_name = None
        if self.dockwidget and hasattr(self.dockwidget, 'get_uuid_field'):
            uuid_field_name = self.dockwidget.get_uuid_field()

        result = clip_isolated(self.current_layer, cutter_ids, target_ids, snap_tolerance, split_multipart, uuid_field_name)
        return result

    def execute_clip_smart(self, snap_tolerance):
        """Execute smart clip"""
        selected_ids = self.current_layer.selectedFeatureIds()
        if not selected_ids or len(selected_ids) < 2:
            return None

        # Get split multipart setting from UI
        split_multipart = False
        if self.dockwidget and hasattr(self.dockwidget, 'split_multipart_checkbox'):
            split_multipart = self.dockwidget.split_multipart_checkbox.isChecked()

        # Get UUID field setting for regeneration when splitting
        uuid_field_name = None
        if self.dockwidget and hasattr(self.dockwidget, 'get_uuid_field'):
            uuid_field_name = self.dockwidget.get_uuid_field()

        result = clip_small_into_large(self.current_layer, selected_ids, snap_tolerance, split_multipart, uuid_field_name)
        return result

    def execute_find_overlaps(self):
        """Execute overlap detection"""
        if not self.is_active:
            self.activate_plugin()

        if not self.current_layer:
            return

        try:
            # Import the overlap detection function
            from .clipping.clipper_core import find_polygon_overlaps

            # Update status
            self.dockwidget.update_status("Searching for overlaps...", 'info')

            # Find overlaps
            result = find_polygon_overlaps(self.current_layer)

            if result and result.success:
                # Show overlap preview
                self.show_overlap_preview(result)
            elif result and result.error:
                self.dockwidget.update_status(result.error, 'warning')
                self.dockwidget.update_overlaps_count(0)

        except Exception as e:
            self.dockwidget.update_status(f"Error: {str(e)}", 'error')

    def show_overlap_preview(self, result):
        """Show overlap detection preview"""
        # Update count in UI
        self.dockwidget.update_overlaps_count(result.clipped_count, result.bisecting_count)

        # Update status
        self.dockwidget.update_status(f"Creating overlap preview for {result.clipped_count} area(s)...", 'info')

        # Create and show preview layer with overlap styling
        preview_layer = self.preview_manager.create_preview(
            self.current_layer,
            result,
            style_mode='overlap'
        )

        # Update final status with bisecting breakdown
        if result.bisecting_count > 0:
            status_msg = (
                f"Found {result.clipped_count} overlapping areas ({result.bisecting_count} bisecting). "
                f"Inspect and zoom as needed."
            )
        else:
            status_msg = (
                f"Found {result.clipped_count} overlapping areas. Inspect and zoom as needed. "
                f"Click 'Clear Preview' when done."
            )
        self.dockwidget.update_status(status_msg, 'warning')

    def execute_find_slivers(self):
        """Execute sliver detection"""
        if not self.is_active:
            self.activate_plugin()

        if not self.current_layer:
            return

        try:
            from .clipping.clipper_core import find_polygon_slivers

            max_area = self.dockwidget.get_max_sliver_area()
            min_area = self.dockwidget.get_min_sliver_area()
            snap_tolerance = self.dockwidget.get_sliver_snap_tolerance()
            self.dockwidget.update_status("Searching for slivers...", 'info')

            result = find_polygon_slivers(
                self.current_layer, max_area,
                min_area=min_area,
                snap_tolerance=snap_tolerance,
            )

            if result and result.success:
                self.show_sliver_preview(result)
            elif result and result.error:
                self.dockwidget.update_status(result.error, 'warning')
                self.dockwidget.update_slivers_count(0)

        except Exception as e:
            self.dockwidget.update_status(f"Error: {str(e)}", 'error')

    def show_sliver_preview(self, result):
        """Show sliver detection preview"""
        self.dockwidget.update_slivers_count(result.clipped_count)
        self.dockwidget.update_status(
            f"Creating sliver preview for {result.clipped_count} gap(s)...", 'info'
        )

        self.preview_manager.create_preview(
            self.current_layer,
            result,
            style_mode='sliver'
        )

        self.dockwidget.update_status(
            f"Found {result.clipped_count} sliver(s). Inspect and zoom as needed. "
            f"Click 'Clear Preview' when done.",
            'warning'
        )

    def show_preview_and_confirm(self, result):
        """Show preview and confirmation dialog"""
        # Provide detailed feedback even when no features are clipped
        if result.clipped_count == 0:
            from qgis.PyQt.QtWidgets import QMessageBox

            mode = self.dockwidget.get_mode()
            if mode == 'clip_smart':
                msg = ("No clipping performed.\n\n"
                      "Smart Clip requires:\n"
                      "• At least 2 selected polygons\n"
                      "• Small polygons must overlap larger ones\n"
                      "• Polygon sizes must differ by at least 1%\n\n"
                      "Try selecting polygons with different sizes that intersect.")
            elif mode == 'clip_all':
                msg = ("No intersecting features found.\n\n"
                      "The selected cutter polygon does not intersect\n"
                      "any other polygons in the layer.\n\n"
                      "Try selecting a different cutter polygon.")
            else:  # clip_isolated
                msg = ("No intersecting features found.\n\n"
                      "The cutter polygons do not intersect\n"
                      "any of the target polygons.\n\n"
                      "Ensure cutters and targets overlap.")

            QMessageBox.information(
                self.iface.mainWindow(),
                "No Clipping Required",
                msg
            )
            self.dockwidget.update_status("No features to clip", 'warning')
            return

        # Update status before showing preview
        self.dockwidget.update_status(f"Creating preview for {result.clipped_count} feature(s)...", 'info')

        # Create and show preview layer
        preview_layer = self.preview_manager.create_preview(self.current_layer, result)

        # Update status while showing dialog
        self.dockwidget.update_status(f"Review preview - {result.clipped_count} features will be clipped", 'warning')

        # Show preview dialog (non-blocking to allow zoom/pan during inspection)
        # Callbacks handle confirmation or cancellation asynchronously
        self.preview_manager.show_preview_dialog(
            self.current_layer,
            result,
            self.dockwidget.update_status,
            self.clear_all
        )

    def clear_all(self):
        """Clear all selections and highlights"""
        self.selection_manager.clear_all()
        self.preview_manager.remove_preview()

        # Clear selection (protect against deleted layers)
        try:
            if self.current_layer:
                try:
                    self.current_layer.removeSelection()
                except RuntimeError:
                    pass
        except RuntimeError:
            pass

        self.dockwidget.reset_to_step_1()
        self.dockwidget.update_selection_counts(0, 0)

    def activate_plugin(self):
        """Activate plugin - start intercepting selections"""
        self.is_active = True

    def deactivate_plugin(self):
        """Deactivate plugin - stop intercepting selections"""
        self.is_active = False
        self.selection_manager.clear_all()
        self.preview_manager.remove_preview()

        # Clear selection (protect against deleted layers)
        try:
            if self.current_layer:
                try:
                    self.current_layer.removeSelection()
                except RuntimeError:
                    pass
        except RuntimeError:
            pass

    def on_panel_closing(self):
        """Handle panel closing event"""
        self.deactivate_plugin()

    def toggle_panel(self):
        """Toggle panel visibility"""
        if self.dockwidget.isVisible():
            self.dockwidget.setVisible(False)
        else:
            self.dockwidget.setVisible(True)
            self.dockwidget.raise_()
            if not self.is_active:
                self.activate_plugin()

    def on_panel_visibility_changed(self, visible):
        """Handle panel visibility changes"""
        if self.action_panel:
            self.action_panel.setChecked(visible)

        self.save_panel_state()

        if not visible and self.is_active:
            self.deactivate_plugin()

    def on_spline_settings_changed(self):
        """Handle spline settings change"""
        pass  # Settings are already saved by dock widget

    def save_panel_state(self):
        """Save panel position, size, and visibility"""
        if not self.dockwidget:
            return

        settings = QSettings()
        settings.setValue(f"{self.settings_key}/visible", self.dockwidget.isVisible())
        settings.setValue(f"{self.settings_key}/geometry", self.dockwidget.saveGeometry())

        area = self.iface.mainWindow().dockWidgetArea(self.dockwidget)
        settings.setValue(f"{self.settings_key}/dockarea", area)

    def restore_panel_state(self):
        """Restore panel position, size, and visibility"""
        if not self.dockwidget:
            return

        settings = QSettings()

        geometry = settings.value(f"{self.settings_key}/geometry")
        if geometry:
            self.dockwidget.restoreGeometry(geometry)

        area = settings.value(f"{self.settings_key}/dockarea", type=int)
        if area is not None:
            self.iface.removeDockWidget(self.dockwidget)
            self.iface.addDockWidget(area, self.dockwidget)

        visible = settings.value(f"{self.settings_key}/visible", False, type=bool)
        self.dockwidget.setVisible(visible)
        if self.action_panel:
            self.action_panel.setChecked(visible)

        if visible:
            self.activate_plugin()
        else:
            self.deactivate_plugin()
