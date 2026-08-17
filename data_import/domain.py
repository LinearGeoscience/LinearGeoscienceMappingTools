"""
The destination, described from itself.

Everything the importer needs to know about a mapping GeoPackage — its layers,
their geometry, every field's type/constraint/default, and for coded fields the
lookup table behind them plus the cascade that filters it — is read out of the
file at run time. There is no hardcoded schema and no hardcoded code list, so
the next template change does not silently break the importer.

Two facts about the current template look like bugs and are not: MineralCodes
keys on `Value` rather than `Code`, and TextureCodes' description column is
spelled `Desciption`. Both fall out of the widget configuration automatically;
tests/test_import_domain.py pins them so a future rename is noticed.

Pure python: sqlite3 + ElementTree only, no qgis import at module scope. That is
deliberate — the whole matching layer above this is unit-testable outside QGIS,
the same way scripts/inject_*.py read and rewrite the template's styles. The one
QGIS-backed entry point, read_project_model(), imports qgis inside the function.
"""

import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections import OrderedDict

try:
    from ..lgs_layers import CANONICAL_LAYERS, base_name, has_ordinal, same_layer
except ImportError:  # flat execution / pure test loader
    from lgs_layers import CANONICAL_LAYERS, base_name, has_ordinal, same_layer


# Non-spatial tables that are plumbing, never importable content.
SYSTEM_TABLES = frozenset({'layer_styles'})

# Columns that must never be carried across: per-file sequential ids and QGIS'
# own label-editing sidecar columns.
NEVER_COPY_FIELDS = frozenset({'fid', 'ogc_fid'})
NEVER_COPY_PREFIXES = ('auxiliary_storage_',)

# Description columns seen on lookup tables, best first. 'Desciption' is the
# real (misspelled) column on TextureCodes.
_DESC_COLUMNS = ('Description', 'Desciption', 'Name', 'Label', 'Value')

# Parses the two FilterExpression shapes the template uses on a cascading
# ValueRelation:
#     "Type" = current_value('Category')      -> cascade on a sibling field
#     "Type" IN ('Alteration', 'Weathering')  -> fixed subset of the table
_CASCADE_RE = re.compile(
    r'"(?P<col>[^"]+)"\s*=\s*current_value\(\s*[\'"](?P<field>[^\'"]+)[\'"]\s*\)',
    re.IGNORECASE)
_STATIC_IN_RE = re.compile(
    r'"(?P<col>[^"]+)"\s*IN\s*\((?P<values>[^)]*)\)', re.IGNORECASE)
_STATIC_EQ_RE = re.compile(
    r'"(?P<col>[^"]+)"\s*=\s*\'(?P<value>[^\']*)\'')

_LENGTH_RE = re.compile(r'\(\s*(\d+)')


# ── small helpers ─────────────────────────────────────────────────────

def normalise(value):
    """Collapse a value to its comparison form: trimmed, whitespace-collapsed.

    Trailing spaces are real in old code lists ('Fault - Normal ' shipped that
    way before the Aug-2026 audit), so every comparison goes through here rather
    than trusting the raw string.
    """
    if value is None:
        return ''
    return re.sub(r'\s+', ' ', str(value)).strip()


def fold(value):
    """Case-insensitive comparison key."""
    return normalise(value).casefold()


def is_blank(value):
    """True for nothing-at-all, including the literal string 'NULL'.

    Exports out of QField and out of the old append tool write the four
    characters N-U-L-L into empty text columns, so a test that only looks for
    None or '' treats 804 empty SampleType cells as a code nobody recognises.
    Same rule as hardcode_data.analysis.is_empty, deliberately.
    """
    if value is None:
        return True
    if hasattr(value, 'isNull'):
        try:
            if value.isNull():
                return True
        except Exception:
            pass
    text = normalise(value)
    return text == '' or text.upper() == 'NULL'


_SQUASH_RE = re.compile(r'[^a-z0-9]+')


def squash(value):
    """Comparison key with case, spacing and punctuation removed entirely.

    'Rockchip', 'ROCKCHIP' and 'Rock Chip' are the same sample type and get
    typed all three ways. This is still exact string work, not fuzzy matching,
    so it is safe to apply automatically — but only where it is unambiguous,
    which CodeDomain enforces by dropping any key two codes share. (Across the
    current template's seven code tables there are no such collisions;
    tests/test_import_domain.py checks that it stays true.)
    """
    return _SQUASH_RE.sub('', normalise(value).lower())


def description_tail(code, description):
    """Strip a leading '<code> - ' from a description.

    Lookup descriptions are written two ways in the same table: 'Fresh' and
    'Hem - Hematite'. The tail is the part that carries meaning, and it is what
    lets a value like 'Hematite' resolve to the code 'Hem'.
    """
    text = normalise(description)
    if not text:
        return ''
    match = re.match(r'^' + re.escape(normalise(code)) + r'\s*[-–—:]\s*(.+)$',
                     text, re.IGNORECASE)
    return normalise(match.group(1)) if match else text


def base_sql_type(declared):
    """Bucket a SQLite declared type into text/int/real/datetime/blob."""
    text = (declared or '').upper()
    if 'BLOB' in text:
        return 'blob'
    if 'DATE' in text or 'TIME' in text:
        return 'datetime'
    if 'INT' in text:
        return 'int'
    if any(token in text for token in ('REAL', 'FLOA', 'DOUB', 'NUMERIC', 'DECIMAL')):
        return 'real'
    return 'text'


def uuid_field_of(layer_spec):
    """The column that identifies a feature across GeoPackages, or ''."""
    for name in layer_spec.fields:
        if fold(name) == 'uuid':
            return name
    return ''


def is_copyable_field(name):
    """False for fid and QGIS auxiliary-storage columns."""
    lowered = (name or '').lower()
    if lowered in NEVER_COPY_FIELDS:
        return False
    return not any(lowered.startswith(prefix) for prefix in NEVER_COPY_PREFIXES)


# ── value objects ─────────────────────────────────────────────────────

class FieldSpec(object):
    """One column on a layer, with everything that decides how to fill it."""

    __slots__ = ('name', 'declared_type', 'base_type', 'max_length',
                 'notnull_strength', 'default_expression', 'apply_on_update',
                 'widget', 'alias', 'shadow_expression')

    def __init__(self, name, declared_type='TEXT', notnull_strength=0,
                 default_expression='', apply_on_update=False, widget='TextEdit',
                 alias='', shadow_expression=''):
        self.name = name
        self.declared_type = declared_type or 'TEXT'
        self.base_type = base_sql_type(declared_type)
        match = _LENGTH_RE.search(declared_type or '')
        self.max_length = int(match.group(1)) if match else None
        self.notnull_strength = notnull_strength
        self.default_expression = default_expression or ''
        self.apply_on_update = bool(apply_on_update)
        self.widget = widget or 'TextEdit'
        self.alias = alias or ''
        # Some columns exist BOTH as a real column and as a QML expression
        # field of the same name — Basemap's Lithology1Code is a real TEXT
        # column and is re-declared as `"Lithology1"`. The form shows the
        # expression's value while the stored column can be empty, so the
        # expression is the template telling us what the column should hold.
        self.shadow_expression = shadow_expression or ''

    @property
    def is_expression_field(self):
        return bool(self.shadow_expression)

    @property
    def required(self):
        """True when the form treats an empty value as invalid."""
        return self.notnull_strength > 0

    def __repr__(self):
        return 'FieldSpec({0!r}, {1})'.format(self.name, self.declared_type)


class CodeDomain(object):
    """The set of legal values for one coded field, and how to search it.

    Built either from a ValueRelation (a real lookup table, optionally filtered
    by a parent field) or from a ValueMap (an inline list). `entries` is
    (code, description, parent) triples; parent is '' when the table has no
    grouping column.
    """

    __slots__ = ('field', 'table', 'key_column', 'desc_column', 'parent_column',
                 'parent_field', 'allowed_parents', 'entries', 'source_kind',
                 '_by_code', '_by_desc', '_by_tail', '_by_squash', '_parent_of')

    def __init__(self, field, entries, table=None, key_column='Code',
                 desc_column='', parent_column=None, parent_field=None,
                 allowed_parents=(), source_kind='ValueRelation'):
        self.field = field
        self.table = table
        self.key_column = key_column
        self.desc_column = desc_column
        self.parent_column = parent_column
        self.parent_field = parent_field
        self.allowed_parents = tuple(allowed_parents)
        self.source_kind = source_kind
        self.entries = tuple(entries)
        self._index()

    def _index(self):
        self._by_code = {}
        self._by_desc = {}
        self._by_tail = {}
        self._parent_of = {}
        squash_hits = {}
        for code, description, parent in self.entries:
            key = fold(code)
            if not key:
                continue
            self._by_code.setdefault(key, normalise(code))
            self._parent_of.setdefault(key, normalise(parent))
            if description:
                self._by_desc.setdefault(fold(description), normalise(code))
            tail = description_tail(code, description)
            if tail:
                self._by_tail.setdefault(fold(tail), normalise(code))
            for text in (code, tail):
                squashed = squash(text)
                if squashed:
                    squash_hits.setdefault(squashed, set()).add(normalise(code))
        # Only unambiguous squashed keys survive: if two codes collapse to the
        # same key, guessing between them is not this tier's job.
        self._by_squash = {key: next(iter(codes))
                           for key, codes in squash_hits.items()
                           if len(codes) == 1}

    # -- lookups ------------------------------------------------------

    @property
    def codes(self):
        return [code for code, _desc, _parent in self.entries]

    def has_code(self, value):
        return fold(value) in self._by_code

    def canonical_code(self, value):
        """The code as spelled in the table, for a case/space-insensitive hit."""
        return self._by_code.get(fold(value))

    def code_for_description(self, value):
        key = fold(value)
        return self._by_desc.get(key) or self._by_tail.get(key)

    def code_for_squashed(self, value):
        """Unambiguous hit ignoring case, spacing and punctuation entirely."""
        return self._by_squash.get(squash(value))

    def parent_of(self, code):
        """The grouping value ('Structural', 'Lithology', ...) for a code."""
        return self._parent_of.get(fold(code), '')

    def description_of(self, code):
        key = fold(code)
        for entry_code, description, _parent in self.entries:
            if fold(entry_code) == key:
                return normalise(description)
        return ''

    def search_pool(self):
        """{comparison key: code} across codes, descriptions and tails.

        Used for fuzzy suggestion only — never for automatic resolution.
        """
        pool = {}
        pool.update(self._by_tail)
        pool.update(self._by_desc)
        pool.update(self._by_code)
        return pool

    def add_entry(self, code, description='', parent=''):
        """Register a code added during this import.

        Without this a brand-new code has no parent as far as the cascade
        back-fill is concerned, so its features arrive with the child code set
        and Category / Type / TypeLith1 empty — exactly the breakage the
        back-fill exists to prevent.
        """
        if self.has_code(code):
            return False
        self.entries = self.entries + ((normalise(code), normalise(description),
                                        normalise(parent)),)
        self._index()
        return True

    def entries_by_parent(self):
        """OrderedDict parent -> [(code, description)], for grouped pickers."""
        grouped = OrderedDict()
        for code, description, parent in self.entries:
            grouped.setdefault(normalise(parent), []).append(
                (normalise(code), normalise(description)))
        return grouped

    def __repr__(self):
        return 'CodeDomain({0!r}, {1} codes from {2})'.format(
            self.field, len(self.entries), self.table or self.source_kind)


class LayerSpec(object):
    """One spatial layer in a mapping GeoPackage."""

    __slots__ = ('name', 'geometry_type', 'has_z', 'has_m', 'srs_id', 'fields',
                 'code_domains', 'feature_count')

    def __init__(self, name, geometry_type='', has_z=False, has_m=False,
                 srs_id=None, fields=None, code_domains=None, feature_count=0):
        self.name = name
        self.geometry_type = (geometry_type or '').upper()
        self.has_z = has_z
        self.has_m = has_m
        self.srs_id = srs_id
        self.fields = fields or OrderedDict()
        self.code_domains = code_domains or OrderedDict()
        self.feature_count = feature_count

    @property
    def base_name(self):
        return base_name(self.name)

    @property
    def field_names(self):
        return list(self.fields.keys())

    def copyable_field_names(self):
        return [name for name in self.fields if is_copyable_field(name)]

    def field(self, name):
        return self.fields.get(name)

    def domain(self, field_name):
        return self.code_domains.get(field_name)

    def child_fields_of(self, parent_field):
        """Coded fields whose cascade is driven by `parent_field`."""
        return [name for name, domain in self.code_domains.items()
                if domain.parent_field and domain.parent_field == parent_field]

    def __repr__(self):
        return 'LayerSpec({0!r}, {1}, {2} fields)'.format(
            self.name, self.geometry_type, len(self.fields))


class MappingModel(object):
    """A whole mapping GeoPackage (or project): layers plus lookup tables.

    Used for both ends of an import. The destination end supplies the code
    domains; a source end that happens to be an LGS project supplies its OWN
    lookup tables, which is what makes rename detection possible — 'FAP - Aplite'
    on one side and 'FAPL - Aplite' on the other is a rename, not a coincidence.
    """

    def __init__(self, path='', layers=None, tables=None, label='', srs=None):
        self.path = path
        self.layers = layers or OrderedDict()
        self.tables = tables or OrderedDict()   # name -> [(code, description, parent)]
        self.label = label or (os.path.basename(path) if path else '')
        self.srs = srs or {}                    # srs_id -> 'EPSG:7850'

    def crs_of(self, layer_name):
        """'EPSG:7850' for a layer, or '' when the file does not say."""
        spec = self.layers.get(layer_name)
        if spec is None:
            return ''
        return self.srs.get(spec.srs_id, '')

    def primary_crs(self):
        """The CRS shared by the spatial layers, or '' when they disagree."""
        found = {self.crs_of(name) for name in self.layers}
        found.discard('')
        return found.pop() if len(found) == 1 else ''

    # -- access -------------------------------------------------------

    def layer(self, name):
        return self.layers.get(name)

    def find_layer(self, canonical):
        """Resolve a canonical layer name, tolerating a different ordinal."""
        if canonical in self.layers:
            return self.layers[canonical]
        for name, spec in self.layers.items():
            if has_ordinal(name) and same_layer(name, canonical):
                return spec
        return None

    @property
    def lookup_table_names(self):
        return [name for name in self.tables if name not in SYSTEM_TABLES]

    def table_entries(self, table_name):
        """(code, description, parent) rows for a lookup table, case-tolerant."""
        if table_name in self.tables:
            return self.tables[table_name]
        folded = fold(table_name)
        for name, rows in self.tables.items():
            if fold(name) == folded:
                return rows
        return []

    def describe_code(self, table_name, code):
        """Description of a code in one of THIS model's own lookup tables."""
        target = fold(code)
        for entry_code, description, _parent in self.table_entries(table_name):
            if fold(entry_code) == target:
                return normalise(description)
        return ''

    # -- template identification --------------------------------------

    def fingerprint(self):
        """Feature flags standing in for the version marker the gpkg lacks.

        The template carries no version column (gpkg user_version is the spec
        version, and gpkg_metadata records the QGIS build that last wrote the
        style), so capability is probed instead. Cheapest, most decisive first.
        """
        flags = set()
        names = set(self.layers)
        if any(name == '2 - Linework' for name in names):
            flags.add('layer_order_swapped')
        linework = self.find_layer('2 - Linework')
        basemap = self.find_layer('4 - Basemap')
        overlay = self.find_layer('3 - Overlay')
        if 'SampleTypeCodes' in self.tables:
            flags.add('sample_type_codes')
        if 'LineworkCategories' in self.tables:
            flags.add('linework_categories')
        if linework is not None:
            if 'Category' in linework.fields:
                flags.add('linework_category_field')
            if 'Width_cm' in linework.fields:
                flags.add('vein_detail')
            if 'Mineral1Pct' in linework.fields:
                flags.add('per_mineral_percent')
        if overlay is not None and 'Intensity' in overlay.fields:
            flags.add('overlay_intensity')
        if basemap is not None:
            if 'Lith1Mineral3' in basemap.fields:
                flags.add('basemap_mineral3')
            if 'Lith1Feature' in basemap.fields or 'Float' in basemap.fields:
                flags.add('pre_audit_basemap')
        if any('Confidence' in spec.fields for spec in self.layers.values()):
            flags.add('confidence')
        if any('Elevation' in spec.fields for spec in self.layers.values()):
            flags.add('elevation')
        return flags

    def template_summary(self):
        """One human sentence naming the vintage, for both ends of an import."""
        flags = self.fingerprint()
        if not self.is_lgs_template:
            return 'Mapping data (not built from an LGS template)'
        missing = []
        if 'layer_order_swapped' not in flags:
            missing.append('layer renumbering')
        if 'linework_category_field' not in flags:
            missing.append('Linework Category')
        if 'confidence' not in flags:
            missing.append('Confidence')
        if 'per_mineral_percent' not in flags:
            missing.append('mineral percentages')
        if not missing:
            return 'LGS template, current (Aug 2026)'
        if 'pre_audit_basemap' in flags:
            return ('LGS template, pre-audit (before Aug 2026) — layer numbering '
                    'and many codes have changed since')
        return 'LGS template, older — missing {0}'.format(', '.join(missing))

    @property
    def is_lgs_template(self):
        """True when at least two of the four canonical layers are present."""
        found = sum(1 for canonical in CANONICAL_LAYERS
                    if self.find_layer(canonical) is not None)
        return found >= 2

    def __repr__(self):
        return 'MappingModel({0!r}, {1} layers, {2} tables)'.format(
            self.label, len(self.layers), len(self.tables))


# ── GeoPackage reader ─────────────────────────────────────────────────

def _connect(path):
    """Read-only connection. mode=ro keeps a live QGIS session's file safe."""
    return sqlite3.connect('file:{0}?mode=ro'.format(path.replace('?', '%3f')),
                           uri=True)


def _style_qml(connection, table_name):
    """The QML for a table, preferring the row flagged as the default style.

    layer_styles routinely holds several rows per table (QGIS writes a
    lowercased duplicate), so pick deliberately rather than taking the first.
    """
    try:
        rows = connection.execute(
            "SELECT styleQML, useAsDefault FROM layer_styles "
            "WHERE f_table_name = ? OR lower(f_table_name) = lower(?)",
            (table_name, table_name)).fetchall()
    except sqlite3.Error:
        return None
    if not rows:
        return None
    rows.sort(key=lambda row: (1 if row[1] else 0, len(row[0] or '')), reverse=True)
    return rows[0][0]


def _option_map(element):
    """Flatten an <Option type="Map"> into {name: value} for scalar entries."""
    values = {}
    for option in element.iter('Option'):
        name = option.get('name')
        if name is not None and option.get('value') is not None:
            values.setdefault(name, option.get('value'))
    return values


def _value_map_entries(edit_widget):
    """ValueMap's <Option name="map" type="List"> -> [(code, label, '')].

    Both shapes occur in the wild: a List of single-entry Maps (what the
    template uses) and a flat Map. Order is preserved — it is the order the
    dropdown shows.
    """
    entries = []
    for option in edit_widget.iter('Option'):
        if option.get('name') != 'map':
            continue
        if option.get('type') == 'List':
            for item in option:
                for pair in item:
                    label = pair.get('name')
                    code = pair.get('value')
                    if label is not None and code is not None:
                        entries.append((code, label, ''))
        else:
            for pair in option:
                label = pair.get('name')
                code = pair.get('value')
                if label is not None and code is not None:
                    entries.append((code, label, ''))
        break
    return entries


def _parse_filter(expression):
    """(parent_column, parent_field, allowed_parents) from a FilterExpression."""
    text = (expression or '').strip()
    if not text:
        return None, None, ()
    cascade = _CASCADE_RE.search(text)
    if cascade:
        return cascade.group('col'), cascade.group('field'), ()
    static_in = _STATIC_IN_RE.search(text)
    if static_in:
        values = tuple(normalise(part).strip('\'"')
                       for part in static_in.group('values').split(','))
        return static_in.group('col'), None, tuple(v for v in values if v)
    static_eq = _STATIC_EQ_RE.search(text)
    if static_eq:
        return static_eq.group('col'), None, (static_eq.group('value'),)
    return None, None, ()


def _resolve_table(connection, wanted, known_tables):
    """Match a widget's LayerName against a real table, case-insensitively.

    The widget's LayerSource is deliberately ignored: nearly every one in the
    shipped template still points at somebody else's old project on a drive
    that is not this one. gpkg_contents is the only trustworthy source.
    """
    if not wanted:
        return None
    if wanted in known_tables:
        return wanted
    folded = fold(wanted)
    for name in known_tables:
        if fold(name) == folded:
            return name
    return None


def _table_columns(connection, table_name):
    try:
        return [row[1] for row in connection.execute(
            'PRAGMA table_info("{0}")'.format(table_name.replace('"', '""')))]
    except sqlite3.Error:
        return []


def _pick_description_column(columns, key_column, declared_value):
    """The column that actually carries meaning for matching.

    When a widget displays the code itself (Linework Type is Key=Code,
    Value=Code) the declared value column is useless for matching, so fall back
    to the table's real description column.
    """
    if declared_value and declared_value != key_column and declared_value in columns:
        return declared_value
    for candidate in _DESC_COLUMNS:
        if candidate in columns and candidate != key_column:
            return candidate
    return declared_value if declared_value in columns else ''


def _read_lookup_rows(connection, table_name, key_column, desc_column,
                      parent_column):
    """(code, description, parent) triples from a lookup table, in table order."""
    columns = _table_columns(connection, table_name)
    if key_column not in columns:
        return []
    select = ['"{0}"'.format(key_column)]
    select.append('"{0}"'.format(desc_column) if desc_column in columns else "''")
    select.append('"{0}"'.format(parent_column)
                  if parent_column and parent_column in columns else "''")
    try:
        rows = connection.execute(
            'SELECT {0} FROM "{1}"'.format(
                ', '.join(select), table_name.replace('"', '""'))).fetchall()
    except sqlite3.Error:
        return []
    return [(normalise(code), normalise(desc), normalise(parent))
            for code, desc, parent in rows if normalise(code)]


def _parse_qml(qml_text):
    """{'widgets', 'defaults', 'constraints', 'aliases', 'expression_fields'}."""
    parsed = {'widgets': {}, 'defaults': {}, 'constraints': {},
              'aliases': {}, 'expression_fields': {}}
    if not qml_text:
        return parsed
    try:
        root = ET.fromstring(qml_text)
    except ET.ParseError:
        return parsed

    for configuration in root.iter('fieldConfiguration'):
        for field in configuration:
            name = field.get('name')
            edit_widget = field.find('editWidget')
            if name is None or edit_widget is None:
                continue
            parsed['widgets'][name] = {
                'type': edit_widget.get('type') or 'TextEdit',
                'config': _option_map(edit_widget),
                'value_map': (_value_map_entries(edit_widget)
                              if edit_widget.get('type') == 'ValueMap' else []),
            }

    for default in root.iter('default'):
        name = default.get('field')
        if name is not None:
            parsed['defaults'][name] = (default.get('expression') or '',
                                        default.get('applyOnUpdate') == '1')

    for constraints in root.iter('constraints'):
        for constraint in constraints:
            name = constraint.get('field')
            if name is not None:
                try:
                    strength = int(constraint.get('notnull_strength') or 0)
                except ValueError:
                    strength = 0
                parsed['constraints'][name] = strength

    # <alias name="Width (cm)" index="16" field="Width_cm" /> — name is the
    # human label and is usually empty.
    for aliases in root.iter('aliases'):
        for alias in aliases:
            field_name = alias.get('field')
            label = alias.get('name')
            if field_name and label:
                parsed['aliases'][field_name] = label

    for expression_fields in root.iter('expressionfields'):
        for field in expression_fields:
            name = field.get('name')
            if name:
                parsed['expression_fields'][name] = field.get('expression') or ''

    return parsed


def read_gpkg_model(path):
    """Build a MappingModel from a GeoPackage on disk. Read-only, no QGIS.

    Raises IOError when the file is missing or is not a GeoPackage.
    """
    if not path or not os.path.exists(path):
        raise IOError('GeoPackage not found: {0}'.format(path))

    connection = _connect(path)
    try:
        try:
            contents = connection.execute(
                'SELECT table_name, data_type FROM gpkg_contents ORDER BY rowid'
            ).fetchall()
        except sqlite3.Error as error:
            raise IOError('Not a GeoPackage: {0} ({1})'.format(path, error))

        feature_tables = [name for name, kind in contents if kind == 'features']
        attribute_tables = [name for name, kind in contents if kind != 'features']

        geometry = {}
        try:
            for row in connection.execute(
                    'SELECT table_name, geometry_type_name, z, m, srs_id '
                    'FROM gpkg_geometry_columns'):
                geometry[row[0]] = row[1:]
        except sqlite3.Error:
            pass

        # srs_id is a GeoPackage-local id, not an EPSG code — 29030 in the
        # shipped template is EPSG:7851. Resolve it once here.
        srs = {}
        try:
            for srs_id, organisation, code in connection.execute(
                    'SELECT srs_id, organization, organization_coordsys_id '
                    'FROM gpkg_spatial_ref_sys'):
                if organisation and code and int(code) > 0:
                    srs[srs_id] = '{0}:{1}'.format(
                        str(organisation).upper(), code)
        except sqlite3.Error:
            pass

        # Lookup tables first: a layer's CodeDomain needs their rows.
        raw_tables = OrderedDict()
        for name in attribute_tables:
            if name in SYSTEM_TABLES:
                continue
            columns = _table_columns(connection, name)
            key_column = 'Code' if 'Code' in columns else (
                'Value' if 'Value' in columns else (columns[1] if len(columns) > 1
                                                    else (columns[0] if columns else '')))
            desc_column = _pick_description_column(columns, key_column, '')
            parent_column = 'Type' if 'Type' in columns and 'Type' != key_column else None
            raw_tables[name] = _read_lookup_rows(
                connection, name, key_column, desc_column, parent_column)

        layers = OrderedDict()
        for table_name in feature_tables:
            layers[table_name] = _read_layer(
                connection, table_name, geometry.get(table_name, ('', 0, 0, None)),
                attribute_tables, raw_tables)

        return MappingModel(path=path, layers=layers, tables=raw_tables, srs=srs)
    finally:
        connection.close()


def _read_layer(connection, table_name, geometry_info, attribute_tables,
                raw_tables):
    """One LayerSpec: columns from PRAGMA, behaviour from the stored QML."""
    geometry_type, has_z, has_m, srs_id = geometry_info
    qml = _parse_qml(_style_qml(connection, table_name))

    fields = OrderedDict()
    for row in connection.execute(
            'PRAGMA table_info("{0}")'.format(table_name.replace('"', '""'))):
        name, declared = row[1], row[2]
        if declared and declared.upper() in ('POINT', 'LINESTRING', 'POLYGON',
                                             'MULTIPOINT', 'MULTILINESTRING',
                                             'MULTIPOLYGON', 'GEOMETRY',
                                             'GEOMCOLLECTION'):
            continue  # the geometry column, not an attribute
        widget = qml['widgets'].get(name, {})
        default_expression, apply_on_update = qml['defaults'].get(name, ('', False))
        fields[name] = FieldSpec(
            name=name,
            declared_type=declared,
            notnull_strength=qml['constraints'].get(name, 0),
            default_expression=default_expression,
            apply_on_update=apply_on_update,
            widget=widget.get('type', 'TextEdit'),
            alias=qml['aliases'].get(name, ''),
            shadow_expression=qml['expression_fields'].get(name, ''),
        )

    code_domains = OrderedDict()
    for name, widget in qml['widgets'].items():
        if name not in fields:
            continue
        domain = _build_domain(connection, name, widget, attribute_tables,
                               raw_tables)
        if domain is not None:
            code_domains[name] = domain

    try:
        count = connection.execute(
            'SELECT COUNT(*) FROM "{0}"'.format(
                table_name.replace('"', '""'))).fetchone()[0]
    except sqlite3.Error:
        count = 0

    return LayerSpec(name=table_name, geometry_type=geometry_type,
                     has_z=bool(has_z), has_m=bool(has_m), srs_id=srs_id,
                     fields=fields, code_domains=code_domains,
                     feature_count=count)


def _build_domain(connection, field_name, widget, attribute_tables, raw_tables):
    """A CodeDomain from one field's widget configuration, or None."""
    kind = widget.get('type')

    if kind == 'ValueMap':
        entries = widget.get('value_map') or []
        if not entries:
            return None
        return CodeDomain(field=field_name, entries=entries, table=None,
                          key_column='', desc_column='',
                          source_kind='ValueMap')

    if kind != 'ValueRelation':
        return None

    config = widget.get('config', {})
    table = _resolve_table(connection, config.get('LayerName'), attribute_tables)
    if table is None:
        return None

    columns = _table_columns(connection, table)
    key_column = config.get('Key') or 'Code'
    if key_column not in columns:
        return None
    desc_column = _pick_description_column(columns, key_column,
                                           config.get('Value') or '')
    parent_column, parent_field, allowed = _parse_filter(
        config.get('FilterExpression'))
    if parent_column and parent_column not in columns:
        parent_column, parent_field, allowed = None, None, ()
    if parent_column is None and 'Type' in columns and 'Type' != key_column:
        # Table is grouped even though this widget does not filter on it —
        # still worth knowing, because it is what back-fills the parent field.
        parent_column = 'Type'

    entries = _read_lookup_rows(connection, table, key_column, desc_column,
                                parent_column)
    if allowed:
        allowed_folded = {fold(value) for value in allowed}
        entries = [entry for entry in entries if fold(entry[2]) in allowed_folded]
    if not entries:
        return None

    return CodeDomain(field=field_name, entries=entries, table=table,
                      key_column=key_column, desc_column=desc_column,
                      parent_column=parent_column, parent_field=parent_field,
                      allowed_parents=allowed, source_kind='ValueRelation')


# ── project reader ────────────────────────────────────────────────────

def read_project_model(project=None, layers=None):
    """Build a MappingModel from layers loaded in QGIS.

    Used when the destination is the open project rather than a file, and when
    the source is a database/filtered layer. Falls through to read_gpkg_model()
    for any layer backed by a GeoPackage so the file's own lookup tables come
    along; otherwise the model is layer-only (no code domains), which is the
    right answer for a PostGIS source.
    """
    from qgis.core import QgsProject, Qgis

    project = project or QgsProject.instance()
    candidates = list(layers) if layers is not None else [
        layer for layer in project.mapLayers().values()
        if layer.type() == Qgis.LayerType.Vector]

    gpkg_paths = OrderedDict()
    for layer in candidates:
        path = gpkg_path_of(layer)
        if path:
            gpkg_paths.setdefault(path, []).append(layer)

    merged = MappingModel(label='Current project')
    for path in gpkg_paths:
        try:
            file_model = read_gpkg_model(path)
        except IOError:
            continue
        if not merged.path:
            merged.path = path
        for name, spec in file_model.layers.items():
            merged.layers.setdefault(name, spec)
        for name, rows in file_model.tables.items():
            merged.tables.setdefault(name, rows)

    # Layers with no GeoPackage behind them (PostGIS, memory, delimited text)
    # are described directly from the provider.
    for layer in candidates:
        if not layer.isSpatial():
            continue
        if gpkg_path_of(layer):
            continue
        merged.layers.setdefault(layer.name(), _spec_from_qgs_layer(layer))
    return merged


def gpkg_path_of(layer):
    """The .gpkg file behind a layer, or '' when it is not GeoPackage-backed."""
    try:
        if layer.providerType() != 'ogr':
            return ''
        source = layer.source()
    except Exception:
        return ''
    path = source.split('|', 1)[0]
    return path if path.lower().endswith('.gpkg') and os.path.exists(path) else ''


def layer_table_name(layer):
    """The table a GeoPackage-backed layer points at, else its display name."""
    try:
        source = layer.source()
    except Exception:
        return layer.name()
    match = re.search(r'layername=([^|]+)', source)
    return match.group(1) if match else layer.name()


def _spec_from_qgs_layer(layer):
    """LayerSpec for a non-GeoPackage layer, read from the provider + widgets."""
    from qgis.core import QgsWkbTypes

    wkb = layer.wkbType()
    fields = OrderedDict()
    code_domains = OrderedDict()
    for index, field in enumerate(layer.fields()):
        name = field.name()
        default = layer.defaultValueDefinition(index)
        try:
            expression = default.expression() or ''
            apply_on_update = default.applyOnUpdate()
        except Exception:
            expression, apply_on_update = '', False
        fields[name] = FieldSpec(
            name=name,
            declared_type=field.typeName() or 'TEXT',
            notnull_strength=0,
            default_expression=expression,
            apply_on_update=apply_on_update,
            widget=_widget_type(layer, index),
            alias=layer.attributeAlias(index) or '',
        )
    return LayerSpec(
        name=layer.name(),
        geometry_type=QgsWkbTypes.displayString(
            QgsWkbTypes.flatType(wkb)).upper(),
        has_z=QgsWkbTypes.hasZ(wkb),
        has_m=QgsWkbTypes.hasM(wkb),
        fields=fields,
        code_domains=code_domains,
        feature_count=max(layer.featureCount(), 0),
    )


def _widget_type(layer, index):
    try:
        return layer.editorWidgetSetup(index).type() or 'TextEdit'
    except Exception:
        return 'TextEdit'
