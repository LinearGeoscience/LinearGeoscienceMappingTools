"""
Photo Panel - Main QDockWidget with PhotoDataWorker thread.

Bug fixes:
  #2:  Connect PhotoThumbnail.clicked signal instead of lambda override
  #7:  Keep viewer alive on close (hide, don't destroy)
  #9:  Per-instance cache
  #10: PhotoDataWorker QThread replaces processEvents() calls
  Auto-scroll loading when within 200px of bottom
"""

import os
import re
from typing import List, Optional

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QGridLayout, QMessageBox, QFrame, QSizePolicy,
    QProgressBar, QToolButton, QStyle, QComboBox
)
from qgis.PyQt.QtCore import (
    Qt, QEvent, QThread, pyqtSignal, QTimer
)
from qgis.PyQt.QtGui import QPixmap, QDesktopServices, QIcon, QImage

from qgis.core import (
    QgsProject, QgsFeatureRequest, QgsCoordinateTransform,
    QgsMessageLog, Qgis, QgsWkbTypes
)

try:
    from ..layer_select import layer_candidates, populate_layer_combo, combo_current_layer
except ImportError:
    from layer_select import layer_candidates, populate_layer_combo, combo_current_layer
from qgis.PyQt.QtCore import QUrl
from qgis.gui import QgsMapToolIdentifyFeature

from .constants import (
    STYLE, get_scale_manager, AUTO_LOAD_THRESHOLD, THUMB_CHUNK_SIZE
)
from .models import PhotoInfo, PhotoCollection
from .cache import ThumbnailCache
from .loader import LoadingScheduler
from .widgets import PhotoThumbnail, FilterPanel
from .viewer import PhotoViewer
from .slideshow import SlideshowControls


# =============================================================================
# Data Loading Worker (Bug fix #10)
# =============================================================================

def _attr_to_str(value) -> str:
    """Convert a feature attribute to a clean string (NULL/None-safe)."""
    if value is None:
        return ""
    text = str(value).strip()
    if text in ("NULL", "None"):
        return ""
    return text


def _photo_layer_candidates():
    """Point layers with the fields PhotoDataWorker requires."""
    return layer_candidates(geometry=QgsWkbTypes.PointGeometry,
                            required_fields=['PhotoFiles', 'PhotoPath'])


# Key for persisting the chosen photo layer in the project file
PHOTO_LAYER_SETTING_SCOPE = "LinearGeoscience"
PHOTO_LAYER_SETTING_KEY = "photo_panel/layer_id"


class PhotoDataWorker(QThread):
    """
    Background thread for loading photo data from the QGIS layer.

    Bug fix #10: replaces processEvents() calls with a proper QThread.
    """

    progress = pyqtSignal(int, int)          # processed, total
    photo_loaded = pyqtSignal(object)        # PhotoInfo
    # Named data_finished: shadowing the built-in QThread.finished signal
    # is an anti-pattern.
    data_finished = pyqtSignal(int)          # total loaded
    error = pyqtSignal(str)

    def __init__(self, layer):
        super().__init__()
        self.layer = layer
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        try:
            required_fields = ['PhotoFiles', 'PhotoPath']
            for field in required_fields:
                if self.layer.fields().indexFromName(field) < 0:
                    self.error.emit(f"Required field '{field}' not found in layer")
                    return

            total_features = self.layer.featureCount()
            if total_features == 0:
                self.data_finished.emit(0)
                return

            photo_files_idx = self.layer.fields().indexFromName('PhotoFiles')
            photo_path_idx = self.layer.fields().indexFromName('PhotoPath')
            geologist_idx = self.layer.fields().indexFromName('Geologist')
            comments_idx = self.layer.fields().indexFromName('Comments')
            layer_crs = self.layer.crs()

            processed = 0
            total_photos = 0
            request = QgsFeatureRequest()

            for feature in self.layer.getFeatures(request):
                if not self._is_running:
                    break

                processed += 1

                if processed % 10 == 0:
                    self.progress.emit(processed, total_features)

                photo_files_str = _attr_to_str(feature.attribute(photo_files_idx))
                if not photo_files_str:
                    continue

                if not feature.hasGeometry():
                    continue

                photo_folder = os.path.dirname(
                    _attr_to_str(feature.attribute(photo_path_idx))
                )
                feature_id = feature.id()
                geologist = _attr_to_str(
                    feature.attribute(geologist_idx)) if geologist_idx >= 0 else ""
                comment = _attr_to_str(
                    feature.attribute(comments_idx)) if comments_idx >= 0 else ""
                point = feature.geometry().asPoint()

                # Accept both comma- and semicolon-separated photo lists
                photo_files = [f.strip() for f in re.split(r'[,;]', photo_files_str)]
                for photo_file in photo_files:
                    if not photo_file:
                        continue
                    photo_path = os.path.join(photo_folder, photo_file)
                    if not os.path.exists(photo_path):
                        continue

                    photo = PhotoInfo(
                        path=photo_path,
                        feature_id=feature_id,
                        point=point,
                        geologist=geologist,
                        comment=comment,
                        crs=layer_crs,
                        layer_id=self.layer.id()
                    )
                    self.photo_loaded.emit(photo)
                    total_photos += 1

            self.data_finished.emit(total_photos)

        except Exception as e:
            self.error.emit(str(e))


# =============================================================================
# Main Panel
# =============================================================================

class PhotoPanel(QDockWidget):
    """
    Main dockable panel for displaying and managing georeferenced field photos.
    """

    def __init__(self, iface, parent=None):
        super().__init__("Field Photos", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setObjectName("FieldPhotosPanel")
        self.iface = iface

        # Bug fix #9: per-instance cache
        self._cache = ThumbnailCache()

        self._init_data_model()
        self._init_workers()
        self._setup_ui()
        self._setup_connections()
        self._connect_qgis_signals()

        # Data loading worker reference
        self._data_worker: Optional[PhotoDataWorker] = None

        QTimer.singleShot(100, self._initial_load)

    def _init_data_model(self):
        """Initialize data models."""
        self.photo_collection = PhotoCollection()
        self.current_batch = 0
        self.batch_size = 30
        self.columns = 2
        self.current_photo_path = None
        self.current_photo_index = -1
        self.in_slideshow_mode = False
        self.photo_layer = None
        self.saved_view_state = None
        self.map_extent_filter = None
        # Chunked thumbnail creation state
        self._pending_photos: List = []
        self._build_generation = 0
        # O(1) widget lookup by photo path
        self._thumb_by_path = {}

    def _init_workers(self):
        """Initialize worker threads and thumbnail processor."""
        # Bug fix #9: pass per-instance cache to loader
        self.loader_scheduler = LoadingScheduler(self._cache)

        # Bug fix #12: connect QImage signal, convert to QPixmap on main thread
        self.loader_scheduler.loader.thumbnail_ready.connect(self._on_thumbnail_ready)
        self.loader_scheduler.loader.thumbnail_error.connect(self._on_thumbnail_error)
        self.loader_scheduler.loader.progress.connect(self._update_loading_progress)
        self.loader_scheduler.loader.finished_batch.connect(self._on_batch_loaded)

    def _on_thumbnail_ready(self, path: str, key: str, image: QImage):
        """
        Bug fix #12: convert QImage to QPixmap on main thread, then update thumbnail.
        """
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            self._cache.put(key, pixmap)
        else:
            # Image is null means it was already in cache
            pixmap = self._cache.get(key)

        if pixmap and not pixmap.isNull():
            thumbnail = self._thumb_by_path.get(path)
            if thumbnail is not None:
                thumbnail.set_thumbnail(pixmap)

    def _on_thumbnail_error(self, path: str, error_message: str):
        """Handle thumbnail loading errors."""
        thumbnail = self._thumb_by_path.get(path)
        if thumbnail is not None:
            thumbnail.photo_label.setText("Image Error")
            thumbnail.photo_label.setToolTip(f"Error loading image: {error_message}")

    def _setup_ui(self):
        """Set up the UI components."""
        self.main_widget = QWidget()
        self.main_widget.setStyleSheet("background-color: white;")
        self.main_layout = QVBoxLayout(self.main_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self._create_header_ribbon()

        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background-color: white;")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(
            STYLE['MARGIN_XL'], STYLE['MARGIN_XL'],
            STYLE['MARGIN_XL'], STYLE['MARGIN_XL']
        )
        self.content_layout.setSpacing(STYLE['MARGIN_LG'])

        # Photo layer selector — only shown when more than one candidate
        # layer exists in the project
        self.layer_select_widget = QWidget()
        layer_select_layout = QHBoxLayout(self.layer_select_widget)
        layer_select_layout.setContentsMargins(0, 0, 0, 0)
        layer_select_layout.setSpacing(STYLE['MARGIN_SM'])
        layer_select_label = QLabel("Photo layer:")
        layer_select_label.setStyleSheet(
            f"color: {STYLE['TEXT_SECONDARY']}; font-size: {STYLE['FONT_SIZE_SM']};"
        )
        layer_select_layout.addWidget(layer_select_label)
        self.layer_combo = QComboBox()
        layer_select_layout.addWidget(self.layer_combo, 1)
        self.layer_select_widget.setVisible(False)
        self.content_layout.addWidget(self.layer_select_widget)

        self.filter_panel = FilterPanel()
        self.content_layout.addWidget(self.filter_panel)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                border-radius: {STYLE['RADIUS_SM']};
                background-color: {STYLE['SECONDARY_LIGHT']};
                height: 6px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {STYLE['PRIMARY']};
                border-radius: {STYLE['RADIUS_SM']};
            }}
        """)
        self.progress_bar.hide()
        self.content_layout.addWidget(self.progress_bar)

        self._setup_photo_grid()
        self._create_status_bar()

        self.main_layout.addWidget(self.content_widget)
        self.setWidget(self.main_widget)

        # Bug fix #7: viewer kept alive, reused
        self.photo_viewer: Optional[PhotoViewer] = None
        self.slideshow_controls: Optional[SlideshowControls] = None

        # Keyboard navigation
        self.main_widget.setFocusPolicy(Qt.StrongFocus)
        self.main_widget.installEventFilter(self)
        self.focused_index = -1
        self.thumbnails = []

    def _create_header_ribbon(self):
        """Create the header ribbon with title and actions."""
        scale = get_scale_manager()
        self.ribbon = QFrame()
        self.ribbon.setObjectName("ribbon")
        self.ribbon.setMinimumHeight(scale.dimension(60))
        self.ribbon.setStyleSheet(f"""
            QFrame#ribbon {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                        stop:0 {STYLE['HEADER_START']},
                                        stop:1 {STYLE['HEADER_END']});
                border-bottom: 1px solid rgba(0,0,0,0.1);
            }}
        """)

        ribbon_layout = QHBoxLayout(self.ribbon)
        ribbon_layout.setContentsMargins(
            STYLE['MARGIN_XL'], STYLE['MARGIN_MD'],
            STYLE['MARGIN_XL'], STYLE['MARGIN_MD']
        )

        title_container = QWidget()
        title_container.setStyleSheet("background-color: transparent;")
        title_layout = QHBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(scale.spacing(8))

        icon_label = QLabel()
        icon_label.setPixmap(
            QIcon(":/images/themes/default/mActionAddImage.svg").pixmap(scale.icon_size(24, 24))
        )
        icon_label.setStyleSheet("background-color: transparent;")

        title_label = QLabel("Field Photos")
        title_label.setStyleSheet(f"""
            color: white;
            font-size: {STYLE['FONT_SIZE_XL']};
            font-weight: bold;
            background-color: transparent;
        """)

        title_layout.addWidget(icon_label)
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        actions_container = QWidget()
        actions_container.setStyleSheet("background-color: transparent;")
        actions_layout = QHBoxLayout(actions_container)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(scale.spacing(8))

        button_style = f"""
            QToolButton {{
                border: none;
                border-radius: {STYLE['RADIUS_MD']};
                background-color: rgba(255, 255, 255, 0.2);
                padding: 8px;
            }}
            QToolButton:hover {{
                background-color: rgba(255, 255, 255, 0.3);
            }}
            QToolButton:pressed {{
                background-color: rgba(0, 0, 0, 0.1);
            }}
            QToolButton:checked {{
                background-color: rgba(255, 255, 0, 0.3);
            }}
        """

        self.map_extent_btn = QToolButton()
        self.map_extent_btn.setIcon(QIcon(":/images/themes/default/mActionZoomToSelected.svg"))
        self.map_extent_btn.setIconSize(scale.icon_size(18, 18))
        self.map_extent_btn.setToolTip("Filter photos to current map extent")
        self.map_extent_btn.setCheckable(True)
        self.map_extent_btn.setStyleSheet(button_style)

        self.select_tool_btn = QToolButton()
        self.select_tool_btn.setIcon(QIcon(":/images/themes/default/mActionSelect.svg"))
        self.select_tool_btn.setIconSize(scale.icon_size(18, 18))
        self.select_tool_btn.setToolTip("Toggle Map Selection Tool")
        self.select_tool_btn.setCheckable(True)
        self.select_tool_btn.setStyleSheet(button_style)

        self.slideshow_btn = QToolButton()
        self.slideshow_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.slideshow_btn.setIconSize(scale.icon_size(18, 18))
        self.slideshow_btn.setToolTip("Start Slideshow (Ctrl+S)")
        self.slideshow_btn.setStyleSheet(button_style)

        self.filter_toggle_btn = QToolButton()
        self.filter_toggle_btn.setIcon(QIcon(":/images/themes/default/mActionFilter.svg"))
        self.filter_toggle_btn.setIconSize(scale.icon_size(18, 18))
        self.filter_toggle_btn.setToolTip("Toggle Filter Panel")
        self.filter_toggle_btn.setStyleSheet(button_style)

        self.refresh_btn = QToolButton()
        self.refresh_btn.setIcon(QIcon(":/images/themes/default/mActionRefresh.svg"))
        self.refresh_btn.setIconSize(scale.icon_size(18, 18))
        self.refresh_btn.setToolTip("Refresh Photos")
        self.refresh_btn.setStyleSheet(button_style)

        actions_layout.addWidget(self.map_extent_btn)
        actions_layout.addWidget(self.select_tool_btn)
        actions_layout.addWidget(self.slideshow_btn)
        actions_layout.addWidget(self.filter_toggle_btn)
        actions_layout.addWidget(self.refresh_btn)

        ribbon_layout.addWidget(title_container, 1)
        ribbon_layout.addWidget(actions_container, 0)

        self.main_layout.addWidget(self.ribbon)

    def _setup_photo_grid(self):
        """Initialize the scroll area and photo grid."""
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setFrameShape(QFrame.StyledPanel)
        self.scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scale = get_scale_manager()
        scrollbar_width = scale.dimension(8)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: white;
                border-radius: {STYLE['RADIUS_MD']};
                border: 1px solid {STYLE['BORDER']};
            }}
            QScrollBar:vertical {{
                border: none;
                background: {STYLE['SECONDARY_LIGHT']};
                width: {scrollbar_width}px;
                border-radius: {scrollbar_width // 2}px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {STYLE['BORDER_DARK']};
                border-radius: {scrollbar_width // 2}px;
                min-height: {scale.dimension(30)}px;
            }}
        """)

        self.scroll_widget = QWidget()
        self.scroll_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.thumbnail_layout = QGridLayout(self.scroll_widget)
        self.thumbnail_layout.setContentsMargins(
            STYLE['MARGIN_SM'], STYLE['MARGIN_SM'],
            STYLE['MARGIN_SM'], STYLE['MARGIN_SM']
        )
        self.thumbnail_layout.setSpacing(STYLE['MARGIN_LG'])
        self.thumbnail_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        self.scroll_area.setWidget(self.scroll_widget)
        self.content_layout.addWidget(self.scroll_area)

    def _create_status_bar(self):
        """Create the status bar with controls."""
        scale = get_scale_manager()
        self.status_layout = QHBoxLayout()
        self.status_layout.setContentsMargins(0, scale.spacing(8), 0, 0)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(f"""
            color: {STYLE['TEXT_LIGHT']};
            font-size: {STYLE['FONT_SIZE_SM']};
            font-style: italic;
            padding: 2px 0;
        """)

        buttons_container = QHBoxLayout()
        buttons_container.setSpacing(scale.spacing(8))

        self.load_all_btn = QPushButton("Load All Photos")
        self.load_all_btn.setIcon(QIcon(":/images/themes/default/mActionAllEdits.svg"))
        self.load_all_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {STYLE['SECONDARY']};
                color: white;
                border: none;
                border-radius: {STYLE['RADIUS_MD']};
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {STYLE['TEXT_PRIMARY']};
            }}
        """)
        self.load_all_btn.setHidden(True)

        self.load_more_btn = QPushButton("Load More Photos")
        self.load_more_btn.setIcon(QIcon(":/images/themes/default/mActionAdd.svg"))
        self.load_more_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {STYLE['PRIMARY']};
                color: white;
                border: none;
                border-radius: {STYLE['RADIUS_MD']};
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {STYLE['PRIMARY_DARK']};
            }}
        """)
        self.load_more_btn.setHidden(True)

        self.restore_view_btn = QPushButton("Show All Photos")
        self.restore_view_btn.setIcon(QIcon(":/images/themes/default/mActionShowAllLayers.svg"))
        self.restore_view_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {STYLE['SECONDARY']};
                color: white;
                border: none;
                border-radius: {STYLE['RADIUS_MD']};
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {STYLE['TEXT_PRIMARY']};
            }}
        """)
        self.restore_view_btn.setVisible(False)

        buttons_container.addWidget(self.load_all_btn)
        buttons_container.addWidget(self.load_more_btn)
        buttons_container.addWidget(self.restore_view_btn)

        self.status_layout.addWidget(self.status_label)
        self.status_layout.addStretch()
        self.status_layout.addLayout(buttons_container)

        self.content_layout.addLayout(self.status_layout)

    def _setup_connections(self):
        """Set up signal-slot connections."""
        self.map_extent_btn.clicked.connect(self._toggle_map_extent_filter)
        self.select_tool_btn.clicked.connect(self._toggle_selection_tool)
        self.slideshow_btn.clicked.connect(self._start_slideshow)
        self.filter_toggle_btn.clicked.connect(self._toggle_filter_panel)
        self.refresh_btn.clicked.connect(self.refresh_photos)

        self.filter_panel.filter_changed.connect(self.refresh_photos)
        self.filter_panel.columns_changed.connect(self._update_grid_columns)

        self.layer_combo.currentIndexChanged.connect(self._on_photo_layer_selected)

        self.load_more_btn.clicked.connect(self._load_more_photos)
        self.load_all_btn.clicked.connect(self._load_all_photos)
        self.restore_view_btn.clicked.connect(self._restore_previous_view)

        # Auto-scroll loading
        self.scroll_area.verticalScrollBar().valueChanged.connect(
            self._on_scroll_changed
        )

    def _on_scroll_changed(self, value):
        """Auto-load next batch when near bottom of scroll area."""
        if self._pending_photos:
            return  # a chunked build is already in flight

        scrollbar = self.scroll_area.verticalScrollBar()
        max_val = scrollbar.maximum()
        if max_val <= 0:
            return

        distance_from_bottom = max_val - value
        if distance_from_bottom < AUTO_LOAD_THRESHOLD:
            total = len(self.photo_collection.filtered_photos)
            loaded = min(total, self.batch_size * (self.current_batch + 1))
            if loaded < total:
                self._load_more_photos()

    def _connect_qgis_signals(self):
        """Connect to QGIS project signals."""
        QgsProject.instance().layersAdded.connect(self._on_layers_changed)
        QgsProject.instance().layersRemoved.connect(self._on_layers_changed)

    # =========================================================================
    # Data Loading (Bug fix #10: threaded)
    # =========================================================================

    def _initial_load(self):
        """Perform initial loading of photos."""
        self.progress_bar.show()
        self.status_label.setText("Loading photo layer...")

        if not self._load_photo_layer():
            self.progress_bar.hide()
            self.status_label.setText(
                "No photo layer found (needs a point layer with "
                "PhotoFiles and PhotoPath fields)")
            return

        QTimer.singleShot(100, self._load_photo_data)

    @staticmethod
    def _layer_is_valid(layer) -> bool:
        """True if the layer reference is alive and valid (RuntimeError-safe)."""
        if layer is None:
            return False
        try:
            return layer.isValid()
        except RuntimeError:
            # Underlying C++ object has been deleted
            return False

    def _stop_data_worker(self):
        """Stop and dispose of the current data worker, if any."""
        if self._data_worker:
            if self._data_worker.isRunning():
                self._data_worker.stop()
                self._data_worker.wait(5000)
            self._data_worker.deleteLater()
            self._data_worker = None

    def _persisted_layer_id(self) -> str:
        """Read the photo-layer choice stored in the project file."""
        value, ok = QgsProject.instance().readEntry(
            PHOTO_LAYER_SETTING_SCOPE, PHOTO_LAYER_SETTING_KEY, "")
        return value if ok else ""

    def _persist_layer_choice(self, layer_id: str):
        """Store the photo-layer choice in the project file."""
        QgsProject.instance().writeEntry(
            PHOTO_LAYER_SETTING_SCOPE, PHOTO_LAYER_SETTING_KEY, layer_id)

    def _sync_layer_combo(self, candidates):
        """Repopulate the layer combo (signals blocked) and set row visibility."""
        populate_layer_combo(
            self.layer_combo, candidates,
            select_layer_id=self.photo_layer.id() if self._layer_is_valid(self.photo_layer) else None
        )
        self.layer_select_widget.setVisible(len(candidates) > 1)

    def _load_photo_layer(self) -> bool:
        """Resolve which photo layer to use.

        Priority: project-persisted choice → current layer if still valid →
        auto-match on 'Photo Points' → first candidate.
        """
        candidates = _photo_layer_candidates()
        if not candidates:
            self.photo_layer = None
            self._sync_layer_combo(candidates)
            return False

        candidate_ids = {l.id(): l for l in candidates}

        chosen = None
        persisted = self._persisted_layer_id()
        if persisted in candidate_ids:
            chosen = candidate_ids[persisted]
        elif (self._layer_is_valid(self.photo_layer)
                and self.photo_layer.id() in candidate_ids):
            chosen = self.photo_layer
        else:
            for layer in candidates:
                if layer.name() == 'Photo Points':
                    chosen = layer
                    break
            if chosen is None:
                chosen = candidates[0]

        self.photo_layer = chosen
        self._sync_layer_combo(candidates)
        return True

    def _on_photo_layer_selected(self, index):
        """User picked a different photo layer in the combo."""
        layer = combo_current_layer(self.layer_combo)
        if layer is None:
            return
        if self._layer_is_valid(self.photo_layer) and layer.id() == self.photo_layer.id():
            return

        self.photo_layer = layer
        self._persist_layer_choice(layer.id())
        self._stop_data_worker()
        self.progress_bar.show()
        self.status_label.setText(f"Loading photos from '{layer.name()}'...")
        self._load_photo_data()

    def _load_photo_data(self):
        """
        Bug fix #10: Load photo data via PhotoDataWorker thread.
        No more processEvents() calls.
        """
        if not self.photo_layer:
            self.progress_bar.hide()
            self.status_label.setText("No photo layer available")
            return

        self.photo_collection.clear()
        self.progress_bar.setValue(0)

        self._stop_data_worker()

        self._data_worker = PhotoDataWorker(self.photo_layer)
        self._data_worker.progress.connect(self._on_data_progress)
        self._data_worker.photo_loaded.connect(self._on_photo_data_loaded)
        self._data_worker.data_finished.connect(self._on_data_finished)
        self._data_worker.error.connect(self._on_data_error)
        self._data_worker.start()

    def _on_data_progress(self, processed, total):
        """Update progress bar during data loading."""
        if total > 0:
            progress = int((processed / total) * 100)
            self.progress_bar.setValue(progress)
            self.status_label.setText(f"Loading photos... ({processed}/{total})")

    def _on_photo_data_loaded(self, photo):
        """Called for each photo loaded by the worker thread."""
        self.photo_collection.add_photo(photo)

    def _on_data_finished(self, total_photos):
        """Called when data loading is complete."""
        self.progress_bar.hide()
        self._update_filter_panel()
        self.photo_collection.apply_filters()
        self._display_current_photos(update_status=True)

        total_features = self.photo_layer.featureCount() if self.photo_layer else 0
        self.status_label.setText(
            f"Loaded {len(self.photo_collection.all_photos)} photos from {total_features} features"
        )

    def _on_data_error(self, error_msg):
        """Handle data loading error."""
        self.progress_bar.hide()
        self.status_label.setText(f"Error loading photos: {error_msg}")
        QgsMessageLog.logMessage(
            f"Photo panel: error loading photo data: {error_msg}",
            'Linear Geoscience', Qgis.Warning
        )
        QMessageBox.critical(self, "Error", f"Error loading photos: {error_msg}")

    # =========================================================================
    # Filter & Display
    # =========================================================================

    def _update_filter_panel(self):
        """Update the filter panel with current data."""
        geologists = self.photo_collection.get_sorted_geologists()
        self.filter_panel.set_geologists(geologists)
        total_photos = len(self.photo_collection.all_photos)
        filtered_photos = len(self.photo_collection.filtered_photos)
        self.filter_panel.set_photo_count(filtered_photos, total_photos)

    def _toggle_filter_panel(self):
        """Toggle the filter panel visibility."""
        self.filter_panel.toggle_expanded()

    def _update_grid_columns(self, columns: int):
        """Update the grid layout column count."""
        self.columns = columns
        scroll_value = self.scroll_area.verticalScrollBar().value()
        self._display_current_photos(update_status=False)
        QTimer.singleShot(
            50, lambda: self.scroll_area.verticalScrollBar().setValue(scroll_value)
        )

    def _toggle_selection_tool(self):
        """Toggle the map selection tool."""
        if self.select_tool_btn.isChecked():
            self._activate_selection_tool()
        else:
            self._deactivate_selection_tool()

    def _toggle_map_extent_filter(self):
        """Toggle filtering photos to current map extent (CRS-aware)."""
        if self.map_extent_btn.isChecked():
            canvas = self.iface.mapCanvas()
            extent = canvas.extent()
            if extent.isEmpty():
                self.iface.messageBar().pushMessage(
                    "Map Extent Filter",
                    "Cannot apply map extent filter: Map extent is empty.",
                    level=1, duration=3
                )
                self.map_extent_btn.setChecked(False)
                return
            # Photo points are stored in the layer CRS: transform the canvas
            # extent into it before comparing.
            try:
                dest_crs = canvas.mapSettings().destinationCrs()
                if self._layer_is_valid(self.photo_layer):
                    layer_crs = self.photo_layer.crs()
                    if layer_crs.isValid() and layer_crs != dest_crs:
                        transform = QgsCoordinateTransform(
                            dest_crs, layer_crs, QgsProject.instance()
                        )
                        extent = transform.transformBoundingBox(extent)
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Photo panel: extent CRS transform failed: {e}",
                    'Linear Geoscience', Qgis.Warning
                )
            self.map_extent_filter = extent
            self.iface.messageBar().pushMessage(
                "Map Extent Filter Enabled",
                "Now showing only photos within the current map view.",
                level=0, duration=3
            )
        else:
            self.map_extent_filter = None
            self.iface.messageBar().pushMessage(
                "Map Extent Filter Disabled",
                "Now showing all photos (subject to other filters).",
                level=0, duration=2
            )
        self.refresh_photos()

    def _activate_selection_tool(self):
        """Activate the selection tool."""
        if not self._layer_is_valid(self.photo_layer):
            self.iface.messageBar().pushMessage(
                "Selection Tool Error",
                "Cannot activate selection tool: No valid photo points layer found.",
                level=2, duration=3
            )
            self.select_tool_btn.setChecked(False)
            return

        self.previous_map_tool = self.iface.mapCanvas().mapTool()

        if not hasattr(self, 'selection_handler'):
            self.selection_handler = QgsMapToolIdentifyFeature(self.iface.mapCanvas())
            self.selection_handler.featureIdentified.connect(self._on_feature_identified)

        self.selection_handler.setLayer(self.photo_layer)
        self.iface.mapCanvas().setMapTool(self.selection_handler)
        self.iface.messageBar().pushMessage(
            "Selection Tool Activated",
            "Click on a photo point to view its photos.",
            level=0, duration=2
        )

    def _deactivate_selection_tool(self):
        """Deactivate the selection tool."""
        if hasattr(self, 'previous_map_tool') and self.previous_map_tool:
            self.iface.mapCanvas().setMapTool(self.previous_map_tool)
            self.previous_map_tool = None
        self.select_tool_btn.setChecked(False)
        self.iface.messageBar().pushMessage(
            "Selection Tool Deactivated",
            "Map selection tool turned off.",
            level=0, duration=2
        )

    def _on_feature_identified(self, feature):
        """Handle when a photo point is identified on the map."""
        if not feature.isValid():
            self.iface.messageBar().pushMessage(
                "No Feature",
                "No valid feature identified. Try again.",
                level=1, duration=2
            )
            return
        self._filter_to_feature(feature.id())

    def _filter_to_feature(self, feature_id):
        """Filter photos to show only those for a specific feature."""
        photos = self.photo_collection.get_photos_by_feature(feature_id)
        if not photos:
            self.iface.messageBar().pushMessage(
                "No Photos",
                f"No photos found for feature ID {feature_id}.",
                level=1, duration=3
            )
            return False

        self.status_label.setText(f"Displaying {len(photos)} photos for selected point...")
        self._save_current_view()
        self.photo_collection.filtered_photos = photos
        # Rebuild index map for feature-filtered view
        self.photo_collection._path_index_map = {
            p.path: i for i, p in enumerate(photos)
        }
        self.current_batch = 0
        self._display_current_photos(update_status=False)
        self.filter_panel.set_photo_count(
            len(photos), len(self.photo_collection.all_photos)
        )
        self.restore_view_btn.setVisible(True)

        return True

    def _save_current_view(self):
        """Save the current view state for later restoration."""
        self.saved_view_state = {
            'filtered_photos': self.photo_collection.filtered_photos.copy(),
            'current_batch': self.current_batch,
            'filter_state': self.filter_panel.get_filter_state()
        }

    def _restore_previous_view(self):
        """Restore the previously saved view."""
        if not self.saved_view_state:
            return

        self.restore_view_btn.setVisible(False)
        self.photo_collection.filtered_photos = self.saved_view_state['filtered_photos'].copy()
        # Rebuild index map
        self.photo_collection._path_index_map = {
            p.path: i for i, p in enumerate(self.photo_collection.filtered_photos)
        }
        self.current_batch = self.saved_view_state['current_batch']
        self.filter_panel.set_filter_state(self.saved_view_state['filter_state'])

        self._display_current_photos(update_status=False)
        self.filter_panel.set_photo_count(
            len(self.photo_collection.filtered_photos),
            len(self.photo_collection.all_photos)
        )
        self.status_label.setText("Restored previous view")

    def _load_more_photos(self):
        """Load the next batch of photos (appends, no grid rebuild)."""
        self.current_batch += 1
        self._display_current_photos(update_status=False, append=True)

    def _load_all_photos(self):
        """Load all remaining photos (appended in responsive chunks)."""
        total_photos = len(self.photo_collection.filtered_photos)
        shown = len(self.thumbnails) + len(self._pending_photos)
        remaining_photos = total_photos - shown
        if remaining_photos <= 0:
            return

        self.iface.messageBar().pushMessage(
            "Loading All Photos",
            f"Loading {remaining_photos} remaining photos...",
            level=0, duration=3
        )

        # Widen the batch window to cover the whole collection
        self.current_batch = max(
            self.current_batch, (total_photos - 1) // self.batch_size
        )
        self._display_current_photos(update_status=True, append=True)

    def refresh_photos(self):
        """Reload photo data and refresh the display."""
        self.current_batch = 0
        self.photo_collection.filter_options = self.filter_panel.get_filter_state()
        self.photo_collection.map_extent = self.map_extent_filter or None

        self.photo_collection.apply_filters()
        self._display_current_photos(update_status=True)
        self.filter_panel.set_photo_count(
            len(self.photo_collection.filtered_photos),
            len(self.photo_collection.all_photos)
        )

    def _display_current_photos(self, update_status: bool = True,
                                append: bool = False):
        """
        Display the current batch of photos.

        append=False rebuilds the grid; append=True only creates widgets for
        photos not already shown (Load More / auto-scroll), avoiding the old
        full-grid teardown on every batch.
        """
        if not append:
            self._clear_thumbnails()

        photos = self.photo_collection.filtered_photos
        if not photos:
            self.status_label.setText("No photos found with current filters")
            self.load_more_btn.setHidden(True)
            self.load_all_btn.setHidden(True)
            return

        start_idx = len(self.thumbnails) + len(self._pending_photos) if append else 0
        end_idx = min(len(photos), self.batch_size * (self.current_batch + 1))
        if start_idx >= end_idx:
            self._update_load_buttons()
            return

        batch_data = photos[start_idx:end_idx]

        # Queue thumbnail image loading once for the whole batch
        self.loader_scheduler.schedule_loading(
            [(p.path, p.cache_key) for p in batch_data]
        )

        # Create the widgets in chunks so large batches don't freeze the UI
        self._pending_photos.extend(batch_data)
        self._set_load_buttons_enabled(False)
        self._create_thumbnail_chunk(self._build_generation)

        if update_status:
            filter_state = self.filter_panel.get_filter_state()
            filter_info = ""
            if filter_state['geologist'] != "All Geologists":
                filter_info += f" | Geologist: {filter_state['geologist']}"
            if filter_state['search']:
                filter_info += f" | Search: '{filter_state['search']}'"
            self.status_label.setText(
                f"Showing {end_idx} of {len(photos)} photos | "
                f"Sorted by {filter_state['sort_by']}{filter_info}"
            )

    def _create_thumbnail_chunk(self, generation: int):
        """Create up to THUMB_CHUNK_SIZE thumbnail widgets, then yield."""
        if generation != self._build_generation:
            return  # superseded by a rebuild
        chunk = self._pending_photos[:THUMB_CHUNK_SIZE]
        del self._pending_photos[:len(chunk)]

        for photo in chunk:
            thumbnail = PhotoThumbnail(photo, self.iface, self.scroll_widget)
            # Bug fix #2: connect signal, no lambda override
            thumbnail.clicked.connect(self._on_thumbnail_clicked)

            index = len(self.thumbnails)
            self.thumbnail_layout.addWidget(
                thumbnail, index // self.columns, index % self.columns
            )
            self.thumbnails.append(thumbnail)
            self._thumb_by_path[photo.path] = thumbnail

        self.scroll_widget.adjustSize()

        if self._pending_photos:
            QTimer.singleShot(0, lambda: self._create_thumbnail_chunk(generation))
        else:
            self._set_load_buttons_enabled(True)
            self._update_load_buttons()
            if self.thumbnails and self.focused_index < 0:
                self.focused_index = 0
                self._update_focus()

    def _update_load_buttons(self):
        """Show/hide Load More / Load All based on what's left."""
        total = len(self.photo_collection.filtered_photos)
        shown = len(self.thumbnails) + len(self._pending_photos)
        has_more = shown < total
        self.load_more_btn.setHidden(not has_more)
        self.load_all_btn.setHidden(not has_more)

    def _set_load_buttons_enabled(self, enabled: bool):
        self.load_more_btn.setEnabled(enabled)
        self.load_all_btn.setEnabled(enabled)

    def _update_loading_progress(self, completed: int, total: int):
        """Update the progress bar for thumbnail loading."""
        if total <= 0:
            return
        progress = int((completed / total) * 100)
        if self.progress_bar.isVisible():
            self.progress_bar.setValue(progress)

    def _on_batch_loaded(self):
        """Handle when a batch of thumbnails has been loaded."""
        self.progress_bar.hide()

    def _clear_thumbnails(self):
        """Clear all thumbnails from the layout."""
        # Cancel any in-flight chunked build and drop queued image loads
        self._build_generation += 1
        self._pending_photos.clear()
        self.loader_scheduler.reset()

        while self.thumbnail_layout.count():
            item = self.thumbnail_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        self.thumbnails.clear()
        self._thumb_by_path.clear()
        self.focused_index = -1
        self._set_load_buttons_enabled(True)

    # =========================================================================
    # Photo Viewing
    # =========================================================================

    def _on_thumbnail_clicked(self, photo_path: str):
        """Handle when a thumbnail is clicked. Bug fix #2: receives signal."""
        index = self.photo_collection.find_photo_index(photo_path)
        if index < 0:
            return
        self.current_photo_path = photo_path
        self.current_photo_index = index
        self._view_photo(photo_path)

    def _view_photo(self, photo_path: str):
        """View a photo in the photo viewer."""
        if not photo_path or not os.path.isfile(photo_path):
            return

        # Bug fix #7: reuse viewer, don't destroy on close
        if not self.photo_viewer:
            self.photo_viewer = PhotoViewer()
            self.photo_viewer.prev_requested.connect(self._view_previous_photo)
            self.photo_viewer.next_requested.connect(self._view_next_photo)
            self.photo_viewer.closed.connect(self._on_viewer_closed)

        index = self.photo_collection.find_photo_index(photo_path)
        if index < 0:
            return

        self.current_photo_path = photo_path
        self.current_photo_index = index

        total = len(self.photo_collection.filtered_photos)
        self.photo_viewer.display_photo(photo_path, index, total)

        if self.in_slideshow_mode and self.slideshow_controls:
            self.slideshow_controls.set_position(index, total)

        self.photo_viewer.show()
        self.photo_viewer.raise_()
        self._focus_on_photo(photo_path)

    def _view_previous_photo(self):
        """View the previous photo in the collection."""
        if self.current_photo_index <= 0:
            return
        prev_index = self.current_photo_index - 1
        prev_photo = self.photo_collection.filtered_photos[prev_index]
        self._view_photo(prev_photo.path)

    def _view_next_photo(self):
        """View the next photo (wraps to the start during a slideshow)."""
        total = len(self.photo_collection.filtered_photos)
        if total == 0:
            return
        if self.current_photo_index >= total - 1:
            if not self.in_slideshow_mode:
                return
            next_index = 0
        else:
            next_index = self.current_photo_index + 1
        next_photo = self.photo_collection.filtered_photos[next_index]
        self._view_photo(next_photo.path)

    def _on_viewer_closed(self):
        """
        Bug fix #7: Keep viewer alive (just hidden) so signals stay connected.
        Don't set self.photo_viewer = None.
        """
        pass

    # =========================================================================
    # Slideshow
    # =========================================================================

    def _start_slideshow(self):
        """Start a slideshow of photos (auto-advancing)."""
        if not self.photo_collection.filtered_photos:
            return

        if not self.slideshow_controls:
            self.slideshow_controls = SlideshowControls()
            self.slideshow_controls.prev_requested.connect(self._view_previous_photo)
            self.slideshow_controls.next_requested.connect(self._view_next_photo)
            self.slideshow_controls.view_requested.connect(self._view_current_photo)
            self.slideshow_controls.closed.connect(self._end_slideshow)

        self.slideshow_controls.position_on_screen(self.iface)
        self.slideshow_controls.show()
        self.slideshow_controls.raise_()

        if self.current_photo_index < 0 and self.photo_collection.filtered_photos:
            self.current_photo_index = 0
            self.current_photo_path = self.photo_collection.filtered_photos[0].path

        self.slideshow_controls.set_position(
            self.current_photo_index,
            len(self.photo_collection.filtered_photos)
        )
        self.in_slideshow_mode = True

        # Open the viewer on the current photo and start playback
        if self.current_photo_path:
            self._view_photo(self.current_photo_path)
        self.slideshow_controls.play()

        self.iface.messageBar().pushMessage(
            "Photo Slideshow",
            "Playing automatically. Space pauses, arrow keys navigate, "
            "Escape exits.",
            level=0, duration=4
        )

    def _end_slideshow(self):
        """End the slideshow."""
        if self.slideshow_controls:
            self.slideshow_controls.pause()
            self.slideshow_controls.hide()
        self.in_slideshow_mode = False

    def _view_current_photo(self):
        """View the currently selected photo in external viewer."""
        if not self.current_photo_path:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.current_photo_path))

    # =========================================================================
    # Focus & Navigation
    # =========================================================================

    def _focus_on_photo(self, photo_path: str):
        """Focus on a specific photo in the grid."""
        thumbnail = self._thumb_by_path.get(photo_path)
        if thumbnail is None:
            return
        self.focused_index = self.thumbnails.index(thumbnail)
        self._update_focus()
        self.scroll_area.ensureWidgetVisible(thumbnail)

    def _update_focus(self, ensure_visible: bool = False):
        """
        Bug fix #1: update focus using set_selected() with dynamic property
        instead of brittle stylesheet .replace().

        Highlights only; does not call setFocus() so keyboard focus isn't
        stolen from whatever the user is doing.
        """
        if not self.thumbnails:
            return
        if self.focused_index < 0 or self.focused_index >= len(self.thumbnails):
            self.focused_index = 0

        for i, thumbnail in enumerate(self.thumbnails):
            thumbnail.set_selected(i == self.focused_index)

        if ensure_visible:
            self.scroll_area.ensureWidgetVisible(
                self.thumbnails[self.focused_index]
            )

    def eventFilter(self, obj, event):
        """Handle keyboard navigation events."""
        if event.type() == QEvent.KeyPress and obj == self.main_widget:
            key = event.key()

            if not self.thumbnails:
                return super().eventFilter(obj, event)

            # Slideshow mode
            if self.in_slideshow_mode:
                if key == Qt.Key_Left:
                    self._view_previous_photo()
                    return True
                elif key == Qt.Key_Right:
                    self._view_next_photo()
                    return True
                elif key == Qt.Key_Space:
                    if self.slideshow_controls:
                        self.slideshow_controls.toggle_play()
                    return True
                elif key == Qt.Key_Escape:
                    self._end_slideshow()
                    return True
                elif key in (Qt.Key_Return, Qt.Key_Enter):
                    self._view_current_photo()
                    return True

            # Normal navigation
            if key == Qt.Key_Right:
                self._navigate_next()
                return True
            elif key == Qt.Key_Left:
                self._navigate_previous()
                return True
            elif key == Qt.Key_Up:
                self._navigate_up()
                return True
            elif key == Qt.Key_Down:
                self._navigate_down()
                return True
            elif key in (Qt.Key_Return, Qt.Key_Enter):
                self._open_focused_photo()
                return True
            elif key == Qt.Key_Space:
                self._zoom_to_focused_photo()
                return True
            elif key == Qt.Key_S and event.modifiers() & Qt.ControlModifier:
                self._start_slideshow()
                return True

        return super().eventFilter(obj, event)

    def _navigate_next(self):
        if not self.thumbnails:
            return
        self.focused_index = (self.focused_index + 1) % len(self.thumbnails)
        self._update_focus(ensure_visible=True)

    def _navigate_previous(self):
        if not self.thumbnails:
            return
        self.focused_index = (self.focused_index - 1) % len(self.thumbnails)
        self._update_focus(ensure_visible=True)

    def _navigate_up(self):
        if not self.thumbnails:
            return
        if self.focused_index >= self.columns:
            self.focused_index -= self.columns
            self._update_focus(ensure_visible=True)

    def _navigate_down(self):
        if not self.thumbnails:
            return
        next_index = self.focused_index + self.columns
        if next_index < len(self.thumbnails):
            self.focused_index = next_index
            self._update_focus(ensure_visible=True)

    def _open_focused_photo(self):
        if not self.thumbnails or self.focused_index < 0 or self.focused_index >= len(self.thumbnails):
            return
        thumbnail = self.thumbnails[self.focused_index]
        self._view_photo(thumbnail.photo.path)

    def _zoom_to_focused_photo(self):
        if not self.thumbnails or self.focused_index < 0 or self.focused_index >= len(self.thumbnails):
            return
        thumbnail = self.thumbnails[self.focused_index]
        thumbnail.zoom_to_location()

    # =========================================================================
    # Layer Change Handling
    # =========================================================================

    def _on_layers_changed(self, layers=None):
        """Handle changes to QGIS project layers (RuntimeError-safe)."""
        candidates = _photo_layer_candidates()

        if candidates:
            # Keep the current layer if it survived; otherwise re-resolve
            if (self._layer_is_valid(self.photo_layer)
                    and self.photo_layer.id() in {l.id() for l in candidates}):
                self._sync_layer_combo(candidates)
            else:
                self._load_photo_layer()
                self.status_label.setText("Photo layer changed. Reloading...")
                self._load_photo_data()
        elif self.photo_layer is not None:
            self.photo_layer = None
            self._sync_layer_combo(candidates)
            self.photo_collection.clear()
            self._clear_thumbnails()
            self.filter_panel.set_photo_count(0, 0)
            self.status_label.setText("The photo layer was removed from the project.")

    # =========================================================================
    # Cleanup
    # =========================================================================

    def closeEvent(self, event):
        """
        Handle panel closing.

        Closing a QDockWidget only HIDES it - the same instance is re-shown
        by toggle_photo_panel()/run_photo_panel(). So this must stay
        hide-safe: stop transient work and close child windows, but keep the
        thumbnail loader thread, cache, and project signals alive so the
        panel still works after reopening. Full teardown happens in
        shutdown() (called on plugin unload).
        """
        self._stop_data_worker()

        if self.in_slideshow_mode:
            self._end_slideshow()

        # Bug fix #7: close but don't destroy viewer
        if self.photo_viewer:
            self.photo_viewer.close()

        if self.slideshow_controls:
            self.slideshow_controls.close()

        if self.select_tool_btn.isChecked():
            self._deactivate_selection_tool()

        event.accept()

    def shutdown(self):
        """
        Full teardown: stop all worker threads and disconnect project
        signals. Must be called before the panel is removed for good
        (plugin unload).
        """
        self._stop_data_worker()
        self.loader_scheduler.stop()

        # Bug fix #9: clear per-instance cache
        self._cache.clear()

        if self.photo_viewer:
            self.photo_viewer.shutdown()
            self.photo_viewer = None

        if self.slideshow_controls:
            self.slideshow_controls.close()
            self.slideshow_controls = None

        if self.select_tool_btn.isChecked():
            self._deactivate_selection_tool()

        try:
            QgsProject.instance().layersAdded.disconnect(self._on_layers_changed)
            QgsProject.instance().layersRemoved.disconnect(self._on_layers_changed)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Photo panel: signal disconnect during shutdown failed: {e}",
                'Linear Geoscience', Qgis.Warning
            )


# =============================================================================
# Entry Point
# =============================================================================

def run_photo_panel(iface):
    """
    Create and show the photo panel.

    Args:
        iface: QGIS interface object

    Returns:
        PhotoPanel: The created panel instance, or None on failure
    """
    # Check if panel is already open
    for dock in iface.mainWindow().findChildren(QDockWidget):
        if isinstance(dock, PhotoPanel):
            dock.show()
            dock.raise_()
            dock.activateWindow()
            QTimer.singleShot(100, dock.refresh_photos)
            return dock

    # Check that at least one suitable photo layer exists
    if not _photo_layer_candidates():
        QMessageBox.warning(
            iface.mainWindow(),
            "Missing Photo Layer",
            "No photo layer was found (a point layer with 'PhotoFiles' and "
            "'PhotoPath' fields). Please run the "
            "'Georeference Field Photos' tool first."
        )
        return None

    iface.messageBar().pushMessage(
        "Loading Field Photo Panel",
        "Initializing panel and loading photo data...",
        level=0, duration=5
    )

    panel = PhotoPanel(iface)
    iface.addDockWidget(Qt.RightDockWidgetArea, panel)

    panel.show()
    panel.raise_()
    panel.activateWindow()

    return panel
