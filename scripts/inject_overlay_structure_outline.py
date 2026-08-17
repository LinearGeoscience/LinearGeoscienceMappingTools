"""Clip the Overlay Structure zone hatches to their polygons; add a border.

The 9 Structure zone symbols (codes from OverlayCodes WHERE
Type='Structure') were authored as boundary-free hatches: their
LinePatternFill layers carry clip_mode="no" (Do not clip), so the hatch
lines render across the full pattern tile grid and bleed past the polygon
boundary; and no symbol has any outline layer at all. This fixes both:

    - clip_mode "no" -> "shape" (ClipToIntersection) on every
      LinePatternFill in the Structure symbols: hatch geometry is clipped
      to the feature, so line ends land exactly on the boundary — correct
      with the data-defined lineAngle rotation, unlike a painter-only
      clip which leaves artefacts where zones overlap. The two
      PointPatternFill Structure symbols (Breccia Zone, Crackle Breccia
      Zone) already clip with "completely_within" and are untouched.
    - a dedicated SimpleLine border appended to all 9 symbols:
      solid, line_width 0.4 Point (heavier than the 0.3 Alteration dash,
      in line with Infrastructure's 0.35 solid), self-coloured from the
      pattern's colour at full alpha, ring_filter 0 so clipped annuli are
      outlined on both edges. Deliberately NOT the 1.5;0.7 MM custom dash
      of the Alteration outlines — a matching signature would break
      inject_overlay_alteration_outline.py's population asserts.

Run scripts/inject_weight_scaling.py afterwards: its Overlay-zone pass
merges the Weight scaling expression onto SimpleLine.line_width, so the
new border tracks zone weight exactly like the hatch lines do.

Idempotent and re-runnable: requires exactly 0 (already applied) or 9
(fresh) symbol edits, anything else aborts without writing. Each edited
symbol block is ET round-tripped, which normalises its whitespace on
first run - semantics are unchanged and validated. Borders are matched
by their deterministic uuid5 layer ids, never by style signature.

Usage:  python scripts/inject_overlay_structure_outline.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import uuid
import xml.etree.ElementTree as ET
from collections import Counter

LAYER = "3 - Overlay"
EXPECT_STRUCTURE = 9
EXPECT_LPF = 8            # LinePatternFill layers across the 9 symbols (Stockwork has 2)
EXPECT_ALT_OUTLINES = 125  # Alteration dashed outlines must stay untouched
CLIP_FROM = "no"
CLIP_TO = "shape"          # ClipToIntersection
OUTLINE_WIDTH = "0.4"      # Point - between Infrastructure 0.35 and Pit Outline 0.45
ALT_OUTLINE_DASH = "1.5;0.7"
MUS = "3x:0,0,0,0,0,0"

# Full SimpleLine option set, modelled on inject_overlay_alteration_outline
# but solid / no custom dash (see docstring for why the dash must differ).
LINE_OPTS = {
    "align_dash_pattern": "0",
    "capstyle": "square",
    "customdash": "5;2",
    "customdash_map_unit_scale": MUS,
    "customdash_unit": "MM",
    "dash_pattern_offset": "0",
    "dash_pattern_offset_map_unit_scale": MUS,
    "dash_pattern_offset_unit": "MM",
    "draw_inside_polygon": "0",
    "joinstyle": "bevel",
    "line_color": None,  # filled per symbol from the pattern colour
    "line_style": "solid",
    "line_width": OUTLINE_WIDTH,
    "line_width_unit": "Point",
    "offset": "0",
    "offset_map_unit_scale": MUS,
    "offset_unit": "MM",
    "ring_filter": "0",
    "trim_distance_end": "0",
    "trim_distance_end_map_unit_scale": MUS,
    "trim_distance_end_unit": "MM",
    "trim_distance_start": "0",
    "trim_distance_start_map_unit_scale": MUS,
    "trim_distance_start_unit": "MM",
    "tweak_dash_pattern_on_corners": "0",
    "use_custom_dash": "0",
    "width_map_unit_scale": MUS,
}


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def outline_id(code):
    return "{%s}" % uuid.uuid5(uuid.NAMESPACE_URL, "lgs-struct-outline:" + code)


def symbol_block(q, name):
    m = re.search(r'<symbol\b[^>]*\bname="%s"[^>]*>' % re.escape(name), q)
    if not m:
        bail(f"symbol {name!r} not found")
    depth = 0
    for t in re.finditer(r'<symbol\b|</symbol>', q[m.start():]):
        depth += 1 if t.group(0) == '<symbol' else -1
        if depth == 0:
            return m.start(), m.start() + t.end()
    bail(f"unbalanced symbol {name!r}")


def direct_opts(layer_el):
    """The layer's OWN options - never descend into pattern sub-symbols."""
    cont = layer_el.find("Option")
    if cont is None:
        return {}
    return {o.get("name"): o for o in cont.findall("Option")}


def full_alpha(color):
    parts = (color or "").split(",")
    if len(parts) >= 4 and parts[3].isdigit():
        parts[3] = "255"
    return ",".join(parts)


def pattern_color(code, sym_el):
    """Border colour: the hatch line colour, or the point pattern's marker."""
    for lyr in sym_el.findall("layer"):
        if lyr.get("class") == "LinePatternFill":
            opt = direct_opts(lyr).get("color")
            if opt is not None:
                return full_alpha(opt.get("value"))
    for lyr in sym_el.findall("layer"):
        if lyr.get("class") != "PointPatternFill":
            continue
        for sub in lyr.iter("layer"):
            if sub.get("class") == "SimpleMarker":
                opt = direct_opts(sub).get("color")
                if opt is not None:
                    return full_alpha(opt.get("value"))
    bail(f"{code!r}: no pattern colour found")


def build_outline_layer(code, color):
    layer = ET.Element("layer", {
        "id": outline_id(code),
        "class": "SimpleLine", "locked": "0", "pass": "0", "enabled": "1",
    })
    opts = ET.SubElement(layer, "Option", {"type": "Map"})
    for name, value in LINE_OPTS.items():
        if name == "line_color":
            value = color
        ET.SubElement(opts, "Option",
                      {"name": name, "type": "QString", "value": value})
    dd = ET.SubElement(layer, "data_defined_properties")
    outer = ET.SubElement(dd, "Option", {"type": "Map"})
    ET.SubElement(outer, "Option", {"name": "name", "type": "QString", "value": ""})
    ET.SubElement(outer, "Option", {"name": "properties"})
    ET.SubElement(outer, "Option", {"name": "type", "type": "QString",
                                    "value": "collection"})
    return layer


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    cur.execute("SELECT Code FROM OverlayCodes WHERE Type='Structure'")
    codes = [r[0] for r in cur.fetchall()]
    if len(codes) != EXPECT_STRUCTURE:
        bail(f"expected {EXPECT_STRUCTURE} Structure codes, found {len(codes)}")
    expected_ids = {outline_id(code) for code in codes}

    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    row = cur.fetchone()
    if not row or not row[0]:
        bail(f"no styleQML for {LAYER!r}")
    qml = row[0]

    changed = 0
    already = 0
    for code in codes:
        # Re-search on the current string each iteration: replacements change
        # length, so offsets shift as edits are spliced in.
        cm = re.search(r'<category[^>]*value="%s"[^>]*/>' % re.escape(code), qml)
        if not cm:
            bail(f"Overlay category {code!r} not found")
        sym = re.search(r'symbol="(\d+)"', cm.group(0)).group(1)
        s, e = symbol_block(qml, sym)
        sym_el = ET.fromstring(qml[s:e])

        edited = False
        for lyr in sym_el.findall("layer"):
            if lyr.get("class") != "LinePatternFill":
                continue
            clip = direct_opts(lyr).get("clip_mode")
            if clip is None:
                bail(f"{code!r}: LinePatternFill without clip_mode")
            value = clip.get("value")
            if value == CLIP_FROM:
                clip.set("value", CLIP_TO)
                edited = True
            elif value != CLIP_TO:
                bail(f"{code!r}: unexpected clip_mode {value!r}")

        if not any(l.get("id") in expected_ids for l in sym_el.findall("layer")):
            sym_el.append(build_outline_layer(code, pattern_color(code, sym_el)))
            edited = True

        if edited:
            qml = qml[:s] + ET.tostring(sym_el, encoding="unicode") + qml[e:]
            changed += 1
        else:
            already += 1
    if changed not in (0, EXPECT_STRUCTURE):
        bail(f"partial prior state: would change {changed} of {EXPECT_STRUCTURE}; not writing")

    # Validate BEFORE writing: never persist a QML that no longer parses.
    try:
        ET.fromstring(qml)
    except ET.ParseError as exc:
        bail(f"edited QML no longer parses, aborting without write: {exc}")

    if changed:
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?", (qml, LAYER))
        assert cur.rowcount == 1
        con.commit()
        print(f"styleQML updated: {changed} Structure symbols (clip + border)")
    else:
        print(f"already applied (no change): {already} Structure symbols ok")

    # Validate: gpkg intact, QML parses, clip modes + border population exact,
    # Alteration outlines untouched.
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    final = cur.fetchone()[0]
    root = ET.fromstring(final)
    lpf_clips = Counter()
    borders = 0
    alt_outlines = 0
    for lyr in root.iter("layer"):
        cls = lyr.get("class")
        opts = {o.get("name"): o.get("value")
                for o in lyr.iter("Option") if o.get("name")}
        if cls == "LinePatternFill":
            lpf_clips[opts.get("clip_mode")] += 1
        elif cls == "SimpleLine":
            if lyr.get("id") in expected_ids:
                borders += 1
                assert opts.get("line_width") == OUTLINE_WIDTH, opts.get("line_width")
                assert opts.get("line_style") == "solid"
                assert opts.get("ring_filter") == "0"
                assert opts.get("line_color", "").split(",")[3:4] == ["255"]
            elif opts.get("use_custom_dash") == "1" \
                    and opts.get("customdash") == ALT_OUTLINE_DASH:
                alt_outlines += 1
    assert lpf_clips == {CLIP_TO: EXPECT_LPF}, lpf_clips
    assert borders == EXPECT_STRUCTURE, f"{borders} border layers"
    assert alt_outlines == EXPECT_ALT_OUTLINES, f"{alt_outlines} alteration outlines"
    print(f"round-trip ok: {dict(lpf_clips)} hatch clips, {borders} borders "
          f"({OUTLINE_WIDTH} Point solid), {alt_outlines} alteration outlines intact")
    con.close()


if __name__ == "__main__":
    main()
