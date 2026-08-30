"""Fix Overlay label placement for nested/clipped zones; activate the callout.

Nested same-alteration zones (Intensity 5 core -> 3 -> 1) are clipped into
each other, so the outer polygons are annuli whose centroids fall inside the
hole. Under the old OverPoint (centroid) placement every zone's label stacked
at the same point and all but one collided away. This switches the "2 -
Overlay" simple labeling to:

    - placement=Horizontal: candidates are generated across the ACTUAL
      (holed) geometry, so an annulus label lands in its own ring band,
      never in the hole.
    - polygonPlacementFlags=3 + fitInPolygonOnly=1: inside placement is
      preferred and only used when the label truly fits; otherwise the
      label is placed outside the polygon...
    - ...which activates the callout (grey dashed leader,
      anchorPoint=point_on_exterior so the leader terminates at the
      nearest point on the zone's edge - pole_of_inaccessibility would
      run it deep into the polygon interior). The authored callout was
      curved; it is converted to the straight "simple" type so leaders
      match the FieldNotebook comment callouts
      (inject_dynamic_callouts.py), whose dynamics are mirrored too:
      dist=25 / maximumDistance=75 map units (1x / 3x the scale-5000
      callout ring unit, callout_dist_for_scale; tightened 2026-08-30
      from 7.5 mm / 5x), minLength 1 MM so no stub is drawn on
      inside-placed labels.
    - Data-defined LabelDistance / MaximumDistance hold the ring at
      5 mm / 15 mm ON PAPER at any zoom - the statics are map units,
      which take the referenceScale/mapScale multiplier, so without
      the expressions the alteration leaders drifted as the SQUARE of
      the zoom ratio. Same fix as the Basemap leaders
      (inject_basemap_label_placement.py RING_MM) and the FieldNotebook
      comments (inject_dynamic_callouts.py).
    - overlapHandling=AllowOverlapIfRequired: zone labels never vanish.

The map-unit distances are baked for the template's
symbologyReferenceScale of 5000; Set Mapping Scale rescales dist /
maximumDistance per mapping scale (script_setmapping.py
rescale_overlay_label_distance - a copy-edit, so the dd ring
expressions survive it) while everything else here persists.

Untouched: the label expression (text-style), rendering/obstacle settings,
and the dd_properties auxiliary-storage bindings that back manual label moves
(PositionX/PositionY/Show/LineAnchor*).

Idempotent and re-runnable. The labeling block is parsed and edited with
ElementTree (this region of the QML jams tags onto shared lines, so regex
editing is unsafe); the first run therefore also normalises the block's
whitespace formatting - semantics are unchanged and validated.

Usage:  python scripts/inject_overlay_label_placement.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

LAYER = "3 - Overlay"

U = 25    # callout_dist_for_scale(5000) = 0.005 * 5000 map units, mirrors FieldNotebook
PLACEMENT_ATTRS = {
    "placement": "4",               # Horizontal (surface candidates over holed geometry)
    "polygonPlacementFlags": "3",   # inside (preferred) + outside allowed
    "fitInPolygonOnly": "1",        # inside only when the label truly fits
    "dist": "25",                   # 1 x U
    "distUnits": "MapUnit",
    "maximumDistance": "75",        # 3 x U (COMMENT_MAX_FACTOR)
    "maximumDistanceUnit": "MapUnit",
    "overlapHandling": "AllowOverlapIfRequired",
}

# The paper-constant ring. Keep byte-identical with
# script_setmapping.comment_ring_expression(COMMENT_RING_MM) and with
# scripts/inject_dynamic_callouts.py.
COMMENT_RING_MM = 5.0
COMMENT_MAX_FACTOR = 3
_REF = "coalesce(to_real(@lgs_reference_scale), 0)"


def ring_expr(mm):
    return ("CASE WHEN coalesce(@map_scale, 0) > 0 AND " + _REF +
            " > 0 THEN %s * @map_scale * @map_scale / (1000 * %s) "
            "ELSE %s * @map_scale / 1000 END" % (mm, _REF, mm))


DD_EXPRESSIONS = {
    "LabelDistance": ring_expr(COMMENT_RING_MM),
    "MaximumDistance": ring_expr(COMMENT_RING_MM * COMMENT_MAX_FACTOR),
}
CALLOUT_TYPE = "simple"  # straight leader, same as the FieldNotebook callouts
CALLOUT_OPTS = {
    "enabled": "1",
    "minLength": "1",
    "offsetFromAnchor": "0.5",
    "offsetFromLabel": "1",
    # Leader must terminate at the zone's EDGE nearest the label —
    # pole_of_inaccessibility runs it deep into the polygon interior.
    "anchorPoint": "point_on_exterior",
    # false: point_on_exterior already lands on the nearest part of a
    # multipart zone; true would leader every fragment (spider-web).
    "drawToAllParts": "false",
}
CURVED_ONLY_OPTS = ("curvature", "orientation")  # meaningless on a simple callout


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


def inject_dd(settings, name, expr):
    """Set one data-defined property, leaving its siblings alone.

    The settings-level dd_properties also carries the auxiliary-storage
    bindings for manual label moves, so this replaces one named entry and
    never rewrites the block. Same shape as
    inject_basemap_label_placement.inject_dd."""
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
        if o.get("name") == name:
            props.remove(o)
    entry = ET.SubElement(props, "Option", {"name": name, "type": "Map"})
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

    placement = settings.find("placement")
    for k, v in PLACEMENT_ATTRS.items():
        if placement.get(k) != v:
            placement.set(k, v)
            print(f"placement {k} -> {v}")

    callout = settings.find("callout")
    if callout is None or callout.get("type") not in ("curved", CALLOUT_TYPE):
        bail("authored <callout> not found")
    if callout.get("type") != CALLOUT_TYPE:
        callout.set("type", CALLOUT_TYPE)
        print(f"callout type -> {CALLOUT_TYPE}")
    if settings.get("calloutType") != CALLOUT_TYPE:
        settings.set("calloutType", CALLOUT_TYPE)
        print(f"settings calloutType -> {CALLOUT_TYPE}")
    opts_map = callout.find("Option")
    opts = {o.get("name"): o for o in callout.iter("Option") if o.get("name")}
    for k in CURVED_ONLY_OPTS:
        if k in opts:
            opts_map.remove(opts.pop(k))
            print(f"callout {k} removed (curved-only)")
    for k, v in CALLOUT_OPTS.items():
        if k not in opts:
            bail(f"callout Option {k!r} not found")
        if opts[k].get("value") != v:
            opts[k].set("value", v)
            print(f"callout {k} -> {v}")

    for name, expr in DD_EXPRESSIONS.items():
        if not inject_dd(settings, name, expr):
            bail(f"no dd_properties block to carry {name}")
        print(f"dd {name} -> paper-constant ring")

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
    root = ET.fromstring(final)
    print(f"QML parses: {LAYER}")

    lab = re.search(r'<labeling type="simple">.*?</labeling>', final, re.S)
    settings = ET.fromstring(lab.group(0)).find("settings")
    assert settings.get("calloutType") == CALLOUT_TYPE
    placement = settings.find("placement")
    for k, v in PLACEMENT_ATTRS.items():
        assert placement.get(k) == v, f"placement {k}={placement.get(k)!r}, want {v!r}"
    opts = {o.get("name"): o.get("value")
            for o in settings.find("callout").iter("Option") if o.get("name")}
    for k, v in CALLOUT_OPTS.items():
        assert opts[k] == v, f"callout {k}={opts[k]!r}, want {v!r}"
    callout = settings.find("callout")
    assert callout.get("type") == CALLOUT_TYPE
    for k in CURVED_ONLY_OPTS:
        assert k not in opts, f"curved-only option {k!r} still present"
    # Manual label moves (auxiliary storage) must survive.
    dd = ET.tostring(settings.find("dd_properties"), encoding="unicode")
    assert "auxiliary_storage_labeling_positionx" in dd
    assert "auxiliary_storage_labeling_positiony" in dd
    # The paper-constant ring expressions are in, verbatim.
    for name, expr in DD_EXPRESSIONS.items():
        entry = next((o for o in settings.find("dd_properties").iter("Option")
                      if o.get("name") == name and o.get("type") == "Map"),
                     None)
        assert entry is not None, f"dd {name} missing"
        by = {o.get("name"): o.get("value")
              for o in entry.iter("Option") if o.get("name")}
        assert by.get("active") == "true" and by.get("expression") == expr, \
            f"dd {name} wrong: {by!r}"
    # Label expression untouched.
    assert "'Alteration'" in settings.find("text-style").get("fieldName")
    # Renderer untouched: still categorized on SubType1 at reference scale 5000.
    rend = re.search(r'<renderer-v2\b[^>]*>', final).group(0)
    assert 'type="categorizedSymbol"' in rend and 'attr="SubType1"' in rend, rend
    assert 'referencescale="5000"' in rend, rend
    print("round-trip ok: placement, callout, dd bindings, expression, renderer")
    con.close()


if __name__ == "__main__":
    main()
