"""Vein generations (V1-V5) and selvedges, on Linework lines and Basemap polygons.

Generational vein mapping - V1 cut by V2 cut by V3 - is the backbone of
structural and economic mapping, and the alteration selvedge either side of
a vein is very often the thing that identifies which generation it belongs
to.  Neither could be recorded before: a vein carried a width, minerals,
a texture and a confidence, and nothing else.

Three fields per layer:

    VeinGen         TEXT   ValueMap V1..V5
    Selvedge_cm     REAL   selvedge width in cm (mm as decimals, 0.5 = 5mm)
    SelvedgeMineral TEXT   ValueRelation -> MineralCodes

GENERATION IS DELIBERATELY LABEL-ONLY.  Colour on the vein symbols already
means vein TYPE (quartz orange, mineralised red, shear red-wave), and the
template's other generation systems - Fold Axial Trace F1-F5, Formline
S1-S5 - spend the whole Type code on the generation, which 13 vein codes
cannot afford.  So VeinGen is orthogonal to Type: any vein type can carry
any generation, and it reads on the map as a tag, not as a colour.

THE SELVEDGE IS DRAWN, as a stipple.  A selvedge is a diffuse alteration
halo and a solid line says the opposite - it reads as a second contact - so
each vein wears up to three rings of fine dots, phased against each other so
they interleave rather than line up.  Rings step OUTWARD as the recorded
width grows (ring 1 always, ring 2 past 10 cm, ring 3 past a metre), so a wide
selvedge visibly reaches further into the wallrock than a narrow one.  On
Linework the rings are offset curves either side of the vein; on Basemap
they are buffers OUTSIDE the polygon, because that is where altered wallrock
actually is - and because an outward buffer cannot degenerate the way the
inward band it replaced did.  Dot colour follows SelvedgeMineral.

Everything evaluates in PAPER MILLIMETRES (units=MM honours the renderer's
referenceScale), so the ornament is the same size on the page at UG 1:100
and surface 1:10 000.

Scope is Veins-only, narrower than the sibling detail fields that
inject_linework_detail_scope.py widened onto dykes/sills and faults/shears.
That is on purpose: the form gate must match where ink can appear, and the
stipple only exists on the 9 vein symbols.  Letting a mapper record a dyke's
chilled margin that renders nowhere would be worse than not offering it.

Run order matters:

    inject_linework_mineral_pcts.py   owns the Linework label this splices into
    inject_basemap_mineral_pcts.py    owns the Basemap label - MUST NOT be
                                      re-run after this script, it rewrites
                                      fieldName wholesale and would drop the
                                      vein tag (recovery chain below)
    inject_vein_generation_selvedge.py   <- this script
    remove_linework_codes.py          MUST run first if codes are being
                                      retired - this script bails on a
                                      LW_VEIN_CODES entry it cannot find
    inject_weight_scaling.py          MUST run after: its Linework pass
                                      recurses into sub-symbols and ramps the
                                      stipple dot size to Weight x Width_cm
                                      for us.  Do not author that ramp here.
    inject_basemap_lith_patterns.py   re-bakes LGS_MappingTemplate_Patterns.gpkg

inject_label_grammar.py joins the Linework label's groups and owns that
assembly; the fragments here (LW_GEN_TEXT, LW_SLV_TEXT) are embedded in it
verbatim, so this script no-ops once it has run.

If inject_basemap_mineral_pcts.py ever has to run again - it rewrites the
Basemap label wholesale, so it is the one injector a no-op sweep must skip -
replay:
    inject_basemap_mineral_pcts -> inject_confidence_system ->
    inject_label_grammar -> inject_vein_generation_selvedge ->
    inject_label_cartography -> inject_weight_scaling ->
    inject_label_size_scaling -> inject_basemap_lith_patterns

styleSLD is deliberately left alone: SLD cannot express a geometry
generator, and no category or colour changes here (same reasoning as
inject_basemap_lith_patterns.py).

Idempotent and re-runnable.  Symbol layers are matched by deterministic
uuid5 id, never by style, and every QML is parse-validated BEFORE it is
written.

Usage:  python scripts/inject_vein_generation_selvedge.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import shutil
import sqlite3
import sys
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inject_basemap_mineral_pcts as _basemap  # noqa: E402
from inject_weight_scaling import DETAIL_WIDTH_FACTOR, FACTORS  # noqa: E402

LW = "2 - Linework"
BM = "4 - Basemap"
BACKUP_DATE = "2026-08-18"
BACKUP_NAME = "LGS_MappingTemplate_pre-vein-generations_%s.gpkg" % BACKUP_DATE
MUS = "3x:0,0,0,0,0,0"
MM_PER_PT = 25.4 / 72.0
ALT_OUTLINE_DASH = "1.5;0.7"   # inject_overlay_alteration_outline counts
                               # its outlines by this dash over a
                               # recursive walk.  Unreachable now that the
                               # stipple carries no SimpleLine, but kept so
                               # the test can keep asserting we never emit it.

GENERATIONS = ("V1", "V2", "V3", "V4", "V5")

# Basemap lithology codes in the vein family (BasemapCodes 'V' prefix).
VEIN_LITHS = ("VC", "VL", "VN", "VPG", "VQ", "VQC", "VS", "VSTW", "VT", "VX")

LW_VEINS = "\"Category\" = 'Veins'"
BM_VEINS = '"Lithology1" IN (%s)' % ", ".join("'%s'" % c for c in VEIN_LITHS)

# Either field on its own is enough to say "there is a selvedge here" - a
# mapper often knows 'sericite selvedge' without stopping to measure it,
# and 0 means unrecorded rather than zero-width (inject_zero_value_guards).
SELVEDGE_ON = ("(coalesce(\"Selvedge_cm\", 0) > 0 "
               "OR coalesce(\"SelvedgeMineral\", '') != '')")

# Linework: the 9 vein codes that draw as a single solid backbone.  Vein
# Set / Sheeted and Stockwork Zone Boundary are excluded - a swarm and a
# zone envelope have no two margins to hem, and their dashes encode
# identity.  Vein - Epidote and Vein - Mineralised were retired in Aug 2026
# (scripts/remove_linework_codes.py).  Same 9 as
# inject_confidence_system.SOLID_CODES' vein block, and for the same reason.
LW_VEIN_CODES = [
    "Vein", "Vein - Breccia", "Vein - Carbonate",
    "Vein - Extension", "Vein - Laminated",
    "Vein - Pegmatite", "Vein - Quartz", "Vein - Quartz-Carbonate",
    "Vein - Shear",
]

# --- The stipple -----------------------------------------------------------
# A selvedge is a diffuse alteration halo, and a solid line says the opposite
# - it reads as a second contact.  So it is drawn as rings of fine dots that
# step OUTWARD as the recorded width grows: ring 1 always, ring 2 past
# 10 cm, ring 3 past a metre.
#
# The tiers are set against what a SELVEDGE does, not what a vein does.  They
# started life as the vein-width tiers (2 cm / 10 cm) and saturated far too
# early - a 10 cm alteration halo and a 3 m one drew identically, collapsing
# the top two thirds of the real range into one step.
#
# Three authored layers rather than one generator emitting every ring,
# because the interleave has to come from somewhere: offset_along_line is a
# SYMBOL LAYER property, so rings can only differ in phase if each owns its
# sub-symbol.  Without that the dots line up in radial rows and read as a
# grid instead of a stipple.
RINGS = (1, 2, 3)
RING_SPACING = 1.0           # paper-mm between successive rings
RING_ON = {
    1: SELVEDGE_ON,
    2: "%s AND coalesce(\"Selvedge_cm\", 0) > 10" % SELVEDGE_ON,
    3: "%s AND coalesce(\"Selvedge_cm\", 0) > 100" % SELVEDGE_ON,
}

DOT_INTERVAL = 2.2           # paper-mm between dots along a ring
DOT_SIZE = "0.45"            # paper-mm; the vein's OWN decoration is a 1.8mm
                             # circle every 6mm, so the stipple stays clearly
                             # subordinate to it
# Phase per ring, as a fraction of the interval: thirds, so three rings never
# line up with each other.
DOT_PHASE = {r: round(DOT_INTERVAL * (r - 1) / 3.0, 3) for r in RINGS}

# Vein - Shear already wears a decorative selvage: a one-sided
# wave(offset_curve($geometry, 1.1), amplitude:=0.4) whose outer envelope
# reaches 1.1 + 0.4 + 0.28/2 = 1.64mm from the centreline, and whose offset
# is a STATIC that does not shrink with Weight or Width.  Push the stipple
# outside it so the two read as two things.
LW_CLEARANCE = {"Vein - Shear": 1.40}

# Paper-mm of white between the drawn vein EDGE and ring 1.  A constant now:
# the recorded width is carried by how many rings appear, not by the gap.
# Wide enough that the stipple reads as a separate halo rather than as fluff
# on the line itself.
LW_GAP = 0.55

# Paper-mm from the polygon boundary out to ring 1.  Outward, so a narrow
# vein pod cannot degenerate the way an inward buffer did.
BM_GAP = 0.7

WEIGHT_F = ("CASE WHEN \"Weight\" = 'Major' THEN %s "
            "WHEN \"Weight\" = 'Minor' THEN %s ELSE 1 END"
            % (FACTORS["Major"], FACTORS["Minor"]))

# --- Selvedge mineral -> colour --------------------------------------------
# Extends the paper convention in inject_overlay_mineralisation.MINERAL_RGB,
# keyed on SelvedgeMineral instead of Mineral1.  Grouped by FAMILY, because a
# selvedge is logged as a species but read as an alteration type - a sericite
# and a muscovite selvedge are the same thing to the eye at map scale.
#
# Every code here was checked against MineralCodes.Value (which is the key
# column - it has no Code column, see data_import/domain.py).  Codes not
# listed fall through to the ELSE, which is the FEATURE'S OWN COLOUR rather
# than a neutral: an unrecorded mineral should still read as belonging to its
# vein, not introduce a hue that means nothing.
SELVEDGE_RGB = [
    (("Ser", "Ms", "Ilt", "Pg", "Prl"), "196,176,110"),      # white mica
    (("Chl", "Fch", "Stp", "Cld"), "86,138,94"),             # chlorite
    (("Bt", "Phl"), "138,94,54"),                            # biotite
    (("Slc", "Qz", "Ccd", "Opl", "Jsp"), "150,155,160"),     # silica
    (("Cb", "Cal", "Dol", "Ank", "Sd", "Mgs"), "108,152,178"),   # carbonate
    (("Kfs", "Or", "Adl", "Mc", "Afs"), "198,124,140"),      # K-feldspar
    (("Ab", "Olg", "Pl", "Sau"), "216,198,196"),             # albite
    (("Ep", "Czo", "Zo", "Prh", "Grt", "Di", "Hd", "Scp"), "140,160,60"),
    (("Act", "Tr", "Amp", "Hbl", "Cum", "Ath"), "62,102,78"),    # amphibole
    (("Tlc", "Srp", "Atg", "Ctl", "Lz", "Brc"), "132,178,164"),  # talc/serp
    (("Hem", "Mrt", "FeOx", "Gth", "Lm", "Jrs"), "176,72,58"),   # iron oxide
    (("Mag", "Mgh", "Ilm"), "72,74,80"),                     # magnetite
    (("Py", "Po", "Ccp", "Apy", "Sul", "MSul"), "196,150,42"),   # sulphide
    (("Tur", "Elb", "Gr", "C"), "48,46,46"),                 # tourmaline
    (("Kln", "Kao", "Cly", "Mnt", "Sme", "Alu", "Dck"), "200,186,160"),  # clay
]

# The Basemap fallback dot: the unit's own fill, 25% deeper, so a dot
# with no mineral recorded still reads as belonging to that unit.
BAND_DARKEN = 0.75

DOT_ALPHA = 235


def rgb_only(value):
    """'r,g,b' from a QGIS colour string.

    color_rgba() takes FOUR arguments.  Handing it a 4-part 'r,g,b,a' string
    plus an alpha builds a five-argument call, which fails to PARSE - and a
    data-defined expression that does not parse is dropped in silence, so the
    dots simply keep their static colour and nothing anywhere complains.
    That is exactly how this shipped broken once; tests/test_vein_selvedge_qgis
    now parses every dd expression in the template for that reason.
    """
    return ",".join(value.split(",")[:3])


def selvedge_colour_expr(fallback_rgb):
    """Dot colour from SelvedgeMineral, falling back to the feature's own.

    fallback_rgb must be a bare 'r,g,b' triple - see rgb_only().

    Flat CASE, no nesting - QgsExpression parse cost doubles per
    with_variable level and this is evaluated per feature per ring.
    """
    branches = " ".join(
        "WHEN \"SelvedgeMineral\" IN (%s) THEN color_rgba(%s,%d)"
        % (", ".join("'%s'" % c for c in codes), rgb, DOT_ALPHA)
        for codes, rgb in SELVEDGE_RGB)
    return "CASE %s ELSE color_rgba(%s,%d) END" % (branches, fallback_rgb,
                                                   DOT_ALPHA)


# --- Label fragments -------------------------------------------------------
# The mm/cm/m formatter is inject_linework_vein_fields.WIDTH_TEXT, re-pointed
# at Selvedge_cm.  0 reads as unrecorded, never as '0mm'.


def auto_width_text(field):
    return ("CASE WHEN coalesce(\"{f}\", 0) <= 0 THEN '' "
            "WHEN \"{f}\" >= 100 THEN round(\"{f}\"/100.0, 2) || 'm' "
            "WHEN \"{f}\" < 1 THEN round(\"{f}\"*10, 1) || 'mm' "
            "ELSE round(\"{f}\", 1) || 'cm' END".format(f=field))


def slv_text(gate):
    """'Slv: 3cm Bt', or '' when there is no selvedge on this feature.

    A named group, because the vein already carries a width of its own and
    two bare measurements in a row cannot be told apart - which is exactly
    what '10cm Brt slv 10cm Afs' did.

    The gate is not belt-and-braces.  On Linework the selvedge sits inside
    the detail-scope branch of the label, which also covers dykes, faults
    and shears - and a stray Selvedge_cm arriving there by attribute copy
    or import would print a selvedge the symbology never draws.  A label
    must not promise ink that cannot appear.
    """
    return ("CASE WHEN NOT (%s AND %s) THEN '' ELSE 'Slv:' || "
            "coalesce(' ' || nullif(%s, ''), '') || "
            "coalesce(' ' || \"SelvedgeMineral\", '') END"
            % (gate, SELVEDGE_ON, auto_width_text("Selvedge_cm")))


LW_SLV_TEXT = slv_text(LW_VEINS)
BM_SLV_TEXT = slv_text(BM_VEINS)

LW_GEN_TEXT = ("CASE WHEN %s AND coalesce(\"VeinGen\",'') != '' "
               "THEN \"VeinGen\" ELSE '' END" % LW_VEINS)

# Linework anchors, both asserted unique before use.
LW_HEAD = 'array_remove_all(array(CASE WHEN coalesce("Width_cm", 0)'
LW_TAIL = 'coalesce("Label",\'\')'

# The vein tag goes AFTER the Lith1 modifier span, so a vein reads
# 'VQ (Qtz(90%), Bnd), V2, Slv: 5cm Ser' rather than wedging the vein data
# between the unit code and the unit's own modifiers.  SPAN1 is unique in
# the expression - SPAN2 reads the Lith2 fields - so it is a safe anchor.
#
# The tag's own span string MUST be the font-weight:400 variant - the bare
# 'font-style:italic;font-size:70%;' is what inject_label_cartography counts.
# That same rewrite is why the anchor has to be recognised in EITHER weight,
# depending on whether cartography has run yet.
CART_SPAN = "font-style:italic;font-size:70%;"
CART_SPAN_LIGHT = "font-style:italic;font-weight:400;font-size:70%;"


def bm_anchor(expr):
    plain = _basemap.SPAN1 + " ||"
    for cand in (plain, plain.replace(CART_SPAN, CART_SPAN_LIGHT)):
        if expr.count(cand) == 1:
            return cand
    return None
BM_TAG = (
    "CASE WHEN (%s) AND (coalesce(\"VeinGen\",'') != '' OR %s) THEN "
    "'<span style=\"font-style:italic;font-weight:400;font-size:70%%;\">, ' || "
    "array_to_string(array_remove_all(array(coalesce(\"VeinGen\",''), %s), ''), ', ') "
    "|| '</span>' ELSE '' END" % (BM_VEINS, SELVEDGE_ON, BM_SLV_TEXT))

# --- Field specs -----------------------------------------------------------
# field, sql type, widget kind, alias, visibility, insert-after container
LW_SPEC = [
    ("VeinGen", "TEXT(10)", "generation", "Vein Generation",
     LW_VEINS, "Vein Texture"),
    ("Selvedge_cm", "REAL", "selvedge", "Selvedge (cm)",
     LW_VEINS, "Vein Generation"),
    ("SelvedgeMineral", "TEXT(250)", "mineral", "Selvedge Mineral",
     LW_VEINS, "Selvedge (cm)"),
]
BM_SPEC = [
    ("VeinGen", "TEXT(10)", "generation", "Vein Generation",
     BM_VEINS, "Lith2 Texture 2"),
    ("Selvedge_cm", "REAL", "selvedge", "Selvedge (cm)",
     BM_VEINS, "Vein Generation"),
    ("SelvedgeMineral", "TEXT(100)", "mineral", "Selvedge Mineral",
     BM_VEINS, "Selvedge (cm)"),
]


def bail(msg):
    raise SystemExit("ABORT: " + msg)


# ---------------------------------------------------------------------------
# File guards (lifted from inject_overlay_shear_fabric.py)
# ---------------------------------------------------------------------------

def back_up(repo, gpkg):
    """Snapshot beside the file being edited, not always into the repo."""
    if os.path.abspath(gpkg) == os.path.abspath(
            os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")):
        dest = os.path.join(repo, "Template", "Backup", BACKUP_NAME)
    else:
        stem, ext = os.path.splitext(gpkg)
        dest = "%s_pre-vein-generations_%s%s" % (stem, BACKUP_DATE, ext)
    if not os.path.exists(dest):
        shutil.copy2(gpkg, dest)
    return dest


def refuse_if_open(gpkg):
    """Bail if QGIS still has the gpkg open.

    The quiet hazard is the second one: SQLite may let the write through,
    but QGIS holds layer_styles in memory and writes its own copy back on
    the next project save - so the change appears to work, then vanishes.

    The -wal check MUST come first and MUST NOT be preceded by a connection
    of our own: connecting and closing cleanly checkpoints and DELETES the
    -wal, destroying the evidence.
    """
    if os.path.exists(gpkg + "-wal"):
        bail("%s has an active -wal alongside it, so something still has it "
             "open. Close the project in QGIS first: styles live in "
             "layer_styles, and QGIS would write its in-memory copy straight "
             "back over this edit on the next save."
             % os.path.basename(gpkg))
    try:
        con = sqlite3.connect(gpkg, timeout=1.0)
        con.execute("BEGIN IMMEDIATE")
        con.execute("ROLLBACK")
        con.close()
    except sqlite3.OperationalError as exc:
        bail("%s is locked (%s) - close the project in QGIS and re-run"
             % (os.path.basename(gpkg), exc))


def layer_id(kind, code):
    return "{%s}" % uuid.uuid5(uuid.NAMESPACE_URL,
                               "lgs-selvedge-%s:%s" % (kind, code))


# ---------------------------------------------------------------------------
# Widget / form XML (shapes from inject_linework_vein_fields.py and
# inject_confidence_system.py)
# ---------------------------------------------------------------------------

def opt(parent, name, otype=None, value=None):
    e = ET.SubElement(parent, "Option")
    e.set("name", name)
    if otype is not None:
        e.set("type", otype)
    if value is not None:
        e.set("value", value)
    return e


def _field_root(field):
    root = ET.Element("field")
    root.set("name", field)
    root.set("configurationFlags", "NoFlag")
    return root


def value_relation_block(field, layer_name, key, value, gpkg_path):
    root = _field_root(field)
    ew = ET.SubElement(root, "editWidget")
    ew.set("type", "ValueRelation")
    cfg = ET.SubElement(ew, "config")
    m = ET.SubElement(cfg, "Option")
    m.set("type", "Map")
    opt(m, "AllowMulti", "bool", "false")
    opt(m, "AllowNull", "bool", "true")
    opt(m, "CompleterMatchFlags", "int", "2")
    opt(m, "Description", "invalid")
    opt(m, "DisplayGroupName", "bool", "false")
    opt(m, "FilterExpression", "invalid")
    opt(m, "Group", "invalid")
    opt(m, "Key", "QString", key)
    opt(m, "LayerName", "QString", layer_name)
    opt(m, "LayerProviderName", "QString", "ogr")
    opt(m, "LayerSource", "QString",
        gpkg_path.replace("\\", "/") + "|layername=" + layer_name)
    opt(m, "NofColumns", "int", "1")
    opt(m, "OrderByValue", "bool", "true")
    opt(m, "UseCompleter", "bool", "false")
    opt(m, "Value", "QString", value)
    return ET.tostring(root, encoding="unicode")


def range_block(field, minv, maxv, step, precision):
    root = _field_root(field)
    ew = ET.SubElement(root, "editWidget")
    ew.set("type", "Range")
    cfg = ET.SubElement(ew, "config")
    m = ET.SubElement(cfg, "Option")
    m.set("type", "Map")
    opt(m, "AllowNull", "bool", "true")
    opt(m, "Max", "int", maxv)
    opt(m, "Min", "int", minv)
    opt(m, "Precision", "int", precision)
    opt(m, "Step", "int", step)
    opt(m, "Style", "QString", "SpinBox")
    return ET.tostring(root, encoding="unicode")


def valuemap_block(field, values):
    root = _field_root(field)
    ew = ET.SubElement(root, "editWidget")
    ew.set("type", "ValueMap")
    cfg = ET.SubElement(ew, "config")
    outer = ET.SubElement(cfg, "Option", {"type": "Map"})
    lst = ET.SubElement(outer, "Option", {"name": "map", "type": "List"})
    for v in values:
        m = ET.SubElement(lst, "Option", {"type": "Map"})
        ET.SubElement(m, "Option", {"name": v, "type": "QString", "value": v})
    return ET.tostring(root, encoding="unicode")


def widget_block(field, kind, gpkg):
    if kind == "generation":
        return valuemap_block(field, GENERATIONS)
    if kind == "mineral":
        return value_relation_block(field, "MineralCodes", "Value",
                                    "Description", gpkg)
    if kind == "selvedge":
        # Byte-identical config to Width_cm: precision 1, so 0.5 = 5mm.
        return range_block(field, "0", "100000", "1", "1")
    bail("unknown widget kind %r" % kind)


def container_block(field, alias, vis_expr, index):
    c = ET.Element("attributeEditorContainer")
    for k, v in [("name", alias), ("type", "GroupBox"), ("collapsed", "0"),
                 ("collapsedExpression", ""), ("horizontalStretch", "0"),
                 ("groupBox", "1"), ("showLabel", "0"),
                 ("verticalStretch", "0"), ("columnCount", "1"),
                 ("collapsedExpressionEnabled", "0"),
                 ("visibilityExpressionEnabled", "1"),
                 ("visibilityExpression", vis_expr)]:
        c.set(k, v)
    f = ET.SubElement(c, "attributeEditorField")
    for k, v in [("name", field), ("index", str(index)),
                 ("horizontalStretch", "0"), ("showLabel", "1"),
                 ("verticalStretch", "0")]:
        f.set(k, v)
    return ET.tostring(c, encoding="unicode")


def insert_before(qml, closing_tag, fragment):
    i = qml.find(closing_tag)
    if i < 0 or qml.find(closing_tag, i + 1) >= 0:
        bail("%r not found or not unique" % closing_tag)
    return qml[:i] + fragment + qml[i:]


def container_span(qml, name):
    """Byte range of the named attributeEditorContainer (one field, no nesting)."""
    m = re.search(r'<attributeEditorContainer[^>]*\bname=%s[^>]*>'
                  % re.escape(quoteattr(name)), qml)
    if not m:
        bail("form container %r not found" % name)
    end = qml.find("</attributeEditorContainer>", m.end())
    if end < 0:
        bail("form container %r not closed" % name)
    return m.start(), end + len("</attributeEditorContainer>")


def add_fields(cur, layer, qml, spec, gpkg):
    """Columns, the 11 per-field QML tags, and one gated container each."""
    cols = [r[1] for r in cur.execute('PRAGMA table_info("%s")' % layer)]
    for field, sqltype, _k, _a, _v, _after in spec:
        if field in cols:
            print("  column %s: already present" % field)
        else:
            cur.execute('ALTER TABLE "%s" ADD COLUMN "%s" %s'
                        % (layer, field, sqltype))
            print("  column %s: added (%s)" % (field, sqltype))
    # Recompute AFTER the ALTERs - form indexes are QGIS field indexes,
    # i.e. table columns minus geom.
    cols = [r[1] for r in cur.execute('PRAGMA table_info("%s")' % layer)]
    qgis_cols = [c for c in cols if c != "geom"]
    index = {f: qgis_cols.index(f) for f, *_ in spec}

    for field, _t, kind, alias, _vis, _after in spec:
        if '<field name="%s" configurationFlags' % field in qml:
            print("  %s: config already present" % field)
            continue
        qml = insert_before(qml, "</fieldConfiguration>",
                            widget_block(field, kind, gpkg))
        qml = insert_before(qml, "</aliases>",
                            '<alias name="%s" index="%d" field="%s"/>'
                            % (alias, index[field], field))
        qml = insert_before(qml, "</splitPolicies>",
                            '<policy policy="Duplicate" field="%s"/>' % field)
        qml = insert_before(qml, "</duplicatePolicies>",
                            '<policy policy="Duplicate" field="%s"/>' % field)
        qml = insert_before(qml, "</defaults>",
                            '<default expression="" applyOnUpdate="0" '
                            'field="%s"/>' % field)
        qml = insert_before(qml, "</constraints>",
                            '<constraint constraints="0" notnull_strength="0" '
                            'field="%s" unique_strength="0" exp_strength="0"/>'
                            % field)
        qml = insert_before(qml, "</constraintExpressions>",
                            '<constraint desc="" field="%s" exp=""/>' % field)
        qml = insert_before(qml, "</columns>",
                            '<column name="%s" type="field" hidden="0" '
                            'width="-1"/>' % field)
        qml = insert_before(qml, "</editable>",
                            '<field name="%s" editable="1"/>' % field)
        qml = insert_before(qml, "</labelOnTop>",
                            '<field name="%s" labelOnTop="0"/>' % field)
        qml = insert_before(qml, "</reuseLastValue>",
                            '<field reuseLastValue="0" name="%s"/>' % field)
        print("  %s: config injected" % field)

    for field, _t, _k, alias, vis, after in spec:
        if '<attributeEditorContainer name=%s' % quoteattr(alias) in qml:
            print("  %s: container already present" % alias)
            continue
        _s, e = container_span(qml, after)
        qml = qml[:e] + container_block(field, alias, vis, index[field]) + qml[e:]
        print("  %s: container injected after %r" % (alias, after))
    return qml


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def splice_label(qml, layer):
    """Splice the vein tag into the layer's label expression, in place.

    Both layers' expressions are OWNED by other injectors, so this only ever
    inserts at a checked-unique anchor - it never rewrites the expression,
    and it never appends past the Confidence suffix (which would make
    inject_confidence_system bolt on a second '?' on its next run).
    """
    lm = re.search(r'<labeling type="simple">.*?</labeling>', qml, re.S)
    if not lm:
        bail("%s: simple labeling block not found" % layer)
    lab = ET.fromstring(lm.group(0))
    ts = lab.find(".//text-style")
    expr = ts.get("fieldName") or ""
    if ts.get("isExpression") != "1":
        bail("%s: label is not an expression - has the owning injector run?"
             % layer)

    if layer == LW:
        if LW_GEN_TEXT in expr:
            print("  label: already applied")
            return qml, False
        for anchor in (LW_HEAD, LW_TAIL):
            if expr.count(anchor) != 1:
                bail("%s: label anchor %r appears %d times, expected 1 - has "
                     "inject_linework_mineral_pcts.py been re-run since?"
                     % (layer, anchor[:48], expr.count(anchor)))
        # Generation leads, the way a vein is tagged on paper: 'V2 7cm Qz-Py'.
        new = expr.replace(
            LW_HEAD, 'array_remove_all(array(%s, CASE WHEN coalesce("Width_cm", 0)'
                     % LW_GEN_TEXT)
        new = new.replace(LW_TAIL, "%s, %s" % (LW_SLV_TEXT, LW_TAIL))
    else:
        if BM_TAG in expr:
            print("  label: already applied")
            return qml, False
        anchor = bm_anchor(expr)
        if anchor is None:
            bail("%s: the Lith1 modifier span is not in the label exactly "
                 "once, in either weight - has inject_basemap_mineral_pcts.py "
                 "been re-run since?" % layer)
        new = expr.replace(anchor, "%s %s ||" % (anchor, BM_TAG))

    ts.set("fieldName", new)
    print("  label: vein tag spliced in")
    return qml[:lm.start()] + ET.tostring(lab, encoding="unicode") + qml[lm.end():], True


# ---------------------------------------------------------------------------
# Symbology
# ---------------------------------------------------------------------------

def symbol_block(q, name):
    """Byte range of the balanced <symbol name="..."> block."""
    m = re.search(r'<symbol\b[^>]*\bname="%s"[^>]*>' % re.escape(name), q)
    if not m:
        bail("symbol %r not found" % name)
    depth = 0
    for t in re.finditer(r'<symbol\b|</symbol>', q[m.start():]):
        depth += 1 if t.group(0) == '<symbol' else -1
        if depth == 0:
            return m.start(), m.start() + t.end()
    bail("unbalanced symbol %r" % name)


def direct_opts(el):
    """The element's OWN options - never descend into sub-symbols."""
    cont = el.find("Option")
    if cont is None:
        return {}
    return {o.get("name"): o for o in cont.findall("Option")}


def empty_dd():
    """Every layer needs one, even when empty.

    inject_weight_scaling.inject_into_scope() finds a layer's dd block with
    a forward re.search from the layer tag; a layer with no block of its own
    makes it grab the NEXT layer's and rewrite it with the wrong statics.
    """
    el = ET.Element("data_defined_properties")
    outer = ET.SubElement(el, "Option", {"type": "Map"})
    ET.SubElement(outer, "Option", {"name": "name", "type": "QString", "value": ""})
    ET.SubElement(outer, "Option", {"name": "properties"})
    ET.SubElement(outer, "Option", {"name": "type", "type": "QString",
                                    "value": "collection"})
    return el


def set_dd(layer_el, key, expression):
    """Merge one data-defined property in, leaving any siblings alone."""
    dd = layer_el.find("data_defined_properties")
    if dd is None:
        dd = ET.SubElement(layer_el, "data_defined_properties")
    outer = dd.find("Option")
    if outer is None:
        outer = ET.SubElement(dd, "Option", {"type": "Map"})
        ET.SubElement(outer, "Option",
                      {"name": "name", "type": "QString", "value": ""})
        ET.SubElement(outer, "Option", {"name": "type", "type": "QString",
                                        "value": "collection"})
    props = None
    for o in outer.findall("Option"):
        if o.get("name") == "properties":
            props = o
            break
    if props is None:
        props = ET.SubElement(outer, "Option", {"name": "properties"})
    props.set("type", "Map")
    for existing in props.findall("Option"):
        if existing.get("name") == key:
            props.remove(existing)
    entry = ET.SubElement(props, "Option", {"name": key, "type": "Map"})
    ET.SubElement(entry, "Option",
                  {"name": "active", "type": "bool", "value": "true"})
    ET.SubElement(entry, "Option",
                  {"name": "expression", "type": "QString", "value": expression})
    ET.SubElement(entry, "Option", {"name": "type", "type": "int", "value": "3"})


def get_dd(layer_el, key):
    dd = layer_el.find("data_defined_properties")
    if dd is None:
        return None
    for outer in dd.findall("Option"):
        for props in outer.findall("Option"):
            if props.get("name") != "properties":
                continue
            for entry in props.findall("Option"):
                if entry.get("name") == key:
                    for o in entry.findall("Option"):
                        if o.get("name") == "expression":
                            return o.get("value")
    return None


def marker_line_opts(phase_mm):
    """A MarkerLine that lays dots along the ring at a per-ring phase.

    offset_along_line is what interleaves the rings; it is a symbol-layer
    property, which is the whole reason each ring is its own authored layer
    rather than one generator emitting all three.
    """
    return {
        "average_angle_length": "4",
        "average_angle_map_unit_scale": MUS,
        "average_angle_unit": "MM",
        "interval": _num(DOT_INTERVAL),
        "interval_map_unit_scale": MUS,
        "interval_unit": "MM",
        "offset": "0",
        "offset_along_line": _num(phase_mm),
        "offset_along_line_map_unit_scale": MUS,
        "offset_along_line_unit": "MM",
        "offset_map_unit_scale": MUS,
        "offset_unit": "MM",
        "place_on_every_part": "true",
        "placements": "Interval",
        "ring_filter": "0",
        "rotate": "0",
    }


def dot_opts(color):
    """One stipple dot.

    outline_width 0 keeps inject_weight_scaling's SimpleMarker->outlineWidth
    mapping a no-op (it skips a base of 0), and the size is kept off the
    Weight x Width_cm ramp entirely by weight_scaling_skip_ids() - see the
    reasoning there.  An earlier version of this comment claimed the
    opposite; it was written before the skip hook existed.
    """
    return {
        "angle": "0",
        "cap_style": "square",
        "color": color,
        "horizontal_anchor_point": "1",
        "joinstyle": "bevel",
        "name": "circle",
        "offset": "0,0",
        "offset_map_unit_scale": MUS,
        "offset_unit": "MM",
        "outline_color": color,
        "outline_style": "solid",
        "outline_width": "0",
        "outline_width_map_unit_scale": MUS,
        "outline_width_unit": "MM",
        "scale_method": "diameter",
        "size": DOT_SIZE,
        "size_map_unit_scale": MUS,
        "size_unit": "MM",
        "vertical_anchor_point": "1",
    }


def build_ring(code, ring, expression, colour_expr, static_rgb, sym_name):
    """A GeometryGenerator wrapping a MarkerLine wrapping one dot.

    The option set on the generator is exactly the three keys
    QgsGeometryGeneratorSymbolLayer round-trips - SymbolType,
    geometryModifier, units - matching the generator already on Vein - Shear.
    """
    layer = ET.Element("layer", {
        "id": layer_id("ring%d" % ring, code), "class": "GeometryGenerator",
        "locked": "0", "pass": "0", "enabled": "1"})
    opts = ET.SubElement(layer, "Option", {"type": "Map"})
    for name, value in (("SymbolType", "Line"),
                        ("geometryModifier", expression),
                        ("units", "MM")):
        ET.SubElement(opts, "Option",
                      {"name": name, "type": "QString", "value": value})
    layer.append(empty_dd())
    # Static enabled="1" stays, so a dd evaluation failure falls back to
    # DRAWING rather than to silence.
    set_dd(layer, "enabled", RING_ON[ring])

    sym = ET.SubElement(layer, "symbol", {
        "name": sym_name, "type": "line", "alpha": "1", "clip_to_extent": "1",
        "force_rhr": "0", "frame_rate": "10", "is_animated": "0"})
    sym.append(empty_dd())
    ml = ET.SubElement(sym, "layer", {
        "id": layer_id("dots%d" % ring, code), "class": "MarkerLine",
        "locked": "0", "pass": "0", "enabled": "1"})
    ml_opts = ET.SubElement(ml, "Option", {"type": "Map"})
    for name, value in sorted(marker_line_opts(DOT_PHASE[ring]).items()):
        ET.SubElement(ml_opts, "Option",
                      {"name": name, "type": "QString", "value": value})
    ml.append(empty_dd())

    dot_sym = ET.SubElement(ml, "symbol", {
        "name": "%s@0" % sym_name, "type": "marker", "alpha": "1",
        "clip_to_extent": "1", "force_rhr": "0", "frame_rate": "10",
        "is_animated": "0"})
    dot_sym.append(empty_dd())
    dot = ET.SubElement(dot_sym, "layer", {
        "id": layer_id("dot%d" % ring, code), "class": "SimpleMarker",
        "locked": "0", "pass": "0", "enabled": "1"})
    dot_opt = ET.SubElement(dot, "Option", {"type": "Map"})
    for name, value in sorted(dot_opts(static_rgb).items()):
        ET.SubElement(dot_opt, "Option",
                      {"name": name, "type": "QString", "value": value})
    dot.append(empty_dd())
    # The static colour above is the feature's own; this overrides it per
    # feature from the recorded mineral.  Both are set, so a dd evaluation
    # failure still draws something sensible.
    set_dd(dot, "fillColor", colour_expr)
    set_dd(dot, "outlineColor", colour_expr)
    return layer


def insert_layer(sym_el, gen, above):
    """Insert a symbol layer `above` positions up from the bottom.

    NOT a plain sym_el.insert(n, ...): a <symbol> also carries a
    <data_defined_properties> child, so raw child indexes are off by one and
    an "index 1" insert lands the generator BENEATH the class fill, where it
    is drawn over and invisible.  Document order among <layer> elements is
    bottom-to-top.
    """
    first = next(i for i, c in enumerate(list(sym_el)) if c.tag == "layer")
    sym_el.insert(first + above, gen)


def rgba(value, alpha=None, scale=None):
    """Normalise a QGIS colour string to plain 'r,g,b,a'.

    Template colours come in both the bare 4-part form and the extended
    '...,rgb:0.1,0.2,0.3,1' / '...,hsv:...' form; keep only the first four
    channels so the emitted colour cannot disagree with its own hint.
    """
    parts = (value or "").split(",")
    if len(parts) < 3:
        bail("cannot read colour %r" % value)
    try:
        r, g, b = (int(parts[i]) for i in range(3))
    except ValueError:
        bail("cannot read colour %r" % value)
    if scale is not None:
        r, g, b = (max(0, min(255, int(round(c * scale)))) for c in (r, g, b))
    a = alpha if alpha is not None else (parts[3] if len(parts) > 3 else "255")
    return "%d,%d,%d,%s" % (r, g, b, a)


def backbone(sym_el, code):
    """The widest solid top-level SimpleLine - the vein's own stroke.

    Top-level only, and widest, because Vein - Laminated also carries a
    0.7pt inner line that must not win, and Vein - Shear's wave sub-symbol
    stroke is nested where findall() will not see it.
    """
    best = None
    for lyr in sym_el.findall("layer"):
        if lyr.get("class") != "SimpleLine":
            continue
        o = direct_opts(lyr)
        if "line_width" not in o or "line_color" not in o:
            continue
        if o.get("line_style") is not None and \
                o["line_style"].get("value") != "solid":
            continue
        try:
            w = float(o["line_width"].get("value"))
        except (TypeError, ValueError):
            continue
        if best is None or w > best[0]:
            best = (w, o["line_color"].get("value"))
    if best is None:
        bail("%r: no solid top-level SimpleLine to take the backbone from" % code)
    return best


def _num(v):
    return ("%.4f" % v).rstrip("0").rstrip(".") or "0"


def lw_expression(half_mm, clearance, ring):
    """One ring of the stipple: paired offset curves, both sides, paper mm.

    The offset carries the same Weight and Width_cm factors the backbone
    stroke does, so the WHITE GAP between vein edge and ring 1 stays
    constant however thick the vein is drawn.  Rings then step outward at a
    fixed spacing, which is what makes a wide selvedge visibly reach
    further into the wallrock than a narrow one.

    array_filter is not decoration: offset_curve() returns null on a
    degenerate or zero-length line, and an unguarded null inside
    collect_geometries takes down the whole symbol layer - every feature -
    not just that one.
    """
    step = LW_GAP + clearance + (ring - 1) * RING_SPACING
    off = ("(%s * (%s) * (%s) + %s)"
           % (round(half_mm, 4), WEIGHT_F, DETAIL_WIDTH_FACTOR, _num(step)))
    return ("CASE WHEN %s THEN collect_geometries(array_filter(array("
            "offset_curve($geometry, %s), offset_curve($geometry, 0 - %s)), "
            "not is_empty_or_null(@element))) ELSE NULL END"
            % (RING_ON[ring], off, off))


def bm_expression(ring):
    """One ring OUTSIDE the polygon boundary, in paper mm.

    Outward, so there is nothing to degenerate: the inward band this
    replaced collapsed on any pod narrower than twice the band, and
    difference(poly, empty) then handed back the WHOLE polygon, flooding it.
    A positive buffer always grows.  Geologically it is also the truer
    statement - a selvedge is altered wallrock, outside the vein.

    The only guard left is against a null/empty geometry, which buffer()
    would propagate.
    """
    off = BM_GAP + (ring - 1) * RING_SPACING
    return ("CASE WHEN %s AND NOT is_empty_or_null($geometry) "
            "THEN boundary(buffer($geometry, %s)) ELSE NULL END"
            % (RING_ON[ring], _num(off)))


def strip_round1(sym_el, code):
    """Remove the round-1 single solid halo/band layer, if present.

    Round 1 authored one generator per symbol under the id layer_id("gen",
    code).  This script is idempotent by uuid5 id, so without this the old
    solid halo would simply survive alongside the new rings - two different
    selvedges on the same vein.
    """
    dropped = 0
    for lyr in list(sym_el.findall("layer")):
        if lyr.get("class") != "GeometryGenerator":
            continue
        if lyr.get("id") == layer_id("gen", code):
            sym_el.remove(lyr)
            dropped += 1
    return dropped


def rings_current(sym_el, code, expr_for):
    """True if the symbol's rings say exactly what we would author now.

    Identity alone is NOT enough.  This script is idempotent by uuid5 layer
    id, so a plain "are the ring ids present?" test makes any change to a
    CONSTANT a silent no-op: edit RING_ON and re-run, and the old thresholds
    stay baked while the script cheerfully reports "already applied".  That
    is how the tier change nearly shipped as nothing at all.

    RING_ON reaches three places per ring - the data-defined `enabled`, and
    the geometryModifier's own CASE for the line and the polygon - so all
    three are compared.
    """
    for ring in RINGS:
        lyr = next((l for l in sym_el.findall("layer")
                    if l.get("id") == layer_id("ring%d" % ring, code)), None)
        if lyr is None:
            return False
        opts = direct_opts(lyr)
        if "geometryModifier" not in opts:
            return False
        if opts["geometryModifier"].get("value") != expr_for(ring):
            return False
        if get_dd(lyr, "enabled") != RING_ON[ring]:
            return False
    return True


def strip_rings(sym_el, code):
    """Drop this symbol's ring generators so they can be re-authored."""
    for lyr in list(sym_el.findall("layer")):
        if lyr.get("class") != "GeometryGenerator":
            continue
        if lyr.get("id") in {layer_id("ring%d" % r, code) for r in RINGS}:
            sym_el.remove(lyr)


def convert_linework(qml, code):
    """Returns (qml, changed).  Idempotent: matched by uuid5 id, not style."""
    cm = re.search(r'<category[^>]*value=%s[^>]*/>' % re.escape(quoteattr(code)),
                   qml)
    if not cm:
        bail("Linework category %r not found" % code)
    sym_name = re.search(r'symbol="(\d+)"', cm.group(0)).group(1)
    s, e = symbol_block(qml, sym_name)
    sym_el = ET.fromstring(qml[s:e])
    width_pt, colour = backbone(sym_el, code)

    def expr_for(ring):
        return lw_expression(width_pt * MM_PER_PT / 2.0,
                             LW_CLEARANCE.get(code, 0.0), ring)

    if rings_current(sym_el, code, expr_for):
        return qml, False

    strip_round1(sym_el, code)
    strip_rings(sym_el, code)
    own = rgba(colour, alpha="255")
    colour_expr = selvedge_colour_expr(rgb_only(own))
    n = len(sym_el.findall("layer"))
    for k, ring in enumerate(RINGS):
        gen = build_ring(code, ring, expr_for(ring), colour_expr, own,
                         "@%s@%d" % (sym_name, n + k))
        # Bottom of the stack, so the backbone and its markers draw on top -
        # the position the Vein - Shear wave already occupies.  Rings go in
        # in order, so ring 1 sits innermost in the stack as well as on the
        # map.
        insert_layer(sym_el, gen, k)
    return qml[:s] + ET.tostring(sym_el, encoding="unicode") + qml[e:], True


def convert_basemap(qml, code):
    cm = re.search(r'<category[^>]*value=%s[^>]*/>' % re.escape(quoteattr(code)),
                   qml)
    if not cm:
        bail("Basemap category %r not found" % code)
    sym_name = re.search(r'symbol="(\d+)"', cm.group(0)).group(1)
    s, e = symbol_block(qml, sym_name)
    sym_el = ET.fromstring(qml[s:e])
    if rings_current(sym_el, code, bm_expression):
        return qml, False

    strip_round1(sym_el, code)
    strip_rings(sym_el, code)
    fill = None
    for lyr in sym_el.findall("layer"):
        if lyr.get("class") == "SimpleFill":
            fill = direct_opts(lyr).get("color")
            break
    if fill is None:
        bail("%r: no SimpleFill to take the fallback dot colour from" % code)
    own = rgba(fill.get("value"), alpha="255", scale=BAND_DARKEN)
    colour_expr = selvedge_colour_expr(rgb_only(own))
    n = len(sym_el.findall("layer"))
    for k, ring in enumerate(RINGS):
        gen = build_ring(code, ring, bm_expression(ring), colour_expr, own,
                         "@%s@%d" % (sym_name, n + k))
        # Above the class fill, below the ContactType boundary line.  A
        # <symbol> also carries a <data_defined_properties> child, so this
        # index counts <layer> elements - see insert_layer().
        insert_layer(sym_el, gen, 1 + k)
    return qml[:s] + ET.tostring(sym_el, encoding="unicode") + qml[e:], True


def apply_symbology(qml, layer, codes, convert):
    rm = re.search(r'<renderer-v2\b.*?</renderer-v2>', qml, re.S)
    if not rm:
        bail("%s: renderer-v2 not found" % layer)
    renderer = rm.group(0)
    changed = []
    for code in codes:
        renderer, did = convert(renderer, code)
        if did:
            changed.append(code)
    if changed and len(changed) != len(codes):
        bail("%s: partial prior state - would change %d of %d; not writing"
             % (layer, len(changed), len(codes)))
    print("  symbology: %s"
          % ("%d selvedge generators added" % len(changed) if changed
             else "already applied (%d codes)" % len(codes)))
    return qml[:rm.start()] + renderer + qml[rm.end():], bool(changed)


# ---------------------------------------------------------------------------

def weight_scaling_skip_ids():
    """Stipple dot layer ids, for inject_weight_scaling to step over.

    The dots are a TEXTURE standing for the alteration halo, not part of the
    vein's own line weight, so they must not carry the Weight x Width_cm
    ramp: under it a Minor hairline vein's selvedge shrinks to invisible
    (x0.275) and a Major thick vein's swells into touching blobs (x3).  The
    ring OFFSET still scales - that is what keeps the stipple clear of the
    stroke - but the dot itself stays the size it was drawn.
    """
    return {layer_id("dot%d" % r, c)
            for r in RINGS
            for c in list(LW_VEIN_CODES) + list(VEIN_LITHS)}


def count_generators(qml):
    return sum(1 for l in ET.fromstring(qml).iter("layer")
               if l.get("class") == "GeometryGenerator")


def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default = os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail("gpkg not found: %s" % gpkg)
    if "_Patterns" in os.path.basename(gpkg):
        bail("that is the generated patterns template - this belongs in the "
             "live template; run inject_basemap_lith_patterns.py after")

    refuse_if_open(gpkg)
    print("backed up to %s" % back_up(repo, gpkg))

    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    have = {r[0] for r in cur.execute(
        "SELECT Code FROM BasemapCodes WHERE Type='Lithology'")}
    missing = set(VEIN_LITHS) - have
    if missing:
        bail("not Lithology codes in BasemapCodes: %s" % ", ".join(sorted(missing)))
    have = {r[0] for r in cur.execute(
        "SELECT Code FROM LineworkCodes WHERE Type='Veins'")}
    missing = set(LW_VEIN_CODES) - have
    if missing:
        bail("not Veins codes in LineworkCodes: %s" % ", ".join(sorted(missing)))

    before_gg = {}
    for layer, spec, codes, convert in (
            (LW, LW_SPEC, LW_VEIN_CODES, convert_linework),
            (BM, BM_SPEC, list(VEIN_LITHS), convert_basemap)):
        print("== %s" % layer)
        cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                    (layer,))
        row = cur.fetchone()
        if not row or not row[0]:
            bail("no styleQML for %r" % layer)
        qml = original = row[0]
        before_gg[layer] = count_generators(qml)

        qml = add_fields(cur, layer, qml, spec, gpkg)
        qml, _ = splice_label(qml, layer)
        qml, _ = apply_symbology(qml, layer, codes, convert)

        # Validate BEFORE writing: never persist a QML that no longer parses.
        try:
            ET.fromstring(qml)
        except ET.ParseError as exc:
            bail("%s: edited QML no longer parses, aborting without write: %s"
                 % (layer, exc))
        if qml != original:
            cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                        (qml, layer))
            assert cur.rowcount == 1
            print("  styleQML updated")
        else:
            print("  styleQML: no change")
    con.commit()

    # --- Round-trip validation -------------------------------------------
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])

    for layer, spec, codes, n_cats, attr in (
            (LW, LW_SPEC, LW_VEIN_CODES, 135, "Type"),
            (BM, BM_SPEC, list(VEIN_LITHS), 284, "Lithology1")):
        cols = [r[1] for r in cur.execute('PRAGMA table_info("%s")' % layer)]
        cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                    (layer,))
        root = ET.fromstring(cur.fetchone()[0])

        widgets = {f.get("name"): f.find("editWidget")
                   for f in root.find("fieldConfiguration")}
        aliases = {a.get("field"): a.get("name") for a in root.find("aliases")}
        containers = {}
        for c in root.iter("attributeEditorContainer"):
            for fld in c.findall("attributeEditorField"):
                containers[fld.get("name")] = c
        want_widget = {"generation": "ValueMap", "selvedge": "Range",
                       "mineral": "ValueRelation"}
        for field, _t, kind, alias, vis, _after in spec:
            assert field in cols, "%s: %s column missing" % (layer, field)
            ew = widgets.get(field)
            assert ew is not None and ew.get("type") == want_widget[kind], \
                (layer, field, want_widget[kind])
            assert aliases.get(field) == alias, "%s: %s alias wrong" % (layer, field)
            c = containers.get(field)
            assert c is not None and c.get("visibilityExpressionEnabled") == "1" \
                and c.get("visibilityExpression") == vis, \
                "%s: %s visibility wrong" % (layer, field)

        expr = root.find(".//labeling/settings/text-style").get("fieldName")
        token = LW_GEN_TEXT if layer == LW else BM_TAG
        assert token in expr, "%s: label tag missing" % layer
        slv = LW_SLV_TEXT if layer == LW else BM_SLV_TEXT
        assert slv in expr, "%s: selvedge label missing" % layer

        renderer = root.find(".//renderer-v2")
        assert renderer.get("type") == "categorizedSymbol", layer
        assert renderer.get("attr") == attr, (layer, renderer.get("attr"))
        assert len(renderer.find("categories")) == n_cats, \
            (layer, len(renderer.find("categories")))

        # Stack position, per symbol.  Rings sit at the bottom on Linework so
        # the backbone and its markers draw over them, and one up on Basemap
        # so they sit ON the class fill rather than under it - a generator
        # drawn under an opaque fill is invisible, and in round 1 nothing
        # else caught that.  A <symbol> also carries a
        # <data_defined_properties> child, which is why these are positions
        # among <layer> elements, not raw child indexes.
        base_pos = 0 if layer == LW else 1
        ring_id = {layer_id("ring%d" % r, c): r for c in codes for r in RINGS}
        for sym in renderer.find("symbols"):
            for pos, lyr in enumerate(sym.findall("layer")):
                r = ring_id.get(lyr.get("id"))
                if r is None:
                    continue
                want_pos = base_pos + RINGS.index(r)
                assert pos == want_pos, \
                    "%s: ring %d at stack position %d, expected %d - it " \
                    "would be drawn over" % (layer, r, pos, want_pos)

        seen = 0
        for lyr in root.iter("layer"):
            if lyr.get("class") != "GeometryGenerator":
                continue
            r = ring_id.get(lyr.get("id"))
            if r is None:
                continue
            seen += 1
            o = direct_opts(lyr)
            assert o["units"].get("value") == "MM", layer
            assert o["SymbolType"].get("value") == "Line", layer
            assert get_dd(lyr, "enabled") == RING_ON[r], \
                "%s: ring %d has the wrong dd enabled" % (layer, r)
            dots = lyr.find("symbol/layer")
            assert dots is not None and dots.get("class") == "MarkerLine", \
                "%s: ring %d is not a MarkerLine" % (layer, r)
            dot = dots.find("symbol/layer")
            assert dot is not None and dot.get("class") == "SimpleMarker", \
                "%s: ring %d has no dot" % (layer, r)
            assert "SelvedgeMineral" in (get_dd(dot, "fillColor") or ""), \
                "%s: ring %d dot is not coloured by mineral" % (layer, r)
        assert seen == len(codes) * len(RINGS), \
            (layer, seen, len(codes) * len(RINGS))
        # Round 1's single solid halo must be gone, not merely outnumbered.
        old = {layer_id("gen", c) for c in codes}
        assert not any(l.get("id") in old for l in root.iter("layer")), \
            "%s: a round-1 solid selvedge survived alongside the rings" % layer
        # Every layer must own a dd block, or inject_weight_scaling will
        # rewrite its neighbour's with the wrong statics.
        for sym in renderer.find("symbols"):
            for lyr in sym.iter("layer"):
                assert lyr.find("data_defined_properties") is not None, \
                    "%s: layer %s has no dd block" % (layer, lyr.get("id"))
        print("round-trip ok: %s - 3 fields, label tag, %d selvedge rings "
              "(%d generators total, was %d)"
              % (layer, seen, count_generators(ET.tostring(root, encoding="unicode")),
                 before_gg[layer]))

    con.close()
    print("\nNOW RUN: python scripts/inject_weight_scaling.py"
          "   (ramps the stipple dots to Weight x Width_cm)")
    print('THEN:    "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" '
          "scripts/inject_basemap_lith_patterns.py   (re-bakes the Patterns gpkg)")


if __name__ == "__main__":
    main()
