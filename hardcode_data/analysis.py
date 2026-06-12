"""
Analysis logic for the Hardcode Data & Update Legends tool.

Pure logic — qgis.core / QtCore only, no QtWidgets. A single pass over each
layer produces a LayerReport containing column statistics for every field,
the complete list of attribute changes (standard fields, field copies,
legend lookups, UUID fills) and a UUID quality report. Commit applies the
previewed change records verbatim — it never re-evaluates.
"""

import uuid
from dataclasses import dataclass, field

from qgis.PyQt.QtCore import QVariant
try:
    from qgis.PyQt.QtCore import QMetaType
except ImportError:
    QMetaType = None
from qgis.core import QgsField

try:
    from ..script_adddata.utils import detect_uuid_field
except ImportError:
    from script_adddata.utils import detect_uuid_field


# Update modes
MODE_EMPTY_ONLY = 0
MODE_OVERWRITE_ALL = 1
MODE_SELECTED_ONLY = 2

# Change sources (shown in the preview "Source" column)
SOURCE_STANDARD = "Standard field"
SOURCE_COPY = "Field copy"
SOURCE_GEOMETRY = "From geometry"
SOURCE_LEGEND = "Legend lookup"
SOURCE_UUID = "UUID fill"

DISTINCT_CAP = 1000
SAMPLE_VALUES_MAX = 5
PROGRESS_EVERY = 500

# copy_operations tuples are (source_field, target_field, geometry_axis);
# geometry_axis 'x'/'y' enables a from-geometry fallback when the source
# attribute is empty, so every point still gets hardcoded coordinates
LAYER_CONFIGS = {
    '1 - FieldNotebook': {
        'standard_fields': ['ProjectID', 'MappedScale', 'MappedCRS'],
        'copy_operations': [
            ('Easting', 'MappedEasting', 'x'),
            ('Northing', 'MappedNorthing', 'y'),
            ('SubType1Code', 'MappedSubType1', None),
        ],
        'legend': {
            'target_field': 'Legend',
            'source_field': 'Subtype1',
            'lookup_table': 'FieldNotebookCodes',
        },
    },
    '2 - Overlay': {
        'standard_fields': ['ProjectID', 'MappedScale', 'MappedCRS'],
        'copy_operations': [],
        'legend': None,
    },
    '3 - Linework': {
        'standard_fields': ['ProjectID', 'MappedScale', 'MappedCRS'],
        'copy_operations': [],
        'legend': None,
    },
    '4 - Basemap': {
        'standard_fields': ['ProjectID', 'MappedScale', 'MappedCRS'],
        'copy_operations': [
            ('Lithology1', 'MappedLithology1', None),
            ('Lithology2', 'MappedLithology2', None),
        ],
        'legend': {
            'target_field': 'Description',
            'source_field': 'Lithology1',
            'lookup_table': 'BasemapCodes',
        },
    },
}


def create_compatible_field(name, field_type='string'):
    """Create QgsField with QGIS version compatibility"""
    try:
        # Try QGIS 3.34+ syntax first
        if QMetaType and hasattr(QMetaType, 'Type'):
            if field_type == 'string':
                return QgsField(name, QMetaType.Type.QString)
        # Fallback for older versions
        if field_type == 'string':
            return QgsField(name, QVariant.String)
    except Exception:
        # Final fallback to QGIS 3.4 syntax
        if field_type == 'string':
            return QgsField(name, QVariant.String)

    # Default fallback
    return QgsField(name, QVariant.String)


def is_empty(value):
    """True for None, QVariant null, blank strings and the literal 'NULL'."""
    if value is None:
        return True
    if hasattr(value, 'isNull'):
        try:
            return value.isNull()
        except Exception:
            pass
    text = str(value).strip()
    return text == '' or text == 'NULL'


def _norm(value):
    """Normalise a value for change comparison and lookup keys."""
    return '' if is_empty(value) else str(value).strip()


def _format_coordinate(value, geographic):
    """Format a geometry coordinate: degrees keep more precision than metres."""
    text = f"{value:.8f}" if geographic else f"{value:.3f}"
    return text.rstrip('0').rstrip('.')


def build_lookup_dict(lookup_layer):
    """Build {Code: Description} from a lookup table (first occurrence wins).

    Keys are normalised strings so integer/string code drift still matches.
    """
    lookup = {}
    for feat in lookup_layer.getFeatures():
        code = _norm(feat['Code'])
        if not code or code in lookup:
            continue
        desc = feat['Description']
        if not is_empty(desc):
            lookup[code] = str(desc)
    return lookup


@dataclass
class FieldChange:
    feature_id: int
    field_name: str
    current_value: object
    new_value: object
    source: str


@dataclass
class ColumnStats:
    name: str
    type_name: str
    filled: int
    missing: int
    distinct_count: int
    distinct_capped: bool
    sample_values: list
    notes: list = field(default_factory=list)
    will_modify: bool = False
    is_new: bool = False

    @property
    def pct_complete(self):
        total = self.filled + self.missing
        return (self.filled / total * 100.0) if total else 0.0


@dataclass
class UuidReport:
    field_name: object        # str or None when no UUID field detected
    missing_count: int = 0
    duplicates: dict = field(default_factory=dict)   # {value: [feature_ids]}

    @property
    def duplicate_feature_count(self):
        return sum(len(fids) for fids in self.duplicates.values())


@dataclass
class LayerReport:
    layer_id: str
    layer_name: str
    feature_count: int = 0
    scoped_feature_count: int = 0
    fields_to_create: list = field(default_factory=list)
    column_stats: list = field(default_factory=list)
    changes: list = field(default_factory=list)
    uuid_report: object = None
    missing_codes: list = field(default_factory=list)
    legend_skipped_reason: object = None
    notes: list = field(default_factory=list)

    def counts_by_source(self):
        counts = {}
        for ch in self.changes:
            counts[ch.source] = counts.get(ch.source, 0) + 1
        return counts


class _ColumnAccumulator:
    """Per-field stat accumulator used during the single feature pass."""

    __slots__ = ('filled', 'missing', 'distinct', 'capped', 'samples')

    def __init__(self):
        self.filled = 0
        self.missing = 0
        self.distinct = set()
        self.capped = False
        self.samples = []

    def add(self, value):
        if is_empty(value):
            self.missing += 1
            return
        self.filled += 1
        text = str(value)
        if self.capped:
            return
        if text not in self.distinct:
            self.distinct.add(text)
            if len(self.samples) < SAMPLE_VALUES_MAX:
                self.samples.append(text)
            if len(self.distinct) >= DISTINCT_CAP:
                self.capped = True


def analyze_layer(layer, config, *, project_id, mapped_scale, project_crs,
                  mode, lookup_layer=None, progress_cb=None):
    """Single-pass analysis of one layer.

    Computes column stats for ALL fields plus the complete change list for
    every change source. UUID fill is always empty-only (existing UUIDs are
    never overwritten) but respects selected-only scope; UUID duplicate
    detection runs over all features regardless of scope.

    MappedCRS records the LAYER's CRS — that is the CRS the geometry and
    any hardcoded coordinates are actually stored in.
    """
    report = LayerReport(layer_id=layer.id(), layer_name=layer.name())
    fields = layer.fields()
    field_names = [f.name() for f in fields]

    overwrite = (mode == MODE_OVERWRITE_ALL)
    scope_ids = set(layer.selectedFeatureIds()) if mode == MODE_SELECTED_ONLY else None

    layer_crs = layer.crs()
    layer_crs_id = layer_crs.authid()
    if project_crs and layer_crs_id and layer_crs_id != project_crs:
        report.notes.append(
            f"Layer CRS {layer_crs_id} differs from project CRS "
            f"{project_crs} — MappedCRS records the layer CRS (the CRS of "
            "the geometry/coordinates)")

    # Standard fields: fixed user-supplied values (CRS comes from the layer)
    standard_values = {'ProjectID': project_id, 'MappedScale': mapped_scale,
                       'MappedCRS': layer_crs_id}
    standard_ops = []           # (field_name, index_or_-1, new_value)
    for name in config['standard_fields']:
        idx = fields.indexOf(name)
        if idx == -1 and name not in report.fields_to_create:
            report.fields_to_create.append(name)
        standard_ops.append((name, idx, standard_values.get(name, '')))

    # Copy operations: need an existing source field, unless a geometry
    # axis provides a fallback value
    geographic = layer_crs.isGeographic()
    copy_ops = []   # (source_name, src_idx_or_-1, target_name, tgt_idx_or_-1, axis)
    for source_name, target_name, axis in config['copy_operations']:
        src_idx = fields.indexOf(source_name)
        if src_idx == -1 and axis is None:
            report.notes.append(
                f"Source field '{source_name}' not found — copy to "
                f"'{target_name}' skipped")
            continue
        if src_idx == -1:
            report.notes.append(
                f"Source field '{source_name}' not found — "
                f"'{target_name}' will be filled from geometry")
        tgt_idx = fields.indexOf(target_name)
        if tgt_idx == -1 and target_name not in report.fields_to_create:
            report.fields_to_create.append(target_name)
        copy_ops.append((source_name, src_idx, target_name, tgt_idx, axis))

    # Legend lookup
    legend_cfg = config.get('legend')
    legend_op = None            # (src_idx, target_name, tgt_idx_or_-1, lookup_dict)
    seen_codes = set()
    if legend_cfg:
        if lookup_layer is None:
            report.legend_skipped_reason = (
                f"No lookup table selected — '{legend_cfg['target_field']}' "
                "not updated")
        else:
            src_idx = fields.indexOf(legend_cfg['source_field'])
            if src_idx == -1:
                report.legend_skipped_reason = (
                    f"Source field '{legend_cfg['source_field']}' not found — "
                    f"'{legend_cfg['target_field']}' not updated")
            else:
                lookup_dict = build_lookup_dict(lookup_layer)
                target_name = legend_cfg['target_field']
                tgt_idx = fields.indexOf(target_name)
                if tgt_idx == -1 and target_name not in report.fields_to_create:
                    report.fields_to_create.append(target_name)
                legend_op = (src_idx, target_name, tgt_idx, lookup_dict)

    # UUID detection
    uuid_field_name = detect_uuid_field(field_names)
    uuid_idx = fields.indexOf(uuid_field_name) if uuid_field_name else -1
    uuid_values = {}            # value -> [feature_ids], for duplicate report
    uuid_report = UuidReport(field_name=uuid_field_name)

    accumulators = [_ColumnAccumulator() for _ in field_names]
    changes = report.changes

    def add_change(fid, field_name, current, new_value, source):
        changes.append(FieldChange(fid, field_name, current, new_value, source))

    for count, feat in enumerate(layer.getFeatures()):
        attrs = feat.attributes()
        fid = feat.id()

        for idx, acc in enumerate(accumulators):
            acc.add(attrs[idx])

        in_scope = scope_ids is None or fid in scope_ids
        if in_scope:
            report.scoped_feature_count += 1

            for name, idx, new_value in standard_ops:
                current = attrs[idx] if idx != -1 else None
                if ((overwrite or is_empty(current))
                        and _norm(current) != _norm(new_value)):
                    add_change(fid, name, current, new_value, SOURCE_STANDARD)

            feat_point = None   # lazily computed, shared by the x and y ops
            for source_name, src_idx, target_name, tgt_idx, axis in copy_ops:
                source_val = attrs[src_idx] if src_idx != -1 else None
                source = SOURCE_COPY
                if is_empty(source_val):
                    if axis is None:
                        continue   # never copy an empty value over anything
                    # Coordinate hardcoding: fall back to the point geometry
                    if feat_point is None:
                        geom = feat.geometry()
                        if geom is None or geom.isNull() or geom.isEmpty():
                            continue
                        feat_point = geom.centroid().asPoint()
                    coord = feat_point.x() if axis == 'x' else feat_point.y()
                    source_val = _format_coordinate(coord, geographic)
                    source = SOURCE_GEOMETRY
                current = attrs[tgt_idx] if tgt_idx != -1 else None
                if ((overwrite or is_empty(current))
                        and _norm(current) != _norm(source_val)):
                    add_change(fid, target_name, current, source_val,
                               source)

        if legend_op is not None:
            src_idx, target_name, tgt_idx, lookup_dict = legend_op
            code = _norm(attrs[src_idx])
            if code:
                seen_codes.add(code)
                if in_scope:
                    current = attrs[tgt_idx] if tgt_idx != -1 else None
                    new_value = lookup_dict.get(code)
                    if (new_value is not None
                            and (overwrite or is_empty(current))
                            and _norm(current) != _norm(new_value)):
                        add_change(fid, target_name, current, new_value,
                                   SOURCE_LEGEND)

        if uuid_idx != -1:
            value = attrs[uuid_idx]
            if is_empty(value):
                uuid_report.missing_count += 1
                if in_scope:
                    add_change(fid, uuid_field_name, value,
                               str(uuid.uuid4()), SOURCE_UUID)
            else:
                uuid_values.setdefault(str(value), []).append(fid)

        if progress_cb and count % PROGRESS_EVERY == 0:
            progress_cb(count)

    report.feature_count = layer.featureCount()
    if mode != MODE_SELECTED_ONLY:
        report.scoped_feature_count = report.feature_count

    uuid_report.duplicates = {
        value: fids for value, fids in uuid_values.items() if len(fids) > 1}
    report.uuid_report = uuid_report
    if uuid_field_name is None:
        report.notes.append("No UUID field detected — UUID checks skipped")

    if legend_op is not None:
        report.missing_codes = sorted(seen_codes - set(legend_op[3].keys()))

    # Build the per-column stats, flagging fields this run will write to
    modified_fields = {ch.field_name for ch in changes}
    planned_fields = {name for name, _idx, _val in standard_ops}
    planned_fields.update(target for _s, _si, target, _ti, _ax in copy_ops)
    if legend_op is not None:
        planned_fields.add(legend_op[1])

    for idx, name in enumerate(field_names):
        acc = accumulators[idx]
        stats = ColumnStats(
            name=name,
            type_name=fields[idx].typeName(),
            filled=acc.filled,
            missing=acc.missing,
            distinct_count=len(acc.distinct),
            distinct_capped=acc.capped,
            sample_values=acc.samples,
            will_modify=name in planned_fields or name in modified_fields,
        )
        if name in planned_fields or name in modified_fields:
            stats.notes.append("← will be filled/updated by this tool")
        if name == uuid_field_name:
            parts = [f"UUID field — {uuid_report.missing_count} missing"
                     + (" (will fill)" if uuid_report.missing_count else "")]
            if uuid_report.duplicates:
                parts.append(f"{len(uuid_report.duplicates)} duplicated "
                             "values (report only)")
            stats.notes.append("; ".join(parts))
            stats.will_modify = stats.will_modify or uuid_report.missing_count > 0
        report.column_stats.append(stats)

    # Fields that don't exist yet but will be created on commit
    for name in report.fields_to_create:
        report.column_stats.append(ColumnStats(
            name=name, type_name='(new)', filled=0,
            missing=report.feature_count, distinct_count=0,
            distinct_capped=False, sample_values=[],
            notes=["➕ field will be created by this tool"],
            will_modify=True, is_new=True))

    return report


def apply_layer_report(layer, report, progress_cb=None):
    """Apply the previewed changes for one layer. Returns (applied, errors)."""
    errors = []
    if not layer.isEditable() and not layer.startEditing():
        return 0, [f"Could not start editing '{layer.name()}'"]

    try:
        for name in report.fields_to_create:
            if layer.fields().indexOf(name) == -1:
                layer.addAttribute(create_compatible_field(name, 'string'))
        if report.fields_to_create:
            layer.updateFields()

        # Resolve indexes by name AFTER field creation
        index_cache = {}
        missing_reported = set()
        applied = 0
        for count, change in enumerate(report.changes):
            idx = index_cache.get(change.field_name)
            if idx is None:
                idx = layer.fields().indexOf(change.field_name)
                index_cache[change.field_name] = idx
            if idx == -1:
                if change.field_name not in missing_reported:
                    missing_reported.add(change.field_name)
                    errors.append(f"Field '{change.field_name}' not found — "
                                  "its changes were skipped")
                continue
            layer.changeAttributeValue(change.feature_id, idx, change.new_value)
            applied += 1
            if progress_cb and count % PROGRESS_EVERY == 0:
                progress_cb(count)

        if layer.commitChanges():
            layer.triggerRepaint()
            return applied, errors
        errors.extend(str(e) for e in layer.commitErrors())
        layer.rollBack()
        return 0, errors

    except Exception as exc:
        layer.rollBack()
        errors.append(str(exc))
        return 0, errors
