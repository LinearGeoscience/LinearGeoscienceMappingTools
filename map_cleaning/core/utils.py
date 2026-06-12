"""
/***************************************************************************
                     Map Cleaning Toolkit - Utilities
                              -------------------
        begin                : 2025-10-28
        copyright            : (C) 2025 Linear Geoscience

        Based on code from:
        - Spline Plugin by Radim Blazek
        - Polygon Clipper by Giuseppe De Marco
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
import os

# Unified settings namespace for all Map Cleaning Toolkit features
SETTINGS_NAME = "LinearGeosciencePlugin/MapCleaning"

# Geometry area threshold - below this is considered zero area
MIN_AREA_THRESHOLD = 1e-10

# Spline interpolation defaults
# These values match the specification image provided
DEFAULT_TIGHTNESS = 0.5         # Tightness/tension (0.0 = loose, 1.0 = tight)
DEFAULT_TOLERANCE = 0.1         # Simplification tolerance (Douglas-Peucker)
DEFAULT_MAX_SEGMENTS = 200      # Maximum segments per spline section


def icon_path(icon_filename):
    """
    Return the full path to an icon file in the plugin directory.

    Args:
        icon_filename (str): The filename of the icon (e.g., 'icon.png')

    Returns:
        str: Full path to the icon file
    """
    plugin_dir = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(plugin_dir, icon_filename)


def get_icon_from_subdir(subdir, icon_filename):
    """
    Return the full path to an icon file in a subdirectory.

    Args:
        subdir (str): Subdirectory name (e.g., 'icons')
        icon_filename (str): The filename of the icon

    Returns:
        str: Full path to the icon file
    """
    plugin_dir = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(plugin_dir, subdir, icon_filename)
