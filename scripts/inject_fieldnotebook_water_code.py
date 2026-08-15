"""WTR - Water observation code for 1 - FieldNotebook.

UG paper-mapping parity: water is annotated wherever it occurs
("Trickling water", "FLT H2O", "DDH loading H2O?").  One code (user
decision 2026-08-15 - severity/description goes in Comments, which the
dynamic callout system already renders):

    FieldNotebookCodes: WTR / 'Water' (Type=FieldObservation,
    SymbolType=Point), fid 101.

Renderer: category cloned from OBS - a water-blue circle at 1.8 MM
(OBS's 0.4 MM dot is too small for a hazard-relevant observation).
The FieldNotebook styleSLD is deliberately untouched: it is not
maintained per-code for this layer (91 stale rules vs 101 categories).

Idempotent and re-runnable; QML parse-validated BEFORE writing.

Usage:  python scripts/inject_fieldnotebook_water_code.py [path\\to\\gpkg]
"""
import os
import re
import sqlite3
import sys
import uuid
import xml.etree.ElementTree as ET

LAYER = "1 - FieldNotebook"
TABLE = "FieldNotebookCodes"
CODE = "WTR"
DESC = "Water"
FID = 101
SYMBOL_NAME = "101"   # current max renderer symbol name = 100
CLONE_SOURCE = "OBS"
BLUE = "33,113,181,255"
SIZE_MM = "1.8"


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def symbol_span(q, name):
    m = re.search(r'<symbol\b[^>]*\bname="%s"[^>]*>' % re.escape(name), q)
    if not m:
        bail(f"symbol {name!r} not found")
    depth = 0
    for t in re.finditer(r'<symbol\b|</symbol>', q[m.start():]):
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

    row_exists = cur.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE Code=?", (CODE,)).fetchone()[0]

    qml, = cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                       (LAYER,)).fetchone()
    original = qml
    rm = re.search(r'<renderer-v2\b.*?</renderer-v2>', qml, re.S)
    if not rm:
        bail("renderer-v2 not found")
    renderer = rm.group(0)
    cat_exists = f'value="{CODE}"' in renderer

    if row_exists != (1 if cat_exists else 0):
        bail("table/renderer state out of step")

    if not cat_exists:
        cm = re.search(r'<category[^>]*value="%s"[^>]*/>' % CLONE_SOURCE, renderer)
        if not cm:
            bail(f"category {CLONE_SOURCE!r} not found")
        src_sym = re.search(r'symbol="(\d+)"', cm.group(0)).group(1)
        s, e = symbol_span(renderer, src_sym)
        sym = ET.fromstring(renderer[s:e])
        sym.set("name", SYMBOL_NAME)
        lyr = sym.find("layer")
        if lyr is None or lyr.get("class") != "SimpleMarker":
            bail("OBS symbol shape unexpected")
        lyr.set("id", "{%s}" % uuid.uuid5(uuid.NAMESPACE_URL, "lgs-water:0"))
        opts = {o.get("name"): o for o in lyr.find("Option").findall("Option")}
        opts["color"].set("value", BLUE)
        opts["size"].set("value", SIZE_MM)
        cat = ('<category render="true" type="string" label="%s" value="%s" '
               'uuid="%s" symbol="%s"/>'
               % (DESC, CODE,
                  "{%s}" % uuid.uuid5(uuid.NAMESPACE_URL, "lgs-water-cat"),
                  SYMBOL_NAME))
        i = renderer.index("</categories>")
        renderer = renderer[:i] + cat + renderer[i:]
        i = renderer.index("</symbols>")
        renderer = renderer[:i] + ET.tostring(sym, encoding="unicode") + renderer[i:]
        qml = qml[:rm.start()] + renderer + qml[rm.end():]
        print(f"{CODE}: category + symbol {SYMBOL_NAME} (blue circle {SIZE_MM} MM)")
    else:
        print(f"{CODE}: category already present")

    try:
        ET.fromstring(qml)
    except ET.ParseError as exc:
        bail(f"edited QML no longer parses: {exc}")

    if not row_exists:
        cur.execute(f"INSERT INTO {TABLE} (fid, Type, Code, Description, UUID, "
                    "SymbolType) VALUES (?,?,?,?,?,?)",
                    (FID, "FieldObservation", CODE, DESC,
                     str(uuid.uuid5(uuid.NAMESPACE_URL, "lgs-water-row")),
                     "Point"))
        print(f"{TABLE}: {CODE} row added (fid {FID})")
    if qml != original:
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, LAYER))
        assert cur.rowcount == 1
    con.commit()

    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    q, = cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                     (LAYER,)).fetchone()
    root = ET.fromstring(q)
    print(f"QML parses: {LAYER}")
    assert cur.execute(f"SELECT Type, Description, SymbolType FROM {TABLE} "
                       "WHERE Code=?", (CODE,)).fetchone() == \
        ("FieldObservation", DESC, "Point")
    cats = root.find(".//renderer-v2/categories").findall("category")
    assert sum(1 for c in cats if c.get("value") == CODE) == 1
    syms = {s.get("name") for s in root.find(".//renderer-v2/symbols")}
    assert SYMBOL_NAME in syms
    print(f"round-trip ok: WTR row + category + symbol ({len(cats)} categories)")
    con.close()


if __name__ == "__main__":
    main()
