#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
End-to-end reconcile test that MUST run inside QGIS (needs the QGIS Python API).

It builds fixtures from a COPY of Template/LGS_MappingTemplate.gpkg (never the
real data), runs the migration, then drives the full lifecycle through the
engine and asserts the master ends up correct:

  Phase 1  insert -> update (re-sync without loss) -> delete -> idempotent no-op
  Phase 2  update/update conflict (resolved), disjoint auto-merge,
           blanking protection, optimistic version guard
  Phase 3  split (1->2) and merge (2->1) with lineage stamps + attr-carry
  Phase 4  delete tombstones, in-gpkg lgs_changelog table

How to run (QGIS Python console):
    from qgis.utils import iface
    exec(open(r"<repo>/tests/reconcile/test_reconcile_qgis.py").read())
"""

import os
import sys
import shutil
import sqlite3
import tempfile

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
RECONCILE_DIR = os.path.join(REPO_ROOT, "script_adddata", "reconcile")
for p in (REPO_ROOT, RECONCILE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

# Engine + helpers resolve their internal deps via fallback imports (needs both
# REPO_ROOT and RECONCILE_DIR on sys.path, set above).
import engine            # noqa: E402
import migrate           # noqa: E402
import checkout          # noqa: E402
import reconcile         # noqa: E402
import tombstones        # noqa: E402

from qgis.core import (QgsVectorLayer, QgsFeature, QgsGeometry,  # noqa: E402
                       QgsPointXY, QgsWkbTypes)

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


def _set_field(gpkg, uuid, field, value, name=LAYER):
    lyr = _layer(gpkg, name)
    uidx = lyr.fields().indexOf("UUID")
    fidx = lyr.fields().indexOf(field)
    if fidx == -1:
        return False
    lyr.startEditing()
    for f in lyr.getFeatures():
        if str(f.attribute(uidx)) == uuid:
            lyr.changeAttributeValue(f.id(), fidx, value)
    assert lyr.commitChanges(), lyr.commitErrors()
    return True


def _set_dip(gpkg, uuid, dip):
    _set_field(gpkg, uuid, "Dip", dip)


def _delete(gpkg, uuid, name=LAYER):
    lyr = _layer(gpkg, name)
    uidx = lyr.fields().indexOf("UUID")
    lyr.startEditing()
    for f in lyr.getFeatures():
        if str(f.attribute(uidx)) == uuid:
            lyr.deleteFeature(f.id())
    assert lyr.commitChanges(), lyr.commitErrors()


def _field_exists(gpkg, field, name=LAYER):
    return _layer(gpkg, name).fields().indexOf(field) != -1


def _master_by_uuid(gpkg, name=LAYER):
    lyr = _layer(gpkg, name)
    uidx = lyr.fields().indexOf("UUID")
    out = {}
    for f in lyr.getFeatures():
        out[str(f.attribute(uidx))] = f
    return lyr, out


def _find_polygon_layer(gpkg):
    for name in ["2 - Overlay", "3 - Linework", "4 - Basemap"]:
        lyr = QgsVectorLayer(f"{gpkg}|layername={name}", name, "ogr")
        if lyr.isValid() and QgsWkbTypes.geometryType(lyr.wkbType()) == \
                QgsWkbTypes.PolygonGeometry:
            return name
    return None


def _add_polygon(gpkg, name, uuid, wkt):
    lyr = _layer(gpkg, name)
    lyr.startEditing()
    feat = QgsFeature(lyr.fields())
    feat.setAttribute(lyr.fields().indexOf("UUID"), uuid)
    feat.setGeometry(QgsGeometry.fromWkt(wkt))
    lyr.addFeature(feat)
    assert lyr.commitChanges(), lyr.commitErrors()


def _reconcile(master, working, mapper="HW", resolve=None, accept_lineage=True):
    """Build + apply in one shot, optionally stamping conflict resolutions.

    resolve: dict "<layer>\\x1f<uuid>" -> RES_* applied before commit.
    """
    build = engine.build_plans(master, working)
    if resolve:
        for plan in build["plans"]:
            for c in plan.conflicts:
                k = f"{plan.layer}\x1f{c.uuid}"
                if k in resolve:
                    c.resolution = resolve[k]
    if accept_lineage:
        for plan in build["plans"]:
            for g in list(plan.splits) + list(plan.merges):
                g.accepted = True
    return build, engine.apply_plans(master, working, build, mapper=mapper)


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
    build, res = _reconcile(master, working)
    plan = next(p for p in build["plans"] if p.layer == LAYER)
    check(sorted(o.uuid for o in plan.clean_inserts) == ["U1", "U2"],
          "two clean inserts detected")
    check(res["ok"] and res["totals"]["inserted"] == 2, "applied 2 inserts")
    _, mfeat = _master_by_uuid(master)
    check(set(mfeat) >= {"U1", "U2"}, "master has U1, U2")
    check(str(mfeat["U1"]["lgs_version"]) == "1", "U1 lgs_version=1")
    check(str(mfeat["U1"]["lgs_author"]) == "HW", "U1 lgs_author=HW")

    # --- re-sync after EDIT: the data-loss fix ---
    print("\n[update / re-sync without loss]")
    _set_dip(working, "U1", 42)
    build, res = _reconcile(master, working)
    plan = next(p for p in build["plans"] if p.layer == LAYER)
    check([o.uuid for o in plan.clean_updates] == ["U1"],
          "edited feature classified as update (not skipped)")
    check(res["ok"] and res["totals"]["updated"] == 1, "applied 1 update")
    _, mfeat = _master_by_uuid(master)
    check(str(mfeat["U1"]["Dip"]) == "42", "U1 Dip updated to 42")
    check(str(mfeat["U1"]["lgs_version"]) == "2", "U1 lgs_version bumped to 2")

    # --- delete propagation + tombstone ---
    print("\n[delete + tombstone]")
    _delete(working, "U2")
    build, res = _reconcile(master, working)
    check(res["ok"] and res["totals"]["deleted"] == 1, "applied 1 delete")
    _, mfeat = _master_by_uuid(master)
    check("U2" not in mfeat, "U2 removed from master")
    tss = tombstones.load_tombstones(master)
    check(any(t["uuid"] == "U2" for t in tss), "U2 recorded as a tombstone")

    # --- unedited re-sync is a no-op ---
    print("\n[idempotency]")
    build = engine.build_plans(master, working)
    plan = next(p for p in build["plans"] if p.layer == LAYER)
    check(not plan.has_applicable_changes(), "unedited re-sync is a no-op")

    # --- update/update conflict, resolved take-working ---
    print("\n[conflict update/update]")
    _set_dip(master, "U1", 100)         # master edit (direct)
    _set_dip(working, "U1", 55)         # working edit (same field) -> clash
    build = engine.build_plans(master, working)
    plan = next(p for p in build["plans"] if p.layer == LAYER)
    conf = [c for c in plan.conflicts if c.uuid == "U1"]
    check(len(conf) == 1 and conf[0].type == reconcile.CONFLICT_UPDATE_UPDATE,
          "U1 edited on both sides -> update/update conflict")
    conf[0].resolution = reconcile.RES_TAKE_WORKING
    res = engine.apply_plans(master, working, build, mapper="HW")
    check(res["ok"], "apply with a resolved conflict ok")
    _, mfeat = _master_by_uuid(master)
    check(str(mfeat["U1"]["Dip"]) == "55", "take_working applied (Dip=55)")

    # --- disjoint auto-merge + blanking protection ---
    GEO = "Geologist"
    if _field_exists(master, GEO):
        print("\n[auto-merge disjoint + blanking guard]")
        _set_dip(working, "U1", 70)             # working edits Dip
        _set_field(master, "U1", GEO, "AB")     # master edits Geologist
        build = engine.build_plans(master, working)
        plan = next(p for p in build["plans"] if p.layer == LAYER)
        check(any(o.uuid == "U1" for o in plan.auto_merges),
              "disjoint edits -> auto-merge")
        engine.apply_plans(master, working, build, mapper="HW")
        _, mfeat = _master_by_uuid(master)
        check(str(mfeat["U1"]["Dip"]) == "70", "auto-merge kept working Dip")
        check(str(mfeat["U1"][GEO]) == "AB", "auto-merge kept master Geologist")

        # working never set Geologist -> a re-sync must NOT silently wipe it.
        build = engine.build_plans(master, working)
        plan = next(p for p in build["plans"] if p.layer == LAYER)
        check(any(c.uuid == "U1" and c.type == reconcile.CONFLICT_BLANKING
                  for c in plan.conflicts),
              "blank template would wipe Geologist -> held as blanking conflict")
        # Mapper fills it in -> converges.
        _set_field(working, "U1", GEO, "AB")
        build = engine.build_plans(master, working)
        plan = next(p for p in build["plans"] if p.layer == LAYER)
        check(not any(c.uuid == "U1" for c in plan.conflicts),
              "filling the field clears the blanking conflict")
    else:
        print("\n[auto-merge] skipped: no Geologist field")

    # --- optimistic version guard ---
    print("\n[version guard]")
    build_stale = engine.build_plans(master, working)
    _add_point(working, "UZ", 5)            # someone else reconciles meanwhile
    _, res = _reconcile(master, working)
    check(res["ok"], "intervening reconcile applied")
    res_stale = engine.apply_plans(master, working, build_stale, mapper="HW")
    check(res_stale.get("aborted") and not res_stale.get("ok"),
          "stale plan aborts (master moved since preview)")

    # --- in-gpkg changelog table (Phase 4) ---
    print("\n[changelog table]")
    try:
        con = sqlite3.connect(master)
        n = con.execute("SELECT COUNT(*) FROM lgs_changelog").fetchone()[0]
        con.close()
        check(n >= 1, f"lgs_changelog table mirrored in the gpkg ({n} rows)")
    except Exception as exc:
        check(False, f"lgs_changelog table present ({exc})")

    # --- split / merge lineage (polygons) ---
    print("\n[split / merge]")
    poly = _find_polygon_layer(master)
    if poly:
        try:
            _run_lineage(master, working, poly)
        except Exception as exc:
            check(False, f"lineage section raised: {exc}")
    else:
        print("  skipped: no polygon layer found")

    print(f"\n{_passed} checks passed, {_failed} failed   (fixtures: {tmp})")
    return 1 if _failed else 0


def _run_lineage(master, working, poly):
    # SPLIT: a parent square reconciled into master, then split into two halves.
    _add_polygon(working, poly, "PP",
                 "POLYGON((0 0,0 10,10 10,10 0,0 0))")
    _set_field(working, "PP", "UUID", "PP", name=poly)  # ensure UUID set
    _reconcile(master, working)                          # master now has PP
    _delete(working, "PP", name=poly)
    _add_polygon(working, poly, "C1", "POLYGON((0 0,0 10,5 10,5 0,0 0))")
    _add_polygon(working, poly, "C2", "POLYGON((5 0,5 10,10 10,10 0,5 0))")
    build = engine.build_plans(master, working)
    plan = next(p for p in build["plans"] if p.layer == poly)
    check(any(g.parent_uuid == "PP" and set(g.child_uuids) == {"C1", "C2"}
              for g in plan.splits), "split PP -> C1,C2 detected")
    _, res = _reconcile(master, working)
    _, mp = _master_by_uuid(master, name=poly)
    check("PP" not in mp and {"C1", "C2"} <= set(mp), "split applied to master")
    pidx = _layer(master, poly).fields().indexOf("lgs_parent_uuid")
    if pidx != -1:
        check(str(mp["C1"]["lgs_parent_uuid"]) == "PP",
              "child carries lgs_parent_uuid")

    # MERGE: two parent halves reconciled in, then merged into one survivor.
    _add_polygon(working, poly, "QA", "POLYGON((20 0,20 10,25 10,25 0,20 0))")
    _add_polygon(working, poly, "QB", "POLYGON((25 0,25 10,30 10,30 0,25 0))")
    _reconcile(master, working)                          # master has QA, QB
    _delete(working, "QA", name=poly)
    _delete(working, "QB", name=poly)
    _add_polygon(working, poly, "SV", "POLYGON((20 0,20 10,30 10,30 0,20 0))")
    build = engine.build_plans(master, working)
    plan = next(p for p in build["plans"] if p.layer == poly)
    check(any(g.survivor_uuid == "SV" and set(g.parent_uuids) == {"QA", "QB"}
              for g in plan.merges), "merge QA,QB -> SV detected")
    _reconcile(master, working)
    _, mp = _master_by_uuid(master, name=poly)
    check("SV" in mp and "QA" not in mp and "QB" not in mp,
          "merge applied to master")
    midx = _layer(master, poly).fields().indexOf("lgs_merged_from")
    if midx != -1:
        check("QA" in str(mp["SV"]["lgs_merged_from"]),
              "survivor carries lgs_merged_from")


if __name__ == "__main__":
    sys.exit(main())
else:
    # When exec()'d in the QGIS console, run immediately.
    main()
