#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Working out which column identifies a feature across GeoPackages.

All that is left of the old append tool's utility module. Two other features
depend on it and neither is going anywhere: hardcode_data fills empty UUIDs
before a reconcile, and the reconcile engine needs the same answer to match
features between a checkout and its master. The recoding classes, fuzzy value
matching and the date-filter constants left with the tool that owned them —
see data_import/.

No qgis import: hardcode_data and reconcile both reach this from contexts where
that matters, and nothing here needs it.
"""

import re

# Bundled fuzzywuzzy, for field names that are close but not exact.
try:
    from ..vendor.fuzzywuzzy import fuzz
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
