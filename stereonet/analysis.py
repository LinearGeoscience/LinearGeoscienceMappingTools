"""
Scope grouping and analysis-overlay drawing for the stereonet plot.

Pure functions: numpy + mplstereonet only, no Qt/QGIS imports, so the
analysis math is testable outside QGIS. Each draw_* function renders one
analysis overlay (best fit / contours / mean) for one AnalysisGroup onto
a mplstereonet axes, reproducing the legend labels, markers and
annotations of the original inline implementation.
"""

import os
import sys
from collections import namedtuple

# Add vendor directory to path for mplstereonet (core.py normally does this
# first, but keep this module importable on its own)
vendor_dir = os.path.join(os.path.dirname(__file__), '..', 'vendor')
if vendor_dir not in sys.path:
    sys.path.insert(0, vendor_dir)

import numpy as np
import mplstereonet


# scope:    'combined' | 'per_dataset' | 'per_code'
# name:     None (combined) | dataset name | code string
# annotate: True only for combined groups (annotations are drawn only in
#           "All Combined" scope, matching the original behaviour)
AnalysisGroup = namedtuple(
    "AnalysisGroup", "scope name plunges bearings color annotate"
)

# Indices into the per-category analysis flag tuples (best fit, contours, mean)
FLAG_BEST_FIT = 0
FLAG_CONTOURS = 1
FLAG_MEAN = 2

_ALL_ON = (True, True, True)


def _flatten(values):
    """Concatenate a sequence of scalars and/or small numpy arrays into a 1-D array.

    Plane pole plunges/bearings come from mplstereonet.pole2plunge_bearing and
    are 1-element arrays; line values are plain floats. This normalises both.
    """
    return np.concatenate([np.atleast_1d(v) for v in values])


def _scalar(value):
    """Coerce possible 1-element arrays returned by mplstereonet to floats."""
    if hasattr(value, '__len__'):
        return float(value[0])
    return value


def iter_analysis_groups(scope, per_category, analysis_flags, flag_index,
                         dataset_configs, combined_color):
    """Yield AnalysisGroup objects for one analysis kind.

    Args:
        scope: 'combined', 'per_dataset' or 'per_code'.
        per_category: insertion-ordered dict
            {(code_str, dataset_idx): {"plunges": [...], "bearings": [...], "color": c}}
            built in plotted order (per-code groups keep the first-seen
            category's colour, matching the original implementation).
        analysis_flags: {(code_str, dataset_idx): (best_fit, contours, mean)};
            missing keys default to all-enabled.
        flag_index: FLAG_BEST_FIT / FLAG_CONTOURS / FLAG_MEAN.
        dataset_configs: list of {"enabled": bool, "name": str, "color": str}
            (only consulted for 'per_dataset' scope).
        combined_color: colour for the single combined group
            ('red' for planes, 'green' for lines).
    """
    enabled = {
        key: cat for key, cat in per_category.items()
        if analysis_flags.get(key, _ALL_ON)[flag_index]
    }

    if scope == 'per_dataset':
        for ds_idx in (0, 1):
            if not dataset_configs[ds_idx]["enabled"]:
                continue
            plunges, bearings = [], []
            for (code_str, cat_ds_idx), cat in enabled.items():
                if cat_ds_idx != ds_idx:
                    continue
                plunges.extend(cat["plunges"])
                bearings.extend(cat["bearings"])
            if not plunges:
                continue
            yield AnalysisGroup('per_dataset', dataset_configs[ds_idx]["name"],
                                plunges, bearings,
                                dataset_configs[ds_idx]["color"], False)

    elif scope == 'per_code':
        # Merge categories by code across datasets, keeping first-seen order
        # and the first-seen category's colour
        by_code = {}
        for (code_str, _ds_idx), cat in enabled.items():
            if code_str not in by_code:
                by_code[code_str] = {"plunges": [], "bearings": [],
                                     "color": cat["color"]}
            by_code[code_str]["plunges"].extend(cat["plunges"])
            by_code[code_str]["bearings"].extend(cat["bearings"])
        for code_str, merged in by_code.items():
            if not merged["plunges"]:
                continue
            yield AnalysisGroup('per_code', code_str,
                                merged["plunges"], merged["bearings"],
                                merged["color"], False)

    else:  # 'combined'
        plunges, bearings = [], []
        for cat in enabled.values():
            plunges.extend(cat["plunges"])
            bearings.extend(cat["bearings"])
        if plunges:
            yield AnalysisGroup('combined', None, plunges, bearings,
                                combined_color, True)


def draw_best_fit_plane(ax, group, stats=None):
    """Best-fit (girdle) plane through plane poles: great circle + pole marker.

    If ``stats`` (a list) is given, annotation text is appended to it as
    (text, color) instead of being drawn on the axes, so the caller can
    render all stat lines off-plot in one block.
    """
    fit_strike, fit_dip = mplstereonet.fit_girdle(
        group.plunges, group.bearings, measurement='lines'  # Poles stored as lines
    )
    fit_strike = _scalar(fit_strike)
    fit_dip = _scalar(fit_dip)
    # Dashed so the best-fit plane is distinguishable from the (solid) mean
    # plane; matches the dashed convention of draw_best_fit_line
    ax.plane(fit_strike, fit_dip, color=group.color, lw=2, linestyle='--')
    # Large, bold pi-axis marker so the best-fit pole stands out from data points
    ax.pole(fit_strike, fit_dip, marker='x', color=group.color, markersize=12,
            markeredgewidth=3)

    pole_plunge, pole_bearing = mplstereonet.pole2plunge_bearing(fit_strike, fit_dip)
    pole_plunge = _scalar(pole_plunge)
    pole_bearing = _scalar(pole_bearing)

    if group.scope == 'per_dataset':
        ax.plot([], [], color=group.color, linestyle='--',
                label=f'Best Fit Plane ({group.name})')
    elif group.scope == 'per_code':
        ax.plot([], [], color=group.color, linestyle='--',
                label=f'Best Fit ({group.name})')
    else:
        ax.plot([], [], color=group.color, linestyle='--', label='Best Fit Plane & Pole')

    if stats is not None:
        # Stat line for every group; named in per-dataset/per-code scopes
        if group.name:
            text = f"Best Fit π-axis ({group.name}): Plg={pole_plunge:.1f}°, Trd={pole_bearing:.1f}°"
        else:
            text = f"Best Fit Plane π-axis: Plg={pole_plunge:.1f}°, Trd={pole_bearing:.1f}°"
        stats.append((text, group.color))
    elif group.annotate:
        ax.annotate(
            f"Best Fit Plane π-axis: Plg={pole_plunge:.1f}°, Trd={pole_bearing:.1f}°",
            xy=(0.95, 0.10),
            xycoords='axes fraction',
            ha='right', va='bottom', fontsize=8, color=group.color
        )


def draw_plane_contours(ax, group):
    """Density contours of plane poles."""
    if group.scope == 'combined':
        ax.density_contour(
            group.plunges, group.bearings,
            measurement='lines',  # Poles are stored as lines
            sigma=1.5,
            cmap='Blues',
            filled=False,
            label="Plane Pole Contours"
        )
    else:
        # Grouped contours need a minimum population (combined intentionally
        # has no guard, preserving the original behaviour)
        if len(group.plunges) < 3:
            return
        if group.scope == 'per_dataset':
            label = f"Plane Contours ({group.name})"
        else:
            label = f"Contours ({group.name})"
        ax.density_contour(group.plunges, group.bearings, measurement='lines',
                           sigma=1.5, colors=[group.color], filled=False,
                           label=label)


def draw_mean_plane(ax, group, mean_plane_type, stats=None):
    """Mean vector of plane poles, shown as a pole point or as a great circle.

    ``stats``: optional list collecting (text, color) instead of drawing
    the annotation on the axes (see draw_best_fit_plane).
    """
    flat_plunges = _flatten(group.plunges)
    flat_bearings = _flatten(group.bearings)
    (mean_plg, mean_brg), r_val = mplstereonet.find_mean_vector(
        flat_plunges, flat_bearings, measurement='lines'
    )

    if group.scope == 'per_dataset':
        plane_label = f'Mean Plane ({group.name})'
        pole_label = f'Mean Pole ({group.name})'
    elif group.scope == 'per_code':
        plane_label = f'Mean Plane ({group.name})'
        pole_label = f'Mean Pole ({group.name})'
    else:
        plane_label = 'Mean Plane'
        pole_label = 'Mean Pole'

    if mean_plane_type == "Plane":
        mean_strike, mean_dip = mplstereonet.plunge_bearing2pole(mean_plg, mean_brg)
        mean_strike = _scalar(mean_strike)
        mean_dip = _scalar(mean_dip)
        # Report in dip / dip-direction convention: plunge_bearing2pole
        # returns RHR strike, so dip direction is 90° clockwise of it
        mean_dipdir = (mean_strike + 90) % 360
        ax.plane(mean_strike, mean_dip, color=group.color, lw=2, linestyle='-')
        ax.pole(mean_strike, mean_dip, marker='o', color=group.color, markersize=8)
        ax.plot([], [], '-', color=group.color, lw=2, label=plane_label)
        if stats is not None:
            name_part = f" ({group.name})" if group.name else ""
            stats.append((
                f"Mean Plane{name_part}: Dip={mean_dip:.1f}°, DipDir={mean_dipdir:.1f}° (R={r_val:.3f})",
                group.color))
        elif group.annotate:
            ax.annotate(
                f"Mean Plane: Dip={mean_dip:.1f}°, DipDir={mean_dipdir:.1f}° (R={r_val:.3f})",
                xy=(0.95, 0.05),
                xycoords='axes fraction',
                ha='right', va='bottom', fontsize=8, color=group.color
            )
    else:  # Pole mode
        ax.line([mean_plg], [mean_brg], marker='o', color=group.color, markersize=8)
        ax.plot([], [], 'o', color=group.color, markersize=8, label=pole_label)
        if stats is not None:
            name_part = f" ({group.name})" if group.name else ""
            stats.append((
                f"Mean Pole{name_part}: Plg={mean_plg:.1f}°, Trd={mean_brg:.1f}° (R={r_val:.3f})",
                group.color))
        elif group.annotate:
            ax.annotate(
                f"Mean Pole: Plg={mean_plg:.1f}°, Trd={mean_brg:.1f}° (R={r_val:.3f})",
                xy=(0.95, 0.05),
                xycoords='axes fraction',
                ha='right', va='bottom', fontsize=8, color=group.color
            )


def draw_best_fit_line(ax, group, stats=None):
    """Best-fit girdle through lines: dashed great circle + axis marker.

    ``stats``: optional list collecting (text, color) instead of drawing
    the annotation on the axes (see draw_best_fit_plane).
    """
    fit_strike, fit_dip = mplstereonet.fit_girdle(
        group.plunges, group.bearings, measurement='lines'
    )
    fit_strike = _scalar(fit_strike)
    fit_dip = _scalar(fit_dip)
    ax.plane(fit_strike, fit_dip, color=group.color, lw=2, linestyle='--')

    # Calculate the axis (pole to the plane)
    axis_plunge, axis_bearing = mplstereonet.pole2plunge_bearing(fit_strike, fit_dip)
    axis_plunge = _scalar(axis_plunge)
    axis_bearing = _scalar(axis_bearing)
    ax.line([axis_plunge], [axis_bearing], marker='x', color=group.color, markersize=8)

    if group.scope == 'per_dataset' or group.scope == 'per_code':
        ax.plot([], [], color=group.color, linestyle='--',
                label=f'Best Fit Line ({group.name})')
    else:
        ax.plot([], [], color=group.color, linestyle='--', label='Best Fit Line Plane')

    if stats is not None:
        # Stat line for every group; named in per-dataset/per-code scopes
        name_part = f" ({group.name})" if group.name else ""
        stats.append((
            f"Best Fit Line Axis{name_part}: Plg={axis_plunge:.1f}°, Trd={axis_bearing:.1f}°",
            group.color))
    elif group.annotate:
        ax.annotate(
            f"Best Fit Line Axis: Plg={axis_plunge:.1f}°, Trd={axis_bearing:.1f}°",
            xy=(0.05, 0.90),
            xycoords='axes fraction',
            ha='left', va='top', fontsize=8, color=group.color
        )


def draw_line_contours(ax, group):
    """Density contours of linear measurements."""
    if group.scope == 'combined':
        ax.density_contour(
            group.plunges, group.bearings,
            measurement='lines',
            sigma=1.5,
            cmap='Greens',
            filled=False,
            label="Line Contours"
        )
    else:
        if len(group.plunges) < 3:
            return
        if group.scope == 'per_dataset':
            label = f"Line Contours ({group.name})"
        else:
            label = f"Contours ({group.name})"
        ax.density_contour(group.plunges, group.bearings, measurement='lines',
                           sigma=1.5, colors=[group.color], filled=False,
                           label=label)


def draw_mean_line(ax, group, stats=None):
    """Mean vector of linear measurements, shown as a square marker.

    ``stats``: optional list collecting (text, color) instead of drawing
    the annotation on the axes (see draw_best_fit_plane).
    """
    flat_plunges = _flatten(group.plunges)
    flat_bearings = _flatten(group.bearings)
    (mean_plg, mean_brg), r_val = mplstereonet.find_mean_vector(
        flat_plunges, flat_bearings, measurement='lines'
    )
    ax.line([mean_plg], [mean_brg], marker='s', color=group.color, markersize=8)

    if group.scope == 'per_dataset' or group.scope == 'per_code':
        ax.plot([], [], 's', color=group.color, markersize=8,
                label=f'Mean Line ({group.name})')
    else:
        ax.plot([], [], 's', color=group.color, markersize=8, label='Mean Line')

    if stats is not None:
        # Stat line for every group; named in per-dataset/per-code scopes
        name_part = f" ({group.name})" if group.name else ""
        stats.append((
            f"Mean Line{name_part}: Plg={mean_plg:.1f}°, Trd={mean_brg:.1f}° (R={r_val:.3f})",
            group.color))
    elif group.annotate:
        ax.annotate(
            f"Mean Line: Plg={mean_plg:.1f}°, Trd={mean_brg:.1f}° (R={r_val:.3f})",
            xy=(0.05, 0.85),
            xycoords='axes fraction',
            ha='left', va='top', fontsize=8, color=group.color
        )
