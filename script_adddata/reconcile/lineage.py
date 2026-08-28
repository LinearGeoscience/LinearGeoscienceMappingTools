#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Split / merge lineage detection (Phase 3).

After the UUID-keyed classification, some changes are really one feature
becoming many (a SPLIT) or many becoming one (a MERGE) — but because the field
software hands the new parts fresh UUIDs, the UUID merge can only see them as
"some inserts" and "some deletes". This module looks at the *residual* —
working inserts (the new children) against the master geometry of the just-
deleted parents — and proposes split/merge groups on geometric overlap.

Nothing here is auto-applied: detection returns proposals that the preview UI
shows for confirm/reject. On accept the engine stamps lgs_parent_uuid /
lgs_merged_from and carries the parent's attributes into the child's EMPTY
fields (a working blank is never overwritten with a parent value).

Design split, like snapshot.py:
- The geometric thresholds are decided by a PURE function (`_evaluate`) that
  takes pre-computed areas, so the decision logic is unit-testable headlessly.
- `detect_lineage` is the QGIS-bound wrapper (QgsGeometry + QgsSpatialIndex,
  mirroring map_cleaning/clipping/clipper_core.py) that computes the overlaps
  and calls the pure evaluator.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:  # package context
    from .snapshot import is_empty, _is_excluded, FeaturePayload
except ImportError:  # standalone (headless tests)
    from snapshot import is_empty, _is_excluded, FeaturePayload


@dataclass
class LineageConfig:
    cover_frac: float = 0.85   # fraction of the whole that the parts must cover
    inside_frac: float = 0.90  # fraction of a part that must lie inside the whole
    min_parts: int = 2         # a split/merge needs at least this many parts


@dataclass
class SplitGroup:
    """One parent feature split into several children."""
    layer: str
    parent_uuid: str
    child_uuids: List[str]
    cover_frac: float
    accepted: bool = True

    def to_dict(self) -> dict:
        return {"kind": "split", "layer": self.layer,
                "parent_uuid": self.parent_uuid,
                "child_uuids": list(self.child_uuids),
                "cover_frac": round(self.cover_frac, 4),
                "accepted": self.accepted}


@dataclass
class MergeGroup:
    """Several parent features merged into one survivor (a new child)."""
    layer: str
    survivor_uuid: str
    parent_uuids: List[str]
    cover_frac: float
    accepted: bool = True

    def to_dict(self) -> dict:
        return {"kind": "merge", "layer": self.layer,
                "survivor_uuid": self.survivor_uuid,
                "parent_uuids": list(self.parent_uuids),
                "cover_frac": round(self.cover_frac, 4),
                "accepted": self.accepted}


def _evaluate(total_area: float,
              parts: Dict[str, Tuple[float, float]],
              cfg: LineageConfig) -> Optional[Tuple[List[str], float]]:
    """Pure decision: does `parts` split/merge `total_area`?

    `parts` maps part_uuid -> (part_area, overlap_area_with_total). A part
    "belongs" if it lies mostly inside (overlap/part_area >= inside_frac). If
    at least `min_parts` belong and together they cover >= cover_frac of the
    total, return (belonging_uuids, cover_fraction); else None.
    """
    if total_area <= 0:
        return None
    belonging = [u for u, (pa, oa) in parts.items()
                 if pa > 0 and (oa / pa) >= cfg.inside_frac]
    if len(belonging) < cfg.min_parts:
        return None
    cover = sum(parts[u][1] for u in belonging) / total_area
    if cover >= cfg.cover_frac:
        return sorted(belonging), cover
    return None


def is_polygon(wkb_type: Optional[str]) -> bool:
    return bool(wkb_type) and "polygon" in wkb_type.lower()


def carry_attrs(child: FeaturePayload, parents: List[FeaturePayload]) -> List[str]:
    """Fill the child's EMPTY content fields from the parents. Returns filled.

    A field that already has a value in the child is never overwritten; the
    first parent with a non-empty value wins. UUID / geometry / housekeeping
    fields are never carried.
    """
    filled = []
    for name in list(child.attrs.keys()):
        if _is_excluded(name, child.uuid_field, child.geom_field):
            continue
        if not is_empty(child.attrs.get(name)):
            continue
        for p in parents:
            pv = p.attrs.get(name)
            if not is_empty(pv):
                child.attrs[name] = pv
                filled.append(name)
                break
    return filled


def _copy_payload(p: FeaturePayload) -> FeaturePayload:
    return FeaturePayload(uuid=p.uuid, attrs=dict(p.attrs), wkb=p.wkb,
                          wkb_type=p.wkb_type, fid=p.fid,
                          uuid_field=p.uuid_field, geom_field=p.geom_field)


# --------------------------------------------------------------------------
# QGIS-bound detection (lazy import; not exercised in headless unit tests)
# --------------------------------------------------------------------------

def detect_lineage(layer: str,
                   child_payloads: Dict[str, FeaturePayload],
                   parent_payloads: Dict[str, FeaturePayload],
                   cfg: Optional[LineageConfig] = None
                   ) -> Tuple[List[SplitGroup], List[MergeGroup]]:
    """Detect split/merge proposals (polygons only) from the residual.

    `child_payloads` are the working inserts; `parent_payloads` are the master
    geometries of the just-deleted features. Both carry WKB in the master CRS.
    Returns (splits, merges); a feature is consumed by at most one group.
    """
    cfg = cfg or LineageConfig()
    splits: List[SplitGroup] = []
    merges: List[MergeGroup] = []
    if QgsGeometry is None:  # no QGIS -> nothing to do
        return splits, merges

    child_geoms = _polygon_geoms(child_payloads)
    parent_geoms = _polygon_geoms(parent_payloads)
    if not child_geoms or not parent_geoms:
        return splits, merges

    consumed_children, consumed_parents = set(), set()

    # ---- SPLIT: one parent covered by >= min_parts children ----
    child_index, child_ids = _build_index(child_geoms)
    for puid, pgeom in parent_geoms.items():
        parea = pgeom.area()
        parts = {}
        for fid in child_index.intersects(pgeom.boundingBox()):
            cuid = child_ids.get(fid)
            if cuid is None or cuid in consumed_children:
                continue
            cg = child_geoms[cuid]
            oa = _overlap_area(pgeom, cg)
            if oa > 0:
                parts[cuid] = (cg.area(), oa)
        res = _evaluate(parea, parts, cfg)
        if res:
            quids, cover = res
            splits.append(SplitGroup(layer, puid, quids, cover))
            consumed_parents.add(puid)
            consumed_children.update(quids)

    # ---- MERGE: one child covered by >= min_parts parents ----
    avail_parents = {u: g for u, g in parent_geoms.items()
                     if u not in consumed_parents}
    if avail_parents:
        parent_index, parent_ids = _build_index(avail_parents)
        for cuid, cgeom in child_geoms.items():
            if cuid in consumed_children:
                continue
            carea = cgeom.area()
            parts = {}
            for fid in parent_index.intersects(cgeom.boundingBox()):
                puid = parent_ids.get(fid)
                if puid is None or puid in consumed_parents:
                    continue
                pg = parent_geoms[puid]
                oa = _overlap_area(cgeom, pg)
                if oa > 0:
                    parts[puid] = (pg.area(), oa)
            res = _evaluate(carea, parts, cfg)
            if res:
                puids, cover = res
                merges.append(MergeGroup(layer, cuid, puids, cover))
                consumed_children.add(cuid)
                consumed_parents.update(puids)

    splits.sort(key=lambda g: g.parent_uuid)
    merges.sort(key=lambda g: g.survivor_uuid)
    return splits, merges


def stamp_accepted(plan, parent_payloads: Dict[str, FeaturePayload]):
    """Apply accepted split/merge groups onto the plan's insert ops.

    Mutates a COPY of each affected child payload (never the shared working
    capture) so the carried attributes go to master while the base advance and
    next-sync diff still see the template's real (blank) values.
    """
    insert_by_uuid = {op.uuid: op for op in plan.clean_inserts}

    for g in plan.splits:
        if not getattr(g, "accepted", True):
            continue
        parent = parent_payloads.get(g.parent_uuid)
        for cuid in g.child_uuids:
            op = insert_by_uuid.get(cuid)
            if op is None:
                continue
            op.lgs_parent_uuid = g.parent_uuid
            if op.payload is not None and parent is not None:
                op.payload = _copy_payload(op.payload)
                carry_attrs(op.payload, [parent])

    for g in plan.merges:
        if not getattr(g, "accepted", True):
            continue
        op = insert_by_uuid.get(g.survivor_uuid)
        if op is None:
            continue
        op.lgs_merged_from = ",".join(g.parent_uuids)
        parents = [parent_payloads[p] for p in g.parent_uuids
                   if p in parent_payloads]
        if op.payload is not None and parents:
            op.payload = _copy_payload(op.payload)
            carry_attrs(op.payload, parents)


def _polygon_geoms(payloads: Dict[str, FeaturePayload]) -> Dict[str, object]:
    out = {}
    for u, p in payloads.items():
        if not is_polygon(p.wkb_type) or not p.wkb:
            continue
        g = QgsGeometry()
        g.fromWkb(p.wkb)
        if not g.isNull() and not g.isEmpty():
            out[u] = g
    return out


def _build_index(geoms: Dict[str, object]):
    index = QgsSpatialIndex()
    ids = {}
    for i, (u, g) in enumerate(geoms.items(), start=1):
        feat = QgsFeature(i)
        feat.setGeometry(g)
        index.insertFeature(feat)
        ids[i] = u
    return index, ids


def _overlap_area(a, b) -> float:
    try:
        if not a.intersects(b):
            return 0.0
        inter = a.intersection(b)
        if inter is None or inter.isNull() or inter.isEmpty():
            return 0.0
        return inter.area()
    except Exception:
        return 0.0


# Lazy QGIS symbols (imported on first use so the module imports without QGIS).
try:  # pragma: no cover - exercised only inside QGIS
    from qgis.core import QgsGeometry, QgsSpatialIndex, QgsFeature
except Exception:  # pragma: no cover
    QgsGeometry = None
    QgsSpatialIndex = None
    QgsFeature = None
