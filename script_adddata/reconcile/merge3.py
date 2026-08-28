#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Field-level three-way merge (pure, no QGIS).

Given a base fingerprint (with per-field hashes), the working payload and the
master payload for ONE feature edited on both sides, work out — per field —
which side changed it relative to the common ancestor:

- a field only the working side changed     -> take working's value
- a field only the master side changed      -> keep master's value
- a field both changed to the SAME value     -> converged, no clash
- a field both changed to DIFFERENT values   -> a *hard* clash

If there are no hard clashes (and geometry didn't change incompatibly on both
sides) the feature is **auto-mergeable**: working's independent edits and
master's independent edits are combined with no human decision. If there are
hard clashes it is a real **conflict** that needs a resolution; the default
``field_merge`` rule keeps both sides' independent edits and lets working win
the clashing fields (the field mapper's latest value), which a human can
override per conflict in the UI.

Requires the base fingerprint to carry ``field_hashes`` (written by snapshots
created after the per-field-hash upgrade) and BOTH sides to be full payloads.
When that information is missing, ``compute_merge`` returns ``None`` and the
caller falls back to a whole-feature conflict — so it is fully back-compatible
with bases written by the MVP.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

try:  # package context
    from .snapshot import (norm_value, field_hash, _is_excluded,
                           geom_hash, FeaturePayload, FeatureFingerprint)
except ImportError:  # standalone (headless tests)
    from snapshot import (norm_value, field_hash, _is_excluded,
                          geom_hash, FeaturePayload, FeatureFingerprint)


# Geometry provenance for a merged feature.
GEOM_NONE = "none"        # neither side changed geometry — keep master's
GEOM_WORKING = "working"  # take working's geometry
GEOM_MASTER = "master"    # master changed geometry, working didn't — keep it

_EMPTY_HASH = field_hash("")


@dataclass
class FieldMerge:
    """The result of a per-field three-way merge for one feature."""
    uuid: str
    merged_attrs: Dict[str, object]            # full attrs to write to master
    work_fields: List[str] = field(default_factory=list)   # working-only edits
    master_fields: List[str] = field(default_factory=list)  # master-only edits
    hard_fields: List[str] = field(default_factory=list)    # both, differing
    geom_from: str = GEOM_NONE
    geom_conflict: bool = False                 # both changed geometry, differ
    # Per hard field: {"base"?: , "working": , "master": } display strings.
    field_values: Dict[str, dict] = field(default_factory=dict)
    working_payload: Optional[FeaturePayload] = None
    master_payload: Optional[FeaturePayload] = None
    working_wkb: Optional[bytes] = None
    working_wkb_type: Optional[str] = None
    master_wkb_type: Optional[str] = None

    def is_auto_mergeable(self) -> bool:
        """No human decision needed: no field clash and no geometry clash."""
        return not self.hard_fields and not self.geom_conflict

    def merged_payload(self, geom_choice: Optional[str] = None) -> FeaturePayload:
        """Build the payload to apply to master.

        geom_choice overrides which geometry wins (used by the UI when a human
        picks take-master geometry); defaults to this merge's geom_from.
        """
        choice = geom_choice or self.geom_from
        wkb = self.working_wkb if choice == GEOM_WORKING else None
        return FeaturePayload(
            uuid=self.uuid,
            attrs=dict(self.merged_attrs),
            wkb=wkb,
            wkb_type=self.working_wkb_type if choice == GEOM_WORKING
            else self.master_wkb_type,
            uuid_field=(self.master_payload.uuid_field
                        if self.master_payload else "UUID"),
            geom_field=(self.master_payload.geom_field
                        if self.master_payload else "geom"),
        )


def _content_fields(working: FeaturePayload, master: FeaturePayload,
                    uuid_field: str, geom_field: str) -> List[str]:
    seen = []
    for name in list(working.attrs.keys()) + list(master.attrs.keys()):
        if name in seen:
            continue
        if _is_excluded(name, uuid_field, geom_field):
            continue
        seen.append(name)
    return seen


def compute_merge(base_fp: Optional[FeatureFingerprint],
                  working: FeaturePayload,
                  master: FeaturePayload) -> Optional[FieldMerge]:
    """Three-way field merge for one feature, or None if not possible.

    None means the base lacks per-field hashes (legacy base) — the caller
    should fall back to a whole-feature conflict.
    """
    if base_fp is None or base_fp.field_hashes is None:
        return None
    if working is None or master is None:
        return None

    base_fh = base_fp.field_hashes
    uuid_field = master.uuid_field or "UUID"
    geom_field = master.geom_field or "geom"

    merged = dict(master.attrs)          # start from master's current values
    work_fields: List[str] = []
    master_fields: List[str] = []
    hard_fields: List[str] = []
    field_values: Dict[str, dict] = {}

    for name in _content_fields(working, master, uuid_field, geom_field):
        bh = base_fh.get(name, _EMPTY_HASH)
        wv = working.attrs.get(name)
        mv = master.attrs.get(name)
        wh = field_hash(wv)
        mh = field_hash(mv)
        w_ch = wh != bh
        m_ch = mh != bh

        if w_ch and m_ch:
            if wh == mh:
                merged[name] = wv            # both moved to the same value
            else:
                hard_fields.append(name)
                merged[name] = wv            # default: working wins the clash
                field_values[name] = {"working": norm_value(wv),
                                       "master": norm_value(mv)}
        elif w_ch:
            work_fields.append(name)
            merged[name] = wv
        elif m_ch:
            master_fields.append(name)
            merged[name] = mv                # already master's value
        # else: untouched on both sides — keep master's value

    # --- geometry (hashed independently of attributes) ---
    base_geom = base_fp.geom_hash
    w_geom = geom_hash(working.wkb)
    m_geom = geom_hash(master.wkb)
    w_geom_ch = w_geom != base_geom
    m_geom_ch = m_geom != base_geom
    geom_conflict = False
    if w_geom_ch and m_geom_ch and w_geom != m_geom:
        geom_conflict = True
        geom_from = GEOM_WORKING             # default: working geometry wins
    elif w_geom_ch:
        geom_from = GEOM_WORKING
    elif m_geom_ch:
        geom_from = GEOM_MASTER
    else:
        geom_from = GEOM_NONE

    return FieldMerge(
        uuid=working.uuid,
        merged_attrs=merged,
        work_fields=sorted(work_fields),
        master_fields=sorted(master_fields),
        hard_fields=sorted(hard_fields),
        geom_from=geom_from,
        geom_conflict=geom_conflict,
        field_values=field_values,
        working_payload=working,
        master_payload=master,
        working_wkb=working.wkb,
        working_wkb_type=working.wkb_type,
        master_wkb_type=master.wkb_type,
    )
