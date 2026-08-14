"""Basemap lithology modifiers: minerals + textures replace Lith*Feature.

Removes the free-text Lith1Feature/Lith2Feature fields and adds, per
lithology, up to two minerals and up to two textures picked from the
MineralCodes/TextureCodes lookup tables:

    Lith1Mineral1/2, Lith1Texture1/2, Lith2Mineral1/2, Lith2Texture1/2

- ValueRelation widgets (minerals store the standard abbreviation from
  MineralCodes.Value - see update_mineral_abbreviations.py - and display
  the full Description; textures store/display full names).
- Progressive disclosure on the form (user decision): each dropdown sits
  in its own visibility-controlled container in the old Lith*Feature
  slot - first mineral/texture appear once the lithology is chosen, the
  second slot once the first is filled.
- Label parenthetical becomes e.g. 'Mb (Ol-Px, Amygdaloidal)': minerals
  joined '-', then ', ', then textures, in the existing 70%-italic span.
  The UncodedLithology full-label override is preserved.

Supersedes the label expression from inject_basemap_uncoded_label.py.

Idempotent and re-runnable; the QML is validated with ElementTree BEFORE
anything is written.

Usage:  python scripts/inject_basemap_lith_modifiers.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

LAYER = "4 - Basemap"
OLD_FIELDS = ("Lith1Feature", "Lith2Feature")

LITH1_VIS = "coalesce(\"Lithology1\",'') != ''"
LITH2_VIS = "coalesce(\"Lithology2\",'') != ''"
# (field, lookup layer, key col, value col, alias, visibility expression)
SPEC = [
    ("Lith1Mineral1", "MineralCodes", "Value", "Description",
     "Lith1 Mineral 1", LITH1_VIS),
    ("Lith1Mineral2", "MineralCodes", "Value", "Description",
     "Lith1 Mineral 2", "coalesce(\"Lith1Mineral1\",'') != ''"),
    ("Lith1Texture1", "TextureCodes", "Code", "Desciption",
     "Lith1 Texture 1", LITH1_VIS),
    ("Lith1Texture2", "TextureCodes", "Code", "Desciption",
     "Lith1 Texture 2", "coalesce(\"Lith1Texture1\",'') != ''"),
    ("Lith2Mineral1", "MineralCodes", "Value", "Description",
     "Lith2 Mineral 1", LITH2_VIS),
    ("Lith2Mineral2", "MineralCodes", "Value", "Description",
     "Lith2 Mineral 2", "coalesce(\"Lith2Mineral1\",'') != ''"),
    ("Lith2Texture1", "TextureCodes", "Code", "Desciption",
     "Lith2 Texture 1", LITH2_VIS),
    ("Lith2Texture2", "TextureCodes", "Code", "Desciption",
     "Lith2 Texture 2", "coalesce(\"Lith2Texture1\",'') != ''"),
]


def join_fields(fields, sep):
    """QGIS-expression join of non-empty field values with a separator."""
    items = ", ".join("coalesce(\"%s\",'')" % f for f in fields)
    return ("array_to_string(array_remove_all(array(%s), ''), '%s')"
            % (items, sep))


def modifiers_expr(m1, m2, t1, t2):
    """Minerals joined '-', textures joined '-', families joined ', '."""
    return ("array_to_string(array_remove_all(array(%s, %s), ''), ', ')"
            % (join_fields((m1, m2), "-"), join_fields((t1, t2), "-")))


def span_expr(mods):
    return ("case when " + mods + " != '' then "
            "' <span style=\"font-style:italic;font-size:70%;\">(' || "
            + mods + " || ')</span>' else '' end")


SPAN1 = span_expr(modifiers_expr("Lith1Mineral1", "Lith1Mineral2",
                                 "Lith1Texture1", "Lith1Texture2"))
SPAN2 = span_expr(modifiers_expr("Lith2Mineral1", "Lith2Mineral2",
                                 "Lith2Texture1", "Lith2Texture2"))

LABEL_EXPR = (
    "-- Uncoded lithology override: free-text lithology becomes the whole label\r\n"
    "case \r\n"
    "  when coalesce(\"UncodedLithology\",'') != '' then\r\n"
    "    '<div>' || \"UncodedLithology\" || '</div>'\r\n"
    "  else\r\n"
    "\r\n"
    "-- Lithology 1 line (prefix, sulphides, mineral/texture modifiers)\r\n"
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
    "-- Lithology 2 line (mineral/texture modifiers)\r\n"
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


def old_field_patterns(f):
    return [
        re.compile(r'<attributeEditorField\b[^>]*name="%s".*?</attributeEditorField>' % f, re.S),
        re.compile(r'<field name="%s" configurationFlags[^>]*>.*?</field>' % f, re.S),
        re.compile(r'<alias [^>]*field="%s"[^>]*/>' % f),
        re.compile(r'<policy [^>]*field="%s"[^>]*/>' % f),
        re.compile(r'<default [^>]*field="%s"[^>]*/>' % f),
        re.compile(r'<constraint [^>]*field="%s"[^>]*/>' % f),
        re.compile(r'<column name="%s"[^>]*/>' % f),
        re.compile(r'<field name="%s" editable[^>]*/>' % f),
        re.compile(r'<field name="%s" labelOnTop[^>]*/>' % f),
        re.compile(r'<field reuseLastValue="0" name="%s"[^>]*/>' % f),
    ]


def opt(parent, name, otype=None, value=None):
    e = ET.SubElement(parent, "Option")
    e.set("name", name)
    if otype is not None:
        e.set("type", otype)
    if value is not None:
        e.set("value", value)
    return e


def widget_block(field, layer_name, key, value, gpkg_path):
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
    for f in OLD_FIELDS:
        if f not in cols:
            print(f"column {f}: already dropped")
            continue
        n = cur.execute(f'SELECT COUNT(*) FROM "{LAYER}" '
                        f'WHERE "{f}" IS NOT NULL AND "{f}" != \'\'').fetchone()[0]
        if n:
            bail(f"refusing to drop {f}: {n} feature(s) carry a value")
        cur.execute(f'ALTER TABLE "{LAYER}" DROP COLUMN "{f}"')
        print(f"column {f}: dropped")
    for f, *_ in SPEC:
        if f in cols:
            print(f"column {f}: already present")
        else:
            cur.execute(f'ALTER TABLE "{LAYER}" ADD COLUMN "{f}" TEXT(100)')
            print(f"column {f}: added")
    con.commit()
    cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{LAYER}")')]
    qgis_cols = [c for c in cols if c != "geom"]
    qgis_index = {f: qgis_cols.index(f) for f, *_ in SPEC}

    # --- styleQML ---
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
        print("label expression: mineral/texture modifiers injected")

    # 2. Scrub the old fields.
    removed = 0
    for f in OLD_FIELDS:
        for pat in old_field_patterns(f):
            qml, n = pat.subn("", qml)
            removed += n
    print(f"old-field styleQML references removed: {removed}"
          if removed else "old-field styleQML references: already removed")

    # 3. New field config (skip whole step per field if its widget exists).
    for field, layer_name, key, value, alias, _vis in SPEC:
        if f'<field name="{field}" configurationFlags' in qml:
            print(f"{field}: config already present")
            continue
        idx = qgis_index[field]
        qml = insert_before(qml, "</fieldConfiguration>",
                            widget_block(field, layer_name, key, value, gpkg))
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

    # 4. Form containers, inserted after ContactType in the General tab.
    if '<attributeEditorContainer name="Lith1 Mineral 1"' in qml:
        print("form containers: already present")
    else:
        anchor = re.search(
            r'<attributeEditorField\b[^>]*name="ContactType".*?</attributeEditorField>',
            qml, re.S)
        if not anchor:
            bail("ContactType form field not found")
        blocks = "".join(container_block(f, alias, vis, qgis_index[f])
                         for f, _l, _k, _v, alias, vis in SPEC)
        qml = qml[:anchor.end()] + blocks + qml[anchor.end():]
        print("form containers: injected with progressive visibility")

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

    # --- Validate everything round-trips. ---
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    final = cur.fetchone()[0]
    root = ET.fromstring(final)
    print(f"QML parses: {LAYER}")

    assert root.find(".//labeling/settings/text-style").get("fieldName") == LABEL_EXPR
    for f in OLD_FIELDS:
        assert f not in final, f"{f} still referenced in styleQML"
        assert f not in cols, f"{f} column still present"

    widgets = {fl.get("name"): fl.find("editWidget")
               for fl in root.find("fieldConfiguration")}
    aliases = {a.get("field"): a.get("name") for a in root.find("aliases")}
    containers = {}
    for c in root.iter("attributeEditorContainer"):
        for fld in c.findall("attributeEditorField"):
            containers[fld.get("name")] = c
    for field, layer_name, key, value, alias, vis in SPEC:
        assert field in cols, f"{field} column missing"
        ew = widgets.get(field)
        assert ew is not None and ew.get("type") == "ValueRelation", field
        opts = {o.get("name"): o.get("value") for o in ew.iter("Option")}
        assert opts.get("Key") == key and opts.get("Value") == value \
            and opts.get("LayerName") == layer_name, f"{field} widget options wrong"
        assert aliases.get(field) == alias, f"{field} alias wrong"
        c = containers.get(field)
        assert c is not None and c.get("visibilityExpressionEnabled") == "1" \
            and c.get("visibilityExpression") == vis, f"{field} container/visibility wrong"
    renderer = root.find(".//renderer-v2")
    assert renderer.get("type") == "categorizedSymbol" and renderer.get("attr") == "Lithology1"
    print(f"round-trip ok: 8 fields (widgets, aliases, visibility containers), "
          f"label expression, old fields gone, renderer untouched "
          f"({len(renderer.find('categories'))} categories)")
    con.close()


if __name__ == "__main__":
    main()
