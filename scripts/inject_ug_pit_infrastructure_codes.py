"""Underground + open-pit infrastructure codes (UG paper-mapping parity).

The Dec 2023 scans annotate mining context everywhere: sump, pillar
("on hold due to pillar"), stopes, backfill, drives.  Pit mapping needs
the bench geometry equivalents.  User-approved sets (2026-08-15):

3 - Overlay (Infrastructure):
    Stope Outline (line-only, muted maroon - clone of Pit Outline)
    Pillar / Sump / Backfilled / Underground Workings /
    Stockpile / ROM Pad (flat washes - clones of Laydown, house alpha)

2 - Linework (Infrastructure), all grey Track clones:
    Decline (long dash) . Drive Outline (solid) . Vent Raise (thin)
    Bench Crest (solid) . Bench Toe (dash) . Ramp (wider)
    Haul Road (widest)

Table + QML renderer + SLD kept in lockstep on BOTH layers (each is
maintained per-code).  Run inject_weight_scaling.py afterwards so the
new Linework strokes pick up Weight/width dd expressions.

Idempotent and re-runnable: each edit group must be 0 or full count;
styles parse-validated BEFORE anything is written.

Usage:  python scripts/inject_ug_pit_infrastructure_codes.py [gpkg]
"""
import os
import re
import sqlite3
import sys
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

OV_LAYER = "3 - Overlay"
LW_LAYER = "2 - Linework"

OV_FIRST_FID = 159     # max OverlayCodes fid = 158
OV_FIRST_SYMBOL = 159  # max Overlay symbol = 158
LW_FIRST_FID = 130     # max LineworkCodes fid = 129
LW_FIRST_SYMBOL = 151  # max Linework symbol = 150

# code, build, rgb (wash colour / line colour)
OV_CODES = [
    ("Stope Outline", "line", (122, 62, 62)),
    ("Pillar", "wash", (120, 120, 120)),
    ("Sump", "wash", (100, 130, 150)),
    ("Backfilled", "wash", (189, 170, 140)),
    ("Underground Workings", "wash", (150, 150, 150)),
    ("Stockpile", "wash", (170, 150, 110)),
    ("ROM Pad", "wash", (152, 138, 120)),
]
OV_WASH_ALPHA = 28
OV_WASH_SOURCE = "Laydown"
OV_LINE_SOURCE = "Pit Outline"

# code, dash (None = solid), width factor
LW_CODES = [
    ("Decline", "25;6", 1.0),
    ("Drive Outline", None, 1.0),
    ("Vent Raise", None, 0.8),
    ("Bench Crest", None, 1.0),
    ("Bench Toe", "12;4", 1.0),
    ("Ramp", None, 1.3),
    ("Haul Road", None, 1.6),
]
LW_SOURCE = "Track"


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def t_uuid(tag):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "lgs-infra-row:" + tag))


def c_uuid(tag):
    return "{%s}" % uuid.uuid5(uuid.NAMESPACE_URL, "lgs-infra-cat:" + tag)


def l_id(tag, i):
    return "{%s}" % uuid.uuid5(uuid.NAMESPACE_URL, f"lgs-infra-layer:{tag}:{i}")


def symbol_span(q, name):
    m = re.search(r'<symbol\b[^>]*\bname="%s"[^>]*>' % re.escape(name), q)
    if not m:
        bail(f"symbol {name!r} not found")
    depth = 0
    for t in re.finditer(r'<symbol\b|</symbol>', q[m.start():]):
        depth += 1 if t.group(0) == '<symbol' else -1
        if depth == 0:
            return m.start(), m.start() + t.end()
    bail(f"unbalanced symbol {name!r}")


def sym_for(renderer, code):
    cm = re.search(r'<category[^>]*value="%s"[^>]*/>' % re.escape(code), renderer)
    if not cm:
        bail(f"category {code!r} not found")
    return re.search(r'symbol="(\d+)"', cm.group(0)).group(1)


def direct_opts(el):
    cont = el.find("Option")
    return {o.get("name"): o for o in cont.findall("Option")} if cont is not None else {}


def set_opt(layer_el, name, value):
    opts = direct_opts(layer_el)
    if name in opts:
        opts[name].set("value", value)
        opts[name].set("type", "QString")
    else:
        ET.SubElement(layer_el.find("Option"), "Option",
                      {"name": name, "type": "QString", "value": value})


def rename_subsymbols(sym_el, old, new):
    for sub in sym_el.iter("symbol"):
        n = sub.get("name")
        if n and n.startswith("@%s@" % old):
            sub.set("name", "@%s@%s" % (new, n.split("@")[-1]))


def clone(renderer, source_code, new_name, tag):
    s, e = symbol_span(renderer, sym_for(renderer, source_code))
    sym = ET.fromstring(renderer[s:e])
    old = sym.get("name")
    sym.set("name", new_name)
    rename_subsymbols(sym, old, new_name)
    for i, lyr in enumerate(sym.iter("layer")):
        lyr.set("id", l_id(tag, i))
    return sym


def sld_rule_for(sld, code):
    needle = f"<ogc:Literal>{escape(code)}</ogc:Literal>"
    for m in re.finditer(r'<se:Rule>.*?</se:Rule>', sld, re.S):
        if needle in m.group(0):
            return m
    return None


def clone_sld_rule(sld, source_code, code, hexcolor):
    m = sld_rule_for(sld, source_code)
    if m is None:
        bail(f"SLD rule for {source_code!r} not found")
    rule = m.group(0)
    xml_code = escape(code)
    rule = re.sub(r'<se:Name>.*?</se:Name>', f'<se:Name>{xml_code}</se:Name>',
                  rule, count=1, flags=re.S)
    rule = re.sub(r'<se:Title>.*?</se:Title>', f'<se:Title>{xml_code}</se:Title>',
                  rule, count=1, flags=re.S)
    rule = rule.replace(f"<ogc:Literal>{escape(source_code)}</ogc:Literal>",
                        f"<ogc:Literal>{xml_code}</ogc:Literal>")
    rule = re.sub(r'(<se:SvgParameter name="(?:fill|stroke)">)#[0-9a-fA-F]{6}'
                  r'(</se:SvgParameter>)', r'\g<1>%s\g<2>' % hexcolor, rule)
    return rule


def rgb_hex(rgb):
    return "#%02x%02x%02x" % rgb


def process_layer(cur, layer, table, code_type, codes, first_fid, first_symbol,
                  build_fn, sld_source_for):
    row = cur.execute(
        "SELECT styleQML, styleSLD FROM layer_styles WHERE f_table_name=?",
        (layer,)).fetchone()
    qml, sld = row
    original_qml, original_sld = qml, sld

    existing = {c for (c,) in cur.execute(
        f"SELECT Code FROM {table} WHERE Code IN (%s)"
        % ",".join("?" * len(codes)), [c[0] for c in codes])}
    if existing and len(existing) != len(codes):
        bail(f"{table}: partial code state {sorted(existing)}")
    inserts_needed = not existing

    rm = re.search(r'<renderer-v2\b.*?</renderer-v2>', qml, re.S)
    renderer = rm.group(0)
    present = [c for c, *_ in codes if f'value="{c}"' in renderer]
    if present and len(present) != len(codes):
        bail(f"{layer}: partial category state {present}")
    cats_needed = not present

    if cats_needed:
        cat_lines, sym_blocks = [], []
        for i, spec in enumerate(codes):
            code = spec[0]
            name = str(first_symbol + i)
            cat_lines.append(
                '<category render="true" type="string" label="%s" value="%s" '
                'uuid="%s" symbol="%s"/>' % (escape(code, {'"': "&quot;"}),
                                             escape(code, {'"': "&quot;"}),
                                             c_uuid(code), name))
            sym_blocks.append(build_fn(renderer, name, spec))
            print(f"{code}: category + symbol {name}")
        i = renderer.index("</categories>")
        renderer = renderer[:i] + "".join(cat_lines) + renderer[i:]
        i = renderer.index("</symbols>")
        renderer = renderer[:i] + "".join(sym_blocks) + renderer[i:]
    else:
        print(f"{layer}: categories already present")
    qml = qml[:rm.start()] + renderer + qml[rm.end():]

    sld_present = [c for c, *_ in codes if sld_rule_for(sld, c)]
    if sld_present and len(sld_present) != len(codes):
        bail(f"{layer}: partial SLD state {sld_present}")
    sld_needed = not sld_present
    if sld_needed:
        rules = []
        for spec in codes:
            code = spec[0]
            src, hexcolor = sld_source_for(spec)
            rules.append(clone_sld_rule(sld, src, code, hexcolor))
        i = sld.index("</se:FeatureTypeStyle>")
        sld = sld[:i] + "".join(rules) + sld[i:]
        print(f"{layer}: {len(rules)} SLD rules appended")
    else:
        print(f"{layer}: SLD rules already present")

    if len({inserts_needed, cats_needed, sld_needed}) != 1:
        bail(f"{layer}: insert state differs between table/QML/SLD")
    try:
        ET.fromstring(qml)
        ET.fromstring(sld)
    except ET.ParseError as exc:
        bail(f"{layer}: edited style no longer parses: {exc}")

    if inserts_needed:
        for i, spec in enumerate(codes):
            code = spec[0]
            cur.execute(f"INSERT INTO {table} (fid, Type, Code, Description, "
                        "UUID) VALUES (?,?,?,?,?)",
                        (first_fid + i, code_type, code, code, t_uuid(code)))
        print(f"{table}: {len(codes)} rows added")
    if qml != original_qml or sld != original_sld:
        cur.execute("UPDATE layer_styles SET styleQML=?, styleSLD=? "
                    "WHERE f_table_name=?", (qml, sld, layer))
        assert cur.rowcount == 1


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    # ---- Overlay ----
    def ov_build(renderer, name, spec):
        code, kind, rgb = spec
        if kind == "line":
            sym = clone(renderer, OV_LINE_SOURCE, name, code)
            lyr = sym.find("layer")
            if lyr.get("class") != "SimpleLine":
                bail("Pit Outline clone shape unexpected")
            set_opt(lyr, "line_color", "%d,%d,%d,255" % rgb)
        else:
            sym = clone(renderer, OV_WASH_SOURCE, name, code)
            lyr = sym.find("layer")
            if lyr.get("class") != "SimpleFill":
                bail("Laydown clone shape unexpected")
            set_opt(lyr, "color", "%d,%d,%d,%d" % (rgb + (OV_WASH_ALPHA,)))
            set_opt(lyr, "outline_color", "%d,%d,%d,255" % rgb)
        return ET.tostring(sym, encoding="unicode")

    def ov_sld_src(spec):
        code, kind, rgb = spec
        return (OV_LINE_SOURCE if kind == "line" else OV_WASH_SOURCE), rgb_hex(rgb)

    process_layer(cur, OV_LAYER, "OverlayCodes", "Infrastructure", OV_CODES,
                  OV_FIRST_FID, OV_FIRST_SYMBOL, ov_build, ov_sld_src)

    # ---- Linework ----
    def lw_build(renderer, name, spec):
        code, dash, factor = spec
        sym = clone(renderer, LW_SOURCE, name, code)
        lyr = sym.find("layer")
        if lyr.get("class") != "SimpleLine":
            bail("Track clone shape unexpected")
        opts = direct_opts(lyr)
        if factor != 1.0:
            w = float(opts["line_width"].get("value"))
            set_opt(lyr, "line_width", "%.3g" % (w * factor))
        if dash:
            set_opt(lyr, "line_style", "dash")
            set_opt(lyr, "use_custom_dash", "1")
            set_opt(lyr, "customdash", dash)
            set_opt(lyr, "customdash_unit", "Point")
        # strip cloned dd (weight scaling re-run will rebuild from statics)
        dd = lyr.find("data_defined_properties")
        for child in list(dd):
            dd.remove(child)
        outer = ET.SubElement(dd, "Option", {"type": "Map"})
        ET.SubElement(outer, "Option", {"name": "name", "type": "QString", "value": ""})
        ET.SubElement(outer, "Option", {"name": "properties"})
        ET.SubElement(outer, "Option", {"name": "type", "type": "QString",
                                        "value": "collection"})
        return ET.tostring(sym, encoding="unicode")

    def lw_sld_src(spec):
        return LW_SOURCE, "#232323"

    process_layer(cur, LW_LAYER, "LineworkCodes", "Infrastructure", LW_CODES,
                  LW_FIRST_FID, LW_FIRST_SYMBOL, lw_build, lw_sld_src)

    con.commit()

    # ---- validation ----
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    for layer, table, codes, first_symbol in [
            (OV_LAYER, "OverlayCodes", OV_CODES, OV_FIRST_SYMBOL),
            (LW_LAYER, "LineworkCodes", LW_CODES, LW_FIRST_SYMBOL)]:
        q, s = cur.execute("SELECT styleQML, styleSLD FROM layer_styles "
                           "WHERE f_table_name=?", (layer,)).fetchone()
        root = ET.fromstring(q)
        ET.fromstring(s)
        cats = root.find(".//renderer-v2/categories").findall("category")
        values = [c.get("value") for c in cats]
        syms = {x.get("name") for x in root.find(".//renderer-v2/symbols")}
        for i, spec in enumerate(codes):
            code = spec[0]
            got = cur.execute(f"SELECT Type FROM {table} WHERE Code=?",
                              (code,)).fetchone()
            assert got == ("Infrastructure",), (code, got)
            assert values.count(code) == 1, code
            assert str(first_symbol + i) in syms
            assert s.count(f"<ogc:Literal>{escape(code)}</ogc:Literal>") == 1, code
        print(f"round-trip ok: {layer} ({len(cats)} categories)")
    con.close()


if __name__ == "__main__":
    main()
