"""
Level suggestions for the Z filter: cluster the Elevation values found in
the data into a short list of suggested bench/levels, each with a fitted
± tolerance.

Pure python, no qgis imports — unit-tested in tests/test_z_levels.py and
MIRRORED IN JAVASCRIPT inside z_filter/qfield/lgs_companion.qml; keep the
two implementations in sync.

Behaviour by data shape (see tests for the worked examples):
- Discrete typed/snapped RLs (up to MAX_SUGGESTIONS distinct values, every
  gap wider than MIN_TOL): each distinct value IS a level — one suggestion
  at exactly that value, tolerance MIN_TOL. No gap-clustering, which would
  merge genuinely distinct mine levels only ~2 m apart.
- Noisy measured values around benches (365.8, 366.0 x40, 366.2 ...): values
  within GAP_FLOOR of each other merge; the modal value wins when it holds
  at least half the cluster (a typed RL with stragglers), otherwise the
  weighted mean; tolerance covers the scatter.
- Continuous survey data (every metre from 320-410): a single huge cluster
  is re-binned on a "nice" step (1/2/5x10^k) so at most ~MAX_SUGGESTIONS
  chips cover the range, tolerance = half the step.
- A final pass clamps each tolerance toward the midpoint between
  neighbouring cluster edges, but a window is never clamped below what
  covers its own cluster's lo..hi: coverage wins over non-overlap, because
  features cut out of their own suggestion are unreachable from any chip.
- suggest_step() proposes the steppers' sweep increment: the median gap
  between adjacent suggested levels, rounded to the nearest 1/2/5 x 10^k.
- attach_labels() decorates suggestions with the modal level-name text
  (e.g. a "Level" field: "000 Level") collected by the scan.
- range_vote() decides the single elevation a feature contributes to the
  histogram, including the Z_Min/Z_Max range features that carry a whole
  survey string's envelope.
"""

import math
import re

# No package imports (not even .expression) so tests can load this file
# directly.
DEFAULT_TOLERANCE = 5.0   # keep equal to expression.DEFAULT_TOLERANCE
FLAT_SPAN = 2.0           # keep equal to expression.FLAT_SPAN
LEVEL_SPAN_CAP = 20.0  # m — wider spans are declines / multi-level strings
LABEL_SLACK = 2.0      # m — a level's RL may sit just outside its envelope

GAP_FLOOR = 2.0        # m — gaps <= this never split a cluster
GAP_FACTOR = 0.5       # split on gaps > max(GAP_FLOOR, GAP_FACTOR * median gap)
GAP_EPS = 1e-6         # relative — gaps within this of a threshold count as
                       # equal (merge), so float noise never decides a split
MIN_TOL = 1.0          # m — floor for a suggested tolerance
TOL_MARGIN = 0.5       # m — headroom added to half the cluster span
MAX_TOL = 15.0         # m — wider clusters are treated as continuous data
MAX_SUGGESTIONS = 12   # chips shown on the panel
TOL_PRESETS = [1.0, 2.5, 5.0, 10.0]   # quick-set ± buttons (desktop + QField)

DEFAULT_STEP = 5.0     # m — stepper increment before any scan suggests one
STEP_FLOOR = 0.5       # m — smallest auto-suggested step


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _pairs(value_counts):
    """Normalize input (dict or iterable of (value, count)) to sorted pairs."""
    if value_counts is None:
        return []
    items = value_counts.items() if hasattr(value_counts, 'items') else value_counts
    cleaned = {}
    for value, count in items:
        try:
            value = float(value)
            count = int(count)
        except (TypeError, ValueError):
            continue
        if count <= 0 or value != value or value in (float('inf'), float('-inf')):
            continue
        cleaned[value] = cleaned.get(value, 0) + count
    return sorted(cleaned.items())


_LABEL_NUMBER = re.compile(r'-?\d+(?:\.\d+)?')


def label_elevation(text):
    """The RL embedded in a level name ('205', '205 Level', 'RL205'), or None.

    Exactly one number must appear: names like '13/42' are level *names*,
    not RLs, and guessing 13 from them would plant a rung 190 m from the
    data. Mirrored in the QML companion.
    """
    if text is None:
        return None
    matches = _LABEL_NUMBER.findall(str(text))
    if len(matches) != 1:
        return None
    try:
        return float(matches[0])
    except (TypeError, ValueError):
        return None


def range_vote(z_min, z_max, label=None):
    """The one elevation a feature votes for, or None when it abstains.

    Single-field layers pass the same value twice and vote it unchanged.
    Range features (Z_Min/Z_Max) carry a whole survey string's envelope:
    - flat (span <= FLAT_SPAN): the midpoint, as before;
    - undulating but named (a Surpac 'Level' whose RL sits inside the
      envelope): that RL, so a level's strings all land on one rung;
    - undulating and unnamed, up to LEVEL_SPAN_CAP: the midpoint;
    - wider than that (declines, multi-level strings): abstain, so a
      mid-ramp RL never becomes a suggested level.

    Voting for spanning features matches how they are filtered: range mode
    uses overlap semantics (expression.z_range_clause), so a string
    spanning 203-207 already shows on level 205.
    """
    try:
        lo = float(z_min)
        hi = float(z_max)
    except (TypeError, ValueError):
        return None
    if lo > hi:
        lo, hi = hi, lo
    if hi - lo <= FLAT_SPAN:
        return (lo + hi) / 2.0
    rl = label_elevation(label)
    if rl is not None and lo - LABEL_SLACK <= rl <= hi + LABEL_SLACK:
        return rl
    if hi - lo <= LEVEL_SPAN_CAP:
        return (lo + hi) / 2.0
    return None


def _nice_step(raw):
    """Smallest of 1/2/5 x 10^k that is >= raw."""
    if raw <= 0:
        return 1.0
    magnitude = 1.0
    while magnitude * 10.0 <= raw:
        magnitude *= 10.0
    while magnitude > raw:
        magnitude /= 10.0
    for factor in (1.0, 2.0, 5.0, 10.0):
        if magnitude * factor >= raw:
            return magnitude * factor
    return magnitude * 10.0


def _nice_step_nearest(raw):
    """The 1/2/5 x 10^k value nearest to raw (ties -> the smaller value)."""
    if raw <= 0:
        return 1.0
    magnitude = 1.0
    while magnitude * 10.0 <= raw:
        magnitude *= 10.0
    while magnitude > raw:
        magnitude /= 10.0
    best = magnitude
    for factor in (1.0, 2.0, 5.0, 10.0):
        candidate = magnitude * factor
        if abs(candidate - raw) < abs(best - raw):
            best = candidate
    return best


def _bin_continuous(pairs):
    """Re-bin an over-wide cluster on a nice step (continuous survey data)."""
    lo, hi = pairs[0][0], pairs[-1][0]
    step = _nice_step((hi - lo) / float(MAX_SUGGESTIONS))
    bins = {}
    for value, count in pairs:
        # floor(x + 0.5) == JS Math.round — keeps the QML mirror identical
        # (python's round() would use banker's rounding on .5 boundaries).
        level = math.floor(value / step + 0.5) * step
        entry = bins.setdefault(level, {'count': 0, 'lo': value, 'hi': value})
        entry['count'] += count
        entry['lo'] = min(entry['lo'], value)
        entry['hi'] = max(entry['hi'], value)
    tol = max(MIN_TOL, step / 2.0)
    return [{'level': level, 'count': entry['count'],
             'lo': entry['lo'], 'hi': entry['hi'], 'suggested_tol': tol}
            for level, entry in sorted(bins.items())]


def _summarize(pairs):
    """Turn one raw cluster (sorted pairs) into suggestion dict(s)."""
    lo, hi = pairs[0][0], pairs[-1][0]

    total = sum(count for _v, count in pairs)
    mode_value, mode_count = pairs[0]
    for value, count in pairs:
        if count > mode_count:
            mode_value, mode_count = value, count
    if mode_count * 2 >= total:
        level = mode_value      # a typed RL dominates the cluster
    else:
        weighted = sum(value * count for value, count in pairs) / float(total)
        level = round(weighted, 1)

    # The tolerance must reach the far edge of the cluster from the level
    # (which may sit off-centre, e.g. a modal value at one end); clusters
    # too wide for that are treated as continuous data instead.
    needed = max(level - lo, hi - level)
    if needed + TOL_MARGIN > MAX_TOL:
        return _bin_continuous(pairs)
    tol = max(MIN_TOL, needed + TOL_MARGIN)
    return [{'level': level, 'count': total, 'lo': lo, 'hi': hi,
             'suggested_tol': tol}]


def cluster_levels(value_counts):
    """Cluster {elevation: feature count} into suggested levels.

    Returns dicts sorted ascending by level:
        {'level', 'count', 'lo', 'hi', 'suggested_tol'}
    Deterministic for any input ordering.
    """
    pairs = _pairs(value_counts)
    if not pairs:
        return []

    gaps = [b[0] - a[0] for a, b in zip(pairs, pairs[1:])]

    # Discrete fast path: few distinct values, all separated by more than
    # MIN_TOL — each distinct value IS a level (typed/snapped RLs), so a
    # MIN_TOL window on each is both selective (never reaches a neighbour)
    # and covering (lo == hi == level).
    if len(pairs) <= MAX_SUGGESTIONS and (
            not gaps or min(gaps) > MIN_TOL * (1.0 + GAP_EPS)):
        return [{'level': value, 'count': count, 'lo': value, 'hi': value,
                 'suggested_tol': MIN_TOL} for value, count in pairs]

    threshold = max(GAP_FLOOR, GAP_FACTOR * _median(gaps)) if gaps else GAP_FLOOR

    clusters = []
    current = [pairs[0]]
    for previous, pair in zip(pairs, pairs[1:]):
        if pair[0] - previous[0] > threshold * (1.0 + GAP_EPS):
            clusters.append(current)
            current = []
        current.append(pair)
    clusters.append(current)

    suggestions = []
    for cluster in clusters:
        suggestions.extend(_summarize(cluster))
    suggestions.sort(key=lambda s: s['level'])

    # A window may extend at most to the midpoint between adjacent cluster
    # edges, but is never clamped below what covers its own lo..hi: a window
    # that cuts out its own members leaves them unreachable from any chip,
    # which is worse than a little overlap toward a neighbour.
    for i, suggestion in enumerate(suggestions):
        needed = max(suggestion['level'] - suggestion['lo'],
                     suggestion['hi'] - suggestion['level'])
        allowed = [suggestion['suggested_tol']]
        if i > 0:
            allowed.append(suggestion['level']
                           - (suggestions[i - 1]['hi'] + suggestion['lo']) / 2.0)
        if i < len(suggestions) - 1:
            allowed.append((suggestion['hi'] + suggestions[i + 1]['lo']) / 2.0
                           - suggestion['level'])
        suggestion['suggested_tol'] = max(MIN_TOL, needed, min(allowed))
    return suggestions


def suggest_tolerance(clusters):
    """Global ± suggestion for the 'Auto' button."""
    if not clusters:
        return DEFAULT_TOLERANCE
    return round(_median([c['suggested_tol'] for c in clusters]), 1)


def suggest_step(clusters):
    """Sweep increment for the level steppers: the median gap between
    adjacent suggested levels, rounded to the nearest 1/2/5 x 10^k."""
    levels = sorted(c['level'] for c in clusters)
    if len(levels) < 2:
        return DEFAULT_STEP
    gaps = [b - a for a, b in zip(levels, levels[1:])]
    return max(STEP_FLOOR, _nice_step_nearest(_median(gaps)))


LABEL_EPS = 1e-9


def attach_labels(suggestions, value_labels):
    """Attach the modal level-name label to each suggestion whose [lo, hi]
    (inclusive, LABEL_EPS) covers the labelled values.

    value_labels: {elevation: {label text: feature count}} from the scan.
    Mutates the suggestion dicts in place and returns them; the 'label'
    key is ABSENT (not None) when no labels apply, so the QML mirror's
    undefined semantics line up.
    """
    for suggestion in suggestions:
        tally = {}
        for value, labels in (value_labels or {}).items():
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if not (suggestion['lo'] - LABEL_EPS <= value
                    <= suggestion['hi'] + LABEL_EPS):
                continue
            for label, count in labels.items():
                label = str(label).strip()
                if not label:
                    continue
                tally[label] = tally.get(label, 0) + count
        if tally:
            # Modal label; ties break to the lexicographically smallest.
            suggestion['label'] = sorted(
                tally.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return suggestions


def top_suggestions(clusters, n=MAX_SUGGESTIONS):
    """The n highest-count suggestions, re-sorted ascending by level."""
    ranked = sorted(clusters, key=lambda c: (-c['count'], c['level']))[:n]
    return sorted(ranked, key=lambda c: c['level'])


def value_range(value_counts):
    """(min, max, total feature count) or None when there are no values."""
    pairs = _pairs(value_counts)
    if not pairs:
        return None
    return (pairs[0][0], pairs[-1][0], sum(count for _v, count in pairs))
