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
    field_hash,
    compute_field_hashes,
    fingerprint_attrs,
)
from .diff_backend import FeatureDelta, Changeset, PyDiffBackend, diff_fingerprints
from .merge3 import compute_merge, FieldMerge
from .lineage import (LineageConfig, SplitGroup, MergeGroup, detect_lineage,
                      stamp_accepted, carry_attrs)
from .reconcile import (
    Op,
    ConflictRecord,
    ReconcilePlan,
    classify,
    compute_next_base,
    conflict_to_op,
    OP_INSERT,
    OP_UPDATE,
    OP_DELETE,
    RES_TAKE_WORKING,
    RES_TAKE_MASTER,
    RES_FIELD_MERGE,
    RES_SKIP,
    CONFLICT_UPDATE_UPDATE,
    CONFLICT_UPDATE_DELETE,
    CONFLICT_DELETE_UPDATE,
    CONFLICT_INSERT_INSERT,
    CONFLICT_BLANKING,
)

__all__ = [
    "FeatureFingerprint",
    "FeaturePayload",
    "LayerSnapshot",
    "attr_hash",
    "geom_hash",
    "field_hash",
    "compute_field_hashes",
    "fingerprint_attrs",
    "FeatureDelta",
    "Changeset",
    "PyDiffBackend",
    "diff_fingerprints",
    "compute_merge",
    "FieldMerge",
    "LineageConfig",
    "SplitGroup",
    "MergeGroup",
    "detect_lineage",
    "stamp_accepted",
    "carry_attrs",
    "Op",
    "ConflictRecord",
    "ReconcilePlan",
    "classify",
    "compute_next_base",
    "conflict_to_op",
    "OP_INSERT",
    "OP_UPDATE",
    "OP_DELETE",
    "RES_TAKE_WORKING",
    "RES_TAKE_MASTER",
    "RES_FIELD_MERGE",
    "RES_SKIP",
    "CONFLICT_UPDATE_UPDATE",
    "CONFLICT_UPDATE_DELETE",
    "CONFLICT_DELETE_UPDATE",
    "CONFLICT_INSERT_INSERT",
    "CONFLICT_BLANKING",
]
