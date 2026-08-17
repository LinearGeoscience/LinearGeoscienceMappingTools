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
    SymbolSuffix   17 pt -> 29.99 at dip direction +135; fallback 14.99

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
D_SUFFIX = pt_to_map_units(17.0)          # 29.99
D_SUFFIX_FALLBACK = pt_to_map_units(8.5)  # 14.99

_in = ",".join("'%s'" % c for c in LINEAR)


def dip_expr(dist_linear, dist_planar, fallback):
    return ("CASE WHEN &quot;Type&quot; = 'Structure' THEN with_variable('lgs_d', "
            "CASE WHEN &quot;Subtype1&quot; IN (%s) THEN %s ELSE %s END, "
            "to_string((@lgs_d * cos(radians(&quot;DipDirection&quot; - 90)))) "
            "|| ',' || "
            "to_string((@lgs_d * sin(radians(&quot;DipDirection&quot; - 90))))) "
            "ELSE '%s' END" % (_in, dist_linear, dist_planar, fallback))


def suffix_expr(dist, fallback):
    return ("CASE WHEN &quot;Type&quot; = 'Structure' THEN "
            "to_string((%s * cos(radians(&quot;DipDirection&quot; - 90 + 135)))) "
            "|| ',' || "
            "to_string((%s * sin(radians(&quot;DipDirection&quot; - 90 + 135)))) "
            "ELSE '%s' END" % (dist, dist, fallback))


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

# SymbolSuffix rule: every prior form -> ground distances
SUF_OLD = suffix_expr("30.0", "15,15")
SUF_MM = suffix_expr("5.7", "2.8,2.8")
SUF_POINT = suffix_expr("17.0", "8.5,8.5")
SUF_NEW = suffix_expr(D_SUFFIX, "%s,%s" % (D_SUFFIX_FALLBACK,
                                           D_SUFFIX_FALLBACK))


def bail(msg):
    raise SystemExit("ABORT: " + msg)


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

    # 2. SymbolSuffix expression -> ground distances
    if SUF_NEW in qml:
        print("suffix expression already ground distances")
    elif SUF_POINT in qml:
        qml = qml.replace(SUF_POINT, SUF_NEW)
        print("suffix expression converted from Point (17.0)")
    elif SUF_OLD in qml:
        qml = qml.replace(SUF_OLD, SUF_NEW)
        print("suffix expression converted from authored MapUnit form")
    elif SUF_MM in qml:
        qml = qml.replace(SUF_MM, SUF_NEW)
        print("suffix expression converted from interim MM form")
    else:
        bail("SymbolSuffix OffsetXY expression not in any known state")

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
    ET.fromstring(q)
    assert NEW in q and SUF_NEW in q
    for desc in ("Dip Labels", "SymbolSuffix Labels"):
        block = re.search(r'<rule\b[^>]*description="%s">.*?</rule>' % desc,
                          q, re.S).group(0)
        assert 'offsetUnits="MapUnit"' in block, desc
        assert 'offsetUnits="Point"' not in block, desc
        assert 'offsetUnits="MM"' not in block, desc
    assert OLD_FLAT30 not in q and OLD_MU not in q and OLD_MM not in q
    assert OLD_POINT not in q
    assert SUF_OLD not in q and SUF_MM not in q and SUF_POINT not in q
    # The Regolith ring is a paper distance BY DESIGN and must survive.
    regolith = re.search(r'<rule\b[^>]*description="Regolith Note">.*?</rule>',
                         q, re.S).group(0)
    assert 'distUnits="Point"' in regolith, \
        "the Regolith ring should still be a paper distance"
    print(f"round-trip ok: {LAYER} dip labels family-aware ground distances "
          f"(linear {D_LINEAR} / planar {D_PLANAR}, suffix {D_SUFFIX} "
          f"at 1:{REFERENCE_SCALE})")
    con.close()


if __name__ == "__main__":
    main()
