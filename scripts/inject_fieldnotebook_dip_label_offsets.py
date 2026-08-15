"""Point-unit, family-aware dip-label offsets for 1 - FieldNotebook.

Point units for everything (user directive 2026-08-15): the renderer
reference scale is a per-project knob (users retarget it to 1:200 -
1:500 for UG mapping), and only Point measurements track the 30 pt
markers under it.  The authored offsets were MapUnits sized against
the 1:5000 design footprint - at a 1:200 reference scale those ground
distances swamp the symbol.

Distances are the symbol-ratio equivalents on the 30 pt marker (whose
canvas spans 52.9 design units), family-aware because a flat distance
is too far for planar strike symbols and lands inside the plunge
arrows:

    Dip Labels     linear (plunge arrows)  21.5 pt (clears the arrowhead)
                   planar (strike symbols)  9.6 pt (hugs the dip tick)
                   non-structure fallback  '2.3,-2.3'
    SymbolSuffix   17 pt at dip direction +135; fallback '8.5,8.5'

offsetUnits become Point on the two structural rules only.  The linear
code list mirrors stereonet/data.py structure_classification ('L'/'l'
entries).  Upgrades cleanly from the flat-30 MapUnit original, the
family-aware MapUnit interim (38/17), or the MM interim (7.2/3.2).
Type='Structure' gating is kept as-is.

Idempotent and re-runnable; QML parse-validated BEFORE writing.

Usage:  python scripts/inject_fieldnotebook_dip_label_offsets.py [gpkg]
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

LAYER = "1 - FieldNotebook"

# stereonet/data.py structure_classification codes marked 'L' or 'l'
LINEAR = ("BAX", "FAX", "FAX1", "FAX1M", "FAX1S", "FAX1Z",
          "FAX2", "FAX2M", "FAX2S", "FAX2Z", "FAX3", "FAX3M", "FAX3S",
          "FAX3Z", "FAX4", "FAX4M", "FAX4S", "FAX4Z", "FAX5", "FAX5M",
          "FAX5S", "FAX5Z", "FAXCR", "FAXK", "FAXSZ", "LME", "LNI",
          "LNI1", "LNI2", "LNI3", "LNI4", "LNI5", "LNISC", "LNS",
          "SLF", "SLK", "STR")
D_LINEAR = "21.5"
D_PLANAR = "9.6"

_in = ",".join("'%s'" % c for c in LINEAR)


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
NEW = dip_expr(D_LINEAR, D_PLANAR, "2.3,-2.3")

# SymbolSuffix rule: authored MapUnit / interim MM forms -> Point
SUF_OLD = ("CASE WHEN &quot;Type&quot; = 'Structure' THEN "
           "to_string((30.0 * cos(radians(&quot;DipDirection&quot; - 90 + 135)))) "
           "|| ',' || "
           "to_string((30.0 * sin(radians(&quot;DipDirection&quot; - 90 + 135)))) "
           "ELSE '15,15' END")
SUF_MM = ("CASE WHEN &quot;Type&quot; = 'Structure' THEN "
           "to_string((5.7 * cos(radians(&quot;DipDirection&quot; - 90 + 135)))) "
           "|| ',' || "
           "to_string((5.7 * sin(radians(&quot;DipDirection&quot; - 90 + 135)))) "
           "ELSE '2.8,2.8' END")
SUF_NEW = ("CASE WHEN &quot;Type&quot; = 'Structure' THEN "
           "to_string((17.0 * cos(radians(&quot;DipDirection&quot; - 90 + 135)))) "
           "|| ',' || "
           "to_string((17.0 * sin(radians(&quot;DipDirection&quot; - 90 + 135)))) "
           "ELSE '8.5,8.5' END")


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
        print("dip expression already family-aware Point")
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

    # 2. SymbolSuffix expression -> Point distances
    if SUF_NEW in qml:
        print("suffix expression already Point")
    elif SUF_OLD in qml:
        qml = qml.replace(SUF_OLD, SUF_NEW)
        print("suffix expression converted from authored MapUnit form")
    elif SUF_MM in qml:
        qml = qml.replace(SUF_MM, SUF_NEW)
        print("suffix expression converted from interim MM form")
    else:
        bail("SymbolSuffix OffsetXY expression not in any known state")

    # 3. offsetUnits -> Point on the two structural rules only; other
    #    rules (comment/callout labels) keep their own tuned units
    for desc in ("Dip Labels", "SymbolSuffix Labels"):
        m = re.search(r'<rule\b[^>]*description="%s">.*?</rule>' % desc,
                      qml, re.S)
        if not m:
            bail(f"rule {desc!r} not found")
        block = m.group(0)
        for wrong in ('offsetUnits="MapUnit"', 'offsetUnits="MM"'):
            if wrong in block:
                block = block.replace(wrong, 'offsetUnits="Point"')
                print(f"{desc}: {wrong} -> Point")
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
        assert 'offsetUnits="Point"' in block, desc
        assert 'offsetUnits="MapUnit"' not in block, desc
        assert 'offsetUnits="MM"' not in block, desc
    assert OLD_FLAT30 not in q and OLD_MU not in q and OLD_MM not in q
    assert SUF_OLD not in q and SUF_MM not in q
    print(f"round-trip ok: {LAYER} dip labels family-aware Point "
          f"(linear {D_LINEAR} / planar {D_PLANAR} pt, suffix 17 pt)")
    con.close()


if __name__ == "__main__":
    main()
