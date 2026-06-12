"""
Utility functions for stereonet calculations and data processing.

This module contains helper functions for structural geology calculations,
coordinate transformations, and data processing operations.
"""

import re
import math
import numpy as np

from .data import normalized_classification


def unify_fax_code(code):
    """
    Unify FAX codes to standardized format.
    
    Args:
        code (str): Structure code to process
        
    Returns:
        str: Unified code format
    """
    match = re.match(r'^(FAX\d+)', code, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return code


def classify_code(code):
    """
    Classify a structure code as planar or linear.
    
    Args:
        code (str): Structure code to classify
        
    Returns:
        str or None: 'plane' for planar structures, 'line' for linear structures,
                     None for unrecognized codes
    """
    code = unify_fax_code(code.upper())
    return normalized_classification.get(code, None)


def dip_direction_to_strike(dip_direction):
    """
    Convert dip direction to strike using right-hand rule.
    
    Args:
        dip_direction (float): Dip direction in degrees
        
    Returns:
        float: Strike in degrees (0-360)
    """
    return (dip_direction - 90) % 360


def rake2plunge_bearing(dip_direction, dip, rake_angle):
    """
    Convert a plane (DipDirection, Dip) plus a rake_angle (degrees)
    into the line's (plunge, bearing) so it matches mplstereonet's
    ax.rake() convention. That convention measures 0° rake along
    'strike + 90' (the plane's dip direction).

    We compute strike_rhr = (dip_direction - 90) % 360 internally,
    build the plane's normal & a strike vector, rotate that by rake_angle,
    and convert to plunge/bearing.

    Args:
        dip_direction (float): Dip direction in degrees
        dip (float): Dip angle in degrees
        rake_angle (float): Rake angle in degrees

    Returns:
        tuple: (plunge_deg, bearing_deg) with plunge >= 0
    """
    # RHR strike from dipdir
    strike_rhr = (dip_direction - 90) % 360

    def _plane(strike_deg, dip_deg):
        """Calculate plane normal vector."""
        st = math.radians(strike_deg)
        dp = math.radians(dip_deg)
        return np.array([
            -math.sin(dp) * math.sin(st),
            -math.sin(dp) * math.cos(st),
            math.cos(dp)
        ])

    def _strike_vec(strike_deg):
        """Calculate strike vector."""
        st = math.radians(strike_deg)
        return np.array([math.sin(st), math.cos(st), 0.0])

    def rotate(v, k, alpha_rad):
        """Rotate vector v around axis k by angle alpha_rad."""
        k = k / np.linalg.norm(k)  # unit axis
        return (v * math.cos(alpha_rad)
                + np.cross(k, v) * math.sin(alpha_rad)
                + k * np.dot(k, v) * (1 - math.cos(alpha_rad)))

    def vector_to_line(vec):
        """Convert 3D vector to plunge/bearing."""
        x, y, z = vec
        r = np.linalg.norm(vec)
        if r < 1e-12:
            return (0.0, 0.0)
        plunge = math.degrees(math.asin(z / r))
        bearing = math.degrees(math.atan2(x, y))
        if bearing < 0:
            bearing += 360.0
        return plunge, bearing

    alpha_rad = math.radians(rake_angle)
    plane_normal = _plane(strike_rhr, dip)
    svec = _strike_vec(strike_rhr)

    rake_vec = rotate(svec, plane_normal, alpha_rad)

    plunge, bearing = vector_to_line(rake_vec)
    if plunge < 0:
        plunge = -plunge
        bearing = (bearing + 180) % 360

    return plunge, bearing


def exact_rake2line(strike_deg, dip_deg, rake_deg):
    """
    Compute (plunge, bearing) exactly as mplstereonet.ax.rake(strike, dip, rake, measurement='plane')
    does internally. No offsets or guesses required.

    Args:
        strike_deg (float): Strike in degrees (right-hand-rule convention)
        dip_deg (float): Dip angle in degrees
        rake_deg (float): Rake angle in degrees

    Returns:
        tuple: (plunge_deg, bearing_deg) each in [0..360)
    """
    st_rad = math.radians(strike_deg)
    dp_rad = math.radians(dip_deg)
    rk_rad = math.radians(rake_deg)

    # Calculate plane normal
    nx = -math.sin(dp_rad) * math.sin(st_rad)
    ny = -math.sin(dp_rad) * math.cos(st_rad)
    nz = math.cos(dp_rad)
    normal = np.array([nx, ny, nz], dtype=float)

    # Calculate dip direction vector
    dipdir_x = math.cos(st_rad)
    dipdir_y = -math.sin(st_rad)
    dipdir_z = 0.0
    dipdir_vec = np.array([dipdir_x, dipdir_y, dipdir_z], dtype=float)

    def rotate(v, axis, angle_rad):
        """Rotate vector around axis using Rodrigues' rotation formula."""
        axis = axis / np.linalg.norm(axis)
        c = math.cos(angle_rad)
        s = math.sin(angle_rad)
        one_c = 1.0 - c
        return (v * c
                + np.cross(axis, v) * s
                + axis * (np.dot(axis, v)) * one_c)

    # Rotate dip direction by rake angle around normal
    rake_vec_3d = rotate(dipdir_vec, normal, -rk_rad)

    # Convert to plunge and bearing
    length = np.linalg.norm(rake_vec_3d)
    if length < 1e-12:
        return (0.0, 0.0)
    x, y, z = rake_vec_3d

    plunge_deg = math.degrees(math.asin(z / length))
    bearing_deg = math.degrees(math.atan2(x, y))
    if bearing_deg < 0:
        bearing_deg += 360.0

    # Ensure positive plunge
    if plunge_deg < 0:
        plunge_deg = -plunge_deg
        bearing_deg = (bearing_deg + 180) % 360

    return plunge_deg, bearing_deg