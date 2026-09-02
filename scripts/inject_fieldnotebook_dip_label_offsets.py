"""Ground-fixed, family-aware dip-label offsets for 1 - FieldNotebook.

The offsets are QUOTED in Point on the 30 pt marker and BAKED as the ground
distances those points span at the template's 1:5000 reference scale.

Why not simply store them in Point, as this file did between 2026-08-15 and
2026-08-17: QGIS multiplies paper-unit SYMBOL sizes by
referenceScale/mapScale, so a 30 pt marker under a 1:5000 reference scale
keeps a constant GROUND footprint - it spans 52.9 m at every zoom. Label
offsets get no such treatment. Measured
(tests/test_label_offset_invariance_qgis.py): a 21.5 pt offset holds ~28 px
while its symbol grows 40 -> 400 px between 1:5000 and 1:500, so the label
slides right across the symbol as you zoom in. Ground-fixed symbols need
ground-fixed offsets.

Commit 55eaeed moved these to Point along with the symbol's stroke width.
That was right for the stroke - it lives INSIDE the symbol and must share
its units, or it drifts against the artwork - and wrong for the offset,
which does not. The concern that drove it is still handled: the reference
scale is a per-project knob (UG mapping retargets it to 1:200 - 1:500), and
Set Mapping Scale re-derives these offsets from the very same scale_value it
hands the renderer, so the ratio survives a retarget.

Distances are the symbol-ratio equivalents on the 30 pt marker (whose canvas
spans 52.9 design units - which is 52.9 m at 1:5000, the same units these
offsets are in), family-aware because a flat distance is too far for planar
strike symbols and lands inside the plunge arrows:

    Dip Labels     linear (plunge arrows)  21.5 pt -> 37.92
                   planar (strike symbols)  9.6 pt -> 16.93
                   non-structure fallback   2.3 pt -> '4.06,-4.06'
    SymbolSuffix   upright map-frame subscript on the symbol's rotated
                   bounding extent (see suffix_offset_expression below);
                   non-structure fallback 8.5 pt -> '14.99,14.99'

offsetUnits become MapUnit on the two structural rules only. The linear
code list mirrors stereonet/data.py structure_classification ('L'/'l'
entries). Upgrades cleanly from the flat-30 MapUnit original, the
family-aware MapUnit interim (38/17), the MM interim (7.2/3.2), or the
Point form (21.5/9.6). Type='Structure' gating is kept as-is.

MUST STAY IN STEP with script_setmapping.py, which regenerates this whole
labeling block whenever Set Mapping Scale runs -
tests/test_label_code_template_qgis.py is the enforcement. This script runs
on plain Python and cannot import that module (it imports qgis), hence the
duplicated constants.

Idempotent and re-runnable; QML parse-validated BEFORE writing.

Usage:  python scripts/inject_fieldnotebook_dip_label_offsets.py [gpkg]
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

LAYER = "1 - FieldNotebook"

# The template is authored at this reference scale; Set Mapping Scale
# re-derives everything below at whatever scale the user picks.
REFERENCE_SCALE = 5000
POINTS_PER_INCH = 72.0
METRES_PER_INCH = 0.0254


def pt_to_map_units(points, scale=REFERENCE_SCALE):
    """Mirror of script_setmapping.pt_to_map_units - same 2 dp rounding, so
    the two produce byte-identical expression text."""
    return "%g" % round(points * METRES_PER_INCH / POINTS_PER_INCH * scale, 2)


# stereonet/data.py structure_classification codes marked 'L' or 'l'
LINEAR = ("BAX", "FAX", "FAX1", "FAX1M", "FAX1S", "FAX1Z",
          "FAX2", "FAX2M", "FAX2S", "FAX2Z", "FAX3", "FAX3M", "FAX3S",
          "FAX3Z", "FAX4", "FAX4M", "FAX4S", "FAX4Z", "FAX5", "FAX5M",
          "FAX5S", "FAX5Z", "FAXCR", "FAXK", "FAXSZ", "LME", "LNI",
          "LNI1", "LNI2", "LNI3", "LNI4", "LNI5", "LNISC", "LNS",
          "SLF", "SLK", "STR")
D_LINEAR = pt_to_map_units(21.5)          # 37.92
D_PLANAR = pt_to_map_units(9.6)           # 16.93
D_FALLBACK = pt_to_map_units(2.3)         # 4.06

# The SymbolSuffix annotation sits UPRIGHT in the map frame as a subscript
# to the symbol: below it, right-aligned to its rotated bounding extent for
# planar structures, hanging off the bottom-right for linear ones (user
# decision, 2 Sep 2026 - the old rotating +135-degree ring wandered above
# and below the symbol as the bearing turned). Constants and expression text
# mirror script_setmapping.suffix_offset_expression /
# suffix_quadrant_expression; tests/test_label_code_template_qgis.py pins
# template == code, and Set Mapping Scale rebuilds this rule wholesale.
SUFFIX_HALF_PLANAR_PT = 15.0
SUFFIX_HALF_LINEAR_PT = 15.0
SUFFIX_TICK_PT = 7.0
SUFFIX_GAP_PT = 2.0
SUFFIX_DIP_CLEAR_PT = 10.0
SUFFIX_OFFSET_FALLBACK_PT = 8.5

_in = ",".join("'%s'" % c for c in LINEAR)


def suffix_offset_expression():
    """Plain-text twin of script_setmapping.suffix_offset_expression(5000).
    Real quote characters here - ElementTree escapes them on serialise."""
    lp = pt_to_map_units(SUFFIX_HALF_PLANAR_PT)
    ll = pt_to_map_units(SUFFIX_HALF_LINEAR_PT)
    tk = pt_to_map_units(SUFFIX_TICK_PT)
    gap = pt_to_map_units(SUFFIX_GAP_PT)
    clear = pt_to_map_units(SUFFIX_DIP_CLEAR_PT)
    fallback = pt_to_map_units(SUFFIX_OFFSET_FALLBACK_PT)
    dd = 'radians("DipDirection")'
    dip_in_corner = f'(sin({dd}) >= 0 AND cos({dd}) < 0.1)'
    return (
        f'CASE WHEN "Type" = \'Structure\' AND "Subtype1" IN ({_in}) THEN '
        f'to_string(({ll} * abs(sin({dd})))) '
        f'|| \',\' || '
        f'to_string(({ll} * abs(cos({dd})) + {gap} + '
        f'(CASE WHEN {dip_in_corner} THEN {clear} ELSE 0 END))) '
        f'WHEN "Type" = \'Structure\' THEN '
        f'to_string(max({lp} * abs(cos({dd})), {tk} * sin({dd}))) '
        f'|| \',\' || '
        f'to_string((max({lp} * abs(sin({dd})), -{tk} * cos({dd})) + {gap})) '
        f'ELSE \'{fallback},{fallback}\' END')


def suffix_quadrant_expression():
    """Plain-text twin of script_setmapping.suffix_quadrant_expression()."""
    return (f'CASE WHEN "Type" = \'Structure\' AND "Subtype1" IN ({_in}) '
            f'THEN 8 ELSE 6 END')


def dip_expr(dist_linear, dist_planar, fallback):
    return ("CASE WHEN &quot;Type&quot; = 'Structure' THEN with_variable('lgs_d', "
            "CASE WHEN &quot;Subtype1&quot; IN (%s) THEN %s ELSE %s END, "
            "to_string((@lgs_d * cos(radians(&quot;DipDirection&quot; - 90)))) "
            "|| ',' || "
            "to_string((@lgs_d * sin(radians(&quot;DipDirection&quot; - 90))))) "
            "ELSE '%s' END" % (_in, dist_linear, dist_planar, fallback))


# Prior states of the Dip Labels OffsetXY expression
OLD_FLAT30 = ("CASE WHEN &quot;Type&quot; = 'Structure' THEN "
              "to_string((30.0 * cos(radians(&quot;DipDirection&quot; - 90)))) "
              "|| ',' || "
              "to_string((30.0 * sin(radians(&quot;DipDirection&quot; - 90)))) "
              "ELSE '4,-4' END")
OLD_MM = dip_expr("7.2", "3.2", "0.8,-0.8")
OLD_MU = dip_expr("38.0", "17.0", "4,-4")
OLD_POINT = dip_expr("21.5", "9.6", "2.3,-2.3")
NEW = dip_expr(D_LINEAR, D_PLANAR, "%s,-%s" % (D_FALLBACK, D_FALLBACK))


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def _set_dd(settings, name, expr):
    """Replace one settings-level dd entry, leaving its siblings alone
    (same surgical shape as inject_basemap_label_placement.inject_dd)."""
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


def _remove_dd(settings, name):
    dd = settings.find("dd_properties")
    if dd is None:
        return False
    for props in dd.iter("Option"):
        if props.get("name") != "properties":
            continue
        for o in props.findall("Option"):
            if o.get("name") == name:
                props.remove(o)
                return True
    return False


def rebuild_suffix_dd(qml):
    """Rewrite the SymbolSuffix rule's placement dd to the upright design."""
    m = re.search(r'<labeling type="rule-based">.*?</labeling>', qml, re.S)
    if not m:
        bail("rule-based <labeling> block not found")
    lab = ET.fromstring(m.group(0))
    settings = None
    for rule in lab.iter("rule"):
        if rule.get("description") == "SymbolSuffix Labels":
            settings = rule.find("settings")
    if settings is None:
        bail("SymbolSuffix Labels rule not found")
    if not _set_dd(settings, "OffsetXY", suffix_offset_expression()):
        bail("SymbolSuffix: no dd_properties block")
    _set_dd(settings, "OffsetQuad", suffix_quadrant_expression())
    if _remove_dd(settings, "LabelRotation"):
        print("SymbolSuffix: dd LabelRotation removed - the suffix is "
              "upright now")
    print("SymbolSuffix: dd OffsetXY -> bounding-extent subscript, "
          "dd OffsetQuad -> below-left/right by family")
    new_qml = qml[:m.start()] + ET.tostring(lab, encoding="unicode") \
        + qml[m.end():]
    try:
        ET.fromstring(new_qml)
    except ET.ParseError as exc:
        bail(f"edited QML no longer parses: {exc}")
    return new_qml


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()
    qml, = cur.execute("SELECT styleQML FROM layer_styles WHERE "
                       "f_table_name=?", (LAYER,)).fetchone()
    original = qml

    # 1. Dip Labels expression (from any known prior state)
    if NEW in qml:
        print("dip expression already family-aware ground distances")
    elif OLD_POINT in qml:
        qml = qml.replace(OLD_POINT, NEW)
        print("dip expression converted from Point (21.5/9.6)")
    elif OLD_MU in qml:
        qml = qml.replace(OLD_MU, NEW)
        print("dip expression converted from family-aware MapUnit (38/17)")
    elif OLD_MM in qml:
        qml = qml.replace(OLD_MM, NEW)
        print("dip expression converted from interim MM form")
    elif OLD_FLAT30 in qml:
        qml = qml.replace(OLD_FLAT30, NEW)
        print("dip expression upgraded from flat 30 MapUnit")
    else:
        bail("Dip Labels OffsetXY expression not in any known state")

    # 2. SymbolSuffix rule: rebuilt outright rather than converted from
    #    known prior states - the 2 Sep 2026 redesign replaced the rotating
    #    +135-degree ring with the upright bounding-extent subscript, and a
    #    whole-rebuild (the inject_label_size_scaling philosophy) upgrades
    #    every prior form at once. ElementTree surgery: OffsetXY and
    #    OffsetQuad are (re)written, the old LabelRotation dd is removed so
    #    the annotation stays upright, and every other dd entry (the scale
    #    gate among them) is left alone.
    qml = rebuild_suffix_dd(qml)

    # 3. offsetUnits -> MapUnit on the two structural rules only; other
    #    rules (comment/callout labels) keep their own tuned units
    for desc in ("Dip Labels", "SymbolSuffix Labels"):
        m = re.search(r'<rule\b[^>]*description="%s">.*?</rule>' % desc,
                      qml, re.S)
        if not m:
            bail(f"rule {desc!r} not found")
        block = m.group(0)
        for wrong in ('offsetUnits="Point"', 'offsetUnits="MM"'):
            if wrong in block:
                block = block.replace(wrong, 'offsetUnits="MapUnit"')
                print(f"{desc}: {wrong} -> MapUnit")
        qml = qml[:m.start()] + block + qml[m.end():]

    if qml != original:
        try:
            ET.fromstring(qml)
        except ET.ParseError as exc:
            bail(f"edited QML no longer parses: {exc}")
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, LAYER))
        assert cur.rowcount == 1
        con.commit()
    else:
        print("no-op")

    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    q, = cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                     (LAYER,)).fetchone()
    root = ET.fromstring(q)
    assert NEW in q
    # The suffix dd, post-parse: OffsetXY + OffsetQuad in verbatim, the old
    # LabelRotation gone, and the scale gate untouched beside them.
    for rule in root.iter("rule"):
        if rule.get("description") != "SymbolSuffix Labels":
            continue
        entries = {}
        dd = rule.find("settings").find("dd_properties")
        for entry in dd.iter("Option"):
            if entry.get("type") == "Map" and entry.get("name"):
                by = {o.get("name"): o.get("value")
                      for o in entry.findall("Option")}
                entries[entry.get("name")] = by.get("expression")
        assert entries.get("OffsetXY") == suffix_offset_expression(), \
            f"suffix OffsetXY wrong: {entries.get('OffsetXY')!r}"
        assert entries.get("OffsetQuad") == suffix_quadrant_expression(), \
            f"suffix OffsetQuad wrong: {entries.get('OffsetQuad')!r}"
        assert "LabelRotation" not in entries, \
            "the suffix still rotates with the symbol"
        assert "MinimumScale" in entries, \
            "the scale gate was lost from the suffix rule"
    for desc in ("Dip Labels", "SymbolSuffix Labels"):
        block = re.search(r'<rule\b[^>]*description="%s">.*?</rule>' % desc,
                          q, re.S).group(0)
        assert 'offsetUnits="MapUnit"' in block, desc
        assert 'offsetUnits="Point"' not in block, desc
        assert 'offsetUnits="MM"' not in block, desc
    assert OLD_FLAT30 not in q and OLD_MU not in q and OLD_MM not in q
    assert OLD_POINT not in q
    # The Regolith ring is a paper distance BY DESIGN and must survive.
    regolith = re.search(r'<rule\b[^>]*description="Regolith Note">.*?</rule>',
                         q, re.S).group(0)
    assert 'distUnits="Point"' in regolith, \
        "the Regolith ring should still be a paper distance"
    print(f"round-trip ok: {LAYER} dip labels family-aware ground distances "
          f"(linear {D_LINEAR} / planar {D_PLANAR}, suffix upright subscript "
          f"at 1:{REFERENCE_SCALE})")
    con.close()


if __name__ == "__main__":
    main()
