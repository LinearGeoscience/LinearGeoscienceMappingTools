"""
One similarity score for the whole importer, and a rule about how it may be used.

Fuzzy matching NEVER resolves a value on its own. Run over the real Abra
Linework data it proposes 'Fault - Minor' -> 'Fault - Normal',
'Shear - Minor' -> 'Shear - Normal' and 'Formline - Fine' -> 'Formline - S5'.
Those are geologically wrong and would be invisible once written. So every
caller here treats a fuzzy hit as a ranked SUGGESTION that a human confirms;
the automatic tiers (exact code, description, rename, split) are all exact
string work and live in match_values.py.

Prefers the bundled fuzzywuzzy when it is importable, falls back to difflib so
the pure modules stay testable outside QGIS.
"""

import difflib
import warnings

# fuzzywuzzy warns once at import when python-Levenshtein is absent, which it
# always is here. The pure-python matcher is fast enough for code lists of a
# few hundred entries, so the warning is noise in the QGIS log.
with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    try:
        from ..vendor.fuzzywuzzy import fuzz as _fuzz
    except ImportError:  # flat execution, or running outside the plugin package
        try:
            from vendor.fuzzywuzzy import fuzz as _fuzz
        except ImportError:
            _fuzz = None


def ratio(left, right):
    """Similarity of two strings, 0-100."""
    left = (left or '').lower()
    right = (right or '').lower()
    if not left or not right:
        return 0
    if left == right:
        return 100
    if _fuzz is not None:
        return int(_fuzz.ratio(left, right))
    return int(round(difflib.SequenceMatcher(None, left, right).ratio() * 100))


def best_matches(needle, candidates, limit=3, threshold=60):
    """Top `limit` candidates by ratio, descending, above `threshold`.

    `candidates` is an iterable of comparison strings. Returns
    [(candidate, score), ...] — the caller maps candidates back to codes.
    """
    scored = []
    for candidate in candidates:
        score = ratio(needle, candidate)
        if score >= threshold:
            scored.append((candidate, score))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored[:limit]


def jaccard(left, right):
    """Overlap of two sets, 0.0-1.0. Empty on either side scores 0."""
    left, right = set(left), set(right)
    if not left or not right:
        return 0.0
    return len(left & right) / float(len(left | right))
