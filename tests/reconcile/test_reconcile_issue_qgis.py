#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QGIS-bound tests for the Issue Field Copy tool (issue.py) and the embedded
checkout lifecycle it produces.

Covers: full / blank / clip issue modes, the hash-consistency canary
(embedded base == a fresh capture of the master), the unmigrated-master
refusal, no-overwrite, and the end-to-end field round trip on an issued
copy: edit -> reconcile (embedded base) -> base refresh -> edit -> re-sync.

Run in the QGIS console:
    exec(open(r"<repo>/tests/reconcile/test_reconcile_issue_qgis.py").read())
or headless:
    python-qgis-ltr.bat run_headless_qgis.py test_reconcile_issue_qgis.py
"""

import os
import sys
import shutil
import tempfile

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
RECONCILE_DIR = os.path.join(REPO_ROOT, "script_adddata", "reconcile")
for p in (REPO_ROOT, RECONCILE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import engine            # noqa: E402
import migrate           # noqa: E402
import checkout          # noqa: E402
import basestore         # noqa: E402
import issue             # noqa: E402
from snapshot import capture_layer  # noqa: E402

from qgis.core import (QgsVectorLayer, QgsFeature, QgsGeometry,  # noqa: E402
                       QgsPointXY)

LAYER = "1 - FieldNotebook"
_passed = 0
_failed = 0


def check(cond, label):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"  FAIL {label}")


def _layer(gpkg, name=LAYER):
    lyr = QgsVectorLayer(f"{gpkg}|layername={name}", name, "ogr")
    assert lyr.isValid(), f"could not open {name} in {gpkg}"
    return lyr


def _add_point(gpkg, uuid, dip, x=100.0, y=200.0):
    lyr = _layer(gpkg)
    lyr.startEditing()
    feat = QgsFeature(lyr.fields())
    feat.setAttribute(lyr.fields().indexOf("UUID"), uuid)
    didx = lyr.fields().indexOf("Dip")
    if didx != -1:
        feat.setAttribute(didx, dip)
    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
    lyr.addFeature(feat)
    assert lyr.commitChanges(), lyr.commitErrors()


def _set_dip(gpkg, uuid, dip):
    lyr = _layer(gpkg)
    uidx = lyr.fields().indexOf("UUID")
    didx = lyr.fields().indexOf("Dip")
    lyr.startEditing()
    for f in lyr.getFeatures():
        if str(f.attribute(uidx)) == uuid:
            lyr.changeAttributeValue(f.id(), didx, dip)
    assert lyr.commitChanges(), lyr.commitErrors()


def _delete(gpkg, uuid):
    lyr = _layer(gpkg)
    uidx = lyr.fields().indexOf("UUID")
    lyr.startEditing()
    for f in lyr.getFeatures():
        if str(f.attribute(uidx)) == uuid:
            lyr.deleteFeature(f.id())
    assert lyr.commitChanges(), lyr.commitErrors()


def _uuids(gpkg, name=LAYER):
    lyr = _layer(gpkg, name)
    uidx = lyr.fields().indexOf("UUID")
    return {str(f.attribute(uidx)) for f in lyr.getFeatures()}


def main():
    template = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")
    if not os.path.exists(template):
        print(f"Template not found: {template}")
        return 1

    tmp = tempfile.mkdtemp(prefix="lgs_issue_")
    master = os.path.join(tmp, "LGS_Master_28350.gpkg")
    shutil.copy(template, master)
    print(f"fixtures in {tmp}")

    # Three master features at known spots (M2/M3 inside the clip AOI below).
    print("\n[fixture]")
    unmigrated_dest = os.path.join(tmp, "too_early.gpkg")
    res = issue.issue_copy(master, unmigrated_dest, mode=issue.MODE_FULL)
    check(not res["ok"] and not os.path.exists(unmigrated_dest),
          "unmigrated master refused (and no partial copy left)")

    report = migrate.run_migration(master)
    check(report.get("ok"), "master migrated")
    _add_point(master, "M1", 10, x=0.0, y=0.0)
    _add_point(master, "M2", 20, x=100.0, y=100.0)
    _add_point(master, "M3", 30, x=110.0, y=110.0)

    # --- full copy ---
    print("\n[issue full]")
    full = os.path.join(tmp, "handout_full.gpkg")
    res = issue.issue_copy(master, full, mode=issue.MODE_FULL, mapper="HW")
    check(res["ok"], f"full issue ok ({res['errors']})")
    check(res["feature_counts"].get(LAYER) == 3, "3 features snapshotted")
    check(_uuids(full) == {"M1", "M2", "M3"}, "copy holds all master features")
    ck = basestore.read_checkout(full)
    check(ck and ck["source_mode"] == "full" and ck["mapper"] == "HW",
          "checkout stamp records mode + mapper")
    check(ck["master_id"] == basestore.read_master_uid(master),
          "stamp paired to the master uid")
    entry = checkout.CheckoutRegistry(master).get(res["checkout_id"])
    check(entry and entry["status"] == "out", "registered as out")

    # Hash-consistency canary: the embedded base must equal a fresh capture
    # of the master (the fingerprints came through capture->sqlite->load).
    emb = basestore.read_base(full)["layers"][LAYER]
    payloads, _ = capture_layer(_layer(master), uuid_field="UUID")
    fresh = {u: p.fingerprint() for u, p in payloads.items()}
    check(set(emb) == set(fresh), "embedded base uuids == master capture")
    check(all(emb[u].equals(fresh[u]) and
              emb[u].field_hashes == fresh[u].field_hashes
              for u in fresh),
          "embedded fingerprints identical to a fresh master capture")

    check(not issue.issue_copy(master, full, mode=issue.MODE_FULL)["ok"],
          "existing destination refused")

    # --- blank copy ---
    print("\n[issue blank]")
    blank = os.path.join(tmp, "handout_blank.gpkg")
    res = issue.issue_copy(master, blank, mode=issue.MODE_BLANK, mapper="JS")
    check(res["ok"], f"blank issue ok ({res['errors']})")
    check(_uuids(blank) == set(), "blank copy has no features")
    check(basestore.read_base(blank)["layers"].get(LAYER) == {},
          "blank base recorded as empty (not absent)")
    lyr = _layer(blank)
    check(lyr.fields().indexOf("UUID") != -1 and
          lyr.fields().indexOf("lgs_version") != -1,
          "blank copy keeps the schema (UUID + lgs_* columns)")

    # --- clipped copy ---
    print("\n[issue clip]")
    clip = os.path.join(tmp, "handout_clip.gpkg")
    aoi = "POLYGON((50 50, 150 50, 150 150, 50 150, 50 50))"
    res = issue.issue_copy(master, clip, mode=issue.MODE_CLIP, mapper="AB",
                           area_wkt=aoi)
    check(res["ok"], f"clip issue ok ({res['errors']})")
    check(_uuids(clip) == {"M2", "M3"}, "clip keeps only intersecting features")
    ck = basestore.read_checkout(clip)
    check(ck and ck["area_wkt"].startswith("POLYGON"), "AOI recorded in stamp")
    check(set(basestore.read_base(clip)["layers"][LAYER]) == {"M2", "M3"},
          "clip base covers exactly the clipped features")
    check(not issue.issue_copy(master, os.path.join(tmp, "x.gpkg"),
                               mode=issue.MODE_CLIP)["ok"],
          "clip without an AOI refused")

    # --- the field round trip on an issued copy ---
    print("\n[round trip]")
    _add_point(full, "F1", 40, x=5.0, y=5.0)   # mapper adds
    _set_dip(full, "M1", 11)                    # mapper edits
    _delete(full, "M2")                         # mapper deletes
    build = engine.build_plans(master, full)
    check(build["base_source"] == "embedded", "sync reads the embedded base")
    plan = next(p for p in build["plans"] if p.layer == LAYER)
    check([o.uuid for o in plan.clean_inserts] == ["F1"], "add detected")
    check([o.uuid for o in plan.clean_updates] == ["M1"], "edit detected")
    check([o.uuid for o in plan.clean_deletes] == ["M2"],
          "delete detected (impossible without the issued base)")
    res = engine.apply_plans(master, full, build, mapper="HW")
    check(res["ok"] and res["totals"] == {"inserted": 1, "updated": 1,
                                          "deleted": 1}, "sync applied")
    check(res.get("embedded_base_refreshed") is True, "embedded base refreshed")
    check(_uuids(master) == {"M1", "M3", "F1"}, "master reflects the sync")

    # Same tablet keeps mapping: only NEW work syncs next time.
    _set_dip(full, "F1", 41)
    build = engine.build_plans(master, full)
    plan = next(p for p in build["plans"] if p.layer == LAYER)
    check([o.uuid for o in plan.clean_updates] == ["F1"]
          and not plan.clean_inserts and not plan.clean_deletes,
          "second sync sees only the new edit (no re-import, no phantom ops)")
    res = engine.apply_plans(master, full, build, mapper="HW")
    check(res["ok"] and res["totals"]["updated"] == 1, "second sync applied")
    entry = checkout.CheckoutRegistry(master).get(
        basestore.read_checkout(full)["checkout_id"])
    check(entry and entry["status"] == "reconciled",
          "registry marks the checkout reconciled")

    print(f"\n{_passed} checks passed, {_failed} failed   (fixtures: {tmp})")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
else:
    main()
