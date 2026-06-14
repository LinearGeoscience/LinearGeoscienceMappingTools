#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Headless tests for split/merge lineage (no QGIS): the pure threshold evaluator,
attribute carry, and stamp_accepted's op mutation (incl. no-alias copy).

The geometry-bound detect_lineage itself needs QGIS and is exercised by
tests/reconcile/test_reconcile_qgis.py.

Run:  python tests/reconcile/test_reconcile_lineage.py
"""

import os
import sys

RECONCILE_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "script_adddata", "reconcile"))
sys.path.insert(0, RECONCILE_DIR)

import lineage          # noqa: E402
import reconcile as rc  # noqa: E402
from lineage import (LineageConfig, SplitGroup, MergeGroup, carry_attrs,
                     stamp_accepted, _evaluate)                       # noqa: E402
from snapshot import FeaturePayload                                   # noqa: E402

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
    return FeaturePayload(uuid=uuid, attrs=a, uuid_field="UUID", geom_field="geom")


def test_evaluate_thresholds():
    cfg = LineageConfig()  # cover 0.85, inside 0.90, min_parts 2
    # Two children fully inside a parent of area 100 -> split.
    parts = {"c1": (50.0, 50.0), "c2": (50.0, 50.0)}
    res = _evaluate(100.0, parts, cfg)
    check(res is not None and sorted(res[0]) == ["c1", "c2"],
          "two fully-inside parts -> split group")
    check(abs(res[1] - 1.0) < 1e-9, "cover fraction is 1.0")

    # Only one qualifying part -> below min_parts -> None.
    check(_evaluate(100.0, {"c1": (50.0, 50.0)}, cfg) is None,
          "single part is not a split")

    # Parts that stick out (inside fraction < 0.9) don't belong.
    check(_evaluate(100.0, {"c1": (50.0, 40.0), "c2": (50.0, 40.0)}, cfg) is None,
          "parts not mostly-inside are rejected")

    # Mostly-inside but together cover < 0.85 of the whole -> None.
    check(_evaluate(100.0, {"c1": (30.0, 30.0), "c2": (30.0, 30.0)}, cfg) is None,
          "insufficient coverage is not a split")

    # Zero/negative total area is never a split.
    check(_evaluate(0.0, {"c1": (1.0, 1.0), "c2": (1.0, 1.0)}, cfg) is None,
          "zero-area whole -> None")


def test_carry_attrs():
    child = payload("c1", Rock="", Dip=15, Note="")
    parent = payload("p1", Rock="granite", Dip=99, Note="seen")
    filled = carry_attrs(child, [parent])
    check(child.attrs["Rock"] == "granite", "empty child field filled from parent")
    check(str(child.attrs["Dip"]) == "15", "non-empty child field NOT overwritten")
    check(child.attrs["Note"] == "seen", "second empty field filled")
    check(set(filled) == {"Rock", "Note"}, "filled list reports carried fields")

    # First non-empty parent wins; UUID never carried.
    child2 = payload("c2", Rock="")
    p_a = payload("pa", Rock="")
    p_b = payload("pb", Rock="basalt")
    carry_attrs(child2, [p_a, p_b])
    check(child2.attrs["Rock"] == "basalt", "first non-empty parent value wins")
    check(child2.attrs["UUID"] == "c2", "UUID is never carried")


def test_stamp_accepted_split_and_copy():
    child = payload("c1", Rock="")
    op = rc.Op(uuid="c1", op=rc.OP_INSERT, payload=child)
    plan = rc.ReconcilePlan(layer="3 - Linework")
    plan.clean_inserts = [op]
    plan.splits = [SplitGroup("3 - Linework", "p1", ["c1"], 0.95)]
    parents = {"p1": payload("p1", Rock="granite")}

    stamp_accepted(plan, parents)
    check(op.lgs_parent_uuid == "p1", "split stamps lgs_parent_uuid on the child")
    check(op.payload.attrs["Rock"] == "granite", "split carries parent attrs")
    # The shared working capture must be untouched (stamp_accepted copies).
    check(child.attrs["Rock"] == "", "original working payload NOT mutated (no alias)")

    # Rejected group leaves everything alone.
    child2 = payload("c2", Rock="")
    op2 = rc.Op(uuid="c2", op=rc.OP_INSERT, payload=child2)
    plan2 = rc.ReconcilePlan(layer="3 - Linework")
    plan2.clean_inserts = [op2]
    g = SplitGroup("3 - Linework", "p2", ["c2"], 0.95, accepted=False)
    plan2.splits = [g]
    stamp_accepted(plan2, {"p2": payload("p2", Rock="schist")})
    check(op2.lgs_parent_uuid is None, "rejected split does not stamp")
    check(op2.payload.attrs["Rock"] == "", "rejected split does not carry")


def test_stamp_accepted_merge():
    survivor = payload("s1", Rock="")
    op = rc.Op(uuid="s1", op=rc.OP_INSERT, payload=survivor)
    plan = rc.ReconcilePlan(layer="2 - Overlay")
    plan.clean_inserts = [op]
    plan.merges = [MergeGroup("2 - Overlay", "s1", ["p1", "p2"], 0.9)]
    parents = {"p1": payload("p1", Rock="granite"),
               "p2": payload("p2", Rock="basalt")}
    stamp_accepted(plan, parents)
    check(op.lgs_merged_from == "p1,p2", "merge stamps lgs_merged_from")
    check(op.payload.attrs["Rock"] == "granite",
          "merge carries first parent's value into empty survivor field")


def test_blanking_rule():
    """A working update that ONLY empties a field that holds a value in master
    is held as a conflict, not a clean update (protects carried lineage attrs)."""
    base = {"f1": payload("f1", Rock="granite", Dip=20).fingerprint()}
    working = {"f1": payload("f1", Rock="", Dip=20)}     # cleared Rock only
    master = {"f1": payload("f1", Rock="granite", Dip=20)}
    plan = rc.classify("L", "UUID", base, working, master)
    check(not plan.clean_updates, "pure blanking is NOT a clean update")
    check(len(plan.conflicts) == 1
          and plan.conflicts[0].type == rc.CONFLICT_BLANKING,
          "pure blanking -> blanking conflict")
    check(plan.conflicts[0].effective_resolution() == rc.RES_SKIP,
          "blanking conflict defaults to skip (no silent wipe)")
    # take_working still lets the user apply the clear deliberately.
    plan.conflicts[0].resolution = rc.RES_TAKE_WORKING
    op = rc.conflict_to_op(plan.conflicts[0])
    check(op is not None and op.op == rc.OP_UPDATE,
          "take_working applies the blanking on request")

    # A real edit alongside a clear is a normal update, not a blanking conflict.
    working2 = {"f1": payload("f1", Rock="", Dip=99)}    # cleared Rock, changed Dip
    plan2 = rc.classify("L", "UUID", base, working2, master)
    check([o.uuid for o in plan2.clean_updates] == ["f1"],
          "clear + real edit is a normal clean update")


def test_blanking_on_legacy_base():
    """Blanking protection must also work for a legacy base WITHOUT per-field
    hashes — the check compares working to the (unchanged) master, not to base."""
    legacy = payload("f1", Rock="granite", Dip=20).fingerprint()
    legacy.field_hashes = None                 # simulate a pre-upgrade base
    base = {"f1": legacy}
    working = {"f1": payload("f1", Rock="", Dip=20)}      # cleared Rock
    master = {"f1": payload("f1", Rock="granite", Dip=20)}
    plan = rc.classify("L", "UUID", base, working, master)
    check(any(c.uuid == "f1" and c.type == rc.CONFLICT_BLANKING
              for c in plan.conflicts),
          "blanking detected even when the base lacks field_hashes")
    check(not plan.clean_updates,
          "legacy-base blanking is held, not silently applied")


def test_blanking_ignores_master_only_field():
    """_is_pure_blanking must only consider fields the WORKING side carries:
    a field present only in master (schema divergence) must not be mis-counted
    as an emptied field. (Unit-tests the helper directly; the integration path
    never reaches it for this case because a master-only column also changes
    master's attr hash, routing it to update/update instead.)"""
    master = payload("f1", Rock="granite")
    master.attrs["Extra"] = "master-only-value"     # column the template lacks
    # working changed Rock to a real new value -> a real edit, not blanking.
    working = payload("f1", Rock="basalt")
    check(rc._is_pure_blanking(working, master, None) is False,
          "real edit + master-only field -> not blanking")
    # working genuinely blanks Rock -> still detected; Extra is ignored.
    working2 = payload("f1", Rock="")
    check(rc._is_pure_blanking(working2, master, None) is True,
          "genuine blanking detected; master-only field does not inflate it")


def main():
    tests = [
        test_evaluate_thresholds,
        test_carry_attrs,
        test_stamp_accepted_split_and_copy,
        test_stamp_accepted_merge,
        test_blanking_rule,
        test_blanking_on_legacy_base,
        test_blanking_ignores_master_only_field,
    ]
    for t in tests:
        print(f"- {t.__name__}")
        t()
    print(f"\n{_passed} checks passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
