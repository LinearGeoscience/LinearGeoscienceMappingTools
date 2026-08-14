"""Scope the Overlay "Weight" field to Structure zones only.

Weight (Major/Moderate/Minor) only drives the Structure zone symbology
(see inject_weight_scaling.py — Alteration/Weathering use Intensity, and
Infrastructure is untouched), but the form config required it everywhere
and showed it on the Alteration tab. Three fixes to "2 - Overlay":

    1. Constraint: hard not-null on Weight -> expression constraint,
       required only when Type = 'Structure'.
    2. Form layout: the Weight field moves from the Alteration container
       to the Structure container (after SubType1).
    3. Default: 'Moderate' (stamped on every feature) -> applyOnUpdate
       CASE that fills 'Moderate' for Structure zones (preserving a manual
       choice, DipDirection idiom) and keeps Weight NULL elsewhere.

Intensity gets the equivalent treatment in inject_overlay_intensity_scope.py.

Idempotent and re-runnable.

Usage:  python scripts/inject_overlay_weight_scope.py [path\\to\\gpkg]
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
                  'field="Weight" unique_strength="0" exp_strength="1"/>')
CONSTRAINT_EXPR = ("\"Type\" IS NULL OR \"Type\" != 'Structure' "
                   "OR \"Weight\" IS NOT NULL")
CONSTRAINT_DESC = "Weight is required for Structure zones"
DEFAULT_EXPR = ("CASE WHEN \"Type\" = 'Structure' "
                "THEN COALESCE(\"Weight\", 'Moderate') ELSE NULL END")


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


def container_span(qml, name):
    """(start, end) of a form container that holds no nested containers."""
    m = re.search(r'<attributeEditorContainer\b[^>]*name="%s"[^>]*>' % name, qml)
    if not m:
        bail(f"container {name!r} not found")
    end = qml.find("</attributeEditorContainer>", m.end())
    if end < 0 or "<attributeEditorContainer" in qml[m.end():end]:
        bail(f"container {name!r} has unexpected nesting")
    return m.start(), end


def field_block(qml, field, start=0, end=None):
    m = re.search(
        r'<attributeEditorField\b[^>]*name="%s".*?</attributeEditorField>' % field,
        qml[start:end if end is not None else len(qml)], re.S)
    return (start + m.start(), start + m.end()) if m else None


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

    # 1. Constraint: not-null everywhere -> expression, Structure only.
    m = re.search(r'<constraint\b(?![^>]*\bexp=)[^>]*field="Weight"[^>]*/>', qml)
    if not m:
        bail("Weight <constraint> tag not found")
    if m.group(0) != CONSTRAINT_TAG:
        qml = qml[:m.start()] + CONSTRAINT_TAG + qml[m.end():]
        changed = True
        print("constraint: scoped to expression")
    else:
        print("constraint: already applied")

    m = re.search(r'<constraint\b[^>]*field="Weight"[^>]*\bexp=[^>]*/>', qml)
    if not m:
        bail("Weight constraint-expression tag not found")
    new_tag = ('<constraint desc=%s field="Weight" exp=%s/>'
               % (quoteattr(CONSTRAINT_DESC), quoteattr(CONSTRAINT_EXPR)))
    if m.group(0) != new_tag:
        qml = qml[:m.start()] + new_tag + qml[m.end():]
        changed = True
        print("constraint expression: set")
    else:
        print("constraint expression: already applied")

    # 2. Form layout: Weight moves Alteration -> Structure (after SubType1).
    alt = container_span(qml, "Alteration")
    struct = container_span(qml, "Structure")
    in_alt = field_block(qml, "Weight", *alt)
    in_struct = field_block(qml, "Weight", *struct)
    if in_alt and not in_struct:
        # Move the exact balanced block; parts of this XML region jam close
        # and open tags onto one line, so no line/indent assumptions.
        s, e = in_alt
        block = qml[s:e]
        qml = qml[:s] + qml[e:]
        struct = container_span(qml, "Structure")
        sub = field_block(qml, "SubType1", *struct)
        if not sub:
            bail("SubType1 not found in Structure container")
        qml = qml[:sub[1]] + block + qml[sub[1]:]
        changed = True
        print("form layout: Weight moved Alteration -> Structure")
    elif in_struct and not in_alt:
        print("form layout: already applied")
    else:
        bail("unexpected Weight placement (found in: %s)"
             % ", ".join(n for n, b in [("Alteration", in_alt),
                                        ("Structure", in_struct)] if b))

    # 3. Default: Structure-only 'Moderate' (applyOnUpdate, manual choice wins).
    m = re.search(r'<default\b[^>]*field="Weight"[^>]*/>', qml)
    if not m:
        bail("Weight <default> tag not found")
    new_tag = ('<default expression=%s applyOnUpdate="1" field="Weight"/>'
               % quoteattr(DEFAULT_EXPR))
    if m.group(0) != new_tag:
        qml = qml[:m.start()] + new_tag + qml[m.end():]
        changed = True
        print("default: Structure-only Moderate")
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

    # Validate: gpkg intact, QML parses, all three edits round-trip.
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    root = ET.fromstring(cur.fetchone()[0])
    print(f"QML parses: {LAYER}")

    c = next(c for c in root.iter("constraint")
             if c.get("field") == "Weight" and c.get("exp") is None)
    assert (c.get("constraints"), c.get("notnull_strength"),
            c.get("exp_strength")) == ("4", "0", "1"), "constraint attrs wrong"
    ce = next(c for c in root.iter("constraint")
              if c.get("field") == "Weight" and c.get("exp") is not None)
    assert ce.get("exp") == CONSTRAINT_EXPR, "constraint expression wrong"
    d = next(d for d in root.iter("default") if d.get("field") == "Weight")
    assert (d.get("expression"), d.get("applyOnUpdate")) == (DEFAULT_EXPR, "1")
    containers = {f.get("name"): c.get("name")
                  for c in root.iter("attributeEditorContainer")
                  for f in c.findall("attributeEditorField")}
    assert containers.get("Weight") == "Structure", "Weight not in Structure tab"
    assert containers.get("Intensity") == "Alteration", "Intensity moved unexpectedly"
    print("round-trip ok: constraint, expression, default, form placement")
    con.close()


if __name__ == "__main__":
    main()
