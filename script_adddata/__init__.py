#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Enhanced GeoPackage Append Tool with Advanced Recoding
------------------------------------------------------
A modular PyQGIS tool for appending data from source GeoPackages
to master GeoPackages with advanced recoding and duplicate detection.

Features:
- Layer and field name mapping
- Value recoding with templates
- UUID-based duplicate detection with JSON tracking
- Temporal overlap warnings
- Enhanced preview with comprehensive statistics
- Timeline visualization of data additions
- Comprehensive timezone support
"""

# Import core utilities (always available)
from .utils import LayerRecoding, ValueRecoding
from .metadata import UUIDTracker, MetadataManager

# Import main window
from .main import GeoPackageAppendTool, run_gpkg_append_tool_dialog

__version__ = "3.1.0"

__all__ = [
    'GeoPackageAppendTool',
    'run_gpkg_append_tool_dialog',
    'LayerRecoding',
    'ValueRecoding',
    'UUIDTracker',
    'MetadataManager'
]
