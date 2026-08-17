"""Overlay 'Mineralisation' zone system (UG paper-mapping parity).

Expert underground mapping constantly outlines mineralisation-style
zones - "galena zone (7%)", "semi-massive galena zone", "zone of
stringers to clustered galena", "VcZ 3-5%", "Ba barren".  This adds a
fifth Overlay category with seven STYLE codes; the mineral species and
percentage are attributes, so one code list covers galena, barite,
pyrite, anything:

    Massive Sulphide Zone . Semi-Massive Sulphide Zone . Stringer Zone
    Disseminated Zone . Blebby Zone . Vein Zone . Barren Zone

New fields on '3 - Overlay' (Mineralisation form container only):
    Mineral1  TEXT  ValueRelation -> MineralCodes
    Percent   MEDIUMINT 0-100

Symbology stays in the house wash language (translucent, self-coloured,
light borders) with two data-defined behaviours:

    - COLOUR follows Mineral1 (paper convention): Gn blue, Brt purple,
      Hem red, Py/Ccp gold, Mag dark grey, Sp brown, anything else /
      unset renders neutral blue-grey.
    - DENSITY follows Percent in 5 steps (stipple spacing and hatch
      spacing; ore-scale breaks <2 / 2-5 / 5-10 / 10-20 / >=20,
      NULL = middle step).

Symbols are cloned from house sources: the alteration stipple stack
(SimpleFill wash + PointPatternFill + outline) for Disseminated /
Blebby / Semi-Massive, wash-only for Massive / Barren, and the
strike-rotated zone hatch (Shear Zone) for Vein / Stringer - the
OverlayStrike lineAngle dd is preserved.  Weight dd from the zone
clone is stripped (Weight stays Structure-scoped).

Table + QML renderer + SLD are kept in lockstep (audit precedent).
Label expression gains a Mineralisation branch: 'Stringer Zone Gn 12%'.

NOTE for inject_weight_scaling.py: its Overlay passes select codes by
Type (Alteration/Weathering) or the OVERLAY_ZONE_CODES list, so these
symbols are deliberately untouched by it.

Idempotent and re-runnable: each edit group must be 0 or its full
count; styles are parse-validated BEFORE anything is written.

Usage:  python scripts/inject_overlay_mineralisation.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

LAYER = "3 - Overlay"
CAT_TABLE = "OverlayCategories"
CODE_TABLE = "OverlayCodes"
NEW_TYPE = "Mineralisation"

FIRST_FID = 152      # current max(fid) in OverlayCodes = 151
FIRST_SYMBOL = 152   # current max renderer symbol name = 151
CAT_FID = 5          # OverlayCategories has fids 1-4

# style code -> (build kind, params)
#   stipple: (marker_size_pt, dist_x, dist_y, wash_alpha)
#   wash:    (wash_alpha, border_dashed)
#   hatch:   (hatch_dashed,)
NEW_CODES = [
    ("Massive Sulphide Zone", "wash", (110, False)),
    ("Semi-Massive Sulphide Zone", "stipple", (2.2, 4.2, 5.8, 60)),
    ("Stringer Zone", "hatch", (True,)),
    ("Disseminated Zone", "stipple", (1.4, 6.3, 8.6, 28)),
    ("Blebby Zone", "stipple", (2.6, 9.5, 12.5, 28)),
    ("Vein Zone", "hatch", (False,)),
    ("Barren Zone", "wash", (14, True)),
]

STIPPLE_SOURCE = "Hem"       # SimpleFill + PointPatternFill + SimpleLine
HATCH_SOURCE = "Shear Zone"  # LinePatternFill(+sub line) + SimpleLine border
HATCH_BASE_DISTANCE = "8"    # Point (Shear Zone authored value)

MINERAL_RGB = [
    ("Gn", "43,95,158"),     # galena - blue
    ("Brt", "126,87,194"),   # barite - purple
    ("Hem", "198,57,57"),    # hematite - red
    ("Py", "212,160,23"),    # pyrite - gold
    ("Ccp", "217,142,31"),   # chalcopyrite - gold-orange
    ("Mag", "70,70,75"),     # magnetite - dark grey
    ("Sp", "121,85,61"),     # sphalerite - brown
]
DEFAULT_RGB = "96,110,125"   # neutral blue-grey (unset / other minerals)

# 0 counts as UNRECORDED (middle step), not as "0%": coalesce(...) <= 0
# rather than IS NULL, so a stray 0 cannot render the sparsest stipple tier
# (same guard as inject_weight_scaling.DETAIL_WIDTH_FACTOR).
PCT_FACTOR = ("CASE WHEN coalesce(\"Percent\", 0) <= 0 THEN 1 "
              "WHEN \"Percent\" < 2 THEN 1.732 "
              "WHEN \"Percent\" < 5 THEN 1.225 "
              "WHEN \"Percent\" < 10 THEN 1 "
              "WHEN \"Percent\" < 20 THEN 0.866 "
              "ELSE 0.775 END")

OLD_LABEL_TAIL = " ELSE concat("
NEW_LABEL_BRANCH = (
    "WHEN \"Type\" = 'Mineralisation' THEN \"SubType1\" || "
    "coalesce(' ' || nullif(\"Mineral1\",''), '') || "
    "CASE WHEN coalesce(\"Percent\", 0) > 0 THEN ' ' || \"Percent\" || '%' "
    "ELSE '' END")
# The same branch before the zero guard - recognised only so a re-run does
# not inject a duplicate on a template that predates
# inject_zero_value_guards.py.
LEGACY_LABEL_BRANCH = NEW_LABEL_BRANCH.replace(
    "coalesce(\"Percent\", 0) > 0", "\"Percent\" IS NOT NULL")

# field, sql type, kind, alias
FIELD_SPEC = [
    ("Mineral1", "TEXT(100)", "mineral", "Mineral"),
    ("Percent", "MEDIUMINT", "percent", "Percent"),
]


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def mineral_color_expr(alpha):
    branches = " ".join(
        "WHEN \"Mineral1\" = '%s' THEN color_rgba(%s,%d)" % (code, rgb, alpha)
        for code, rgb in MINERAL_RGB)
    return "CASE %s ELSE color_rgba(%s,%d) END" % (branches, DEFAULT_RGB, alpha)


def density_expr(base):
    return "%s * %s" % (base, PCT_FACTOR)


def table_uuid(code):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "lgs-minz-row:" + code))


def category_uuid(code):
    return "{%s}" % uuid.uuid5(uuid.NAMESPACE_URL, "lgs-minz-cat:" + code)


def layer_id(code, index):
    return "{%s}" % uuid.uuid5(uuid.NAMESPACE_URL,
                               f"lgs-minz-layer:{code}:{index}")


# ---------------------------------------------------------------- XML helpers
def symbol_block(q, name):
    m = re.search(r'<symbol\b[^>]*\bname="%s"[^>]*>' % re.escape(name), q)
    if not m:
        bail(f"symbol {name!r} not found")
    depth = 0
    for t in re.finditer(r'<symbol\b|</symbol>', q[m.start():]):
        depth += 1 if t.group(0) == '<symbol' else -1
        if depth == 0:
            return m.start(), m.start() + t.end()
    bail(f"unbalanced symbol {name!r}")


def symbol_for_value(qml, value):
    cm = re.search(r'<category[^>]*value="%s"[^>]*/>' % re.escape(value), qml)
    if not cm:
        bail(f"Overlay category {value!r} not found")
    return re.search(r'symbol="(\d+)"', cm.group(0)).group(1)


def direct_opts(el):
    cont = el.find("Option")
    if cont is None:
        return {}
    return {o.get("name"): o for o in cont.findall("Option")}


def set_static(layer_el, name, value):
    opts = direct_opts(layer_el)
    if name in opts:
        opts[name].set("value", value)
        opts[name].set("type", "QString")
    else:
        cont = layer_el.find("Option")
        ET.SubElement(cont, "Option",
                      {"name": name, "type": "QString", "value": value})


def set_dd(layer_el, props):
    """Replace the layer's data_defined_properties with exactly `props`."""
    dd = layer_el.find("data_defined_properties")
    if dd is None:
        bail("layer without data_defined_properties")
    for child in list(dd):
        dd.remove(child)
    outer = ET.SubElement(dd, "Option", {"type": "Map"})
    ET.SubElement(outer, "Option", {"name": "name", "type": "QString", "value": ""})
    if props:
        pr = ET.SubElement(outer, "Option", {"name": "properties", "type": "Map"})
        for key, expr in props.items():
            entry = ET.SubElement(pr, "Option", {"name": key, "type": "Map"})
            ET.SubElement(entry, "Option",
                          {"name": "active", "type": "bool", "value": "true"})
            ET.SubElement(entry, "Option",
                          {"name": "expression", "type": "QString", "value": expr})
            ET.SubElement(entry, "Option",
                          {"name": "type", "type": "int", "value": "3"})
    else:
        ET.SubElement(outer, "Option", {"name": "properties"})
    ET.SubElement(outer, "Option",
                  {"name": "type", "type": "QString", "value": "collection"})


def merge_dd(layer_el, props, keep=()):
    """Like set_dd but preserves the named existing properties."""
    kept = {}
    dd = layer_el.find("data_defined_properties")
    if dd is not None:
        for opt in dd.iter("Option"):
            if opt.get("name") in keep and opt.get("type") == "Map":
                sub = {o.get("name"): o.get("value") for o in opt.findall("Option")}
                if "expression" in sub:
                    kept[opt.get("name")] = sub["expression"]
    merged = dict(kept)
    merged.update(props)
    set_dd(layer_el, merged)


def rename_subsymbols(sym_el, old_name, new_name):
    for sub in sym_el.iter("symbol"):
        n = sub.get("name")
        if n and n.startswith("@%s@" % old_name):
            sub.set("name", "@%s@%s" % (new_name, n.split("@")[-1]))


def fresh_layer_ids(sym_el, code):
    for i, lyr in enumerate(sym_el.iter("layer")):
        lyr.set("id", layer_id(code, i))


# ---------------------------------------------------------------- builders
def build_stipple(renderer, new_name, code, marker_size, dx, dy, wash_alpha):
    s, e = symbol_block(renderer, symbol_for_value(renderer, STIPPLE_SOURCE))
    sym = ET.fromstring(renderer[s:e])
    old_name = sym.get("name")
    sym.set("name", new_name)
    layers = sym.findall("layer")
    classes = [l.get("class") for l in layers]
    if classes != ["SimpleFill", "PointPatternFill", "SimpleLine"]:
        bail(f"{STIPPLE_SOURCE!r}: unexpected stack {classes}")
    fill, stipple, outline = layers
    set_static(fill, "color", "%s,%d" % (DEFAULT_RGB, wash_alpha))
    set_static(fill, "outline_color", "%s,255" % DEFAULT_RGB)
    set_dd(fill, {"fillColor": mineral_color_expr(wash_alpha)})
    set_static(stipple, "distance_x", str(dx))
    set_static(stipple, "distance_y", str(dy))
    set_dd(stipple, {"distanceX": density_expr(dx),
                     "distanceY": density_expr(dy)})
    marker = stipple.find("symbol/layer")
    if marker is None or marker.get("class") != "SimpleMarker":
        bail(f"{STIPPLE_SOURCE!r}: stipple marker not found")
    set_static(marker, "name", "circle")
    set_static(marker, "size", str(marker_size))
    set_static(marker, "color", "%s,255" % DEFAULT_RGB)
    set_dd(marker, {"fillColor": mineral_color_expr(255)})
    set_static(outline, "line_color", "%s,255" % DEFAULT_RGB)
    set_dd(outline, {"outlineColor": mineral_color_expr(255)})
    rename_subsymbols(sym, old_name, new_name)
    fresh_layer_ids(sym, code)
    return ET.tostring(sym, encoding="unicode")


def build_wash(renderer, new_name, code, wash_alpha, border_dashed):
    s, e = symbol_block(renderer, symbol_for_value(renderer, STIPPLE_SOURCE))
    sym = ET.fromstring(renderer[s:e])
    old_name = sym.get("name")
    sym.set("name", new_name)
    layers = sym.findall("layer")
    if [l.get("class") for l in layers] != ["SimpleFill", "PointPatternFill",
                                            "SimpleLine"]:
        bail(f"{STIPPLE_SOURCE!r}: unexpected stack for wash build")
    fill, stipple, outline = layers
    sym.remove(stipple)
    set_static(fill, "color", "%s,%d" % (DEFAULT_RGB, wash_alpha))
    set_static(fill, "outline_color", "%s,255" % DEFAULT_RGB)
    set_dd(fill, {"fillColor": mineral_color_expr(wash_alpha)})
    set_static(outline, "line_color", "%s,255" % DEFAULT_RGB)
    if border_dashed:
        set_static(outline, "use_custom_dash", "1")
        set_static(outline, "customdash", "1.5;0.7")
        set_static(outline, "customdash_unit", "MM")
    else:
        set_static(outline, "use_custom_dash", "0")
        set_static(outline, "line_style", "solid")
    set_dd(outline, {"outlineColor": mineral_color_expr(255)})
    rename_subsymbols(sym, old_name, new_name)
    fresh_layer_ids(sym, code)
    return ET.tostring(sym, encoding="unicode")


def build_hatch(renderer, new_name, code, hatch_dashed):
    s, e = symbol_block(renderer, symbol_for_value(renderer, HATCH_SOURCE))
    sym = ET.fromstring(renderer[s:e])
    old_name = sym.get("name")
    sym.set("name", new_name)
    layers = sym.findall("layer")
    if [l.get("class") for l in layers] != ["LinePatternFill", "SimpleLine"]:
        bail(f"{HATCH_SOURCE!r}: unexpected stack "
             f"{[l.get('class') for l in layers]}")
    hatch, border = layers
    set_static(hatch, "color", "%s,255" % DEFAULT_RGB)
    # keep the OverlayStrike lineAngle dd, add Percent-driven spacing
    merge_dd(hatch, {"lineDistance": density_expr(HATCH_BASE_DISTANCE)},
             keep=("lineAngle",))
    hline = hatch.find("symbol/layer")
    if hline is None or hline.get("class") != "SimpleLine":
        bail(f"{HATCH_SOURCE!r}: hatch sub-line not found")
    set_static(hline, "line_color", "%s,255" % DEFAULT_RGB)
    if hatch_dashed:
        set_static(hline, "use_custom_dash", "1")
        set_static(hline, "customdash", "5;3.5")
        set_static(hline, "customdash_unit", "Point")
    # replace the zone Weight dd with mineral colour only
    set_dd(hline, {"outlineColor": mineral_color_expr(255)})
    set_static(border, "line_color", "%s,255" % DEFAULT_RGB)
    set_dd(border, {"outlineColor": mineral_color_expr(255)})
    rename_subsymbols(sym, old_name, new_name)
    fresh_layer_ids(sym, code)
    return ET.tostring(sym, encoding="unicode")


BUILDERS = {"stipple": build_stipple, "wash": build_wash, "hatch": build_hatch}


# ---------------------------------------------------------------- widgets/form
def opt(parent, name, otype=None, value=None):
    e = ET.SubElement(parent, "Option")
    e.set("name", name)
    if otype is not None:
        e.set("type", otype)
    if value is not None:
        e.set("value", value)
    return e


def mineral_widget(field, gpkg_path):
    root = ET.Element("field")
    root.set("name", field)
    root.set("configurationFlags", "NoFlag")
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
    opt(m, "Key", "QString", "Value")
    opt(m, "LayerName", "QString", "MineralCodes")
    opt(m, "LayerProviderName", "QString", "ogr")
    opt(m, "LayerSource", "QString",
        gpkg_path.replace("\\", "/") + "|layername=MineralCodes")
    opt(m, "NofColumns", "int", "1")
    opt(m, "OrderByValue", "bool", "true")
    opt(m, "UseCompleter", "bool", "false")
    opt(m, "Value", "QString", "Description")
    return ET.tostring(root, encoding="unicode")


def percent_widget(field):
    root = ET.Element("field")
    root.set("name", field)
    root.set("configurationFlags", "NoFlag")
    ew = ET.SubElement(root, "editWidget")
    ew.set("type", "Range")
    cfg = ET.SubElement(ew, "config")
    m = ET.SubElement(cfg, "Option")
    m.set("type", "Map")
    opt(m, "AllowNull", "bool", "true")
    opt(m, "Max", "int", "100")
    opt(m, "Min", "int", "0")
    opt(m, "Precision", "int", "0")
    opt(m, "Step", "int", "1")
    opt(m, "Style", "QString", "SpinBox")
    return ET.tostring(root, encoding="unicode")


def insert_before(qml, closing_tag, fragment):
    i = qml.find(closing_tag)
    if i < 0 or qml.find(closing_tag, i + 1) >= 0:
        bail(f"{closing_tag!r} not found or not unique")
    return qml[:i] + fragment + qml[i:]


def form_container(indexes):
    vis = "\"Type\" = '%s'\r\n" % NEW_TYPE
    c = ET.Element("attributeEditorContainer")
    for k, v in [("name", NEW_TYPE), ("type", "GroupBox"), ("collapsed", "0"),
                 ("collapsedExpression", ""), ("horizontalStretch", "0"),
                 ("groupBox", "1"), ("showLabel", "1"),
                 ("verticalStretch", "0"), ("columnCount", "1"),
                 ("collapsedExpressionEnabled", "0"),
                 ("visibilityExpressionEnabled", "1"),
                 ("visibilityExpression", vis)]:
        c.set(k, v)
    for fname in ("SubType1", "Mineral1", "Percent", "OverlayStrike",
                  "Comments"):
        f = ET.SubElement(c, "attributeEditorField")
        for k, v in [("name", fname), ("index", str(indexes[fname])),
                     ("horizontalStretch", "0"), ("showLabel", "1"),
                     ("verticalStretch", "0")]:
            f.set(k, v)
    return ET.tostring(c, encoding="unicode")


# ---------------------------------------------------------------- SLD
def sld_rule_for(sld, code):
    needle = f"<ogc:Literal>{escape(code)}</ogc:Literal>"
    for m in re.finditer(r'<se:Rule>.*?</se:Rule>', sld, re.S):
        if needle in m.group(0):
            return m
    return None


def clone_sld_rule(sld, source_code, code):
    m = sld_rule_for(sld, source_code)
    if m is None:
        bail(f"SLD rule for {source_code!r} not found")
    rule = m.group(0)
    xml_code = escape(code)
    rule = re.sub(r'<se:Name>.*?</se:Name>',
                  f'<se:Name>{xml_code}</se:Name>', rule, count=1, flags=re.S)
    rule = re.sub(r'<se:Title>.*?</se:Title>',
                  f'<se:Title>{xml_code}</se:Title>', rule, count=1, flags=re.S)
    rule = rule.replace(f"<ogc:Literal>{escape(source_code)}</ogc:Literal>",
                        f"<ogc:Literal>{xml_code}</ogc:Literal>")
    rule = re.sub(r'(<se:SvgParameter name="(?:fill|stroke)">)#[0-9a-fA-F]{6}'
                  r'(</se:SvgParameter>)',
                  r'\g<1>#606e7d\g<2>', rule)
    return rule


# ---------------------------------------------------------------- main
def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    # ---------------- table state + guards ----------------------------
    cat_exists = cur.execute(
        f"SELECT COUNT(*) FROM {CAT_TABLE} WHERE Type=?", (NEW_TYPE,)
    ).fetchone()[0]
    existing = {c for (c,) in cur.execute(
        f"SELECT Code FROM {CODE_TABLE} WHERE Code IN (%s)"
        % ",".join("?" * len(NEW_CODES)), [c[0] for c in NEW_CODES])}
    if existing and len(existing) != len(NEW_CODES):
        bail(f"partial code state: {sorted(existing)}")
    inserts_needed = not existing
    cat_needed = cat_exists == 0

    # ---------------- columns -----------------------------------------
    cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{LAYER}")')]
    for f, sqltype, *_ in FIELD_SPEC:
        if f in cols:
            print(f"column {f}: already present")
        else:
            cur.execute(f'ALTER TABLE "{LAYER}" ADD COLUMN "{f}" {sqltype}')
            print(f"column {f}: added ({sqltype})")
    con.commit()
    cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{LAYER}")')]
    qgis_cols = [c for c in cols if c != "geom"]
    qgis_index = {c: qgis_cols.index(c) for c in qgis_cols}

    # ---------------- styles ------------------------------------------
    row = cur.execute(
        "SELECT styleQML, styleSLD FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()
    if not row or not row[0] or not row[1]:
        bail(f"styleQML/styleSLD missing for {LAYER!r}")
    qml, sld = row
    original_qml, original_sld = qml, sld

    # 1. Label expression branch.
    m = re.search(r'<labeling type="simple">.*?</labeling>', qml, re.S)
    if not m:
        bail("simple <labeling> block not found")
    lab = ET.fromstring(m.group(0))
    ts = lab.find(".//text-style")
    label = ts.get("fieldName")
    if NEW_LABEL_BRANCH in label or LEGACY_LABEL_BRANCH in label:
        # LEGACY_ = the pre-zero-guard wording.  Matching it too keeps this
        # script idempotent against a template that has not yet been run
        # through inject_zero_value_guards.py; without it a re-run would
        # inject a SECOND Mineralisation branch.
        print("label: Mineralisation branch already present")
    else:
        if label.count(OLD_LABEL_TAIL) != 1:
            bail("label expression shape unexpected (ELSE concat not unique)")
        ts.set("fieldName",
               label.replace(OLD_LABEL_TAIL,
                             " " + NEW_LABEL_BRANCH + OLD_LABEL_TAIL))
        qml = qml[:m.start()] + ET.tostring(lab, encoding="unicode") + qml[m.end():]
        print("label: Mineralisation branch injected")

    # 2. Field widget config.
    for field, _sqltype, kind, alias in FIELD_SPEC:
        if f'<field name="{field}" configurationFlags' in qml:
            print(f"{field}: config already present")
            continue
        idx = qgis_index[field]
        widget = (mineral_widget(field, gpkg) if kind == "mineral"
                  else percent_widget(field))
        qml = insert_before(qml, "</fieldConfiguration>", widget)
        qml = insert_before(qml, "</aliases>",
                            f'<alias name="{alias}" index="{idx}" field="{field}"/>')
        qml = insert_before(qml, "</splitPolicies>",
                            f'<policy policy="Duplicate" field="{field}"/>')
        qml = insert_before(qml, "</duplicatePolicies>",
                            f'<policy policy="Duplicate" field="{field}"/>')
        qml = insert_before(qml, "</defaults>",
                            f'<default expression="" applyOnUpdate="0" field="{field}"/>')
        qml = insert_before(qml, "</constraints>",
                            f'<constraint constraints="0" notnull_strength="0" '
                            f'field="{field}" unique_strength="0" exp_strength="0"/>')
        qml = insert_before(qml, "</constraintExpressions>",
                            f'<constraint desc="" field="{field}" exp=""/>')
        qml = insert_before(qml, "</columns>",
                            f'<column name="{field}" type="field" hidden="0" width="-1"/>')
        qml = insert_before(qml, "</editable>",
                            f'<field name="{field}" editable="1"/>')
        qml = insert_before(qml, "</labelOnTop>",
                            f'<field name="{field}" labelOnTop="0"/>')
        qml = insert_before(qml, "</reuseLastValue>",
                            f'<field reuseLastValue="0" name="{field}"/>')
        print(f"{field}: config injected")

    # 3. Form container after Weathering.
    if f'<attributeEditorContainer name="{NEW_TYPE}"' in qml:
        print("form container: already present")
    else:
        anchor = re.search(
            r'<attributeEditorContainer[^>]*name="Weathering".*?'
            r'</attributeEditorContainer>', qml, re.S)
        if not anchor:
            bail("Weathering form container not found")
        qml = (qml[:anchor.end()] + form_container(qgis_index)
               + qml[anchor.end():])
        print("form container: injected")

    # 4. Renderer categories + symbols.
    rm = re.search(r'<renderer-v2\b.*?</renderer-v2>', qml, re.S)
    if not rm:
        bail("renderer-v2 block not found")
    renderer = rm.group(0)
    present = [c for c, *_ in NEW_CODES if f'value="{c}"' in renderer]
    if present and len(present) != len(NEW_CODES):
        bail(f"partial category state: {present}")
    cats_needed = not present
    if cats_needed:
        cat_lines = []
        sym_blocks = []
        for i, (code, kind, params) in enumerate(NEW_CODES):
            name = str(FIRST_SYMBOL + i)
            cat_lines.append(
                '<category render="true" type="string" label="%s" '
                'value="%s" uuid="%s" symbol="%s"/>'
                % (escape(code, {'"': "&quot;"}), escape(code, {'"': "&quot;"}),
                   category_uuid(code), name))
            sym_blocks.append(BUILDERS[kind](renderer, name, code, *params))
            print(f"{code}: category + symbol {name} ({kind})")
        close_cats = renderer.index("</categories>")
        renderer = (renderer[:close_cats] + "".join(cat_lines)
                    + renderer[close_cats:])
        close_syms = renderer.index("</symbols>")
        renderer = (renderer[:close_syms] + "".join(sym_blocks)
                    + renderer[close_syms:])
    else:
        print("renderer: categories already present")
    qml = qml[:rm.start()] + renderer + qml[rm.end():]

    # 5. SLD rules.
    sld_present = [c for c, *_ in NEW_CODES if sld_rule_for(sld, c)]
    if sld_present and len(sld_present) != len(NEW_CODES):
        bail(f"partial SLD state: {sld_present}")
    sld_needed = not sld_present
    if sld_needed:
        rules = [clone_sld_rule(sld, HATCH_SOURCE, code)
                 for code, _k, _p in NEW_CODES]
        close_fts = sld.index("</se:FeatureTypeStyle>")
        sld = sld[:close_fts] + "".join(rules) + sld[close_fts:]
        print(f"SLD: {len(rules)} rules appended")
    else:
        print("SLD: rules already present")

    # ---------------- consistency + write -----------------------------
    if len({inserts_needed, cats_needed, sld_needed}) != 1:
        bail("insert state differs between table/QML/SLD")
    try:
        ET.fromstring(qml)
        ET.fromstring(sld)
    except ET.ParseError as exc:
        bail(f"edited style no longer parses, aborting without write: {exc}")

    if cat_needed:
        cur.execute(f"INSERT INTO {CAT_TABLE} (fid, Type, Description, UUID) "
                    "VALUES (?,?,?,?)",
                    (CAT_FID, NEW_TYPE, NEW_TYPE,
                     table_uuid("category:" + NEW_TYPE)))
        print(f"{CAT_TABLE}: {NEW_TYPE} added")
    if inserts_needed:
        for i, (code, _k, _p) in enumerate(NEW_CODES):
            cur.execute(f"INSERT INTO {CODE_TABLE} "
                        "(fid, Type, Code, Description, UUID) VALUES (?,?,?,?,?)",
                        (FIRST_FID + i, NEW_TYPE, code, code, table_uuid(code)))
        print(f"{CODE_TABLE}: {len(NEW_CODES)} codes added")
    if qml != original_qml or sld != original_sld:
        cur.execute("UPDATE layer_styles SET styleQML=?, styleSLD=? "
                    "WHERE f_table_name=?", (qml, sld, LAYER))
        assert cur.rowcount == 1
    con.commit()
    print("styles written" if (qml != original_qml or sld != original_sld)
          else "styles: no change")

    # ---------------- validation --------------------------------------
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    assert cur.execute(f"SELECT COUNT(*) FROM {CAT_TABLE}").fetchone()[0] == 5
    assert cur.execute(
        f"SELECT COUNT(*) FROM {CODE_TABLE} WHERE Type=?", (NEW_TYPE,)
    ).fetchone()[0] == len(NEW_CODES)
    final_qml, final_sld = cur.execute(
        "SELECT styleQML, styleSLD FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()
    root = ET.fromstring(final_qml)
    ET.fromstring(final_sld)
    print(f"QML+SLD parse: {LAYER}")

    renderer_el = root.find(".//renderer-v2")
    cats = renderer_el.find("categories").findall("category")
    values = [c.get("value") for c in cats]
    sym_names = {s.get("name") for s in renderer_el.find("symbols")}
    for i, (code, kind, _p) in enumerate(NEW_CODES):
        assert values.count(code) == 1, code
        assert str(FIRST_SYMBOL + i) in sym_names
        assert final_sld.count(f"<ogc:Literal>{escape(code)}</ogc:Literal>") == 1, code
    label = root.find(".//labeling/settings/text-style").get("fieldName")
    assert NEW_LABEL_BRANCH in label or LEGACY_LABEL_BRANCH in label
    # dd spot-checks: mineral colour + percent density present in new symbols
    for i, (code, kind, _p) in enumerate(NEW_CODES):
        s, e = symbol_block(final_qml, str(FIRST_SYMBOL + i))
        blk = final_qml[s:e]
        assert "Mineral1" in blk, f"{code}: colour dd missing"
        if kind != "wash":
            assert "Percent" in blk, f"{code}: density dd missing"
        if kind == "hatch":
            assert "OverlayStrike" in blk, f"{code}: lineAngle dd lost"
    widgets = {fl.get("name"): fl.find("editWidget")
               for fl in root.find("fieldConfiguration")}
    assert widgets["Mineral1"].get("type") == "ValueRelation"
    assert widgets["Percent"].get("type") == "Range"
    containers = [c for c in root.iter("attributeEditorContainer")
                  if c.get("name") == NEW_TYPE]
    assert len(containers) == 1 and \
        containers[0].get("visibilityExpressionEnabled") == "1"
    print(f"round-trip ok: category row, {len(NEW_CODES)} codes, "
          f"{len(NEW_CODES)} categories+symbols (colour dd from Mineral1, "
          f"density dd from Percent, strike dd kept on hatches), SLD lockstep, "
          f"label branch, form container ({len(cats)} categories total)")
    con.close()


if __name__ == "__main__":
    main()
