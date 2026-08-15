"""FieldNotebook per-mineral percentages.

QField attribute-copy parity (Aug 2026): the sidecar Copy Attributes
tool stamps Basemap modal mineralogy onto Field Notebook points
(Lith1Mineral1..3 -> Mineral/Mineral2/Mineral3).  Basemap carries a
percentage per mineral slot (inject_basemap_mineral_pcts.py) but
'1 - FieldNotebook' has only the single 'Vein %', so the percentages
had nowhere to land.  Adds:

    - MineralPct / Mineral2Pct / Mineral3Pct (0-100 spinbox, optional),
      each appearing only once its mineral is filled (progressive
      disclosure, the family convention).

Unlike the Basemap form (one group box per field), the FieldNotebook
form keeps the mineral fields flat inside the 'Lithology' group box,
so each Pct field is wrapped in its own borderless visibility-gated
container inserted directly after its mineral's attributeEditorField.
Labels are untouched.

Idempotent and re-runnable; QML validated with ElementTree BEFORE
anything is written.

Usage:  python scripts/inject_fieldnotebook_mineral_pcts.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

LAYER = "1 - FieldNotebook"

# field, sql type, alias, visibility expression, insert-after form field
SPEC = [
    ("MineralPct", "MEDIUMINT", "Mineral %",
     "coalesce(\"Mineral\",'') != ''", "Mineral"),
    ("Mineral2Pct", "MEDIUMINT", "Mineral 2 %",
     "coalesce(\"Mineral2\",'') != ''", "Mineral2"),
    ("Mineral3Pct", "MEDIUMINT", "Mineral 3 %",
     "coalesce(\"Mineral3\",'') != ''", "Mineral3"),
]


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
    return ET.tostring(c, encoding="unicode")


def insert_before(qml, closing_tag, fragment):
    i = qml.find(closing_tag)
    if i < 0 or qml.find(closing_tag, i + 1) >= 0:
        bail(f"{closing_tag!r} not found or not unique")
    return qml[:i] + fragment + qml[i:]


def form_field_span(qml, name):
    m = re.search(r'<attributeEditorField name=%s.*?</attributeEditorField>'
                  % quoteattr(name), qml, re.S)
    if not m:
        bail(f"form field {name!r} not found")
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
    for pre in ("Mineral", "Mineral2", "Mineral3"):
        if pre not in cols:
            bail(f"prerequisite column {pre} missing on {LAYER!r}")
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

    # 1. New field config.
    for field, _sqltype, alias, _vis, _after in SPEC:
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

    # 2. Form containers, each after its mineral's attributeEditorField
    #    (the mineral fields sit flat in the 'Lithology' group box).
    for field, _sqltype, alias, vis, after in SPEC:
        if f'<attributeEditorContainer name={quoteattr(alias)}' in qml \
                or f'<attributeEditorContainer name="{alias}"' in qml:
            print(f"container {alias}: already present")
            continue
        anchor = form_field_span(qml, after)
        block = container_block(field, alias, vis, qgis_index[field])
        qml = qml[:anchor.end()] + block + qml[anchor.end():]
        print(f"container {alias}: inserted after form field {after!r}")

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
            containers[fld.get("name")] = c
    for field, _sqltype, alias, vis, _after in SPEC:
        assert field in cols, f"{field} column missing"
        ew = widgets.get(field)
        assert ew is not None and ew.get("type") == "Range", field
        assert aliases.get(field) == alias, f"{field} alias wrong"
        c = containers.get(field)
        assert c is not None and c.get("visibilityExpressionEnabled") == "1" \
            and c.get("visibilityExpression") == vis, f"{field} visibility wrong"
    print("round-trip ok: 3 percent fields with progressive disclosure, "
          "labels untouched")
    con.close()


if __name__ == "__main__":
    main()
