"""
Transposing an old code vocabulary onto the current one.

This is the part the old tool had no answer for. Between a project mapped in
2025 and the current template, codes have been renamed (FAP -> FAPL,
SAS -> ZSAS, TRSL/Loam -> TRSLM, L1-L5 -> LNI1-LNI5), retired (HSPG), had their
meaning changed under the same spelling (IAC was Intermediate Volcaniclastic,
it is now Andesitic Volcaniclastic), and had a whole suffix convention replaced
by a field (`Fault - Minor` is now Fault with Weight = Minor).

Five exact tiers resolve those automatically, in this order:

    exact           the value is already a code here
    renamed         the SOURCE's own lookup table describes it the same way the
                    destination describes a differently-spelled code
    description     the value is a destination description, or the tail of one
                    ('Hematite' is how 'Hem - Hematite' reads)
    spelling        the same code typed differently — 'Rockchip', 'ROCKCHIP'
                    and 'Rock Chip' are one sample type
    split           a trailing '- Major/Minor/Inferred' matches a ValueMap on a
                    sibling field, so the value splits into code + that field
    meaning changed the code still exists but the source meant something else

Only then is fuzzy matching consulted, and only to offer ranked suggestions a
human clicks. That restraint is not fussiness: on the real Abra Linework data,
fuzzy proposes 'Fault - Minor' -> 'Fault - Normal' and 'Shear - Minor' ->
'Shear - Normal', both of which would be silently wrong forever.
"""

import re
from collections import OrderedDict

try:
    from .domain import description_tail, fold, normalise
    from . import fuzzy
except ImportError:  # flat execution / pure test loader
    from domain import description_tail, fold, normalise
    import fuzzy


# Automatic outcomes.
EXACT = 'exact'
RENAMED = 'renamed'
DESCRIPTION = 'description'
SPELLING = 'spelling'
SPLIT = 'split'
MEANING_CHANGED = 'meaning_changed'
# Needs a human.
SUGGESTED = 'suggested'
UNRESOLVED = 'unresolved'
# Human decisions.
MANUAL = 'manual'
ADD_CODE = 'add_code'
BLANK = 'blank'

AUTO_STATUSES = frozenset({EXACT, RENAMED, DESCRIPTION, SPELLING, SPLIT,
                           MEANING_CHANGED})
DECIDED_STATUSES = AUTO_STATUSES | {MANUAL, ADD_CODE, BLANK}

# Plain-English labels for the UI badge.
STATUS_LABELS = {
    EXACT: 'Matches',
    RENAMED: 'Renamed',
    DESCRIPTION: 'Matched by name',
    SPELLING: 'Matched (spelling)',
    SPLIT: 'Split out',
    MEANING_CHANGED: 'Meaning changed',
    SUGGESTED: 'Suggestion — confirm',
    UNRESOLVED: 'Needs a decision',
    MANUAL: 'Chosen',
    ADD_CODE: 'New code',
    BLANK: 'Left blank',
}

_SUFFIX_RE_CACHE = {}
_FUZZY_FLOOR = 70
_FUZZY_LIMIT = 4


class ValueResolution(object):
    """What one distinct source value becomes in the destination."""

    __slots__ = ('field', 'value', 'count', 'status', 'code', 'extras',
                 'suggestions', 'note', 'new_code_description', 'new_code_parent',
                 'to_comments')

    def __init__(self, field, value, count=0, status=UNRESOLVED, code=None,
                 extras=None, suggestions=(), note='',
                 new_code_description='', new_code_parent='', to_comments=False):
        self.field = field
        self.value = value
        self.count = count
        self.status = status
        self.code = code
        self.extras = extras or {}
        self.suggestions = list(suggestions)   # [(code, description, score)]
        self.note = note
        self.new_code_description = new_code_description
        self.new_code_parent = new_code_parent
        self.to_comments = to_comments

    @property
    def decided(self):
        return self.status in DECIDED_STATUSES

    @property
    def automatic(self):
        return self.status in AUTO_STATUSES

    @property
    def needs_attention(self):
        """True when a human has to look, even if a value is pre-filled."""
        return self.status in (SUGGESTED, UNRESOLVED, MEANING_CHANGED)

    @property
    def label(self):
        return STATUS_LABELS.get(self.status, self.status)

    def choose(self, code, extras=None):
        self.status = MANUAL
        self.code = code
        self.extras = extras or {}
        self.note = 'chosen by hand'

    def add_as_new_code(self, parent='', description=''):
        self.status = ADD_CODE
        self.code = self.value
        self.new_code_parent = parent
        self.new_code_description = description or self.value
        self.note = 'will be added to the code table'

    def leave_blank(self, to_comments=False):
        self.status = BLANK
        self.code = None
        self.extras = {}
        self.to_comments = to_comments
        self.note = ('original kept in Comments' if to_comments
                     else 'left empty')

    def as_profile_entry(self):
        return {
            'value': self.value,
            'status': self.status,
            'code': self.code,
            'extras': dict(self.extras),
            'to_comments': self.to_comments,
            'new_code_parent': self.new_code_parent,
            'new_code_description': self.new_code_description,
        }

    def __repr__(self):
        return 'ValueResolution({0!r} -> {1!r}, {2})'.format(
            self.value, self.code, self.status)


def _suffix_pattern(tokens):
    """Compiled '<stem> - <token>' matcher for one ValueMap's codes."""
    key = tuple(sorted(tokens))
    pattern = _SUFFIX_RE_CACHE.get(key)
    if pattern is None:
        alternation = '|'.join(re.escape(token) for token in tokens if token)
        pattern = re.compile(
            r'^(?P<stem>.+?)\s*[-–—]\s*(?P<token>' + alternation + r')\s*$',
            re.IGNORECASE)
        _SUFFIX_RE_CACHE[key] = pattern
    return pattern


def sibling_value_maps(layer_spec, field_name):
    """ValueMap domains on the same layer, excluding this field.

    These are what a retired '- Major' / '- Minor' suffix moves into. Reading
    them off the destination rather than hardcoding 'Weight' means the rule
    keeps working when the template grows another such field.
    """
    siblings = OrderedDict()
    for name, domain in layer_spec.code_domains.items():
        if name == field_name:
            continue
        if domain.source_kind == 'ValueMap' and domain.codes:
            siblings[name] = domain
    return siblings


def _exact_or_description(domain, value):
    """(code, status) for the exact tiers, or (None, None).

    Shared by the top of the ladder and by the split tier, which has to re-run
    the same tests against the stem it peeled a suffix off.
    """
    canonical = domain.canonical_code(value)
    if canonical is not None:
        return canonical, EXACT
    by_description = domain.code_for_description(value)
    if by_description is not None:
        return by_description, DESCRIPTION
    squashed = domain.code_for_squashed(value)
    if squashed is not None:
        return squashed, SPELLING
    return None, None


def resolve_value(value, domain, layer_spec=None, source_describe=None):
    """Run the ladder for one source value. Returns (status, code, extras, note)."""
    value = normalise(value)

    # 1 — the value is already a code here.
    canonical = domain.canonical_code(value)
    if canonical is not None:
        if source_describe is not None:
            old = normalise(source_describe(value))
            new = domain.description_of(canonical)
            if old and new:
                old_tail = fold(description_tail(value, old))
                new_tail = fold(description_tail(canonical, new))
                if old_tail and new_tail and old_tail != new_tail:
                    return (MEANING_CHANGED, canonical, {},
                            'was {0!r}, now {1!r}'.format(
                                description_tail(value, old),
                                description_tail(canonical, new)))
        return EXACT, canonical, {}, ''

    # 2 — the source's own code table describes it the way the destination
    #     describes a differently-spelled code. That is a rename, not a guess.
    if source_describe is not None:
        old = normalise(source_describe(value))
        if old:
            tail = description_tail(value, old)
            renamed = domain.code_for_description(tail) or \
                domain.code_for_description(old)
            if renamed is not None:
                return (RENAMED, renamed, {},
                        '{0!r} is now {1!r}'.format(value, renamed))

    # 3 — the value IS a destination description, or the tail of one.
    by_description = domain.code_for_description(value)
    if by_description is not None:
        return (DESCRIPTION, by_description, {},
                '{0!r} is the name of code {1!r}'.format(value, by_description))

    # 3b — the same code typed with different case, spacing or punctuation.
    squashed = domain.code_for_squashed(value)
    if squashed is not None:
        return (SPELLING, squashed, {},
                '{0!r} is {1!r} spelled differently'.format(value, squashed))

    # 4 — a retired suffix that now lives on a sibling field.
    if layer_spec is not None:
        for sibling_name, sibling in sibling_value_maps(
                layer_spec, domain.field).items():
            match = _suffix_pattern(tuple(sibling.codes)).match(value)
            if not match:
                continue
            stem = normalise(match.group('stem'))
            token = sibling.canonical_code(match.group('token'))
            code, status = _exact_or_description(domain, stem)
            if code is not None and token is not None:
                return (SPLIT, code, {sibling_name: token},
                        '{0!r} became {1!r} with {2} = {3!r}'.format(
                            value, code, sibling_name, token))

    return UNRESOLVED, None, {}, ''


def suggest(value, domain, limit=_FUZZY_LIMIT, threshold=_FUZZY_FLOOR):
    """Ranked (code, description, score) suggestions. Never auto-applied."""
    pool = domain.search_pool()
    scored = fuzzy.best_matches(fold(value), list(pool.keys()),
                                limit=limit * 2, threshold=threshold)
    seen = set()
    suggestions = []
    for key, score in scored:
        code = pool[key]
        if code in seen:
            continue
        seen.add(code)
        suggestions.append((code, domain.description_of(code), score))
        if len(suggestions) >= limit:
            break
    return suggestions


def resolve_field(field_name, value_counts, domain, layer_spec=None,
                  source_describe=None, seeded=None):
    """Resolve every distinct value of one coded field.

    Returns an OrderedDict value -> ValueResolution, commonest value first so
    the rows that matter most are at the top of the list.
    """
    seeded = seeded or {}
    resolutions = OrderedDict()
    for value, count in value_counts.most_common():
        saved = seeded.get(value)
        if saved and saved.get('status') in DECIDED_STATUSES:
            resolution = ValueResolution(
                field_name, value, count,
                status=saved['status'], code=saved.get('code'),
                extras=dict(saved.get('extras') or {}),
                to_comments=bool(saved.get('to_comments')),
                new_code_parent=saved.get('new_code_parent', ''),
                new_code_description=saved.get('new_code_description', ''),
                note='from saved profile')
            resolutions[value] = resolution
            continue

        status, code, extras, note = resolve_value(
            value, domain, layer_spec=layer_spec,
            source_describe=source_describe)
        resolution = ValueResolution(field_name, value, count, status, code,
                                     extras, note=note)
        if status == UNRESOLVED:
            resolution.suggestions = suggest(value, domain)
            if resolution.suggestions:
                resolution.status = SUGGESTED
                best, description, score = resolution.suggestions[0]
                resolution.code = None  # deliberately NOT pre-applied
                resolution.note = 'closest is {0}{1} ({2}% alike)'.format(
                    best, ' — ' + description if description else '', score)
            else:
                resolution.note = 'nothing like this in the destination'
            if source_describe is not None:
                old = normalise(source_describe(value))
                if old:
                    resolution.new_code_description = old
        resolutions[value] = resolution
    return resolutions


def derive_parent(domain, code):
    """The parent value a resolved code implies, e.g. 'Fault' -> 'Structural'.

    Every code in the current template's four grouped tables belongs to exactly
    one parent, which is what makes back-filling Category / Type / TypeLith1
    safe to do without asking. tests/test_import_domain.py pins that property.
    """
    if not code or not domain.parent_column:
        return ''
    return domain.parent_of(code)


def summarise(resolutions):
    """Counts by status across a set of resolutions, for the review page."""
    summary = OrderedDict()
    for resolution in resolutions:
        summary[resolution.status] = summary.get(resolution.status, 0) + 1
    return summary


def unresolved_count(resolutions):
    return sum(1 for resolution in resolutions if not resolution.decided)
