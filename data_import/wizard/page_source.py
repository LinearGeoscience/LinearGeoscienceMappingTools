"""
Step 1 — what is being imported, and where into.

The page does more than collect two paths: as soon as both ends are known it
reads them and works out everything it can, so by the time the user presses
Next the layers, columns and codes are already matched. That analysis runs on
the task pool, because a filtered PostGIS layer is a perfectly ordinary source
here and counting its values must not freeze QGIS.

Anything that has to touch a project layer — capturing a feature source,
reading the open project's model — happens here on the main thread first, and
the worker only ever sees the snapshots.
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QProgressBar, QPushButton, QRadioButton, QVBoxLayout, QWizardPage,
)
from qgis.core import Qgis, QgsProject, QgsVectorLayerFeatureSource

try:
    from ... import lgs_layers
    from ...lgs_tasks import run_in_task
    from .. import domain, plan as plan_module, profile as profile_module, scan
    from ..date_filter import GlobalDateFilterWidget
    from . import style
except ImportError:  # direct (non-package) execution inside QGIS
    import lgs_layers
    from lgs_tasks import run_in_task
    from data_import import (domain, plan as plan_module,
                             profile as profile_module, scan)
    from data_import.date_filter import GlobalDateFilterWidget
    from data_import.wizard import style


class SourcePage(QWizardPage):

    def __init__(self, wizard):
        super().__init__(wizard)
        self.wizard_ref = wizard
        self._task = None
        self._restart_pending = False
        self._analysed = False
        self._loaded_profile_path = ''

        self.setTitle('What are you importing?')
        self.setSubTitle('Pick the mapping data to bring in and the project to '
                         'bring it into. Everything else is worked out for you.')

        layout = QVBoxLayout(self)

        # -- source ---------------------------------------------------
        source_box = QGroupBox('Import from')
        source_layout = QVBoxLayout(source_box)

        self.source_file_radio = QRadioButton('A GeoPackage file')
        self.source_file_radio.setChecked(True)
        source_layout.addWidget(self.source_file_radio)

        file_row = QHBoxLayout()
        file_row.addSpacing(22)
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText('Choose the mapping GeoPackage...')
        browse = QPushButton('Browse...')
        browse.clicked.connect(self._browse_source)
        file_row.addWidget(self.source_edit)
        file_row.addWidget(browse)
        source_layout.addLayout(file_row)

        self.source_layers_radio = QRadioButton('Layers open in QGIS')
        source_layout.addWidget(self.source_layers_radio)
        source_layout.addWidget(style.hint(
            '        Use this to bring in a filtered subset from a database — '
            'whatever the layer is currently showing is what gets imported.'))

        layers_row = QHBoxLayout()
        layers_row.addSpacing(22)
        self.layer_list = QListWidget()
        self.layer_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.layer_list.setMaximumHeight(style.scaled(100, 110)[1])
        layers_row.addWidget(self.layer_list)
        source_layout.addLayout(layers_row)

        selected_row = QHBoxLayout()
        selected_row.addSpacing(22)
        self.selected_only_check = QCheckBox(
            'Only the features currently selected')
        selected_row.addWidget(self.selected_only_check)
        selected_row.addStretch()
        source_layout.addLayout(selected_row)

        layout.addWidget(source_box)

        # -- destination ----------------------------------------------
        destination_box = QGroupBox('Import into')
        destination_layout = QVBoxLayout(destination_box)

        self.destination_project_radio = QRadioButton('This project')
        destination_layout.addWidget(self.destination_project_radio)
        self.project_hint = style.hint('')
        destination_layout.addWidget(self.project_hint)

        self.destination_file_radio = QRadioButton('A GeoPackage file')
        destination_layout.addWidget(self.destination_file_radio)

        destination_row = QHBoxLayout()
        destination_row.addSpacing(22)
        self.destination_edit = QLineEdit()
        self.destination_edit.setPlaceholderText(
            'Choose the project GeoPackage to import into...')
        destination_browse = QPushButton('Browse...')
        destination_browse.clicked.connect(self._browse_destination)
        destination_row.addWidget(self.destination_edit)
        destination_row.addWidget(destination_browse)
        destination_layout.addLayout(destination_row)

        layout.addWidget(destination_box)

        # -- optional date filter -------------------------------------
        # Kept from the old tool: appending one season's field data by date is
        # a real workflow, and it is not the same thing as the duplicate check.
        self.date_filter = GlobalDateFilterWidget()
        layout.addWidget(self.date_filter)

        # -- saved profile --------------------------------------------
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel('Saved settings:'))
        self.profile_combo = QComboBox()
        self.profile_combo.addItem('Work it out from scratch', '')
        profile_row.addWidget(self.profile_combo, 1)
        load_profile = QPushButton('Load from file...')
        load_profile.clicked.connect(self._load_profile_file)
        profile_row.addWidget(load_profile)
        layout.addLayout(profile_row)

        # -- status ---------------------------------------------------
        self.status_label = style.hint('')
        layout.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        layout.addStretch()

        for widget in (self.source_file_radio, self.source_layers_radio,
                       self.destination_project_radio,
                       self.destination_file_radio):
            widget.toggled.connect(self._on_mode_changed)
        self.source_edit.textChanged.connect(self._on_input_changed)
        self.destination_edit.textChanged.connect(self._on_input_changed)
        self.layer_list.itemChanged.connect(self._on_input_changed)
        self.selected_only_check.toggled.connect(self._on_input_changed)

    # -- page lifecycle ------------------------------------------------

    def initializePage(self):
        self._populate_layers()
        self._populate_destination()
        last_source, last_destination = profile_module.recall_paths()
        if last_source and not self.source_edit.text():
            self.source_edit.setText(last_source)
        if (last_destination and not self.destination_edit.text()
                and not self.destination_project_radio.isChecked()):
            self.destination_edit.setText(last_destination)
        self._on_mode_changed()

    def isComplete(self):
        return self._analysed and self.wizard_ref.state.ready

    def validatePage(self):
        return self._analysed and self.wizard_ref.state.ready

    # -- population ----------------------------------------------------

    def _populate_layers(self):
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            if layer.type() != Qgis.LayerType.Vector or not layer.isSpatial():
                continue
            item = QListWidgetItem('{0}  ({1} features)'.format(
                layer.name(), max(layer.featureCount(), 0)))
            item.setData(Qt.ItemDataRole.UserRole, layer.id())
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.layer_list.addItem(item)
        self.layer_list.blockSignals(False)

    def _populate_destination(self):
        found = lgs_layers.find_layers(QgsProject.instance())
        if found:
            self.destination_project_radio.setEnabled(True)
            self.destination_project_radio.setChecked(True)
            self.project_hint.setText(
                '        Found {0} in the open project.'.format(
                    ', '.join(sorted(found))))
        else:
            self.destination_project_radio.setEnabled(False)
            self.destination_file_radio.setChecked(True)
            self.project_hint.setText(
                '        No LGS mapping layers are open — choose a '
                'GeoPackage instead, or load a project first.')

    # -- interaction ---------------------------------------------------

    def _browse_source(self):
        start = os.path.dirname(self.source_edit.text()) or ''
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select the mapping GeoPackage to import', start,
            'GeoPackage (*.gpkg)')
        if path:
            self.source_file_radio.setChecked(True)
            self.source_edit.setText(path)

    def _browse_destination(self):
        start = os.path.dirname(self.destination_edit.text()) or ''
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select the project GeoPackage to import into', start,
            'GeoPackage (*.gpkg)')
        if path:
            self.destination_file_radio.setChecked(True)
            self.destination_edit.setText(path)

    def _load_profile_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Load saved import settings', '', 'Import settings (*.json)')
        if not path:
            return
        loaded = profile_module.import_from_file(path)
        if loaded is None:
            self.wizard_ref.warn('Could not read that file',
                                 'It does not look like exported import '
                                 'settings.')
            return
        self._loaded_profile_path = path
        index = self.profile_combo.count()
        self.profile_combo.addItem(profile_module.describe(loaded), 'file')
        self.profile_combo.setItemData(index, loaded, Qt.ItemDataRole.UserRole + 1)
        self.profile_combo.setCurrentIndex(index)
        self._on_input_changed()

    def _on_mode_changed(self, *_args):
        file_source = self.source_file_radio.isChecked()
        self.source_edit.setEnabled(file_source)
        self.layer_list.setEnabled(not file_source)
        self.selected_only_check.setEnabled(not file_source)
        self.destination_edit.setEnabled(
            self.destination_file_radio.isChecked())
        self._on_input_changed()

    def _on_input_changed(self, *_args):
        self._analysed = False
        self.wizard_ref.state.reset_analysis()
        self.completeChanged.emit()
        if self._inputs_ready():
            self._start_analysis()
        else:
            self.status_label.setText('')

    def _inputs_ready(self):
        state = self._collect_state()
        if state is None:
            return False
        if state.source_kind == 'gpkg':
            if not state.source_path or not os.path.exists(state.source_path):
                return False
        elif not state.source_layer_ids:
            return False
        if state.destination_kind == 'gpkg':
            if (not state.destination_path
                    or not os.path.exists(state.destination_path)):
                return False
        return True

    def _collect_state(self):
        state = self.wizard_ref.state
        state.source_kind = ('gpkg' if self.source_file_radio.isChecked()
                             else 'layers')
        state.source_path = self.source_edit.text().strip()
        state.selected_only = self.selected_only_check.isChecked()
        state.source_layer_ids = [
            self.layer_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.layer_list.count())
            if self.layer_list.item(row).checkState() == Qt.CheckState.Checked]
        state.destination_kind = (
            'project' if self.destination_project_radio.isChecked() else 'gpkg')
        state.destination_path = self.destination_edit.text().strip()
        return state

    # -- analysis ------------------------------------------------------

    def _start_analysis(self):
        state = self._collect_state()
        if self._task is not None:
            # Inputs changed while the previous read was still running. Dropping
            # the new one leaves the stale answer on screen and, worse, leaves
            # the value/UUID readers bound to the OLD file while the worker
            # reads the new one — so supersede it instead.
            self._restart_pending = True
            self._task.cancel()
            return

        try:
            self._capture_main_thread_inputs(state)
        except Exception as error:
            self.status_label.setText('Could not read that: {0}'.format(error))
            return

        state.profile = self._chosen_profile(state)
        state.date_filter = self._date_filter_config()

        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.status_label.setText('Reading both ends...')

        def work(progress_cb):
            return self.wizard_ref.build_plan(progress_cb)

        def finished(result):
            self._task = None
            if self._resume_if_superseded():
                return
            self.progress.setVisible(False)
            source_model, target_model, built = result
            state.source_model = source_model
            state.target_model = target_model
            state.plan = built
            self._analysed = True
            self._describe(state)
            self.completeChanged.emit()

        def failed(error, _traceback):
            self._task = None
            if self._resume_if_superseded():
                return
            self.progress.setVisible(False)
            state.analysis_error = str(error)
            self.status_label.setText('Could not read that: {0}'.format(error))
            self.completeChanged.emit()

        def cancelled():
            self._task = None
            if self._resume_if_superseded():
                return
            self.progress.setVisible(False)
            self.status_label.setText('Cancelled.')

        self._task = run_in_task(
            'Reading mapping data', work, on_finished=finished,
            on_error=failed, on_cancelled=cancelled, owner=self,
            bar=self.progress, label=self.status_label)

    def _resume_if_superseded(self):
        """True when this result is stale and a fresh read has been started."""
        if not self._restart_pending:
            return False
        self._restart_pending = False
        self._start_analysis()
        return True

    def _capture_main_thread_inputs(self, state):
        """Snapshot everything the worker may not touch.

        The paths are pinned here too. The worker used to re-read them from the
        wizard state, which meant a path changed mid-read gave a model from one
        file and value readers bound to another.
        """
        project = QgsProject.instance()
        state.source_refs = {}
        state.layer_snapshots = {}
        state.analysis_source_path = state.source_path
        state.analysis_destination_path = state.destination_path

        if state.destination_kind == 'project':
            # Work out which GeoPackage the project's mapping layers live in
            # before reading anything. The old path — first gpkg wins — sent
            # the whole import into whichever unrelated file happened to sort
            # ahead of the mapping one. The import's own source file never
            # qualifies as its destination.
            exclude = [state.source_path] if state.source_kind == 'gpkg' else []
            resolved, problem = domain.resolve_project_destination(
                project, exclude)
            if problem:
                raise IOError(problem)
            # Overwrites the pin above: in project mode the destination edit
            # box is disabled and may hold stale text from an earlier choice.
            state.analysis_destination_path = resolved

            def _same(path):
                return path and (os.path.normcase(os.path.abspath(path))
                                 == os.path.normcase(os.path.abspath(resolved)))

            state.target_model = domain.read_project_model(project, layers=[
                layer for layer in project.mapLayers().values()
                if layer.type() == Qgis.LayerType.Vector
                and _same(domain.gpkg_path_of(layer))])
            if not state.target_model.layers:
                raise IOError('the open project has no mapping layers')
        else:
            state.target_model = None

        if state.source_kind == 'gpkg':
            path = state.source_path
            date_filter = self._date_filter_config()

            def counts(table, fields, _p=path, _f=date_filter):
                # The scan honours the same date filter the write will, so a
                # filtered append does not ask about codes it is going to
                # leave behind.
                names = scan.gpkg_column_names(_p, table)
                where = scan.date_filter_expression(_f, names)
                return scan.gpkg_value_counts(_p, table, fields, where=where)

            def source_uuids(table, _p=path, _f=date_filter):
                names = scan.gpkg_column_names(_p, table)
                column = next((n for n in names if n.lower() == 'uuid'), '')
                if not column:
                    return None, 0
                where = scan.date_filter_expression(_f, names)
                counted = scan.gpkg_value_counts(_p, table, [column],
                                                 where=where).get(column)
                if counted is None:
                    return None, 0
                return set(counted.counts), counted.empty

            state.counts_provider = counts
            state.source_uuids_provider = source_uuids
            state.source_model = None
            return

        # Layers open in QGIS: build the model and capture a feature source
        # per layer here, on the main thread.
        layers = [project.mapLayer(layer_id)
                  for layer_id in state.source_layer_ids]
        layers = [layer for layer in layers if layer is not None]
        state.source_model = domain.read_project_model(project, layers)

        sources = {}
        for layer in layers:
            table = domain.layer_table_name(layer)
            if table not in state.source_model.layers:
                table = layer.name()
            fids = (list(layer.selectedFeatureIds())
                    if state.selected_only else None)
            sources[table] = (QgsVectorLayerFeatureSource(layer),
                              [field.name() for field in layer.fields()], fids)
            state.source_refs[table] = plan_module.SourceRef(
                kind='layer', layer_id=layer.id(), table=table,
                selected_only=state.selected_only, label=layer.name())
        state.layer_snapshots = sources

        def counts(table, fields, _sources=sources):
            entry = _sources.get(table)
            if entry is None:
                return {}
            feature_source, names, fids = entry
            return scan.feature_source_value_counts(feature_source, names,
                                                    fields, fids)

        state.counts_provider = counts

        def source_uuids(table, _sources=sources):
            entry = _sources.get(table)
            if entry is None:
                return None, 0
            feature_source, names, fids = entry
            column = next((n for n in names if n.lower() == 'uuid'), '')
            if not column:
                return None, 0
            counted = scan.feature_source_value_counts(
                feature_source, names, [column], fids).get(column)
            if counted is None:
                return None, 0
            return set(counted.counts), counted.empty

        state.source_uuids_provider = source_uuids

    def _date_filter_config(self):
        try:
            return self.date_filter.get_filter_config()
        except Exception:
            return None

    def _chosen_profile(self, state):
        data = self.profile_combo.currentData(Qt.ItemDataRole.UserRole + 1)
        if isinstance(data, dict):
            return data
        return None

    def _describe(self, state):
        source_model = state.source_model
        target_model = state.target_model
        built = state.plan
        matched = sum(1 for item in built.included() if item.target_layer)
        summary = built.summary()

        lines = [
            'Source: {0} — {1}'.format(source_model.label or state.source_label(),
                                       source_model.template_summary()),
            'Destination: {0} — {1}'.format(state.destination_label(),
                                            target_model.template_summary()),
            '{0} of {1} layer(s) matched, {2} feature(s) to bring in.'.format(
                matched, len(built.layer_imports), summary['features']),
        ]
        source_crs = source_model.primary_crs()
        target_crs = target_model.primary_crs()
        if source_crs and target_crs and source_crs != target_crs:
            lines.append('Coordinates will be reprojected from {0} to {1}.'
                         .format(source_crs, target_crs))
        if summary['codes_total']:
            lines.append('{0} of {1} code value(s) matched automatically.'
                         .format(summary['codes_auto'], summary['codes_total']))

        saved = profile_module.load_for(source_model, target_model)
        if saved and state.profile is None:
            lines.append('Saved settings exist for this pair — pick them above '
                         'to reuse your last decisions.')
            if self.profile_combo.count() == 1:
                self.profile_combo.addItem(profile_module.describe(saved),
                                           'stored')
                self.profile_combo.setItemData(1, saved,
                                               Qt.ItemDataRole.UserRole + 1)

        self.status_label.setText('\n'.join(lines))
        profile_module.remember_paths(
            state.source_path if state.source_kind == 'gpkg' else '',
            state.destination_path if state.destination_kind == 'gpkg' else '')
