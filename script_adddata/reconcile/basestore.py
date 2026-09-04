#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Embedded base-snapshot store: the working copy carries its own ancestor.

Three hidden tables are stamped INSIDE each issued working GeoPackage:

    lgs_checkout   one row  - checkout identity (checkout_id, which master,
                              mapper, when, how the copy was made)
    lgs_base_meta  per layer - uuid field, capture time, feature count
    lgs_base       per feat  - the fingerprint map (the common ancestor)

and one inside the master:

    lgs_master     one row  - stable master_uid so a working copy can prove
                              which master it was issued from even after the
                              master file is renamed or moved

None of these are registered in ``gpkg_contents``, so OGR/QGIS/QField never
list them: to every mapping tool the working copy is an ordinary template.

This replaces the filename-stem-keyed JSON sidecars as the primary base
store (checkout.py keeps the sidecar functions as the legacy fallback and
the apply-time recovery mirror). Identity is ``checkout_id`` (uuid4), so
renamed files and same-named exports from different mappers can no longer
share or clobber a base.

Pure module (no QGIS): sqlite3 + json only, headless-testable. It stores
and loads fingerprints but NEVER computes them - hashing lives solely in
snapshot.py (capture_layer / FeaturePayload.fingerprint), because a second
sqlite-side hashing path would inevitably drift from QGIS value/WKB
stringification and make every feature classify as changed.
"""

import os
import json
import sqlite3
import uuid as uuid_module
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

try:  # package context
    from .snapshot import LayerSnapshot, FeatureFingerprint
except ImportError:  # standalone (headless tests)
    from snapshot import LayerSnapshot, FeatureFingerprint

SCHEMA_VERSION = "1.0"

CHECKOUT_TABLE = "lgs_checkout"
BASE_TABLE = "lgs_base"
BASE_META_TABLE = "lgs_base_meta"
MASTER_TABLE = "lgs_master"

# Every source_mode a checkout row may carry.
MODE_FULL = "full"          # full copy of the master
MODE_BLANK = "blank"        # schema/styles only, no features
MODE_CLIP = "clip"          # clipped area of the master
MODE_EXPORT = "export"      # stamped by the QField exporter
MODE_TEMPLATE = "template"  # stamped by the New Mapping Template loader


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(gpkg_path: str) -> sqlite3.Connection:
    # timeout=5 matches changelog._mirror_to_gpkg; enough to ride out a
    # brief writer (QGIS save, OneDrive touch) without hanging the UI.
    return sqlite3.connect(gpkg_path, timeout=5)


def _table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


# --------------------------------------------------------------------------
# lgs_checkout (working copy identity)
# --------------------------------------------------------------------------

_CHECKOUT_DDL = (
    f"CREATE TABLE IF NOT EXISTS {CHECKOUT_TABLE} ("
    "id INTEGER PRIMARY KEY CHECK (id = 1), "
    "schema_version TEXT NOT NULL, "
    "checkout_id TEXT NOT NULL, "
    "master_id TEXT, "
    "master_name TEXT, "
    "mapper TEXT, "
    "issued_utc TEXT NOT NULL, "
    "master_version INTEGER, "
    "source_mode TEXT, "
    "area_wkt TEXT)"
)

_CHECKOUT_COLS = ("schema_version", "checkout_id", "master_id", "master_name",
                  "mapper", "issued_utc", "master_version", "source_mode",
                  "area_wkt")


def has_checkout(gpkg_path: str) -> bool:
    """True if the gpkg carries an embedded checkout stamp."""
    if not os.path.exists(gpkg_path):
        return False
    try:
        con = _connect(gpkg_path)
    except sqlite3.Error:
        return False
    try:
        cur = con.cursor()
        if not _table_exists(cur, CHECKOUT_TABLE):
            return False
        cur.execute(f"SELECT 1 FROM {CHECKOUT_TABLE} WHERE id=1")
        return cur.fetchone() is not None
    except sqlite3.Error:
        return False
    finally:
        con.close()


def read_checkout(gpkg_path: str) -> Optional[dict]:
    """The checkout row as a dict, or None if the file was never stamped."""
    if not os.path.exists(gpkg_path):
        return None
    try:
        con = _connect(gpkg_path)
    except sqlite3.Error:
        return None
    try:
        cur = con.cursor()
        if not _table_exists(cur, CHECKOUT_TABLE):
            return None
        cur.execute(
            f"SELECT {', '.join(_CHECKOUT_COLS)} FROM {CHECKOUT_TABLE} "
            "WHERE id=1")
        row = cur.fetchone()
        if row is None:
            return None
        return dict(zip(_CHECKOUT_COLS, row))
    except sqlite3.Error:
        return None
    finally:
        con.close()


def write_checkout(gpkg_path: str, checkout: dict) -> dict:
    """Stamp (or restamp) the checkout identity. Returns the stored row.

    ``checkout`` may omit checkout_id/issued_utc/schema_version - they are
    generated. Raises sqlite3.Error on failure (e.g. locked file): stamping
    is the moment the whole system depends on, so it must not fail silently.
    """
    row = {
        "schema_version": SCHEMA_VERSION,
        "checkout_id": checkout.get("checkout_id") or str(uuid_module.uuid4()),
        "master_id": checkout.get("master_id"),
        "master_name": checkout.get("master_name"),
        "mapper": checkout.get("mapper", ""),
        "issued_utc": checkout.get("issued_utc") or _utc_now(),
        "master_version": checkout.get("master_version"),
        "source_mode": checkout.get("source_mode", ""),
        "area_wkt": checkout.get("area_wkt", ""),
    }
    con = _connect(gpkg_path)
    try:
        cur = con.cursor()
        cur.execute(_CHECKOUT_DDL)
        cur.execute(
            f"INSERT OR REPLACE INTO {CHECKOUT_TABLE} "
            f"(id, {', '.join(_CHECKOUT_COLS)}) "
            f"VALUES (1, {', '.join('?' for _ in _CHECKOUT_COLS)})",
            tuple(row[c] for c in _CHECKOUT_COLS))
        con.commit()
        return row
    finally:
        con.close()


def drop_embedded_tables(gpkg_path: str):
    """Remove any lgs_checkout/lgs_base tables (defensive, e.g. before
    restamping a copy-of-a-copy so a stale identity can't survive)."""
    con = _connect(gpkg_path)
    try:
        cur = con.cursor()
        for name in (CHECKOUT_TABLE, BASE_TABLE, BASE_META_TABLE):
            cur.execute(f"DROP TABLE IF EXISTS {name}")
        con.commit()
    finally:
        con.close()


# --------------------------------------------------------------------------
# lgs_base / lgs_base_meta (the embedded ancestor)
# --------------------------------------------------------------------------

_BASE_DDL = (
    f"CREATE TABLE IF NOT EXISTS {BASE_TABLE} ("
    "layer TEXT NOT NULL, "
    "uuid TEXT NOT NULL, "
    "attr_hash TEXT NOT NULL, "
    "geom_hash TEXT, "
    "wkb_type TEXT, "
    "field_hashes TEXT, "
    "PRIMARY KEY (layer, uuid))"
)

_BASE_META_DDL = (
    f"CREATE TABLE IF NOT EXISTS {BASE_META_TABLE} ("
    "layer TEXT PRIMARY KEY, "
    "uuid_field TEXT NOT NULL, "
    "captured_utc TEXT NOT NULL, "
    "master_version INTEGER, "
    "feature_count INTEGER)"
)


def write_base(gpkg_path: str, layers: Dict[str, LayerSnapshot],
               master_version: int = 0,
               captured_utc: Optional[str] = None) -> dict:
    """Write (replace wholesale) the embedded base snapshot.

    Refuses to write into a file with no checkout stamp - a legacy file must
    stay legacy, otherwise a half-stamped copy would look embedded to
    _resolve_base but carry no identity. One transaction: either the whole
    new base lands or none of it does.

    Returns {layer: feature_count}.
    """
    captured = captured_utc or _utc_now()
    con = _connect(gpkg_path)
    try:
        cur = con.cursor()
        if not _table_exists(cur, CHECKOUT_TABLE):
            raise ValueError(
                f"{os.path.basename(gpkg_path)} has no lgs_checkout stamp; "
                "write_checkout() must run before write_base()")
        cur.execute(_BASE_DDL)
        cur.execute(_BASE_META_DDL)
        counts = {}
        for name, snap in layers.items():
            cur.execute(f"DELETE FROM {BASE_TABLE} WHERE layer=?", (name,))
            rows = [
                (name, u, fp.attr_hash, fp.geom_hash, fp.wkb_type,
                 json.dumps(fp.field_hashes, ensure_ascii=False)
                 if fp.field_hashes is not None else None)
                for u, fp in snap.features.items()
            ]
            cur.executemany(
                f"INSERT INTO {BASE_TABLE} "
                "(layer, uuid, attr_hash, geom_hash, wkb_type, field_hashes) "
                "VALUES (?,?,?,?,?,?)", rows)
            cur.execute(
                f"INSERT OR REPLACE INTO {BASE_META_TABLE} "
                "(layer, uuid_field, captured_utc, master_version, "
                "feature_count) VALUES (?,?,?,?,?)",
                (name, snap.uuid_field, captured, master_version, len(rows)))
            counts[name] = len(rows)
        con.commit()
        return counts
    finally:
        con.close()


def read_base(gpkg_path: str) -> Optional[dict]:
    """Load the embedded base in the SAME shape as checkout.load_base():

        {"master_version_at_capture", "captured_utc", "mapper",
         "layers": {layer_name: {uuid: FeatureFingerprint}}}

    Returns None when the file has no embedded base (never stamped, or
    stamped but write_base never ran) so callers fall through to the legacy
    sidecar and then to synthesis. A recorded-but-empty layer comes back as
    an empty dict, preserving the "empty vs absent" distinction the engine
    relies on.
    """
    if not os.path.exists(gpkg_path):
        return None
    try:
        con = _connect(gpkg_path)
    except sqlite3.Error:
        return None
    try:
        cur = con.cursor()
        if not (_table_exists(cur, BASE_META_TABLE)
                and _table_exists(cur, BASE_TABLE)):
            return None
        cur.execute(f"SELECT layer, uuid_field, captured_utc, master_version "
                    f"FROM {BASE_META_TABLE}")
        meta_rows = cur.fetchall()
        if not meta_rows:
            return None

        layers: Dict[str, Dict[str, FeatureFingerprint]] = {}
        captured_utc = None
        master_version = 0
        for layer, _uuid_field, captured, mver in meta_rows:
            layers[layer] = {}
            # Newest layer capture stamps the envelope (they normally match).
            if captured and (captured_utc is None or captured > captured_utc):
                captured_utc = captured
                master_version = mver or 0

        cur.execute(f"SELECT layer, uuid, attr_hash, geom_hash, wkb_type, "
                    f"field_hashes FROM {BASE_TABLE}")
        for layer, u, ah, gh, wt, fh in cur.fetchall():
            fingerprints = layers.setdefault(layer, {})
            field_hashes = None
            if fh:
                try:
                    field_hashes = json.loads(fh)
                except (json.JSONDecodeError, TypeError):
                    field_hashes = None
            fingerprints[u] = FeatureFingerprint(
                attr_hash=ah, geom_hash=gh, wkb_type=wt,
                field_hashes=field_hashes)

        checkout = read_checkout(gpkg_path) or {}
        return {
            "master_version_at_capture": master_version,
            "captured_utc": captured_utc,
            "mapper": checkout.get("mapper", ""),
            "layers": layers,
        }
    except sqlite3.Error:
        return None
    finally:
        con.close()


def read_base_layer(gpkg_path: str, layer_name: str
                    ) -> Optional[Dict[str, FeatureFingerprint]]:
    """{uuid: fingerprint} for one layer; None = no embedded base at all."""
    base = read_base(gpkg_path)
    if base is None:
        return None
    return base["layers"].get(layer_name, {})


def newest_base(embedded: Optional[dict], sidecar: Optional[dict]
                ) -> Tuple[Optional[dict], Optional[str]]:
    """Pick between an embedded and a legacy sidecar base: newest capture wins.

    Both dicts are the load_base()/read_base() shape (or None). Returns
    (base, source) with source in {"embedded", "sidecar", None}. Newest-wins
    heals divergence: if one of the two post-apply writes failed (locked
    working file, missing sidecar folder), the survivor with the later
    captured_utc is the true ancestor.
    """
    if embedded is None and sidecar is None:
        return None, None
    if sidecar is None:
        return embedded, "embedded"
    if embedded is None:
        return sidecar, "sidecar"
    e_cap = embedded.get("captured_utc") or ""
    s_cap = sidecar.get("captured_utc") or ""
    # ISO-8601 UTC strings compare lexicographically; ties go to embedded
    # (the primary store).
    if s_cap > e_cap:
        return sidecar, "sidecar"
    return embedded, "embedded"


# --------------------------------------------------------------------------
# lgs_master (stable master identity)
# --------------------------------------------------------------------------

_MASTER_DDL = (
    f"CREATE TABLE IF NOT EXISTS {MASTER_TABLE} ("
    "id INTEGER PRIMARY KEY CHECK (id = 1), "
    "master_uid TEXT NOT NULL, "
    "created_utc TEXT NOT NULL)"
)


def read_master_uid(master_gpkg: str) -> Optional[str]:
    """The master's stable uid, or None if never stamped. Read-only."""
    if not os.path.exists(master_gpkg):
        return None
    try:
        con = _connect(master_gpkg)
    except sqlite3.Error:
        return None
    try:
        cur = con.cursor()
        if not _table_exists(cur, MASTER_TABLE):
            return None
        cur.execute(f"SELECT master_uid FROM {MASTER_TABLE} WHERE id=1")
        row = cur.fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def ensure_master_uid(master_gpkg: str) -> Optional[str]:
    """Read the master uid, creating it on first call. Best-effort: returns
    None (never raises) when the file is locked/unwritable - callers fall
    back to basename matching for the pairing guard."""
    existing = read_master_uid(master_gpkg)
    if existing:
        return existing
    if not os.path.exists(master_gpkg):
        return None
    uid = str(uuid_module.uuid4())
    try:
        con = _connect(master_gpkg)
    except sqlite3.Error:
        return None
    try:
        cur = con.cursor()
        cur.execute(_MASTER_DDL)
        # INSERT OR IGNORE: if two processes race, first writer wins and we
        # re-read the winner below.
        cur.execute(
            f"INSERT OR IGNORE INTO {MASTER_TABLE} "
            "(id, master_uid, created_utc) VALUES (1,?,?)",
            (uid, _utc_now()))
        con.commit()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return read_master_uid(master_gpkg)
