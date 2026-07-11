#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless self-test for lgs_tasks (MUST run inside QGIS's Python).

Covers the three run_in_task outcomes (success / error / cancel) and the
two ChunkRunner outcomes (finish with return value / cancel running the
generator's finally block).

How to run (either launcher, from the repo root):
    C:\\OSGeo4W\\bin\\python-qgis-ltr.bat -  <<'EOF'
    from qgis.core import QgsApplication
    app = QgsApplication([], False); app.initQgis()
    path = r"<repo>\\tests\\test_lgs_tasks_qgis.py"
    exec(compile(open(path, encoding="utf-8").read(), path, "exec"),
         {"__file__": path, "__name__": "__main__"})
    app.exitQgis()
    EOF
"""

import os
import sys
import time

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from qgis.PyQt.QtCore import QCoreApplication

from lgs_tasks import ChunkRunner, run_in_task

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


def pump(cond, timeout=30):
    """Process events until cond() or timeout."""
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


# ---- run_in_task: success ------------------------------------------------
print("[run_in_task success]")
out = {}


def work_ok(progress_cb):
    for i in range(5):
        progress_cb(i * 20, f"step {i}")
    return 42


run_in_task("lgs-test-ok", work_ok,
            on_finished=lambda r: out.setdefault("result", r),
            on_error=lambda e, tb: out.setdefault("error", e),
            on_cancelled=lambda: out.setdefault("cancelled", True))
check(pump(lambda: out), "task completed")
check(out.get("result") == 42, "on_finished received the return value")
check("error" not in out and "cancelled" not in out, "no error/cancel callback")

# ---- run_in_task: error --------------------------------------------------
print("[run_in_task error]")
out = {}


def work_boom(progress_cb):
    progress_cb(10)
    raise ValueError("boom")


run_in_task("lgs-test-error", work_boom,
            on_finished=lambda r: out.setdefault("result", r),
            on_error=lambda e, tb: out.update(error=e, tb=tb),
            on_cancelled=lambda: out.setdefault("cancelled", True))
check(pump(lambda: out), "task completed")
check(isinstance(out.get("error"), ValueError), "on_error received the exception")
check("boom" in out.get("tb", ""), "traceback string carried")
check("result" not in out and "cancelled" not in out, "no success/cancel callback")

# ---- run_in_task: cancel -------------------------------------------------
print("[run_in_task cancel]")
out = {}
seen = {"pct": 0}


def work_slow(progress_cb):
    for i in range(1000):
        seen["pct"] = i
        progress_cb(i % 100)
        time.sleep(0.01)
    return "never"


task = run_in_task("lgs-test-cancel", work_slow,
                   on_finished=lambda r: out.setdefault("result", r),
                   on_error=lambda e, tb: out.update(error=e, tb=tb),
                   on_cancelled=lambda: out.setdefault("cancelled", True))
check(pump(lambda: seen["pct"] > 3), "worker is running")
task.cancel()
check(pump(lambda: out), "task completed after cancel")
check(out.get("cancelled") is True, "on_cancelled fired")
check("result" not in out and "error" not in out, "no success/error callback")

# ---- ChunkRunner: finish -------------------------------------------------
print("[ChunkRunner finish]")
out = {}
steps = []


def gen_ok():
    for i in range(4):
        steps.append(i)
        yield (i + 1) * 25, f"chunk {i}"
    return "chunk-done"


ChunkRunner(gen_ok(),
            on_finished=lambda r: out.setdefault("result", r),
            on_error=lambda e, tb: out.update(error=e),
            on_cancelled=lambda: out.setdefault("cancelled", True)).start()
check(pump(lambda: out), "runner completed")
check(out.get("result") == "chunk-done", "on_finished received generator return value")
check(steps == [0, 1, 2, 3], "all steps ran in order")

# ---- ChunkRunner: cancel runs finally ------------------------------------
print("[ChunkRunner cancel]")
out = {}
state = {"finally": False, "steps": 0}


def gen_slow():
    try:
        for i in range(10000):
            state["steps"] += 1
            time.sleep(0.002)  # keep the run alive long enough to cancel
            yield i % 100, ""
    finally:
        state["finally"] = True


runner = ChunkRunner(gen_slow(), budget_ms=5,
                     on_finished=lambda r: out.setdefault("result", r),
                     on_error=lambda e, tb: out.update(error=e),
                     on_cancelled=lambda: out.setdefault("cancelled", True))
runner.start()
check(pump(lambda: state["steps"] > 0), "runner is running")
runner.cancel()
check(pump(lambda: out), "runner completed after cancel")
check(out.get("cancelled") is True, "on_cancelled fired")
check(state["finally"] is True, "generator finally block ran (cleanup)")
check("result" not in out and "error" not in out, "no success/error callback")

print(f"\n{_passed} checks passed, {_failed} failed")
sys.exit(1 if _failed else 0)
