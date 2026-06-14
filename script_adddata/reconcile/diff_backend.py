#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Changeset computation: diff a base snapshot against a current state.

A *changeset* is a per-UUID map of FeatureDelta describing what changed
between a base (common ancestor) and a current state, with attribute and
geometry changes flagged independently.

`PyDiffBackend` is the default, pure-Python backend. An optional
`GeodiffBackend` may be added later behind the same interface; both return a
`Changeset`, so nothing downstream couples to the backend choice.

Pure module: no QGIS import. Operates on the fingerprint maps produced by
`snapshot` (which is where any QGIS reading already happened).
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

try:  # package context (inside QGIS)
    from .snapshot import FeatureFingerprint, LayerSnapshot, FeaturePayload
except ImportError:  # standalone (headless tests)
    from snapshot import FeatureFingerprint, LayerSnapshot, FeaturePayload

OP_INSERT = "insert"
OP_UPDATE = "update"
OP_DELETE = "delete"


@dataclass
class FeatureDelta:
    """One feature's change between base and current."""
    uuid: str
    op: str                      # insert | update | delete
    attr_changed: bool = False
    geom_changed: bool = False
    new_fingerprint: Optional[FeatureFingerprint] = None  # None for delete

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid,
            "op": self.op,
            "attr_changed": self.attr_changed,
            "geom_changed": self.geom_changed,
        }


@dataclass
class Changeset:
    """All deltas for one layer (base -> current), keyed by UUID."""
    layer: str
    deltas: Dict[str, FeatureDelta] = field(default_factory=dict)

    def __len__(self):
        return len(self.deltas)

    def of_op(self, op: str):
        return [d for d in self.deltas.values() if d.op == op]

    def get(self, uuid: str) -> Optional[FeatureDelta]:
        return self.deltas.get(uuid)


def _as_fingerprint_map(state) -> Dict[str, FeatureFingerprint]:
    """Accept a LayerSnapshot, a {uuid: FeatureFingerprint} dict, or a
    {uuid: FeaturePayload} dict and return a {uuid: FeatureFingerprint} map."""
    if isinstance(state, LayerSnapshot):
        return dict(state.features)
    if isinstance(state, dict):
        out: Dict[str, FeatureFingerprint] = {}
        for u, v in state.items():
            if isinstance(v, FeatureFingerprint):
                out[u] = v
            elif isinstance(v, FeaturePayload):
                out[u] = v.fingerprint()
            else:
                raise TypeError(f"Unsupported state value for {u!r}: {type(v)}")
        return out
    raise TypeError(f"Unsupported state type: {type(state)}")


def diff_fingerprints(base, current, layer: str = "") -> Changeset:
    """Diff two states into a Changeset.

    `base` and `current` may each be a LayerSnapshot, a {uuid: fingerprint}
    map, or a {uuid: FeaturePayload} map. UUID is identity throughout.
    """
    base_fp = _as_fingerprint_map(base)
    cur_fp = _as_fingerprint_map(current)
    cs = Changeset(layer=layer)

    for u, fp in cur_fp.items():
        b = base_fp.get(u)
        if b is None:
            cs.deltas[u] = FeatureDelta(
                uuid=u, op=OP_INSERT, attr_changed=True,
                geom_changed=fp.geom_hash is not None,
                new_fingerprint=fp,
            )
        elif not b.equals(fp):
            cs.deltas[u] = FeatureDelta(
                uuid=u, op=OP_UPDATE,
                attr_changed=(b.attr_hash != fp.attr_hash),
                geom_changed=(b.geom_hash != fp.geom_hash),
                new_fingerprint=fp,
            )
        # else: unchanged -> no delta

    for u in base_fp:
        if u not in cur_fp:
            cs.deltas[u] = FeatureDelta(uuid=u, op=OP_DELETE)

    return cs


class PyDiffBackend:
    """Default pure-Python diff backend."""

    name = "python"

    def diff(self, base, current, layer: str = "") -> Changeset:
        return diff_fingerprints(base, current, layer)
