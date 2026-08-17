"""
Step 6 — the import itself.

Starts on entry, runs on the task pool, and reports what actually happened per
layer including the things that are easy to leave out: features skipped as
duplicates, multi-part shapes split, parent values worked out, and required
columns that came out empty anyway. The old tool logged its skip reasons
through a debug_log() that was disabled by a module constant, so a run that
dropped 800 features reported one aggregate number and no reason.
"""

import os

from qgis.PyQt.QtWidgets import (
    QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextEdit, QVBoxLayout,
    QWizardPage,
)

try:
    from ...lgs_tasks import run_in_task
    from .. import execute
except ImportError:  # direct (non-package) execution inside QGIS
    from lgs_tasks import run_in_task
    from data_import import execute


class RunPage(QWizardPage):

    def __init__(self, wizard):
        super().__init__(wizard)
        self.wizard_ref = wizard
        self._task = None
        self._finished = False
        self._result = None

        self.setTitle('Importing')
        self.setSubTitle('')

        layout = QVBoxLayout(self)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        self.status_label = QLabel('Starting...')
        layout.addWidget(self.status_label)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)

        buttons = QHBoxLayout()
        self.cancel_button = QPushButton('Stop')
        self.cancel_button.clicked.connect(self._cancel)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        self.open_backup_button = QPushButton('Show the backup copy')
        self.open_backup_button.setVisible(False)
        self.open_backup_button.clicked.connect(self._show_backup)
        buttons.addWidget(self.open_backup_button)
        layout.addLayout(buttons)

    # -- lifecycle -----------------------------------------------------

    def initializePage(self):
        self._finished = False
        self._result = None
        self.log.clear()
        self.progress.setValue(0)
        self.cancel_button.setEnabled(True)
        self.open_backup_button.setVisible(False)
        self.completeChanged.emit()
        self._start()

    def isComplete(self):
        return self._finished

    def cleanupPage(self):
        # Back is not offered from here, but QWizard calls this on restart.
        self._cancel()

    # -- the run -------------------------------------------------------

    def _start(self):
        state = self.wizard_ref.state
        plan = state.plan
        if plan is None:
            self._say('Nothing to import.')
            self._finish(None)
            return

        try:
            snapshots = execute.prepare_sources(plan)
        except Exception as error:
            self._say('Could not read the source: {0}'.format(error))
            self._finish(None)
            return

        transform_context = None
        try:
            from qgis.core import QgsProject
            transform_context = QgsProject.instance().transformContext()
        except Exception:
            pass

        def work(progress_cb):
            return execute.run_import(plan, snapshots,
                                      progress_cb=progress_cb,
                                      transform_context=transform_context)

        def finished(result):
            self._task = None
            self._result = result
            self.progress.setValue(100)
            self._report(result)
            self._finish(result)

        def failed(error, traceback_text):
            self._task = None
            self._say('The import failed: {0}'.format(error))
            self._say(traceback_text)
            self._say('The destination was copied before anything was '
                      'written; restore that copy if the layer looks wrong.')
            self._finish(None)

        def cancelled():
            self._task = None
            self._say('Stopped. Whatever had already been written is still '
                      'there — restore the backup copy to undo it.')
            self._finish(None)

        self._task = run_in_task(
            'Importing mapping data', work, on_finished=finished,
            on_error=failed, on_cancelled=cancelled, owner=self,
            bar=self.progress, label=self.status_label)

    def _cancel(self):
        if self._task is not None:
            self._task.cancel()
            self.cancel_button.setEnabled(False)

    def _finish(self, result):
        self._finished = True
        self.cancel_button.setEnabled(False)
        self.setSubTitle('Finished.')
        if result is not None and result.backup_path:
            self.open_backup_button.setVisible(True)
        try:
            execute.reload_destination_layers(self.wizard_ref.state.plan)
        except Exception:
            pass
        self.completeChanged.emit()

    # -- reporting -----------------------------------------------------

    def _report(self, result):
        self._say('{0} feature(s) added, {1} skipped.'.format(
            result.total_added, result.total_skipped))
        self._say('')
        for line in result.report_lines():
            self._say(line)

        problems = [line for layer in result.layers for line in layer.errors]
        if problems:
            self._say('')
            self._say('Problems:')
            for line in problems:
                self._say('  ' + line)

        coercion = [(layer.target_layer, dict(layer.coercion_failures))
                    for layer in result.layers if layer.coercion_failures]
        if coercion:
            self._say('')
            self._say('Values that would not convert (left empty):')
            for layer_name, failures in coercion:
                self._say('  {0}: {1}'.format(
                    layer_name,
                    ', '.join('{0} ({1})'.format(field, count)
                              for field, count in failures.items())))

        conflicts = sum(layer.parent_conflicts for layer in result.layers)
        if conflicts:
            self._say('')
            self._say('{0} feature(s) carried a group value that disagreed '
                      'with their code; the code won.'.format(conflicts))

        if result.backup_path:
            self._say('')
            self._say('Backup copy: {0}'.format(result.backup_path))

        self._say('')
        self._say('Next: run Hardcode Data & Update Legends to fill the '
                  'Mapped* columns and the legend text.')
        if result.new_codes:
            self._say('Then run Recode & Restyle so the new codes get symbols.')

    def _say(self, text):
        self.log.append(text)

    def _show_backup(self):
        if self._result is None or not self._result.backup_path:
            return
        folder = os.path.dirname(self._result.backup_path)
        try:
            from qgis.PyQt.QtCore import QUrl
            from qgis.PyQt.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        except Exception:
            pass
