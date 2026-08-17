"""
Which source layer goes into which destination layer.

Name matching alone is not enough and never was. Real exports carry names the
canon has never seen — `1_Structures`, `2_Alteration&StructuralZones`,
`4_Lithology` — while an LGS project written before Aug 2026 carries the RIGHT
names under the WRONG numbers (`2 - Overlay`, `3 - Linework`). Matching purely
on the ordinal is worse than useless there: `3_Linework` would land in
`3 - Overlay`, putting lines into a polygon layer.

So geometry decides what is even possible, and three signals rank what is left:
the ordinal-tolerant canonical name (lgs_layers.same_layer), a small alias
vocabulary, and the overlap between the two field-name sets. The field-name
overlap is what actually pairs `1_Structures` with `1 - FieldNotebook` — they
share ~50 column names and no name similarity at all.
"""

import re
from collections import OrderedDict

try:
    from ..lgs_layers import base_name, has_ordinal, same_layer
except ImportError:  # top-level import, or the pure test loader
    from lgs_layers import base_name, has_ordinal, same_layer

try:
    from .domain import fold, is_copyable_field
    from . import fuzzy
except ImportError:  # flat execution / pure test loader
    from domain import fold, is_copyable_field
    import fuzzy


# Alias vocabulary, keyed by destination base name. These are hints that
# survive a client renaming their layers on export; the geometry gate and the
# field-signature score still have to agree before anything is auto-assigned.
LAYER_ALIASES = {
    'fieldnotebook': ('fieldnotebook', 'notebook', 'structure', 'structures',
                      'point', 'points', 'observation', 'observations',
                      'site', 'sites', 'station', 'stations', 'measurement',
                      'measurements', 'sample', 'samples'),
    'linework': ('linework', 'line', 'lines', 'contact', 'contacts', 'trace',
                 'traces', 'structurelines', 'lineament', 'lineaments'),
    'overlay': ('overlay', 'overlays', 'alteration', 'alterations', 'zone',
                'zones', 'structuralzones', 'weathering', 'mineralisation',
                'mineralization'),
    'basemap': ('basemap', 'lithology', 'lithologies', 'lith', 'geology',
                'geol', 'rocktype', 'rocktypes', 'unit', 'units', 'polygon',
                'polygons', 'mapping'),
}

# Confidence bands. AUTO is applied without asking; REVIEW is pre-selected but
# flagged; NONE leaves the row unassigned.
AUTO = 'auto'
REVIEW = 'review'
NONE = 'none'

_CANON_SCORE = 1000
_ALIAS_SCORE = 300
_SIGNATURE_WEIGHT = 600
_NAME_WEIGHT = 120

# A clear winner has to beat the runner-up by this much to be auto-assigned.
_AUTO_MARGIN = 120
_AUTO_FLOOR = 260

_TOKEN_RE = re.compile(r'[^a-z0-9]+')


def tokenise(name):
    """Base name -> lowercase word tokens. '2_Alteration&Zones' -> {alteration, zones}."""
    stripped = base_name(name)
    parts = [part for part in _TOKEN_RE.split(stripped.lower()) if part]
    # Also split runs like 'structuralzones' against the alias vocabulary by
    # keeping the whole token; alias membership is a substring test below.
    return set(parts)


def normalise_field(name):
    """Field name reduced for set comparison: lowercase, punctuation removed."""
    return _TOKEN_RE.sub('', (name or '').lower())


def field_signature(layer_spec):
    """The comparable set of a layer's field names, minus bookkeeping columns."""
    return {normalise_field(name) for name in layer_spec.fields
            if is_copyable_field(name) and normalise_field(name)}


def geometry_family(geometry_type):
    """POINT / LINE / POLYGON, ignoring MULTI- and Z/M. '' when unknown."""
    text = (geometry_type or '').upper().replace('MULTI', '')
    text = text.replace(' Z', '').replace('Z', '') if text.endswith('Z') else text
    if 'POINT' in text:
        return 'POINT'
    if 'LINE' in text:
        return 'LINE'
    if 'POLYGON' in text or 'SURFACE' in text:
        return 'POLYGON'
    if 'GEOMETRY' in text or 'COLLECTION' in text:
        return 'ANY'
    return ''


def geometry_compatible(source_spec, target_spec):
    """True when features from `source_spec` can be written to `target_spec`."""
    source_family = geometry_family(source_spec.geometry_type)
    target_family = geometry_family(target_spec.geometry_type)
    if not source_family or not target_family:
        return True
    if 'ANY' in (source_family, target_family):
        return True
    return source_family == target_family


def alias_hit(source_name, target_name):
    """True when a source token appears in the destination's alias vocabulary."""
    vocabulary = LAYER_ALIASES.get(fold(base_name(target_name)))
    if not vocabulary:
        return False
    tokens = tokenise(source_name)
    for token in tokens:
        if token in vocabulary:
            return True
        # 'structuralzones' contains 'zones'; 'lithologies' contains 'lith'.
        for word in vocabulary:
            if len(word) >= 4 and word in token:
                return True
    return False


class LayerMatch(object):
    """One source layer's destination, with why and what else was possible."""

    __slots__ = ('source_name', 'target_name', 'confidence', 'reason',
                 'candidates', 'blocked', 'feature_count')

    def __init__(self, source_name, target_name=None, confidence=NONE,
                 reason='', candidates=(), blocked='', feature_count=0):
        self.source_name = source_name
        self.target_name = target_name
        self.confidence = confidence
        self.reason = reason
        self.candidates = list(candidates)   # [(target_name, score, reason)]
        self.blocked = blocked
        self.feature_count = feature_count

    @property
    def is_assigned(self):
        return bool(self.target_name)

    @property
    def needs_review(self):
        return self.confidence != AUTO

    def __repr__(self):
        return 'LayerMatch({0!r} -> {1!r}, {2})'.format(
            self.source_name, self.target_name, self.confidence)


def score_pair(source_spec, target_spec):
    """(score, reason) for one candidate pairing. Geometry is assumed checked."""
    reasons = []
    score = 0.0

    if has_ordinal(source_spec.name) and same_layer(source_spec.name,
                                                   target_spec.name):
        score += _CANON_SCORE
        reasons.append('same layer name')
    elif fold(base_name(source_spec.name)) == fold(base_name(target_spec.name)):
        score += _CANON_SCORE
        reasons.append('same layer name')
    elif alias_hit(source_spec.name, target_spec.name):
        score += _ALIAS_SCORE
        reasons.append('name recognised')

    overlap = fuzzy.jaccard(field_signature(source_spec),
                            field_signature(target_spec))
    if overlap:
        score += overlap * _SIGNATURE_WEIGHT
        reasons.append('{0:.0f}% of fields in common'.format(overlap * 100))

    name_score = fuzzy.ratio(base_name(source_spec.name),
                             base_name(target_spec.name))
    score += (name_score / 100.0) * _NAME_WEIGHT

    return score, ', '.join(reasons) or 'geometry matches'


def match_layers(source_model, target_model, seeded=None):
    """Pair every spatial source layer with a destination layer.

    `seeded` is an optional {source_name: target_name} from a saved profile;
    those pairings win outright as long as the geometry still allows them.
    Returns an OrderedDict source_name -> LayerMatch, in source order.
    """
    seeded = seeded or {}
    targets = [spec for spec in target_model.layers.values()
               if geometry_family(spec.geometry_type)]

    matches = OrderedDict()
    for source_name, source_spec in source_model.layers.items():
        match = LayerMatch(source_name, feature_count=source_spec.feature_count)
        matches[source_name] = match

        compatible = [spec for spec in targets
                      if geometry_compatible(source_spec, spec)]
        if not compatible:
            wanted = geometry_family(source_spec.geometry_type) or 'unknown'
            match.blocked = (
                'No destination layer holds {0} geometry ({1} is {2}).'.format(
                    wanted.lower(), source_name,
                    source_spec.geometry_type or 'unknown'))
            continue

        scored = []
        for target_spec in compatible:
            score, reason = score_pair(source_spec, target_spec)
            scored.append((target_spec.name, score, reason))
        scored.sort(key=lambda row: -row[1])
        match.candidates = scored

        seed = seeded.get(source_name)
        if seed and any(name == seed for name, _s, _r in scored):
            match.target_name = seed
            match.confidence = AUTO
            match.reason = 'from saved profile'
            continue

        best_name, best_score, best_reason = scored[0]
        runner_up = scored[1][1] if len(scored) > 1 else 0.0
        if best_score >= _AUTO_FLOOR and (best_score - runner_up) >= _AUTO_MARGIN:
            match.target_name = best_name
            match.confidence = AUTO
            match.reason = best_reason
        else:
            match.target_name = best_name
            match.confidence = REVIEW
            match.reason = (best_reason + ' — check this one'
                            if best_reason else 'best guess')
    return matches


def excluded_tables(source_model):
    """Non-spatial tables in the source, with why they are not imported.

    Code tables and layer_styles are content the destination already owns; the
    old tool checked them by default, which appended 15 lookup tables and a pile
    of duplicate style rows into people's projects.
    """
    reasons = OrderedDict()
    for name in source_model.tables:
        reasons[name] = 'code table — the destination has its own'
    return reasons
