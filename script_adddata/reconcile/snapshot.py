#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Content fingerprinting and base-snapshot capture for reconcile.

A *fingerprint* is a stable content hash of one feature, split into an
attribute hash and an independent geometry hash so "moved a vertex" and
"edited a field" classify separately. A *snapshot* is a per-layer map of
UUID -> fingerprint, persisted as JSON beside the master (the common
ancestor for the three-way merge).

This module has NO top-level QGIS import: the hashing helpers are pure
Python (unit-testable headlessly). `capture_layer` is the only QGIS-bound
function and imports QGIS lazily.

Hashing rules (must stay consistent across capture sites or every feature
reads as "changed"):
- Attribute hash excludes the UUID field (it's the key), the geometry
  column, and all housekeeping columns (``lgs_*``, ``data_added_*``).
- Values are normalised exactly like hardcode_data: None / QVariant-null /
  blank / the literal "NULL" all collapse to "", everything else is
  str(value).strip(). This absorbs int/str drift and NULL/blank drift so
  there are no false changes.
- Geometry hash is sha1 of the WKB. Callers that compare across CRSes must
  pass a transform so every site hashes geometry in the SAME (master) CRS.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Housekeeping column prefixes never included in the content hash.
HOUSEKEEPING_PREFIXES = ("lgs_", "data_added_")


def is_empty(value) -> bool:
    """True for None, QVariant null, blank strings and the literal 'NULL'.

    Mirrors hardcode_data.analysis.is_empty so hashes match what that tool
    considers "empty". Kept local (pure) so this module imports without QGIS.
    """
    if value is None:
        return True
    if hasattr(value, "isNull"):
        try:
            return value.isNull()
        except Exception:
            pass
    text = str(value).strip()
    return text == "" or text == "NULL"


def norm_value(value) -> str:
    """Normalise a single attribute value for hashing/comparison."""
    return "" if is_empty(value) else str(value).strip()


def _is_excluded(name: str, uuid_field: str, geom_field: str) -> bool:
    if name == uuid_field or name == geom_field:
        return True
    lname = name.lower()
    return any(lname.startswith(p) for p in HOUSEKEEPING_PREFIXES)


def attr_hash(attrs: Dict[str, object], uuid_field: str = "UUID",
              geom_field: str = "geom") -> str:
    """Stable sha1 over the canonically-ordered, normalised content attrs.

    `attrs` is a plain {field_name: value} dict. Excluded fields (UUID,
    geometry, housekeeping) are dropped before hashing.
    """
    items = [
        (name, norm_value(value))
        for name, value in attrs.items()
        if not _is_excluded(name, uuid_field, geom_field)
    ]
    items.sort(key=lambda kv: kv[0])
    canonical = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def geom_hash(wkb: Optional[bytes]) -> Optional[str]:
    """sha1 of geometry WKB, or None for no/empty geometry."""
    if not wkb:
        return None
    if isinstance(wkb, str):
        wkb = wkb.encode("utf-8")
    return hashlib.sha1(wkb).hexdigest()


@dataclass
class FeatureFingerprint:
    """Content fingerprint of one feature (no payload)."""
    attr_hash: str
    geom_hash: Optional[str] = None
    wkb_type: Optional[str] = None

    def to_dict(self) -> dict:
        d = {"hash": self.attr_hash}
        if self.geom_hash is not None:
            d["geom_hash"] = self.geom_hash
        if self.wkb_type is not None:
            d["wkb_type"] = self.wkb_type
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FeatureFingerprint":
        return cls(
            attr_hash=d.get("hash", ""),
            geom_hash=d.get("geom_hash"),
            wkb_type=d.get("wkb_type"),
        )

    def equals(self, other: "FeatureFingerprint") -> bool:
        return (self.attr_hash == other.attr_hash
                and self.geom_hash == other.geom_hash)


@dataclass
class FeaturePayload:
    """Full in-memory feature (used for both fingerprinting and commit).

    Captured from a working layer; never serialised to JSON. `attrs` holds
    raw values keyed by field name; `wkb` is geometry already transformed to
    the master CRS (or None).
    """
    uuid: str
    attrs: Dict[str, object]
    wkb: Optional[bytes] = None
    wkb_type: Optional[str] = None
    fid: Optional[int] = None
    uuid_field: str = "UUID"
    geom_field: str = "geom"

    def fingerprint(self) -> FeatureFingerprint:
        return FeatureFingerprint(
            attr_hash=attr_hash(self.attrs, self.uuid_field, self.geom_field),
            geom_hash=geom_hash(self.wkb),
            wkb_type=self.wkb_type,
        )


def fingerprint_attrs(attrs: Dict[str, object], wkb: Optional[bytes] = None,
                      uuid_field: str = "UUID", geom_field: str = "geom",
                      wkb_type: Optional[str] = None) -> FeatureFingerprint:
    """Convenience: build a fingerprint from a plain attrs dict (+ optional wkb)."""
    return FeatureFingerprint(
        attr_hash=attr_hash(attrs, uuid_field, geom_field),
        geom_hash=geom_hash(wkb),
        wkb_type=wkb_type,
    )


@dataclass
class LayerSnapshot:
    """Per-layer UUID -> fingerprint map (one layer of a base snapshot)."""
    layer_name: str
    uuid_field: str = "UUID"
    features: Dict[str, FeatureFingerprint] = field(default_factory=dict)
    # UUIDs seen with no/blank value or duplicated, recorded for reporting.
    skipped_no_uuid: int = 0
    duplicate_uuids: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "uuid_field": self.uuid_field,
            "features": {u: fp.to_dict() for u, fp in self.features.items()},
        }

    @classmethod
    def from_dict(cls, layer_name: str, d: dict) -> "LayerSnapshot":
        feats = {
            u: FeatureFingerprint.from_dict(fp)
            for u, fp in (d.get("features") or {}).items()
        }
        return cls(layer_name=layer_name,
                   uuid_field=d.get("uuid_field", "UUID"),
                   features=feats)


def snapshot_from_payloads(layer_name: str, uuid_field: str,
                           payloads: Dict[str, FeaturePayload]) -> LayerSnapshot:
    """Derive a fingerprint-only LayerSnapshot from captured payloads."""
    snap = LayerSnapshot(layer_name=layer_name, uuid_field=uuid_field)
    for u, p in payloads.items():
        snap.features[u] = p.fingerprint()
    return snap


# --------------------------------------------------------------------------
# QGIS-bound capture (lazy import; not exercised in headless unit tests)
# --------------------------------------------------------------------------

def capture_layer(layer, uuid_field: str = "UUID",
                  geom_field: str = "geom",
                  transform=None,
                  include_geometry: bool = True
                  ) -> Tuple[Dict[str, "FeaturePayload"], dict]:
    """Read a QgsVectorLayer into {uuid: FeaturePayload} (+ a report dict).

    `transform` (a QgsCoordinateTransform or None) is applied to every
    geometry before WKB extraction so geometry hashes are comparable across
    CRSes — pass the source->master transform when capturing a working layer.

    Returns (payloads, report) where report = {
        'skipped_no_uuid': int, 'duplicate_uuids': [uuid, ...],
        'total': int, 'geom_field': str }.
    Features with a blank UUID are skipped (and counted); the FIRST feature
    for a duplicated UUID wins and later ones are recorded as duplicates.
    """
    payloads: Dict[str, FeaturePayload] = {}
    duplicates: List[str] = []
    skipped_no_uuid = 0
    total = 0

    fields = layer.fields()
    field_names = [f.name() for f in fields]
    # Resolve the actual geometry column name from the provider if possible.
    try:
        gname = layer.dataProvider().geometryColumnName() or geom_field
        if gname:
            geom_field = gname
    except Exception:
        pass

    uuid_idx = fields.indexOf(uuid_field)

    for feat in layer.getFeatures():
        total += 1
        raw_uuid = feat.attribute(uuid_idx) if uuid_idx != -1 else None
        if is_empty(raw_uuid):
            skipped_no_uuid += 1
            continue
        u = str(raw_uuid).strip()
        if u in payloads:
            duplicates.append(u)
            continue

        attrs = {}
        feat_attrs = feat.attributes()
        for i, name in enumerate(field_names):
            attrs[name] = feat_attrs[i]

        wkb = None
        wkb_type = None
        if include_geometry and feat.hasGeometry():
            geom = feat.geometry()
            if transform is not None:
                try:
                    geom = QgsGeometry(geom)  # copy so we don't mutate the layer
                    geom.transform(transform)
                except Exception:
                    pass
            if geom is not None and not geom.isNull() and not geom.isEmpty():
                try:
                    wkb = bytes(geom.asWkb())
                except Exception:
                    wkb = None
                try:
                    wkb_type = QgsWkbTypes.displayString(geom.wkbType())
                except Exception:
                    wkb_type = None

        payloads[u] = FeaturePayload(
            uuid=u, attrs=attrs, wkb=wkb, wkb_type=wkb_type,
            fid=feat.id(), uuid_field=uuid_field, geom_field=geom_field,
        )

    report = {
        "total": total,
        "skipped_no_uuid": skipped_no_uuid,
        "duplicate_uuids": duplicates,
        "geom_field": geom_field,
    }
    return payloads, report


# Lazy QGIS symbols used only inside capture_layer; imported on first use so
# the module imports cleanly without QGIS for headless testing.
try:  # pragma: no cover - exercised only inside QGIS
    from qgis.core import QgsGeometry, QgsWkbTypes
except Exception:  # pragma: no cover
    QgsGeometry = None
    QgsWkbTypes = None
