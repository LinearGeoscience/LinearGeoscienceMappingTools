"""
Which source column feeds which destination column.

Five exact tiers before anything fuzzy is offered, and a target may only be
claimed once — that last rule is what stops a legacy `Type` column on an old
Basemap from stealing `TypeLith1` away from the real `TypeLith1` beside it.

The destination schema is immutable. A source column with nowhere to go is
dropped, or folded into Comments if the user says so; it is never added to the
destination as a new column. Doing that is what put `data_added_timestamp` and
`data_added_batch_id` onto two of the four layers of the shipped template and
nowhere else.
"""

import re
from collections import OrderedDict

try:
    from ..lgs_layers import base_name
except ImportError:  # top-level import, or the pure test loader
    from lgs_layers import base_name

try:
    from .domain import fold, is_copyable_field, normalise
    from . import fuzzy
except ImportError:  # flat execution / pure test loader
    from domain import fold, is_copyable_field, normalise
    import fuzzy


EXACT = 'exact'
ALIAS = 'alias'
SUGGESTED = 'suggested'
UNMATCHED = 'unmatched'
IGNORED = 'ignored'

# What to do with a source column that has no destination.
DROP = 'drop'
TO_COMMENTS = 'comments'

# Renames the plugin itself already knows about, applied automatically.
# SubType1Code -> MappedSubType1 is hardcode_data.LAYER_CONFIGS' own copy
# operation, so the pairing is authoritative rather than a guess.
FIELD_ALIASES = {
    'subtype1code': 'MappedSubType1',
    'structurelegend': 'Legend',
}

# Weaker pairings: pre-selected but flagged for confirmation, because the
# meaning is a judgement call. Keyed by destination base layer name.
FIELD_HINTS = {
    'basemap': {
        'type': 'TypeLith1',
    },
}

# Retired columns whose content is free-text worth keeping. Defaulting these to
# Comments rather than to a coded field is a deliberate reading of the real
# data: Lith1Feature holds notes like 'Chl-k altered', 'After peg?' and
# 'Po, chl-k altered'. Pointing that at Lith1Texture1 would have dumped nine
# free-text phrases into the Codes step for a decision nobody can make well.
COMMENT_DEFAULTS = frozenset({'lith1feature', 'lith2feature', 'float'})

# Columns that exist to be filled by another tool after the import, so
# "empty after import" is the expected state and worth saying out loud.
_FILLED_LATER = {
    'mappedeasting': 'Hardcode Data',
    'mappednorthing': 'Hardcode Data',
    'mappedcrs': 'Hardcode Data',
    'mappedscale': 'Hardcode Data',
    'mappedsubtype1': 'Hardcode Data',
    'mappedlithology1': 'Hardcode Data',
    'mappedlithology2': 'Hardcode Data',
    'projectid': 'Hardcode Data',
    'legend': 'Hardcode Data',
}

_ALNUM_RE = re.compile(r'[^a-z0-9]+')

# Numeric-suffix family, e.g. Mineral2 -> ('mineral', 2).
_FAMILY_RE = re.compile(r'^(.*?)(\d*)$')

_FUZZY_FLOOR = 82


def compare_key(name):
    """Field name reduced for comparison: lowercase, punctuation stripped.

    Makes 'Date&Time', 'date_time' and 'DateTime' the same field, which they
    are in every export of this data that exists.
    """
    return _ALNUM_RE.sub('', (name or '').lower())


def family_of(name):
    """('mineral', 2) for 'Mineral2'; ('comments', 0) for 'Comments'."""
    match = _FAMILY_RE.match(compare_key(name))
    stem, digits = match.group(1), match.group(2)
    return stem, int(digits) if digits else 0


def types_compatible(source_field, target_field):
    """(ok, note) for writing a source value into a destination column."""
    if source_field is None or target_field is None:
        return True, ''
    source_type = source_field.base_type
    target_type = target_field.base_type
    if source_type == target_type:
        return True, ''
    if target_type == 'text':
        return True, ''
    if source_type == 'text' and target_type in ('int', 'real', 'datetime'):
        return True, 'text will be converted to {0}'.format(target_type)
    if source_type in ('int', 'real') and target_type in ('int', 'real'):
        if source_type == 'real' and target_type == 'int':
            return True, 'decimals will be rounded'
        return True, ''
    if source_type == 'datetime' and target_type == 'text':
        return True, ''
    return False, '{0} cannot be written to {1}'.format(source_type, target_type)


class FieldMatch(object):
    """One source column's destination, or the reason it has none."""

    __slots__ = ('source_name', 'target_name', 'status', 'reason',
                 'candidates', 'unmatched_action', 'type_note', 'type_ok')

    def __init__(self, source_name, target_name=None, status=UNMATCHED,
                 reason='', candidates=(), unmatched_action=DROP,
                 type_note='', type_ok=True):
        self.source_name = source_name
        self.target_name = target_name
        self.status = status
        self.reason = reason
        self.candidates = list(candidates)
        self.unmatched_action = unmatched_action
        self.type_note = type_note
        self.type_ok = type_ok

    @property
    def is_mapped(self):
        return bool(self.target_name) and self.status != IGNORED

    @property
    def needs_review(self):
        return self.status == SUGGESTED or not self.type_ok

    def __repr__(self):
        return 'FieldMatch({0!r} -> {1!r}, {2})'.format(
            self.source_name, self.target_name, self.status)


class TargetFieldNote(object):
    """A destination column no source field feeds, and what will fill it."""

    __slots__ = ('name', 'how', 'detail', 'required')

    def __init__(self, name, how, detail='', required=False):
        self.name = name
        self.how = how              # 'default' | 'derived' | 'later' | 'empty'
        self.detail = detail
        self.required = required

    def __repr__(self):
        return 'TargetFieldNote({0!r}, {1})'.format(self.name, self.how)


class LayerFieldPlan(object):
    """Every field decision for one source layer -> destination layer pairing."""

    def __init__(self, source_layer, target_layer, matches, target_notes):
        self.source_layer = source_layer
        self.target_layer = target_layer
        self.matches = matches          # OrderedDict source_field -> FieldMatch
        self.target_notes = target_notes  # OrderedDict target_field -> note

    def mapping(self):
        """{source_field: target_field} for the fields that will be written."""
        return OrderedDict(
            (name, match.target_name)
            for name, match in self.matches.items() if match.is_mapped)

    def dropped(self):
        return [name for name, match in self.matches.items()
                if match.status == UNMATCHED and match.unmatched_action == DROP]

    def to_comments(self):
        return [name for name, match in self.matches.items()
                if match.status == UNMATCHED
                and match.unmatched_action == TO_COMMENTS]

    def review_count(self):
        return sum(1 for match in self.matches.values() if match.needs_review)

    def __repr__(self):
        return 'LayerFieldPlan({0!r} -> {1!r}, {2} mapped)'.format(
            self.source_layer, self.target_layer, len(self.mapping()))


def _hint_table(target_layer_name):
    return FIELD_HINTS.get(fold(base_name(target_layer_name)), {})


def match_fields(source_spec, target_spec, seeded=None):
    """Pair a source layer's columns with a destination layer's columns.

    `seeded` is {source_field: target_field or ''} from a saved profile; an
    empty string means "deliberately unmapped" and is honoured as such.
    """
    seeded = seeded or {}
    hints = _hint_table(target_spec.name)

    source_fields = [name for name in source_spec.fields]
    target_fields = [name for name in target_spec.fields
                     if is_copyable_field(name)]

    target_by_exact = {name: name for name in target_fields}
    target_by_key = {}
    for name in target_fields:
        target_by_key.setdefault(compare_key(name), name)

    matches = OrderedDict()
    claimed = set()

    def claim(source_name, target_name, status, reason):
        source_field = source_spec.field(source_name)
        target_field = target_spec.field(target_name)
        ok, note = types_compatible(source_field, target_field)
        matches[source_name] = FieldMatch(
            source_name, target_name, status, reason,
            type_note=note, type_ok=ok)
        claimed.add(target_name)

    # Bookkeeping columns never travel.
    pending = []
    for name in source_fields:
        if not is_copyable_field(name):
            matches[name] = FieldMatch(name, None, IGNORED,
                                       'internal column, not imported')
        else:
            pending.append(name)

    # 0 — a saved profile wins outright.
    remaining = []
    for name in pending:
        if name not in seeded:
            remaining.append(name)
            continue
        target = seeded[name]
        if not target:
            matches[name] = FieldMatch(name, None, UNMATCHED,
                                       'unmapped in saved profile')
        elif target in target_by_exact and target not in claimed:
            claim(name, target, ALIAS, 'from saved profile')
        else:
            remaining.append(name)
    pending = remaining

    # 1 — identical names.
    remaining = []
    for name in pending:
        if name in target_by_exact and name not in claimed:
            claim(name, name, EXACT, 'same name')
        else:
            remaining.append(name)
    pending = remaining

    # 2 — same name once case and punctuation are ignored.
    remaining = []
    for name in pending:
        target = target_by_key.get(compare_key(name))
        if target and target not in claimed:
            claim(name, target, EXACT, 'same name ({0})'.format(target))
        else:
            remaining.append(name)
    pending = remaining

    # 3 — renames the plugin already knows.
    remaining = []
    for name in pending:
        key = compare_key(name)
        target = FIELD_ALIASES.get(key)
        if target and target in target_by_exact and target not in claimed:
            claim(name, target, ALIAS, 'known rename')
            continue
        remaining.append(name)
    pending = remaining

    # 4 — weaker per-layer hints, pre-selected but flagged.
    remaining = []
    for name in pending:
        target = hints.get(compare_key(name))
        if target and target in target_by_exact and target not in claimed:
            claim(name, target, SUGGESTED, 'likely replacement — confirm')
            continue
        remaining.append(name)
    pending = remaining

    # 5 — fuzzy, offered as a suggestion only.
    free_targets = [name for name in target_fields if name not in claimed]
    for name in pending:
        scored = fuzzy.best_matches(compare_key(name),
                                    [compare_key(target) for target in free_targets],
                                    limit=3, threshold=_FUZZY_FLOOR)
        candidates = []
        for key, score in scored:
            for target in free_targets:
                if compare_key(target) == key:
                    candidates.append((target, score))
                    break
        if candidates:
            best, score = candidates[0]
            source_field = source_spec.field(name)
            target_field = target_spec.field(best)
            ok, note = types_compatible(source_field, target_field)
            matches[name] = FieldMatch(
                name, best, SUGGESTED,
                'looks like {0} ({1}% similar) — confirm'.format(best, score),
                candidates=candidates, type_note=note, type_ok=ok)
            claimed.add(best)
            free_targets = [t for t in free_targets if t != best]
        else:
            matches[name] = FieldMatch(
                name, None, UNMATCHED, 'nothing matching in the destination',
                unmatched_action=(TO_COMMENTS
                                  if compare_key(name) in COMMENT_DEFAULTS
                                  else DROP))

    # Put the matches back in source-field order for a stable UI.
    ordered = OrderedDict()
    for name in source_fields:
        if name in matches:
            ordered[name] = matches[name]

    return LayerFieldPlan(source_spec.name, target_spec.name, ordered,
                          target_notes(target_spec, claimed))


def target_notes(target_spec, claimed):
    """What fills each destination column no source field feeds."""
    notes = OrderedDict()
    for name, field in target_spec.fields.items():
        if not is_copyable_field(name) or name in claimed:
            continue
        required = field.required
        domain = target_spec.domain(name)
        children = target_spec.child_fields_of(name)
        if children:
            notes[name] = TargetFieldNote(
                name, 'derived',
                'worked out from {0}'.format(', '.join(children)), required)
        elif field.default_expression:
            notes[name] = TargetFieldNote(
                name, 'default',
                _describe_default(field.default_expression), required)
        elif compare_key(name) in _FILLED_LATER:
            notes[name] = TargetFieldNote(
                name, 'later',
                'filled by {0}'.format(_FILLED_LATER[compare_key(name)]),
                required)
        elif name == 'Elevation':
            notes[name] = TargetFieldNote(
                name, 'derived', 'taken from geometry Z where present', required)
        else:
            notes[name] = TargetFieldNote(name, 'empty', '', required)
        if domain is not None and notes[name].how == 'empty':
            notes[name].detail = 'coded field — left empty'
    return notes


def _describe_default(expression):
    """A short human rendering of a QGIS default-value expression."""
    text = normalise(expression)
    if not text:
        return ''
    lowered = text.lower()
    if lowered.startswith("uuid("):
        return 'a new UUID'
    if lowered.startswith('format_date') or 'now()' in lowered:
        return 'the import date and time'
    if lowered.startswith('x($geometry)'):
        return 'the easting of the geometry'
    if lowered.startswith('y($geometry)'):
        return 'the northing of the geometry'
    simple = re.match(r"^'([^']*)'$", text)
    if simple:
        return 'the template default {0!r}'.format(simple.group(1))
    if len(text) > 70:
        text = text[:67] + '...'
    return 'the template rule: {0}'.format(text)
