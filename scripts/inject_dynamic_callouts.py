"""Set the placement and leader policy on the FieldNotebook comment rules.

Two rules label free text on "1 - FieldNotebook", and they are deliberately
NOT treated the same:

  "Fallback Labels (Comments/Labels)" - engine-arranged with a leader.
    - OrderedPositionsAroundPoint placement: 8 candidate orientations.
    - dist=25 / maximumDistance=75 map units (1x / 3x the scale-5000
      callout ring unit, callout_dist_for_scale): labels pushed further
      out only when closer spots are taken -> variable callout length,
      PreferCloser. (Tightened 2026-08-30 from 7.5 mm / 5x on the user's
      call - station labels were wandering too far.)
    - Data-defined LabelDistance / MaximumDistance hold that ring at
      5 mm / 15 mm ON PAPER at any zoom. The statics above are map
      units, which take the referenceScale/mapScale multiplier, so
      without the expressions the ring drifts as the SQUARE of the zoom
      ratio - 5 mm at reference became 125 mm five zooms in, the
      leader-across-half-the-map screenshots. Same fix, same expression
      shape, as the Basemap leaders
      (scripts/inject_basemap_label_placement.py RING_MM).
    - Callout enabled (grey dashed leader), minLength 1 MM so no stub is
      drawn when the label sits at its nominal ring.
    - Its fixed data-defined OffsetXY ('120,-60') is removed (inert under
      around-point placement).

  "Regolith Note" - engine-arranged, NO leader (user decision 2026-08-17).
    A regolith note annotates the ground under the point, not a feature you
    need to trace a line back to. It keeps the 8 candidate positions so
    notes declutter, but sits on a short 3 pt ring with no push-out, so it
    never wanders far enough to need a leader. The leader it used to draw
    was collateral: the 2026-08-14 refactor routed both rules through one
    placement helper and switched the callout on for both.

Both rules keep overlapHandling=AllowOverlapIfRequired: a label that truly
cannot fit is drawn anyway instead of hidden - comments never vanish.

Point units on the Regolith ring, not map units, for the same reason as
the dip-label offsets (scripts/inject_fieldnotebook_dip_label_offsets.py):
the renderer reference scale is a per-project knob and only paper
measurements track the 30 pt markers under it.

Must stay in step with script_setmapping.build_structural_labeling(),
which regenerates this block when Set Mapping Scale runs; the values
here mirror LayerConfigurator at scale 5000 (the template's
symbologyReferenceScale).

Idempotent and re-runnable. The labeling block is parsed and edited with
ElementTree (this region of the QML jams tags onto shared lines, so
regex editing is unsafe); the first run therefore also normalises the
block's whitespace formatting - semantics are unchanged and validated.

Usage:  python scripts/inject_dynamic_callouts.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import copy
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

LAYER = "1 - FieldNotebook"
FALLBACK = "Fallback Labels (Comments/Labels)"
REGOLITH = "Regolith Note"
RULES = (REGOLITH, FALLBACK)

U = 25    # callout_dist_for_scale(5000) = 0.005 * 5000 map units
R = 3     # script_setmapping.REGOLITH_RING, in Point units

AROUND_POINT = {
    "placement": "6",              # OrderedPositionsAroundPoint
    "offsetType": "1",             # FromSymbolBounds
    "overlapHandling": "AllowOverlapIfRequired",
}
PLACEMENT_ATTRS = {
    FALLBACK: dict(AROUND_POINT, **{
        "dist": "25",                  # 1 x U
        "distUnits": "MapUnit",
        "maximumDistance": "75",       # 3 x U (COMMENT_MAX_FACTOR)
        "maximumDistanceUnit": "MapUnit",
    }),
    REGOLITH: dict(AROUND_POINT, **{
        "dist": "3",                   # R, a short ring beside the point
        "distUnits": "Point",
        "maximumDistance": "3",        # == dist: no push-out, so no leader
        "maximumDistanceUnit": "Point",
        "offsetUnits": "Point",        # inert here, but consistent
    }),
}
CALLOUT_OPTS = {
    FALLBACK: {
        "enabled": "1",
        "minLength": "1",
        "offsetFromAnchor": "0.3",
        "offsetFromLabel": "0.3",
    },
    REGOLITH: {
        "enabled": "0",
    },
}

# The paper-constant ring. Keep byte-identical with
# script_setmapping.comment_ring_expression(COMMENT_RING_MM) - Set Mapping
# Scale rebuilds this labeling wholesale, and
# tests/test_label_code_template_qgis.py pins template == code.
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

# The leader's end gaps and minimum length, held constant ON PAPER. They are
# MM options and MM takes the referenceScale/mapScale multiplier, while the
# ring above is paper-constant - so the static 0.5 + 1 mm gaps outgrew the
# whole leader a few zooms in and the callouts vanished (user report,
# 2 Sep 2026; measured at ZERO leader pixels by 5x). Tiny gaps by the same
# request. Keep values and expression text byte-identical with
# script_setmapping (CALLOUT_GAP_*_MM / callout_gap_expression) - Set
# Mapping Scale rebuilds this labeling wholesale.
GAP_ANCHOR_MM = 0.3
GAP_LABEL_MM = 0.3
MIN_CALLOUT_MM = 1.0


def gap_expr(mm):
    return ("CASE WHEN coalesce(@map_scale, 0) > 0 AND " + _REF + " > 0 "
            "THEN %s * @map_scale / %s ELSE %s END" % (mm, _REF, mm))


CALLOUT_DD = {
    "OffsetFromAnchor": gap_expr(GAP_ANCHOR_MM),
    "OffsetFromLabel": gap_expr(GAP_LABEL_MM),
    "MinimumCalloutLength": gap_expr(MIN_CALLOUT_MM),
}


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


def inject_callout_dd(callout, name, expr):
    """Set one data-defined property ON THE CALLOUT, leaving siblings alone.

    A callout's dd collection serialises as an Option named "ddProperties"
    inside the callout's outer Option map (not as a <dd_properties> element
    the way the label settings' does)."""
    outer = callout.find("Option")
    if outer is None:
        return False
    dd = next((o for o in outer.findall("Option")
               if o.get("name") == "ddProperties"), None)
    if dd is None:
        dd = ET.SubElement(outer, "Option",
                           {"name": "ddProperties", "type": "Map"})
        ET.SubElement(dd, "Option",
                      {"name": "name", "type": "QString", "value": ""})
        ET.SubElement(dd, "Option", {"name": "type", "type": "QString",
                                     "value": "collection"})
    props = next((o for o in dd.findall("Option")
                  if o.get("name") == "properties"), None)
    if props is None:
        props = ET.SubElement(dd, "Option",
                              {"name": "properties", "type": "Map"})
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


def inject_dd(settings, name, expr):
    """Set one data-defined property, leaving its siblings alone.
    Same surgical shape as inject_basemap_label_placement.inject_dd."""
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

    m = re.search(r'<labeling type="rule-based">.*?</labeling>', qml, re.S)
    if not m:
        bail("rule-based <labeling> block not found")
    lab = ET.fromstring(m.group(0))

    rules = {r.get("description"): r for r in lab.iter("rule")}
    missing = [d for d in RULES if d not in rules]
    if missing:
        bail(f"labeling rules not found: {missing}")

    fallback_callout = None
    for desc in RULES:
        settings = rules[desc].find("settings")
        placement = settings.find("placement")
        for k, v in PLACEMENT_ATTRS[desc].items():
            if placement.get(k) != v:
                placement.set(k, v)
                print(f"{desc}: placement {k} -> {v}")

        callout = settings.find("callout")
        opts = {o.get("name"): o for o in callout.iter("Option") if o.get("name")}
        for k, v in CALLOUT_OPTS[desc].items():
            if opts[k].get("value") != v:
                opts[k].set("value", v)
                print(f"{desc}: callout {k} -> {v}")

        if desc == FALLBACK:
            fallback_callout = callout
            dd = settings.find("dd_properties")
            props = next((o for o in dd.iter("Option")
                          if o.get("name") == "properties"), None)
            offset_xy = next((o for o in props.iter("Option")
                              if o.get("name") == "OffsetXY"), None) \
                if props is not None else None
            if offset_xy is not None:
                props.remove(offset_xy)
                print(f"{desc}: dd OffsetXY removed")
            for name, expr in DD_EXPRESSIONS.items():
                if not inject_dd(settings, name, expr):
                    bail(f"{desc}: no dd_properties block to carry {name}")
                print(f"{desc}: dd {name} -> paper-constant ring")
            for name, expr in CALLOUT_DD.items():
                if not inject_callout_dd(callout, name, expr):
                    bail(f"{desc}: callout has no Option map for {name}")
                print(f"{desc}: callout dd {name} -> paper-constant gap")

    # Regolith's callout is switched off, not deleted - QGIS always writes
    # one. Keep it byte-identical to the Fallback leader apart from
    # enabled, so a dormant symbol can never drift into something else.
    regolith_settings = rules[REGOLITH].find("settings")
    regolith_callout = regolith_settings.find("callout")
    dormant = copy.deepcopy(fallback_callout)
    for opt in dormant.iter("Option"):
        if opt.get("name") == "enabled":
            opt.set("value", "0")
    if ET.tostring(regolith_callout) != ET.tostring(dormant):
        idx = list(regolith_settings).index(regolith_callout)
        regolith_settings.remove(regolith_callout)
        regolith_settings.insert(idx, dormant)
        print(f"{REGOLITH}: callout symbol matched to Fallback, left disabled")

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

    # Validate: gpkg intact, QML parses, target config round-trips.
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    root = ET.fromstring(cur.fetchone()[0])
    print(f"QML parses: {LAYER}")

    checked = 0
    for rule in root.iter("rule"):
        desc = rule.get("description")
        if desc not in RULES:
            continue
        settings = rule.find("settings")
        placement = settings.find("placement")
        for k, v in PLACEMENT_ATTRS[desc].items():
            assert placement.get(k) == v, \
                f"{desc}: {k}={placement.get(k)!r}, want {v!r}"
        opts = {o.get("name"): o.get("value")
                for o in settings.find("callout").iter("Option") if o.get("name")}
        for k, v in CALLOUT_OPTS[desc].items():
            assert opts[k] == v, f"{desc}: callout {k}={opts[k]!r}, want {v!r}"
        checked += 1
    assert checked == 2, f"expected 2 rules verified, got {checked}"

    # The Fallback rule alone carries a leader.
    enabled = [r.get("description") for r in root.iter("rule")
               if any(o.get("name") == "enabled" and o.get("value") == "1"
                      for o in r.find("settings").find("callout").iter("Option"))]
    assert enabled == [FALLBACK], f"rules drawing a leader: {enabled}"

    # ...and alone carries the paper-constant ring expressions, verbatim.
    for rule in root.iter("rule"):
        desc = rule.get("description")
        dd = rule.find("settings").find("dd_properties")
        found = {}
        for entry in dd.iter("Option"):
            if entry.get("name") in DD_EXPRESSIONS and entry.get("type") == "Map":
                by = {o.get("name"): o.get("value")
                      for o in entry.iter("Option") if o.get("name")}
                found[entry.get("name")] = (by.get("active"),
                                            by.get("expression"))
        if desc == FALLBACK:
            for name, expr in DD_EXPRESSIONS.items():
                assert found.get(name) == ("true", expr), \
                    f"{desc}: dd {name} wrong: {found.get(name)!r}"
        else:
            assert not found, f"{desc}: unexpected ring dd {sorted(found)}"

    # The paper-constant end gaps on the Fallback leader, verbatim. (The
    # dormant Regolith copy inherits them by construction; only the live
    # one is asserted.)
    for rule in root.iter("rule"):
        if rule.get("description") != FALLBACK:
            continue
        callout = rule.find("settings").find("callout")
        found = {}
        for entry in callout.iter("Option"):
            if entry.get("name") in CALLOUT_DD and entry.get("type") == "Map":
                by = {o.get("name"): o.get("value")
                      for o in entry.iter("Option") if o.get("name")}
                found[entry.get("name")] = (by.get("active"),
                                            by.get("expression"))
        for name, expr in CALLOUT_DD.items():
            assert found.get(name) == ("true", expr), \
                f"{FALLBACK}: callout dd {name} wrong: {found.get(name)!r}"

    # Untouched rules keep their config.
    descs = {r.get("description") for r in root.iter("rule")}
    assert {"Dip Labels", "SymbolSuffix Labels"} <= descs
    print("round-trip ok: Fallback keeps its leader with paper-constant "
          "gaps, Regolith Note sits beside its point with none")
    con.close()


if __name__ == "__main__":
    main()
