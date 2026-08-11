"""
Pure-python subset-string logic for the Z (elevation) filter.

No qgis imports here — this module is shared by the desktop controller,
the QField exporter sanitizer, and the unit tests, and its semantics are
mirrored in JavaScript inside z_filter/qfield/zfilter_sidecar.qml.

Subset strings are OGR/GPKG provider SQL: double-quoted field names,
plain numeric literals.
"""

import re

# The elevation attribute added to the four standard mapping layers.
ELEVATION_FIELD = "Elevation"

# Canonical layer names the filter targets (mirror of
# script_adddata/reconcile/migrate.LGS_LAYERS, which imports qgis).
Z_LAYERS = ['1 - FieldNotebook', '2 - Overlay', '3 - Linework', '4 - Basemap']

# Project-entry scope + keys (QgsProject.writeEntry/readEntry).
SCOPE = "LinearGeoscience"
ENTRY_ENABLED = "z_filter/enabled"
ENTRY_LEVEL = "z_filter/level"
ENTRY_TOLERANCE = "z_filter/tolerance"
ENTRY_SHOW_NULL = "z_filter/show_null"
# User-TYPED levels only; data-derived suggestions are recomputed on every
# scan (z_filter/levels.py) and never persisted.
ENTRY_LEVELS = "z_filter/levels"
ENTRY_LAYER_IDS = "z_filter/layer_ids"
ENTRY_LAYER_CHECKED = "z_filter/layer_checked"
ENTRY_ORIG_SUBSET_PREFIX = "z_filter/orig_subset/"

# Project variables mirrored for the QField sidecar plugin.
VAR_ENABLED = "lgs_z_enabled"
VAR_LEVEL = "lgs_z_level"
VAR_TOLERANCE = "lgs_z_tolerance"
VAR_SHOW_NULL = "lgs_z_shownull"
VAR_LEVELS = "lgs_z_levels"
VAR_ORIG_PREFIX = "lgs_z_orig_"

DEFAULT_TOLERANCE = 5.0


def format_number(value):
    """Format a level/tolerance as compact SQL literal text (no trailing .0)."""
    return '%g' % float(value)


def z_clause(level, tol, show_null=True, field=ELEVATION_FIELD):
    """Build the elevation window clause for one level.

    show_null keeps features with no elevation visible — values are entered
    manually, so hiding NULLs would make un-attributed features look lost.
    """
    lo = float(level) - float(tol)
    hi = float(level) + float(tol)
    core = '"%s" >= %s AND "%s" <= %s' % (
        field, format_number(lo), field, format_number(hi))
    if show_null:
        return '("%s" IS NULL OR (%s))' % (field, core)
    return '(%s)' % core


def combine(orig_subset, z_expr):
    """AND the z clause onto a pre-existing subset string (if any)."""
    orig_subset = (orig_subset or "").strip()
    if orig_subset:
        return '(%s) AND %s' % (orig_subset, z_expr)
    return z_expr


def _z_clause_patterns(field):
    f = re.escape(field)
    num = r'-?[0-9.eE+]+'
    core = r'"%s"\s*>=\s*%s\s+AND\s+"%s"\s*<=\s*%s' % (f, num, f, num)
    with_null = r'\(\s*"%s"\s+IS\s+NULL\s+OR\s+\(\s*%s\s*\)\s*\)' % (f, core)
    plain = r'\(\s*%s\s*\)' % core
    return [with_null, plain]


def strip_z_subset(subset, field=ELEVATION_FIELD):
    """Remove a z_clause() previously combined into a subset string.

    Returns the original (pre-filter) subset, '' if the whole string was the
    z clause, or the input unchanged when no z clause is recognized. Used by
    the QField exporter so an active filter is never baked into the exported
    project's datasources.
    """
    if not subset:
        return ""
    text = subset.strip()
    flags = re.IGNORECASE | re.DOTALL
    for pattern in _z_clause_patterns(field):
        match = re.fullmatch(r'\((?P<orig>.*)\)\s+AND\s+' + pattern, text, flags)
        if match:
            return match.group('orig')
        if re.fullmatch(pattern, text, flags):
            return ""
    return subset


def parse_levels(text):
    """Parse a comma-separated persisted level list into sorted unique floats."""
    levels = set()
    for part in (text or "").split(','):
        part = part.strip()
        if not part:
            continue
        try:
            levels.add(float(part))
        except ValueError:
            continue
    return sorted(levels)


def format_levels(levels):
    """Serialize levels for project-entry / project-variable persistence."""
    return ','.join(format_number(v) for v in sorted(set(float(v) for v in levels)))
