"""Rebuild the Linework ornament MarkerLines from source SVGs and one spec.

User request, 29-30 Aug 2026, after a styling review found the hand-
authored markers wrong, soft, and drifting:

  * Antiformal Syncline shared Antiform - Overturned's SVG byte-for-byte
    (and Synformal Anticline shared Synform - Overturned's) - four codes,
    two glyphs.  Thrust and Reverse shared the same filled triangle.
  * The sinistral/dextral couples were bare bent polylines with no
    arrowheads, hand-mirrored onto 500- and 501-unit canvases.  (After
    comparing redraws and the original on 30 Aug 2026, the user settled
    on the plain half-arrow redraw - shaft + 45-degree barb line.)
  * Marker size was Weight-scaled but the perpendicular offsets were
    constants (-1.4 teeth, +0.2/+0.6 overturned folds, 2.0 stem arrows),
    so ornaments floated off the stroke at Very Minor and buried into it
    at Regional.
  * Every glyph lived only as a base64 blob inside the QML.

The fix is structural:

  * Source SVGs live in Template/markers/ (see its README).  Canvas is
    500 units wide, the line is the horizontal centerline y = H/2, and
    the QML marker offset is always "0,0" - anchoring is geometry, so a
    tooth whose base touches the centerline sits ON the stroke at every
    Weight.  Arrowheads are strokeless filled polygons (razor sharp at
    any size); param(fill)/param(outline)/param(outline-width) keep
    colour and stroke weight adjustable from the symbol.
  * slip_dextral is generated from slip_sinistral.svg by x -> 500 - x at
    run time, so the pair can never misregister again.
  * SPEC below is the whole placement story: one row per code, clean
    round numbers replacing the UI-drag artefacts (12.4193, 18.4,
    -5.55112e-17, ...).  Thrust keeps the filled tooth; Reverse gets the
    open tooth; the refolded folds get their own nested-arrow glyphs.
  * interval / offsetAlongLine / averageAngleLength / MarkerLine offset
    gain the same Weight CASE the stroke widths use (imported from
    inject_weight_scaling so the text stays byte-identical), making
    every tier a pure zoom of the Moderate design.  Scoping that here
    deliberately leaves the vein-stipple / selvedge MarkerLines alone -
    that system owns its geometry.
  * Marker size / outline_width Weight dd is written here too, from the
    same statics inject_weight_scaling would use, so its re-run stays a
    byte-identical no-op on these layers.

Confidence dashing is untouched (it lives on the backbone SimpleLine),
and the Shear Zone Boundary arrows keep riding the ORIGINAL geometry
beside the wave generator (inject_linework_shear_wave.py).

Never point this at LGS_MappingTemplate_Patterns.gpkg - that file is
re-baked wholesale by inject_basemap_lith_patterns.py.

Idempotent and re-runnable: each spec'd MarkerLine is regenerated from
SPEC + the SVG file and replaced only if the bytes differ, so a re-run
is a no-op and editing an SVG or a SPEC number then re-running is the
tuning path.  A symbol whose MarkerLine count does not match its spec
rows aborts without writing.

Usage:
    python scripts/inject_linework_marker_decorations.py [path\\to\\file.gpkg]
"""

import base64
import os
import re
import shutil
import sqlite3
import sys
import uuid
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inject_weight_scaling import FACTORS, weight_case  # noqa: E402

LW = "2 - Linework"
MARKER_DIR = "markers"          # under Template/, beside the gpkg

EXPECT_SVG_MARKERS = 23         # invariant, before and after

BACKUP_DATE = "2026-08-30"
BACKUP_NAME = "LGS_MappingTemplate_pre-marker-deco_%s.gpkg" % BACKUP_DATE

BLACK = "0,0,0,255"
RED = "255,29,29,255"
INK = "0,29,29,255"
DARK = "35,35,35,255"
NEAR = "19,19,19,255"
ORANGE = "230,81,0,255"
BROWN = "121,85,72,255"
WHITE = "255,255,255,255"
ISOGRAD = "230,145,20,255"

# ---------------------------------------------------------------------------
# The spec.  Everything a MarkerLine needs, one row per code.
#
# keys: kind (svg/simple/font), svg / shape / chr, size (+size_unit),
# color, outline (colour), ow (outline_width, mm), interval, along
# (offset_along_line), aal (average_angle_length), placements,
# ml_offset (perpendicular MarkerLine offset - becomes Weight-scaled),
# marker_offset ("x,y" marker offset - Weight-scaled y), angle,
# rows (list of placement overrides -> that many MarkerLine layers).
# ---------------------------------------------------------------------------

FOLD = dict(kind="svg", size="1.2", color=BLACK, outline=BLACK, ow="0.35",
            interval="56", along="6", aal="4.6")
FOLD_OV = dict(kind="svg", size="8.4", color=BLACK, outline=BLACK, ow="0.5",
               interval="56", along="6", aal="4.6")
TOOTH = dict(kind="svg", size="2.6", interval="16", along="7", aal="4.6")
SLIP = dict(kind="svg", size="12", ow="0.6", placements="CentralPoint",
            aal="4.6")
STEM = dict(kind="svg", svg="stem_arrow.svg", ow="0.5", aal="4")

SPEC = {
    "Antiform":              dict(FOLD, svg="fold_antiform.svg"),
    "Anticline":             dict(FOLD, svg="fold_antiform.svg"),
    "Synform":               dict(FOLD, svg="fold_synform.svg"),
    "Syncline":              dict(FOLD, svg="fold_synform.svg"),
    "Antiform - Overturned": dict(FOLD_OV, svg="fold_antiform_overturned.svg"),
    "Synform - Overturned":  dict(FOLD_OV, svg="fold_synform_overturned.svg"),
    "Antiformal Syncline":   dict(FOLD, svg="fold_antiformal_syncline.svg"),
    "Synformal Anticline":   dict(FOLD, svg="fold_synformal_anticline.svg"),

    "Fault - Thrust":  dict(TOOTH, svg="fault_tooth_filled.svg",
                            color=BLACK, outline=BLACK, ow="1"),
    "Fault - Reverse": dict(TOOTH, svg="fault_tooth_open.svg",
                            color=BLACK, outline=BLACK, ow="0.26"),
    "Shear - Reverse": dict(TOOTH, svg="fault_tooth_open.svg",
                            color=RED, outline=RED, ow="0.26"),
    "Fault - Normal":  dict(TOOTH, svg="fault_tick_normal.svg",
                            color=BLACK, outline=BLACK, ow="1"),
    "Shear - Normal":  dict(TOOTH, svg="fault_tick_normal.svg",
                            color=RED, outline=RED, ow="1"),

    "Fault - Sinistral": dict(SLIP, svg="slip_sinistral.svg",
                              color=BLACK, outline=BLACK),
    "Fault - Dextral":   dict(SLIP, svg="slip_dextral", color=BLACK,
                              outline=BLACK),
    "Shear - Sinistral": dict(SLIP, svg="slip_sinistral.svg",
                              color=RED, outline=RED),
    "Shear - Dextral":   dict(SLIP, svg="slip_dextral", color=RED,
                              outline=RED),

    "Monocline":               dict(STEM, size="2.6", interval="40",
                                    along="20", color=INK, outline=INK),
    "Shear Zone Boundary":     dict(STEM, size="2.4", interval="14",
                                    color=RED, outline=RED),
    "Stockwork Zone Boundary": dict(STEM, size="2.4", interval="14",
                                    color=ORANGE, outline=ORANGE),

    "Formline - S0 (Younging Known)": dict(
        kind="svg", svg="younging_chevron.svg", size="3", ow="0.3",
        interval="24", aal="4", color=NEAR, outline=NEAR),

    "Costean": dict(kind="svg", svg="costean_chevron.svg", size="30",
                    size_unit="Point", ow="0.9", aal="4", angle="-90",
                    color=NEAR, outline=NEAR,
                    rows=[dict(placements="FirstVertex"),
                          dict(placements="LastVertex")]),

    # SimpleMarker / FontMarker decorations: same drift/zoom fixes.
    "Detachment":     dict(kind="simple", shape="semi_circle", size="1.8",
                           interval="16", aal="4", color=WHITE, outline=INK,
                           ow="0.4"),
    "Fault - Queried": dict(kind="font", chr="?", size="4", interval="60",
                            along="30", aal="4", color=INK, outline=INK,
                            ow="0"),
    "Fold Vergence":  dict(kind="simple", shape="filled_arrowhead", size="3",
                           placements="LastVertex", aal="4", color=DARK,
                           outline=DARK, ow="0.4"),
    "Metamorphic Isograd": dict(kind="simple", shape="triangle", size="1.8",
                                interval="16", aal="4", ml_offset="1",
                                color=WHITE, outline=ISOGRAD, ow="0.4"),
    "Unconformity - Angular": dict(kind="simple", shape="line", size="1.4",
                                   interval="12", aal="4", ml_offset="1",
                                   color=DARK, outline=DARK, ow="0.4"),
    "Contact - Intrusive": dict(kind="simple", shape="line", size="2",
                                interval="10", aal="4", color=DARK,
                                outline=DARK, ow="0.4"),
    "Breakaway":  dict(kind="simple", shape="half_square", size="1.4",
                       interval="6", along="6", aal="4",
                       marker_offset=("0", "-0.8"), color=BLACK,
                       outline=DARK, ow="0"),
    "Escarpment": dict(kind="simple", shape="half_square", size="1.4",
                       interval="6", along="6", aal="4",
                       marker_offset=("0", "-0.8"), color=BROWN,
                       outline=BROWN, ow="0"),
}

NO_SCALE_3X = "3x:0,0,0,0,0,0"


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
        dest = "%s_pre-marker-deco_%s%s" % (stem, BACKUP_DATE, ext)
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
# SVG loading + the dextral mirror
# ---------------------------------------------------------------------------

def load_svgs(repo):
    d = os.path.join(repo, "Template", MARKER_DIR)
    out = {}
    for name in os.listdir(d):
        if name.endswith(".svg"):
            with open(os.path.join(d, name), "rb") as fh:
                out[name] = fh.read()
    if "slip_sinistral.svg" not in out:
        bail("Template/%s/slip_sinistral.svg missing" % MARKER_DIR)
    out["slip_dextral"] = mirror_svg(out["slip_sinistral.svg"])
    return out


def mirror_svg(data):
    """x -> 500 - x on every coordinate; <line> and <polygon> only."""
    text = data.decode("utf-8")
    if re.search(r"<path\b", text):
        bail("slip_sinistral.svg grew a <path> - the mirror only handles "
             "<line> and <polygon>; keep it to those elements")

    def flip_x(m):
        return '%s="%g"' % (m.group(1), 500.0 - float(m.group(2)))

    text = re.sub(r'\b(x1|x2)="([\d.]+)"', flip_x, text)

    def flip_points(m):
        pts = []
        for pair in m.group(1).split():
            x, y = pair.split(",")
            pts.append("%g,%s" % (500.0 - float(x), y))
        return 'points="%s"' % " ".join(pts)

    text = re.sub(r'points="([^"]+)"', flip_points, text)
    text = text.replace("Sinistral slip couple", "Dextral slip couple "
                        "(machine mirror of slip_sinistral.svg)")
    return text.encode("utf-8")


# ---------------------------------------------------------------------------
# XML builders (schemas copied from the live template's own layers)
# ---------------------------------------------------------------------------

def stable_id(code, row, role):
    return "{%s}" % uuid.uuid5(uuid.NAMESPACE_URL,
                               "lgs-marker-deco:%s:%d:%s" % (code, row, role))


def opt(parent, name, value, typ="QString"):
    # Attribute order is name, type, value - the order QGIS itself writes
    # and the order every injector's statics regex expects.
    a = {"name": name}
    if value is not None:
        a["type"] = typ
        a["value"] = value
    return ET.SubElement(parent, "Option", a)


def dd_block(props):
    """<data_defined_properties> carrying {key: expression}."""
    el = ET.Element("data_defined_properties")
    outer = ET.SubElement(el, "Option", {"type": "Map"})
    opt(outer, "name", "")
    if props:
        pcont = ET.SubElement(outer, "Option", {"name": "properties",
                                                "type": "Map"})
        for key, expr in props.items():
            entry = ET.SubElement(pcont, "Option", {"name": key,
                                                    "type": "Map"})
            opt(entry, "active", "true", "bool")
            opt(entry, "expression", expr)
            opt(entry, "type", "3", "int")
    else:
        opt(outer, "properties", None)
    opt(outer, "type", "collection")
    return el


def scaled(base):
    return "%s * %s" % (base, weight_case(FACTORS))


def marker_dd(spec):
    """Weight dd for the marker layer: baked offset, size, outline width.

    Entry order matters for convergence: inject_weight_scaling's merge
    removes and RE-APPENDS size/outlineWidth after everything else, so
    offset must come first or the two injectors rebuild each other's
    bytes forever.
    """
    props = {}
    moff = spec.get("marker_offset")
    if moff:
        x, y = moff
        props["offset"] = "'%s,' || (%s * %s)" % (x, y, weight_case(FACTORS))
    props["size"] = scaled(spec["size"])
    ow = spec.get("ow", "0")
    if float(ow) > 0:
        props["outlineWidth"] = scaled(ow)
    return props


def markerline_dd(spec, placements):
    props = {}
    if placements == "Interval":
        props["interval"] = scaled(spec["interval"])
    if float(spec.get("along", "0")) > 0:
        props["offsetAlongLine"] = scaled(spec["along"])
    props["averageAngleLength"] = scaled(spec["aal"])
    if float(spec.get("ml_offset", "0")) != 0:
        props["offset"] = scaled(spec["ml_offset"])
    return props


def build_marker_layer(code, row, spec, svgs):
    kind = spec["kind"]
    cls = {"svg": "SvgMarker", "simple": "SimpleMarker",
           "font": "FontMarker"}[kind]
    lyr = ET.Element("layer", {"id": stable_id(code, row, "marker"),
                               "class": cls, "locked": "0", "pass": "0",
                               "enabled": "1"})
    o = ET.SubElement(lyr, "Option", {"type": "Map"})
    size_unit = spec.get("size_unit", "MM")
    moff = spec.get("marker_offset")
    offset = "%s,%s" % moff if moff else "0,0"

    opt(o, "angle", spec.get("angle", "0"))
    if kind == "font":
        opt(o, "chr", spec["chr"])
    if kind == "simple":
        opt(o, "cap_style", "square")
    opt(o, "color", spec["color"])
    if kind == "svg":
        opt(o, "fixedAspectRatio", "0")
    if kind == "font":
        opt(o, "font", "Arial")
        opt(o, "font_style", "")
    opt(o, "horizontal_anchor_point", "1")
    if kind in ("simple", "font"):
        opt(o, "joinstyle", "miter" if kind == "font" else "bevel")
    if kind == "svg":
        opt(o, "name", "base64:"
            + base64.b64encode(svgs[spec["svg"]]).decode("ascii"))
    elif kind == "simple":
        opt(o, "name", spec["shape"])
    opt(o, "offset", offset)
    opt(o, "offset_map_unit_scale", NO_SCALE_3X)
    opt(o, "offset_unit", "MM")
    opt(o, "outline_color", spec["outline"])
    if kind == "simple":
        opt(o, "outline_style", "solid")
    opt(o, "outline_width", spec.get("ow", "0"))
    opt(o, "outline_width_map_unit_scale", NO_SCALE_3X)
    opt(o, "outline_width_unit", "MM")
    if kind == "svg":
        opt(o, "parameters", None)
    if kind != "font":
        opt(o, "scale_method", "diameter")
    opt(o, "size", spec["size"])
    opt(o, "size_map_unit_scale", NO_SCALE_3X)
    opt(o, "size_unit", size_unit)
    opt(o, "vertical_anchor_point", "1")
    lyr.append(dd_block(marker_dd(spec)))
    return lyr


def build_markerline(code, row, spec, sym_name, layer_index, svgs,
                     placements):
    lyr = ET.Element("layer", {"id": stable_id(code, row, "ml"),
                               "class": "MarkerLine", "locked": "0",
                               "pass": "0", "enabled": "1"})
    o = ET.SubElement(lyr, "Option", {"type": "Map"})
    opt(o, "average_angle_length", spec["aal"])
    opt(o, "average_angle_map_unit_scale", NO_SCALE_3X)
    opt(o, "average_angle_unit", "MM")
    opt(o, "interval", spec.get("interval", "3"))
    opt(o, "interval_map_unit_scale", NO_SCALE_3X)
    opt(o, "interval_unit", "MM")
    opt(o, "offset", spec.get("ml_offset", "0"))
    opt(o, "offset_along_line", spec.get("along", "0"))
    opt(o, "offset_along_line_map_unit_scale", NO_SCALE_3X)
    opt(o, "offset_along_line_unit", "MM")
    opt(o, "offset_map_unit_scale", NO_SCALE_3X)
    opt(o, "offset_unit", "MM")
    opt(o, "place_on_every_part", "true", "bool")
    opt(o, "placements", placements)
    opt(o, "ring_filter", "0")
    opt(o, "rotate", "1")
    lyr.append(dd_block(markerline_dd(spec, placements)))
    sub = ET.SubElement(lyr, "symbol", {
        "name": "@%s@%d" % (sym_name, layer_index), "frame_rate": "10",
        "clip_to_extent": "1", "alpha": "1", "type": "marker",
        "force_rhr": "0", "is_animated": "0"})
    sub.append(dd_block({}))
    sub.append(build_marker_layer(code, row, spec, svgs))
    return ET.tostring(lyr, encoding="unicode")


# ---------------------------------------------------------------------------
# QML surgery
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


def toplevel_layer_spans(sym_xml):
    """(start, end, class) of each layer that is a DIRECT child of the
    outer symbol - nested sub-symbol layers stay untouched."""
    spans = []
    depth_sym = depth_layer = 0
    start = None
    for t in re.finditer(r'<symbol\b|</symbol>|<layer\b|</layer>', sym_xml):
        tok = t.group(0)
        if tok == '<symbol':
            depth_sym += 1
        elif tok == '</symbol>':
            depth_sym -= 1
        elif tok == '<layer':
            if depth_sym == 1 and depth_layer == 0:
                start = t.start()
            depth_layer += 1
        else:
            depth_layer -= 1
            if depth_layer == 0 and start is not None:
                cls = re.search(r'class="(\w+)"', sym_xml[start:start + 200])
                spans.append((start, t.end(), cls.group(1)))
                start = None
    return spans


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
    svgs = load_svgs(repo)

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
    svg_before = renderer.count('class="SvgMarker"')
    if svg_before != EXPECT_SVG_MARKERS:
        bail("expected %d SvgMarkers before the rebuild, found %d"
             % (EXPECT_SVG_MARKERS, svg_before))

    rebuilt = kept = 0
    # Work code by code; recompute spans after each symbol edit.
    for code, spec in sorted(SPEC.items()):
        cm = re.search(r'<category[^>]*value="%s"[^>]*/>' % re.escape(code),
                       renderer)
        if not cm:
            bail("Linework category %r not found" % code)
        sym_name = re.search(r'symbol="(\d+)"', cm.group(0)).group(1)
        s, e = symbol_span(renderer, sym_name)
        sym_xml = renderer[s:e]
        spans = toplevel_layer_spans(sym_xml)
        ml_spans = [(a, b) for a, b, cls in spans if cls == "MarkerLine"]
        rows = spec.get("rows", [None])
        if len(ml_spans) != len(rows):
            bail("%s: %d MarkerLine layer(s), spec has %d row(s) - the "
                 "symbol is not in a shape this injector understands"
                 % (code, len(ml_spans), len(rows)))
        edits = []
        for n, ((a, b), override) in enumerate(zip(ml_spans, rows)):
            row_spec = dict(spec, **override) if override else spec
            placements = row_spec.get("placements", "Interval")
            layer_index = next(i for i, (sa, _sb, _c) in enumerate(spans)
                               if sa == a)
            new_xml = build_markerline(code, n, row_spec, sym_name,
                                       layer_index, svgs, placements)
            if sym_xml[a:b] == new_xml:
                kept += 1
            else:
                edits.append((a, b, new_xml))
                rebuilt += 1
        for a, b, new_xml in reversed(edits):
            sym_xml = sym_xml[:a] + new_xml + sym_xml[b:]
        renderer = renderer[:s] + sym_xml + renderer[e:]

    if rebuilt == 0:
        print("already applied: %d MarkerLine(s) match the spec - nothing "
              "to do" % kept)
        con.close()
        return
    print("rebuilding %d MarkerLine(s) (%d already current)" % (rebuilt, kept))

    svg_after = renderer.count('class="SvgMarker"')
    if svg_after != EXPECT_SVG_MARKERS:
        bail("SvgMarker count moved: %d -> %d" % (svg_before, svg_after))

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
    con.close()
    root = ET.fromstring(q)
    rend = root.find("renderer-v2")
    svgs_found = [l for l in rend.iter("layer")
                  if l.get("class") == "SvgMarker"]
    assert len(svgs_found) == EXPECT_SVG_MARKERS, len(svgs_found)
    for lyr in svgs_found:
        o = {x.get("name"): x.get("value")
             for x in lyr.find("Option").findall("Option")}
        body = base64.b64decode(o["name"].split("base64:")[1])
        assert b"param(fill)" in body or b'fill="none"' in body, "unparam'd"
        assert b"param(outline)" in body or lyr.get("id").startswith(
            "{"), "unparam'd outline"
    # thrust and reverse must no longer share artwork
    def svg_of(code):
        for cat in rend.iter("category"):
            if cat.get("value") == code:
                s, e = symbol_span(q, cat.get("symbol"))
                m = re.search(r'value="base64:([^"]+)"', q[s:e])
                return m.group(1)
    assert svg_of("Fault - Thrust") != svg_of("Fault - Reverse")
    assert svg_of("Antiformal Syncline") != svg_of("Antiform - Overturned")
    assert svg_of("Synformal Anticline") != svg_of("Synform - Overturned")
    assert svg_of("Fault - Sinistral") != svg_of("Fault - Dextral")
    print("done: %d MarkerLine(s) rebuilt from Template/%s + SPEC"
          % (rebuilt, MARKER_DIR))


if __name__ == "__main__":
    main()
