"""Confidence (Observed / Inferred / Queried) across all four layers.

UG paper-mapping parity: expert mapping queries structures liberally
("Ft?", "VQZ/Ft?") and distinguishes mapped from inferred geometry by
line style.  This adds a `Confidence` field (ValueMap, default
'Observed') to 1 - FieldNotebook, 3 - Overlay, 2 - Linework and
4 - Basemap, plus:

LABELS - Queried appends '?':
    - Linework / Overlay: inline after the existing label expression.
    - Basemap: inline right after the Lithology1 code ('MIC?').
    - FieldNotebook: the Dip Labels rule renders '75?'
      (script_setmapping.create_dip_rule carries the same expression for
      regenerated labelling - keep the two in step).

LINEWORK DASHING (Structural + Veins + Lithology categories only;
user-reviewed classification, 2026-08-15):
    - FLIP codes (authored dashed but representing observed features -
      faults, shears, fold traces, dykes/sill, faulted/sheared
      contacts): base style becomes SOLID; Confidence Inferred/Queried
      restores each code's own authored dash via a data-defined
      customDash (ELSE a '100000;1' mega-dash == solid; empirically a
      dd customDash applies even with use_custom_dash=0, and an empty
      ELSE erases the line - hence the mega-dash).
    - SOLID codes: dd outlineStyle 'dash' when Inferred/Queried, on
      backbone SimpleLine layers whose base is solid (decorative dashed
      layers like Vein - Shear's wavy selvage are skipped by that
      condition).
    - EXCLUDED (dash encodes identity, not certainty): fold-generation
      dash-dots, gradational-contact dots, trend/formline styles,
      marker patterns, and the existing '- Inferred/Queried/Concealed'
      variant codes, which are kept as-is.

Existing dd (Weight/width outlineWidth expressions) are preserved -
properties are merged, never replaced wholesale.  Styles are
parse-validated BEFORE anything is written; idempotent and re-runnable.

Usage:  python scripts/inject_confidence_system.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

QUERIED_SUFFIX = "CASE WHEN \"Confidence\" = 'Queried' THEN '?' ELSE '' END"
INFERRED_TEST = "\"Confidence\" IN ('Inferred','Queried')"
MEGA_DASH = "100000;1"

# layer -> (anchor form field, place '?' handling key)
LAYERS = ["1 - FieldNotebook", "2 - Linework", "3 - Overlay", "4 - Basemap"]
FORM_ANCHOR = {
    "1 - FieldNotebook": "Type",
    "2 - Linework": "Weight",
    "3 - Overlay": "Type",
    "4 - Basemap": "ContactType",
}

# FLIP codes -> expected authored customdash (asserted before flipping)
FLIP_CODES = {
    "Fault": "38;7", "Fault - Dextral": "38;7", "Fault - Normal": "38;7",
    "Fault - Reverse": "38;7", "Fault - Sinistral": "38;7",
    "Fault - Strike-Slip": "38;7",
    "Shear": "38;7", "Shear - Dextral": "38;7", "Shear - Normal": "38;7",
    "Shear - Reverse": "38;7", "Shear - Sinistral": "38;7",
    # Shear Zone Boundary is NOT here: its Inferred/Queried rendering is
    # whole-tilde gaps emitted by the geometry generator - see
    # inject_linework_shear_wave.py.
    "Contact - Faulted": "25;4", "Contact - Sheared": "12;4",
    "Anticline": "30;10", "Antiform": "30;10",
    "Antiform - Overturned": "30;10", "Antiformal Syncline": "30;10",
    "Syncline": "30;10", "Synform": "30;10",
    "Synform - Overturned": "30;10", "Synformal Anticline": "30;10",
    "Aplite Dykes": "15;8", "Carbonatite Dykes": "15;8",
    "Dolerite Dykes": "15;8", "Felsic Dykes": "15;8",
    "Intermediate Dykes": "15;8", "Lamprophyre Dykes": "15;8",
    "Mafic Dykes": "15;8", "Porphyry Dykes": "15;8",
    "Ultramafic Dykes": "15;8", "Sill": "25;6",
}

SOLID_CODES = [
    "Contact - Intrusive", "Contact - Observed", "Detachment",
    "Fault - Thrust", "Kink Band Trace", "Marker - BIF", "Marker - Chert",
    "Monocline", "Nonconformity", "Unconformity", "Unconformity - Angular",
    "Terrane Boundary", "Pegmatite",
    "Vein", "Vein - Breccia", "Vein - Carbonate",
    "Vein - Extension", "Vein - Laminated",
    "Vein - Pegmatite", "Vein - Quartz", "Vein - Quartz-Carbonate",
    "Vein - Shear",   # Epidote and Mineralised retired Aug 2026
]


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def insert_before(qml, closing_tag, fragment):
    i = qml.find(closing_tag)
    if i < 0 or qml.find(closing_tag, i + 1) >= 0:
        bail(f"{closing_tag!r} not found or not unique")
    return qml[:i] + fragment + qml[i:]


def valuemap_widget(field):
    root = ET.Element("field")
    root.set("name", field)
    root.set("configurationFlags", "NoFlag")
    ew = ET.SubElement(root, "editWidget")
    ew.set("type", "ValueMap")
    cfg = ET.SubElement(ew, "config")
    outer = ET.SubElement(cfg, "Option", {"type": "Map"})
    lst = ET.SubElement(outer, "Option", {"name": "map", "type": "List"})
    for v in ("Observed", "Inferred", "Queried"):
        m = ET.SubElement(lst, "Option", {"type": "Map"})
        ET.SubElement(m, "Option", {"name": v, "type": "QString", "value": v})
    return ET.tostring(root, encoding="unicode")


def form_field_block(field, index):
    f = ET.Element("attributeEditorField")
    for k, v in [("name", field), ("index", str(index)),
                 ("horizontalStretch", "0"), ("showLabel", "1"),
                 ("verticalStretch", "0")]:
        f.set(k, v)
    return ET.tostring(f, encoding="unicode")


def add_field_to_layer(cur, layer, qml, gpkg):
    """Column + widget + default + form placement for Confidence."""
    cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{layer}")')]
    if "Confidence" not in cols:
        cur.execute(f'ALTER TABLE "{layer}" ADD COLUMN "Confidence" TEXT(20)')
        print(f"{layer}: Confidence column added")
    else:
        print(f"{layer}: Confidence column already present")
    cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{layer}")')]
    qgis_cols = [c for c in cols if c != "geom"]
    idx = qgis_cols.index("Confidence")

    if '<field name="Confidence" configurationFlags' in qml:
        print(f"{layer}: Confidence config already present")
    else:
        qml = insert_before(qml, "</fieldConfiguration>", valuemap_widget("Confidence"))
        qml = insert_before(qml, "</aliases>",
                            f'<alias name="Confidence" index="{idx}" field="Confidence"/>')
        qml = insert_before(qml, "</splitPolicies>",
                            '<policy policy="Duplicate" field="Confidence"/>')
        qml = insert_before(qml, "</duplicatePolicies>",
                            '<policy policy="Duplicate" field="Confidence"/>')
        qml = insert_before(qml, "</defaults>",
                            '<default expression="\'Observed\'" applyOnUpdate="0" field="Confidence"/>')
        qml = insert_before(qml, "</constraints>",
                            '<constraint constraints="0" notnull_strength="0" '
                            'field="Confidence" unique_strength="0" exp_strength="0"/>')
        qml = insert_before(qml, "</constraintExpressions>",
                            '<constraint desc="" field="Confidence" exp=""/>')
        qml = insert_before(qml, "</columns>",
                            '<column name="Confidence" type="field" hidden="0" width="-1"/>')
        qml = insert_before(qml, "</editable>",
                            '<field name="Confidence" editable="1"/>')
        qml = insert_before(qml, "</labelOnTop>",
                            '<field name="Confidence" labelOnTop="0"/>')
        qml = insert_before(qml, "</reuseLastValue>",
                            '<field reuseLastValue="0" name="Confidence"/>')
        print(f"{layer}: Confidence config injected")

    anchor_name = FORM_ANCHOR[layer]
    if re.search(r'<attributeEditorField name="Confidence"', qml):
        print(f"{layer}: form placement already present")
    else:
        anchor = re.search(
            r'<attributeEditorField name="%s".*?</attributeEditorField>'
            % re.escape(anchor_name), qml, re.S)
        if not anchor:
            bail(f"{layer}: form anchor {anchor_name!r} not found")
        qml = (qml[:anchor.end()] + form_field_block("Confidence", idx)
               + qml[anchor.end():])
        print(f"{layer}: form placement after {anchor_name}")
    return qml


# ------------------------------------------------------------- dd machinery
def merge_dd_into_layer_xml(layer_xml, new_props):
    """Merge properties into the layer's dd block (string in, string out)."""
    ddm = re.search(r'<data_defined_properties>.*?</data_defined_properties>',
                    layer_xml, re.S)
    if not ddm:
        bail("layer without data_defined_properties")
    root = ET.fromstring(ddm.group(0))
    outer = root.find("Option")
    if outer is None:
        outer = ET.SubElement(root, "Option", {"type": "Map"})
    props = None
    for o in outer.findall("Option"):
        if o.get("name") == "properties":
            props = o
    if props is None:
        props = ET.SubElement(outer, "Option", {"name": "properties"})
    props.set("type", "Map")
    props.attrib.pop("value", None)
    existing = {o.get("name"): o for o in props.findall("Option")}
    for key, expr in new_props.items():
        if key in existing:
            props.remove(existing[key])
        entry = ET.SubElement(props, "Option", {"name": key, "type": "Map"})
        ET.SubElement(entry, "Option", {"name": "active", "type": "bool", "value": "true"})
        ET.SubElement(entry, "Option", {"name": "expression", "type": "QString", "value": expr})
        ET.SubElement(entry, "Option", {"name": "type", "type": "int", "value": "3"})
    return (layer_xml[:ddm.start()] + ET.tostring(root, encoding="unicode")
            + layer_xml[ddm.end():])


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


def simpleline_layers(sym_xml):
    """Yield (start, end, layer_xml) for each complete SimpleLine <layer>."""
    for lm in re.finditer(r'<layer\b[^>]*class="SimpleLine"[^>]*>', sym_xml):
        depth = 0
        for t in re.finditer(r'<layer\b|</layer>', sym_xml[lm.start():]):
            depth += 1 if t.group(0) == '<layer' else -1
            if depth == 0:
                yield lm.start(), lm.start() + t.end()
                break


def statics_of(layer_xml):
    ddm = re.search(r'<data_defined_properties>', layer_xml)
    region = layer_xml[:ddm.start()] if ddm else layer_xml
    def val(name):
        m = re.search(r'name="%s" type="QString" value="([^"]*)"' % name, region)
        return m.group(1) if m else None
    return val


def set_static(layer_xml, name, value):
    ddm = re.search(r'<data_defined_properties>', layer_xml)
    cut = ddm.start() if ddm else len(layer_xml)
    head, tail = layer_xml[:cut], layer_xml[cut:]
    head, n = re.subn(r'(name="%s" type="QString" value=")[^"]*(")' % name,
                      r'\g<1>%s\g<2>' % value, head, count=1)
    if n != 1:
        bail(f"static {name!r} not found to set")
    return head + tail


def apply_flip(sym_xml, code, expected_dash):
    changed = False
    out = sym_xml
    # iterate repeatedly since offsets shift after each edit
    while True:
        edited = False
        for s, e in simpleline_layers(out):
            lx = out[s:e]
            val = statics_of(lx)
            dashed = val("line_style") not in (None, "solid") or val("use_custom_dash") == "1"
            if not dashed:
                continue
            if "customDash" in lx and MEGA_DASH in lx:
                continue  # already flipped
            authored = val("customdash")
            if authored != expected_dash:
                bail(f"{code}: authored dash {authored!r} != expected {expected_dash!r}")
            lx = set_static(lx, "line_style", "solid")
            lx = set_static(lx, "use_custom_dash", "0")
            lx = merge_dd_into_layer_xml(lx, {
                "customDash": "CASE WHEN %s THEN '%s' ELSE '%s' END"
                              % (INFERRED_TEST, authored, MEGA_DASH)})
            out = out[:s] + lx + out[e:]
            changed = edited = True
            break
        if not edited:
            break
    return out, changed


def apply_solid(sym_xml, code):
    changed = False
    out = sym_xml
    while True:
        edited = False
        for s, e in simpleline_layers(out):
            lx = out[s:e]
            val = statics_of(lx)
            if val("line_style") != "solid" or val("use_custom_dash") == "1":
                continue  # decorative dashed layer (e.g. selvage) - skip
            if '"outlineStyle"' in lx or "name=\"outlineStyle\"" in lx:
                continue  # already applied
            lx = merge_dd_into_layer_xml(lx, {
                "outlineStyle": "CASE WHEN %s THEN 'dash' ELSE 'solid' END"
                                % INFERRED_TEST})
            out = out[:s] + lx + out[e:]
            changed = edited = True
            break
        if not edited:
            break
    return out, changed


# ------------------------------------------------------------- labels
def wrap_label_suffix(qml, layer):
    """Append the Queried '?' to the layer's label expression."""
    if layer == "1 - FieldNotebook":
        # Dip Labels rule: fieldName="Dip" isExpression -> expression with '?'
        new_expr = "\"Dip\" || " + QUERIED_SUFFIX
        m = re.search(r'<rule\b[^>]*description="Dip Labels"[^>]*>', qml)
        if not m:
            bail("Dip Labels rule not found")
        tsm = re.search(r'<text-style\b[^>]*>', qml[m.end():])
        ts = tsm.group(0)
        if quoteattr(new_expr)[1:-1] in ts:
            print(f"{layer}: Dip label '?' already applied")
            return qml
        if 'fieldName="Dip"' not in ts:
            bail(f"Dip rule text-style unexpected: {ts[:200]}")
        ts_new = ts.replace('fieldName="Dip"', "fieldName=%s" % quoteattr(new_expr))
        if 'isExpression="0"' in ts_new:
            ts_new = ts_new.replace('isExpression="0"', 'isExpression="1"')
        qml = qml[:m.end() + tsm.start()] + ts_new + qml[m.end() + tsm.end():]
        print(f"{layer}: Dip label '?' injected")
        return qml

    m = re.search(r'<labeling type="simple">.*?</labeling>', qml, re.S)
    if not m:
        bail(f"{layer}: simple labeling block not found")
    lab = ET.fromstring(m.group(0))
    ts = lab.find(".//text-style")
    expr = ts.get("fieldName")
    if layer == "4 - Basemap":
        # '?' inline after the Lithology1 code, before the modifier span
        needle = "\"Lithology1\" ||"
        marker = "\"Lithology1\" || " + QUERIED_SUFFIX + " ||"
        if marker in expr:
            print(f"{layer}: label '?' already applied")
            return qml
        if expr.count(needle) != 1:
            bail(f"{layer}: label shape unexpected ({expr.count(needle)} Lithology1 anchors)")
        new = expr.replace(needle, marker)
    else:
        if expr.rstrip().endswith(QUERIED_SUFFIX):
            print(f"{layer}: label '?' already applied")
            return qml
        new = expr + " || " + QUERIED_SUFFIX
    ts.set("fieldName", new)
    if ts.get("isExpression") == "0":
        ts.set("isExpression", "1")
    qml = qml[:m.start()] + ET.tostring(lab, encoding="unicode") + qml[m.end():]
    print(f"{layer}: label '?' injected")
    return qml


# ------------------------------------------------------------- main
def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    new_qmls = {}
    for layer in LAYERS:
        row = cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                          (layer,)).fetchone()
        if not row or not row[0]:
            bail(f"no styleQML for {layer!r}")
        qml = row[0]
        qml = add_field_to_layer(cur, layer, qml, gpkg)
        qml = wrap_label_suffix(qml, layer)
        new_qmls[layer] = qml
    con.commit()

    # Linework dashing
    qml = new_qmls["2 - Linework"]
    rm = re.search(r'<renderer-v2\b.*?</renderer-v2>', qml, re.S)
    if not rm:
        bail("Linework renderer-v2 not found")
    renderer = rm.group(0)

    def cat_symbol(code):
        cm = re.search(r'<category[^>]*value=%s[^>]*/>' % quoteattr(code), renderer)
        if not cm:
            bail(f"Linework category {code!r} not found")
        return re.search(r'symbol="(\d+)"', cm.group(0)).group(1)

    n_flip = n_solid = 0
    for code, dash in FLIP_CODES.items():
        s, e = symbol_span(renderer, cat_symbol(code))
        new_sym, changed = apply_flip(renderer[s:e], code, dash)
        renderer = renderer[:s] + new_sym + renderer[e:]
        n_flip += bool(changed)
    for code in SOLID_CODES:
        s, e = symbol_span(renderer, cat_symbol(code))
        new_sym, changed = apply_solid(renderer[s:e], code)
        renderer = renderer[:s] + new_sym + renderer[e:]
        n_solid += bool(changed)
    print(f"Linework dashing: {n_flip} flip codes changed, "
          f"{n_solid} solid codes changed "
          f"(0/0 on re-run means already applied)")
    new_qmls["2 - Linework"] = qml[:rm.start()] + renderer + qml[rm.end():]

    # Validate BEFORE writing.
    for layer, q in new_qmls.items():
        try:
            ET.fromstring(q)
        except ET.ParseError as exc:
            bail(f"{layer}: edited QML no longer parses, aborting: {exc}")

    for layer, q in new_qmls.items():
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (q, layer))
        assert cur.rowcount == 1
    con.commit()
    print("styleQML updated for all four layers")

    # ---------------- validation --------------------------------------
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    for layer in LAYERS:
        q, = cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                         (layer,)).fetchone()
        root = ET.fromstring(q)
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{layer}")')]
        assert "Confidence" in cols, layer
        widgets = {fl.get("name"): fl.find("editWidget")
                   for fl in root.find("fieldConfiguration")}
        assert widgets["Confidence"].get("type") == "ValueMap", layer
        d = next(d for d in root.iter("default")
                 if d.get("field") == "Confidence")
        assert d.get("expression") == "'Observed'", layer
        placed = any(f.get("name") == "Confidence"
                     for f in root.iter("attributeEditorField"))
        assert placed, f"{layer}: Confidence not on form"
        assert "Queried" in q, layer
        print(f"round-trip ok: {layer}")

    q, = cur.execute("SELECT styleQML FROM layer_styles "
                     "WHERE f_table_name='2 - Linework'").fetchone()
    assert q.count(MEGA_DASH) >= len(FLIP_CODES), "flip dd missing"
    assert q.count("outlineStyle") >= len(SOLID_CODES), "solid dd missing"
    # excluded variants untouched: their symbols contain no Confidence dd
    rm = re.search(r'<renderer-v2\b.*?</renderer-v2>', q, re.S)
    renderer = rm.group(0)
    for code in ("Fault - Inferred", "Contact - Gradational",
                 "Fold Axial Trace - F3", "Foliation Trend"):
        cm = re.search(r'<category[^>]*value=%s[^>]*/>' % quoteattr(code), renderer)
        sym = re.search(r'symbol="(\d+)"', cm.group(0)).group(1)
        s, e = symbol_span(renderer, sym)
        assert "Confidence" not in renderer[s:e], f"{code} was touched!"
    print("round-trip ok: dash dd counts, excluded codes untouched")
    con.close()


if __name__ == "__main__":
    main()
