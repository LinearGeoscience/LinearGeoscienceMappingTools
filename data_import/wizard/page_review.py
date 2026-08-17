"""
Step 5 — read this before it happens.

Blocking problems are kept visually apart from things merely worth knowing,
because conflating the two is how a warning list stops being read. Everything
here is generated from the same ImportPlan the writer will consume, so the page
cannot drift from what actually happens — which the old tool's preview did: its
OK button did nothing, and the preview resolved the UUID field by a different
route than the run did, so the two could disagree.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWizardPage,
)

try:
    from .. import profile as profile_module
    from . import style
except ImportError:  # direct (non-package) execution inside QGIS
    from data_import import profile as profile_module
    from data_import.wizard import style


class ReviewPage(QWizardPage):

    def __init__(self, wizard):
        super().__init__(wizard)
        self.wizard_ref = wizard

        self.setTitle('Ready to import')
        self.setSubTitle('A copy of the destination is taken first, so this '
                         'can be undone by restoring it.')
        self.setCommitPage(True)

        layout = QVBoxLayout(self)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.summary_label)

        self.findings_label = QLabel()
        self.findings_label.setWordWrap(True)
        self.findings_label.setTextFormat(Qt.TextFormat.RichText)
        self.findings_label.setOpenExternalLinks(False)
        layout.addWidget(self.findings_label, 1)

        options = QGroupBox('Options')
        options_layout = QVBoxLayout(options)
        self.backup_check = QCheckBox(
            'Take a copy of the destination first')
        self.backup_check.setChecked(True)
        self.duplicates_check = QCheckBox(
            'Skip features already there (matched on UUID)')
        self.duplicates_check.setChecked(True)
        self.uuid_check = QCheckBox(
            'Give features without a UUID a new one')
        self.uuid_check.setChecked(True)
        for widget in (self.backup_check, self.duplicates_check,
                       self.uuid_check):
            options_layout.addWidget(widget)
            widget.toggled.connect(self._apply_options)
        layout.addWidget(options)

        buttons = QHBoxLayout()
        save_profile = QPushButton('Save these settings for next time')
        save_profile.clicked.connect(self._save_profile)
        buttons.addWidget(save_profile)
        export_profile = QPushButton('Export settings to a file...')
        export_profile.clicked.connect(self._export_profile)
        buttons.addWidget(export_profile)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.saved_label = style.hint('')
        layout.addWidget(self.saved_label)

    # -- lifecycle -----------------------------------------------------

    def initializePage(self):
        plan = self.wizard_ref.state.plan
        if plan is None:
            return
        self._apply_options()
        self.summary_label.setText(self._summary_html(plan))
        self.findings_label.setText(self._findings_html(plan.validate()))
        self.saved_label.setText('')

    def _apply_options(self, *_args):
        plan = self.wizard_ref.state.plan
        if plan is None:
            return
        plan.options.backup = self.backup_check.isChecked()
        plan.options.skip_duplicate_uuids = self.duplicates_check.isChecked()
        plan.options.generate_missing_uuids = self.uuid_check.isChecked()

    def isComplete(self):
        plan = self.wizard_ref.state.plan
        return plan is not None and plan.validate().ok

    # -- rendering -----------------------------------------------------

    def _summary_html(self, plan):
        summary = plan.summary()
        already = summary['already_present']
        headline = ('<b>{0} new feature(s)</b> into <b>{1}</b>, across '
                    '{2} layer(s)').format(
            '{0:,}'.format(summary['expected_new']), summary['destination'],
            summary['layers'])
        if already:
            headline += (' — {0:,} of the {1:,} in the source '
                         'are already there'.format(already,
                                                    summary['features']))
        lines = [headline + ':', '<ul>']
        for item in plan.included():
            if item.already_present:
                detail = '{0:,} new, {1:,} already there'.format(
                    item.expected_new, item.already_present)
            else:
                detail = '{0:,} features'.format(item.feature_count)
            lines.append('<li>{0} → <b>{1}</b> ({2})</li>'.format(
                item.source.label, item.target_layer, detail))
        lines.append('</ul>')
        if summary['codes_total']:
            lines.append(
                '{0} of {1} code value(s) were worked out automatically.'
                .format(summary['codes_auto'], summary['codes_total']))
        if summary['new_codes']:
            lines.append(
                '<br><b>{0} new code(s)</b> will be added to this project\'s '
                'code tables. Run <i>Recode &amp; Restyle</i> afterwards to '
                'give them symbols.'.format(summary['new_codes']))
        return '\n'.join(lines)

    def _findings_html(self, report):
        blocks = []
        if report.errors:
            blocks.append(self._block('Must be fixed first', report.errors,
                                      style.STOP_FG))
        if report.warnings:
            blocks.append(self._block('Worth knowing', report.warnings,
                                      style.WARN_FG))
        if report.notes:
            blocks.append(self._block('What was changed for you', report.notes,
                                      style.INFO_FG))
        if not blocks:
            return '<span style="color:{0}">Nothing to flag.</span>'.format(
                style.GOOD_FG)
        return '<br>'.join(blocks)

    @staticmethod
    def _block(title, findings, colour):
        rows = []
        for finding in findings:
            prefix = '<b>{0}:</b> '.format(finding.layer) if finding.layer else ''
            detail = ('<br><span style="color:{0}">{1}</span>'.format(
                style.MUTED_FG, finding.detail) if finding.detail else '')
            rows.append('<li>{0}{1}{2}</li>'.format(prefix, finding.title,
                                                    detail))
        return '<b style="color:{0}">{1}</b><ul>{2}</ul>'.format(
            colour, title, ''.join(rows))

    # -- profiles ------------------------------------------------------

    def _save_profile(self):
        plan = self.wizard_ref.state.plan
        if plan is None:
            return
        captured = profile_module.capture(
            plan, name='{0} → {1}'.format(plan.source_model.label,
                                          plan.destination.label))
        profile_module.save(captured)
        self.saved_label.setText(
            'Saved. Next time you import data shaped like this, these '
            'decisions are offered on the first step.')

    def _export_profile(self):
        plan = self.wizard_ref.state.plan
        if plan is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export import settings', 'import-settings.json',
            'Import settings (*.json)')
        if not path:
            return
        captured = profile_module.capture(
            plan, name='{0} → {1}'.format(plan.source_model.label,
                                          plan.destination.label))
        profile_module.export_to_file(captured, path)
        self.saved_label.setText('Exported to {0}'.format(path))
