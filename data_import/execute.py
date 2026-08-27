"""
Writing the plan.

Three things here are deliberate departures from how the old append tool wrote,
and each fixes something that damaged real projects:

* The destination's schema is never touched. No addAttributes, no new columns,
  no provenance stamps unless the column is already there. The old path added
  every unmatched source field to the target, which is how the shipped template
  ended up with data_added_timestamp on two layers out of four.

* Features are built so the TEMPLATE'S OWN default expressions fire.
  provider.addFeatures() bypasses them, so imported features used to arrive with
  Confidence, Weight, Intensity, Basemap Description and Lithology1Code all
  NULL — the Confidence dash system, the Weight symbol scaling and the Intensity
  alpha ramp all render wrong on data like that. Defaults are evaluated here in
  field order against the part-built feature, which is what QGIS itself does, so
  a default that reads a sibling column (Overlay's Weight reads Type) sees it.

* Everything is written by file path, never through project layers, so the whole
  run sits on the task pool without touching a main-thread object. When the
  destination is the open project the layers are reloaded afterwards, on the
  main thread.

Failure is compensated, not left half-done: the fids the provider hands back are
kept, and a batch that fails deletes what it already wrote before giving up. A
copy of the destination is taken first regardless.
"""

import os
import uuid as uuid_module
from collections import OrderedDict
from datetime import datetime, timezone

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsExpression,
    QgsCoordinateTransform,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)

try:
    from .domain import fold, is_blank, normalise, uuid_field_of
    from . import derive
    from .scan import date_filter_expression
    from .metadata import MetadataManager, UUIDTracker
except ImportError:  # flat execution inside QGIS
    from domain import fold, is_blank, normalise, uuid_field_of
    import derive
    from scan import date_filter_expression
    from metadata import MetadataManager, UUIDTracker

# The backup helper is shared with the mining importer rather than duplicated:
# same job, same lock-retry behaviour, same pruning of old copies.
try:
    from ..mining_import.gpkg import backup as _backup_file
    from ..lgs_layers import gpkg_feature_layers
except ImportError:
    from mining_import.gpkg import backup as _backup_file
    from lgs_layers import gpkg_feature_layers


BATCH_SIZE = 500


class LayerResult(object):
    """What happened to one layer."""

    def __init__(self, source_label, target_layer):
        self.source_label = source_label
        self.target_layer = target_layer
        self.added = 0
        self.skipped_duplicate = 0
        self.skipped_no_geometry = 0
        self.skipped_unresolved = 0
        self.split_parts = 0
        self.dropped_z = 0
        self.parent_fills = 0
        self.parent_conflicts = 0
        self.coercion_failures = OrderedDict()   # field -> count
        self.unresolved_seen = OrderedDict()     # (field, value) -> count
        # Destination columns the form marks as required that still came out
        # empty. Not a failure — the features import — but the geologist should
        # hear it from the importer rather than from a red form later.
        self.required_empty = OrderedDict()      # field -> count
        self.errors = []

    @property
    def skipped(self):
        return (self.skipped_duplicate + self.skipped_no_geometry
                + self.skipped_unresolved)

    def summary_line(self):
        parts = ['{0} added'.format(self.added)]
        if self.skipped_duplicate:
            parts.append('{0} already there'.format(self.skipped_duplicate))
        if self.skipped_no_geometry:
            parts.append('{0} had no shape'.format(self.skipped_no_geometry))
        if self.skipped_unresolved:
            parts.append('{0} had an unresolved code'.format(
                self.skipped_unresolved))
        if self.split_parts:
            parts.append('{0} multi-part shapes split'.format(self.split_parts))
        if self.parent_fills:
            parts.append('{0} parent values worked out'.format(
                self.parent_fills))
        if self.required_empty:
            parts.append('required but empty: ' + ', '.join(
                '{0} ({1})'.format(name, count)
                for name, count in self.required_empty.items()))
        return '{0} → {1}: {2}'.format(
            self.source_label, self.target_layer, ', '.join(parts))

    def __repr__(self):
        return 'LayerResult({0!r}, +{1})'.format(self.target_layer, self.added)


class ImportResult(object):
    """The run as a whole."""

    def __init__(self, batch_id):
        self.batch_id = batch_id
        self.backup_path = None
        self.layers = []
        self.new_codes = []
        self.warnings = []
        self.failed = False
        self.message = ''

    @property
    def total_added(self):
        return sum(result.added for result in self.layers)

    @property
    def total_skipped(self):
        return sum(result.skipped for result in self.layers)

    def report_lines(self):
        lines = [result.summary_line() for result in self.layers]
        if self.new_codes:
            lines.append('{0} new code(s) added: {1}'.format(
                len(self.new_codes),
                ', '.join('{0} → {1}'.format(code.code, code.table)
                          for code in self.new_codes)))
        lines.extend(self.warnings)
        return lines

    def __repr__(self):
        return 'ImportResult({0}, +{1})'.format(self.batch_id, self.total_added)


# ── source snapshots (main thread) ────────────────────────────────────

class SourceSnapshot(object):
    """A thread-safe handle on one source layer's features.

    A GeoPackage source is just a path and a table, opened inside the worker.
    A source that is a layer loaded in QGIS cannot be touched off the main
    thread, so its QgsVectorLayerFeatureSource is captured here first — that
    object carries the layer's state, including the subset filter that makes
    "import the filtered subset I am looking at" mean what it says.
    """

    def __init__(self, kind, label, fields=None, crs=None, path='', table='',
                 feature_source=None, fids=None, wkb_type=None,
                 filter_expression=''):
        self.kind = kind
        self.label = label
        self.fields = fields
        self.crs = crs
        self.path = path
        self.table = table
        self.feature_source = feature_source
        self.fids = fids
        self.wkb_type = wkb_type
        self.filter_expression = filter_expression

    def iterate(self):
        """Yield (attributes_by_name, geometry, ok) for every source feature."""
        if self.kind == 'gpkg':
            layer = QgsVectorLayer('{0}|layername={1}'.format(self.path,
                                                             self.table),
                                   self.table, 'ogr')
            if not layer.isValid():
                return
            names = [field.name() for field in layer.fields()]
            request = QgsFeatureRequest()
            expression = date_filter_expression(self.filter_expression, names)
            if expression:
                request.setFilterExpression(expression)
            for feature in layer.getFeatures(request):
                yield _attributes_by_name(feature, names), feature.geometry()
            return

        names = [field.name() for field in self.fields]
        request = QgsFeatureRequest()
        if self.fids is not None:
            request.setFilterFids(list(self.fids))
        expression = date_filter_expression(self.filter_expression, names)
        if expression:
            request.setFilterExpression(expression)
        for feature in self.feature_source.getFeatures(request):
            yield _attributes_by_name(feature, names), feature.geometry()

    def count(self):
        if self.kind == 'gpkg':
            layer = QgsVectorLayer('{0}|layername={1}'.format(self.path,
                                                             self.table),
                                   self.table, 'ogr')
            return layer.featureCount() if layer.isValid() else 0
        if self.fids is not None:
            return len(self.fids)
        return 0


def _attributes_by_name(feature, names):
    values = feature.attributes()
    return {name: (values[index] if index < len(values) else None)
            for index, name in enumerate(names)}


def prepare_sources(plan, project=None):
    """Capture every source layer on the MAIN thread. Call before run_import."""
    from qgis.core import QgsVectorLayerFeatureSource

    project = project or QgsProject.instance()
    snapshots = {}
    for item in plan.included():
        reference = item.source
        if reference.kind == 'gpkg':
            snapshots[reference.table] = SourceSnapshot(
                'gpkg', reference.label, path=reference.path,
                table=reference.table,
                filter_expression=plan.options.date_filter)
            continue
        layer = project.mapLayer(reference.layer_id)
        if layer is None:
            continue
        fids = (list(layer.selectedFeatureIds())
                if reference.selected_only else None)
        snapshots[reference.table] = SourceSnapshot(
            'layer', reference.label,
            fields=layer.fields(), crs=layer.crs(),
            table=reference.table,
            feature_source=QgsVectorLayerFeatureSource(layer),
            fids=fids, wkb_type=layer.wkbType(),
            filter_expression=plan.options.date_filter)
    return snapshots


def destination_gpkg(plan, project=None):
    """The GeoPackage the plan writes to, resolving the open project's layers."""
    if plan.destination.kind == 'gpkg':
        return plan.destination.path
    return plan.destination.path or (plan.target_model.path or '')


# ── the run ───────────────────────────────────────────────────────────

def run_import(plan, snapshots, progress_cb=None, transform_context=None):
    """Execute a validated plan. Safe to call on a worker thread.

    `snapshots` comes from prepare_sources(). `progress_cb(pct, msg)` is
    lgs_tasks' callback and raises TaskCancelled when the user cancels.
    """
    def progress(percent, message=''):
        if progress_cb is not None:
            progress_cb(int(percent), message)

    batch_id = 'import_{0}_{1}'.format(
        datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S'),
        uuid_module.uuid4().hex[:8])
    result = ImportResult(batch_id)

    gpkg_path = destination_gpkg(plan)
    if not gpkg_path or not os.path.exists(gpkg_path):
        result.failed = True
        result.message = 'Destination GeoPackage not found: {0}'.format(gpkg_path)
        return result

    # A destination that lacks the target tables is the wrong file — one
    # clear refusal here, before a backup of it appears on disk, beats four
    # "could not open for writing" errors after.
    existing = {fold(name) for name in gpkg_feature_layers(gpkg_path)}
    missing = [item.target_layer for item in plan.included()
               if fold(item.target_layer) not in existing]
    if missing:
        result.failed = True
        result.message = ('"{0}" does not contain {1} — is this the right '
                          'mapping GeoPackage?'.format(
                              gpkg_path, ', '.join(missing)))
        return result

    if plan.options.backup:
        progress(1, 'Backing up the destination...')
        result.backup_path = _backup_file(gpkg_path, batch_id, result.warnings)

    tracker = None
    metadata = None
    if plan.options.use_uuid_tracker:
        try:
            tracker = UUIDTracker(gpkg_path)
            metadata = MetadataManager(gpkg_path)
        except Exception as error:
            result.warnings.append(
                'Could not open the import ledger ({0}); duplicate detection '
                'falls back to the layer itself.'.format(error))

    progress(3, 'Adding new codes...')
    result.new_codes = _write_new_codes(gpkg_path, plan, result.warnings)
    plan.register_new_codes(result.new_codes)

    # Opened once for the whole run; the code tables are the same for every
    # layer and reopening them per layer is pure waste.
    store = lookup_store(gpkg_path, plan)

    items = plan.included()
    total = max(sum(item.feature_count for item in items), 1)
    done = 0

    for item in items:
        snapshot = snapshots.get(item.source.table)
        if snapshot is None:
            result.warnings.append(
                'Skipped {0}: its source could not be opened.'.format(
                    item.source.label))
            continue
        layer_result = _import_layer(gpkg_path, plan, item, snapshot, batch_id,
                                     progress, done, total, transform_context,
                                     tracker, store)
        result.layers.append(layer_result)
        done += item.feature_count
        if metadata is not None and layer_result.added:
            try:
                metadata.log_batch(
                    batch_id='{0}_{1}'.format(batch_id, item.source.table),
                    layer_name=item.target_layer,
                    records_added=layer_result.added,
                    records_duplicates=layer_result.skipped_duplicate,
                    timezone_used=(plan.options.date_filter or {}).get(
                        'timezone_name', 'UTC'),
                    recoding_template='')
            except Exception:
                pass

    progress(100, 'Finished.')
    result.message = '{0} features added, {1} skipped.'.format(
        result.total_added, result.total_skipped)
    return result


def _open_destination(gpkg_path, table):
    """The destination layer with its stored style applied.

    The style is what carries the default-value expressions, so loading it is
    not cosmetic here — without it every template default silently disappears.
    """
    layer = QgsVectorLayer('{0}|layername={1}'.format(gpkg_path, table),
                           table, 'ogr')
    if not layer.isValid():
        return None
    try:
        layer.loadDefaultStyle()
    except Exception:
        pass
    return layer


def _import_layer(gpkg_path, plan, item, snapshot, batch_id, progress,
                  done_before, grand_total, transform_context, tracker=None,
                  store=None):
    result = LayerResult(item.source.label, item.target_layer)

    target_spec = plan.target_spec(item)
    layer = _open_destination(gpkg_path, item.target_layer)
    if layer is None or target_spec is None:
        result.errors.append('Could not open {0} for writing.'.format(
            item.target_layer))
        return result

    fields = layer.fields()
    provider = layer.dataProvider()
    field_index = {field.name(): index for index, field in enumerate(fields)}
    fid_index = field_index.get('fid', -1)

    # Fields carrying a default-value expression, in field order — the order
    # matters because a default may read a column filled by an earlier one.
    default_indexes = [index for index in range(fields.count())
                       if layer.defaultValueDefinition(index).isValid()
                       and normalise(
                           layer.defaultValueDefinition(index).expression())]

    # Columns the template shadows with a same-named expression field, e.g.
    # Basemap's Lithology1Code = "Lithology1". Applied last, and only where the
    # real column is still empty.
    shadow_fields = []
    for name, spec in target_spec.fields.items():
        if spec.shadow_expression and name in field_index:
            shadow_fields.append((field_index[name],
                                  QgsExpression(spec.shadow_expression)))

    mapping = item.mapping()
    comment_fields = item.comment_fields()
    comments_target = _comments_field(target_spec)

    uuid_field = uuid_field_of(target_spec)
    existing_uuids = set()
    if plan.options.skip_duplicate_uuids and uuid_field:
        existing_uuids = _existing_uuids(layer, uuid_field)
        if tracker is not None:
            # Features imported once and then deleted on purpose are in the
            # ledger but not in the layer; without this they come straight back.
            try:
                existing_uuids |= {normalise(value) for value
                                   in tracker.get_layer_uuids(item.target_layer)
                                   if not is_blank(value)}
            except Exception:
                pass

    transform = _build_transform(snapshot, layer, plan, item, transform_context)
    target_has_z = QgsWkbTypes.hasZ(layer.wkbType()) or target_spec.has_z
    target_is_multi = QgsWkbTypes.isMultiType(layer.wkbType())
    elevation_index = field_index.get('Elevation', -1)

    required_indexes = [(name, field_index[name])
                        for name, spec in target_spec.fields.items()
                        if spec.required and name in field_index
                        and name != 'fid']

    stamp = {}
    if plan.options.stamp_batch:
        now = datetime.now(timezone.utc).isoformat()
        if 'data_added_timestamp' in field_index:
            stamp['data_added_timestamp'] = now
        if 'data_added_batch_id' in field_index:
            stamp['data_added_batch_id'] = batch_id

    context = _expression_context(layer, store)

    pending = []
    written_ids = []
    seen_uuids = set()
    added_uuids = []
    processed = 0

    for attributes, geometry in snapshot.iterate():
        processed += 1
        if processed % 200 == 0:
            percent = 5 + 90.0 * (done_before + processed) / grand_total
            progress(min(percent, 95),
                     '{0}: {1} of {2}...'.format(item.source.label, processed,
                                                 item.feature_count or '?'))

        if geometry is None or geometry.isEmpty():
            result.skipped_no_geometry += 1
            continue

        target_attributes, extras, unresolved = derive.apply_resolutions(
            mapping, item.resolutions, attributes, target_spec)
        if unresolved:
            result.skipped_unresolved += 1
            for pair in unresolved:
                result.unresolved_seen[pair] = \
                    result.unresolved_seen.get(pair, 0) + 1
            continue

        fills = derive.fill_parents(target_spec, target_attributes)
        result.parent_fills += len(fills)
        result.parent_conflicts += sum(1 for fill in fills if fill.is_conflict)

        if comment_fields and comments_target:
            suffix = derive.comment_suffix(attributes, comment_fields)
            if suffix:
                target_attributes[comments_target] = derive.merge_comments(
                    target_attributes.get(comments_target), suffix)

        target_attributes.update(stamp)

        # Duplicate detection before any geometry work.
        raw_uuid = target_attributes.get(uuid_field) if uuid_field else None
        feature_uuid = '' if is_blank(raw_uuid) else normalise(raw_uuid)
        if uuid_field and plan.options.skip_duplicate_uuids and feature_uuid:
            if feature_uuid in existing_uuids or feature_uuid in seen_uuids:
                result.skipped_duplicate += 1
                continue
            seen_uuids.add(feature_uuid)
        if (uuid_field and not feature_uuid
                and plan.options.generate_missing_uuids):
            feature_uuid = str(uuid_module.uuid4())
            target_attributes[uuid_field] = feature_uuid
        if feature_uuid:
            added_uuids.append(feature_uuid)

        for geometry_part in _prepare_geometries(
                geometry, transform, target_has_z, target_is_multi,
                plan.options.split_multiparts, result):
            elevation = None
            if elevation_index >= 0 and is_blank(
                    target_attributes.get('Elevation')):
                elevation = _first_z(geometry_part)

            feature = _build_feature(
                fields, field_index, target_attributes, target_spec,
                geometry_part, layer, default_indexes, context, result,
                shadow_fields)
            if elevation is not None:
                feature.setAttribute(elevation_index, elevation)
            for name, index in required_indexes:
                if is_blank(feature.attribute(index)):
                    result.required_empty[name] =                         result.required_empty.get(name, 0) + 1
            if fid_index >= 0:
                feature.setAttribute(fid_index, None)
            pending.append(feature)

        if len(pending) >= BATCH_SIZE:
            _flush(provider, pending, written_ids, result, item.target_layer)

    _flush(provider, pending, written_ids, result, item.target_layer)

    if result.errors and written_ids:
        # Compensate rather than leave a half-written layer behind.
        provider.deleteFeatures(written_ids)
        result.added = 0
        result.errors.append(
            'Rolled back {0} feature(s) already written to {1}.'.format(
                len(written_ids), item.target_layer))
    else:
        layer.updateExtents()
        if tracker is not None and added_uuids and result.added:
            try:
                tracker.add_uuids(item.target_layer, added_uuids, batch_id, {})
            except Exception:
                pass

    return result


def lookup_store(gpkg_path, plan):
    """A private QgsProject holding the destination's code tables.

    Basemap's Description default is
    attribute(get_feature('BasemapCodes','Code',"Lithology1"),'Description') —
    a cross-table read. get_feature() resolves the table through the expression
    context's loaded-layer store, so without this the default evaluates to NULL
    and every imported polygon arrives with no description.

    Built once per run rather than once per layer: fifteen lookup tables times
    four destination layers is sixty redundant opens of the same GeoPackage,
    which GDAL complains about loudly and slowly.

    It has to be a QgsProject, not a bare QgsMapLayerStore: get_feature()
    resolves a table name through BOTH the project scope and the loaded-layer
    store, and with the store alone the lookup silently returns NULL. Tearing
    the private project down makes GDAL log one metadata-read grumble per run,
    which is the price of the Description column being filled.

    Returns the project, or None. The caller must keep the reference alive for
    as long as any context built from it is in use.
    """
    # Only the tables a default expression actually reads. Opening all fifteen
    # code tables to satisfy one get_feature() call costs fifteen OGR dataset
    # handles per run and makes GDAL grumble in the QGIS log.
    known = set()
    for layer_spec in plan.target_model.layers.values():
        for domain_ in layer_spec.code_domains.values():
            if domain_.table:
                known.add(domain_.table)

    tables = set()
    for layer_spec in plan.target_model.layers.values():
        for field in layer_spec.fields.values():
            expression = field.default_expression
            if not expression:
                continue
            for table in known:
                if "'{0}'".format(table) in expression or \
                        '"{0}"'.format(table) in expression:
                    tables.add(table)
    if not tables:
        return None
    try:
        loaded = []
        for table in sorted(tables):
            lookup = QgsVectorLayer(
                '{0}|layername={1}'.format(gpkg_path, table), table, 'ogr')
            if lookup.isValid():
                loaded.append(lookup)
        if not loaded:
            return None
        store = QgsProject()
        store.addMapLayers(loaded, False)   # takes ownership
        return store
    except Exception:
        return None


def _expression_context(layer, store):
    """The context template defaults are evaluated in, for one layer."""
    context = QgsExpressionContext()
    context.appendScopes(
        QgsExpressionContextUtils.globalProjectLayerScopes(layer))
    if store is not None:
        context.appendScope(QgsExpressionContextUtils.projectScope(store))
        # The scope alone is not enough: get_feature() also consults the
        # context's loaded-layer store, and without this line the cross-table
        # default returns NULL with no error to show for it.
        context.setLoadedLayerStore(store.layerStore())
    return context


def _flush(provider, pending, written_ids, result, target_layer):
    if not pending:
        return
    ok, added = provider.addFeatures(pending)
    if ok:
        result.added += len(pending)
        written_ids.extend(feature.id() for feature in added
                           if feature.id() > 0)
    else:
        messages = [error for error in provider.errors()] or ['unknown error']
        result.errors.append('Writing to {0} failed: {1}'.format(
            target_layer, '; '.join(messages[:3])))
    pending[:] = []


def _build_feature(fields, field_index, attributes, target_spec, geometry,
                   layer, default_indexes, context, result,
                   shadow_fields=()):
    """One destination feature, with the template's own defaults applied."""
    feature = QgsFeature(fields)
    feature.setGeometry(geometry)

    for name, value in attributes.items():
        index = field_index.get(name)
        if index is None:
            continue
        converted, error = derive.coerce(value, target_spec.field(name))
        if error:
            result.coercion_failures[name] = \
                result.coercion_failures.get(name, 0) + 1
            continue
        if converted is not None:
            feature.setAttribute(index, converted)

    # Template defaults, in field order, each seeing what came before it.
    for index in default_indexes:
        if not is_blank(feature.attribute(index)):
            continue
        context.setFeature(feature)
        try:
            value = layer.defaultValue(index, feature, context)
        except Exception:
            continue
        if value is not None:
            feature.setAttribute(index, value)

    # Shadowed columns last: they read columns the defaults may just have set.
    for index, expression in shadow_fields:
        if not is_blank(feature.attribute(index)):
            continue
        context.setFeature(feature)
        try:
            value = expression.evaluate(context)
        except Exception:
            continue
        if not is_blank(value):
            feature.setAttribute(index, value)

    return feature


def _prepare_geometries(geometry, transform, target_has_z, target_is_multi,
                        split_multiparts, result):
    """Yield destination-ready geometries from one source geometry."""
    geometry = QgsGeometry(geometry)
    if transform is not None:
        try:
            geometry.transform(transform)
        except Exception as error:
            result.errors.append('Reprojection failed: {0}'.format(error))
            return

    if geometry.constGet() is not None and geometry.constGet().is3D() \
            and not target_has_z:
        result.dropped_z += 1

    if geometry.isMultipart() and not target_is_multi and split_multiparts:
        parts = geometry.asGeometryCollection()
        if len(parts) > 1:
            result.split_parts += len(parts) - 1
        for part in parts:
            yield _match_dimension(part, target_has_z)
        return

    if not geometry.isMultipart() and target_is_multi:
        geometry.convertToMultiType()

    yield _match_dimension(geometry, target_has_z)


def _match_dimension(geometry, target_has_z):
    """Drop Z when the destination declares it prohibited, add it when not."""
    abstract = geometry.constGet()
    if abstract is None:
        return geometry
    if abstract.is3D() and not target_has_z:
        geometry.get().dropZValue()
    elif not abstract.is3D() and target_has_z:
        geometry.get().addZValue(0.0)
    return geometry


def _first_z(geometry):
    """The Z of the first vertex, for filling Elevation. None when 2D."""
    abstract = geometry.constGet()
    if abstract is None or not abstract.is3D():
        return None
    for vertex in geometry.vertices():
        value = vertex.z()
        if value is not None and value == value:   # not NaN
            return float(value)
        break
    return None


def _build_transform(snapshot, layer, plan, item, transform_context):
    source_crs = snapshot.crs
    if source_crs is None:
        authid = plan.source_model.crs_of(item.source.table)
        source_crs = (QgsCoordinateReferenceSystem(authid) if authid
                      else None)
    if source_crs is None or not source_crs.isValid():
        return None
    target_crs = layer.crs()
    if not target_crs.isValid() or source_crs == target_crs:
        return None
    context = transform_context or QgsProject.instance().transformContext()
    return QgsCoordinateTransform(source_crs, target_crs, context)


def _comments_field(target_spec):
    for name in target_spec.fields:
        if fold(name) in ('comments', 'comment'):
            return name
    return ''


def _existing_uuids(layer, uuid_field):
    index = layer.fields().lookupField(uuid_field)
    if index < 0:
        return set()
    return {normalise(value) for value in layer.uniqueValues(index)
            if not is_blank(value)}


def _write_new_codes(gpkg_path, plan, warnings):
    """Insert the 'add this code' decisions into the DESTINATION's code tables.

    Only ever this project's GeoPackage — the shipped template under Template/
    is never opened for writing by the importer.
    """
    written = []
    by_table = OrderedDict()
    for new_code in plan.new_codes():
        by_table.setdefault(new_code.table, []).append(new_code)

    for table, codes in by_table.items():
        layer = QgsVectorLayer('{0}|layername={1}'.format(gpkg_path, table),
                               table, 'ogr')
        if not layer.isValid():
            warnings.append(
                'Could not open {0}; {1} new code(s) were not added.'.format(
                    table, len(codes)))
            continue
        fields = layer.fields()
        names = {fold(field.name()): field.name() for field in fields}
        key_name = _code_key_column(plan, table, names)
        existing = set()
        key_index = fields.lookupField(key_name) if key_name else -1
        if key_index >= 0:
            existing = {fold(value) for value in layer.uniqueValues(key_index)}

        features = []
        for new_code in codes:
            if fold(new_code.code) in existing:
                continue
            feature = QgsFeature(fields)
            if key_name:
                feature.setAttribute(key_name, new_code.code)
            for candidate in ('Description', 'Desciption'):
                if fold(candidate) in names:
                    feature.setAttribute(names[fold(candidate)],
                                         new_code.description)
                    break
            if 'type' in names and new_code.parent and names['type'] != key_name:
                feature.setAttribute(names['type'], new_code.parent)
            if 'uuid' in names:
                feature.setAttribute(names['uuid'], str(uuid_module.uuid4()))
            features.append(feature)
            written.append(new_code)

        if features:
            ok, _added = layer.dataProvider().addFeatures(features)
            if not ok:
                warnings.append('Could not add new codes to {0}.'.format(table))
                for new_code in codes:
                    if new_code in written:
                        written.remove(new_code)
    return written


def _code_key_column(plan, table, names):
    """The key column of a lookup table, taken from the widget that uses it."""
    for layer_spec in plan.target_model.layers.values():
        for domain in layer_spec.code_domains.values():
            if domain.table and fold(domain.table) == fold(table):
                return names.get(fold(domain.key_column), domain.key_column)
    for candidate in ('Code', 'Value'):
        if fold(candidate) in names:
            return names[fold(candidate)]
    return ''


def reload_destination_layers(plan, project=None):
    """Refresh the open project's view of a GeoPackage written behind its back.

    Called on the main thread after the worker finishes.
    """
    project = project or QgsProject.instance()
    path = destination_gpkg(plan)
    if not path:
        return
    normalised = os.path.normcase(os.path.abspath(path))
    for layer in project.mapLayers().values():
        try:
            source = layer.source().split('|', 1)[0]
        except Exception:
            continue
        if os.path.normcase(os.path.abspath(source)) != normalised:
            continue
        layer.dataProvider().reloadData()
        layer.updateExtents()
        layer.triggerRepaint()
