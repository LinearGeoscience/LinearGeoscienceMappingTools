"""
Geometry helpers for the level-ladder widget (z_filter/ladder.py).

Pure python, no qgis/Qt imports — unit-tested in tests/test_z_ladder.py,
which loads this file directly. Elevations map to widget y-coordinates
with the HIGHEST elevation at the top (mining convention).
"""


def elev_to_y(value, lo, hi, height, pad):
    """Widget y for an elevation; highest elevation at the top."""
    if hi <= lo:
        return height / 2.0
    return pad + (hi - value) / (hi - lo) * (height - 2.0 * pad)


def y_to_elev(y, lo, hi, height, pad):
    """Inverse of elev_to_y, clamped to [lo, hi]."""
    if hi <= lo:
        return lo
    usable = height - 2.0 * pad
    if usable <= 0:
        return lo
    value = hi - (y - pad) / usable * (hi - lo)
    return min(hi, max(lo, value))


def rung_ys(levels, lo, hi, height, pad):
    """y position of each rung."""
    return [elev_to_y(level, lo, hi, height, pad) for level in levels]


def hit_rung(y, ys, tol_px=8.0):
    """Index of the rung nearest y within tol_px, else None."""
    best = None
    best_dist = tol_px
    for i, rung_y in enumerate(ys):
        dist = abs(rung_y - y)
        if dist <= best_dist:
            best = i
            best_dist = dist
    return best


def snap_elevation(value, step):
    """Snap a picked elevation to the step grid (0.1 m grid without one)."""
    if step and step > 0:
        return round(value / step) * step
    return round(value, 1)


def preferred_height(n_rungs, per_rung=26, lo_px=120, hi_px=400):
    """Ladder height that gives each rung breathing room, clamped."""
    return int(min(hi_px, max(lo_px, n_rungs * per_rung)))


def dodge_labels(ys, min_gap, lo, hi):
    """Dodged label y for each tick y (ys sorted ascending). Order kept,
    consecutive labels >= gap apart, all clamped to [lo, hi]; the gap
    shrinks to (hi - lo) / (n - 1) when n labels cannot fit at min_gap."""
    n = len(ys)
    if n == 0:
        return []
    if hi <= lo:
        return list(ys)
    if n == 1:
        return [min(hi, max(lo, ys[0]))]
    gap = min_gap
    if (n - 1) * gap > hi - lo:
        gap = (hi - lo) / (n - 1)
    out = list(ys)
    for i in range(1, n):                      # spread downward
        out[i] = max(out[i], out[i - 1] + gap)
    out[-1] = min(out[-1], hi)                 # clamp bottom, push back up
    for i in range(n - 2, -1, -1):
        out[i] = min(out[i], out[i + 1] - gap)
    out[0] = max(out[0], lo)                   # clamp top, settle downward
    for i in range(1, n):
        out[i] = max(out[i], out[i - 1] + gap)
    return out


def band_rect_y(level, width, lo, hi, height, pad):
    """(y_top, y_bottom) of the slice band [level-width, level+width],
    each clamped to the widget."""
    y_top = elev_to_y(level + width, lo, hi, height, pad)
    y_bottom = elev_to_y(level - width, lo, hi, height, pad)
    return (min(height, max(0.0, y_top)),
            min(height, max(0.0, y_bottom)))
