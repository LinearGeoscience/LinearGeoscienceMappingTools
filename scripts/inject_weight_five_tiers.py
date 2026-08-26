"""Grow the Weight scale to five tiers: Incipient / Minor / Moderate / Major / Regional.

User request, 27 Aug 2026: three thickness tiers are not enough in the
field.  Two new tiers, named by the user - Incipient below Minor (a
structure just beginning to develop) and Regional above Major (a
regional-scale structure).  Minor / Moderate / Major keep their names and
factors, so no existing data migrates and Moderate stays the default and
the NULL fallback everywhere.

Two edits per layer ("2 - Linework" and "3 - Overlay" - the only layers
with a Weight column), applied to the live template:

  1. The Weight ValueMap widget gains the two tiers, listed descending:
     Regional, Major, Moderate, Minor, Incipient.  The widget is the
     single source of the tier list (there is no WeightCodes table);
     the legend and data_import discover the codes from it.
  2. The baked label fontSize WEIGHT_F CASE is patched in place from the
     two-branch 1.15/0.8 form to the four-branch 1.3/1.15/0.8/0.7 form.
     Patched rather than re-run because inject_label_size_scaling
     multiplies its factors into CURRENT statics - re-running it would
     compound them.  inject_label_size_scaling.WEIGHT_F carries the same
     new text so the constants-agree test holds.

The stroke and zone-hatch ramps are NOT touched here: re-run
inject_weight_scaling.py (then inject_vein_generation_selvedge.py, then
inject_weight_scaling.py again) after this to rebuild those from the
updated FACTORS / OVERLAY_ZONE_FACTORS.

Idempotent and re-runnable: each layer must be exactly three-tier (apply)
or exactly five-tier (no-op); anything else aborts without writing.

Usage:  python scripts/inject_weight_five_tiers.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

LAYERS = ["2 - Linework", "3 - Overlay"]

OLD_TIERS = ["Major", "Moderate", "Minor"]
NEW_TIERS = ["Regional", "Major", "Moderate", "Minor", "Incipient"]

OLD_WEIGHT_F = ("CASE WHEN \"Weight\" = 'Major' THEN 1.15 "
                "WHEN \"Weight\" = 'Minor' THEN 0.8 ELSE 1 END")
NEW_WEIGHT_F = ("CASE WHEN \"Weight\" = 'Regional' THEN 1.3 "
                "WHEN \"Weight\" = 'Major' THEN 1.15 "
                "WHEN \"Weight\" = 'Minor' THEN 0.8 "
                "WHEN \"Weight\" = 'Incipient' THEN 0.7 ELSE 1 END")


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def esc(expr):
    """An expression as it appears inside a styleQML attribute value."""
    return (expr.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def weight_field_block(qml, layer):
    m = re.search(r'<field name="Weight" configurationFlags[^>]*>.*?</field>',
                  qml, re.S)
    if not m:
        bail(f"{layer}: Weight field config not found")
    return m


def tier_entries(block):
    """[(entry substring, name)] for each map entry, in listed order."""
    return [(m.group(0), m.group(1)) for m in re.finditer(
        r'<Option type="Map">\s*<Option name="([^"]+)" type="QString" '
        r'value="[^"]*"/>\s*</Option>', block)]


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    changed = False
    for layer in LAYERS:
        row = cur.execute(
            "SELECT styleQML FROM layer_styles WHERE f_table_name=?",
            (layer,)).fetchone()
        if not row or not row[0]:
            bail(f"styleQML missing for {layer!r}")
        qml = original = row[0]

        # -- 1. ValueMap tiers (0 or 1 edit) ---------------------------
        fm = weight_field_block(qml, layer)
        block = fm.group(0)
        if 'type="ValueMap"' not in block:
            bail(f"{layer}: Weight widget is not a ValueMap")
        entries = tier_entries(block)
        names = [n for _e, n in entries]
        if names == NEW_TIERS:
            print(f"{layer}: ValueMap already five-tier")
        elif names == OLD_TIERS:
            # Template the new entries off the existing Major entry so the
            # attribute layout matches whatever this QGIS build wrote.
            major = entries[0][0]
            if major.count("Major") != 2:
                bail(f"{layer}: unexpected Major entry shape: {major!r}")

            def entry_for(tier):
                return major.replace("Major", tier)

            new_block = (block[:block.index(entries[0][0])]
                         + "".join(entry_for(t) for t in NEW_TIERS)
                         + block[block.index(entries[-1][0]) + len(entries[-1][0]):])
            qml = qml[:fm.start()] + new_block + qml[fm.end():]
            print(f"{layer}: ValueMap {' / '.join(OLD_TIERS)} -> "
                  f"{' / '.join(NEW_TIERS)}")
        else:
            bail(f"{layer}: unexpected Weight tiers {names}")

        # -- 2. label fontSize WEIGHT_F (0 or 1 edit) ------------------
        old_esc, new_esc = esc(OLD_WEIGHT_F), esc(NEW_WEIGHT_F)
        n_old, n_new = qml.count(old_esc), qml.count(new_esc)
        if (n_old, n_new) == (0, 1):
            print(f"{layer}: label WEIGHT_F already four-branch")
        elif (n_old, n_new) == (1, 0):
            qml = qml.replace(old_esc, new_esc)
            print(f"{layer}: label WEIGHT_F patched to four branches")
        else:
            bail(f"{layer}: label WEIGHT_F counts old={n_old} new={n_new}, "
                 "expected (1,0) or (0,1)")

        if qml == original:
            continue
        try:
            ET.fromstring(qml)
        except ET.ParseError as exc:
            bail(f"{layer}: edited QML no longer parses, aborting: {exc}")
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, layer))
        assert cur.rowcount == 1
        changed = True

    if changed:
        con.commit()
        print("styleQML updated")
    else:
        print("already applied (no change)")

    # ---------------- validation --------------------------------------
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    for layer in LAYERS:
        qml, = cur.execute(
            "SELECT styleQML FROM layer_styles WHERE f_table_name=?",
            (layer,)).fetchone()
        ET.fromstring(qml)
        names = [n for _e, n in tier_entries(weight_field_block(qml, layer).group(0))]
        assert names == NEW_TIERS, (layer, names)
        assert qml.count(esc(NEW_WEIGHT_F)) == 1, layer
        assert qml.count(esc(OLD_WEIGHT_F)) == 0, layer
        print(f"round-trip ok: {layer} - 5 tiers, four-branch label WEIGHT_F")
    con.close()


if __name__ == "__main__":
    main()
