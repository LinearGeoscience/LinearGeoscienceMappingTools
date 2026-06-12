"""
Stereonet module for the Linear Geoscience QGIS Plugin.

This module provides comprehensive stereonet plotting functionality for structural
geology data analysis within QGIS.
"""

from .core import StereonetPluginCore
from .data import (
    structure_classification,
    normalized_classification,
    planar_codes,
    linear_codes,
    normalize_structure_type
)
from .utils import (
    unify_fax_code,
    classify_code,
    dip_direction_to_strike,
    rake2plunge_bearing,
    exact_rake2line
)

__version__ = "1.0.0"
__author__ = "Harry West"

__all__ = [
    'StereonetPluginCore',
    'normalize_structure_type',
    'unify_fax_code', 
    'classify_code',
    'dip_direction_to_strike',
    'rake2plunge_bearing',
    'exact_rake2line',
    'structure_classification',
    'normalized_classification',
    'planar_codes',
    'linear_codes'
]