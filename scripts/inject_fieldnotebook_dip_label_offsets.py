"""Family-aware dip-label offsets for 1 - FieldNotebook.

The renderer reference scale (1:5000) makes the Point-sized markers
behave ground-fixed, so the authored MapUnit label offsets are the
correct pairing - they track the symbol at every zoom.  What needed
fixing was the flat 30-unit distance: too far for planar strike
symbols (dip tick reaches ~11 map units) and inside the plunge arrows
(tip at ~26 map units, so the arrowhead touched the dip value).

The Dip Labels OffsetXY expression picks the distance by structural
family (user decision 2026-08-15):

    linear (plunge arrows)  -> 38 map units (clears the arrowhead)
    planar (strike symbols) -> 17 map units (hugs the dip tick)

The linear code list mirrors stereonet/data.py structure_classification
('L'/'l' entries).  The SymbolSuffix rule and all offset units keep
their authored MapUnit form (an interim MM conversion is reverted if
present).  Type='Structure' gating is kept as-is.

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
D_LINEAR = "38.0"
D_PLANAR = "17.0"

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
NEW = dip_expr(D_LINEAR, D_PLANAR, "4,-4")

# SymbolSuffix rule: authored MapUnit form (kept); SUF_MM is the interim
# MM conversion this script now reverts if found
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

    # 1. Dip Labels expression (from either prior state)
    if NEW in qml:
        print("dip expression already family-aware MapUnit")
    elif OLD_MM in qml:
        qml = qml.replace(OLD_MM, NEW)
        print("dip expression reverted from interim MM form")
    elif OLD_FLAT30 in qml:
        qml = qml.replace(OLD_FLAT30, NEW)
        print("dip expression upgraded from flat 30 MapUnit")
    else:
        bail("Dip Labels OffsetXY expression not in any known state")

    # 2. SymbolSuffix expression stays in its authored MapUnit form;
    #    revert the interim MM conversion if present
    if SUF_OLD in qml:
        print("suffix expression in authored MapUnit form")
    elif SUF_MM in qml:
        qml = qml.replace(SUF_MM, SUF_OLD)
        print("suffix expression reverted to MapUnit form")
    else:
        bail("SymbolSuffix OffsetXY expression not in any known state")

    # 3. offsetUnits stay MapUnit on the structural rules (ground-fixed
    #    symbols need ground-fixed offsets); revert the interim MM swap
    for desc in ("Dip Labels", "SymbolSuffix Labels"):
        m = re.search(r'<rule\b[^>]*description="%s">.*?</rule>' % desc,
                      qml, re.S)
        if not m:
            bail(f"rule {desc!r} not found")
        block = m.group(0)
        if 'offsetUnits="MM"' in block:
            qml = (qml[:m.start()]
                   + block.replace('offsetUnits="MM"',
                                   'offsetUnits="MapUnit"')
                   + qml[m.end():])
            print(f"{desc}: offsetUnits reverted MM -> MapUnit")

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
    assert NEW in q and SUF_OLD in q
    for desc in ("Dip Labels", "SymbolSuffix Labels"):
        block = re.search(r'<rule\b[^>]*description="%s">.*?</rule>' % desc,
                          q, re.S).group(0)
        assert 'offsetUnits="MM"' not in block, desc
    assert OLD_FLAT30 not in q and OLD_MM not in q and SUF_MM not in q
    print(f"round-trip ok: {LAYER} dip labels family-aware "
          f"(linear {D_LINEAR} / planar {D_PLANAR} map units)")
    con.close()


if __name__ == "__main__":
    main()
