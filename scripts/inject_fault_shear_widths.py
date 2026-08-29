"""Thin the fault/shear family (30 Aug 2026 field feedback).

Faults and shears rendered a little too heavy at every Weight tier -
the user compared Major-weight GSWA imports at 1:100k against the
published GSWA sheet and settled on trimming the family base 2.26 ->
2.0 Point, keeping the deliberate hierarchy (veins 1.46 < dykes/sills
1.8 < faults/shears 2.0; the Weight FACTORS stay global and untouched).
Terrane Boundary scales down proportionally (3 -> 2.65, its 0.8 second
stroke -> 0.71).  Shear Zone Boundary (1.46) is not part of the heavy
family and stays.

Dashes deliberately keep their authored lengths ('38;7' etc.): thinning
the stroke under a constant dash nudges the dash:width ratio up, the
direction the user already asked for at 100k.

Edits the SimpleLine line_width STATICS in the '2 - Linework' renderer
only, asserting each expected old value.  Re-run
inject_weight_scaling.py afterwards - it rebuilds the Weight/width
data-defined expressions from the current statics (the established
re-bake rule).  inject_dash_weight_scaling and inject_confidence_system
rebuild from customdash statics, which are untouched, so they stay
no-ops.

Never point this at LGS_MappingTemplate_Patterns.gpkg - that file is
re-baked wholesale by inject_basemap_lith_patterns.py.

Idempotent ladder per code: all statics at the old width (apply), all
at the new (no-op), anything else aborts without writing.

Usage:
    python scripts/inject_fault_shear_widths.py [path\\to\\file.gpkg]
"""

import os
import re
import shutil
import sqlite3
import sys
import xml.etree.ElementTree as ET

LAYER = "2 - Linework"

# code -> ordered (old, new) per SimpleLine layer in its symbol
FAMILY = [
    "Fault", "Fault - Dextral", "Fault - Normal", "Fault - Reverse",
    "Fault - Sinistral", "Fault - Strike-Slip", "Fault - Thrust",
    "Fault - Inferred", "Fault - Queried", "Fault - Concealed",
    "Shear", "Shear - Dextral", "Shear - Normal", "Shear - Reverse",
    "Shear - Sinistral", "Detachment",
]
WIDTHS = {code: [("2.26", "2")] for code in FAMILY}
WIDTHS["Terrane Boundary"] = [("3", "2.65"), ("0.8", "0.71")]

BACKUP_DATE = "2026-08-30"
BACKUP_NAME = "LGS_MappingTemplate_pre-fault-thin_%s.gpkg" % BACKUP_DATE


def bail(msg):
    raise SystemExit("ABORT: " + msg)


# ---------------------------------------------------------------------------
# File guards (shape from inject_linework_shear_wave.py)
# ---------------------------------------------------------------------------

def back_up(repo, gpkg):
    if os.path.abspath(gpkg) == os.path.abspath(
            os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")):
        dest = os.path.join(repo, "Template", "Backup", BACKUP_NAME)
    else:
        stem, ext = os.path.splitext(gpkg)
        dest = "%s_pre-fault-thin_%s%s" % (stem, BACKUP_DATE, ext)
    if not os.path.exists(dest):
        shutil.copy2(gpkg, dest)
    return dest


def refuse_if_open(gpkg):
    """Bail if QGIS still has the gpkg open (see inject_linework_shear_wave)."""
    if os.path.exists(gpkg + "-wal"):
        bail("%s has an active -wal alongside it, so something still has it "
             "open. Close the project in QGIS first." % os.path.basename(gpkg))
    try:
        con = sqlite3.connect(gpkg, timeout=1.0)
        con.execute("BEGIN IMMEDIATE")
        con.execute("ROLLBACK")
        con.close()
    except sqlite3.OperationalError as exc:
        bail("%s is locked (%s) - close the project in QGIS and re-run"
             % (os.path.basename(gpkg), exc))


# ---------------------------------------------------------------------------
# QML surgery (shapes from inject_dyke_sill_widths.py)
# ---------------------------------------------------------------------------

def symbol_block(qml, name):
    m = re.search(r'<symbol\b[^>]*\bname="%s"[^>]*>' % re.escape(name), qml)
    if not m:
        bail("symbol %r not found" % name)
    depth = 0
    for t in re.finditer(r'<symbol\b|</symbol>', qml[m.start():]):
        depth += 1 if t.group(0) == '<symbol' else -1
        if depth == 0:
            return m.start(), m.start() + t.end()
    bail("unbalanced symbol %r" % name)


WIDTH_RE = re.compile(
    r'(<Option name="line_width" type="QString" value=")([^"]+)(")')


def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default = os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail("gpkg not found: %s" % gpkg)
    if "_Patterns" in os.path.basename(gpkg):
        bail("never point this at the Patterns gpkg - it is re-baked "
             "wholesale by inject_basemap_lith_patterns.py")

    refuse_if_open(gpkg)

    con = sqlite3.connect(gpkg)
    cur = con.cursor()
    row = cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                      (LAYER,)).fetchone()
    if not row or not row[0]:
        bail("no styleQML for %r" % LAYER)
    qml = row[0]

    changed = kept = 0
    for code, pairs in sorted(WIDTHS.items()):
        cm = re.search(r'<category[^>]*value="%s"[^>]*/>' % re.escape(code),
                       qml)
        if not cm:
            bail("category %r not found" % code)
        sym = re.search(r'symbol="(\d+)"', cm.group(0)).group(1)
        s, e = symbol_block(qml, sym)
        block = qml[s:e]
        found = WIDTH_RE.findall(block)
        widths = [w for _, w, _ in found]
        olds = [o for o, _ in pairs]
        news = [n for _, n in pairs]
        if widths == news:
            kept += len(pairs)
            continue
        if widths != olds:
            bail("%s: line_width statics %r - expected %r (apply) or %r "
                 "(already applied); refusing to guess" % (code, widths,
                                                           olds, news))
        it = iter(pairs)

        def repl(m):
            old, new = next(it)
            assert m.group(2) == old
            return m.group(1) + new + m.group(3)

        block = WIDTH_RE.sub(repl, block)
        qml = qml[:s] + block + qml[e:]
        changed += len(pairs)
        print("%s: %s" % (code, ", ".join("%s -> %s" % p for p in pairs)))

    if not changed:
        print("already applied: %d stroke(s) at the trimmed widths" % kept)
        con.close()
        return

    try:
        ET.fromstring(qml)
    except ET.ParseError as exc:
        bail("edited QML no longer parses, aborting before write: %s" % exc)

    dest = back_up(repo, gpkg)
    print("backup: %s" % dest)

    cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                (qml, LAYER))
    assert cur.rowcount == 1
    con.commit()
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])

    # ---------------- round-trip validation ----------------------------
    q, = cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                     (LAYER,)).fetchone()
    con.close()
    root = ET.fromstring(q)
    rend = root.find("renderer-v2")
    cats = {c.get("value"): c.get("symbol") for c in rend.iter("category")
            if c.get("value")}
    syms = {sm.get("name"): sm for sm in rend.find("symbols").findall("symbol")}
    for code, pairs in WIDTHS.items():
        got = []
        for lyr in syms[cats[code]].iter("layer"):
            if lyr.get("class") != "SimpleLine":
                continue
            o = {x.get("name"): x.get("value")
                 for x in lyr.find("Option").findall("Option")}
            got.append(o.get("line_width"))
        assert got == [n for _, n in pairs], (code, got)
    print("done: %d stroke(s) trimmed" % changed)
    print()
    print("NOW RUN: python scripts/inject_weight_scaling.py   "
          "(re-bakes the Weight outlineWidth ramps from the new statics)")


if __name__ == "__main__":
    main()
