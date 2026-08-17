"""Give the 125 Overlay Alteration washes a fine dashed self-coloured outline.

Nested same-alteration zones (Intensity 5 core -> 3 -> 1, clipped into each
other) are indistinguishable at their shared boundaries because the Alteration
wash draws no outline. This adds a dedicated SimpleLine outline layer to each
of the 125 Alteration symbols:

    - solid pen + custom dash 1.5;0.7 MM - the same dash pattern as the
      Basemap contact outlines, so zone edges read at the map's established
      dash length (a SimpleFill's preset "dash" pen scales its dashes with
      the pen width, which at 0.3 Point is illegibly fine);
    - line_width 0.3 Point (the approved fine weight), colour taken from the
      wash fill's authored outline_color (mineral hue, full alpha);
    - ring_filter 0: dashes on exterior AND interior rings, so clipped
      annuli are outlined on both edges.

The wash SimpleFill's own outline_style is (re)set to "no" - the outline is
the line layer's job (this also migrates the earlier revision of this script,
which set the fill pen to "dash").

Scope is the 125 Alteration category symbol blocks only (codes from
OverlayCodes WHERE Type='Alteration'). Weathering (dash, 0.5 Point),
Infrastructure, Structure zones and the labeling block are untouched, and
inject_weight_scaling.py never scales these outlines (its Intensity map has
no SimpleLine entry).

Idempotent and re-runnable: requires exactly 0 (already applied) or 125
(fresh/migrating) edits, anything else aborts without writing. Each edited
symbol block is ET round-tripped, which normalises its whitespace on first
run - semantics are unchanged and validated.

Usage:  python scripts/inject_overlay_alteration_outline.py [path\\to\\gpkg]
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
EXPECT_ALTERATION = 125
WASH_WIDTH = "0.3"         # Point; identifies the wash SimpleFill in each block
OUTLINE_DASH = "1.5;0.7"   # MM dash;gap - matches the Basemap contact outlines
OUTLINE_WIDTH = "0.3"      # Point - the approved fine weight
MUS = "3x:0,0,0,0,0,0"

# Full SimpleLine option set, modelled on the Basemap contact outline layers.
LINE_OPTS = {
    "align_dash_pattern": "0",
    "capstyle": "square",
    "customdash": OUTLINE_DASH,
    "customdash_map_unit_scale": MUS,
    "customdash_unit": "MM",
    "dash_pattern_offset": "0",
    "dash_pattern_offset_map_unit_scale": MUS,
    "dash_pattern_offset_unit": "MM",
    "draw_inside_polygon": "0",
    "joinstyle": "bevel",
    "line_color": None,  # filled per symbol from the wash outline_color
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
    "use_custom_dash": "1",
    "width_map_unit_scale": MUS,
}


def bail(msg):
    raise SystemExit("ABORT: " + msg)


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


def layer_opts(layer_el):
    return {o.get("name"): o for o in layer_el.iter("Option") if o.get("name")}


def build_outline_layer(code, color):
    layer = ET.Element("layer", {
        "id": "{%s}" % uuid.uuid5(uuid.NAMESPACE_URL, "lgs-alt-outline:" + code),
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


def is_our_outline(layer_el):
    if layer_el.get("class") != "SimpleLine":
        return False
    opts = layer_opts(layer_el)
    return (opts.get("use_custom_dash") is not None
            and opts["use_custom_dash"].get("value") == "1"
            and opts.get("customdash") is not None
            and opts["customdash"].get("value") == OUTLINE_DASH)


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    cur.execute("SELECT Code FROM OverlayCodes WHERE Type='Alteration'")
    codes = [r[0] for r in cur.fetchall()]
    if len(codes) != EXPECT_ALTERATION:
        bail(f"expected {EXPECT_ALTERATION} Alteration codes, found {len(codes)}")

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

        wash = None
        for lyr in sym_el.findall("layer"):
            if lyr.get("class") != "SimpleFill":
                continue
            opts = layer_opts(lyr)
            if opts.get("outline_width") is not None \
                    and opts["outline_width"].get("value") == WASH_WIDTH:
                wash = lyr
                break
        if wash is None:
            bail(f"{code!r}: wash SimpleFill (outline_width {WASH_WIDTH}) not found")
        opts = layer_opts(wash)

        edited = False
        style = opts["outline_style"].get("value")
        if style == "dash":  # migrate the earlier fill-pen-dash revision
            opts["outline_style"].set("value", "no")
            edited = True
        elif style != "no":
            bail(f"{code!r}: unexpected wash outline_style {style!r}")

        if not any(is_our_outline(l) for l in sym_el.findall("layer")):
            color = opts["outline_color"].get("value")  # mineral hue, alpha 255
            sym_el.append(build_outline_layer(code, color))
            edited = True

        if edited:
            qml = qml[:s] + ET.tostring(sym_el, encoding="unicode") + qml[e:]
            changed += 1
        else:
            already += 1
    if changed not in (0, EXPECT_ALTERATION):
        bail(f"partial prior state: would change {changed} of {EXPECT_ALTERATION}; not writing")

    # Validate BEFORE writing: never persist a QML that no longer parses.
    try:
        ET.fromstring(qml)
    except ET.ParseError as exc:
        bail(f"edited QML no longer parses, aborting without write: {exc}")

    if changed:
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?", (qml, LAYER))
        assert cur.rowcount == 1
        con.commit()
        print(f"styleQML updated: {changed} Alteration dashed outline layers")
    else:
        print(f"already applied (no change): {already} Alteration outlines present")

    # Validate: gpkg intact, QML parses, outline population exactly as designed.
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    final = cur.fetchone()[0]
    root = ET.fromstring(final)
    fills = Counter()
    outlines = 0
    for lyr in root.iter("layer"):
        cls = lyr.get("class")
        if cls == "SimpleFill":
            opts = {o.get("name"): o.get("value")
                    for o in lyr.iter("Option") if o.get("name")}
            fills[(opts.get("outline_style"), opts.get("outline_width"))] += 1
        elif is_our_outline(lyr):
            outlines += 1
    assert outlines == EXPECT_ALTERATION, f"{outlines} outline line layers"
    assert fills[("no", WASH_WIDTH)] == EXPECT_ALTERATION, fills
    assert fills[("dash", WASH_WIDTH)] == 0, fills   # fill-pen dash fully migrated
    assert fills[("dash", "0.5")] == 4, fills        # Weathering untouched
    assert fills[("solid", "0.35")] == 8, fills      # Infrastructure untouched
    print(f"round-trip ok: {outlines} dashed outline layers ({OUTLINE_DASH} MM), "
          f"fills {dict(fills)}")
    con.close()


if __name__ == "__main__":
    main()
