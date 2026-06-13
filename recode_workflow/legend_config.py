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
            'group_column': lookup.get('group_column') or None,
        }
    elif lookup and lookup.get('map'):
        # Inline code→description map (e.g. from a ValueMap field widget)
        lookup = {'map': {str(k): str(v)
                          for k, v in dict(lookup['map']).items()}}
    elif lookup and 'pairs' in lookup:
        # Paired columns on the data layer itself: field F holds the code,
        # sibling column F+suffix holds the description.
        pairs = lookup.get('pairs') or {}
        lookup = {'pairs': {
            'suffix': str(pairs.get('suffix') or 'Description')}}
    else:
        lookup = None

    # Layer-explicit scan targets: [{'layer': {id,name}, 'fields': [...]}].
    # When present they are authoritative; 'fields' is the display union.
    field_targets = []
    for target in section.get('field_targets') or []:
        ref = _layer_ref(target.get('layer'))
        fields = [str(f) for f in target.get('fields', []) if str(f).strip()]
        if ref and fields:
            field_targets.append({'layer': ref, 'fields': fields})

    fields = [str(f) for f in section.get('fields', []) if str(f).strip()]
    if field_targets and not fields:
        seen = set()
        for target in field_targets:
            for f in target['fields']:
                if f.lower() not in seen:
                    seen.add(f.lower())
                    fields.append(f)

    return {
        'id': section.get('id') or str(uuid.uuid4()),
        'title': section.get('title', ''),
        'layer': _layer_ref(section.get('layer')),
        'fields': fields,
        'field_targets': field_targets or None,
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
        'code_table_preview': config.get('code_table_preview', ''),
        'options': {
            'per_sheet_scan': bool(options.get('per_sheet_scan', True)),
            'filter_legend_by_map': bool(
                options.get('filter_legend_by_map', True)),
            'text_columns': _clamp_columns(options.get('text_columns', 2)),
        },
    }


def _clamp_columns(value):
    try:
        return min(4, max(1, int(value)))
    except (TypeError, ValueError):
        return 2


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

def _desc_embeds_code(desc, code):
    """True when the description already leads with the code as a word
    ('Chl - Chlorite' embeds 'Chl'; 'Sericite' does NOT embed 'Ser')."""
    dl, cl = desc.lower(), code.lower()
    if not cl or not dl.startswith(cl):
        return False
    return len(dl) == len(cl) or not dl[len(cl)].isalnum()


def format_entry_list(values, lookup_map=None):
    """Format values as a sorted list of 'Code — Description' entries.

    Case-variant codes (CY / Cy / cy) are merged: lookup keys are matched
    case-insensitively and the lookup's canonical casing is displayed.
    A description that already embeds its code ('Chl - Chlorite') is
    shown alone rather than doubled ('Chl — Chl - Chlorite').  Unmatched
    single-token codes are shown lowercase (matching the map labels);
    unmatched multi-word values are descriptions in their own right
    ('Hem - Hematite' in client deliverables) and keep their casing.
    """
    lookup_map = lookup_map or {}
    canonical = {}
    for code, desc in lookup_map.items():
        canonical.setdefault(str(code).lower(), (str(code), str(desc)))

    seen = set()
    entries = []
    for value in values:
        value_s = str(value)
        key = value_s.lower()
        if key in seen:
            continue
        seen.add(key)
        if key in canonical:
            code, desc = canonical[key]
            if desc and _desc_embeds_code(desc, code):
                entries.append(desc)
            elif desc and desc != code:
                entries.append(f"{code} {EM_DASH} {desc}")
            else:
                entries.append(code)
        elif ' ' in value_s.strip():
            entries.append(value_s.strip())
        else:
            entries.append(key)
    return sorted(entries, key=str.lower)


def format_entries(values, lookup_map=None):
    """Comma-joined form of format_entry_list (compact, single line)."""
    return ", ".join(format_entry_list(values, lookup_map))


def group_values_by_lookup(values, group_map, other_label='Other'):
    """Split values into {group: [values]} via a code→group map.

    Codes are matched case-insensitively.  Values whose code has no
    group land under other_label (omitted when empty).  The result
    feeds the subdivided section rendering (sub-header + indented
    entries), giving lookup-table 'Type' discrimination.
    """
    groups_ci = {str(code).lower(): str(group)
                 for code, group in (group_map or {}).items()
                 if is_valid_value(group)}
    grouped = {}
    ungrouped = []
    for value in values:
        group = groups_ci.get(str(value).lower())
        if group:
            grouped.setdefault(group, []).append(value)
        else:
            ungrouped.append(value)
    result = {group: grouped[group] for group in sorted(grouped)}
    if ungrouped:
        result[other_label] = ungrouped
    return result


def build_text_section_lines(sections, scan_results, lookup_maps=None,
                             extra_unmatched=None):
    """Build the structured text block: ordered [(title, [lines])].

    sections: normalised section dicts, in display order.
    scan_results: {section_id: [values]} or {section_id: {sub: [values]}}.
    lookup_maps: {section_id: {code: description}}.
    extra_unmatched: {section_id: values} — auto-mode overflow (values
        with no renderer symbol) listed under the section's heading.

    One 'Code — Description' entry per line; subdivided sections list a
    'Sub:' line followed by indented entries.  Headings are uppercased;
    layout labels render ModeFont so no rich text is used.
    """
    lookup_maps = lookup_maps or {}
    extra_unmatched = extra_unmatched or {}
    result = []

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

        title = section.get('title', '').upper() or 'LEGEND'
        lines = []
        if isinstance(data, dict):
            for sub_value in sorted(data):
                values = data[sub_value]
                if not values:
                    continue
                lines.append(f"{sub_value}:")
                lines.extend(f"  {entry}"
                             for entry in format_entry_list(values, lookup))
        else:
            lines.extend(format_entry_list(data, lookup))

        if lines:
            result.append((title, lines))

    return result


def text_from_section_lines(section_lines):
    """Plain text form of [(title, [lines])]: heading then one entry per
    line, blank line between sections.  Untitled sections emit lines only."""
    blocks = []
    for title, lines in section_lines:
        block_lines = ([title] if title else []) + list(lines)
        if block_lines:
            blocks.append("\n".join(block_lines))
    return "\n\n".join(blocks)


def format_text_sections(sections, scan_results, lookup_maps=None,
                         extra_unmatched=None):
    """Plain-text form of build_text_section_lines.

    Used for the panel preview box and the edit-override comparison.
    """
    return text_from_section_lines(build_text_section_lines(
        sections, scan_results, lookup_maps, extra_unmatched))


# ── Pre-generation text edits (per-entry overrides) ──────────────────

def _entry_key(line):
    """Pairing key for an entry line: the code before the em-dash."""
    s = line.strip()
    if EM_DASH in s:
        return s.split(EM_DASH, 1)[0].strip().lower()
    return s.lower()


def _looks_like_heading(line):
    return (line == line.upper() and EM_DASH not in line
            and not line.endswith(':') and len(line) > 1)


def derive_text_overrides(base_text, edited_text, headings=None):
    """Read the user's edits to the generated preview as corrections.

    Compares stripped lines of the generated text (base) against the
    edited box.  Deleted lines exclude that entry on every sheet; a
    deleted+added pair sharing a code key is a rewording; remaining
    additions are appended under the nearest preceding heading (or at
    the end when above all headings).  Deleting a heading suppresses
    the whole section.

    headings: known section titles (uppercase).  Heuristic detection
    (all-caps, no em-dash) backs it up for stale snapshots.

    Returns {} when the texts match (no overrides).
    """
    base_text = (base_text or '').strip()
    edited_text = (edited_text or '').strip()
    if edited_text == base_text:
        return {}
    if not base_text:
        # Never previewed: treat the typed text as appended manual lines
        lines = [l.strip() for l in edited_text.splitlines() if l.strip()]
        if not lines:
            return {}
        return {'removed': [], 'removed_headings': [], 'replaced': {},
                'added': {}, 'added_top': lines}

    base_lines = [l.strip() for l in base_text.splitlines() if l.strip()]
    edited_lines = [l.strip() for l in edited_text.splitlines() if l.strip()]
    base_set = set(base_lines)
    edited_set = set(edited_lines)

    heading_set = {h for h in (headings or []) if h}
    heading_set.update(l for l in base_lines if _looks_like_heading(l))

    removed_raw = [l for l in base_lines if l not in edited_set]
    added_raw = [l for l in edited_lines if l not in base_set]

    added_by_key = {}
    for line in added_raw:
        added_by_key.setdefault(_entry_key(line), line)

    removed = []
    removed_headings = []
    replaced = {}
    consumed_additions = set()
    for line in removed_raw:
        key = _entry_key(line)
        pair = added_by_key.get(key)
        if pair is not None and pair not in consumed_additions:
            replaced[line] = pair
            consumed_additions.add(pair)
        elif line in heading_set:
            removed_headings.append(line)
        else:
            removed.append(line)

    added = {}
    added_top = []
    current_heading = None
    for line in edited_lines:
        if line in heading_set:
            current_heading = line
            continue
        if line in added_raw and line not in consumed_additions:
            if current_heading:
                added.setdefault(current_heading, []).append(line)
            else:
                added_top.append(line)

    if not (removed or removed_headings or replaced or added or added_top):
        return {}
    return {
        'removed': removed,
        'removed_headings': removed_headings,
        'replaced': replaced,
        'added': added,
        'added_top': added_top,
    }


def apply_text_overrides(section_lines, overrides):
    """Apply derive_text_overrides corrections to [(title, [lines])]."""
    if not overrides:
        return section_lines
    removed = set(overrides.get('removed', []))
    removed_headings = set(overrides.get('removed_headings', []))
    replaced = overrides.get('replaced', {})
    added = overrides.get('added', {})

    result = []
    for title, lines in section_lines:
        if title in removed_headings:
            continue
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped in removed:
                continue
            if stripped in replaced:
                indent = line[:len(line) - len(line.lstrip())]
                new_lines.append(indent + replaced[stripped])
            else:
                new_lines.append(line)
        new_lines.extend(added.get(title, []))
        if new_lines:
            result.append((title, new_lines))

    added_top = overrides.get('added_top', [])
    if added_top:
        result.append(('', list(added_top)))
    return result
