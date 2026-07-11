#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task-path reconcile test (MUST run inside QGIS's Python).

Runs engine.build_plans and engine.apply_plans THROUGH lgs_tasks.run_in_task
(i.e. on a real background task thread) against copies of the bundled
template, and asserts the results match the synchronous engine exactly.
This is the runtime proof that the engine's worker-thread usage is safe:
fresh gpkg-path layers opened inside run(), including the commit path's
startEditing/commitChanges edit session.

Run via the same stdin-exec wrapper as the other *_qgis tests.
"""

import os
import shutil
import sys
import tempfile
import time

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
RECONCILE_DIR = os.path.join(REPO_ROOT, "script_adddata", "reconcile")
for p in (REPO_ROOT, RECONCILE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import engine            # noqa: E402
import migrate           # noqa: E402

from qgis.PyQt.QtCore import QCoreApplication  # noqa: E402
from qgis.core import (QgsFeature, QgsGeometry, QgsPointXY, QgsProject,  # noqa: E402
                       QgsVectorLayer)

from lgs_tasks import run_in_task  # noqa: E402

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


def pump(cond, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def _add_point(gpkg, uuid, x=100.0, y=200.0):
    lyr = QgsVectorLayer(f"{gpkg}|layername={LAYER}", LAYER, "ogr")
    assert lyr.isValid()
    lyr.startEditing()
    feat = QgsFeature(lyr.fields())
    feat.setAttribute(lyr.fields().indexOf("UUID"), uuid)
    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
    lyr.addFeature(feat)
    assert lyr.commitChanges(), lyr.commitErrors()


def _plan_summary(build):
    out = {}
    for plan in build["plans"]:
        s = plan.summary()
        out[plan.layer] = {k: s.get(k, 0) for k in
                           ("inserts", "updates", "deletes", "conflicts")}
    return out


def main():
    template = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")
    if not os.path.exists(template):
        print(f"Template not found: {template}")
        return 1

    tmp = tempfile.mkdtemp(prefix="lgs_taskpath_")
    master = os.path.join(tmp, "master.gpkg")
    working = os.path.join(tmp, "working.gpkg")
    shutil.copy(template, master)
    shutil.copy(template, working)
    print(f"fixtures in {tmp}")

    check(migrate.run_migration(master).get("ok"), "master migrated")
    reg = engine.register_and_snapshot(master, working, mapper="TP")
    check(not reg.get("errors"), "template registered")

    _add_point(working, "TASK-1")
    _add_point(working, "TASK-2", x=150.0)

    ctx = QgsProject.instance().transformContext()

    # --- synchronous reference build (main thread) ---
    sync_build = engine.build_plans(master, working)
    sync_summary = _plan_summary(sync_build)
    plan = next(p for p in sync_build["plans"] if p.layer == LAYER)
    check(sorted(o.uuid for o in plan.clean_inserts) == ["TASK-1", "TASK-2"],
          "sync build sees the two inserts")

    # --- build through a real background task ---
    print("[build via task]")
    out = {}
    run_in_task("taskpath build",
                lambda cb: engine.build_plans(master, working, progress_cb=cb,
                                              transform_context=ctx),
                on_finished=lambda r: out.setdefault("build", r),
                on_error=lambda e, tb: out.setdefault("error", tb))
    check(pump(lambda: out), "task build completed")
    check("error" not in out, f"task build clean ({out.get('error', '')[:200]})")
    task_build = out.get("build") or {}
    check(_plan_summary(task_build) == sync_summary,
          "task-built plans identical to synchronous plans")

    # --- apply through a real background task (worker-thread edit session) ---
    print("[apply via task]")
    out2 = {}
    run_in_task("taskpath apply",
                lambda cb: engine.apply_plans(master, working, task_build,
                                              mapper="TP", progress_cb=cb),
                on_finished=lambda r: out2.setdefault("result", r),
                on_error=lambda e, tb: out2.setdefault("error", tb))
    check(pump(lambda: out2), "task apply completed")
    check("error" not in out2, f"task apply clean ({out2.get('error', '')[:200]})")
    result = out2.get("result") or {}
    check(result.get("ok") is True, "apply ok")
    check(result.get("totals", {}).get("inserted") == 2, "2 inserts applied")

    # --- verify the master really has the features ---
    mlyr = QgsVectorLayer(f"{master}|layername={LAYER}", LAYER, "ogr")
    uidx = mlyr.fields().indexOf("UUID")
    uuids = {str(f.attribute(uidx)) for f in mlyr.getFeatures()}
    check({"TASK-1", "TASK-2"} <= uuids, "master contains both features")

    # --- idempotency through the task path ---
    out3 = {}
    run_in_task("taskpath rebuild",
                lambda cb: engine.build_plans(master, working, progress_cb=cb,
                                              transform_context=ctx),
                on_finished=lambda r: out3.setdefault("build", r),
                on_error=lambda e, tb: out3.setdefault("error", tb))
    check(pump(lambda: out3), "rebuild completed")
    rb = out3.get("build") or {"plans": []}
    quiet = all(not (p.clean_inserts or p.clean_updates or p.clean_deletes
                     or p.conflicts) for p in rb["plans"])
    check(quiet, "re-sync after task apply is a no-op")

    print(f"\n{_passed} checks passed, {_failed} failed   (fixtures: {tmp})")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
