"""Make a lithology texture tile tile seamlessly, and check that it does.

THE DEFECT THIS EXISTS FOR
--------------------------
QGIS fills a polygon by rasterising one tile and repeating it. So the tile is
a torus: its right edge butts its own left edge, its bottom its own top. Most
of the authored library was drawn as a picture in a box instead, which shows
up on a map three ways:

  R1  A stroke lying ALONG a tile edge. Its two halves are rasterised and
      antialiased independently into the brush, so the seam line never quite
      matches the weight of the interior lines - and where only one edge
      carries it, half the stroke is clipped away and the line is simply
      lighter every Nth repeat. The brick tiles (limestone, dolomite, marble,
      marl, chalk), iron_formation, granulite, slate and shale all do this.

  R2  A motif CROSSING an edge with nothing completing it on the far side, so
      it renders as a truncated fragment against the seam.

  R3  Motif rhythm that does not divide the tile: rows every 4 units in a
      24-unit box leaves an 8-unit gap at the wrap, i.e. a blank stripe once
      per repeat. This is the one the user photographed - siltstone runs
      3,3,3,3,3 then 5, laterite 5,5,10.

At referencescale 5000 and a working scale of 1:200-1:500 the 12 pt tile is
drawn 120-300 pt wide, so none of these are subtle: they are full-width
stripes across the polygon.

WHAT COUNTS AS A DEFECT, PRECISELY
----------------------------------
Two things that look similar are NOT defects, and conflating them produces a
checker that cries wolf:

  * A stroke that SPANS the full extent (x=0 to x=W) tiles continuously. The
    wave tiles and slate's cleavage lines are all like this. Exempt per axis.
  * A butt-capped dash whose ENDPOINT sits exactly on the edge loses nothing:
    butt caps do not extend along the line, so the inflated geometry stops at
    the boundary rather than crossing it. claystone, syenite, mylonite and
    dolerite are all fine for this reason. Only round caps, circles and closed
    shapes inflate along every axis.

So the geometry is inflated by the tile's CALIBRATED stroke width - the real
one from stroke_widths.tsv, not the 0.1 placeholder in the artwork - and only
a genuine crossing counts.

R3 IS NOT AUTOMATED, DELIBERATELY
---------------------------------
Four metrics for it were built and measured against known-good and known-bad
tiles; all four were unusable. Band-density uniformity fails legitimately
directional art (shale's partings, slate's cleavage score a zero-ink band,
which is correct). A raster ink-profile gap ratio false-passes mudstone and
limestone and false-FAILS evaporite, which is one of the two tiles that were
already right. A sliding window fails every sparse tile (gabbro 14x, basalt
infinite). A generic motif-lattice ratio fails any quincunx, because two
offset rows legitimately give a 2:1 gap ratio - gabbro, eclogite, crosshatch.

The blank-band tiles are therefore named in a table with the shift or lattice
that fixes each, and every parameter is a STORED CONSTANT rather than a search
result, so `prepare_lith_patterns.py` stays byte-reproducible.
"""
import re

EPS = 1e-6

# Elements the library actually uses. `rect` is the no-op bounding box every
# tile opens with; it is regenerated from the viewBox rather than transformed.
# Non-capturing on purpose: findall() with a group returns the group, not the
# element, and every caller here wants the whole element text.
SHAPE_RE = re.compile(r'<(?:line|circle|polygon|polyline|path)\b[^>]*?/>', re.S)
NUM = r'-?\d+(?:\.\d+)?'


def _attr(el, name):
    m = re.search(r'\b%s\s*=\s*"([^"]*)"' % name, el)
    return m.group(1) if m else None


def _fmt(v):
    """Trim float noise so repeated runs produce byte-identical files."""
    s = "%.4f" % round(v + 0.0, 4)
    s = s.rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def coords_of(el):
    """[(x, y), ...] for any supported element, in document order."""
    kind = re.match(r'<(\w+)', el).group(1)
    if kind == "line":
        return [(float(_attr(el, "x1")), float(_attr(el, "y1"))),
                (float(_attr(el, "x2")), float(_attr(el, "y2")))]
    if kind == "circle":
        return [(float(_attr(el, "cx")), float(_attr(el, "cy")))]
    if kind in ("polygon", "polyline"):
        v = [float(t) for t in re.findall(NUM, _attr(el, "points"))]
        return list(zip(v[0::2], v[1::2]))
    if kind == "path":
        d = _attr(el, "d")
        if re.search(r'[mlqctsahvz]', d):
            raise ValueError("relative path command in %r - the translator "
                             "only handles absolute commands" % d)
        v = [float(t) for t in re.findall(NUM, d)]
        if len(v) % 2:
            raise ValueError("odd coordinate count in path %r" % d)
        return list(zip(v[0::2], v[1::2]))
    raise ValueError("unsupported element: " + kind)


def translate_el(el, dx, dy):
    """Same element with every coordinate moved. Textual, so the diff stays
    reviewable and comments/attribute order survive."""
    kind = re.match(r'<(\w+)', el).group(1)
    if kind == "line":
        out = el
        for a, d in (("x1", dx), ("y1", dy), ("x2", dx), ("y2", dy)):
            out = re.sub(r'\b%s\s*=\s*"[^"]*"' % a,
                         '%s="%s"' % (a, _fmt(float(_attr(el, a)) + d)),
                         out, count=1)
        return out
    if kind == "circle":
        out = el
        for a, d in (("cx", dx), ("cy", dy)):
            out = re.sub(r'\b%s\s*=\s*"[^"]*"' % a,
                         '%s="%s"' % (a, _fmt(float(_attr(el, a)) + d)),
                         out, count=1)
        return out
    if kind in ("polygon", "polyline"):
        pts = " ".join("%s,%s" % (_fmt(x + dx), _fmt(y + dy))
                       for x, y in coords_of(el))
        return re.sub(r'\bpoints\s*=\s*"[^"]*"', 'points="%s"' % pts,
                      el, count=1)
    if kind == "path":
        d = _attr(el, "d")
        it = iter(coords_of(el))
        # Rebuild the d string, replacing number pairs in order and keeping
        # every command letter and separator exactly as authored.
        out, i, pend = [], 0, []
        for m in re.finditer(NUM, d):
            pend.append(m)
        for j in range(0, len(pend), 2):
            x, y = next(it)
            mx, my = pend[j], pend[j + 1]
            out.append(d[i:mx.start()]); out.append(_fmt(x + dx))
            out.append(d[mx.end():my.start()]); out.append(_fmt(y + dy))
            i = my.end()
        out.append(d[i:])
        return re.sub(r'\sd\s*=\s*"[^"]*"', ' d="%s"' % "".join(out),
                      el, count=1)
    raise ValueError("unsupported element: " + kind)


def _round_cap(el):
    kind = re.match(r'<(\w+)', el).group(1)
    if kind in ("circle", "polygon"):
        return True                      # closed: inflates on every side
    return _attr(el, "stroke-linecap") == "round"


def bbox(el, width):
    """Stroke-inflated bounding box: (x0, y0, x1, y1).

    A round cap or a closed shape inflates along every axis. A butt cap - the
    SVG default - inflates only perpendicular to the segment, which is why a
    dash ending exactly on a tile edge is not clipped.
    """
    pts = coords_of(el)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    r = width / 2.0
    if re.match(r'<(\w+)', el).group(1) == "circle":
        r += float(_attr(el, "r"))
    ix = iy = r
    if not _round_cap(el):
        # perpendicular only: a horizontal run inflates in y, not x
        horizontal = max(ys) - min(ys) <= EPS
        vertical = max(xs) - min(xs) <= EPS
        if horizontal and not vertical:
            ix = 0.0
        elif vertical and not horizontal:
            iy = 0.0
    return (min(xs) - ix, min(ys) - iy, max(xs) + ix, max(ys) + iy)


def parse(svg):
    """(W, H, [element strings])."""
    m = re.search(r'viewBox\s*=\s*"0 0 (%s) (%s)"' % (NUM, NUM), svg)
    if not m:
        raise ValueError("tile has no 0-origin viewBox")
    return float(m.group(1)), float(m.group(2)), SHAPE_RE.findall(svg)


# --------------------------------------------------------------- audit
def audit(svg, width):
    """[(rule, message)] - empty means the tile is toroidally sound.

    R1 no stroke may lie along a tile edge.
    R2 anything crossing an edge needs the same shape one period away.
    """
    W, H, els = parse(svg)
    issues = []
    r = width / 2.0
    for el in els:
        pts = coords_of(el)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        kind = re.match(r'<(\w+)', el).group(1)
        if kind == "line" and len(pts) == 2:
            if abs(ys[0] - ys[1]) <= EPS and abs(xs[0] - xs[1]) > EPS:
                for edge in (0.0, H):
                    if abs(ys[0] - edge) <= r + EPS:
                        issues.append(("R1", "horizontal stroke along the "
                                       "y=%s edge" % _fmt(edge)))
            if abs(xs[0] - xs[1]) <= EPS and abs(ys[0] - ys[1]) > EPS:
                for edge in (0.0, W):
                    if abs(xs[0] - edge) <= r + EPS:
                        issues.append(("R1", "vertical stroke along the "
                                       "x=%s edge" % _fmt(edge)))
        x0, y0, x1, y1 = bbox(el, width)
        for lo, hi, span_lo, span_hi, P, axis in (
                (x0, x1, min(xs), max(xs), W, "x"),
                (y0, y1, min(ys), max(ys), H, "y")):
            if span_lo <= EPS and span_hi >= P - EPS:
                continue                       # spans the tile: tiles cleanly
            if lo >= -EPS and hi <= P + EPS:
                continue                       # wholly inside
            d = P if axis == "x" else 0.0
            partner = any(translate_el(el, d, P - d) == other
                          or translate_el(el, -d, -(P - d)) == other
                          for other in els if other is not el)
            if not partner:
                issues.append(("R2", "%s at (%s,%s) crosses the %s edge with "
                               "no wrap partner"
                               % (kind, _fmt(xs[0]), _fmt(ys[0]), axis)))
    # de-duplicate but keep order, so the message list is stable
    seen, out = set(), []
    for it in issues:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


# --------------------------------------------------------------- repair
def _body_bounds(svg):
    """(start, end) of the shape run, so replacements keep header + rect."""
    ms = list(SHAPE_RE.finditer(svg))
    return (ms[0].start(), ms[-1].end()) if ms else (None, None)


def _replace_shapes(svg, elements, indent="  "):
    s, e = _body_bounds(svg)
    if s is None:
        return svg
    return svg[:s] + ("\n" + indent).join(elements) + svg[e:]


def suggest_phase(svg):
    """(dx, dy) putting the tile boundary where no stroke is - analytically.

    A grid search over shifts is both slow and the wrong objective: the
    smallest shift that satisfies R1 leaves the stroke a quarter-unit off the
    edge, where its antialiasing still bleeds across the seam. What is actually
    wanted is maximum clearance, and that has a closed form - collect the
    edge-parallel stroke positions modulo the period, find the largest gap
    between consecutive positions, and move the boundary to the middle of it.
    Exact, O(n log n), and deterministic, so it can be run once and the answer
    stored rather than re-searched on every prepare.

    Hair-length dots count on both axes: they are `<line>` elements with round
    caps, so a dot centred on an edge is half-clipped exactly as a line is.
    """
    W, H, els = parse(svg)
    xs, ys = [], []
    for el in els:
        if not el.startswith("<line"):
            continue
        (x1, y1), (x2, y2) = coords_of(el)
        dot = abs(x2 - x1) < 0.01 and abs(y2 - y1) < 0.01
        if dot:
            xs.append(x1)
            ys.append(y1)
            continue
        if abs(y1 - y2) <= EPS:
            ys.append(y1)
        if abs(x1 - x2) <= EPS:
            xs.append(x1)

    def best_shift(vals, P):
        v = sorted({round(a % P, 4) for a in vals})
        if not v:
            return 0.0
        if len(v) == 1:
            return round(P / 2.0 - v[0], 4)
        gaps = [(v[i + 1] - v[i], v[i]) for i in range(len(v) - 1)]
        gaps.append((v[0] + P - v[-1], v[-1]))
        width, start = max(gaps, key=lambda g: (g[0], -g[1]))
        return round(-((start + width / 2.0) % P), 4)

    return best_shift(xs, W), best_shift(ys, H)


def phase_shift(svg, dx, dy):
    """Move the whole motif, so nothing is left sitting on an edge."""
    W, H, els = parse(svg)
    return _replace_shapes(svg, [translate_el(el, dx, dy) for el in els])


def wrap(svg, width):
    """Emit the toroidal copies that complete every edge-crossing motif.

    This is the technique basalt.svg and evaporite.svg already use by hand -
    a chevron at x=26 paired with its other half at x=-4 - applied to every
    tile mechanically. Anything that ends up entirely outside is dropped.
    """
    W, H, els = parse(svg)
    out, seen = [], set()
    for el in els:
        for dx in (0.0, W, -W):
            for dy in (0.0, H, -H):
                cand = el if (dx == 0.0 and dy == 0.0) \
                    else translate_el(el, dx, dy)
                x0, y0, x1, y1 = bbox(cand, width)
                if x1 <= EPS or x0 >= W - EPS or y1 <= EPS or y0 >= H - EPS:
                    continue              # no overlap with the tile at all
                # Identity on GEOMETRY, not on the element text. basalt already
                # carries its own wrap partner, and the copy this generates is
                # the same shape - but rebuilt with normalised number
                # formatting, so a string compare would miss the match and draw
                # it twice.
                key = (re.match(r'<(\w+)', cand).group(1),
                       tuple((round(x, 4), round(y, 4))
                             for x, y in coords_of(cand)),
                       _attr(cand, "r"))
                if key not in seen:
                    seen.add(key)
                    out.append(cand)
    return _replace_shapes(svg, out)


def resize(svg, W2, H2):
    """Shrink the repeat so the wrap gap matches the interior gap.

    Only the repeat length changes: QGIS scales a tile by WIDTH to
    TILE_WIDTH_PT and derives height from the aspect, so trimming dead space
    off the bottom costs nothing but the blank stripe it removes.
    """
    W, H, _els = parse(svg)
    svg = re.sub(r'viewBox\s*=\s*"0 0 %s %s"' % (NUM, NUM),
                 'viewBox="0 0 %s %s"' % (_fmt(W2), _fmt(H2)), svg, count=1)
    svg = re.sub(r'\bwidth="%s(pt)?"' % NUM, 'width="%spt"' % _fmt(W2),
                 svg, count=1)
    svg = re.sub(r'\bheight="%s(pt)?"' % NUM, 'height="%spt"' % _fmt(H2),
                 svg, count=1)
    return re.sub(r'(<rect\b[^>]*?)width="%s"([^>]*?)height="%s"' % (NUM, NUM),
                  r'\g<1>width="%s"\g<2>height="%s"' % (_fmt(W2), _fmt(H2)),
                  svg, count=1)


def relattice(svg, axis, tol=1.0):
    """Re-space the motif's rows (or columns) so the rhythm divides the tile.

    Groups coordinates into rows within `tol`, then places n rows at
    (i + 0.5) * P / n. Row COUNT and every within-row offset are preserved -
    those are what encode the grain size - only the spacing changes, so ink
    coverage barely moves.
    """
    W, H, els = parse(svg)
    P = H if axis == "y" else W
    idx = 1 if axis == "y" else 0
    keys = []
    for el in els:
        pts = coords_of(el)
        keys.append(sum(p[idx] for p in pts) / len(pts))
    order = sorted(range(len(els)), key=lambda i: keys[i])
    rows, cur = [], [order[0]]
    for i in order[1:]:
        if keys[i] - keys[cur[-1]] <= tol:
            cur.append(i)
        else:
            rows.append(cur)
            cur = [i]
    rows.append(cur)
    n = len(rows)
    out = list(els)
    for j, row in enumerate(rows):
        centre = sum(keys[i] for i in row) / len(row)
        want = (j + 0.5) * P / n
        d = want - centre
        for i in row:
            out[i] = translate_el(els[i], 0.0 if axis == "y" else d,
                                  d if axis == "y" else 0.0)
    return _replace_shapes(svg, out), n
