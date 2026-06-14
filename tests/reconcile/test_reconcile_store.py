#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Headless tests for the pure JSON sidecar stores (no QGIS):
base snapshot store, checkout registry, reconcile changelog.

Run:  python tests/reconcile/test_reconcile_store.py
"""

import os
import sys
import tempfile

RECONCILE_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "script_adddata", "reconcile"))
sys.path.insert(0, RECONCILE_DIR)

import snapshot          # noqa: E402
import checkout          # noqa: E402
import changelog         # noqa: E402
import locking           # noqa: E402
import tombstones        # noqa: E402
import reconcile as rc   # noqa: E402
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


def test_base_roundtrip(master):
    payloads = {"a": payload("a", Dip=10), "b": payload("b", Dip=20)}
    snap = snapshot_from_payloads("1 - FieldNotebook", "UUID", payloads)
    checkout.save_base(master, "LGS_SiteA_28350",
                       {"1 - FieldNotebook": snap}, master_version=0, mapper="HW")

    loaded = checkout.load_base(master, "LGS_SiteA_28350")
    check(loaded is not None, "base loads back")
    fps = loaded["layers"]["1 - FieldNotebook"]
    check(set(fps.keys()) == {"a", "b"}, "base uuids round-trip")
    check(fps["a"].equals(payloads["a"].fingerprint()),
          "base fingerprint matches original payload")
    check(loaded["mapper"] == "HW", "mapper persisted")
    # Per-field hashes survive the JSON round-trip (needed for field merge).
    check(fps["a"].field_hashes is not None and "Dip" in fps["a"].field_hashes,
          "field_hashes persisted in base snapshot")


def test_locking(master):
    lk = locking.ReconcileLock(master, mapper="HW", stale_seconds=10)
    ok, holder = lk.acquire()
    check(ok and holder is None, "first acquire succeeds")
    check(lk.read()["mapper"] == "HW", "lock records mapper")

    lk2 = locking.ReconcileLock(master, mapper="JS", stale_seconds=10)
    ok2, holder2 = lk2.acquire()
    check(not ok2 and holder2 and holder2["mapper"] == "HW",
          "second acquire blocked by a live lock")
    ok3, _ = lk2.acquire(force=True)
    check(ok3, "force overrides the lock")
    lk2.release()
    check(lk.read() is None, "release removes the lock")

    # A lock that is already stale (stale_seconds=0) can be taken over.
    locking.ReconcileLock(master, mapper="HW", stale_seconds=0).acquire()
    ok4, _ = locking.ReconcileLock(master, mapper="JS", stale_seconds=0).acquire()
    check(ok4, "stale lock is overridable")
    locking.ReconcileLock(master).release()

    # Missing base -> None (legacy first sync signal).
    check(checkout.load_base(master, "NoSuchTemplate") is None,
          "missing base returns None")
    # load_base_layer: None when no base, {} when layer absent in an existing base
    check(checkout.load_base_layer(master, "NoSuchTemplate", "x") is None,
          "load_base_layer None when no base")
    check(checkout.load_base_layer(master, "LGS_SiteA_28350", "2 - Overlay") == {},
          "load_base_layer empty dict when layer absent")


def test_registry(master):
    reg = checkout.CheckoutRegistry(master)
    reg.register("LGS_SiteA_28350", "D:/field/LGS_SiteA_28350.gpkg", "HW",
                 master_version=0)
    check(reg.get("LGS_SiteA_28350")["status"] == "out", "registered as out")

    # Reload from disk -> persisted.
    reg2 = checkout.CheckoutRegistry(master)
    check("LGS_SiteA_28350" in reg2.list(), "registry persisted")
    reg2.mark_reconciled("LGS_SiteA_28350", master_version=1)
    reg3 = checkout.CheckoutRegistry(master)
    check(reg3.get("LGS_SiteA_28350")["status"] == "reconciled",
          "mark_reconciled persisted")
    check(reg3.get("LGS_SiteA_28350")["last_sync_utc"] is not None,
          "last_sync_utc set")


def test_changelog(master):
    log = changelog.ReconcileChangelog(master)
    check(log.current_version() == 0, "fresh changelog at version 0")
    log.log_migration({"layers_migrated": 4})
    check(log.current_version() == 1, "migration -> version 1")

    plan = rc.classify(
        "1 - FieldNotebook", "UUID",
        {}, {"x": payload("x", Dip=5)}, {})
    log.log_reconcile("batch_test", "LGS_SiteA_28350", "HW", [plan],
                      applied={"inserts": 1})
    check(log.current_version() == 2, "reconcile -> version 2")

    log2 = changelog.ReconcileChangelog(master)
    check(log2.current_version() == 2, "changelog persisted across reload")
    kinds = [e["kind"] for e in log2.entries()]
    check(kinds == ["migration", "reconcile"], "entry kinds in order")
    check(log2.entries()[1]["layers"][0]["inserted_uuids"] == ["x"],
          "reconcile entry records inserted uuids")


def test_tombstones(master):
    recs = [
        {"uuid": "d1", "layer": "L", "attrs": {"Rock": "granite"},
         "wkb_hex": None, "deleted_utc": "2026-01-01T00:00:00+00:00"},
        {"uuid": "d2", "layer": "L", "attrs": {},
         "wkb_hex": None, "deleted_utc": "2026-06-14T00:00:00+00:00"},
    ]
    n = tombstones.append_tombstones(master, recs)
    check(n == 2, "two tombstones appended")
    check(tombstones.count_tombstones(master) == 2, "count is 2")
    loaded = tombstones.load_tombstones(master)
    check(loaded[0]["uuid"] == "d1", "tombstone attrs/uuid persisted")

    # Purge anything deleted before March 2026 -> drops d1, keeps d2.
    removed = tombstones.purge_tombstones(
        master, before_utc="2026-03-01T00:00:00+00:00")
    check(removed == 1, "purge removed the old tombstone")
    check(tombstones.count_tombstones(master) == 1, "one tombstone remains")
    check(tombstones.load_tombstones(master)[0]["uuid"] == "d2",
          "the recent tombstone survives the purge")


def main():
    with tempfile.TemporaryDirectory() as d:
        master = os.path.join(d, "LGS_Master_28350.gpkg")
        for t in (test_base_roundtrip, test_registry, test_changelog,
                  test_locking, test_tombstones):
            print(f"- {t.__name__}")
            t(master)
    print(f"\n{_passed} checks passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
