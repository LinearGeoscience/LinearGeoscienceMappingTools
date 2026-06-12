"""
Photo Panel Data Models - PhotoInfo and PhotoCollection.

Bug fix #8: O(1) path lookup via _path_index_map dict rebuilt in apply_filters().
"""

import os
import colorsys
from typing import Dict, List, Set

from qgis.PyQt.QtGui import QColor
from qgis.core import QgsPointXY


class PhotoInfo:
    """Model class for a single photo."""

    def __init__(self, path: str, feature_id: int, point: QgsPointXY,
                 geologist: str = "", comment: str = "", crs=None,
                 layer_id: str = ""):
        self.path = path
        self.filename = os.path.basename(path)
        self.feature_id = feature_id
        self.point = point
        self.geologist = geologist or ""
        self.comment = comment or ""
        self.crs = crs  # QgsCoordinateReferenceSystem of the source layer
        self.layer_id = layer_id  # id of the source photo layer

        # Get file date
        try:
            self.file_date = os.path.getmtime(path)
        except Exception:
            self.file_date = 0

        # Cache key: normalized path + mtime, so replacing a photo on disk
        # invalidates its cached thumbnail (display path stays unmodified).
        self.cache_key = f"{os.path.normcase(os.path.abspath(path))}|{self.file_date}"

        # Generate color based on feature_id for grouping
        seed = feature_id * 73 % 997
        self.feature_color = QColor(
            (seed * 47) % 255,
            (seed * 149) % 255,
            (seed * 211) % 255
        )

        # Generate color based on geologist for visual categorization
        if geologist:
            name_hash = sum(ord(c) for c in geologist)
            hue = (name_hash % 360) / 360.0
            rgb = colorsys.hsv_to_rgb(hue, 0.3, 0.98)
            self.geologist_color = QColor(
                int(rgb[0] * 255),
                int(rgb[1] * 255),
                int(rgb[2] * 255)
            )
        else:
            self.geologist_color = QColor("#f5f5f5")

    def __eq__(self, other):
        if not isinstance(other, PhotoInfo):
            return False
        return self.path == other.path

    def __hash__(self):
        return hash(self.path)


class PhotoCollection:
    """
    Model for the collection of photos with filtering and sorting.

    Bug fix #8: Maintains _path_index_map for O(1) index lookup by path.
    """

    def __init__(self):
        self.all_photos: List[PhotoInfo] = []
        self.filtered_photos: List[PhotoInfo] = []
        self.geologists: Set[str] = set()
        self.map_extent = None
        self.filter_options = {
            'geologist': 'All Geologists',
            'search': '',
            'sort_by': 'Filename',
            'sort_order': 'ascending'
        }
        # Bug fix #8: O(1) index map
        self._path_index_map: Dict[str, int] = {}

    def clear(self) -> None:
        """Clear all photos."""
        self.all_photos.clear()
        self.filtered_photos.clear()
        self.geologists.clear()
        self._path_index_map.clear()

    def add_photo(self, photo: PhotoInfo) -> None:
        """Add a single photo to the collection."""
        self.all_photos.append(photo)
        if photo.geologist:
            self.geologists.add(photo.geologist)

    def apply_filters(self) -> None:
        """Apply current filters to the collection."""
        result = self.all_photos.copy()

        # Apply map extent filter first if active
        if self.map_extent is not None:
            result = [
                p for p in result
                if self.map_extent.contains(p.point)
            ]

        # Apply geologist filter
        geologist = self.filter_options['geologist']
        if geologist != 'All Geologists':
            result = [p for p in result if p.geologist == geologist]

        # Apply search filter
        search = self.filter_options['search'].strip().lower()
        if search:
            result = [
                p for p in result if
                search in p.filename.lower() or
                search in (p.comment.lower() if p.comment else "")
            ]

        # Apply sorting
        sort_by = self.filter_options['sort_by']
        is_ascending = self.filter_options['sort_order'] == 'ascending'

        if sort_by == 'Filename':
            result.sort(key=lambda x: x.filename.lower(), reverse=not is_ascending)
        elif sort_by == 'Geologist':
            result.sort(key=lambda x: (x.geologist or "").lower(), reverse=not is_ascending)
        elif sort_by == 'Date':
            result.sort(key=lambda x: x.file_date, reverse=not is_ascending)
        elif sort_by == 'Feature ID':
            result.sort(key=lambda x: x.feature_id, reverse=not is_ascending)

        self.filtered_photos = result

        # Bug fix #8: rebuild O(1) index map
        self._path_index_map = {
            photo.path: i for i, photo in enumerate(self.filtered_photos)
        }

    def get_photos_by_feature(self, feature_id: int) -> List[PhotoInfo]:
        """Get all photos for a specific feature."""
        return [p for p in self.all_photos if p.feature_id == feature_id]

    def find_photo_index(self, photo_path: str) -> int:
        """Find the index of a photo in the filtered list. O(1) via index map."""
        return self._path_index_map.get(photo_path, -1)

    def get_sorted_geologists(self) -> List[str]:
        """Get alphabetically sorted list of geologists."""
        return sorted(list(self.geologists))
