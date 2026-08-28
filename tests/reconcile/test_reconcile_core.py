#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Headless unit tests for the PURE reconcile core (no QGIS required).

Covers content hashing (+ exclusions/normalisation), changeset diff, and the
full three-way classification table including the re-append-without-loss case.

Run:  python tests/reconcile/test_reconcile_core.py
"""

import os
import sys

# Import the pure reconcile modules directly (no QGIS, no parent package).
RECONCILE_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "script_adddata", "reconcile"))
sys.path.insert(0, RECONCILE_DIR)

import snapshot          # noqa: E402
import diff_backend      # noqa: E402
import reconcile as rc   # noqa: E402

from snapshot import FeaturePayload, FeatureFingerprint, attr_hash, geom_hash  # noqa: E402
from diff_backend import diff_fingerprints, OP_INSERT, OP_UPDATE, OP_DELETE    # noqa: E402


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
    return FeaturePayload(uuid=uuid, attrs=a, wkb=attrs.pop("_wkb", None),
                          uuid_field="UUID", geom_field="geom")


def fp(uuid, **attrs):
    return payload(uuid, **attrs).fingerprint()


# --------------------------------------------------------------------------
def test_hash_excludes_and_normalises():
    base = {"UUID": "u1", "geom": None, "Dip": 30, "Comments": "hi"}
    # UUID/geom excluded: changing them must not change the attr hash.
    h0 = attr_hash(base)
    h_uuid = attr_hash({**base, "UUID": "DIFFERENT"})
    h_geom = attr_hash({**base, "geom": b"xyz"})
    check(h0 == h_uuid, "UUID excluded from attr hash")
    check(h0 == h_geom, "geom excluded from attr hash")

    # Housekeeping columns excluded.
    h_house = attr_hash({**base, "lgs_version": "5", "data_added_batch_id": "b"})
    check(h0 == h_house, "lgs_/data_added_ excluded from attr hash")

    # Normalisation: int vs str, None vs '' vs 'NULL' all equal.
    check(attr_hash({"Dip": 30}) == attr_hash({"Dip": "30"}),
          "int/str drift normalised")
    check(attr_hash({"X": None}) == attr_hash({"X": ""}) == attr_hash({"X": "NULL"}),
          "None/blank/NULL normalised")

    # A real content change DOES change the hash.
    check(h0 != attr_hash({**base, "Dip": 31}), "content change detected")

    # geom_hash
    check(geom_hash(None) is None, "geom_hash(None) is None")
    check(geom_hash(b"abc") == geom_hash(b"abc"), "geom_hash deterministic")
    check(geom_hash(b"abc") != geom_hash(b"abd"), "geom_hash distinguishes")


def test_diff():
    base = {"a": fp("a", Dip=10), "b": fp("b", Dip=20), "c": fp("c", Dip=30)}
    cur = {
        "a": fp("a", Dip=10),          # unchanged
        "b": fp("b", Dip=99),          # updated
        "d": fp("d", Dip=40),          # inserted
        # c deleted
    }
    cs = diff_fingerprints(base, cur, "L")
    check(cs.get("a") is None, "unchanged -> no delta")
    check(cs.get("b").op == OP_UPDATE, "changed -> update")
    check(cs.get("d").op == OP_INSERT, "new -> insert")
    check(cs.get("c").op == OP_DELETE, "missing -> delete")


def test_classify_clean_paths():
    # base has f1(old); working updates f1, deletes f2, inserts f3.
    base = {"f1": fp("f1", Dip=10), "f2": fp("f2", Dip=20)}
    working = {
        "f1": payload("f1", Dip=11),   # update
        "f3": payload("f3", Dip=30),   # insert
        # f2 deleted
    }
    # master unchanged from base (still has f1@10, f2@20).
    master = {"f1": fp("f1", Dip=10), "f2": fp("f2", Dip=20)}

    plan = rc.classify("L", "UUID", base, working, master)
    check([o.uuid for o in plan.clean_updates] == ["f1"], "clean update f1")
    check([o.uuid for o in plan.clean_inserts] == ["f3"], "clean insert f3")
    check([o.uuid for o in plan.clean_deletes] == ["f2"], "clean delete f2")
    check(not plan.conflicts, "no conflicts on clean paths")
    # The update op carries the working payload for commit.
    check(plan.clean_updates[0].payload.attrs["Dip"] == 11, "update payload present")


def test_classify_conflicts():
    base = {"f1": fp("f1", Dip=10), "f2": fp("f2", Dip=20),
            "f3": fp("f3", Dip=30)}
    working = {
        "f1": payload("f1", Dip=11),   # working update
        # f2 deleted by working
        "f3": payload("f3", Dip=31),   # working update
    }
    master = {
        "f1": fp("f1", Dip=12),        # master also updated -> update/update
        "f2": fp("f2", Dip=22),        # master updated, working deleted -> delete/update
        # f3 deleted by master, working updated -> update/delete
    }
    plan = rc.classify("L", "UUID", base, working, master)
    types = sorted(c.type for c in plan.conflicts)
    check(types == sorted([rc.CONFLICT_UPDATE_UPDATE,
                           rc.CONFLICT_DELETE_UPDATE,
                           rc.CONFLICT_UPDATE_DELETE]),
          f"three conflict types, got {types}")
    check(not plan.has_applicable_changes(), "conflicts are not auto-applied")


def test_insert_insert():
    base = {}
    # identical insert on both sides -> converge (skip)
    working = {"x": payload("x", Dip=5)}
    master = {"x": fp("x", Dip=5)}
    plan = rc.classify("L", "UUID", base, working, master)
    check(not plan.clean_inserts and not plan.conflicts,
          "identical insert/insert converges")
    check(any(u == "x" for u, _ in plan.skipped), "converge recorded in skipped")

    # differing insert on both sides -> conflict
    master2 = {"x": fp("x", Dip=6)}
    plan2 = rc.classify("L", "UUID", base, working, master2)
    check(len(plan2.conflicts) == 1 and plan2.conflicts[0].type == rc.CONFLICT_INSERT_INSERT,
          "differing insert/insert conflicts")


def test_master_only_change_is_noop():
    base = {"f1": fp("f1", Dip=10)}
    working = {"f1": payload("f1", Dip=10)}   # working unchanged
    master = {"f1": fp("f1", Dip=99)}          # master changed
    plan = rc.classify("L", "UUID", base, working, master)
    check(not plan.has_applicable_changes(), "master-only change -> nothing to write")
    check(any("master-only" in r for _, r in plan.skipped), "master-only recorded")


def test_reappend_without_loss():
    """The headline fix: after a sync the base advances, so re-syncing an
    edited template applies the edit (update) instead of silently skipping."""
    # First sync: blank base, working has a brand-new feature.
    base1 = {}
    working1 = {"f1": payload("f1", Dip=10)}
    master1 = {}  # not yet in master
    plan1 = rc.classify("L", "UUID", base1, working1, master1)
    check([o.uuid for o in plan1.clean_inserts] == ["f1"], "first sync inserts f1")

    # Commit advances base to the working state, and master now has f1@10.
    base2 = {"f1": working1["f1"].fingerprint()}
    master2 = {"f1": fp("f1", Dip=10)}

    # Re-sync with NO further edits -> no-op (the old append would re-skip;
    # the bug was that an EDIT got skipped — see next case).
    plan_noop = rc.classify("L", "UUID", base2, dict(working1), master2)
    check(not plan_noop.has_applicable_changes(), "unedited re-sync is a no-op")

    # Re-sync after EDITING f1 -> update applied (previously this edit was LOST).
    working2 = {"f1": payload("f1", Dip=42)}
    plan_edit = rc.classify("L", "UUID", base2, working2, master2)
    check([o.uuid for o in plan_edit.clean_updates] == ["f1"],
          "edited re-sync applies update (no data loss)")
    check(plan_edit.clean_updates[0].payload.attrs["Dip"] == 42, "edit value carried")


def test_synthesize_base_legacy_first_sync():
    """No recorded base: features in both working+master use master as ancestor,
    so previously-appended features are not re-inserted."""
    working = {"old": payload("old", Dip=10), "new": payload("new", Dip=20)}
    master = {"old": fp("old", Dip=10)}   # 'old' already appended previously
    plan = rc.classify("L", "UUID", None, working, master)
    check(plan.base_was_synthesized, "base synthesized when None")
    check([o.uuid for o in plan.clean_inserts] == ["new"], "only genuinely-new inserts")
    check(not any(o.uuid == "old" for o in plan.clean_inserts),
          "already-appended feature not re-inserted")
    # Editing an already-appended feature with no real base -> update.
    working_edit = {"old": payload("old", Dip=11)}
    plan2 = rc.classify("L", "UUID", None, working_edit, master)
    check([o.uuid for o in plan2.clean_updates] == ["old"],
          "synthesized base lets edits to known features apply as updates")


def basefp(uuid, **attrs):
    """A base fingerprint that carries field_hashes (post-upgrade base)."""
    return payload(uuid, **attrs).fingerprint()


def test_field_hash_decomposition():
    from snapshot import field_hash, compute_field_hashes
    # field_hash normalises like attr_hash.
    check(field_hash(30) == field_hash("30"), "field_hash int/str normalised")
    check(field_hash(None) == field_hash("") == field_hash("NULL"),
          "field_hash None/blank/NULL normalised")
    fh = compute_field_hashes({"UUID": "u", "geom": b"x", "Dip": 10,
                               "lgs_version": "3", "data_added_batch_id": "b",
                               "Rock": "granite"})
    check(set(fh.keys()) == {"Dip", "Rock"},
          "compute_field_hashes excludes UUID/geom/housekeeping")
    # Fingerprints now carry field_hashes; equals still ignores them.
    f = payload("a", Dip=10).fingerprint()
    check(f.field_hashes is not None and "Dip" in f.field_hashes,
          "fingerprint carries field_hashes")


def test_auto_merge_disjoint():
    """Working changed field A, master changed field B -> auto-merge, no conflict."""
    base = {"x": basefp("x", A=1, B=1)}
    working = {"x": payload("x", A=2, B=1)}       # working edited A
    master = {"x": payload("x", A=1, B=2)}        # master edited B (payload!)
    plan = rc.classify("L", "UUID", base, working, master)
    check(not plan.conflicts, "disjoint edits -> no conflict")
    check(len(plan.auto_merges) == 1, "disjoint edits -> one auto-merge")
    merged = plan.auto_merges[0].payload.attrs
    check(str(merged["A"]) == "2" and str(merged["B"]) == "2",
          "auto-merge keeps working's A and master's B")
    check(plan.has_applicable_changes(), "auto-merge is applicable")


def test_hard_conflict_field_detail_and_resolutions():
    """Same field edited differently on both sides -> conflict with field detail."""
    base = {"x": basefp("x", A=1, B=1)}
    working = {"x": payload("x", A=2, B=1)}       # working edited A only
    master = {"x": payload("x", A=3, B=5)}        # master edited A and B
    plan = rc.classify("L", "UUID", base, working, master)
    check(len(plan.conflicts) == 1 and not plan.auto_merges,
          "same-field clash -> conflict (not auto-merge)")
    c = plan.conflicts[0]
    check(c.hard_fields == ["A"], f"A is the hard field, got {c.hard_fields}")
    check(c.master_fields == ["B"], f"B is master-only, got {c.master_fields}")
    check(c.effective_resolution() == rc.RES_FIELD_MERGE,
          "default resolution is field_merge when mergeable")

    # field_merge: working wins the clash (A=2), master's independent edit kept (B=5)
    op = rc.conflict_to_op(c)
    check(op is not None and str(op.payload.attrs["A"]) == "2"
          and str(op.payload.attrs["B"]) == "5", "field_merge: A=working, B=master")

    # take_working: working values throughout (A=2, B=1)
    c.resolution = rc.RES_TAKE_WORKING
    op = rc.conflict_to_op(c)
    check(op is not None and str(op.payload.attrs["A"]) == "2"
          and str(op.payload.attrs["B"]) == "1", "take_working: all working values")

    # take_master / skip: no write
    c.resolution = rc.RES_TAKE_MASTER
    check(rc.conflict_to_op(c) is None, "take_master -> no op")
    c.resolution = rc.RES_SKIP
    check(rc.conflict_to_op(c) is None, "skip -> no op")
    check(not plan.has_applicable_changes(),
          "a skipped conflict leaves nothing applicable")


def test_fingerprint_only_master_falls_back():
    """Master passed as fingerprints (no payload) -> whole-feature conflict."""
    base = {"x": basefp("x", A=1)}
    working = {"x": payload("x", A=2)}
    master = {"x": fp("x", A=3)}                   # fingerprint, not payload
    plan = rc.classify("L", "UUID", base, working, master)
    check(len(plan.conflicts) == 1 and plan.conflicts[0].merge is None,
          "fingerprint-only master -> whole-feature conflict (no field merge)")
    check(plan.conflicts[0].effective_resolution() == rc.RES_SKIP,
          "whole-feature conflict defaults to skip")


def test_compute_next_base_partial():
    """The advanced base reflects applied work, converges no-ops, but KEEPS the
    old entry for a skipped conflict so it re-surfaces next sync."""
    base = {"f1": basefp("f1", A=1), "f2": basefp("f2", A=1),
            "fc": basefp("fc", A=1), "fm": basefp("fm", A=1)}
    working = {
        "f1": payload("f1", A=2),     # clean update (master unchanged)
        # f2 deleted
        "f3": payload("f3", A=9),     # clean insert
        "fc": payload("fc", A=2),     # working edits A ...
        "fm": payload("fm", A=1),     # working unchanged
    }
    master = {
        "f1": payload("f1", A=1),     # unchanged
        "f2": payload("f2", A=1),     # present, unchanged
        "fc": payload("fc", A=3),     # ... master also edits A -> hard conflict
        "fm": payload("fm", A=5),     # master-only change
    }
    plan = rc.classify("L", "UUID", base, working, master)
    check([o.uuid for o in plan.clean_updates] == ["f1"], "cnb: clean update f1")
    check([o.uuid for o in plan.clean_inserts] == ["f3"], "cnb: clean insert f3")
    check([o.uuid for o in plan.clean_deletes] == ["f2"], "cnb: clean delete f2")
    check([c.uuid for c in plan.conflicts] == ["fc"], "cnb: fc is the conflict")

    working_fp = {u: p.fingerprint() for u, p in working.items()}
    master_fp = {u: p.fingerprint() for u, p in master.items()}

    # Leave the conflict unresolved (skip).
    plan.conflicts[0].resolution = rc.RES_SKIP
    nb = rc.compute_next_base(plan, base, working_fp, master_fp)
    check(nb["f1"].equals(working["f1"].fingerprint()), "cnb: update -> working")
    check(nb["f3"].equals(working["f3"].fingerprint()), "cnb: insert added")
    check("f2" not in nb, "cnb: delete dropped from base")
    check(nb["fc"].equals(base["fc"]), "cnb: skipped conflict KEEPS old base")
    check(nb["fm"].equals(master["fm"].fingerprint()),
          "cnb: master-only converges to master")

    # Resolve the conflict as a field-merge -> base converges to the merged state.
    plan.conflicts[0].resolution = rc.RES_FIELD_MERGE
    nb2 = rc.compute_next_base(plan, base, working_fp, master_fp)
    merged_fp = plan.conflicts[0].merge.merged_payload().fingerprint()
    check(nb2["fc"].equals(merged_fp), "cnb: resolved conflict converges to merge")

    # take_master must KEEP the old base (no write-back exists to make it
    # permanent) so the conflict re-surfaces instead of silently re-applying
    # the working edit next sync.
    plan.conflicts[0].resolution = rc.RES_TAKE_MASTER
    nb3 = rc.compute_next_base(plan, base, working_fp, master_fp)
    check(nb3["fc"].equals(base["fc"]),
          "cnb: take_master keeps OLD base (conflict re-surfaces, no silent re-apply)")


def test_take_master_update_delete_no_resurrection():
    """working edited a feature master deleted; take_master must NOT resurrect
    it on the next sync (the old bug popped it from base -> re-inserted)."""
    base = {"f1": basefp("f1", A=1)}
    working = {"f1": payload("f1", A=2)}     # working edited it
    master = {}                              # master deleted it (absent)
    plan = rc.classify("L", "UUID", base, working, master)
    check(len(plan.conflicts) == 1
          and plan.conflicts[0].type == rc.CONFLICT_UPDATE_DELETE,
          "update/delete conflict detected")
    plan.conflicts[0].resolution = rc.RES_TAKE_MASTER     # keep the deletion
    working_fp = {u: p.fingerprint() for u, p in working.items()}
    nb = rc.compute_next_base(plan, base, working_fp, {})
    check("f1" in nb and nb["f1"].equals(base["f1"]),
          "take_master keeps f1 in base -> re-surfaces, does not resurrect")


def main():
    tests = [
        test_hash_excludes_and_normalises,
        test_diff,
        test_classify_clean_paths,
        test_classify_conflicts,
        test_insert_insert,
        test_master_only_change_is_noop,
        test_reappend_without_loss,
        test_synthesize_base_legacy_first_sync,
        test_field_hash_decomposition,
        test_auto_merge_disjoint,
        test_hard_conflict_field_detail_and_resolutions,
        test_fingerprint_only_master_falls_back,
        test_compute_next_base_partial,
        test_take_master_update_delete_no_resurrection,
    ]
    for t in tests:
        print(f"- {t.__name__}")
        t()
    print(f"\n{_passed} checks passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
