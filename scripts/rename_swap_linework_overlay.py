"""Swap the template layer order: Linework becomes 2, Overlay becomes 3.

    "2 - Overlay"  ->  "3 - Overlay"
    "3 - Linework" ->  "2 - Linework"

The point is cartographic: Linework (contacts, veins, structural traces) now
draws ABOVE Overlay's translucent alteration / mineralisation washes instead of
underneath them.

Two things have to happen together, because in this template a layer's name and
its draw order are stored in different places:

  * the NAME is the GeoPackage table name, mirrored into eight metadata tables;
  * the ORDER is the gpkg_contents ROW ORDER - script_reprojectgeopackage.py
    selects feature layers with no ORDER BY and script_loadtemplate.py appends
    them to the layer tree in whatever order that returns.

So the rename is done IN PLACE against the existing gpkg_contents rows: rowid 2
keeps describing "the second layer from the top" and simply starts naming
Linework instead of Overlay. Renaming without that would leave numbers that
disagree with the stacking.

Per layer this touches: the table itself, gpkg_contents (table_name +
identifier), gpkg_geometry_columns, gpkg_ogr_contents, gpkg_extensions,
gpkg_metadata_reference, layer_styles (f_table_name + styleName), the styleSLD
blob (which carries the layer name twice), and the two feature-count triggers
whose NAMES embed the layer name.

Deliberately NOT touched: styleQML carries no self-reference (audited - every
ValueRelation, default expression and virtual field in the template resolves to
a code table or an own-field, never to a mapping layer), there are no relations,
joins, views or constraint expressions, and no per-layer rtree_* tables exist
despite gpkg_extensions declaring the rtree extension for both layers.

Runs against BOTH templates from one invocation so the styled (Patterns) and
unstyled copies cannot drift. Count-asserted throughout: every UPDATE checks it
hit exactly the expected number of rows and the whole file rolls back if not.

Idempotent: re-running after a successful swap is a no-op (it detects the new
names and skips). Back up first - this rewrites the templates in place.

Usage:  python scripts/rename_swap_linework_overlay.py [--dry-run] [gpkg ...]
        (defaults to both templates next to this repo)
"""
import os
import sqlite3
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = [
    os.path.join(REPO, "Template", "LGS_MappingTemplate.gpkg"),
    os.path.join(REPO, "Template", "LGS_MappingTemplate_Patterns.gpkg"),
]

# old -> new. Both halves of each name change, so the two renames can never
# collide with one another and need no temporary name.
RENAMES = {
    "2 - Overlay": "3 - Overlay",
    "3 - Linework": "2 - Linework",
}

# Tables where ROW ORDER is meaningful, so the rename has to move each layer's
# row into the slot its new number implies rather than relabel it in place.
# Two different consumers read two different tables, and both must agree:
#   gpkg_contents          -> the plugin's own loader (script_reprojectgeopackage
#                             .list_gpkg_contents selects with no ORDER BY, so it
#                             gets rowid order) and hence the QGIS layer tree
#   gpkg_geometry_columns  -> OGR's layer enumeration, and hence QGIS Browser,
#                             the Add Layer dialog and the QField export path
# Verified empirically: swapping only gpkg_contents leaves ogrinfo listing
# Overlay above Linework.
# Second element is the extra name-carrying columns to keep in step with
# table_name.
ORDERED_TABLES = [
    ("gpkg_contents", ("identifier",)),
    ("gpkg_geometry_columns", ()),
]

# Tables that merely mirror the table name, and how many rows each is expected
# to hold per renamed layer. Row order here has no consumer.
METADATA_TABLES = [
    ("gpkg_ogr_contents", 1),
    ("gpkg_extensions", 1),
    ("gpkg_metadata_reference", 2),
]

TRIGGER_TEMPLATE = (
    'CREATE TRIGGER "trigger_{action}_feature_count_{layer}" '
    'AFTER {upper} ON "{layer}" BEGIN '
    "UPDATE gpkg_ogr_contents SET feature_count = feature_count {op} 1 "
    "WHERE lower(table_name) = lower('{layer}'); END"
)


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def expect(cur, n, what):
    """Assert the statement just executed touched exactly n rows."""
    if cur.rowcount != n:
        bail("%s: expected %d row(s), hit %d" % (what, n, cur.rowcount))


def slot_swap(con, cur, table, name_cols, stamp):
    """Rename the layers AND move their rows into the new numeric order.

    rowid order is the draw order, so relabelling a row in place would leave
    Overlay sitting in slot 2 wearing a "3" label. Each layer's full row data
    (bbox, srs, geometry type) travels with it to the slot its new name implies:
    the same set of rowids is reoccupied, lowest rowid to the lowest new name.

    table_name is UNIQUE in both tables, so the names are parked on a temporary
    value first - otherwise a direct swap trips the constraint.
    """
    cols = [r[1] for r in con.execute("PRAGMA table_info(%s)" % table)]
    carried = [c for c in cols if c not in ("table_name", "last_change") + name_cols]
    sel = ", ".join('"%s"' % c for c in carried)

    src = {}
    for old in RENAMES:
        row = con.execute(
            "SELECT rowid%s FROM %s WHERE table_name=?"
            % (", " + sel if carried else "", table), (old,)).fetchone()
        if row is None:
            bail("%s: no row for %r" % (table, old))
        src[old] = (row[0], row[1:])

    # park the names so the reassignment cannot collide on the UNIQUE index
    for i, old in enumerate(RENAMES):
        cur.execute("UPDATE %s SET table_name=? WHERE table_name=?" % table,
                    ("__lgs_swap_%d__" % i, old))
        expect(cur, 1, "%s park %r" % (table, old))

    slots = sorted(rowid for rowid, _ in src.values())
    assigns = ["table_name=?"] + ['"%s"=?' % c for c in name_cols]
    if "last_change" in cols:
        assigns.append("last_change=?")
    assigns += ['"%s"=?' % c for c in carried]

    for rowid, (old, new) in zip(slots, sorted(RENAMES.items(),
                                               key=lambda kv: kv[1])):
        values = [new] + [new] * len(name_cols)
        if "last_change" in cols:
            values.append(stamp)
        values += list(src[old][1])
        cur.execute("UPDATE %s SET %s WHERE rowid=?"
                    % (table, ", ".join(assigns)), values + [rowid])
        expect(cur, 1, "%s rowid=%s" % (table, rowid))
        print("  %s rowid=%s: %r -> %r" % (table, rowid, old, new))

    # Only the spatial layers are numbered; gpkg_contents also lists the code
    # tables, whose order is insertion order and means nothing.
    where = " WHERE data_type='features'" if "data_type" in cols else ""
    order = [r[0] for r in con.execute(
        "SELECT table_name FROM %s%s ORDER BY rowid" % (table, where))]
    print("  %s row order: %s" % (table, order))
    if order != sorted(order):
        bail("%s row order does not match the layer numbering: %s"
             % (table, order))


def already_swapped(con):
    names = {r[0] for r in con.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type='features'")}
    if set(RENAMES.values()) <= names:
        return True
    if not set(RENAMES) <= names:
        bail("found neither the old nor the new layer names: %s" % sorted(names))
    return False


def swap_file(path, dry_run=False):
    print("=" * 68)
    print(path)
    if not os.path.exists(path):
        bail("no such file: %s" % path)

    con = sqlite3.connect(path)
    con.isolation_level = None          # explicit transaction control
    cur = con.cursor()

    if already_swapped(con):
        print("  already swapped - nothing to do")
        con.close()
        return

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    cur.execute("BEGIN")
    try:
        # --- 1. drop the feature-count triggers -----------------------------
        # Dropped BEFORE the rename so SQLite does not silently rewrite their
        # bodies and leave us with correct SQL under an obsolete trigger name.
        for old in RENAMES:
            for action in ("insert", "delete"):
                name = "trigger_%s_feature_count_%s" % (action, old)
                if not con.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='trigger' "
                        "AND name=?", (name,)).fetchone():
                    bail("missing expected trigger %r" % name)
                cur.execute('DROP TRIGGER "%s"' % name)
        print("  dropped 4 feature-count triggers")

        # --- 2. rename the tables -------------------------------------------
        for old, new in RENAMES.items():
            cur.execute('ALTER TABLE "%s" RENAME TO "%s"' % (old, new))
        print("  renamed 2 tables")

        # --- 3. the order-bearing tables: swap ROWS, not just names ----------
        for table, name_cols in ORDERED_TABLES:
            slot_swap(con, cur, table, name_cols, stamp)

        # --- 4. the other metadata tables ------------------------------------
        for table, per_layer in METADATA_TABLES:
            for old, new in RENAMES.items():
                cur.execute(
                    "UPDATE %s SET table_name=? WHERE table_name=?" % table,
                    (new, old))
                expect(cur, per_layer, "%s %r" % (table, old))
            print("  %s: %d row(s) updated" % (table, per_layer * len(RENAMES)))

        # --- 5. layer_styles: keys, plus the name embedded in the SLD --------
        for old, new in RENAMES.items():
            rows = con.execute(
                "SELECT id, styleQML, styleSLD FROM layer_styles "
                "WHERE f_table_name=?", (old,)).fetchall()
            if not rows:
                bail("no layer_styles row for %r" % old)
            for sid, qml, sld in rows:
                if qml and old in qml:
                    # Audited as absent; if that ever changes, fix it rather
                    # than leaving a stale self-reference behind.
                    bail("styleQML for %r unexpectedly self-references the "
                         "layer name (id=%s)" % (old, sid))
                new_sld = sld.replace(old, new) if sld else sld
                n_sld = sld.count(old) if sld else 0
                cur.execute(
                    "UPDATE layer_styles SET f_table_name=?, styleName=?, "
                    "styleSLD=? WHERE id=?", (new, new, new_sld, sid))
                expect(cur, 1, "layer_styles id=%s" % sid)
                print("  layer_styles id=%s: %r -> %r (%d SLD ref(s))"
                      % (sid, old, new, n_sld))

        # --- 6. recreate the triggers under their new names ------------------
        for new in RENAMES.values():
            for action, upper, op in (("insert", "INSERT", "+"),
                                      ("delete", "DELETE", "-")):
                cur.execute(TRIGGER_TEMPLATE.format(
                    action=action, upper=upper, op=op, layer=new))
        print("  recreated 4 feature-count triggers")

        if dry_run:
            cur.execute("ROLLBACK")
            print("  DRY RUN - rolled back")
            con.close()
            return

        cur.execute("COMMIT")
    except Exception:
        cur.execute("ROLLBACK")
        con.close()
        raise

    ok, = con.execute("PRAGMA integrity_check").fetchone()
    if ok != "ok":
        bail("integrity_check failed after write: %s" % ok)
    print("  committed; integrity_check ok")
    con.close()


def main(argv):
    dry_run = "--dry-run" in argv
    targets = [a for a in argv if not a.startswith("--")] or TEMPLATES
    for path in targets:
        swap_file(path, dry_run=dry_run)
    print("=" * 68)
    print("done%s" % (" (dry run)" if dry_run else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
