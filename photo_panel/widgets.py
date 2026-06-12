"""
Photo Panel Widgets - PhotoThumbnail and FilterPanel.

Bug fixes:
  #1:  Qt dynamic property for selection styling instead of brittle .replace()
  #2:  clicked = pyqtSignal(str) on PhotoThumbnail, no lambda overrides
  #3:  select_on_map() implemented with layer.selectByIds() + zoomToSelected()
  #4:  menu.exec(pos) instead of deprecated menu.exec_(pos)
  #5:  Persistent QTimer with stop()/start() for search debounce
"""

import os
import datetime
from typing import Dict, List, Any

from qgis.PyQt.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QToolButton,
    QComboBox, QSlider, QLineEdit, QMenu, QAction, QApplication,
    QMessageBox, QWidget, QSizePolicy
)
from qgis.PyQt.QtCore import Qt, pyqtSignal, QTimer
from qgis.PyQt.QtGui import (
    QPixmap, QIcon, QCursor, QDesktopServices
)
from qgis.core import (
    QgsProject, QgsCoordinateTransform, QgsMessageLog, Qgis
)
from qgis.PyQt.QtCore import QUrl

from .constants import STYLE, get_scale_manager
from .models import PhotoInfo


class PhotoThumbnail(QFrame):
    """
    Widget for displaying a single photo thumbnail.

    Bug fix #1: Uses Qt dynamic property 'selected' for selection styling.
    Bug fix #2: Emits clicked(str) signal instead of lambda override.
    Bug fix #3: select_on_map() implemented.
    """

    # Bug fix #2: proper signal
    clicked = pyqtSignal(str)

    def __init__(self, photo: PhotoInfo, iface, parent=None):
        super().__init__(parent)
        self.photo = photo
        self.iface = iface

        # Bug fix #1: dynamic property for selection
        self.setProperty("selected", False)

        self._setup_ui()
        self._setup_connections()

    def _setup_ui(self):
        """Set up the UI components."""
        scale = get_scale_manager()

        self.setFrameShape(QFrame.NoFrame)
        self.setLineWidth(0)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # Bug fix #1: stylesheet uses dynamic property selector
        self.setStyleSheet(f"""
            PhotoThumbnail {{
                background-color: white;
                border-radius: {STYLE['RADIUS_LG']};
                border: 1px solid {STYLE['BORDER']};
                margin: {STYLE['MARGIN_SM']}px;
            }}
            PhotoThumbnail:hover {{
                border: 1px solid {STYLE['PRIMARY']};
            }}
            PhotoThumbnail[selected="true"] {{
                border: 2px solid {STYLE['PRIMARY']};
            }}
        """)

        self.main_layout = QVBoxLayout(self)
        margins = scale.margins(10, 10, 10, 10)
        self.main_layout.setContentsMargins(*margins)
        self.main_layout.setSpacing(scale.spacing(8))

        # Feature indicator at top
        self.feature_indicator = QFrame(self)
        self.feature_indicator.setFrameShape(QFrame.StyledPanel)
        self.feature_indicator.setStyleSheet(f"""
            background-color: {self.photo.feature_color.name()};
            border-top-left-radius: {STYLE['RADIUS_LG']};
            border-top-right-radius: {STYLE['RADIUS_LG']};
            border: none;
        """)
        self.feature_indicator.setFixedHeight(scale.dimension(5))
        self.feature_indicator.setToolTip(f"Photo Point ID: {self.photo.feature_id}")

        indicator_layout = QHBoxLayout()
        indicator_layout.setContentsMargins(0, 0, 0, 0)
        indicator_layout.addWidget(self.feature_indicator)
        self.main_layout.addLayout(indicator_layout)

        # Photo label
        self.photo_label = QLabel()
        self.photo_label.setAlignment(Qt.AlignCenter)
        thumb_width = scale.dimension(180)
        thumb_height = scale.dimension(140)
        self.photo_label.setMinimumSize(thumb_width, thumb_height)
        self.photo_label.setMaximumSize(thumb_width, thumb_height)
        self.photo_label.setStyleSheet(f"""
            background-color: {STYLE['SECONDARY_LIGHT']};
            border-radius: {STYLE['RADIUS_MD']};
            border: 1px solid {STYLE['BORDER']};
        """)
        self.photo_label.setText("Loading...")

        # Date string
        try:
            date_obj = datetime.datetime.fromtimestamp(self.photo.file_date)
            self.date_str = date_obj.strftime("%Y-%m-%d")
            self.short_date = date_obj.strftime("%d/%m/%y")
        except Exception:
            self.date_str = ""
            self.short_date = ""

        self.main_layout.addWidget(self.photo_label)

        # Comment section
        if self.photo.comment and self.photo.comment.strip() and self.photo.comment != "NULL":
            comment_label = QLabel(self.photo.comment)
            comment_label.setWordWrap(True)
            comment_label.setAlignment(Qt.AlignLeft)
            comment_label.setStyleSheet(f"""
                color: {STYLE['TEXT_SECONDARY']};
                font-size: {STYLE['FONT_SIZE_XS']};
                background-color: {STYLE['PRIMARY_LIGHT']};
                border-radius: {STYLE['RADIUS_SM']};
                padding: 3px;
                margin-top: 2px;
                max-height: {scale.dimension(60)}px;
            """)
            comment_label.setMaximumWidth(scale.dimension(180))
            self.main_layout.addWidget(comment_label)

        # Footer with metadata and buttons
        footer_widget = QWidget()
        footer_layout = QHBoxLayout(footer_widget)
        footer_layout.setContentsMargins(2, 2, 2, 2)
        footer_layout.setSpacing(4)

        meta_text = ""
        if self.short_date:
            meta_text = self.short_date
        if self.photo.geologist:
            if meta_text:
                meta_text += " · "
            meta_text += self.photo.geologist

        if meta_text:
            meta_label = QLabel(meta_text)
            meta_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            meta_label.setStyleSheet(f"""
                font-size: {STYLE['FONT_SIZE_XS']};
                color: {STYLE['TEXT_SECONDARY']};
                background: transparent;
                padding: 0;
            """)
            footer_layout.addWidget(meta_label, 1)

        button_style = f"""
            QToolButton {{
                border: none;
                border-radius: {STYLE['RADIUS_SM']};
                background-color: transparent;
                padding: 4px;
            }}
            QToolButton:hover {{
                background-color: {STYLE['PRIMARY_LIGHT']};
            }}
            QToolButton:pressed {{
                background-color: {STYLE['PRIMARY_LIGHT']};
            }}
        """

        self.zoom_btn = QToolButton()
        self.zoom_btn.setIcon(QIcon(":/images/themes/default/mActionZoomToSelected.svg"))
        self.zoom_btn.setIconSize(scale.icon_size(14, 14))
        self.zoom_btn.setToolTip("Zoom to photo location")
        self.zoom_btn.setStyleSheet(button_style)

        self.open_btn = QToolButton()
        self.open_btn.setIcon(QIcon(":/images/themes/default/mActionOpen.svg"))
        self.open_btn.setIconSize(scale.icon_size(14, 14))
        self.open_btn.setToolTip("Open photo")
        self.open_btn.setStyleSheet(button_style)

        footer_layout.addWidget(self.zoom_btn)
        footer_layout.addWidget(self.open_btn)

        self.main_layout.addWidget(footer_widget)

        # Tooltip
        tooltip_text = os.path.basename(self.photo.path)
        if self.photo.comment and self.photo.comment.strip() and self.photo.comment != "NULL":
            tooltip_text += f"\n{self.photo.comment}"
        self.setToolTip(tooltip_text)

    def _setup_connections(self):
        """Set up signal-slot connections."""
        self.zoom_btn.clicked.connect(self.zoom_to_location)
        self.open_btn.clicked.connect(self.open_photo)

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        """Set the thumbnail image."""
        if pixmap and not pixmap.isNull():
            self.photo_label.setPixmap(pixmap)
        else:
            self.photo_label.setText("Image not found")

    def set_selected(self, selected: bool) -> None:
        """
        Bug fix #1: set selection via Qt dynamic property.
        Triggers stylesheet re-evaluation without string replacement.
        """
        self.setProperty("selected", selected)
        # Force style recalculation
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mousePressEvent(self, event):
        """Handle mouse press events. Bug fix #2: emit signal."""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.photo.path)
        elif event.button() == Qt.RightButton:
            self.show_context_menu(event.globalPos())

    def show_context_menu(self, pos) -> None:
        """Show context menu with actions. Bug fix #4: menu.exec()."""
        menu = QMenu(self)

        open_action = QAction(QIcon(":/images/themes/default/mActionOpen.svg"), "Open Photo", self)
        open_action.triggered.connect(self.open_photo)

        zoom_action = QAction(QIcon(":/images/themes/default/mActionZoomToSelected.svg"), "Zoom to Location", self)
        zoom_action.triggered.connect(self.zoom_to_location)

        select_action = QAction(QIcon(":/images/themes/default/mActionSelect.svg"), "Select on Map", self)
        select_action.triggered.connect(self.select_on_map)

        copy_path_action = QAction(QIcon(":/images/themes/default/mActionEditCopy.svg"), "Copy File Path", self)
        copy_path_action.triggered.connect(self.copy_path_to_clipboard)

        menu.addAction(open_action)
        menu.addAction(zoom_action)
        menu.addAction(select_action)
        menu.addSeparator()
        menu.addAction(copy_path_action)

        # Bug fix #4: use exec() not exec_()
        menu.exec(pos)

    def open_photo(self) -> None:
        """Open the photo in the system's default viewer."""
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.photo.path))
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open photo: {str(e)}")

    def zoom_to_location(self) -> None:
        """Zoom the map to the photo's location (CRS-aware, scale-based)."""
        try:
            if not self.photo.point:
                return
            canvas = self.iface.mapCanvas()
            point = self.photo.point
            dest_crs = canvas.mapSettings().destinationCrs()
            if self.photo.crs and self.photo.crs.isValid() and self.photo.crs != dest_crs:
                transform = QgsCoordinateTransform(
                    self.photo.crs, dest_crs, QgsProject.instance()
                )
                point = transform.transform(point)
            canvas.setCenter(point)
            canvas.zoomScale(1000)
            canvas.refresh()
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Photo panel: zoom to location failed: {e}",
                'Linear Geoscience', Qgis.Warning
            )
            QMessageBox.warning(self, "Error", f"Could not zoom to location: {str(e)}")

    def select_on_map(self) -> None:
        """
        Bug fix #3: Select this photo's feature on the map.
        Was previously an empty stub (pass).
        """
        try:
            # Resolve the photo's source layer by id (duplicate-name safe)
            layer = None
            if getattr(self.photo, 'layer_id', ''):
                layer = QgsProject.instance().mapLayer(self.photo.layer_id)
            if layer is None:
                layers = QgsProject.instance().mapLayersByName('Photo Points')
                if not layers:
                    return
                layer = layers[0]
            layer.selectByIds([self.photo.feature_id])
            self.iface.mapCanvas().zoomToSelected(layer)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not select on map: {str(e)}")

    def copy_path_to_clipboard(self) -> None:
        """Copy the photo file path to clipboard."""
        QApplication.clipboard().setText(self.photo.path)


class FilterPanel(QFrame):
    """
    Widget for filtering and sorting photos.

    Bug fix #5: Uses persistent QTimer with stop()/start() for search debounce.
    """

    filter_changed = pyqtSignal()
    columns_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.collapsible = True
        self.is_expanded = True

        # Bug fix #5: persistent debounce timer
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self.filter_changed.emit)

        self._setup_ui()
        self._setup_connections()

    def _setup_ui(self):
        """Set up the UI components."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        self.header = QFrame()
        self.header.setFrameShape(QFrame.StyledPanel)
        self.header.setCursor(QCursor(Qt.PointingHandCursor))
        self.header.setStyleSheet(f"""
            QFrame {{
                background-color: {STYLE['PRIMARY']};
                border-radius: {STYLE['RADIUS_MD']};
                border: none;
                margin: 0;
                padding: 6px;
            }}
        """)

        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(10, 5, 10, 5)
        header_layout.setSpacing(8)

        title_label = QLabel("Filter Options")
        title_label.setStyleSheet(f"""
            color: white;
            font-weight: bold;
            font-size: {STYLE['FONT_SIZE_MD']};
        """)

        self.collapse_indicator = QLabel("▼")
        self.collapse_indicator.setStyleSheet("color: white;")

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.collapse_indicator)

        # Content panel
        self.content = QFrame()
        self.content.setFrameShape(QFrame.StyledPanel)
        self.content.setStyleSheet(f"""
            QFrame {{
                background-color: {STYLE['SECONDARY_LIGHT']};
                border-radius: 0 0 {STYLE['RADIUS_LG']} {STYLE['RADIUS_LG']};
                border: 1px solid {STYLE['BORDER']};
                border-top: none;
            }}
        """)

        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(
            STYLE['MARGIN_MD'], STYLE['MARGIN_MD'],
            STYLE['MARGIN_MD'], STYLE['MARGIN_MD']
        )
        content_layout.setSpacing(STYLE['MARGIN_SM'])

        # First row: Geologist and Sort
        first_row = QHBoxLayout()
        first_row.setSpacing(STYLE['MARGIN_MD'])

        # Geologist filter
        geologist_container = QWidget()
        geologist_layout = QHBoxLayout(geologist_container)
        geologist_layout.setContentsMargins(0, 0, 0, 0)
        geologist_layout.setSpacing(4)

        geologist_label = QLabel("Geologist:")
        geologist_label.setStyleSheet(f"""
            color: {STYLE['TEXT_SECONDARY']};
            font-size: {STYLE['FONT_SIZE_SM']};
        """)

        self.geologist_combo = QComboBox()
        self.geologist_combo.addItem("All Geologists")
        self.geologist_combo.setStyleSheet(f"""
            border: 1px solid {STYLE['BORDER_DARK']};
            border-radius: {STYLE['RADIUS_SM']};
            padding: 2px 4px;
            min-height: 22px;
        """)

        geologist_layout.addWidget(geologist_label)
        geologist_layout.addWidget(self.geologist_combo, 1)

        # Sort options
        sort_container = QWidget()
        sort_layout = QHBoxLayout(sort_container)
        sort_layout.setContentsMargins(0, 0, 0, 0)
        sort_layout.setSpacing(4)

        sort_label = QLabel("Sort by:")
        sort_label.setStyleSheet(f"""
            color: {STYLE['TEXT_SECONDARY']};
            font-size: {STYLE['FONT_SIZE_SM']};
        """)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Filename", "Geologist", "Date", "Feature ID"])
        self.sort_combo.setStyleSheet(f"""
            border: 1px solid {STYLE['BORDER_DARK']};
            border-radius: {STYLE['RADIUS_SM']};
            padding: 2px 4px;
            min-height: 22px;
        """)

        scale = get_scale_manager()
        self.sort_order_btn = QToolButton()
        self.sort_order_btn.setIcon(QIcon(":/images/themes/default/mActionSort.svg"))
        self.sort_order_btn.setIconSize(scale.icon_size(16, 16))
        self.sort_order_btn.setToolTip("Toggle sort order (ascending/descending)")
        self.sort_order_btn.setCheckable(True)
        self.sort_order_btn.setStyleSheet(f"""
            QToolButton {{
                border: 1px solid {STYLE['BORDER_DARK']};
                border-radius: {STYLE['RADIUS_SM']};
                padding: 2px;
            }}
            QToolButton:hover {{
                background-color: {STYLE['PRIMARY_LIGHT']};
            }}
        """)

        sort_layout.addWidget(sort_label)
        sort_layout.addWidget(self.sort_combo, 1)
        sort_layout.addWidget(self.sort_order_btn)

        first_row.addWidget(geologist_container)
        first_row.addWidget(sort_container)

        # Second row: Search
        search_container = QWidget()
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(4)

        search_label = QLabel("Search:")
        search_label.setStyleSheet(f"""
            color: {STYLE['TEXT_SECONDARY']};
            font-size: {STYLE['FONT_SIZE_SM']};
        """)

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Filter by filename or comment...")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.setStyleSheet(f"""
            border: 1px solid {STYLE['BORDER_DARK']};
            border-radius: {STYLE['RADIUS_SM']};
            padding: 2px 4px;
            min-height: 22px;
        """)

        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_field, 1)

        # Third row: Columns and Photo count
        third_row = QHBoxLayout()

        columns_container = QWidget()
        columns_layout = QHBoxLayout(columns_container)
        columns_layout.setContentsMargins(0, 0, 0, 0)
        columns_layout.setSpacing(4)

        columns_label = QLabel("Columns:")
        columns_label.setStyleSheet(f"""
            color: {STYLE['TEXT_SECONDARY']};
            font-size: {STYLE['FONT_SIZE_SM']};
        """)

        self.columns_slider = QSlider(Qt.Horizontal)
        self.columns_slider.setMinimum(1)
        self.columns_slider.setMaximum(4)
        self.columns_slider.setValue(2)
        self.columns_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 3px;
                background: {STYLE['BORDER_DARK']};
                margin: 0px 1px;
            }}
            QSlider::handle:horizontal {{
                background: {STYLE['PRIMARY']};
                width: 12px;
                height: 12px;
                margin: -5px 0;
                border-radius: 6px;
            }}
            QSlider::sub-page:horizontal {{
                background: {STYLE['PRIMARY']};
            }}
        """)

        self.columns_value = QLabel("2")
        self.columns_value.setAlignment(Qt.AlignCenter)
        self.columns_value.setStyleSheet(f"""
            background-color: {STYLE['PRIMARY_LIGHT']};
            color: {STYLE['PRIMARY']};
            border-radius: {STYLE['RADIUS_SM']};
            padding: 0px 4px;
            font-size: {STYLE['FONT_SIZE_XS']};
        """)
        self.columns_value.setFixedWidth(scale.dimension(16))

        columns_layout.addWidget(columns_label)
        columns_layout.addWidget(self.columns_slider, 1)
        columns_layout.addWidget(self.columns_value)

        self.count_label = QLabel("0 photos found")
        self.count_label.setStyleSheet(f"""
            color: white;
            background-color: {STYLE['PRIMARY']};
            border-radius: {STYLE['RADIUS_SM']};
            padding: 2px 6px;
            font-size: {STYLE['FONT_SIZE_SM']};
        """)

        third_row.addWidget(columns_container, 3)
        third_row.addWidget(self.count_label, 1)

        content_layout.addLayout(first_row)
        content_layout.addWidget(search_container)
        content_layout.addLayout(third_row)

        main_layout.addWidget(self.header)
        main_layout.addWidget(self.content)

    def _setup_connections(self):
        """Set up signal-slot connections."""
        if self.collapsible:
            self.header.mousePressEvent = lambda e: self.toggle_expanded()

        self.geologist_combo.currentTextChanged.connect(
            lambda: self.filter_changed.emit()
        )
        self.sort_combo.currentTextChanged.connect(
            lambda: self.filter_changed.emit()
        )
        self.sort_order_btn.toggled.connect(
            lambda: self.filter_changed.emit()
        )
        # Bug fix #5: use persistent timer with stop/start
        self.search_field.textChanged.connect(self._on_search_text_changed)

        self.columns_slider.valueChanged.connect(self._update_columns_value)
        self.columns_slider.valueChanged.connect(
            lambda value: self.columns_changed.emit(value)
        )

    def _on_search_text_changed(self):
        """Bug fix #5: restart debounce timer on each keystroke."""
        self._search_timer.stop()
        self._search_timer.start()

    def _update_columns_value(self, value):
        """Update the displayed columns value."""
        self.columns_value.setText(str(value))

    def toggle_expanded(self):
        """Toggle the expanded state of the panel."""
        self.is_expanded = not self.is_expanded
        self.content.setVisible(self.is_expanded)
        self.collapse_indicator.setText("▼" if self.is_expanded else "▶")

    def get_filter_state(self) -> Dict[str, Any]:
        """Get the current filter state."""
        return {
            'geologist': self.geologist_combo.currentText(),
            'search': self.search_field.text().strip().lower(),
            'sort_by': self.sort_combo.currentText(),
            'sort_order': 'descending' if self.sort_order_btn.isChecked() else 'ascending'
        }

    def set_filter_state(self, state: Dict[str, Any]) -> None:
        """Restore a saved filter state."""
        self.geologist_combo.blockSignals(True)
        self.sort_combo.blockSignals(True)
        self.sort_order_btn.blockSignals(True)
        self.search_field.blockSignals(True)

        if 'geologist' in state:
            index = self.geologist_combo.findText(state['geologist'])
            if index >= 0:
                self.geologist_combo.setCurrentIndex(index)
        if 'sort_by' in state:
            index = self.sort_combo.findText(state['sort_by'])
            if index >= 0:
                self.sort_combo.setCurrentIndex(index)
        if 'sort_order' in state:
            self.sort_order_btn.setChecked(state['sort_order'] == 'descending')
        if 'search' in state:
            self.search_field.setText(state['search'])

        self.geologist_combo.blockSignals(False)
        self.sort_combo.blockSignals(False)
        self.sort_order_btn.blockSignals(False)
        self.search_field.blockSignals(False)

    def set_photo_count(self, count: int, total: int) -> None:
        """Update the photo count label."""
        if count == total:
            self.count_label.setText(f"{count} photos")
        else:
            self.count_label.setText(f"{count} of {total} photos")

    def set_geologists(self, geologists: List[str]) -> None:
        """Update the geologist filter dropdown."""
        current = self.geologist_combo.currentText()
        self.geologist_combo.blockSignals(True)
        self.geologist_combo.clear()
        self.geologist_combo.addItem("All Geologists")
        for geologist in sorted(geologists):
            self.geologist_combo.addItem(geologist)
        index = self.geologist_combo.findText(current)
        if index >= 0:
            self.geologist_combo.setCurrentIndex(index)
        self.geologist_combo.blockSignals(False)
