"""Family-aware dip-label offsets for 1 - FieldNotebook.

The Dip Labels rule offsets the dip value down-dip by a flat 30 map
units.  On the repaired symbol set (uniform 30 pt markers) that is too
far for planar symbols (strike bar + short tick, reach ~11 map units at
the 1:5000 reference scale) and too close for linear symbols (full-length
plunge arrows, tip at ~26 map units - the arrowhead touches the label).

This injector rewrites the rule's data-defined OffsetXY expression so
the distance depends on the structural family (user decision 2026-08-15):

    linear (plunge arrows)  -> 34 map units (clears the arrowhead)
    planar (strike symbols) -> 17 map units (hugs the dip tick)

The linear code list mirrors stereonet/data.py structure_classification
('L'/'l' entries).  The Type='Structure' gate and the '4,-4' fallback
are kept exactly as before, as is the SymbolSuffix rule.

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

OLD = ("CASE WHEN &quot;Type&quot; = 'Structure' THEN "
       "to_string((30.0 * cos(radians(&quot;DipDirection&quot; - 90)))) "
       "|| ',' || "
       "to_string((30.0 * sin(radians(&quot;DipDirection&quot; - 90)))) "
       "ELSE '4,-4' END")

_in_list = ",".join("'%s'" % c for c in LINEAR)
NEW = ("CASE WHEN &quot;Type&quot; = 'Structure' THEN with_variable('lgs_d', "
       "CASE WHEN &quot;Subtype1&quot; IN (%s) THEN %s ELSE %s END, "
       "to_string((@lgs_d * cos(radians(&quot;DipDirection&quot; - 90)))) "
       "|| ',' || "
       "to_string((@lgs_d * sin(radians(&quot;DipDirection&quot; - 90))))) "
       "ELSE '4,-4' END" % (_in_list, D_LINEAR, D_PLANAR))


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

    n_old, n_new = qml.count(OLD), qml.count(NEW)
    if n_new and not n_old:
        print(f"already applied ({n_new} occurrence(s)) - no-op")
    elif n_old and not n_new:
        # the flat-30 expression appears once per storage site of the rule
        qml2 = qml.replace(OLD, NEW)
        assert qml2.count(NEW) == n_old
        try:
            ET.fromstring(qml2)
        except ET.ParseError as exc:
            bail(f"edited QML no longer parses: {exc}")
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml2, LAYER))
        assert cur.rowcount == 1
        con.commit()
        print(f"OffsetXY rewritten ({n_old} occurrence(s)): "
              f"linear {D_LINEAR} / planar {D_PLANAR} map units")
    else:
        bail(f"unexpected state: old={n_old} new={n_new}")

    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    q, = cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                     (LAYER,)).fetchone()
    ET.fromstring(q)
    assert q.count(NEW) >= 1 and q.count(OLD) == 0
    print(f"round-trip ok: {LAYER} dip-label offsets family-aware")
    con.close()


if __name__ == "__main__":
    main()
