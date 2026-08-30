"""Add SVG texture fills to '4 - Basemap' in a SECOND, throwaway template.

WRITES ONLY TO Template/LGS_MappingTemplate_Patterns.gpkg (created here as a
copy). It hard-refuses to open LGS_MappingTemplate.gpkg for writing, so the
live template is untouched and the experiment is undone by deleting the copy.

WHY THIS IS NOT "ADD AN SVGFILL TO EACH CATEGORY"
-------------------------------------------------
QGIS builds every category symbol on every render pass regardless of what is
on screen, and a pattern fill (SVGFill / PointPatternFill) builds a raster
brush in startRender(). Measured headless on the real template, 284
categories with ONE polygon drawn:

    SimpleFill only (today)                     3.8 ms
    + an SVGFill on each of the 284 categories  54.5 ms
    ... all 284 sharing one SVG payload         55.5 ms   <- dedup saves NOTHING
    rule-based, 284 colour rules + 1 pattern    6.1 ms

The cost is per-symbol-layer, not per-feature and not per-distinct-SVG, so
the only fix is to have exactly ONE SVGFill in the whole renderer. That means
a rule-based renderer: the 284 colour rules convert 1:1 from the categories
(QgsRuleBasedRenderer.convertFromRenderer, the same code path as QGIS's own
"Convert to rule-based renderer"), and a single filter-less rule appended
LAST paints the texture over them.

That one symbol layer carries THREE data-defined properties, each verified by
render test before being relied on:
  * PropertyFile        - which tile, per lithology ('base64:' payloads)
  * PropertyStrokeColor - what colour to draw it in, per lithology
  * PropertyStrokeWidth - how heavy, per TEXTURE (see load_stroke_widths:
                          the artwork's line weights span about 35x, so one
                          shared width leaves stipple invisible or line work
                          solid black)

Because all three are expressions on the same layer, going from 16 textures
to 41, from one ink to 48 colours, and from one stroke width to 25 costs
nothing at render time.

WHERE THE ASSIGNMENTS LIVE
--------------------------
Template/patterns/lith_textures.tsv - one row per lithology code, hand
audited. This file is the source of truth; there is deliberately NO keyword
heuristic here any more. Round 1 used one and it produced indefensible
results: a vein hatch on aplite, and 20+ separate felsic intrusives flattened
onto a single texture. A heuristic seeded the TSV once, offline; after that
the table is the map.

The injector refuses to run unless the TSV is exactly 1:1 with BasemapCodes
and every texture names a real tile, so "did I cover everything?" is an
assertion rather than a judgement call.

styleSLD is deliberately LEFT ALONE. Nothing reads it at runtime and SLD
cannot express a data-defined SVG fill, so regenerating it would only invent
a lie. The stored SLD stays a faithful description of the colour rules.

Run:  "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" scripts/inject_basemap_lith_patterns.py [--dry-run]

Idempotent: rebuilds the renderer from the ORIGINAL template's categorized
renderer every run, so it never stacks pattern rules.
"""
import base64
import colorsys
import os
import re
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# the repo root, for the constants the runtime rescale has to agree with
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lith_palette  # noqa: E402
from renderer_compat import SCALE_GATE_RATIO  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGINAL = os.path.join(REPO, "Template", "LGS_MappingTemplate.gpkg")
TARGET = os.path.join(REPO, "Template", "LGS_MappingTemplate_Patterns.gpkg")
PATTERN_DIR = os.path.join(REPO, "Template", "patterns")
TEXTURE_MAP = os.path.join(PATTERN_DIR, "lith_textures.tsv")
STROKE_WIDTHS = os.path.join(PATTERN_DIR, "stroke_widths.tsv")
MINERAL_INKS = os.path.join(PATTERN_DIR, "mineral_inks.tsv")
LITH_FILLS = os.path.join(PATTERN_DIR, "lith_fills.tsv")
TEXTURE_MODULATION = os.path.join(PATTERN_DIR, "texture_modulation.tsv")
MINERAL_FAMILIES = os.path.join(PATTERN_DIR, "mineral_families.tsv")

LAYER = "4 - Basemap"
FIELD = "Lithology1"
EXPECT_CATS = 300          # 299 codes + the NULL / all-other-values class
REFERENCE_SCALE = 5000
# Texture off when zoomed out past this. The ratio, not the number, is the
# thing that is right: paper-unit sizes scale by referenceScale/mapScale, so
# where a texture goes sub-pixel is linear in the reference scale, and the
# old hard-coded 6000 was correct only while the reference scale stayed at
# 5000 - see renderer_compat.SCALE_GATE_RATIO.
#
# Measured behaviour it has to bracket: with referencescale 5000 every
# texture holds a steady 7-10% ink from 1:500 to 1:4000, then collapses to
# ZERO between 1:8000 and 1:16000 as the stroke goes sub-pixel. So the ink is
# genuinely gone by ~3x the reference scale and a gate above that only
# rasterises tiles that draw nothing; the ratio is set to 5 on the user's
# instruction, which trades some of that for headroom.
#
# script_setmapping.py rewrites this rule's maximumScale to the same ratio
# whenever Set Mapping Scale changes the reference scale, so a project does
# not stay pinned to whatever was baked here.
PATTERN_MAX_SCALE = round(SCALE_GATE_RATIO * REFERENCE_SCALE)
TILE_WIDTH_PT = 12.0       # pattern tile width, Point units (see 55eaeed)
TILE_STROKE_PT = 0.3

PATTERN_RULE_LABEL = "Lithology texture"
BLANK = "blank"

# Texture colour is derived from each lithology's OWN fill colour rather than
# being one ink, so it always belongs with the polygon it sits on. Keep the
# hue, damp the saturation, then move lightness until the texture separates
# from the fill by a target (WCAG-style luminance ratio).
#
# THE TARGET IS PER TEXTURE, NOT ONE NUMBER.
# It used to be a flat 4.5 for every tile, which is a *text* legibility bar
# applied to a background texture - the user's report was simply "too strong",
# and 4.5 is why. It also ignored how much ink a tile lays down: measured
# coverage runs from 8.0% (amphibolite, dacite, migmatite) to 20.9%
# (crosshatch), so at one ratio the heavy tiles shout while the sparse ones
# merely show. Scale the target down as coverage goes up and both land in the
# same perceptual place:
#
#     target = clamp(INK_BASE * REF_INK_PCT / tile_ink_pct, MIN, MAX)
#
# INK_BASE is the dial the user picks by eye off a contact sheet. Override it
# for a sweep with the LGS_INK_BASE environment variable rather than an argv
# flag - calibrate_lith_strokes.py and the test both import this module and
# would never see argv.
INK_BASE = float(os.environ.get("LGS_INK_BASE", "1.55"))
REF_INK_PCT = 8.0

# ...EXCEPT THAT THE LOAD SCALING IS NOW OFF, and the reason is worth keeping.
#
# calibrate_lith_strokes.py ALREADY equalises ink coverage: it binary-searches
# each tile's stroke width to land on TARGET_INK = 8%. So coverage is not a
# free variable at this point - 52 of 56 textures sit between 8.1% and 8.6%,
# and scaling contrast by coverage moved them by less than 0.1. It only bit on
# the handful the calibrator could NOT get down to 8% because they are already
# solid at its minimum stroke width, which it reports as "TOO DENSE": crosshatch
# 20.9%, limestone 13.7%, felsic_fine 13.4%, marl 13.1%, then iron_formation,
# slate, shale, syenite and diorite at ~11.4%.
#
# Those are exactly the tiles that were then softened FURTHEST - iron formation
# landed at 1.09 against a 1.55 base, near invisible - so the rule was
# penalising a second time for something already compensated for. Harry called
# it on the rendered sheet: bump iron formation and the others back up.
#
# The mechanism is kept, not deleted, because the reasoning behind it only
# fails while the calibrator is doing its job. If TARGET_INK ever stops being
# enforced, set this back below 1.0 and the scaling returns.
INK_FLOOR_RATIO = 1.0          # 1.0 = flat: every texture aims at INK_BASE
INK_TARGET_MIN = max(1.04, INK_BASE * INK_FLOOR_RATIO)
INK_TARGET_MAX = INK_BASE

# Which WAY to move is decided against this fixed reference, NOT against the
# per-texture target, and that separation is the whole point.
#
# Prefer moving DARKER. A handful of fills - the ultramafic purple among them -
# are already too dark for that to reach the reference, and those invert to a
# LIGHT texture instead. That inversion is intentional: dark-on-dark genuinely
# fails to read, because the contrast ratio is compressive at the dark end and
# a "passing" ratio there can still be an invisible absolute difference.
#
# Deciding direction against the per-texture target instead would silently
# undo it: a softer target IS reachable by darkening a near-black fill, so 17
# to 22 codes would flip from their deliberate light ink to dark-on-dark and
# the paragraph above would stop being true of the code. Direction is a
# property of the FILL; magnitude is a property of the TILE.
DIRECTION_REFERENCE = 4.5

# An ink this far below its own target is not "soft", it is not there. Both
# bars exist because the target is now variable: the margin scales the check
# with the target, the floor keeps it meaningful if the target goes very low.
WEAK_INK_MARGIN = 0.85
WEAK_INK_FLOOR = 1.02

# How much of the fill's chroma the texture ink is allowed to carry. Keeps a
# near-white fill from spawning a saturated ink - see tint().
INK_CHROMA_GAIN = 2.0

# Inks pale enough that the fill beneath them has to be deep for the texture
# to read at all - anorthosite's white plagioclase dots being the case this
# exists for. lith_palette pushes these codes down their family ramp.
#
# `lithium` was here while it was a pale lilac. It is now a deep violet,
# because forcing FPGS's fill dark to host a pale ink put a spodumene
# pegmatite in the same dark pink as the migmatites.
PALE_INKS = ("plagioclase", "talc")

# A texture only needs to be legible, not to pass text-contrast rules, so
# mineral pairs are held to a gentler bar than the auto tint. Pushing every
# mineral pair to 4.5 forced fills right out of the muted palette.
#
# This follows the dial too, or the 93 codes carrying a mineral signal would be
# the only hard thing left on a softened map - at INK_BASE 1.85 a fixed 3.2
# would make them nearly twice the weight of everything around them. The
# multiplier is set so the value is EXACTLY 3.2 at INK_BASE 3.6, which is where
# that number was chosen; the 2.4 floor keeps a mineral ink the strongest mark
# on the page, because it is the one carrying diagnostic mineralogy.
MINERAL_CONTRAST = max(1.45, INK_BASE * 0.889)

# If the fill's hue is already within this of the mineral ink's, the fill is
# ALREADY saying what the ink would say - iron formation drawn in iron-oxide
# ink on an iron-oxide fill is a tautology that just reads as low contrast.
# Those fall back to the auto tint instead of double-encoding.
HUE_TAUTOLOGY_DEG = 30.0



def bail(msg):
    raise SystemExit("ABORT: " + msg)


# ----------------------------------------------------------------- colour
def _srgb_lum(rgb):
    def f(u):
        u /= 255.0
        return u / 12.92 if u <= 0.03928 else ((u + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = _srgb_lum(a), _srgb_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def target_for_ink_pct(ink_pct):
    """The contrast target a tile laying down `ink_pct` percent ink should use.

    Inverse in coverage, so a heavy tile is softened more than a sparse one and
    both read as the same weight of texture on the page.
    """
    if ink_pct <= 0:
        return INK_TARGET_MAX
    return max(INK_TARGET_MIN,
               min(INK_TARGET_MAX, INK_BASE * REF_INK_PCT / ink_pct))


def _scan(fill, h, s, l0, end, target):
    """Walk lightness from l0 toward `end`; return (rgb, contrast, reached)."""
    best, best_r = fill, 0.0
    for i in range(101):
        L = l0 + (end - l0) * i / 100.0
        cand = tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, L, s))
        r = contrast(fill, cand)
        if r > best_r:
            best, best_r = cand, r
        if r >= target:
            return cand, r, True
    return best, best_r, False


def tint(fill, target=DIRECTION_REFERENCE):
    """Texture colour for a polygon fill: (rgb, contrast, direction).

    Two-stage on purpose. DIRECTION is chosen by asking whether darkening can
    reach DIRECTION_REFERENCE - a fixed bar, so which fills invert to a light
    texture never changes when the softness dial moves. Only then is the ink
    placed at `target` in that direction.
    """
    h, l0, s0 = colorsys.rgb_to_hls(*[c / 255.0 for c in fill])
    # HLS saturation is not perceptual near white: a cream like #ffeed6 reports
    # s0 = 1.0 despite having almost no colour in it, so damping s0 still left a
    # vivid hue once lightness dropped and the restored cream regolith fills
    # came out with poster-paint amber textures (#cb7e10 on RDLX). Clamp by the
    # fill's actual chroma instead - it only bites on the near-white and
    # near-black fills, where it is exactly the correction needed.
    chroma = (max(fill) - min(fill)) / 255.0
    s = min(0.85, s0 * 0.85 + 0.10, chroma * INK_CHROMA_GAIN + 0.12)
    _c, _r, darker_ok = _scan(fill, h, s, l0, 0.03, DIRECTION_REFERENCE)
    end, label = (0.03, "darker") if darker_ok else (0.97, "lighter")
    cand, r, reached = _scan(fill, h, s, l0, end, target)
    if reached or darker_ok:
        return cand, r, label
    # Too dark to darken AND too pale to lighten: take the better of the two
    # rather than silently keeping a direction that cannot separate at all.
    alt, alt_r, _ = _scan(fill, h, s, l0, 0.03, target)
    return (cand, r, label) if r >= alt_r else (alt, alt_r, "darker")


def _lab(rgb):
    def f(u):
        u /= 255.0
        return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def k(t):
        return t ** (1 / 3.0) if t > 0.008856 else 7.787 * t + 16 / 116.0
    fx, fy, fz = k(x), k(y), k(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(a, b):
    """CIE76 colour difference. ~2 is a just-noticeable difference on a
    screen; 10 is comfortably separable in adjacent map polygons."""
    la, lb = _lab(a), _lab(b)
    return sum((x - y) ** 2 for x, y in zip(la, lb)) ** 0.5


def mix_rgb(a, b, ratio):
    """What the expression function color_mix_rgb does: linear per-component
    RGB interpolation. The audits must model the render maths exactly."""
    return tuple(round(a[i] + (b[i] - a[i]) * ratio) for i in range(3))


def qt_darker(rgb, factor):
    """Qt QColor::darker() semantics, as darker(color, factor) evaluates
    them: HSV round-trip, V divided by factor/100 - so factor < 100
    LIGHTENS. Shared with inject_basemap_lith_modulation.py's audit."""
    if factor == 100:
        return rgb
    h, s, v = colorsys.rgb_to_hsv(*[c / 255.0 for c in rgb])
    v = min(1.0, v * 100.0 / factor)
    return tuple(round(c * 255) for c in colorsys.hsv_to_rgb(h, s, v))


# Tile pairs that read as the same texture on a map, so using one of each
# separates nothing. Judged by eye against rendered previews rather than by
# a similarity metric - a first attempt at scoring tile similarity
# automatically called crosses-vs-chevrons the closest pair in the set and
# two brick variants among the furthest, so it was not fit to decide this.
LOOKALIKE_TILES = frozenset([
    frozenset(("gneiss", "migmatite")),
    frozenset(("marble", "chalk")),
    frozenset(("gabbro", "peridotite")),
    frozenset(("schist", "serpentinite")),
])

# Separation between two codes that could be mapped adjacent.
#
# Two bars, because they mean different things. IDENTICAL is indefensible and
# aborts the run: two different rocks rendering as the same pixels is the bug
# this whole check exists to catch. TOO CLOSE is a judgement call and only
# warns - pushing every varietal pair (gabbronorite vs olivine gabbro) to a
# comfortable delta would drag the palette out of the muted band, and the
# polygon's code label already carries that distinction.
IDENTICAL_DE = 1.5
MIN_FILL_DE = 7.0
MIN_INK_DE = 30.0

# Flipped to True once the cross-family scan came back clean, so the check is
# enforced rather than advisory. A module constant rather than a --report flag
# on purpose: a flag can be left off and the gate silently never enforced,
# whereas flipping this is visible in the diff and cannot be half-done.
IDENTICAL_ABORTS = True

# The Transported Cover / bedrock boundary is a COLOUR boundary. distinct()
# passes any pair whose tiles differ without ever comparing colour, which is
# how all 21 cover codes sat on the sandstone cream unflagged - TCO rendered
# as SST, byte-for-byte on TALL. On a SHARED tile a cross-type pair must now
# separate on fill alone; across different tiles near pairs are only
# reported, because a pale-grey cover family cannot be dE 7 from every
# neutral bedrock code (SSL, SCT) and there the tile genuinely separates.
# Same flip-to-enforce convention as IDENTICAL_ABORTS above.
COVER_COLOUR_ABORTS = True
COVER_TYPE = "Transported Cover"
COVER_ADVISORY_DE = 5.0

# Cover round 4: the cover texture prints as a faint watermark, not at
# bedrock strength. The user's call off the deployed round-3 map - the
# salmon TCO clasts at INK_BASE strength were half of what made cover
# "too intense". Cover is a veil; its motifs only need to whisper, the
# amber contact and label carry the identity. The weak-ink floor at the
# use site is max(WEAK_INK_FLOOR, target * WEAK_INK_MARGIN), computed
# from the SAME per-code target, so this stays self-consistent - and
# tests/test_basemap_lith_patterns_qgis.py calls ink_target() too, so
# the two cannot disagree.
COVER_INK_TARGET = 1.28

# ---- per-feature modulation (see inject_basemap_lith_modulation.py) ----
# The Lith2 fill blend and texture nudge live in the LIVE template (virtual
# fields + a dd fillColor on every class symbol, written by the modulation
# injector and carried into this template by convertFromRenderer). What is
# added HERE is the pattern side: grain-size textures scale the one SVGFill's
# tile, and the mapper's Lith1Mineral1 tints the pattern ink toward its
# mineral family's colour from mineral_inks.tsv.
#
# The constants are shared: the modulation injector imports them from here so
# the two halves of one feature cannot disagree.
LITH2_MIX = 0.15       # fill leans 15% toward Lithology2's palette colour
MINERAL_MIX = 0.35     # pattern ink leans 35% toward the mineral family ink
NUDGE_FACTORS = (96, 104)   # darker()/lighter() extremes of the texture nudge
MODULATION_MARK = "LGS_Lith2Fill"   # virtual field: presence = applied
MODULATION_DD_MARK = "LGS_ModFill"  # what the symbols' dd fillColor reads


def ink_target(code, texture, tile_ink, type_of):
    """The ink contrast target for one code: the tile's target for
    bedrock, the softened flat target for Transported Cover."""
    if type_of.get(code) == COVER_TYPE:
        return COVER_INK_TARGET
    return target_for_ink_pct(tile_ink[texture])


def _hue_gap(a, b):
    """Smallest angle between two colours' hues, in degrees."""
    ha = colorsys.rgb_to_hls(*[c / 255.0 for c in a])[0] * 360.0
    hb = colorsys.rgb_to_hls(*[c / 255.0 for c in b])[0] * 360.0
    d = abs(ha - hb) % 360.0
    return min(d, 360.0 - d)


def fit_fill_to_ink(fill, ink):
    """Move the FILL's lightness until a mineral ink reads on it.

    The ink is what carries the meaning here, so the ink is what must not
    move. An earlier version slid the ink instead and destroyed exactly the
    signals this feature exists for: anorthosite's white plagioclase dots
    came out near-black, chromite came out near-white, iron formation went
    pale - each because the ink had been dragged across the fill to chase a
    contrast number.

    So: hold the ink exactly as authored, hold the fill's family hue and
    saturation, and slide only the fill's lightness away from the ink. The
    range is bounded to keep the result inside the muted palette.
    """
    if contrast(fill, ink) >= MINERAL_CONTRAST:
        return fill
    fh, fl, fs = colorsys.rgb_to_hls(*[c / 255.0 for c in fill])
    il = colorsys.rgb_to_hls(*[c / 255.0 for c in ink])[1]
    best, best_r = fill, contrast(fill, ink)
    # away from the ink first, then the other way if that cannot reach it
    for end in ((0.30, 0.93) if il >= fl else (0.93, 0.30)):
        for i in range(1, 101):
            L = fl + (end - fl) * i / 100.0
            # Same muted clamps lith_palette applies. Darkening a
            # pale-but-saturated pastel without them turns it fluorescent.
            s = fs
            if L < fl:
                s *= 0.55 + 0.45 * (L / fl)
            if L < 0.62:
                s = min(s, 0.46)
            cand = tuple(round(c * 255)
                         for c in colorsys.hls_to_rgb(fh, L, s))
            r = contrast(cand, ink)
            if r > best_r:
                best, best_r = cand, r
            if r >= MINERAL_CONTRAST:
                return cand
    return best


def soften_mineral(fill, ink, target):
    """Pull a mineral ink back toward its fill until it is only as strong as
    it needs to be.

    MINERAL_CONTRAST is a MINIMUM, and the mineral inks are absolute authored
    colours, so nothing was capping the ones that land far above it: with the
    dial soft, RCC's carbonate ink sat at 5.9:1 while the auto tints around it
    were at 1.3:1. That is 93 codes ignoring the softness setting.

    Blends toward the fill and never past it, which is what makes this safe.
    An earlier round destroyed these signals by sliding an ink's lightness to
    CHASE contrast - anorthosite's white plagioclase came out near-black.
    Interpolating toward the fill cannot do that: a pale ink stays paler than
    its fill and a dark ink stays darker, because the direction is preserved by
    construction. Only the amount changes.
    """
    if contrast(fill, ink) <= target:
        return ink

    def blend(t):
        return tuple(round(ink[i] + (fill[i] - ink[i]) * t) for i in range(3))

    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2.0
        if contrast(fill, blend(mid)) > target:
            lo = mid
        else:
            hi = mid
    return blend(hi)


def hexof(rgb):
    return "#%02x%02x%02x" % rgb


# ----------------------------------------------------------------- inputs
def load_tiles():
    if not os.path.isdir(PATTERN_DIR):
        bail("no %s - run scripts/prepare_lith_patterns.py first" % PATTERN_DIR)
    tiles = {}
    for fn in sorted(os.listdir(PATTERN_DIR)):
        if fn.endswith(".svg"):
            with open(os.path.join(PATTERN_DIR, fn), encoding="utf-8") as fh:
                tiles[fn[:-4]] = fh.read()
    if BLANK not in tiles:
        bail("%s.svg missing from %s" % (BLANK, PATTERN_DIR))
    return tiles


def load_stroke_widths(tiles):
    """{texture: width_pt} from stroke_widths.tsv.

    One shared width cannot serve this artwork: a dot's visible size IS its
    stroke width, so the stipple tiles are invisible below ~1 pt, while the
    dense line tiles are already solid mud at 0.3 pt - about a 35x spread.
    scripts/calibrate_lith_strokes.py measures the per-tile value.
    """
    if not os.path.exists(STROKE_WIDTHS):
        bail("missing %s - run scripts/calibrate_lith_strokes.py"
             % STROKE_WIDTHS)
    out = {}
    with open(STROKE_WIDTHS, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if parts[0] == "texture":
                continue
            if len(parts) < 2:
                bail("malformed row in %s: %r" % (STROKE_WIDTHS, line))
            try:
                out[parts[0]] = float(parts[1])
            except ValueError:
                bail("bad width in %s: %r" % (STROKE_WIDTHS, line))
    missing = sorted({t for t in tiles if t != BLANK} - set(out))
    if missing:
        bail("no calibrated stroke width for: %s (re-run "
             "scripts/calibrate_lith_strokes.py)" % ", ".join(missing))
    return out


def load_tile_ink(tiles):
    """{texture: ink_pct} - column 3 of stroke_widths.tsv.

    The measured ink coverage each tile achieves at its calibrated width. This
    is what makes the contrast target per-texture; see INK_BASE. Kept separate
    from load_stroke_widths() so that function's return shape stays a plain
    {texture: width} for its existing callers.
    """
    out = {}
    with open(STROKE_WIDTHS, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if parts[0] == "texture" or len(parts) < 3:
                continue
            try:
                out[parts[0]] = float(parts[2])
            except ValueError:
                bail("bad ink_pct in %s: %r" % (STROKE_WIDTHS, line))
    missing = sorted({t for t in tiles if t != BLANK} - set(out))
    if missing:
        bail("no measured ink coverage for: %s - stroke_widths.tsv predates "
             "the per-texture contrast target; re-run "
             "scripts/calibrate_lith_strokes.py" % ", ".join(missing))
    return out


def load_mineral_inks():
    """{ink_name: (r,g,b)} from mineral_inks.tsv."""
    if not os.path.exists(MINERAL_INKS):
        bail("missing %s" % MINERAL_INKS)
    out = {}
    with open(MINERAL_INKS, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            p = line.split("\t")
            if p[0] == "ink" or len(p) < 2:
                continue
            h = p[1].lstrip("#")
            if len(h) != 6:
                bail("bad hex in %s: %r" % (MINERAL_INKS, line))
            out[p[0]] = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return out


def load_texture_modulation():
    """{'tile': {texture: multiplier}, 'nudge': {texture: factor}} from
    texture_modulation.tsv. Texture-name validity against TextureCodes is the
    caller's job (each injector reads its own gpkg)."""
    if not os.path.exists(TEXTURE_MODULATION):
        bail("missing %s" % TEXTURE_MODULATION)
    out = {"tile": {}, "nudge": {}}
    with open(TEXTURE_MODULATION, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            p = line.split("\t")
            if p[0] == "texture":
                continue
            if len(p) < 3 or p[1] not in out:
                bail("%s:%d malformed row: %r" % (TEXTURE_MODULATION, n, line))
            texture, channel = p[0], p[1]
            if texture in out["tile"] or texture in out["nudge"]:
                bail("%s:%d duplicate texture %r"
                     % (TEXTURE_MODULATION, n, texture))
            try:
                value = float(p[2]) if channel == "tile" else int(p[2])
            except ValueError:
                bail("%s:%d bad value: %r" % (TEXTURE_MODULATION, n, line))
            if channel == "tile" and not 0.5 <= value <= 2.0:
                bail("%s:%d tile multiplier %s outside sanity range 0.5-2.0"
                     % (TEXTURE_MODULATION, n, p[2]))
            if channel == "nudge" and not 80 <= value <= 125:
                bail("%s:%d nudge factor %s outside sanity range 80-125"
                     % (TEXTURE_MODULATION, n, p[2]))
            out[channel][texture] = value
    if not out["tile"]:
        bail("%s has no tile rows" % TEXTURE_MODULATION)
    return out


def load_mineral_families(inks):
    """{mineral_abbrev: ink_name} from mineral_families.tsv. Every ink must
    exist in mineral_inks.tsv; mineral validity against MineralCodes is the
    caller's job."""
    if not os.path.exists(MINERAL_FAMILIES):
        bail("missing %s" % MINERAL_FAMILIES)
    out = {}
    with open(MINERAL_FAMILIES, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            p = line.split("\t")
            if p[0] == "mineral":
                continue
            if len(p) < 2:
                bail("%s:%d malformed row: %r" % (MINERAL_FAMILIES, n, line))
            mineral, ink = p[0], p[1]
            if mineral in out:
                bail("%s:%d duplicate mineral %r"
                     % (MINERAL_FAMILIES, n, mineral))
            if ink not in inks:
                bail("%s:%d unknown ink %r (not in mineral_inks.tsv)"
                     % (MINERAL_FAMILIES, n, ink))
            out[mineral] = ink
    if not out:
        bail("%s has no rows" % MINERAL_FAMILIES)
    return out


def load_texture_map(codes, tiles):
    """{code: (texture, note, ink)} from the TSV, asserted 1:1 against codes."""
    if not os.path.exists(TEXTURE_MAP):
        bail("missing %s" % TEXTURE_MAP)
    out = {}
    with open(TEXTURE_MAP, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if parts[0] == "code":
                continue
            if len(parts) < 2:
                bail("%s:%d malformed row: %r" % (TEXTURE_MAP, n, line))
            code, texture = parts[0], parts[1]
            note = parts[4] if len(parts) > 4 else "-"
            ink = parts[5] if len(parts) > 5 else "auto"
            variety = parts[6] if len(parts) > 6 and parts[6] != "-" else ""
            if code in out:
                bail("%s:%d duplicate code %r" % (TEXTURE_MAP, n, code))
            out[code] = (texture, note, ink, variety)

    missing = sorted(set(codes) - set(out))
    extra = sorted(set(out) - set(codes))
    unknown = sorted({t for t, _n, _i, _v in out.values()} - set(tiles))
    if missing:
        bail("%d codes in BasemapCodes have no row in %s: %s"
             % (len(missing), os.path.basename(TEXTURE_MAP),
                ", ".join(missing[:15])))
    if extra:
        bail("%d rows name codes that are not in BasemapCodes: %s"
             % (len(extra), ", ".join(extra[:15])))
    if unknown:
        bail("textures with no tile in Template/patterns/: " + ", ".join(unknown))
    return out


# ------------------------------------------------------------ expressions
def b64(svg):
    return "base64:" + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def sql_quote(v):
    return "'" + v.replace("'", "''") + "'"


def case_expr(groups, value_of, else_value):
    """CASE over IN-lists: one branch per distinct value, not per code."""
    parts = ["CASE"]
    for key in sorted(groups):
        codes = ", ".join(sql_quote(c) for c in sorted(groups[key]))
        parts.append('  WHEN "%s" IN (%s) THEN %s'
                     % (FIELD, codes, sql_quote(value_of(key))))
    parts.append("  ELSE %s" % sql_quote(else_value))
    parts.append("END")
    return "\n".join(parts)


def main():
    dry = "--dry-run" in sys.argv

    if not os.path.exists(ORIGINAL):
        bail("original template not found: " + ORIGINAL)
    if os.path.abspath(TARGET) == os.path.abspath(ORIGINAL):
        bail("target resolves to the live template - refusing")
    if os.path.basename(TARGET) == os.path.basename(ORIGINAL):
        bail("target basename equals the live template - refusing")

    tiles = load_tiles()
    widths = load_stroke_widths(tiles)
    tile_ink = load_tile_ink(tiles)
    inks = load_mineral_inks()

    con = sqlite3.connect("file:%s?mode=ro" % ORIGINAL.replace("\\", "/"),
                          uri=True)
    rows = con.execute("SELECT Code FROM BasemapCodes").fetchall()
    minerals = {r[0] for r in con.execute("SELECT Value FROM MineralCodes")}
    texture_codes = {r[0] for r in con.execute("SELECT Code FROM TextureCodes")}
    live_qml = con.execute(
        "SELECT styleQML FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()[0]
    con.close()
    codes = [r[0] for r in rows]
    if not codes:
        bail("BasemapCodes is empty")
    tex_map = load_texture_map(codes, tiles)

    # ---- per-feature modulation: is the live template carrying it? -------
    # Half-applied is the one state that must not slip through a re-bake: the
    # virtual field without the dd fillColor renders nothing, the dd without
    # the field is an expression error on every polygon.
    has_vf = ('<field name="%s"' % MODULATION_MARK) in live_qml
    has_dd = ('name="fillColor"' in live_qml
              and MODULATION_DD_MARK in live_qml.split("<renderer-v2", 1)[-1])
    if has_vf != has_dd:
        bail("live template carries a half-applied modulation state "
             "(virtual field %s, dd fillColor %s) - run "
             "scripts/inject_basemap_lith_modulation.py first"
             % (has_vf, has_dd))
    modulation_active = has_vf and has_dd
    if modulation_active:
        mod_tsv = load_texture_modulation()
        unknown = sorted((set(mod_tsv["tile"]) | set(mod_tsv["nudge"]))
                         - texture_codes)
        if unknown:
            bail("texture_modulation.tsv names textures not in TextureCodes: "
                 + ", ".join(unknown))
        families = load_mineral_families(inks)
        unknown = sorted(set(families) - minerals)
        if unknown:
            bail("mineral_families.tsv names minerals not in MineralCodes: "
                 + ", ".join(unknown))
        print("modulation: live template carries %s - adding tile-width and "
              "mineral-ink channels (%d grain textures, %d minerals -> %d "
              "families)" % (MODULATION_MARK, len(mod_tsv["tile"]),
                             len(families), len(set(families.values()))))
    else:
        mod_tsv, families = None, None
        print("modulation: live template does not carry %s - baking the "
              "pre-modulation pattern (run inject_basemap_lith_modulation.py "
              "to enable)" % MODULATION_MARK)

    # ---- fills and inks: pure colour maths, no QGIS needed ------------
    # Deliberately ahead of initQgis(). Any failure here aborts with a clean
    # message; raising inside the QGIS block instead lets the abort race a
    # teardown segfault and the reason is lost.
    deepen = [c for c, (_t, _n, ink, _v) in tex_map.items()
              if ink in PALE_INKS]
    fill_of = lith_palette.build(deepen=deepen)
    missing_fill = sorted(set(tex_map) - set(fill_of))
    if missing_fill:
        bail("no fill colour for: %s" % ", ".join(missing_fill[:15]))

    type_of = {c: t for c, (_tex, _var, t)
               in lith_palette.read_texture_map().items()}
    by_texture, by_colour, by_width = {}, {}, {}
    ink_of, weak, tautology, unfittable, n_mineral = {}, [], [], [], 0
    short = []
    for code, (texture, _note, ink_name, _var) in tex_map.items():
        by_texture.setdefault(texture, []).append(code)
        by_width.setdefault("%.3f" % widths[texture], []).append(code)
        target = ink_target(code, texture, tile_ink, type_of)
        fill = fill_of[code]
        if ink_name and ink_name != "auto":
            if ink_name not in inks:
                bail("code %s names unknown ink %r" % (code, ink_name))
            mineral = inks[ink_name]
            # Only a fill whose hue was set BY chemistry can be tautological.
            # A family hue that merely lands near the ink is a coincidence:
            # the mafic cyan sits close to quartz blue, but "mafic" and
            # "quartz-bearing" are different statements, and treating that as
            # a tautology silently dropped the quartz signal from MDQ Quartz
            # Dolerite - one of the two cases this feature was asked for.
            # ...and CHEMICAL_HUE only applies to Lithology codes now, so a
            # regolith code on a chert or laterite tile keeps its own cream
            # fill and is NOT chemically hued. Asking the same question the
            # palette asked keeps the two from disagreeing.
            chem_fill = lith_palette.is_chemically_hued(
                code, texture, type_of.get(code, ""))
            if chem_fill and _hue_gap(fill, mineral) <= HUE_TAUTOLOGY_DEG:
                # the fill already carries this chemistry - don't say it twice
                ink = tint(fill, target)[0]
                tautology.append(code)
            else:
                # NB do NOT re-add the slot offset here. The fill arriving
                # from lith_palette already carries it, so adding it again
                # after fitting double-counts and walks the colour out of the
                # family - it is what drove the olivine gabbros to a near
                # white #e8eff2 instead of a mafic teal.
                fitted = fit_fill_to_ink(fill, mineral)
                if contrast(fitted, mineral) >= MINERAL_CONTRAST:
                    fill = fitted
                    fill_of[code] = fill
                    # fit_fill_to_ink RAISES a pair that is too weak; this
                    # LOWERS one that is far stronger than the tile needs, so
                    # a mineral code tracks the softness dial like everything
                    # else. It keeps a slightly higher bar - the mineral inks
                    # carry diagnostic mineralogy, so they should read as the
                    # strongest mark on the page, just not four times over.
                    ink = soften_mineral(
                        fill, mineral, max(MINERAL_CONTRAST, target))
                    n_mineral += 1
                else:
                    # The fill cannot move far enough inside the muted band to
                    # host this ink. Legibility wins over the mineral signal:
                    # an invisible texture says nothing at all.
                    ink = tint(fill, target)[0]
                    unfittable.append((code, ink_name))
        else:
            ink = tint(fill, target)[0]
        ink_of[code] = ink
        r = contrast(fill, ink)
        # Scaled to the code's OWN target, not a flat 3.0. A flat floor made
        # sense while every texture aimed at 4.5; against a 2.15 target it
        # would abort on 55-123 perfectly good codes for the crime of hitting
        # the softness they were asked for. The absolute floor stops a very
        # small target from disabling the check altogether.
        floor = max(WEAK_INK_FLOOR, target * WEAK_INK_MARGIN)
        if r < floor:
            weak.append((code, ink_name, r))
        elif r < target - 0.01:
            short.append((code, texture, r, target))
        by_colour.setdefault(hexof(ink), []).append(code)
    if weak:
        worst = sorted(weak, key=lambda t: t[2])[:8]
        bail("%d code(s) have an ink that cannot separate from their fill: %s"
             % (len(weak), ", ".join("%s/%s %.2f" % w for w in worst)))
    if short:
        print("     %d code(s) fall short of their own target (palette too "
              "flat to reach it, still above the floor): %s"
              % (len(short), ", ".join("%s %.2f<%.2f" % (c, r, t)
                                       for c, _x, r, t in sorted(short)[:6])))

    # ---- separation: codes that could sit side by side must differ -------
    # Round 3 verified that TEXTURES were distinct and reported that as
    # distinctness. It never checked that CODES were, and 218 of the 283
    # shared an identical (fill, ink, tile) triple with another code. This is
    # that missing check.
    def distinct(a, b):
        ta, tb = tex_map[a][0], tex_map[b][0]
        if ta != tb and frozenset((ta, tb)) not in LOOKALIKE_TILES:
            return True
        if delta_e(fill_of[a], fill_of[b]) >= MIN_FILL_DE:
            return True
        return delta_e(ink_of[a], ink_of[b]) >= MIN_INK_DE

    def acceptable_lookalikes(a, b):
        va, vb = tex_map[a][3], tex_map[b][3]
        return bool(va) and va == vb

    by_family = {}
    for code in tex_map:
        by_family.setdefault(lith_palette._family_of(code), []).append(code)
    clashes = []
    for fam, members in by_family.items():
        members.sort()
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                if acceptable_lookalikes(a, b):
                    continue          # declared acceptable look-alikes
                if not distinct(a, b):
                    clashes.append((delta_e(fill_of[a], fill_of[b]), a, b,
                                    tex_map[a][0]))

    # The IDENTICAL bar is GLOBAL; the "too close" warning above stays
    # within-family. Two different rocks rendering as the same pixels is
    # indefensible wherever they sit in the code list, and scoping this check
    # by family made it blind to exactly the cases that occur: a chemistry hue
    # or a shared cream anchor collides ACROSS families, never inside one.
    # It was missing nine pairs - RCC Calcrete drawn as SLI Limestone, Gossan
    # as Iron Formation, Ironstone as Jaspilite, Ferricrete as TDLP, Evaporite
    # as Gypsum, and all four lateritic duricrusts as TLTP.
    # Within-family stays a warning because pushing every varietal pair to a
    # comfortable delta would drag the palette out of the muted band.
    all_codes = sorted(tex_map)
    identical = []
    for i, a in enumerate(all_codes):
        for b in all_codes[i + 1:]:
            if acceptable_lookalikes(a, b):
                continue
            if distinct(a, b):
                continue
            if (delta_e(fill_of[a], fill_of[b]) < IDENTICAL_DE
                    and delta_e(ink_of[a], ink_of[b]) < IDENTICAL_DE):
                identical.append((delta_e(fill_of[a], fill_of[b]), a, b,
                                  tex_map[a][0]))
    print("separation: %d within-family pairs closer than dE %.0f, "
          "%d effectively identical (checked across ALL %d codes)"
          % (len(clashes), MIN_FILL_DE, len(identical), len(all_codes)))
    for de, a, b, t in sorted(clashes)[:8]:
        print("     %-8s / %-8s  tile %-14s fill dE %.1f"
              % (a, b, t, de))
    if identical:
        for de, a, b, t in sorted(identical)[:12]:
            print("   IDENTICAL %-8s / %-8s  tile %-14s (%s / %s)"
                  % (a, b, t, lith_palette._family_of(a),
                     lith_palette._family_of(b)))
        if not IDENTICAL_ABORTS:
            print("   ^ report-only: set IDENTICAL_ABORTS = True to enforce")
        else:
            bail("%d pairs of different rocks render identically - give them "
                 "different textures, or declare them a `variety` group in "
                 "lith_textures.tsv if that is genuinely acceptable"
                 % len(identical))

    # ---- cover vs bedrock: enforce the type boundary in colour -----------
    cover = [c for c in all_codes if type_of.get(c) == COVER_TYPE]
    bedrock = [c for c in all_codes if type_of.get(c) != COVER_TYPE]
    cover_clashes, cover_near = [], []
    for a in cover:
        for b in bedrock:
            de = delta_e(fill_of[a], fill_of[b])
            if tex_map[a][0] == tex_map[b][0]:
                if de < MIN_FILL_DE:
                    cover_clashes.append((de, a, b, tex_map[a][0]))
            elif de < COVER_ADVISORY_DE:
                cover_near.append((de, a, b, tex_map[b][0]))
    print("cover/bedrock: %d same-tile pairs under dE %.0f, %d cross-tile "
          "pairs under dE %.0f (advisory, tile separates)"
          % (len(cover_clashes), MIN_FILL_DE,
             len(cover_near), COVER_ADVISORY_DE))
    for de, a, b, t in sorted(cover_near)[:8]:
        print("     near %-8s / %-8s  bedrock tile %-14s fill dE %.1f"
              % (a, b, t, de))
    if cover_clashes:
        for de, a, b, t in sorted(cover_clashes)[:12]:
            print("   COVER CLASH %-8s / %-8s  tile %-14s fill dE %.1f"
                  % (a, b, t, de))
        if not COVER_COLOUR_ABORTS:
            print("   ^ report-only: set COVER_COLOUR_ABORTS = True to "
                  "enforce")
        else:
            bail("%d cover codes share a tile AND a colour with bedrock - "
                 "move the cover anchor in the live template "
                 "(inject_basemap_cover_recolour.py is the precedent)"
                 % len(cover_clashes))

    svg_expr = case_expr(by_texture, lambda t: b64(tiles[t]), b64(tiles[BLANK]))
    col_expr = case_expr(by_colour, lambda h: h, hexof((0x13, 0x13, 0x13)))
    wid_expr = case_expr(by_width, lambda w: w, "%.3f" % TILE_STROKE_PT)

    # ---- per-feature modulation: pattern-side channels -------------------
    tile_width_expr = None
    if modulation_active:
        # Mineral -> ink family tint. A code whose ink, pulled MINERAL_MIX
        # toward a family colour, can no longer separate from its own fill is
        # EXCLUDED from that family's branch and keeps its base ink - the
        # same "legibility wins over the mineral signal" rule as unfittable
        # inks above. Exclusions ride the expression as AND NOT clauses, so
        # the decision is baked, auditable, and costs nothing at render.
        fam_minerals = {}
        for m, f in families.items():
            fam_minerals.setdefault(f, []).append(m)
        excl, n_excl_pairs = {}, 0
        for fam in sorted(fam_minerals):
            fam_rgb = inks[fam]
            for code in sorted(tex_map):
                blended = mix_rgb(ink_of[code], fam_rgb, MINERAL_MIX)
                target = ink_target(code, tex_map[code][0], tile_ink, type_of)
                floor = max(WEAK_INK_FLOOR, target * WEAK_INK_MARGIN)
                if contrast(fill_of[code], blended) < floor:
                    excl.setdefault(fam, []).append(code)
                    n_excl_pairs += 1
        parts = ["CASE"]
        for fam in sorted(fam_minerals):
            mins = ", ".join(sql_quote(m) for m in sorted(fam_minerals[fam]))
            cond = '"Lith1Mineral1" IN (%s)' % mins
            if fam in excl:
                cond += (' AND NOT "%s" IN (%s)'
                         % (FIELD, ", ".join(sql_quote(c)
                                             for c in sorted(excl[fam]))))
            parts.append("  WHEN %s THEN %s"
                         % (cond, sql_quote(hexof(inks[fam]))))
        parts.append("  ELSE ''")
        parts.append("END")
        mineral_case = "\n".join(parts)
        col_expr = ("if(%s = '', %s,\ncolor_mix_rgb(%s,\n%s, %s))"
                    % (mineral_case, col_expr, col_expr, mineral_case,
                       MINERAL_MIX))
        print("mineral ink tint: %d families, %d code/family pairs excluded "
              "(ink could not separate from its own fill)"
              % (len(fam_minerals), n_excl_pairs))
        if excl:
            for fam in sorted(excl):
                print("     %-12s keeps base ink on: %s"
                      % (fam, ", ".join(sorted(excl[fam])[:10])
                         + (" ..." if len(excl[fam]) > 10 else "")))

        # Grain size -> tile width. The multiplier is relative, so it is
        # scale-neutral under referenceScale; the stroke is compensated by
        # sqrt(m) so ink density stays within ~10% of the calibrated 8%
        # while coarse tiles still read slightly airier - which is the
        # point: coarse = bigger, sparser motifs.
        tile_groups = {}
        for tex, mult in mod_tsv["tile"].items():
            if mult != 1.0:
                tile_groups.setdefault(mult, []).append(tex)

        def grain_case(fmt):
            gparts = ["CASE"]
            for field in ("Lith1Texture1", "Lith1Texture2"):
                for mult in sorted(tile_groups):
                    names = ", ".join(sql_quote(t)
                                      for t in sorted(tile_groups[mult]))
                    gparts.append('  WHEN "%s" IN (%s) THEN %s'
                                  % (field, names, fmt(mult)))
            gparts.append("  ELSE 1.0")
            gparts.append("END")
            return "\n".join(gparts)

        tile_width_expr = ("%s * %s"
                           % (TILE_WIDTH_PT, grain_case(lambda m: "%.2f" % m)))
        wid_expr = ("(%s) * %s"
                    % (wid_expr, grain_case(lambda m: "%.3f" % (m ** 0.5))))
        print("tile width: %d grain-size multipliers, %.2f-%.2fx"
              % (len(tile_groups), min(tile_groups), max(tile_groups)))

    print("%d codes -> %d textures" % (len(tex_map), len(by_texture)))
    anchors = lith_palette.read_code_anchors()
    kept = sum(1 for c, rgb in fill_of.items() if anchors.get(c) == rgb)
    print("fills: %d distinct; %d codes keep the template's exact colour"
          % (len(set(fill_of.values())), kept))
    print("inks: %d distinct, %d carry a mineral signal, %d auto-tinted"
          % (len(by_colour), n_mineral, len(tex_map) - n_mineral))
    if unfittable:
        print("     %d dropped to auto (fill cannot host the ink legibly): %s"
              % (len(unfittable),
                 ", ".join("%s/%s" % u for u in sorted(unfittable))))
    if tautology:
        print("     %d fell back to auto (fill already says it): %s"
              % (len(tautology), ", ".join(sorted(tautology)[:12])))
    print("stroke width: %d distinct values, %.2f-%.2f pt"
          % (len(by_width), min(widths.values()), max(widths.values())))
    print("expressions: svgFile %.1f KB, strokeColor %.1f KB, strokeWidth %.1f KB"
          % (len(svg_expr) / 1024.0, len(col_expr) / 1024.0,
             len(wid_expr) / 1024.0))

    if dry:
        print("--dry-run: nothing written")
        return

    if not dry:
        fresh = not os.path.exists(TARGET)
        shutil.copy2(ORIGINAL, TARGET)
        print("%s %s from the live template"
              % ("created" if fresh else "re-copied", os.path.basename(TARGET)))
    work = TARGET

    from qgis.core import (QgsApplication, QgsVectorLayer, QgsFillSymbol,
                           QgsLineSymbol, QgsSVGFillSymbolLayer, QgsSymbolLayer,
                           QgsProperty, QgsRuleBasedRenderer,
                           QgsCategorizedSymbolRenderer, QgsUnitTypes,
                           QgsReadWriteContext)
    from qgis.PyQt.QtXml import QDomDocument
    from qgis.PyQt.QtGui import QColor

    QgsApplication.setPrefixPath(os.environ.get(
        "QGIS_PREFIX_PATH", "C:/OSGeo4W/apps/qgis-ltr"), True)
    app = QgsApplication([], False)
    app.initQgis()
    qml = None
    try:
        layer = QgsVectorLayer("%s|layername=%s" % (work, LAYER), LAYER, "ogr")
        if not layer.isValid():
            bail("could not load layer %r from %s" % (LAYER, work))
        cat = layer.renderer()
        if not isinstance(cat, QgsCategorizedSymbolRenderer):
            bail("expected a categorized renderer, got %s" % type(cat).__name__)
        if cat.classAttribute() != FIELD:
            bail("renderer attr is %r, expected %r"
                 % (cat.classAttribute(), FIELD))
        if len(cat.categories()) != EXPECT_CATS:
            bail("expected %d categories, found %d"
                 % (EXPECT_CATS, len(cat.categories())))

        rule_renderer = QgsRuleBasedRenderer.convertFromRenderer(cat)
        if rule_renderer is None:
            bail("convertFromRenderer returned None")
        n_colour = len(rule_renderer.rootRule().children())
        if n_colour != EXPECT_CATS:
            bail("conversion produced %d rules, expected %d"
                 % (n_colour, EXPECT_CATS))

        # ---- paint each colour rule from the palette ---------------------
        eq_re = re.compile(r"""^\s*"[^"]+"\s*=\s*'((?:[^']|'')*)'\s*$""")
        painted = set()
        for rule in rule_renderer.rootRule().children():
            m = eq_re.match((rule.filterExpression() or "").strip())
            if not m:
                continue                      # the ELSE / catch-all rule
            code = m.group(1).replace("''", "'")
            rgb = fill_of.get(code)
            sym = rule.symbol()
            if rgb is None or sym is None:
                continue
            for i in range(sym.symbolLayerCount()):
                sl = sym.symbolLayer(i)
                if sl.layerType() == "SimpleFill":
                    sl.setColor(QColor(*rgb))
                    painted.add(code)
                    break
        if len(painted) != len(fill_of):
            bail("painted %d rules but the palette has %d codes; unpainted: %s"
                 % (len(painted), len(fill_of),
                    ", ".join(sorted(set(fill_of) - painted)[:10])))

        svg = QgsSVGFillSymbolLayer(b64(tiles[BLANK]), TILE_WIDTH_PT, 0.0)
        svg.setPatternWidthUnit(QgsUnitTypes.RenderPoints)
        svg.setSvgStrokeWidth(TILE_STROKE_PT)
        svg.setSvgStrokeWidthUnit(QgsUnitTypes.RenderPoints)
        # NB no setSvgFillColor(): every one of the tiles is pure line art
        # with fill="none" throughout, so param(fill) appears nowhere and
        # the fill-colour control is inert. param(outline) is the live one.
        svg.setDataDefinedProperty(QgsSymbolLayer.PropertyFile,
                                   QgsProperty.fromExpression(svg_expr))
        svg.setDataDefinedProperty(QgsSymbolLayer.PropertyStrokeColor,
                                   QgsProperty.fromExpression(col_expr))
        svg.setDataDefinedProperty(QgsSymbolLayer.PropertyStrokeWidth,
                                   QgsProperty.fromExpression(wid_expr))
        if tile_width_expr is not None:
            # grain-size textures scale the tile; the multiplier is relative
            # to TILE_WIDTH_PT so Set Mapping Scale stays agnostic of it
            svg.setDataDefinedProperty(QgsSymbolLayer.PropertyWidth,
                                       QgsProperty.fromExpression(
                                           tile_width_expr))
        # the SVGFill's own sub-symbol would draw a SECOND polygon outline on
        # top of the ContactType line the colour rules already draw
        svg.setSubSymbol(QgsLineSymbol.createSimple({"line_style": "no"}))

        pattern_rule = QgsRuleBasedRenderer.Rule(
            QgsFillSymbol([svg]), 0, PATTERN_MAX_SCALE, "", PATTERN_RULE_LABEL)
        rule_renderer.rootRule().appendChild(pattern_rule)

        rule_renderer.setReferenceScale(REFERENCE_SCALE)
        rule_renderer.setOrderBy(cat.orderBy())
        rule_renderer.setOrderByEnabled(cat.orderByEnabled())
        layer.setRenderer(rule_renderer)

        doc = QDomDocument()
        ctx = QgsReadWriteContext()
        res = layer.exportNamedStyle(doc, ctx)
        err = res if isinstance(res, str) else ""
        if err:
            bail("exportNamedStyle: " + err)
        qml = doc.toString()

        # Drop every QGIS object while the application is still up. If these
        # survive to interpreter shutdown their destructors run against a
        # torn-down QgsApplication and segfault - which would exit 139 long
        # after the work succeeded and read as a failure.
        del doc, ctx, pattern_rule, svg, rule_renderer, cat, layer
    finally:
        app.exitQgis()
        del app

    if qml is None:
        return
    if "FilterExpression" not in qml:
        bail("exported QML lost the ValueRelation FilterExpression config")

    if modulation_active:
        # The live template blends from ITS anchors; this template just
        # repainted every rule from lith_palette.build() (plus the
        # fit_fill_to_ink shifts above), so the colour-carrying virtual
        # fields are regenerated here from the painted fills - each template
        # blends from exactly what it draws. Imported lazily: the modulation
        # injector imports this module at top level, and both are fully
        # initialised by the time main() runs.
        import inject_basemap_lith_modulation as modx
        pal_tex_map = lith_palette.read_texture_map()
        replacements = {
            modx.LITH2_FIELD: modx.build_fill_case(fill_of, "Lithology2"),
            modx.BASE_FIELD: modx.build_fill_case(fill_of, "Lithology1"),
            modx.MIXCAP_FIELD: modx.build_mixcap_case(
                modx.resolve_mix_caps(fill_of, pal_tex_map)),
        }
        ef = re.search(r'<expressionfields>.*?</expressionfields>', qml, re.S)
        if not ef:
            bail("baked QML lost the <expressionfields> block")
        body = ef.group(0)
        for name in sorted(replacements):
            att = modx.xml_attr(replacements[name])
            tag_pat = re.compile(r'<field\b[^>]*name="%s"[^>]*>' % name)

            def fix(m, att=att, name=name):
                tag, k = re.subn(r'expression="[^"]*"',
                                 lambda _m: 'expression="%s"' % att,
                                 m.group(0), count=1)
                if k != 1:
                    bail("field %s has no expression attribute" % name)
                return tag

            body, n = tag_pat.subn(fix, body)
            if n != 1:
                bail("could not rewrite %s in the baked QML (%d hits) - "
                     "the exported expressionfields shape changed"
                     % (name, n))
        qml = qml[:ef.start()] + body + qml[ef.end():]
        print("modulation: re-anchored %s to the painted palette"
              % ", ".join(sorted(replacements)))

    con = sqlite3.connect(TARGET)
    cur = con.cursor()
    cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                (qml, LAYER))
    if cur.rowcount != 1:
        con.rollback()
        con.close()
        bail("expected to update exactly 1 layer_styles row, hit %d"
             % cur.rowcount)
    con.commit()

    print("integrity_check:", cur.execute("PRAGMA integrity_check").fetchone()[0])
    final = cur.execute(
        "SELECT styleQML FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()[0]
    con.close()

    import xml.etree.ElementTree as ET
    ET.fromstring(final)
    n_svgfill = len(re.findall(r'class="SVGFill"', final))
    if n_svgfill != 1:
        bail("expected exactly 1 SVGFill in the style, found %d" % n_svgfill)
    rend = re.search(r'<renderer-v2\b[^>]*>', final).group(0)
    if 'type="RuleRenderer"' not in rend:
        bail("renderer type is not RuleRenderer: " + rend[:120])
    if 'referencescale="%d"' % REFERENCE_SCALE not in rend:
        bail("referencescale lost")
    n_rules = len(re.findall(r'<rule\b', final))
    if n_rules != EXPECT_CATS + 1:
        bail("expected %d rules, found %d" % (EXPECT_CATS + 1, n_rules))
    props = ("file", "outlineColor", "outlineWidth")
    if modulation_active:
        props += ("width",)
    for prop in props:
        if prop not in final:
            bail("data-defined property %r missing from the written style" % prop)
    if modulation_active:
        if not re.search(r'<field\b[^>]*name="%s"' % MODULATION_MARK, final):
            bail("virtual field %s lost in the bake" % MODULATION_MARK)
        n_dd = final.split("<renderer-v2", 1)[-1].count(MODULATION_DD_MARK)
        if n_dd < EXPECT_CATS:
            bail("dd fillColor modulation survives on only %d of %d rule "
                 "symbols - convertFromRenderer dropped it" % (n_dd, EXPECT_CATS))

    with open(LITH_FILLS, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Resolved fill + ink per lithology code, for review.\n"
                 "# Regenerate with inject_basemap_lith_patterns.py\n")
        fh.write("code\tfill\tink\n")
        for code in sorted(fill_of):
            fh.write("%s\t%s\t%s\n" % (code, hexof(fill_of[code]),
                                       hexof(ink_of[code])))
    print("wrote %s" % os.path.basename(LITH_FILLS))
    print("round-trip ok: RuleRenderer, %d colour rules + 1 pattern rule, "
          "exactly 1 SVGFill carrying all three data-defined properties"
          % EXPECT_CATS)
    print("live template untouched:", ORIGINAL)
    print("test template:", TARGET)


if __name__ == "__main__":
    main()
