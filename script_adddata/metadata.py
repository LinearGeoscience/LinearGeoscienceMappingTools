#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Metadata management and UUID tracking for duplicate detection.

This module provides:
- JSON-based UUID tracking (persists even when features are deleted)
- Metadata table management in GeoPackage
- Batch tracking for data additions
- Temporal overlap detection
"""

import os
import json
from datetime import datetime, timezone, date, time
from typing import Dict, List, Set, Optional, Tuple

# Try to import PyQt types for type checking
try:
    from qgis.PyQt.QtCore import QDateTime, QDate
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False

# Try to import QGIS logging
try:
    from qgis.core import QgsMessageLog, Qgis
    _LOG_INFO = Qgis.Info
    _LOG_WARNING = Qgis.Warning
    QGIS_LOGGING_AVAILABLE = True
except ImportError:
    _LOG_INFO = 0
    _LOG_WARNING = 1
    QGIS_LOGGING_AVAILABLE = False


def _log_message(message, level=None):
    """Log a message using QgsMessageLog if available, otherwise pass silently."""
    if QGIS_LOGGING_AVAILABLE:
        if level is None:
            level = _LOG_INFO
        QgsMessageLog.logMessage(message, 'Linear Geoscience', level)


def _ensure_python_datetime(value):
    """
    Ensure a value is a Python datetime object.

    This is a safety function to handle cases where QDateTime or other
    date types might be passed instead of Python datetime.

    Args:
        value: A datetime-like object

    Returns:
        Python datetime object or None
    """
    if value is None:
        return None

    # Already a Python datetime
    if isinstance(value, datetime):
        return value

    # Python date (no time)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time.min)

    # PyQt5 QDateTime
    if PYQT_AVAILABLE and isinstance(value, QDateTime):
        if value.isNull() or not value.isValid():
            return None
        return value.toPyDateTime()

    # PyQt5 QDate
    if PYQT_AVAILABLE and isinstance(value, QDate):
        if value.isNull() or not value.isValid():
            return None
        return datetime.combine(value.toPyDate(), time.min)

    # Try conversion methods if they exist
    if hasattr(value, 'toPyDateTime'):
        try:
            return value.toPyDateTime()
        except Exception:
            pass

    if hasattr(value, 'toPyDate'):
        try:
            return datetime.combine(value.toPyDate(), time.min)
        except Exception:
            pass

    # String parsing
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass

    return None


class UUIDTracker:
    """
    Tracks all UUIDs that have ever been added to a master GeoPackage.

    This solves the problem where users delete/merge features before the next
    data addition, causing the UUID-based duplicate detection to fail.

    The tracker maintains a JSON file in an 'adddata_metadata' folder
    within the master GeoPackage's directory:
    - All UUIDs ever added
    - Timestamp when each UUID was first added
    - Layer information
    - Batch information

    Example:
        If master is at: C:/data/master.gpkg
        Tracker will be: C:/data/adddata_metadata/master_uuid_tracking.json
    """

    def __init__(self, master_gpkg_path: str):
        """
        Initialize UUID tracker.

        Args:
            master_gpkg_path: Path to the master GeoPackage
        """
        self.master_gpkg_path = master_gpkg_path
        self.json_path = self._get_json_path()
        self.data = self._load_or_create()

    def _get_json_path(self) -> str:
        """
        Get path to the UUID tracking JSON file.
        Creates a metadata folder if it doesn't exist.
        """
        # Get the directory and filename of the master GeoPackage
        master_dir = os.path.dirname(self.master_gpkg_path)
        master_filename = os.path.splitext(os.path.basename(self.master_gpkg_path))[0]

        # Create metadata folder
        metadata_folder = os.path.join(master_dir, "adddata_metadata")
        if not os.path.exists(metadata_folder):
            try:
                os.makedirs(metadata_folder)
                _log_message(f"Created metadata folder: {metadata_folder}")
            except OSError as e:
                _log_message(f"Warning: Could not create metadata folder: {e}", _LOG_WARNING)
                # Fallback to same directory as master
                return os.path.join(master_dir, f"{master_filename}_uuid_tracking.json")

        # Return path to JSON file inside metadata folder
        return os.path.join(metadata_folder, f"{master_filename}_uuid_tracking.json")

    def _load_or_create(self) -> dict:
        """Load existing JSON file or create new structure"""
        if os.path.exists(self.json_path):
            try:
                with open(self.json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Validate structure
                    if 'version' not in data:
                        data['version'] = '1.0'
                    if 'layers' not in data:
                        data['layers'] = {}
                    return data
            except (json.JSONDecodeError, IOError) as e:
                _log_message(f"Warning: Could not load UUID tracking file: {e}", _LOG_WARNING)
                _log_message("Creating new tracking file")

        # Create new structure
        return {
            'version': '1.0',
            'created': datetime.now(timezone.utc).isoformat(),
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'master_gpkg': os.path.basename(self.master_gpkg_path),
            'layers': {}  # {layer_name: {uuid: {timestamp, batch_id, date_field_value}}}
        }

    def save(self):
        """Save tracking data to JSON file"""
        self.data['last_updated'] = datetime.now(timezone.utc).isoformat()
        try:
            with open(self.json_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            _log_message(f"Error saving UUID tracking file: {e}", _LOG_WARNING)
            raise

    def get_layer_uuids(self, layer_name: str) -> Set[str]:
        """
        Get all UUIDs tracked for a layer.

        Args:
            layer_name: Layer name

        Returns:
            Set of UUID strings
        """
        if layer_name not in self.data['layers']:
            return set()
        return set(self.data['layers'][layer_name].keys())

    def add_uuids(self, layer_name: str, uuids: List[str], batch_id: str,
                  date_values: Optional[Dict[str, str]] = None):
        """
        Add UUIDs to the tracker.

        Args:
            layer_name: Layer name
            uuids: List of UUID strings to add
            batch_id: Batch ID for this addition
            date_values: Optional dictionary of {uuid: date_field_value}
        """
        if layer_name not in self.data['layers']:
            self.data['layers'][layer_name] = {}

        timestamp = datetime.now(timezone.utc).isoformat()

        for uuid in uuids:
            if uuid not in self.data['layers'][layer_name]:
                self.data['layers'][layer_name][uuid] = {
                    'added': timestamp,
                    'batch_id': batch_id,
                    'date_value': date_values.get(uuid) if date_values else None
                }

        self.save()

    def is_duplicate(self, layer_name: str, uuid: str) -> bool:
        """
        Check if a UUID is already tracked (is a duplicate).

        Args:
            layer_name: Layer name
            uuid: UUID string

        Returns:
            True if UUID exists in tracker
        """
        return uuid in self.get_layer_uuids(layer_name)

    def get_uuid_info(self, layer_name: str, uuid: str) -> Optional[dict]:
        """
        Get information about a tracked UUID.

        Args:
            layer_name: Layer name
            uuid: UUID string

        Returns:
            Dictionary with UUID info or None
        """
        if layer_name in self.data['layers']:
            return self.data['layers'][layer_name].get(uuid)
        return None

    def get_statistics(self, layer_name: Optional[str] = None) -> dict:
        """
        Get statistics about tracked UUIDs.

        Args:
            layer_name: Optional layer name to filter statistics

        Returns:
            Dictionary with statistics
        """
        if layer_name:
            if layer_name not in self.data['layers']:
                return {'total_uuids': 0, 'batches': 0,
                        'earliest_addition': None, 'latest_addition': None}

            layer_data = self.data['layers'][layer_name]
            return {
                'total_uuids': len(layer_data),
                'batches': len(set(info['batch_id'] for info in layer_data.values())),
                'earliest_addition': min((info['added'] for info in layer_data.values()), default=None),
                'latest_addition': max((info['added'] for info in layer_data.values()), default=None)
            }
        else:
            total_uuids = sum(len(layer_data) for layer_data in self.data['layers'].values())
            all_batches = set()
            for layer_data in self.data['layers'].values():
                all_batches.update(info['batch_id'] for info in layer_data.values())

            return {
                'total_layers': len(self.data['layers']),
                'total_uuids': total_uuids,
                'total_batches': len(all_batches)
            }

    def analyze_temporal_overlap(self, layer_name: str, new_date_range: Tuple[datetime, datetime],
                                  tolerance_hours: int = 24) -> dict:
        """
        Analyze if new data overlaps with existing data temporally.

        Args:
            layer_name: Layer name
            new_date_range: Tuple of (start_datetime, end_datetime) for new data
            tolerance_hours: Hours of tolerance for overlap detection

        Returns:
            Dictionary with overlap analysis
        """
        if layer_name not in self.data['layers']:
            return {'has_overlap': False, 'reason': 'no_existing_data'}

        layer_data = self.data['layers'][layer_name]
        overlaps = []

        # Ensure dates are Python datetime objects (handles QDateTime, QDate, etc.)
        new_start = _ensure_python_datetime(new_date_range[0])
        new_end = _ensure_python_datetime(new_date_range[1])

        if not new_start or not new_end:
            return {'has_overlap': False, 'reason': 'invalid_date_range'}

        for uuid, info in layer_data.items():
            if info.get('date_value'):
                try:
                    existing_date = datetime.fromisoformat(info['date_value'])

                    # Check if existing date falls within new range or is very close
                    if new_start <= existing_date <= new_end:
                        overlaps.append({
                            'uuid': uuid,
                            'existing_date': info['date_value'],
                            'batch_id': info['batch_id'],
                            'overlap_type': 'within_range'
                        })
                    elif abs((existing_date - new_start).total_seconds()) < tolerance_hours * 3600:
                        overlaps.append({
                            'uuid': uuid,
                            'existing_date': info['date_value'],
                            'batch_id': info['batch_id'],
                            'overlap_type': 'near_start'
                        })
                    elif abs((existing_date - new_end).total_seconds()) < tolerance_hours * 3600:
                        overlaps.append({
                            'uuid': uuid,
                            'existing_date': info['date_value'],
                            'batch_id': info['batch_id'],
                            'overlap_type': 'near_end'
                        })
                except (ValueError, TypeError):
                    continue

        return {
            'has_overlap': len(overlaps) > 0,
            'overlap_count': len(overlaps),
            'overlaps': overlaps[:10],  # Return first 10 examples
            'new_date_range': (new_start.isoformat(), new_end.isoformat())
        }


class MetadataManager:
    """
    Manages metadata using JSON files in the adddata_metadata folder.

    Creates and maintains:
    - batch_history.json: Track all data addition batches

    Example:
        If master is at: C:/data/master.gpkg
        History will be: C:/data/adddata_metadata/master_batch_history.json
    """

    def __init__(self, master_gpkg_path: str):
        """
        Initialize metadata manager.

        Args:
            master_gpkg_path: Path to the master GeoPackage
        """
        self.master_gpkg_path = master_gpkg_path
        self.history_json_path = self._get_history_json_path()
        self.history_data = self._load_or_create_history()

    def _get_metadata_folder(self) -> str:
        """Get or create the metadata folder"""
        master_dir = os.path.dirname(self.master_gpkg_path)
        metadata_folder = os.path.join(master_dir, "adddata_metadata")

        if not os.path.exists(metadata_folder):
            try:
                os.makedirs(metadata_folder)
                _log_message(f"Created metadata folder: {metadata_folder}")
            except OSError as e:
                _log_message(f"Warning: Could not create metadata folder: {e}", _LOG_WARNING)
                # Fallback to master directory
                return master_dir

        return metadata_folder

    def _get_history_json_path(self) -> str:
        """Get path to the batch history JSON file"""
        master_filename = os.path.splitext(os.path.basename(self.master_gpkg_path))[0]
        metadata_folder = self._get_metadata_folder()
        return os.path.join(metadata_folder, f"{master_filename}_batch_history.json")

    def _load_or_create_history(self) -> dict:
        """Load existing history JSON or create new structure"""
        if os.path.exists(self.history_json_path):
            try:
                with open(self.history_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'version' not in data:
                        data['version'] = '1.0'
                    if 'batches' not in data:
                        data['batches'] = []
                    return data
            except (json.JSONDecodeError, IOError) as e:
                _log_message(f"Warning: Could not load batch history file: {e}", _LOG_WARNING)
                _log_message("Creating new batch history file")

        # Create new structure
        return {
            'version': '1.0',
            'created': datetime.now(timezone.utc).isoformat(),
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'master_gpkg': os.path.basename(self.master_gpkg_path),
            'batches': []
        }

    def _save_history(self):
        """Save history data to JSON file"""
        self.history_data['last_updated'] = datetime.now(timezone.utc).isoformat()
        try:
            with open(self.history_json_path, 'w', encoding='utf-8') as f:
                json.dump(self.history_data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            _log_message(f"Error saving batch history file: {e}", _LOG_WARNING)
            raise

    def log_batch(self, batch_id: str, layer_name: str, records_added: int,
                  records_duplicates: int, timezone_used: str = "UTC",
                  user_notes: str = "", date_filter: str = "",
                  recoding_template: str = ""):
        """
        Log a data addition batch.

        Args:
            batch_id: Unique batch identifier
            layer_name: Layer name
            records_added: Number of records added
            records_duplicates: Number of duplicate records skipped
            timezone_used: Timezone used for this batch
            user_notes: Optional user notes
            date_filter: Date filter description
            recoding_template: Template name used
        """
        batch_entry = {
            'batch_id': batch_id,
            'layer_name': layer_name,
            'timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'timezone_used': timezone_used,
            'records_added': records_added,
            'records_duplicates': records_duplicates,
            'user_notes': user_notes,
            'date_filter_used': date_filter,
            'recoding_template': recoding_template
        }

        self.history_data['batches'].append(batch_entry)
        self._save_history()

    def get_batch_history(self, layer_name: Optional[str] = None) -> List[dict]:
        """
        Get batch history.

        Args:
            layer_name: Optional layer name to filter

        Returns:
            List of batch dictionaries (sorted by timestamp, newest first)
        """
        batches = self.history_data.get('batches', [])

        if layer_name:
            batches = [b for b in batches if b.get('layer_name') == layer_name]

        # Sort by timestamp descending (newest first)
        batches.sort(key=lambda x: x.get('timestamp_utc', ''), reverse=True)

        return batches

    def get_layer_statistics(self, layer_name: str) -> dict:
        """
        Get statistics for a layer from batch history.

        Args:
            layer_name: Layer name

        Returns:
            Dictionary with statistics
        """
        batches = self.get_batch_history(layer_name)

        if not batches:
            return {
                'total_batches': 0,
                'total_records_added': 0,
                'first_addition': None,
                'last_addition': None
            }

        return {
            'total_batches': len(batches),
            'total_records_added': sum(b['records_added'] for b in batches),
            'first_addition': batches[-1]['timestamp_utc'] if batches else None,
            'last_addition': batches[0]['timestamp_utc'] if batches else None
        }
