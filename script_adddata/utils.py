#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Utility functions, constants, and data classes for the GeoPackage Append Tool.
"""

import re
import json
from datetime import datetime, date, time
from qgis.PyQt.QtCore import QVariant, QDateTime, QDate, QTime
from qgis.core import QgsFeatureRequest

# Try to import fuzzywuzzy for better UUID field detection
try:
    from fuzzywuzzy import fuzz
    FUZZY_MATCHING_AVAILABLE = True
except ImportError:
    FUZZY_MATCHING_AVAILABLE = False

# UUID field detection with priority groups (matched case-insensitively).
# Deliberately excludes fid/id/objectid: those are sequential per-file integers,
# not unique across team GeoPackages, and would silently corrupt duplicate
# detection if used as the UUID field.
UUID_FIELD_PATTERNS = [
    [1, r"^uuid$"],
    [1, r"^guid$"],
    [1, r"^globalid$"],
    [2, r"^uniqueid$"],
    [2, r"^unique_id$"],
]

UUID_EXACT_MATCHES = ["uuid", "guid"]

# Per-file sequential ids - must never be picked as the UUID field, not even
# by fuzzy matching at a low threshold (e.g. ratio("id", "uuid") is 67)
NEVER_UUID_FIELDS = {"fid", "id", "objectid"}

# Fields to automatically exclude
EXCLUDED_FIELDS = ["fid", "FID"]

# No UUID field option - for layers without UUID fields
NO_UUID_FIELD = "__NO_UUID__"
NO_UUID_DISPLAY = "<No UUID - Add All Features>"

# Date filter type constants
FILTER_TYPE_AFTER = "after_date_time"
FILTER_TYPE_BEFORE = "before_date_time"
FILTER_TYPE_BETWEEN = "between_dates"


class LayerRecoding:
    """Stores complete recoding configuration for a layer"""

    def __init__(self):
        self.target_layer = None  # Target master layer name
        self.field_mappings = {}  # {source_field: target_field}
        self.value_recodings = {}  # {field: ValueRecoding}
        self.preserve_original = {}  # {field: new_field_name}
        self.default_values = {}  # {target_field: default_value} - NEW
        self.template_name = None  # Template name if loaded from template - NEW

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'target_layer': self.target_layer,
            'field_mappings': self.field_mappings,
            'value_recodings': {
                k: v.to_dict() for k, v in self.value_recodings.items()
            },
            'preserve_original': self.preserve_original,
            'default_values': self.default_values,
            'template_name': self.template_name
        }

    @classmethod
    def from_dict(cls, data):
        """Create from dictionary"""
        recoding = cls()
        recoding.target_layer = data.get('target_layer')
        recoding.field_mappings = data.get('field_mappings', {})
        recoding.preserve_original = data.get('preserve_original', {})
        recoding.default_values = data.get('default_values', {})
        recoding.template_name = data.get('template_name')

        # Reconstruct value recodings
        value_recodings_data = data.get('value_recodings', {})
        for field, vr_data in value_recodings_data.items():
            recoding.value_recodings[field] = ValueRecoding.from_dict(vr_data)

        return recoding


class ValueRecoding:
    """Stores value recoding configuration for a field"""

    def __init__(self):
        self.lookup_layer = None
        self.value_field = None
        self.manual_mappings = {}  # Direct value mappings {old_value: new_value}
        self.preserve_original_field = None
        self.default_value = None  # Default value for unmapped values - NEW

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'lookup_layer': self.lookup_layer,
            'value_field': self.value_field,
            'manual_mappings': self.manual_mappings,
            'preserve_original_field': self.preserve_original_field,
            'default_value': self.default_value
        }

    @classmethod
    def from_dict(cls, data):
        """Create from dictionary"""
        vr = cls()
        vr.lookup_layer = data.get('lookup_layer')
        vr.value_field = data.get('value_field')
        vr.manual_mappings = data.get('manual_mappings', {})
        vr.preserve_original_field = data.get('preserve_original_field')
        vr.default_value = data.get('default_value')
        return vr


def find_matching_field(field_names, target_field):
    """
    Find a matching field name with case-insensitive comparison.

    Args:
        field_names: List of field names to search
        target_field: Field name to find

    Returns:
        Matching field name or None
    """
    if not target_field:
        return None
    if target_field in field_names:
        return target_field
    for field in field_names:
        if field.lower() == target_field.lower():
            return field
    return None


def detect_uuid_field(field_names, fuzzy_threshold=75):
    """
    Detect the most likely UUID field from a list of field names.

    Args:
        field_names: List of field names
        fuzzy_threshold: Threshold for fuzzy matching (0-100)

    Returns:
        Detected UUID field name or None
    """
    # Check exact matches first
    for pattern_priority, pattern in UUID_FIELD_PATTERNS:
        for field_name in field_names:
            if re.match(pattern, field_name, re.IGNORECASE):
                return field_name

    # Try fuzzy matching if available
    if FUZZY_MATCHING_AVAILABLE:
        best_match = None
        best_score = 0

        for field_name in field_names:
            if field_name.lower() in NEVER_UUID_FIELDS:
                continue
            for target in UUID_EXACT_MATCHES:
                score = fuzz.ratio(field_name.lower(), target.lower())
                if score > best_score and score >= fuzzy_threshold:
                    best_score = score
                    best_match = field_name

        if best_match:
            return best_match

    return None


def is_date_field(field):
    """
    Check if a field is a date/datetime field.

    Args:
        field: QgsField object

    Returns:
        True if field is a date/datetime field
    """
    if hasattr(field, 'type'):
        field_type = field.type()
        if field_type in [QVariant.Date, QVariant.DateTime]:
            return True
    if hasattr(field, 'typeName'):
        type_name = field.typeName().lower()
        if any(date_type in type_name for date_type in ['date', 'time', 'timestamp']):
            return True
    return False


def to_python_datetime(value):
    """
    Convert any date/datetime type to Python datetime.

    Handles:
    - Python datetime (returned as-is)
    - Python date (converted to datetime at midnight)
    - PyQt5 QDateTime (converted via toPyDateTime)
    - PyQt5 QDate (converted to datetime at midnight)
    - String (parsed via fromisoformat or common formats)
    - None/NULL (returns None)

    Args:
        value: Date value in any supported format

    Returns:
        Python datetime object or None if conversion fails
    """
    if value is None or (hasattr(value, 'isNull') and value.isNull()):
        return None

    # Already a Python datetime
    if isinstance(value, datetime):
        return value

    # Python date (no time component)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time.min)

    # PyQt5 QDateTime
    if isinstance(value, QDateTime):
        if value.isNull() or not value.isValid():
            return None
        return value.toPyDateTime()

    # PyQt5 QDate
    if isinstance(value, QDate):
        if value.isNull() or not value.isValid():
            return None
        return datetime.combine(value.toPyDate(), time.min)

    # String - try various parsing methods
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None

        # Try ISO format first
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass

        # Try common formats
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y/%m/%d %H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
            "%d-%m-%Y %H:%M:%S",
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue

        return None

    # Unknown type - try to get a Python datetime if method exists
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

    return None


def fuzzy_match_field_names(source_fields, target_fields, threshold=75):
    """
    Intelligently match source field names to target field names using fuzzy matching.

    Args:
        source_fields: List of source field names
        target_fields: List of target field names
        threshold: Fuzzy match threshold (0-100)

    Returns:
        Dictionary of {source_field: target_field} mappings
    """
    if not source_fields or not target_fields:
        return {}

    if not FUZZY_MATCHING_AVAILABLE:
        # Fallback to exact matches only
        mappings = {}
        for source_field in source_fields:
            if source_field in target_fields:
                mappings[source_field] = source_field
        return mappings

    mappings = {}
    used_targets = set()

    # Sort source fields to prioritize exact or near-exact matches
    sorted_sources = sorted(source_fields, key=lambda x: (
        -max([fuzz.ratio(x.lower(), t.lower()) for t in target_fields])
    ))

    for source_field in sorted_sources:
        best_match = None
        best_score = 0

        for target_field in target_fields:
            if target_field in used_targets:
                continue

            # Calculate fuzzy score
            score = fuzz.ratio(source_field.lower(), target_field.lower())

            # Bonus for exact match ignoring case
            if source_field.lower() == target_field.lower():
                score = 100

            if score > best_score and score >= threshold:
                best_score = score
                best_match = target_field

        if best_match:
            mappings[source_field] = best_match
            used_targets.add(best_match)

    return mappings


def fuzzy_match_values(source_values, target_values, threshold=70):
    """
    Match source values to closest target values using fuzzy matching.

    Args:
        source_values: List of source value strings
        target_values: List of valid target value strings
        threshold: Minimum fuzzy match score (0-100)

    Returns:
        Dictionary of {source_value: best_matching_target_value}
    """
    if not FUZZY_MATCHING_AVAILABLE:
        # Exact match fallback (case-insensitive)
        target_lower = {t.lower(): t for t in target_values}
        return {s: target_lower[s.lower()] for s in source_values if s.lower() in target_lower}

    mappings = {}
    for source in source_values:
        best_match, best_score = None, 0
        for target in target_values:
            score = fuzz.ratio(str(source).lower(), str(target).lower())
            if score > best_score and score >= threshold:
                best_score = score
                best_match = target
        if best_match:
            mappings[source] = best_match
    return mappings


def analyze_unique_values(layer, field_name, max_unique=1000):
    """
    Analyze unique values in a field.

    Args:
        layer: QgsVectorLayer
        field_name: Field name to analyze
        max_unique: Maximum number of unique values to track

    Returns:
        Dictionary with value counts: {value: count}
    """
    value_counts = {}

    field_idx = layer.fields().lookupField(field_name)
    if field_idx < 0:
        return value_counts

    # Only fetch the one attribute, no geometry - much faster on large layers
    request = (QgsFeatureRequest()
               .setFlags(QgsFeatureRequest.NoGeometry)
               .setSubsetOfAttributes([field_idx]))

    for feature in layer.getFeatures(request):
        value = feature[field_idx]
        value_str = str(value) if value is not None else '<NULL>'

        if value_str in value_counts:
            value_counts[value_str] += 1
        else:
            if len(value_counts) >= max_unique:
                # Too many unique values, stop counting
                value_counts['<TOO_MANY_UNIQUE_VALUES>'] = value_counts.get('<TOO_MANY_UNIQUE_VALUES>', 0) + 1
            else:
                value_counts[value_str] = 1

    return value_counts


def validate_field_type_compatibility(source_field, target_field):
    """
    Check if two fields have compatible types for mapping.

    Args:
        source_field: QgsField object (source)
        target_field: QgsField object (target)

    Returns:
        Tuple of (is_compatible: bool, warning_message: str or None)
    """
    if source_field.typeName() == target_field.typeName():
        return (True, None)

    source_type = source_field.type()
    target_type = target_field.type()

    # String fields can accept most types
    if target_type == QVariant.String:
        return (True, None)

    # Numeric types
    numeric_types = [QVariant.Int, QVariant.LongLong, QVariant.Double]
    if source_type in numeric_types and target_type in numeric_types:
        if source_type == QVariant.Double and target_type in [QVariant.Int, QVariant.LongLong]:
            return (True, "Warning: Mapping from Double to Integer may lose precision")
        return (True, None)

    # Date/time types
    if source_type == QVariant.Date and target_type == QVariant.DateTime:
        return (True, None)

    # Types don't match
    return (False, f"Type mismatch: {source_field.typeName()} → {target_field.typeName()}")


def format_record_count(count):
    """Format a record count with thousand separators"""
    return f"{count:,}"


def truncate_text(text, max_length=50):
    """Truncate text with ellipsis"""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."
