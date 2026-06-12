# -*- coding: utf-8 -*-
"""Map Cleaning toolkit subpackage for the Linear Geoscience plugin.

Embedded from the standalone MapCleaningToolkit plugin (June 2026).
Provides spline reshape/digitise map tools, the Map Cleaning dock panel
(clipping, smart clip, overlap/sliver finders, geometry fixer, spline
settings) and the lines/polygons-to-splines Processing algorithms.
"""

from .map_cleaning_toolkit import MapCleaningToolkit

__all__ = ["MapCleaningToolkit"]
