"""
Auto-detection heuristics for extra Z-filterable layers (UG survey points,
floor strings) that arrive outside the four canonical mapping layers.

Pure python, no qgis imports — unit-tested in tests/test_z_detect.py. The
qgis side (reading fields/geometry/capabilities off real layers) lives in
z_filter/auto_layers.py.

Eligibility is capability-based: an elevation-like attribute (or min/max
pair) OR Z in the geometry makes a layer filterable. Layer-name hints never
gate eligibility — they only decide whether a geometry-Z layer starts
checked (zero-config bias: confident detections opt in by themselves).
"""

# No package imports (not even .expression) so tests can load this file
# directly.
ELEVATION_FIELD = "Elevation"   # keep equal to expression.ELEVATION_FIELD
Z_MIN_FIELD = "Z_Min"           # keep equal to expression.Z_MIN_FIELD
Z_MAX_FIELD = "Z_Max"           # keep equal to expression.Z_MAX_FIELD

# Attribute names that hold a single level elevation, in match priority
# order (compared case-insensitively against numeric fields only).
ELEVATION_FIELD_CANDIDATES = [
    'elevation', 'rl', 'z', 'elev', 'z_value', 'zvalue', 'altitude', 'alt']

# Min/max pair names for range-mode layers, in match priority order.
RANGE_FIELD_PAIRS = [
    ('z_min', 'z_max'), ('zmin', 'zmax'), ('elev_min', 'elev_max'),
    ('rl_min', 'rl_max'), ('min_z', 'max_z')]

# Substrings that mark a layer as survey-ish, promoting geometry-Z layers
# to auto-checked.
NAME_HINTS = ['survey', 'string', 'floor', 'pickup', 'level', 'bench',
              'ug', 'underground', 'peg', 'station']

READ_ONLY_REASON = "read-only source — import to GeoPackage first"


def match_elevation_field(numeric_field_names):
    """First candidate present among the layer's numeric fields.

    Returns the field's ORIGINAL casing (subset SQL quotes it), or None.
    """
    by_lower = _first_by_lower(numeric_field_names)
    for candidate in ELEVATION_FIELD_CANDIDATES:
        if candidate in by_lower:
            return by_lower[candidate]
    return None


def match_range_pair(numeric_field_names):
    """First min/max pair fully present, original casing. None if no pair."""
    by_lower = _first_by_lower(numeric_field_names)
    for lo, hi in RANGE_FIELD_PAIRS:
        if lo in by_lower and hi in by_lower:
            return (by_lower[lo], by_lower[hi])
    return None


def name_hint(layer_name):
    """True when the layer name suggests survey/level data."""
    lowered = (layer_name or "").lower()
    return any(hint in lowered for hint in NAME_HINTS)


def candidate_specs(layer_name, numeric_field_names, has_z_geometry,
                    geometry_class, writable):
    """Every usable Z source for a non-canonical layer, best first.

    geometry_class: 'point' | 'line' | 'polygon'.
    writable: provider can add fields + change attribute values.

    Each spec:
        mode:            'single' | 'range'
        field / field_min+field_max
        source:          'attr' (existing fields) | 'geom' (to materialize)
        auto_check:      start checked in the panel
        needs_fields:    fields must be added+populated from geometry Z
        disabled_reason: str | None (listed but not usable)

    Priority: existing range pair > existing single field > geometry Z —
    existing data always wins over writing anything new. Later entries feed
    the panel's manual source override.
    """
    specs = []
    pair = match_range_pair(numeric_field_names)
    if pair:
        specs.append({'mode': 'range', 'field_min': pair[0],
                      'field_max': pair[1], 'source': 'attr',
                      'auto_check': True, 'needs_fields': False,
                      'disabled_reason': None})
    field = match_elevation_field(numeric_field_names)
    if field:
        specs.append({'mode': 'single', 'field': field, 'source': 'attr',
                      'auto_check': True, 'needs_fields': False,
                      'disabled_reason': None})
    if has_z_geometry:
        # Geometry Z: points get one Elevation value, lines/polygons get a
        # min/max range so ramps show on every level they touch.
        if geometry_class == 'point':
            spec = {'mode': 'single', 'field': ELEVATION_FIELD}
        else:
            spec = {'mode': 'range', 'field_min': Z_MIN_FIELD,
                    'field_max': Z_MAX_FIELD}
        spec['source'] = 'geom'
        spec['needs_fields'] = True
        if not writable:
            spec['auto_check'] = False
            spec['disabled_reason'] = READ_ONLY_REASON
        else:
            spec['auto_check'] = name_hint(layer_name)
            spec['disabled_reason'] = None
        specs.append(spec)
    return specs


def detect_spec(layer_name, numeric_field_names, has_z_geometry,
                geometry_class, writable):
    """Best spec for a layer, or None when nothing is elevation-like."""
    specs = candidate_specs(layer_name, numeric_field_names, has_z_geometry,
                            geometry_class, writable)
    return specs[0] if specs else None


def _first_by_lower(names):
    """{lowercased: original} keeping the first occurrence of each name."""
    by_lower = {}
    for name in names or []:
        key = str(name).lower()
        if key not in by_lower:
            by_lower[key] = str(name)
    return by_lower
