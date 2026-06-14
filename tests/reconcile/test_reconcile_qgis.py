#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
End-to-end reconcile test that MUST run inside QGIS (needs the QGIS Python API).

It builds fixtures from a COPY of Template/LGS_MappingTemplate.gpkg (never the
real data), runs the migration, then drives the full insert -> update -> delete
-> re-sync cycle through the engine and asserts the master ends up correct —
including the headline "re-sync an edited template without losing edits".

How to run (QGIS Python console):
    from qgis.utils import iface
    exec(open(r"<repo>/tests/reconcile/test_reconcile_qgis.py").read())

or, if the plugin is importable as a package:
    from LinearGeoscienceMappingTools.tests.reconcile import test_reconcile_qgis
    test_reconcile_qgis.main()
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

# Engine + migrate resolve their internal deps via fallback imports (needs both
# REPO_ROOT and RECONCILE_DIR on sys.path, set above).
import engine            # noqa: E402
import migrate           # noqa: E402
import checkout          # noqa: E402

from qgis.core import (QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY)  # noqa: E402

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


def _layer(gpkg, name):
    lyr = QgsVectorLayer(f"{gpkg}|layername={name}", name, "ogr")
    assert lyr.isValid(), f"could not open {name} in {gpkg}"
    return lyr


def _add_point(gpkg, uuid, dip, x=100.0, y=200.0):
    lyr = _layer(gpkg, LAYER)
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
    lyr = _layer(gpkg, LAYER)
    uidx = lyr.fields().indexOf("UUID")
    didx = lyr.fields().indexOf("Dip")
    lyr.startEditing()
    for f in lyr.getFeatures():
        if str(f.attribute(uidx)) == uuid:
            lyr.changeAttributeValue(f.id(), didx, dip)
    assert lyr.commitChanges(), lyr.commitErrors()


def _delete(gpkg, uuid):
    lyr = _layer(gpkg, LAYER)
    uidx = lyr.fields().indexOf("UUID")
    lyr.startEditing()
    for f in lyr.getFeatures():
        if str(f.attribute(uidx)) == uuid:
            lyr.deleteFeature(f.id())
    assert lyr.commitChanges(), lyr.commitErrors()


def _master_by_uuid(gpkg):
    lyr = _layer(gpkg, LAYER)
    uidx = lyr.fields().indexOf("UUID")
    out = {}
    for f in lyr.getFeatures():
        out[str(f.attribute(uidx))] = f
    return lyr, out


def main():
    template = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")
    if not os.path.exists(template):
        print(f"Template not found: {template}")
        return 1

    tmp = tempfile.mkdtemp(prefix="lgs_reconcile_")
    master = os.path.join(tmp, "LGS_Master_28350.gpkg")
    working = os.path.join(tmp, "LGS_SiteA_28350.gpkg")
    shutil.copy(template, master)
    shutil.copy(template, working)
    print(f"fixtures in {tmp}")

    # --- migration ---
    print("\n[migrate]")
    report = migrate.run_migration(master)
    check(report.get("ok"), "migration ok")
    mlyr = _layer(master, LAYER)
    names = {f.name() for f in mlyr.fields()}
    check({"lgs_version", "lgs_author", "lgs_feature_hash"} <= names,
          "lgs_* columns present after migrate")
    check(all(v in ("ok", "patched") for v in report["uuid_defaults"].values()),
          f"UUID defaults verified: {report['uuid_defaults']}")

    # --- register handout (blank template -> empty base) ---
    print("\n[register]")
    reg = engine.register_and_snapshot(master, working, mapper="HW")
    check(not reg.get("errors"), "register_and_snapshot ok")
    tid = checkout.template_id_from_path(working)
    check(checkout.load_base(master, tid) is not None, "base snapshot stored")

    # --- first sync: two inserts ---
    print("\n[insert]")
    _add_point(working, "U1", 10)
    _add_point(working, "U2", 20)
    build = engine.build_plans(master, working)
    plan = next(p for p in build["plans"] if p.layer == LAYER)
    check(sorted(o.uuid for o in plan.clean_inserts) == ["U1", "U2"],
          "two clean inserts detected")
    res = engine.apply_plans(master, working, build, mapper="HW")
    check(res["ok"] and res["totals"]["inserted"] == 2, "applied 2 inserts")
    _, mfeat = _master_by_uuid(master)
    check(set(mfeat) >= {"U1", "U2"}, "master has U1, U2")
    check(str(mfeat["U1"]["lgs_version"]) == "1", "U1 lgs_version=1")
    check(str(mfeat["U1"]["lgs_author"]) == "HW", "U1 lgs_author=HW")

    # --- re-sync after EDIT: the data-loss fix ---
    print("\n[update / re-sync without loss]")
    _set_dip(working, "U1", 42)
    build = engine.build_plans(master, working)
    plan = next(p for p in build["plans"] if p.layer == LAYER)
    check([o.uuid for o in plan.clean_updates] == ["U1"],
          "edited feature classified as update (not skipped)")
    res = engine.apply_plans(master, working, build, mapper="HW")
    check(res["ok"] and res["totals"]["updated"] == 1, "applied 1 update")
    _, mfeat = _master_by_uuid(master)
    check(str(mfeat["U1"]["Dip"]) == "42", "U1 Dip updated to 42")
    check(str(mfeat["U1"]["lgs_version"]) == "2", "U1 lgs_version bumped to 2")

    # --- delete propagation ---
    print("\n[delete]")
    _delete(working, "U2")
    build = engine.build_plans(master, working)
    plan = next(p for p in build["plans"] if p.layer == LAYER)
    check([o.uuid for o in plan.clean_deletes] == ["U2"], "delete detected")
    res = engine.apply_plans(master, working, build, mapper="HW")
    check(res["ok"] and res["totals"]["deleted"] == 1, "applied 1 delete")
    _, mfeat = _master_by_uuid(master)
    check("U2" not in mfeat, "U2 removed from master")

    # --- unedited re-sync is a no-op ---
    print("\n[idempotency]")
    build = engine.build_plans(master, working)
    plan = next(p for p in build["plans"] if p.layer == LAYER)
    check(not plan.has_applicable_changes(), "unedited re-sync is a no-op")

    print(f"\n{_passed} checks passed, {_failed} failed   (fixtures: {tmp})")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
else:
    # When exec()'d in the QGIS console, run immediately.
    main()
