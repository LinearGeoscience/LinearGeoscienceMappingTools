"""Shared background-work helpers for the Linear Geoscience plugin.

Two tools, no framework:

- run_in_task(): run a pure-compute function on the QGIS task manager's
  thread pool with cancel support and progress routed to both the QGIS
  status bar (task manager) and an optional in-dialog progress bar/label.
  The worker function must not touch project layers, iface, or any other
  main-thread object -- pass paths/values in and open resources inside.

- ChunkRunner: run main-thread-only work (project-layer edits, print
  layouts, exporters) as a cancelable generator sliced across event-loop
  ticks, so the UI keeps repainting and a Cancel button stays clickable.
  This replaces the QApplication.processEvents() pattern.

Both run on QGIS 3.40 LTR and QGIS 4.x.
"""

import time
import traceback

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.core import QgsApplication, QgsTask


class TaskCancelled(Exception):
    """Raised inside a worker's progress_cb when the user cancelled."""


# QgsTask objects are garbage-collected (and silently die) if Python drops
# the last reference before they finish; keep them alive here.
_ACTIVE = set()


def _alive(obj):
    return obj is not None and not sip.isdeleted(obj)


class _ProgressRouter(QObject):
    """Routes worker-thread progress to main-thread widgets via a queued
    signal, and gives the worker a cancel-aware callback."""

    sig = pyqtSignal(int, str)

    def __init__(self, bar=None, label=None, owner=None):
        super().__init__()
        self._task = None
        self._bar = bar
        self._label = label
        self._owner = owner
        self.sig.connect(self._update)

    def bind(self, task):
        self._task = task

    def cb(self, pct, msg=None):
        """progress_cb(pct, msg=None) -- signature-compatible with the
        existing progress hooks in the reconcile engine / hardcode runner."""
        if self._task is not None and self._task.isCanceled():
            raise TaskCancelled()
        if self._task is not None:
            self._task.setProgress(float(pct))
        self.sig.emit(int(pct), msg or "")

    def _update(self, pct, msg):
        if self._owner is not None and sip.isdeleted(self._owner):
            return
        if _alive(self._bar):
            self._bar.setValue(pct)
        if msg and _alive(self._label):
            self._label.setText(msg)


def run_in_task(description, func, *, on_finished, on_error=None,
                on_cancelled=None, owner=None, bar=None, label=None):
    """Run func(progress_cb) on the task pool; callbacks on the main thread.

    - func(progress_cb) -> result. progress_cb(pct, msg=None) raises
      TaskCancelled when the user cancelled (from the dialog button or the
      QGIS task-manager widget).
    - on_finished(result) on success, on_error(exc, tb_str) on exception,
      on_cancelled() on cancellation. All are skipped if `owner` (usually
      the launching dialog) has been deleted meanwhile.

    Returns the QgsTask (e.g. to wire a Cancel button to task.cancel()).
    """
    router = _ProgressRouter(bar=bar, label=label, owner=owner)

    def _runner(task):
        router.bind(task)
        try:
            return {"ok": True, "result": func(router.cb)}
        except TaskCancelled:
            return {"cancelled": True}
        except Exception as exc:  # routed to on_error on the main thread
            return {"error": exc, "tb": traceback.format_exc()}

    def _done(exception, state=None):
        _ACTIVE.discard(task)
        router.deleteLater()
        if owner is not None and sip.isdeleted(owner):
            return
        if state is None:
            # run() never produced a state: cancelled while queued, or the
            # wrapper itself failed.
            if task.isCanceled():
                if on_cancelled:
                    on_cancelled()
            elif on_error:
                on_error(exception or Exception("task failed"), str(exception))
            return
        if state.get("cancelled"):
            if on_cancelled:
                on_cancelled()
        elif "error" in state:
            if on_error:
                on_error(state["error"], state["tb"])
        else:
            on_finished(state.get("result"))

    task = QgsTask.fromFunction(description, _runner, on_finished=_done)
    _ACTIVE.add(task)
    QgsApplication.taskManager().addTask(task)
    return task


class ChunkRunner(QObject):
    """Cancelable main-thread work slicer.

    `gen` is a generator: each next() performs one unit of main-thread work
    and yields (pct:int, msg:str). A `return value` from the generator
    becomes on_finished's argument. Cleanup on cancel/error belongs in the
    generator's own try/finally (e.g. layer.rollBack()); cancel() closes the
    generator so those finally blocks run.
    """

    def __init__(self, gen, *, on_finished, on_error=None, on_cancelled=None,
                 owner=None, bar=None, label=None, budget_ms=30, parent=None):
        super().__init__(parent)
        self._gen = gen
        self._on_finished = on_finished
        self._on_error = on_error
        self._on_cancelled = on_cancelled
        self._owner = owner
        self._bar = bar
        self._label = label
        self._budget = budget_ms / 1000.0
        self._cancelled = False
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._tick)

    def start(self):
        # Self-register so the runner survives callers that don't keep a
        # reference (same GC pitfall as QgsTask).
        _ACTIVE.add(self)
        self._timer.start()
        return self

    def cancel(self):
        self._cancelled = True

    def _owner_gone(self):
        return self._owner is not None and sip.isdeleted(self._owner)

    def _stop(self):
        self._timer.stop()
        _ACTIVE.discard(self)
        self.deleteLater()

    def _tick(self):
        if self._cancelled or self._owner_gone():
            self._stop()
            try:
                self._gen.close()  # run the generator's finally blocks
            except Exception:
                pass
            if not self._owner_gone() and self._on_cancelled:
                self._on_cancelled()
            return
        deadline = time.monotonic() + self._budget
        try:
            while True:
                pct, msg = next(self._gen)
                if _alive(self._bar):
                    self._bar.setValue(int(pct))
                if msg and _alive(self._label):
                    self._label.setText(msg)
                if time.monotonic() >= deadline:
                    return  # yield to the event loop; timer re-fires
        except StopIteration as stop:
            self._stop()
            if not self._owner_gone():
                self._on_finished(stop.value)
        except Exception as exc:
            self._stop()
            if not self._owner_gone() and self._on_error:
                self._on_error(exc, traceback.format_exc())
