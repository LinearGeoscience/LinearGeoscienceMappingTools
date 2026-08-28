"""
The wizard shell and the state its pages share.

Five questions in order — what am I importing, into which layers, into which
columns, what do the old codes become, and is this right — then a sixth page
that runs it. Each page owns one question and nothing else, which is the whole
reason this replaced a single window with a modal-inside-a-modal for layer
mapping and another for value recoding.

Non-modal on purpose. The old tool was ApplicationModal and always-on-top, so
you could not look at the attribute table you were trying to reason about while
deciding what a code should become.
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QMessageBox, QWizard

try:
    from .. import domain, plan as plan_module, scan
    from ..domain import uuid_field_of
    from . import (page_codes, page_fields, page_layers, page_review,
                   page_run, page_source, style)
except ImportError:  # direct (non-package) execution inside QGIS
    from data_import import domain, plan as plan_module, scan
    from data_import.domain import uuid_field_of
    from data_import.wizard import (page_codes, page_fields, page_layers,
                                    page_review, page_run, page_source, style)


def describer_for(model):
    """A table_name -> (code -> description) factory, or None.

    Only an LGS-shaped source carries its own code tables, and only then can a
    rename be proved rather than guessed — so the absence of tables is the
    absence of a describer, not an empty one.
    """
    if not model or not model.tables:
        return None

    def factory(table_name):
        return lambda code: model.describe_code(table_name, code)

    return factory


PAGE_SOURCE = 0
PAGE_LAYERS = 1
PAGE_FIELDS = 2
PAGE_CODES = 3
PAGE_REVIEW = 4
PAGE_RUN = 5


class WizardState(object):
    """Everything the pages agree on, in one place."""

    def __init__(self):
        # Chosen on page 1.
        self.source_kind = 'gpkg'          # 'gpkg' | 'layers'
        self.source_path = ''
        self.source_layer_ids = []
        self.selected_only = False
        self.destination_kind = 'project'  # 'project' | 'gpkg'
        self.destination_path = ''

        # Captured on the MAIN thread by page 1, read by the worker.
        # counts_provider(table, fields) -> {field: ValueCounts}; source_refs
        # says where each layer's features come from; layer_snapshots holds the
        # QgsVectorLayerFeatureSource objects alive for the duration.
        # The paths the CURRENT analysis was started against. Pinned on the
        # main thread so the worker cannot read a file the readers were not
        # built for.
        self.analysis_source_path = ''
        self.analysis_destination_path = ''
        self.counts_provider = None
        self.source_uuids_provider = None
        self.destination_uuids_provider = None
        self.source_refs = {}
        self.layer_snapshots = {}

        # Derived by the analysis step.
        self.source_model = None
        self.target_model = None
        self.plan = None
        self.profile = None
        self.date_filter = None
        self.analysis_error = ''

    def reset_analysis(self):
        self.source_model = None
        self.target_model = None
        self.plan = None
        self.analysis_error = ''

    @property
    def ready(self):
        return self.plan is not None

    def destination_label(self):
        if self.destination_kind == 'project':
            resolved = os.path.basename(self.analysis_destination_path or '')
            return ('this project ({0})'.format(resolved) if resolved
                    else 'this project')
        return os.path.basename(self.destination_path) or self.destination_path

    def source_label(self):
        if self.source_kind == 'gpkg':
            return os.path.basename(self.source_path) or self.source_path
        return '{0} layer(s) open in QGIS'.format(len(self.source_layer_ids))


class ImportWizard(QWizard):
    """Import Mapping Data."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.state = WizardState()

        self.setWindowTitle('Import Mapping Data')
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.WizardOption.IndependentPages, False)
        self.setStyleSheet(style.wizard_style())
        width, height = style.scaled(1040, 720)
        self.resize(width, height)

        self.setPage(PAGE_SOURCE, page_source.SourcePage(self))
        self.setPage(PAGE_LAYERS, page_layers.LayersPage(self))
        self.setPage(PAGE_FIELDS, page_fields.FieldsPage(self))
        self.setPage(PAGE_CODES, page_codes.CodesPage(self))
        self.setPage(PAGE_REVIEW, page_review.ReviewPage(self))
        self.setPage(PAGE_RUN, page_run.RunPage(self))

        self.setButtonText(QWizard.WizardButton.CommitButton, 'Import')
        self.setButtonText(QWizard.WizardButton.FinishButton, 'Close')

    # -- shared services ----------------------------------------------

    def build_plan(self, progress_cb=None):
        """Read both ends and auto-decide everything that can be auto-decided.

        Runs on a worker thread for a GeoPackage source. A source that is a
        layer loaded in QGIS is captured on the main thread first (see
        page_source), because a provider read off the main thread is not safe.
        """
        state = self.state

        def note(percent, message):
            if progress_cb is not None:
                progress_cb(percent, message)

        source_path = state.analysis_source_path or state.source_path
        destination_path = (state.analysis_destination_path
                            or state.destination_path)

        note(5, 'Reading the destination...')
        if state.destination_kind == 'gpkg':
            target_model = domain.read_gpkg_model(destination_path)
            destination = plan_module.DestinationRef(
                'gpkg', destination_path,
                os.path.basename(destination_path))
        else:
            target_model = state.target_model     # captured on the main thread
            # The path was resolved from the mapping layers and pinned on the
            # main thread (page_source); the model's own path is only a
            # fallback. The label names the file so the review page shows
            # where the features will actually land.
            resolved = (state.analysis_destination_path
                        or (target_model.path if target_model else ''))
            destination = plan_module.DestinationRef(
                'project', resolved,
                'this project ({0})'.format(os.path.basename(resolved))
                if resolved else 'this project')

        note(25, 'Reading the source...')
        source_model = state.source_model
        if state.source_kind == 'gpkg':
            source_model = domain.read_gpkg_model(source_path)

        note(45, 'Matching layers and columns...')

        counts_cache = {}

        def value_counts_for(table, fields):
            key = (table, tuple(fields))
            if key not in counts_cache:
                counts_cache[key] = state.counts_provider(table, fields)
            return counts_cache[key]

        describe_for = describer_for(source_model)

        note(60, 'Working out what is new and what the old codes become...')

        uuid_source_path = (destination.path or target_model.path or '')

        def destination_uuids(layer_name, _p=uuid_source_path):
            spec = target_model.layers.get(layer_name)
            column = uuid_field_of(spec) if spec else ''
            if not column or not _p:
                return None
            return scan.gpkg_column_set(_p, layer_name, column)

        built = plan_module.build_plan(
            source_model, target_model, destination, value_counts_for,
            source_describe_for=describe_for,
            profile=state.profile or {},
            source_refs=state.source_refs,
            source_uuids_for=state.source_uuids_provider,
            destination_uuids_for=destination_uuids)

        built.options.date_filter = state.date_filter
        # Kept so re-pointing a layer on the Layers page can redo its estimate
        # against the new destination rather than keep the old one's numbers.
        state.destination_uuids_provider = destination_uuids

        note(95, 'Done.')
        return source_model, target_model, built

    def rebuild_layer(self, layer_import):
        """Redo one layer's column and code matching after its target changed.

        A different destination layer means a different column set and
        different code lists, so keeping the old matches would leave decisions
        pointing at columns that are no longer there. Everything is discarded
        deliberately.
        """
        from .. import match_fields

        state = self.state
        layer_import.field_plan = None
        layer_import.resolutions.clear()
        if not layer_import.target_layer:
            return

        source_spec = state.source_model.layers.get(layer_import.source.table)
        target_spec = state.target_model.layers.get(layer_import.target_layer)
        if source_spec is None or target_spec is None:
            return

        # The old target's "already there" and "repeated" counts say nothing
        # about the new one.
        plan_module.estimate_new(
            layer_import, source_spec, target_spec,
            state.source_uuids_provider, state.destination_uuids_provider)

        layer_import.field_plan = match_fields.match_fields(source_spec,
                                                            target_spec)
        self.refresh_resolutions(layer_import, preserve=False)

    def refresh_resolutions(self, layer_import, preserve=True):
        """Re-resolve code values for the columns currently paired up.

        Called whenever the column pairing may have changed. Decisions the user
        has already made are carried across by default — re-pointing one column
        must not silently throw away twenty code decisions made on another.
        """
        from .. import match_values

        state = self.state
        target_spec = state.target_model.layers.get(layer_import.target_layer)
        if target_spec is None or layer_import.field_plan is None:
            return

        kept = {}
        if preserve:
            for target_field, resolutions in layer_import.resolutions.items():
                kept[target_field] = {
                    value: resolution.as_profile_entry()
                    for value, resolution in resolutions.items()
                    if resolution.status in (match_values.MANUAL,
                                             match_values.ADD_CODE,
                                             match_values.BLANK)}

        coded = [(source_field, target_field)
                 for source_field, target_field
                 in layer_import.field_plan.mapping().items()
                 if target_spec.domain(target_field) is not None]
        layer_import.resolutions.clear()
        if not coded or state.counts_provider is None:
            return

        counts = state.counts_provider(layer_import.source.table,
                                       [name for name, _t in coded])
        for source_field, target_field in coded:
            domain_ = target_spec.domain(target_field)
            bucket = counts.get(source_field)
            if bucket is None or not bucket.counts:
                continue
            factory = describer_for(state.source_model)
            describe = (factory(domain_.table)
                        if factory and domain_.table else None)
            layer_import.resolutions[target_field] = match_values.resolve_field(
                target_field, bucket, domain_, layer_spec=target_spec,
                source_describe=describe,
                seeded=kept.get(target_field, {}))

    def warn(self, title, message):
        QMessageBox.warning(self, title, message)


def run_import_dialog(qgis_iface):
    """Open the wizard, re-raising an existing one rather than stacking."""
    existing = getattr(qgis_iface, '_data_import_wizard', None)
    if existing is not None:
        try:
            existing.show()
            existing.activateWindow()
            existing.raise_()
            return existing
        except RuntimeError:
            qgis_iface._data_import_wizard = None

    wizard = ImportWizard(qgis_iface, parent=qgis_iface.mainWindow())
    wizard.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    wizard.setWindowFlags(Qt.WindowType.Window)
    wizard.destroyed.connect(
        lambda: setattr(qgis_iface, '_data_import_wizard', None))
    qgis_iface._data_import_wizard = wizard
    wizard.show()
    wizard.activateWindow()
    wizard.raise_()
    return wizard
