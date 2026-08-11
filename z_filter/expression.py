"""
Pure-python subset-string logic for the Z (elevation) filter.

No qgis imports here — this module is shared by the desktop controller,
the QField exporter sanitizer, and the unit tests, and its semantics are
mirrored in JavaScript inside z_filter/qfield/lgs_companion.qml.

Subset strings are OGR/GPKG provider SQL: double-quoted field names,
plain numeric literals.
"""

import json
import re

# The elevation attribute added to the four standard mapping layers.
ELEVATION_FIELD = "Elevation"

# Range-mode fields for line/polygon layers whose features span elevations
# (ramp/decline strings). ≤ 9 chars so shapefiles keep the exact names.
Z_MIN_FIELD = "Z_Min"
Z_MAX_FIELD = "Z_Max"

# Range features flatter than this (m) vote their midpoint into the level
# scan histogram; wider spans (ramps) abstain so mid-ramp values never
# pollute the suggestions.
FLAT_SPAN = 2.0

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
# Slot-combo selections for the dock. ENTRY_LAYER_IDS used to double as
# this, but _persist_state overwrites it with the applied set — old projects
# without slot_ids fall back to it on restore.
ENTRY_SLOT_IDS = "z_filter/slot_ids"
# Auto-detected extra layers (survey points, floor strings) as JSON:
# {"v":1,"layers":[{"id","name","mode","field"|"field_min"+"field_max",
#  "source","checked"}, ...]}
ENTRY_EXTRA_LAYERS = "z_filter/extra_layers"
ENTRY_ORIG_SUBSET_PREFIX = "z_filter/orig_subset/"

# Project variables mirrored for the QField sidecar plugin.
VAR_ENABLED = "lgs_z_enabled"
VAR_LEVEL = "lgs_z_level"
VAR_TOLERANCE = "lgs_z_tolerance"
VAR_SHOW_NULL = "lgs_z_shownull"
VAR_LEVELS = "lgs_z_levels"
VAR_ORIG_PREFIX = "lgs_z_orig_"
# Same JSON as ENTRY_EXTRA_LAYERS; QField resolves entries by layer name.
VAR_EXTRA = "lgs_z_extra"

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


def z_range_clause(level, tol, show_null=True,
                   field_min=Z_MIN_FIELD, field_max=Z_MAX_FIELD):
    """Window clause for features carrying a Z range (ramp/decline strings).

    Overlap semantics: a feature shows on every level its [min, max] touches.
    Only field_max is NULL-checked — materialization writes both fields or
    neither, and with field_min == field_max this degenerates byte-for-byte
    into z_clause(), so one strip pattern covers both modes.
    """
    lo = float(level) - float(tol)
    hi = float(level) + float(tol)
    core = '"%s" >= %s AND "%s" <= %s' % (
        field_max, format_number(lo), field_min, format_number(hi))
    if show_null:
        return '("%s" IS NULL OR (%s))' % (field_max, core)
    return '(%s)' % core


def clause_for_spec(spec, level, tol, show_null=True):
    """Build the clause for a per-layer spec dict.

    spec: {'mode': 'single', 'field': f}
        | {'mode': 'range', 'field_min': a, 'field_max': b}
    """
    if spec.get('mode') == 'range':
        return z_range_clause(level, tol, show_null,
                              field_min=spec['field_min'],
                              field_max=spec['field_max'])
    return z_clause(level, tol, show_null,
                    field=spec.get('field', ELEVATION_FIELD))


def spec_field_names(spec):
    """The attribute name(s) a layer spec filters on."""
    if spec.get('mode') == 'range':
        return [spec['field_min'], spec['field_max']]
    return [spec.get('field', ELEVATION_FIELD)]


def combine(orig_subset, z_expr):
    """AND the z clause onto a pre-existing subset string (if any)."""
    orig_subset = (orig_subset or "").strip()
    if orig_subset:
        return '(%s) AND %s' % (orig_subset, z_expr)
    return z_expr


def _z_clause_patterns(field, field_max=None):
    """Regexes matching z_clause() (field alone) or z_range_clause() output.

    field/field_max mirror the clause builders: the range core compares
    field_max against lo and field (the min field) against hi, and the NULL
    guard is on field_max. With field_max=None both roles collapse onto
    field, which is exactly the single-field clause.
    """
    f_min = re.escape(field)
    f_max = re.escape(field_max if field_max is not None else field)
    # Must cover every %g spelling, including negative exponents (1e-05).
    num = r'-?[0-9.]+(?:[eE][+-]?[0-9]+)?'
    core = r'"%s"\s*>=\s*%s\s+AND\s+"%s"\s*<=\s*%s' % (f_max, num, f_min, num)
    with_null = r'\(\s*"%s"\s+IS\s+NULL\s+OR\s+\(\s*%s\s*\)\s*\)' % (f_max, core)
    plain = r'\(\s*%s\s*\)' % core
    return [with_null, plain]


def _try_strip(text, patterns):
    """Strip one recognized clause from text. Returns new text or None."""
    flags = re.IGNORECASE | re.DOTALL
    for pattern in patterns:
        match = re.fullmatch(r'\((?P<orig>.*)\)\s+AND\s+' + pattern, text, flags)
        if match:
            return match.group('orig')
        if re.fullmatch(pattern, text, flags):
            return ""
    return None


def strip_z_subset(subset, field=ELEVATION_FIELD):
    """Remove a z_clause() previously combined into a subset string.

    Returns the original (pre-filter) subset, '' if the whole string was the
    z clause, or the input unchanged when no z clause is recognized. Used by
    the QField exporter so an active filter is never baked into the exported
    project's datasources.
    """
    if not subset:
        return ""
    stripped = _try_strip(subset.strip(), _z_clause_patterns(field))
    return subset if stripped is None else stripped


def strip_z_subset_any(subset, specs=()):
    """strip_z_subset over every clause shape this filter can produce.

    Tries the default Elevation clause, the conventional Z_Min/Z_Max range
    clause, then each extra-layer spec (so custom fields like RL strip too).
    The convention shapes run even when specs is stale or empty — a missed
    strip permanently filters the exported QField copy.
    """
    if not subset:
        return ""
    text = subset.strip()
    candidates = [(ELEVATION_FIELD, None), (Z_MIN_FIELD, Z_MAX_FIELD)]
    for spec in specs:
        if spec.get('mode') == 'range':
            candidates.append((spec.get('field_min'), spec.get('field_max')))
        else:
            candidates.append((spec.get('field'), None))
    seen = set()
    for field, field_max in candidates:
        if not field or (field, field_max) in seen:
            continue
        seen.add((field, field_max))
        stripped = _try_strip(text, _z_clause_patterns(field, field_max))
        if stripped is not None:
            return stripped
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


def parse_extra_layers(json_text):
    """Parse the persisted extra-layer JSON into a list of spec dicts.

    Defensive: this string round-trips through project variables and a
    phone, so malformed input degrades to [] / dropped entries, never an
    exception.
    """
    try:
        data = json.loads(json_text or "")
    except (TypeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    entries = []
    for raw in data.get('layers') or []:
        if not isinstance(raw, dict) or not raw.get('name'):
            continue
        mode = raw.get('mode')
        if mode == 'range':
            if not (raw.get('field_min') and raw.get('field_max')):
                continue
        elif mode == 'single':
            if not raw.get('field'):
                continue
        else:
            continue
        entry = {
            'id': str(raw.get('id') or ''),
            'name': str(raw['name']),
            'mode': mode,
            'source': raw.get('source') or 'attr',
            'checked': bool(raw.get('checked', True)),
        }
        if mode == 'range':
            entry['field_min'] = str(raw['field_min'])
            entry['field_max'] = str(raw['field_max'])
        else:
            entry['field'] = str(raw['field'])
        entries.append(entry)
    return entries


def format_extra_layers(entries):
    """Serialize extra-layer specs for the project entry / lgs_z_extra var."""
    return json.dumps({'v': 1, 'layers': list(entries)},
                      separators=(',', ':'), sort_keys=True)
