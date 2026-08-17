"""Canonical LGS mapping layer names, and tolerant ways to match them.

The template ships four spatial layers whose "N - Name" prefix doubles as the
top-to-bottom draw order:

    1 - FieldNotebook   points
    2 - Linework        lines
    3 - Overlay         polygons
    4 - Basemap         polygons

Linework and Overlay swapped numbers in Aug 2026 so that lines (contacts, veins,
structural traces) draw ABOVE Overlay's translucent alteration and mineralisation
washes instead of underneath them.

That swap is why this module exists. The names used to be re-declared as literals
in seven places with no shared import, and every comparison was an exact string
match - so a project built from an older template would silently stop binding.
Matching now goes through base_name(), which strips the ordinal, so "2 - Overlay"
and "3 - Overlay" are the same layer as far as the plugin is concerned. Field data
collected before the swap keeps working without a migration.

Only the ORDER of CANONICAL_LAYERS is load-bearing beyond naming: the QField
sidecar (z_filter/qfield/lgs_companion.qml) mirrors this list and derives its
lgs_z_orig_<i> project-variable keys from each layer's index, so the two must stay
in the same order. tests/test_layer_canon.py enforces that.
"""
import re

FIELDNOTEBOOK = "1 - FieldNotebook"
LINEWORK = "2 - Linework"
OVERLAY = "3 - Overlay"
BASEMAP = "4 - Basemap"

#: The four mapping layers, top of the layer tree first. Order is mirrored by
#: the QField sidecar's `layerNames` - keep them in step.
CANONICAL_LAYERS = [FIELDNOTEBOOK, LINEWORK, OVERLAY, BASEMAP]

# Ordinal-prefix forms seen in the wild. Lifted from
# static_mapping_export.LayerNameParser.extract_base_name so both agree.
_PREFIX_PATTERNS = (
    r'^\d+\s*[-_]\s*(.+)$',           # "1 - Name" / "1_Name" / "1- Name"
    r'^\d+\s+(.+)$',                  # "1 Name"
    r'^[A-Za-z]?\d+\s*[-_]\s*(.+)$',  # "A1 - Name"
)


def base_name(name):
    """Strip any ordinal prefix: "3 - Overlay" and "2 - Overlay" -> "Overlay".

    Names without a recognised prefix come back unchanged, so this is safe to
    call on arbitrary user layers.
    """
    text = (name or "").strip()
    for pattern in _PREFIX_PATTERNS:
        match = re.match(pattern, text)
        if match:
            return match.group(1).strip()
    return text


def same_layer(a, b):
    """True when two layer names denote the same layer, ignoring the ordinal."""
    return base_name(a).casefold() == base_name(b).casefold()


#: Base names of the four mapping layers, for fast membership tests.
CANONICAL_BASE_NAMES = frozenset(base_name(n).casefold() for n in CANONICAL_LAYERS)


def is_canonical(name):
    """True when `name` is one of the four mapping layers, any numbering."""
    return base_name(name).casefold() in CANONICAL_BASE_NAMES


def find_layer(project, canonical):
    """Resolve one canonical layer in `project`, tolerating old numbering.

    Exact name first (the common case), then an ordinal-insensitive sweep so a
    project built from a pre-swap template still resolves. Returns None when the
    layer is absent.
    """
    matches = project.mapLayersByName(canonical)
    if matches:
        return matches[0]
    for layer in project.mapLayers().values():
        if same_layer(layer.name(), canonical):
            return layer
    return None


def find_layers(project):
    """Map canonical name -> layer for whichever mapping layers are present."""
    found = {}
    for canonical in CANONICAL_LAYERS:
        layer = find_layer(project, canonical)
        if layer is not None:
            found[canonical] = layer
    return found


def gpkg_feature_layers(gpkg_path):
    """Feature-table names in a GeoPackage, in layer-tree (row) order.

    Plain sqlite3 so this stays importable outside QGIS.
    """
    import sqlite3
    try:
        con = sqlite3.connect(gpkg_path)
    except sqlite3.Error:
        return []
    try:
        return [r[0] for r in con.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features' "
            "ORDER BY rowid")]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def gpkg_layer_name(gpkg_path, canonical):
    """Actual table name in `gpkg_path` for a canonical layer, or None.

    Returns `canonical` unchanged when it is present. Otherwise falls back to an
    ordinal-insensitive match, so a GeoPackage written from a pre-Aug-2026
    template (where Linework/Overlay carried the other numbers) still resolves.
    """
    names = gpkg_feature_layers(gpkg_path)
    if canonical in names:
        return canonical
    for name in names:
        if same_layer(name, canonical):
            return name
    return None


def lookup(mapping, name, default=None):
    """Fetch from a canonical-name-keyed dict, tolerating old numbering.

    Lets config dicts stay keyed by the canonical names while still matching a
    layer that arrived under its old number.
    """
    if name in mapping:
        return mapping[name]
    target = base_name(name).casefold()
    for key, value in mapping.items():
        if base_name(key).casefold() == target:
            return value
    return default
