"""Take the wave back off the Shear Zone Boundary linework.

The Shear Zone Boundary stroke was wrapped in a GeometryGenerator so it
drew as a sinuous line, with Inferred/Queried rendered as whole tildes
emitted by the generator itself.  It did not look good enough on the
map, so this unwraps it: the stroke returns to a plain top-level
SimpleLine and the code goes back to the ordinary confidence dash
system, exactly like Shear and Contact - Sheared.  The inward-arrow
MarkerLine is untouched throughout - it was never part of the wave.

THE ONE THING THAT MAKES THIS MORE THAN AN UNWRAP.  While the generator
owned the Inferred rendering, the stroke's customDash dd was pinned to
the bare mega-dash and the stroke was left base-solid.  Both of those
make inject_confidence_system.apply_flip() skip the layer: it ignores
anything not `dashed`, and ignores any dd already carrying MEGA_DASH.
So simply putting "Shear Zone Boundary" back into FLIP_CODES restores
nothing and reports 0 changes - the code would stay permanently solid
with no confidence response, and nothing would say so.

This script therefore hands the symbol back in its AUTHORED PRE-FLIP
state - use_custom_dash="1" over the authored customdash 20;5, with no
customDash dd at all - which is what the confidence injector expects as
input.  That keeps one owner for the flip expression instead of
duplicating it here.  Run order afterwards is mandatory, and the footer
prints it:

    python scripts/inject_confidence_system.py     (must report 1 flip)
    python scripts/inject_dash_weight_scaling.py   (62 static + 56 flips)

Deliberately NOT reverted: simplifyDrawingHints stays "0" on
2 - Linework.  It was turned off for the wave's sake, but it makes all
linework draw true to the saved geometry rather than a zoom-dependent
simplification, which is the house priority and what FieldNotebook
already ships.  Do not "restore" it.

Only symbol 77 is touched.  The Unconformity family, Vein - Shear and
the vein selvedge rings are all still GeometryGenerator waves and must
stay that way; the validation counts generators to prove it.

Idempotent: with no generator present it is a no-op.

Never point this at LGS_MappingTemplate_Patterns.gpkg - that file is
re-baked wholesale by inject_basemap_lith_patterns.py.

Usage:
    python scripts/remove_shear_wave.py [path\\to\\file.gpkg]
"""

import os
import re
import shutil
import sqlite3
import sys
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inject_confidence_system import remove_dd_prop  # noqa: E402

CODE = "Shear Zone Boundary"
LW = "2 - Linework"

AUTHORED_DASH = "20;5"      # what apply_flip asserts before flipping

# The generator's layer id, as the wave injector seeded it:
# uuid5(NAMESPACE_URL, "lgs-shear-wave-gen:" + CODE).  Recomputed rather
# than pasted so it cannot be mistyped - the seed string itself never
# appears in the XML, only this hash of it.
GEN_ID = "{%s}" % uuid.uuid5(uuid.NAMESPACE_URL,
                             "lgs-shear-wave-gen:" + CODE)

BACKUP_DATE = "2026-08-30"
BACKUP_NAME = "LGS_MappingTemplate_pre-wave-removal_%s.gpkg" % BACKUP_DATE


def bail(msg):
    raise SystemExit("ABORT: " + msg)


# ---------------------------------------------------------------------------
# File guards (shape from inject_vein_generation_selvedge.py)
# ---------------------------------------------------------------------------

def back_up(repo, gpkg):
    """Snapshot beside the file being edited, not always into the repo."""
    if os.path.abspath(gpkg) == os.path.abspath(
            os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")):
        dest = os.path.join(repo, "Template", "Backup", BACKUP_NAME)
    else:
        stem, ext = os.path.splitext(gpkg)
        dest = "%s_pre-wave-removal_%s%s" % (stem, BACKUP_DATE, ext)
    if not os.path.exists(dest):
        shutil.copy2(gpkg, dest)
    return dest


def refuse_if_open(gpkg):
    """Bail if QGIS still has the gpkg open.

    The quiet hazard is the second one: SQLite may let the write through,
    but QGIS holds layer_styles in memory and writes its own copy back on
    the next project save - so the change appears to work, then vanishes.

    The -wal check MUST come first and MUST NOT be preceded by a connection
    of our own: connecting and closing cleanly checkpoints and DELETES the
    -wal, destroying the evidence.
    """
    if os.path.exists(gpkg + "-wal"):
        bail("%s has an active -wal alongside it, so something still has it "
             "open. Close the project in QGIS first: styles live in "
             "layer_styles, and QGIS would write its in-memory copy straight "
             "back over this edit on the next save."
             % os.path.basename(gpkg))
    try:
        con = sqlite3.connect(gpkg, timeout=1.0)
        con.execute("BEGIN IMMEDIATE")
        con.execute("ROLLBACK")
        con.close()
    except sqlite3.OperationalError as exc:
        bail("%s is locked (%s) - close the project in QGIS and re-run"
             % (os.path.basename(gpkg), exc))


# ---------------------------------------------------------------------------
# QML surgery helpers (shapes from inject_confidence_system.py)
# ---------------------------------------------------------------------------

def symbol_span(q, name):
    m = re.search(r'<symbol\b[^>]*\bname="%s"[^>]*>' % re.escape(name), q)
    if not m:
        bail("symbol %r not found" % name)
    depth = 0
    for t in re.finditer(r'<symbol\b|</symbol>', q[m.start():]):
        depth += 1 if t.group(0) == '<symbol' else -1
        if depth == 0:
            return m.start(), m.start() + t.end()
    bail("unbalanced symbol %r" % name)


def layer_spans(sym_xml, cls):
    """Yield (start, end) for each complete <layer class=cls> in the span."""
    for lm in re.finditer(r'<layer\b[^>]*class="%s"[^>]*>' % cls, sym_xml):
        depth = 0
        for t in re.finditer(r'<layer\b|</layer>', sym_xml[lm.start():]):
            depth += 1 if t.group(0) == '<layer' else -1
            if depth == 0:
                yield lm.start(), lm.start() + t.end()
                break


def set_static(layer_xml, name, value):
    """Set one static Option, never reaching into the dd block."""
    ddm = re.search(r'<data_defined_properties>', layer_xml)
    cut = ddm.start() if ddm else len(layer_xml)
    head, tail = layer_xml[:cut], layer_xml[cut:]
    head, n = re.subn(r'(name="%s" type="QString" value=")[^"]*(")' % name,
                      r'\g<1>%s\g<2>' % value, head, count=1)
    if n != 1:
        bail("static %r not found to set" % name)
    return head + tail


def unwrap(sym_xml, sym_name):
    """Lift the nested SimpleLine out of the generator, byte-for-byte."""
    gens = [(s, e) for s, e in layer_spans(sym_xml, "GeometryGenerator")
            if GEN_ID in sym_xml[s:e]]
    if len(gens) != 1:
        bail("expected exactly one shear-wave GeometryGenerator in symbol "
             "%r, found %d" % (sym_name, len(gens)))
    gs, ge = gens[0]
    inner = list(layer_spans(sym_xml[gs:ge], "SimpleLine"))
    if len(inner) != 1:
        bail("expected exactly one SimpleLine inside the generator, found %d"
             % len(inner))
    ls, le = inner[0]
    stroke = sym_xml[gs:ge][ls:le]
    # Back to the state the confidence injector expects as input: authored
    # dashed, no customDash dd.  See the module docstring.
    stroke = set_static(stroke, "use_custom_dash", "1")
    stroke = remove_dd_prop(stroke, "customDash")
    if "customDash" in stroke:
        bail("the pinned customDash dd survived removal - the confidence "
             "injector would skip this layer and the dash would never "
             "come back")
    return sym_xml[:gs] + stroke + sym_xml[ge:]


def reclip_symbol(sym_xml):
    """clip_to_extent back to 1, as every sibling symbol has it."""
    m = re.match(r'<symbol\b[^>]*>', sym_xml)
    tag = m.group(0)
    new_tag, n = re.subn(r'clip_to_extent="[^"]*"', 'clip_to_extent="1"',
                         tag, count=1)
    if n != 1:
        bail("outer symbol tag carries no clip_to_extent attribute")
    return new_tag + sym_xml[m.end():]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

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
                      (LW,)).fetchone()
    if not row or not row[0]:
        bail("no styleQML for %r" % LW)
    qml = row[0]

    rm = re.search(r'<renderer-v2\b.*?</renderer-v2>', qml, re.S)
    if not rm:
        bail("Linework renderer-v2 not found")
    renderer = rm.group(0)

    cm = re.search(r'<category[^>]*value=%s[^>]*/>' % quoteattr(CODE),
                   renderer)
    if not cm:
        bail("Linework category %r not found" % CODE)
    sym_name = re.search(r'symbol="(\d+)"', cm.group(0)).group(1)
    s, e = symbol_span(renderer, sym_name)
    sym_xml = renderer[s:e]
    gens_before = renderer.count('class="GeometryGenerator"')

    if GEN_ID not in sym_xml:
        print("already removed: %s carries no wave generator - nothing to do"
              % CODE)
        con.close()
        return

    marker_spans = list(layer_spans(sym_xml, "MarkerLine"))
    if len(marker_spans) != 1:
        bail("expected exactly one MarkerLine (the arrows) in symbol %r"
             % sym_name)
    ms_, me_ = marker_spans[0]
    marker_xml = sym_xml[ms_:me_]

    new_sym = reclip_symbol(unwrap(sym_xml, sym_name))
    if marker_xml not in new_sym:
        bail("the arrow MarkerLine did not survive the edit byte-for-byte")

    renderer = renderer[:s] + new_sym + renderer[e:]
    if renderer.count('class="GeometryGenerator"') != gens_before - 1:
        bail("GeometryGenerator count moved by more than this one symbol - "
             "the Unconformity / Vein - Shear / selvedge waves must stay")
    new_qml = qml[:rm.start()] + renderer + qml[rm.end():]

    try:
        ET.fromstring(new_qml)
    except ET.ParseError as exc:
        bail("edited QML no longer parses, aborting before write: %s" % exc)

    dest = back_up(repo, gpkg)
    print("backup: %s" % dest)

    cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                (new_qml, LW))
    assert cur.rowcount == 1
    con.commit()
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])

    # ---------------- round-trip validation ----------------------------
    q, = cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                     (LW,)).fetchone()
    root = ET.fromstring(q)
    con.close()

    sym_el = None
    for el in root.iter("symbol"):
        if el.get("name") == sym_name:
            sym_el = el
            break
    assert sym_el is not None, "symbol vanished"
    layers = sym_el.findall("layer")
    assert len(layers) == 2, "expected stroke + arrows, got %d" % len(layers)
    stroke, marker = layers
    assert stroke.get("class") == "SimpleLine", stroke.get("class")
    assert marker.get("class") == "MarkerLine", "arrows not on top"
    assert sym_el.get("clip_to_extent") == "1"
    assert GEN_ID not in q, "the wave generator id survived in the style"

    statics = {o.get("name"): o.get("value")
               for o in stroke.find("Option").findall("Option")}
    assert statics["line_width"] == "1.46", statics["line_width"]
    assert statics["line_color"].startswith("255,29,29"), statics["line_color"]
    assert statics["customdash"] == AUTHORED_DASH, statics["customdash"]
    assert statics["use_custom_dash"] == "1", \
        "the stroke must be authored-dashed or apply_flip will skip it"
    dd = ET.tostring(stroke.find("data_defined_properties"),
                     encoding="unicode")
    assert "customDash" not in dd, \
        "a customDash dd would make apply_flip skip this layer"
    assert "outlineWidth" in dd and "Weight" in dd, "weight dd lost"
    for el in (sym_el, stroke, marker):
        assert el.find("data_defined_properties") is not None
    print("round-trip ok: %s is a plain SimpleLine + arrows again, authored "
          "dash %s restored, %d wave generators left elsewhere"
          % (CODE, AUTHORED_DASH, gens_before - 1))

    print()
    print("NOW RUN, IN THIS ORDER - the dash is not back until you do:")
    print("  python scripts/inject_confidence_system.py"
          "     (must report 1 flip code changed, not 0)")
    print("  python scripts/inject_dash_weight_scaling.py"
          "   (must report 62 static + 56 flips)")
    print('  "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" '
          'scripts/inject_basemap_lith_patterns.py')


if __name__ == "__main__":
    main()
