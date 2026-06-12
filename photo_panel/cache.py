"""
Photo Panel Thumbnail Cache - OrderedDict-based LRU cache.

Bug fix #9: Per-instance cache (created by PhotoPanel, injected into loader)
instead of a global module-level singleton.
"""

from collections import OrderedDict
from typing import Optional

from qgis.PyQt.QtCore import QMutex
from qgis.PyQt.QtGui import QPixmap

from .constants import MAX_CACHE_SIZE, CACHE_CLEANUP_THRESHOLD


class ThumbnailCache:
    """
    Efficient cache for photo thumbnails with LRU eviction.

    Uses OrderedDict for O(1) access-order tracking instead of a
    separate list (original used list.remove which is O(n)).
    """

    def __init__(self, max_size: int = MAX_CACHE_SIZE):
        self.max_size = max_size
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._mutex = QMutex()

    def get(self, key: str) -> Optional[QPixmap]:
        """Get a thumbnail from cache, updating access time."""
        self._mutex.lock()
        try:
            if key in self._cache:
                # Move to end (most recently used)
                self._cache.move_to_end(key)
                return self._cache[key]
            return None
        finally:
            self._mutex.unlock()

    def put(self, key: str, thumbnail: QPixmap) -> None:
        """Add a thumbnail to cache with cleanup if needed."""
        if thumbnail is None or thumbnail.isNull():
            return

        self._mutex.lock()
        try:
            if key in self._cache:
                # Update existing and move to end
                self._cache[key] = thumbnail
                self._cache.move_to_end(key)
            else:
                # Check if we need to clean up
                if len(self._cache) >= int(self.max_size * CACHE_CLEANUP_THRESHOLD):
                    self._cleanup()
                self._cache[key] = thumbnail
        finally:
            self._mutex.unlock()

    def remove(self, key: str) -> None:
        """Remove a specific item from cache."""
        self._mutex.lock()
        try:
            self._cache.pop(key, None)
        finally:
            self._mutex.unlock()

    def clear(self) -> None:
        """Clear the entire cache."""
        self._mutex.lock()
        try:
            self._cache.clear()
        finally:
            self._mutex.unlock()

    def _cleanup(self) -> None:
        """Remove least recently used items to bring cache below threshold."""
        target_size = int(self.max_size * 0.7)
        items_to_remove = max(0, len(self._cache) - target_size)
        for _ in range(items_to_remove):
            if not self._cache:
                break
            # Pop first item (least recently used)
            self._cache.popitem(last=False)

    def __len__(self) -> int:
        return len(self._cache)
