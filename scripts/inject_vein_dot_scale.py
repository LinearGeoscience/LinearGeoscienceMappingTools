"""Lighten the vein dot decoration (Aug 2026 field feedback).

Every vein code on '2 - Linework' wears the same mark: a MarkerLine placing
a 1.8 mm circle every 6 mm.  On a busy sheet the dots crowd the line and
carry more weight than the vein itself, so they drop to 1.4 mm every
7.5 mm - about a fifth smaller and a quarter further apart, five dots per
30 mm becoming four.

Only the vein's OWN dots.  The selvedge stipple (0.45 mm circles every
2.2 mm) lives inside a GeometryGenerator sub-symbol and is deliberately out
of reach here: this script walks TOP-LEVEL <layer> elements only.

TWO SYMBOLS CARRY A SECOND, PHASED MARKER and it has to move with the
circles.  Vein - Breccia's cross2 and Vein - Extension's line marker are
authored at HALF the interval so their marks interleave with the dots
rather than landing on them; leave their interval at 6 while the circles go
to 7.5 and the two runs drift in and out of phase along the line.  Their
SIZES are deliberately unchanged - they are the vein-type identity, not the
dot.

NOT MATCHED ON SIZE.  Thirteen SimpleMarker layers in this style carry a
1.8 static - Detachment's semi_circle, Metamorphic Isograd's triangle,
Fence's cross2 - so the match is per-symbol on the named code, then on the
circle inside its MarkerLine.

Pegmatite is deliberately excluded.  It is a Lithology-category line, not a
vein, and it happens to carry the identical decoration; leaving it also
finally tells it apart from Vein - Pegmatite, which until now looked the
same.

Re-run inject_weight_scaling.py afterwards - the dot size is data-defined
and the expression bakes the static ("1.8 * CASE WHEN Weight ..."), so
without the re-bake the dots keep rendering at the old size.  That is the
established re-bake rule.

Idempotent and re-runnable; QML validated with ElementTree BEFORE anything
is written.

Usage:  python scripts/inject_vein_dot_scale.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import shutil
import sqlite3
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

LAYER = "2 - Linework"
BACKUP_DATE = "2026-08-19"
BACKUP_NAME = "LGS_MappingTemplate_pre-vein-dots_%s.gpkg" % BACKUP_DATE

OLD_SIZE, NEW_SIZE = "1.8", "1.4"
OLD_INTERVAL, NEW_INTERVAL = "6", "7.5"
# The companion marker sits half an interval along, so it falls between the
# dots instead of on them.
NEW_PHASE = "3.75"

# The Veins category minus the two that never had dots: Vein Set / Sheeted
# has no marker line at all, and Stockwork Zone Boundary uses an SVG tick.
TARGET_TYPES = [
    "Vein", "Vein - Breccia", "Vein - Carbonate", "Vein - Extension",
    "Vein - Laminated", "Vein - Pegmatite", "Vein - Quartz",
    "Vein - Quartz-Carbonate", "Vein - Shear",
]


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def back_up(repo, gpkg):
    if os.path.abspath(gpkg) == os.path.abspath(
            os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")):
        dest = os.path.join(repo, "Template", "Backup", BACKUP_NAME)
    else:
        stem, ext = os.path.splitext(gpkg)
        dest = "%s_pre-vein-dots_%s%s" % (stem, BACKUP_DATE, ext)
    if not os.path.exists(dest):
        shutil.copy2(gpkg, dest)
    return dest


def refuse_if_open(gpkg):
    """Bail if QGIS still has the gpkg open.

    The -wal check MUST come first and MUST NOT be preceded by a connection
    of our own: connecting and closing cleanly checkpoints and DELETES it.
    QGIS holds layer_styles in memory and writes its own copy back on the
    next project save, so an edit made underneath it vanishes.
    """
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


def symbol_block(qml, name):
    """Byte range of the balanced <symbol name="..."> block.

    Balanced, not regex-to-first-close: a symbol's sub-symbols are <symbol>
    elements too, so stopping at the first </symbol> would sever it.
    """
    m = re.search(r'<symbol\b[^>]*\bname="%s"[^>]*>' % re.escape(name), qml)
    if not m:
        bail("symbol %r not found" % name)
    depth = 0
    for t in re.finditer(r'<symbol\b|</symbol>', qml[m.start():]):
        depth += 1 if t.group(0) == '<symbol' else -1
        if depth == 0:
            return m.start(), m.start() + t.end()
    bail("unbalanced symbol %r" % name)


def direct_opts(el):
    """The element's OWN options - never descend into sub-symbols."""
    cont = el.find("Option")
    if cont is None:
        return {}
    return {o.get("name"): o for o in cont.findall("Option")}


def set_opt(el, name, value, where):
    o = direct_opts(el).get(name)
    if o is None:
        bail("%s: no %r option to set" % (where, name))
    o.set("value", value)


def convert(qml, code):
    """Returns (qml, changed).  Idempotent on the circle's size."""
    cm = re.search(r'<category[^>]*\bvalue=%s[^>]*/>'
                   % re.escape(quoteattr(code)), qml)
    if not cm:
        bail("Linework category %r not found" % code)
    sym_name = re.search(r'symbol="(\d+)"', cm.group(0)).group(1)
    s, e = symbol_block(qml, sym_name)
    sym_el = ET.fromstring(qml[s:e])

    # Top-level layers only: the selvedge stipple's MarkerLine is nested
    # inside a GeometryGenerator sub-symbol and must not be touched.
    marker_lines = [l for l in sym_el.findall("layer")
                    if l.get("class") == "MarkerLine"]
    if not marker_lines:
        bail("%s: no MarkerLine to rescale" % code)

    circles = []
    companions = []
    for ml in marker_lines:
        dot = ml.find("symbol/layer")
        shape = direct_opts(dot).get("name") if dot is not None else None
        (circles if shape is not None and shape.get("value") == "circle"
         else companions).append((ml, dot))
    if len(circles) != 1:
        bail("%s: expected exactly 1 circle MarkerLine, found %d"
             % (code, len(circles)))

    ml, dot = circles[0]
    size = direct_opts(dot).get("size")
    if size is not None and size.get("value") == NEW_SIZE:
        return qml, False
    if size is None or size.get("value") != OLD_SIZE:
        bail("%s: the dot reads %r, expected %r - this symbol is not in the "
             "state this script was written against"
             % (code, size.get("value") if size is not None else None,
                OLD_SIZE))

    where = "%s circle" % code
    set_opt(dot, "size", NEW_SIZE, where)
    set_opt(ml, "interval", NEW_INTERVAL, where)
    # offset_along_line is authored equal to the interval; it fixes where the
    # first dot lands, so it has to track it.
    set_opt(ml, "offset_along_line", NEW_INTERVAL, where)

    for ml, _dot in companions:
        o = direct_opts(ml)
        if o.get("interval") is None or o["interval"].get("value") != OLD_INTERVAL:
            continue          # not phased against the dots; leave it alone
        set_opt(ml, "interval", NEW_INTERVAL, "%s companion" % code)
        set_opt(ml, "offset_along_line", NEW_PHASE, "%s companion" % code)
        print("  %s: companion marker re-phased to %s/%s"
              % (code, NEW_INTERVAL, NEW_PHASE))

    print("  %s: dot %s -> %s, interval %s -> %s"
          % (code, OLD_SIZE, NEW_SIZE, OLD_INTERVAL, NEW_INTERVAL))
    return qml[:s] + ET.tostring(sym_el, encoding="unicode") + qml[e:], True


def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default = os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail("gpkg not found: %s" % gpkg)
    if "_Patterns" in os.path.basename(gpkg):
        bail("that is the generated patterns template - restyle the live one "
             "and re-run inject_basemap_lith_patterns.py")

    refuse_if_open(gpkg)
    print("backed up to %s" % back_up(repo, gpkg))

    con = sqlite3.connect(gpkg)
    cur = con.cursor()
    row = cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                      (LAYER,)).fetchone()
    if not row or not row[0]:
        bail("no styleQML for %r" % LAYER)
    qml = original = row[0]

    rm = re.search(r'<renderer-v2\b.*?</renderer-v2>', qml, re.S)
    if not rm:
        bail("Linework renderer-v2 not found")
    renderer = rm.group(0)

    changed = []
    for code in TARGET_TYPES:
        renderer, did = convert(renderer, code)
        if did:
            changed.append(code)
    if changed and len(changed) != len(TARGET_TYPES):
        bail("partial prior state: %d of %d symbols would change (%s); not "
             "writing" % (len(changed), len(TARGET_TYPES), ", ".join(changed)))
    if not changed:
        print("already applied (no change): %d symbols ok" % len(TARGET_TYPES))
    qml = qml[:rm.start()] + renderer + qml[rm.end():]

    # Validate BEFORE writing: never persist a QML that no longer parses.
    try:
        ET.fromstring(qml)
    except ET.ParseError as exc:
        bail("edited QML no longer parses, aborting without write: %s" % exc)

    if qml != original:
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, LAYER))
        if cur.rowcount != 1:
            bail("update hit %d rows" % cur.rowcount)
        con.commit()
        print("styleQML updated: %d symbols" % len(changed))

    # --- Round-trip validation -------------------------------------------
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    root = ET.fromstring(cur.execute(
        "SELECT styleQML FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()[0])
    r = root.find(".//renderer-v2")
    cats = {c.get("value"): c.get("symbol") for c in r.find("categories")}
    syms = {s.get("name"): s for s in r.find("symbols")}

    def circle_of(code):
        for ml in syms[cats[code]].findall("layer"):
            if ml.get("class") != "MarkerLine":
                continue
            dot = ml.find("symbol/layer")
            o = direct_opts(dot) if dot is not None else {}
            if o.get("name") is not None and o["name"].get("value") == "circle":
                return ml, dot
        return None, None

    for code in TARGET_TYPES:
        ml, dot = circle_of(code)
        assert ml is not None, "%s: circle MarkerLine lost" % code
        mo, do = direct_opts(ml), direct_opts(dot)
        assert do["size"].get("value") == NEW_SIZE, code
        assert mo["interval"].get("value") == NEW_INTERVAL, code
        assert mo["offset_along_line"].get("value") == NEW_INTERVAL, code
        for other in syms[cats[code]].findall("layer"):
            if other.get("class") != "MarkerLine" or other is ml:
                continue
            oo = direct_opts(other)
            assert oo["interval"].get("value") == NEW_INTERVAL, \
                "%s: a companion marker still runs at the old interval, so " \
                "its marks drift in and out of phase with the dots" % code
            assert oo["offset_along_line"].get("value") == NEW_PHASE, code

    # Pegmatite is a Lithology line that shares the decoration; it is
    # deliberately NOT in TARGET_TYPES and must not have been swept up.
    ml, dot = circle_of("Pegmatite")
    assert direct_opts(dot)["size"].get("value") == OLD_SIZE and \
        direct_opts(ml)["interval"].get("value") == OLD_INTERVAL, \
        "Pegmatite was changed - it is a Lithology line, not a vein"

    # The selvedge stipple lives in a GeometryGenerator sub-symbol.
    stipple = [l for l in root.iter("layer")
               if l.get("class") == "SimpleMarker"
               and direct_opts(l).get("size") is not None
               and direct_opts(l)["size"].get("value") == "0.45"]
    assert stipple, "the selvedge stipple dots are missing entirely"
    print("round-trip ok: %d vein dots at %s mm every %s mm, Pegmatite left "
          "at %s/%s, %d selvedge stipple dots untouched"
          % (len(TARGET_TYPES), NEW_SIZE, NEW_INTERVAL, OLD_SIZE,
             OLD_INTERVAL, len(stipple)))
    print("\nNOW RUN: python scripts/inject_weight_scaling.py"
          "   (the dot size is data-defined and bakes the static)")
    con.close()


if __name__ == "__main__":
    main()
