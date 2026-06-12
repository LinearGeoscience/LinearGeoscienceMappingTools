"""
Legend configuration schema, migration and text formatting.

Pure-python (no qgis imports) so the config logic is unit-testable
outside QGIS.  The v2 "section" model unifies the previously separate
field-group (symbol expansion) and value-relation (code table) configs:

    {
        'id': str,                      # stable uuid for cross-referencing
        'title': str,                   # legend heading
        'layer': {'id': str, 'name': str} | None,   # None = scan all spatial layers
        'fields': [str],                # columns to scan for values
        'subdivide_by': str | None,     # parent field for sub-headings
        'display': 'auto' | 'symbols' | 'text',
        'lookup': {'table': {'id': str, 'name': str},
                   'key_column': str, 'value_column': str} | None,
    }

display modes:
    'symbols' - values must match renderer categories; unmatched are dropped
                (legacy behaviour, with a warning).
    'text'    - values rendered as a text block below the legend
                (heading + "code — description" list).  For fields with no
                symbology (minerals, textures, intensity, ...).
    'auto'    - matched values become legend symbol entries, the unmatched
                remainder overflows into the text block.  Nothing is dropped.
"""

import json
import uuid

CONFIG_VERSION = 2
DISPLAY_MODES = ('auto', 'symbols', 'text')

EM_DASH = '—'

# Suffixes that identify a lookup/code table by name ('MineralCodes' → the
# 'Mineral' field family).  Shared by table matching and section titling.
LOOKUP_TABLE_SUFFIXES = ('Codes', 'codes', 'Code', 'code',
                         'Categories', 'categories', 'Table', 'table')

# Fields never proposed as auto-detected legend sections: ids/metadata,
# template bookkeeping, free text, and fields already expressed elsewhere
# in the layout.  Matched case-insensitively.
DEFAULT_EXCLUDED_FIELDS = frozenset(f.lower() for f in (
    'fid', 'id', 'uuid', 'objectid',
    'projectid', 'mappedscale', 'mappedcrs',
    'name', 'orientation', 'legend', 'description',
    'notes', 'note', 'comments', 'comment', 'remarks',
    'geologist', 'author', 'date', 'created', 'updated',
    'photo', 'photos', 'photopath',
))


def is_valid_value(val):
    """Check a field value is non-NULL and non-empty.  Keeps 0/'0'."""
    if val is None:
        return False
    s = str(val).strip()
    return bool(s) and s != 'NULL'


def strip_table_suffix(table_name):
    """Strip a lookup-table suffix: 'MineralCodes' → 'Mineral'."""
    for suffix in LOOKUP_TABLE_SUFFIXES:
        if table_name.endswith(suffix) and len(table_name) > len(suffix):
            return table_name[:-len(suffix)]
    return table_name


def strip_family_suffix(field_name):
    """Strip trailing digits: 'Mineral3' → 'Mineral', 'Dip' → 'Dip'."""
    return field_name.rstrip('0123456789') or field_name


def group_fields_into_families(field_names):
    """Group field names into numbered families.

    'Mineral', 'Mineral2', 'Mineral3' → {'Mineral': [all three]}.
    Single fields form their own family.  Returns {family: [fields]}
    with insertion order preserved and members sorted.
    """
    families = {}
    for name in field_names:
        families.setdefault(strip_family_suffix(name), []).append(name)
    return {family: sorted(set(members))
            for family, members in families.items()}


def _layer_ref(ref):
    """Normalise a layer reference to {'id': str, 'name': str} or None."""
    if not ref:
        return None
    if isinstance(ref, str):
        # Legacy: a bare layer id or name — try it as both at resolve time.
        return {'id': ref, 'name': ref}
    return {'id': str(ref.get('id', '') or ''),
            'name': str(ref.get('name', '') or '')}


def normalize_section(section):
    """Fill defaults and validate a section dict. Returns a new dict."""
    display = section.get('display', 'auto')
    if display not in DISPLAY_MODES:
        display = 'auto'

    lookup = section.get('lookup')
    if lookup and lookup.get('table'):
        lookup = {
            'table': _layer_ref(lookup['table']),
            'key_column': lookup.get('key_column', ''),
            'value_column': lookup.get('value_column', ''),
        }
    else:
        lookup = None

    return {
        'id': section.get('id') or str(uuid.uuid4()),
        'title': section.get('title', ''),
        'layer': _layer_ref(section.get('layer')),
        'fields': [str(f) for f in section.get('fields', []) if str(f).strip()],
        'subdivide_by': section.get('subdivide_by') or None,
        'display': display,
        'lookup': lookup,
    }


def normalize_config(config):
    """Fill defaults on a v2 config dict. Returns a new dict."""
    config = dict(config or {})
    options = dict(config.get('options') or {})
    return {
        'version': CONFIG_VERSION,
        'sections': [normalize_section(s) for s in config.get('sections', [])],
        'text_mappings': dict(config.get('text_mappings') or {}),
        'legend_unchecked_layers': [
            _layer_ref(r) for r in config.get('legend_unchecked_layers', [])
            if _layer_ref(r)],
        'code_table_text_manual': config.get('code_table_text_manual', ''),
        'options': {
            'per_sheet_scan': bool(options.get('per_sheet_scan', True)),
            'filter_legend_by_map': bool(
                options.get('filter_legend_by_map', True)),
        },
    }


def migrate_legacy_config(field_configs=None, vr_sections=None,
                          text_mappings=None):
    """Convert v1 config structures to a v2 config dict.

    field_configs: {layer_key: [(name, fields, subdivide_by), ...]} where
        layer_key is a layer id (in-memory form) or layer name (file form),
        and groups may be tuples or {'name','fields','subdivide_by'} dicts.
    vr_sections: [{'name', 'lookup_table', 'key_column', 'value_column',
        'scan_fields'}, ...]
    text_mappings: {layer_name: {'display_name', 'features'}} (v1 was
        keyed by layer name; v2 keeps the key but records 'name' inside the
        entry so it can be re-resolved by name when the key isn't an id).
    """
    sections = []
    for layer_key, groups in (field_configs or {}).items():
        for group in groups:
            if isinstance(group, dict):
                name = group.get('name', '')
                fields = group.get('fields', [])
                sub = group.get('subdivide_by')
            else:
                name, fields, sub = group
            sections.append(normalize_section({
                'title': name,
                'layer': layer_key,
                'fields': fields,
                'subdivide_by': sub,
                'display': 'auto',
            }))

    for vr in (vr_sections or []):
        sections.append(normalize_section({
            'title': vr.get('name', ''),
            'layer': None,
            'fields': vr.get('scan_fields', []),
            'subdivide_by': None,
            'display': 'text',
            'lookup': {
                'table': {'id': '', 'name': vr.get('lookup_table', '')},
                'key_column': vr.get('key_column', ''),
                'value_column': vr.get('value_column', ''),
            },
        }))

    migrated_mappings = {}
    for layer_name, entry in (text_mappings or {}).items():
        new_entry = dict(entry)
        new_entry.setdefault('name', layer_name)
        migrated_mappings[layer_name] = new_entry

    return normalize_config({
        'sections': sections,
        'text_mappings': migrated_mappings,
    })


def serialize_config(config):
    """Serialise a config dict to a JSON string."""
    return json.dumps(normalize_config(config), indent=2)


def deserialize_config(raw):
    """Parse a JSON string or dict into a normalised v2 config.

    Accepts v2 payloads and both v1 file formats:
      - {'legend_field_configs': ..., 'value_relation_sections': ...}
      - {'legend_mappings': ...}
    Unknown keys are ignored; a v1 payload is migrated.
    """
    if raw is None:
        return normalize_config({})
    data = json.loads(raw) if isinstance(raw, str) else dict(raw)

    if data.get('version', 0) >= 2 or 'sections' in data:
        return normalize_config(data)

    return migrate_legacy_config(
        field_configs=data.get('legend_field_configs'),
        vr_sections=data.get('value_relation_sections'),
        text_mappings=data.get('legend_mappings'),
    )


# ── Text block formatting ─────────────────────────────────────────────

def format_entries(values, lookup_map=None):
    """Format a list of values as 'code — Description, code2, ...'."""
    lookup_map = lookup_map or {}
    entries = []
    for code in sorted(values):
        desc = lookup_map.get(code, '')
        if desc and desc != code:
            entries.append(f"{code} {EM_DASH} {desc}")
        else:
            entries.append(code)
    return ", ".join(entries)


def format_text_sections(sections, scan_results, lookup_maps=None,
                         extra_unmatched=None):
    """Build the plain-text legend block for text-mode sections.

    sections: normalised section dicts, in display order.
    scan_results: {section_id: [values]} or {section_id: {sub: [values]}}.
    lookup_maps: {section_id: {code: description}}.
    extra_unmatched: {section_id: [values]} — auto-mode overflow (values
        with no renderer symbol) appended under the section's heading.

    Returns the formatted text ('' if nothing to show).  Headings are
    uppercased; the label item renders ModeFont so no rich text is used.
    """
    lookup_maps = lookup_maps or {}
    extra_unmatched = extra_unmatched or {}
    blocks = []

    for section in sections:
        sid = section['id']
        display = section.get('display', 'auto')
        lookup = lookup_maps.get(sid)

        if display == 'text':
            data = scan_results.get(sid)
        elif display == 'auto':
            data = extra_unmatched.get(sid)
        else:  # 'symbols' — never contributes text
            continue

        if not data:
            continue

        lines = [section.get('title', '').upper() or 'LEGEND']
        if isinstance(data, dict):
            for sub_value in sorted(data):
                values = data[sub_value]
                if not values:
                    continue
                lines.append(f"{sub_value}: {format_entries(values, lookup)}")
            if len(lines) == 1:
                continue
        else:
            lines.append(format_entries(data, lookup))

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)
