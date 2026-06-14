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


def main():
    with tempfile.TemporaryDirectory() as d:
        master = os.path.join(d, "LGS_Master_28350.gpkg")
        for t in (test_base_roundtrip, test_registry, test_changelog):
            print(f"- {t.__name__}")
            t(master)
    print(f"\n{_passed} checks passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
