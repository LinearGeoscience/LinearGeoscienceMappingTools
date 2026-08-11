"""
Level suggestions for the Z filter: cluster the Elevation values found in
the data into a short list of suggested bench/levels, each with a fitted
± tolerance.

Pure python, no qgis imports — unit-tested in tests/test_z_levels.py and
MIRRORED IN JAVASCRIPT inside z_filter/qfield/zfilter_sidecar.qml; keep the
two implementations in sync.

Behaviour by data shape (see tests for the worked examples):
- Clean typed bench RLs (366, 376, 386): every distinct value becomes its
  own suggestion at exactly that value, tolerance MIN_TOL.
- Noisy measured values around benches (365.8, 366.0 x40, 366.2 ...): values
  within GAP_FLOOR of each other merge; the modal value wins when it holds
  at least half the cluster (a typed RL with stragglers), otherwise the
  weighted mean; tolerance covers the scatter.
- Continuous survey data (every metre from 320-410): a single huge cluster
  is re-binned on a "nice" step (1/2/5x10^k) so at most ~MAX_SUGGESTIONS
  chips cover the range, tolerance = half the step.
- A final pass clamps each tolerance to half the distance to the nearest
  neighbouring suggestion so windows never overlap.
"""

# No imports (not even .expression) so tests can load this file directly.
DEFAULT_TOLERANCE = 5.0   # keep equal to expression.DEFAULT_TOLERANCE

GAP_FLOOR = 2.0        # m — gaps <= this never split a cluster
GAP_FACTOR = 0.5       # split on gaps > max(GAP_FLOOR, GAP_FACTOR * median gap)
MIN_TOL = 1.0          # m — floor for a suggested tolerance
TOL_MARGIN = 0.5       # m — headroom added to half the cluster span
MAX_TOL = 15.0         # m — wider clusters are treated as continuous data
MAX_SUGGESTIONS = 12   # chips shown on the panel
TOL_PRESETS = [1.0, 2.5, 5.0, 10.0]   # quick-set ± buttons (desktop + QField)


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


def _bin_continuous(pairs):
    """Re-bin an over-wide cluster on a nice step (continuous survey data)."""
    lo, hi = pairs[0][0], pairs[-1][0]
    step = _nice_step((hi - lo) / float(MAX_SUGGESTIONS))
    bins = {}
    for value, count in pairs:
        level = round(value / step) * step
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
    span = hi - lo
    if span / 2.0 + TOL_MARGIN > MAX_TOL:
        return _bin_continuous(pairs)

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
    tol = min(MAX_TOL, max(MIN_TOL, span / 2.0 + TOL_MARGIN))
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
    threshold = max(GAP_FLOOR, GAP_FACTOR * _median(gaps)) if gaps else GAP_FLOOR

    clusters = []
    current = [pairs[0]]
    for previous, pair in zip(pairs, pairs[1:]):
        if pair[0] - previous[0] > threshold:
            clusters.append(current)
            current = []
        current.append(pair)
    clusters.append(current)

    suggestions = []
    for cluster in clusters:
        suggestions.extend(_summarize(cluster))
    suggestions.sort(key=lambda s: s['level'])

    # Never let neighbouring windows overlap: cap each tolerance at half the
    # distance to the nearest suggested level (MIN_TOL still wins).
    for i, suggestion in enumerate(suggestions):
        half_gaps = []
        if i > 0:
            half_gaps.append((suggestion['level'] - suggestions[i - 1]['level']) / 2.0)
        if i < len(suggestions) - 1:
            half_gaps.append((suggestions[i + 1]['level'] - suggestion['level']) / 2.0)
        if half_gaps:
            suggestion['suggested_tol'] = max(
                MIN_TOL, min(suggestion['suggested_tol'], min(half_gaps)))
    return suggestions


def suggest_tolerance(clusters):
    """Global ± suggestion for the 'Auto' button."""
    if not clusters:
        return DEFAULT_TOLERANCE
    return round(_median([c['suggested_tol'] for c in clusters]), 1)


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
