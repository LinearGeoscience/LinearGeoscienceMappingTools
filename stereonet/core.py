"""
Core stereonet plugin functionality.

This module contains the main StereonetPluginCore class that handles all
stereonet plotting, data management, and user interface operations.
"""

import os
import io
import re
import csv
import sys
import json
from functools import partial
from types import SimpleNamespace
import matplotlib as mpl

# Configure matplotlib backend before importing pyplot
mpl.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

# Qt canvas for the interactive screen plot. Importing a Qt canvas class does
# not disturb the global 'Agg' backend used by the pyplot export paths.
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg

# Add vendor directory to path for mplstereonet
vendor_dir = os.path.join(os.path.dirname(__file__), '..', 'vendor')
if vendor_dir not in sys.path:
    sys.path.insert(0, vendor_dir)

import mplstereonet
import pandas as pd
import numpy as np

# QGIS core modules
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsFieldProxyModel,
    QgsMapLayerProxyModel,
    QgsSettings,
    QgsMessageLog,
    Qgis
)
from qgis.utils import iface

# QGIS GUI modules  
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QFont, QPixmap, QClipboard, QColor, QImage, QBrush
from qgis.PyQt.QtWidgets import (
    QApplication, QDockWidget, QTabWidget, QWidget, QHBoxLayout,
    QVBoxLayout, QFrame, QCheckBox, QLabel, QPushButton, QComboBox,
    QTreeWidget, QTreeWidgetItem, QScrollArea, QGroupBox, QFileDialog,
    QMessageBox, QLineEdit, QRadioButton, QStackedWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QFormLayout, QSizePolicy, QColorDialog,
    QMenu, QInputDialog, QDialog, QTextEdit, QListWidget, QListWidgetItem
)
from qgis.gui import (
    QgsFieldComboBox,
    QgsCollapsibleGroupBox,
    QgsFileWidget,
    QgsMapLayerComboBox,
)

from .data import planar_codes, linear_codes, normalized_classification
from .utils import (
    unify_fax_code, classify_code, dip_direction_to_strike,
    rake2plunge_bearing, exact_rake2line
)
from . import analysis as stereonet_analysis
from .interaction import StereonetPickHandler

# Category tree columns: name/checkbox, plot-mode combo, and the per-category
# analysis toggles (Best Fit / Contours / Mean)
COL_NAME = 0
COL_PLOT_MODE = 1
COL_BF = 2
COL_CT = 3
COL_MN = 4
ANALYSIS_COLUMNS = (COL_BF, COL_CT, COL_MN)


# UI Color Constants - following QGIS theme conventions
PRIMARY_COLOR = "#3498db"  # Blue
SECONDARY_COLOR = "#2c3e50"  # Dark blue/gray
SUCCESS_COLOR = "#2ecc71"  # Green
WARNING_COLOR = "#f39c12"  # Orange
ERROR_COLOR = "#e74c3c"  # Red
LIGHT_BG = "#f8f9fa"
MEDIUM_BG = "#e9ecef"
BORDER_COLOR = "#dee2e6"
TEXT_COLOR = "#212529"

# Standard colors for structural geology codes - geologically meaningful color scheme
DEFAULT_STRUCTURE_COLORS = {
    # Bedding and layering - distinct earth tones
    "BO": "#8B4513",    # Saddle brown - bedding
    "LAY": "#D2691E",   # Chocolate - layering  
    "S0": "#A0522D",    # Sienna - primary bedding
    "S0T": "#CD853F",   # Peru - transitional bedding
    
    # Foliations - HIGHLY DISTINCT colors across spectrum with purples/pinks
    "S1": "#FF0000",    # Pure red - primary foliation
    "S2": "#FF00FF",    # Magenta/Fuchsia - secondary foliation
    "S3": "#9933FF",    # Purple - tertiary foliation
    "S4": "#00FF00",    # Pure lime green - quaternary foliation
    "S5": "#00FFFF",    # Cyan - quinary foliation
    
    # Fractures - DISTINCT colors, not all reds
    "FB": "#B22222",    # Fire brick - fracture in bedding
    "FCT": "#FF4500",   # Orange red - fracture crosscutting  
    "FO": "#FF1493",    # Deep pink - open fracture
    "FT": "#8B0000",    # Dark red - fracture tight
    "FTD": "#4B0082",   # Indigo - fracture with displacement
    "FTN": "#9ACD32",   # Yellow green - fracture normal
    "FTR": "#FF69B4",   # Hot pink - fracture reverse
    "FTS": "#00CED1",   # Dark turquoise - fracture strike-slip
    "FTT": "#8A2BE2",   # Blue violet - fracture thrust
    
    # Fault planes - HIGHLY DISTINCT strong colors with purples/pinks
    "FAP": "#800080",   # Purple - fault plane
    "FAP1": "#FF0000",  # Pure red - fault plane 1 (pairs with S1)
    "FAP2": "#FF00FF",  # Magenta/Fuchsia - fault plane 2 (pairs with S2)
    "FAP3": "#9933FF",  # Purple - fault plane 3 (pairs with S3)
    "FAP4": "#00FF00",  # Pure lime green - fault plane 4 (pairs with S4)
    "FAP5": "#00FFFF",  # Cyan - fault plane 5 (pairs with S5)
    "FAPK": "#2F4F4F",  # Dark slate gray - kinematic fault plane
    
    # Fault axes - HIGHLY DISTINCT darker shades with purples/pinks
    "FAX": "#6B0F7D",   # Dark purple - fault axis
    "FAX1": "#CC0000",  # Dark red - fault axis 1 (darker than FAP1)
    "FAX2": "#CC00CC",  # Dark magenta - fault axis 2 (darker than FAP2)
    "FAX3": "#6600CC",  # Dark purple - fault axis 3 (darker than FAP3)
    "FAX4": "#00CC00",  # Dark green - fault axis 4 (darker than FAP4)
    "FAX5": "#0099CC",  # Dark cyan - fault axis 5 (darker than FAP5)
    "FAXCR": "#6A5ACD", # Slate blue - fault axis conjugate
    "FAXK": "#483D8B",  # Dark slate blue - kinematic fault axis
    "FAXSZ": "#8B4513", # Saddle brown - shear zone fault axis
    
    # Shear zones - DISTINCT grays and cool colors
    "SZB": "#2F4F4F",   # Dark slate gray - shear zone boundary
    "SZC": "#708090",   # Slate gray - shear zone cleavage
    "SZCD": "#483D8B",  # Dark slate blue - shear zone displacement
    "SZCN": "#6A5ACD",  # Slate blue - shear zone normal
    "SZCR": "#9370DB",  # Medium purple - shear zone reverse
    "SZCS": "#8B008B",  # Dark magenta - shear zone strike-slip
    "SZS": "#4169E1",   # Royal blue - shear zone structure

    # Veins - HIGHLY DISTINCT vibrant colors like S1-S5
    "VL": "#FF0000",    # Red - vein longitudinal
    "VN": "#FFFF00",    # Yellow - vein normal
    "VS": "#00FF00",    # Green - vein strike
    "VT": "#0000FF",    # Blue - vein transverse
    "VX": "#FF00FF",    # Magenta - vein extension

    # Contact/Intrusion - DISTINCT warm colors
    "CT": "#FF6347",    # Tomato - contact
    "CTI": "#FF4500",   # Orange red - intrusive contact
    "CTE": "#FF8C00",   # Dark orange - extrusive contact

    # Linear structures - HIGHLY DISTINCT vibrant colors like S1-S5
    "BAX": "#FF0000",   # Red - b-axis
    "LME": "#FF8800",   # Orange - mineral lineation
    "LNI": "#FFFF00",   # Yellow - intersection lineation
    "LNISC": "#00FA9A", # Medium spring green - S-C intersection lineation
    "LNS": "#00FFFF",   # Cyan - slickenside lineation
    "STR": "#9933FF",   # Purple - stretching lineation

    # Additional common codes with DISTINCT colors
    "JT": "#8B4513",    # Saddle brown - joint
    "LIN": "#9932CC",   # Dark orchid - lineation
    "AX": "#FF1493",    # Deep pink - axis
    "POL": "#00BFFF",   # Deep sky blue - pole
    "STK": "#FF69B4",   # Hot pink - strike
    "DIP": "#7FFF00",   # Chartreuse - dip
}


class StereonetPluginCore:
    """
    Main stereonet plugin core class.
    
    This class handles all stereonet functionality including:
    - Dataset management and configuration
    - Plot generation and visualization  
    - Category selection and filtering
    - Data export and analysis
    - Live view monitoring
    """
    
    def __init__(self, iface):
        """
        Initialize the stereonet plugin core.
        
        Args:
            iface: QGIS interface object
        """
        self.iface = iface
        self.dock = None
        self.tab_widget = None

        # Use the global variables but also make class attributes for easier access
        self.planar_codes = planar_codes
        self.linear_codes = linear_codes

        # Main tab widgets
        self.datasets_widget = None
        self.plot_widget = None
        self.categories_widget = None
        self.config_widget = None
        self.coding_widget = None
        self.export_widget = None
        self.colors_widget = None
        
        # Color management
        self.structure_colors = DEFAULT_STRUCTURE_COLORS.copy()  # User-customizable colors
        self.color_buttons = {}  # Dict to store color button references

        # Code groups: merge several codes into one plotted category.
        # {group_name: [base_code, ...]} — a code belongs to at most one group.
        self.code_groups = {}
        self.group_colors_layout = None  # "Code Groups" rows in the Colors tab

        # Dataset configurations
        self.active_dataset = 0  # Index of currently active dataset (0 or 1)
        self.dataset_configs = [
            {
                "name": "Dataset 1",
                "enabled": True,
                "color": "#1f77b4",  # Default blue
                "layer_combo": None,
                "dip_combo": None,
                "dipdir_combo": None,
                "subtype_combo": None,
                "easting_combo": None,
                "northing_combo": None,
                "domain_combo": None  # Domain field selector
            },
            {
                "name": "Dataset 2",
                "enabled": False,
                "color": "#ff7f0e",  # Default orange
                "layer_combo": None,
                "dip_combo": None,
                "dipdir_combo": None,
                "subtype_combo": None,
                "easting_combo": None,
                "northing_combo": None,
                "domain_combo": None  # Domain field selector
            }
        ]

        # Plot tab sub-widgets - separate checkboxes for planes and lines
        self.plot_label = None
        self.plot_figure = None
        self.plot_canvas = None
        self.plot_stack = None
        self.pick_handler = None
        # Set while a stereonet pick applies a QGIS selection, so Live View
        # "by selection" doesn't replot from the click (one-way sync)
        self._suppress_selection_replot = False
        # Layers whose selectionChanged signal is connected to
        # on_selection_changed - tracked explicitly so cleanup disconnects
        # the layers we actually connected to, even if the layer combo
        # changed or a dataset was disabled in the meantime
        self._selection_signal_layers = []
        self.best_fit_plane_checkbox = None
        self.contour_plane_checkbox = None
        self.best_fit_line_checkbox = None
        self.contour_line_checkbox = None

        # Mean vector analysis widgets
        self.analysis_scope_combo = None
        self.mean_plane_checkbox = None
        self.mean_plane_type_combo = None
        self.mean_line_checkbox = None

        # Keep these for backward compatibility
        self.best_fit_checkbox = None
        self.contour_checkbox = None

        self.copy_highres_button = None
        self.save_svg_button = None
        self.transparent_svg_checkbox = None

        # Rake checkbox
        self.rake_checkbox = None

        # Alternate plotting mode checkbox
        self.alternate_plot_mode_checkbox = None

        # Combine-datasets toggle (Datasets tab)
        self.combine_datasets_checkbox = None

        # Legend ordering checkbox
        self.order_by_domain_checkbox = None

        # "Categories" tab sub-widgets
        self.categories_tabwidget = None
        self.category_tree_selection = None
        self.category_tree_domains = None

        # Data dictionaries - arrays for multiple datasets
        self.subtype_dict_selection = [{}, {}]
        self.category_structure_map_selection = [{}, {}]
        self.subtype_dict_domains = [{}, {}]
        self.category_structure_map_domains = [{}, {}]

        self.last_plotted_data = []
        self.last_analysis_flags = {}

        # Stored layersAdded/layersRemoved handlers (one per dataset) so they
        # can be disconnected on unload / combo re-creation
        self._project_signal_connections = [None, None]

        # For backward compatibility, maintain these references to dataset 0
        self.auto_layer_combo = None
        self.dip_column_combo = None
        self.dipdir_column_combo = None
        self.subtype_column_combo = None

        # Coding tab
        self.coding_table = None
        self.coding_entries = {}  # Store references to coding table entries
        self.show_known_codes_checkbox = None
        self.code_count_label = None

        # Live view functionality
        self.live_view_enabled = False
        self.map_canvas = self.iface.mapCanvas()
        self.extent_change_timer = QTimer()
        self.extent_change_timer.setSingleShot(True)
        self.extent_change_timer.timeout.connect(self.update_live_view_data)
        self.last_extent = None
        self.update_delay_ms = 500  # Minimum delay between updates

        # Live view data structures
        self.subtype_dict_live_view = [{}, {}]
        self.category_structure_map_live_view = [{}, {}]
        self.category_tree_live_view = None

        # Temporary dataset for comparison
        self.temporary_dataset = [{}, {}]  # Same structure as live view data
        self.temporary_dataset_captured = False  # Track if temp data exists

        # Selection monitoring
        self.selection_monitoring_active = False
        self.last_selection_ids = [set(), set()]  # Track selection per dataset

        # Intersection analysis
        self.intersection_enabled = False
        self.intersection_checkbox = None

        # Load saved structure colors
        self.load_structure_colors()

        # Load saved code groups
        self.load_code_groups()

    # =========================================================================
    # CATEGORY SELECTION METHODS
    # =========================================================================

    def select_all_categories_selection(self):
        """Select all categories in the selection tree."""
        if not self.category_tree_selection:
            return
        for i in range(self.category_tree_selection.topLevelItemCount()):
            item = self.category_tree_selection.topLevelItem(i)
            item.setCheckState(0, Qt.Checked)
        QgsMessageLog.logMessage("[Selection] All categories selected.", 'Linear Geoscience', Qgis.Info)

    def deselect_all_categories_selection(self):
        """Deselect all categories in the selection tree."""
        if not self.category_tree_selection:
            return
        for i in range(self.category_tree_selection.topLevelItemCount()):
            item = self.category_tree_selection.topLevelItem(i)
            item.setCheckState(0, Qt.Unchecked)
        QgsMessageLog.logMessage("[Selection] All categories deselected.", 'Linear Geoscience', Qgis.Info)

    def select_highlighted_categories_selection(self):
        """Select highlighted categories in the selection tree."""
        if not self.category_tree_selection:
            return
        for item in self.category_tree_selection.selectedItems():
            item.setCheckState(0, Qt.Checked)
        QgsMessageLog.logMessage("[Selection] Highlighted categories selected.", 'Linear Geoscience', Qgis.Info)

    def deselect_highlighted_categories_selection(self):
        """Deselect highlighted categories in the selection tree."""
        if not self.category_tree_selection:
            return
        for item in self.category_tree_selection.selectedItems():
            item.setCheckState(0, Qt.Unchecked)
        QgsMessageLog.logMessage("[Selection] Highlighted categories deselected.", 'Linear Geoscience', Qgis.Info)

    def select_all_categories_domains(self):
        """Select all categories in the domains tree."""
        if not self.category_tree_domains:
            return
        for i in range(self.category_tree_domains.topLevelItemCount()):
            item = self.category_tree_domains.topLevelItem(i)
            item.setCheckState(0, Qt.Checked)
        QgsMessageLog.logMessage("[Domains] All categories selected.", 'Linear Geoscience', Qgis.Info)

    def deselect_all_categories_domains(self):
        """Deselect all categories in the domains tree."""
        if not self.category_tree_domains:
            return
        for i in range(self.category_tree_domains.topLevelItemCount()):
            item = self.category_tree_domains.topLevelItem(i)
            item.setCheckState(0, Qt.Unchecked)
        QgsMessageLog.logMessage("[Domains] All categories deselected.", 'Linear Geoscience', Qgis.Info)

    def select_highlighted_categories_domains(self):
        """Select highlighted categories in the domains tree."""
        if not self.category_tree_domains:
            return
        for item in self.category_tree_domains.selectedItems():
            item.setCheckState(0, Qt.Checked)
        QgsMessageLog.logMessage("[Domains] Highlighted categories selected.", 'Linear Geoscience', Qgis.Info)

    def deselect_highlighted_categories_domains(self):
        """Deselect highlighted categories in the domains tree."""
        if not self.category_tree_domains:
            return
        for item in self.category_tree_domains.selectedItems():
            item.setCheckState(0, Qt.Unchecked)
        QgsMessageLog.logMessage("[Domains] Highlighted categories deselected.", 'Linear Geoscience', Qgis.Info)

    def select_all_categories_live_view(self):
        """Select all categories in the live view tree."""
        if not self.category_tree_live_view:
            return
        for i in range(self.category_tree_live_view.topLevelItemCount()):
            item = self.category_tree_live_view.topLevelItem(i)
            item.setCheckState(0, Qt.Checked)
        QgsMessageLog.logMessage("[Live View] All categories selected.", 'Linear Geoscience', Qgis.Info)

    def deselect_all_categories_live_view(self):
        """Deselect all categories in the live view tree."""
        if not self.category_tree_live_view:
            return
        for i in range(self.category_tree_live_view.topLevelItemCount()):
            item = self.category_tree_live_view.topLevelItem(i)
            item.setCheckState(0, Qt.Unchecked)
        QgsMessageLog.logMessage("[Live View] All categories deselected.", 'Linear Geoscience', Qgis.Info)

    def select_highlighted_categories_live_view(self):
        """Select highlighted categories in the live view tree."""
        if not self.category_tree_live_view:
            return
        for item in self.category_tree_live_view.selectedItems():
            item.setCheckState(0, Qt.Checked)
        QgsMessageLog.logMessage("[Live View] Highlighted categories selected.", 'Linear Geoscience', Qgis.Info)

    def deselect_highlighted_categories_live_view(self):
        """Deselect highlighted categories in the live view tree."""
        if not self.category_tree_live_view:
            return
        for item in self.category_tree_live_view.selectedItems():
            item.setCheckState(0, Qt.Unchecked)
        QgsMessageLog.logMessage("[Live View] Highlighted categories deselected.", 'Linear Geoscience', Qgis.Info)

    # =========================================================================
    # GUI INITIALIZATION AND SETUP METHODS
    # =========================================================================

    def initGui(self):
        QgsMessageLog.logMessage("Initializing Stereonet Plugin GUI...", 'Linear Geoscience', Qgis.Info)

        self.dock = QDockWidget("Stereonet", self.iface.mainWindow())
        self.dock.setObjectName("StereonetDock")
        self.dock.setMinimumWidth(350)  # Ensure minimum width for better layout

        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)  # More modern tab appearance

        # 0) Plot Tab (now first)
        self.plot_widget = QWidget()
        self.setup_plot_tab()

        # For backward compatibility, point old checkbox references to new ones
        if hasattr(self, 'best_fit_plane_checkbox'):
            self.best_fit_checkbox = self.best_fit_plane_checkbox
        if hasattr(self, 'contour_plane_checkbox'):
            self.contour_checkbox = self.contour_plane_checkbox

        scroll_plot = QScrollArea()
        scroll_plot.setWidget(self.plot_widget)
        scroll_plot.setWidgetResizable(True)
        scroll_plot.setFrameShape(QFrame.NoFrame)  # Remove frame for cleaner look
        self.tab_widget.addTab(scroll_plot, "Plot")

        # 1) Categories Tab (now second)
        self.categories_widget = QWidget()
        self.setup_categories_tab()
        scroll_categories = QScrollArea()
        scroll_categories.setWidget(self.categories_widget)
        scroll_categories.setWidgetResizable(True)
        scroll_categories.setFrameShape(QFrame.NoFrame)
        self.tab_widget.addTab(scroll_categories, "Categories")

        # 2) Datasets Tab (now third, renamed from "Datasets & Config" to "Datasets")
        self.datasets_widget = QWidget()
        self.setup_datasets_tab()
        scroll_datasets = QScrollArea()
        scroll_datasets.setWidget(self.datasets_widget)
        scroll_datasets.setWidgetResizable(True)
        scroll_datasets.setFrameShape(QFrame.NoFrame)
        self.tab_widget.addTab(scroll_datasets, "Datasets")  # Renamed to just "Datasets"

        # 3) Coding Tab (fourth position) - Enhanced version
        self.coding_widget = QWidget()
        self.setup_coding_tab()
        scroll_coding = QScrollArea()
        scroll_coding.setWidget(self.coding_widget)
        scroll_coding.setWidgetResizable(True)
        scroll_coding.setFrameShape(QFrame.NoFrame)
        self.tab_widget.addTab(scroll_coding, "Coding")

        # 4) Colors Tab (fifth position)
        self.colors_widget = QWidget()
        self.setup_colors_tab()
        scroll_colors = QScrollArea()
        scroll_colors.setWidget(self.colors_widget)
        scroll_colors.setWidgetResizable(True)
        scroll_colors.setFrameShape(QFrame.NoFrame)
        self.tab_widget.addTab(scroll_colors, "Colors")

        # 5) Export Tab (sixth position)
        self.export_widget = QWidget()
        self.setup_export_tab()
        scroll_export = QScrollArea()
        scroll_export.setWidget(self.export_widget)
        scroll_export.setWidgetResizable(True)
        scroll_export.setFrameShape(QFrame.NoFrame)
        self.tab_widget.addTab(scroll_export, "Export")

        self.dock.setWidget(self.tab_widget)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)

        # Set up backward compatibility references
        self.auto_layer_combo = self.dataset_configs[0]["layer_combo"]
        self.dip_column_combo = self.dataset_configs[0]["dip_combo"]
        self.dipdir_column_combo = self.dataset_configs[0]["dipdir_combo"]
        self.subtype_column_combo = self.dataset_configs[0]["subtype_combo"]

        # Apply modern styling
        self.apply_modern_style()

        # Add the intersection controls
        self.setup_intersection_controls()

        QgsMessageLog.logMessage("Stereonet GUI init done. Datasets tab moved to third position.", 'Linear Geoscience', Qgis.Info)

        # Auto-run refresh
        self.manual_refresh()
        self.update_plot()

        # Initialize coding table
        self.populate_coding_table()


    def apply_modern_style(self):
        """Apply modern styling to all UI components using global constants."""

        # Global stylesheet using constants
        main_style = f"""
        QWidget {{
            color: {TEXT_COLOR};
            font-family: 'Segoe UI', 'Arial', sans-serif;
        }}

        QLabel {{
            padding: 2px;
        }}

        QTabWidget::pane {{
            border: 1px solid {BORDER_COLOR};
            border-radius: 4px;
            padding: 2px;
            background-color: white;
        }}

        QTabBar::tab {{
            background-color: {MEDIUM_BG};
            border: 1px solid {BORDER_COLOR};
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            padding: 6px 12px;
            margin-right: 2px;
        }}

        QTabBar::tab:selected {{
            background-color: white;
            border-bottom: 2px solid {PRIMARY_COLOR};
        }}

        QGroupBox {{
            font-weight: bold;
            border: 1px solid {BORDER_COLOR};
            border-radius: 4px;
            margin-top: 12px;
            padding-top: 8px;
        }}

        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 10px;
            padding: 0 3px;
            background-color: white;
        }}

        QPushButton {{
            background-color: {PRIMARY_COLOR};
            color: white;
            border: none;
            border-radius: 4px;
            padding: 6px 12px;
            font-weight: bold;
            min-width: 80px;
        }}

        QPushButton:hover {{
            background-color: #2980b9;
        }}

        QPushButton:pressed {{
            background-color: #1a5276;
        }}

        QPushButton:disabled {{
            background-color: #bdc3c7;
            color: #7f8c8d;
        }}

        QComboBox {{
            border: 1px solid {BORDER_COLOR};
            border-radius: 4px;
            padding: 4px;
            background-color: white;
            min-height: 20px;
        }}

        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: center right;
            width: 20px;
            border-left: 1px solid {BORDER_COLOR};
        }}

        QLineEdit {{
            border: 1px solid {BORDER_COLOR};
            border-radius: 4px;
            padding: 4px;
            background-color: white;
            selection-background-color: {PRIMARY_COLOR};
        }}

        QTreeWidget {{
            border: 1px solid {BORDER_COLOR};
            border-radius: 4px;
            alternate-background-color: {LIGHT_BG};
            selection-background-color: {PRIMARY_COLOR};
            selection-color: white;
        }}

        QTreeWidget::item {{
            padding: 4px;
            border-bottom: 1px solid {LIGHT_BG};
        }}

        QTreeWidget::item:selected {{
            background-color: {PRIMARY_COLOR};
            color: white;
        }}

        QHeaderView::section {{
            background-color: {MEDIUM_BG};
            border: 1px solid {BORDER_COLOR};
            padding: 4px;
        }}

        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
        }}

        QRadioButton::indicator {{
            width: 16px;
            height: 16px;
        }}

        QTableWidget {{
            border: 1px solid {BORDER_COLOR};
            border-radius: 4px;
            gridline-color: {BORDER_COLOR};
            selection-background-color: {PRIMARY_COLOR};
            selection-color: white;
        }}

        QScrollArea {{
            border: none;
            background-color: white;
        }}

        QScrollBar:vertical {{
            border: none;
            background-color: {LIGHT_BG};
            width: 10px;
            margin: 0px;
        }}

        QScrollBar::handle:vertical {{
            background-color: #bdc3c7;
            border-radius: 5px;
            min-height: 20px;
        }}

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        """

        # Apply the stylesheet to the main application
        self.dock.setStyleSheet(main_style)

        # Custom styling for specific widgets
        if hasattr(self, 'copy_highres_button') and self.copy_highres_button:
            self.copy_highres_button.setStyleSheet(f"""
                background-color: {SECONDARY_COLOR};
                min-width: 120px;
            """)

        if hasattr(self, 'save_svg_button') and self.save_svg_button:
            self.save_svg_button.setStyleSheet(f"""
                background-color: {SECONDARY_COLOR};
                min-width: 120px;
            """)

        # Success buttons
        for widget in self.dock.findChildren(QPushButton):
            if any(text in widget.text().lower() for text in ["refresh", "plot", "apply", "export", "save"]):
                widget.setStyleSheet(f"""
                    background-color: {SUCCESS_COLOR};
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-weight: bold;
                    min-width: 80px;
                """)
                widget.setCursor(Qt.PointingHandCursor)

        # Set cursor for interactive elements
        for button in self.dock.findChildren(QPushButton):
            button.setCursor(Qt.PointingHandCursor)

        for combo in self.dock.findChildren(QComboBox):
            combo.setCursor(Qt.PointingHandCursor)

        for checkbox in self.dock.findChildren(QCheckBox):
            checkbox.setCursor(Qt.PointingHandCursor)

        for radio in self.dock.findChildren(QRadioButton):
            radio.setCursor(Qt.PointingHandCursor)

        # Make plot area stand out
        if hasattr(self, 'plot_label') and self.plot_label:
            self.plot_label.setStyleSheet(f"""
                background-color: white;
                border: 2px solid {BORDER_COLOR};
                border-radius: 8px;
                padding: 10px;
            """)
















##############################StereonetContourplanes


    def setup_intersection_controls(self):
        """Add an Intersection Contours checkbox to the plot controls"""
        if hasattr(self, 'plot_widget') and self.plot_widget:
            # Find the analysis group in the plot tab
            analysis_group = None
            for child in self.plot_widget.findChildren(QGroupBox):
                if "Analysis" in child.title():
                    analysis_group = child
                    break

            if analysis_group and analysis_group.layout():
                # Create a layout for intersection controls
                intersection_layout = QHBoxLayout()
                intersection_layout.setSpacing(15)

                # Create the label
                intersect_label = QLabel("Intersections:")
                intersect_label.setStyleSheet("font-weight: bold;")

                # Create the checkbox
                self.intersection_contour_checkbox = QCheckBox("Show Contours")
                self.intersection_contour_checkbox.setChecked(False)

                # Connect to plot update
                self.intersection_contour_checkbox.stateChanged.connect(self.request_plot_update)

                # Add to layout
                intersection_layout.addWidget(intersect_label)
                intersection_layout.addWidget(self.intersection_contour_checkbox)
                intersection_layout.addStretch()

                # Add to the analysis group layout
                analysis_group.layout().addLayout(intersection_layout)


    def setup_datasets_tab(self):
        layout = QVBoxLayout(self.datasets_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)

        # Title and description - updated name
        title_label = QLabel("Dataset Manager")
        title_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: #2c3e50;")
        desc_label = QLabel("Configure and manage multiple datasets for comparative analysis.")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #7f8c8d; font-style: italic;")

        layout.addWidget(title_label)
        layout.addWidget(desc_label)

        # Combine-datasets option: merge identical codes across datasets at
        # plot time (one colour / legend entry / analysis per code)
        self.combine_datasets_checkbox = QCheckBox(
            "Combine datasets — plot identical codes from both datasets as one category")
        self.combine_datasets_checkbox.setToolTip(
            "When checked, the same code from both datasets plots as a single "
            "merged category (one colour, one legend entry, merged analysis) "
            "instead of separate filled/hollow series.\n"
            "Exports always include both datasets either way.")
        self.combine_datasets_checkbox.stateChanged.connect(self._on_combine_datasets_toggled)
        layout.addWidget(self.combine_datasets_checkbox)
        layout.addSpacing(10)

        # --- Dataset 1 Group ---
        dataset1_group = QGroupBox("Dataset 1")
        dataset1_layout = QVBoxLayout(dataset1_group)  # Changed layout type
        dataset1_layout.setContentsMargins(10, 15, 10, 10)
        dataset1_layout.setSpacing(10)

        # Dataset 1 basic controls (Enable checkbox, Name, Color)
        dataset1_enable = QCheckBox("Enable Dataset 1")
        dataset1_enable.setChecked(self.dataset_configs[0]["enabled"])
        dataset1_enable.stateChanged.connect(lambda state: self.toggle_dataset(0, state))

        dataset1_name = QLineEdit(self.dataset_configs[0]["name"])
        dataset1_name.setPlaceholderText("Dataset Name")
        dataset1_name.textChanged.connect(lambda text: self.rename_dataset(0, text))

        dataset1_color_btn = QPushButton("Set Color")
        dataset1_color_btn.clicked.connect(lambda: self.set_dataset_color(0))

        # Color preview with rounded corners
        dataset1_color_preview = QFrame()
        dataset1_color_preview.setStyleSheet(f"""
            background-color: {self.dataset_configs[0]['color']};
            border-radius: 4px;
            border: 1px solid #dee2e6;
        """)
        dataset1_color_preview.setFixedSize(20, 20)
        dataset1_color_preview.setFrameShape(QFrame.Box)

        dataset1_controls_layout = QHBoxLayout()  # Layout for basic controls
        dataset1_controls_layout.setSpacing(10)
        dataset1_controls_layout.addWidget(dataset1_enable)
        dataset1_controls_layout.addWidget(QLabel("Name:"))
        dataset1_controls_layout.addWidget(dataset1_name)
        dataset1_controls_layout.addWidget(QLabel("Color:"))
        dataset1_controls_layout.addWidget(dataset1_color_preview)
        dataset1_controls_layout.addWidget(dataset1_color_btn)
        dataset1_controls_layout.addStretch()
        dataset1_layout.addLayout(dataset1_controls_layout)
        # --- End Basic Controls ---

        # Configuration section - Dataset 1
        config1_group = QGroupBox("Field Configuration")  # Renamed for clarity
        config1_form_layout = QFormLayout(config1_group)  # Use Form layout for fields
        config1_form_layout.setContentsMargins(10, 15, 10, 10)
        config1_form_layout.setSpacing(10)
        config1_form_layout.setLabelAlignment(Qt.AlignRight)

        # Custom Layer selection with sources
        self.dataset_configs[0]["layer_combo"] = self.create_layer_combo_with_source(0)
        config1_form_layout.addRow(QLabel("Layer:"), self.dataset_configs[0]["layer_combo"])

        # Field selections (Dip, DipDir, Subtype)
        self.dataset_configs[0]["dip_combo"] = QComboBox()
        self.dataset_configs[0]["dip_combo"].setMaxVisibleItems(15)
        config1_form_layout.addRow(QLabel("Dip Field:"), self.dataset_configs[0]["dip_combo"])

        self.dataset_configs[0]["dipdir_combo"] = QComboBox()
        self.dataset_configs[0]["dipdir_combo"].setMaxVisibleItems(15)
        config1_form_layout.addRow(QLabel("Dip Direction Field:"), self.dataset_configs[0]["dipdir_combo"])

        self.dataset_configs[0]["subtype_combo"] = QComboBox()
        self.dataset_configs[0]["subtype_combo"].setMaxVisibleItems(15)
        config1_form_layout.addRow(QLabel("Structure Code Field:"), self.dataset_configs[0]["subtype_combo"])

        # --- NEW: Domain Field Selection ---
        self.dataset_configs[0]["domain_combo"] = QComboBox()
        self.dataset_configs[0]["domain_combo"].setMaxVisibleItems(15)
        config1_form_layout.addRow(QLabel("Domain Field:"), self.dataset_configs[0]["domain_combo"])
        # --- END NEW ---

        # Easting/Northing Field Selection
        self.dataset_configs[0]["easting_combo"] = QComboBox()
        self.dataset_configs[0]["easting_combo"].setMaxVisibleItems(15)
        self.dataset_configs[0]["easting_combo"].addItem("", None)  # Add empty option
        config1_form_layout.addRow(QLabel("Easting (X) Field:"), self.dataset_configs[0]["easting_combo"])

        self.dataset_configs[0]["northing_combo"] = QComboBox()
        self.dataset_configs[0]["northing_combo"].setMaxVisibleItems(15)
        self.dataset_configs[0]["northing_combo"].addItem("", None)  # Add empty option
        config1_form_layout.addRow(QLabel("Northing (Y) Field:"), self.dataset_configs[0]["northing_combo"])

        # Refresh fields button
        refresh_button1 = QPushButton("Refresh Fields")
        refresh_button1.clicked.connect(lambda: self.populate_field_combo_boxes(0))
        config1_form_layout.addRow(refresh_button1)  # Add to form layout

        # Add config group to dataset layout
        dataset1_layout.addWidget(config1_group)
        layout.addWidget(dataset1_group)  # Add Dataset 1 group to main layout
        layout.addSpacing(10)

        # --- Dataset 2 Group ---
        dataset2_group = QGroupBox("Dataset 2")
        dataset2_layout = QVBoxLayout(dataset2_group)  # Changed layout type
        dataset2_layout.setContentsMargins(10, 15, 10, 10)
        dataset2_layout.setSpacing(10)

        # Dataset 2 basic controls (Enable checkbox, Name, Color)
        dataset2_enable = QCheckBox("Enable Dataset 2")
        dataset2_enable.setChecked(self.dataset_configs[1]["enabled"])
        dataset2_enable.stateChanged.connect(lambda state: self.toggle_dataset(1, state))

        dataset2_name = QLineEdit(self.dataset_configs[1]["name"])
        dataset2_name.setPlaceholderText("Dataset Name")
        dataset2_name.textChanged.connect(lambda text: self.rename_dataset(1, text))

        dataset2_color_btn = QPushButton("Set Color")
        dataset2_color_btn.clicked.connect(lambda: self.set_dataset_color(1))

        dataset2_color_preview = QFrame()
        dataset2_color_preview.setStyleSheet(f"""
            background-color: {self.dataset_configs[1]['color']};
            border-radius: 4px;
            border: 1px solid #dee2e6;
        """)
        dataset2_color_preview.setFixedSize(20, 20)
        dataset2_color_preview.setFrameShape(QFrame.Box)

        dataset2_controls_layout = QHBoxLayout()  # Layout for basic controls
        dataset2_controls_layout.setSpacing(10)
        dataset2_controls_layout.addWidget(dataset2_enable)
        dataset2_controls_layout.addWidget(QLabel("Name:"))
        dataset2_controls_layout.addWidget(dataset2_name)
        dataset2_controls_layout.addWidget(QLabel("Color:"))
        dataset2_controls_layout.addWidget(dataset2_color_preview)
        dataset2_controls_layout.addWidget(dataset2_color_btn)
        dataset2_controls_layout.addStretch()
        dataset2_layout.addLayout(dataset2_controls_layout)
        # --- End Basic Controls ---

        # Configuration section - Dataset 2
        config2_group = QGroupBox("Field Configuration")  # Renamed for clarity
        config2_form_layout = QFormLayout(config2_group)  # Use Form layout for fields
        config2_form_layout.setContentsMargins(10, 15, 10, 10)
        config2_form_layout.setSpacing(10)
        config2_form_layout.setLabelAlignment(Qt.AlignRight)

        # Custom Layer selection with sources
        self.dataset_configs[1]["layer_combo"] = self.create_layer_combo_with_source(1)
        config2_form_layout.addRow(QLabel("Layer:"), self.dataset_configs[1]["layer_combo"])

        # Field selections (Dip, DipDir, Subtype)
        self.dataset_configs[1]["dip_combo"] = QComboBox()
        self.dataset_configs[1]["dip_combo"].setMaxVisibleItems(15)
        config2_form_layout.addRow(QLabel("Dip Field:"), self.dataset_configs[1]["dip_combo"])

        self.dataset_configs[1]["dipdir_combo"] = QComboBox()
        self.dataset_configs[1]["dipdir_combo"].setMaxVisibleItems(15)
        config2_form_layout.addRow(QLabel("Dip Direction Field:"), self.dataset_configs[1]["dipdir_combo"])

        self.dataset_configs[1]["subtype_combo"] = QComboBox()
        self.dataset_configs[1]["subtype_combo"].setMaxVisibleItems(15)
        config2_form_layout.addRow(QLabel("Structure Code Field:"), self.dataset_configs[1]["subtype_combo"])

        # --- NEW: Domain Field Selection ---
        self.dataset_configs[1]["domain_combo"] = QComboBox()
        self.dataset_configs[1]["domain_combo"].setMaxVisibleItems(15)
        config2_form_layout.addRow(QLabel("Domain Field:"), self.dataset_configs[1]["domain_combo"])
        # --- END NEW ---

        # Easting/Northing Field Selection
        self.dataset_configs[1]["easting_combo"] = QComboBox()
        self.dataset_configs[1]["easting_combo"].setMaxVisibleItems(15)
        self.dataset_configs[1]["easting_combo"].addItem("", None)  # Add empty option
        config2_form_layout.addRow(QLabel("Easting (X) Field:"), self.dataset_configs[1]["easting_combo"])

        self.dataset_configs[1]["northing_combo"] = QComboBox()
        self.dataset_configs[1]["northing_combo"].setMaxVisibleItems(15)
        self.dataset_configs[1]["northing_combo"].addItem("", None)  # Add empty option
        config2_form_layout.addRow(QLabel("Northing (Y) Field:"), self.dataset_configs[1]["northing_combo"])

        # Refresh fields button
        refresh_button2 = QPushButton("Refresh Fields")
        refresh_button2.clicked.connect(lambda: self.populate_field_combo_boxes(1))
        config2_form_layout.addRow(refresh_button2)  # Add to form layout

        # Add config group to dataset layout
        dataset2_layout.addWidget(config2_group)
        layout.addWidget(dataset2_group)  # Add Dataset 2 group to main layout

        # Store dataset panel references (optional, might not be needed anymore)
        self.dataset1_panel = dataset1_group
        self.dataset2_panel = dataset2_group

        # Add notes about usage
        note_label = QLabel(
            "Note: Enable datasets and select the layer and ALL required fields (Dip, Dip Direction, Structure Code). "
            "Use 'Refresh Fields' if needed.")
        note_label.setWordWrap(True)
        note_label.setStyleSheet("font-style: italic; color: #7f8c8d; padding: 10px;")

        # Add everything to main layout
        layout.addSpacing(5)
        layout.addWidget(note_label)
        layout.addStretch()

        # Set backward compatibility references
        self.auto_layer_combo = self.dataset_configs[0]["layer_combo"]
        self.dip_column_combo = self.dataset_configs[0]["dip_combo"]
        self.dipdir_column_combo = self.dataset_configs[0]["dipdir_combo"]
        self.subtype_column_combo = self.dataset_configs[0]["subtype_combo"]


    def setup_plot_tab(self):
        layout = QVBoxLayout(self.plot_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)

        # Visualization controls group
        controls_group = QgsCollapsibleGroupBox("Visualization Settings")
        controls_group.setFlat(True)
        controls_layout = QVBoxLayout()
        controls_layout.setContentsMargins(10, 15, 10, 10)
        controls_layout.setSpacing(10)
        controls_group.setLayout(controls_layout)

        # Live View section with enhanced controls
        live_view_group = QGroupBox("Live View Mode")
        live_view_layout = QVBoxLayout()
        live_view_layout.setContentsMargins(10, 10, 10, 10)
        live_view_layout.setSpacing(8)
        live_view_group.setLayout(live_view_layout)

        # Main live view checkbox
        self.show_visible_features_checkbox = QCheckBox("Enable Live View")
        self.show_visible_features_checkbox.setChecked(False)
        self.show_visible_features_checkbox.stateChanged.connect(self.toggle_live_view_mode)
        live_view_layout.addWidget(self.show_visible_features_checkbox)

        # Live view options (horizontal layout)
        live_view_options_layout = QHBoxLayout()
        live_view_options_layout.setContentsMargins(20, 5, 5, 5)  # Indent to show they're sub-options
        live_view_options_layout.setSpacing(15)

        # By Map Extent checkbox (default mode)
        self.live_view_by_extent_checkbox = QCheckBox("By Map Extent")
        self.live_view_by_extent_checkbox.setChecked(True)  # Default to map extent mode
        self.live_view_by_extent_checkbox.stateChanged.connect(self.on_extent_mode_changed)
        live_view_options_layout.addWidget(self.live_view_by_extent_checkbox)

        # By Selection checkbox
        self.live_view_by_selection_checkbox = QCheckBox("By Selection")
        self.live_view_by_selection_checkbox.setChecked(False)
        self.live_view_by_selection_checkbox.stateChanged.connect(self.on_selection_mode_changed)
        live_view_options_layout.addWidget(self.live_view_by_selection_checkbox)

        # By Domain checkbox
        self.live_view_by_domain_checkbox = QCheckBox("By Domain")
        self.live_view_by_domain_checkbox.setChecked(False)
        self.live_view_by_domain_checkbox.stateChanged.connect(self.on_domain_mode_changed)
        live_view_options_layout.addWidget(self.live_view_by_domain_checkbox)

        live_view_options_layout.addStretch()  # Push options to the left
        live_view_layout.addLayout(live_view_options_layout)

        # Info label for live view
        self.live_view_info_label = QLabel("Select features or pan/zoom to update the plot")
        self.live_view_info_label.setStyleSheet("color: #7f8c8d; font-style: italic; font-size: 9pt;")
        self.live_view_info_label.setVisible(False)  # Hidden by default
        live_view_layout.addWidget(self.live_view_info_label)

        # Temporary comparison controls (horizontal layout)
        temp_controls_layout = QHBoxLayout()
        temp_controls_layout.setContentsMargins(20, 5, 5, 5)  # Indent to show they're sub-options
        temp_controls_layout.setSpacing(10)

        self.capture_button = QPushButton("Capture Current View")
        self.capture_button.setEnabled(False)  # Disabled until live view is active
        self.capture_button.clicked.connect(self.capture_temporary_dataset)
        temp_controls_layout.addWidget(self.capture_button)

        self.clear_temp_button = QPushButton("Clear Temporary")
        self.clear_temp_button.setEnabled(False)  # Disabled until temp data exists
        self.clear_temp_button.clicked.connect(self.clear_temporary_dataset)
        temp_controls_layout.addWidget(self.clear_temp_button)

        temp_controls_layout.addStretch()  # Push buttons to the left
        live_view_layout.addLayout(temp_controls_layout)

        # Status label for temporary data
        self.temp_status_label = QLabel("")
        self.temp_status_label.setStyleSheet("color: #27ae60; font-style: italic; font-size: 9pt;")
        self.temp_status_label.setVisible(False)
        live_view_layout.addWidget(self.temp_status_label)

        controls_layout.addWidget(live_view_group)

        # Alternate plotting mode section
        alternate_mode_group = QGroupBox("Plotting Style")
        alternate_mode_layout = QVBoxLayout()
        alternate_mode_layout.setContentsMargins(10, 10, 10, 10)
        alternate_mode_layout.setSpacing(8)
        alternate_mode_group.setLayout(alternate_mode_layout)

        self.alternate_plot_mode_checkbox = QCheckBox("Alternate Mode: Shape by Code, Color by Domain")
        self.alternate_plot_mode_checkbox.setChecked(False)
        self.alternate_plot_mode_checkbox.setToolTip(
            "When enabled:\n"
            "- Each code gets a unique marker shape\n"
            "- Each domain gets a single distinct color"
        )
        self.alternate_plot_mode_checkbox.stateChanged.connect(self.request_plot_update)
        alternate_mode_layout.addWidget(self.alternate_plot_mode_checkbox)

        # Legend ordering checkbox
        self.order_by_domain_checkbox = QCheckBox("Order Legend by Domain")
        self.order_by_domain_checkbox.setChecked(False)
        self.order_by_domain_checkbox.setToolTip(
            "When enabled: Legend entries are sorted by domain\n"
            "When disabled: Legend entries are sorted by structure code"
        )
        self.order_by_domain_checkbox.stateChanged.connect(self.request_plot_update)
        alternate_mode_layout.addWidget(self.order_by_domain_checkbox)

        controls_layout.addWidget(alternate_mode_group)

        # Analysis tools - separate for planes and lines
        analysis_group = QGroupBox("Analysis Tools")
        analysis_layout = QVBoxLayout()
        analysis_layout.setContentsMargins(10, 15, 10, 10)
        analysis_layout.setSpacing(10)
        analysis_group.setLayout(analysis_layout)

        # Scope selection (All Combined vs Per Dataset)
        scope_layout = QHBoxLayout()
        scope_layout.setSpacing(10)
        scope_label = QLabel("Scope:")
        scope_label.setStyleSheet("font-weight: bold;")
        self.analysis_scope_combo = QComboBox()
        self.analysis_scope_combo.addItems(["All Combined", "Per Dataset", "Per Code"])
        self.analysis_scope_combo.setToolTip("All Combined: Pool data from all datasets\nPer Dataset: Separate analysis for each dataset\nPer Code: Separate analysis for each structure code")
        scope_layout.addWidget(scope_label)
        scope_layout.addWidget(self.analysis_scope_combo)
        scope_layout.addStretch()

        # Plane analysis
        plane_analysis_layout = QHBoxLayout()
        plane_analysis_layout.setSpacing(15)
        plane_label = QLabel("Planes:")
        plane_label.setStyleSheet("font-weight: bold;")
        self.best_fit_plane_checkbox = QCheckBox("Best Fit")
        self.contour_plane_checkbox = QCheckBox("Contours")
        self.mean_plane_checkbox = QCheckBox("Mean")
        self.mean_plane_type_combo = QComboBox()
        self.mean_plane_type_combo.addItems(["Pole", "Plane"])
        self.mean_plane_type_combo.setToolTip("Pole: Plot mean as pole point\nPlane: Plot mean as great circle")
        self.mean_plane_type_combo.setEnabled(False)
        self.mean_plane_type_combo.setMaximumWidth(70)
        plane_analysis_layout.addWidget(plane_label)
        plane_analysis_layout.addWidget(self.best_fit_plane_checkbox)
        plane_analysis_layout.addWidget(self.contour_plane_checkbox)
        plane_analysis_layout.addWidget(self.mean_plane_checkbox)
        plane_analysis_layout.addWidget(self.mean_plane_type_combo)
        plane_analysis_layout.addStretch()

        # Line analysis
        line_analysis_layout = QHBoxLayout()
        line_analysis_layout.setSpacing(15)
        line_label = QLabel("Lines:")
        line_label.setStyleSheet("font-weight: bold;")
        self.best_fit_line_checkbox = QCheckBox("Best Fit")
        self.contour_line_checkbox = QCheckBox("Contours")
        self.mean_line_checkbox = QCheckBox("Mean")
        line_analysis_layout.addWidget(line_label)
        line_analysis_layout.addWidget(self.best_fit_line_checkbox)
        line_analysis_layout.addWidget(self.contour_line_checkbox)
        line_analysis_layout.addWidget(self.mean_line_checkbox)
        line_analysis_layout.addStretch()

        # Rake checkbox
        rake_layout = QHBoxLayout()
        self.rake_checkbox = QCheckBox("Show Rakes")
        rake_layout.addWidget(self.rake_checkbox)
        rake_layout.addStretch()

        # Connect checkboxes and combos so that the plot updates when toggled
        # (debounced via request_plot_update so rapid toggles coalesce into one render)
        self.analysis_scope_combo.currentIndexChanged.connect(self.request_plot_update)
        self.best_fit_plane_checkbox.stateChanged.connect(self.request_plot_update)
        self.contour_plane_checkbox.stateChanged.connect(self.request_plot_update)
        self.mean_plane_checkbox.stateChanged.connect(self.request_plot_update)
        self.mean_plane_checkbox.stateChanged.connect(
            lambda state: self.mean_plane_type_combo.setEnabled(state == Qt.Checked)
        )
        self.mean_plane_type_combo.currentIndexChanged.connect(self.request_plot_update)
        self.best_fit_line_checkbox.stateChanged.connect(self.request_plot_update)
        self.contour_line_checkbox.stateChanged.connect(self.request_plot_update)
        self.mean_line_checkbox.stateChanged.connect(self.request_plot_update)
        self.rake_checkbox.stateChanged.connect(self.request_plot_update)

        analysis_layout.addLayout(scope_layout)
        analysis_layout.addLayout(plane_analysis_layout)
        analysis_layout.addLayout(line_analysis_layout)
        analysis_layout.addLayout(rake_layout)

        # Output actions
        output_group = QGroupBox("Output Actions")
        output_layout = QHBoxLayout()
        output_layout.setContentsMargins(10, 15, 10, 10)
        output_layout.setSpacing(15)
        output_group.setLayout(output_layout)

        self.copy_highres_button = QPushButton("Copy to Clipboard")
        self.save_svg_button = QPushButton("Save as SVG")
        self.generate_legend_button = QPushButton("Generate Legend")
        self.generate_legend_button.setToolTip(
            "Build a 'CODE = Description' text legend for everything in the "
            "current plot (descriptions from the code field's Value Relation "
            "lookup table)")
        self.transparent_svg_checkbox = QCheckBox("Transparent")
        self.transparent_svg_checkbox.setToolTip("Export without white background (applies to SVG and clipboard)")

        # Connect buttons to functions
        self.copy_highres_button.clicked.connect(self.copy_highres_to_clipboard)
        self.save_svg_button.clicked.connect(self.save_plot_as_svg)
        self.generate_legend_button.clicked.connect(self.generate_plot_legend)

        output_layout.addWidget(self.copy_highres_button)
        output_layout.addWidget(self.save_svg_button)
        output_layout.addWidget(self.generate_legend_button)
        output_layout.addWidget(self.transparent_svg_checkbox)
        output_layout.addStretch()

        # Add to controls
        controls_layout.addWidget(analysis_group)
        controls_layout.addWidget(output_group)

        # Main plot area: a live matplotlib canvas (points stay clickable —
        # pick events select the source features in QGIS) stacked with a
        # QLabel that remains the message surface for empty/info states
        self.plot_label = QLabel("Plot will appear here")
        self.plot_label.setAlignment(Qt.AlignCenter)
        self.plot_label.setMinimumHeight(400)  # Ensure enough space for plot
        self.plot_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.plot_figure = Figure(figsize=(7, 5), dpi=100)
        self.plot_canvas = FigureCanvasQTAgg(self.plot_figure)
        self.plot_canvas.setMinimumHeight(400)
        self.plot_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.plot_stack = QStackedWidget()
        self.plot_stack.addWidget(self.plot_label)   # page 0: messages
        self.plot_stack.addWidget(self.plot_canvas)  # page 1: live plot

        self.pick_handler = StereonetPickHandler(self)
        self.pick_handler.connect(self.plot_canvas)

        # Debounce timer for UI-driven replots: coalesces rapid checkbox/combo
        # toggles into a single full re-render
        self.plot_update_timer = QTimer(self.plot_widget)
        self.plot_update_timer.setSingleShot(True)
        self.plot_update_timer.setInterval(150)
        self.plot_update_timer.timeout.connect(self.update_plot)

        # Assemble layout
        layout.addWidget(controls_group)
        layout.addWidget(self.plot_stack, 1)


    def setup_categories_tab(self):
        main_layout = QVBoxLayout(self.categories_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)

        # --- Top Buttons ---
        top_buttons_layout = QHBoxLayout()
        top_buttons_layout.setSpacing(10)

        btn_refresh = QPushButton("Refresh Selection")
        font_refresh = QFont()
        font_refresh.setBold(True)
        btn_refresh.setFont(font_refresh)
        btn_refresh.setToolTip("Load the features currently selected in the dataset layers")
        btn_refresh.clicked.connect(self.manual_refresh)

        btn_refresh_all = QPushButton("Refresh with All")
        btn_refresh_all.setFont(font_refresh)
        btn_refresh_all.setToolTip("Load every feature from the enabled dataset layers (no selection needed)")
        btn_refresh_all.clicked.connect(self.manual_refresh_all)

        btn_plot = QPushButton("Plot")
        font_plot = QFont()
        font_plot.setBold(True)
        btn_plot.setFont(font_plot)
        btn_plot.clicked.connect(self.plot_and_swap)

        top_buttons_layout.addWidget(btn_refresh)
        top_buttons_layout.addWidget(btn_refresh_all)
        top_buttons_layout.addWidget(btn_plot)
        main_layout.addLayout(top_buttons_layout)
        # ---

        self.categories_tabwidget = QTabWidget()
        self.categories_tabwidget.setDocumentMode(True)

        # "Selection" sub-tab
        self.category_tree_selection = QTreeWidget()
        self._setup_category_tree_columns(self.category_tree_selection)
        self.category_tree_selection.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.category_tree_selection.setAlternatingRowColors(True)

        selection_widget = QWidget()
        sel_layout = QVBoxLayout(selection_widget)
        sel_layout.setContentsMargins(10, 10, 10, 10)
        sel_layout.setSpacing(10)

        # Button bar with selection controls
        selection_actions = QWidget()
        button_style = """
            QPushButton {
                padding: 5px 10px;
                font-size: 8pt;
                min-width: 0;
            }
        """
        selection_actions.setStyleSheet(button_style)
        action_layout = QHBoxLayout(selection_actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(5)

        btn_sel_all = QPushButton("Select All")
        btn_sel_all.clicked.connect(self.select_all_categories_selection)

        btn_sel_none = QPushButton("Deselect All")
        btn_sel_none.clicked.connect(self.deselect_all_categories_selection)

        btn_sel_high = QPushButton("Select Highlighted")
        btn_sel_high.clicked.connect(self.select_highlighted_categories_selection)

        btn_desel_high = QPushButton("Deselect Highlighted")
        btn_desel_high.clicked.connect(self.deselect_highlighted_categories_selection)

        action_layout.addWidget(btn_sel_all)
        action_layout.addWidget(btn_sel_none)
        action_layout.addWidget(btn_sel_high)
        action_layout.addWidget(btn_desel_high)

        sel_layout.addWidget(selection_actions)
        sel_layout.addWidget(self.category_tree_selection)

        self.categories_tabwidget.addTab(selection_widget, "Selection")

        # "Domains" sub-tab
        self.category_tree_domains = QTreeWidget()
        self._setup_category_tree_columns(self.category_tree_domains)
        self.category_tree_domains.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.category_tree_domains.setAlternatingRowColors(True)
        self.category_tree_domains.setSortingEnabled(True)  # Enable sorting
        self.category_tree_domains.sortByColumn(0, Qt.AscendingOrder)  # Default sort by first column

        domains_widget = QWidget()
        dom_layout = QVBoxLayout(domains_widget)
        dom_layout.setContentsMargins(10, 10, 10, 10)
        dom_layout.setSpacing(10)

        # Sorting buttons
        sort_actions = QWidget()
        sort_actions.setStyleSheet(button_style)
        sort_layout = QHBoxLayout(sort_actions)
        sort_layout.setContentsMargins(0, 0, 0, 0)
        sort_layout.setSpacing(5)

        sort_label = QLabel("Sort by:")
        btn_sort_code = QPushButton("Code")
        btn_sort_code.clicked.connect(lambda: self.sort_domains_tree("code"))

        btn_sort_domain = QPushButton("Domain")
        btn_sort_domain.clicked.connect(lambda: self.sort_domains_tree("domain"))

        btn_sort_dataset = QPushButton("Dataset")
        btn_sort_dataset.clicked.connect(lambda: self.sort_domains_tree("dataset"))

        sort_layout.addWidget(sort_label)
        sort_layout.addWidget(btn_sort_code)
        sort_layout.addWidget(btn_sort_domain)
        sort_layout.addWidget(btn_sort_dataset)
        sort_layout.addStretch()

        # Button bar with domain controls
        domain_actions = QWidget()
        domain_actions.setStyleSheet(button_style)
        dom_action_layout = QHBoxLayout(domain_actions)
        dom_action_layout.setContentsMargins(0, 0, 0, 0)
        dom_action_layout.setSpacing(5)

        btn_dom_all = QPushButton("Select All")
        btn_dom_all.clicked.connect(self.select_all_categories_domains)

        btn_dom_none = QPushButton("Deselect All")
        btn_dom_none.clicked.connect(self.deselect_all_categories_domains)

        btn_dom_sel_high = QPushButton("Select Highlighted")
        btn_dom_sel_high.clicked.connect(self.select_highlighted_categories_domains)

        btn_dom_desel_high = QPushButton("Deselect Highlighted")
        btn_dom_desel_high.clicked.connect(self.deselect_highlighted_categories_domains)

        dom_action_layout.addWidget(btn_dom_all)
        dom_action_layout.addWidget(btn_dom_none)
        dom_action_layout.addWidget(btn_dom_sel_high)
        dom_action_layout.addWidget(btn_dom_desel_high)

        dom_layout.addWidget(sort_actions)
        dom_layout.addWidget(domain_actions)
        dom_layout.addWidget(self.category_tree_domains)

        self.categories_tabwidget.addTab(domains_widget, "Domains")

        # NEW: "Live View" sub-tab
        self.category_tree_live_view = QTreeWidget()
        self._setup_category_tree_columns(self.category_tree_live_view)
        self.category_tree_live_view.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.category_tree_live_view.setAlternatingRowColors(True)

        live_view_widget = QWidget()
        live_layout = QVBoxLayout(live_view_widget)
        live_layout.setContentsMargins(10, 10, 10, 10)
        live_layout.setSpacing(10)

        # Button bar with live view controls
        live_view_actions = QWidget()
        live_view_actions.setStyleSheet(button_style)
        live_action_layout = QHBoxLayout(live_view_actions)
        live_action_layout.setContentsMargins(0, 0, 0, 0)
        live_action_layout.setSpacing(5)

        btn_live_all = QPushButton("Select All")
        btn_live_all.clicked.connect(self.select_all_categories_live_view)

        btn_live_none = QPushButton("Deselect All")
        btn_live_none.clicked.connect(self.deselect_all_categories_live_view)

        btn_live_sel_high = QPushButton("Select Highlighted")
        btn_live_sel_high.clicked.connect(self.select_highlighted_categories_live_view)

        btn_live_desel_high = QPushButton("Deselect Highlighted")
        btn_live_desel_high.clicked.connect(self.deselect_highlighted_categories_live_view)

        live_action_layout.addWidget(btn_live_all)
        live_action_layout.addWidget(btn_live_none)
        live_action_layout.addWidget(btn_live_sel_high)
        live_action_layout.addWidget(btn_live_desel_high)

        live_layout.addWidget(live_view_actions)
        live_layout.addWidget(self.category_tree_live_view)

        self.categories_tabwidget.addTab(live_view_widget, "Live View")

        main_layout.addWidget(self.categories_tabwidget)

    ########################################################################
    # Configuration Tab (New-Only)
    ########################################################################


    def setup_config_tab(self):
        """This is kept for backward compatibility only"""
        QgsMessageLog.logMessage("Configuration tab has been merged with Datasets tab", 'Linear Geoscience', Qgis.Info)
        pass


    def setup_coding_tab(self):
        """Set up the Coding tab with enhanced multi-dataset support and batch operations"""
        layout = QVBoxLayout(self.coding_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)

        # Title and description
        title_label = QLabel("Structure Code Classification")
        title_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: #2c3e50;")
        desc_label = QLabel("Classify unknown structure codes as Planar or Linear across all datasets.")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #7f8c8d; font-style: italic;")
        layout.addWidget(title_label)
        layout.addWidget(desc_label)
        layout.addSpacing(10)

        # Options area
        options_layout = QHBoxLayout()
        options_layout.setSpacing(10)

        # Option to show/hide known codes
        self.show_known_codes_checkbox = QCheckBox("Show Already Classified Codes")
        self.show_known_codes_checkbox.setChecked(False)
        self.show_known_codes_checkbox.stateChanged.connect(self.populate_coding_table)
        options_layout.addWidget(self.show_known_codes_checkbox)

        # Label to show count of displayed codes
        self.code_count_label = QLabel("No codes loaded")
        self.code_count_label.setStyleSheet("color: #7f8c8d;")
        options_layout.addWidget(self.code_count_label, alignment=Qt.AlignRight)

        layout.addLayout(options_layout)

        # Batch operation controls
        batch_group = QGroupBox("Batch Operations")
        batch_layout = QVBoxLayout(batch_group)
        batch_layout.setContentsMargins(10, 15, 10, 10)
        batch_layout.setSpacing(10)

        # Selection instructions
        instruction_label = QLabel("Use Ctrl+Click or Shift+Click to select multiple rows")
        instruction_label.setStyleSheet("color: #7f8c8d; font-style: italic;")
        batch_layout.addWidget(instruction_label)

        # Batch action buttons - use a grid for better layout
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)

        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.select_all_coding_codes)
        buttons_layout.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self.deselect_all_coding_codes)
        buttons_layout.addWidget(deselect_all_btn)

        set_planar_btn = QPushButton("Set Selected as Planar")
        set_planar_btn.setStyleSheet("background-color: #3498db;")
        set_planar_btn.clicked.connect(lambda: self.set_selected_classification("Planar"))
        buttons_layout.addWidget(set_planar_btn)

        set_linear_btn = QPushButton("Set Selected as Linear")
        set_linear_btn.setStyleSheet("background-color: #9b59b6;")
        set_linear_btn.clicked.connect(lambda: self.set_selected_classification("Linear"))
        buttons_layout.addWidget(set_linear_btn)

        batch_layout.addLayout(buttons_layout)
        layout.addWidget(batch_group)

        # Add separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet("background-color: #dee2e6; margin: 10px 0;")
        layout.addWidget(separator)

        # Create coding table
        self.coding_table = QTableWidget()
        self.coding_table.setColumnCount(4)  # Code, Dataset, Planar, Linear
        self.coding_table.setHorizontalHeaderLabels(["Code", "Dataset", "Planar", "Linear"])
        self.coding_table.setAlternatingRowColors(True)

        # Enable multiple selection
        self.coding_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.coding_table.setSelectionMode(QTableWidget.ExtendedSelection)

        # Set column widths
        self.coding_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)  # Code column stretches
        self.coding_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Dataset
        self.coding_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Planar
        self.coding_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Linear

        layout.addWidget(self.coding_table)

        # File handling group (CSV Import/Export)
        file_group = QgsCollapsibleGroupBox("CSV Import/Export")
        file_group.setFlat(True)
        file_layout = QVBoxLayout()
        file_layout.setContentsMargins(10, 15, 10, 10)
        file_layout.setSpacing(10)
        file_group.setLayout(file_layout)

        # Export section
        export_layout = QHBoxLayout()
        export_layout.setSpacing(10)

        self.export_file_widget = QgsFileWidget()
        self.export_file_widget.setFilter("CSV Files (*.csv)")
        self.export_file_widget.setStorageMode(QgsFileWidget.SaveFile)
        export_layout.addWidget(self.export_file_widget)

        export_btn = QPushButton("Export")
        export_btn.clicked.connect(self.export_coding_csv)
        export_layout.addWidget(export_btn)

        file_layout.addWidget(QLabel("Export Classifications:"))
        file_layout.addLayout(export_layout)

        # Import section
        import_layout = QHBoxLayout()
        import_layout.setSpacing(10)

        self.import_file_widget = QgsFileWidget()
        self.import_file_widget.setFilter("CSV Files (*.csv)")
        self.import_file_widget.setStorageMode(QgsFileWidget.GetFile)
        import_layout.addWidget(self.import_file_widget)

        import_btn = QPushButton("Import")
        import_btn.clicked.connect(self.import_coding_csv)
        import_layout.addWidget(import_btn)

        file_layout.addWidget(QLabel("Import Classifications:"))
        file_layout.addLayout(import_layout)

        layout.addWidget(file_group)

        # Buttons at bottom
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        refresh_btn = QPushButton("Refresh Codes")
        refresh_btn.clicked.connect(self.populate_coding_table)
        button_layout.addWidget(refresh_btn)

        button_layout.addStretch()

        apply_btn = QPushButton("Apply Changes")
        apply_btn.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold;")
        apply_btn.clicked.connect(self.apply_coding_changes)
        button_layout.addWidget(apply_btn)

        layout.addLayout(button_layout)


    def setup_colors_tab(self):
        """Set up the Colors tab UI for customizing structure colors"""
        layout = QVBoxLayout(self.colors_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
        
        # Header with reset button
        header_layout = QHBoxLayout()
        
        title = QLabel("Structure Color Configuration")
        title.setFont(QFont("Arial", 12, QFont.Bold))
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Reset to defaults button
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {WARNING_COLOR};
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #e67e22;
            }}
        """)
        reset_btn.clicked.connect(self.reset_colors_to_default)
        header_layout.addWidget(reset_btn)
        
        layout.addLayout(header_layout)
        
        # Instructions
        instructions = QLabel(
            "Click on any color button to customize the color for that structural geology code. "
            "Colors are preserved between sessions."
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet(f"color: {TEXT_COLOR}; margin-bottom: 10px;")
        layout.addWidget(instructions)
        
        # Create grouped color controls
        self.setup_color_groups(layout)
        
        layout.addStretch()


    def setup_color_groups(self, parent_layout):
        """Set up color control groups organized by structure type"""
        
        # Define structure groups with their codes and descriptions
        structure_groups = [
            ("Bedding & Layering", ["BO", "LAY", "S0", "S0T"], "#8B4513"),
            ("Foliations", ["S1", "S2", "S3", "S4", "S5"], "#708090"),
            ("Fractures", ["FB", "FCT", "FO", "FT", "FTD", "FTN", "FTR", "FTS", "FTT"], "#DC143C"),
            ("Fault Planes", ["FAP", "FAP1", "FAP2", "FAP3", "FAP4", "FAP5", "FAPK"], "#800080"),
            ("Fault Axes", ["FAX", "FAX1", "FAX2", "FAX3", "FAX4", "FAX5", "FAXCR", "FAXK", "FAXSZ"], "#8B008B"),
            ("Shear Zones", ["SZB", "SZC", "SZCD", "SZCN", "SZCR", "SZCS", "SZS"], "#2F4F4F"),
            ("Veins", ["VL", "VN", "VS", "VT", "VX"], "#00FF7F"),
            ("Contacts", ["CT"], "#FF8C00"),
            ("Linear Structures", ["BAX", "LME", "LNI", "LNISC", "LNS", "STR"], "#FF1493")
        ]
        
        for group_name, codes, group_color in structure_groups:
            # Create collapsible group box
            group_box = QgsCollapsibleGroupBox(group_name)
            group_box.setFlat(True)
            group_layout = QVBoxLayout()
            group_layout.setContentsMargins(15, 10, 15, 10)
            group_layout.setSpacing(8)
            
            # Add color controls for each code in the group
            for code in codes:
                if code in self.structure_colors:  # Only show codes that exist in our dictionary
                    color_layout = QHBoxLayout()
                    
                    # Code label
                    code_label = QLabel(code)
                    code_label.setMinimumWidth(50)
                    code_label.setFont(QFont("Courier", 10, QFont.Bold))
                    color_layout.addWidget(code_label)
                    
                    # Structure type indicator
                    struct_type = "Planar" if code in self.planar_codes else "Linear" if code in self.linear_codes else "Unknown"
                    type_label = QLabel(f"({struct_type})")
                    type_label.setStyleSheet("color: #7f8c8d; font-size: 9px;")
                    type_label.setMinimumWidth(60)
                    color_layout.addWidget(type_label)
                    
                    color_layout.addStretch()
                    
                    # Color button
                    color_btn = QPushButton()
                    color_btn.setFixedSize(40, 25)
                    color_btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {self.structure_colors[code]};
                            border: 2px solid #bdc3c7;
                            border-radius: 4px;
                        }}
                        QPushButton:hover {{
                            border: 2px solid {PRIMARY_COLOR};
                        }}
                    """)
                    color_btn.clicked.connect(lambda checked, c=code: self.choose_color_for_code(c))
                    
                    # Store reference to update button later
                    self.color_buttons[code] = color_btn
                    
                    color_layout.addWidget(color_btn)
                    group_layout.addLayout(color_layout)
            
            group_box.setLayout(group_layout)
            parent_layout.addWidget(group_box)

        # User-defined code groups get their own colour rows
        groups_box = QgsCollapsibleGroupBox("Code Groups")
        groups_box.setFlat(True)
        self.group_colors_layout = QVBoxLayout()
        self.group_colors_layout.setContentsMargins(15, 10, 15, 10)
        self.group_colors_layout.setSpacing(8)
        groups_box.setLayout(self.group_colors_layout)
        parent_layout.addWidget(groups_box)
        self._refresh_group_color_section()


    def _refresh_group_color_section(self):
        """Rebuild the 'Code Groups' colour rows in the Colors tab."""
        layout = self.group_colors_layout
        if layout is None:
            return
        # Drop stale button references (group rows are the only custom ones),
        # then clear existing rows
        for name in list(self.color_buttons.keys()):
            if name not in DEFAULT_STRUCTURE_COLORS:
                self.color_buttons.pop(name, None)
        while layout.count():
            entry = layout.takeAt(0)
            w = entry.widget()
            if w is not None:
                w.deleteLater()
            elif entry.layout() is not None:
                sub = entry.layout()
                while sub.count():
                    sw = sub.takeAt(0).widget()
                    if sw is not None:
                        sw.deleteLater()

        if not self.code_groups:
            hint = QLabel("No code groups defined. Right-click codes in a "
                          "category tree to group them.")
            hint.setStyleSheet("color: #7f8c8d; font-size: 9px;")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            return

        for group_name, members in self.code_groups.items():
            color_layout = QHBoxLayout()

            name_label = QLabel(group_name)
            name_label.setMinimumWidth(50)
            name_label.setFont(QFont("Courier", 10, QFont.Bold))
            color_layout.addWidget(name_label)

            members_label = QLabel("(" + ", ".join(members) + ")")
            members_label.setStyleSheet("color: #7f8c8d; font-size: 9px;")
            color_layout.addWidget(members_label)

            color_layout.addStretch()

            color_btn = QPushButton()
            color_btn.setFixedSize(40, 25)
            color_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self.structure_colors.get(group_name, '#808080')};
                    border: 2px solid #bdc3c7;
                    border-radius: 4px;
                }}
                QPushButton:hover {{
                    border: 2px solid {PRIMARY_COLOR};
                }}
            """)
            color_btn.clicked.connect(lambda checked, c=group_name: self.choose_color_for_code(c))
            self.color_buttons[group_name] = color_btn

            color_layout.addWidget(color_btn)
            layout.addLayout(color_layout)


    def choose_color_for_code(self, code):
        """Open color dialog to choose color for a specific structure code"""
        current_color = self.structure_colors.get(code, "#000000")
        
        color = QColorDialog.getColor(
            QColor(current_color),
            self.colors_widget,
            f"Choose color for {code}"
        )
        
        if color.isValid():
            color_hex = color.name()
            self.structure_colors[code] = color_hex
            
            # Update the button color
            if code in self.color_buttons:
                self.color_buttons[code].setStyleSheet(f"""
                    QPushButton {{
                        background-color: {color_hex};
                        border: 2px solid #bdc3c7;
                        border-radius: 4px;
                    }}
                    QPushButton:hover {{
                        border: 2px solid {PRIMARY_COLOR};
                    }}
                """)
            
            QgsMessageLog.logMessage(f"Updated color for {code} to {color_hex}", 'Linear Geoscience', Qgis.Info)
            
            # Save colors to settings
            self.save_structure_colors()


    def reset_colors_to_default(self):
        """Reset all structure colors to their default values"""
        reply = QMessageBox.question(
            self.colors_widget,
            "Reset Colors",
            "Are you sure you want to reset all colors to their default values?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.structure_colors = DEFAULT_STRUCTURE_COLORS.copy()

            # Re-seed code-group colours so groups aren't orphaned by the reset
            for group_name, members in self.code_groups.items():
                seed = next((self.structure_colors[c] for c in members
                             if c in self.structure_colors), "#808080")
                self.structure_colors[group_name] = seed

            # Update all color buttons
            for code, button in self.color_buttons.items():
                color = self.structure_colors.get(code, "#000000")
                button.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {color};
                        border: 2px solid #bdc3c7;
                        border-radius: 4px;
                    }}
                    QPushButton:hover {{
                        border: 2px solid {PRIMARY_COLOR};
                    }}
                """)
            
            QgsMessageLog.logMessage("All colors reset to defaults", 'Linear Geoscience', Qgis.Info)
            
            # Save the reset colors to settings
            self.save_structure_colors()


    def save_structure_colors(self):
        """Save current structure colors to QGIS settings"""
        settings = QgsSettings()
        settings.beginGroup("LinearGeosciencePlugin/StructureColors")
        
        for code, color in self.structure_colors.items():
            settings.setValue(code, color)
        
        settings.endGroup()
        QgsMessageLog.logMessage("Structure colors saved to settings", 'Linear Geoscience', Qgis.Info)


    def load_structure_colors(self):
        """Load structure colors from QGIS settings"""
        settings = QgsSettings()
        settings.beginGroup("LinearGeosciencePlugin/StructureColors")
        
        # Load saved colors, fallback to defaults if not found
        for code in DEFAULT_STRUCTURE_COLORS.keys():
            saved_color = settings.value(code, DEFAULT_STRUCTURE_COLORS[code])
            self.structure_colors[code] = saved_color

        # Also load custom keys (e.g. code-group colours) not in the defaults
        for key in settings.childKeys():
            if key not in self.structure_colors:
                self.structure_colors[key] = settings.value(key)

        settings.endGroup()
        QgsMessageLog.logMessage("Structure colors loaded from settings", 'Linear Geoscience', Qgis.Info)


    # =========================================================================
    # CODE GROUPS (merge several codes into one plotted category)
    # =========================================================================

    def save_code_groups(self):
        """Save code group definitions to QGIS settings"""
        settings = QgsSettings()
        settings.beginGroup("LinearGeosciencePlugin/CodeGroups")
        settings.setValue("groups", json.dumps(self.code_groups))
        settings.endGroup()
        QgsMessageLog.logMessage("Code groups saved to settings", 'Linear Geoscience', Qgis.Info)


    def load_code_groups(self):
        """Load code group definitions from QGIS settings"""
        settings = QgsSettings()
        settings.beginGroup("LinearGeosciencePlugin/CodeGroups")
        raw = settings.value("groups", "{}")
        settings.endGroup()
        try:
            groups = json.loads(raw)
            if isinstance(groups, dict):
                self.code_groups = {
                    str(name): [str(c) for c in codes]
                    for name, codes in groups.items()
                    if isinstance(codes, list)
                }
            else:
                self.code_groups = {}
        except (TypeError, ValueError):
            self.code_groups = {}


    def get_group_for_code(self, code):
        """Return the group name containing this base code, or None."""
        for group_name, codes in self.code_groups.items():
            if code in codes:
                return group_name
        return None


    def _partition_codes_by_group(self, codes):
        """Split an iterable of base codes into grouped and ungrouped sets.

        Returns (grouped, ungrouped) where grouped is an OrderedDict-like
        {group_name: [present member codes]} in code_groups insertion order
        and ungrouped is a list preserving the incoming order.
        """
        grouped = {}
        ungrouped = []
        code_list = list(codes)
        for group_name, members in self.code_groups.items():
            present = [c for c in code_list if c in members]
            if present:
                grouped[group_name] = present
        in_any_group = {c for present in grouped.values() for c in present}
        for c in code_list:
            if c not in in_any_group:
                ungrouped.append(c)
        return grouped, ungrouped


    def _group_state_key(self, display_key, dataset_idx):
        """Analysis-state dict key for a group parent item. The NUL sentinel
        guarantees no collision with real structure codes."""
        return ("\x00group\x00" + display_key, dataset_idx)


    def _make_group_parent_item(self, tree, user_data, label, struct_type,
                                saved_analysis=None, saved_plot_mode=None):
        """Create a top-level group parent item on a category tree.

        The parent owns the column-0 checkbox (auto-tristate from children),
        the plot-mode combo (planes) and the BF/Ct/Mn analysis toggles.
        """
        item = QTreeWidgetItem(tree)
        item.setText(0, label)
        # NOTE: deliberately NOT Qt.ItemIsAutoTristate — with that flag an
        # item with children derives its check state from the children in
        # EVERY column, and group children carry no BF/Ct/Mn states, so the
        # parent's analysis toggles would always read Unchecked. The
        # parent<->child column-0 sync is done manually in
        # _on_category_tree_item_changed instead.
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable
                      | Qt.ItemIsEnabled)
        item.setCheckState(0, Qt.Unchecked)
        item.setData(0, Qt.UserRole, user_data)
        saved = None
        if saved_analysis is not None:
            saved = saved_analysis.get(
                self._group_state_key(user_data["display"], user_data["dataset_idx"]))
        self._init_item_analysis_columns(item, saved)

        if struct_type == "plane":
            combo = QComboBox()
            combo.addItem("Poles Only")
            combo.addItem("Planes Only")
            combo.addItem("Both")
            if saved_plot_mode:
                idx = combo.findText(saved_plot_mode)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            tree.setItemWidget(item, COL_PLOT_MODE, combo)
        else:
            tree.setItemWidget(item, COL_PLOT_MODE, QLabel("(Line)"))
        return item


    def _add_group_child_item(self, parent_item, label, user_data, checked=Qt.Unchecked):
        """Create a member-code child under a group parent. Children carry the
        legacy tuple UserRole, only a name checkbox (no analysis columns, no
        plot-mode widget)."""
        child = QTreeWidgetItem(parent_item)
        child.setText(0, label)
        child.setFlags(child.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable
                       | Qt.ItemIsEnabled)
        child.setData(0, Qt.UserRole, user_data)
        child.setCheckState(0, checked)
        return child


    @staticmethod
    def _base_code_from_item_data(data):
        """Extract the base structure code from a category tree item's
        UserRole tuple (any of the three trees, either mode)."""
        if not isinstance(data, tuple) or not data:
            return None
        if len(data) >= 5:
            # Domains tree: (st, dataset_idx, code, domain, dataset_name)
            return data[2] if data[2] else data[0]
        code_str = data[0]
        # Live-view domain mode keys look like "CODE - DOMAIN (Dataset)"
        if isinstance(code_str, str) and " - " in code_str:
            return code_str.split(" - ")[0]
        return code_str


    def _classify_base_code(self, code):
        """Best-effort plane/line classification for a base code: the static
        code tables first, then whatever the current category maps say."""
        struct_type = classify_code(code)
        if struct_type:
            return struct_type
        for ds in range(2):
            struct_type = (self.category_structure_map_selection[ds].get(code)
                           or self.category_structure_map_live_view[ds].get(code))
            if struct_type:
                return struct_type
            for st, typ in self.category_structure_map_domains[ds].items():
                base = st.split(" - ")[0] if " - " in st else st
                if base == code:
                    return typ
        return None


    def _show_category_tree_menu(self, tree, pos):
        """Right-click menu on a category tree: create/modify code groups."""
        clicked = tree.itemAt(pos)
        menu = QMenu(tree)

        # Codes eligible for grouping from the current selection (flat items
        # and group children; group parents are excluded)
        selected_codes = []
        for sel in tree.selectedItems():
            code = self._base_code_from_item_data(sel.data(0, Qt.UserRole))
            if code and code not in selected_codes:
                selected_codes.append(code)

        if selected_codes:
            label = (f"Group {len(selected_codes)} selected codes..."
                     if len(selected_codes) > 1
                     else f"Group '{selected_codes[0]}'...")
            menu.addAction(label, lambda: self._create_group_from_codes(tree, selected_codes))

        if clicked is not None:
            cdata = clicked.data(0, Qt.UserRole)
            if isinstance(cdata, dict) and cdata.get("is_group"):
                group_name = cdata["group"]
                if not menu.isEmpty():
                    menu.addSeparator()
                menu.addAction(f"Rename group '{group_name}'...",
                               lambda: self._rename_group(group_name))
                menu.addAction(f"Ungroup '{group_name}'",
                               lambda: self._ungroup(group_name))
            else:
                parent = clicked.parent()
                pdata = parent.data(0, Qt.UserRole) if parent is not None else None
                if isinstance(pdata, dict) and pdata.get("is_group"):
                    code = self._base_code_from_item_data(cdata)
                    if code:
                        if not menu.isEmpty():
                            menu.addSeparator()
                        menu.addAction(
                            f"Remove '{code}' from group '{pdata['group']}'",
                            lambda: self._remove_code_from_group(code))

        if not menu.isEmpty():
            menu.exec(tree.viewport().mapToGlobal(pos))


    def _create_group_from_codes(self, tree, codes):
        """Validate and create (or extend) a code group from base codes."""
        name, ok = QInputDialog.getText(
            tree, "Group Codes",
            "Group name for: " + ", ".join(codes))
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if " - " in name:
            QMessageBox.warning(tree, "Group Codes",
                                "Group names cannot contain ' - ' (reserved for "
                                "domain categories).")
            return

        adding_to_existing = name in self.code_groups

        # Block names that collide with real structure codes — they would
        # corrupt the colour map and per-code analysis keys
        if not adding_to_existing:
            # _classify_base_code scans the static tables plus all three
            # category maps (incl. domains), so any real code is caught
            collides = (name in DEFAULT_STRUCTURE_COLORS
                        or self._classify_base_code(name) is not None)
            if collides:
                QMessageBox.warning(tree, "Group Codes",
                                    f"'{name}' is an existing structure code. "
                                    "Choose a different group name.")
                return

        # All members (new + existing when extending) must share one
        # structure type: merged data plots as a single plane or line series
        all_members = list(codes)
        if adding_to_existing:
            all_members += [c for c in self.code_groups[name] if c not in all_members]
        types = {c: self._classify_base_code(c) for c in all_members}
        distinct = {t for t in types.values() if t is not None}
        if len(distinct) > 1:
            detail = ", ".join(f"{c}: {t or 'unknown'}" for c, t in types.items())
            QMessageBox.warning(tree, "Group Codes",
                                "Cannot mix planar and linear codes in one group.\n"
                                f"({detail})")
            return

        # A code belongs to at most one group: moving codes out may empty
        # other groups, which are then removed
        for code in codes:
            old_group = self.get_group_for_code(code)
            if old_group and old_group != name:
                self.code_groups[old_group].remove(code)
                QgsMessageLog.logMessage(
                    f"Moved '{code}' from group '{old_group}' to '{name}'",
                    'Linear Geoscience', Qgis.Info)
                if not self.code_groups[old_group]:
                    self._drop_group_entry(old_group)

        if adding_to_existing:
            self.code_groups[name] += [c for c in codes if c not in self.code_groups[name]]
        else:
            self.code_groups[name] = list(codes)

        # Seed the group colour from its first member so the plot doesn't
        # change colour scheme unexpectedly
        seed = next((self.structure_colors[c] for c in self.code_groups[name]
                     if c in self.structure_colors), "#808080")
        self.structure_colors.setdefault(name, seed)
        self.save_structure_colors()

        self._refresh_after_group_change()


    def _rename_group(self, group_name):
        if group_name not in self.code_groups:
            return
        tree = self.category_tree_selection
        name, ok = QInputDialog.getText(
            tree, "Rename Group", f"New name for group '{group_name}':",
            text=group_name)
        if not ok:
            return
        name = name.strip()
        if not name or name == group_name:
            return
        if " - " in name or name in self.code_groups or name in DEFAULT_STRUCTURE_COLORS \
                or self._classify_base_code(name) is not None:
            QMessageBox.warning(tree, "Rename Group",
                                f"'{name}' is not a valid group name (already in "
                                "use or reserved).")
            return

        self.code_groups = {name if k == group_name else k: v
                            for k, v in self.code_groups.items()}
        if group_name in self.structure_colors:
            self.structure_colors[name] = self.structure_colors.pop(group_name)
            self._remove_color_setting(group_name)
            self.save_structure_colors()
        self._refresh_after_group_change()


    def _ungroup(self, group_name):
        if group_name not in self.code_groups:
            return
        self._drop_group_entry(group_name)
        self._refresh_after_group_change()


    def _remove_code_from_group(self, code):
        group_name = self.get_group_for_code(code)
        if not group_name:
            return
        self.code_groups[group_name].remove(code)
        if not self.code_groups[group_name]:
            self._drop_group_entry(group_name)
        self._refresh_after_group_change()


    def _drop_group_entry(self, group_name):
        """Delete a group definition and its colour (memory + settings)."""
        self.code_groups.pop(group_name, None)
        if group_name not in DEFAULT_STRUCTURE_COLORS:
            self.structure_colors.pop(group_name, None)
            self._remove_color_setting(group_name)


    def _remove_color_setting(self, key):
        settings = QgsSettings()
        settings.beginGroup("LinearGeosciencePlugin/StructureColors")
        settings.remove(key)
        settings.endGroup()


    def _refresh_after_group_change(self):
        """Persist group definitions and rebuild every UI surface that shows
        categories, then replot."""
        self.save_code_groups()
        self.rebuild_category_tree_selection()
        self.rebuild_category_tree_domains()
        if self.live_view_enabled:
            if (getattr(self, 'live_view_by_domain_checkbox', None) is not None
                    and self.live_view_by_domain_checkbox.isChecked()):
                self.rebuild_category_tree_live_view_domains()
            else:
                # The rebuild empties the live-view data dicts; refill them
                # from the current map extent
                self.rebuild_category_tree_live_view()
                self.update_live_view_data()
        self._refresh_group_color_section()
        self.request_plot_update()


    def get_color_for_code(self, code):
        """
        Get the color for a specific structure code.
        
        Args:
            code (str): Structure code (e.g., 'S1', 'FAX', etc.)
            
        Returns:
            str: Hex color code
        """
        # Remove domain info if present
        base_code = code
        if " - " in base_code:
            base_code = base_code.split(" - ")[0]
        
        return self.structure_colors.get(base_code, "#000000")


    def setup_export_tab(self):
        """Set up the Export tab UI"""
        layout = QVBoxLayout(self.export_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)

        # Output folder selection
        output_group = QgsCollapsibleGroupBox("Export Settings")
        output_group.setFlat(True)
        output_layout = QVBoxLayout()
        output_layout.setContentsMargins(10, 15, 10, 10)
        output_layout.setSpacing(10)
        output_group.setLayout(output_layout)

        self.export_dir_widget = QgsFileWidget()
        self.export_dir_widget.setStorageMode(QgsFileWidget.GetDirectory)
        output_layout.addWidget(QLabel("Output Directory:"))
        output_layout.addWidget(self.export_dir_widget)

        # File prefix/naming
        self.export_prefix = QLineEdit()
        self.export_prefix.setText("stereonet_export")
        output_layout.addWidget(QLabel("File Prefix:"))
        output_layout.addWidget(self.export_prefix)

        # Filter options
        filter_group = QgsCollapsibleGroupBox("Filter Options")
        filter_group.setFlat(True)
        filter_layout = QVBoxLayout()
        filter_layout.setContentsMargins(10, 15, 10, 10)
        filter_layout.setSpacing(10)
        filter_group.setLayout(filter_layout)

        # Structure type filter
        filter_layout.addWidget(QLabel("Select structure types to include:"))
        self.export_structure_tree = QTreeWidget()
        self.export_structure_tree.setHeaderLabels(["Structure Type", "Type"])
        self.export_structure_tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.export_structure_tree.setAlternatingRowColors(True)
        filter_layout.addWidget(self.export_structure_tree)

        # Filter buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_select_all = QPushButton("Select All")
        btn_select_all.clicked.connect(self.select_all_export)

        btn_deselect_all = QPushButton("Deselect All")
        btn_deselect_all.clicked.connect(self.deselect_all_export)

        btn_layout.addWidget(btn_select_all)
        btn_layout.addWidget(btn_deselect_all)
        btn_layout.addStretch()
        filter_layout.addLayout(btn_layout)

        # Additional filter options
        filter_options_group = QGroupBox("Data Filters")
        filter_options_layout = QVBoxLayout()
        filter_options_layout.setContentsMargins(10, 15, 10, 10)
        filter_options_layout.setSpacing(10)
        filter_options_group.setLayout(filter_options_layout)

        # Min/Max dip
        dip_filter_layout = QHBoxLayout()
        dip_filter_layout.setSpacing(10)

        self.min_dip_filter = QLineEdit()
        self.min_dip_filter.setPlaceholderText("Min")
        self.min_dip_filter.setMaximumWidth(80)

        self.max_dip_filter = QLineEdit()
        self.max_dip_filter.setPlaceholderText("Max")
        self.max_dip_filter.setMaximumWidth(80)

        dip_filter_layout.addWidget(QLabel("Dip/Plunge Range:"))
        dip_filter_layout.addWidget(self.min_dip_filter)
        dip_filter_layout.addWidget(QLabel("to"))
        dip_filter_layout.addWidget(self.max_dip_filter)
        dip_filter_layout.addStretch()
        filter_options_layout.addLayout(dip_filter_layout)

        # Domain filter checkbox
        self.filter_by_domain_checkbox = QCheckBox("Filter by Structural Domain")
        self.filter_by_domain_checkbox.stateChanged.connect(self.toggle_domain_filter)
        filter_options_layout.addWidget(self.filter_by_domain_checkbox)

        # Domain combobox (starts hidden)
        self.domain_filter_combo = QComboBox()
        self.domain_filter_combo.setVisible(False)
        filter_options_layout.addWidget(self.domain_filter_combo)

        filter_layout.addWidget(filter_options_group)

        # Format options
        format_group = QGroupBox("Format Options")
        format_layout = QVBoxLayout()
        format_layout.setContentsMargins(10, 15, 10, 10)
        format_layout.setSpacing(10)
        format_group.setLayout(format_layout)

        # Export format selector. The format-specific options below live in
        # their own container widgets, which also keeps each radio pair in
        # its own exclusive group.
        export_format_label = QLabel("Export Format:")
        export_format_label.setStyleSheet("font-weight: bold;")
        format_layout.addWidget(export_format_label)

        self.format_stereonet11_radio = QRadioButton("Stereonet 11 (tab-separated)")
        self.format_leapfrog_radio = QRadioButton("Leapfrog CSV")
        self.format_stereonet11_radio.setChecked(True)
        self.format_stereonet11_radio.toggled.connect(self._on_export_format_changed)
        format_layout.addWidget(self.format_stereonet11_radio)
        format_layout.addWidget(self.format_leapfrog_radio)

        # --- Stereonet 11 specific options ---
        self.stereonet11_options_widget = QWidget()
        sn11_layout = QVBoxLayout(self.stereonet11_options_widget)
        sn11_layout.setContentsMargins(0, 5, 0, 0)
        sn11_layout.setSpacing(10)

        # Separate files option
        self.separate_files_checkbox = QCheckBox("Create separate file for each structure type")
        self.separate_files_checkbox.setChecked(True)
        sn11_layout.addWidget(self.separate_files_checkbox)

        # Include headers
        self.include_headers_checkbox = QCheckBox("Include column headers")
        self.include_headers_checkbox.setChecked(True)
        sn11_layout.addWidget(self.include_headers_checkbox)

        self.format_label = QLabel("Orientation Convention:")
        self.format_label.setStyleSheet("font-weight: bold;")
        sn11_layout.addWidget(self.format_label)

        self.format_dipdir_radio = QRadioButton("Dip Direction / Dip (planes) or Trend / Plunge (lines)")
        self.format_strike_radio = QRadioButton("Strike / Dip (RHR convention)")
        self.format_dipdir_radio.setChecked(True)  # Default format
        sn11_layout.addWidget(self.format_dipdir_radio)
        sn11_layout.addWidget(self.format_strike_radio)

        format_layout.addWidget(self.stereonet11_options_widget)

        # --- Leapfrog specific options ---
        self.leapfrog_options_widget = QWidget()
        leapfrog_layout = QVBoxLayout(self.leapfrog_options_widget)
        leapfrog_layout.setContentsMargins(0, 5, 0, 0)
        leapfrog_layout.setSpacing(10)

        self.leapfrog_group_col_checkbox = QCheckBox("Add grouped code column (CodeGroup)")
        self.leapfrog_group_col_checkbox.setChecked(True)
        self.leapfrog_group_col_checkbox.setToolTip(
            "Adds a CodeGroup column: codes in a code group get the group "
            "name, all other codes repeat their own code")
        leapfrog_layout.addWidget(self.leapfrog_group_col_checkbox)

        core_cols_note = QLabel(
            "East / North / Elevation, orientation and Code columns come from "
            "the Datasets field configuration and are always exported.")
        core_cols_note.setWordWrap(True)
        core_cols_note.setStyleSheet("color: #7f8c8d; font-size: 10px;")
        leapfrog_layout.addWidget(core_cols_note)

        leapfrog_layout.addWidget(QLabel("Additional columns:"))
        self.leapfrog_fields_list = QListWidget()
        self.leapfrog_fields_list.setMaximumHeight(140)
        self.leapfrog_fields_list.setAlternatingRowColors(True)
        leapfrog_layout.addWidget(self.leapfrog_fields_list)

        self.leapfrog_options_widget.setVisible(False)
        format_layout.addWidget(self.leapfrog_options_widget)

        # Add to main layout
        layout.addWidget(output_group)
        layout.addWidget(filter_group)
        layout.addWidget(format_group)

        # Refresh and export buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        self.refresh_export_button = QPushButton("Refresh Available Data")
        self.refresh_export_button.clicked.connect(self.refresh_export_data)

        self.export_button = QPushButton("Export Files")
        self.export_button.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold;")
        self.export_button.clicked.connect(self.run_export)

        button_layout.addWidget(self.refresh_export_button)
        button_layout.addWidget(self.export_button)
        layout.addLayout(button_layout)

        # Help text
        self.export_help_label = QLabel(
            "Stereonet 11 format: One measurement per line, tab-separated values")
        self.export_help_label.setWordWrap(True)
        self.export_help_label.setStyleSheet("color: #7f8c8d; font-style: italic; padding: 5px;")
        layout.addWidget(self.export_help_label)

        # Initialize the structure tree
        self.refresh_export_data()


    def _on_export_format_changed(self):
        """Show the option set for the selected export format."""
        is_leapfrog = self.format_leapfrog_radio.isChecked()
        self.stereonet11_options_widget.setVisible(not is_leapfrog)
        self.leapfrog_options_widget.setVisible(is_leapfrog)
        if is_leapfrog:
            self.export_help_label.setText(
                "Leapfrog format: two CSV files — planar structures "
                "(East,North,Elevation,Dip,DipDirection,Code,...) and "
                "lineations (East,North,Elevation,Plunge,Trend,Code,...)")
            self._populate_leapfrog_fields()
        else:
            self.export_help_label.setText(
                "Stereonet 11 format: One measurement per line, tab-separated values")


    def run_export(self):
        """Dispatch the Export button to the selected format."""
        if self.format_leapfrog_radio.isChecked():
            self.export_leapfrog()
        else:
            self.export_stereonet11()


    def setup_live_view_monitoring(self):
        """Set up monitoring based on the selected live view mode"""
        if not self.live_view_enabled:
            return

        # Clean up existing monitoring first
        self.cleanup_live_view_monitoring()

        if self.live_view_by_extent_checkbox.isChecked():
            # Set up map canvas extent change monitoring
            self.setup_map_canvas_monitoring()
            QgsMessageLog.logMessage("Live View monitoring: Map extent changes", 'Linear Geoscience', Qgis.Info)

        elif self.live_view_by_selection_checkbox.isChecked():
            # Set up selection change monitoring for all enabled datasets
            for dataset_idx in range(2):
                if self.dataset_configs[dataset_idx]["enabled"]:
                    layer = self.get_layer(dataset_idx)
                    if layer:
                        try:
                            layer.selectionChanged.connect(self.on_selection_changed)
                            self._selection_signal_layers.append(layer)
                            QgsMessageLog.logMessage(f"Live View monitoring: Selection changes for dataset {dataset_idx + 1}", 'Linear Geoscience', Qgis.Info)
                        except Exception:
                            QgsMessageLog.logMessage(f"Warning: Could not connect to selection changes for dataset {dataset_idx + 1}", 'Linear Geoscience', Qgis.Warning)


    def setup_map_canvas_monitoring(self):
        """Set up map canvas extent change monitoring with smart delay"""
        if not self.map_canvas:
            return

        # Connect to map canvas extent change signal
        # (extent_change_timer.timeout is connected once in __init__)
        try:
            self.map_canvas.extentsChanged.connect(self.on_map_extent_changed)
        except Exception:
            pass  # Might already be connected


    # =========================================================================
    # DATA PROCESSING METHODS
    # =========================================================================

    def refresh_layer_combo(self, dataset_idx):
        """Refresh the layer combo when layers are added or removed"""
        combo = self.dataset_configs[dataset_idx]["layer_combo"]
        if not combo:
            return

        # Remember current selection
        current_text = combo.currentText()

        # Block signals to prevent multiple field refreshes
        combo.blockSignals(True)

        # Clear and repopulate
        combo.clear()

        # Add an empty option first
        combo.addItem("")

        # Get all vector layers
        layers = []
        for layer in QgsProject.instance().mapLayers().values():
            if hasattr(layer, 'geometryType'):
                layers.append(layer)

        # Dictionary to store layers by display name
        if not hasattr(self, 'layer_maps'):
            self.layer_maps = [{}, {}]

        # Clear the map for this dataset
        self.layer_maps[dataset_idx] = {}

        # Add each layer with its source
        for layer in layers:
            try:
                source = layer.source()
                import os
                if '|' in source:
                    base_path = source.split('|')[0]
                else:
                    base_path = source
                filename = os.path.basename(base_path)
                if len(filename) > 30:
                    filename = filename[:17] + "..."
                display_name = f"{layer.name()} [{filename}]"

                # Make sure display name is unique
                counter = 1
                original_display_name = display_name
                while display_name in self.layer_maps[dataset_idx]:
                    display_name = f"{original_display_name} ({counter})"
                    counter += 1
            except Exception:
                display_name = layer.name()

                # Ensure unique display name
                counter = 1
                original_display_name = display_name
                while display_name in self.layer_maps[dataset_idx]:
                    display_name = f"{original_display_name} ({counter})"
                    counter += 1

            # Add to combo and store in map
            combo.addItem(display_name)
            self.layer_maps[dataset_idx][display_name] = layer

        # Try to restore previous selection if it still exists
        index = combo.findText(current_text)
        if index >= 0:
            combo.setCurrentIndex(index)

        # Re-enable signals
        combo.blockSignals(False)

        # Force a field refresh if a layer is selected
        if combo.currentText():
            self.handle_layer_selection(combo.currentText(), dataset_idx)


    def field_detect(self, dataset_idx, layer):
        """Handle layer changes and auto-detect fields - improved version"""
        if not layer:
            QgsMessageLog.logMessage(f"Dataset {dataset_idx + 1}: No layer selected", 'Linear Geoscience', Qgis.Info)
            return

        QgsMessageLog.logMessage(f"Dataset {dataset_idx + 1}: Layer changed to '{layer.name()}'", 'Linear Geoscience', Qgis.Info)

        # Skip the all-or-nothing check and try to directly update the field combos
        # Even if combos exist but aren't fully initialized, this will attempt to populate them
        self.direct_update_fields(dataset_idx, layer)


    def populate_field_combo_boxes(self, dataset_idx, layer=None):
        """Populate the field combo boxes for a specific dataset, including coordinates."""
        QgsMessageLog.logMessage(f"Attempting to populate fields for dataset {dataset_idx + 1}", 'Linear Geoscience', Qgis.Info)

        # Get combo boxes references from config
        config = self.dataset_configs[dataset_idx]
        dip_combo = config.get("dip_combo")
        dipdir_combo = config.get("dipdir_combo")
        subtype_combo = config.get("subtype_combo")
        easting_combo = config.get("easting_combo")
        northing_combo = config.get("northing_combo")
        domain_combo = config.get("domain_combo")  # New domain combo

        all_combos = [dip_combo, dipdir_combo, subtype_combo, easting_combo, northing_combo, domain_combo]

        # Check that combo box widgets exist
        if not all(combo is not None for combo in all_combos):
            QgsMessageLog.logMessage(f"Error: One or more QComboBox widgets for dataset {dataset_idx + 1} were not created correctly.", 'Linear Geoscience', Qgis.Warning)
            return

        # Clear all combo boxes safely
        QgsMessageLog.logMessage(f"Clearing existing items for dataset {dataset_idx + 1} combos...", 'Linear Geoscience', Qgis.Info)
        for combo in all_combos:
            combo.blockSignals(True)
            combo.clear()
            # Add an initial empty/none option ONLY for coordinate fields
            if combo in [easting_combo, northing_combo]:
                combo.addItem("", None)
            combo.blockSignals(False)

        # If no layer is provided and we can't find one, exit
        if not layer:
            QgsMessageLog.logMessage(f"No valid layer selected for dataset {dataset_idx + 1}", 'Linear Geoscience', Qgis.Info)
            return

        # Get field names from the valid layer
        try:
            field_names = [f.name() for f in layer.fields()]
            if not field_names:
                QgsMessageLog.logMessage(f"Warning: Layer '{layer.name()}' has no fields.", 'Linear Geoscience', Qgis.Warning)
                return
            QgsMessageLog.logMessage(f"Fields found in layer '{layer.name()}': {field_names}", 'Linear Geoscience', Qgis.Info)
        except Exception as e:
            QgsMessageLog.logMessage(f"Critical Error: Could not get fields from layer '{layer.name()}': {e}", 'Linear Geoscience', Qgis.Warning)
            return

        # Populate combos with field names
        QgsMessageLog.logMessage(f"Populating dataset {dataset_idx + 1} combos with fields...", 'Linear Geoscience', Qgis.Info)
        for combo in all_combos:
            combo.blockSignals(True)
            # Skip adding "" again for coord fields as it was added during clear
            if combo in [easting_combo, northing_combo]:
                for field in field_names:
                    combo.addItem(field, field)
            else:  # For non-coordinate fields
                for field in field_names:
                    combo.addItem(field, field)
            combo.blockSignals(False)

        # Auto-select common fields
        selected_fields = {}

        def try_set_field(combo, field_prefs, field_key):
            for field_name in field_prefs:
                index = combo.findText(field_name, Qt.MatchFixedString)
                if index >= 0:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(index)
                    combo.blockSignals(False)
                    selected_fields[field_key] = field_name
                    QgsMessageLog.logMessage(f"  Auto-selected '{field_name}' for {field_key}", 'Linear Geoscience', Qgis.Info)
                    return True
            QgsMessageLog.logMessage(f"  Could not auto-select for {field_key}", 'Linear Geoscience', Qgis.Info)
            return False

        try_set_field(dip_combo, ["Dip", "DIP", "dip", "Angle", "angle"], 'dip')
        try_set_field(dipdir_combo,
                      ["DipDirection", "DIPDIRECTION", "dipdir", "DipDir", "Azimuth", "azimuth", "Bearing", "bearing"],
                      'dipdir')
        try_set_field(subtype_combo,
                      ["Subtype1", "SUBTYPE", "Subtype", "subtype", "StructureCode", "Code", "StructCode", "Type"],
                      'subtype')
        # Auto-select domain field
        try_set_field(domain_combo,
                      ["StructuralDomain", "Domain", "DOMAIN", "domain", "Structure_Domain", "Litho_Domain"],
                      'domain')
        try_set_field(easting_combo, ["Easting", "EASTING", "east", "X", "x", "XCOORD", "xcoord", "X_Coord"], 'easting')
        try_set_field(northing_combo, ["Northing", "NORTHING", "north", "Y", "y", "YCOORD", "ycoord", "Y_Coord"],
                      'northing')

        QgsMessageLog.logMessage(f"Finished populating fields for dataset {dataset_idx + 1}. Auto-selected: {selected_fields}", 'Linear Geoscience', Qgis.Info)


    def populate_field_combos_for_dataset(self, dataset_idx, layer):
        """Populate field combos for a specific dataset"""
        # Safety check
        if not self.dataset_configs[dataset_idx]["dip_combo"] or not self.dataset_configs[dataset_idx][
            "dipdir_combo"] or not self.dataset_configs[dataset_idx]["subtype_combo"]:
            QgsMessageLog.logMessage(f"Dataset {dataset_idx + 1}: Field combos not properly initialized", 'Linear Geoscience', Qgis.Info)
            return

        if not layer or not layer.isValid():
            QgsMessageLog.logMessage(f"Dataset {dataset_idx + 1}: Invalid layer", 'Linear Geoscience', Qgis.Warning)
            return

        QgsMessageLog.logMessage(f"Dataset {dataset_idx + 1}: Populating field combos for layer '{layer.name()}'", 'Linear Geoscience', Qgis.Info)

        # Set the layer for each combo
        self.dataset_configs[dataset_idx]["dip_combo"].setLayer(layer)
        self.dataset_configs[dataset_idx]["dipdir_combo"].setLayer(layer)
        self.dataset_configs[dataset_idx]["subtype_combo"].setLayer(layer)

        # Auto-select fields based on common names
        fields = [f.name() for f in layer.fields()]
        QgsMessageLog.logMessage(f"Dataset {dataset_idx + 1}: Available fields: {fields}", 'Linear Geoscience', Qgis.Info)

        # Auto-select Dip field
        for field_name in ["Dip", "DIP", "dip", "Angle", "angle"]:
            if field_name in fields:
                self.dataset_configs[dataset_idx]["dip_combo"].setCurrentText(field_name)
                QgsMessageLog.logMessage(f"Dataset {dataset_idx + 1}: Auto-selected '{field_name}' for Dip", 'Linear Geoscience', Qgis.Info)
                break

        # Auto-select DipDirection field
        for field_name in ["DipDirection", "DIPDIRECTION", "dipdir", "DipDir", "Azimuth", "azimuth"]:
            if field_name in fields:
                self.dataset_configs[dataset_idx]["dipdir_combo"].setCurrentText(field_name)
                QgsMessageLog.logMessage(f"Dataset {dataset_idx + 1}: Auto-selected '{field_name}' for DipDirection", 'Linear Geoscience', Qgis.Info)
                break

        # Auto-select Structure code field
        for field_name in ["Subtype1", "SUBTYPE", "Subtype", "subtype", "StructureCode", "Code"]:
            if field_name in fields:
                self.dataset_configs[dataset_idx]["subtype_combo"].setCurrentText(field_name)
                QgsMessageLog.logMessage(f"Dataset {dataset_idx + 1}: Auto-selected '{field_name}' for Structure Code", 'Linear Geoscience', Qgis.Info)
                break


    def update_dataset_panel_visibility(self):
        """Update which dataset panel is visible"""
        if hasattr(self, 'dataset1_panel') and hasattr(self, 'dataset2_panel'):
            self.dataset1_panel.setVisible(self.active_dataset == 0)
            self.dataset2_panel.setVisible(self.active_dataset == 1)


    def populate_fields_for_layer_auto(self, layer):
        if not layer or not layer.isValid():
            QgsMessageLog.logMessage("No valid layer in new approach; skipping field population.", 'Linear Geoscience', Qgis.Info)
            return

        self.dip_column_combo.clear()
        self.dipdir_column_combo.clear()
        self.subtype_column_combo.clear()

        fields = [f.name() for f in layer.fields()]
        QgsMessageLog.logMessage(f"Auto approach sees {len(fields)} fields -> {fields}", 'Linear Geoscience', Qgis.Info)

        for f in fields:
            self.dip_column_combo.addItem(f)
            self.dipdir_column_combo.addItem(f)
            self.subtype_column_combo.addItem(f)

        if "Dip" in fields:
            self.dip_column_combo.setCurrentText("Dip")
        if "DipDirection" in fields:
            self.dipdir_column_combo.setCurrentText("DipDirection")
        if "Subtype1" in fields:
            self.subtype_column_combo.setCurrentText("Subtype1")

    ########################################################################
    # Coding Tab
    ########################################################################


    def populate_coding_table(self):
        """
        Load structure codes from all enabled datasets into the coding table.
        Shows unknown codes and their current classification.
        """
        self.coding_table.setRowCount(0)  # Clear existing rows
        self.coding_entries = {}  # Clear existing entries

        # Get all structure codes from all datasets
        all_codes = {}  # {code: {dataset_idx: code_data}}

        for dataset_idx in range(len(self.dataset_configs)):
            if not self.dataset_configs[dataset_idx]["enabled"]:
                continue

            # Get the layer for this dataset
            layer = self.get_layer(dataset_idx)
            if not layer:
                continue

            # Get the field names
            dip_field = self.dataset_configs[dataset_idx]["dip_combo"].currentText()
            dipdir_field = self.dataset_configs[dataset_idx]["dipdir_combo"].currentText()
            subtype_field = self.dataset_configs[dataset_idx]["subtype_combo"].currentText()

            if not all([dip_field, dipdir_field, subtype_field]):
                continue

            # Process all features to get unique codes
            for feat in layer.getFeatures():
                code = feat[subtype_field]
                if not code:
                    continue

                code_str = str(code).upper()

                # Check if this is a known code
                is_known = False
                if code_str in planar_codes:  # Using global planar_codes
                    is_known = True
                    code_type = "plane"
                elif code_str in linear_codes:  # Using global linear_codes
                    is_known = True
                    code_type = "line"
                else:
                    # Check in normalized_classification
                    code_type = normalized_classification.get(code_str)
                    is_known = (code_type is not None)

                # Store code data
                if code_str not in all_codes:
                    all_codes[code_str] = {}

                all_codes[code_str][dataset_idx] = {
                    "is_known": is_known,
                    "type": code_type
                }

        # Add codes to the table
        sorted_codes = sorted(all_codes.keys())

        for code in sorted_codes:
            for dataset_idx, code_data in all_codes[code].items():
                # Skip known codes if desired
                if code_data["is_known"] and not self.show_known_codes_checkbox.isChecked():
                    continue

                # Add row for this code-dataset combination
                row = self.coding_table.rowCount()
                self.coding_table.insertRow(row)

                # Code
                code_item = QTableWidgetItem(code)
                self.coding_table.setItem(row, 0, code_item)

                # Dataset name
                dataset_name = self.dataset_configs[dataset_idx]["name"]
                dataset_item = QTableWidgetItem(dataset_name)
                self.coding_table.setItem(row, 1, dataset_item)

                # Planar checkbox
                planar_cell = QWidget()
                planar_layout = QHBoxLayout(planar_cell)
                planar_layout.setContentsMargins(0, 0, 0, 0)
                planar_layout.setAlignment(Qt.AlignCenter)
                planar_chk = QCheckBox()

                # Set checked state based on current classification
                if code_data["type"] == "plane":
                    planar_chk.setChecked(True)

                planar_layout.addWidget(planar_chk)
                self.coding_table.setCellWidget(row, 2, planar_cell)

                # Linear checkbox
                linear_cell = QWidget()
                linear_layout = QHBoxLayout(linear_cell)
                linear_layout.setContentsMargins(0, 0, 0, 0)
                linear_layout.setAlignment(Qt.AlignCenter)
                linear_chk = QCheckBox()

                # Set checked state based on current classification
                if code_data["type"] == "line":
                    linear_chk.setChecked(True)

                linear_layout.addWidget(linear_chk)
                self.coding_table.setCellWidget(row, 3, linear_cell)

                # Connect checkboxes to ensure mutual exclusivity
                planar_chk.stateChanged.connect(lambda state, r=row, l=linear_chk:
                                                self.handle_checkbox_change(state, r, l, is_planar=True))
                linear_chk.stateChanged.connect(lambda state, r=row, p=planar_chk:
                                                self.handle_checkbox_change(state, r, p, is_planar=False))

                # Store reference to this entry
                self.coding_entries[row] = {
                    "code": code,
                    "dataset_idx": dataset_idx,
                    "planar_chk": planar_chk,
                    "linear_chk": linear_chk
                }

        # Update row count label
        count_text = f"Displaying {self.coding_table.rowCount()} code entries"
        if self.code_count_label:
            self.code_count_label.setText(count_text)


    def refresh_domain_list(self):
        """Refresh the list of available domains"""
        self.domain_filter_combo.clear()

        # Get all unique domains
        domains = set()

        # Extract from domain-based entries - check each dataset
        for dataset_idx in range(len(self.subtype_dict_domains)):
            if self.dataset_configs[dataset_idx]["enabled"]:
                for st in self.subtype_dict_domains[dataset_idx]:
                    if " - " in st:
                        domain = st.split(" - ")[1]
                        domains.add(domain)

        # Add to combo box
        self.domain_filter_combo.addItem("All Domains")
        for domain in sorted(domains):
            self.domain_filter_combo.addItem(domain)


    def refresh_export_data(self):
        """Refresh the export tab with current data"""
        # Refresh both data sources if needed
        self.update_data_selection()
        self.update_data_domains()

        # Populate the structure tree
        self.populate_export_structure_tree()

        # Refresh the Leapfrog additional-columns list
        self._populate_leapfrog_fields()

        # Update domain list if domain filtering is active
        if hasattr(self, 'filter_by_domain_checkbox') and self.filter_by_domain_checkbox.isChecked():
            self.refresh_domain_list()


    def populate_export_structure_tree(self):
        """Populate the structure tree in the export tab"""
        if not hasattr(self, 'export_structure_tree'):
            return

        self.export_structure_tree.clear()

        # Union codes from every loaded view (exports always read all layer
        # features, so the checklist should list everything available)
        all_structures = set()

        for dataset_idx in range(len(self.subtype_dict_selection)):
            if self.dataset_configs[dataset_idx]["enabled"]:
                all_structures.update(self.subtype_dict_selection[dataset_idx].keys())

        for dataset_idx in range(len(self.subtype_dict_domains)):
            if self.dataset_configs[dataset_idx]["enabled"]:
                # For domains, extract the structure code (before the " - ")
                for st in self.subtype_dict_domains[dataset_idx].keys():
                    if " - " in st:
                        code = st.split(" - ")[0]
                        all_structures.add(code)
                    else:
                        all_structures.add(st)

        # Also include Live View categories (the dicts above are empty when
        # the user plots via Live View instead of map selection)
        for dataset_idx in range(2):
            if not self.dataset_configs[dataset_idx]["enabled"]:
                continue
            for st in self.category_structure_map_live_view[dataset_idx].keys():
                base = st.split(" - ")[0] if " - " in st else st
                all_structures.add(base)

        # Always union the codes actually present in the configured layers,
        # so the list never depends on selection state or refresh order
        for dataset_idx in range(2):
            if not self.dataset_configs[dataset_idx]["enabled"]:
                continue
            layer = self.get_layer(dataset_idx)
            subtype_combo = self.dataset_configs[dataset_idx].get("subtype_combo")
            field_name = subtype_combo.currentText() if subtype_combo else ""
            if layer is None or not field_name:
                continue
            field_idx = layer.fields().indexOf(field_name)
            if field_idx < 0:
                continue
            try:
                for value in layer.uniqueValues(field_idx):
                    if value is None:
                        continue
                    text = str(value).strip()
                    if not text or text == "NULL":
                        continue
                    all_structures.add(unify_fax_code(text.upper()))
            except Exception:
                QgsMessageLog.logMessage(
                    f"Export: could not read codes from layer for dataset "
                    f"{dataset_idx + 1}", 'Linear Geoscience', Qgis.Warning)

        # Create tree items: classified codes first (checked); unclassified
        # codes flagged red and unchecked at the bottom — they can't be
        # exported until classified in the Coding tab
        known = []
        unknown = []
        for st in sorted(all_structures):
            struct_type = self._classify_base_code(st)
            (known if struct_type else unknown).append((st, struct_type))

        for st, struct_type in known + unknown:
            item = QTreeWidgetItem(self.export_structure_tree)
            item.setText(0, st)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)

            if struct_type:
                item.setCheckState(0, Qt.Checked)  # Default to checked
                type_label = QLabel(f"({struct_type})")
            else:
                item.setCheckState(0, Qt.Unchecked)
                item.setForeground(0, QBrush(QColor("#d62728")))
                item.setToolTip(0, "Not classified as planar or linear — "
                                   "classify it in the Coding tab to export")
                type_label = QLabel("(unknown)")
                type_label.setStyleSheet("color: #d62728;")
            self.export_structure_tree.setItemWidget(item, 1, type_label)

        # Resize columns
        self.export_structure_tree.resizeColumnToContents(0)
        self.export_structure_tree.resizeColumnToContents(1)


    def manually_populate_fields(self, dataset_idx, field_names=None):
        """Manually populate the field combo boxes"""
        QgsMessageLog.logMessage(f"Starting manual field population for dataset {dataset_idx + 1}", 'Linear Geoscience', Qgis.Info)

        # Get the layer
        layer = self.dataset_configs[dataset_idx]["layer_combo"].currentLayer()
        if not layer or not layer.isValid():
            QgsMessageLog.logMessage(f"No valid layer selected for dataset {dataset_idx + 1}", 'Linear Geoscience', Qgis.Info)
            return False

        QgsMessageLog.logMessage(f"Using layer: {layer.name()}", 'Linear Geoscience', Qgis.Info)

        # Get field names if not provided
        if field_names is None:
            field_names = [f.name() for f in layer.fields()]

        QgsMessageLog.logMessage(f"Fields found: {field_names}", 'Linear Geoscience', Qgis.Info)

        # Create new standard QComboBox widgets (more reliable than QgsFieldComboBox)
        dip_combo = QComboBox()
        dipdir_combo = QComboBox()
        subtype_combo = QComboBox()

        # Add all fields to the combo boxes
        for field in field_names:
            dip_combo.addItem(field)
            dipdir_combo.addItem(field)
            subtype_combo.addItem(field)

        # Auto-select common field names
        for field_name in ["Dip", "DIP", "dip", "Angle", "angle"]:
            if field_name in field_names:
                dip_combo.setCurrentText(field_name)
                QgsMessageLog.logMessage(f"Selected '{field_name}' for Dip field", 'Linear Geoscience', Qgis.Info)
                break

        for field_name in ["DipDirection", "DIPDIRECTION", "dipdir", "DipDir", "Azimuth", "azimuth"]:
            if field_name in field_names:
                dipdir_combo.setCurrentText(field_name)
                QgsMessageLog.logMessage(f"Selected '{field_name}' for DipDirection field", 'Linear Geoscience', Qgis.Info)
                break

        for field_name in ["Subtype1", "SUBTYPE", "Subtype", "subtype", "StructureCode", "Code"]:
            if field_name in field_names:
                subtype_combo.setCurrentText(field_name)
                QgsMessageLog.logMessage(f"Selected '{field_name}' for Structure Code field", 'Linear Geoscience', Qgis.Info)
                break

        # Get the appropriate panel
        panel = self.dataset1_panel if dataset_idx == 0 else self.dataset2_panel
        if not panel:
            QgsMessageLog.logMessage(f"Could not find panel for dataset {dataset_idx + 1}", 'Linear Geoscience', Qgis.Info)
            return False

        # Get the layout
        layout = panel.layout()
        if not layout:
            QgsMessageLog.logMessage(f"Could not find layout for dataset {dataset_idx + 1}", 'Linear Geoscience', Qgis.Info)
            return False

        # Find the label indices
        dip_label_idx = -1
        dipdir_label_idx = -1
        subtype_label_idx = -1

        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if isinstance(widget, QLabel):
                if widget.text() == "Dip Field:":
                    dip_label_idx = i
                elif widget.text() == "Dip Direction Field:":
                    dipdir_label_idx = i
                elif widget.text() == "Structure Code Field:":
                    subtype_label_idx = i

        QgsMessageLog.logMessage(f"Found labels at indices: Dip={dip_label_idx}, DipDir={dipdir_label_idx}, Subtype={subtype_label_idx}", 'Linear Geoscience', Qgis.Info)

        # Replace the existing field combo boxes with our new ones
        if dip_label_idx >= 0 and dip_label_idx + 1 < layout.count():
            old_item = layout.itemAt(dip_label_idx + 1)
            if old_item:
                old_widget = old_item.widget()
                if old_widget:
                    layout.removeWidget(old_widget)
                    old_widget.deleteLater()
                    layout.insertWidget(dip_label_idx + 1, dip_combo)
                    self.dataset_configs[dataset_idx]["dip_combo"] = dip_combo
                    QgsMessageLog.logMessage("Replaced Dip combo box", 'Linear Geoscience', Qgis.Info)

        if dipdir_label_idx >= 0 and dipdir_label_idx + 1 < layout.count():
            old_item = layout.itemAt(dipdir_label_idx + 1)
            if old_item:
                old_widget = old_item.widget()
                if old_widget:
                    layout.removeWidget(old_widget)
                    old_widget.deleteLater()
                    layout.insertWidget(dipdir_label_idx + 1, dipdir_combo)
                    self.dataset_configs[dataset_idx]["dipdir_combo"] = dipdir_combo
                    QgsMessageLog.logMessage("Replaced DipDirection combo box", 'Linear Geoscience', Qgis.Info)

        if subtype_label_idx >= 0 and subtype_label_idx + 1 < layout.count():
            old_item = layout.itemAt(subtype_label_idx + 1)
            if old_item:
                old_widget = old_item.widget()
                if old_widget:
                    layout.removeWidget(old_widget)
                    old_widget.deleteLater()
                    layout.insertWidget(subtype_label_idx + 1, subtype_combo)
                    self.dataset_configs[dataset_idx]["subtype_combo"] = subtype_combo
                    QgsMessageLog.logMessage("Replaced Subtype combo box", 'Linear Geoscience', Qgis.Info)

        # Update backward compatibility references if this is dataset 0
        if dataset_idx == 0:
            self.dip_column_combo = dip_combo
            self.dipdir_column_combo = dipdir_combo
            self.subtype_column_combo = subtype_combo

        QgsMessageLog.logMessage(f"Field combo boxes successfully replaced for dataset {dataset_idx + 1}", 'Linear Geoscience', Qgis.Info)
        return True


    def update_data_selection(self, dataset_index=0, use_all_features=False):
        """Update selection data for the specified dataset, using selected coordinate fields.

        use_all_features=True loads every feature in the layer ("Refresh with
        All"); the default loads only the QGIS-selected features.
        """
        self.subtype_dict_selection[dataset_index].clear()
        self.category_structure_map_selection[dataset_index].clear()

        layer = self.get_layer(dataset_index)
        if not layer:
            QgsMessageLog.logMessage(f"update_data_selection: No valid layer selected for Dataset {dataset_index + 1}.", 'Linear Geoscience', Qgis.Info)
            return

        # Get field selection combo boxes
        dip_combo = self.dataset_configs[dataset_index].get("dip_combo")
        dipdir_combo = self.dataset_configs[dataset_index].get("dipdir_combo")
        subtype_combo = self.dataset_configs[dataset_index].get("subtype_combo")
        easting_combo = self.dataset_configs[dataset_index].get("easting_combo")  # Get Easting combo
        northing_combo = self.dataset_configs[dataset_index].get("northing_combo")  # Get Northing combo

        # Check if required combo boxes exist
        if not all([dip_combo, dipdir_combo, subtype_combo, easting_combo, northing_combo]):
            QgsMessageLog.logMessage(f"Configuration error: One or more field combo boxes are missing for Dataset {dataset_index + 1}", 'Linear Geoscience', Qgis.Warning)
            # Maybe show a warning message to the user
            # QMessageBox.critical(self.iface.mainWindow(), "Config Error", f"Field selectors not properly initialized for Dataset {dataset_index + 1}. Check plugin setup.")
            return

        # Get selected field names
        dip_field = dip_combo.currentText()
        dipdir_field = dipdir_combo.currentText()
        subtype_field = subtype_combo.currentText()
        # --- MODIFIED: Get coordinate fields from combo boxes ---
        easting_field = easting_combo.currentText()
        northing_field = northing_combo.currentText()
        # Treat empty selection as no field selected
        if not easting_field: easting_field = None
        if not northing_field: northing_field = None
        QgsMessageLog.logMessage(
            f"[Dataset {dataset_index + 1}] Using fields: Dip='{dip_field}', DipDir='{dipdir_field}', Subtype='{subtype_field}', Easting='{easting_field}', Northing='{northing_field}'", 'Linear Geoscience', Qgis.Info)
        # --- END MODIFIED ---

        # Check if essential fields are selected
        if not all([dip_field, dipdir_field, subtype_field]):
            QgsMessageLog.logMessage(f"[Dataset {dataset_index + 1}] Essential fields (Dip, DipDir, Subtype) not selected.", 'Linear Geoscience', Qgis.Info)
            # Optionally inform the user they need to select these fields
            # QMessageBox.warning(self.iface.mainWindow(), "Fields Missing", f"Please select Dip, Dip Direction, and Structure Code fields for Dataset {dataset_index + 1}.")
            return

        # Check if selected fields exist in the layer
        try:
            fields_in_layer = {f.name() for f in layer.fields()}
            required_fields = {dip_field, dipdir_field, subtype_field}
            # Add coordinate fields to check only if they were selected
            if easting_field: required_fields.add(easting_field)
            if northing_field: required_fields.add(northing_field)

            missing_fields = required_fields - fields_in_layer
            if missing_fields:
                # Filter out None if it somehow got into missing_fields
                missing_fields_str = ", ".join(filter(None, missing_fields))
                if missing_fields_str:  # Check if there are actually missing fields after filtering None
                    QgsMessageLog.logMessage(
                        f"[Dataset {dataset_index + 1}] Selected fields not found in layer '{layer.name()}': {missing_fields_str}", 'Linear Geoscience', Qgis.Warning)
                    QMessageBox.warning(self.iface.mainWindow(), "Field Not Found",
                                        f"The following selected field(s) are not in layer '{layer.name()}': {missing_fields_str}. Please reselect.")
                    return  # Stop processing if essential fields are missing
        except Exception as e:
            QgsMessageLog.logMessage(f"Error validating fields for layer '{layer.name()}': {e}", 'Linear Geoscience', Qgis.Warning)
            return

        # Decide whether to use selected features or all features
        if use_all_features:
            feature_iterator = layer.getFeatures()
            QgsMessageLog.logMessage(
                f"update_data_selection: Processing ALL {layer.featureCount()} features in {layer.name()} for Dataset {dataset_index + 1}.", 'Linear Geoscience', Qgis.Info)
        elif layer.selectedFeatureCount() > 0:
            feature_iterator = layer.selectedFeatures()
            QgsMessageLog.logMessage(
                f"update_data_selection: Processing {layer.selectedFeatureCount()} selected features in {layer.name()} for Dataset {dataset_index + 1}.", 'Linear Geoscience', Qgis.Info)
        else:
            QgsMessageLog.logMessage(
                f"update_data_selection: No features selected in {layer.name()} for Dataset {dataset_index + 1}. Select features to include them.", 'Linear Geoscience', Qgis.Info)
            # Clear previous data and exit if only processing selected features
            self.subtype_dict_selection[dataset_index].clear()
            self.category_structure_map_selection[dataset_index].clear()
            return  # Or comment out to process all features if none selected

        found_categories = 0
        processed_points_count = 0
        added_points_count = 0
        out_of_range_count = 0

        for f in feature_iterator:
            processed_points_count += 1
            sv = f.attribute(subtype_field)
            dv = f.attribute(dip_field)
            ddv = f.attribute(dipdir_field)

            if sv is None or dv is None or ddv is None or str(sv).strip() == '' or str(dv).strip() == '' or str(
                    ddv).strip() == '':
                continue

            dip, dipdir = None, None
            try:
                dip = float(dv)
                dipdir = float(ddv)
            except (ValueError, TypeError):
                continue

            if not (isinstance(dip, (int, float)) and isinstance(dipdir, (int, float))):
                continue

            # Range check (warn but keep the point - may indicate a field mix-up)
            if not (0 <= dip <= 90) or not (0 <= dipdir <= 360):
                out_of_range_count += 1

            unified = unify_fax_code(str(sv).upper())
            struct_type = classify_code(unified)
            if not struct_type:
                continue

            # --- MODIFIED: Collect coordinate data using SELECTED fields ---
            x_coord = None
            y_coord = None
            if easting_field:  # Only try if a field was selected
                try:
                    val_x = f.attribute(easting_field)  # Use attribute() for better NULL handling
                    if val_x is not None:
                        x_coord = float(val_x)
                except (ValueError, TypeError):
                    # print(f"Warning: Could not convert easting '{f[easting_field]}' to float for feature {f.id()}")
                    pass

            if northing_field:  # Only try if a field was selected
                try:
                    val_y = f.attribute(northing_field)  # Use attribute() for better NULL handling
                    if val_y is not None:
                        y_coord = float(val_y)
                except (ValueError, TypeError):
                    # print(f"Warning: Could not convert northing '{f[northing_field]}' to float for feature {f.id()}")
                    pass
            # --- END MODIFIED ---

            pitch_val = None
            # Find pitch field case-insensitively
            pitch_field_name = next((name for name in fields_in_layer if name.lower() == "pitch"), None)
            if pitch_field_name:
                tmp = f.attribute(pitch_field_name)
                if tmp not in (None, "NULL", ""):
                    try:
                        pitch_val = float(tmp)
                    except (ValueError, TypeError):
                        pass

            data_dict = {
                "dip": dip,
                "dipdir": dipdir,
                "pitch": pitch_val,
                "dataset": dataset_index,
                "feature_id": f.id(),
                "x": x_coord,
                "y": y_coord
            }

            if unified not in self.subtype_dict_selection[dataset_index]:
                self.subtype_dict_selection[dataset_index][unified] = []
                self.category_structure_map_selection[dataset_index][unified] = struct_type
                found_categories += 1

            self.subtype_dict_selection[dataset_index][unified].append(data_dict)
            added_points_count += 1

        QgsMessageLog.logMessage(
            f"[Dataset {dataset_index + 1} Selection] Processed {processed_points_count} features, added {added_points_count} valid data points.", 'Linear Geoscience', Qgis.Info)
        QgsMessageLog.logMessage(f"[Dataset {dataset_index + 1} Selection] Found {found_categories} categories from selection.", 'Linear Geoscience', Qgis.Info)

        if out_of_range_count:
            range_msg = (f"{out_of_range_count} measurement(s) in Dataset {dataset_index + 1} have dip outside "
                         f"0-90 or dip direction outside 0-360; they are plotted as-is - check field mapping.")
            QgsMessageLog.logMessage(range_msg, 'Linear Geoscience', Qgis.Warning)
            self.iface.messageBar().pushWarning("Stereonet", range_msg)

        if added_points_count == 0 and processed_points_count > 0:
            QMessageBox.information(self.iface.mainWindow(), "No Data Added",
                                    f"Processed {processed_points_count} selected features for Dataset {dataset_index + 1}, but none contained valid data based on the selected fields. Please check field selections and data values.")
        elif added_points_count == 0 and processed_points_count == 0:
            # This case handled earlier if no features were selected
            pass


    def update_data_domains(self, dataset_index=0):
        """Update domain data for the specified dataset using the selected domain field"""
        self.subtype_dict_domains[dataset_index].clear()
        self.category_structure_map_domains[dataset_index].clear()

        layer = self.get_layer(dataset_index)
        if not layer:
            QgsMessageLog.logMessage(f"update_data_domains: No layer chosen for Dataset {dataset_index + 1}.", 'Linear Geoscience', Qgis.Info)
            return

        # Get field names from combo boxes
        dip_combo = self.dataset_configs[dataset_index]["dip_combo"]
        dipdir_combo = self.dataset_configs[dataset_index]["dipdir_combo"]
        subtype_combo = self.dataset_configs[dataset_index]["subtype_combo"]
        domain_combo = self.dataset_configs[dataset_index]["domain_combo"]  # Get domain combo

        if not all([dip_combo, dipdir_combo, subtype_combo, domain_combo]):
            QgsMessageLog.logMessage(f"Missing combo boxes for dataset {dataset_index + 1}", 'Linear Geoscience', Qgis.Info)
            return

        dip_field = dip_combo.currentText()
        dipdir_field = dipdir_combo.currentText()
        subtype_field = subtype_combo.currentText()
        domain_field = domain_combo.currentText()  # Get selected domain field

        # If no domain field is selected, default to "StructuralDomain" for backwards compatibility
        if not domain_field:
            domain_field = "StructuralDomain"
            QgsMessageLog.logMessage(f"[Dataset {dataset_index + 1}] No domain field selected, defaulting to 'StructuralDomain'", 'Linear Geoscience', Qgis.Info)

        if not all([dip_field, dipdir_field, subtype_field]):
            QgsMessageLog.logMessage(f"[Dataset {dataset_index + 1}] Empty field names selected", 'Linear Geoscience', Qgis.Info)
            return

        fields = [f.name() for f in layer.fields()]
        for req in [dip_field, dipdir_field, subtype_field]:
            if req not in fields:
                QgsMessageLog.logMessage(f"[Dataset {dataset_index + 1} Domains] Missing field '{req}' in layer.", 'Linear Geoscience', Qgis.Info)
                return

        # Check if the selected domain field exists in the layer
        if domain_field not in fields:
            QgsMessageLog.logMessage(f"[Dataset {dataset_index + 1} Domains] Selected domain field '{domain_field}' not found in layer.", 'Linear Geoscience', Qgis.Warning)
            # Continue without domain grouping if the field doesn't exist
            domain_field = None

        # Get the field index for the domain field to access its configuration
        domain_field_index = None
        if domain_field:
            domain_field_index = layer.fields().indexOf(domain_field)

        feats = list(layer.getFeatures())
        QgsMessageLog.logMessage(f"update_data_domains: {len(feats)} features in {layer.name()} for Dataset {dataset_index + 1}.", 'Linear Geoscience', Qgis.Info)

        found_categories = 0
        out_of_range_count = 0
        for f in feats:
            sv = f[subtype_field]
            dv = f[dip_field]
            ddv = f[dipdir_field]
            if sv is None or dv is None or ddv is None:
                continue

            try:
                dip = float(dv)
                dd = float(ddv)
            except (ValueError, TypeError):
                continue

            # Range check (warn but keep the point - may indicate a field mix-up)
            if not (0 <= dip <= 90) or not (0 <= dd <= 360):
                out_of_range_count += 1

            unified = unify_fax_code(str(sv).upper())
            struct_type = classify_code(unified)
            if not struct_type:
                continue

            # Get domain value from the selected field, or use a default if no field is selected
            if domain_field and domain_field in fields:
                dom_val = f[domain_field]
                if dom_val is None:
                    dom_val = "NoDomain"
                else:
                    # Try to get the display value using QGIS field formatting
                    try:
                        # Get the field configuration
                        field_config = layer.fields().field(domain_field_index)
                        editor_widget_setup = layer.editorWidgetSetup(domain_field_index)

                        # If it's a value relation or value map widget, get the display value
                        if editor_widget_setup.type() == 'ValueRelation':
                            # For value relation widgets, we need to get the display value
                            from qgis.core import QgsValueRelationFieldFormatter
                            formatter = QgsValueRelationFieldFormatter()
                            context = layer.createExpressionContext()
                            context.setFeature(f)
                            display_value = formatter.representValue(layer, domain_field_index,
                                                                     editor_widget_setup.config(), None, dom_val)
                            if display_value and display_value != str(dom_val):
                                dom_val = display_value
                            else:
                                dom_val = str(dom_val)
                        elif editor_widget_setup.type() == 'ValueMap':
                            # For value map widgets
                            value_map = editor_widget_setup.config().get('map', {})
                            # Value map stores display_name: stored_value, so we need to reverse lookup
                            for display_name, stored_value in value_map.items():
                                if str(stored_value) == str(dom_val):
                                    dom_val = display_name
                                    break
                            else:
                                dom_val = str(dom_val)
                        else:
                            # For other widget types, just use the raw value
                            dom_val = str(dom_val)
                    except Exception as e:
                        # If anything goes wrong with getting display value, fall back to raw value
                        QgsMessageLog.logMessage(f"Warning: Could not get display value for {domain_field}: {e}", 'Linear Geoscience', Qgis.Warning)
                        dom_val = str(dom_val)
            else:
                dom_val = "NoDomain"

            strike_rhr = None
            pitch_val = None
            if "Strike_RHR" in fields:
                tmp = f["Strike_RHR"]
                if tmp is not None:
                    try:
                        strike_rhr = float(tmp)
                    except (ValueError, TypeError):
                        pass
            if "Pitch" in fields:
                tmp2 = f["Pitch"]
                if tmp2 is not None:
                    try:
                        pitch_val = float(tmp2)
                    except (ValueError, TypeError):
                        pass

            data_dict = {
                "dip": dip,
                "dipdir": dd,
                "strike_rhr": strike_rhr,
                "pitch": pitch_val,
                "dataset": dataset_index,  # Store dataset index
                "feature_id": f.id(),  # Links plotted points back to the layer
                "domain": dom_val  # Store the domain value for reference
            }

            # Include dataset name in the category name: "CODE - DOMAIN (Dataset Name)"
            dataset_name = self.dataset_configs[dataset_index]["name"]
            cat_name = f"{unified} - {dom_val} ({dataset_name})"
            if cat_name not in self.subtype_dict_domains[dataset_index]:
                self.subtype_dict_domains[dataset_index][cat_name] = []
                self.category_structure_map_domains[dataset_index][cat_name] = struct_type
                found_categories += 1

            self.subtype_dict_domains[dataset_index][cat_name].append(data_dict)

        QgsMessageLog.logMessage(f"[Dataset {dataset_index + 1} Domains] Found {found_categories} categories from domain classification.", 'Linear Geoscience', Qgis.Info)
        if domain_field:
            QgsMessageLog.logMessage(f"[Dataset {dataset_index + 1} Domains] Used domain field: '{domain_field}'", 'Linear Geoscience', Qgis.Info)

        if out_of_range_count:
            range_msg = (f"{out_of_range_count} measurement(s) in Dataset {dataset_index + 1} have dip outside "
                         f"0-90 or dip direction outside 0-360; they are plotted as-is - check field mapping.")
            QgsMessageLog.logMessage(range_msg, 'Linear Geoscience', Qgis.Warning)
            self.iface.messageBar().pushWarning("Stereonet", range_msg)


    def _setup_category_tree_columns(self, tree):
        """Configure the shared category tree columns, including the
        per-category analysis toggle columns (Best Fit / Contours / Mean)."""
        tree.setHeaderLabels(["Structure Type", "Plot type", "BF", "Ct", "Mn"])
        tree.setColumnWidth(COL_NAME, 220)
        tree.setColumnWidth(COL_PLOT_MODE, 120)
        for col, tip in ((COL_BF, "Include this category in Best Fit analysis.\n"
                                  "Click the header to toggle all rows."),
                         (COL_CT, "Include this category in Contours analysis.\n"
                                  "Click the header to toggle all rows."),
                         (COL_MN, "Include this category in Mean analysis.\n"
                                  "Click the header to toggle all rows.")):
            tree.setColumnWidth(col, 36)
            tree.headerItem().setToolTip(col, tip)
        tree.itemChanged.connect(self._on_category_tree_item_changed)
        header = tree.header()
        header.setSectionsClickable(True)
        header.sectionClicked.connect(
            lambda col, t=tree: self._on_analysis_header_clicked(t, col))
        # Right-click menu for grouping codes into combined categories
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.customContextMenuRequested.connect(
            lambda pos, t=tree: self._show_category_tree_menu(t, pos))

    def _capture_tree_analysis_states(self, tree):
        """Read the per-category analysis toggle states (BF/Ct/Mn columns),
        keyed by (code_str, dataset_idx), so a rebuild can restore them."""
        states = {}
        if tree is None:
            return states
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            data = item.data(0, Qt.UserRole)
            if isinstance(data, tuple) and len(data) >= 2:
                states[(data[0], data[1])] = tuple(
                    item.checkState(col) for col in ANALYSIS_COLUMNS
                )
            elif isinstance(data, dict) and data.get("is_group"):
                states[self._group_state_key(data["display"], data["dataset_idx"])] = tuple(
                    item.checkState(col) for col in ANALYSIS_COLUMNS
                )
        return states

    def _init_item_analysis_columns(self, item, saved_states=None):
        """Initialise the BF/Ct/Mn toggle columns on a tree item.

        Defaults to all-enabled (which reproduces the pre-feature behaviour).
        Signals are blocked while setting states so tree rebuilds don't
        trigger replots through itemChanged.
        """
        tree = item.treeWidget()
        was_blocked = tree.blockSignals(True) if tree is not None else False
        try:
            for idx, col in enumerate(ANALYSIS_COLUMNS):
                state = saved_states[idx] if saved_states is not None else Qt.Checked
                item.setCheckState(col, state)
        finally:
            if tree is not None:
                tree.blockSignals(was_blocked)

    def _on_category_tree_item_changed(self, item, column):
        """Replot when a per-category analysis toggle changes, and keep
        group parent/child column-0 checkboxes in sync (manual tri-state —
        see the note in _make_group_parent_item). Column-0 changes on flat
        items keep their existing Plot-button workflow."""
        if column == 0:
            tree = item.treeWidget()
            if tree is None:
                return
            data = item.data(0, Qt.UserRole)
            if isinstance(data, dict) and data.get("is_group"):
                # Parent toggled -> drive all children
                state = item.checkState(0)
                if state != Qt.PartiallyChecked:
                    was_blocked = tree.blockSignals(True)
                    try:
                        for j in range(item.childCount()):
                            item.child(j).setCheckState(0, state)
                    finally:
                        tree.blockSignals(was_blocked)
                return
            parent = item.parent()
            if parent is not None:
                pdata = parent.data(0, Qt.UserRole)
                if isinstance(pdata, dict) and pdata.get("is_group"):
                    # Child toggled -> recompute the parent's tri-state
                    states = {parent.child(j).checkState(0)
                              for j in range(parent.childCount())}
                    if states == {Qt.Checked}:
                        new_state = Qt.Checked
                    elif states == {Qt.Unchecked}:
                        new_state = Qt.Unchecked
                    else:
                        new_state = Qt.PartiallyChecked
                    was_blocked = tree.blockSignals(True)
                    try:
                        parent.setCheckState(0, new_state)
                    finally:
                        tree.blockSignals(was_blocked)
            return
        if column in ANALYSIS_COLUMNS:
            self.request_plot_update()

    def _on_analysis_header_clicked(self, tree, column):
        """Toggle a whole BF/Ct/Mn column when its header is clicked:
        if any row is unchecked, check all rows; otherwise uncheck all."""
        if column not in ANALYSIS_COLUMNS:
            return
        count = tree.topLevelItemCount()
        if count == 0:
            return
        any_unchecked = any(
            tree.topLevelItem(i).checkState(column) != Qt.Checked
            for i in range(count)
        )
        new_state = Qt.Checked if any_unchecked else Qt.Unchecked
        was_blocked = tree.blockSignals(True)
        try:
            for i in range(count):
                tree.topLevelItem(i).setCheckState(column, new_state)
        finally:
            tree.blockSignals(was_blocked)
        self.request_plot_update()

    def rebuild_category_tree_selection(self):
        if not self.category_tree_selection:
            return
        saved_analysis = self._capture_tree_analysis_states(self.category_tree_selection)
        self.category_tree_selection.clear()

        # One view per enabled dataset, or a single merged view when the
        # Combine-datasets option is on (one row per code, summed counts)
        if self._combined_mode():
            sub, cmap = self._merged_view(self.subtype_dict_selection,
                                          self.category_structure_map_selection)
            views = [(0, sub, cmap, None)]
        else:
            views = [(ds, self.subtype_dict_selection[ds],
                      self.category_structure_map_selection[ds],
                      self.dataset_configs[ds]["name"])
                     for ds in range(2) if self.dataset_configs[ds]["enabled"]]

        any_data = False
        for dataset_idx, sub, cmap, ds_name in views:
            grouped, ungrouped = self._partition_codes_by_group(sorted(sub.keys()))

            for group_name, members in grouped.items():
                struct_type = cmap[members[0]]
                # Runtime guard: drop members whose type doesn't match the
                # group's (creation already blocks mixed groups, but the
                # Coding tab can reclassify codes afterwards)
                same_type = [c for c in members if cmap.get(c) == struct_type]
                skipped = [c for c in members if c not in same_type]
                if skipped:
                    QgsMessageLog.logMessage(
                        f"Group '{group_name}': skipped {', '.join(skipped)} "
                        f"(structure type differs from group)",
                        'Linear Geoscience', Qgis.Warning)
                if not same_type:
                    continue

                total_n = sum(len(sub[c]) for c in same_type)
                user_data = {
                    "is_group": True,
                    "group": group_name,
                    "display": group_name,
                    "dataset_idx": dataset_idx,
                    "struct_type": struct_type,
                }
                if ds_name is None:
                    parent_label = f"{group_name} (n={total_n})"
                else:
                    parent_label = f"{group_name} [{ds_name}] (n={total_n})"
                parent = self._make_group_parent_item(
                    self.category_tree_selection, user_data,
                    parent_label, struct_type, saved_analysis)
                for c in same_type:
                    n = len(sub[c])
                    self._add_group_child_item(parent, f"{c} (n={n})", (c, dataset_idx))
                parent.setExpanded(True)
                any_data = True

            for st in ungrouped:
                struct_type = cmap[st]
                item = QTreeWidgetItem(self.category_tree_selection)
                # Add dataset name to differentiate (omitted in combined mode)
                item_text = st if ds_name is None else f"{st} [{ds_name}]"
                item.setText(0, item_text)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                item.setCheckState(0, Qt.Unchecked)
                # Store both code and dataset index
                item.setData(0, Qt.UserRole, (st, dataset_idx))
                self._init_item_analysis_columns(item, saved_analysis.get((st, dataset_idx)))

                if struct_type == "plane":
                    combo = QComboBox()
                    combo.addItem("Poles Only")
                    combo.addItem("Planes Only")
                    combo.addItem("Both")
                    self.category_tree_selection.setItemWidget(item, 1, combo)
                else:
                    line_label = QLabel("(Line)")
                    self.category_tree_selection.setItemWidget(item, 1, line_label)
                any_data = True

        return any_data


    def rebuild_category_tree_domains(self):
        if not self.category_tree_domains:
            return

        saved_analysis = self._capture_tree_analysis_states(self.category_tree_domains)

        # Temporarily disable sorting to avoid issues during tree population
        self.category_tree_domains.setSortingEnabled(False)
        self.category_tree_domains.clear()

        # One view per enabled dataset, or one merged view (keys stripped of
        # the " (DatasetName)" suffix) when Combine datasets is on
        if self._combined_mode():
            sub, cmap = self._merged_view(self.subtype_dict_domains,
                                          self.category_structure_map_domains,
                                          strip_suffix=True)
            views = [(0, sub, cmap)]
        else:
            views = [(ds, self.subtype_dict_domains[ds],
                      self.category_structure_map_domains[ds])
                     for ds in range(2) if self.dataset_configs[ds]["enabled"]]

        any_data = False
        for dataset_idx, sub, cmap in views:
            if not sub:
                continue

            # Bucket grouped categories by (group, domain suffix) so each
            # group keeps its per-domain split; everything else stays flat
            group_buckets = {}  # (group_name, suffix) -> [(st, code, domain, dataset_name)]
            flat_categories = []

            for st in sorted(sub.keys()):
                code, domain, dataset_name = self._parse_domain_category(st, dataset_idx)
                base_code = code if code else st
                group_name = self.get_group_for_code(base_code)
                if group_name:
                    suffix = st[len(base_code):]  # e.g. " - Domain1 (Dataset 1)"
                    group_buckets.setdefault((group_name, suffix), []).append(
                        (st, base_code, domain, dataset_name))
                else:
                    flat_categories.append((st, code, domain, dataset_name))

            for (group_name, suffix), entries in group_buckets.items():
                struct_type = cmap[entries[0][0]]
                same_type = [e for e in entries if cmap.get(e[0]) == struct_type]
                skipped = [e[0] for e in entries if e not in same_type]
                if skipped:
                    QgsMessageLog.logMessage(
                        f"Group '{group_name}': skipped {', '.join(skipped)} "
                        f"(structure type differs from group)",
                        'Linear Geoscience', Qgis.Warning)
                if not same_type:
                    continue

                display = group_name + suffix
                _, _, domain, dataset_name = same_type[0]
                total_n = sum(len(sub[e[0]]) for e in same_type)
                user_data = {
                    "is_group": True,
                    "group": group_name,
                    "display": display,
                    "dataset_idx": dataset_idx,
                    "struct_type": struct_type,
                    "code": group_name,
                    "domain": domain,
                    "dataset_name": dataset_name,
                }
                parent = self._make_group_parent_item(
                    self.category_tree_domains, user_data,
                    f"{display} (n={total_n})", struct_type, saved_analysis)
                for st, base_code, e_domain, e_dataset_name in same_type:
                    n = len(sub[st])
                    self._add_group_child_item(
                        parent, f"{st} (n={n})",
                        (st, dataset_idx, base_code, e_domain, e_dataset_name))
                parent.setExpanded(True)
                any_data = True

            for st, code, domain, dataset_name in flat_categories:
                struct_type = cmap[st]
                item = QTreeWidgetItem(self.category_tree_domains)

                # Display the category with format "CODE - DOMAIN (Dataset)"
                item_text = st
                item.setText(0, item_text)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                item.setCheckState(0, Qt.Unchecked)

                # Store full category string, dataset index, and parsed components for sorting
                item.setData(0, Qt.UserRole, (st, dataset_idx, code, domain, dataset_name))
                self._init_item_analysis_columns(item, saved_analysis.get((st, dataset_idx)))

                if struct_type == "plane":
                    combo = QComboBox()
                    combo.addItem("Poles Only")
                    combo.addItem("Planes Only")
                    combo.addItem("Both")
                    self.category_tree_domains.setItemWidget(item, 1, combo)
                else:
                    line_label = QLabel("(Line)")
                    self.category_tree_domains.setItemWidget(item, 1, line_label)
                any_data = True

        # Re-enable sorting after population
        self.category_tree_domains.setSortingEnabled(True)

        return any_data


    def _parse_domain_category(self, st, dataset_idx):
        """Parse a domains-tab category string "CODE - DOMAIN (DATASET)" into
        (code, domain, dataset_name); empty strings where parts are absent."""
        code = ""
        domain = ""
        dataset_name = ""
        if " - " in st:
            parts = st.split(" - ", 1)
            code = parts[0]
            remainder = parts[1]
            # Extract domain and dataset from "DOMAIN (DATASET)"
            if " (" in remainder and remainder.endswith(")"):
                domain = remainder.split(" (")[0]
                dataset_name = remainder.split(" (")[1][:-1]  # Remove closing parenthesis
            else:
                domain = remainder
                dataset_name = self.dataset_configs[dataset_idx]["name"]
        return code, domain, dataset_name


    def sort_domains_tree(self, sort_by):
        """Sort the domains tree by code, domain, or dataset"""
        if not self.category_tree_domains:
            return

        QgsMessageLog.logMessage(f"Sorting domains tree by: {sort_by}", 'Linear Geoscience', Qgis.Info)

        # Disable sorting temporarily to avoid interference
        self.category_tree_domains.setSortingEnabled(False)

        # Collect all items with their data
        items_data = []
        for i in range(self.category_tree_domains.topLevelItemCount()):
            item = self.category_tree_domains.topLevelItem(i)
            data = item.data(0, Qt.UserRole)
            if isinstance(data, dict) and data.get("is_group"):
                # Group parent: capture its own state plus the children
                widget = self.category_tree_domains.itemWidget(item, 1)
                plot_mode = widget.currentText() if isinstance(widget, QComboBox) else None
                children = []
                for j in range(item.childCount()):
                    child = item.child(j)
                    children.append({
                        'label': child.text(0),
                        'data': child.data(0, Qt.UserRole),
                        'check_state': child.checkState(0),
                    })
                items_data.append({
                    'group_data': data,
                    'st': data['display'],
                    'dataset_idx': data['dataset_idx'],
                    'code': data['code'],
                    'domain': data['domain'],
                    'dataset_name': data['dataset_name'],
                    'struct_type': data['struct_type'],
                    'plot_mode': plot_mode,
                    'analysis_states': tuple(item.checkState(col) for col in ANALYSIS_COLUMNS),
                    'label': item.text(0),
                    'children': children,
                })
            elif isinstance(data, tuple) and len(data) >= 5:
                st, dataset_idx, code, domain, dataset_name = data
                check_state = item.checkState(0)
                struct_type = self.category_structure_map_domains[dataset_idx][st]

                # Preserve the plot-mode combo selection across the rebuild
                widget = self.category_tree_domains.itemWidget(item, 1)
                plot_mode = widget.currentText() if isinstance(widget, QComboBox) else None

                items_data.append({
                    'st': st,
                    'dataset_idx': dataset_idx,
                    'code': code,
                    'domain': domain,
                    'dataset_name': dataset_name,
                    'check_state': check_state,
                    'struct_type': struct_type,
                    'plot_mode': plot_mode,
                    'analysis_states': tuple(item.checkState(col) for col in ANALYSIS_COLUMNS)
                })

        # Sort based on the selected criterion
        if sort_by == "code":
            items_data.sort(key=lambda x: (x['code'].upper(), x['domain'].upper(), x['dataset_name'].upper()))
        elif sort_by == "domain":
            items_data.sort(key=lambda x: (x['domain'].upper(), x['code'].upper(), x['dataset_name'].upper()))
        elif sort_by == "dataset":
            items_data.sort(key=lambda x: (x['dataset_name'].upper(), x['code'].upper(), x['domain'].upper()))

        # Clear and rebuild the tree with sorted items
        self.category_tree_domains.clear()

        for item_data in items_data:
            if 'group_data' in item_data:
                # Recreate the group parent + its children; the parent
                # check state recomputes from children via auto-tristate
                gd = item_data['group_data']
                saved = {self._group_state_key(gd['display'], gd['dataset_idx']):
                         item_data['analysis_states']}
                parent = self._make_group_parent_item(
                    self.category_tree_domains, gd, item_data['label'],
                    item_data['struct_type'], saved, item_data['plot_mode'])
                for child_data in item_data['children']:
                    self._add_group_child_item(
                        parent, child_data['label'], child_data['data'],
                        child_data['check_state'])
                parent.setExpanded(True)
                continue

            item = QTreeWidgetItem(self.category_tree_domains)
            item.setText(0, item_data['st'])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            item.setCheckState(0, item_data['check_state'])

            # Store data for future sorting
            item.setData(0, Qt.UserRole, (
                item_data['st'],
                item_data['dataset_idx'],
                item_data['code'],
                item_data['domain'],
                item_data['dataset_name']
            ))
            self._init_item_analysis_columns(item, item_data['analysis_states'])

            # Add plot type widget
            if item_data['struct_type'] == "plane":
                combo = QComboBox()
                combo.addItem("Poles Only")
                combo.addItem("Planes Only")
                combo.addItem("Both")
                if item_data['plot_mode']:
                    mode_index = combo.findText(item_data['plot_mode'])
                    if mode_index >= 0:
                        combo.setCurrentIndex(mode_index)
                self.category_tree_domains.setItemWidget(item, 1, combo)
            else:
                line_label = QLabel("(Line)")
                self.category_tree_domains.setItemWidget(item, 1, line_label)

        # Don't re-enable sorting - keep the custom sort order
        # (If we re-enable, Qt will auto-sort by column 0 text which starts with CODE)

        QgsMessageLog.logMessage(f"Sorted {len(items_data)} items by {sort_by}", 'Linear Geoscience', Qgis.Info)


    ########################################################################
    # Live View Methods
    ########################################################################


    def update_data_live_view(self, dataset_index, canvas_extent):
        """Update live view data for specified dataset based on current map extent"""
        from qgis.core import QgsFeatureRequest, QgsCoordinateTransform, QgsProject

        layer = self.get_layer(dataset_index)
        if not layer:
            QgsMessageLog.logMessage(f"update_data_live_view: No valid layer selected for Dataset {dataset_index + 1}.", 'Linear Geoscience', Qgis.Info)
            return

        # Get field selection combo boxes
        dip_combo = self.dataset_configs[dataset_index].get("dip_combo")
        dipdir_combo = self.dataset_configs[dataset_index].get("dipdir_combo")
        subtype_combo = self.dataset_configs[dataset_index].get("subtype_combo")

        if not all([dip_combo, dipdir_combo, subtype_combo]):
            QgsMessageLog.logMessage(f"Configuration error: One or more field combo boxes are missing for Dataset {dataset_index + 1}", 'Linear Geoscience', Qgis.Warning)
            return

        # Get selected field names
        dip_field = dip_combo.currentText()
        dipdir_field = dipdir_combo.currentText()
        subtype_field = subtype_combo.currentText()

        if not all([dip_field, dipdir_field, subtype_field]):
            QgsMessageLog.logMessage(f"[Dataset {dataset_index + 1} Live View] Essential fields not selected.", 'Linear Geoscience', Qgis.Info)
            return

        # Transform extent to layer CRS if needed
        map_crs = self.map_canvas.mapSettings().destinationCrs()
        layer_crs = layer.crs()

        if map_crs != layer_crs:
            transform = QgsCoordinateTransform(map_crs, layer_crs, QgsProject.instance())
            try:
                transformed_extent = transform.transformBoundingBox(canvas_extent)
            except Exception:
                QgsMessageLog.logMessage(f"Failed to transform extent for dataset {dataset_index + 1}", 'Linear Geoscience', Qgis.Warning)
                return
        else:
            transformed_extent = canvas_extent

        # Create spatial filter request
        request = QgsFeatureRequest().setFilterRect(transformed_extent)

        found_categories = 0
        processed_points_count = 0
        added_points_count = 0
        out_of_range_count = 0

        # Process features within the current extent
        for f in layer.getFeatures(request):
            processed_points_count += 1

            try:
                sv = f.attribute(subtype_field)
                dv = f.attribute(dip_field)
                ddv = f.attribute(dipdir_field)

                if sv is None or dv is None or ddv is None or str(sv).strip() == '' or str(dv).strip() == '' or str(
                        ddv).strip() == '':
                    continue

                dip, dipdir = float(dv), float(ddv)
            except (ValueError, TypeError):
                continue

            if not (isinstance(dip, (int, float)) and isinstance(dipdir, (int, float))):
                continue

            # Range check (warn but keep the point - may indicate a field mix-up)
            if not (0 <= dip <= 90) or not (0 <= dipdir <= 360):
                out_of_range_count += 1

            unified = unify_fax_code(str(sv).upper())
            struct_type = classify_code(unified)
            if not struct_type:
                continue

            # Get geometry for coordinates
            geom = f.geometry()
            if geom and not geom.isEmpty():
                point = geom.asPoint()
                x_coord = point.x()
                y_coord = point.y()
            else:
                x_coord = None
                y_coord = None

            pitch_val = None
            # Find pitch field case-insensitively
            fields_in_layer = {f.name() for f in layer.fields()}
            pitch_field_name = next((name for name in fields_in_layer if name.lower() == "pitch"), None)
            if pitch_field_name:
                tmp = f.attribute(pitch_field_name)
                if tmp not in (None, "NULL", ""):
                    try:
                        pitch_val = float(tmp)
                    except (ValueError, TypeError):
                        pass

            data_dict = {
                "dip": dip,
                "dipdir": dipdir,
                "pitch": pitch_val,
                "dataset": dataset_index,
                "feature_id": f.id(),
                "x": x_coord,
                "y": y_coord
            }

            if unified not in self.subtype_dict_live_view[dataset_index]:
                self.subtype_dict_live_view[dataset_index][unified] = []
                self.category_structure_map_live_view[dataset_index][unified] = struct_type
                found_categories += 1

            self.subtype_dict_live_view[dataset_index][unified].append(data_dict)
            added_points_count += 1

        QgsMessageLog.logMessage(
            f"[Dataset {dataset_index + 1} Live View] Processed {processed_points_count} features, added {added_points_count} valid data points.", 'Linear Geoscience', Qgis.Info)
        QgsMessageLog.logMessage(f"[Dataset {dataset_index + 1} Live View] Found {found_categories} categories from visible features.", 'Linear Geoscience', Qgis.Info)

        if out_of_range_count:
            # Log only (no message bar) - live view refreshes on every map pan
            QgsMessageLog.logMessage(
                f"[Dataset {dataset_index + 1} Live View] {out_of_range_count} measurement(s) have dip outside "
                f"0-90 or dip direction outside 0-360; they are plotted as-is - check field mapping.",
                'Linear Geoscience', Qgis.Warning)


    def rebuild_category_tree_live_view(self):
        """
        Rebuild the live view category tree with ALL available categories.
        This maintains persistent categories that stay visible regardless of map extent.
        Called when datasets change or when live view is first enabled.
        """
        if not self.category_tree_live_view:
            return False

        QgsMessageLog.logMessage("Rebuilding live view category tree with all available categories...", 'Linear Geoscience', Qgis.Info)

        # Store current check states, plot modes and analysis toggles before clearing
        current_check_states = {}
        current_plot_modes = {}
        saved_analysis = self._capture_tree_analysis_states(self.category_tree_live_view)

        for i in range(self.category_tree_live_view.topLevelItemCount()):
            item = self.category_tree_live_view.topLevelItem(i)
            data = item.data(0, Qt.UserRole)
            if isinstance(data, tuple):
                code_str, dataset_idx = data
                # Store check state
                current_check_states[(code_str, dataset_idx)] = item.checkState(0)

                # Store plot mode if it's a plane
                widget = self.category_tree_live_view.itemWidget(item, 1)
                if isinstance(widget, QComboBox):
                    current_plot_modes[(code_str, dataset_idx)] = widget.currentText()
            elif isinstance(data, dict) and data.get("is_group"):
                # Group parent: keep its plot mode (keyed by group state key,
                # parent check state recomputes from children) and the
                # children's check states (children carry plain code tuples)
                widget = self.category_tree_live_view.itemWidget(item, 1)
                if isinstance(widget, QComboBox):
                    gkey = self._group_state_key(data["display"], data["dataset_idx"])
                    current_plot_modes[gkey] = widget.currentText()
                for j in range(item.childCount()):
                    child = item.child(j)
                    cdata = child.data(0, Qt.UserRole)
                    if isinstance(cdata, tuple):
                        current_check_states[(cdata[0], cdata[1])] = child.checkState(0)

        # Clear the tree
        self.category_tree_live_view.clear()

        # Initialize live view data structures
        for i in range(2):
            if not hasattr(self, 'subtype_dict_live_view') or len(self.subtype_dict_live_view) <= i:
                # Initialize if not exists
                if not hasattr(self, 'subtype_dict_live_view'):
                    self.subtype_dict_live_view = [{}, {}]
                if not hasattr(self, 'category_structure_map_live_view'):
                    self.category_structure_map_live_view = [{}, {}]

            # Clear existing data but preserve structure
            self.subtype_dict_live_view[i].clear()
            self.category_structure_map_live_view[i].clear()

        # Collect ALL available categories from both Selection and Domains tabs
        all_categories = {}  # {(code, dataset_idx): struct_type}

        # From Selection tab - get all available categories
        for dataset_idx in range(2):
            if not self.dataset_configs[dataset_idx]["enabled"]:
                continue

            # Add all categories from selection data
            for code in self.category_structure_map_selection[dataset_idx]:
                struct_type = self.category_structure_map_selection[dataset_idx][code]
                all_categories[(code, dataset_idx)] = struct_type

                # Initialize empty data list in live view
                self.subtype_dict_live_view[dataset_idx][code] = []
                self.category_structure_map_live_view[dataset_idx][code] = struct_type

        # From Domains tab - add any additional categories
        for dataset_idx in range(2):
            if not self.dataset_configs[dataset_idx]["enabled"]:
                continue

            for domain_code in self.category_structure_map_domains[dataset_idx]:
                struct_type = self.category_structure_map_domains[dataset_idx][domain_code]

                # Extract base code (remove domain suffix for live view)
                base_code = domain_code
                if " - " in domain_code:
                    base_code = domain_code.split(" - ")[0]

                # Add if not already present from selection tab
                if (base_code, dataset_idx) not in all_categories:
                    all_categories[(base_code, dataset_idx)] = struct_type

                    # Initialize empty data list in live view
                    if base_code not in self.subtype_dict_live_view[dataset_idx]:
                        self.subtype_dict_live_view[dataset_idx][base_code] = []
                        self.category_structure_map_live_view[dataset_idx][base_code] = struct_type

        # Create tree items for all categories (grouped codes become a parent
        # with member-code children, mirroring the Selection tree). Combined
        # mode shows one row per code across both datasets.
        if self._combined_mode():
            type_of = {}
            for (c, d), t in all_categories.items():
                type_of.setdefault(c, t)
            code_views = [(0, sorted(type_of.keys()), None, type_of)]
        else:
            code_views = []
            for ds in range(2):
                ds_codes = sorted(c for (c, d) in all_categories if d == ds)
                type_of = {c: all_categories[(c, ds)] for c in ds_codes}
                code_views.append((ds, ds_codes, self.dataset_configs[ds]["name"], type_of))

        any_data = False
        for dataset_idx, ds_codes, dataset_name, type_of in code_views:
            if not ds_codes:
                continue
            grouped, ungrouped = self._partition_codes_by_group(ds_codes)

            for group_name, members in grouped.items():
                struct_type = type_of[members[0]]
                same_type = [c for c in members
                             if type_of.get(c) == struct_type]
                skipped = [c for c in members if c not in same_type]
                if skipped:
                    QgsMessageLog.logMessage(
                        f"Group '{group_name}': skipped {', '.join(skipped)} "
                        f"(structure type differs from group)",
                        'Linear Geoscience', Qgis.Warning)
                if not same_type:
                    continue

                user_data = {
                    "is_group": True,
                    "group": group_name,
                    "display": group_name,
                    "dataset_idx": dataset_idx,
                    "struct_type": struct_type,
                }
                gkey = self._group_state_key(group_name, dataset_idx)
                parent_label = (group_name if dataset_name is None
                                else f"{group_name} [{dataset_name}]")
                parent = self._make_group_parent_item(
                    self.category_tree_live_view, user_data,
                    parent_label,
                    struct_type, saved_analysis,
                    current_plot_modes.get(gkey))
                for c in same_type:
                    self._add_group_child_item(
                        parent, c, (c, dataset_idx),
                        current_check_states.get((c, dataset_idx), Qt.Unchecked))
                parent.setExpanded(True)
                any_data = True

            for code_str in ungrouped:
                struct_type = type_of[code_str]
                item = QTreeWidgetItem(self.category_tree_live_view)

                # Add dataset name to differentiate (omitted in combined mode)
                item_text = (code_str if dataset_name is None
                             else f"{code_str} [{dataset_name}]")
                item.setText(0, item_text)

                # Set item properties
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)

                # Restore previous check state if it exists, otherwise default to unchecked
                if (code_str, dataset_idx) in current_check_states:
                    item.setCheckState(0, current_check_states[(code_str, dataset_idx)])
                else:
                    item.setCheckState(0, Qt.Unchecked)

                # Store both code and dataset index
                item.setData(0, Qt.UserRole, (code_str, dataset_idx))
                self._init_item_analysis_columns(item, saved_analysis.get((code_str, dataset_idx)))

                # Create appropriate widget for column 1 based on structure type
                if struct_type == "plane":
                    combo = QComboBox()
                    combo.addItem("Poles Only")
                    combo.addItem("Planes Only")
                    combo.addItem("Both")

                    # Restore previous plot mode if available
                    if (code_str, dataset_idx) in current_plot_modes:
                        saved_mode = current_plot_modes[(code_str, dataset_idx)]
                        index = combo.findText(saved_mode)
                        if index >= 0:
                            combo.setCurrentIndex(index)

                    self.category_tree_live_view.setItemWidget(item, 1, combo)
                else:
                    # For lines, just show a label
                    line_label = QLabel("(Line)")
                    self.category_tree_live_view.setItemWidget(item, 1, line_label)

                any_data = True

        # Resize columns for better display
        self.category_tree_live_view.resizeColumnToContents(0)
        self.category_tree_live_view.resizeColumnToContents(1)

        total_categories = len(all_categories)
        enabled_datasets = sum(1 for i in range(2) if self.dataset_configs[i]["enabled"])

        QgsMessageLog.logMessage(f"Live view rebuilt with {total_categories} categories from {enabled_datasets} enabled datasets", 'Linear Geoscience', Qgis.Info)

        return any_data


    def rebuild_category_tree_live_view_domains(self):
        """
        Rebuild the live view category tree with domain categories.
        Called when domain mode is enabled.
        Categories are shown with domain suffixes like "BDS - Domain1".
        All categories start unchecked - user must select which to plot.
        """
        if not self.category_tree_live_view:
            return False

        QgsMessageLog.logMessage("Rebuilding live view category tree with domain categories...", 'Linear Geoscience', Qgis.Info)

        # Preserve analysis toggles across the rebuild
        saved_analysis = self._capture_tree_analysis_states(self.category_tree_live_view)

        # Clear the tree
        self.category_tree_live_view.clear()

        # Initialize live view data structures
        for i in range(2):
            self.subtype_dict_live_view[i].clear()
            self.category_structure_map_live_view[i].clear()

        # Get ALL domain categories from the Domains tab
        all_domain_categories = {}  # {(domain_code, dataset_idx): struct_type}

        for dataset_idx in range(2):
            if not self.dataset_configs[dataset_idx]["enabled"]:
                QgsMessageLog.logMessage(f"[Dataset {dataset_idx + 1}] Not enabled, skipping", 'Linear Geoscience', Qgis.Info)
                continue

            # Check if domain field is configured
            domain_combo = self.dataset_configs[dataset_idx].get("domain_combo")
            if not domain_combo or not domain_combo.currentText():
                QgsMessageLog.logMessage(f"[Dataset {dataset_idx + 1}] Domain field not configured, skipping", 'Linear Geoscience', Qgis.Info)
                continue

            QgsMessageLog.logMessage(f"[Dataset {dataset_idx + 1}] Domain field configured: '{domain_combo.currentText()}'", 'Linear Geoscience', Qgis.Info)
            QgsMessageLog.logMessage(f"[Dataset {dataset_idx + 1}] Domains dict has {len(self.category_structure_map_domains[dataset_idx])} entries", 'Linear Geoscience', Qgis.Info)

            # Get all domain categories from the Domains tab
            for domain_code in self.category_structure_map_domains[dataset_idx]:
                struct_type = self.category_structure_map_domains[dataset_idx][domain_code]
                all_domain_categories[(domain_code, dataset_idx)] = struct_type

                if len(all_domain_categories) <= 5:  # Only log first 5
                    QgsMessageLog.logMessage(f"    Added domain category: '{domain_code}' ({struct_type})", 'Linear Geoscience', Qgis.Info)

                # Initialize empty data list in live view
                self.subtype_dict_live_view[dataset_idx][domain_code] = []
                self.category_structure_map_live_view[dataset_idx][domain_code] = struct_type

        # Bucket grouped domain categories by (group, domain suffix); the rest
        # stay flat. Suffix keeps the "CODE - DOMAIN (Dataset)" formatting.
        # Combined mode strips the dataset suffix so the same code+domain
        # from both datasets shows as one row.
        combined = self._combined_mode()
        group_buckets = {}   # (group_name, suffix, dataset_idx) -> [display_code]
        flat_categories = []
        flat_seen = set()
        domain_type = {}     # display key -> struct type (first wins)
        for (domain_code, dataset_idx), struct_type in sorted(all_domain_categories.items()):
            display_code = self._strip_dataset_suffix(domain_code) if combined else domain_code
            out_ds = 0 if combined else dataset_idx
            domain_type.setdefault(display_code, struct_type)
            base_code = display_code.split(" - ")[0] if " - " in display_code else display_code
            group_name = self.get_group_for_code(base_code)
            if group_name:
                suffix = display_code[len(base_code):]
                bucket = group_buckets.setdefault((group_name, suffix, out_ds), [])
                if display_code not in bucket:
                    bucket.append(display_code)
            else:
                if (display_code, out_ds) not in flat_seen:
                    flat_seen.add((display_code, out_ds))
                    flat_categories.append((display_code, out_ds, struct_type))

        # Create tree items for all domain categories
        any_data = False
        for (group_name, suffix, dataset_idx), members in group_buckets.items():
            struct_type = domain_type[members[0]]
            same_type = [dc for dc in members
                         if domain_type.get(dc) == struct_type]
            skipped = [dc for dc in members if dc not in same_type]
            if skipped:
                QgsMessageLog.logMessage(
                    f"Group '{group_name}': skipped {', '.join(skipped)} "
                    f"(structure type differs from group)",
                    'Linear Geoscience', Qgis.Warning)
            if not same_type:
                continue

            display = group_name + suffix
            user_data = {
                "is_group": True,
                "group": group_name,
                "display": display,
                "dataset_idx": dataset_idx,
                "struct_type": struct_type,
            }
            parent = self._make_group_parent_item(
                self.category_tree_live_view, user_data, display,
                struct_type, saved_analysis)
            for dc in same_type:
                self._add_group_child_item(parent, dc, (dc, dataset_idx))
            parent.setExpanded(True)
            any_data = True

        for domain_code, dataset_idx, struct_type in flat_categories:
            item = QTreeWidgetItem(self.category_tree_live_view)

            # Domain code already includes dataset name in format "CODE - DOMAIN (Dataset)"
            # So we can use it directly
            item_text = domain_code
            item.setText(0, item_text)

            # Set item properties
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)

            # Start all categories unchecked - user selects what to plot
            item.setCheckState(0, Qt.Unchecked)

            # Store both code and dataset index
            item.setData(0, Qt.UserRole, (domain_code, dataset_idx))
            self._init_item_analysis_columns(item, saved_analysis.get((domain_code, dataset_idx)))

            # Create appropriate widget for column 1 based on structure type
            if struct_type == "plane":
                combo = QComboBox()
                combo.addItem("Poles Only")
                combo.addItem("Planes Only")
                combo.addItem("Both")
                self.category_tree_live_view.setItemWidget(item, 1, combo)
            else:
                # For lines, just show a label
                line_label = QLabel("(Line)")
                self.category_tree_live_view.setItemWidget(item, 1, line_label)

            any_data = True

        # Resize columns for better display
        self.category_tree_live_view.resizeColumnToContents(0)
        self.category_tree_live_view.resizeColumnToContents(1)

        total_categories = len(all_domain_categories)
        enabled_datasets = sum(1 for i in range(2) if self.dataset_configs[i]["enabled"])

        QgsMessageLog.logMessage(f"Live view domain mode rebuilt with {total_categories} domain categories from {enabled_datasets} enabled datasets", 'Linear Geoscience', Qgis.Info)

        # If no domain categories found, warn user
        if total_categories == 0:
            QgsMessageLog.logMessage("WARNING: No domain categories found. Please:", 'Linear Geoscience', Qgis.Warning)
            QgsMessageLog.logMessage("  1. Ensure domain field is configured in Configuration tab", 'Linear Geoscience', Qgis.Info)
            QgsMessageLog.logMessage("  2. Go to Domains tab and click 'Refresh Domains' button", 'Linear Geoscience', Qgis.Info)
            QgsMessageLog.logMessage("  3. Then enable domain mode in Live View", 'Linear Geoscience', Qgis.Info)

        return any_data

    ########################################################################
    # Plotting
    ########################################################################


    # =========================================================================
    # PLOT GENERATION METHODS
    # =========================================================================

    ########################################################################
    # Categories Tab
    ########################################################################


    def request_plot_update(self, *args):
        """Debounced entry point for UI-driven replots; coalesces rapid toggles."""
        if hasattr(self, 'plot_update_timer') and self.plot_update_timer is not None:
            self.plot_update_timer.start()
        else:
            self.update_plot()

    def _combine_datasets_plotted(self, plotted_data, analysis_flags):
        """Merge plotted categories with the same code across datasets into
        single ds-0 entries (the 'Combine datasets' option).

        Domain-mode keys embed the dataset name ("CODE - DOM (Dataset 1)") —
        the suffix is stripped so the same code+domain merges. All merged
        entries get dataset_idx 0, which flips single_dataset_mode on
        downstream (no dataset labels, no hollow markers). BF/Ct/Mn flags
        OR-merge; first-seen plot mode and colour win.
        """
        merged = {}      # (key, ds) -> [key, struct, data, plot_mode, ds, color]
        new_flags = {}
        for (code_str, struct_type, data_list, plot_mode, ds, color) in plotted_data:
            key = code_str
            for d in range(2):
                suffix = f" ({self.dataset_configs[d]['name']})"
                if key.endswith(suffix):
                    key = key[:-len(suffix)]
                    break
            dict_key = (key, 0)
            out_ds = 0
            if dict_key in merged and merged[dict_key][1] != struct_type:
                # Same code classified differently per dataset: keep this
                # entry separate under its own dataset index
                dict_key = (code_str, ds)
                key = code_str
                out_ds = ds
            if dict_key not in merged:
                merged[dict_key] = [key, struct_type, list(data_list),
                                    plot_mode, out_ds, color]
            else:
                merged[dict_key][2].extend(data_list)
            old = analysis_flags.get((code_str, ds), (True, True, True))
            cur = new_flags.get((key, out_ds), (False, False, False))
            new_flags[(key, out_ds)] = tuple(a or b for a, b in zip(old, cur))
        return [tuple(v) for v in merged.values()], new_flags

    def _combined_mode(self):
        """True when the Datasets-tab 'Combine datasets' option is on."""
        return bool(self.combine_datasets_checkbox
                    and self.combine_datasets_checkbox.isChecked())

    def _strip_dataset_suffix(self, key):
        """Remove a trailing ' (DatasetName)' from a category key, if any."""
        for ds in range(2):
            suffix = f" ({self.dataset_configs[ds]['name']})"
            if key.endswith(suffix):
                return key[:-len(suffix)]
        return key

    def _resolve_ds_key(self, dict_list, ds, key):
        """Per-dataset dict key for a (possibly dataset-stripped) category
        key: the key itself, its '(DatasetName)'-suffixed variant, or None."""
        if key in dict_list[ds]:
            return key
        suffixed = f"{key} ({self.dataset_configs[ds]['name']})"
        return suffixed if suffixed in dict_list[ds] else None

    def _combined_category_data(self, dict_list, key):
        """Concatenated category data across all enabled datasets."""
        out = []
        for ds in range(2):
            if not self.dataset_configs[ds]["enabled"]:
                continue
            k = self._resolve_ds_key(dict_list, ds, key)
            if k is not None:
                out.extend(dict_list[ds][k])
        return out

    def _merged_view(self, dict_list, map_list, strip_suffix=False):
        """Union the per-dataset subtype dicts / category maps of enabled
        datasets into one (subtype_dict, category_map) pair for combined
        mode. strip_suffix removes ' (DatasetName)' from keys (domains-style
        dicts). Data lists concatenate per merged key; first-seen type wins
        (classification is global, so types agree across datasets)."""
        merged_data = {}
        merged_map = {}
        for ds in range(2):
            if not self.dataset_configs[ds]["enabled"]:
                continue
            for key in dict_list[ds]:
                out_key = self._strip_dataset_suffix(key) if strip_suffix else key
                merged_data.setdefault(out_key, []).extend(dict_list[ds][key])
                if out_key not in merged_map and key in map_list[ds]:
                    merged_map[out_key] = map_list[ds][key]
        return merged_data, merged_map

    def _on_combine_datasets_toggled(self, *args):
        """Rebuild all category trees in the new mode, then replot."""
        self.rebuild_category_tree_selection()
        self.rebuild_category_tree_domains()
        if self.live_view_enabled:
            if (getattr(self, 'live_view_by_domain_checkbox', None) is not None
                    and self.live_view_by_domain_checkbox.isChecked()):
                self.rebuild_category_tree_live_view_domains()
            else:
                self.rebuild_category_tree_live_view()
                self.update_live_view_data()
        self.request_plot_update()

    def update_plot(self):
        if not self.categories_tabwidget:
            QgsMessageLog.logMessage("update_plot: categories tab not built yet.", 'Linear Geoscience', Qgis.Info)
            return

        # Determine which data source to use
        if self.live_view_enabled:
            # Use live view data
            subtype_dict = self.subtype_dict_live_view
            category_map = self.category_structure_map_live_view
            tree_widget = self.category_tree_live_view
            tab_name = "[Live View]"
        else:
            # Use existing logic for selection/domains tabs
            tab_index = self.categories_tabwidget.currentIndex()
            if tab_index == 0:
                # "Selection"
                subtype_dict = self.subtype_dict_selection
                category_map = self.category_structure_map_selection
                tree_widget = self.category_tree_selection
                tab_name = "[Selection]"
            elif tab_index == 1:
                # "Domains"
                subtype_dict = self.subtype_dict_domains
                category_map = self.category_structure_map_domains
                tree_widget = self.category_tree_domains
                tab_name = "[Domains]"
            else:
                # "Live View" tab but live view not enabled
                if self.plot_label:
                    self.plot_label.setText("Enable 'Show visible features on map' to use Live View.")
                self.show_empty_plot()
                return

        if not any(subtype_dict[i] for i in range(len(subtype_dict))):
            if self.plot_label:
                self.plot_label.setText(f"No valid data in {tab_name} to plot. Try 'Refresh Selection'.")
            self.show_empty_plot()
            return

        # ----------------------------------------------------------------------
        # Gather which categories are checked
        combined = self._combined_mode()
        plotted_data = []
        analysis_flags = {}
        for i in range(tree_widget.topLevelItemCount()):
            item = tree_widget.topLevelItem(i)
            data = item.data(0, Qt.UserRole)

            if isinstance(data, dict) and data.get("is_group"):
                # Group parent: merge the checked children's data into one
                # plotted category. PartiallyChecked parents must pass.
                if item.checkState(0) == Qt.Unchecked:
                    continue
                merged = []
                for j in range(item.childCount()):
                    child = item.child(j)
                    if child.checkState(0) != Qt.Checked:
                        continue
                    cdata = child.data(0, Qt.UserRole)
                    if combined:
                        merged.extend(self._combined_category_data(subtype_dict, cdata[0]))
                    else:
                        merged.extend(subtype_dict[cdata[1]].get(cdata[0], []))
                if not merged:
                    continue
                code_str = data["display"]
                dataset_idx = data["dataset_idx"]
                struct_type = data["struct_type"]
                if struct_type == "plane":
                    w = tree_widget.itemWidget(item, 1)
                    plot_mode = w.currentText() if isinstance(w, QComboBox) else "Poles Only"
                else:
                    plot_mode = "Line"
                plotted_data.append((code_str, struct_type, merged, plot_mode,
                                     dataset_idx, self.dataset_configs[dataset_idx]["color"]))
                analysis_flags[(code_str, dataset_idx)] = (
                    item.checkState(COL_BF) == Qt.Checked,
                    item.checkState(COL_CT) == Qt.Checked,
                    item.checkState(COL_MN) == Qt.Checked,
                )
                continue

            if item.checkState(0) == Qt.Checked:
                # Get both code and dataset index
                if isinstance(data, tuple):
                    if len(data) >= 5:
                        # New format: (st, dataset_idx, code, domain, dataset_name)
                        code_str, dataset_idx = data[0], data[1]
                    else:
                        # Old format: (code_str, dataset_idx)
                        code_str, dataset_idx = data
                else:
                    # For backward compatibility
                    code_str = data
                    dataset_idx = 0

                # Get data based on current mode
                if combined:
                    # Merged rows: gather data across enabled datasets and
                    # resolve "(DatasetName)"-suffixed keys (Domains mode)
                    struct_type = (category_map[0].get(code_str)
                                   or category_map[1].get(code_str)
                                   or self._classify_base_code(
                                       code_str.split(" - ")[0]
                                       if " - " in code_str else code_str))
                    data_list = self._combined_category_data(subtype_dict, code_str)
                elif self.live_view_enabled:
                    struct_type = category_map[dataset_idx].get(code_str)
                    data_list = subtype_dict[dataset_idx][code_str]
                else:
                    if tab_index == 0:  # Selection tab
                        struct_type = category_map[dataset_idx].get(code_str)
                        data_list = subtype_dict[dataset_idx][code_str]
                    else:  # Domains tab
                        struct_type = category_map[dataset_idx].get(code_str)
                        data_list = subtype_dict[dataset_idx][code_str]

                # Get dataset color
                dataset_color = self.dataset_configs[dataset_idx]["color"]

                if struct_type == "plane":
                    w = tree_widget.itemWidget(item, 1)
                    plot_mode = w.currentText() if isinstance(w, QComboBox) else "Poles Only"
                else:
                    plot_mode = "Line"

                plotted_data.append((code_str, struct_type, data_list, plot_mode, dataset_idx, dataset_color))

                # Per-category analysis toggles (BF/Ct/Mn tree columns)
                analysis_flags[(code_str, dataset_idx)] = (
                    item.checkState(COL_BF) == Qt.Checked,
                    item.checkState(COL_CT) == Qt.Checked,
                    item.checkState(COL_MN) == Qt.Checked,
                )

        if not plotted_data:
            if self.plot_label:
                self.plot_label.setText(f"No categories are checked in {tab_name}.")
            self.show_empty_plot()
            return

        # Combine-datasets option: merge identical codes across datasets
        if self.combine_datasets_checkbox and self.combine_datasets_checkbox.isChecked():
            plotted_data, analysis_flags = self._combine_datasets_plotted(
                plotted_data, analysis_flags)

        self.last_plotted_data = plotted_data
        self.last_analysis_flags = analysis_flags

        # Sort plotted_data based on legend ordering preference
        if self.order_by_domain_checkbox and self.order_by_domain_checkbox.isChecked():
            # Order by domain
            def sort_key(item):
                code_str = item[0]
                # Extract domain from code_str (format: "CODE - DOMAIN" or "CODE - DOMAIN (Dataset Name)")
                if " - " in code_str:
                    domain_part = code_str.split(" - ")[1]
                    if " (" in domain_part:
                        domain = domain_part.split(" (")[0].strip()
                    else:
                        domain = domain_part.strip()
                    # Extract base code
                    base_code = code_str.split(" - ")[0]
                    return (domain, base_code, item[4])  # Sort by domain, then code, then dataset
                else:
                    # No domain, sort by code
                    return (code_str, "", item[4])

            plotted_data = sorted(plotted_data, key=sort_key)
            self.last_plotted_data = plotted_data  # Update after sorting
        else:
            # Order by structure code (default)
            def sort_key(item):
                code_str = item[0]
                # Extract base code without domain
                if " - " in code_str:
                    base_code = code_str.split(" - ")[0]
                    domain_part = code_str.split(" - ")[1]
                    if " (" in domain_part:
                        domain = domain_part.split(" (")[0].strip()
                    else:
                        domain = domain_part.strip()
                    return (base_code, domain, item[4])  # Sort by code, then domain, then dataset
                else:
                    return (code_str, "", item[4])

            plotted_data = sorted(plotted_data, key=sort_key)
            self.last_plotted_data = plotted_data  # Update after sorting

        settings = self._collect_render_settings('screen')

        # Only check for rake conflicts now
        any_analysis = (settings.best_fit_plane or settings.contour_plane or
                        settings.mean_plane or settings.best_fit_line or
                        settings.contour_line or settings.mean_line)
        if settings.rake_enabled and any_analysis:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Plot Conflict",
                "Cannot combine rakes with analysis tools.\nDisable either rakes or analysis."
            )
            if self.plot_label:
                self.plot_label.setText(
                    "Cannot combine rakes with analysis tools - disable one and replot.")
            self.show_empty_plot()
            return

        # Render into the persistent live canvas figure (interactive picking
        # stays wired up); exports keep their own pyplot/Agg figures
        self.plot_figure.clear()
        try:
            _, pick_registry = self._render_stereonet_into(
                self.plot_figure, plotted_data, self.last_analysis_flags, settings)
        except Exception:
            self.plot_label.setText(
                "Plot rendering failed - see the Linear Geoscience log for details.")
            self.show_empty_plot()
            raise
        self.pick_handler.set_plot(pick_registry)
        self.plot_stack.setCurrentWidget(self.plot_canvas)
        self.plot_canvas.draw_idle()
        QgsMessageLog.logMessage("Plot updated successfully with legend properly positioned.", 'Linear Geoscience', Qgis.Info)


    def _collect_render_settings(self, profile):
        """Snapshot the analysis/display settings that drive a stereonet render.

        profile: 'screen' (plot tab - renders into the live canvas figure, so
        the dpi field is unused there), 'svg' or 'clipboard' (300 dpi, honour
        the Transparent checkbox).
        """
        def checked(attr):
            widget = getattr(self, attr, None)
            return widget is not None and widget.isChecked()

        scope_text = self.analysis_scope_combo.currentText() if getattr(self, 'analysis_scope_combo', None) is not None else "All Combined"
        if scope_text == "Per Dataset":
            analysis_scope = 'per_dataset'
        elif scope_text == "Per Code":
            analysis_scope = 'per_code'
        else:
            analysis_scope = 'combined'

        return SimpleNamespace(
            profile=profile,
            dpi=200 if profile == 'screen' else 300,
            transparent=(profile != 'screen' and checked('transparent_svg_checkbox')),
            rake_enabled=checked('rake_checkbox'),
            best_fit_plane=checked('best_fit_plane_checkbox'),
            contour_plane=checked('contour_plane_checkbox'),
            mean_plane=checked('mean_plane_checkbox'),
            mean_plane_type=(self.mean_plane_type_combo.currentText()
                             if getattr(self, 'mean_plane_type_combo', None) else "Pole"),
            best_fit_line=checked('best_fit_line_checkbox'),
            contour_line=checked('contour_line_checkbox'),
            mean_line=checked('mean_line_checkbox'),
            analysis_scope=analysis_scope,
            alternate_mode=checked('alternate_plot_mode_checkbox'),
            intersections_enabled=checked('intersection_contour_checkbox'),
        )

    def _render_stereonet_figure(self, plotted_data, analysis_flags, settings):
        """Build and return the stereonet Figure for the given plotted data.

        The caller owns the returned figure and must plt.close() it.
        On failure the partially built figure is closed before re-raising.
        """
        fig = plt.figure(figsize=(7, 5), dpi=settings.dpi)
        try:
            fig, _pick_registry = self._render_stereonet_into(
                fig, plotted_data, analysis_flags, settings)
            return fig
        except Exception:
            plt.close(fig)
            raise

    def _render_stereonet_into(self, fig, plotted_data, analysis_flags, settings):
        # Determine if we're plotting only a single dataset
        dataset_indices = set(item[4] for item in plotted_data)
        single_dataset_mode = len(dataset_indices) == 1

        # Generate color map based on mode
        if settings.alternate_mode:
            # Alternate mode: color by domain
            structure_color_map = self.generate_structure_color_map_by_domain(plotted_data, single_dataset_mode)
        else:
            # Normal mode: color by code with domain differentiation
            structure_color_map = self.generate_structure_color_map(plotted_data)


        # Per-category collections feeding the analysis overlays, keyed by
        # (code_str, dataset_idx) in plotted order. Insertion order matters:
        # per-code analysis groups keep the first-seen category's colour.
        plane_per_category = {}  # {(code, ds): {"plunges": [], "bearings": [], "color": c}}
        line_per_category = {}

        # Stat lines (best fit / mean / rake text) are collected here and
        # drawn as one block in the right margin after the legend, so they
        # never overlap the stereonet itself
        analysis_stats = []

        # Pick registry for the interactive screen plot: each point artist
        # maps to its source features in point order. Export profiles skip
        # this entirely so their output is untouched.
        interactive = settings.profile == 'screen'
        pick_registry = {}

        def _register_pickable(arts, point_dicts, default_dataset_idx):
            if not (interactive and arts):
                return
            # Per-point dataset (set on each dict) wins over the category's
            # dataset_idx so combined-dataset/group merges resolve correctly
            entries = [
                (d.get("dataset", default_dataset_idx), d.get("feature_id"))
                for d in point_dicts
            ]
            # Distribute entries across the returned artists by each artist's
            # actual point count: ax.pole gives one N-point artist, while
            # ax.line's 2-D input wrapping gives N single-point artists.
            offset = 0
            groups = []
            for art in arts:
                n = len(art.get_xdata())
                groups.append((art, entries[offset:offset + n]))
                offset += n
            if offset != len(entries):
                QgsMessageLog.logMessage(
                    f"Stereonet: {offset} plotted point(s) but {len(entries)} "
                    "measurement(s) in a category - picking disabled for it",
                    'Linear Geoscience', Qgis.Warning)
                return
            for art, art_entries in groups:
                art.set_picker(True)
                art.set_pickradius(6)
                pick_registry[art] = art_entries

        ax = fig.add_subplot(111, projection='stereonet')
        ax.set_azimuth_ticks(range(0, 360, 30))

        # Transparent background for SVG/clipboard exports
        if settings.transparent:
            fig.patch.set_facecolor('none')
            ax.patch.set_facecolor('none')

        # Create color cycle for single dataset mode
        color_cycle = iter(mpl.rcParams['axes.prop_cycle'])

        # Build marker mapping for alternate mode - sequential assignment based on appearance order
        code_to_marker_map = {}
        if settings.alternate_mode:
            # Define marker shapes - simple list for sequential assignment
            marker_shapes = ['o', 's', '^', 'D', '*', 'X', 'p', 'P', 'h', 'H', '8', 'd']

            # Extract unique base codes in order of first appearance
            seen_codes = []
            for (code_str, _, _, _, _, _) in plotted_data:
                # Extract base code without domain suffix or dataset name
                base_code = code_str
                if " - " in base_code:
                    base_code = base_code.split(" - ")[0]
                if " (" in base_code:
                    base_code = base_code.split(" (")[0]

                if base_code not in seen_codes:
                    seen_codes.append(base_code)

            # Assign markers sequentially: first code gets first marker, second gets second, etc.
            for idx, code in enumerate(seen_codes):
                code_to_marker_map[code] = marker_shapes[idx % len(marker_shapes)]

        # FIRST: Plot temporary dataset as background (hollow markers) if it exists
        # BUT ONLY for categories that are currently checked
        # Triple-check: live view enabled, captured flag true, and actual data exists
        if (self.live_view_enabled and 
            self.temporary_dataset_captured and 
            hasattr(self, 'temporary_dataset') and
            self.temporary_dataset and
            any(any(temp_data.values()) for temp_data in self.temporary_dataset if temp_data)):
            temp_color_cycle = iter(mpl.rcParams['axes.prop_cycle'])
            
            # Create temporary plotted data ONLY for currently plotted categories.
            # Derive everything from plotted_data (no tree access) so the same
            # logic serves both the screen plot and the export renders.
            temp_plotted_data = []

            plotted_categories = set()
            for (plot_code_str, _, _, _, plot_dataset_idx, _) in plotted_data:
                plotted_categories.add((plot_code_str, plot_dataset_idx))

            # Only plot temporary data for plotted categories.
            # Known limitation: code-group categories plot under the group
            # name, while temporary data is keyed by individual code, so
            # captured temp data is not overlaid for grouped categories.
            for (code_str, dataset_idx) in plotted_categories:
                if not self.dataset_configs[dataset_idx]["enabled"]:
                    continue

                # Check if we have temporary data for this category
                if (dataset_idx < len(self.temporary_dataset) and
                    code_str in self.temporary_dataset[dataset_idx] and
                    self.temporary_dataset[dataset_idx][code_str]):

                    temp_data_list = self.temporary_dataset[dataset_idx][code_str]

                    # Get structure type and plot mode from the plotted data
                    for (plot_code_str, plot_struct_type, _, plot_plot_mode,
                         plot_dataset_idx, plot_dataset_color) in plotted_data:
                        if plot_code_str == code_str and plot_dataset_idx == dataset_idx:
                            temp_plotted_data.append((code_str, plot_struct_type, temp_data_list,
                                                      plot_plot_mode, dataset_idx, plot_dataset_color))
                            break
            
            # Plot temporary data with hollow markers
            for (temp_code_str, temp_struct_type, temp_data_list, temp_plot_mode, temp_dataset_idx, temp_dataset_color) in temp_plotted_data:
                # Use color map for domain differentiation
                if single_dataset_mode:
                    temp_color = structure_color_map.get((temp_code_str, temp_dataset_idx), None)

                    if temp_color is None:
                        temp_base_code = temp_code_str
                        if " - " in temp_base_code:
                            temp_base_code = temp_base_code.split(" - ")[0]

                        if temp_base_code in self.structure_colors:
                            temp_color = self.structure_colors[temp_base_code]
                        else:
                            try:
                                temp_color = next(temp_color_cycle)['color']
                            except StopIteration:
                                temp_color_cycle = iter(mpl.rcParams['axes.prop_cycle'])
                                temp_color = next(temp_color_cycle)['color']
                else:
                    # Keep full code including domain for color lookup
                    temp_color = structure_color_map.get((temp_code_str, temp_dataset_idx), temp_dataset_color)
                
                temp_n_points = len(temp_data_list)
                temp_dataset_name = self.dataset_configs[temp_dataset_idx]["name"]

                # Strip dataset name from temp_code_str if it's already present (for domain mode)
                temp_display_code = temp_code_str
                if f" ({temp_dataset_name})" in temp_code_str:
                    temp_display_code = temp_code_str.replace(f" ({temp_dataset_name})", "")

                # Create temporary data label
                if single_dataset_mode:
                    temp_label = f"{temp_display_code} (Temp, n={temp_n_points})"
                else:
                    temp_label = f"{temp_display_code} (Temp, {temp_dataset_name}, n={temp_n_points})"

                # Determine marker for temporary data based on mode
                if settings.alternate_mode:
                    # Alternate mode: shape by code using sequential mapping
                    temp_base_code = temp_code_str
                    if " - " in temp_base_code:
                        temp_base_code = temp_base_code.split(" - ")[0]
                    if " (" in temp_base_code:
                        temp_base_code = temp_base_code.split(" (")[0]
                    temp_marker = code_to_marker_map.get(temp_base_code, 'o')
                else:
                    # Normal mode: standard shapes
                    if temp_struct_type == "line":
                        temp_marker = '^'
                    else:
                        temp_marker = 'o'

                # Plot temporary data with hollow markers
                if temp_struct_type == "line":
                    temp_plunges = [d["dip"] for d in temp_data_list]
                    temp_bearings = [d["dipdir"] for d in temp_data_list]

                    # Hollow markers for temporary lines
                    ax.line(temp_plunges, temp_bearings, marker=temp_marker, markersize=5,
                            linestyle='none', color=temp_color, markerfacecolor='none',
                            markeredgecolor=temp_color, alpha=0.7, markeredgewidth=1.5)
                    ax.plot([], [], marker=temp_marker, color=temp_color, markersize=5,
                           markerfacecolor='none', markeredgecolor=temp_color,
                           alpha=0.7, markeredgewidth=1.5, label=temp_label)

                else:  # temp_struct_type == "plane"
                    temp_strikes = []
                    temp_dips = []
                    for temp_d_dict in temp_data_list:
                        temp_s_val = dip_direction_to_strike(temp_d_dict['dipdir'])
                        temp_strikes.append(temp_s_val)
                        temp_dips.append(temp_d_dict['dip'])

                    if temp_plot_mode in ["Poles Only", "Both"]:
                        # Hollow markers for temporary poles
                        ax.pole(temp_strikes, temp_dips, marker=temp_marker, markersize=5,
                                linestyle='none', color=temp_color, markerfacecolor='none',
                                markeredgecolor=temp_color, alpha=0.7, markeredgewidth=1.5)
                        ax.plot([], [], marker=temp_marker, color=temp_color, markersize=5,
                               markerfacecolor='none', markeredgecolor=temp_color,
                               alpha=0.7, markeredgewidth=1.5, label=temp_label)
                    
                    if temp_plot_mode in ["Planes Only", "Both"]:
                        # Lighter/translucent planes for temporary data
                        for (temp_s, temp_di) in zip(temp_strikes, temp_dips):
                            temp_lons, temp_lats = mplstereonet.plane(temp_s, temp_di)
                            ax.plot(temp_lons, temp_lats, '-', alpha=0.3, color=temp_color, linewidth=1)

        # Plot all current data points and collect analysis data
        for (code_str, struct_type, data_list, plot_mode, dataset_idx, dataset_color) in plotted_data:
            # Select color - ALWAYS use structure_color_map for domain differentiation
            if single_dataset_mode:
                # Even in single dataset mode, use color map to support domain differentiation
                color = structure_color_map.get((code_str, dataset_idx), None)

                # If not in color map, fall back to base structure color
                if color is None:
                    base_code = code_str
                    if " - " in base_code:
                        base_code = base_code.split(" - ")[0]

                    if base_code in self.structure_colors:
                        color = self.structure_colors[base_code]
                    else:
                        # Fallback to color cycle for unknown codes
                        try:
                            color = next(color_cycle)['color']
                        except StopIteration:
                            color_cycle = iter(mpl.rcParams['axes.prop_cycle'])
                            color = next(color_cycle)['color']
            else:
                # In multi-dataset mode, use paired colors based on structure code
                # Keep full code including domain for color lookup
                color = structure_color_map.get((code_str, dataset_idx), dataset_color)

            n_points = len(data_list)
            dataset_name = self.dataset_configs[dataset_idx]["name"]

            # Strip dataset name from code_str if it's already present (for domain mode)
            # Format: "CODE - DOMAIN (Dataset Name)" -> "CODE - DOMAIN"
            display_code = code_str
            if f" ({dataset_name})" in code_str:
                display_code = code_str.replace(f" ({dataset_name})", "")

            # Label with or without dataset name based on mode
            if single_dataset_mode:
                label = f"{display_code} (n={n_points})"
            else:
                label = f"{display_code} ({dataset_name}, n={n_points})"

            # Determine marker based on mode
            if settings.alternate_mode:
                # Alternate mode: shape by code using sequential mapping
                base_code = code_str
                if " - " in base_code:
                    base_code = base_code.split(" - ")[0]
                if " (" in base_code:
                    base_code = base_code.split(" (")[0]
                marker = code_to_marker_map.get(base_code, 'o')  # Default to circle if not found
            else:
                # Normal mode: standard shapes
                if struct_type == "line":
                    marker = '^'
                else:
                    marker = 'o'

            # Dataset 2 plots hollow markers (and dashed great circles below)
            # so the two datasets stay distinguishable even when a code's
            # colour is near-identical in both. Single-dataset plots unchanged.
            hollow = (not single_dataset_mode) and dataset_idx == 1
            if hollow:
                marker_kwargs = {"markerfacecolor": "none",
                                 "markeredgecolor": color,
                                 "markeredgewidth": 1.2}
            elif settings.alternate_mode:
                marker_kwargs = {"markeredgewidth": 0.5, "markeredgecolor": color}
            else:
                marker_kwargs = {}

            if struct_type == "line":
                # Line data => (dip, dipdir) = plunge,bearing
                plunges = [d["dip"] for d in data_list]
                bearings = [d["dipdir"] for d in data_list]

                # Plot the lines - use stereonet math directly for better marker control
                if settings.alternate_mode:
                    # In alternate mode, use direct plot with explicit marker for better control
                    lon, lat = mplstereonet.line(plunges, bearings)
                    arts = ax.plot(lon, lat, marker=marker, markersize=5,
                                   linestyle='none', color=color, **marker_kwargs)
                    ax.plot([], [], marker=marker, color=color, markersize=5, label=label,
                            **marker_kwargs)
                else:
                    # Normal mode uses ax.line() method
                    arts = ax.line(plunges, bearings, marker=marker, markersize=5,
                                   linestyle='none', color=color, **marker_kwargs)
                    ax.plot([], [], marker=marker, color=color, markersize=5, label=label,
                            **marker_kwargs)
                _register_pickable(arts, data_list, dataset_idx)

                # Store for line analysis
                cat_key = (code_str, dataset_idx)
                if cat_key not in line_per_category:
                    line_per_category[cat_key] = {"plunges": [], "bearings": [], "color": color}
                line_per_category[cat_key]["plunges"].extend(plunges)
                line_per_category[cat_key]["bearings"].extend(bearings)

            else:  # struct_type == "plane"
                strikes = []
                dips = []
                for d_dict in data_list:
                    dip_val = d_dict["dip"]
                    dd_val = d_dict["dipdir"]
                    s_val = dip_direction_to_strike(dd_val)
                    strikes.append(s_val)
                    dips.append(dip_val)

                if plot_mode in ["Poles Only", "Both"]:
                    # Plot poles - use stereonet math directly for better marker control
                    if settings.alternate_mode:
                        # In alternate mode, use direct plot with explicit marker for better control
                        lon, lat = mplstereonet.pole(strikes, dips)
                        arts = ax.plot(lon, lat, marker=marker, markersize=5,
                                       linestyle='none', color=color, **marker_kwargs)
                        ax.plot([], [], marker=marker, color=color, markersize=5, label=label,
                                **marker_kwargs)
                    else:
                        # Normal mode uses ax.pole() method
                        arts = ax.pole(strikes, dips, marker=marker, markersize=5,
                                       linestyle='none', color=color, **marker_kwargs)
                        ax.plot([], [], marker=marker, color=color, markersize=5, label=label,
                                **marker_kwargs)
                    _register_pickable(arts, data_list, dataset_idx)

                    # Store for plane analysis
                    cat_key = (code_str, dataset_idx)
                    if cat_key not in plane_per_category:
                        plane_per_category[cat_key] = {"plunges": [], "bearings": [], "color": color}
                    for (s, di) in zip(strikes, dips):
                        p, b = mplstereonet.pole2plunge_bearing(s, di)
                        plane_per_category[cat_key]["plunges"].append(p)
                        plane_per_category[cat_key]["bearings"].append(b)

                if plot_mode in ["Planes Only", "Both"]:
                    # Dataset 2 great circles dashed (matches its hollow markers)
                    for (s, di) in zip(strikes, dips):
                        lons, lats = mplstereonet.plane(s, di)
                        ax.plot(lons, lats, '--' if hollow else '-', alpha=0.5, color=color)

                    if plot_mode == "Planes Only":
                        cat_key = (code_str, dataset_idx)
                        if cat_key not in plane_per_category:
                            plane_per_category[cat_key] = {"plunges": [], "bearings": [], "color": color}
                        for (s, di) in zip(strikes, dips):
                            p, b = mplstereonet.pole2plunge_bearing(s, di)
                            plane_per_category[cat_key]["plunges"].append(p)
                            plane_per_category[cat_key]["bearings"].append(b)

                    # Rake handling
                    if settings.rake_enabled:
                        category_rake_label_drawn = False
                        for d_dict in data_list:
                            pit = d_dict.get("pitch", None)
                            if pit is None:
                                continue

                            dipdir_val = d_dict["dipdir"]
                            dip_val = d_dict["dip"]
                            rhr_strike = (dipdir_val - 90) % 360

                            lon_arr, lat_arr = mplstereonet.rake(rhr_strike, dip_val, pit)

                            ax.plot(lon_arr, lat_arr, 'x', color=color, markersize=8)

                            if not category_rake_label_drawn:
                                ax.plot([], [], 'x', color=color, markersize=5,
                                        label=f"{code_str} Rake")
                                category_rake_label_drawn = True

                            lon_pt = lon_arr[-1]
                            lat_pt = lat_arr[-1]
                            x, y, z = mplstereonet.stereonet2xyz(lon_pt, lat_pt)
                            plg_array, trd_array = mplstereonet.vector2plunge_bearing(x, y, z)

                            plg_val = plg_array[-1]
                            trd_val = trd_array[-1]
                            label_txt = f"Rake: Plg={plg_val:.1f}°, Trd={trd_val:.1f}°"
                            analysis_stats.append((label_txt, color))

        # PLANE ANALYSIS - only runs if plane checkbox is checked
        if settings.best_fit_plane:
            for group in stereonet_analysis.iter_analysis_groups(
                    settings.analysis_scope, plane_per_category, analysis_flags,
                    stereonet_analysis.FLAG_BEST_FIT, self.dataset_configs, 'red'):
                stereonet_analysis.draw_best_fit_plane(ax, group, stats=analysis_stats)

        if settings.contour_plane:
            for group in stereonet_analysis.iter_analysis_groups(
                    settings.analysis_scope, plane_per_category, analysis_flags,
                    stereonet_analysis.FLAG_CONTOURS, self.dataset_configs, 'red'):
                stereonet_analysis.draw_plane_contours(ax, group)

        # MEAN PLANE ANALYSIS
        if settings.mean_plane:
            for group in stereonet_analysis.iter_analysis_groups(
                    settings.analysis_scope, plane_per_category, analysis_flags,
                    stereonet_analysis.FLAG_MEAN, self.dataset_configs, 'red'):
                stereonet_analysis.draw_mean_plane(ax, group, settings.mean_plane_type,
                                                   stats=analysis_stats)

        # LINE ANALYSIS - only runs if line checkbox is checked
        if settings.best_fit_line:
            for group in stereonet_analysis.iter_analysis_groups(
                    settings.analysis_scope, line_per_category, analysis_flags,
                    stereonet_analysis.FLAG_BEST_FIT, self.dataset_configs, 'green'):
                stereonet_analysis.draw_best_fit_line(ax, group, stats=analysis_stats)

        if settings.contour_line:
            for group in stereonet_analysis.iter_analysis_groups(
                    settings.analysis_scope, line_per_category, analysis_flags,
                    stereonet_analysis.FLAG_CONTOURS, self.dataset_configs, 'green'):
                stereonet_analysis.draw_line_contours(ax, group)

        # MEAN LINE ANALYSIS
        if settings.mean_line:
            for group in stereonet_analysis.iter_analysis_groups(
                    settings.analysis_scope, line_per_category, analysis_flags,
                    stereonet_analysis.FLAG_MEAN, self.dataset_configs, 'green'):
                stereonet_analysis.draw_mean_line(ax, group, stats=analysis_stats)

        # ==================================================================
        # ADD THE INTERSECTION CONTOURS CODE HERE - JUST BEFORE LEGEND CREATION
        # ==================================================================
        # Add intersection contours if enabled - this must be the LAST thing plotted
        if settings.intersections_enabled:
            # Create a progress dialog for long calculations
            num_planes = sum(len(data_list) for _, struct_type, data_list, _, _, _ in plotted_data
                             if struct_type == "plane")

            if num_planes >= 2:
                max_intersections = (num_planes * (num_planes - 1)) // 2

                if max_intersections > 1000:  # Only show progress for large calculations
                    progress = QMessageBox.information(
                        self.iface.mainWindow(),
                        "Processing Intersections",
                        f"Calculating up to {max_intersections} plane intersections.\nThis may take a moment..."
                    )

                # Add the intersection contours - will be on top since added
                # last. Pass the plotted planes explicitly: the tree-walking
                # fallback can't see grouped categories or live-view data.
                plane_records = [rec for _, struct_type, data_list, _, _, _ in plotted_data
                                 if struct_type == "plane" for rec in data_list]
                num_intersections = self.add_intersection_contours(ax, plane_records)

                if num_intersections == 0:
                    QMessageBox.warning(
                        self.iface.mainWindow(),
                        "No Intersections",
                        "No valid intersections found between the selected planes."
                    )
            else:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Insufficient Data",
                    "Need at least 2 planes to calculate intersections."
                )
        # ==================================================================
        # END OF ADDED CODE
        # ==================================================================

        # LEGEND POSITIONING: Place in right side with proper spacing
        legend = ax.legend(
            loc='center left',  # Position at the center left of the legend box
            bbox_to_anchor=(1.08, 0.5),  # Place legend to the right of the plot
            fontsize=8,
            handletextpad=0.5,
            frameon=True,  # Add frame around legend
            framealpha=0.9,  # Less transparency for better readability
        )

        # Make sure legend text has a light background (unless transparent mode)
        if settings.transparent:
            legend.get_frame().set_facecolor('none')
            legend.get_frame().set_alpha(0)
        else:
            legend.get_frame().set_facecolor('white')
            legend.get_frame().set_alpha(0.9)

        # Adjust subplot position to make room for legend
        if settings.profile == 'clipboard':
            fig.subplots_adjust(right=0.75, bottom=0.1)  # Bottom margin prevents cutoff
            fig.tight_layout(pad=1.2)  # Increased padding to prevent cutoff
        else:
            fig.subplots_adjust(right=0.75)  # Reserves 25% of figure width for the legend
            fig.tight_layout()
            if settings.profile == 'screen':
                # tight_layout overrides the right margin. Exports recover the
                # overflowing legend/stat text via savefig(bbox_inches='tight'),
                # but the live canvas hard-clips at the figure edge, so
                # re-reserve the margin after layout.
                fig.subplots_adjust(right=0.75)
        ax._polar.set_position(ax.get_position())

        # Draw the collected analysis stat lines off-plot in the right
        # margin, starting just below the legend's measured extent so a
        # tall legend never overlaps them. Must run after the layout calls
        # above: tight_layout resizes the axes, which changes how much
        # axes-fraction span the (fixed pixel height) legend covers.
        if analysis_stats:
            legend_bottom = 0.30  # fallback if the extent can't be measured
            try:
                fig.canvas.draw()
                renderer = fig.canvas.get_renderer()
                bbox = legend.get_window_extent(renderer)
                legend_bottom = ax.transAxes.inverted().transform(
                    (bbox.x0, bbox.y0))[1]
            except Exception:
                pass
            spacing = 0.045
            available = max(legend_bottom - 0.02, 0.0)
            if len(analysis_stats) * spacing > available:
                # Compress to fit the space under the legend (the floor
                # keeps 8pt lines from overlapping each other; beyond that
                # the block just runs low)
                spacing = max(0.03, available / max(len(analysis_stats), 1))
            stat_y = legend_bottom - spacing
            for stat_text, stat_color in analysis_stats:
                ax.annotate(stat_text, xy=(1.08, stat_y),
                            xycoords='axes fraction',
                            ha='left', va='top', fontsize=8,
                            color=stat_color, annotation_clip=False)
                stat_y -= spacing

        return fig, pick_registry


    def plot_and_swap(self):
        self.tab_widget.setCurrentIndex(0)  # Switch to the Plot tab

        # If live view is enabled, fetch data first before plotting
        if self.live_view_enabled:
            self.update_live_view_data()

        self.update_plot()  # Then update the plot


    def show_empty_plot(self):
        """
        Show the message label when no data is available. Callers set the
        message via plot_label.setText() before calling this.
        """
        self.plot_figure.clear()
        if self.pick_handler:
            self.pick_handler.set_plot({})
        self.plot_canvas.draw_idle()
        self.plot_stack.setCurrentWidget(self.plot_label)

    ########################################################################
    # Updated Clipboard Copy Function
    ########################################################################


    def save_plot_as_svg(self):
        """
        Let user save the current stereonet plot as an SVG vector file.

        Re-renders the last plotted data through the shared render pipeline
        at 300 dpi, honouring the Transparent checkbox.
        """
        if not self.last_plotted_data:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "No Data",
                "No data plotted yet; cannot save SVG."
            )
            return

        # Prompt file name
        save_path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            "Save Stereonet as SVG",
            os.path.expanduser("~"),
            "Scalable Vector Graphics (*.svg)"
        )
        if not save_path:
            return  # user canceled

        settings = self._collect_render_settings('svg')
        fig = self._render_stereonet_figure(self.last_plotted_data,
                                            self.last_analysis_flags, settings)
        try:
            fig.savefig(save_path, format='svg', bbox_inches='tight',
                        transparent=settings.transparent)
            QgsMessageLog.logMessage(f"Stereonet saved as SVG: {save_path}", 'Linear Geoscience', Qgis.Info)
            QMessageBox.information(
                self.iface.mainWindow(),
                "Export Successful",
                f"Stereonet saved to:\n{save_path}"
            )
        except Exception as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "SVG Export Error",
                str(e)
            )
        finally:
            plt.close(fig)


    # =========================================================================
    # CODE-DESCRIPTION LEGEND GENERATION
    # =========================================================================

    def _build_code_description_map(self):
        """Resolve {normalized_code: description} from the editor widget on
        each enabled dataset's structure-code field.

        Supports the QGIS 'ValueRelation' widget (descriptions live in a
        lookup layer referenced by the field config) and 'ValueMap'
        (descriptions stored directly in the field config). Keys are
        normalized the same way data collection normalizes codes so lookups
        match plotted categories. Returns ({}, [field names checked]) when
        nothing is configured.
        """
        descriptions = {}
        checked_fields = []
        for ds in range(2):
            if not self.dataset_configs[ds]["enabled"]:
                continue
            layer = self.get_layer(ds)
            subtype_combo = self.dataset_configs[ds].get("subtype_combo")
            field_name = subtype_combo.currentText() if subtype_combo else ""
            if layer is None or not field_name:
                continue
            field_idx = layer.fields().indexOf(field_name)
            if field_idx < 0:
                continue
            checked_fields.append(field_name)

            try:
                setup = layer.editorWidgetSetup(field_idx)
                widget_type = setup.type()
                cfg = setup.config()
            except Exception:
                continue

            if widget_type == 'ValueRelation':
                rel_layer = QgsProject.instance().mapLayer(cfg.get('Layer', ''))
                if rel_layer is None and cfg.get('LayerName'):
                    matches = QgsProject.instance().mapLayersByName(cfg['LayerName'])
                    rel_layer = matches[0] if matches else None
                key_field = cfg.get('Key')
                value_field = cfg.get('Value')
                if rel_layer is None or not key_field or not value_field:
                    continue
                try:
                    for f in rel_layer.getFeatures():
                        k = f[key_field]
                        v = f[value_field]
                        if k is None or v is None:
                            continue
                        code = unify_fax_code(str(k).strip().upper())
                        descriptions.setdefault(code, str(v).strip())
                except Exception:
                    QgsMessageLog.logMessage(
                        f"Legend: failed reading value-relation table for "
                        f"field '{field_name}'", 'Linear Geoscience', Qgis.Warning)

            elif widget_type == 'ValueMap':
                # cfg['map'] is a list of {description: value} dicts in
                # modern QGIS, or one flat {description: value} dict in
                # older projects
                raw = cfg.get('map', [])
                pairs = []
                if isinstance(raw, dict):
                    pairs = list(raw.items())
                elif isinstance(raw, list):
                    for entry in raw:
                        if isinstance(entry, dict):
                            pairs.extend(entry.items())
                for desc_text, stored_value in pairs:
                    if stored_value is None:
                        continue
                    code = unify_fax_code(str(stored_value).strip().upper())
                    descriptions.setdefault(code, str(desc_text).strip())

        return descriptions, checked_fields


    @staticmethod
    def _format_legend_entries(plotted_keys, code_groups, desc_map):
        """Build the legend text from plotted category keys.

        plotted_keys: code_str values in plot order ("CODE", "CODE - DOMAIN"
        or "CODE - DOMAIN (Dataset)"); duplicates across domains/datasets
        collapse to one entry. Group keys break down into their members:
        "Shears = SZCS (Sinistral Shear) + SZCR (Crenulated Shear)".
        """
        entries = []
        seen = set()
        for code_str in plotted_keys:
            base = code_str.split(" - ")[0] if " - " in code_str else code_str
            if base in seen:
                continue
            seen.add(base)
            if base in code_groups:
                members = code_groups[base]
                parts = []
                for m in members:
                    desc = desc_map.get(m)
                    parts.append(f"{m} ({desc})" if desc else m)
                entries.append(f"{base} = " + " + ".join(parts))
            else:
                desc = desc_map.get(base)
                entries.append(f"{base} = {desc}" if desc else base)
        return ", ".join(entries)


    def generate_plot_legend(self):
        """Generate a 'CODE = Description' text legend for the current plot
        and show it in an editable dialog with a copy button."""
        if not self.last_plotted_data:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "No Data",
                "Nothing is plotted yet — plot some data first."
            )
            return

        desc_map, checked_fields = self._build_code_description_map()
        plotted_keys = [item[0] for item in self.last_plotted_data]
        legend_text = self._format_legend_entries(
            plotted_keys, self.code_groups, desc_map)

        hint = None
        if not desc_map:
            fields = ", ".join(f"'{f}'" for f in checked_fields) or "the code field"
            hint = (f"No Value Relation / Value Map found on {fields} — "
                    "descriptions unavailable, showing codes only.")

        self._show_legend_dialog(legend_text, hint)


    def _show_legend_dialog(self, text, hint=None):
        """Editable legend text in a small dialog with Copy to Clipboard."""
        dialog = QDialog(self.dock)
        dialog.setWindowTitle("Plot Legend")
        dialog.resize(560, 220)
        layout = QVBoxLayout(dialog)

        if hint:
            hint_label = QLabel(hint)
            hint_label.setStyleSheet("color: #7f8c8d; font-size: 10px;")
            hint_label.setWordWrap(True)
            layout.addWidget(hint_label)

        text_edit = QTextEdit()
        text_edit.setPlainText(text)
        text_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        layout.addWidget(text_edit)

        button_layout = QHBoxLayout()
        copy_btn = QPushButton("Copy to Clipboard")
        close_btn = QPushButton("Close")

        def do_copy():
            QApplication.clipboard().setText(text_edit.toPlainText())
            copy_btn.setText("Copied!")
            QTimer.singleShot(1500, lambda: copy_btn.setText("Copy to Clipboard"))

        copy_btn.clicked.connect(do_copy)
        close_btn.clicked.connect(dialog.accept)
        button_layout.addStretch()
        button_layout.addWidget(copy_btn)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)

        dialog.exec()


    # =========================================================================
    # EXPORT FUNCTIONALITY METHODS
    # =========================================================================

    def export_coding_csv(self):
        """Export current code classifications to CSV file"""
        filename = self.export_file_widget.filePath()
        if not filename:
            # If no path is set, prompt for one
            filename, _ = QFileDialog.getSaveFileName(
                self.iface.mainWindow(),
                "Export Codes to CSV",
                os.path.expanduser("~"),
                "CSV Files (*.csv)"
            )

        if not filename:
            return  # User canceled

        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Code", "Type", "Dataset"])  # Enhanced header with dataset info

                # Export all codes from the table
                for row, entry in self.coding_entries.items():
                    code = entry["code"]
                    dataset_name = self.dataset_configs[entry["dataset_idx"]]["name"]

                    if entry["planar_chk"].isChecked():
                        writer.writerow([code, "P", dataset_name])
                    elif entry["linear_chk"].isChecked():
                        writer.writerow([code, "L", dataset_name])
                    else:
                        writer.writerow([code, "", dataset_name])  # Unclassified

            QMessageBox.information(
                self.iface.mainWindow(),
                "Export Successful",
                f"Classification codes exported to:\n{filename}"
            )
        except Exception as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Export Error",
                str(e)
            )


    def export_stereonet11(self):
        """Export data to Stereonet 11 format"""
        # Get output directory
        out_dir = self.export_dir_widget.filePath()
        if not out_dir:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Export Error",
                "Please select an output directory."
            )
            return

        # Get file prefix
        prefix = self.export_prefix.text()
        if not prefix:
            prefix = "stereonet_export"

        # Get selected structure types
        selected_structures = []
        for i in range(self.export_structure_tree.topLevelItemCount()):
            item = self.export_structure_tree.topLevelItem(i)
            if item.checkState(0) == Qt.Checked:
                selected_structures.append(item.text(0))

        if not selected_structures:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Export Error",
                "No structure types selected for export."
            )
            return

        # Get filter values
        min_dip = None
        max_dip = None

        if hasattr(self, 'min_dip_filter') and self.min_dip_filter.text():
            try:
                min_dip = float(self.min_dip_filter.text())
            except ValueError:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Filter Error",
                    "Invalid minimum dip value. Using no minimum."
                )

        if hasattr(self, 'max_dip_filter') and self.max_dip_filter.text():
            try:
                max_dip = float(self.max_dip_filter.text())
            except ValueError:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Filter Error",
                    "Invalid maximum dip value. Using no maximum."
                )

        # Get domain filter
        domain_filter = None
        if (hasattr(self, 'filter_by_domain_checkbox') and
                self.filter_by_domain_checkbox.isChecked() and
                self.domain_filter_combo.currentText() != "All Domains"):
            domain_filter = self.domain_filter_combo.currentText()

        # Format type
        use_strike_format = self.format_strike_radio.isChecked()

        # Process and export data
        exported_files = 0

        # Separate file for each structure or combined file
        separate_files = self.separate_files_checkbox.isChecked()
        include_headers = self.include_headers_checkbox.isChecked()

        # ALL layer features, regardless of QGIS selection or refresh state;
        # dip and domain filters are applied inside the gather
        per_code, _ds_info, stats = self._gather_export_measurements(
            selected_structures, min_dip, max_dip, domain_filter)

        if separate_files:
            # Export each structure type to its own file
            for structure_code in selected_structures:
                bucket = per_code.get(structure_code)
                if not bucket or not bucket["points"]:
                    continue

                # Generate filename
                safe_code = ''.join(c if c.isalnum() else '_' for c in structure_code)
                filename = f"{prefix}_{safe_code}.txt"
                filepath = os.path.join(out_dir, filename)

                # Export based on structure type and format
                success = self.export_data_to_stereonet11(
                    bucket["points"],
                    filepath,
                    bucket["struct_type"],
                    include_headers,
                    use_strike_format
                )

                if success:
                    exported_files += 1
        else:
            # Combined file - one for planes, one for lines
            plane_data = []
            line_data = []

            for bucket in per_code.values():
                if bucket["struct_type"].lower() == "plane":
                    plane_data.extend(bucket["points"])
                elif bucket["struct_type"].lower() == "line":
                    line_data.extend(bucket["points"])

            # Export planes
            if plane_data:
                plane_file = os.path.join(out_dir, f"{prefix}_planes.txt")
                if self.export_data_to_stereonet11(
                        plane_data,
                        plane_file,
                        "plane",
                        include_headers,
                        use_strike_format
                ):
                    exported_files += 1

            # Export lines
            if line_data:
                line_file = os.path.join(out_dir, f"{prefix}_lines.txt")
                if self.export_data_to_stereonet11(
                        line_data,
                        line_file,
                        "line",
                        include_headers,
                        use_strike_format
                ):
                    exported_files += 1

        # Show results
        if exported_files > 0:
            QMessageBox.information(
                self.iface.mainWindow(),
                "Export Successful",
                f"Exported {exported_files} files to {out_dir}"
            )
        else:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Export Notice",
                self._export_no_match_message(stats)
            )


    def export_data_to_stereonet11(self, data_points, filepath, struct_type, include_headers, use_strike_format):
        """
        Export structural data to Stereonet 11 format

        Parameters:
        - data_points: list of dictionaries with measurement data
        - filepath: output file path
        - struct_type: "plane" or "line"
        - include_headers: whether to include column headers
        - use_strike_format: use strike/dip format instead of dip_direction/dip

        Returns:
        - bool: success or failure
        """
        try:
            with open(filepath, 'w', newline='') as f:
                # Determine headers and format based on type and format choice
                if struct_type.lower() == "plane":
                    if use_strike_format:
                        # Strike/Dip format (RHR)
                        if include_headers:
                            f.write("strike\tdip\n")

                        # Write data with strike calculated from dip direction
                        for p in data_points:
                            strike = dip_direction_to_strike(p['dipdir'])
                            # Note: Strike/Dip format has correct column order already
                            f.write(f"{strike:.1f}\t{p['dip']:.1f}\n")
                    else:
                        # Dip Direction/Dip format
                        if include_headers:
                            # Use "DD" header for Stereonet 11 format for planes
                            f.write("DD\n")

                        # Write data with correct column order for DD format:
                        # First column: Dip, Second column: Dip Direction
                        for p in data_points:
                            f.write(f"{p['dip']:.1f}\t{p['dipdir']:.1f}\n")

                elif struct_type.lower() == "line":
                    # For lines, format is always trend/plunge
                    if include_headers:
                        # Use "PT" header for Stereonet 11 format for lines
                        f.write("PT\n")

                    # Write data with correct column order for PT format:
                    # First column: Plunge (dip), Second column: Trend (dipdir)
                    for p in data_points:
                        f.write(f"{p['dip']:.1f}\t{p['dipdir']:.1f}\n")

                else:
                    # Unknown type - skip
                    return False

            return True
        except Exception as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Export Error",
                f"Error exporting to {filepath}: {str(e)}"
            )
            return False

    # =========================================================================
    # LEAPFROG EXPORT
    # =========================================================================

    @staticmethod
    def _attr_str(value):
        """Feature attribute as a clean string ('' for NULL/None)."""
        if value is None:
            return ""
        s = str(value).strip()
        return "" if s == "NULL" else s

    @staticmethod
    def _detect_elevation_field(layer):
        """First layer field that looks like an elevation column, or None."""
        if layer is None:
            return None
        for f in layer.fields():
            if f.name().lower() in ('elevation', 'elev', 'z', 'rl', 'height'):
                return f.name()
        return None

    def _leapfrog_core_fields(self, ds):
        """Field names already consumed as Leapfrog core columns for a
        dataset (excluded from the additional-columns checklist)."""
        cfg = self.dataset_configs[ds]
        names = set()
        for key in ('dip_combo', 'dipdir_combo', 'subtype_combo',
                    'easting_combo', 'northing_combo'):
            combo = cfg.get(key)
            if combo is not None and combo.currentText():
                names.add(combo.currentText())
        elev = self._detect_elevation_field(self.get_layer(ds))
        if elev:
            names.add(elev)
        return names

    def _populate_leapfrog_fields(self):
        """Rebuild the Leapfrog additional-columns checklist: union of layer
        fields across enabled datasets minus the core columns. Comments and
        PhotoID default to checked; user choices survive refreshes."""
        if getattr(self, 'leapfrog_fields_list', None) is None:
            return

        previously_checked = set()
        previously_seen = set()
        for i in range(self.leapfrog_fields_list.count()):
            item = self.leapfrog_fields_list.item(i)
            previously_seen.add(item.text())
            if item.checkState() == Qt.Checked:
                previously_checked.add(item.text())

        available = set()
        for ds in range(2):
            if not self.dataset_configs[ds]["enabled"]:
                continue
            layer = self.get_layer(ds)
            if layer is None:
                continue
            core = self._leapfrog_core_fields(ds)
            for f in layer.fields():
                if f.name() not in core:
                    available.add(f.name())

        self.leapfrog_fields_list.clear()
        default_checked = ('comments', 'comment', 'photoid', 'photo_id')
        for name in sorted(available, key=str.lower):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            if name in previously_seen:
                state = Qt.Checked if name in previously_checked else Qt.Unchecked
            else:
                state = Qt.Checked if name.lower() in default_checked else Qt.Unchecked
            item.setCheckState(state)
            self.leapfrog_fields_list.addItem(item)

    def _gather_export_measurements(self, selected_structures, min_dip=None,
                                    max_dip=None, domain_filter=None):
        """Read ALL features from the enabled dataset layers and bucket the
        measurements per structure code. Exports never depend on the QGIS
        feature selection or on refresh state; the structure checklist and
        the dip/domain filters are the only filters.

        Returns (per_code, ds_info, stats):
        - per_code: {code: {"struct_type": 'plane'|'line',
                            "points": [{"dip", "dipdir", "dataset", "feature"}]}}
          (for lines, dip/dipdir hold plunge/trend, matching the layer fields)
        - ds_info:  {ds: {"east_field", "north_field", "elev_field",
                          "layer_field_names"}} for coordinate/extra columns
        - stats:    skip counters for the diagnostic no-match message
        """
        per_code = {}
        ds_info = {}
        stats = {
            "datasets_used": 0,
            "datasets_unconfigured": 0,
            "scanned": 0,
            "no_code": 0,
            "code_unchecked": 0,
            "unclassified": 0,
            "bad_numbers": 0,
            "dip_filtered": 0,
            "domain_filtered": 0,
            "unknown_codes": set(),
        }

        for ds in range(2):
            if not self.dataset_configs[ds]["enabled"]:
                continue
            layer = self.get_layer(ds)
            if layer is None:
                continue
            cfg = self.dataset_configs[ds]

            def field_of(key):
                combo = cfg.get(key)
                return combo.currentText() if combo is not None else ""

            dip_field = field_of('dip_combo')
            dipdir_field = field_of('dipdir_combo')
            subtype_field = field_of('subtype_combo')
            if not (dip_field and dipdir_field and subtype_field):
                stats["datasets_unconfigured"] += 1
                QgsMessageLog.logMessage(
                    f"Export: dataset {ds + 1} skipped (dip/dipdir/code "
                    "fields not configured)", 'Linear Geoscience', Qgis.Warning)
                continue
            domain_field = field_of('domain_combo')
            ds_info[ds] = {
                "east_field": field_of('easting_combo'),
                "north_field": field_of('northing_combo'),
                "elev_field": self._detect_elevation_field(layer),
                "layer_field_names": {f.name() for f in layer.fields()},
            }
            stats["datasets_used"] += 1

            for f in layer.getFeatures():
                stats["scanned"] += 1
                try:
                    sv = f[subtype_field]
                except KeyError:
                    stats["no_code"] += 1
                    continue
                if sv is None or not str(sv).strip():
                    stats["no_code"] += 1
                    continue
                code = unify_fax_code(str(sv).strip().upper())
                if code not in selected_structures:
                    stats["code_unchecked"] += 1
                    continue
                struct_type = self._classify_base_code(code)
                if struct_type is None:
                    stats["unclassified"] += 1
                    stats["unknown_codes"].add(code)
                    continue

                try:
                    dip = float(f[dip_field])
                    dipdir = float(f[dipdir_field])
                except (TypeError, ValueError, KeyError):
                    stats["bad_numbers"] += 1
                    continue
                if ((min_dip is not None and dip < min_dip)
                        or (max_dip is not None and dip > max_dip)):
                    stats["dip_filtered"] += 1
                    continue
                if domain_filter and domain_field:
                    if self._attr_str(f[domain_field]) != domain_filter:
                        stats["domain_filtered"] += 1
                        continue

                bucket = per_code.setdefault(
                    code, {"struct_type": struct_type, "points": []})
                bucket["points"].append({"dip": dip, "dipdir": dipdir,
                                         "dataset": ds, "feature": f})

        if stats["unknown_codes"]:
            QgsMessageLog.logMessage(
                "Export: skipped unclassified codes: "
                + ", ".join(sorted(stats["unknown_codes"])),
                'Linear Geoscience', Qgis.Warning)
        return per_code, ds_info, stats

    def _export_no_match_message(self, stats):
        """Human-readable breakdown of why an export produced zero rows."""
        parts = ["No measurements matched the export filters.",
                 f"Scanned {stats['scanned']} feature(s) in "
                 f"{stats['datasets_used']} dataset(s)."]
        reasons = [
            ("code_unchecked", "with codes not checked in the structure list"),
            ("unclassified", "with unclassified codes (classify them in the Coding tab)"),
            ("no_code", "with an empty structure code"),
            ("bad_numbers", "with invalid dip / dip-direction values"),
            ("dip_filtered", "outside the dip range filter"),
            ("domain_filtered", "excluded by the domain filter"),
        ]
        lines = [f"  • {stats[key]} {label}"
                 for key, label in reasons if stats.get(key)]
        if lines:
            parts.append("Excluded:\n" + "\n".join(lines))
        if stats.get("datasets_unconfigured"):
            parts.append(f"{stats['datasets_unconfigured']} dataset(s) skipped: "
                         "dip / dip-direction / code fields not configured "
                         "in the Datasets tab.")
        message = "\n".join(parts)
        QgsMessageLog.logMessage(message, 'Linear Geoscience', Qgis.Warning)
        return message

    def export_leapfrog(self):
        """Export to Leapfrog CSV format: planar structures and lineations in
        separate files, with coordinates, orientation, code, optional
        CodeGroup and user-selected attribute columns."""
        out_dir = self.export_dir_widget.filePath()
        if not out_dir:
            QMessageBox.warning(self.iface.mainWindow(), "Export Error",
                                "Please select an output directory.")
            return

        prefix = self.export_prefix.text() or "stereonet_export"

        selected_structures = set()
        for i in range(self.export_structure_tree.topLevelItemCount()):
            item = self.export_structure_tree.topLevelItem(i)
            if item.checkState(0) == Qt.Checked:
                selected_structures.add(item.text(0))
        if not selected_structures:
            QMessageBox.warning(self.iface.mainWindow(), "Export Error",
                                "No structure types selected for export.")
            return

        min_dip = max_dip = None
        if self.min_dip_filter.text():
            try:
                min_dip = float(self.min_dip_filter.text())
            except ValueError:
                QMessageBox.warning(self.iface.mainWindow(), "Filter Error",
                                    "Invalid minimum dip value. Using no minimum.")
        if self.max_dip_filter.text():
            try:
                max_dip = float(self.max_dip_filter.text())
            except ValueError:
                QMessageBox.warning(self.iface.mainWindow(), "Filter Error",
                                    "Invalid maximum dip value. Using no maximum.")

        domain_filter = None
        if (self.filter_by_domain_checkbox.isChecked()
                and self.domain_filter_combo.currentText() != "All Domains"):
            domain_filter = self.domain_filter_combo.currentText()

        extra_fields = []
        for i in range(self.leapfrog_fields_list.count()):
            item = self.leapfrog_fields_list.item(i)
            if item.checkState() == Qt.Checked:
                extra_fields.append(item.text())
        want_group_col = self.leapfrog_group_col_checkbox.isChecked()

        # Code descriptions from the Value Relation / Value Map lookup
        # (same source as the Generate Legend button)
        desc_map, _ = self._build_code_description_map()

        # ALL layer features, regardless of QGIS selection or refresh state
        per_code, ds_info, stats = self._gather_export_measurements(
            selected_structures, min_dip, max_dip, domain_filter)

        planar_rows = []
        linear_rows = []
        for code in sorted(per_code):
            bucket = per_code[code]
            for p in bucket["points"]:
                f = p["feature"]
                info = ds_info[p["dataset"]]

                east = (self._attr_str(f[info["east_field"]])
                        if info["east_field"] else "")
                north = (self._attr_str(f[info["north_field"]])
                         if info["north_field"] else "")
                if not east or not north:
                    # Fall back to the feature geometry
                    try:
                        geom = f.geometry()
                        if geom is not None and not geom.isNull():
                            pt = geom.asPoint()
                            east = f"{pt.x():.3f}"
                            north = f"{pt.y():.3f}"
                    except Exception:
                        pass
                elev = (self._attr_str(f[info["elev_field"]])
                        if info["elev_field"] else "")

                row = [east, north, elev,
                       f"{p['dip']:.1f}", f"{p['dipdir']:.1f}", code]
                if want_group_col:
                    row.append(self.get_group_for_code(code) or code)
                row.append(desc_map.get(code, ""))
                for name in extra_fields:
                    row.append(self._attr_str(f[name])
                               if name in info["layer_field_names"] else "")

                if bucket["struct_type"] == 'plane':
                    planar_rows.append(row)
                else:
                    linear_rows.append(row)

        if not planar_rows and not linear_rows:
            QMessageBox.warning(self.iface.mainWindow(), "Export Notice",
                                self._export_no_match_message(stats))
            return

        group_part = ["CodeGroup"] if want_group_col else []
        planar_header = (["East", "North", "Elevation", "Dip", "DipDirection",
                          "Code"] + group_part + ["Description"] + extra_fields)
        linear_header = (["East", "North", "Elevation", "Plunge", "Trend",
                          "Code"] + group_part + ["Description"] + extra_fields)

        written = []
        try:
            if planar_rows:
                path = os.path.join(out_dir, f"{prefix}_leapfrog_planar.csv")
                with open(path, 'w', newline='', encoding='utf-8') as fh:
                    writer = csv.writer(fh)
                    writer.writerow(planar_header)
                    writer.writerows(planar_rows)
                written.append(f"{os.path.basename(path)} ({len(planar_rows)} rows)")
            if linear_rows:
                path = os.path.join(out_dir, f"{prefix}_leapfrog_lineations.csv")
                with open(path, 'w', newline='', encoding='utf-8') as fh:
                    writer = csv.writer(fh)
                    writer.writerow(linear_header)
                    writer.writerows(linear_rows)
                written.append(f"{os.path.basename(path)} ({len(linear_rows)} rows)")
        except Exception as e:
            QMessageBox.critical(self.iface.mainWindow(), "Export Error",
                                 f"Error writing Leapfrog CSV: {e}")
            return

        QMessageBox.information(
            self.iface.mainWindow(), "Export Successful",
            "Exported to {}:\n{}".format(out_dir, "\n".join(written)))

    ########################################################################
    # get_layer => always use auto_layer_combo
    ########################################################################


    def copy_highres_to_clipboard(self):
        """Copy a 300 dpi render of the last plotted data to the clipboard.

        Uses the shared render pipeline; honours the Transparent checkbox
        (transparent copies go through QImage to preserve the alpha channel).
        """
        if not self.last_plotted_data:
            QgsMessageLog.logMessage("No data plotted yet. Cannot copy high-res image.", 'Linear Geoscience', Qgis.Warning)
            # Create blank figure to avoid errors
            fig = plt.figure(figsize=(5, 5), dpi=300)
            try:
                fig.patch.set_facecolor('white')
                buf = io.BytesIO()
                fig.savefig(buf, format='png')
                buf.seek(0)
            finally:
                plt.close(fig)

            pixmap = QPixmap()
            pixmap.loadFromData(buf.getvalue(), 'PNG')
            QApplication.clipboard().setPixmap(pixmap, QClipboard.Clipboard)
            return

        settings = self._collect_render_settings('clipboard')

        # Check for rake conflicts
        any_analysis = (settings.best_fit_plane or settings.contour_plane or
                        settings.mean_plane or settings.best_fit_line or
                        settings.contour_line or settings.mean_line)
        if settings.rake_enabled and any_analysis:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Export Conflict",
                "Cannot export rake with analysis.\nDisable either rakes or analysis."
            )
            return

        fig = self._render_stereonet_figure(self.last_plotted_data,
                                            self.last_analysis_flags, settings)
        try:
            # Copy to clipboard with extra padding to prevent cutoff
            buf = io.BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.3,
                        transparent=settings.transparent)
            buf.seek(0)
        finally:
            plt.close(fig)

        if settings.transparent:
            # Use QImage for proper alpha channel handling
            image = QImage()
            image.loadFromData(buf.getvalue(), 'PNG')
            QApplication.clipboard().setImage(image, QClipboard.Clipboard)
            QgsMessageLog.logMessage("High-res image (300 dpi) with transparent background copied to clipboard.", 'Linear Geoscience', Qgis.Info)
        else:
            pixmap = QPixmap()
            pixmap.loadFromData(buf.getvalue(), 'PNG')
            QApplication.clipboard().setPixmap(pixmap, QClipboard.Clipboard)
            QgsMessageLog.logMessage("High-res image (300 dpi) copied to clipboard.", 'Linear Geoscience', Qgis.Info)


    # =========================================================================
    # LIVE VIEW MONITORING METHODS
    # =========================================================================

    def cleanup_live_view_mode(self):
        """Clean up live view mode when plugin is unloaded or mode is disabled"""
        # Disconnects extentsChanged AND the per-layer selectionChanged
        # connections (the latter previously leaked at unload, leaving stale
        # handlers that raised RuntimeError after a plugin reload)
        self.cleanup_live_view_monitoring()

        # Clear live view data
        if hasattr(self, 'subtype_dict_live_view'):
            for i in range(len(self.subtype_dict_live_view)):
                self.subtype_dict_live_view[i].clear()

        if hasattr(self, 'category_structure_map_live_view'):
            for i in range(len(self.category_structure_map_live_view)):
                self.category_structure_map_live_view[i].clear()


    def toggle_live_view_mode(self, state):
        """Enable/disable live view mode and set up map canvas monitoring"""
        self.live_view_enabled = (state == Qt.Checked)

        if self.live_view_enabled:
            QgsMessageLog.logMessage("Live View mode enabled", 'Linear Geoscience', Qgis.Info)
            # Switch to Live View tab
            if self.categories_tabwidget:
                self.categories_tabwidget.setCurrentIndex(2)  # Live View is tab index 2

            # Show info label and enable options
            self.live_view_info_label.setVisible(True)
            self.live_view_by_extent_checkbox.setEnabled(True)
            self.live_view_by_selection_checkbox.setEnabled(True)
            self.live_view_by_domain_checkbox.setEnabled(True)

            # Enable capture button if any datasets are enabled
            any_datasets_enabled = any(self.dataset_configs[i]["enabled"] for i in range(2))
            self.capture_button.setEnabled(any_datasets_enabled)

            # Initialize live view with ALL available categories
            self.initialize_live_view_categories()

            # Set up monitoring based on selected mode
            self.setup_live_view_monitoring()

            # Initial update
            self.update_live_view_data()

        else:
            QgsMessageLog.logMessage("Live View mode disabled", 'Linear Geoscience', Qgis.Info)
            # Hide info label and disable options
            self.live_view_info_label.setVisible(False)
            self.live_view_by_extent_checkbox.setEnabled(False)
            self.live_view_by_selection_checkbox.setEnabled(False)
            self.live_view_by_domain_checkbox.setEnabled(False)

            # Disable capture button when live view is disabled
            self.capture_button.setEnabled(False)

            # Clean up monitoring
            self.cleanup_live_view_monitoring()

            # Clear live view data
            for i in range(2):
                self.subtype_dict_live_view[i].clear()
                self.category_structure_map_live_view[i].clear()

            # Clear temporary data when live view is disabled
            for i in range(2):
                self.temporary_dataset[i].clear()
            self.temporary_dataset_captured = False
            self.clear_temp_button.setEnabled(False)
            self.temp_status_label.setVisible(False)

            # Clear live view tree
            if self.category_tree_live_view:
                self.category_tree_live_view.clear()


    def on_live_view_mode_changed(self, state):
        """Handle changes to live view mode options"""
        if not self.live_view_enabled:
            return

        sender = self.sender()

        # Ensure only one mode is active at a time
        if sender == self.live_view_by_extent_checkbox and state == Qt.Checked:
            self.live_view_by_selection_checkbox.blockSignals(True)
            self.live_view_by_selection_checkbox.setChecked(False)
            self.live_view_by_selection_checkbox.blockSignals(False)
            QgsMessageLog.logMessage("Live View mode: By Map Extent", 'Linear Geoscience', Qgis.Info)

        elif sender == self.live_view_by_selection_checkbox and state == Qt.Checked:
            self.live_view_by_extent_checkbox.blockSignals(True)
            self.live_view_by_extent_checkbox.setChecked(False)
            self.live_view_by_extent_checkbox.blockSignals(False)
            QgsMessageLog.logMessage("Live View mode: By Selection", 'Linear Geoscience', Qgis.Info)

        # If both are unchecked, default back to extent mode
        if not self.live_view_by_extent_checkbox.isChecked() and not self.live_view_by_selection_checkbox.isChecked():
            self.live_view_by_extent_checkbox.blockSignals(True)
            self.live_view_by_extent_checkbox.setChecked(True)
            self.live_view_by_extent_checkbox.blockSignals(False)
            QgsMessageLog.logMessage("Live View mode: Defaulted back to By Map Extent", 'Linear Geoscience', Qgis.Info)

        # Update monitoring and data
        self.setup_live_view_monitoring()
        self.update_live_view_data()


    def cleanup_live_view_monitoring(self):
        """Clean up all live view monitoring"""
        # Disconnect map canvas signals
        if self.map_canvas:
            try:
                self.map_canvas.extentsChanged.disconnect(self.on_map_extent_changed)
            except Exception:
                pass  # Signal might not be connected

        # Stop timers
        if hasattr(self, 'extent_change_timer') and self.extent_change_timer:
            self.extent_change_timer.stop()

        # Disconnect selection signals from the layers we actually connected
        # to (NOT get_layer(): the combo may point at a different layer now,
        # which previously leaked connections into reloaded plugin instances)
        for layer in self._selection_signal_layers:
            try:
                layer.selectionChanged.disconnect(self.on_selection_changed)
            except Exception:
                pass  # Signal not connected or layer already deleted
        self._selection_signal_layers = []


    def _disconnect_stale_selection_signals(self):
        """Disconnect on_selection_changed from every project layer.

        Called when the handler fires on an instance whose Qt widgets are
        already deleted (i.e. the plugin was reloaded but a layer's
        selectionChanged signal still references this old instance)."""
        try:
            for layer in QgsProject.instance().mapLayers().values():
                try:
                    layer.selectionChanged.disconnect(self.on_selection_changed)
                except Exception:
                    pass
        except Exception:
            pass
        self._selection_signal_layers = []
        QgsMessageLog.logMessage(
            "Stereonet: severed stale selection-signal connections from a "
            "previous plugin instance", 'Linear Geoscience', Qgis.Info)

    def initialize_live_view_categories(self):
        """Initialize live view with ALL available categories from both
        Selection and Domains tabs. Delegates to the live-view rebuild, which
        does the same data initialisation and additionally preserves plot
        modes and code-group structure."""
        self.rebuild_category_tree_live_view()


    def on_extent_mode_changed(self, state):
        """Handle changes to 'By Map Extent' checkbox"""
        if not self.live_view_enabled:
            return

        if state == Qt.Checked:
            # If extent mode is checked, uncheck selection mode
            self.live_view_by_selection_checkbox.blockSignals(True)
            self.live_view_by_selection_checkbox.setChecked(False)
            self.live_view_by_selection_checkbox.blockSignals(False)
            QgsMessageLog.logMessage("Live View mode: By Map Extent", 'Linear Geoscience', Qgis.Info)

            # Update monitoring and data
            self.setup_live_view_monitoring()
            self.update_live_view_data()
        else:
            # If extent mode is unchecked, check selection mode
            self.live_view_by_selection_checkbox.blockSignals(True)
            self.live_view_by_selection_checkbox.setChecked(True)
            self.live_view_by_selection_checkbox.blockSignals(False)
            QgsMessageLog.logMessage("Live View mode: Switched to By Selection", 'Linear Geoscience', Qgis.Info)

            # Update monitoring and data
            self.setup_live_view_monitoring()
            self.update_live_view_data()


    def on_selection_mode_changed(self, state):
        """Handle changes to 'By Selection' checkbox"""
        if not self.live_view_enabled:
            return

        if state == Qt.Checked:
            # If selection mode is checked, uncheck extent mode
            self.live_view_by_extent_checkbox.blockSignals(True)
            self.live_view_by_extent_checkbox.setChecked(False)
            self.live_view_by_extent_checkbox.blockSignals(False)
            QgsMessageLog.logMessage("Live View mode: By Selection", 'Linear Geoscience', Qgis.Info)

            # Update monitoring and data
            self.setup_live_view_monitoring()
            self.update_live_view_data()
        else:
            # If selection mode is unchecked, check extent mode
            self.live_view_by_extent_checkbox.blockSignals(True)
            self.live_view_by_extent_checkbox.setChecked(True)
            self.live_view_by_extent_checkbox.blockSignals(False)
            QgsMessageLog.logMessage("Live View mode: Switched to By Map Extent", 'Linear Geoscience', Qgis.Info)

            # Update monitoring and data
            self.setup_live_view_monitoring()
            self.update_live_view_data()


    def on_domain_mode_changed(self, state):
        """Handle changes to 'By Domain' checkbox"""
        if not self.live_view_enabled:
            return

        if state == Qt.Checked:
            QgsMessageLog.logMessage("Live View mode: By Domain", 'Linear Geoscience', Qgis.Info)

            # Rebuild category tree with domain categories
            self.rebuild_category_tree_live_view_domains()

            # Clear plot - don't populate until categories are selected
            for i in range(2):
                self.subtype_dict_live_view[i].clear()
            self.update_plot()
        else:
            QgsMessageLog.logMessage("Live View mode: Domain disabled", 'Linear Geoscience', Qgis.Info)

            # Rebuild category tree with regular categories
            self.rebuild_category_tree_live_view()

            # Update monitoring and data
            self.update_live_view_data()


    def on_map_extent_changed(self):
        """Handle map canvas extent changes with smart timing"""
        if not self.live_view_enabled:
            return

        current_extent = self.map_canvas.extent()

        try:
            # First update: instant
            if self.last_extent is None:
                self.last_extent = current_extent
                self.update_live_view_data()
                return

            # Subsequent updates: delayed
            self.last_extent = current_extent

            # Restart timer for delayed update
            if self.extent_change_timer.isActive():
                self.extent_change_timer.stop()

            self.extent_change_timer.start(self.update_delay_ms)
        except RuntimeError:
            # Our widgets/timers were deleted (plugin reloaded) but the map
            # canvas signal still points at this stale instance - sever it
            if self.map_canvas:
                try:
                    self.map_canvas.extentsChanged.disconnect(self.on_map_extent_changed)
                except Exception:
                    pass


    def update_live_view_data(self):
        """Update live view data based on current mode and checked categories"""
        if not self.live_view_enabled:
            QgsMessageLog.logMessage("update_live_view_data: Live view not enabled", 'Linear Geoscience', Qgis.Info)
            return

        QgsMessageLog.logMessage("=== update_live_view_data called ===", 'Linear Geoscience', Qgis.Info)

        # Get list of checked categories (group members live one level down;
        # their per-code keys are what the update_single_category_* fns need)
        checked_categories = []
        if self.category_tree_live_view:
            for i in range(self.category_tree_live_view.topLevelItemCount()):
                item = self.category_tree_live_view.topLevelItem(i)
                data = item.data(0, Qt.UserRole)
                if isinstance(data, dict) and data.get("is_group"):
                    for j in range(item.childCount()):
                        child = item.child(j)
                        cdata = child.data(0, Qt.UserRole)
                        if child.checkState(0) == Qt.Checked and isinstance(cdata, tuple):
                            checked_categories.append((cdata[0], cdata[1]))
                            QgsMessageLog.logMessage(f"  Checked category: '{cdata[0]}' [Dataset {cdata[1] + 1}] (group '{data['group']}')", 'Linear Geoscience', Qgis.Info)
                elif item.checkState(0) == Qt.Checked:
                    if isinstance(data, tuple):
                        code_str, dataset_idx = data
                        checked_categories.append((code_str, dataset_idx))
                        QgsMessageLog.logMessage(f"  Checked category: '{code_str}' [Dataset {dataset_idx + 1}]", 'Linear Geoscience', Qgis.Info)

        # Combined mode: tree rows carry merged keys with ds 0 — fan each one
        # out to every enabled dataset, resolving per-dataset key variants
        if self._combined_mode():
            expanded = []
            for key, _ in checked_categories:
                for ds in range(2):
                    if not self.dataset_configs[ds]["enabled"]:
                        continue
                    resolved = self._resolve_ds_key(self.subtype_dict_live_view, ds, key)
                    if resolved is not None:
                        expanded.append((resolved, ds))
            checked_categories = expanded

        QgsMessageLog.logMessage(f"  Total checked categories: {len(checked_categories)}", 'Linear Geoscience', Qgis.Info)

        if len(checked_categories) == 0:
            QgsMessageLog.logMessage("  WARNING: No categories are checked!", 'Linear Geoscience', Qgis.Warning)
            return

        # Clear data only for checked categories
        for code_str, dataset_idx in checked_categories:
            if code_str in self.subtype_dict_live_view[dataset_idx]:
                self.subtype_dict_live_view[dataset_idx][code_str].clear()

        # Update data based on current mode
        # Check if domain mode is enabled
        is_domain_mode = self.live_view_by_domain_checkbox.isChecked()
        QgsMessageLog.logMessage(f"  Domain mode: {is_domain_mode}", 'Linear Geoscience', Qgis.Info)
        QgsMessageLog.logMessage(f"  Extent mode: {self.live_view_by_extent_checkbox.isChecked()}", 'Linear Geoscience', Qgis.Info)
        QgsMessageLog.logMessage(f"  Selection mode: {self.live_view_by_selection_checkbox.isChecked()}", 'Linear Geoscience', Qgis.Info)

        if self.live_view_by_extent_checkbox.isChecked():
            # Update by map extent (with or without domain filtering)
            if self.map_canvas:
                canvas_extent = self.map_canvas.extent()
                QgsMessageLog.logMessage(f"  Using map extent: {canvas_extent}", 'Linear Geoscience', Qgis.Info)
                for code_str, dataset_idx in checked_categories:
                    if self.dataset_configs[dataset_idx]["enabled"]:
                        if is_domain_mode:
                            QgsMessageLog.logMessage(f"  Calling update_single_category_live_view_by_domain_extent for '{code_str}'", 'Linear Geoscience', Qgis.Info)
                            self.update_single_category_live_view_by_domain_extent(dataset_idx, code_str, canvas_extent)
                        else:
                            QgsMessageLog.logMessage(f"  Calling update_single_category_live_view_by_extent for '{code_str}'", 'Linear Geoscience', Qgis.Info)
                            self.update_single_category_live_view_by_extent(dataset_idx, code_str, canvas_extent)

        elif self.live_view_by_selection_checkbox.isChecked():
            # Update by selection (with or without domain filtering)
            for code_str, dataset_idx in checked_categories:
                if self.dataset_configs[dataset_idx]["enabled"]:
                    if is_domain_mode:
                        QgsMessageLog.logMessage(f"  Calling update_single_category_live_view_by_domain_selection for '{code_str}'", 'Linear Geoscience', Qgis.Info)
                        self.update_single_category_live_view_by_domain_selection(dataset_idx, code_str)
                    else:
                        QgsMessageLog.logMessage(f"  Calling update_single_category_live_view_by_selection for '{code_str}'", 'Linear Geoscience', Qgis.Info)
                        self.update_single_category_live_view_by_selection(dataset_idx, code_str)

        # Update plot if live view is active
        if self.categories_tabwidget and self.categories_tabwidget.currentIndex() == 2:
            self.update_plot()

        QgsMessageLog.logMessage(f"=== update_live_view_data complete: {len(checked_categories)} checked categories ===", 'Linear Geoscience', Qgis.Info)

        # Debug: Show what data we have
        for dataset_idx in range(2):
            for cat_code, data_list in self.subtype_dict_live_view[dataset_idx].items():
                if len(data_list) > 0:
                    QgsMessageLog.logMessage(f"  Dataset {dataset_idx + 1}, '{cat_code}': {len(data_list)} data points", 'Linear Geoscience', Qgis.Info)


    def on_selection_changed(self):
        """Handle selection changes in live view by selection mode"""
        # Ignore selection changes made by clicking points on the stereonet
        # itself, or the plot would collapse to just the clicked points
        if self._suppress_selection_replot:
            return
        try:
            active = (self.live_view_enabled and
                      self.live_view_by_selection_checkbox.isChecked())
        except RuntimeError:
            # Our widgets were deleted (plugin reloaded) but a layer signal
            # still points at this stale instance - sever it and bail out
            self._disconnect_stale_selection_signals()
            return
        if not active:
            return

        QgsMessageLog.logMessage("Selection changed - updating live view", 'Linear Geoscience', Qgis.Info)
        self.update_live_view_data()


    def update_single_category_live_view_by_selection(self, dataset_index, target_code):
        """Update live view data for a single category based on current selection"""
        layer = self.get_layer(dataset_index)
        if not layer or layer.selectedFeatureCount() == 0:
            QgsMessageLog.logMessage(f"No selection in dataset {dataset_index + 1} for category {target_code}", 'Linear Geoscience', Qgis.Info)
            return

        # Get field selection combo boxes
        dip_combo = self.dataset_configs[dataset_index].get("dip_combo")
        dipdir_combo = self.dataset_configs[dataset_index].get("dipdir_combo")
        subtype_combo = self.dataset_configs[dataset_index].get("subtype_combo")

        if not all([dip_combo, dipdir_combo, subtype_combo]):
            return

        # Get selected field names
        dip_field = dip_combo.currentText()
        dipdir_field = dipdir_combo.currentText()
        subtype_field = subtype_combo.currentText()

        if not all([dip_field, dipdir_field, subtype_field]):
            return

        added_points_count = 0

        # Process only selected features
        for f in layer.selectedFeatures():
            try:
                sv = f.attribute(subtype_field)
                dv = f.attribute(dip_field)
                ddv = f.attribute(dipdir_field)

                if sv is None or dv is None or ddv is None or str(sv).strip() == '' or str(dv).strip() == '' or str(
                        ddv).strip() == '':
                    continue

                dip, dipdir = float(dv), float(ddv)
            except (ValueError, TypeError):
                continue

            if not (isinstance(dip, (int, float)) and isinstance(dipdir, (int, float))):
                continue

            unified = unify_fax_code(str(sv).upper())

            # Only process if this matches our target code
            if unified != target_code:
                continue

            struct_type = classify_code(unified)
            if not struct_type:
                continue

            # Get geometry for coordinates
            geom = f.geometry()
            if geom and not geom.isEmpty():
                point = geom.asPoint()
                x_coord = point.x()
                y_coord = point.y()
            else:
                x_coord = None
                y_coord = None

            pitch_val = None
            # Find pitch field case-insensitively
            fields_in_layer = {f.name() for f in layer.fields()}
            pitch_field_name = next((name for name in fields_in_layer if name.lower() == "pitch"), None)
            if pitch_field_name:
                tmp = f.attribute(pitch_field_name)
                if tmp not in (None, "NULL", ""):
                    try:
                        pitch_val = float(tmp)
                    except (ValueError, TypeError):
                        pass

            data_dict = {
                "dip": dip,
                "dipdir": dipdir,
                "pitch": pitch_val,
                "dataset": dataset_index,
                "feature_id": f.id(),
                "x": x_coord,
                "y": y_coord
            }

            # Add to the specific category
            if target_code in self.subtype_dict_live_view[dataset_index]:
                self.subtype_dict_live_view[dataset_index][target_code].append(data_dict)
                added_points_count += 1

        QgsMessageLog.logMessage(
            f"[Dataset {dataset_index + 1} Live View - Selection] Added {added_points_count} points for category '{target_code}'", 'Linear Geoscience', Qgis.Info)


    def update_single_category_live_view_by_extent(self, dataset_index, target_code, canvas_extent):
        """Update live view data for a single category based on current map extent (existing function)"""
        from qgis.core import QgsFeatureRequest, QgsCoordinateTransform, QgsProject

        layer = self.get_layer(dataset_index)
        if not layer:
            return

        # Get field selection combo boxes
        dip_combo = self.dataset_configs[dataset_index].get("dip_combo")
        dipdir_combo = self.dataset_configs[dataset_index].get("dipdir_combo")
        subtype_combo = self.dataset_configs[dataset_index].get("subtype_combo")

        if not all([dip_combo, dipdir_combo, subtype_combo]):
            return

        # Get selected field names
        dip_field = dip_combo.currentText()
        dipdir_field = dipdir_combo.currentText()
        subtype_field = subtype_combo.currentText()

        if not all([dip_field, dipdir_field, subtype_field]):
            return

        # Transform extent to layer CRS if needed
        map_crs = self.map_canvas.mapSettings().destinationCrs()
        layer_crs = layer.crs()

        if map_crs != layer_crs:
            transform = QgsCoordinateTransform(map_crs, layer_crs, QgsProject.instance())
            try:
                transformed_extent = transform.transformBoundingBox(canvas_extent)
            except Exception:
                QgsMessageLog.logMessage(f"Failed to transform extent for dataset {dataset_index + 1}", 'Linear Geoscience', Qgis.Warning)
                return
        else:
            transformed_extent = canvas_extent

        # Create spatial filter request
        request = QgsFeatureRequest().setFilterRect(transformed_extent)

        added_points_count = 0

        # Process features within the current extent
        for f in layer.getFeatures(request):
            try:
                sv = f.attribute(subtype_field)
                dv = f.attribute(dip_field)
                ddv = f.attribute(dipdir_field)

                if sv is None or dv is None or ddv is None or str(sv).strip() == '' or str(dv).strip() == '' or str(
                        ddv).strip() == '':
                    continue

                dip, dipdir = float(dv), float(ddv)
            except (ValueError, TypeError):
                continue

            if not (isinstance(dip, (int, float)) and isinstance(dipdir, (int, float))):
                continue

            unified = unify_fax_code(str(sv).upper())

            # Only process if this matches our target code
            if unified != target_code:
                continue

            struct_type = classify_code(unified)
            if not struct_type:
                continue

            # Get geometry for coordinates
            geom = f.geometry()
            if geom and not geom.isEmpty():
                point = geom.asPoint()
                x_coord = point.x()
                y_coord = point.y()
            else:
                x_coord = None
                y_coord = None

            pitch_val = None
            # Find pitch field case-insensitively
            fields_in_layer = {f.name() for f in layer.fields()}
            pitch_field_name = next((name for name in fields_in_layer if name.lower() == "pitch"), None)
            if pitch_field_name:
                tmp = f.attribute(pitch_field_name)
                if tmp not in (None, "NULL", ""):
                    try:
                        pitch_val = float(tmp)
                    except (ValueError, TypeError):
                        pass

            data_dict = {
                "dip": dip,
                "dipdir": dipdir,
                "pitch": pitch_val,
                "dataset": dataset_index,
                "feature_id": f.id(),
                "x": x_coord,
                "y": y_coord
            }

            # Add to the specific category
            if target_code in self.subtype_dict_live_view[dataset_index]:
                self.subtype_dict_live_view[dataset_index][target_code].append(data_dict)
                added_points_count += 1

        QgsMessageLog.logMessage(
            f"[Dataset {dataset_index + 1} Live View - Extent] Added {added_points_count} points for category '{target_code}'", 'Linear Geoscience', Qgis.Info)


    def update_single_category_live_view_by_domain_extent(self, dataset_index, target_domain_code, canvas_extent):
        """Update live view data for a single domain category based on current map extent"""
        from qgis.core import QgsFeatureRequest, QgsCoordinateTransform, QgsProject

        layer = self.get_layer(dataset_index)
        if not layer:
            return

        # Parse the domain category: "CODE - DomainValue (Dataset)" or "CODE - DomainValue"
        if " - " not in target_domain_code:
            QgsMessageLog.logMessage(f"Invalid domain category format: {target_domain_code}", 'Linear Geoscience', Qgis.Warning)
            return

        target_code, target_domain = target_domain_code.split(" - ", 1)

        # Remove dataset name from target_domain if present: "DOMAIN (Dataset)" -> "DOMAIN"
        if " (" in target_domain and target_domain.endswith(")"):
            target_domain = target_domain.split(" (")[0]

        # Get field selection combo boxes
        dip_combo = self.dataset_configs[dataset_index].get("dip_combo")
        dipdir_combo = self.dataset_configs[dataset_index].get("dipdir_combo")
        subtype_combo = self.dataset_configs[dataset_index].get("subtype_combo")
        domain_combo = self.dataset_configs[dataset_index].get("domain_combo")

        if not all([dip_combo, dipdir_combo, subtype_combo, domain_combo]):
            return

        # Get selected field names
        dip_field = dip_combo.currentText()
        dipdir_field = dipdir_combo.currentText()
        subtype_field = subtype_combo.currentText()
        domain_field = domain_combo.currentText()

        if not all([dip_field, dipdir_field, subtype_field, domain_field]):
            QgsMessageLog.logMessage(f"[Dataset {dataset_index + 1}] Domain field not configured for domain mode", 'Linear Geoscience', Qgis.Info)
            return

        # Check if domain field exists
        fields = [f.name() for f in layer.fields()]
        if domain_field not in fields:
            QgsMessageLog.logMessage(f"[Dataset {dataset_index + 1}] Domain field '{domain_field}' not found in layer", 'Linear Geoscience', Qgis.Warning)
            return

        # Get the field index for the domain field
        domain_field_index = layer.fields().indexOf(domain_field)

        # Transform extent to layer CRS if needed
        map_crs = self.map_canvas.mapSettings().destinationCrs()
        layer_crs = layer.crs()

        if map_crs != layer_crs:
            transform = QgsCoordinateTransform(map_crs, layer_crs, QgsProject.instance())
            try:
                transformed_extent = transform.transformBoundingBox(canvas_extent)
            except Exception:
                QgsMessageLog.logMessage(f"Failed to transform extent for dataset {dataset_index + 1}", 'Linear Geoscience', Qgis.Warning)
                return
        else:
            transformed_extent = canvas_extent

        # Create spatial filter request
        request = QgsFeatureRequest().setFilterRect(transformed_extent)

        added_points_count = 0
        processed_count = 0
        code_mismatch_count = 0
        domain_mismatch_count = 0
        found_domains_for_code = set()  # Track what domain values we find for this code

        QgsMessageLog.logMessage(f"    DEBUG: Looking for code='{target_code}', domain='{target_domain}'", 'Linear Geoscience', Qgis.Info)

        # Process features within the current extent
        for f in layer.getFeatures(request):
            processed_count += 1
            try:
                sv = f.attribute(subtype_field)
                dv = f.attribute(dip_field)
                ddv = f.attribute(dipdir_field)
                domain_val = f.attribute(domain_field)

                if sv is None or dv is None or ddv is None or str(sv).strip() == '' or str(dv).strip() == '' or str(
                        ddv).strip() == '':
                    continue

                dip, dipdir = float(dv), float(ddv)
            except (ValueError, TypeError):
                continue

            if not (isinstance(dip, (int, float)) and isinstance(dipdir, (int, float))):
                continue

            unified = unify_fax_code(str(sv).upper())

            # Only process if this matches our target code
            if unified != target_code:
                if processed_count <= 5:  # Only log first 5 mismatches
                    QgsMessageLog.logMessage(f"    DEBUG: Code mismatch - found '{unified}', need '{target_code}'", 'Linear Geoscience', Qgis.Info)
                code_mismatch_count += 1
                continue

            # Get display value for domain (same logic as update_data_domains)
            if domain_val is None:
                domain_display = "NoDomain"
            else:
                try:
                    editor_widget_setup = layer.editorWidgetSetup(domain_field_index)

                    if editor_widget_setup.type() == 'ValueRelation':
                        from qgis.core import QgsValueRelationFieldFormatter
                        formatter = QgsValueRelationFieldFormatter()
                        context = layer.createExpressionContext()
                        context.setFeature(f)
                        display_value = formatter.representValue(layer, domain_field_index,
                                                                 editor_widget_setup.config(), None, domain_val)
                        if display_value and display_value != str(domain_val):
                            domain_display = display_value
                        else:
                            domain_display = str(domain_val)
                    elif editor_widget_setup.type() == 'ValueMap':
                        value_map = editor_widget_setup.config().get('map', {})
                        domain_display = str(domain_val)
                        for display_name, stored_value in value_map.items():
                            if str(stored_value) == str(domain_val):
                                domain_display = display_name
                                break
                    else:
                        domain_display = str(domain_val)
                except Exception as e:
                    domain_display = str(domain_val)

            # Only process if domain matches
            if domain_display != target_domain:
                found_domains_for_code.add(domain_display)  # Track what we found
                if processed_count <= 5:  # Only log first 5 mismatches
                    QgsMessageLog.logMessage(f"    DEBUG: Domain mismatch - found '{domain_display}', need '{target_domain}'", 'Linear Geoscience', Qgis.Info)
                domain_mismatch_count += 1
                continue

            struct_type = classify_code(unified)
            if not struct_type:
                continue

            # Get geometry for coordinates
            geom = f.geometry()
            if geom and not geom.isEmpty():
                point = geom.asPoint()
                x_coord = point.x()
                y_coord = point.y()
            else:
                x_coord = None
                y_coord = None

            pitch_val = None
            fields_in_layer = {f.name() for f in layer.fields()}
            pitch_field_name = next((name for name in fields_in_layer if name.lower() == "pitch"), None)
            if pitch_field_name:
                tmp = f.attribute(pitch_field_name)
                if tmp not in (None, "NULL", ""):
                    try:
                        pitch_val = float(tmp)
                    except (ValueError, TypeError):
                        pass

            data_dict = {
                "dip": dip,
                "dipdir": dipdir,
                "pitch": pitch_val,
                "dataset": dataset_index,
                "feature_id": f.id(),
                "x": x_coord,
                "y": y_coord,
                "domain": domain_display
            }

            # Add to the specific domain category
            if target_domain_code in self.subtype_dict_live_view[dataset_index]:
                self.subtype_dict_live_view[dataset_index][target_domain_code].append(data_dict)
                added_points_count += 1

        QgsMessageLog.logMessage(
            f"[Dataset {dataset_index + 1} Live View - Domain Extent] Added {added_points_count} points for category '{target_domain_code}'", 'Linear Geoscience', Qgis.Info)
        QgsMessageLog.logMessage(f"    DEBUG: Processed {processed_count} features, {code_mismatch_count} code mismatches, {domain_mismatch_count} domain mismatches", 'Linear Geoscience', Qgis.Info)
        if found_domains_for_code:
            QgsMessageLog.logMessage(f"    DEBUG: Found these domain values for code '{target_code}': {sorted(found_domains_for_code)}", 'Linear Geoscience', Qgis.Info)


    def update_single_category_live_view_by_domain_selection(self, dataset_index, target_domain_code):
        """Update live view data for a single domain category based on current selection"""
        layer = self.get_layer(dataset_index)
        if not layer or layer.selectedFeatureCount() == 0:
            QgsMessageLog.logMessage(f"No selection in dataset {dataset_index + 1} for category {target_domain_code}", 'Linear Geoscience', Qgis.Info)
            return

        # Parse the domain category: "CODE - DomainValue (Dataset)" or "CODE - DomainValue"
        if " - " not in target_domain_code:
            QgsMessageLog.logMessage(f"Invalid domain category format: {target_domain_code}", 'Linear Geoscience', Qgis.Warning)
            return

        target_code, target_domain = target_domain_code.split(" - ", 1)

        # Remove dataset name from target_domain if present: "DOMAIN (Dataset)" -> "DOMAIN"
        if " (" in target_domain and target_domain.endswith(")"):
            target_domain = target_domain.split(" (")[0]

        # Get field selection combo boxes
        dip_combo = self.dataset_configs[dataset_index].get("dip_combo")
        dipdir_combo = self.dataset_configs[dataset_index].get("dipdir_combo")
        subtype_combo = self.dataset_configs[dataset_index].get("subtype_combo")
        domain_combo = self.dataset_configs[dataset_index].get("domain_combo")

        if not all([dip_combo, dipdir_combo, subtype_combo, domain_combo]):
            return

        # Get selected field names
        dip_field = dip_combo.currentText()
        dipdir_field = dipdir_combo.currentText()
        subtype_field = subtype_combo.currentText()
        domain_field = domain_combo.currentText()

        if not all([dip_field, dipdir_field, subtype_field, domain_field]):
            QgsMessageLog.logMessage(f"[Dataset {dataset_index + 1}] Domain field not configured for domain mode", 'Linear Geoscience', Qgis.Info)
            return

        # Check if domain field exists
        fields = [f.name() for f in layer.fields()]
        if domain_field not in fields:
            QgsMessageLog.logMessage(f"[Dataset {dataset_index + 1}] Domain field '{domain_field}' not found in layer", 'Linear Geoscience', Qgis.Warning)
            return

        # Get the field index for the domain field
        domain_field_index = layer.fields().indexOf(domain_field)

        added_points_count = 0
        processed_count = 0
        code_mismatch_count = 0
        domain_mismatch_count = 0
        found_domains_for_code = set()  # Track what domain values we find for this code

        QgsMessageLog.logMessage(f"    DEBUG: Looking for code='{target_code}', domain='{target_domain}'", 'Linear Geoscience', Qgis.Info)

        # Process only selected features
        for f in layer.selectedFeatures():
            processed_count += 1
            try:
                sv = f.attribute(subtype_field)
                dv = f.attribute(dip_field)
                ddv = f.attribute(dipdir_field)
                domain_val = f.attribute(domain_field)

                if sv is None or dv is None or ddv is None or str(sv).strip() == '' or str(dv).strip() == '' or str(
                        ddv).strip() == '':
                    continue

                dip, dipdir = float(dv), float(ddv)
            except (ValueError, TypeError):
                continue

            if not (isinstance(dip, (int, float)) and isinstance(dipdir, (int, float))):
                continue

            unified = unify_fax_code(str(sv).upper())

            # Only process if this matches our target code
            if unified != target_code:
                if processed_count <= 5:  # Only log first 5 mismatches
                    QgsMessageLog.logMessage(f"    DEBUG: Code mismatch - found '{unified}', need '{target_code}'", 'Linear Geoscience', Qgis.Info)
                code_mismatch_count += 1
                continue

            # Get display value for domain (same logic as update_data_domains)
            if domain_val is None:
                domain_display = "NoDomain"
            else:
                try:
                    editor_widget_setup = layer.editorWidgetSetup(domain_field_index)

                    if editor_widget_setup.type() == 'ValueRelation':
                        from qgis.core import QgsValueRelationFieldFormatter
                        formatter = QgsValueRelationFieldFormatter()
                        context = layer.createExpressionContext()
                        context.setFeature(f)
                        display_value = formatter.representValue(layer, domain_field_index,
                                                                 editor_widget_setup.config(), None, domain_val)
                        if display_value and display_value != str(domain_val):
                            domain_display = display_value
                        else:
                            domain_display = str(domain_val)
                    elif editor_widget_setup.type() == 'ValueMap':
                        value_map = editor_widget_setup.config().get('map', {})
                        domain_display = str(domain_val)
                        for display_name, stored_value in value_map.items():
                            if str(stored_value) == str(domain_val):
                                domain_display = display_name
                                break
                    else:
                        domain_display = str(domain_val)
                except Exception as e:
                    domain_display = str(domain_val)

            # Only process if domain matches
            if domain_display != target_domain:
                found_domains_for_code.add(domain_display)  # Track what we found
                if processed_count <= 5:  # Only log first 5 mismatches
                    QgsMessageLog.logMessage(f"    DEBUG: Domain mismatch - found '{domain_display}', need '{target_domain}'", 'Linear Geoscience', Qgis.Info)
                domain_mismatch_count += 1
                continue

            struct_type = classify_code(unified)
            if not struct_type:
                continue

            # Get geometry for coordinates
            geom = f.geometry()
            if geom and not geom.isEmpty():
                point = geom.asPoint()
                x_coord = point.x()
                y_coord = point.y()
            else:
                x_coord = None
                y_coord = None

            pitch_val = None
            fields_in_layer = {f.name() for f in layer.fields()}
            pitch_field_name = next((name for name in fields_in_layer if name.lower() == "pitch"), None)
            if pitch_field_name:
                tmp = f.attribute(pitch_field_name)
                if tmp not in (None, "NULL", ""):
                    try:
                        pitch_val = float(tmp)
                    except (ValueError, TypeError):
                        pass

            data_dict = {
                "dip": dip,
                "dipdir": dipdir,
                "pitch": pitch_val,
                "dataset": dataset_index,
                "feature_id": f.id(),
                "x": x_coord,
                "y": y_coord,
                "domain": domain_display
            }

            # Add to the specific domain category
            if target_domain_code in self.subtype_dict_live_view[dataset_index]:
                self.subtype_dict_live_view[dataset_index][target_domain_code].append(data_dict)
                added_points_count += 1

        QgsMessageLog.logMessage(
            f"[Dataset {dataset_index + 1} Live View - Domain Selection] Added {added_points_count} points for category '{target_domain_code}'", 'Linear Geoscience', Qgis.Info)
        QgsMessageLog.logMessage(f"    DEBUG: Processed {processed_count} features, {code_mismatch_count} code mismatches, {domain_mismatch_count} domain mismatches", 'Linear Geoscience', Qgis.Info)
        if found_domains_for_code:
            QgsMessageLog.logMessage(f"    DEBUG: Found these domain values for code '{target_code}': {sorted(found_domains_for_code)}", 'Linear Geoscience', Qgis.Info)


    def capture_temporary_dataset(self):
        """Capture current live view data as temporary comparison dataset"""
        if not self.live_view_enabled:
            QgsMessageLog.logMessage("Cannot capture: Live view mode is not enabled", 'Linear Geoscience', Qgis.Warning)
            return
        
        # FIRST: Completely clear any existing temporary data to start fresh
        QgsMessageLog.logMessage("Clearing any existing temporary data before capture...", 'Linear Geoscience', Qgis.Info)
        for dataset_idx in range(2):
            # Clear each category's data list explicitly
            for code_str in list(self.temporary_dataset[dataset_idx].keys()):
                self.temporary_dataset[dataset_idx][code_str].clear()
            # Clear the entire dataset dictionary
            self.temporary_dataset[dataset_idx].clear()
        
        # Reset state
        self.temporary_dataset_captured = False
        
        # Deep copy current live view data
        total_points = 0
        for dataset_idx in range(2):
            for code, data_list in self.subtype_dict_live_view[dataset_idx].items():
                if data_list:  # Only copy non-empty data
                    self.temporary_dataset[dataset_idx][code] = [dict(item) for item in data_list]
                    total_points += len(data_list)
        
        self.temporary_dataset_captured = True
        self.clear_temp_button.setEnabled(True)
        
        # Update UI and replot
        self.temp_status_label.setText(f"Temporary dataset captured ({total_points} points)")
        self.temp_status_label.setVisible(True)
        
        QgsMessageLog.logMessage(f"Captured {total_points} points as temporary comparison dataset", 'Linear Geoscience', Qgis.Info)
        self.update_plot()


    def clear_temporary_dataset(self):
        """Clear temporary comparison dataset completely and permanently"""
        # Count points before clearing for verification
        total_points_before = sum(
            len(data_list) for dataset in self.temporary_dataset 
            for data_list in dataset.values()
        )
        
        # Clear temporary data completely - use explicit clearing
        for dataset_idx in range(2):
            # Clear each category's data list
            for code_str in list(self.temporary_dataset[dataset_idx].keys()):
                self.temporary_dataset[dataset_idx][code_str].clear()
            # Clear the entire dataset dictionary
            self.temporary_dataset[dataset_idx].clear()
        
        # Reset all temporary dataset state flags
        self.temporary_dataset_captured = False
        
        # Update UI state
        self.clear_temp_button.setEnabled(False)
        self.temp_status_label.setVisible(False)
        
        # Verify clearing worked
        total_points_after = sum(
            len(data_list) for dataset in self.temporary_dataset 
            for data_list in dataset.values()
        )
        
        QgsMessageLog.logMessage(f"Cleared temporary comparison dataset: {total_points_before} points removed", 'Linear Geoscience', Qgis.Info)
        if total_points_after > 0:
            QgsMessageLog.logMessage(f"WARNING: {total_points_after} points still remain after clearing!", 'Linear Geoscience', Qgis.Warning)
        else:
            QgsMessageLog.logMessage("Temporary dataset completely cleared - verified empty", 'Linear Geoscience', Qgis.Info)
        
        # Force plot update to remove any lingering temporary markers
        self.update_plot()


    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def calculate_plane_intersection_points(self, planes_data):
        """
        Calculate all intersection points between all possible plane pairs.

        Parameters:
        - planes_data: List of dictionaries containing plane data with 'dip' and 'dipdir' keys

        Returns:
        - List of intersection points as (plunge, bearing) tuples
        """
        import numpy as np

        # Function to convert dip/dipdir to plane normal vector
        def plane_to_normal(dip, dipdir):
            # Convert to radians
            dip_rad = np.radians(dip)
            dipdir_rad = np.radians(dipdir)

            # Calculate normal vector components
            nx = -np.sin(dip_rad) * np.sin(dipdir_rad)
            ny = -np.sin(dip_rad) * np.cos(dipdir_rad)
            nz = np.cos(dip_rad)

            return np.array([nx, ny, nz])

        # Function to calculate the intersection line between two planes
        def calculate_intersection(plane1, plane2):
            # Extract dip and dipdir from plane dictionaries
            dip1, dipdir1 = plane1['dip'], plane1['dipdir']
            dip2, dipdir2 = plane2['dip'], plane2['dipdir']

            # Get normal vectors
            normal1 = plane_to_normal(dip1, dipdir1)
            normal2 = plane_to_normal(dip2, dipdir2)

            # Check if planes are parallel (cross product near zero)
            cross_product = np.cross(normal1, normal2)
            if np.linalg.norm(cross_product) < 1e-6:
                return None  # Planes are parallel or coincident

            # Normalize the cross product to get the direction vector of the intersection line
            line_vector = cross_product / np.linalg.norm(cross_product)

            # Convert line vector to plunge/bearing
            # Plunge is the angle between line vector and horizontal plane
            plunge = np.degrees(np.arcsin(line_vector[2]))

            # Bearing is the azimuth of the projection of the line onto the horizontal plane
            bearing = np.degrees(np.arctan2(line_vector[0], line_vector[1]))
            if bearing < 0:
                bearing += 360.0

            # Ensure plunge is positive by flipping the line direction if needed
            if plunge < 0:
                plunge = -plunge
                bearing = (bearing + 180) % 360

            return (plunge, bearing)

        # Calculate all pairwise intersections
        intersections = []
        for i in range(len(planes_data)):
            for j in range(i + 1, len(planes_data)):
                intersection = calculate_intersection(planes_data[i], planes_data[j])
                if intersection:
                    intersections.append(intersection)

        return intersections


    def add_intersection_contours(self, ax, plane_data=None):
        """
        Add intersection contours to an existing stereonet plot.

        Parameters:
        - ax: Matplotlib stereonet axis
        - plane_data: List of dictionaries containing plane data (optional)
                      If None, will collect planes from selected data

        Returns:
        - Number of intersections processed
        """
        # If no plane data provided, collect from selected categories
        if plane_data is None:
            plane_data = []

            # Process each dataset
            for dataset_idx in range(len(self.dataset_configs)):
                if not self.dataset_configs[dataset_idx]["enabled"]:
                    continue

                # Get data from selection tab
                category_tree = self.category_tree_selection
                for i in range(category_tree.topLevelItemCount()):
                    item = category_tree.topLevelItem(i)
                    if item.checkState(0) == Qt.Checked:
                        # Get both code and dataset index
                        data = item.data(0, Qt.UserRole)
                        if isinstance(data, tuple):
                            code_str, item_dataset_idx = data
                        else:
                            # For backward compatibility
                            code_str = data
                            item_dataset_idx = 0

                        # Only process if it matches the current dataset and is a plane
                        if item_dataset_idx == dataset_idx and code_str in self.category_structure_map_selection[
                            dataset_idx]:
                            struct_type = self.category_structure_map_selection[dataset_idx][code_str]
                            if struct_type == "plane":
                                # Add all planes from this category
                                plane_data.extend(self.subtype_dict_selection[dataset_idx][code_str])

                # Also get data from domains tab
                domain_tree = self.category_tree_domains
                for i in range(domain_tree.topLevelItemCount()):
                    item = domain_tree.topLevelItem(i)
                    if item.checkState(0) == Qt.Checked:
                        # Get both code and dataset index
                        data = item.data(0, Qt.UserRole)
                        if isinstance(data, tuple):
                            if len(data) >= 5:
                                # New format: (st, dataset_idx, code, domain, dataset_name)
                                code_str, item_dataset_idx = data[0], data[1]
                            else:
                                # Old format: (code_str, dataset_idx)
                                code_str, item_dataset_idx = data
                        else:
                            # For backward compatibility
                            code_str = data
                            item_dataset_idx = 0

                        # Only process if it matches the current dataset and is a plane
                        if item_dataset_idx == dataset_idx and code_str in self.category_structure_map_domains[
                            dataset_idx]:
                            struct_type = self.category_structure_map_domains[dataset_idx][code_str]
                            if struct_type == "plane":
                                # Add all planes from this category
                                plane_data.extend(self.subtype_dict_domains[dataset_idx][code_str])

        # Check if we have enough planes
        if len(plane_data) < 2:
            return 0

        # Calculate all pairwise intersections
        intersections = self.calculate_plane_intersection_points(plane_data)

        if not intersections:
            return 0

        # Extract plunges and bearings for plotting
        plunges = [p[0] for p in intersections]
        bearings = [p[1] for p in intersections]

        # Plot the intersections as nearly invisible points
        # (so they don't distract but contribute to density calculation)
        ax.line(plunges, bearings, marker='.', markersize=1, color='gray', alpha=0.05,
                linestyle='none')

        # Create contours from the intersection points
        # The contours will be on top since they're being plotted last
        if len(intersections) >= 10:  # Need enough points for meaningful contours
            ax.density_contour(
                plunges,
                bearings,
                measurement='lines',
                sigma=2.0,  # Adjust based on point density
                cmap='viridis',
                levels=10,  # Number of contour levels
                alpha=0.7  # Make it slightly transparent to see underlying data
            )

        return len(intersections)

    # Function to create an "Intersection Contours" checkbox in the Plot tab


    def unload(self):
        QgsMessageLog.logMessage("Unloading Stereonet Plugin...", 'Linear Geoscience', Qgis.Info)

        # Stop timers
        for timer_name in ('extent_change_timer', 'plot_update_timer'):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()

        # Disconnect interactive pick handling from the plot canvas
        if self.pick_handler is not None:
            self.pick_handler.disconnect()

        # Clean up live view mode (disconnects canvas/selection signals)
        self.cleanup_live_view_mode()

        # Disconnect project-level layer registry signals
        project = QgsProject.instance()
        for i, handler in enumerate(self._project_signal_connections):
            if handler is None:
                continue
            for signal in (project.layersAdded, project.layersRemoved):
                try:
                    signal.disconnect(handler)
                except Exception:
                    pass
            self._project_signal_connections[i] = None

        # Release any matplotlib figures still registered
        plt.close('all')

        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None


    def create_layer_combo_with_source(self, dataset_idx):
        """Create a combo box showing layer names with their sources - improved version"""
        # Create a standard combo box
        combo = QComboBox()
        combo.clear()

        # Add an empty option first
        combo.addItem("")

        # Get all vector layers
        layers = []
        for layer in QgsProject.instance().mapLayers().values():
            # Check if it's a vector layer without using QgsMapLayer.VectorLayer
            if hasattr(layer, 'geometryType'):  # Only vector layers have this method
                layers.append(layer)

        # Dictionary to store layers by display name
        if not hasattr(self, 'layer_maps'):
            self.layer_maps = [{}, {}]  # One map for each dataset

        # Clear the map for this dataset
        self.layer_maps[dataset_idx] = {}

        # Add each layer with its source
        for layer in layers:
            try:
                source = layer.source()

                # Extract the filename from source path
                import os
                if '|' in source:
                    base_path = source.split('|')[0]
                else:
                    base_path = source

                filename = os.path.basename(base_path)

                # Limit filename to 30 characters
                if len(filename) > 30:
                    filename = filename[:17] + "..."

                display_name = f"{layer.name()} [{filename}]"

                # Make sure display name is unique
                counter = 1
                original_display_name = display_name
                while display_name in self.layer_maps[dataset_idx]:
                    display_name = f"{original_display_name} ({counter})"
                    counter += 1

            except Exception:
                # Fallback if source extraction fails
                display_name = layer.name()

                # Ensure unique display name
                counter = 1
                original_display_name = display_name
                while display_name in self.layer_maps[dataset_idx]:
                    display_name = f"{original_display_name} ({counter})"
                    counter += 1

            # Add to combo and store in map
            combo.addItem(display_name)
            self.layer_maps[dataset_idx][display_name] = layer

        # Connect to a handler that updates fields when selection changes
        combo.currentTextChanged.connect(
            lambda text, idx=dataset_idx: self.handle_layer_selection(text, idx)
        )

        # Monitor layer registry changes to update the combo box when layers are added/removed.
        # Store the handler so it can be disconnected on unload (and so re-creating the
        # combo for a dataset doesn't stack duplicate connections).
        old_handler = self._project_signal_connections[dataset_idx]
        if old_handler is not None:
            for signal in (QgsProject.instance().layersAdded, QgsProject.instance().layersRemoved):
                try:
                    signal.disconnect(old_handler)
                except Exception:
                    pass
        handler = partial(self._on_project_layers_changed, dataset_idx)
        QgsProject.instance().layersAdded.connect(handler)
        QgsProject.instance().layersRemoved.connect(handler)
        self._project_signal_connections[dataset_idx] = handler

        return combo


    def _on_project_layers_changed(self, dataset_idx, *args):
        """Slot for QgsProject layersAdded/layersRemoved; ignores the signal's layer list."""
        self.refresh_layer_combo(dataset_idx)


    def handle_layer_selection(self, display_name, dataset_idx):
        """Handle when a layer is selected in the custom combo box - improved version"""
        if not display_name:  # Empty selection
            return

        if not hasattr(self, 'layer_maps'):
            self.layer_maps = [{}, {}]
            QgsMessageLog.logMessage(f"Layer maps not initialized for dataset {dataset_idx + 1}", 'Linear Geoscience', Qgis.Info)
            return

        if display_name in self.layer_maps[dataset_idx]:
            # Get the actual layer object
            layer = self.layer_maps[dataset_idx][display_name]

            if not layer.isValid():
                QgsMessageLog.logMessage(f"Selected layer is not valid for dataset {dataset_idx + 1}", 'Linear Geoscience', Qgis.Warning)
                return

            QgsMessageLog.logMessage(f"Selected layer '{layer.name()}' for dataset {dataset_idx + 1}", 'Linear Geoscience', Qgis.Info)

            # Populate fields
            self.populate_field_combo_boxes(dataset_idx, layer)
        else:
            QgsMessageLog.logMessage(f"Layer '{display_name}' not found in layer map for dataset {dataset_idx + 1}", 'Linear Geoscience', Qgis.Warning)


    def toggle_dataset(self, dataset_index, state):
        """Enable or disable a dataset"""
        self.dataset_configs[dataset_index]["enabled"] = (state == Qt.Checked)
        QgsMessageLog.logMessage(f"Dataset {dataset_index + 1} {'enabled' if state == Qt.Checked else 'disabled'}", 'Linear Geoscience', Qgis.Info)
        
        # Update capture button state - enabled only if live view is active and any datasets are enabled
        if hasattr(self, 'capture_button'):
            any_datasets_enabled = any(self.dataset_configs[i]["enabled"] for i in range(2))
            self.capture_button.setEnabled(self.live_view_enabled and any_datasets_enabled)
        
        self.update_plot()


    def rename_dataset(self, dataset_index, name):
        """Rename a dataset"""
        self.dataset_configs[dataset_index]["name"] = name
        if hasattr(self, 'active_dataset_combo'):
            self.active_dataset_combo.setItemText(dataset_index, name)
        QgsMessageLog.logMessage(f"Dataset {dataset_index + 1} renamed to '{name}'", 'Linear Geoscience', Qgis.Info)


    def set_dataset_color(self, dataset_index):
        """Set the color for a dataset"""
        current_color = self.dataset_configs[dataset_index]["color"]
        color = QColorDialog.getColor(QColor(current_color), self.iface.mainWindow())

        if color.isValid():
            color_hex = color.name()
            self.dataset_configs[dataset_index]["color"] = color_hex

            # Update color preview in the UI
            if self.datasets_widget:
                for child in self.datasets_widget.findChildren(QFrame):
                    if child.frameShape() == QFrame.Box and child.width() == 20:
                        if child.parentWidget() == self.datasets_widget.layout().itemAt(dataset_index).widget():
                            child.setStyleSheet(f"background-color: {color_hex};")
                            break

            QgsMessageLog.logMessage(f"Dataset {dataset_index + 1} color set to {color_hex}", 'Linear Geoscience', Qgis.Info)
            self.update_plot()


    def get_marker_for_code(self, code):
        """
        Get a unique marker shape for each structure code.

        Args:
            code: The structure code (e.g., 'S1', 'S2', 'FAP')

        Returns:
            str: Matplotlib marker string
        """
        # Extract base code without domain suffix
        base_code = code
        if " - " in base_code:
            base_code = base_code.split(" - ")[0]

        # Remove dataset name if present (e.g., "CODE (Dataset Name)" -> "CODE")
        if " (" in base_code:
            base_code = base_code.split(" (")[0]

        # Define marker shapes (matplotlib markers) - expanded list for more unique assignments
        # Using only distinctly different shapes to avoid confusion
        marker_shapes = [
            'o',      # 0: circle
            's',      # 1: square
            '^',      # 2: triangle up
            'D',      # 3: diamond (large)
            '*',      # 4: star
            'X',      # 5: X (filled)
            'p',      # 6: pentagon
            'P',      # 7: plus (filled)
            'h',      # 8: hexagon1
            'H',      # 9: hexagon2
            '8',      # 10: octagon
            'd',      # 11: thin diamond
            '+',      # 12: plus (not filled)
            'x',      # 13: x (not filled)
            '1',      # 14: tri_down marker
            '2',      # 15: tri_up marker
            '3',      # 16: tri_left marker
            '4',      # 17: tri_right marker
            '.',      # 18: point
            '|',      # 19: vertical line
            '_',      # 20: horizontal line
            0,        # 21: tickleft
            1,        # 22: tickright
            2,        # 23: tickup
            3,        # 24: tickdown
        ]

        # Get all unique codes from structure_colors
        all_codes = sorted(self.structure_colors.keys())

        # Find index of this code
        if base_code in all_codes:
            code_index = all_codes.index(base_code)
            # Use modulo to cycle through markers if we have more codes than markers
            return marker_shapes[code_index % len(marker_shapes)]

        # Default marker if code not found
        return 'o'


    def generate_structure_color_map_by_domain(self, plotted_data, single_dataset_mode):
        """
        Generate a color map based on domain only (alternate plotting mode).
        Each domain gets one distinct color (same for both datasets).

        Args:
            plotted_data: List of tuples containing structure data
            single_dataset_mode: Boolean indicating if only one dataset is active

        Returns:
            Dictionary mapping (full_code_with_domain, dataset_idx) to color
        """
        color_map = {}

        # Define base domain colors - optimized for maximum perceptual distinctness
        # Uses Tableau 20 + additional distinct colors for up to 25 domains
        domain_colors = [
            "#E41A1C",  # 1. Bright red
            "#377EB8",  # 2. Strong blue
            "#4DAF4A",  # 3. Vivid green
            "#FF7F00",  # 4. Bright orange
            "#984EA3",  # 5. Purple
            "#FFFF33",  # 6. Bright yellow
            "#A65628",  # 7. Brown
            "#F781BF",  # 8. Pink
            "#00CED1",  # 9. Dark turquoise
            "#FF1493",  # 10. Deep pink
            "#32CD32",  # 11. Lime green
            "#FF4500",  # 12. Orange red
            "#1E90FF",  # 13. Dodger blue
            "#FFD700",  # 14. Gold
            "#8B4513",  # 15. Saddle brown
            "#00FA9A",  # 16. Medium spring green
            "#DC143C",  # 17. Crimson
            "#7B68EE",  # 18. Medium slate blue
            "#FF69B4",  # 19. Hot pink
            "#2E8B57",  # 20. Sea green
            "#FF8C00",  # 21. Dark orange
            "#4169E1",  # 22. Royal blue
            "#9ACD32",  # 23. Yellow green
            "#FF6347",  # 24. Tomato
            "#48D1CC",  # 25. Medium turquoise
        ]

        # Extract all unique domains
        unique_domains = set()
        for (code_str, _, _, _, _, _) in plotted_data:
            if " - " in code_str:
                # Extract domain, remove dataset name if present
                domain_part = code_str.split(" - ")[1]
                if " (" in domain_part:
                    domain = domain_part.split(" (")[0].strip()
                else:
                    domain = domain_part.strip()
                unique_domains.add(domain)

        # Create domain to color mapping
        domain_to_color = {}
        for idx, domain in enumerate(sorted(unique_domains)):
            base_color = domain_colors[idx % len(domain_colors)]
            domain_to_color[domain] = base_color

        # Assign colors to each code based on its domain
        for (code_str, _, _, _, dataset_idx, _) in plotted_data:
            domain = None
            if " - " in code_str:
                domain_part = code_str.split(" - ")[1]
                if " (" in domain_part:
                    domain = domain_part.split(" (")[0].strip()
                else:
                    domain = domain_part.strip()

            if domain and domain in domain_to_color:
                color = domain_to_color[domain]
            else:
                # No domain, use gray
                color = "#808080"

            # Use the same color for both datasets - no brightness adjustment
            color_map[(code_str, dataset_idx)] = color

        return color_map


    def get_domain_color_variant(self, base_color, domain_suffix, domain_index):
        """
        Create color variant based on domain using completely different colors.

        Args:
            base_color: Hex color code (e.g., "#FF0000")
            domain_suffix: Domain string (e.g., " - Harry West", " - D1") or empty string
            domain_index: Integer index for this domain (0, 1, 2, etc.)

        Returns:
            Hex color code - completely different color per domain
        """
        if not domain_suffix or " - " not in domain_suffix:
            return base_color  # No domain, use base color

        # Define a list of HIGHLY DISTINCT colors for domains
        # Uses Tableau 20 + additional distinct colors for up to 25 domains
        domain_colors = [
            "#E41A1C",  # 1. Bright red
            "#377EB8",  # 2. Strong blue
            "#4DAF4A",  # 3. Vivid green
            "#FF7F00",  # 4. Bright orange
            "#984EA3",  # 5. Purple
            "#FFFF33",  # 6. Bright yellow
            "#A65628",  # 7. Brown
            "#F781BF",  # 8. Pink
            "#00CED1",  # 9. Dark turquoise
            "#FF1493",  # 10. Deep pink
            "#32CD32",  # 11. Lime green
            "#FF4500",  # 12. Orange red
            "#1E90FF",  # 13. Dodger blue
            "#FFD700",  # 14. Gold
            "#8B4513",  # 15. Saddle brown
            "#00FA9A",  # 16. Medium spring green
            "#DC143C",  # 17. Crimson
            "#7B68EE",  # 18. Medium slate blue
            "#FF69B4",  # 19. Hot pink
            "#2E8B57",  # 20. Sea green
            "#FF8C00",  # 21. Dark orange
            "#4169E1",  # 22. Royal blue
            "#9ACD32",  # 23. Yellow green
            "#FF6347",  # 24. Tomato
            "#48D1CC",  # 25. Medium turquoise
        ]

        # Use modulo to cycle through colors if we have more than 15 domains
        return domain_colors[domain_index % len(domain_colors)]


    def generate_structure_color_map(self, plotted_data):
        """
        Generate a color map for structure codes with domain differentiation.
        Creates color variants for:
        - Different domains (indexed brightness variations)
        - Different datasets (additional subtle adjustment)

        Args:
            plotted_data: List of tuples containing (code_str, struct_type, data_list, plot_mode, dataset_idx, dataset_color)

        Returns:
            Dictionary mapping (full_code_with_domain, dataset_idx) to color
        """
        # First pass: Extract all unique domain suffixes for each base code
        # This allows us to create a consistent index for each domain
        base_code_domains = {}  # Maps base_code -> list of unique domain suffixes

        for item in plotted_data:
            code_str = item[0]
            # Split into base code and domain
            if " - " in code_str:
                base_code = code_str.split(" - ")[0]
                domain_suffix = " - " + code_str.split(" - ")[1]
            else:
                base_code = code_str
                domain_suffix = ""

            if base_code not in base_code_domains:
                base_code_domains[base_code] = []
            if domain_suffix not in base_code_domains[base_code]:
                base_code_domains[base_code].append(domain_suffix)

        # Sort domain lists for consistency
        for base_code in base_code_domains:
            base_code_domains[base_code].sort()

        # Second pass: Build color map
        color_map = {}

        # Fallback colors for unknown codes
        fallback_colors = [
            '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
            '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'
        ]
        fallback_index = 0

        # Extract unique (base_code, domain) combinations and assign global color index
        code_domain_pairs = set()
        for item in plotted_data:
            code_str = item[0]
            if " - " in code_str:
                base_code = code_str.split(" - ")[0]
                domain_suffix = " - " + code_str.split(" - ")[1]
            else:
                base_code = code_str
                domain_suffix = ""
            code_domain_pairs.add((base_code, domain_suffix))

        # Sort to ensure consistent ordering
        sorted_pairs = sorted(code_domain_pairs)

        # Assign a unique global color index to each (base_code, domain) combination
        for global_index, (base_code, domain_suffix) in enumerate(sorted_pairs):
            # Get base structure color
            if base_code in self.structure_colors:
                base_color = self.structure_colors[base_code]
            else:
                base_color = fallback_colors[fallback_index % len(fallback_colors)]
                fallback_index += 1
                QgsMessageLog.logMessage(f"Using fallback color for unknown code: {base_code}", 'Linear Geoscience', Qgis.Info)

            # Use the global index for color assignment - this ensures every code gets a unique color
            # Apply domain-based color variation with global index
            domain_color = self.get_domain_color_variant(base_color, domain_suffix, global_index)

            # Create dataset variants (for multi-dataset plotting)
            # Dataset 0: Slightly lighter than domain color
            # Dataset 1: Slightly darker than domain color
            dataset_0_color = self.adjust_color_brightness(domain_color, 1.08)  # 8% lighter
            dataset_1_color = self.adjust_color_brightness(domain_color, 0.92)  # 8% darker

            # Full code string (base + domain)
            full_code = base_code + domain_suffix if domain_suffix else base_code

            # Store in map
            color_map[(full_code, 0)] = dataset_0_color
            color_map[(full_code, 1)] = dataset_1_color

        return color_map


    def adjust_color_brightness(self, hex_color, factor):
        """
        Adjusts the brightness of a hex color by the given factor.

        Args:
            hex_color: Color in hex format (e.g., '#FF9933')
            factor: Factor to adjust brightness by (< 1 lightens, > 1 darkens)

        Returns:
            Adjusted color in hex format
        """
        # Convert hex to RGB
        hex_color = hex_color.lstrip('#')
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)

        # Adjust brightness
        r = min(255, max(0, int(r / factor)))
        g = min(255, max(0, int(g / factor)))
        b = min(255, max(0, int(b / factor)))

        # Convert back to hex
        return f'#{r:02x}{g:02x}{b:02x}'


    def set_active_dataset(self, index):
        """Set which dataset is currently active (simplified for combined tab)"""
        self.active_dataset = index
        QgsMessageLog.logMessage(f"Active dataset set to {index + 1}", 'Linear Geoscience', Qgis.Info)

    ########################################################################
    # Plot Tab Setup (Updated)
    ########################################################################


    def switch_config_dataset(self, index):
        """Switch which dataset is currently active (compatibility method)"""
        self.active_dataset = index
        QgsMessageLog.logMessage(f"Active dataset set to {index + 1}", 'Linear Geoscience', Qgis.Info)


    def simple_switch_dataset(self, index):
        """Simple handler for dataset selection in config tab"""
        self.active_dataset = index
        QgsMessageLog.logMessage(f"Switching to dataset {index + 1}", 'Linear Geoscience', Qgis.Info)

        # Update the stacked widget to show the selected dataset's config
        if hasattr(self, 'dataset_stacks'):
            self.dataset_stacks.setCurrentIndex(index)

        # In case the active dataset combo in the Datasets tab exists, sync it
        if hasattr(self, 'active_dataset_combo'):
            self.active_dataset_combo.blockSignals(True)
            self.active_dataset_combo.setCurrentIndex(index)
            self.active_dataset_combo.blockSignals(False)


    def on_dataset0_layer_changed(self, layer):
        """Direct handler for dataset 0 layer changes"""
        if not layer or not layer.isValid():
            QgsMessageLog.logMessage("Dataset 0: Invalid layer selected", 'Linear Geoscience', Qgis.Warning)
            return

        QgsMessageLog.logMessage(f"Dataset 0: Layer changed to '{layer.name()}'", 'Linear Geoscience', Qgis.Info)
        self.populate_field_combos_for_dataset(0, layer)


    def on_dataset1_layer_changed(self, layer):
        """Direct handler for dataset 1 layer changes"""
        if not layer or not layer.isValid():
            QgsMessageLog.logMessage("Dataset 1: Invalid layer selected", 'Linear Geoscience', Qgis.Warning)
            return

        QgsMessageLog.logMessage(f"Dataset 1: Layer changed to '{layer.name()}'", 'Linear Geoscience', Qgis.Info)
        self.populate_field_combos_for_dataset(1, layer)


    def config_change_dataset(self, index):
        """Change the active dataset in the config tab"""
        self.active_dataset = index

        # Show fields for the selected dataset, hide for the other
        for i in range(2):
            visible = (i == index)
            self.dataset_configs[i]["layer_combo"].setVisible(visible)
            self.dataset_configs[i]["dip_combo"].setVisible(visible)
            self.dataset_configs[i]["dipdir_combo"].setVisible(visible)
            self.dataset_configs[i]["subtype_combo"].setVisible(visible)

        # Update the labels based on dataset
        color = self.dataset_configs[index]["color"]
        name = self.dataset_configs[index]["name"]
        self.config_dataset_combo.setItemText(index, f"{name} (Active)")


    def create_dataset_panel(self, dataset_idx, parent_layout):
        """Create a fresh panel for dataset configuration"""
        panel_name = f"dataset{dataset_idx + 1}_panel"

        # Create the panel
        panel = QGroupBox(f"Dataset {dataset_idx + 1} Configuration")
        panel.setVisible(self.active_dataset == dataset_idx)

        # Create layout
        panel_layout = QVBoxLayout(panel)

        # Layer selection
        panel_layout.addWidget(QLabel("Layer:"))
        layer_combo = QgsMapLayerComboBox()
        layer_combo.setFilters(QgsMapLayerProxyModel.VectorLayer)

        # Connect layer change event
        layer_combo.layerChanged.connect(lambda layer: self.populate_field_combo_boxes(dataset_idx, layer))
        panel_layout.addWidget(layer_combo)
        self.dataset_configs[dataset_idx]["layer_combo"] = layer_combo

        # Field dropdowns using regular QComboBox
        field_labels = ["Dip Field:", "Dip Direction Field:", "Structure Code Field:"]
        field_keys = ["dip_combo", "dipdir_combo", "subtype_combo"]

        for label_text, key in zip(field_labels, field_keys):
            panel_layout.addWidget(QLabel(label_text))
            combo = QComboBox()
            combo.setMaxVisibleItems(15)  # Show more items in dropdown
            combo.setMinimumWidth(200)  # Make dropdown wider
            panel_layout.addWidget(combo)
            self.dataset_configs[dataset_idx][key] = combo

        # Add refresh button
        refresh_button = QPushButton("Refresh Fields")
        refresh_button.clicked.connect(lambda: self.populate_field_combo_boxes(dataset_idx))
        panel_layout.addWidget(refresh_button)

        # Add to parent layout
        parent_layout.addWidget(panel)

        # Store reference to panel
        if dataset_idx == 0:
            self.dataset1_panel = panel
        else:
            self.dataset2_panel = panel

        # For dataset 0, update backward compatibility references
        if dataset_idx == 0:
            self.auto_layer_combo = layer_combo
            self.dip_column_combo = self.dataset_configs[0]["dip_combo"]
            self.dipdir_column_combo = self.dataset_configs[0]["dipdir_combo"]
            self.subtype_column_combo = self.dataset_configs[0]["subtype_combo"]


    def direct_update_fields(self, dataset_idx, layer):
        """Directly update field combo boxes for the specified dataset"""
        if not layer or not layer.isValid():
            QgsMessageLog.logMessage(f"Invalid layer for dataset {dataset_idx + 1}", 'Linear Geoscience', Qgis.Warning)
            return

        QgsMessageLog.logMessage(f"Updating fields for dataset {dataset_idx + 1} with layer: {layer.name()}", 'Linear Geoscience', Qgis.Info)

        # Get combo box references
        dip_combo = self.dataset_configs[dataset_idx]["dip_combo"]
        dipdir_combo = self.dataset_configs[dataset_idx]["dipdir_combo"]
        subtype_combo = self.dataset_configs[dataset_idx]["subtype_combo"]

        # Check if combo boxes exist
        if not all([dip_combo, dipdir_combo, subtype_combo]):
            QgsMessageLog.logMessage(f"Dataset {dataset_idx + 1}: One or more combo boxes are missing", 'Linear Geoscience', Qgis.Info)
            return

        # Get field names from layer
        field_names = [f.name() for f in layer.fields()]
        QgsMessageLog.logMessage(f"Dataset {dataset_idx + 1}: Fields found: {field_names}", 'Linear Geoscience', Qgis.Info)

        # Clear and repopulate the combo boxes
        try:
            # First try the QGIS API way
            dip_combo.setLayer(layer)
            dipdir_combo.setLayer(layer)
            subtype_combo.setLayer(layer)

            # Auto-select common field names
            # Try to auto-select Dip field
            for field_name in ["Dip", "DIP", "dip", "Angle", "angle"]:
                if field_name in field_names:
                    dip_combo.setCurrentText(field_name)
                    QgsMessageLog.logMessage(f"Dataset {dataset_idx + 1}: Auto-selected '{field_name}' for Dip field", 'Linear Geoscience', Qgis.Info)
                    break

            # Try to auto-select DipDirection field
            for field_name in ["DipDirection", "DIPDIRECTION", "dipdir", "DipDir", "Azimuth", "azimuth"]:
                if field_name in field_names:
                    dipdir_combo.setCurrentText(field_name)
                    QgsMessageLog.logMessage(f"Dataset {dataset_idx + 1}: Auto-selected '{field_name}' for DipDirection field", 'Linear Geoscience', Qgis.Info)
                    break

            # Try to auto-select Subtype field
            for field_name in ["Subtype1", "SUBTYPE", "Subtype", "subtype", "StructureCode", "Code"]:
                if field_name in field_names:
                    subtype_combo.setCurrentText(field_name)
                    QgsMessageLog.logMessage(f"Dataset {dataset_idx + 1}: Auto-selected '{field_name}' for Subtype field", 'Linear Geoscience', Qgis.Info)
                    break
        except Exception as e:
            QgsMessageLog.logMessage(f"Dataset {dataset_idx + 1}: Error setting fields: {str(e)}", 'Linear Geoscience', Qgis.Warning)
            # Fallback to direct population if QGIS API fails
            self.manually_populate_fields(dataset_idx, field_names)


    def update_config_for_active_dataset(self):
        """Update configuration tab to show active dataset's settings"""
        if not self.config_widget:
            return

        # Update active dataset label
        active_label = self.config_widget.findChild(QLabel, "activeDatasetLabel")
        if active_label:
            color = self.dataset_configs[self.active_dataset]["color"]
            name = self.dataset_configs[self.active_dataset]["name"]
            active_label.setText(f"Configuring: {name}")
            active_label.setStyleSheet(f"font-weight: bold; color: {color};")

        # Show/hide the appropriate widgets using our container widgets
        for i in range(len(self.layer_containers)):
            self.layer_containers[i].setVisible(i == self.active_dataset)

        for i in range(len(self.dip_containers)):
            self.dip_containers[i].setVisible(i == self.active_dataset)

        for i in range(len(self.dipdir_containers)):
            self.dipdir_containers[i].setVisible(i == self.active_dataset)

        for i in range(len(self.subtype_containers)):
            self.subtype_containers[i].setVisible(i == self.active_dataset)


    def update_field_combos(self, layer, dataset_index=None):
        """Update field combos when layer changes and auto-select common field names"""
        # If dataset_index is None, use active dataset
        if dataset_index is None:
            dataset_index = self.active_dataset

        # Check if we have valid references
        if (not self.dataset_configs[dataset_index]["dip_combo"] or
                not self.dataset_configs[dataset_index]["dipdir_combo"] or
                not self.dataset_configs[dataset_index]["subtype_combo"]):
            QgsMessageLog.logMessage(f"Field combos not initialized for dataset {dataset_index + 1}", 'Linear Geoscience', Qgis.Info)
            return

        # First set the layer to populate the combo boxes
        self.dataset_configs[dataset_index]["dip_combo"].setLayer(layer)
        self.dataset_configs[dataset_index]["dipdir_combo"].setLayer(layer)
        self.dataset_configs[dataset_index]["subtype_combo"].setLayer(layer)

        # Auto-detect and select common field names
        if layer and layer.isValid():
            fields = [f.name() for f in layer.fields()]
            QgsMessageLog.logMessage(f"Dataset {dataset_index + 1} field auto-detection found {len(fields)} fields -> {fields}", 'Linear Geoscience', Qgis.Info)

            # Auto-select Dip field
            for field_name in ["Dip", "DIP", "dip", "Angle", "angle"]:
                if field_name in fields:
                    self.dataset_configs[dataset_index]["dip_combo"].setCurrentText(field_name)
                    QgsMessageLog.logMessage(f"Auto-selected {field_name} for Dip field", 'Linear Geoscience', Qgis.Info)
                    break

            # Auto-select DipDirection field
            for field_name in ["DipDirection", "DIPDIRECTION", "dipdir", "DipDir", "Azimuth", "azimuth"]:
                if field_name in fields:
                    self.dataset_configs[dataset_index]["dipdir_combo"].setCurrentText(field_name)
                    QgsMessageLog.logMessage(f"Auto-selected {field_name} for DipDirection field", 'Linear Geoscience', Qgis.Info)
                    break

            # Auto-select Subtype field
            for field_name in ["Subtype1", "SUBTYPE", "Subtype", "subtype", "StructureCode", "Code"]:
                if field_name in fields:
                    self.dataset_configs[dataset_index]["subtype_combo"].setCurrentText(field_name)
                    QgsMessageLog.logMessage(f"Auto-selected {field_name} for Subtype field", 'Linear Geoscience', Qgis.Info)
                    break

        # Update backward compatibility references if this is dataset 0
        if dataset_index == 0:
            self.dip_column_combo = self.dataset_configs[0]["dip_combo"]
            self.dipdir_column_combo = self.dataset_configs[0]["dipdir_combo"]
            self.subtype_column_combo = self.dataset_configs[0]["subtype_combo"]


    def handle_checkbox_change(self, state, row, other_checkbox, is_planar):
        """Ensure only one of Planar or Linear is selected"""
        if state == Qt.Checked:
            other_checkbox.blockSignals(True)
            other_checkbox.setChecked(False)
            other_checkbox.blockSignals(False)


    def select_all_coding_codes(self):
        """Select all rows in the coding table"""
        self.coding_table.selectAll()


    def deselect_all_coding_codes(self):
        """Deselect all rows in the coding table"""
        self.coding_table.clearSelection()


    def set_selected_classification(self, classification_type):
        """Set classification for all selected table rows"""
        selected_rows = set(index.row() for index in self.coding_table.selectedIndexes())

        if not selected_rows:
            return  # No rows selected

        for row in selected_rows:
            if row in self.coding_entries:
                entry = self.coding_entries[row]

                if classification_type == "Planar":
                    entry["planar_chk"].blockSignals(True)
                    entry["linear_chk"].blockSignals(True)

                    entry["planar_chk"].setChecked(True)
                    entry["linear_chk"].setChecked(False)

                    entry["planar_chk"].blockSignals(False)
                    entry["linear_chk"].blockSignals(False)

                elif classification_type == "Linear":
                    entry["planar_chk"].blockSignals(True)
                    entry["linear_chk"].blockSignals(True)

                    entry["planar_chk"].setChecked(False)
                    entry["linear_chk"].setChecked(True)

                    entry["planar_chk"].blockSignals(False)
                    entry["linear_chk"].blockSignals(False)


    def apply_coding_changes(self):
        """Apply all code classifications from the table"""
        count = 0

        # Track all modified codes for later selection
        modified_codes = []

        # Process each row in the coding table
        for row, entry in self.coding_entries.items():
            code = entry["code"]
            dataset_idx = entry["dataset_idx"]
            is_planar = entry["planar_chk"].isChecked()
            is_linear = entry["linear_chk"].isChecked()

            # Determine type
            code_type = None
            if is_planar:
                code_type = "plane"
                if code not in planar_codes:
                    planar_codes.append(code)
            elif is_linear:
                code_type = "line"
                if code not in linear_codes:
                    linear_codes.append(code)

            # Save to normalized_classification
            if code_type:
                normalized_classification[code.upper()] = code_type
                count += 1
                modified_codes.append((code, dataset_idx))

        # Show confirmation
        QMessageBox.information(
            self.iface.mainWindow(),
            "Classification Complete",
            f"Applied {count} code classifications.\nChanges will be used for all future processing."
        )

        # Do a complete refresh of the data
        self.manual_refresh()

        # After refresh, try to select the newly classified codes in the category trees
        self.select_newly_classified_codes(modified_codes)

        # Switch to the Categories tab to help user see the newly classified codes
        if count > 0:
            self.tab_widget.setCurrentIndex(1)  # Index 1 should be Categories tab


    def select_newly_classified_codes(self, coded_items):
        """Select newly classified codes in the category tree"""
        if not coded_items:
            return

        try:
            # For Selection tab
            if self.category_tree_selection:
                for i in range(self.category_tree_selection.topLevelItemCount()):
                    item = self.category_tree_selection.topLevelItem(i)
                    data = item.data(0, Qt.UserRole)

                    if isinstance(data, dict) and data.get("is_group"):
                        # Grouped codes live one level down
                        for j in range(item.childCount()):
                            child = item.child(j)
                            cdata = child.data(0, Qt.UserRole)
                            if isinstance(cdata, tuple):
                                for code, ds_idx in coded_items:
                                    if cdata[0] == code and cdata[1] == ds_idx:
                                        child.setCheckState(0, Qt.Checked)
                                        break
                        continue

                    if isinstance(data, tuple):
                        code_str, dataset_idx = data
                    else:
                        # For backward compatibility
                        code_str = data
                        dataset_idx = 0

                    # Check if this item matches any of our newly classified codes
                    for code, ds_idx in coded_items:
                        if code_str == code and dataset_idx == ds_idx:
                            item.setCheckState(0, Qt.Checked)
                            break

            # For Domains tab
            if self.category_tree_domains:
                for i in range(self.category_tree_domains.topLevelItemCount()):
                    item = self.category_tree_domains.topLevelItem(i)
                    data = item.data(0, Qt.UserRole)

                    if isinstance(data, dict) and data.get("is_group"):
                        for j in range(item.childCount()):
                            child = item.child(j)
                            cdata = child.data(0, Qt.UserRole)
                            if isinstance(cdata, tuple) and len(cdata) >= 5:
                                for code, ds_idx in coded_items:
                                    if cdata[2] == code and cdata[1] == ds_idx:
                                        child.setCheckState(0, Qt.Checked)
                                        break
                        continue

                    if isinstance(data, tuple):
                        if len(data) >= 5:
                            # New format: (st, dataset_idx, code, domain, dataset_name)
                            code_str, dataset_idx = data[0], data[1]
                        else:
                            # Old format: (code_str, dataset_idx)
                            code_str, dataset_idx = data
                    else:
                        # For backward compatibility
                        code_str = data
                        dataset_idx = 0

                    # Match code with domain suffix (e.g., "CODE - Domain")
                    if " - " in code_str:
                        base_code = code_str.split(" - ")[0]
                        # Check if this item matches any of our newly classified codes
                        for code, ds_idx in coded_items:
                            if base_code == code and dataset_idx == ds_idx:
                                item.setCheckState(0, Qt.Checked)
                                break
        except Exception as e:
            QgsMessageLog.logMessage(f"Error selecting newly classified codes: {e}", 'Linear Geoscience', Qgis.Warning)


    def import_coding_csv(self):
        """Import code classifications from CSV file"""
        filename = self.import_file_widget.filePath()
        if not filename:
            # If no path is set, prompt for one
            filename, _ = QFileDialog.getOpenFileName(
                self.iface.mainWindow(),
                "Import Codes from CSV",
                os.path.expanduser("~"),
                "CSV Files (*.csv)"
            )

        if not filename:
            return  # User canceled

        try:
            with open(filename, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)

                # Check required columns
                if "Code" not in reader.fieldnames or "Type" not in reader.fieldnames:
                    QMessageBox.critical(
                        self.iface.mainWindow(),
                        "Import Error",
                        "CSV must have columns 'Code' and 'Type'."
                    )
                    return

                count_updated = 0
                for row in reader:
                    code = row["Code"].strip()
                    t_letter = row["Type"].strip().upper()
                    if not code:
                        continue

                    if t_letter == "P":
                        normalized_classification[code.upper()] = "plane"
                        if code not in planar_codes:
                            planar_codes.append(code)
                        count_updated += 1
                    elif t_letter == "L":
                        normalized_classification[code.upper()] = "line"
                        if code not in linear_codes:
                            linear_codes.append(code)
                        count_updated += 1

            # Refresh the coding table to show updated classifications
            self.populate_coding_table()

            QMessageBox.information(
                self.iface.mainWindow(),
                "Import Successful",
                f"Imported {count_updated} codes from:\n{filename}"
            )

            # Update categories to reflect new classifications
            self.update_data_selection()
            self.update_data_domains()
            self.rebuild_category_tree_selection()
            self.rebuild_category_tree_domains()

        except Exception as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Import Error",
                str(e)
            )

    ########################################################################
    # Export Tab
    ########################################################################


    def toggle_domain_filter(self, state):
        """Show/hide domain filter based on checkbox state"""
        self.domain_filter_combo.setVisible(state == Qt.Checked)
        if state == Qt.Checked:
            self.refresh_domain_list()


    def select_all_export(self):
        """Select all structures for export"""
        if not hasattr(self, 'export_structure_tree'):
            return

        for i in range(self.export_structure_tree.topLevelItemCount()):
            item = self.export_structure_tree.topLevelItem(i)
            item.setCheckState(0, Qt.Checked)


    def deselect_all_export(self):
        """Deselect all structures for export"""
        if not hasattr(self, 'export_structure_tree'):
            return

        for i in range(self.export_structure_tree.topLevelItemCount()):
            item = self.export_structure_tree.topLevelItem(i)
            item.setCheckState(0, Qt.Unchecked)


    def get_layer(self, dataset_index=None):
        """Get the selected layer for the specified dataset"""
        if dataset_index is None:
            dataset_index = self.active_dataset

        if dataset_index < 0 or dataset_index >= len(self.dataset_configs):
            QgsMessageLog.logMessage(f"Invalid dataset index: {dataset_index}", 'Linear Geoscience', Qgis.Warning)
            return None

        if self.dataset_configs[dataset_index]["layer_combo"] is None:
            QgsMessageLog.logMessage(f"Layer combo not initialized for dataset {dataset_index + 1}", 'Linear Geoscience', Qgis.Info)
            return None

        # Get the display text of the selected layer
        combo_box = self.dataset_configs[dataset_index]["layer_combo"]
        display_text = combo_box.currentText()

        # If the combo box is empty or no selection, return None
        if not display_text:
            QgsMessageLog.logMessage(f"No layer selected for Dataset {dataset_index + 1}", 'Linear Geoscience', Qgis.Info)
            return None

        # If we have a layer maps attribute and the selected text is in the map
        if hasattr(self, 'layer_maps') and display_text in self.layer_maps[dataset_index]:
            return self.layer_maps[dataset_index][display_text]

        # Fallback: try to find a layer with this name in the project
        # First check for exact name (might contain source in brackets)
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == display_text:
                return layer

        # Second check just for the layer name part (before any brackets)
        if '[' in display_text:
            layer_name = display_text.split('[')[0].strip()
            for layer in QgsProject.instance().mapLayers().values():
                if layer.name() == layer_name:
                    return layer

        QgsMessageLog.logMessage(f"Could not find layer for Dataset {dataset_index + 1} with text: {display_text}", 'Linear Geoscience', Qgis.Info)
        return None

    ########################################################################
    # Data Refresh / Plot
    ########################################################################


    def manual_refresh(self):
        """Refresh categories from the QGIS-selected features."""
        self._do_refresh(use_all_features=False)

    def manual_refresh_all(self):
        """Refresh categories from ALL features in the enabled dataset layers,
        so the user doesn't have to Ctrl+A-select each layer first."""
        self._do_refresh(use_all_features=True)

    def _do_refresh(self, use_all_features=False):
        mode = "Refresh with All" if use_all_features else "Refresh Selection"
        QgsMessageLog.logMessage(f"=== {mode} Clicked ===", 'Linear Geoscience', Qgis.Info)

        # Process each enabled dataset
        for i in range(2):
            if self.dataset_configs[i]["enabled"]:
                QgsMessageLog.logMessage(f"Refreshing Dataset {i + 1}: {self.dataset_configs[i]['name']}", 'Linear Geoscience', Qgis.Info)
                self.update_data_selection(i, use_all_features=use_all_features)
                self.update_data_domains(i)

        # Rebuild category trees
        self.rebuild_category_tree_selection()
        self.rebuild_category_tree_domains()

        # Also refresh live view data if enabled
        if self.live_view_enabled:
            for i in range(2):
                if self.dataset_configs[i]["enabled"]:
                    self.update_data_live_view(i, self.map_canvas.extent())

            # Rebuild appropriate category tree based on domain mode
            if self.live_view_by_domain_checkbox and self.live_view_by_domain_checkbox.isChecked():
                QgsMessageLog.logMessage("Rebuilding live view tree with domain categories (domain mode active)", 'Linear Geoscience', Qgis.Info)
                self.rebuild_category_tree_live_view_domains()
            else:
                QgsMessageLog.logMessage("Rebuilding live view tree with regular categories", 'Linear Geoscience', Qgis.Info)
                self.rebuild_category_tree_live_view()

        # Check if any data was found
        any_data_found = False
        for i in range(2):
            if (self.dataset_configs[i]["enabled"] and
                    (bool(self.subtype_dict_selection[i]) or bool(self.subtype_dict_domains[i]))):
                any_data_found = True
                break

        if not any_data_found and self.plot_label:
            self.plot_label.setText("No valid structural data found. Check fields or selection.")
            QgsMessageLog.logMessage("manual_refresh: No valid data found.", 'Linear Geoscience', Qgis.Info)
        else:
            if self.plot_label:
                self.plot_label.setText("Categories refreshed. Now hit 'Plot' to update the stereonet.")
            QgsMessageLog.logMessage("manual_refresh: Categories found and displayed.", 'Linear Geoscience', Qgis.Info)

        # Also refresh the coding table to show new classifications
        if hasattr(self, 'populate_coding_table') and self.coding_table:
            self.populate_coding_table()

        # Update the plot if any categories are already selected
        self.update_plot()


