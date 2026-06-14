#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Advisory reconcile lock (pure: file + os only).

Two people reconciling the same master at the same time could interleave edit
sessions and corrupt the base snapshot. This is a cooperative, best-effort
guard — a single JSON lock file beside the master recording who holds it, their
PID and when. It is NOT a kernel lock: a stale lock (older than ``stale_seconds``
or from a dead PID on this host) can be stolen. Combined with the optimistic
``master_version`` check in the engine, it makes concurrent reconciles safe in
practice for a small mapping team.

    <master_dir>/adddata_metadata/<master_stem>.reconcile.lock
"""

import os
import json
from datetime import datetime, timezone

try:  # package context
    from .checkout import metadata_folder, master_stem
except ImportError:  # standalone (headless tests)
    from checkout import metadata_folder, master_stem

DEFAULT_STALE_SECONDS = 900  # 15 minutes


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _epoch_now() -> float:
    return datetime.now(timezone.utc).timestamp()


def lock_path(master_gpkg: str) -> str:
    return os.path.join(metadata_folder(master_gpkg),
                        f"{master_stem(master_gpkg)}.reconcile.lock")


class ReconcileLock:
    """Cooperative advisory lock for one master GeoPackage."""

    def __init__(self, master_gpkg: str, mapper: str = "",
                 stale_seconds: int = DEFAULT_STALE_SECONDS):
        self.master_gpkg = master_gpkg
        self.mapper = mapper
        self.stale_seconds = stale_seconds
        self.path = lock_path(master_gpkg)
        self._held = False

    # ----------------------------------------------------------------- reads
    def read(self):
        """Return the current lock holder info, or None if unlocked."""
        if not os.path.exists(self.path):
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def is_stale(self, info=None) -> bool:
        info = info if info is not None else self.read()
        if not info:
            return True
        try:
            age = _epoch_now() - float(info.get("epoch", 0))
        except (TypeError, ValueError):
            return True
        # A future-dated lock (clock skew / system clock change) is treated as
        # stale, otherwise a negative age would never trip the threshold below
        # and a dead lock could persist forever on Windows.
        if age < 0 or age >= self.stale_seconds:
            return True
        # A lock from a dead PID on THIS host is stale too.
        if info.get("host") == os.environ.get("COMPUTERNAME", "") \
                and not _pid_alive(info.get("pid")):
            return True
        return False

    # --------------------------------------------------------------- acquire
    def acquire(self, force: bool = False):
        """Try to take the lock.

        Returns (acquired: bool, blocking_info: dict|None). If another live,
        fresh lock is held and force is False, returns (False, that_info).
        """
        existing = self.read()
        if existing and not force and not self.is_stale(existing):
            return False, existing
        info = {
            "mapper": self.mapper,
            "pid": os.getpid(),
            "host": os.environ.get("COMPUTERNAME", ""),
            "acquired_utc": _utc_now_iso(),
            "epoch": _epoch_now(),
        }
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(info, f, indent=2)
            self._held = True
            return True, None
        except IOError as exc:
            return False, {"error": str(exc)}

    def release(self):
        """Remove the lock if we hold it (or it is ours by PID)."""
        info = self.read()
        if info is None:
            self._held = False
            return
        if self._held or info.get("pid") == os.getpid():
            try:
                os.remove(self.path)
            except OSError:
                pass
        self._held = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


def _pid_alive(pid) -> bool:
    """Best-effort: is a PID running on this machine? Unknown -> assume alive."""
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    if os.name == "nt":
        # No cheap, dependency-free probe on Windows; assume alive (so we fall
        # back to the time-based staleness check rather than stealing eagerly).
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True
