"""Per-code fill colours for '4 - Basemap', built off the template's own palette.

THE MISTAKE THIS MODULE WAS REWRITTEN TO FIX
--------------------------------------------
The first version took the MODAL fill colour per family letter and ramped
every code in that family off it. But the live template carries 48 distinct
colours and they encode real distinctions, all of which that flattened:

  * F splits into #fef1ae yellow for 13 volcanic codes and #feafc2 pink for
    17 intrusives. Pink won the modal vote 17-13, so every felsic volcanic
    was dragged onto the pink ramp and the yellow disappeared.
  * The seven migmatites are deliberately graded #f0b6c3 -> #af3a58. Ramping
    them off one base, then declaring them a `variety`, made all seven
    identical.
  * The mafic volcanic green vs intrusive cyan split, the two ultramafic
    purples and the grey pelites all went the same way.

So: ANCHOR EVERY CODE ON ITS OWN ORIGINAL COLOUR. A code whose colour is
unique in the template keeps it exactly - no ramp, no drift. Only codes that
already collided get separated, and they are separated as offsets from the
colour they shared. The palette is subdivided, never replaced.

Three deliberate overrides sit on top of that:

  * PROTOLITH - sheared (Z*) and metamorphic (H*) rocks take the colour of
    what they were made from, because "schist" and "gneiss" are textures, not
    compositions. Each carries a consistent shift so the three readings of one
    protolith stay apart: basalt / mafic gneiss (deeper, richer) / basalt
    schist (deeper, paler).
  * CHEMICAL_HUE - carbonate, chert, iron formation, laterite and evaporite
    take a hue set by their chemistry rather than their family.
  * ANCHOR_OVERRIDE - two codes where the template breaks its own convention.

Pure stdlib so it can be imported without QGIS.
"""
import colorsys
import os
import re
import sqlite3

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGINAL = os.path.join(REPO, "Template", "LGS_MappingTemplate.gpkg")
TEXTURE_MAP = os.path.join(REPO, "Template", "patterns", "lith_textures.tsv")
LAYER = "4 - Basemap"

# Muted clamps.
L_MIN, L_MAX = 0.34, 0.92

# Separation applied ONLY to codes that already shared a colour. Lightness
# step plus a small hue fan, because lightness alone runs out past ~8 codes.
#
# Both ranges are deliberately TIGHT. A wider fan overshoots the family: at
# +-0.17 lightness the gabbroids reached L 92% - near-white, far too pale for
# a mafic intrusive - and at +-22 degrees the ortho-amphibolite crossed clean
# out of the intrusive teal into the extrusive green, inverting the
# template's own green-is-extrusive / teal-is-intrusive convention.
SLOT_STEP = 0.038
SLOT_HALF_RANGE = 0.105
HUE_SLOT_STEP = 4.0
HUE_SLOT_MAX = 9.0

# Conglomerates named for their clast composition get a hue nudge toward that
# composition, so a felsic and an ultramafic conglomerate are not the same
# blue. Kept modest: they are still sedimentary rocks and must read as such,
# so this tints the sedimentary blue rather than adopting the clast family's
# colour outright.
CLAST_TINT = {}
for _codes, _deg in (("SCGFM SCGFP", 32.0),      # felsic clasts, toward violet
                     ("SCGIM SCGIP", -18.0),     # intermediate, toward cyan
                     ("SCGMM SCGMP", -34.0),     # mafic, toward teal-green
                     ("SCGUM SCGUP", 54.0)):     # ultramafic, toward purple
    for _c in _codes.split():
        CLAST_TINT[_c] = _deg

# The template breaks its own extrusive=yellow / intrusive=pink convention in
# exactly two places. Corrected here; every other F code keeps its original.
FELSIC_YELLOW = (254, 241, 174)
FELSIC_PINK = (254, 175, 194)
ANCHOR_OVERRIDE = {
    "FD": FELSIC_YELLOW,     # Dacite is a lava, was sitting in the pink
    "FAB": FELSIC_PINK,      # Albitite is intrusive, was sitting in the yellow
    # 'Felsic Undifferentiated' is #a4c9cb in the template - a mafic cyan,
    # which cannot be right for the generic felsic code and collided with the
    # mafic-protolith amphibolites once those were re-based.
    "F": FELSIC_PINK,
}

# Textures whose chemistry, not their family, should set the hue.
# (hue degrees, lightness, saturation) - absolute, muted, hand-picked.
#
# SCOPED TO `Lithology` ONLY - see CHEMICAL_TYPES. This rule earns its keep on
# the sedimentary codes, where 32 of them share one blue `#78a7d3` and
# chemistry is the only thing available to separate limestone from chert from
# iron formation. It was actively harmful on Regolith and Transported Cover:
# those codes already carry a deliberate cream-and-buff palette in the
# template, and overriding it
#   * made RCC Calcrete render as SLI Limestone - same fill, same ink, same
#     brick tile, which is what a calcrete is not,
#   * did the same to RIST/SJP, RGO/SIF, RFC/TDLP, SEV/TGYP and TLTP/RDL*,
#     nine pixel-identical cross-family pairs in all, and
#   * flattened the regolith profile that the transported-cover toggle and
#     every regolith map depends on being able to read.
# A regolith unit is named for its weathering habit; its chemistry is already
# in its name. Only the Lithology codes needed chemistry to separate them.
CHEMICAL_HUE = {
    "limestone":      (196, 0.72, 0.26),
    "chert":          (205, 0.78, 0.12),
    "iron_formation": (14,  0.42, 0.34),
    "laterite":       (28,  0.62, 0.34),
    "evaporite":      (48,  0.86, 0.22),
}
CHEMICAL_TYPES = frozenset(["Lithology"])
CHEMICAL_EXEMPT = {("H", "limestone"), ("H", "marble")}   # marble stays H

# Rocks coloured by WHAT THEY WERE. The texture already says schist / gneiss.
PROTOLITH = {}
SHEARED = set()
METAMORPHIC = set()


def _proto(spec, bucket):
    for fam, codes in spec:
        for c in codes.split():
            PROTOLITH[c] = fam
            bucket.add(c)


_proto([
    ("M", "ZM ZMB ZMD ZMG ZMAM ZCS"),
    ("U", "ZU ZU-A ZU-CA ZU-P ZU-T ZU-TA ZU-TCB"),
    ("S", "ZS ZSAS ZSBS ZSPE ZSQT ZSST ZGT ZQM ZBXSI"),
    ("F", "ZF"),
    ("I", "ZI"),
], SHEARED)

_proto([
    ("I", "HIG HGI"),
    ("M", "HMG HGM HAMP HPA HPC HPK HPMA HEC HBL HGS"),
    ("U", "HGU"),
    ("S", "HPG HPEG HPPG HPSG HPH HSL"),
], METAMORPHIC)

# NOT re-based, deliberately: the migmatites keep the template's graded ramp,
# and hornfels / marble / skarn / the fault rocks have no single protolith.
#
# HFG HGF HGG HGGA HCK were re-based onto F and had to be REMOVED. The
# protolith target is a family MODAL colour, and F's modal is the intrusive
# pink (it beats the extrusive yellow 17-13), so "colour it like what it was
# made from" resolved felsic gneiss / granulite / charnockite to exactly the
# granitoid pink they most need to be told apart from - and it discarded the
# terracotta the user had deliberately set on HGG and HGGA to do it. They now
# carry their own colours from the template, as a terracotta gneiss family.
# Protolith colouring is still right for the mafic, intermediate, ultramafic
# and sedimentary metamorphics above: those families have one unambiguous
# colour each, so re-basing tells the reader something true.

# Sheared: deeper and PALER. Metamorphic: deeper and RICHER. Inverted on
# purpose so basalt, mafic gneiss and basalt schist all separate.
SHEAR_LIGHTNESS, SHEAR_SATURATION = -0.05, 0.72
META_LIGHTNESS, META_SATURATION = -0.09, 1.18

# "Richer" only means something where there is room to be richer. The
# intermediate family's own template colour #7bf4d4 is already at saturation
# 0.85, and multiplying that by META_SATURATION drove HGI Intermediate
# Granulite and HIG Intermediate Gneiss to #48faca - a fluorescent mint, on a
# geological map. Above this ceiling the fill is already as saturated as the
# palette goes, so the lightness shift alone carries the metamorphic signal.
# Deliberately NOT a blanket clamp in _mute(): 93 fills sit above 0.60,
# including the granitoid pink, the felsic yellow, the vein reds and the
# intermediate cyan, and every one of those is a colour the template chose.
# Flattening them is the exact mistake this module was rewritten to undo.
META_SATURATION_CEIL = 0.62

# Per-code lightness nudges, applied after the slot offset.
#
# The slot mechanism cannot express "make this one paler": which slot a code
# gets is an accident of alphabetical order over the variety keys, so asking
# for the pale end of a subgroup lands wherever sorting puts it. FGRL
# Leucogranite is defined by being pale, and it was previously forced DARK
# (#ab3f56) because a pale plagioclase ink needs a deep ground - which put a
# leucogranite in the same dark pink as the migmatites. Its ink is now `auto`,
# so instead of a dark ground it gets the pale fill the rock actually has.
LIGHTNESS_NUDGE = {
    "FGRL": +0.05,
}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def read_code_anchors():
    """{code: (r,g,b)} - the fill the live template gives THIS code.

    Per code, not per family. Using a family modal here is what flattened the
    palette in the first place.
    """
    con = sqlite3.connect("file:%s?mode=ro" % ORIGINAL.replace("\\", "/"),
                          uri=True)
    qml = con.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                      (LAYER,)).fetchone()[0]
    con.close()
    sym = {}
    for m in re.finditer(r'<symbol[^>]*name="(\d+)"', qml):
        seg = qml[m.start():m.start() + 2500]
        c = re.search(r'class="SimpleFill".*?<Option name="color" '
                      r'type="QString" value="(\d+),(\d+),(\d+)', seg, re.S)
        if c:
            sym[m.group(1)] = tuple(int(x) for x in c.groups())
    out = {}
    for m in re.finditer(r'<category([^>]*)/>', qml):
        a = m.group(1)
        v = re.search(r'value="([^"]*)"', a)
        s = re.search(r'symbol="(\d+)"', a)
        if not (v and s) or s.group(1) not in sym:
            continue
        code = v.group(1)
        if not code or code == "NULL":
            continue
        out[code] = sym[s.group(1)]
    out.update(ANCHOR_OVERRIDE)
    return out


def family_bases(anchors):
    """{family: (r,g,b)} modal colour, used only as a PROTOLITH target."""
    per = {}
    for code, rgb in anchors.items():
        if code in PROTOLITH:
            continue                      # re-based codes cannot define a base
        per.setdefault(code[0].upper(), []).append(rgb)
    bases = {}
    for fam, cols in per.items():
        counts = {}
        for c in cols:
            counts[c] = counts.get(c, 0) + 1
        bases[fam] = max(counts, key=counts.get)
    return bases


def read_texture_map():
    """{code: (texture, variety, type)} from lith_textures.tsv."""
    out = {}
    with open(TEXTURE_MAP, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if parts[0] == "code" or len(parts) < 2:
                continue
            variety = parts[6] if len(parts) > 6 and parts[6] != "-" else ""
            type_ = parts[2] if len(parts) > 2 else ""
            out[parts[0]] = (parts[1], variety, type_)
    return out


def is_chemically_hued(code, texture, type_):
    """Does this code take its hue from its chemistry rather than its family?

    Shared with the injector, which needs the same answer for its
    hue-tautology check: an iron-oxide ink on a chemically iron-oxide fill
    says nothing twice, but that reasoning only holds where the fill's hue
    really was set by chemistry.
    """
    return (texture in CHEMICAL_HUE
            and type_ in CHEMICAL_TYPES
            and (code[0].upper(), texture) not in CHEMICAL_EXEMPT)


def _family_of(code):
    """Which family this code resolves against."""
    return PROTOLITH.get(code, code[0].upper())


def _slots(tex_of):
    """{code: (lightness offset, hue offset)} within its subgroup."""
    groups = {}
    for code, (tex, _var, _type) in tex_of.items():
        groups.setdefault((_family_of(code), tex), []).append(code)
    slot_of = {}
    for codes in groups.values():
        buckets = {}
        for c in sorted(codes):
            var = tex_of[c][1] or ("=" + c)
            buckets.setdefault(var, []).append(c)
        order = sorted(buckets)
        n = len(order)
        if n > 1:
            step = min(SLOT_STEP, (2.0 * SLOT_HALF_RANGE) / (n - 1))
            hstep = min(HUE_SLOT_STEP, (2.0 * HUE_SLOT_MAX) / (n - 1))
            for i, var in enumerate(order):
                k = i - (n - 1) / 2.0
                for c in buckets[var]:
                    slot_of[c] = (k * step, k * hstep)
        else:
            for c in codes:
                slot_of[c] = (0.0, 0.0)
    return slot_of


def slot_offsets():
    """Exposed so a caller can restore separation after fitting a fill."""
    return _slots(read_texture_map())


def _mute(h, l, s, l_ref):
    """Shared muted clamps. Any lightness move must go through these."""
    l = _clamp(l, L_MIN, L_MAX)
    if l_ref and l < l_ref:
        s *= 0.55 + 0.45 * (l / l_ref)
    if l < 0.62:
        s = min(s, 0.46)
    return h % 1.0, l, _clamp(s, 0.0, 1.0)


def build(deepen=()):
    """{code: (r,g,b)}.

    deepen: codes carrying a pale mineral ink, which need a dark ground for
    the texture to read (anorthosite's white plagioclase dots).
    """
    anchors = read_code_anchors()
    tex_of = read_texture_map()
    bases = family_bases(anchors)
    slot_of = _slots(tex_of)

    # Which anchors are shared? Only those need separating.
    counts = {}
    for rgb in anchors.values():
        counts[rgb] = counts.get(rgb, 0) + 1

    out = {}
    for code, (tex, _var, type_) in tex_of.items():
        anchor = anchors.get(code)
        if anchor is None:
            continue
        moved = False

        if code in PROTOLITH:
            anchor = bases.get(PROTOLITH[code], anchor)
            moved = True
        elif is_chemically_hued(code, tex, type_):
            hue, lig, sat = CHEMICAL_HUE[tex]
            anchor = tuple(round(c * 255)
                           for c in colorsys.hls_to_rgb(hue / 360.0, lig, sat))
            moved = True

        h, l, s = colorsys.rgb_to_hls(*[c / 255.0 for c in anchor])
        l_ref = l
        touched = moved

        if code in SHEARED:
            l += SHEAR_LIGHTNESS
            s *= SHEAR_SATURATION
            touched = True
        elif code in METAMORPHIC:
            l += META_LIGHTNESS
            s = min(s * META_SATURATION, max(s, META_SATURATION_CEIL))
            touched = True

        # Separate only where the colour was already shared, or where the code
        # has been moved onto a shared base. A unique original colour is left
        # exactly as the template has it.
        if moved or counts.get(anchors[code], 0) > 1:
            dl, dh = slot_of.get(code, (0.0, 0.0))
            l += dl
            h += dh / 360.0
            touched = touched or bool(dl) or bool(dh)
        if code in CLAST_TINT:
            h += CLAST_TINT[code] / 360.0
            touched = True
        if code in LIGHTNESS_NUDGE:
            l += LIGHTNESS_NUDGE[code]
            touched = True

        if code in deepen:
            l = min(l, 0.46)
            touched = True

        if not touched:
            # Nothing moved this colour, so hand back the template's own value
            # byte for byte. Sending it through the muted clamps anyway
            # desaturates any mid-lightness saturated colour - it turned the
            # user's HGG Granite Gneiss terracotta #d96a4e into #c57662 - which
            # silently breaks the rule this module exists to enforce: a colour
            # the template already decided is kept EXACTLY.
            out[code] = tuple(anchor)
            continue

        h, l, s = _mute(h, l, s, l_ref)
        out[code] = tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, l, s))
    return out


def hexof(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


if __name__ == "__main__":
    anchors = read_code_anchors()
    p = build()
    kept = sum(1 for c, rgb in p.items() if anchors.get(c) == rgb)
    print("%d codes -> %d distinct fills (%d keep their exact original colour)"
          % (len(p), len(set(p.values())), kept))
    for label, codes in (("felsic extrusive", "FR FIG FTA FV FVC FD"),
                         ("felsic intrusive", "FGR FGD FSY FAB"),
                         ("migmatites", "HMIP HMIS HMIN HMIT HMI HMIM HMID"),
                         ("mafic gneiss / basalt / basalt schist",
                          "HMG MB ZMB")):
        print("  %-38s %s" % (label, "  ".join(
            "%s=%s" % (c, hexof(p[c])) for c in codes.split() if c in p)))
