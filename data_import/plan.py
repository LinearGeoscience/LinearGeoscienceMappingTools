"""
The whole import as one reviewable object, and the checks that gate it.

Nothing is written until an ImportPlan validates clean, and the plan is the
only thing execute.py reads — the wizard's job is to build one, not to carry
decisions around in widget state. That separation is why the review page can
say exactly what will happen: it is describing the same object the writer will
consume, not a second guess at it.

The one invariant worth stating out loud: a plan contains no operation that
alters the destination's schema. There is no add-column op to construct.
Adding unmatched source columns to the target is what put
data_added_timestamp/data_added_batch_id onto two of the four layers of the
shipped template and nowhere else, and it is why importing an old project used
to leave the destination's forms and styling quietly broken.
"""

from collections import OrderedDict

try:
    from .domain import fold, uuid_field_of
    from . import match_fields, match_layers, match_values
except ImportError:  # flat execution / pure test loader
    from domain import fold, uuid_field_of
    import match_fields
    import match_layers
    import match_values


ERROR = 'error'
WARNING = 'warning'
NOTE = 'note'


class SourceRef(object):
    """Where one source layer's features come from."""

    __slots__ = ('kind', 'path', 'table', 'layer_id', 'selected_only', 'label')

    def __init__(self, kind='gpkg', path='', table='', layer_id='',
                 selected_only=False, label=''):
        self.kind = kind                    # 'gpkg' | 'layer'
        self.path = path
        self.table = table
        self.layer_id = layer_id
        self.selected_only = selected_only
        self.label = label or table

    def __repr__(self):
        return 'SourceRef({0}, {1!r})'.format(self.kind, self.label)


class DestinationRef(object):
    """Where features are written."""

    __slots__ = ('kind', 'path', 'label')

    def __init__(self, kind='gpkg', path='', label=''):
        self.kind = kind                    # 'gpkg' | 'project'
        self.path = path
        self.label = label

    def __repr__(self):
        return 'DestinationRef({0}, {1!r})'.format(self.kind, self.label)


class NewCode(object):
    """A code to add to the DESTINATION PROJECT's lookup table before writing.

    Never the shipped template — that stays byte-identical. A new code needs
    symbology afterwards, which Recode & Restyle does; the review page says so.
    """

    __slots__ = ('table', 'code', 'description', 'parent', 'field', 'count')

    def __init__(self, table, code, description='', parent='', field='',
                 count=0):
        self.table = table
        self.code = code
        self.description = description or code
        self.parent = parent
        self.field = field
        self.count = count

    def key(self):
        return (fold(self.table), fold(self.code))

    def __repr__(self):
        return 'NewCode({0}.{1!r})'.format(self.table, self.code)


class LayerImport(object):
    """One source layer landing in one destination layer."""

    def __init__(self, source, target_layer, field_plan=None,
                 resolutions=None, include=True, feature_count=0,
                 layer_match=None):
        # Filled by build_plan when both ends can be counted. Appending to a
        # master that already holds most of this file is the common case, and
        # "1,653 features" is a misleading thing to show when 1,600 of them are
        # already there.
        self.already_present = 0
        self.without_uuid = 0
        self.new_estimate = None
        self.source = source                  # SourceRef
        self.target_layer = target_layer      # destination table name
        self.field_plan = field_plan          # match_fields.LayerFieldPlan
        self.resolutions = resolutions or OrderedDict()
        # {target_field: OrderedDict[value -> ValueResolution]}
        self.include = include
        self.feature_count = feature_count
        self.layer_match = layer_match        # match_layers.LayerMatch

    # -- derived views -------------------------------------------------

    def mapping(self):
        return self.field_plan.mapping() if self.field_plan else OrderedDict()

    def comment_fields(self):
        return self.field_plan.to_comments() if self.field_plan else []

    def dropped_fields(self):
        return self.field_plan.dropped() if self.field_plan else []

    def all_resolutions(self):
        for field_resolutions in self.resolutions.values():
            for resolution in field_resolutions.values():
                yield resolution

    def undecided(self):
        return [resolution for resolution in self.all_resolutions()
                if not resolution.decided]

    def attention(self):
        return [resolution for resolution in self.all_resolutions()
                if resolution.needs_attention]

    def new_codes(self, target_spec):
        """NewCode rows implied by 'add this code' decisions on this layer."""
        codes = OrderedDict()
        for target_field, field_resolutions in self.resolutions.items():
            domain = target_spec.domain(target_field)
            if domain is None or not domain.table:
                continue
            for resolution in field_resolutions.values():
                if resolution.status != match_values.ADD_CODE:
                    continue
                new_code = NewCode(
                    table=domain.table,
                    code=resolution.code or resolution.value,
                    description=resolution.new_code_description,
                    parent=resolution.new_code_parent,
                    field=target_field,
                    count=resolution.count)
                codes.setdefault(new_code.key(), new_code)
        return list(codes.values())

    def value_counts_by_status(self):
        return match_values.summarise(list(self.all_resolutions()))

    @property
    def expected_new(self):
        """Features expected to land. None when it could not be worked out."""
        return (self.feature_count if self.new_estimate is None
                else self.new_estimate)

    def __repr__(self):
        return 'LayerImport({0!r} -> {1!r}, {2} features)'.format(
            self.source.label, self.target_layer, self.feature_count)


class Finding(object):
    """One line of the validation report."""

    __slots__ = ('level', 'title', 'detail', 'layer')

    def __init__(self, level, title, detail='', layer=''):
        self.level = level
        self.title = title
        self.detail = detail
        self.layer = layer

    def __repr__(self):
        return 'Finding({0}, {1!r})'.format(self.level, self.title)


class ValidationReport(object):
    """Blocking errors kept apart from things worth knowing."""

    def __init__(self, findings=None):
        self.findings = list(findings or [])

    def add(self, level, title, detail='', layer=''):
        self.findings.append(Finding(level, title, detail, layer))

    @property
    def errors(self):
        return [f for f in self.findings if f.level == ERROR]

    @property
    def warnings(self):
        return [f for f in self.findings if f.level == WARNING]

    @property
    def notes(self):
        return [f for f in self.findings if f.level == NOTE]

    @property
    def ok(self):
        return not self.errors

    def __repr__(self):
        return 'ValidationReport({0} errors, {1} warnings)'.format(
            len(self.errors), len(self.warnings))


class ImportOptions(object):
    """Run-time switches, all with a safe default."""

    __slots__ = ('skip_duplicate_uuids', 'generate_missing_uuids', 'backup',
                 'apply_defaults', 'split_multiparts', 'stamp_batch',
                 'date_filter', 'use_uuid_tracker')

    def __init__(self, skip_duplicate_uuids=True, generate_missing_uuids=True,
                 backup=True, apply_defaults=True, split_multiparts=True,
                 stamp_batch=True, date_filter=None, use_uuid_tracker=True):
        self.skip_duplicate_uuids = skip_duplicate_uuids
        self.generate_missing_uuids = generate_missing_uuids
        self.backup = backup
        self.apply_defaults = apply_defaults
        self.split_multiparts = split_multiparts
        # Only ever written to columns that ALREADY exist on the destination.
        self.stamp_batch = stamp_batch
        # The date-filter widget's config dict, or None. Kept because appending
        # a season's field data by date is a real workflow, distinct from the
        # migration this tool was rebuilt for.
        self.date_filter = date_filter
        # Consult the JSON UUID ledger beside the destination as well as the
        # layer itself, so a feature that was imported and then deliberately
        # deleted does not come back on the next run.
        self.use_uuid_tracker = use_uuid_tracker


class ImportPlan(object):
    """Everything the writer needs, and nothing it has to infer."""

    def __init__(self, source_model, target_model, destination,
                 layer_imports=None, options=None):
        self.source_model = source_model
        self.target_model = target_model
        self.destination = destination        # DestinationRef
        self.layer_imports = layer_imports or []
        self.options = options or ImportOptions()

    # -- views ---------------------------------------------------------

    def included(self):
        return [item for item in self.layer_imports if item.include]

    def target_spec(self, layer_import):
        return self.target_model.layers.get(layer_import.target_layer)

    def total_features(self):
        return sum(item.feature_count for item in self.included())

    def total_expected_new(self):
        return sum(item.expected_new for item in self.included())

    def total_already_present(self):
        return sum(item.already_present for item in self.included())

    def total_without_uuid(self):
        return sum(item.without_uuid for item in self.included())

    def new_codes(self):
        codes = OrderedDict()
        for item in self.included():
            spec = self.target_spec(item)
            if spec is None:
                continue
            for new_code in item.new_codes(spec):
                codes.setdefault(new_code.key(), new_code)
        return list(codes.values())

    def register_new_codes(self, new_codes=None):
        """Teach the in-memory code domains about codes added by this run.

        Called once the rows are actually in the destination's lookup tables,
        so parent back-fill treats a new code exactly like a shipped one.
        Every domain sharing that table learns it, not just the field that
        asked for it — OverlayCodes feeds four fields across two layers.
        """
        added = 0
        for new_code in (new_codes if new_codes is not None else self.new_codes()):
            for layer_spec in self.target_model.layers.values():
                for domain_ in layer_spec.code_domains.values():
                    if not domain_.table or fold(domain_.table) != fold(new_code.table):
                        continue
                    if domain_.allowed_parents and fold(new_code.parent) not in {
                            fold(value) for value in domain_.allowed_parents}:
                        continue
                    if domain_.add_entry(new_code.code, new_code.description,
                                         new_code.parent):
                        added += 1
        return added

    def undecided_count(self):
        return sum(len(item.undecided()) for item in self.included())

    def status_totals(self):
        totals = OrderedDict()
        for item in self.included():
            for status, count in item.value_counts_by_status().items():
                totals[status] = totals.get(status, 0) + count
        return totals

    # -- validation ----------------------------------------------------

    def validate(self):
        report = ValidationReport()
        included = self.included()

        if not included:
            report.add(ERROR, 'Nothing selected to import',
                       'Choose at least one layer on the Layers step.')
            return report

        if (self.destination.kind == 'gpkg' and self.source_model.path
                and _same_file(self.destination.path, self.source_model.path)):
            report.add(ERROR, 'Source and destination are the same file',
                       self.destination.path)

        destination_crs = self.target_model.primary_crs()

        for item in included:
            label = item.source.label
            target_spec = self.target_spec(item)

            if not item.target_layer or target_spec is None:
                report.add(ERROR, 'No destination chosen for {0}'.format(label),
                           'Pick a destination layer on the Layers step.',
                           layer=label)
                continue

            if item.layer_match is not None and item.layer_match.blocked:
                report.add(ERROR, 'Cannot import {0}'.format(label),
                           item.layer_match.blocked, layer=label)
                continue

            source_spec = self.source_model.layers.get(item.source.table)
            if source_spec is not None and not match_layers.geometry_compatible(
                    source_spec, target_spec):
                report.add(
                    ERROR, 'Geometry does not match for {0}'.format(label),
                    '{0} holds {1}; {2} holds {3}.'.format(
                        label, source_spec.geometry_type or 'unknown',
                        item.target_layer, target_spec.geometry_type
                        or 'unknown'),
                    layer=label)
                continue

            undecided = item.undecided()
            if undecided:
                shown = ', '.join(sorted({r.value for r in undecided})[:6])
                report.add(
                    ERROR,
                    '{0} code value{1} still {2} a decision in {3}'.format(
                        len(undecided), '' if len(undecided) == 1 else 's',
                        'needs' if len(undecided) == 1 else 'need', label),
                    shown, layer=label)

            changed = [r for r in item.all_resolutions()
                       if r.status == match_values.MEANING_CHANGED]
            if changed:
                report.add(
                    WARNING,
                    '{0} code{1} kept the same spelling but changed meaning'
                    .format(len(changed), '' if len(changed) == 1 else 's'),
                    '; '.join(r.note for r in changed[:4]), layer=label)

            renamed = [r for r in item.all_resolutions()
                       if r.status == match_values.RENAMED]
            if renamed:
                report.add(
                    NOTE, '{0} code{1} renamed automatically'.format(
                        len(renamed), '' if len(renamed) == 1 else 's'),
                    '; '.join(r.note for r in renamed[:4]), layer=label)

            split = [r for r in item.all_resolutions()
                     if r.status == match_values.SPLIT]
            if split:
                fields = sorted({field for r in split for field in r.extras})
                report.add(
                    NOTE, '{0} code{1} split into {2}'.format(
                        len(split), '' if len(split) == 1 else 's',
                        ' and '.join(fields) or 'another field'),
                    '; '.join(r.note for r in split[:4]), layer=label)

            dropped = item.dropped_fields()
            if dropped:
                report.add(
                    WARNING,
                    '{0} column{1} in {2} will not be imported'.format(
                        len(dropped), '' if len(dropped) == 1 else 's', label),
                    ', '.join(dropped), layer=label)

            to_comments = item.comment_fields()
            if to_comments:
                report.add(NOTE, 'Kept in Comments',
                           ', '.join(to_comments), layer=label)

            if item.field_plan is not None:
                bad_types = [match.source_name
                             for match in item.field_plan.matches.values()
                             if match.is_mapped and not match.type_ok]
                if bad_types:
                    report.add(
                        ERROR, 'Incompatible column types in {0}'.format(label),
                        ', '.join(bad_types), layer=label)

            # Required destination columns nothing will fill.
            mapped_targets = set(item.mapping().values())
            for name, note in (item.field_plan.target_notes.items()
                               if item.field_plan else []):
                if not note.required or name in mapped_targets:
                    continue
                if note.how in ('default', 'derived'):
                    continue
                report.add(
                    WARNING, '{0} is required but will be empty'.format(name),
                    'Features will import; the form will flag them until it is '
                    'filled in.', layer=label)

            # Geometry dimension.
            if (source_spec is not None and source_spec.has_z
                    and not target_spec.has_z):
                detail = 'Z values go into Elevation instead.' \
                    if 'Elevation' in target_spec.fields else \
                    'Z values will be discarded.'
                report.add(WARNING,
                           '{0} carries 3D geometry; {1} does not'.format(
                               label, item.target_layer),
                           detail, layer=label)

            source_crs = (self.source_model.crs_of(item.source.table)
                          if item.source.kind == 'gpkg' else '')
            if source_crs and destination_crs and source_crs != destination_crs:
                report.add(
                    WARNING, 'Coordinates will be reprojected',
                    '{0} is {1}; the destination is {2}.'.format(
                        label, source_crs, destination_crs), layer=label)

        for item in included:
            label = item.source.label
            if item.new_estimate is not None and item.already_present:
                if item.new_estimate == 0:
                    report.add(
                        WARNING,
                        'Nothing new in {0}'.format(label),
                        'All {0:,} features are already in the destination, '
                        'matched on UUID. Nothing will be added.'.format(
                            item.already_present), layer=label)
                else:
                    report.add(
                        NOTE, '{0}: {1:,} new, {2:,} already there'.format(
                            label, item.new_estimate, item.already_present),
                        'Existing features are matched on UUID and skipped.',
                        layer=label)
            if item.without_uuid:
                report.add(
                    WARNING,
                    '{0:,} feature(s) in {1} have no UUID'.format(
                        item.without_uuid, label),
                    'They will be given new ones, so importing this same file '
                    'again would add them a second time. Everything with a '
                    'UUID is still matched and skipped as normal.',
                    layer=label)

        new_codes = self.new_codes()
        if new_codes:
            report.add(
                NOTE,
                '{0} new code{1} will be added to the destination'.format(
                    len(new_codes), '' if len(new_codes) == 1 else 's'),
                ', '.join('{0} in {1}'.format(code.code, code.table)
                          for code in new_codes[:6])
                + '. Run Recode & Restyle afterwards to give them symbology.')

        return report

    # -- summary for the review page -----------------------------------

    def summary(self):
        totals = self.status_totals()
        auto = sum(count for status, count in totals.items()
                   if status in match_values.AUTO_STATUSES)
        return {
            'layers': len(self.included()),
            'features': self.total_features(),
            'expected_new': self.total_expected_new(),
            'already_present': self.total_already_present(),
            'without_uuid': self.total_without_uuid(),
            'codes_total': sum(totals.values()),
            'codes_auto': auto,
            'codes_by_status': totals,
            'new_codes': len(self.new_codes()),
            'undecided': self.undecided_count(),
            'destination': self.destination.label or self.destination.path,
        }

    def __repr__(self):
        return 'ImportPlan({0} layers, {1} features)'.format(
            len(self.included()), self.total_features())


def _same_file(left, right):
    import os
    if not left or not right:
        return False
    return (os.path.normcase(os.path.abspath(left))
            == os.path.normcase(os.path.abspath(right)))


# ── assembly ──────────────────────────────────────────────────────────

def build_plan(source_model, target_model, destination, value_counts_for,
               source_describe_for=None, profile=None, options=None,
               source_refs=None, source_uuids_for=None,
               destination_uuids_for=None):
    """Auto-build a complete plan. The wizard then edits it in place.

    `value_counts_for(source_table, fields)` returns {field: ValueCounts} —
    injected so the same assembly works for a GeoPackage table and for a
    filtered layer loaded in QGIS.

    `source_describe_for(table_name)` returns a callable code -> description
    using the SOURCE's own lookup table of that name, or None when the source
    has no code tables. That is what powers rename detection.

    `source_uuids_for(table)` and `destination_uuids_for(layer)` return sets of
    UUIDs. Optional, and only used to say up front how much of an append is
    actually new — the writer does its own matching regardless.
    """
    profile = profile or {}
    seeded_layers = profile.get('layers') or {}
    seeded_fields = profile.get('fields') or {}
    seeded_values = profile.get('values') or {}

    layer_matches = match_layers.match_layers(source_model, target_model,
                                              seeded=seeded_layers)

    layer_imports = []
    for source_name, layer_match in layer_matches.items():
        source_spec = source_model.layers[source_name]
        reference = (source_refs or {}).get(source_name) or SourceRef(
            kind='gpkg', path=source_model.path, table=source_name,
            label=source_name)

        item = LayerImport(
            source=reference,
            target_layer=layer_match.target_name,
            include=bool(layer_match.target_name) and not layer_match.blocked,
            feature_count=source_spec.feature_count,
            layer_match=layer_match)
        layer_imports.append(item)

        target_spec = target_model.layers.get(layer_match.target_name)
        if target_spec is None:
            continue

        _estimate_new(item, source_spec, target_spec, source_uuids_for,
                      destination_uuids_for)

        item.field_plan = match_fields.match_fields(
            source_spec, target_spec,
            seeded=seeded_fields.get(source_name))

        coded = [(source_field, target_field)
                 for source_field, target_field in item.field_plan.mapping().items()
                 if target_spec.domain(target_field) is not None]
        if not coded:
            continue

        counts = value_counts_for(source_name,
                                  [source_field for source_field, _t in coded])
        for source_field, target_field in coded:
            domain = target_spec.domain(target_field)
            bucket = counts.get(source_field)
            if bucket is None or not bucket.counts:
                continue
            describe = None
            if source_describe_for is not None and domain.table:
                describe = source_describe_for(domain.table)
            item.resolutions[target_field] = match_values.resolve_field(
                target_field, bucket, domain, layer_spec=target_spec,
                source_describe=describe,
                seeded=(seeded_values.get(source_name, {})
                        .get(target_field, {})))

    return ImportPlan(source_model, target_model, destination, layer_imports,
                      options or ImportOptions())


def _estimate_new(item, source_spec, target_spec, source_uuids_for,
                  destination_uuids_for):
    """Work out how much of this layer is genuinely new, before writing."""
    if source_uuids_for is None or destination_uuids_for is None:
        return
    if not uuid_field_of(source_spec) or not uuid_field_of(target_spec):
        return
    try:
        source_uuids, blank = source_uuids_for(item.source.table)
        existing = destination_uuids_for(item.target_layer)
    except Exception:
        return
    if source_uuids is None or existing is None:
        return
    item.without_uuid = blank
    item.already_present = len(source_uuids & existing)
    item.new_estimate = len(source_uuids - existing) + blank
