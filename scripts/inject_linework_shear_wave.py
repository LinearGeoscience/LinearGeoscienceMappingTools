"""Give the Shear Zone Boundary linework a wavy stroke of whole tildes.

The Shear Zone Boundary symbol on "2 - Linework" draws a straight red
stroke with an inward-pointing arrow MarkerLine.  This injector replaces
only the straight backbone: the existing SimpleLine - with every static
option and its Weight outlineWidth dd - is wrapped byte-for-byte inside
a GeometryGenerator, so the stroke itself undulates.  The arrow
MarkerLine is not touched and keeps riding the ORIGINAL geometry.

The generator also OWNS the Inferred/Queried rendering.  A dash pattern
applied to a waved line has no phase relationship to the wave, so dashes
cut tildes at arbitrary points.  Instead the modifier is a CASE: for
Inferred/Queried it emits only whole tildes - one full wave period per
TILDE_MM-long substring of the base line, GAP_MM of nothing between
them - so every dash IS a '~' by construction, with zero drift on long
or bent lines.  Anything else (including NULL) waves continuously.  The
stroke's customDash dd is pinned to the mega-dash (solid) so nothing
dashes the tildes a second time; "Shear Zone Boundary" is accordingly
absent from inject_confidence_system.py FLIP_CODES.

The wrapper is emitted in the shape the template already ships for the
Unconformity family (symbol 42) - GeometryGenerator, SymbolType Line,
one line sub-symbol - EXCEPT the units: this generator runs in MapUnit,
not MM.  A geometryModifier evaluates in the generator's own units
space at the current render scale and ignores the renderer
referenceScale (stroke widths honour it; modifier numerics do not), so
a mm wave re-flows on every zoom.  Ground units derived from
@lgs_reference_scale lock the curve to the map: zoom magnifies it, pan
cannot re-phase it (clip_to_extent is switched off on the symbol), and
render simplification is disabled layer-wide (simplifyDrawingHints=0,
as FieldNotebook already ships) so the base line the wave follows is
identical at every scale.

The scale reaches the expression two ways, both maintained by
script_setmapping.py: the @lgs_reference_scale project variable, and -
for projects where no variable is published - the literal fallback
inside the coalesce, which bake_reference_scale_into_styles() rewrites
in the live style.  That literal is baked 0, meaning "unknown, behave
as before", never a guessed scale; the expression guards it explicitly
because wave() with a zero wavelength returns NULL, which would erase
the boundary rather than degrade it.  Keep the coalesce token in step
with script_setmapping.REFERENCE_SCALE_LITERAL_RE.

Symbol-42 precedent still proves the neighbouring injectors need no
changes:

* inject_confidence_system.py no longer lists this code (the generator
  handles Inferred/Queried itself), so it never touches the symbol; the
  moved stroke is base-solid so apply_flip would skip it anyway.  Run
  order with this script does not matter.
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
and a neutral customDash is a no-op; anything else refreshes in place,
which is the tuning path - edit WAVELENGTH_MM / AMPLITUDE_MM / GAP_MM
below and re-run.

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
TILDE_MM = WAVELENGTH_MM     # one Inferred dash = exactly one wave period
GAP_MM = 5.0                 # blank base-line between tildes (~67% ink)

# What the stroke's customDash dd is pinned to: effectively solid.  Keeping
# the dd key (rather than deleting it) preserves the MEGA_DASH the
# confidence validator counts and the dd block inject_weight_scaling needs.
NEUTRAL_DASH = "'100000;1'"

# The wave is GROUND-LOCKED: the generator runs in MapUnit space and every
# distance is ground units derived from the mapping scale, so zoom purely
# magnifies a fixed curve.  units=MM would NOT do this - a geometryModifier
# evaluates in the generator's own paper-mm space at the CURRENT scale and
# ignores the renderer referenceScale (unlike stroke widths), so a mm wave
# re-flows on every zoom.  The mapping scale comes from the project
# variable Set Mapping Scale maintains (script_setmapping.py), with the
# template's authored 1:5000 as the fallback - same shape as
# inject_label_size_scaling.py.
GEN_UNITS = "MapUnit"
# 0 means "unknown - behave as before", never a guess at the scale someone
# is working at (a guessed 5000 draws a 1:100000 map's wave 20x too small,
# the same class of bug that drew labels at 110 pt).  Set Mapping Scale
# rewrites this literal in the live style - the token and its shape must
# stay in step with script_setmapping.REFERENCE_SCALE_LITERAL_RE and
# inject_label_size_scaling.REF_SCALE.
FALLBACK_SCALE = 0
REF = "coalesce(to_real(@lgs_reference_scale), %s)" % FALLBACK_SCALE


def _ground(mm):
    """Paper mm at the mapping scale, as a ground-units expression."""
    return "%s*%s" % (mm / 1000.0, REF)


_SOLID_WAVE = ("wave($geometry, wavelength:=%s, amplitude:=%s)"
               % (_ground(WAVELENGTH_MM), _ground(AMPLITUDE_MM)))
_TILDE_WAVE = ("wave(line_substring($geometry, @element, @element + %s), "
               "wavelength:=%s, amplitude:=%s)"
               % (_ground(TILDE_MM), _ground(WAVELENGTH_MM),
                  _ground(AMPLITUDE_MM)))
# NULL Confidence falls to ELSE (NULL AND x is never true); lines shorter
# than one tilde wave continuously rather than hitting the empty
# generate_series edge (it returns NULL below its range).  Flat on purpose:
# QgsExpression parse cost doubles per with_variable nesting level, so the
# coalesce is repeated inline rather than bound once.
_WAVED = (
    "CASE WHEN \"Confidence\" IN ('Inferred','Queried') "
    "AND length($geometry) >= %s "
    "THEN collect_geometries(array_foreach("
    "generate_series(0, length($geometry) - %s, %s), %s)) "
    "ELSE %s END"
    % (_ground(TILDE_MM), _ground(TILDE_MM), _ground(TILDE_MM + GAP_MM),
       _TILDE_WAVE, _SOLID_WAVE))
# Unknown scale MUST be guarded, not left to arithmetic: wave() with a
# zero wavelength returns NULL, so the generator would draw nothing at all
# and the boundary would silently vanish.  Degrade to the plain line
# instead - the arrows are a separate layer and still mark it as a shear
# zone boundary - until Set Mapping Scale or the plugin supplies a scale.
WAVE_EXPR = "CASE WHEN %s <= 0 THEN $geometry ELSE %s END" % (REF, _WAVED)

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
                                   "value": GEN_UNITS})
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
    # On a from-scratch rebuild neither dd need exist yet: the generator
    # owns dashing now, and inject_weight_scaling recurses in later.
    for needle, what in (("customDash", "confidence customDash dd"),
                         ("outlineWidth", "Weight outlineWidth dd")):
        if needle not in stroke:
            print("note: the stroke has no %s yet - fine, carrying on"
                  % what)
    return sym_xml[:s] + generator_wrapper(sym_name, stroke) + sym_xml[e:]


def refresh_expression(sym_xml):
    """Tuning path: the generator exists; bring expression + units current."""
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
        new_layer, n = re.subn(
            r'(<Option name="units" type="QString" value=)"[^"]*"',
            lambda m: m.group(1) + quoteattr(GEN_UNITS),
            new_layer, count=1)
        if n != 1:
            bail("generator found but its units option was not")
        return sym_xml[:s] + new_layer + sym_xml[e:]
    bail("refresh called with no generator present")


def unclip_symbol(sym_xml):
    """clip_to_extent=0 on the OUTER symbol tag.

    With clipping on, the generator receives the view-clipped geometry, so
    the tilde phase is measured from wherever the viewport happens to cut
    the line - the tildes crawl as you pan.  Unclipped, the whole feature
    is waved every render and the curve never moves.
    """
    m = re.match(r'<symbol\b[^>]*>', sym_xml)
    tag = m.group(0)
    new_tag, n = re.subn(r'clip_to_extent="[^"]*"', 'clip_to_extent="0"',
                         tag, count=1)
    if n != 1:
        bail("outer symbol tag carries no clip_to_extent attribute")
    return new_tag + sym_xml[m.end():]


def neutralize_custom_dash(sym_xml):
    """Pin the stroke's customDash dd to NEUTRAL_DASH (solid).

    The generator emits the gaps itself; a live confidence dash on top
    would cut the tildes a second time.  A stroke with no customDash dd
    at all (from-scratch rebuild order) needs nothing.
    """
    hits = sym_xml.count('<Option name="customDash" type="Map">')
    if hits == 0:
        return sym_xml
    if hits > 1:
        bail("expected at most one customDash dd in the symbol, found %d"
             % hits)
    new, n = re.subn(
        r'(<Option name="customDash" type="Map">.*?'
        r'<Option name="expression" type="QString" value=)"[^"]*"',
        lambda m: m.group(1) + quoteattr(NEUTRAL_DASH),
        sym_xml, count=1, flags=re.S)
    if n != 1:
        bail("customDash dd present but its expression option was not")
    return new


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

    simplify_ok = re.search(r'<qgis\b[^>]*\bsimplifyDrawingHints="0"', qml)
    clip_ok = 'clip_to_extent="0"' in re.match(r'<symbol\b[^>]*>',
                                               sym_xml).group(0)

    if GEN_ID in sym_xml:
        cur_expr = cur_units = cur_dash = None
        for el in ET.fromstring(sym_xml).iter("layer"):
            if el.get("id") == GEN_ID:
                for o in el.find("Option").findall("Option"):
                    if o.get("name") == "geometryModifier":
                        cur_expr = o.get("value")
                    if o.get("name") == "units":
                        cur_units = o.get("value")
                for sl in el.iter("layer"):
                    if sl.get("class") != "SimpleLine":
                        continue
                    for entry in sl.iter("Option"):
                        if entry.get("name") != "customDash":
                            continue
                        for o in entry.findall("Option"):
                            if o.get("name") == "expression":
                                cur_dash = o.get("value")
        if (cur_expr == WAVE_EXPR and cur_units == GEN_UNITS
                and cur_dash in (None, NEUTRAL_DASH)
                and clip_ok and simplify_ok):
            print("already applied: %s carries the ground-locked wave - "
                  "nothing to do" % CODE)
            con.close()
            return
        print("refreshing wave: units %r -> %r, expression -> ground-locked"
              % (cur_units, GEN_UNITS))
        new_sym = neutralize_custom_dash(refresh_expression(sym_xml))
        gen_delta = 0
    else:
        new_sym = neutralize_custom_dash(convert(sym_xml, sym_name))
        gen_delta = 1
    new_sym = unclip_symbol(new_sym)

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

    # Crest positions must not drift with zoom: render-time simplification
    # feeds the generator a scale-dependent base line.  FieldNotebook
    # already ships with it off; Linework follows (smooth linework is the
    # house priority).
    new_qml, n = re.subn(r'(<qgis\b[^>]*?\bsimplifyDrawingHints=)"[^"]*"',
                         r'\g<1>"0"', new_qml, count=1)
    if n != 1:
        bail("simplifyDrawingHints not found on the qgis document element")

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
    assert opts["SymbolType"] == "Line" and opts["units"] == GEN_UNITS
    assert opts["geometryModifier"] == WAVE_EXPR
    assert "@lgs_reference_scale" in opts["geometryModifier"], \
        "the wave should follow the mapping scale"
    assert sym_el.get("clip_to_extent") == "0", \
        "clipped input geometry would re-phase the tildes on pan"
    assert root.get("simplifyDrawingHints") == "0", \
        "render simplification would drift the crests with zoom"
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
    if "customDash" in dd:
        assert "100000;1" in dd, "customDash dd not neutral"
        assert "Inferred" not in dd, \
            "a live confidence dash would cut the tildes a second time"
    assert "Inferred" in opts["geometryModifier"], \
        "the generator should own the Inferred rendering"
    if "outlineWidth" in dd:
        assert "Weight" in dd, "weight dd mangled"
    for el in (sym_el, gen, marker, sub, stroke):
        assert el.find("data_defined_properties") is not None
    print("round-trip ok: %s = ground-locked wavy stroke (%s mm wavelength "
          "/ %s mm amplitude at the mapping scale), Inferred as whole "
          "%s mm tildes with %s mm gaps, under untouched arrows"
          % (CODE, WAVELENGTH_MM, AMPLITUDE_MM, TILDE_MM, GAP_MM))

    print()
    print("NOW RE-BAKE THE PATTERNS GPKG so its mirrored Linework style "
          "picks up the wave:")
    print('  "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" '
          'scripts/inject_basemap_lith_patterns.py')
    print("Optional no-op sanity: python scripts/inject_weight_scaling.py")


if __name__ == "__main__":
    main()
