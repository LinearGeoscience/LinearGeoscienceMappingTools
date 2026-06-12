"""
Photo Panel Viewer - QGraphicsView-based photo viewer with zoom/pan.

Bug fixes:
  #11: EXIF orientation applied when displaying full-size photos
  #13: resizeEvent calls fitInView() when in fit-mode

UI improvements:
  - QGraphicsView with mouse wheel zoom, click-and-drag pan
  - Control bar: Zoom In, Zoom Out, Fit to Window, 100%
  - Keyboard shortcuts: +/= zoom in, - zoom out, 0 fit, 1 actual size
  - Auto-fit on resize when user hasn't manually zoomed
"""

import os

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QFrame
)
from qgis.PyQt.QtCore import Qt, pyqtSignal, QRectF
from qgis.PyQt.QtGui import (
    QPixmap, QIcon, QImage, QTransform, QPainter, QColor
)

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.core import QgsMessageLog, Qgis

from .constants import STYLE, get_scale_manager, ZOOM_FACTOR, ZOOM_MIN, ZOOM_MAX
from .loader import FullImageLoader


class ZoomableImageView(QGraphicsView):
    """
    QGraphicsView subclass with mouse-wheel zoom and click-drag pan.

    Bug fix #13: resizeEvent calls fitInView when in fit-mode.
    """

    zoom_changed = pyqtSignal()
    double_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem = None
        self._fit_mode = True  # auto-fit until user manually zooms

        # Configure view
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setBackgroundBrush(Qt.black)
        self.setFrameShape(QFrame.NoFrame)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        """Display a pixmap in the view."""
        self._scene.clear()
        if pixmap and not pixmap.isNull():
            self._pixmap_item = self._scene.addPixmap(pixmap)
            self._scene.setSceneRect(QRectF(pixmap.rect()))
            self._fit_mode = True
            self.fit_in_view()
        else:
            self._pixmap_item = None
            self.zoom_changed.emit()

    def show_message(self, text: str) -> None:
        """Clear the scene and show a centered text message (e.g. Loading...)."""
        self._scene.clear()
        self._pixmap_item = None
        text_item = self._scene.addText(text)
        text_item.setDefaultTextColor(QColor("white"))
        self._scene.setSceneRect(text_item.boundingRect())
        self.resetTransform()
        self.zoom_changed.emit()

    def fit_in_view(self) -> None:
        """Fit the image in the view, maintaining aspect ratio."""
        if self._pixmap_item:
            self._fit_mode = True
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)
            self.zoom_changed.emit()

    def actual_size(self) -> None:
        """Show image at 100% (1:1 pixel mapping)."""
        self._fit_mode = False
        self.resetTransform()
        self.zoom_changed.emit()

    def zoom_in(self) -> None:
        """Zoom in by ZOOM_FACTOR."""
        self._fit_mode = False
        current = self.transform().m11()
        if current < ZOOM_MAX:
            self.scale(ZOOM_FACTOR, ZOOM_FACTOR)
        self.zoom_changed.emit()

    def zoom_out(self) -> None:
        """Zoom out by ZOOM_FACTOR."""
        self._fit_mode = False
        current = self.transform().m11()
        if current > ZOOM_MIN:
            factor = 1.0 / ZOOM_FACTOR
            self.scale(factor, factor)
        self.zoom_changed.emit()

    def wheelEvent(self, event):
        """Mouse wheel zoom, anchored under mouse."""
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def mouseDoubleClickEvent(self, event):
        """Double-click toggles fullscreen (handled by the viewer)."""
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event):
        """Bug fix #13: re-fit when in fit-mode on window resize."""
        super().resizeEvent(event)
        if self._fit_mode and self._pixmap_item:
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)
            self.zoom_changed.emit()


class PhotoViewer(QWidget):
    """
    Photo viewer window with zoom/pan and navigation controls.
    """

    prev_requested = pyqtSignal()
    next_requested = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.current_photo = None
        self.current_index = -1
        self.total_photos = 0
        self.current_rotation = 0
        self.original_pixmap = None
        self._request_id = 0

        # Background loader for full-resolution images (no UI freeze)
        self._image_loader = FullImageLoader()
        self._image_loader.image_ready.connect(self._on_image_ready)
        self._image_loader.image_error.connect(self._on_image_error)

        self._setup_ui()
        self._setup_connections()

    def _setup_ui(self):
        """Set up the UI components."""
        scale = get_scale_manager()

        self.setWindowTitle("Photo Viewer")
        viewer_width, viewer_height = scale.dialog_size(800, 600)
        self.setMinimumSize(viewer_width, viewer_height)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Zoomable image view (replaces QLabel + QScrollArea)
        self.image_view = ZoomableImageView()
        self.image_view.setStyleSheet(f"background-color: {STYLE['VIEWER_BG']};")

        # Control bar
        self.control_bar = QWidget()
        self.control_bar.setStyleSheet(f"""
            background-color: {STYLE['PRIMARY_DARK']};
            color: white;
        """)
        self.control_bar.setFixedHeight(scale.dimension(50))

        control_layout = QHBoxLayout(self.control_bar)
        control_margins = scale.margins(10, 5, 10, 5)
        control_layout.setContentsMargins(
            control_margins[0], control_margins[3],
            control_margins[1], control_margins[2]
        )

        btn_padding = scale.dimension(5)
        btn_radius = scale.dimension(3)
        btn_style = f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                padding: {btn_padding}px;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.2);
                border-radius: {btn_radius}px;
            }}
            QPushButton:checked {{
                background-color: rgba(255, 255, 255, 0.3);
                border-radius: {btn_radius}px;
            }}
        """

        # Navigation buttons
        self.prev_btn = QPushButton()
        self.prev_btn.setIcon(QIcon(":/images/themes/default/mActionArrowLeft.svg"))
        self.prev_btn.setIconSize(scale.icon_size(24, 24))
        self.prev_btn.setToolTip("Previous Photo (Left Arrow)")
        self.prev_btn.setStyleSheet(btn_style)

        # Rotation buttons
        self.rotate_left_btn = QPushButton()
        self.rotate_left_btn.setIcon(QIcon(":/images/themes/default/mActionUndo.svg"))
        self.rotate_left_btn.setIconSize(scale.icon_size(20, 20))
        self.rotate_left_btn.setToolTip("Rotate Left 90°")
        self.rotate_left_btn.setStyleSheet(btn_style)

        self.rotate_right_btn = QPushButton()
        self.rotate_right_btn.setIcon(QIcon(":/images/themes/default/mActionRedo.svg"))
        self.rotate_right_btn.setIconSize(scale.icon_size(20, 20))
        self.rotate_right_btn.setToolTip("Rotate Right 90°")
        self.rotate_right_btn.setStyleSheet(btn_style)

        # Zoom buttons
        self.zoom_in_btn = QPushButton()
        self.zoom_in_btn.setIcon(QIcon(":/images/themes/default/mActionZoomIn.svg"))
        self.zoom_in_btn.setIconSize(scale.icon_size(20, 20))
        self.zoom_in_btn.setToolTip("Zoom In (+)")
        self.zoom_in_btn.setStyleSheet(btn_style)

        self.zoom_out_btn = QPushButton()
        self.zoom_out_btn.setIcon(QIcon(":/images/themes/default/mActionZoomOut.svg"))
        self.zoom_out_btn.setIconSize(scale.icon_size(20, 20))
        self.zoom_out_btn.setToolTip("Zoom Out (-)")
        self.zoom_out_btn.setStyleSheet(btn_style)

        self.fit_btn = QPushButton()
        self.fit_btn.setIcon(QIcon(":/images/themes/default/mActionZoomFullExtent.svg"))
        self.fit_btn.setIconSize(scale.icon_size(20, 20))
        self.fit_btn.setToolTip("Fit to Window (0)")
        self.fit_btn.setCheckable(True)
        self.fit_btn.setChecked(True)
        self.fit_btn.setStyleSheet(btn_style)

        self.actual_btn = QPushButton()
        self.actual_btn.setIcon(QIcon(":/images/themes/default/mActionZoomActual.svg"))
        self.actual_btn.setIconSize(scale.icon_size(20, 20))
        self.actual_btn.setToolTip("Actual Size (1)")
        self.actual_btn.setCheckable(True)
        self.actual_btn.setStyleSheet(btn_style)

        # Zoom percentage indicator
        self.zoom_label = QLabel("")
        self.zoom_label.setStyleSheet("color: white;")
        self.zoom_label.setMinimumWidth(scale.dimension(45))
        self.zoom_label.setAlignment(Qt.AlignCenter)

        # Fullscreen toggle
        self.fullscreen_btn = QPushButton()
        self.fullscreen_btn.setIcon(QIcon(":/images/themes/default/mActionToggleFullScreen.png"))
        self.fullscreen_btn.setIconSize(scale.icon_size(20, 20))
        self.fullscreen_btn.setToolTip("Toggle Fullscreen (F11 or double-click)")
        self.fullscreen_btn.setCheckable(True)
        self.fullscreen_btn.setStyleSheet(btn_style)

        # Open in system viewer
        self.open_external_btn = QPushButton()
        self.open_external_btn.setIcon(QIcon(":/images/themes/default/mActionOpen.svg"))
        self.open_external_btn.setIconSize(scale.icon_size(20, 20))
        self.open_external_btn.setToolTip("Open in System Viewer (Enter)")
        self.open_external_btn.setStyleSheet(btn_style)

        # Photo counter
        self.photo_counter = QLabel("Photo 0 of 0")
        self.photo_counter.setStyleSheet("color: white;")
        self.photo_counter.setAlignment(Qt.AlignCenter)

        # File name label
        self.filename_label = QLabel("")
        self.filename_label.setStyleSheet("color: white; font-weight: bold;")

        # Next button
        self.next_btn = QPushButton()
        self.next_btn.setIcon(QIcon(":/images/themes/default/mActionArrowRight.svg"))
        self.next_btn.setIconSize(scale.icon_size(24, 24))
        self.next_btn.setToolTip("Next Photo (Right Arrow)")
        self.next_btn.setStyleSheet(btn_style)

        # Build control layout
        control_layout.addWidget(self.prev_btn)
        control_layout.addWidget(self.rotate_left_btn)
        control_layout.addWidget(self.rotate_right_btn)
        control_layout.addWidget(self.zoom_in_btn)
        control_layout.addWidget(self.zoom_out_btn)
        control_layout.addWidget(self.fit_btn)
        control_layout.addWidget(self.actual_btn)
        control_layout.addWidget(self.zoom_label)
        control_layout.addWidget(self.fullscreen_btn)
        control_layout.addWidget(self.open_external_btn)
        control_layout.addStretch(1)
        control_layout.addWidget(self.photo_counter)
        control_layout.addStretch(1)
        control_layout.addWidget(self.filename_label)
        control_layout.addStretch(1)
        control_layout.addWidget(self.next_btn)

        layout.addWidget(self.image_view)
        layout.addWidget(self.control_bar)

    def _setup_connections(self):
        """Set up signal-slot connections."""
        self.prev_btn.clicked.connect(self.prev_requested.emit)
        self.next_btn.clicked.connect(self.next_requested.emit)
        self.rotate_left_btn.clicked.connect(self._rotate_left)
        self.rotate_right_btn.clicked.connect(self._rotate_right)
        self.zoom_in_btn.clicked.connect(self.image_view.zoom_in)
        self.zoom_out_btn.clicked.connect(self.image_view.zoom_out)
        self.fit_btn.clicked.connect(self.image_view.fit_in_view)
        self.actual_btn.clicked.connect(self.image_view.actual_size)
        self.fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        self.open_external_btn.clicked.connect(self._open_in_native_viewer)
        self.image_view.zoom_changed.connect(self._update_zoom_ui)
        self.image_view.double_clicked.connect(self._toggle_fullscreen)

    def display_photo(self, photo_path: str, index: int, total: int) -> None:
        """Display a photo with navigation context (loaded asynchronously)."""
        if not photo_path or not os.path.isfile(photo_path):
            return

        self.current_photo = photo_path
        self.current_index = index
        self.total_photos = total
        self.current_rotation = 0
        self.original_pixmap = None

        # Update UI immediately; the image arrives via _on_image_ready
        filename = os.path.basename(photo_path)
        self.setWindowTitle(f"Photo Viewer - {filename}")
        self.filename_label.setText(filename)
        self.photo_counter.setText(f"Photo {index + 1} of {total}")
        self.image_view.show_message(f"Loading {filename}...")

        self._request_id += 1
        self._image_loader.request(self._request_id, photo_path)

    def _on_image_ready(self, request_id: int, path: str, image: QImage) -> None:
        """Receive the full-size image from the background loader."""
        if request_id != self._request_id:
            return  # stale result from rapid navigation
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            self.image_view.show_message("Could not display image")
            return
        self.original_pixmap = pixmap
        self.image_view.set_pixmap(pixmap)

    def _on_image_error(self, request_id: int, path: str, error: str) -> None:
        """Handle a full-size image load failure."""
        if request_id != self._request_id:
            return
        self.image_view.show_message(f"Could not load image:\n{os.path.basename(path)}")
        QgsMessageLog.logMessage(
            f"Photo panel: failed to load '{path}': {error}",
            'Linear Geoscience', Qgis.Warning
        )

    def _update_zoom_ui(self) -> None:
        """Sync zoom label and fit/actual button states with the view."""
        zoom = self.image_view.transform().m11()
        self.zoom_label.setText(f"{int(round(zoom * 100))}%")
        fit_mode = self.image_view._fit_mode
        self.fit_btn.setChecked(fit_mode)
        self.actual_btn.setChecked(not fit_mode and abs(zoom - 1.0) < 0.01)

    def _toggle_fullscreen(self) -> None:
        """Toggle fullscreen mode (F11, button, or double-click)."""
        if self.isFullScreen():
            self.showNormal()
            self.fullscreen_btn.setChecked(False)
        else:
            self.showFullScreen()
            self.fullscreen_btn.setChecked(True)

    def shutdown(self) -> None:
        """Stop the background image loader (called on panel shutdown)."""
        self._image_loader.stop()
        self.close()

    def keyPressEvent(self, event):
        """Handle key press events with zoom shortcuts."""
        key = event.key()
        mod = event.modifiers()

        if key == Qt.Key_Left and mod & Qt.ControlModifier:
            self._rotate_left()
        elif key == Qt.Key_Right and mod & Qt.ControlModifier:
            self._rotate_right()
        elif key == Qt.Key_Left:
            self.prev_requested.emit()
        elif key == Qt.Key_Right:
            self.next_requested.emit()
        elif key == Qt.Key_F11:
            self._toggle_fullscreen()
        elif key == Qt.Key_Escape:
            if self.isFullScreen():
                self._toggle_fullscreen()
            else:
                self.close()
        elif key == Qt.Key_Return or key == Qt.Key_Enter:
            self._open_in_native_viewer()
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self.image_view.zoom_in()
        elif key == Qt.Key_Minus:
            self.image_view.zoom_out()
        elif key == Qt.Key_0:
            self.image_view.fit_in_view()
        elif key == Qt.Key_1:
            self.image_view.actual_size()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        """Handle window close event."""
        self.closed.emit()
        super().closeEvent(event)

    def _rotate_left(self):
        """Rotate the image 90 degrees counter-clockwise."""
        if self.original_pixmap and not self.original_pixmap.isNull():
            self.current_rotation = (self.current_rotation - 90) % 360
            self._apply_rotation()

    def _rotate_right(self):
        """Rotate the image 90 degrees clockwise."""
        if self.original_pixmap and not self.original_pixmap.isNull():
            self.current_rotation = (self.current_rotation + 90) % 360
            self._apply_rotation()

    def _apply_rotation(self):
        """Apply current rotation to the image."""
        if not self.original_pixmap or self.original_pixmap.isNull():
            return

        pixmap = self.original_pixmap
        if self.current_rotation != 0:
            transform = QTransform()
            transform.rotate(self.current_rotation)
            pixmap = pixmap.transformed(transform, Qt.SmoothTransformation)

        self.image_view.set_pixmap(pixmap)

    def _open_in_native_viewer(self):
        """Open the current photo in the system's default viewer."""
        if self.current_photo and os.path.isfile(self.current_photo):
            try:
                QDesktopServices.openUrl(QUrl.fromLocalFile(self.current_photo))
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Photo panel: could not open '{self.current_photo}' "
                    f"in system viewer: {e}",
                    'Linear Geoscience', Qgis.Warning
                )
