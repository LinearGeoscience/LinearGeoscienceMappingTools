"""The Transported Cover register: mechanism-tinted fills, contacts, label.

ROUND 1 (inject_basemap_cover_recolour.py) moved all 21 cover codes off the
sandstone cream onto a near-neutral grey ladder, so cover stopped reading as
bedrock. ROUND 2 - this module - keeps that figure-ground win and adds the
device the old Ora Banda project used to such good effect: HUE SAYS HOW THE
MATERIAL GOT THERE.

  water / alluvial     pale blue        (its TALL was periwinkle, on purpose)
  gravity / colluvial  pale olive-green
  residual / lag       warm neutral     (round 1's greys, kept)
  aeolian              dusty pink       (its TSD was dusty pink, not yellow)
  evaporitic           cool near-white  (kept)
  glacial              icy cyan
  coastal / marine     teal
  lacustrine / organic green-teal
  airfall              pale violet
  anthropogenic        mauve

Every fill stays pale (L* 68-97) and low-chroma: cover is still a veil the
bedrock shows through, not a competing colour scheme. The hue is a whisper
that names the mechanism, which is why the families sit at the same
lightness rungs as the round-1 ladder rather than above them.

THREE PROPERTIES CARRY THE REGISTER
-----------------------------------
* FILL      - per code, this module's `COVER`.
* CONTACT   - per FAMILY, not per code: a mid-tone of the family hue, drawn
              where bedrock draws #2a2a2a. The ContactType mechanism is
              untouched - Solid/Dashed/None still choose the dash, the width
              and the transparency exactly as before, and only the COLOUR
              moves. (User's call: "tinted contacts for transported cover,
              but they retain the same mechanism for solid/dashed/none".)
* LABEL     - ONE token colour for every cover code, the old project's
              gold-vs-black identity signal. Not per family: the label says
              "this polygon is cover", the fill already says which cover.

WHY THESE EXACT NUMBERS
-----------------------
Fills: every same-tile pair (cover-vs-cover and cover-vs-bedrock alike)
clears CIE76 dE 7, no cover fill sits within dE 7 of the sandstone creams on
any tile, and every anchor is unique so `lith_palette.build()` passes it
through byte-for-byte. `audit()` below is the executable form of that
paragraph; tests/test_cover_palette.py runs it.

Contacts: each is >= 2.0:1 in luminance against the DARKEST fill in its own
family (a 0.1 mm hairline needs it) and stays well clear of the bedrock
#2a2a2a, so a tinted cover edge never reads as a bedrock contact.

Label token #6f6436: a deep muted ochre. Paler tokens were tried first - the
#9a8c55 sketched during the design round manages only 1.36:1 on the darkest
cover fills (TPEA, TLGC, TLSD) with no buffer behind the text, which is not
a label. #6f6436 holds 2.4:1 there and 5.5:1 on the pale rungs, while still
reading as clearly-not-black beside bedrock's #1a1a1a.

Pure stdlib: injectors, tests and the contact sheet all import it, and none
of them may need QGIS to know what colour something is.
"""

# family -> contact ink. Mid-tone of the family hue.
FAMILY_CONTACT = {
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

# The one identity colour every cover label takes; bedrock keeps the near
# black it has always had.
LABEL_TOKEN = (0x6f, 0x64, 0x36)
LABEL_BEDROCK = (0x1a, 0x1a, 0x1a)

# code -> (fill, family, tile, variety, description, note)
# `tile`, `variety` and `note` mirror Template/patterns/lith_textures.tsv;
# `description` is the BasemapCodes text, stored as "CODE - description".
COVER = {
    # --- water / alluvial: pale blue ---------------------------------
    "TALL":  ((0xe3, 0xea, 0xf2), "water", "alluvium", "",
              "Alluvium", "alluvium"),
    "TSW":   ((0xc9, 0xd8, 0xe6), "water", "alluvium", "",
              "Sheetwash", "alluvium"),
    "TSA":   ((0xea, 0xef, 0xf5), "water", "sandstone", "",
              "Sand", "sandy cover"),
    "TSAC":  ((0xc1, 0xcc, 0xd7), "water", "sandstone", "",
              "Clayey Sand", "sandy cover"),
    "TGRV":  ((0xd2, 0xdd, 0xe9), "water", "gravel", "",
              "Gravel", "gravel / lag"),
    "TSI":   ((0xc7, 0xcf, 0xd8), "water", "siltstone", "",
              "Silt", "silt"),
    "TCY":   ((0xdb, 0xe6, 0xee), "water", "claystone", "",
              "Clay", "clay / loam / hardpan"),

    # --- gravity / colluvial: pale olive-green -----------------------
    "TCO":   ((0xd6, 0xe3, 0xc7), "gravity", "colluvium", "colluvium",
              "Colluvium", "colluvial / scree"),
    "TCOC":  ((0xd1, 0xdd, 0xbe), "gravity", "colluvium", "colluvium",
              "Colluvium, Coarse", "colluvial / scree"),
    "TCOS":  ((0xcc, 0xd4, 0xbc), "gravity", "sandstone", "",
              "Colluvium, Sands", "sandy cover"),
    "TCOD":  ((0xc5, 0xd1, 0xbd), "gravity", "claystone", "",
              "Colluvium, Fine silt & Clay", "clay / loam / hardpan"),
    "TLSC":  ((0xbf, 0xc7, 0xab), "gravity", "colluvium", "",
              "Lithic Scree", "colluvial / scree"),
    "TLSD":  ((0xa6, 0xb2, 0x95), "gravity", "colluvium", "",
              "Landslide & Debris Flow", "colluvial / scree"),

    # --- residual / lag / duricrust: round 1's warm neutrals ---------
    "TRSL":  ((0xb7, 0xb8, 0xb1), "residual", "colluvium", "residual_soil",
              "Residual Soil, Lithic Fragments", "colluvial / scree"),
    "TRSS":  ((0xb5, 0xb7, 0xb2), "residual", "sandstone", "residual_soil",
              "Residual Soil, Sandy", "sandy cover"),
    "TRSLM": ((0xd9, 0xd9, 0xd2), "residual", "claystone", "",
              "Residual Soil, Loam", "clay / loam / hardpan"),
    "THP":   ((0xb2, 0xb7, 0xb9), "residual", "claystone", "",
              "Hard Pan", "clay / loam / hardpan"),
    "TLG":   ((0xc2, 0xc3, 0xbd), "residual", "gravel", "",
              "Lag", "gravel / lag"),
    "TLGC":  ((0xa9, 0xa5, 0x98), "residual", "gravel", "",
              "Lag on Colluvium", "gravel / lag"),
    "TDLP":  ((0xd7, 0xd3, 0xc8), "residual", "laterite", "",
              "Duricrust of Transported Pisoliths", "transported pisoliths"),
    "TLTP":  ((0xc2, 0xbe, 0xb2), "residual", "laterite", "",
              "Transported Pisoliths", "transported pisoliths"),

    # --- aeolian: dusty pink ----------------------------------------
    "TAES":  ((0xe9, 0xd9, 0xd6), "wind", "sandstone", "",
              "Aeolian Sand", "aeolian"),
    "TLOE":  ((0xda, 0xc9, 0xc5), "wind", "siltstone", "",
              "Loess", "aeolian"),

    # --- evaporitic: cool near-whites, kept from round 1 -------------
    "TSP":   ((0xf7, 0xf6, 0xf4), "evaporite", "evaporite", "",
              "Salt Pan", "salt pan / evaporitic / gypsum dunes"),
    "TGYP":  ((0xde, 0xe5, 0xea), "evaporite", "evaporite", "",
              "Gypsum dunes, Kopai", "salt pan / evaporitic / gypsum dunes"),
    "TEVS":  ((0xcc, 0xd0, 0xcd), "evaporite", "evaporite", "",
              "Evaporitic Sediments", "salt pan / evaporitic / gypsum dunes"),

    # --- glacial: icy cyan ------------------------------------------
    "TTIL":  ((0xd2, 0xe0, 0xdf), "ice", "conglomerate", "",
              "Glacial Till", "glacial"),
    "TGFO":  ((0xb7, 0xcc, 0xcd), "ice", "gravel", "",
              "Glaciofluvial Outwash", "glacial"),

    # --- coastal / marine: teal -------------------------------------
    "TBCH":  ((0xcd, 0xe0, 0xe4), "coast", "sandstone", "",
              "Beach & Coastal Sand", "coastal / marine"),
    "TMUD":  ((0xbe, 0xca, 0xc7), "coast", "mudstone", "",
              "Tidal & Estuarine Mud", "coastal / marine"),

    # --- standing water / organic: green-teal ------------------------
    "TLAC":  ((0xcd, 0xe2, 0xda), "lake", "claystone", "",
              "Lacustrine Clay", "lacustrine"),
    "TPEA":  ((0xa8, 0xad, 0xa0), "lake", "marl", "",
              "Peat & Organic Soil", "organic"),

    # --- airfall / anthropogenic ------------------------------------
    "TASH":  ((0xdc, 0xd8, 0xe6), "air", "tuff", "",
              "Volcanic Ash", "airfall"),
    "TFIL":  ((0xe1, 0xd3, 0xda), "human", "crosshatch", "",
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
# are round 2's own, and are born on their final fill.
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
