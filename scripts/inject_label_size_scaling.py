"""Scale label sizes with feature significance (Aug 2026 field feedback).

Big features carried the same label size as hairline veins and sliver
polygons, so busy maps read wrong.  Injects a data-defined SIZE
expression into the simple-labeling settings of three layers:

    2 - Linework   base * Weight factor * recorded-width factor
                   (width factor mirrors the stroke ramp, dampened -
                   same detail-scope gate as inject_weight_scaling)
    3 - Overlay    base * Weight factor * on-screen-extent factor
    4 - Basemap    base * on-screen-extent factor

Every layer also carries the paper factor, which takes label text out of
QGIS' reference-scale multiplier so lettering holds its authored point
size at any zoom.  See PAPER_F below for why that is needed at all.

The extent factor is screen-relative (sqrt($area)*1000/@map_scale =
the polygon's characteristic size in mm at the current map scale), so
it behaves identically at UG 1:100 and surface 1:10,000 without any
per-project configuration: polygons smaller than ~8 mm on screen label
at 0.7x, under ~16 mm at 0.85x, everything else at the authored size.

'1 - FieldNotebook' (rule-based point labeling) is untouched.

Idempotent and re-runnable: the expression is rebuilt from each layer's
CURRENT static fontSize, so re-run after restyling label fonts in QGIS
(same re-bake rule as inject_weight_scaling.py).

Usage:  python scripts/inject_label_size_scaling.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

DETAIL_GATE = ("(\"Category\" IN ('Veins','Lithology') "
               "OR \"Type\" LIKE 'Fault%' OR \"Type\" LIKE 'Shear%' "
               "OR \"Type\" IN ('Shear Zone Boundary','Detachment'))")

# Kept in step with the baked label fontSize expression by
# inject_weight_five_tiers.py, which is the one that is NOT safely
# re-runnable - it multiplies factors into current statics. THIS file is,
# because it rebuilds the whole expression from the static fontSize rather
# than from whatever expression is already there. Worth being explicit:
# the sentence used to say "this script itself", and a second pair of eyes
# read it as a warning against re-running this one.
WEIGHT_F = ("CASE WHEN \"Weight\" = 'Regional' THEN 1.3 "
            "WHEN \"Weight\" = 'Major' THEN 1.15 "
            "WHEN \"Weight\" = 'Minor' THEN 0.8 "
            "WHEN \"Weight\" = 'Very Minor' THEN 0.7 ELSE 1 END")

# 0 counts as UNRECORDED, not "0 cm wide" - same guard as
# inject_linework_vein_fields.WIDTH_TEXT, so a stray 0 cannot shrink the
# label to 0.7x.  (This label-size ramp is the ONLY ramp Width_cm still
# drives: the stroke-width twin it once had in inject_weight_scaling was
# removed 27 Aug 2026 - drawn thickness is Weight-only.)
WIDTH_F = (
    "CASE WHEN " + DETAIL_GATE + " AND coalesce(\"Width_cm\", 0) > 0 THEN "
    "(CASE WHEN \"Width_cm\" <= 0.5 THEN 0.7 "
    "WHEN \"Width_cm\" <= 2 THEN 0.85 "
    "WHEN \"Width_cm\" <= 5 THEN 1 "
    "WHEN \"Width_cm\" <= 10 THEN 1.1 "
    "ELSE 1.2 END) ELSE 1 END"
)

# Characteristic on-screen size in mm; degenerate scale -> factor 1.
EXTENT_MM = "(sqrt($area) * 1000.0 / @map_scale)"
EXTENT_F = (
    "CASE WHEN coalesce(@map_scale, 0) <= 0 THEN 1 "
    "WHEN " + EXTENT_MM + " < 8 THEN 0.7 "
    "WHEN " + EXTENT_MM + " < 16 THEN 0.85 "
    "ELSE 1 END"
)

# Cover round 3: Transported Cover labels sit a step above the lithology
# lettering (6.5 pt against the 5.5 pt static), the size half of the gold
# identity that inject_cover_gold_round3.py paints. Written as a ratio so a
# restyled static fontSize keeps cover proportionally larger.
COVER_F = ("CASE WHEN \"TypeLith1\" = 'Transported Cover' "
           "THEN (6.5 / 5.5) ELSE 1 END")

# Undo QGIS' reference-scale multiplier, for label text only.
#
# QGIS multiplies EVERY rendered size by referenceScale/mapScale - measured
# against QgsRenderContext.convertToPainterUnits, Points, Millimeters, Pixels,
# MapUnits, MetersInMapUnits and Inches all take the same factor, so there is
# no unit to escape into.  That is right for symbols: a 30 pt structural
# marker is meant to cover a fixed patch of ground.  It is wrong for lettering,
# which has to stay legible rather than stay proportional, and at a 1:100,000
# reference scale a 5.5 pt label draws at 27 pt by the time you are in at
# 1:20,000.  Multiplying by the inverse leaves the authored point size at every
# zoom, and leaves it untouched at the reference scale itself.
#
# QGIS exposes no reference-scale expression variable (@map_scale is the only
# scale in the context), so the plugin publishes one: script_setmapping writes
# @lgs_reference_scale whenever it sets the reference scale, and
# script_loadtemplate seeds it for a project that never runs Set Mapping Scale.
# TEMPLATE_REFERENCE_SCALE is the fallback for anything older, and
# tests/test_label_size_invariance_qgis.py pins it to the referencescale the
# template actually carries so the two cannot drift apart in silence.
#
# Both coalesce guards are load-bearing: a NULL number reads as 0 in a QGIS
# expression, and an unguarded divide would take every label to zero.
TEMPLATE_REFERENCE_SCALE = 5000
REF_SCALE = "coalesce(to_real(@lgs_reference_scale), %d)" % TEMPLATE_REFERENCE_SCALE
PAPER_F = ("CASE WHEN coalesce(@map_scale, 0) > 0 AND " + REF_SCALE + " > 0 "
           "THEN @map_scale / " + REF_SCALE + " ELSE 1 END")

LAYER_FACTORS = {
    "2 - Linework": [WEIGHT_F, WIDTH_F, PAPER_F],
    "3 - Overlay": [WEIGHT_F, EXTENT_F, PAPER_F],
    "4 - Basemap": [COVER_F, EXTENT_F, PAPER_F],
}


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


def size_expression(base, factors):
    return base + " * (" + ") * (".join(factors) + ")"


def inject_size(settings, expr):
    dd = settings.find("dd_properties")
    if dd is None:
        return False
    outer = dd.find("Option")
    if outer is None:
        outer = ET.SubElement(dd, "Option", {"type": "Map"})
    props = None
    for o in outer.findall("Option"):
        if o.get("name") == "properties":
            props = o
    if props is None:
        props = ET.SubElement(outer, "Option", {"name": "properties"})
    props.set("type", "Map")
    props.attrib.pop("value", None)
    for o in props.findall("Option"):
        if o.get("name") == "Size":
            props.remove(o)
    entry = ET.SubElement(props, "Option", {"name": "Size", "type": "Map"})
    ET.SubElement(entry, "Option",
                  {"name": "active", "type": "bool", "value": "true"})
    ET.SubElement(entry, "Option",
                  {"name": "expression", "type": "QString", "value": expr})
    ET.SubElement(entry, "Option", {"name": "type", "type": "int", "value": "3"})
    return True


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    for layer, factors in LAYER_FACTORS.items():
        cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                    (layer,))
        row = cur.fetchone()
        if not row or not row[0]:
            bail(f"no styleQML for {layer!r}")
        qml = row[0]
        lm = re.search(r'<labeling type="simple">.*?</labeling>', qml, re.S)
        if not lm:
            bail(f"{layer}: simple labeling block not found")
        lab = ET.fromstring(lm.group(0))
        settings = lab.find("settings")
        ts = settings.find("text-style")
        base = ts.get("fontSize")
        try:
            assert float(base) > 0
        except (TypeError, ValueError, AssertionError):
            bail(f"{layer}: bad static fontSize {base!r}")
        expr = size_expression(base, factors)
        if not inject_size(settings, expr):
            bail(f"{layer}: settings-level dd_properties not found")
        qml = (qml[:lm.start()] + ET.tostring(lab, encoding="unicode")
               + qml[lm.end():])
        try:
            ET.fromstring(qml)
        except ET.ParseError as exc:
            bail(f"{layer}: edited QML no longer parses, aborting: {exc}")
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, layer))
        assert cur.rowcount == 1
        print(f"{layer}: dd label Size = {base} * {len(factors)} factor(s)")

    con.commit()
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])

    # --- Round-trip validation. ---
    for layer, factors in LAYER_FACTORS.items():
        cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                    (layer,))
        root = ET.fromstring(cur.fetchone()[0])
        settings = root.find(".//labeling/settings")
        base = settings.find("text-style").get("fontSize")
        dd = settings.find("dd_properties")
        found = None
        for props in dd.iter("Option"):
            if props.get("name") == "Size":
                for o in props.findall("Option"):
                    if o.get("name") == "expression":
                        found = o.get("value")
        assert found == size_expression(base, factors), f"{layer} Size dd wrong"
        print(f"QML parses, Size dd verified: {layer}")
    con.close()


if __name__ == "__main__":
    main()
