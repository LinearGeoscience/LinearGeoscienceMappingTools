"""Broaden Linework detail fields beyond veins (Aug 2026 field feedback).

The per-vein detail block (Width_cm, Mineral1-3, VeinTexture - injected
by inject_linework_vein_fields.py) was gated on Category='Veins' only,
but dykes want minerals and textures, shears have thickness, and so on.
Rewrites the visibility gate on the existing form containers to the
shared detail scope:

    Veins + Lithology categories (all dyke types, Sill, Pegmatite)
    + every Fault* / Shear* type, Shear Zone Boundary and Detachment.

('Dyke - Aeromagnetic' is Interpretation and deliberately stays out.)

The auto width-mineral label tags get the same broadened gate, so a
"10cm ga vn" style tag now renders on dykes and shears too.  The label
expression is WRAPPED by later injectors (Confidence '?' suffix), so the
gate swap is a targeted substring replacement inside the current
expression, never a whole-expression match.

The old single 'Percent' container is left alone here - it is retired by
inject_linework_mineral_pcts.py.

Idempotent and re-runnable; QML validated with ElementTree BEFORE
anything is written.

Usage:  python scripts/inject_linework_detail_scope.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

LAYER = "2 - Linework"

OLD_GATE = "\"Category\" = 'Veins'"
DETAIL_VIS = ("(\"Category\" IN ('Veins','Lithology') "
              "OR \"Type\" LIKE 'Fault%' OR \"Type\" LIKE 'Shear%' "
              "OR \"Type\" IN ('Shear Zone Boundary','Detachment'))")

# container name -> progressive-disclosure AND-clause (kept verbatim)
CONTAINERS = {
    "Width (cm)": "",
    "Mineral 1": "",
    "Mineral 2": " AND coalesce(\"Mineral1\",'') != ''",
    "Mineral 3": " AND coalesce(\"Mineral2\",'') != ''",
    "Vein Texture": "",
}


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
    qml = original = row[0]

    # 1. Container visibility gates.
    for name, tail in CONTAINERS.items():
        tm = re.search(r'<attributeEditorContainer\b[^>]*\bname=%s[^>]*>'
                       % re.escape(quoteattr(name)), qml)
        if not tm:
            bail(f"container {name!r} not found")
        tag = tm.group(0)
        vm = re.search(r'visibilityExpression="([^"]*)"', tag)
        if not vm:
            bail(f"container {name!r} has no visibilityExpression")
        current = vm.group(1)
        if "Lithology" in current:
            print(f"container {name!r}: already broadened")
            continue
        new_attr = "visibilityExpression=" + quoteattr(DETAIL_VIS + tail)
        new_tag = tag[:vm.start()] + new_attr + tag[vm.end():]
        qml = qml[:tm.start()] + new_tag + qml[tm.end():]
        print(f"container {name!r}: gate broadened")

    # 2. Label expression gate (inside the possibly-wrapped fieldName).
    lm = re.search(r'<labeling type="simple">.*?</labeling>', qml, re.S)
    if not lm:
        bail("simple labeling block not found")
    lab = ET.fromstring(lm.group(0))
    ts = lab.find(".//text-style")
    expr = ts.get("fieldName")
    gate = "CASE WHEN " + OLD_GATE + " THEN"
    if DETAIL_VIS in expr:
        print("label: gate already broadened")
    elif gate in expr:
        ts.set("fieldName", expr.replace(gate,
                                         "CASE WHEN " + DETAIL_VIS + " THEN"))
        qml = (qml[:lm.start()] + ET.tostring(lab, encoding="unicode")
               + qml[lm.end():])
        print("label: gate broadened")
    else:
        bail("label expression carries neither the Veins gate nor the "
             "broadened gate: %r" % expr[:120])

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
    containers = {c.get("name"): c for c in root.iter("attributeEditorContainer")}
    for name, tail in CONTAINERS.items():
        c = containers.get(name)
        assert c is not None, name
        assert c.get("visibilityExpression") == DETAIL_VIS + tail, name
    ts = root.find(".//labeling/settings/text-style")
    assert DETAIL_VIS in ts.get("fieldName")
    print("round-trip ok: 5 containers + label gate on the detail scope")
    con.close()


if __name__ == "__main__":
    main()
