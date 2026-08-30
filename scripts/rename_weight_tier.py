"""Rename the lowest Weight tier: "Incipient" -> "Very Minor".

User request, 29 Aug 2026: "Incipient" reads as jargon in the field; the
tier below Minor should simply be "Very Minor".  Factors, defaults and
sort order are untouched - only the value string changes.

The tier list has no lookup table (the Weight ValueMap widget in each
layer's styleQML is the single source - see inject_weight_five_tiers.py),
so the rename is a string swap across every baked occurrence:

  * "2 - Linework" styleQML - the ValueMap entry plus every baked
    CASE WHEN "Weight" = 'Incipient' branch (stroke widths, marker
    sizes/outlines, selvedge ring offsets, label fontSize).
  * "3 - Overlay" styleQML - ValueMap + zone-hatch ramp + label ramp.
  * Any feature rows already recorded with Weight='Incipient' (zero in
    the shipped template; this is the migration path for field-project
    gpkgs - point the script at the project file).

A plain replace is safe: the token appears only as the tier name, always
inside an attribute value (ValueMap Option name/value, or a
single-quoted literal inside an expression), and "Very Minor" is legal
in both contexts.  The SLD twin never names Weight tiers (asserted).

The python constants that bake these expressions move in the same
commit: inject_weight_scaling.FACTORS / OVERLAY_ZONE_FACTORS,
inject_weight_five_tiers.NEW_TIERS / NEW_WEIGHT_F,
inject_label_size_scaling.WEIGHT_F, tests/test_import_domain.

Never point this at LGS_MappingTemplate_Patterns.gpkg - that file is
re-baked wholesale by inject_basemap_lith_patterns.py.

Idempotent: a layer must carry only old names (apply) or only new names
(no-op); a mix aborts without writing.

Usage:
    python scripts/rename_weight_tier.py [path\\to\\file.gpkg]
"""

import os
import shutil
import sqlite3
import sys
import xml.etree.ElementTree as ET

OLD = "Incipient"
NEW = "Very Minor"

LAYERS = ["2 - Linework", "3 - Overlay"]

BACKUP_DATE = "2026-08-29"
BACKUP_NAME = "LGS_MappingTemplate_pre-very-minor_%s.gpkg" % BACKUP_DATE


def bail(msg):
    raise SystemExit("ABORT: " + msg)


# ---------------------------------------------------------------------------
# File guards (shape from inject_vein_generation_selvedge.py)
# ---------------------------------------------------------------------------

def back_up(repo, gpkg):
    if os.path.abspath(gpkg) == os.path.abspath(
            os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")):
        dest = os.path.join(repo, "Template", "Backup", BACKUP_NAME)
    else:
        stem, ext = os.path.splitext(gpkg)
        dest = "%s_pre-very-minor_%s%s" % (stem, BACKUP_DATE, ext)
    if not os.path.exists(dest):
        shutil.copy2(gpkg, dest)
    return dest


def refuse_if_open(gpkg):
    """Bail if QGIS still has the gpkg open (see inject_vein_generation_selvedge)."""
    if os.path.exists(gpkg + "-wal"):
        bail("%s has an active -wal alongside it, so something still has it "
             "open. Close the project in QGIS first." % os.path.basename(gpkg))
    try:
        con = sqlite3.connect(gpkg, timeout=1.0)
        con.execute("BEGIN IMMEDIATE")
        con.execute("ROLLBACK")
        con.close()
    except sqlite3.OperationalError as exc:
        bail("%s is locked (%s) - close the project in QGIS and re-run"
             % (os.path.basename(gpkg), exc))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default = os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail("gpkg not found: %s" % gpkg)
    if "_Patterns" in os.path.basename(gpkg):
        bail("never point this at the Patterns gpkg - it is re-baked "
             "wholesale by inject_basemap_lith_patterns.py")

    refuse_if_open(gpkg)

    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    # Decide per layer, all-or-nothing across the file.
    updates = {}
    for layer in LAYERS:
        rows = cur.execute(
            "SELECT styleQML, styleSLD FROM layer_styles WHERE f_table_name=?",
            (layer,)).fetchall()
        if not rows:
            bail("no layer_styles row for %r" % layer)
        qml, sld = rows[0]
        if len(rows) > 1:
            bail("%d layer_styles rows for %r - expected one" % (len(rows), layer))
        if sld and OLD in sld:
            bail("styleSLD for %r names %r - this script only handles QML"
                 % (layer, OLD))
        n_old = (qml or "").count(OLD)
        n_new = (qml or "").count(NEW)
        if n_old and not n_new:
            updates[layer] = qml.replace(OLD, NEW)
            print("%s: renaming %d occurrence(s)" % (layer, n_old))
        elif n_new and not n_old:
            print("%s: already renamed (%d occurrence(s) of %r)"
                  % (layer, n_new, NEW))
        elif not n_old and not n_new:
            bail("%r styleQML names neither tier - is this a five-tier "
                 "template? Run inject_weight_five_tiers.py first." % layer)
        else:
            bail("%r styleQML carries BOTH %r (%d) and %r (%d) - half-applied "
                 "state, refusing to guess" % (layer, OLD, n_old, NEW, n_new))

    # Feature rows (the migration path for field-project gpkgs).
    migrations = {}
    for layer in LAYERS:
        has = cur.execute(
            "SELECT COUNT(*) FROM gpkg_contents WHERE table_name=?",
            (layer,)).fetchone()[0]
        if not has:
            continue
        n = cur.execute(
            'SELECT COUNT(*) FROM "%s" WHERE Weight=?' % layer, (OLD,)
        ).fetchone()[0]
        migrations[layer] = n

    if not updates and not any(migrations.values()):
        print("nothing to do")
        con.close()
        return

    for layer, qml in updates.items():
        try:
            ET.fromstring(qml)
        except ET.ParseError as exc:
            bail("renamed QML for %r no longer parses, aborting before "
                 "write: %s" % (layer, exc))

    dest = back_up(repo, gpkg)
    print("backup: %s" % dest)

    for layer, qml in updates.items():
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, layer))
        assert cur.rowcount == 1
    for layer, n in migrations.items():
        cur.execute('UPDATE "%s" SET Weight=? WHERE Weight=?' % layer,
                    (NEW, OLD))
        print("%s: migrated %d feature row(s)" % (layer, cur.rowcount))
        assert cur.rowcount == n

    con.commit()
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])

    # ---------------- round-trip validation ----------------------------
    for layer in LAYERS:
        row = cur.execute(
            "SELECT styleQML FROM layer_styles WHERE f_table_name=?",
            (layer,)).fetchone()
        q = row[0]
        assert OLD not in q, "%s still names %r" % (layer, OLD)
        root = ET.fromstring(q)
        # The ValueMap must offer the new tier exactly once per Weight widget.
        offered = [el for el in root.iter("Option")
                   if el.get("value") == NEW or el.get("name") == NEW]
        assert offered, "%s ValueMap does not offer %r" % (layer, NEW)
    print("done: %r -> %r" % (OLD, NEW))
    con.close()


if __name__ == "__main__":
    main()
