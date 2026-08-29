"""The Transported Cover register: cream fills, bright amber, faint texture.

ROUND 1 moved cover off the sandstone cream onto a grey ladder. ROUND 2
added mechanism hues with tinted contacts - too loud. ROUND 3 compressed
the fills to a whisper and moved the identity to gold - but the tans still
read salmon on the map (the rose-lean that kept them dE 7 clear of the
creams, printed at full texture-ink strength), and the "gold" read brown:
it had been darkened to hold a 2.0:1 luminance floor on the deepest fills.

ROUND 4 - this module's current numbers - is the actual Ora Banda look the
user keeps pointing at:

* FILLS are true cream / near-paper (most L* 88-96, chroma cut hard; no
  rose-lean, the tans are cream-buff). Cover may now sit CLOSE to the
  bedrock creams - the user's call: on that old map the cover WAS cream,
  and the amber edge + amber label did all the "this is cover" work.
* GOLD is the bright amber off the reference map, not an antique.
* The cover texture ink prints much softer than bedrock's - see
  COVER_INK_TARGET in inject_basemap_lith_patterns.py.

Hue still whispers the mechanism: barely-blue alluvial, cream-buff
colluvial, stone-grey residual, rose aeolian, and so on.

THE FLOORS, AND WHY TWO OF THEM DROPPED
---------------------------------------
MIN_CONTACT_RATIO fell 2.0 -> 1.35. The 2.0 was luminance-thinking: it
forced the gold down to #9a7118, which is brown. On the reference map the
amber edge holds ~1.4:1 on the cream and is perfectly legible, because a
saturated 40deg-hue line on a near-neutral field is carried by CHROMA, not
by darkness. The floor now only guards against the truly invisible; the
hard-coded 2.0 against the bedrock contact #2a2a2a stays (amber ~5.8:1).

The dE floors split three ways:
* MIN_FILL_DE 7.0 stays wherever inject_basemap_lith_patterns.py HARD
  FAILS anyway: cover vs bedrock sharing a texture tile. That is the real
  protection, and it is why TCOS (sandstone tile, vs SSTS), TCOD
  (claystone tile, vs the RSPL/RFSP saprolite peaches), TLOE (siltstone,
  vs SSL/SSLS), TSI (vs SSL), TEVS (vs SEV) and TDLP/TLTP (laterite, vs
  RDLN/RDLM) lean grey-mushroom instead of cream - the exceptions that
  keep their distance the audit still enforces at 7.
* CREAM_DE 4.5: cover vs the sandstone creams on OTHER tiles. Relaxed
  from 7 by the user's decision above - the gold identity now does the
  cover-vs-bedrock work, the fill only has to not be IDENTICAL.
* COVER_PAIR_DE 4.5: cover vs cover on a shared tile. The patterns
  injector only warns there; rungs of one family may sit closer now that
  the register is this pale - the code label tells them apart.

Unique anchors remain mandatory: lith_palette.build() offsets any shared
anchor, and the cover ladder depends on passing through byte-for-byte.

Label token: the amber #b3922e holds >=1.84:1 on the deepest rung (TLSD)
and ~2.8:1 on the pale ones; tests/test_cover_palette.py's floor is 1.8.
It reads as unmistakably gold beside bedrock's #1a1a1a (5.9:1 apart).

Pure stdlib: injectors, tests and the contact sheets all import it, and
none of them may need QGIS to know what colour something is.
"""

# The one amber contact ink and the one amber label token, sampled off the
# reference map. GOLD_CONTACT is kept per-family in FAMILY_CONTACT so
# contact_of() and the injector machinery are unchanged - every family
# simply maps to the same ink.
GOLD_CONTACT = (0xcf, 0x9d, 0x28)
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
LABEL_TOKEN = (0xb3, 0x92, 0x2e)
LABEL_BEDROCK = (0x1a, 0x1a, 0x1a)

# code -> (fill, family, tile, variety, description, note)
# `tile`, `variety` and `note` mirror Template/patterns/lith_textures.tsv;
# `description` is the BasemapCodes text, stored as "CODE - description".
COVER = {
    # --- water / alluvial: barely-blue -------------------------------
    "TALL":  ((0xec, 0xf1, 0xf6), "water", "alluvium", "",
              "Alluvium", "alluvium"),
    "TSW":   ((0xdd, 0xe6, 0xee), "water", "alluvium", "",
              "Sheetwash", "alluvium"),
    "TSA":   ((0xf1, 0xf4, 0xf8), "water", "sandstone", "",
              "Sand", "sandy cover"),
    "TSAC":  ((0xe2, 0xe8, 0xef), "water", "sandstone", "",
              "Clayey Sand", "sandy cover"),
    "TGRV":  ((0xe7, 0xed, 0xf4), "water", "gravel", "",
              "Gravel", "gravel / lag"),
    "TSI":   ((0xd3, 0xde, 0xea), "water", "siltstone", "",
              "Silt", "silt"),
    "TCY":   ((0xe9, 0xef, 0xf5), "water", "claystone", "",
              "Clay", "clay / loam / hardpan"),

    # --- gravity / colluvial: cream-buff, no salmon ------------------
    "TCO":   ((0xf2, 0xe8, 0xda), "gravity", "colluvium", "colluvium",
              "Colluvium", "colluvial / scree"),
    "TCOC":  ((0xee, 0xe0, 0xcc), "gravity", "colluvium", "colluvium",
              "Colluvium, Coarse", "colluvial / scree"),
    "TCOS":  ((0xdc, 0xd3, 0xc6), "gravity", "sandstone", "",
              "Colluvium, Sands", "sandy cover"),
    "TCOD":  ((0xd2, 0xce, 0xc9), "gravity", "claystone", "",
              "Colluvium, Fine silt & Clay", "clay / loam / hardpan"),
    "TLSC":  ((0xe4, 0xd1, 0xb0), "gravity", "colluvium", "",
              "Lithic Scree", "colluvial / scree"),
    "TLSD":  ((0xd8, 0xca, 0xb5), "gravity", "colluvium", "",
              "Landslide & Debris Flow", "colluvial / scree"),

    # --- residual / lag / duricrust: light stone-grey ----------------
    "TRSL":  ((0xe0, 0xde, 0xd7), "residual", "colluvium", "residual_soil",
              "Residual Soil, Lithic Fragments", "colluvial / scree"),
    "TRSS":  ((0xe3, 0xe2, 0xde), "residual", "sandstone", "residual_soil",
              "Residual Soil, Sandy", "sandy cover"),
    "TRSLM": ((0xed, 0xea, 0xe1), "residual", "claystone", "",
              "Residual Soil, Loam", "clay / loam / hardpan"),
    "THP":   ((0xde, 0xe0, 0xe1), "residual", "claystone", "",
              "Hard Pan", "clay / loam / hardpan"),
    "TLG":   ((0xe6, 0xe4, 0xdd), "residual", "gravel", "",
              "Lag", "gravel / lag"),
    "TLGC":  ((0xd6, 0xd2, 0xc6), "residual", "gravel", "",
              "Lag on Colluvium", "gravel / lag"),
    "TDLP":  ((0xe3, 0xde, 0xd6), "residual", "laterite", "",
              "Duricrust of Transported Pisoliths", "transported pisoliths"),
    "TLTP":  ((0xd8, 0xd0, 0xc1), "residual", "laterite", "",
              "Transported Pisoliths", "transported pisoliths"),

    # --- aeolian: faint rose -----------------------------------------
    "TAES":  ((0xf5, 0xeb, 0xe5), "wind", "sandstone", "",
              "Aeolian Sand", "aeolian"),
    "TLOE":  ((0xf0, 0xde, 0xd4), "wind", "siltstone", "",
              "Loess", "aeolian"),

    # --- evaporitic: cool near-whites --------------------------------
    "TSP":   ((0xf7, 0xf6, 0xf4), "evaporite", "evaporite", "",
              "Salt Pan", "salt pan / evaporitic / gypsum dunes"),
    "TGYP":  ((0xe4, 0xea, 0xef), "evaporite", "evaporite", "",
              "Gypsum dunes, Kopai", "salt pan / evaporitic / gypsum dunes"),
    "TEVS":  ((0xcc, 0xd7, 0xd0), "evaporite", "evaporite", "",
              "Evaporitic Sediments", "salt pan / evaporitic / gypsum dunes"),

    # --- glacial: faint cyan -----------------------------------------
    "TTIL":  ((0xe6, 0xef, 0xee), "ice", "conglomerate", "",
              "Glacial Till", "glacial"),
    "TGFO":  ((0xd3, 0xe2, 0xe3), "ice", "gravel", "",
              "Glaciofluvial Outwash", "glacial"),

    # --- coastal / marine: faint sand-teal ---------------------------
    "TBCH":  ((0xde, 0xeb, 0xe6), "coast", "sandstone", "",
              "Beach & Coastal Sand", "coastal / marine"),
    "TMUD":  ((0xda, 0xe2, 0xdf), "coast", "mudstone", "",
              "Tidal & Estuarine Mud", "coastal / marine"),

    # --- standing water / organic: faint green-teal ------------------
    "TLAC":  ((0xdf, 0xeb, 0xe4), "lake", "claystone", "",
              "Lacustrine Clay", "lacustrine"),
    "TPEA":  ((0xd3, 0xd9, 0xcb), "lake", "marl", "",
              "Peat & Organic Soil", "organic"),

    # --- airfall / anthropogenic -------------------------------------
    "TASH":  ((0xea, 0xe7, 0xf2), "air", "tuff", "",
              "Volcanic Ash", "airfall"),
    "TFIL":  ((0xf0, 0xe5, 0xeb), "human", "crosshatch", "",
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

# Round 3's whisper fills and antique gold - the "old" side of round 4's
# idempotency check.
ROUND3_FILLS = {
    "TALL": (0xe8, 0xee, 0xf5), "TSW": (0xcb, 0xd9, 0xe9),
    "TSA": (0xee, 0xf2, 0xf7), "TSAC": (0xd6, 0xdf, 0xea),
    "TGRV": (0xdf, 0xe8, 0xf2), "TSI": (0xd2, 0xdc, 0xe8),
    "TCY": (0xe4, 0xec, 0xf3), "TCO": (0xef, 0xd8, 0xc9),
    "TCOC": (0xea, 0xcc, 0xb4), "TCOS": (0xd6, 0xc4, 0xac),
    "TCOD": (0xdc, 0xc3, 0xae), "TLSC": (0xd3, 0xbc, 0x9e),
    "TLSD": (0xbe, 0xae, 0x9a), "TRSL": (0xda, 0xd8, 0xd0),
    "TRSS": (0xdb, 0xda, 0xd6), "TRSLM": (0xe8, 0xe5, 0xdb),
    "THP": (0xd6, 0xd8, 0xd9), "TLG": (0xe0, 0xde, 0xd6),
    "TLGC": (0xcb, 0xc6, 0xb8), "TDLP": (0xde, 0xd6, 0xcb),
    "TLTP": (0xcc, 0xc2, 0xb0), "TAES": (0xf3, 0xe2, 0xdc),
    "TLOE": (0xee, 0xd5, 0xcd), "TSP": (0xf7, 0xf6, 0xf4),
    "TGYP": (0xdc, 0xe4, 0xec), "TEVS": (0xcc, 0xd4, 0xcd),
    "TTIL": (0xdf, 0xeb, 0xea), "TGFO": (0xc4, 0xd9, 0xda),
    "TBCH": (0xd5, 0xe6, 0xe0), "TMUD": (0xd2, 0xdc, 0xd8),
    "TLAC": (0xd5, 0xe7, 0xdc), "TPEA": (0xc9, 0xd1, 0xc1),
    "TASH": (0xe6, 0xe2, 0xf0), "TFIL": (0xec, 0xdf, 0xe7),
}
ROUND3_CONTACT = (0x9a, 0x71, 0x18)
ROUND3_LABEL_TOKEN = (0x83, 0x5f, 0x11)

# The contact colour every category carried before round 2 - bedrock's, and
# still bedrock's.
CONTACT_BEDROCK = (0x2a, 0x2a, 0x2a)

MIN_FILL_DE = 7.0        # cover vs SAME-TILE bedrock - the patterns
                         # injector hard-fails here, the audit mirrors it
CREAM_DE = 4.5           # cover vs the sandstone creams, other tiles
COVER_PAIR_DE = 4.5      # cover vs cover on a shared tile
SANDSTONE_CREAMS = ("SST", "SSTL", "SSTM", "SSTS")
MIN_CONTACT_RATIO = 1.35  # chroma carries the amber edge; see docstring


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
            if de < COVER_PAIR_DE:
                bad.append("%s / %s share tile %s at dE %.1f < %.1f"
                           % (a, b, tile_of(a), de, COVER_PAIR_DE))

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
                # Same-tile creams fall under the hard MIN_FILL_DE below;
                # this is the relaxed cross-tile floor.
                if bedrock_tiles and bedrock_tiles.get(cream) == tile_of(a):
                    continue
                de = delta_e(fills[a], bedrock_fills[cream])
                if de < CREAM_DE:
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
