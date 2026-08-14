"""Scope the Overlay "Intensity" field to Alteration polygons only.

Sibling of inject_overlay_weight_scope.py. Intensity (1-5) drives the
Alteration/Weathering stipple symbology, but Weathering renders at the
authored (Intensity 3 / NULL) look by convention - only Alteration
features actually record an intensity. Two fixes to "2 - Overlay":

    1. Constraint: hard not-null on Intensity -> expression constraint,
       required only when Type = 'Alteration'.
    2. Default: 3 (stamped on every feature) -> applyOnUpdate CASE that
       fills 3 for Alteration (preserving a manual choice) and keeps
       Intensity NULL elsewhere. NULL renders identically to 3.

The form already shows Intensity only on the Alteration tab - that
placement is verified, not changed.

Idempotent and re-runnable.

Usage:  python scripts/inject_overlay_intensity_scope.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

LAYER = "2 - Overlay"

CONSTRAINT_TAG = ('<constraint constraints="4" notnull_strength="0" '
                  'field="Intensity" unique_strength="0" exp_strength="1"/>')
CONSTRAINT_EXPR = ("\"Type\" IS NULL OR \"Type\" != 'Alteration' "
                   "OR \"Intensity\" IS NOT NULL")
CONSTRAINT_DESC = "Intensity is required for Alteration"
DEFAULT_EXPR = ("CASE WHEN \"Type\" = 'Alteration' "
                "THEN COALESCE(\"Intensity\", 3) ELSE NULL END")


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


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

    # 1. Constraint: not-null everywhere -> expression, Alteration only.
    m = re.search(r'<constraint\b(?![^>]*\bexp=)[^>]*field="Intensity"[^>]*/>', qml)
    if not m:
        bail("Intensity <constraint> tag not found")
    if m.group(0) != CONSTRAINT_TAG:
        qml = qml[:m.start()] + CONSTRAINT_TAG + qml[m.end():]
        changed = True
        print("constraint: scoped to expression")
    else:
        print("constraint: already applied")

    m = re.search(r'<constraint\b[^>]*field="Intensity"[^>]*\bexp=[^>]*/>', qml)
    if not m:
        bail("Intensity constraint-expression tag not found")
    new_tag = ('<constraint desc=%s field="Intensity" exp=%s/>'
               % (quoteattr(CONSTRAINT_DESC), quoteattr(CONSTRAINT_EXPR)))
    if m.group(0) != new_tag:
        qml = qml[:m.start()] + new_tag + qml[m.end():]
        changed = True
        print("constraint expression: set")
    else:
        print("constraint expression: already applied")

    # 2. Default: Alteration-only 3 (applyOnUpdate, manual choice wins).
    m = re.search(r'<default\b[^>]*field="Intensity"[^>]*/>', qml)
    if not m:
        bail("Intensity <default> tag not found")
    new_tag = ('<default expression=%s applyOnUpdate="1" field="Intensity"/>'
               % quoteattr(DEFAULT_EXPR))
    if m.group(0) != new_tag:
        qml = qml[:m.start()] + new_tag + qml[m.end():]
        changed = True
        print("default: Alteration-only 3")
    else:
        print("default: already applied")

    # Validate BEFORE writing: never persist a QML that no longer parses.
    try:
        ET.fromstring(qml)
    except ET.ParseError as exc:
        bail(f"edited QML no longer parses, aborting without write: {exc}")

    if changed:
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, LAYER))
        assert cur.rowcount == 1
        con.commit()

    # Validate: gpkg intact, QML parses, edits + form placement round-trip.
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    root = ET.fromstring(cur.fetchone()[0])
    print(f"QML parses: {LAYER}")

    c = next(c for c in root.iter("constraint")
             if c.get("field") == "Intensity" and c.get("exp") is None)
    assert (c.get("constraints"), c.get("notnull_strength"),
            c.get("exp_strength")) == ("4", "0", "1"), "constraint attrs wrong"
    ce = next(c for c in root.iter("constraint")
              if c.get("field") == "Intensity" and c.get("exp") is not None)
    assert ce.get("exp") == CONSTRAINT_EXPR, "constraint expression wrong"
    d = next(d for d in root.iter("default") if d.get("field") == "Intensity")
    assert (d.get("expression"), d.get("applyOnUpdate")) == (DEFAULT_EXPR, "1")
    containers = {f.get("name"): c.get("name")
                  for c in root.iter("attributeEditorContainer")
                  for f in c.findall("attributeEditorField")}
    assert containers.get("Intensity") == "Alteration", "Intensity placement wrong"
    assert containers.get("Weight") == "Structure", "Weight placement disturbed"
    print("round-trip ok: constraint, expression, default, form placement")
    con.close()


if __name__ == "__main__":
    main()
