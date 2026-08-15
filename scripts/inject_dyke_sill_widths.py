"""Thicken dyke/sill linework (Aug 2026 field feedback).

The Lithology-category lines rendered at hairline weights - every dyke
type and Sill at 1.0 mm, Pegmatite at 1.46 mm - visually lighter than
veins (1.46) and far lighter than faults/shears (2.26).  Intrusive
bodies are map-defining features; bump them all to 1.8 mm, clearly
heavier than veins while staying below the fault/shear tier.

Edits the SimpleLine line_width STATICS in the '3 - Linework' renderer
only.  Re-run inject_weight_scaling.py afterwards - it rebuilds the
Weight/width data-defined expressions from the current statics, so the
overrides pick up the new 1.8 base (the established re-bake rule).

Idempotent and re-runnable; QML validated with ElementTree BEFORE
anything is written.

Usage:  python scripts/inject_dyke_sill_widths.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

LAYER = "3 - Linework"
NEW_WIDTH = "1.8"
# Every Lithology-category code (LineworkCodes Type='Lithology').
TARGET_TYPES = [
    "Aplite Dykes", "Carbonatite Dykes", "Dolerite Dykes", "Felsic Dykes",
    "Intermediate Dykes", "Lamprophyre Dykes", "Mafic Dykes", "Pegmatite",
    "Porphyry Dykes", "Sill", "Ultramafic Dykes",
]


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


def symbol_block(qml, name):
    m = re.search(r'<symbol\b[^>]*\bname="%s"[^>]*>' % re.escape(name), qml)
    if not m:
        bail(f"symbol {name!r} not found")
    depth = 0
    for t in re.finditer(r'<symbol\b|</symbol>', qml[m.start():]):
        depth += 1 if t.group(0) == '<symbol' else -1
        if depth == 0:
            return m.start(), m.start() + t.end()
    bail(f"unbalanced symbol {name!r}")


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

    changed = 0
    for code in TARGET_TYPES:
        cm = re.search(r'<category[^>]*value="%s"[^>]*/>' % re.escape(code), qml)
        if not cm:
            bail(f"category {code!r} not found")
        sym = re.search(r'symbol="(\d+)"', cm.group(0)).group(1)
        s, e = symbol_block(qml, sym)
        block = qml[s:e]
        wm = re.search(r'(<Option name="line_width" type="QString" value=")([^"]+)(")',
                       block)
        if not wm:
            bail(f"{code}: no SimpleLine line_width static in symbol {sym}")
        old = wm.group(2)
        if old == NEW_WIDTH:
            print(f"{code}: already {NEW_WIDTH}")
            continue
        block = block[:wm.start()] + wm.group(1) + NEW_WIDTH + wm.group(3) \
            + block[wm.end():]
        qml = qml[:s] + block + qml[e:]
        changed += 1
        print(f"{code}: line_width {old} -> {NEW_WIDTH}")

    try:
        ET.fromstring(qml)
    except ET.ParseError as exc:
        bail(f"edited QML no longer parses, aborting without write: {exc}")

    if qml != original:
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, LAYER))
        assert cur.rowcount == 1
        con.commit()
        print(f"styleQML updated ({changed} symbols)")
    else:
        print("styleQML: no change")

    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    root = ET.fromstring(cur.fetchone()[0])
    cats = {c.get("value"): c.get("symbol")
            for c in root.find(".//renderer-v2/categories")}
    syms = {s.get("name"): s for s in root.find(".//renderer-v2/symbols")}
    for code in TARGET_TYPES:
        sym = syms[cats[code]]
        widths = [o.get("value") for o in sym.iter("Option")
                  if o.get("name") == "line_width"]
        assert NEW_WIDTH in widths, (code, widths)
    print(f"round-trip ok: {len(TARGET_TYPES)} Lithology symbols at {NEW_WIDTH}")
    con.close()


if __name__ == "__main__":
    main()
