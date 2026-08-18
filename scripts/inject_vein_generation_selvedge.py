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

THE SELVEDGE IS DRAWN.  On Linework a GeometryGenerator puts a thin paired
halo either side of the vein, offset far enough to clear the widest the
backbone ever renders; on Basemap it hems the inside of the vein polygon
with a band in a deepened shade of the unit's own colour.  Both evaluate in
PAPER MILLIMETRES (units=MM honours the renderer's referenceScale), so the
ornament is the same size on the page at UG 1:100 and surface 1:10 000.

Scope is Veins-only, narrower than the sibling detail fields that
inject_linework_detail_scope.py widened onto dykes/sills and faults/shears.
That is on purpose: the form gate must match where ink can appear, and the
halo only exists on the 11 vein symbols.  Letting a mapper record a dyke's
chilled margin that renders nowhere would be worse than not offering it.

Run order matters:

    inject_linework_mineral_pcts.py   owns the Linework label this splices into
    inject_basemap_mineral_pcts.py    owns the Basemap label - MUST NOT be
                                      re-run after this script, it rewrites
                                      fieldName wholesale and would drop the
                                      vein tag (recovery chain below)
    inject_vein_generation_selvedge.py   <- this script
    inject_weight_scaling.py          MUST run after: its Linework pass
                                      recurses into sub-symbols and ramps the
                                      halo stroke to Weight x Width_cm for us.
                                      Do not author that ramp here.
    inject_basemap_lith_patterns.py   re-bakes LGS_MappingTemplate_Patterns.gpkg

If inject_basemap_mineral_pcts.py ever has to run again, replay:
    inject_basemap_mineral_pcts -> inject_confidence_system ->
    inject_label_cartography -> inject_vein_generation_selvedge ->
    inject_weight_scaling -> inject_label_size_scaling ->
    inject_basemap_lith_patterns

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
from inject_weight_scaling import DETAIL_WIDTH_FACTOR, FACTORS  # noqa: E402

LW = "2 - Linework"
BM = "4 - Basemap"
BACKUP_DATE = "2026-08-18"
BACKUP_NAME = "LGS_MappingTemplate_pre-vein-generations_%s.gpkg" % BACKUP_DATE
MUS = "3x:0,0,0,0,0,0"
MM_PER_PT = 25.4 / 72.0
ALT_OUTLINE_DASH = "1.5;0.7"   # never emit this - see line_opts()

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

# Linework: the 11 vein codes that draw as a single solid backbone.  Vein
# Set / Sheeted and Stockwork Zone Boundary are excluded - a swarm and a
# zone envelope have no two margins to hem, and their dashes encode
# identity.  Same 11 as inject_confidence_system.SOLID_CODES' vein block,
# and for the same reason.
LW_VEIN_CODES = [
    "Vein", "Vein - Breccia", "Vein - Carbonate", "Vein - Epidote",
    "Vein - Extension", "Vein - Laminated", "Vein - Mineralised",
    "Vein - Pegmatite", "Vein - Quartz", "Vein - Quartz-Carbonate",
    "Vein - Shear",
]

# Vein - Shear already wears a decorative selvage: a one-sided
# wave(offset_curve($geometry, 1.1), amplitude:=0.4) whose outer envelope
# reaches 1.1 + 0.4 + 0.28/2 = 1.64mm from the centreline, and whose offset
# is a STATIC that does not shrink with Weight or Width.  Push the halo
# outside it so the two read as two things.
LW_CLEARANCE = {"Vein - Shear": 1.40}

# Paper-mm of white between the drawn vein EDGE and the halo CENTRELINE.
# This, not the offset, is the constant of the design.
LW_GAP = ("CASE WHEN coalesce(\"Selvedge_cm\", 0) <= 2 THEN 0.34 "
          "WHEN \"Selvedge_cm\" <= 10 THEN 0.50 ELSE 0.70 END")

# Paper-mm width of the Basemap inner band.
BM_BAND = ("CASE WHEN coalesce(\"Selvedge_cm\", 0) <= 2 THEN 0.45 "
           "WHEN \"Selvedge_cm\" <= 10 THEN 0.70 ELSE 1.00 END")

WEIGHT_F = ("CASE WHEN \"Weight\" = 'Major' THEN %s "
            "WHEN \"Weight\" = 'Minor' THEN %s ELSE 1 END"
            % (FACTORS["Major"], FACTORS["Minor"]))

HALO_WIDTH_PT = "0.6"     # subordinate to the 1.46pt backbone
HALO_ALPHA = "150"
BAND_DARKEN = 0.75        # band = the unit's own fill, 25% deeper

# Pre-authored so inject_confidence_system.apply_solid() skips this stroke
# on its next run (it skips SimpleLine layers already carrying outlineStyle)
# - and because an inferred vein's inferred selvedge should dash too.
CONFIDENCE_DASH = ("CASE WHEN \"Confidence\" IN ('Inferred','Queried') "
                   "THEN 'dash' ELSE 'solid' END")

# --- Label fragments -------------------------------------------------------
# The mm/cm/m formatter is inject_linework_vein_fields.WIDTH_TEXT, re-pointed
# at Selvedge_cm.  0 reads as unrecorded, never as '0mm'.


def auto_width_text(field):
    return ("CASE WHEN coalesce(\"{f}\", 0) <= 0 THEN '' "
            "WHEN \"{f}\" >= 100 THEN round(\"{f}\"/100.0, 2) || 'm' "
            "WHEN \"{f}\" < 1 THEN round(\"{f}\"*10, 1) || 'mm' "
            "ELSE round(\"{f}\", 1) || 'cm' END".format(f=field))


def slv_text(gate):
    """'slv 3cm Bt', or '' when there is no selvedge on this feature.

    The gate is not belt-and-braces.  On Linework the selvedge sits inside
    the detail-scope branch of the label, which also covers dykes, faults
    and shears - and a stray Selvedge_cm arriving there by attribute copy
    or import would print a selvedge the symbology never draws.  A label
    must not promise ink that cannot appear.
    """
    return ("CASE WHEN NOT (%s AND %s) THEN '' ELSE 'slv' || "
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

# Basemap: sits straight after the lithology code and its Confidence '?', in
# the light span so it does not compete with the semibold unit code.  The
# span string MUST be the font-weight:400 variant - the bare
# 'font-style:italic;font-size:70%;' is what inject_label_cartography counts.
BM_ANCHOR = ('"Lithology1" || CASE WHEN "Confidence" = \'Queried\' '
             "THEN '?' ELSE '' END ||")
BM_TAG = (
    "CASE WHEN (%s) AND (coalesce(\"VeinGen\",'') != '' OR %s) THEN "
    "' <span style=\"font-style:italic;font-weight:400;font-size:70%%;\">' || "
    "array_to_string(array_remove_all(array(coalesce(\"VeinGen\",''), %s), ''), ' ') "
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
        if expr.count(BM_ANCHOR) != 1:
            bail("%s: label anchor appears %d times, expected 1 - has "
                 "inject_basemap_mineral_pcts.py or inject_confidence_system.py "
                 "been re-run since?" % (layer, expr.count(BM_ANCHOR)))
        new = expr.replace(BM_ANCHOR, "%s %s ||" % (BM_ANCHOR, BM_TAG))

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


def line_opts(color, width_pt):
    """Solid stroke.  Deliberately NOT the 1.5;0.7 custom dash - that is the
    signature inject_overlay_alteration_outline.py counts its outlines by,
    over a recursive walk that would see this sub-symbol."""
    return {
        "align_dash_pattern": "0",
        "capstyle": "round",
        "customdash": "5;2",
        "customdash_map_unit_scale": MUS,
        "customdash_unit": "MM",
        "dash_pattern_offset": "0",
        "dash_pattern_offset_map_unit_scale": MUS,
        "dash_pattern_offset_unit": "MM",
        "draw_inside_polygon": "0",
        "joinstyle": "round",
        "line_color": color,
        "line_style": "solid",
        "line_width": width_pt,
        "line_width_unit": "Point",
        "offset": "0",
        "offset_map_unit_scale": MUS,
        "offset_unit": "MM",
        "ring_filter": "0",
        "trim_distance_end": "0",
        "trim_distance_end_map_unit_scale": MUS,
        "trim_distance_end_unit": "MM",
        "trim_distance_start": "0",
        "trim_distance_start_map_unit_scale": MUS,
        "trim_distance_start_unit": "MM",
        "tweak_dash_pattern_on_corners": "0",
        "use_custom_dash": "0",
        "width_map_unit_scale": MUS,
    }


def fill_opts(color):
    """Solid fill, no outline.  outline_width 0 keeps inject_weight_scaling's
    SimpleFill->outlineWidth mapping a no-op (it skips a base of 0)."""
    return {
        "border_width_map_unit_scale": MUS,
        "color": color,
        "joinstyle": "bevel",
        "offset": "0,0",
        "offset_map_unit_scale": MUS,
        "offset_unit": "MM",
        "outline_color": color,
        "outline_style": "no",
        "outline_width": "0",
        "outline_width_unit": "MM",
        "style": "solid",
    }


def build_generator(code, expression, sub_name, sub_kind, sub_options,
                    sub_dd=None):
    """A GeometryGenerator layer wrapping a single sub-symbol layer.

    The option set is exactly the three keys QgsGeometryGeneratorSymbolLayer
    round-trips - SymbolType, geometryModifier, units - matching the
    generator already on Vein - Shear.
    """
    sym_type = "Line" if sub_kind == "SimpleLine" else "Fill"
    layer = ET.Element("layer", {
        "id": layer_id("gen", code), "class": "GeometryGenerator",
        "locked": "0", "pass": "0", "enabled": "1"})
    opts = ET.SubElement(layer, "Option", {"type": "Map"})
    for name, value in (("SymbolType", sym_type),
                        ("geometryModifier", expression),
                        ("units", "MM")):
        ET.SubElement(opts, "Option",
                      {"name": name, "type": "QString", "value": value})
    layer.append(empty_dd())
    # Static enabled="1" stays, so a dd evaluation failure falls back to
    # DRAWING rather than to silence.
    set_dd(layer, "enabled", SELVEDGE_ON)

    sym = ET.SubElement(layer, "symbol", {
        "name": sub_name, "type": sym_type.lower(), "alpha": "1",
        "clip_to_extent": "1", "force_rhr": "0", "frame_rate": "10",
        "is_animated": "0"})
    sym.append(empty_dd())
    sub = ET.SubElement(sym, "layer", {
        "id": layer_id("stroke", code), "class": sub_kind,
        "locked": "0", "pass": "0", "enabled": "1"})
    sub_opts = ET.SubElement(sub, "Option", {"type": "Map"})
    for name, value in sorted(sub_options.items()):
        ET.SubElement(sub_opts, "Option",
                      {"name": name, "type": "QString", "value": value})
    # No Weight ramp here on purpose: inject_weight_scaling.py rebuilds
    # outlineWidth from the current static line_width and would overwrite
    # anything authored here.  Run it after this script.
    sub.append(empty_dd())
    if sub_dd:
        for key, expr in sub_dd.items():
            set_dd(sub, key, expr)
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


def lw_expression(half_mm, clearance):
    """Paired offset curves, both sides, in paper mm.

    The offset carries the same Weight and Width_cm factors the backbone
    stroke does, so the WHITE GAP between vein edge and halo is the
    constant, not the offset.

    array_filter is not decoration: offset_curve() returns null on a
    degenerate or zero-length line, and an unguarded null inside
    collect_geometries takes down the whole symbol layer - every feature -
    not just that one.
    """
    off = ("(%s * (%s) * (%s) + (%s) + %s)"
           % (round(half_mm, 4), WEIGHT_F, DETAIL_WIDTH_FACTOR, LW_GAP,
              _num(clearance)))
    return ("CASE WHEN %s THEN collect_geometries(array_filter(array("
            "offset_curve($geometry, %s), offset_curve($geometry, 0 - %s)), "
            "not is_empty_or_null(@element))) ELSE NULL END"
            % (SELVEDGE_ON, off, off))


def bm_expression():
    """A band hemming the inside of the polygon edge, in paper mm.

    buffer(poly, -d) on a polygon narrower than 2d returns EMPTY, and
    difference(poly, empty) returns the WHOLE polygon - so without the
    guard every small vein pod would flood solid in the band colour.  The
    area test kills the near-degenerate case where a sliver of core
    survives and the 'band' is almost the whole shape.  Both return NULL,
    which draws nothing: a polygon too small to carry a band should not
    pretend to.
    """
    return ("CASE WHEN %s THEN with_variable('core', "
            "buffer($geometry, 0 - (%s)), "
            "CASE WHEN is_empty_or_null(@core) OR area(@core) < 0.5 THEN NULL "
            "ELSE difference($geometry, @core) END) ELSE NULL END"
            % (SELVEDGE_ON, BM_BAND))


def _num(v):
    return ("%.4f" % v).rstrip("0").rstrip(".") or "0"


def convert_linework(qml, code):
    """Returns (qml, changed).  Idempotent: matched by uuid5 id, not style."""
    cm = re.search(r'<category[^>]*value=%s[^>]*/>' % re.escape(quoteattr(code)),
                   qml)
    if not cm:
        bail("Linework category %r not found" % code)
    sym_name = re.search(r'symbol="(\d+)"', cm.group(0)).group(1)
    s, e = symbol_block(qml, sym_name)
    sym_el = ET.fromstring(qml[s:e])
    if layer_id("gen", code) in {l.get("id") for l in sym_el.findall("layer")}:
        return qml, False

    width_pt, colour = backbone(sym_el, code)
    gen = build_generator(
        code,
        lw_expression(width_pt * MM_PER_PT / 2.0, LW_CLEARANCE.get(code, 0.0)),
        "@%s@%d" % (sym_name, len(sym_el.findall("layer"))),
        "SimpleLine",
        line_opts(rgba(colour, alpha=HALO_ALPHA), HALO_WIDTH_PT),
        sub_dd={"outlineStyle": CONFIDENCE_DASH},
    )
    # Bottom of the stack, so the backbone and its markers draw on top -
    # the position the Vein - Shear wave already occupies.
    insert_layer(sym_el, gen, 0)
    return qml[:s] + ET.tostring(sym_el, encoding="unicode") + qml[e:], True


def convert_basemap(qml, code):
    cm = re.search(r'<category[^>]*value=%s[^>]*/>' % re.escape(quoteattr(code)),
                   qml)
    if not cm:
        bail("Basemap category %r not found" % code)
    sym_name = re.search(r'symbol="(\d+)"', cm.group(0)).group(1)
    s, e = symbol_block(qml, sym_name)
    sym_el = ET.fromstring(qml[s:e])
    if layer_id("gen", code) in {l.get("id") for l in sym_el.findall("layer")}:
        return qml, False

    fill = None
    for lyr in sym_el.findall("layer"):
        if lyr.get("class") == "SimpleFill":
            fill = direct_opts(lyr).get("color")
            break
    if fill is None:
        bail("%r: no SimpleFill to take the band colour from" % code)

    gen = build_generator(
        code, bm_expression(),
        "@%s@%d" % (sym_name, len(sym_el.findall("layer"))),
        "SimpleFill",
        fill_opts(rgba(fill.get("value"), alpha="255", scale=BAND_DARKEN)),
    )
    # Above the class fill, below the ContactType boundary line.
    insert_layer(sym_el, gen, 1)
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
            (LW, LW_SPEC, LW_VEIN_CODES, 137, "Type"),
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

        # Stack position, per symbol: bottom on Linework so the backbone
        # draws over the halo, one up on Basemap so the band sits ON the
        # class fill rather than under it.  A generator drawn under an
        # opaque fill is invisible and nothing else would catch it.
        want_pos = 0 if layer == LW else 1
        ids = {layer_id("gen", c) for c in codes}
        for sym in renderer.find("symbols"):
            layers = sym.findall("layer")
            for pos, lyr in enumerate(layers):
                if lyr.get("id") in ids:
                    assert pos == want_pos,                         "%s: selvedge generator at stack position %d, "                         "expected %d - it would be drawn over"                         % (layer, pos, want_pos)

        seen = 0
        for lyr in root.iter("layer"):
            if lyr.get("class") != "GeometryGenerator":
                continue
            if lyr.get("id") not in ids:
                continue
            seen += 1
            o = direct_opts(lyr)
            assert o["units"].get("value") == "MM", layer
            assert o["SymbolType"].get("value") == (
                "Line" if layer == LW else "Fill"), layer
            assert get_dd(lyr, "enabled") == SELVEDGE_ON, \
                "%s: generator has no dd enabled" % layer
        assert seen == len(codes), (layer, seen, len(codes))
        # Every layer must own a dd block, or inject_weight_scaling will
        # rewrite its neighbour's with the wrong statics.
        for sym in renderer.find("symbols"):
            for lyr in sym.iter("layer"):
                assert lyr.find("data_defined_properties") is not None, \
                    "%s: layer %s has no dd block" % (layer, lyr.get("id"))
        print("round-trip ok: %s - 3 fields, label tag, %d selvedge generators "
              "(%d generators total, was %d)"
              % (layer, seen, count_generators(ET.tostring(root, encoding="unicode")),
                 before_gg[layer]))

    con.close()
    print("\nNOW RUN: python scripts/inject_weight_scaling.py"
          "   (ramps the halo stroke to Weight x Width_cm)")
    print('THEN:    "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" '
          "scripts/inject_basemap_lith_patterns.py   (re-bakes the Patterns gpkg)")


if __name__ == "__main__":
    main()
