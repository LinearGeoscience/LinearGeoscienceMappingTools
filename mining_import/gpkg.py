"""
GeoPackage write engine: create-or-append with a merge policy, plus the
import log that makes incremental re-import possible.

Write ordering is append-first, delete-last
-------------------------------------------
The obvious ordering -- delete what this source contributed, then append the
new version -- has a window in which the user's previous data is gone and the
new data is not yet written. A failure there (disk full, SQLITE_BUSY, a
malformed record) destroys survey data.

So features are appended first, tagged with this run's BatchId, and only then
are the superseded rows deleted with the new batch explicitly excluded. A
crash before the delete leaves temporary duplicates: detectable,
non-destructive, and cleaned either by rollback_batch() or by simply
re-running the import. A crash after it leaves the correct state. There is no
window where the old data is gone and the new data absent.

That is why BatchId is a real column on every layer, not just a log field.

Runs on the import worker thread: paths and worker-local layers only, never
project layers or widgets.
"""

import json
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone

from qgis.PyQt.QtCore import QMetaType
from qgis.core import (
    QgsFeature,
    QgsFeatureRequest,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

try:
    from . import merge, schema
except ImportError:  # non-package execution inside QGIS
    import merge
    import schema

# A GeoPackage whose layers are loaded in the current project is locked by
# QGIS often enough that this is the most likely real-world failure, so
# writes retry rather than surfacing "database is locked" to the user.
_RETRY_DELAYS = (0.2, 0.5, 1.0, 2.0, 3.0)

BACKUP_DIRNAME = 'lgs_import_backup'
BACKUP_KEEP = 3
# Copying a multi-gigabyte GeoPackage before every import costs more than it
# protects; above this the backup is skipped with a warning.
BACKUP_MAX_BYTES = 500 * 1024 * 1024


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def layer_uri(gpkg_path, layer_name):
    return '{0}|layername={1}'.format(gpkg_path, layer_name)


def open_layer(gpkg_path, layer_name):
    if not os.path.exists(gpkg_path):
        return None
    layer = QgsVectorLayer(layer_uri(gpkg_path, layer_name), layer_name, 'ogr')
    return layer if layer.isValid() else None


def layer_exists(gpkg_path, layer_name):
    return open_layer(gpkg_path, layer_name) is not None


def existing_layer_names(gpkg_path):
    if not os.path.exists(gpkg_path):
        return []
    container = QgsVectorLayer(gpkg_path, 'probe', 'ogr')
    if not container.isValid():
        return []
    names = []
    for item in container.dataProvider().subLayers():
        parts = item.split('!!::!!')
        if len(parts) > 1:
            names.append(parts[1])
    return names


def legacy_layers_present(gpkg_path):
    """Pre-release Surpac-only layer names found in the target, if any."""
    present = set(existing_layer_names(gpkg_path))
    return [name for name in schema.LEGACY_LAYERS if name in present]


def _is_lock_error(message):
    lowered = (message or '').lower()
    return 'locked' in lowered or 'busy' in lowered


def _retrying(func, what, before_retry=None):
    """Run a provider write, retrying while SQLite reports a locked database.

    before_retry runs prior to every attempt after the first, so a caller
    whose operation is not naturally idempotent can undo a partial attempt.
    """
    last_error = ''
    for index, delay in enumerate((0.0,) + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        if index and before_retry is not None:
            before_retry()
        ok, error = func()
        if ok:
            return
        last_error = error or ''
        if not _is_lock_error(last_error):
            break
    raise RuntimeError(
        '{0}: {1}\n\nIf this GeoPackage is loaded in the current project, '
        'close or remove those layers and try again.'.format(what, last_error))


def backup(gpkg_path, batch_id, warnings):
    """Copy an existing target aside before the first write of a run."""
    if not os.path.exists(gpkg_path):
        return None
    size = os.path.getsize(gpkg_path)
    if size > BACKUP_MAX_BYTES:
        warnings.append(
            'Backup skipped: {0} is {1:.0f} MB. The import is still safe to '
            'interrupt, but there is no copy to fall back on.'.format(
                os.path.basename(gpkg_path), size / (1024.0 * 1024.0)))
        return None
    folder = os.path.join(os.path.dirname(gpkg_path), BACKUP_DIRNAME)
    try:
        os.makedirs(folder, exist_ok=True)
        stem = os.path.splitext(os.path.basename(gpkg_path))[0]
        dest = os.path.join(folder, '{0}_{1}.gpkg'.format(stem, batch_id))
        shutil.copy2(gpkg_path, dest)
    except OSError as exc:
        warnings.append('Backup failed ({0}) — import continued.'.format(exc))
        return None
    _prune_backups(folder, stem)
    return dest


def _prune_backups(folder, stem):
    try:
        made = sorted(
            (os.path.join(folder, f) for f in os.listdir(folder)
             if f.startswith(stem + '_') and f.endswith('.gpkg')),
            key=os.path.getmtime, reverse=True)
        for stale in made[BACKUP_KEEP:]:
            os.remove(stale)
    except OSError:
        pass


def create_layer(gpkg_path, layer_name, crs, transform_context):
    """Create an empty layer, preserving anything already in the file."""
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = 'GPKG'
    options.layerName = layer_name
    if os.path.exists(gpkg_path):
        # CreateOrOverwriteLayer opens the file in update mode, so it only
        # works when the file already exists; it leaves sibling layers alone.
        options.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer)
    else:
        options.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile)
    # NOTE: the 5th argument is the coordinate transform context, NOT the
    # driver name (see script_adddata/data_processing.py).
    writer = QgsVectorFileWriter.create(
        gpkg_path, schema.make_fields(layer_name), schema.wkb_type(layer_name),
        crs, transform_context, options)
    failed = (writer is None or
              writer.hasError() != QgsVectorFileWriter.WriterError.NoError)
    message = writer.errorMessage() if writer is not None else 'writer not created'
    del writer  # flush and close before anything reopens the file
    if failed:
        raise RuntimeError('Could not create layer {0}: {1}'.format(
            layer_name, message))
    _create_index(gpkg_path, layer_name)
    apply_style(gpkg_path, layer_name)


def style_path(layer_name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'styles', layer_name + '.qml')
    return path if os.path.exists(path) else None


def apply_style(gpkg_path, layer_name):
    """Save the shipped symbology into the GeoPackage as the layer default.

    Called ONLY on layer creation. Re-applying on every append would stomp
    whatever the user had customised, which is worse than shipping no style
    at all.

    Best-effort throughout: an import that wrote its data correctly must not
    fail because a stylesheet did not load.
    """
    path = style_path(layer_name)
    if path is None:
        return False
    layer = open_layer(gpkg_path, layer_name)
    if layer is None:
        return False
    try:
        _message, ok = layer.loadNamedStyle(path)
        if not ok:
            return False
        # Embeds the style in the .gpkg itself, so it travels with the file
        # (same approach as qfield_export/utils/qgis_utils.py).
        saved, _msg = layer.saveStyleToDatabase(layer_name, '', True, '')
        return bool(saved)
    except Exception:
        return False


def _create_index(gpkg_path, layer_name):
    """Index SourceKey — without it every re-import full-scans the layer."""
    con = None
    try:
        con = sqlite3.connect(gpkg_path, timeout=15)
        con.execute(
            'CREATE INDEX IF NOT EXISTS "idx_{0}_srckey" ON "{0}"("SourceKey")'
            .format(layer_name))
        con.commit()
    except sqlite3.Error:
        pass  # an index is an optimisation, never a reason to fail an import
    finally:
        if con is not None:
            con.close()


# Keyed on the QMetaType value itself rather than its name: PyQt5 exposes
# these as int-backed sip enums whose str() is just the number, while PyQt6
# uses real Python enums. Both are hashable, so direct lookup works on each.
_SQLITE_TYPES = {
    QMetaType.Type.QString: 'TEXT',
    QMetaType.Type.Double: 'REAL',
    QMetaType.Type.Int: 'INTEGER',
    QMetaType.Type.Bool: 'INTEGER',
}


def _add_missing_columns(gpkg_path, layer_name, missing, warnings):
    """ALTER an existing layer up to the current schema. Returns names added.

    Used when a GeoPackage predates a schema version. sqlite3 rather than the
    OGR provider because ALTER through the provider requires an edit session,
    and this runs on the import worker thread.
    """
    wanted = dict(schema.field_defs(layer_name))
    added = []
    con = None
    try:
        con = sqlite3.connect(gpkg_path, timeout=15)
        for name in missing:
            decl = _SQLITE_TYPES.get(wanted.get(name), 'TEXT')
            try:
                con.execute('ALTER TABLE "{0}" ADD COLUMN "{1}" {2}'.format(
                    layer_name, name, decl))
                added.append(name)
            except sqlite3.Error as exc:
                warnings.append('Could not add column {0} to {1}: {2}'.format(
                    name, layer_name, exc))
        con.commit()
    except sqlite3.Error as exc:
        warnings.append('Could not upgrade {0}: {1}'.format(layer_name, exc))
    finally:
        if con is not None:
            con.close()
    if added:
        warnings.append(
            '{0}: added new column(s) {1} to match the current schema.'.format(
                layer_name, ', '.join(added)))
    return added


def _delete_where(layer, expression, what):
    request = QgsFeatureRequest().setFilterExpression(expression)
    request.setNoAttributes()
    ids = [f.id() for f in layer.getFeatures(request)]
    if not ids:
        return 0
    provider = layer.dataProvider()
    _retrying(lambda: (provider.deleteFeatures(ids),
                       provider.error().message()), what)
    return len(ids)


def write_features(gpkg_path, layer_name, features, crs, transform_context,
                   policy, source_keys, levels, batch_id, warnings):
    """Append features, then delete what they supersede. See module docstring.

    Returns (added, removed). Raises RuntimeError on any failure, having left
    the new features in place for rollback_batch() to clean up.
    """
    layer = open_layer(gpkg_path, layer_name)
    if layer is None:
        create_layer(gpkg_path, layer_name, crs, transform_context)
        layer = open_layer(gpkg_path, layer_name)
        if layer is None:
            raise RuntimeError(
                'Layer {0} could not be opened after creation'.format(
                    layer_name))

    missing = [name for name in schema.required_fields(layer_name)
               if layer.fields().lookupField(name) < 0]
    if missing:
        # A GeoPackage written by an older schema version is upgraded in
        # place rather than rejected — refusing it would strand every file
        # made before the columns existed. Only ever ADDs; a layer that is
        # genuinely someone else's data still fails below, because the add
        # will not produce the full expected field set.
        added = _add_missing_columns(gpkg_path, layer_name, missing, warnings)
        if added:
            layer = open_layer(gpkg_path, layer_name)
        still_missing = [name for name in schema.required_fields(layer_name)
                         if layer is None
                         or layer.fields().lookupField(name) < 0]
        if still_missing:
            raise RuntimeError(
                'Layer {0} in {1} is missing field(s) {2} and they could not '
                'be added — it was probably made by a different tool. Choose '
                'a different output GeoPackage.'.format(
                    layer_name, os.path.basename(gpkg_path),
                    ', '.join(still_missing)))

    provider = layer.dataProvider()
    target_fields = layer.fields()

    added = 0
    if features:
        # Rebuild against the live layer's fields: an existing GeoPackage
        # layer carries a leading fid that shifts every positional index.
        rebuilt = []
        for feat in features:
            src_fields = feat.fields()
            attrs = {src_fields[i].name(): feat.attribute(i)
                     for i in range(len(src_fields))}
            rebuilt.append(_rebuild(target_fields, feat.geometry(), attrs))
        before = provider.featureCount()

        def _purge_partial_attempt():
            # addFeatures is not idempotent: a retry after a partly-applied
            # attempt would duplicate. This batch has only ever been written
            # by this run, so clearing it is safe and makes the retry clean.
            try:
                _delete_where(layer, merge.batch_expression(batch_id),
                              'Retry cleanup of {0}'.format(layer_name))
            except RuntimeError:
                pass

        _retrying(lambda: (provider.addFeatures(rebuilt)[0],
                           provider.error().message()),
                  'Could not write features to {0}'.format(layer_name),
                  before_retry=_purge_partial_attempt)
        added = len(rebuilt)
        actual = provider.featureCount() - before
        if 0 <= actual < added:
            # Stop before the delete: the previous data is still intact, and
            # rollback_batch() will remove what did land.
            raise RuntimeError(
                'Only {0} of {1} features reached {2} — nothing was deleted, '
                'so the existing data is untouched.'.format(
                    actual, added, layer_name))

    # Delete only now, and never the rows just written.
    expression = merge.delete_expression(
        policy, source_keys=source_keys, levels=levels,
        exclude_batch=batch_id)
    removed = 0
    if expression is not None:
        removed = _delete_where(
            layer, expression,
            'Could not replace superseded features in {0}'.format(layer_name))
    return added, removed


def _rebuild(fields, geometry, attrs):
    feat = QgsFeature(fields)
    feat.setGeometry(geometry)
    for name, value in attrs.items():
        idx = fields.lookupField(name)
        if idx >= 0:
            feat.setAttribute(idx, value)
    return feat


def rollback_batch(gpkg_path, layer_names, batch_id):
    """Remove every feature written by one run. Best-effort compensation.

    Called when a multi-layer import fails partway: the layers already
    written are left holding rows that supersede nothing, so they are undone
    rather than left as silent duplicates.

    Returns a list of human-readable notes about what could not be undone.
    """
    notes = []
    expression = merge.batch_expression(batch_id)
    for layer_name in layer_names:
        layer = open_layer(gpkg_path, layer_name)
        if layer is None:
            continue
        try:
            _delete_where(layer, expression,
                          'Cleanup of {0}'.format(layer_name))
        except RuntimeError as exc:
            notes.append(
                '{0}: could not remove the partial import ({1}). Features '
                'from batch {2} may remain.'.format(layer_name, exc, batch_id))
    return notes


# --- import log -------------------------------------------------------------

_LOG_COLUMNS = (
    ('source_key', 'TEXT NOT NULL'),
    ('scan_root', 'TEXT'),
    ('abs_path', 'TEXT'),
    ('source_file', 'TEXT'),
    ('format_key', 'TEXT'),
    ('level', 'TEXT'),
    ('file_size', 'INTEGER'),
    ('file_mtime_utc', 'TEXT'),
    ('content_hash', 'TEXT'),
    ('batch_id', 'TEXT'),
    ('imported_at_utc', 'TEXT'),
    ('crs_authid', 'TEXT'),
    ('options_json', 'TEXT'),
    ('feature_counts_json', 'TEXT'),
    ('plugin_version', 'TEXT'),
    ('schema_version', 'INTEGER'),
    ('status', 'TEXT'),
    ('warnings_json', 'TEXT'),
)


def ensure_log(gpkg_path):
    """Create the log table and register it so QGIS can open it.

    Mirrors script_adddata/reconcile/changelog.py: create, commit, then
    best-effort gpkg_contents registration.
    """
    con = None
    try:
        con = sqlite3.connect(gpkg_path, timeout=15)
        cur = con.cursor()
        columns = ', '.join('{0} {1}'.format(n, t) for n, t in _LOG_COLUMNS)
        cur.execute(
            'CREATE TABLE IF NOT EXISTS {0} ('
            'fid INTEGER PRIMARY KEY AUTOINCREMENT, {1})'.format(
                schema.LOG_TABLE, columns))
        cur.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_{0}_key ON {0}(source_key)'
            .format(schema.LOG_TABLE))
        con.commit()
        # Adding a column to an existing log must never hard-fail an import.
        existing = {row[1] for row in
                    cur.execute('PRAGMA table_info({0})'.format(
                        schema.LOG_TABLE))}
        for name, decl in _LOG_COLUMNS:
            if name not in existing:
                try:
                    cur.execute('ALTER TABLE {0} ADD COLUMN {1} {2}'.format(
                        schema.LOG_TABLE, name, decl.replace(' NOT NULL', '')))
                except sqlite3.Error:
                    pass
        con.commit()
        try:
            stamp = datetime.now(timezone.utc).strftime(
                '%Y-%m-%dT%H:%M:%S.000Z')
            cur.execute(
                'INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, '
                'identifier, description, last_change) VALUES (?,?,?,?,?)',
                (schema.LOG_TABLE, 'attributes', schema.LOG_TABLE,
                 'Mining import provenance', stamp))
            con.commit()
        except sqlite3.Error:
            pass
    finally:
        if con is not None:
            con.close()


def read_log(gpkg_path):
    """{source_key: row dict} from the target, or {} if there is no log yet."""
    if not os.path.exists(gpkg_path):
        return {}
    con = None
    try:
        con = sqlite3.connect(gpkg_path, timeout=15)
        con.row_factory = sqlite3.Row
        rows = con.execute('SELECT * FROM {0}'.format(schema.LOG_TABLE))
        return {row['source_key']: dict(row) for row in rows}
    except sqlite3.Error:
        return {}
    finally:
        if con is not None:
            con.close()


def write_log_rows(gpkg_path, rows):
    """Upsert one row per imported source, keyed on source_key.

    Called only after every layer has committed, so the log can lag the data
    but never lead it — the worst case is a harmless re-import.
    """
    if not rows:
        return
    ensure_log(gpkg_path)
    names = [name for name, _decl in _LOG_COLUMNS]
    placeholders = ', '.join('?' for _ in names)
    sql = 'INSERT OR REPLACE INTO {0} (fid, {1}) VALUES (' \
          '(SELECT fid FROM {0} WHERE source_key = ?), {2})'.format(
              schema.LOG_TABLE, ', '.join(names), placeholders)
    con = None
    try:
        con = sqlite3.connect(gpkg_path, timeout=15)
        for row in rows:
            values = [row.get(name) for name in names]
            con.execute(sql, [row.get('source_key')] + values)
        con.commit()
    finally:
        if con is not None:
            con.close()


def relink_log_keys(gpkg_path, mapping):
    """Rewrite source keys after the scan root moved. Confirmed by the user."""
    if not mapping:
        return
    con = None
    try:
        con = sqlite3.connect(gpkg_path, timeout=15)
        for old_key, new_key in mapping.items():
            con.execute(
                'UPDATE {0} SET source_key = ? WHERE source_key = ?'.format(
                    schema.LOG_TABLE), (new_key, old_key))
            for layer_name in schema.LAYER_ORDER:
                try:
                    con.execute(
                        'UPDATE "{0}" SET "SourceKey" = ? WHERE '
                        '"SourceKey" = ?'.format(layer_name),
                        (new_key, old_key))
                except sqlite3.Error:
                    pass  # layer absent from this GeoPackage
        con.commit()
    finally:
        if con is not None:
            con.close()


def log_row(entry_key, scan_root, path, fmt_key, level, size, mtime,
            content_hash, batch_id, crs_authid, options, counts,
            plugin_version, status, warnings):
    return {
        'source_key': entry_key,
        'scan_root': scan_root,
        'abs_path': path,
        'source_file': os.path.basename(path),
        'format_key': fmt_key,
        'level': level,
        'file_size': size,
        'file_mtime_utc': mtime,
        'content_hash': content_hash,
        'batch_id': batch_id,
        'imported_at_utc': utc_now(),
        'crs_authid': crs_authid,
        'options_json': json.dumps(options or {}, sort_keys=True, default=str),
        'feature_counts_json': json.dumps(counts or {}, sort_keys=True),
        'plugin_version': plugin_version,
        'schema_version': schema.SCHEMA_VERSION,
        'status': status,
        'warnings_json': json.dumps(list(warnings or ()), default=str),
    }
