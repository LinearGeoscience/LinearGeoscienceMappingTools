"""
Reconcile: UUID-keyed, snapshot-based three-way merge between QField working
templates and the QGIS master GeoPackage.

Replaces the insert-only append model with a three-way reconcile that can
propagate updates and deletes, re-sync an edited template without losing
edits, and (later phases) detect conflicts and split/merge lineage.

Design split (so the core is testable without QGIS):
- Pure logic, no QGIS import: hashing + fingerprints (`snapshot` helpers),
  changeset diff (`diff_backend`), three-way classification (`reconcile`),
  the sidecar JSON stores (`checkout`, `changelog`).
- QGIS-bound (imported lazily inside functions): capturing features from a
  layer (`snapshot.capture_layer`), applying a plan to master (`commit`),
  and the one-time `migrate` setup.

See the plan/design notes for the full classification table and phasing.
"""

from .snapshot import (
    FeatureFingerprint,
    FeaturePayload,
    LayerSnapshot,
    attr_hash,
    geom_hash,
    fingerprint_attrs,
)
from .diff_backend import FeatureDelta, Changeset, PyDiffBackend, diff_fingerprints
from .reconcile import (
    Op,
    ConflictRecord,
    ReconcilePlan,
    classify,
    OP_INSERT,
    OP_UPDATE,
    OP_DELETE,
)

__all__ = [
    "FeatureFingerprint",
    "FeaturePayload",
    "LayerSnapshot",
    "attr_hash",
    "geom_hash",
    "fingerprint_attrs",
    "FeatureDelta",
    "Changeset",
    "PyDiffBackend",
    "diff_fingerprints",
    "Op",
    "ConflictRecord",
    "ReconcilePlan",
    "classify",
    "OP_INSERT",
    "OP_UPDATE",
    "OP_DELETE",
]
