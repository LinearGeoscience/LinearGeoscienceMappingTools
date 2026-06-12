# -*- coding: utf-8 -*-
"""
Geometry Issues Preview Dialog
Shows list of geometry issues before fixing
"""
from qgis.gui import QgsHighlight
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class GeometryIssuesDialog(QDialog):
    """
    Dialog for displaying geometry issues before fixing.
    Allows highlighting and zooming to problematic features.
    """

    def __init__(self, layer, issues, iface, parent=None):
        """
        Initialize dialog.

        Args:
            layer: QgsVectorLayer - the layer being checked
            issues: List[GeometryIssue] - detected issues
            iface: QgisInterface - QGIS interface
            parent: parent widget
        """
        super(GeometryIssuesDialog, self).__init__(parent)
        self.layer = layer
        self.issues = issues
        self.iface = iface
        self.highlights = []  # List of QgsHighlight objects
        self.setup_ui()

    def setup_ui(self):
        """Build the dialog UI"""
        self.setWindowTitle("Geometry Issues Found")
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)

        # Make dialog non-modal to allow map interaction
        self.setModal(False)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout()

        # Title and summary
        title = QLabel(f"<h3>Geometry Issues - {self.layer.name()}</h3>")
        layout.addWidget(title)

        summary_label = QLabel(
            f"Found <b>{len(self.issues)}</b> geometry issues in <b>{self.layer.featureCount()}</b> features."
        )
        summary_label.setStyleSheet("padding: 8px; background-color: #FFF3E0; border-radius: 4px; color: #E65100;")
        layout.addWidget(summary_label)

        # Info box
        info_box = QLabel(
            "Click on an issue to highlight it on the map.\n"
            "You can zoom and pan to inspect the problematic geometries.\n"
            "Click 'Fix All' to automatically fix all issues."
        )
        info_box.setWordWrap(True)
        info_box.setStyleSheet("padding: 6px; background-color: #E3F2FD; border-radius: 4px;")
        layout.addWidget(info_box)

        # Issues table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Feature ID", "Issue Type", "Description"])
        self.table.setRowCount(len(self.issues))
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        # Populate table
        for row, issue in enumerate(self.issues):
            # Feature ID
            fid_item = QTableWidgetItem(str(issue.fid))
            fid_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, fid_item)

            # Issue Type
            type_item = QTableWidgetItem(self.format_issue_type(issue.issue_type))
            type_item.setTextAlignment(Qt.AlignCenter)
            # Color code by severity
            if issue.issue_type == 'invalid':
                type_item.setBackground(QColor(255, 200, 200))  # Light red
            elif issue.issue_type == 'zero_area':
                type_item.setBackground(QColor(255, 180, 180))  # Light red (severe)
            elif issue.issue_type == 'duplicate_vertices_collapse':
                type_item.setBackground(QColor(255, 210, 180))  # Orange-red (warning)
            elif issue.issue_type == 'multipart':
                type_item.setBackground(QColor(255, 230, 200))  # Light orange
            elif issue.issue_type == 'duplicate_vertices':
                type_item.setBackground(QColor(255, 255, 200))  # Light yellow
            else:
                type_item.setBackground(QColor(200, 200, 200))  # Gray
            self.table.setItem(row, 1, type_item)

            # Description
            desc_item = QTableWidgetItem(issue.description)
            self.table.setItem(row, 2, desc_item)

        # Adjust column widths
        self.table.setColumnWidth(0, 100)
        self.table.setColumnWidth(1, 150)
        self.table.horizontalHeader().setStretchLastSection(True)

        # Connect selection signal
        self.table.itemSelectionChanged.connect(self.on_issue_selected)

        layout.addWidget(self.table)

        # Statistics box
        stats_layout = QHBoxLayout()
        stats_label = QLabel(self.get_statistics_text())
        stats_label.setStyleSheet("padding: 6px; background-color: #F5F5F5; border-radius: 4px;")
        stats_layout.addWidget(stats_label)
        layout.addLayout(stats_layout)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.zoom_button = QPushButton("Zoom to Selected")
        self.zoom_button.setEnabled(False)
        self.zoom_button.setStyleSheet("padding: 8px 16px;")
        self.zoom_button.clicked.connect(self.on_zoom_to_selected)
        button_layout.addWidget(self.zoom_button)

        self.fix_button = QPushButton("Fix All Issues")
        self.fix_button.setDefault(True)
        self.fix_button.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "padding: 8px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #45a049; }"
        )
        self.fix_button.clicked.connect(self.accept)
        button_layout.addWidget(self.fix_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet("padding: 8px 16px;")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def format_issue_type(self, issue_type):
        """Format issue type for display"""
        type_map = {
            'invalid': 'Invalid Geometry',
            'multipart': 'Multipart',
            'empty': 'Empty/Null',
            'duplicate_vertices': 'Duplicate Vertices',
            'duplicate_vertices_collapse': 'Duplicate Vertices (Collapse)',
            'zero_area': 'Zero Area'
        }
        return type_map.get(issue_type, issue_type)

    def get_statistics_text(self):
        """Generate statistics summary text"""
        stats = {}
        for issue in self.issues:
            issue_type = issue.issue_type
            stats[issue_type] = stats.get(issue_type, 0) + 1

        parts = []
        if 'invalid' in stats:
            parts.append(f"<b>{stats['invalid']}</b> invalid")
        if 'zero_area' in stats:
            parts.append(f"<b>{stats['zero_area']}</b> zero area")
        if 'duplicate_vertices_collapse' in stats:
            parts.append(f"<b>{stats['duplicate_vertices_collapse']}</b> collapse on duplicate removal")
        if 'multipart' in stats:
            parts.append(f"<b>{stats['multipart']}</b> multipart")
        if 'duplicate_vertices' in stats:
            parts.append(f"<b>{stats['duplicate_vertices']}</b> with duplicates")
        if 'empty' in stats:
            parts.append(f"<b>{stats['empty']}</b> empty")

        return "Issues: " + ", ".join(parts)

    def on_issue_selected(self):
        """Handle issue selection in table"""
        # Clear previous highlights
        self.clear_highlights()

        # Get selected row
        selected_rows = self.table.selectedIndexes()
        if not selected_rows:
            self.zoom_button.setEnabled(False)
            return

        row = selected_rows[0].row()
        issue = self.issues[row]

        # Enable zoom button
        self.zoom_button.setEnabled(True)

        # Highlight the feature
        if issue.geometry:
            self.highlight_geometry(issue.geometry)

    def highlight_geometry(self, geometry):
        """Highlight a geometry on the map"""
        if not geometry:
            return

        # Create highlight
        highlight = QgsHighlight(self.iface.mapCanvas(), geometry, self.layer)
        highlight.setColor(QColor(255, 0, 0, 100))  # Red with transparency
        highlight.setFillColor(QColor(255, 0, 0, 50))
        highlight.setWidth(3)
        highlight.show()

        self.highlights.append(highlight)

    def on_zoom_to_selected(self):
        """Zoom to the selected issue"""
        selected_rows = self.table.selectedIndexes()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        issue = self.issues[row]

        if issue.geometry:
            # Zoom to geometry with buffer
            extent = issue.geometry.boundingBox()
            extent.scale(1.5)  # 50% buffer
            self.iface.mapCanvas().setExtent(extent)
            self.iface.mapCanvas().refresh()

    def clear_highlights(self):
        """Clear all highlights from the map"""
        for highlight in self.highlights:
            try:
                highlight.hide()
            except RuntimeError:
                pass
        self.highlights = []

    def closeEvent(self, event):
        """Handle dialog close"""
        self.clear_highlights()
        event.accept()

    def reject(self):
        """Handle cancel"""
        self.clear_highlights()
        super(GeometryIssuesDialog, self).reject()

    def accept(self):
        """Handle fix all"""
        self.clear_highlights()
        super(GeometryIssuesDialog, self).accept()
