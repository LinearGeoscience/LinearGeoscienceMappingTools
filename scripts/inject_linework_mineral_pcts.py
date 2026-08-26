"""Linework per-mineral percentages (Aug 2026 field feedback).

The vein detail block carried a SINGLE 'Mineral %' field (Percent);
paper mapping records a percentage per mineral ("ga 5% cpy 2%").  Adds:

    - Mineral1Pct / Mineral2Pct / Mineral3Pct (0-100 spinbox, optional),
      each in its own container directly after its mineral's container,
      visible only once that mineral is filled (progressive disclosure)
      - the FieldNotebook pattern, adapted to Linework's one-field-per-
      container form layout.  Labels are ITALIC (labelStyle override).

    - The old 'Mineral %' (Percent) form container is retired; the
      column and any recorded data stay in the table.

    - The auto label tag renders each mineral with its own percentage
      ("5mm ga5%-cpy2%" instead of "5mm ga-cpy 5%").  The expression is
      wrapped by later injectors (Confidence suffix), so the swap is a
      targeted substring replacement of the minerals+percent segments.

Run AFTER inject_linework_detail_scope.py - the visibility gates reuse
its broadened detail scope.

Idempotent and re-runnable; QML validated with ElementTree BEFORE
anything is written.

Usage:  python scripts/inject_linework_mineral_pcts.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

LAYER = "2 - Linework"

DETAIL_VIS = ("(\"Category\" IN ('Veins','Lithology') "
              "OR \"Type\" LIKE 'Fault%' OR \"Type\" LIKE 'Shear%' "
              "OR \"Type\" IN ('Shear Zone Boundary','Detachment'))")

# field, alias, gating mineral, host container (inserted after it)
SPEC = [
    ("Mineral1Pct", "Mineral 1 %", "Mineral1", "Mineral 1"),
    ("Mineral2Pct", "Mineral 2 %", "Mineral2", "Mineral 2"),
    ("Mineral3Pct", "Mineral 3 %", "Mineral3", "Mineral 3"),
]

# Italic QFont: description slot 5 is the style/italic flag.
ITALIC_FONT_DESC = "MS Shell Dlg 2,8.1,-1,5,50,1,0,0,0,0"

# --- label expression segments (verbatim from inject_linework_vein_fields) ---
OLD_MINERALS_TEXT = (
    "array_to_string(array_remove_all(array("
    "coalesce(\"Mineral1\",''), coalesce(\"Mineral2\",''), "
    "coalesce(\"Mineral3\",'')), ''), '-')"
)
OLD_PERCENT_TEXT = ("CASE WHEN \"Percent\" IS NULL THEN '' "
                    "ELSE \"Percent\" || '%' END")


def mineral_piece(n):
    """'Qz(60%)' - the mineral code with its percentage bracketed onto it.

    Bracketed, not glued: a bare 'Qz60%' next to a vein width reads as two
    unrelated numbers, and the whole point of the label grammar is that a
    value is attached to the thing it measures.  Identical in shape to
    inject_basemap_mineral_pcts.mineral_token, so the two layers say the
    same thing the same way.

    coalesce(...) > 0 rather than IS NOT NULL: a percentage of zero is not
    a reading, and 'Qz(0%)' on the map is worse than plain 'Qz' (same guard
    as inject_label_size_scaling.WIDTH_F).
    """
    return ("coalesce(\"Mineral{n}\",'') || "
            "CASE WHEN coalesce(\"Mineral{n}\",'') != '' "
            "AND coalesce(\"Mineral{n}Pct\", 0) > 0 "
            "THEN '(' || \"Mineral{n}Pct\" || '%)' ELSE '' END").format(n=n)


NEW_MINERALS_TEXT = (
    "array_to_string(array_remove_all(array("
    + mineral_piece(1) + ", " + mineral_piece(2) + ", "
    + mineral_piece(3) + "), ''), '-')"
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
    ls = ET.SubElement(f, "labelStyle")
    ls.set("overrideLabelFont", "1")
    ls.set("labelColor", "0,0,0,255,rgb:0,0,0,1")
    ls.set("overrideLabelColor", "0")
    lf = ET.SubElement(ls, "labelFont")
    for k, v in [("style", ""), ("strikethrough", "0"), ("bold", "0"),
                 ("description", ITALIC_FONT_DESC), ("italic", "1"),
                 ("underline", "0")]:
        lf.set(k, v)
    return ET.tostring(c, encoding="unicode")


def insert_before(qml, closing_tag, fragment):
    i = qml.find(closing_tag)
    if i < 0 or qml.find(closing_tag, i + 1) >= 0:
        bail(f"{closing_tag!r} not found or not unique")
    return qml[:i] + fragment + qml[i:]


def container_span(qml, name):
    # The detail containers hold a single attributeEditorField - no
    # nesting, so the non-greedy close is the right close.
    m = re.search(r'<attributeEditorContainer\b[^>]*\bname=%s[^>]*>.*?'
                  r'</attributeEditorContainer>'
                  % re.escape(quoteattr(name)), qml, re.S)
    if not m:
        bail(f"container {name!r} not found")
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
    for pre in ("Mineral1", "Mineral2", "Mineral3", "Percent"):
        if pre not in cols:
            bail(f"prerequisite column {pre} missing on {LAYER!r}")
    for f, *_ in SPEC:
        if f in cols:
            print(f"column {f}: already present")
        else:
            cur.execute(f'ALTER TABLE "{LAYER}" ADD COLUMN "{f}" MEDIUMINT')
            print(f"column {f}: added (MEDIUMINT)")
    con.commit()
    cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{LAYER}")')]
    qgis_cols = [c for c in cols if c != "geom"]
    qgis_index = {f: qgis_cols.index(f) for f, *_ in SPEC}

    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    row = cur.fetchone()
    if not row or not row[0]:
        bail(f"no styleQML for {LAYER!r}")
    qml = original = row[0]

    # 1. New field config.
    for field, alias, _min, _host in SPEC:
        if f'<field name="{field}" configurationFlags' in qml:
            print(f"{field}: config already present")
            continue
        idx = qgis_index[field]
        qml = insert_before(qml, "</fieldConfiguration>", percent_widget(field))
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

    # 2. Form containers, each a sibling after its mineral's container.
    for field, alias, mineral, host in SPEC:
        if f'<attributeEditorContainer name={quoteattr(alias)}' in qml \
                or f'<attributeEditorContainer name="{alias}"' in qml:
            print(f"container {alias}: already present")
            continue
        anchor = container_span(qml, host)
        vis = DETAIL_VIS + f" AND coalesce(\"{mineral}\",'') != ''"
        block = container_block(field, alias, vis, qgis_index[field])
        qml = qml[:anchor.end()] + block + qml[anchor.end():]
        print(f"container {alias}: inserted after container {host!r}")

    # 3. Retire the old single 'Mineral %' container (column stays).
    pm = re.search(r'<attributeEditorContainer\b[^>]*\bname="Mineral %"[^>]*>'
                   r'.*?</attributeEditorContainer>', qml, re.S)
    if pm:
        qml = qml[:pm.start()] + qml[pm.end():]
        print("container 'Mineral %': removed (Percent column retained)")
    else:
        print("container 'Mineral %': already absent")

    # 4. Label tag: per-mineral percentages.
    lm = re.search(r'<labeling type="simple">.*?</labeling>', qml, re.S)
    if not lm:
        bail("simple labeling block not found")
    lab = ET.fromstring(lm.group(0))
    ts = lab.find(".//text-style")
    expr = ts.get("fieldName")
    old_segment = OLD_MINERALS_TEXT + ", " + OLD_PERCENT_TEXT
    if NEW_MINERALS_TEXT in expr:
        print("label: per-mineral percentages already applied")
    elif old_segment in expr:
        ts.set("fieldName", expr.replace(old_segment, NEW_MINERALS_TEXT))
        qml = (qml[:lm.start()] + ET.tostring(lab, encoding="unicode")
               + qml[lm.end():])
        print("label: minerals+percent segment -> per-mineral percentages")
    else:
        bail("label expression carries neither the old minerals+percent "
             "segment nor the new one: %r" % expr[:120])

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

    widgets = {fl.get("name"): fl.find("editWidget")
               for fl in root.find("fieldConfiguration")}
    aliases = {a.get("field"): a.get("name") for a in root.find("aliases")}
    containers = {}
    for c in root.iter("attributeEditorContainer"):
        for fld in c.findall("attributeEditorField"):
            containers[fld.get("name")] = (c, fld)
    assert "Percent" not in containers, "old Percent container still present"
    for field, alias, mineral, _host in SPEC:
        assert field in cols, f"{field} column missing"
        ew = widgets.get(field)
        assert ew is not None and ew.get("type") == "Range", field
        assert aliases.get(field) == alias, f"{field} alias wrong"
        c, fld = containers.get(field)
        assert c.get("visibilityExpressionEnabled") == "1" and \
            mineral in c.get("visibilityExpression") and \
            "Lithology" in c.get("visibilityExpression"), f"{field} visibility wrong"
        ls = fld.find("labelStyle")
        assert ls is not None and ls.get("overrideLabelFont") == "1" and \
            ls.find("labelFont").get("italic") == "1", f"{field} label not italic"
    ts = root.find(".//labeling/settings/text-style")
    assert NEW_MINERALS_TEXT in ts.get("fieldName") and \
        OLD_PERCENT_TEXT not in ts.get("fieldName")
    print("round-trip ok: 3 italic per-mineral % fields, Percent container "
          "retired, per-mineral label tags")
    con.close()


if __name__ == "__main__":
    main()
