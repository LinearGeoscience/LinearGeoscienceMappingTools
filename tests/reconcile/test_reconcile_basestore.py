#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Headless tests for the embedded base store (basestore.py), the checkout_id
registry additions, and the pure migration_status preflight. No QGIS.

Run:  python tests/reconcile/test_reconcile_basestore.py
"""

import os
import sys
import sqlite3
import tempfile

PLUGIN_ROOT = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", ".."))
RECONCILE_DIR = os.path.join(PLUGIN_ROOT, "script_adddata", "reconcile")
sys.path.insert(0, RECONCILE_DIR)
sys.path.insert(0, PLUGIN_ROOT)  # lgs_layers for migrate

import basestore         # noqa: E402
import checkout          # noqa: E402
import migrate           # noqa: E402
from commit import LGS_META_FIELDS                       # noqa: E402
from snapshot import FeaturePayload, snapshot_from_payloads  # noqa: E402

_passed = 0
_failed = 0


def check(cond, label):
    global _passed, _failed
    if cond:
        _passed += 1
    else:
        _failed += 1
        print(f"  FAIL: {label}")


def payload(uuid, **attrs):
    a = {"UUID": uuid, "geom": None}
    a.update(attrs)
    return FeaturePayload(uuid=uuid, attrs=a, uuid_field="UUID", geom_field="geom")


def make_gpkg(path, feature_tables=()):
    """A minimal fake GeoPackage: gpkg_contents + optional feature tables."""
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("CREATE TABLE gpkg_contents (table_name TEXT PRIMARY KEY, "
                "data_type TEXT, identifier TEXT, description TEXT, "
                "last_change TEXT)")
    for name, cols in feature_tables:
        col_sql = ", ".join(f'"{c}" TEXT' for c in cols)
        cur.execute(f'CREATE TABLE "{name}" '
                    f'(fid INTEGER PRIMARY KEY, {col_sql})')
        cur.execute("INSERT INTO gpkg_contents (table_name, data_type, "
                    "identifier) VALUES (?, 'features', ?)", (name, name))
    con.commit()
    con.close()


def snap_of(*payloads_):
    return snapshot_from_payloads(
        "1 - FieldNotebook", "UUID", {p.uuid: p for p in payloads_})


def gpkg_contents_names(path):
    con = sqlite3.connect(path)
    try:
        return {r[0] for r in con.execute(
            "SELECT table_name FROM gpkg_contents")}
    finally:
        con.close()


def test_checkout_roundtrip(d):
    wc = os.path.join(d, "copy_a.gpkg")
    make_gpkg(wc)
    check(not basestore.has_checkout(wc), "fresh file has no checkout")
    check(basestore.read_checkout(wc) is None, "read_checkout None when unstamped")

    row = basestore.write_checkout(wc, {
        "master_id": "m-uid-1", "master_name": "LGS_Master.gpkg",
        "mapper": "HW", "master_version": 3, "source_mode": "full"})
    check(bool(row["checkout_id"]), "checkout_id generated")
    check(basestore.has_checkout(wc), "has_checkout after stamp")
    back = basestore.read_checkout(wc)
    check(back["checkout_id"] == row["checkout_id"], "checkout_id round-trips")
    check(back["master_id"] == "m-uid-1" and back["mapper"] == "HW"
          and back["source_mode"] == "full" and back["master_version"] == 3,
          "checkout fields round-trip")

    # Restamp replaces the singleton (new identity), never adds a second row.
    row2 = basestore.write_checkout(wc, {"mapper": "JS", "source_mode": "clip"})
    back2 = basestore.read_checkout(wc)
    check(back2["checkout_id"] == row2["checkout_id"] != row["checkout_id"],
          "restamp replaces the singleton with a fresh identity")

    # None of the embedded tables leak into gpkg_contents.
    check(gpkg_contents_names(wc) == set(),
          "embedded tables NOT registered in gpkg_contents")


def test_base_roundtrip(d):
    wc = os.path.join(d, "copy_b.gpkg")
    make_gpkg(wc)

    # write_base before write_checkout must refuse: legacy files stay legacy.
    try:
        basestore.write_base(wc, {"1 - FieldNotebook": snap_of(payload("a"))})
        check(False, "write_base without checkout raises")
    except ValueError:
        check(True, "write_base without checkout raises")

    basestore.write_checkout(wc, {"mapper": "HW"})
    p_a, p_b = payload("a", Dip=10), payload("b", Dip=20)
    snap = snap_of(p_a, p_b)
    empty = snapshot_from_payloads("2 - Linework", "UUID", {})
    counts = basestore.write_base(
        wc, {"1 - FieldNotebook": snap, "2 - Linework": empty},
        master_version=5)
    check(counts == {"1 - FieldNotebook": 2, "2 - Linework": 0},
          "write_base reports per-layer counts")

    base = basestore.read_base(wc)
    check(base is not None, "base loads back")
    fps = base["layers"]["1 - FieldNotebook"]
    check(set(fps) == {"a", "b"}, "base uuids round-trip")
    check(fps["a"].equals(p_a.fingerprint()), "fingerprint round-trips intact")
    check(fps["a"].field_hashes == p_a.fingerprint().field_hashes,
          "field_hashes JSON round-trips")
    check(base["layers"]["2 - Linework"] == {},
          "recorded-but-empty layer is an empty dict")
    check(base["master_version_at_capture"] == 5, "master_version persisted")
    check(base["mapper"] == "HW", "mapper comes from the checkout row")
    check(basestore.read_base_layer(wc, "3 - Overlay") == {},
          "absent layer in an existing base reads as empty (not None)")

    # A fingerprint written with field_hashes=None stays None (legacy shape).
    fp_nofields = p_a.fingerprint()
    fp_nofields.field_hashes = None
    snap2 = snap_of(p_a)
    snap2.features["a"] = fp_nofields
    basestore.write_base(wc, {"1 - FieldNotebook": snap2})
    base2 = basestore.read_base(wc)
    check(base2["layers"]["1 - FieldNotebook"]["a"].field_hashes is None,
          "None field_hashes survives the round-trip")
    # And that second write replaced the layer wholesale (b is gone).
    check(set(base2["layers"]["1 - FieldNotebook"]) == {"a"},
          "write_base replaces a layer wholesale")

    check(gpkg_contents_names(wc) == set(),
          "base tables NOT registered in gpkg_contents")

    # Unstamped/absent files read as None (fall through to sidecar).
    other = os.path.join(d, "copy_c.gpkg")
    make_gpkg(other)
    check(basestore.read_base(other) is None, "no base -> None")
    check(basestore.read_base(os.path.join(d, "missing.gpkg")) is None,
          "missing file -> None")

    basestore.drop_embedded_tables(wc)
    check(not basestore.has_checkout(wc) and basestore.read_base(wc) is None,
          "drop_embedded_tables removes stamp and base")


def test_newest_base():
    older = {"captured_utc": "2026-09-01T00:00:00+00:00", "layers": {}}
    newer = {"captured_utc": "2026-09-03T00:00:00+00:00", "layers": {}}
    check(basestore.newest_base(None, None) == (None, None),
          "neither -> (None, None)")
    check(basestore.newest_base(older, None)[1] == "embedded",
          "embedded only -> embedded")
    check(basestore.newest_base(None, older)[1] == "sidecar",
          "sidecar only -> sidecar")
    base, src = basestore.newest_base(older, newer)
    check(src == "sidecar" and base is newer, "newer sidecar wins")
    base, src = basestore.newest_base(newer, older)
    check(src == "embedded" and base is newer, "newer embedded wins")
    tie, src = basestore.newest_base(older, dict(older))
    check(src == "embedded", "tie goes to embedded")


def test_master_uid(d):
    master = os.path.join(d, "LGS_Master_28350.gpkg")
    make_gpkg(master)
    check(basestore.read_master_uid(master) is None,
          "unstamped master has no uid")
    uid = basestore.ensure_master_uid(master)
    check(bool(uid), "ensure_master_uid creates a uid")
    check(basestore.ensure_master_uid(master) == uid,
          "ensure_master_uid is idempotent")
    check(basestore.read_master_uid(master) == uid, "read matches ensure")
    check(basestore.ensure_master_uid(os.path.join(d, "gone.gpkg")) is None,
          "missing master -> None, no crash")
    check("lgs_master" not in gpkg_contents_names(master),
          "lgs_master NOT registered in gpkg_contents")


def test_registry_checkout_ids(d):
    master = os.path.join(d, "LGS_Master_reg.gpkg")
    reg = checkout.CheckoutRegistry(master)
    # Two mappers with SAME-NAMED files: distinct checkout_ids, no clobber.
    e1 = reg.register_checkout({
        "checkout_id": "ck-1", "template_id": "LGS_SiteA_28350",
        "template_path": "D:/hw/LGS_SiteA_28350.gpkg", "mapper": "HW",
        "source_mode": "full", "master_version": 3})
    e2 = reg.register_checkout({
        "checkout_id": "ck-2", "template_id": "LGS_SiteA_28350",
        "template_path": "D:/js/LGS_SiteA_28350.gpkg", "mapper": "JS",
        "source_mode": "clip", "area_wkt": "POLYGON((0 0,1 0,1 1,0 0))"})
    check(e1["status"] == "out" and e2["status"] == "out",
          "both checkouts registered as out")
    reg2 = checkout.CheckoutRegistry(master)
    check(reg2.get("ck-1")["mapper"] == "HW"
          and reg2.get("ck-2")["mapper"] == "JS",
          "same-named templates coexist under different checkout_ids")
    check(reg2.get("ck-2")["area_wkt"].startswith("POLYGON"),
          "area_wkt persisted")

    # mark_reconciled by checkout_id + mapper backfill on a blank one.
    reg2.register_checkout({"checkout_id": "ck-3", "template_id": "Export1",
                            "mapper": "", "source_mode": "export"})
    reg2.mark_reconciled("ck-3", master_version=7, mapper="HW")
    reg3 = checkout.CheckoutRegistry(master)
    e3 = reg3.get("ck-3")
    check(e3["status"] == "reconciled" and e3["master_version"] == 7,
          "mark_reconciled by checkout_id")
    check(e3["mapper"] == "HW", "blank mapper backfilled at first reconcile")
    reg3.mark_reconciled("ck-3", master_version=8, mapper="JS")
    check(checkout.CheckoutRegistry(master).get("ck-3")["mapper"] == "HW",
          "a set mapper is never overwritten by backfill")

    # Legacy entries coexist; entries() normalizes both kinds.
    reg3.register("LGS_Old_28350", "D:/old.gpkg", "AB")
    rows = checkout.CheckoutRegistry(master).entries()
    check(len(rows) == 4, "entries() lists embedded + legacy")
    by_key = {r["key"]: r for r in rows}
    check(by_key["ck-1"]["base"] == "embedded"
          and by_key["LGS_Old_28350"]["base"] == "sidecar",
          "entries() labels base kind per entry")
    check(by_key["LGS_Old_28350"]["source_mode"] == "legacy",
          "legacy entries default source_mode")
    check(all("key" in r for r in rows), "every row carries its key")


def test_describe_entry(d):
    # Live file whose stamp matches -> ok.
    wc = os.path.join(d, "desc_a.gpkg")
    make_gpkg(wc)
    row_stamp = basestore.write_checkout(wc, {"mapper": "HW"})
    row = checkout.describe_entry({
        "key": "k1", "checkout_id": row_stamp["checkout_id"],
        "template_id": "desc_a", "template_path": wc, "mapper": "HW",
        "source_mode": "full", "base": "embedded",
        "created_utc": "2026-09-04T01:00:00+00:00",
        "last_sync_utc": None, "status": "out"})
    check(row["file_state"] == "ok", "matching stamp -> ok")
    check(row["issued"] == "2026-09-04" and row["last_sync"] == "—",
          "dates shortened, blank sync dashed")

    # Restamped file (new identity at the same path) -> historical entry.
    basestore.write_checkout(wc, {"mapper": "JS"})
    row2 = checkout.describe_entry({
        "checkout_id": row_stamp["checkout_id"], "template_path": wc})
    check(row2["file_state"] == "restamped", "old entry reads restamped")

    # Missing file -> moved; legacy entry (no checkout_id) with a live file -> ok.
    row3 = checkout.describe_entry({
        "checkout_id": "x", "template_path": os.path.join(d, "gone.gpkg")})
    check(row3["file_state"] == "moved", "missing file -> moved")
    row4 = checkout.describe_entry({"template_id": "old", "template_path": wc})
    check(row4["file_state"] == "ok" and row4["source"] == "legacy"
          and row4["base"] == "sidecar", "legacy entry defaults")


def test_migration_status(d):
    lgs_cols = ["UUID"] + list(LGS_META_FIELDS)
    layers = [("1 - FieldNotebook", lgs_cols), ("2 - Linework", lgs_cols),
              ("3 - Overlay", lgs_cols), ("4 - Basemap", lgs_cols)]

    # Unmigrated: canonical tables but no lgs columns.
    bare = os.path.join(d, "LGS_Bare.gpkg")
    make_gpkg(bare, [(n, ["UUID", "Legend"]) for n, _ in layers])
    st = migrate.migration_status(bare)
    check(not st["migrated"], "bare master reads unmigrated")
    check(st["layers"]["1 - FieldNotebook"]["present"], "layers detected")
    check(not st["layers"]["1 - FieldNotebook"]["has_lgs_columns"],
          "missing lgs columns detected")

    # Migrated shape: lgs columns + a migration marker row + master uid.
    done = os.path.join(d, "LGS_Done.gpkg")
    make_gpkg(done, layers)
    con = sqlite3.connect(done)
    con.execute("CREATE TABLE lgs_changelog (fid INTEGER PRIMARY KEY, "
                "master_version INTEGER, kind TEXT, batch_id TEXT, "
                "template_id TEXT, mapper TEXT, timestamp_utc TEXT, "
                "applied TEXT, notes TEXT)")
    con.execute("INSERT INTO lgs_changelog (kind) VALUES ('migration')")
    con.commit()
    con.close()
    basestore.ensure_master_uid(done)
    st2 = migrate.migration_status(done)
    check(st2["migrated"], "migrated master reads migrated")
    check(st2["has_migration_marker"], "migration marker found in gpkg table")
    check(bool(st2["master_uid"]), "master_uid reported")

    # Missing file: error, not crash.
    st3 = migrate.migration_status(os.path.join(d, "nope.gpkg"))
    check(not st3["migrated"] and "error" in st3,
          "missing master -> error dict")


def main():
    with tempfile.TemporaryDirectory() as d:
        for t in (test_checkout_roundtrip, test_base_roundtrip,
                  test_master_uid, test_registry_checkout_ids,
                  test_describe_entry, test_migration_status):
            print(f"- {t.__name__}")
            t(d)
        print("- test_newest_base")
        test_newest_base()
    print(f"\n{_passed} checks passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
