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
    from .snapshot import (FeatureFingerprint, FeaturePayload,
                           field_hash, is_empty, _is_excluded)
    from .diff_backend import (diff_fingerprints, Changeset, FeatureDelta,
                               _as_fingerprint_map,
                               OP_INSERT, OP_UPDATE, OP_DELETE)
    from .merge3 import compute_merge, FieldMerge, GEOM_WORKING
except ImportError:  # standalone (headless tests)
    from snapshot import (FeatureFingerprint, FeaturePayload,
                          field_hash, is_empty, _is_excluded)
    from diff_backend import (diff_fingerprints, Changeset, FeatureDelta,
                             _as_fingerprint_map,
                             OP_INSERT, OP_UPDATE, OP_DELETE)
    from merge3 import compute_merge, FieldMerge, GEOM_WORKING


# Conflict type labels
CONFLICT_UPDATE_UPDATE = "update/update"
CONFLICT_UPDATE_DELETE = "update/delete"
CONFLICT_DELETE_UPDATE = "delete/update"
CONFLICT_INSERT_INSERT = "insert/insert"
CONFLICT_BLANKING = "blanking"      # working clears fields that have values in master

# Conflict resolutions (set by the Phase 2 UI; default chosen at classify time).
RES_TAKE_WORKING = "take_working"   # apply the working (field) version
RES_TAKE_MASTER = "take_master"     # keep master; converge base, no write
RES_FIELD_MERGE = "field_merge"     # combine independent edits, working wins clashes
RES_SKIP = "skip"                   # leave unresolved; do NOT converge base


@dataclass
class Op:
    """A single planned operation against the master layer."""
    uuid: str
    op: str                                  # insert | update | delete
    payload: Optional[FeaturePayload] = None  # working feature (None for delete)
    attr_changed: bool = False
    geom_changed: bool = False
    # Lineage provenance stamped on accept (Phase 3); None = leave unset.
    lgs_parent_uuid: Optional[str] = None
    lgs_merged_from: Optional[str] = None


@dataclass
class ConflictRecord:
    """A feature changed on both sides — needs a resolution before it applies.

    For an update/update (or differing insert/insert) where the base carries
    per-field hashes and both payloads are present, the field-level merge is
    attached (``merge``) so the UI can show which fields clash and the commit
    can apply a field-merge or take-one-side. Otherwise it degrades to a
    whole-feature conflict (merge is None; only take-working/take-master/skip
    apply).
    """
    uuid: str
    layer: str
    type: str
    reason: str = ""
    working_attr_changed: bool = False
    working_geom_changed: bool = False
    master_attr_changed: bool = False
    master_geom_changed: bool = False
    # Field-level detail (when available).
    work_fields: List[str] = field(default_factory=list)
    master_fields: List[str] = field(default_factory=list)
    hard_fields: List[str] = field(default_factory=list)
    field_values: Dict[str, dict] = field(default_factory=dict)
    geom_conflict: bool = False
    merge: Optional[FieldMerge] = None        # in-memory only (not serialised)
    working_payload: Optional[FeaturePayload] = None
    master_payload: Optional[FeaturePayload] = None
    default_resolution: str = RES_SKIP
    resolution: Optional[str] = None          # set by the UI (falls back to default)
    resolved_by: Optional[str] = None
    resolved_utc: Optional[str] = None

    def effective_resolution(self) -> str:
        return self.resolution or self.default_resolution

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid, "layer": self.layer, "type": self.type,
            "reason": self.reason,
            "working_attr_changed": self.working_attr_changed,
            "working_geom_changed": self.working_geom_changed,
            "master_attr_changed": self.master_attr_changed,
            "master_geom_changed": self.master_geom_changed,
            "work_fields": list(self.work_fields),
            "master_fields": list(self.master_fields),
            "hard_fields": list(self.hard_fields),
            "geom_conflict": self.geom_conflict,
            "default_resolution": self.default_resolution,
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
    # Disjoint update/update merges, auto-applied like updates (Phase 2).
    auto_merges: List[Op] = field(default_factory=list)
    conflicts: List[ConflictRecord] = field(default_factory=list)
    # (uuid, reason) no-ops kept for transparency / changelog.
    skipped: List[tuple] = field(default_factory=list)
    # Phase 3 lineage groups.
    splits: List[object] = field(default_factory=list)
    merges: List[object] = field(default_factory=list)
    base_was_synthesized: bool = False

    def summary(self) -> dict:
        return {
            "layer": self.layer,
            "inserts": len(self.clean_inserts),
            "updates": len(self.clean_updates),
            "deletes": len(self.clean_deletes),
            "auto_merges": len(self.auto_merges),
            "conflicts": len(self.conflicts),
            "resolved": sum(1 for c in self.conflicts
                            if c.effective_resolution() != RES_SKIP),
            "skipped": len(self.skipped),
            "splits": len(self.splits),
            "merges": len(self.merges),
            "base_was_synthesized": self.base_was_synthesized,
        }

    def applicable_ops(self):
        """Consolidate everything that will be written, after resolutions.

        Returns (inserts, updates, deletes) as lists of Op, folding in
        auto-merges and any resolved conflicts. Skipped/unresolved conflicts
        contribute nothing.
        """
        inserts = list(self.clean_inserts)
        updates = list(self.clean_updates) + list(self.auto_merges)
        deletes = list(self.clean_deletes)
        for c in self.conflicts:
            op = conflict_to_op(c)
            if op is None:
                continue
            if op.op == OP_INSERT:
                inserts.append(op)
            elif op.op == OP_UPDATE:
                updates.append(op)
            elif op.op == OP_DELETE:
                deletes.append(op)
        return inserts, updates, deletes

    def has_applicable_changes(self) -> bool:
        inserts, updates, deletes = self.applicable_ops()
        return bool(inserts or updates or deletes)


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


def conflict_to_op(conflict: ConflictRecord) -> Optional[Op]:
    """Translate a conflict's effective resolution into a master-mutating Op.

    take_master / skip / unresolved -> None (no write). Resolution semantics:
    - update/update, differing insert/insert (feature present in master):
        field_merge -> update master to the merged payload;
        take_working -> update master to the working payload.
    - update/delete (working edited, master deleted -> feature absent):
        take_working -> re-insert working into master (resurrect).
    - delete/update (working deleted, master edited -> feature present):
        take_working -> delete the feature from master.
    """
    res = conflict.effective_resolution()
    if res in (RES_TAKE_MASTER, RES_SKIP):
        return None

    if conflict.type == CONFLICT_UPDATE_DELETE:
        if res == RES_TAKE_WORKING and conflict.working_payload is not None:
            wp = conflict.working_payload
            return Op(uuid=conflict.uuid, op=OP_INSERT, payload=wp,
                      attr_changed=True, geom_changed=wp.wkb is not None)
        return None

    if conflict.type == CONFLICT_DELETE_UPDATE:
        if res == RES_TAKE_WORKING:
            return Op(uuid=conflict.uuid, op=OP_DELETE)
        return None

    # update/update or differing insert/insert -> the feature is in master.
    if res == RES_FIELD_MERGE and conflict.merge is not None:
        return Op(uuid=conflict.uuid, op=OP_UPDATE,
                  payload=conflict.merge.merged_payload(), attr_changed=True,
                  geom_changed=(conflict.merge.geom_from == GEOM_WORKING))
    if res == RES_TAKE_WORKING and conflict.working_payload is not None:
        wp = conflict.working_payload
        return Op(uuid=conflict.uuid, op=OP_UPDATE, payload=wp,
                  attr_changed=True, geom_changed=wp.wkb is not None)
    return None


def _is_pure_blanking(working_payload: Optional[FeaturePayload],
                      master_payload: Optional[FeaturePayload],
                      w_delta) -> bool:
    """True if working's ONLY change is emptying field(s) that hold a value.

    Protects against silently wiping master data — most importantly the parent
    attributes carried onto a split/merge child, which the (still-blank) template
    would otherwise clear on the next sync. Called only in the clean-update
    branch, where master is UNCHANGED from base, so master's values ARE the base
    values — which means the check works even for legacy bases that carry no
    per-field hashes (we compare against master directly, not base hashes). A
    geometry change, or any field set to a *different* non-empty value, means it
    is a real edit and returns False. With no master payload (fingerprint-only
    callers, e.g. headless tests) it returns False — the prior behaviour.
    """
    if working_payload is None or master_payload is None:
        return False
    if w_delta is not None and w_delta.geom_changed:
        return False
    uuid_field = working_payload.uuid_field or "UUID"
    geom_field = working_payload.geom_field or "geom"
    changed = 0
    blankings = 0
    # Only the fields the WORKING side actually carries can be a working
    # blanking. Iterating the union would mis-count a field that exists in
    # master but not in the template (schema divergence) as an emptied field.
    for name in working_payload.attrs.keys():
        if _is_excluded(name, uuid_field, geom_field):
            continue
        wv = working_payload.attrs.get(name)
        mv = master_payload.attrs.get(name)
        if field_hash(wv) == field_hash(mv):
            continue
        changed += 1
        if is_empty(wv) and not is_empty(mv):
            blankings += 1
        else:
            return False          # a real (non-blanking) edit is present
    return changed > 0 and changed == blankings


def _both_edited(layer, uuid, ctype, reason, w, m, base_entry,
                 working_payload, master_payload):
    """Return ('auto', Op) for a disjoint merge or ('conflict', ConflictRecord).

    Attempts a field-level three-way merge; if the base lacks per-field hashes
    or a payload is missing it degrades to a whole-feature conflict (the UI then
    offers take-working / take-master / skip only).
    """
    merge = compute_merge(base_entry, working_payload, master_payload)
    if merge is not None and merge.is_auto_mergeable():
        return ("auto", Op(
            uuid=uuid, op=OP_UPDATE, payload=merge.merged_payload(),
            attr_changed=bool(merge.work_fields),
            geom_changed=(merge.geom_from == GEOM_WORKING)))

    rec = ConflictRecord(
        uuid=uuid, layer=layer, type=ctype, reason=reason,
        working_attr_changed=w.attr_changed if w else False,
        working_geom_changed=w.geom_changed if w else False,
        master_attr_changed=m.attr_changed if m else False,
        master_geom_changed=m.geom_changed if m else False,
        working_payload=working_payload, master_payload=master_payload)
    if merge is not None:
        rec.work_fields = merge.work_fields
        rec.master_fields = merge.master_fields
        rec.hard_fields = merge.hard_fields
        rec.field_values = merge.field_values
        rec.geom_conflict = merge.geom_conflict
        rec.merge = merge
        rec.default_resolution = RES_FIELD_MERGE
    else:
        rec.default_resolution = RES_SKIP
    return ("conflict", rec)


def compute_next_base(plan: "ReconcilePlan",
                      old_base: Optional[Dict[str, FeatureFingerprint]],
                      working_fp: Dict[str, FeatureFingerprint],
                      master_fp: Dict[str, FeatureFingerprint]
                      ) -> Dict[str, FeatureFingerprint]:
    """The new common ancestor after this reconcile (per UUID, not wholesale).

    This is the correct base-advance for a *partial* reconcile: applied
    inserts/updates/auto-merges/resolved-conflicts converge to the agreed
    post-apply fingerprint; applied deletes drop out; **skipped or unresolved
    conflicts keep their OLD base entry so they re-surface next sync**;
    master-only changes and converged deletes/identical-inserts converge so
    they stop being re-reported. Starting from a copy of old_base preserves
    untouched features and unresolved conflicts.

    `working_fp` / `master_fp` are the pre-apply fingerprints of the working
    and master layers (used only for features we did not rewrite).
    """
    new_base: Dict[str, FeatureFingerprint] = dict(old_base) if old_base else {}

    inserts, updates, deletes = plan.applicable_ops()
    for op in inserts + updates:
        if op.payload is not None:
            new_base[op.uuid] = op.payload.fingerprint()
        elif op.uuid in working_fp:
            new_base[op.uuid] = working_fp[op.uuid]
    for op in deletes:
        new_base.pop(op.uuid, None)

    # take_working / field_merge already converged via applicable_ops above.
    # take_master, skip and unresolved conflicts are all LEFT at their old base
    # entry (new_base started as a copy of old_base): there is no template
    # write-back, so the working side still disagrees — converging the base to
    # master would silently re-apply the working edit (or resurrect a deletion)
    # on the next sync. Keeping the old base makes the conflict re-surface for a
    # fresh decision instead. (Nothing to do here — intentional no-op.)

    for uuid, reason in plan.skipped:
        if reason.startswith("master-only"):
            if uuid in master_fp:
                new_base[uuid] = master_fp[uuid]
        elif "delete/delete converged" in reason:
            new_base.pop(uuid, None)
        elif "insert/insert identical" in reason and uuid in master_fp:
            new_base[uuid] = master_fp[uuid]

    return new_base


def classify(layer: str,
             uuid_field: str,
             base_fp: Optional[Dict[str, FeatureFingerprint]],
             working_payloads: Dict[str, FeaturePayload],
             master_state: Dict[str, object]) -> ReconcilePlan:
    """Classify one layer's three-way state into a ReconcilePlan.

    ``master_state`` may map UUID -> FeaturePayload (preferred, enables
    field-level merge and conflict resolution) or UUID -> FeatureFingerprint
    (fingerprint-only; both-sides edits degrade to whole-feature conflicts).
    """
    plan = ReconcilePlan(layer=layer, uuid_field=uuid_field)

    master_fp = _as_fingerprint_map(master_state)
    master_payloads = {u: v for u, v in master_state.items()
                       if isinstance(v, FeaturePayload)}

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
                    kind, obj = _both_edited(
                        layer, u, CONFLICT_INSERT_INSERT,
                        "same UUID inserted in master and working with "
                        "different content (possible UUID collision)",
                        w, m, base_fp.get(u), payload, master_payloads.get(u))
                    (plan.auto_merges if kind == "auto"
                     else plan.conflicts).append(obj)
            else:
                # m_op delete impossible for an insert (u not in base).
                plan.skipped.append((u, f"insert with unexpected master {m_op}"))
            continue

        # ---- working UPDATE (u in base) ----
        if w_op == OP_UPDATE:
            if m_op is None:
                # Master unchanged since base. But is u still in master?
                if u in master_present:
                    if _is_pure_blanking(payload, master_payloads.get(u), w):
                        # Working only emptied fields that have values in master
                        # — hold it for confirmation rather than wiping data.
                        plan.conflicts.append(ConflictRecord(
                            uuid=u, layer=layer, type=CONFLICT_BLANKING,
                            reason="working clears field(s) that hold values in "
                                   "master (e.g. a blank split/merge child)",
                            working_attr_changed=True,
                            working_payload=payload,
                            master_payload=master_payloads.get(u),
                            default_resolution=RES_SKIP))
                    else:
                        plan.clean_updates.append(Op(
                            uuid=u, op=OP_UPDATE, payload=payload,
                            attr_changed=w.attr_changed if w else False,
                            geom_changed=w.geom_changed if w else False))
                else:
                    # In base, unchanged-in-master-diff, yet absent: treat as
                    # master-deleted (shouldn't normally happen).
                    plan.conflicts.append(ConflictRecord(
                        uuid=u, layer=layer, type=CONFLICT_UPDATE_DELETE,
                        reason="working updated a feature missing from master",
                        working_attr_changed=w.attr_changed if w else False,
                        working_geom_changed=w.geom_changed if w else False,
                        working_payload=payload))
            elif m_op == OP_UPDATE:
                kind, obj = _both_edited(
                    layer, u, CONFLICT_UPDATE_UPDATE,
                    "feature edited in both master and working",
                    w, m, base_fp.get(u), payload, master_payloads.get(u))
                (plan.auto_merges if kind == "auto"
                 else plan.conflicts).append(obj)
            elif m_op == OP_DELETE:
                plan.conflicts.append(ConflictRecord(
                    uuid=u, layer=layer, type=CONFLICT_UPDATE_DELETE,
                    reason="working updated a feature deleted in master",
                    working_attr_changed=w.attr_changed if w else False,
                    working_geom_changed=w.geom_changed if w else False,
                    working_payload=payload))
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
                    master_geom_changed=m.geom_changed if m else False,
                    master_payload=master_payloads.get(u)))
            else:
                plan.skipped.append((u, f"delete with unexpected master {m_op}"))
            continue

    # Stable ordering for deterministic previews/changelogs.
    plan.clean_inserts.sort(key=lambda o: o.uuid)
    plan.clean_updates.sort(key=lambda o: o.uuid)
    plan.clean_deletes.sort(key=lambda o: o.uuid)
    plan.auto_merges.sort(key=lambda o: o.uuid)
    plan.conflicts.sort(key=lambda c: c.uuid)
    plan.skipped.sort(key=lambda t: t[0])
    return plan
