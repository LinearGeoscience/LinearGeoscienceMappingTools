#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Three-way classification: base (common ancestor) x working (template) x
master, all keyed by UUID, producing a ReconcilePlan.

Pure module (no QGIS). Inputs:
- base_fp:           {uuid: FeatureFingerprint}     ancestor (from JSON)
- working_payloads:  {uuid: FeaturePayload}         current template (with data)
- master_fp:         {uuid: FeatureFingerprint}     current master

The working side carries full payloads so inserts/updates can be applied to
master at commit; the master side only needs fingerprints (commit operates on
the live master layer by UUID).

MVP scope (Phase 1): clean insert / update / delete are planned for
application. Anything where BOTH sides touched the same feature (update/update,
update/delete, delete/update, insert/insert with differing content) is recorded
as a conflict and NOT auto-applied — surfaced for manual handling until the
Phase 2 resolution UI lands. Field-level auto-merge of disjoint edits needs
master+base attribute values (not captured in the MVP) and is deferred.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

try:  # package context
    from .snapshot import FeatureFingerprint, FeaturePayload
    from .diff_backend import (diff_fingerprints, Changeset, FeatureDelta,
                               OP_INSERT, OP_UPDATE, OP_DELETE)
except ImportError:  # standalone (headless tests)
    from snapshot import FeatureFingerprint, FeaturePayload
    from diff_backend import (diff_fingerprints, Changeset, FeatureDelta,
                             OP_INSERT, OP_UPDATE, OP_DELETE)


# Conflict type labels
CONFLICT_UPDATE_UPDATE = "update/update"
CONFLICT_UPDATE_DELETE = "update/delete"
CONFLICT_DELETE_UPDATE = "delete/update"
CONFLICT_INSERT_INSERT = "insert/insert"


@dataclass
class Op:
    """A single planned operation against the master layer."""
    uuid: str
    op: str                                  # insert | update | delete
    payload: Optional[FeaturePayload] = None  # working feature (None for delete)
    attr_changed: bool = False
    geom_changed: bool = False


@dataclass
class ConflictRecord:
    """A feature changed on both sides — not auto-applied in the MVP."""
    uuid: str
    layer: str
    type: str
    reason: str = ""
    working_attr_changed: bool = False
    working_geom_changed: bool = False
    master_attr_changed: bool = False
    master_geom_changed: bool = False
    resolution: Optional[str] = None         # set by Phase 2 UI
    resolved_by: Optional[str] = None
    resolved_utc: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid, "layer": self.layer, "type": self.type,
            "reason": self.reason,
            "working_attr_changed": self.working_attr_changed,
            "working_geom_changed": self.working_geom_changed,
            "master_attr_changed": self.master_attr_changed,
            "master_geom_changed": self.master_geom_changed,
            "resolution": self.resolution,
            "resolved_by": self.resolved_by,
            "resolved_utc": self.resolved_utc,
        }


@dataclass
class ReconcilePlan:
    """Everything to do for one layer, grouped by operation."""
    layer: str
    uuid_field: str = "UUID"
    clean_inserts: List[Op] = field(default_factory=list)
    clean_updates: List[Op] = field(default_factory=list)
    clean_deletes: List[Op] = field(default_factory=list)
    conflicts: List[ConflictRecord] = field(default_factory=list)
    # (uuid, reason) no-ops kept for transparency / changelog.
    skipped: List[tuple] = field(default_factory=list)
    # Phase 3 lineage groups (unused in MVP).
    splits: List[object] = field(default_factory=list)
    merges: List[object] = field(default_factory=list)
    base_was_synthesized: bool = False

    def summary(self) -> dict:
        return {
            "layer": self.layer,
            "inserts": len(self.clean_inserts),
            "updates": len(self.clean_updates),
            "deletes": len(self.clean_deletes),
            "conflicts": len(self.conflicts),
            "skipped": len(self.skipped),
            "splits": len(self.splits),
            "merges": len(self.merges),
            "base_was_synthesized": self.base_was_synthesized,
        }

    def has_applicable_changes(self) -> bool:
        return bool(self.clean_inserts or self.clean_updates or self.clean_deletes)


def synthesize_base(working_payloads: Dict[str, FeaturePayload],
                    master_fp: Dict[str, FeatureFingerprint]
                    ) -> Dict[str, FeatureFingerprint]:
    """Best-effort ancestor when no real base exists (legacy first sync).

    Assume features present in BOTH working and master share master's current
    state as their ancestor. Consequence: features in both classify as update
    (if working changed them) or no-op (if identical); working-only features
    classify as inserts; no deletes are inferred (can't be known without a
    real base). Avoids re-inserting already-appended features.
    """
    return {u: master_fp[u] for u in working_payloads if u in master_fp}


def classify(layer: str,
             uuid_field: str,
             base_fp: Optional[Dict[str, FeatureFingerprint]],
             working_payloads: Dict[str, FeaturePayload],
             master_fp: Dict[str, FeatureFingerprint]) -> ReconcilePlan:
    """Classify one layer's three-way state into a ReconcilePlan."""
    plan = ReconcilePlan(layer=layer, uuid_field=uuid_field)

    if base_fp is None:
        base_fp = synthesize_base(working_payloads, master_fp)
        plan.base_was_synthesized = True

    working_cs = diff_fingerprints(base_fp, working_payloads, layer)
    master_cs = diff_fingerprints(base_fp, master_fp, layer)

    master_present = set(master_fp.keys())

    # Union of all UUIDs that changed on either side.
    touched = set(working_cs.deltas) | set(master_cs.deltas)

    for u in touched:
        w: Optional[FeatureDelta] = working_cs.get(u)
        m: Optional[FeatureDelta] = master_cs.get(u)
        w_op = w.op if w else None
        m_op = m.op if m else None
        payload = working_payloads.get(u)

        # ---- working did not change this feature (master-only change) ----
        if w_op is None:
            # Keep master; nothing to write. Recorded for transparency.
            plan.skipped.append((u, f"master-only {m_op}"))
            continue

        # ---- working INSERT (u not in base) ----
        if w_op == OP_INSERT:
            if m_op is None:
                # Not in master either -> clean insert.
                plan.clean_inserts.append(Op(
                    uuid=u, op=OP_INSERT, payload=payload,
                    attr_changed=True,
                    geom_changed=w.geom_changed if w else False))
            elif m_op == OP_INSERT:
                # Same UUID inserted on both sides.
                if w and m and w.new_fingerprint and m.new_fingerprint \
                        and w.new_fingerprint.equals(m.new_fingerprint):
                    plan.skipped.append((u, "insert/insert identical (converged)"))
                else:
                    plan.conflicts.append(ConflictRecord(
                        uuid=u, layer=layer, type=CONFLICT_INSERT_INSERT,
                        reason="same UUID inserted in master and working with "
                               "different content (possible UUID collision)",
                        working_attr_changed=True,
                        master_attr_changed=True))
            else:
                # m_op delete impossible for an insert (u not in base).
                plan.skipped.append((u, f"insert with unexpected master {m_op}"))
            continue

        # ---- working UPDATE (u in base) ----
        if w_op == OP_UPDATE:
            if m_op is None:
                # Master unchanged since base. But is u still in master?
                if u in master_present:
                    plan.clean_updates.append(Op(
                        uuid=u, op=OP_UPDATE, payload=payload,
                        attr_changed=w.attr_changed if w else False,
                        geom_changed=w.geom_changed if w else False))
                else:
                    # In base, unchanged-in-master-diff, yet absent: treat as
                    # master-deleted (shouldn't normally happen).
                    plan.conflicts.append(ConflictRecord(
                        uuid=u, layer=layer, type=CONFLICT_UPDATE_DELETE,
                        reason="working updated a feature missing from master"))
            elif m_op == OP_UPDATE:
                plan.conflicts.append(ConflictRecord(
                    uuid=u, layer=layer, type=CONFLICT_UPDATE_UPDATE,
                    reason="feature edited in both master and working",
                    working_attr_changed=w.attr_changed if w else False,
                    working_geom_changed=w.geom_changed if w else False,
                    master_attr_changed=m.attr_changed if m else False,
                    master_geom_changed=m.geom_changed if m else False))
            elif m_op == OP_DELETE:
                plan.conflicts.append(ConflictRecord(
                    uuid=u, layer=layer, type=CONFLICT_UPDATE_DELETE,
                    reason="working updated a feature deleted in master",
                    working_attr_changed=w.attr_changed if w else False,
                    working_geom_changed=w.geom_changed if w else False))
            continue

        # ---- working DELETE (u in base, gone from working) ----
        if w_op == OP_DELETE:
            if m_op is None:
                if u in master_present:
                    plan.clean_deletes.append(Op(uuid=u, op=OP_DELETE))
                else:
                    plan.skipped.append((u, "delete/delete converged"))
            elif m_op == OP_DELETE:
                plan.skipped.append((u, "delete/delete converged"))
            elif m_op == OP_UPDATE:
                plan.conflicts.append(ConflictRecord(
                    uuid=u, layer=layer, type=CONFLICT_DELETE_UPDATE,
                    reason="working deleted a feature updated in master",
                    master_attr_changed=m.attr_changed if m else False,
                    master_geom_changed=m.geom_changed if m else False))
            else:
                plan.skipped.append((u, f"delete with unexpected master {m_op}"))
            continue

    # Stable ordering for deterministic previews/changelogs.
    plan.clean_inserts.sort(key=lambda o: o.uuid)
    plan.clean_updates.sort(key=lambda o: o.uuid)
    plan.clean_deletes.sort(key=lambda o: o.uuid)
    plan.conflicts.sort(key=lambda c: c.uuid)
    plan.skipped.sort(key=lambda t: t[0])
    return plan
