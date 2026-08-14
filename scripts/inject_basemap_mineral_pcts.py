"""Basemap third mineral slots + per-mineral percentages.

UG paper-mapping parity (Dec 2023 scan analysis): modal mineralogy with
percentages is written straight onto mapped units and vein polygons
("VQ ba 60% ga 15%", "msv ga 7-10%").  Extends the lith-modifier system
from inject_basemap_lith_modifiers.py on '4 - Basemap':

    - Lith1Mineral3 / Lith2Mineral3 (ValueRelation -> MineralCodes),
      appearing once Mineral2 is filled (progressive disclosure).
    - A percentage spinbox per mineral slot: Lith1Mineral1Pct ..
      Lith2Mineral3Pct (0-100, optional), each appearing only once its
      mineral is filled.

Label: the parenthetical modifier span becomes per-mineral, percentage
attached to its own mineral -  'Qtz(5%)-Fsp-Gn(5%)' or
'Opx(60%)-Cpx(40%)' - textures unchanged after the comma.  SUPERSEDES
the label expression written by inject_basemap_lith_modifiers.py (do
not re-run that script afterwards; its label assert reflects the older
expression - precedent: it superseded inject_basemap_uncoded_label.py
the same way).

Idempotent and re-runnable; QML validated with ElementTree BEFORE
anything is written.

Usage:  python scripts/inject_basemap_mineral_pcts.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

LAYER = "4 - Basemap"

# field, sql type, kind, alias, visibility expression, insert-after container
SPEC = [
    ("Lith1Mineral1Pct", "MEDIUMINT", "percent", "Lith1 Mineral 1 %",
     "coalesce(\"Lith1Mineral1\",'') != ''", "Lith1 Mineral 1"),
    ("Lith1Mineral2Pct", "MEDIUMINT", "percent", "Lith1 Mineral 2 %",
     "coalesce(\"Lith1Mineral2\",'') != ''", "Lith1 Mineral 2"),
    ("Lith1Mineral3", "TEXT(100)", "mineral", "Lith1 Mineral 3",
     "coalesce(\"Lith1Mineral2\",'') != ''", "Lith1 Mineral 2 %"),
    ("Lith1Mineral3Pct", "MEDIUMINT", "percent", "Lith1 Mineral 3 %",
     "coalesce(\"Lith1Mineral3\",'') != ''", "Lith1 Mineral 3"),
    ("Lith2Mineral1Pct", "MEDIUMINT", "percent", "Lith2 Mineral 1 %",
     "coalesce(\"Lith2Mineral1\",'') != ''", "Lith2 Mineral 1"),
    ("Lith2Mineral2Pct", "MEDIUMINT", "percent", "Lith2 Mineral 2 %",
     "coalesce(\"Lith2Mineral2\",'') != ''", "Lith2 Mineral 2"),
    ("Lith2Mineral3", "TEXT(100)", "mineral", "Lith2 Mineral 3",
     "coalesce(\"Lith2Mineral2\",'') != ''", "Lith2 Mineral 2 %"),
    ("Lith2Mineral3Pct", "MEDIUMINT", "percent", "Lith2 Mineral 3 %",
     "coalesce(\"Lith2Mineral3\",'') != ''", "Lith2 Mineral 3"),
]


def mineral_token(m, p):
    """'Gn(5%)' - mineral code with its optional percentage attached."""
    return ("coalesce(\"%s\",'') || CASE WHEN coalesce(\"%s\",'') != '' AND "
            "\"%s\" IS NOT NULL THEN '(' || \"%s\" || '%%)' ELSE '' END"
            % (m, m, p, p))


def join_items(items, sep):
    return ("array_to_string(array_remove_all(array(%s), ''), '%s')"
            % (", ".join(items), sep))


def minerals_expr(lith):
    return join_items(
        [mineral_token(f"{lith}Mineral{i}", f"{lith}Mineral{i}Pct")
         for i in (1, 2, 3)], "-")


def textures_expr(lith):
    return join_items([f"coalesce(\"{lith}Texture1\",'')",
                       f"coalesce(\"{lith}Texture2\",'')"], "-")


def modifiers_expr(lith):
    return join_items([minerals_expr(lith), textures_expr(lith)], ", ")


def span_expr(mods):
    return ("case when " + mods + " != '' then "
            "' <span style=\"font-style:italic;font-size:70%;\">(' || "
            + mods + " || ')</span>' else '' end")


SPAN1 = span_expr(modifiers_expr("Lith1"))
SPAN2 = span_expr(modifiers_expr("Lith2"))

LABEL_EXPR = (
    "-- Uncoded lithology override: free-text lithology becomes the whole label\r\n"
    "case \r\n"
    "  when coalesce(\"UncodedLithology\",'') != '' then\r\n"
    "    '<div>' || \"UncodedLithology\" || '</div>'\r\n"
    "  else\r\n"
    "\r\n"
    "-- Lithology 1 line (prefix, sulphides, mineral(%)/texture modifiers)\r\n"
    "case \r\n"
    "  when coalesce(\"Lithology1\",'') != '' then\r\n"
    "    '<div>' ||\r\n"
    "      coalesce(\"Sulphides/Mineralisation\",'') ||\r\n"
    "      case \r\n"
    "        when coalesce(\"LithologyPrefix\",'') != '' \r\n"
    "          then ' ' || \"LithologyPrefix\" || '-' \r\n"
    "        else '' \r\n"
    "      end ||\r\n"
    "      \"Lithology1\" ||\r\n"
    "      " + SPAN1 + " ||\r\n"
    "    '</div>'\r\n"
    "  else '' \r\n"
    "end ||\r\n"
    "\r\n"
    "-- Lithology 2 line (mineral(%)/texture modifiers)\r\n"
    "case \r\n"
    "  when coalesce(\"Lithology2\",'') != '' then\r\n"
    "    '<div>' || \"Lithology2\" || " + SPAN2 + " || '</div>'\r\n"
    "  else '' \r\n"
    "end\r\n"
    "\r\n"
    "  end\r\n"
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


def container_span(qml, name):
    m = re.search(r'<attributeEditorContainer name=%s.*?</attributeEditorContainer>'
                  % quoteattr(name), qml, re.S)
    if not m:
        bail(f"form container {name!r} not found")
    return m


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
    for pre in ("Lith1Mineral1", "Lith1Mineral2", "Lith2Mineral1", "Lith2Mineral2"):
        if pre not in cols:
            bail(f"prerequisite column {pre} missing - run "
                 f"inject_basemap_lith_modifiers.py first")
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

    # 1. Label expression.
    m = re.search(r'<labeling type="simple">.*?</labeling>', qml, re.S)
    if not m:
        bail("simple <labeling> block not found")
    lab = ET.fromstring(m.group(0))
    ts = lab.find(".//text-style")
    if ts.get("fieldName") == LABEL_EXPR:
        print("label expression: already applied")
    else:
        ts.set("fieldName", LABEL_EXPR)
        qml = qml[:m.start()] + ET.tostring(lab, encoding="unicode") + qml[m.end():]
        print("label expression: per-mineral percentages injected")

    # 2. New field config.
    for field, _sqltype, kind, alias, _vis, _after in SPEC:
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

    # 3. Form containers, each after its named predecessor (SPEC order
    #    guarantees predecessors exist by the time they are needed).
    for field, _sqltype, _kind, alias, vis, after in SPEC:
        if f'<attributeEditorContainer name={quoteattr(alias)}' in qml \
                or f'<attributeEditorContainer name="{alias}"' in qml:
            print(f"container {alias}: already present")
            continue
        anchor = container_span(qml, after)
        block = container_block(field, alias, vis, qgis_index[field])
        qml = qml[:anchor.end()] + block + qml[anchor.end():]
        print(f"container {alias}: inserted after {after!r}")

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

    assert root.find(".//labeling/settings/text-style").get("fieldName") == LABEL_EXPR
    widgets = {fl.get("name"): fl.find("editWidget")
               for fl in root.find("fieldConfiguration")}
    aliases = {a.get("field"): a.get("name") for a in root.find("aliases")}
    containers = {}
    for c in root.iter("attributeEditorContainer"):
        for fld in c.findall("attributeEditorField"):
            containers[fld.get("name")] = c
    for field, _sqltype, kind, alias, vis, _after in SPEC:
        assert field in cols, f"{field} column missing"
        ew = widgets.get(field)
        want = "ValueRelation" if kind == "mineral" else "Range"
        assert ew is not None and ew.get("type") == want, (field, want)
        assert aliases.get(field) == alias, f"{field} alias wrong"
        c = containers.get(field)
        assert c is not None and c.get("visibilityExpressionEnabled") == "1" \
            and c.get("visibilityExpression") == vis, f"{field} visibility wrong"
    renderer = root.find(".//renderer-v2")
    assert renderer.get("type") == "categorizedSymbol" and renderer.get("attr") == "Lithology1"
    print(f"round-trip ok: 8 fields (Mineral3 pair + 6 percents), per-mineral "
          f"label expression, renderer untouched "
          f"({len(renderer.find('categories'))} categories)")
    con.close()


if __name__ == "__main__":
    main()
