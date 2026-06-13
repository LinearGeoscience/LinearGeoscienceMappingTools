"""
Legend builder utility functions.

Core logic for scanning fields across groups, collecting unique values,
and building rule-based renderers with hierarchical group rules.
Used by the Map Layout Generator for print legend expansion.

Per-sheet scanning (scan_layer_values / scan_sections_for_sheet) restricts
value collection to features intersecting a mapsheet polygon, so each
generated layout's legend reflects only that sheet's content.

Pure config/formatting logic lives in legend_config.py (no qgis imports).
"""

from qgis.core import (
    QgsCategorizedSymbolRenderer, QgsRuleBasedRenderer,
    QgsSymbol, QgsFeatureRequest, QgsGeometry,
    QgsCoordinateTransform, QgsCsException,
    QgsMapLayerType, QgsMessageLog, Qgis,
)

try:
    from .legend_config import (
        is_valid_value as _is_valid_value,
        normalize_section, strip_table_suffix, group_fields_into_families,
        LOOKUP_TABLE_SUFFIXES, DEFAULT_EXCLUDED_FIELDS,
    )
except ImportError:
    from legend_config import (
        is_valid_value as _is_valid_value,
        normalize_section, strip_table_suffix, group_fields_into_families,
        LOOKUP_TABLE_SUFFIXES, DEFAULT_EXCLUDED_FIELDS,
    )

LOG_TAG = 'Linear Geoscience'


def scan_field_group(layer, field_names):
    """Collect unique non-NULL values across all fields in a group.

    Uses layer.uniqueValues() for performance.
    Returns a sorted list of unique string values.
    """
    unique = set()
    for fname in field_names:
        idx = layer.fields().indexOf(fname)
        if idx < 0:
            continue
        for val in layer.uniqueValues(idx):
            if _is_valid_value(val):
                unique.add(str(val))
    return sorted(unique)


def scan_field_group_subdivided(layer, field_names, subdivide_field):
    """Scan values grouped by a parent/type field.

    Iterates features to correlate each value with its parent type.
    Returns {subdivide_value: [sorted unique subtype values]}.
    """
    sub_idx = layer.fields().indexOf(subdivide_field)
    if sub_idx < 0:
        return {}

    field_indices = []
    for fn in field_names:
        fi = layer.fields().indexOf(fn)
        if fi >= 0:
            field_indices.append((fn, fi))

    if not field_indices:
        return {}

    grouped = {}  # {type_val: set(subtype_vals)}

    for feat in layer.getFeatures():
        type_val = feat[sub_idx]
        if not _is_valid_value(type_val):
            continue
        type_str = str(type_val)

        if type_str not in grouped:
            grouped[type_str] = set()

        for _fname, fidx in field_indices:
            val = feat[fidx]
            if _is_valid_value(val):
                grouped[type_str].add(str(val))

    return {k: sorted(v) for k, v in sorted(grouped.items())}


def preview_legend_groups(layer, field_groups):
    """Dry-run scan of field groups.

    field_groups: list of (group_name, [field_names], subdivide_by_or_None).
    Returns dict of {group_name: data} where data is either:
      - list[str] for flat groups (subdivide_by is None)
      - dict[str, list[str]] for subdivided groups
    """
    result = {}
    for group_name, field_names, subdivide_by in field_groups:
        if subdivide_by:
            result[group_name] = scan_field_group_subdivided(
                layer, field_names, subdivide_by)
        else:
            result[group_name] = scan_field_group(layer, field_names)
    return result


def build_grouped_renderer(layer, field_groups, existing_renderer,
                           include_catch_all=True):
    """Build a QgsRuleBasedRenderer with hierarchical group rules.

    Args:
        layer: QgsVectorLayer to build renderer for.
        field_groups: list of (group_name, [field_names], subdivide_by_or_None).
        existing_renderer: current renderer (to extract symbols from).
        include_catch_all: whether to add an else rule for unmatched features.

    Returns:
        QgsRuleBasedRenderer with nested group structure.
    """
    # Extract value -> symbol map from existing categorized renderer
    symbol_map = {}
    if isinstance(existing_renderer, QgsCategorizedSymbolRenderer):
        for cat in existing_renderer.categories():
            val = cat.value()
            if val is not None and str(val).strip():
                symbol_map[str(val)] = cat.symbol().clone()

    default_symbol = QgsSymbol.defaultSymbol(layer.geometryType())

    # Build rule tree
    root_rule = QgsRuleBasedRenderer.Rule(None)

    for group_name, field_names, subdivide_by in field_groups:
        if not field_names:
            continue

        # Parent group rule -- legend heading, no filter, no symbol
        group_rule = QgsRuleBasedRenderer.Rule(None)
        group_rule.setLabel(group_name)

        if subdivide_by:
            # Subdivided: create sub-groups by type value
            subdivided = scan_field_group_subdivided(
                layer, field_names, subdivide_by)

            for type_val, subtype_values in subdivided.items():
                sub_group = QgsRuleBasedRenderer.Rule(None)
                sub_group.setLabel(type_val)

                for val in subtype_values:
                    escaped_val = val.replace("'", "''")
                    escaped_type = type_val.replace("'", "''")

                    subtype_parts = [
                        f'"{fn}" = \'{escaped_val}\'' for fn in field_names]
                    filter_expr = (
                        f'"{subdivide_by}" = \'{escaped_type}\' AND '
                        f'({" OR ".join(subtype_parts)})')

                    symbol = symbol_map.get(val, default_symbol).clone()
                    child_rule = QgsRuleBasedRenderer.Rule(symbol)
                    child_rule.setFilterExpression(filter_expr)
                    child_rule.setLabel(val)
                    sub_group.appendChild(child_rule)

                group_rule.appendChild(sub_group)
        else:
            # Flat: scan unique values across all fields
            unique_values = scan_field_group(layer, field_names)

            for val in unique_values:
                escaped_val = val.replace("'", "''")
                parts = [
                    f'"{fname}" = \'{escaped_val}\'' for fname in field_names]
                filter_expr = " OR ".join(parts)

                symbol = symbol_map.get(val, default_symbol).clone()
                child_rule = QgsRuleBasedRenderer.Rule(symbol)
                child_rule.setFilterExpression(filter_expr)
                child_rule.setLabel(val)
                group_rule.appendChild(child_rule)

        root_rule.appendChild(group_rule)

    # Optional catch-all else rule for unmatched features
    if include_catch_all:
        else_rule = QgsRuleBasedRenderer.Rule(default_symbol.clone())
        else_rule.setIsElse(True)
        else_rule.setLabel("Other")
        root_rule.appendChild(else_rule)

    return QgsRuleBasedRenderer(root_rule)


# ── Layer / lookup resolution ─────────────────────────────────────────

def resolve_layer_ref(project, ref):
    """Resolve a {'id', 'name'} layer reference: id first, then name."""
    if not ref:
        return None
    layer = project.mapLayer(ref.get('id', ''))
    if layer:
        return layer
    name = ref.get('name', '')
    if name:
        matches = project.mapLayersByName(name)
        if matches:
            return matches[0]
    return None


def find_fields_for_table(project, table_name):
    """Find fields across spatial layers that correspond to a lookup table.

    Name-pattern matching: 'TextureCodes' → fields starting with 'Texture'
    (Texture, Texture2, Texture3...).  Returns [(layer, field_name), ...].
    """
    prefix = strip_table_suffix(table_name)

    results = []
    for lyr in project.mapLayers().values():
        if lyr.type() != QgsMapLayerType.VectorLayer or not lyr.isSpatial():
            continue
        for field in lyr.fields():
            if field.name().lower().startswith(prefix.lower()):
                results.append((lyr, field.name()))
    return results


def detect_lookup_columns(table_layer):
    """Guess key and value columns from a lookup table.

    Tries common column names first; falls back to the table's string
    columns, skipping id/system fields — never fid or other integer
    bookkeeping columns.
    """
    fields = table_layer.fields()
    key_names = ['Code', 'code', 'KEY', 'Key']
    val_names = ['Description', 'Desciption', 'description',
                 'Name', 'name', 'Label', 'Value', 'value']

    eligible = [f.name() for f in fields
                if _is_string_field(f)
                and f.name().lower() not in DEFAULT_EXCLUDED_FIELDS]

    key_col = next((k for k in key_names if fields.indexOf(k) >= 0),
                   eligible[0] if eligible
                   else (fields[0].name() if fields.count() > 0 else ''))
    val_col = next((v for v in val_names if fields.indexOf(v) >= 0), '')
    if not val_col:
        after_key = [name for name in eligible if name != key_col]
        val_col = after_key[0] if after_key else key_col
    return key_col, val_col


def load_lookup_table(table_layer, key_column, value_column,
                      group_column=None):
    """Build ({code: description}, {code: group}) from a lookup table.

    NULL-safe: keys/descriptions go through is_valid_value, so a code of
    0 or '0' survives (truthiness checks would drop it).  The group map
    is empty unless group_column is given (the table's discriminator,
    e.g. a 'Type' column splitting Alteration from Weathering codes).
    """
    key_idx = table_layer.fields().indexOf(key_column)
    val_idx = table_layer.fields().indexOf(value_column)
    grp_idx = (table_layer.fields().indexOf(group_column)
               if group_column else -1)
    if key_idx < 0:
        return {}, {}

    request = QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry)
    lookup = {}
    groups = {}
    for feat in table_layer.getFeatures(request):
        key = feat[key_idx]
        if not _is_valid_value(key):
            continue
        key_s = str(key)
        desc = feat[val_idx] if val_idx >= 0 else None
        lookup[key_s] = str(desc) if _is_valid_value(desc) else ''
        if grp_idx >= 0:
            group = feat[grp_idx]
            if _is_valid_value(group):
                groups[key_s] = str(group)
    return lookup, groups


def load_lookup_map(table_layer, key_column, value_column):
    """{code: description} from a lookup table (no grouping)."""
    return load_lookup_table(table_layer, key_column, value_column)[0]


# QGIS sentinel used by ValueMap widgets for NULL entries
_VALUE_MAP_NULL = '{2839923C-8B7D-419E-B84B-CA2FE9B80EC7}'


def widget_lookup_config(project, layer, field_idx):
    """Read a field's editor widget setup as a section-ready lookup dict.

    QField/QGIS dropdowns store the authoritative code→description
    mapping on the field itself:
      - ValueRelation → {'table': {id,name}, 'key_column', 'value_column'}
      - ValueMap → {'map': {code: description}}
    Returns None when the field has neither.
    """
    try:
        setup = layer.editorWidgetSetup(field_idx)
    except Exception:
        return None
    wtype = setup.type()
    config = setup.config() or {}

    if wtype == 'ValueRelation':
        table = project.mapLayer(config.get('Layer', ''))
        if table is None:
            name = config.get('LayerName', '')
            matches = project.mapLayersByName(name) if name else []
            table = matches[0] if matches else None
        key = config.get('Key', '')
        value = config.get('Value', '')
        if table is None or not key:
            return None
        return {
            'table': {'id': table.id(), 'name': table.name()},
            'key_column': key,
            'value_column': value or key,
        }

    if wtype == 'ValueMap':
        raw = config.get('map')
        # Both forms occur: {description: code} dict, or a list of
        # single-entry {description: code} dicts.
        if isinstance(raw, dict):
            items = list(raw.items())
        elif isinstance(raw, list):
            items = []
            for entry in raw:
                if isinstance(entry, dict):
                    items.extend(entry.items())
        else:
            return None
        mapping = {}
        for desc, code in items:
            if code is None or str(code) == _VALUE_MAP_NULL:
                continue
            code_s = str(code)
            if code_s:
                mapping.setdefault(code_s, str(desc))
        return {'map': mapping} if mapping else None

    return None


def lookup_from_widget(project, layer, field_idx):
    """{code: description} from a field's editor widget, or None."""
    config = widget_lookup_config(project, layer, field_idx)
    if config is None:
        return None
    if 'map' in config:
        return config['map']
    table = resolve_layer_ref(project, config['table'])
    if table is None:
        return None
    return load_lookup_map(
        table, config['key_column'], config['value_column']) or None


def resolve_section_targets(project, section):
    """Resolve a section to its scan targets: [(layer, [field_names])].

    Sections with explicit field_targets use exactly those layer/field
    pairs.  Explicit-layer sections target that layer; project-wide
    sections (layer=None) target every spatial vector layer holding any
    of the fields; project-wide sections with a lookup but no fields
    auto-detect fields from the lookup table's name pattern.
    """
    field_targets = section.get('field_targets')
    if field_targets:
        targets = []
        for target in field_targets:
            layer = resolve_layer_ref(project, target.get('layer'))
            if layer is None:
                QgsMessageLog.logMessage(
                    f"Legend section '{section.get('title')}': target layer "
                    f"'{target.get('layer', {}).get('name')}' not found — "
                    f"skipped.", LOG_TAG, Qgis.Warning)
                continue
            targets.append((layer, list(target.get('fields', []))))
        return targets

    fields = list(section.get('fields', []))
    layer_ref = section.get('layer')

    if layer_ref:
        layer = resolve_layer_ref(project, layer_ref)
        return [(layer, fields)] if layer is not None else []

    lookup = section.get('lookup')
    if not fields and lookup and lookup.get('table'):
        table_name = lookup['table'].get('name', '')
        by_layer = {}
        for lyr, fname in find_fields_for_table(project, table_name):
            by_layer.setdefault(lyr.id(), (lyr, []))[1].append(fname)
        return list(by_layer.values())

    targets = []
    for lyr in project.mapLayers().values():
        if (lyr.type() != QgsMapLayerType.VectorLayer
                or not lyr.isSpatial()):
            continue
        present = [f for f in fields if lyr.fields().indexOf(f) >= 0]
        if present:
            targets.append((lyr, present))
    return targets


def collect_widget_lookups(project, section):
    """Merge {code: description} from editor widgets across a section's
    target fields.  First definition of a code wins."""
    merged = {}
    for layer, field_names in resolve_section_targets(project, section):
        for fname in field_names:
            idx = layer.fields().indexOf(fname)
            if idx < 0:
                continue
            mapping = lookup_from_widget(project, layer, idx)
            if mapping:
                for code, desc in mapping.items():
                    merged.setdefault(code, desc)
    return merged


def _squash(name):
    """Lowercase a field name and drop '_'/' ' separators for matching."""
    return name.lower().replace('_', '').replace(' ', '')


def find_paired_description_field(layer, field_name):
    """Find the sibling description column for a code field.

    Matches '<field>description' case-insensitively, tolerating '_' and
    ' ' separators: Subtype1 ↔ SubType1Description / SubType1_Description.
    Returns the column name or None.
    """
    target = _squash(field_name) + 'description'
    for field in layer.fields():
        if field.name() != field_name and _squash(field.name()) == target:
            return field.name()
    return None


def paired_base_field(layer, field_name):
    """Inverse of find_paired_description_field: the code column that a
    '*Description' field describes, or None."""
    squashed = _squash(field_name)
    if not squashed.endswith('description'):
        return None
    base = squashed[:-len('description')]
    if not base:
        return None
    for field in layer.fields():
        if field.name() != field_name and _squash(field.name()) == base:
            return field.name()
    return None


def collect_paired_lookups(project, section):
    """{code: description} built from paired columns on the data layers.

    For each scan target field F with a sibling description column
    (Subtype1 ↔ SubType1Description), one feature pass per layer collects
    code→description pairs.  First definition of a code wins.
    """
    merged = {}
    for layer, field_names in resolve_section_targets(project, section):
        pairs = []
        for fname in field_names:
            code_idx = layer.fields().indexOf(fname)
            if code_idx < 0:
                continue
            desc_name = find_paired_description_field(layer, fname)
            if not desc_name:
                continue
            desc_idx = layer.fields().indexOf(desc_name)
            if desc_idx >= 0:
                pairs.append((code_idx, desc_idx))
        if not pairs:
            continue

        needed = sorted({idx for pair in pairs for idx in pair})
        request = QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry)
        request.setSubsetOfAttributes(needed)
        for feat in layer.getFeatures(request):
            for code_idx, desc_idx in pairs:
                code = feat[code_idx]
                desc = feat[desc_idx]
                if _is_valid_value(code) and _is_valid_value(desc):
                    merged.setdefault(str(code), str(desc))
    return merged


# ── Auto-detection of legend sections ─────────────────────────────────

def field_has_data(layer, field_idx):
    """True if the field holds at least one non-NULL, non-empty value."""
    return any(_is_valid_value(v) for v in layer.uniqueValues(field_idx))


def _is_string_field(field):
    from qgis.PyQt.QtCore import QVariant
    return field.type() == QVariant.String


def discover_section_candidates(project):
    """Discover legend section candidates from columns that contain data.

    Two passes:
      1. Lookup-matched: every non-spatial table named '<Family>Codes' /
         '<Family>Categories' etc. claims its field family across spatial
         layers (Mineral, Mineral2, Mineral3...).  Only populated string
         fields count.
      2. Unmatched extras: remaining populated string fields (minus the
         DEFAULT_EXCLUDED_FIELDS skip-list), grouped into numbered
         families — e.g. Intensity with no IntensityCodes table.

    Returns ordered candidate dicts:
        {'title', 'fields': [names], 'lookup': {...}|None,
         'matched': bool, 'layers': [layer names]}
    """
    spatial_layers = [
        lyr for lyr in project.mapLayers().values()
        if lyr.type() == QgsMapLayerType.VectorLayer and lyr.isSpatial()]
    tables = sorted(
        (lyr for lyr in project.mapLayers().values()
         if lyr.type() == QgsMapLayerType.VectorLayer and not lyr.isSpatial()),
        key=lambda l: l.name())

    candidates = []
    claimed = set()  # lowercased field names taken by a matched candidate

    # Pass 1: lookup-matched field families
    for table in tables:
        if not any(table.name().endswith(s) for s in LOOKUP_TABLE_SUFFIXES):
            continue
        matched = find_fields_for_table(project, table.name())
        keep_fields = set()
        keep_layers = set()
        for lyr, fname in matched:
            if fname.lower() in claimed:
                continue
            idx = lyr.fields().indexOf(fname)
            if idx < 0 or not _is_string_field(lyr.fields()[idx]):
                continue
            if field_has_data(lyr, idx):
                keep_fields.add(fname)
                keep_layers.add(lyr.name())
        if not keep_fields:
            continue
        claimed.update(f.lower() for f in keep_fields)
        key_col, val_col = detect_lookup_columns(table)
        candidates.append({
            'title': strip_table_suffix(table.name()),
            'fields': sorted(keep_fields),
            'lookup': {
                'table': {'id': table.id(), 'name': table.name()},
                'key_column': key_col,
                'value_column': val_col,
            },
            'matched': True,
            'layers': sorted(keep_layers),
        })

    # Pass 2: remaining populated string fields, grouped into families.
    # A family whose fields carry a ValueRelation/ValueMap editor widget
    # (QField dropdowns) gets that lookup attached and counts as matched
    # — the widget config is the authoritative code→description source.
    remaining = {}  # field name → [layer objects]
    for lyr in spatial_layers:
        for field in lyr.fields():
            fname = field.name()
            if fname.lower() in claimed:
                continue
            if fname.lower() in DEFAULT_EXCLUDED_FIELDS:
                continue
            if not _is_string_field(field):
                continue
            # '*Description' columns paired with a code field are
            # description sources, not code families of their own.
            if paired_base_field(lyr, fname):
                continue
            idx = lyr.fields().indexOf(fname)
            if field_has_data(lyr, idx):
                remaining.setdefault(fname, []).append(lyr)

    for family, members in group_fields_into_families(
            sorted(remaining)).items():
        layers = set()
        lookup = None
        has_pairs = False
        for member in members:
            for lyr in remaining[member]:
                layers.add(lyr.name())
                if lookup is None:
                    idx = lyr.fields().indexOf(member)
                    lookup = widget_lookup_config(project, lyr, idx)
                if not has_pairs and find_paired_description_field(
                        lyr, member):
                    has_pairs = True
        if lookup is None and has_pairs:
            lookup = {'pairs': {'suffix': 'Description'}}
        candidates.append({
            'title': family,
            'fields': members,
            'lookup': lookup,
            'matched': lookup is not None,
            'layers': sorted(layers),
        })

    return candidates


def auto_sections_from_candidates(candidates, matched_only=True):
    """Build normalised text sections from discovery candidates."""
    sections = []
    for cand in candidates:
        if matched_only and not cand['matched']:
            continue
        sections.append(normalize_section({
            'title': cand['title'],
            'layer': None,
            'fields': cand['fields'],
            'display': 'text',
            'lookup': cand['lookup'],
        }))
    return sections


def build_renderer_value_index(layer):
    """Map renderer values/labels to legend symbol indices.

    For categorized renderers, maps BOTH the category value (raw data)
    AND the display label, since field scans return raw values but
    legendSymbolItems may return display labels.  Other renderer types
    map labels only.  Returns ({value_or_label: index}, symbol_count).
    """
    renderer = layer.renderer() if layer else None
    if renderer is None:
        return {}, 0

    symbol_items = renderer.legendSymbolItems()
    value_to_idx = {}

    if isinstance(renderer, QgsCategorizedSymbolRenderer):
        for idx, cat in enumerate(renderer.categories()):
            val = cat.value()
            if val is not None and str(val).strip():
                value_to_idx[str(val)] = idx
            label = cat.label()
            if label and label not in value_to_idx:
                value_to_idx[label] = idx
    else:
        for idx, item in enumerate(symbol_items):
            if item.label():
                value_to_idx[item.label()] = idx

    return value_to_idx, len(symbol_items)


# ── Per-sheet scanning ────────────────────────────────────────────────

def transform_geom_to_layer(sheet_geom, sheet_crs, layer, project):
    """Return a copy of sheet_geom transformed into the layer's CRS.

    Returns None on transform failure (caller falls back to an
    unfiltered scan for that layer rather than aborting the sheet).
    """
    layer_crs = layer.crs()
    geom = QgsGeometry(sheet_geom)
    if sheet_crs == layer_crs:
        return geom
    try:
        transform = QgsCoordinateTransform(sheet_crs, layer_crs, project)
        if geom.transform(transform) != 0:
            raise QgsCsException("geometry transform returned non-zero")
        return geom
    except QgsCsException as e:
        QgsMessageLog.logMessage(
            f"CRS transform to '{layer.name()}' failed ({e}); "
            f"scanning whole layer instead.", LOG_TAG, Qgis.Warning)
        return None


def scan_layer_values(layer, field_names, filter_geom=None, subdivide_by=None):
    """Collect unique values for fields, optionally spatially filtered.

    filter_geom must already be in the layer's CRS.
    Returns sorted [values] (flat) or {sub_value: sorted [values]}
    when subdivide_by is given.
    """
    flat = None if subdivide_by else set(field_names)
    specs = [('_', list(field_names), subdivide_by)] if subdivide_by else []
    field_values, sub_results = _scan_layer_combined(
        layer, flat or set(), specs, filter_geom)

    if subdivide_by:
        grouped = sub_results.get('_', {})
        return {k: sorted(v) for k, v in sorted(grouped.items())}
    unique = set()
    for fname in field_names:
        unique.update(field_values.get(fname, set()))
    return sorted(unique)


def _scan_layer_combined(layer, flat_fields, subdivided_specs, filter_geom):
    """One feature pass over a layer serving several sections at once.

    flat_fields: set of field names to collect unique values for.
    subdivided_specs: [(section_id, [field_names], subdivide_field), ...].
    filter_geom: geometry in layer CRS, or None for whole-layer scan.

    Returns (field_values: {fname: set}, sub_results: {section_id: {sub: set}}).
    """
    fields = layer.fields()
    flat_idx = {f: fields.indexOf(f) for f in flat_fields}
    flat_idx = {f: i for f, i in flat_idx.items() if i >= 0}

    specs = []
    for sid, fnames, sub_field in subdivided_specs:
        sub_idx = fields.indexOf(sub_field)
        f_idx = [fields.indexOf(f) for f in fnames]
        f_idx = [i for i in f_idx if i >= 0]
        if sub_idx >= 0 and f_idx:
            specs.append((sid, f_idx, sub_idx))

    field_values = {f: set() for f in flat_idx}
    sub_results = {sid: {} for sid, _, _ in specs}

    if not flat_idx and not specs:
        return field_values, sub_results

    # Fast path: no spatial filter, no feature-level correlation needed.
    if filter_geom is None and not specs:
        for fname, idx in flat_idx.items():
            for val in layer.uniqueValues(idx):
                if _is_valid_value(val):
                    field_values[fname].add(str(val))
        return field_values, sub_results

    needed = set(flat_idx.values())
    for _, f_idx, sub_idx in specs:
        needed.update(f_idx)
        needed.add(sub_idx)

    request = QgsFeatureRequest()
    request.setSubsetOfAttributes(sorted(needed))
    engine = None
    if filter_geom is not None:
        request.setFilterRect(filter_geom.boundingBox())
        engine = QgsGeometry.createGeometryEngine(filter_geom.constGet())
        engine.prepareGeometry()
    else:
        request.setFlags(QgsFeatureRequest.NoGeometry)

    for feat in layer.getFeatures(request):
        if engine is not None:
            geom = feat.geometry()
            if geom.isNull() or not engine.intersects(geom.constGet()):
                continue

        for fname, idx in flat_idx.items():
            val = feat[idx]
            if _is_valid_value(val):
                field_values[fname].add(str(val))

        for sid, f_idx, sub_idx in specs:
            sub_val = feat[sub_idx]
            if not _is_valid_value(sub_val):
                continue
            bucket = sub_results[sid].setdefault(str(sub_val), set())
            for idx in f_idx:
                val = feat[idx]
                if _is_valid_value(val):
                    bucket.add(str(val))

    return field_values, sub_results


def scan_sections_for_sheet(project, sections, sheet_geom=None,
                            sheet_crs=None):
    """Scan all sections' fields, optionally restricted to a sheet polygon.

    Groups work so each layer is iterated at most once per sheet, however
    many sections reference it.  Sections with layer=None scan their
    fields across every spatial vector layer (subdivide_by is ignored for
    these — feature-level correlation across layers is undefined).
    Sections with a lookup but no fields auto-detect fields by the lookup
    table's name pattern (TextureCodes → Texture*).

    Returns {section_id: sorted [values] | {sub_value: sorted [values]}}.
    """
    # Build per-layer work lists: {layer_id: (layer, flat_fields, specs)}
    work = {}
    # Track which (layer, fields) targets feed each flat section.
    flat_targets = {}  # {section_id: [(layer_id, [fields])]}

    def _add_flat(layer, section_id, fnames):
        entry = work.setdefault(layer.id(), (layer, set(), []))
        entry[1].update(fnames)
        flat_targets.setdefault(section_id, []).append((layer.id(), fnames))

    for section in sections:
        sid = section['id']
        targets = resolve_section_targets(project, section)
        if not targets:
            if section.get('layer'):
                QgsMessageLog.logMessage(
                    f"Legend section '{section.get('title')}': layer "
                    f"'{section['layer'].get('name')}' not found — skipped.",
                    LOG_TAG, Qgis.Warning)
            continue

        if section.get('subdivide_by'):
            # One spec per target layer; layers lacking the subdivide
            # field are skipped inside _scan_layer_combined.
            for layer, fields in targets:
                entry = work.setdefault(layer.id(), (layer, set(), []))
                entry[2].append((sid, fields, section['subdivide_by']))
        else:
            for lyr, fnames in targets:
                _add_flat(lyr, sid, fnames)

    # Scan each layer once.  Subdivided results are merged across layers
    # (a section's field_targets may span several layers).
    layer_field_values = {}  # {layer_id: {fname: set}}
    sub_accum = {}  # {sid: {sub_value: set}}
    results = {}
    for layer_id, (layer, flat_fields, specs) in work.items():
        filter_geom = None
        if sheet_geom is not None and sheet_crs is not None:
            filter_geom = transform_geom_to_layer(
                sheet_geom, sheet_crs, layer, project)
        field_values, sub_results = _scan_layer_combined(
            layer, flat_fields, specs, filter_geom)
        layer_field_values[layer_id] = field_values
        for sid, grouped in sub_results.items():
            acc = sub_accum.setdefault(sid, {})
            for sub_value, values in grouped.items():
                acc.setdefault(sub_value, set()).update(values)

    for sid, grouped in sub_accum.items():
        results[sid] = {k: sorted(v) for k, v in sorted(grouped.items())}

    # Assemble flat sections (union across their layer targets).
    for sid, targets in flat_targets.items():
        unique = set()
        for layer_id, fnames in targets:
            field_values = layer_field_values.get(layer_id, {})
            for fname in fnames:
                unique.update(field_values.get(fname, set()))
        results[sid] = sorted(unique)

    return results
