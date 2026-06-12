"""
Photo Panel Loader - Background thumbnail loading with EXIF support.

Bug fixes:
  #6:  QWaitCondition instead of busy-wait msleep(50)
  #11: EXIF orientation reading (minimal JPEG parser, no external deps)
  #12: Use QImage on background thread, emit QImage signal, convert to QPixmap on main thread
"""

import os
import struct
import time
from typing import List, Optional, Tuple

from qgis.PyQt.QtCore import (
    Qt, QThread, pyqtSignal, QMutex, QWaitCondition, QRectF
)
from qgis.PyQt.QtGui import (
    QImage, QPainter, QPainterPath, QTransform
)
from qgis.core import QgsMessageLog, Qgis

from .constants import get_scale_manager, get_default_thumbnail_size


# =============================================================================
# EXIF Orientation Helper (Bug fix #11)
# =============================================================================

def read_exif_orientation(filepath: str) -> int:
    """
    Read EXIF orientation tag from a JPEG file without external dependencies.

    Returns orientation value 1-8, or 1 (normal) on failure.
    """
    try:
        with open(filepath, 'rb') as f:
            # Check JPEG SOI marker
            if f.read(2) != b'\xff\xd8':
                return 1

            while True:
                marker = f.read(2)
                if len(marker) < 2:
                    return 1

                if marker[0] != 0xFF:
                    return 1

                # Skip non-APP markers
                if marker[1] == 0xE1:  # APP1 (EXIF)
                    break
                elif marker[1] in (0xD9, 0xDA):  # EOI or SOS
                    return 1
                else:
                    # Skip this segment
                    size_bytes = f.read(2)
                    if len(size_bytes) < 2:
                        return 1
                    size = struct.unpack('>H', size_bytes)[0]
                    f.seek(size - 2, 1)
                    continue

            # Read APP1 segment
            size_bytes = f.read(2)
            if len(size_bytes) < 2:
                return 1

            # Check "Exif\0\0" header
            exif_header = f.read(6)
            if exif_header[:4] != b'Exif':
                return 1

            # TIFF header starts here
            tiff_start = f.tell()
            tiff_header = f.read(8)
            if len(tiff_header) < 8:
                return 1

            # Determine byte order
            if tiff_header[:2] == b'II':
                endian = '<'
            elif tiff_header[:2] == b'MM':
                endian = '>'
            else:
                return 1

            # Read IFD0 offset
            ifd_offset = struct.unpack(endian + 'I', tiff_header[4:8])[0]
            f.seek(tiff_start + ifd_offset)

            # Read number of IFD entries
            num_entries_bytes = f.read(2)
            if len(num_entries_bytes) < 2:
                return 1
            num_entries = struct.unpack(endian + 'H', num_entries_bytes)[0]

            # Search for orientation tag (0x0112)
            for _ in range(num_entries):
                entry = f.read(12)
                if len(entry) < 12:
                    return 1
                tag = struct.unpack(endian + 'H', entry[:2])[0]
                if tag == 0x0112:
                    orientation = struct.unpack(endian + 'H', entry[8:10])[0]
                    if 1 <= orientation <= 8:
                        return orientation
                    return 1

    except Exception:
        pass
    return 1


def get_exif_transform(orientation: int) -> Optional[QTransform]:
    """
    Get a QTransform for the given EXIF orientation value.
    Returns None if no transformation needed (orientation 1).
    """
    if orientation <= 1:
        return None

    t = QTransform()
    if orientation == 2:
        t.scale(-1, 1)
    elif orientation == 3:
        t.rotate(180)
    elif orientation == 4:
        t.scale(1, -1)
    elif orientation == 5:
        t.rotate(90)
        t.scale(-1, 1)
    elif orientation == 6:
        t.rotate(90)
    elif orientation == 7:
        t.rotate(-90)
        t.scale(-1, 1)
    elif orientation == 8:
        t.rotate(-90)

    return t


# =============================================================================
# Workers
# =============================================================================

class PhotoLoadRequest:
    """Data structure for photo loading requests."""

    def __init__(self, path: str, key: str, priority: int = 0):
        self.path = path
        self.key = key  # cache key (normalized path + mtime)
        self.priority = priority
        self.timestamp = time.time()


class BackgroundLoader(QThread):
    """
    Thread for loading photos in the background with priority queue.

    Bug fix #6:  Uses QWaitCondition instead of busy-wait msleep(50).
    Bug fix #12: Loads QImage on background thread, emits QImage signal.
    """
    progress = pyqtSignal(int, int)  # completed, total
    finished_batch = pyqtSignal()
    # Bug fix #12: emit QImage instead of QPixmap
    thumbnail_ready = pyqtSignal(str, str, QImage)  # path, cache key, image
    thumbnail_error = pyqtSignal(str, str)          # path, error message

    def __init__(self, cache):
        super().__init__()
        self.cache = cache  # Bug fix #9: injected per-instance cache
        self.queue: List[PhotoLoadRequest] = []
        self.pending_count = 0
        self.completed_count = 0
        self.total_count = 0
        self.is_running = True
        self.mutex = QMutex()
        # Bug fix #6: wait condition replaces busy-wait
        self._wait_condition = QWaitCondition()

    def add_batch(self, items: List[Tuple[str, str]], priority: int = 0) -> None:
        """Add a batch of (path, cache_key) pairs to the queue."""
        self.mutex.lock()
        for path, key in items:
            self.queue.append(PhotoLoadRequest(path, key, priority))
        self.queue.sort(key=lambda x: (-x.priority, x.timestamp))
        self.pending_count += len(items)
        self.total_count += len(items)
        self.mutex.unlock()
        # Bug fix #6: wake thread
        self._wait_condition.wakeOne()

    def stop(self) -> None:
        """Stop the loader thread."""
        self.mutex.lock()
        self.is_running = False
        self.mutex.unlock()
        self._wait_condition.wakeAll()
        self.wait()

    def run(self) -> None:
        """Thread main method - process queue items."""
        while True:
            self.mutex.lock()
            if not self.is_running:
                self.mutex.unlock()
                break

            if not self.queue:
                # Bug fix #6: sleep on wait condition instead of msleep(50)
                self._wait_condition.wait(self.mutex)
                self.mutex.unlock()
                continue

            request = self.queue.pop(0)
            self.mutex.unlock()

            # Process the request
            self._load_single(request)

            # Update progress
            self.mutex.lock()
            self.completed_count += 1
            self.pending_count -= 1
            completed = self.completed_count
            total = self.total_count
            queue_empty = len(self.queue) == 0
            self.mutex.unlock()

            self.progress.emit(completed, total)

            if queue_empty:
                self.finished_batch.emit()

    def _load_single(self, request: PhotoLoadRequest) -> None:
        """Load a single thumbnail (runs on background thread)."""
        path = request.path
        key = request.key

        # Check cache first (cache has its own mutex)
        cached = self.cache.get(key)
        if cached is not None:
            # Already cached as QPixmap; emit a dummy QImage signal
            # The panel will find it in cache when it processes the signal
            self.thumbnail_ready.emit(path, key, QImage())
            return

        try:
            size = get_default_thumbnail_size()
            width, height = size

            # Bug fix #12: load as QImage (thread-safe)
            image = QImage(path)
            if image.isNull():
                self.thumbnail_error.emit(path, "Failed to load image")
                return

            # Bug fix #11: apply EXIF orientation
            ext = os.path.splitext(path)[1].lower()
            if ext in ('.jpg', '.jpeg'):
                orientation = read_exif_orientation(path)
                transform = get_exif_transform(orientation)
                if transform is not None:
                    image = image.transformed(transform, Qt.SmoothTransformation)

            # Scale
            scaled_image = image.scaled(
                width, height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )

            # Apply rounded corners
            scale = get_scale_manager()
            final_image = self._apply_rounded_corners(scaled_image, scale.dimension(6))

            self.thumbnail_ready.emit(path, key, final_image)

        except Exception as e:
            self.thumbnail_error.emit(path, str(e))

    @staticmethod
    def _apply_rounded_corners(image: QImage, radius: int) -> QImage:
        """Apply rounded corners to a QImage."""
        if image.isNull():
            return image

        try:
            target = QImage(image.size(), QImage.Format_ARGB32_Premultiplied)
            target.fill(Qt.transparent)

            painter = QPainter(target)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)

            path = QPainterPath()
            path.addRoundedRect(
                QRectF(0, 0, image.width(), image.height()),
                radius, radius
            )

            painter.setClipPath(path)
            painter.drawImage(0, 0, image)
            painter.end()

            return target
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Photo panel: rounded-corner rendering failed: {e}",
                'Linear Geoscience', Qgis.Warning
            )
            return image

    def clear_queue(self) -> None:
        """Clear all pending requests."""
        self.mutex.lock()
        self.queue.clear()
        self.pending_count = 0
        self.mutex.unlock()

    def reset_counters(self) -> None:
        """Reset progress counters."""
        self.mutex.lock()
        self.completed_count = 0
        self.total_count = 0
        self.mutex.unlock()


class LoadingScheduler:
    """Schedules and prioritizes photo loading tasks."""

    def __init__(self, cache):
        self.cache = cache
        self.loader = BackgroundLoader(cache)
        self.loader.start()

    def schedule_loading(self, items: List[Tuple[str, str]], priority: int = 0) -> None:
        """Schedule a batch of (path, cache_key) pairs for loading."""
        self.loader.add_batch(items, priority)

    def reset(self) -> None:
        """Drop pending requests and reset progress counters (on grid rebuild)."""
        self.loader.clear_queue()
        self.loader.reset_counters()

    def stop(self) -> None:
        """Stop the scheduler and its loader thread."""
        self.loader.stop()


class FullImageLoader(QThread):
    """
    Background loader for full-resolution photos shown in the viewer.

    Holds at most one pending request: rapid next/prev navigation simply
    replaces the pending path, and a request id lets the viewer discard
    results that arrive late.
    """

    image_ready = pyqtSignal(int, str, QImage)  # request id, path, image
    image_error = pyqtSignal(int, str, str)     # request id, path, error

    def __init__(self):
        super().__init__()
        self._mutex = QMutex()
        self._wait_condition = QWaitCondition()
        self._pending: Optional[Tuple[int, str]] = None
        self._is_running = True

    def request(self, request_id: int, path: str) -> None:
        """Queue a photo for loading, replacing any pending request."""
        self._mutex.lock()
        self._pending = (request_id, path)
        self._mutex.unlock()
        self._wait_condition.wakeOne()
        if not self.isRunning():
            self.start()

    def stop(self) -> None:
        """Stop the loader thread."""
        self._mutex.lock()
        self._is_running = False
        self._mutex.unlock()
        self._wait_condition.wakeAll()
        self.wait(3000)

    def run(self) -> None:
        while True:
            self._mutex.lock()
            if not self._is_running:
                self._mutex.unlock()
                break
            if self._pending is None:
                self._wait_condition.wait(self._mutex)
                self._mutex.unlock()
                continue
            request_id, path = self._pending
            self._pending = None
            self._mutex.unlock()

            try:
                image = QImage(path)
                if image.isNull():
                    self.image_error.emit(request_id, path, "Failed to load image")
                    continue

                ext = os.path.splitext(path)[1].lower()
                if ext in ('.jpg', '.jpeg'):
                    orientation = read_exif_orientation(path)
                    transform = get_exif_transform(orientation)
                    if transform is not None:
                        image = image.transformed(transform, Qt.SmoothTransformation)

                self.image_ready.emit(request_id, path, image)
            except Exception as e:
                self.image_error.emit(request_id, path, str(e))
