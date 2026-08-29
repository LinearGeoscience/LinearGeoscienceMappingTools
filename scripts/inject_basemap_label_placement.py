"""Give Basemap lithology labels mobility instead of at-no-cost stamping.

At dense mapping scales the baked Basemap labeling drew every lithology
label at the polygon centroid with overlapHandling=AllowOverlapAtNoCost:
the engine never even attempted avoidance, so "SST (Very Coarse Grained)"
landed straight on top of structure dip symbols and dip numbers. This
switches the "4 - Basemap" simple labeling to the proven Overlay pattern
(scripts/inject_overlay_label_placement.py):

    - polygonPlacementFlags=3 + fitInPolygonOnly=1: inside placement is
      preferred and only used when the label truly fits; otherwise the
      label steps just outside the polygon...
    - ...where the callout draws the leader back to the polygon edge.
      The authored callout was manhattan; it is converted to the straight
      "simple" type because the right-angle elbow at the label end reads
      badly (user decision 2026-08-29) - one leader look across Basemap,
      Overlay and the FieldNotebook comments. dist=18.75 map units - HALF
      the Overlay ring (script_setmapping.BASEMAP_DIST_FACTOR), because
      leader lines on lithology labels must stay short (user decision
      2026-08-29).
      maximumDistance is kept mirrored at 5x dist purely for consistency
      (inert for polygon placement). minLength 1 MM so no stub is drawn
      on inside-placed labels.
    - overlapHandling=PreventOverlap: a lithology label that has nowhere
      free is dropped rather than stamped over its neighbours. It was
      AllowOverlapIfRequired, which on a 1141-polygon sheet meant "never
      vanish" resolved to "pile up" - the polygon still carries its colour
      and its texture, so the code is the one thing that can be spared,
      and it comes back as soon as zooming in opens up room. Linework and
      Overlay deliberately keep AllowOverlapIfRequired: a vein width is a
      measurement, not a restatement of the fill.
    - priority=6: below the structure lettering (dip 10, suffix 8),
      above Linework 5 / Overlay 4 / comments 3.
    - rendering obstacle=0: Basemap fills tile the whole map, so
      interior-obstacle cost is uniform noise that only distorts
      candidate costs near contacts.

The map-unit distances are baked for the template's
symbologyReferenceScale of 5000; Set Mapping Scale rescales dist /
maximumDistance per mapping scale (script_setmapping.py
rescale_overlay_label_distance with factor=BASEMAP_DIST_FACTOR) while
everything else here persists.

Untouched: the label expression (its string literals carry HTML - never
normalise it), fonts, the settings-level dd_properties (auxiliary-storage
label moves plus the injected Color/Size expressions), and the renderer.
Only individual XML attributes are edited, never whole blocks, so
concurrent injectors owning other attributes of the same elements are
safe.

Run against BOTH Template/LGS_MappingTemplate.gpkg (default) and
Template/LGS_MappingTemplate_Patterns.gpkg - the patterns re-bake
(inject_basemap_lith_patterns.py) regenerates the Patterns Basemap style
from a copy of the live template, but until that next runs the two must
agree by themselves.

Idempotent and re-runnable. The labeling block is parsed and edited with
ElementTree (this region of the QML jams tags onto shared lines, so regex
editing is unsafe); the first run therefore also normalises the block's
whitespace formatting - semantics are unchanged and validated.

Usage:  python scripts/inject_basemap_label_placement.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

LAYER = "4 - Basemap"

# 0.5 x the Overlay/FieldNotebook callout ring unit U=37.5
# (callout_dist_for_scale(5000)) - short leaders, per BASEMAP_DIST_FACTOR.
PLACEMENT_ATTRS = {
    "placement": "4",               # Horizontal (already authored)
    "polygonPlacementFlags": "3",   # inside (preferred) + outside allowed
    "fitInPolygonOnly": "1",        # inside only when the label truly fits
    "dist": "18.75",                # 0.5 x U
    "distUnits": "MapUnit",
    "maximumDistance": "93.75",     # 5 x dist
    "maximumDistanceUnit": "MapUnit",
    "overlapHandling": "PreventOverlap",
    "priority": "6",
}
CALLOUT_TYPE = "simple"             # straight leader; manhattan's elbow reads badly
CALLOUT_FROM_TYPES = ("manhattan", CALLOUT_TYPE)
CALLOUT_OPTS = {
    "enabled": "1",
    "minLength": "1",               # MM; no stub on inside-placed labels
    # Same end gaps as every other leader on the map (Overlay,
    # FieldNotebook comments).
    "offsetFromAnchor": "0.5",
    "offsetFromLabel": "1",
}
RENDERING_ATTRS = {
    "obstacle": "0",
    # A polygon has to be 2 mm across on the rendered page before it is
    # worth lettering. This was hand-authored in the template and owned by
    # no script, so clearing it in QGIS would have stuck; it is asserted
    # here now. The number is deliberately unchanged - raising it thins the
    # long tail of leader lines, but it also changes what a 1:1000 field
    # project draws, so tune it against a rendered sheet, not in the
    # abstract.
    "minFeatureSize": "2",
}


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    row = cur.fetchone()
    if not row or not row[0]:
        bail(f"no styleQML for {LAYER!r}")
    qml = row[0]

    m = re.search(r'<labeling type="simple">.*?</labeling>', qml, re.S)
    if not m:
        bail('simple <labeling> block not found')
    lab = ET.fromstring(m.group(0))

    settings = lab.find("settings")
    if settings is None:
        bail("labeling <settings> not found")

    # Captured to prove the HTML label expression survives untouched.
    field_name_before = settings.find("text-style").get("fieldName")

    placement = settings.find("placement")
    for k, v in PLACEMENT_ATTRS.items():
        if placement.get(k) != v:
            placement.set(k, v)
            print(f"placement {k} -> {v}")

    rendering = settings.find("rendering")
    if rendering is None:
        bail("labeling <rendering> not found")
    for k, v in RENDERING_ATTRS.items():
        if rendering.get(k) != v:
            rendering.set(k, v)
            print(f"rendering {k} -> {v}")

    callout = settings.find("callout")
    if callout is None or callout.get("type") not in CALLOUT_FROM_TYPES:
        bail("authored <callout> not found")
    if callout.get("type") != CALLOUT_TYPE:
        callout.set("type", CALLOUT_TYPE)
        print(f"callout type -> {CALLOUT_TYPE}")
    if settings.get("calloutType") != CALLOUT_TYPE:
        settings.set("calloutType", CALLOUT_TYPE)
        print(f"settings calloutType -> {CALLOUT_TYPE}")
    opts = {o.get("name"): o for o in callout.iter("Option") if o.get("name")}
    for k, v in CALLOUT_OPTS.items():
        if k not in opts:
            bail(f"callout Option {k!r} not found")
        if opts[k].get("value") != v:
            opts[k].set("value", v)
            print(f"callout {k} -> {v}")

    new_block = ET.tostring(lab, encoding="unicode")
    new_qml = qml[:m.start()] + new_block + qml[m.end():]

    # Validate BEFORE writing: never persist a QML that no longer parses.
    try:
        ET.fromstring(new_qml)
    except ET.ParseError as exc:
        bail(f"edited QML no longer parses, aborting without write: {exc}")

    if new_qml != qml:
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (new_qml, LAYER))
        assert cur.rowcount == 1
        con.commit()
        print("styleQML updated")
    else:
        print("already applied (no change)")

    # Validate: gpkg intact, QML parses, target config round-trips,
    # neighbouring config undisturbed.
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    final = cur.fetchone()[0]
    ET.fromstring(final)
    print(f"QML parses: {LAYER}")

    lab = re.search(r'<labeling type="simple">.*?</labeling>', final, re.S)
    settings = ET.fromstring(lab.group(0)).find("settings")
    placement = settings.find("placement")
    for k, v in PLACEMENT_ATTRS.items():
        assert placement.get(k) == v, f"placement {k}={placement.get(k)!r}, want {v!r}"
    rendering = settings.find("rendering")
    for k, v in RENDERING_ATTRS.items():
        assert rendering.get(k) == v, f"rendering {k}={rendering.get(k)!r}, want {v!r}"
    callout = settings.find("callout")
    assert callout.get("type") == CALLOUT_TYPE
    assert settings.get("calloutType") == CALLOUT_TYPE
    opts = {o.get("name"): o.get("value")
            for o in callout.iter("Option") if o.get("name")}
    for k, v in CALLOUT_OPTS.items():
        assert opts[k] == v, f"callout {k}={opts[k]!r}, want {v!r}"
    # Manual label moves (auxiliary storage) must survive.
    dd = ET.tostring(settings.find("dd_properties"), encoding="unicode")
    assert "auxiliary_storage_labeling_positionx" in dd
    assert "auxiliary_storage_labeling_positiony" in dd
    # The HTML label expression must be byte-identical.
    assert settings.find("text-style").get("fieldName") == field_name_before
    # Renderer untouched: same renderer opening tag as before the edit.
    rend_before = re.search(r'<renderer-v2\b[^>]*>', qml).group(0)
    rend_after = re.search(r'<renderer-v2\b[^>]*>', final).group(0)
    assert rend_before == rend_after, (rend_before, rend_after)
    print("round-trip ok: placement, rendering, callout, dd bindings, expression, renderer")
    con.close()


if __name__ == "__main__":
    main()
