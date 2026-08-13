"""
Import orchestration: the two functions the dialog hands to lgs_tasks.

scan_sources() and import_sources() both run on a background task, so they
work only on paths and worker-local layers — never project layers, iface or
widgets. load_into_project() is the main-thread follow-up.

Output conventions are chosen so the Z Filter panel picks the layers up with
zero configuration (see schema.py).
"""

import os
import uuid

from qgis.core import QgsProject, QgsVectorLayer

try:
    from . import build, gpkg, merge, registry, scan, schema
except ImportError:  # non-package execution inside QGIS
    import build
    import gpkg
    import merge
    import registry
    import scan
    import schema


def plugin_version():
    """Version string for the import log. Never worth failing an import over."""
    try:
        try:
            from ..version_info import short_version_string
        except ImportError:
            from version_info import short_version_string
        return short_version_string()
    except Exception:
        return ''


def scan_sources(folder=None, paths=None, gpkg_path=None, deep=False,
                 progress_cb=None):
    """Discover sources and compare them against the target's import log.

    Returns a dict with 'entries', 'root', 'log', 'duplicates', 'missing',
    'relink' and 'legacy_layers'. Runs on a background task: reading and
    hashing a survey tree is not main-thread work.
    """
    def progress(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    progress(5, 'Looking for importable files…')
    if paths:
        entries, root = scan.discover_paths(paths)
    else:
        root = scan.normalise_root(folder)
        entries = scan.discover(root)

    progress(45, 'Reading import history…')
    log = gpkg.read_log(gpkg_path) if gpkg_path else {}

    progress(70, 'Comparing against the last import…')
    classified = scan.classify(entries, log, deep=deep)

    return {
        'entries': classified,
        'root': root,
        'log': log,
        'duplicates': scan.duplicate_keys(classified),
        'missing': scan.missing_sources(classified, log),
        'relink': scan.relink_candidates(classified, log) if log else {},
        'legacy_layers': gpkg.legacy_layers_present(gpkg_path)
        if gpkg_path else [],
    }


def import_sources(gpkg_path, crs, transform_context, entries, root,
                   policy=merge.POLICY_REPLACE_SOURCE, make_backup=True,
                   options_by_key=None, progress_cb=None):
    """Parse the selected sources and write them into gpkg_path.

    entries: [scan.Entry] already filtered to what the user checked, with
    their (possibly edited) level.

    Every layer in one run shares a BatchId. Features are appended before the
    superseded rows are deleted, so a failure part-way leaves duplicates
    rather than a hole — see gpkg.write_features. If anything raises, the
    batch is rolled back off every layer already touched.
    """
    def progress(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    batch_id = uuid.uuid4().hex
    warnings = []
    crs_authid = crs.authid() if crs is not None else ''
    version = plugin_version()

    # --- parse ------------------------------------------------------------
    parsed_files = []
    total = max(len(entries), 1)
    for index, entry in enumerate(entries):
        name = os.path.basename(entry.path)
        progress(5 + int(45 * index / total),
                 'Reading {0} ({1}/{2})'.format(name, index + 1, len(entries)))
        fmt = registry.spec(entry.fmt_key)
        reader = registry.reader_for(fmt)
        options = dict((options_by_key or {}).get(entry.key, {}))
        parsed = reader(entry.path, companions=entry.companions,
                        level=entry.level, **options)
        warnings.extend(parsed.warnings)
        parsed_files.append((entry, parsed, options))

    # --- build features ---------------------------------------------------
    progress(55, 'Building features…')
    by_layer = {name: [] for name in schema.LAYER_ORDER}
    counts_by_key = {}
    fields = {name: schema.make_fields(name) for name in schema.LAYER_ORDER}
    degenerate = 0

    for entry, parsed, _options in parsed_files:
        provenance = {
            'Level': entry.level,
            'SourceKey': entry.key,
            'SourceFile': parsed.name,
            'Format': parsed.format_key,
            'BatchId': batch_id,
            'ImportedAt': gpkg.utc_now(),
        }
        strings, skipped = build.build_polylines(
            parsed, provenance, fields[schema.STRINGS_LAYER])
        degenerate += skipped
        stations = build.build_stations(
            parsed, provenance, fields[schema.STATIONS_LAYER])
        outlines = build.build_outlines(
            parsed, provenance, fields[schema.OUTLINES_LAYER], warnings)
        notes = build.build_annotations(
            parsed, provenance, fields[schema.TEXT_LAYER])

        by_layer[schema.STRINGS_LAYER].extend(strings)
        by_layer[schema.STATIONS_LAYER].extend(stations)
        by_layer[schema.OUTLINES_LAYER].extend(outlines)
        by_layer[schema.TEXT_LAYER].extend(notes)
        counts_by_key[entry.key] = {
            schema.STRINGS_LAYER: len(strings),
            schema.STATIONS_LAYER: len(stations),
            schema.OUTLINES_LAYER: len(outlines),
            schema.TEXT_LAYER: len(notes),
        }

    source_keys = [e.key for e in entries]
    levels = sorted({e.level for e in entries})

    # --- write ------------------------------------------------------------
    if make_backup:
        progress(60, 'Backing up the existing GeoPackage…')
        gpkg.backup(gpkg_path, batch_id, warnings)

    written = {}
    touched = []
    pct = 65
    try:
        for layer_name in schema.LAYER_ORDER:
            features = by_layer[layer_name]
            # A layer with nothing new still has to be visited when it
            # already exists, or a source that used to contribute (say) a
            # station and no longer does would leave that station behind
            # forever. Skipping is only safe when the layer does not exist
            # yet -- creating it empty would just be clutter.
            if not features and not gpkg.layer_exists(gpkg_path, layer_name):
                continue
            progress(pct, 'Writing {0} {1}…'.format(
                len(features), schema.LAYERS[layer_name]['label'].lower()))
            pct = min(pct + 7, 90)
            touched.append(layer_name)
            added, removed = gpkg.write_features(
                gpkg_path, layer_name, features, crs, transform_context,
                policy, source_keys, levels, batch_id, warnings)
            written[layer_name] = {'added': added, 'removed': removed}
    except Exception:
        notes = gpkg.rollback_batch(gpkg_path, touched, batch_id)
        warnings.extend(notes)
        raise

    # --- log --------------------------------------------------------------
    # Written last, so the log can lag the data but never lead it: the worst
    # consequence of a crash here is a harmless re-import.
    progress(93, 'Recording import history…')
    rows = []
    for entry, parsed, options in parsed_files:
        rows.append(gpkg.log_row(
            entry_key=entry.key, scan_root=root, path=entry.path,
            fmt_key=entry.fmt_key, level=entry.level, size=entry.size,
            mtime=entry.mtime_utc,
            content_hash=scan.content_hash(entry.path, entry.size),
            batch_id=batch_id, crs_authid=crs_authid,
            options=dict(options, **parsed.attrs), counts=counts_by_key[entry.key],
            plugin_version=version, status='ok', warnings=parsed.warnings))
    gpkg.write_log_rows(gpkg_path, rows)

    progress(97, 'Finishing…')
    return {
        'batch_id': batch_id,
        'layers': [name for name in schema.LAYER_ORDER if name in written],
        'written': written,
        'levels': levels,
        'sources': len(entries),
        'degenerate': degenerate,
        'warnings': warnings,
    }


def load_into_project(gpkg_path, layer_names):
    """Main-thread follow-up: add (or reload) the written layers.

    The Z Filter panel finds them on its next refresh via
    z_filter/auto_layers.detect_extra_layers — nothing to wire up here.
    """
    project = QgsProject.instance()
    loaded = []
    targets = {name: os.path.normcase(os.path.normpath(
        gpkg.layer_uri(gpkg_path, name))) for name in layer_names}
    existing = {}
    for layer in project.mapLayers().values():
        src = os.path.normcase(os.path.normpath(layer.source()))
        for name, target in targets.items():
            if src == target:
                existing[name] = layer
    for name in layer_names:
        layer = existing.get(name)
        if layer is not None:
            layer.reload()
            layer.triggerRepaint()
            loaded.append(layer)
            continue
        layer = QgsVectorLayer(gpkg.layer_uri(gpkg_path, name), name, 'ogr')
        if layer.isValid():
            project.addMapLayer(layer)
            loaded.append(layer)
    return loaded
