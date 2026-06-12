"""
Photo Panel Slideshow Controls - Floating control panel for photo slideshow.

Auto-advance: QTimer with play/pause toggle and an interval spinner, so the
slideshow actually plays instead of requiring manual clicks.
"""

from qgis.PyQt.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel, QSpinBox, QStyle
)
from qgis.PyQt.QtCore import Qt, pyqtSignal, QTimer
from qgis.PyQt.QtGui import QIcon

from .constants import STYLE, get_scale_manager

DEFAULT_INTERVAL_S = 4
MIN_INTERVAL_S = 2
MAX_INTERVAL_S = 10


class SlideshowControls(QWidget):
    """Floating control panel for photo slideshow with auto-advance."""

    prev_requested = pyqtSignal()
    next_requested = pyqtSignal()
    view_requested = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.drag_position = None

        # Auto-advance timer
        self._timer = QTimer(self)
        self._timer.setInterval(DEFAULT_INTERVAL_S * 1000)
        self._timer.timeout.connect(self.next_requested.emit)

        self._setup_ui()
        self._setup_connections()

    def _setup_ui(self):
        """Set up the UI components."""
        scale = get_scale_manager()

        self.setWindowFlags(
            Qt.Window | Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {STYLE['PRIMARY_DARK']};
                border-radius: {STYLE['RADIUS_LG']};
                border: 1px solid {STYLE['BORDER_DARK']};
            }}
        """)

        layout = QHBoxLayout(self)
        margins = scale.margins(10, 10, 10, 10)
        layout.setContentsMargins(*margins)
        layout.setSpacing(scale.spacing(10))

        btn_padding = scale.dimension(8)
        button_style = f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: {STYLE['RADIUS_MD']};
                padding: {btn_padding}px;
                color: white;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.2);
            }}
            QPushButton:pressed {{
                background-color: rgba(255, 255, 255, 0.3);
            }}
        """

        self.prev_btn = QPushButton()
        self.prev_btn.setIcon(QIcon(":/images/themes/default/mActionArrowLeft.svg"))
        self.prev_btn.setIconSize(scale.icon_size(24, 24))
        self.prev_btn.setToolTip("Previous Photo (Left Arrow)")
        self.prev_btn.setStyleSheet(button_style)

        # Play/pause toggle (standard style icons are always available)
        self.play_btn = QPushButton()
        self.play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_btn.setIconSize(scale.icon_size(24, 24))
        self.play_btn.setToolTip("Play/Pause Slideshow (Space)")
        self.play_btn.setStyleSheet(button_style)

        # Interval spinner (seconds between photos)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(MIN_INTERVAL_S, MAX_INTERVAL_S)
        self.interval_spin.setValue(DEFAULT_INTERVAL_S)
        self.interval_spin.setSuffix(" s")
        self.interval_spin.setToolTip("Seconds between photos")
        self.interval_spin.setFocusPolicy(Qt.ClickFocus)
        self.interval_spin.setStyleSheet(f"""
            QSpinBox {{
                background-color: rgba(255, 255, 255, 0.15);
                color: white;
                border: none;
                border-radius: {STYLE['RADIUS_SM']};
                padding: 2px 4px;
            }}
        """)

        indicator_padding = scale.dimension(8)
        self.indicator = QLabel("Photo 0 of 0")
        self.indicator.setStyleSheet(f"""
            color: white;
            font-size: {STYLE['FONT_SIZE_MD']};
            padding: 0 {indicator_padding}px;
        """)

        self.next_btn = QPushButton()
        self.next_btn.setIcon(QIcon(":/images/themes/default/mActionArrowRight.svg"))
        self.next_btn.setIconSize(scale.icon_size(24, 24))
        self.next_btn.setToolTip("Next Photo (Right Arrow)")
        self.next_btn.setStyleSheet(button_style)

        self.view_btn = QPushButton()
        self.view_btn.setIcon(QIcon(":/images/themes/default/mActionOpen.svg"))
        self.view_btn.setIconSize(scale.icon_size(20, 20))
        self.view_btn.setToolTip("View Current Photo")
        self.view_btn.setStyleSheet(button_style)

        self.close_btn = QPushButton()
        self.close_btn.setIcon(QIcon(":/images/themes/default/mActionRemove.svg"))
        self.close_btn.setIconSize(scale.icon_size(16, 16))
        self.close_btn.setToolTip("Close Slideshow")
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: {STYLE['RADIUS_MD']};
                padding: {btn_padding}px;
                color: white;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 0, 0, 0.3);
            }}
            QPushButton:pressed {{
                background-color: rgba(255, 0, 0, 0.5);
            }}
        """)

        layout.addWidget(self.prev_btn)
        layout.addWidget(self.play_btn)
        layout.addWidget(self.indicator)
        layout.addWidget(self.next_btn)
        layout.addWidget(self.interval_spin)
        layout.addWidget(self.view_btn)
        layout.addWidget(self.close_btn)

        # Scaled fixed size
        self._panel_width = scale.dimension(440)
        self._panel_height = scale.dimension(60)
        self.setFixedSize(self._panel_width, self._panel_height)

    def _setup_connections(self):
        """Set up signal-slot connections."""
        self.prev_btn.clicked.connect(self._on_manual_nav_prev)
        self.next_btn.clicked.connect(self._on_manual_nav_next)
        self.play_btn.clicked.connect(self.toggle_play)
        self.interval_spin.valueChanged.connect(
            lambda seconds: self._timer.setInterval(seconds * 1000)
        )
        self.view_btn.clicked.connect(self.view_requested.emit)
        self.close_btn.clicked.connect(self.close_slideshow)

    # -------------------------------------------------------------------
    # Playback
    # -------------------------------------------------------------------
    def is_playing(self) -> bool:
        return self._timer.isActive()

    def toggle_play(self):
        """Toggle auto-advance playback."""
        if self._timer.isActive():
            self.pause()
        else:
            self.play()

    def play(self):
        """Start auto-advance."""
        self._timer.start()
        self.play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self.play_btn.setToolTip("Pause Slideshow (Space)")

    def pause(self):
        """Pause auto-advance."""
        self._timer.stop()
        self.play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_btn.setToolTip("Play Slideshow (Space)")

    def _on_manual_nav_prev(self):
        """Manual previous: restart the timer so the photo gets full time."""
        if self._timer.isActive():
            self._timer.start()
        self.prev_requested.emit()

    def _on_manual_nav_next(self):
        """Manual next: restart the timer so the photo gets full time."""
        if self._timer.isActive():
            self._timer.start()
        self.next_requested.emit()

    def close_slideshow(self):
        """Close the slideshow panel."""
        self.pause()
        self.hide()
        self.closed.emit()

    def closeEvent(self, event):
        """Ensure the timer stops when the window is closed directly."""
        self.pause()
        self.closed.emit()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        """Keyboard control when the floating panel has focus."""
        key = event.key()
        if key == Qt.Key_Left:
            self._on_manual_nav_prev()
        elif key == Qt.Key_Right:
            self._on_manual_nav_next()
        elif key == Qt.Key_Space:
            self.toggle_play()
        elif key == Qt.Key_Escape:
            self.close_slideshow()
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self.view_requested.emit()
        else:
            super().keyPressEvent(event)

    def set_position(self, index: int, total: int) -> None:
        """Update the photo position indicator."""
        self.indicator.setText(f"Photo {index + 1} of {total}")

    def position_on_screen(self, iface) -> None:
        """Position the panel on screen. Uses scaled half-width (was hardcoded 175)."""
        qgis_rect = iface.mainWindow().geometry()
        half_width = self._panel_width // 2
        panel_x = qgis_rect.x() + qgis_rect.width() // 2 - half_width
        panel_y = qgis_rect.y() + 120
        self.move(int(panel_x), int(panel_y))

    def mousePressEvent(self, event):
        """Handle mouse press for dragging."""
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """Handle mouse move for dragging."""
        if event.buttons() == Qt.LeftButton and self.drag_position:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        """Handle mouse release for dragging."""
        if event.button() == Qt.LeftButton:
            self.drag_position = None
            event.accept()
