"""Inject Sample auto-default expressions into the FieldNotebook form config.

Sets default-value expressions (applyOnUpdate) on two "1 - FieldNotebook"
fields so the attribute form fills itself when logging a sample:

    Subtype1:  Type = 'Sample'  ->  'Sample'
               (the only valid Subtype1 for samples; the field is not-null,
               so this removes a mandatory tap)
    Label:     Type = 'Sample' and Label unfilled  ->  SampleID
               (Label drives the map labeling rule; a manually typed Label
               is never overwritten)

Both follow the layer's existing DipDirection idiom: applyOnUpdate="1" with
the field's own current value as the ELSE fallback, so the auto-set never
clobbers a manual entry on non-Sample features.

Idempotent and re-runnable: a tag already carrying the target expression is
reported as "already applied" and left untouched.

Usage:  python scripts/inject_fieldnotebook_sample_defaults.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

LAYER = "1 - FieldNotebook"

DEFAULTS = {
    "Subtype1":
        "CASE WHEN \"Type\" = 'Sample' THEN 'Sample' "
        "ELSE \"Subtype1\" END",
    "Label":
        "CASE WHEN \"Type\" = 'Sample' AND (\"Label\" IS NULL OR trim(\"Label\") = '') "
        "THEN \"SampleID\" ELSE \"Label\" END",
}


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


def find_default_tag(qml, field):
    """Find a field's <default> tag in a styleQML (order-agnostic)."""
    for m in re.finditer(r"<default\b[^>]*>", qml):
        tag = m.group(0)
        fm = re.search(r'field="([^"]*)"', tag)
        if fm and fm.group(1) == field:
            return tag
    return None


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    row = cur.fetchone()
    if not row or not row[0]:
        bail(f"no styleQML for {LAYER!r}")
    qml = row[0]

    changed = False
    for field, expr in DEFAULTS.items():
        tag = find_default_tag(qml, field)
        if tag is None:
            bail(f"<default> tag for field {field!r} not found")
        new_tag = re.sub(r'expression="[^"]*"',
                         lambda _m: "expression=" + quoteattr(expr), tag)
        new_tag = re.sub(r'applyOnUpdate="[^"]*"', 'applyOnUpdate="1"', new_tag)
        if new_tag == tag:
            print(f"{field}: already applied")
            continue
        if qml.count(tag) != 1:
            bail(f"<default> tag for {field!r} is not unique in the QML")
        qml = qml.replace(tag, new_tag, 1)
        changed = True
        print(f"{field}: default injected")

    if changed:
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, LAYER))
        assert cur.rowcount == 1
        con.commit()

    # Validate: gpkg intact, QML still parses, expressions round-trip.
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    root = ET.fromstring(cur.fetchone()[0])
    print(f"QML parses: {LAYER}")
    stored = {d.get("field"): d for d in root.iter("default")}
    for field, expr in DEFAULTS.items():
        d = stored.get(field)
        if d is None or d.get("expression") != expr or d.get("applyOnUpdate") != "1":
            bail(f"round-trip check failed for {field!r}")
        print(f"round-trip ok: {field}")
    con.close()


if __name__ == "__main__":
    main()
