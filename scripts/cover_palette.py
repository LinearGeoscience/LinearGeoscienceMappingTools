"""The Transported Cover register: whisper fills, gold contacts, gold label.

ROUND 1 (inject_basemap_cover_recolour.py) moved all 21 cover codes off the
sandstone cream onto a near-neutral grey ladder, so cover stopped reading as
bedrock. ROUND 2 (inject_cover_mechanism.py) added mechanism hues - pale
blue for alluvial, olive-green for colluvial - with a tinted contact per
family. On the map that round proved too loud: the colluvial green competed
with the lithology and regolith units instead of sitting behind them.

ROUND 3 - this module's current numbers - keeps the mechanism-hue idea but
turns everything down to the register the old Ora Banda project used: fills
are a WHISPER (near-paper, the hue barely-there but present), and the
"this is cover" identity moves to GOLD - one gold contact ink and one gold
label token for every cover code, the way that project drew TCO/TLGC.

  water / alluvial     whisper blue     (kept from round 2, lightened)
  gravity / colluvial  whisper buff-tan (the green is gone; tan is what
                                         colluvium actually looks like)
  residual / lag       warm stone-grey  (round 1's greys, lifted)
  aeolian              whisper rose
  evaporitic           cool near-white  (kept)
  glacial              whisper cyan
  coastal / marine     whisper sand-teal
  lacustrine / organic whisper green-teal (green is free now)
  airfall              whisper violet
  anthropogenic        whisper mauve

Every fill sits in a narrow near-paper band (L* ~80-97, low chroma): cover
is a veil the map shows through, not a competing colour scheme. Within a
family the codes still form a light-to-deeper ladder so same-tile pairs
stay dE 7 apart, which is why the deepest rungs (TLSD, TLGC, TPEA) sit a
little below pure whisper.

THREE PROPERTIES CARRY THE REGISTER
-----------------------------------
* FILL      - per code, this module's `COVER`.
* CONTACT   - ONE gold ink for every family, drawn where bedrock draws
              #2a2a2a. The ContactType mechanism is untouched - Solid /
              Dashed / None still choose the dash, the width and the
              transparency exactly as before, and only the COLOUR moves.
              (Round 2's per-family inks are gone: the fill already says
              which mechanism; the gold edge says "cover, not bedrock".)
* LABEL     - ONE gold token for every cover code, a shade deeper than the
              contact so text carries more weight than a hairline.

WHY THESE EXACT NUMBERS
-----------------------
Fills: every same-tile pair (cover-vs-cover and cover-vs-bedrock alike)
clears CIE76 dE 7, no cover fill sits within dE 7 of the sandstone creams
on any tile, and every anchor is unique so `lith_palette.build()` passes it
through byte-for-byte. The buff-tans are the tight squeeze - they must stay
clear of the SST creams and the regolith warm tones while still reading as
earth - which is why they lean grey-rose rather than yellow. `audit()`
below is the executable form of this paragraph; tests/test_cover_palette.py
runs it.

Contacts: the gold must hold >= 2.0:1 in luminance against the DARKEST fill
in every family (a 0.1 mm hairline needs it), which caps how bright it can
be: the Ora Banda amber (~#d0a028) manages only ~1.4:1 on the deep rungs.
The antique gold here clears 2.0:1 on every fill (2.04:1 on TLSD, the
deepest rung) and sits 3.25:1 from the bedrock contact #2a2a2a, so a gold
cover edge never reads as a bedrock contact.

Label token: deeper gold than the contact. Round 2 needed a dark ochre
because the fills ran down to L* ~68; with every fill lifted into the
whisper band the gold holds 2.7:1 on the deepest rung (TLSD) and 4.5-5.4:1
on the pale rungs, while reading as clearly-gold beside bedrock's #1a1a1a.

Pure stdlib: injectors, tests and the contact sheets all import it, and
none of them may need QGIS to know what colour something is.
"""

# The one gold contact ink, and the one gold label token. GOLD_CONTACT is
# kept per-family in FAMILY_CONTACT below so contact_of() and the injector
# machinery are unchanged from round 2 - every family simply maps to the
# same ink now.
GOLD_CONTACT = (0x9a, 0x71, 0x18)
FAMILY_CONTACT = {
    "water":     GOLD_CONTACT,
    "gravity":   GOLD_CONTACT,
    "residual":  GOLD_CONTACT,
    "wind":      GOLD_CONTACT,
    "evaporite": GOLD_CONTACT,
    "ice":       GOLD_CONTACT,
    "coast":     GOLD_CONTACT,
    "lake":      GOLD_CONTACT,
    "air":       GOLD_CONTACT,
    "human":     GOLD_CONTACT,
}

# The one identity colour every cover label takes; bedrock keeps the near
# black it has always had.
LABEL_TOKEN = (0x83, 0x5f, 0x11)
LABEL_BEDROCK = (0x1a, 0x1a, 0x1a)

# code -> (fill, family, tile, variety, description, note)
# `tile`, `variety` and `note` mirror Template/patterns/lith_textures.tsv;
# `description` is the BasemapCodes text, stored as "CODE - description".
COVER = {
    # --- water / alluvial: whisper blue ------------------------------
    "TALL":  ((0xe8, 0xee, 0xf5), "water", "alluvium", "",
              "Alluvium", "alluvium"),
    "TSW":   ((0xcb, 0xd9, 0xe9), "water", "alluvium", "",
              "Sheetwash", "alluvium"),
    "TSA":   ((0xee, 0xf2, 0xf7), "water", "sandstone", "",
              "Sand", "sandy cover"),
    "TSAC":  ((0xd6, 0xdf, 0xea), "water", "sandstone", "",
              "Clayey Sand", "sandy cover"),
    "TGRV":  ((0xdf, 0xe8, 0xf2), "water", "gravel", "",
              "Gravel", "gravel / lag"),
    "TSI":   ((0xd2, 0xdc, 0xe8), "water", "siltstone", "",
              "Silt", "silt"),
    "TCY":   ((0xe4, 0xec, 0xf3), "water", "claystone", "",
              "Clay", "clay / loam / hardpan"),

    # --- gravity / colluvial: whisper buff-tan -----------------------
    "TCO":   ((0xef, 0xd8, 0xc9), "gravity", "colluvium", "colluvium",
              "Colluvium", "colluvial / scree"),
    "TCOC":  ((0xea, 0xcc, 0xb4), "gravity", "colluvium", "colluvium",
              "Colluvium, Coarse", "colluvial / scree"),
    "TCOS":  ((0xd6, 0xc4, 0xac), "gravity", "sandstone", "",
              "Colluvium, Sands", "sandy cover"),
    "TCOD":  ((0xdc, 0xc3, 0xae), "gravity", "claystone", "",
              "Colluvium, Fine silt & Clay", "clay / loam / hardpan"),
    "TLSC":  ((0xd3, 0xbc, 0x9e), "gravity", "colluvium", "",
              "Lithic Scree", "colluvial / scree"),
    "TLSD":  ((0xbe, 0xae, 0x9a), "gravity", "colluvium", "",
              "Landslide & Debris Flow", "colluvial / scree"),

    # --- residual / lag / duricrust: warm stone-grey -----------------
    "TRSL":  ((0xda, 0xd8, 0xd0), "residual", "colluvium", "residual_soil",
              "Residual Soil, Lithic Fragments", "colluvial / scree"),
    "TRSS":  ((0xdb, 0xda, 0xd6), "residual", "sandstone", "residual_soil",
              "Residual Soil, Sandy", "sandy cover"),
    "TRSLM": ((0xe8, 0xe5, 0xdb), "residual", "claystone", "",
              "Residual Soil, Loam", "clay / loam / hardpan"),
    "THP":   ((0xd6, 0xd8, 0xd9), "residual", "claystone", "",
              "Hard Pan", "clay / loam / hardpan"),
    "TLG":   ((0xe0, 0xde, 0xd6), "residual", "gravel", "",
              "Lag", "gravel / lag"),
    "TLGC":  ((0xcb, 0xc6, 0xb8), "residual", "gravel", "",
              "Lag on Colluvium", "gravel / lag"),
    "TDLP":  ((0xde, 0xd6, 0xcb), "residual", "laterite", "",
              "Duricrust of Transported Pisoliths", "transported pisoliths"),
    "TLTP":  ((0xcc, 0xc2, 0xb0), "residual", "laterite", "",
              "Transported Pisoliths", "transported pisoliths"),

    # --- aeolian: whisper rose ---------------------------------------
    "TAES":  ((0xf3, 0xe2, 0xdc), "wind", "sandstone", "",
              "Aeolian Sand", "aeolian"),
    "TLOE":  ((0xee, 0xd5, 0xcd), "wind", "siltstone", "",
              "Loess", "aeolian"),

    # --- evaporitic: cool near-whites, kept --------------------------
    "TSP":   ((0xf7, 0xf6, 0xf4), "evaporite", "evaporite", "",
              "Salt Pan", "salt pan / evaporitic / gypsum dunes"),
    "TGYP":  ((0xdc, 0xe4, 0xec), "evaporite", "evaporite", "",
              "Gypsum dunes, Kopai", "salt pan / evaporitic / gypsum dunes"),
    "TEVS":  ((0xcc, 0xd4, 0xcd), "evaporite", "evaporite", "",
              "Evaporitic Sediments", "salt pan / evaporitic / gypsum dunes"),

    # --- glacial: whisper cyan ---------------------------------------
    "TTIL":  ((0xdf, 0xeb, 0xea), "ice", "conglomerate", "",
              "Glacial Till", "glacial"),
    "TGFO":  ((0xc4, 0xd9, 0xda), "ice", "gravel", "",
              "Glaciofluvial Outwash", "glacial"),

    # --- coastal / marine: whisper sand-teal -------------------------
    "TBCH":  ((0xd5, 0xe6, 0xe0), "coast", "sandstone", "",
              "Beach & Coastal Sand", "coastal / marine"),
    "TMUD":  ((0xd2, 0xdc, 0xd8), "coast", "mudstone", "",
              "Tidal & Estuarine Mud", "coastal / marine"),

    # --- standing water / organic: whisper green-teal ----------------
    "TLAC":  ((0xd5, 0xe7, 0xdc), "lake", "claystone", "",
              "Lacustrine Clay", "lacustrine"),
    "TPEA":  ((0xc9, 0xd1, 0xc1), "lake", "marl", "",
              "Peat & Organic Soil", "organic"),

    # --- airfall / anthropogenic -------------------------------------
    "TASH":  ((0xe6, 0xe2, 0xf0), "air", "tuff", "",
              "Volcanic Ash", "airfall"),
    "TFIL":  ((0xec, 0xdf, 0xe7), "human", "crosshatch", "",
              "Anthropogenic Fill", "anthropogenic"),
}

# The 13 codes round 2 adds, in the order that fixes their fid and symbol
# allocation - DO NOT REORDER. Each names the cover code its symbol block
# and SLD rule are cloned from (structure only; the colour comes from
# COVER above).
NEW_CODES = [
    ("TSW",  "TALL"),
    ("TLGC", "TLG"),
    ("TAES", "TSA"),
    ("TLAC", "TCY"),
    ("TLOE", "TSI"),
    ("TTIL", "TGRV"),
    ("TGFO", "TGRV"),
    ("TBCH", "TSA"),
    ("TMUD", "TCY"),
    ("TASH", "TCY"),
    ("TFIL", "TCY"),
    ("TLSD", "TLSC"),
    ("TPEA", "TCY"),
]

# The 21 codes round 1 left on the grey ladder, with the grey they carry -
# the "old" side of round 2's idempotency check. Cover codes not listed here
# are round 2's own, and were born on their round-2 fill.
ROUND1_GREY = {
    "TALL": (0xe9, 0xeb, 0xea), "TSA": (0xf2, 0xf2, 0xf0),
    "TCOS": (0xdc, 0xdd, 0xd7), "TSAC": (0xc9, 0xc9, 0xc8),
    "TRSS": (0xb5, 0xb7, 0xb2), "TCO": (0xe7, 0xe7, 0xe2),
    "TCOC": (0xe1, 0xe1, 0xdc), "TLSC": (0xcb, 0xcd, 0xc6),
    "TRSL": (0xb7, 0xb8, 0xb1), "TGRV": (0xd6, 0xd8, 0xd3),
    "TLG": (0xc2, 0xc3, 0xbd), "TCY": (0xe4, 0xe9, 0xec),
    "TRSLM": (0xd9, 0xd9, 0xd2), "TCOD": (0xcd, 0xd2, 0xd7),
    "THP": (0xb2, 0xb7, 0xb9), "TSI": (0xc6, 0xc7, 0xc4),
    "TSP": (0xf7, 0xf6, 0xf4), "TGYP": (0xde, 0xe5, 0xea),
    "TEVS": (0xcc, 0xd0, 0xcd), "TDLP": (0xd7, 0xd3, 0xc8),
    "TLTP": (0xc2, 0xbe, 0xb2),
}

# Every fill as round 2 painted it - the "old" side of round 3's
# idempotency check, exactly as ROUND1_GREY served round 2.
ROUND2_FILLS = {
    "TALL": (0xe3, 0xea, 0xf2), "TSW": (0xc9, 0xd8, 0xe6),
    "TSA": (0xea, 0xef, 0xf5), "TSAC": (0xc1, 0xcc, 0xd7),
    "TGRV": (0xd2, 0xdd, 0xe9), "TSI": (0xc7, 0xcf, 0xd8),
    "TCY": (0xdb, 0xe6, 0xee), "TCO": (0xd6, 0xe3, 0xc7),
    "TCOC": (0xd1, 0xdd, 0xbe), "TCOS": (0xcc, 0xd4, 0xbc),
    "TCOD": (0xc5, 0xd1, 0xbd), "TLSC": (0xbf, 0xc7, 0xab),
    "TLSD": (0xa6, 0xb2, 0x95), "TRSL": (0xb7, 0xb8, 0xb1),
    "TRSS": (0xb5, 0xb7, 0xb2), "TRSLM": (0xd9, 0xd9, 0xd2),
    "THP": (0xb2, 0xb7, 0xb9), "TLG": (0xc2, 0xc3, 0xbd),
    "TLGC": (0xa9, 0xa5, 0x98), "TDLP": (0xd7, 0xd3, 0xc8),
    "TLTP": (0xc2, 0xbe, 0xb2), "TAES": (0xe9, 0xd9, 0xd6),
    "TLOE": (0xda, 0xc9, 0xc5), "TSP": (0xf7, 0xf6, 0xf4),
    "TGYP": (0xde, 0xe5, 0xea), "TEVS": (0xcc, 0xd0, 0xcd),
    "TTIL": (0xd2, 0xe0, 0xdf), "TGFO": (0xb7, 0xcc, 0xcd),
    "TBCH": (0xcd, 0xe0, 0xe4), "TMUD": (0xbe, 0xca, 0xc7),
    "TLAC": (0xcd, 0xe2, 0xda), "TPEA": (0xa8, 0xad, 0xa0),
    "TASH": (0xdc, 0xd8, 0xe6), "TFIL": (0xe1, 0xd3, 0xda),
}

# Round 2's per-family contact inks and label token - the "old" side of
# round 3's contact/label idempotency check.
ROUND2_CONTACT = {
    "water":     (0x5f, 0x7c, 0x99),
    "gravity":   (0x68, 0x78, 0x4f),
    "residual":  (0x6f, 0x6c, 0x5c),
    "wind":      (0x9a, 0x72, 0x68),
    "evaporite": (0x7c, 0x87, 0x8d),
    "ice":       (0x5c, 0x82, 0x86),
    "coast":     (0x5b, 0x84, 0x7f),
    "lake":      (0x58, 0x7c, 0x69),
    "air":       (0x7a, 0x73, 0x96),
    "human":     (0x93, 0x74, 0x8c),
}
ROUND2_LABEL_TOKEN = (0x6f, 0x64, 0x36)

# The contact colour every category carried before round 2 - bedrock's, and
# still bedrock's.
CONTACT_BEDROCK = (0x2a, 0x2a, 0x2a)

MIN_FILL_DE = 7.0                 # inject_basemap_lith_patterns.MIN_FILL_DE
SANDSTONE_CREAMS = ("SST", "SSTL", "SSTM", "SSTS")
MIN_CONTACT_RATIO = 2.0           # hairline legibility on its own fills


def rgb_hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def fill_of(code):
    return COVER[code][0]


def family_of(code):
    return COVER[code][1]


def contact_of(code):
    return FAMILY_CONTACT[COVER[code][1]]


def tile_of(code):
    return COVER[code][2]


def variety_of(code):
    return COVER[code][3]


def description_of(code):
    return COVER[code][4]


def note_of(code):
    return COVER[code][5]


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
    """CIE76, the same maths as inject_basemap_lith_patterns.delta_e."""
    return sum((x - y) ** 2 for x, y in zip(_lab(a), _lab(b))) ** 0.5


def _relative_luminance(rgb):
    def f(u):
        u /= 255.0
        return u / 12.92 if u <= 0.03928 else ((u + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b):
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def audit(bedrock_fills=None, bedrock_tiles=None):
    """Every rule the palette claims to obey, as a list of failure strings.

    bedrock_fills/bedrock_tiles: {code: rgb} / {code: tile} for the NON-cover
    codes, normally read from Template/patterns/lith_*.tsv. Omit them to
    check cover against itself only (what a unit test can do without the
    template to hand).
    """
    bad = []
    fills = {c: fill_of(c) for c in COVER}

    seen = {}
    for code, rgb in sorted(fills.items()):
        seen.setdefault(rgb, []).append(code)
    for rgb, codes in sorted(seen.items()):
        if len(codes) > 1:
            bad.append("shared anchor %s: %s - build() would offset these"
                       % (rgb_hex(rgb), ", ".join(codes)))

    codes = sorted(COVER)
    for i, a in enumerate(codes):
        for b in codes[i + 1:]:
            if tile_of(a) != tile_of(b):
                continue
            if variety_of(a) and variety_of(a) == variety_of(b):
                continue
            de = delta_e(fills[a], fills[b])
            if de < MIN_FILL_DE:
                bad.append("%s / %s share tile %s at dE %.1f < %.1f"
                           % (a, b, tile_of(a), de, MIN_FILL_DE))

    for fam, ink in sorted(FAMILY_CONTACT.items()):
        members = [c for c in COVER if family_of(c) == fam]
        if not members:
            bad.append("family %r has a contact ink but no codes" % fam)
            continue
        worst = min((contrast_ratio(ink, fills[c]), c) for c in members)
        if worst[0] < MIN_CONTACT_RATIO:
            bad.append("contact %s reads %.2f:1 on %s (floor %.2f:1)"
                       % (rgb_hex(ink), worst[0], worst[1],
                          MIN_CONTACT_RATIO))
        if contrast_ratio(ink, CONTACT_BEDROCK) < 2.0:
            bad.append("contact %s for %r is too close to the bedrock "
                       "contact %s" % (rgb_hex(ink), fam,
                                       rgb_hex(CONTACT_BEDROCK)))

    if bedrock_fills:
        for a in codes:
            for cream in SANDSTONE_CREAMS:
                if cream not in bedrock_fills:
                    continue
                de = delta_e(fills[a], bedrock_fills[cream])
                if de < MIN_FILL_DE:
                    bad.append("%s sits dE %.1f from the %s cream"
                               % (a, de, cream))
            if not bedrock_tiles:
                continue
            for b, rgb in bedrock_fills.items():
                if bedrock_tiles.get(b) != tile_of(a):
                    continue
                de = delta_e(fills[a], rgb)
                if de < MIN_FILL_DE:
                    bad.append("cover %s and bedrock %s share tile %s at "
                               "dE %.1f" % (a, b, tile_of(a), de))
    return bad
