"""Per-vein detail fields on '3 - Linework' (UG paper-mapping parity).

Expert underground mapping annotates every vein with width, mineral
assemblage, texture and sulphide percentage ("10cm HYV GA vn 5%",
"0.5cm HyV GA+cpy", "7cm wide barite vein ... galena blob").  Six new
fields bring that onto the Veins category of the Linework layer:

    Width_cm   REAL     vein width in cm (mm entered as decimals, 0.5 = 5mm)
    Mineral1-3 TEXT     ValueRelation -> MineralCodes (standard abbreviations)
    VeinTexture TEXT    ValueRelation -> TextureCodes (banded, stringer, ...)
    Percent    MEDIUMINT sulphide/mineral percentage 0-100

Form: each field sits in its own visibility-gated container after Weight
in the General tab - shown only when Category = 'Veins'; Mineral2/3
appear progressively once the previous mineral is filled (Basemap
lith-modifier pattern).

Label: the simple 'Label' field label becomes an expression.  Veins
auto-label like the paper tags - width (auto mm/cm/m: 0.5 -> "5mm",
7 -> "7cm", 120 -> "1.2m"), minerals joined '-', percent, then any
manual Label text; everything optional.  Non-vein categories keep the
plain Label behaviour.

Width also scales the drawn stroke via inject_weight_scaling.py (vein
width factor gated on Category='Veins' there) - re-run that script
after this one.

Idempotent and re-runnable; QML validated with ElementTree BEFORE
anything is written.

Usage:  python scripts/inject_linework_vein_fields.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

LAYER = "3 - Linework"

VEINS_VIS = "\"Category\" = 'Veins'"
# field, sql type, widget kind, alias, visibility expression
SPEC = [
    ("Width_cm", "REAL", "width", "Width (cm)", VEINS_VIS),
    ("Mineral1", "TEXT(250)", "mineral", "Mineral 1", VEINS_VIS),
    ("Mineral2", "TEXT(250)", "mineral", "Mineral 2",
     VEINS_VIS + " AND coalesce(\"Mineral1\",'') != ''"),
    ("Mineral3", "TEXT(250)", "mineral", "Mineral 3",
     VEINS_VIS + " AND coalesce(\"Mineral2\",'') != ''"),
    ("VeinTexture", "TEXT(250)", "texture", "Vein Texture", VEINS_VIS),
    ("Percent", "MEDIUMINT", "percent", "Mineral %", VEINS_VIS),
]

WIDTH_TEXT = (
    "CASE WHEN \"Width_cm\" IS NULL THEN '' "
    "WHEN \"Width_cm\" >= 100 THEN round(\"Width_cm\"/100.0, 2) || 'm' "
    "WHEN \"Width_cm\" < 1 THEN round(\"Width_cm\"*10, 1) || 'mm' "
    "ELSE round(\"Width_cm\", 1) || 'cm' END"
)
MINERALS_TEXT = (
    "array_to_string(array_remove_all(array("
    "coalesce(\"Mineral1\",''), coalesce(\"Mineral2\",''), "
    "coalesce(\"Mineral3\",'')), ''), '-')"
)
PERCENT_TEXT = ("CASE WHEN \"Percent\" IS NULL THEN '' "
                "ELSE \"Percent\" || '%' END")

LABEL_EXPR = (
    "CASE WHEN \"Category\" = 'Veins' THEN "
    "array_to_string(array_remove_all(array("
    + WIDTH_TEXT + ", "
    + MINERALS_TEXT + ", "
    + PERCENT_TEXT + ", "
    "coalesce(\"Label\",'')), ''), ' ') "
    "ELSE \"Label\" END"
)


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


def opt(parent, name, otype=None, value=None):
    e = ET.SubElement(parent, "Option")
    e.set("name", name)
    if otype is not None:
        e.set("type", otype)
    if value is not None:
        e.set("value", value)
    return e


def value_relation_block(field, layer_name, key, value, gpkg_path):
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
    root = ET.Element("field")
    root.set("name", field)
    root.set("configurationFlags", "NoFlag")
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


def widget_block(field, kind, gpkg):
    if kind == "mineral":
        return value_relation_block(field, "MineralCodes", "Value",
                                    "Description", gpkg)
    if kind == "texture":
        return value_relation_block(field, "TextureCodes", "Code",
                                    "Desciption", gpkg)
    if kind == "width":
        return range_block(field, "0", "100000", "1", "1")
    if kind == "percent":
        return range_block(field, "0", "100", "1", "0")
    bail(f"unknown widget kind {kind!r}")


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
        bail(f"{closing_tag!r} not found or not unique")
    return qml[:i] + fragment + qml[i:]


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    # --- Columns first, so field indexes reflect the final table. ---
    cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{LAYER}")')]
    for f, sqltype, *_ in SPEC:
        if f in cols:
            print(f"column {f}: already present")
        else:
            cur.execute(f'ALTER TABLE "{LAYER}" ADD COLUMN "{f}" {sqltype}')
            print(f"column {f}: added ({sqltype})")
    con.commit()
    cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{LAYER}")')]
    qgis_cols = [c for c in cols if c != "geom"]
    qgis_index = {f: qgis_cols.index(f) for f, *_ in SPEC}

    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    row = cur.fetchone()
    if not row or not row[0]:
        bail(f"no styleQML for {LAYER!r}")
    qml = original = row[0]

    # 1. Label: plain 'Label' field -> vein-aware expression.  Later
    # injectors may WRAP this expression (e.g. the Confidence '?' suffix), so
    # "already applied" means the vein expression appears WITHIN the current
    # one, not that it matches exactly.
    lm = re.search(r'<labeling type="simple">.*?</labeling>', qml, re.S)
    if not lm:
        bail("simple labeling block not found")
    lab = ET.fromstring(lm.group(0))
    ts = lab.find(".//text-style")
    current = ts.get("fieldName")
    if current == "Label" and ts.get("isExpression") == "0":
        ts.set("fieldName", LABEL_EXPR)
        ts.set("isExpression", "1")
        qml = (qml[:lm.start()] + ET.tostring(lab, encoding="unicode")
               + qml[lm.end():])
        print("label: vein expression injected")
    elif LABEL_EXPR in current:
        print("label: already applied")
    else:
        bail("labeling text-style unexpected (neither plain Label nor "
             "vein expression): %r" % current[:120])

    # 2. New field config.
    for field, _sqltype, kind, alias, _vis in SPEC:
        if f'<field name="{field}" configurationFlags' in qml:
            print(f"{field}: config already present")
            continue
        idx = qgis_index[field]
        qml = insert_before(qml, "</fieldConfiguration>",
                            widget_block(field, kind, gpkg))
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

    # 3. Form containers after Weight in the General tab.
    if '<attributeEditorContainer name="Width (cm)"' in qml:
        print("form containers: already present")
    else:
        anchor = re.search(
            r'<attributeEditorField name="Weight".*?</attributeEditorField>',
            qml, re.S)
        if not anchor:
            bail("Weight form field not found")
        blocks = "".join(container_block(f, alias, vis, qgis_index[f])
                         for f, _t, _k, alias, vis in SPEC)
        qml = qml[:anchor.end()] + blocks + qml[anchor.end():]
        print("form containers: injected (Veins-only visibility)")

    # Validate BEFORE writing.
    try:
        ET.fromstring(qml)
    except ET.ParseError as exc:
        bail(f"edited QML no longer parses, aborting without write: {exc}")

    if qml != original:
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, LAYER))
        assert cur.rowcount == 1
        con.commit()
        print("styleQML updated")
    else:
        print("styleQML: no change")

    # --- Round-trip validation. ---
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    root = ET.fromstring(cur.fetchone()[0])
    print(f"QML parses: {LAYER}")

    ts = root.find(".//labeling/settings/text-style")
    assert LABEL_EXPR in ts.get("fieldName") and ts.get("isExpression") == "1", \
        "label expression wrong"
    widgets = {fl.get("name"): fl.find("editWidget")
               for fl in root.find("fieldConfiguration")}
    aliases = {a.get("field"): a.get("name") for a in root.find("aliases")}
    containers = {}
    for c in root.iter("attributeEditorContainer"):
        for fld in c.findall("attributeEditorField"):
            containers[fld.get("name")] = c
    for field, _sqltype, kind, alias, vis in SPEC:
        assert field in cols, f"{field} column missing"
        ew = widgets.get(field)
        want = "Range" if kind in ("width", "percent") else "ValueRelation"
        assert ew is not None and ew.get("type") == want, (field, want)
        assert aliases.get(field) == alias, f"{field} alias wrong"
        c = containers.get(field)
        assert c is not None and c.get("visibilityExpressionEnabled") == "1" \
            and c.get("visibilityExpression") == vis, f"{field} visibility wrong"
    renderer = root.find(".//renderer-v2")
    assert renderer.get("type") == "categorizedSymbol" and renderer.get("attr") == "Type"
    print(f"round-trip ok: 6 vein fields (widgets, aliases, Veins-gated "
          f"containers), vein label expression, renderer untouched "
          f"({len(renderer.find('categories'))} categories)")
    con.close()


if __name__ == "__main__":
    main()
