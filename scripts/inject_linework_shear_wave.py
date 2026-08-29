"""Give the Shear Zone Boundary linework a wavy stroke.

The Shear Zone Boundary symbol on "2 - Linework" draws a straight red
stroke with an inward-pointing arrow MarkerLine.  This injector replaces
only the straight backbone: the existing SimpleLine - with every static
option and both of its data-defined properties (the confidence customDash
and the Weight outlineWidth) - is wrapped byte-for-byte inside a
GeometryGenerator whose modifier is wave($geometry, ...), so the stroke
itself undulates.  The arrow MarkerLine is not touched and keeps riding
the ORIGINAL geometry.

The wrapper is emitted in exactly the shape the template already ships
for the Unconformity family (symbol 42): GeometryGenerator, SymbolType
Line, units MM (so the renderer's referenceScale applies), one line
sub-symbol.  That precedent is also the proof that no neighbouring
injector needs changing:

* inject_confidence_system.py finds SimpleLines by regex over the whole
  symbol span, nested or not, and the moved layer is base-solid, so
  apply_flip re-runs no-op on it while the preserved customDash dd keeps
  the Inferred/Queried dashing working along the wavy path.  Run order
  with this script does not matter.
* inject_weight_scaling.py likewise recurses into sub-symbols (symbol 42
  carries its Weight dd on the nested SimpleLine).  The generator layer
  gets its own empty data_defined_properties block because
  inject_weight_scaling.inject_into_scope() finds a layer's dd block with
  a forward search - a layer without one would donate its neighbour's.
* inject_linework_dash_order.py does not touch this symbol; the label /
  detail-scope injectors match the code STRING, which is unchanged.

The SLD twin is deliberately left alone: SLD cannot express a
GeometryGenerator, and the house precedent (vein selvedge, basemap lith
patterns) is to keep the existing straight-line rule as the
approximation when no category or colour changed.

QField renders wave generators already (Vein - Shear, the Unconformity
family), so nothing export-side is needed.

Idempotent: a re-run that finds the generator with the same expression
is a no-op; one that finds a DIFFERENT expression refreshes it in place,
which is the tuning path - edit WAVELENGTH_MM / AMPLITUDE_MM below and
re-run.

Never point this at LGS_MappingTemplate_Patterns.gpkg - that file is
re-baked wholesale by inject_basemap_lith_patterns.py (see the footer).

Usage:
    python scripts/inject_linework_shear_wave.py [path\\to\\file.gpkg]
"""

import os
import re
import shutil
import sqlite3
import sys
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

CODE = "Shear Zone Boundary"
LW = "2 - Linework"

# The tuning knobs.  The Unconformity family uses wavelength 6 / amplitude
# 0.5 under a 0.38 mm stroke; the boundary stroke is 1.46 pt (~0.51 mm), so
# a longer wavelength and slightly larger amplitude keep it reading as a
# bold undulating boundary rather than a squiggle.
WAVELENGTH_MM = 10.0
AMPLITUDE_MM = 0.7
WAVE_EXPR = ("wave($geometry, wavelength:=%s, amplitude:=%s)"
             % (WAVELENGTH_MM, AMPLITUDE_MM))

GEN_ID = "{%s}" % uuid.uuid5(uuid.NAMESPACE_URL, "lgs-shear-wave-gen:" + CODE)

BACKUP_DATE = "2026-08-29"
BACKUP_NAME = "LGS_MappingTemplate_pre-shear-wave_%s.gpkg" % BACKUP_DATE


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
        dest = "%s_pre-shear-wave_%s%s" % (stem, BACKUP_DATE, ext)
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


def empty_dd():
    """Every layer needs one, even when empty.

    inject_weight_scaling.inject_into_scope() finds a layer's dd block with
    a forward re.search from the layer tag; a layer with no block of its own
    makes it grab the NEXT layer's and rewrite it with the wrong statics.
    """
    el = ET.Element("data_defined_properties")
    outer = ET.SubElement(el, "Option", {"type": "Map"})
    ET.SubElement(outer, "Option", {"name": "name", "type": "QString",
                                    "value": ""})
    ET.SubElement(outer, "Option", {"name": "properties"})
    ET.SubElement(outer, "Option", {"name": "type", "type": "QString",
                                    "value": "collection"})
    return el


PLACEHOLDER = "LGSSHEARWAVEPLACEHOLDER"


def generator_wrapper(sym_name, simpleline_xml):
    """The symbol-42-shaped GeometryGenerator wrapping the existing stroke.

    Child order matters and matches the shipped precedent: Option map,
    then the layer's own dd block, then the sub-symbol.
    """
    layer = ET.Element("layer", {"id": GEN_ID, "class": "GeometryGenerator",
                                 "locked": "0", "pass": "0", "enabled": "1"})
    opts = ET.SubElement(layer, "Option", {"type": "Map"})
    ET.SubElement(opts, "Option", {"name": "SymbolType", "type": "QString",
                                   "value": "Line"})
    ET.SubElement(opts, "Option", {"name": "geometryModifier",
                                   "type": "QString", "value": WAVE_EXPR})
    ET.SubElement(opts, "Option", {"name": "units", "type": "QString",
                                   "value": "MM"})
    layer.append(empty_dd())
    sub = ET.SubElement(layer, "symbol", {
        "name": "@%s@0" % sym_name, "frame_rate": "10", "clip_to_extent": "1",
        "alpha": "1", "type": "line", "force_rhr": "0", "is_animated": "0"})
    sub.append(empty_dd())
    ET.SubElement(sub, PLACEHOLDER)
    out = ET.tostring(layer, encoding="unicode")
    return out.replace("<%s />" % PLACEHOLDER, simpleline_xml)


def convert(sym_xml, sym_name):
    """Wrap the single top-level SimpleLine; MarkerLine bytes untouched."""
    lines = list(layer_spans(sym_xml, "SimpleLine"))
    if len(lines) != 1:
        bail("expected exactly one SimpleLine in symbol %r, found %d - "
             "the symbol is not in the shape this injector understands, "
             "fix it by hand in QGIS" % (sym_name, len(lines)))
    s, e = lines[0]
    nested = re.search(r'<symbol\b', sym_xml[:s])
    # The only <symbol tag before the stroke must be the outer symbol itself.
    if nested and re.search(r'<symbol\b', sym_xml[nested.end():s]):
        bail("the SimpleLine in symbol %r is nested inside a sub-symbol - "
             "already converted by hand? Refusing to guess." % sym_name)
    stroke = sym_xml[s:e]
    for needle, what in (("customDash", "confidence customDash dd"),
                         ("outlineWidth", "Weight outlineWidth dd")):
        if needle not in stroke:
            bail("the stroke is missing its %s - run "
                 "inject_confidence_system.py / inject_weight_scaling.py "
                 "first so there is something to preserve" % what)
    return sym_xml[:s] + generator_wrapper(sym_name, stroke) + sym_xml[e:]


def refresh_expression(sym_xml):
    """Tuning path: the generator exists, only its expression differs."""
    for s, e in layer_spans(sym_xml, "GeometryGenerator"):
        if GEN_ID not in sym_xml[s:e]:
            continue
        layer_xml = sym_xml[s:e]
        new_layer, n = re.subn(
            r'(<Option name="geometryModifier" type="QString" value=)"[^"]*"',
            lambda m: m.group(1) + quoteattr(WAVE_EXPR),
            layer_xml, count=1)
        if n != 1:
            bail("generator found but its geometryModifier option was not")
        return sym_xml[:s] + new_layer + sym_xml[e:]
    bail("refresh called with no generator present")


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
    gen_count_before = renderer.count('class="GeometryGenerator"')

    if GEN_ID in sym_xml:
        cur_expr = None
        for el in ET.fromstring(sym_xml).iter("layer"):
            if el.get("id") == GEN_ID:
                for o in el.find("Option").findall("Option"):
                    if o.get("name") == "geometryModifier":
                        cur_expr = o.get("value")
        if cur_expr == WAVE_EXPR:
            print("already applied: %s carries %s - nothing to do"
                  % (CODE, WAVE_EXPR))
            con.close()
            return
        print("refreshing wave parameters: %r -> %r" % (cur_expr, WAVE_EXPR))
        new_sym = refresh_expression(sym_xml)
        gen_delta = 0
    else:
        new_sym = convert(sym_xml, sym_name)
        gen_delta = 1

    # The arrows are critical: their bytes must survive verbatim.
    marker_spans = list(layer_spans(sym_xml, "MarkerLine"))
    if len(marker_spans) != 1:
        bail("expected exactly one MarkerLine (the arrows) in symbol %r"
             % sym_name)
    ms_, me_ = marker_spans[0]
    marker_xml = sym_xml[ms_:me_]
    if marker_xml not in new_sym:
        bail("the arrow MarkerLine did not survive the edit byte-for-byte")

    renderer = renderer[:s] + new_sym + renderer[e:]
    if renderer.count('class="GeometryGenerator"') != \
            gen_count_before + gen_delta:
        bail("GeometryGenerator count moved by more than this one symbol")
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
    assert len(layers) == 2, "expected generator + arrows, got %d" % len(layers)
    gen, marker = layers
    assert gen.get("class") == "GeometryGenerator" and gen.get("id") == GEN_ID
    opts = {o.get("name"): o.get("value")
            for o in gen.find("Option").findall("Option")}
    assert opts["SymbolType"] == "Line" and opts["units"] == "MM"
    assert opts["geometryModifier"] == WAVE_EXPR
    assert gen.find("data_defined_properties") is not None
    assert marker.get("class") == "MarkerLine", "arrows not on top"

    sub = gen.find("symbol")
    stroke = sub.find("layer")
    assert stroke.get("class") == "SimpleLine"
    statics = {o.get("name"): o.get("value")
               for o in stroke.find("Option").findall("Option")}
    assert statics["line_width"] == "1.46", statics["line_width"]
    assert statics["line_color"].startswith("255,29,29"), statics["line_color"]
    assert statics["line_style"] == "solid"
    assert statics["use_custom_dash"] == "0"
    dd = ET.tostring(stroke.find("data_defined_properties"),
                     encoding="unicode")
    assert "customDash" in dd and "100000;1" in dd and "20;5" in dd, \
        "confidence dd lost"
    assert "outlineWidth" in dd and "Weight" in dd, "weight dd lost"
    for el in (sym_el, gen, marker, sub, stroke):
        assert el.find("data_defined_properties") is not None
    print("round-trip ok: %s = wavy stroke (wavelength %s mm, amplitude "
          "%s mm) under untouched arrows" % (CODE, WAVELENGTH_MM,
                                             AMPLITUDE_MM))

    print()
    print("NOW RE-BAKE THE PATTERNS GPKG so its mirrored Linework style "
          "picks up the wave:")
    print('  "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" '
          'scripts/inject_basemap_lith_patterns.py')
    print("Optional no-op sanity: python scripts/inject_weight_scaling.py")


if __name__ == "__main__":
    main()
