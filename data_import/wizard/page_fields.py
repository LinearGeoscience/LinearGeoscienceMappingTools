"""
Step 3 — which column feeds which column.

One tab per layer, one table per tab. The old tool put this behind a Configure
button that opened a modal per layer, inside which field mapping was one tab
and value recoding another, and the checkboxes that actually decided what got
imported lived in a different window again. Everything for a layer is on screen
here at once.

The table below the mapping is the half nobody used to be told about: the
destination columns nothing feeds, and what will fill them. "Confidence — the
template default 'Observed'" and "Category — worked out from Type" are the
difference between a geologist trusting the result and opening the attribute
table to check.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox, QTabWidget, QVBoxLayout, QWidget, QWizardPage,
)

try:
    from .. import match_fields
    from . import style
except ImportError:  # direct (non-package) execution inside QGIS
    from data_import import match_fields
    from data_import.wizard import style


NOT_IMPORTED = '— not imported —'
TO_COMMENTS = '— keep in Comments —'

_TONE = {
    match_fields.EXACT: ('Matched', 'good'),
    match_fields.ALIAS: ('Renamed', 'good'),
    match_fields.SUGGESTED: ('Check this', 'warn'),
    match_fields.UNMATCHED: ('Not imported', 'muted'),
    match_fields.IGNORED: ('Internal', 'muted'),
}

_HOW_LABELS = {
    'default': 'Filled by',
    'derived': 'Worked out',
    'later': 'Later',
    'empty': 'Left empty',
}


class FieldsPage(QWizardPage):

    def __init__(self, wizard):
        super().__init__(wizard)
        self.wizard_ref = wizard
        self._building = False
        self._tabs_for = []

        self.setTitle('Which columns go where?')
        self.setSubTitle('Columns with the same meaning are already paired. '
                         'Anything needing a look is marked.')

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.summary_label = style.hint('')
        layout.addWidget(self.summary_label)

    def initializePage(self):
        plan = self.wizard_ref.state.plan
        if plan is None:
            return
        self._building = True
        self.tabs.clear()
        self._tabs_for = []
        for item in plan.included():
            if item.field_plan is None:
                continue
            self.tabs.addTab(self._build_tab(item),
                             '{0} → {1}'.format(item.source.label,
                                                item.target_layer))
            self._tabs_for.append(item)
        self._building = False
        self._refresh_summary()

    # -- one layer -----------------------------------------------------

    def _build_tab(self, item):
        target_spec = self.wizard_ref.state.target_model.layers.get(
            item.target_layer)
        page = QWidget()
        layout = QVBoxLayout(page)

        table = style.make_table(
            ['From', 'Type', '', 'Into', 'Status'], stretch_columns=(0, 3, 4))
        matches = [match for match in item.field_plan.matches.values()
                   if match.status != match_fields.IGNORED]
        table.setRowCount(len(matches))

        free_targets = self._free_targets(item, target_spec)

        for row, match in enumerate(matches):
            source_field = (self.wizard_ref.state.source_model
                            .layers[item.source.table].field(match.source_name))
            table.setItem(row, 0, style.read_only_item(match.source_name))
            table.setItem(row, 1, style.read_only_item(
                source_field.declared_type if source_field else '', muted=True))
            arrow = style.read_only_item('→', muted=True)
            arrow.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 2, arrow)

            combo = QComboBox()
            combo.addItem(NOT_IMPORTED, '')
            if self._has_comments(target_spec):
                combo.addItem(TO_COMMENTS, '__comments__')
            options = sorted(set(free_targets)
                             | ({match.target_name} if match.target_name
                                else set()))
            for name in options:
                combo.addItem(name, name)
            if match.is_mapped:
                combo.setCurrentIndex(max(combo.findData(match.target_name), 0))
            elif match.unmatched_action == match_fields.TO_COMMENTS:
                combo.setCurrentIndex(max(combo.findData('__comments__'), 0))
            else:
                combo.setCurrentIndex(0)
            combo.currentIndexChanged.connect(
                lambda _index, i=item, m=match, t=table, r=row:
                self._on_target_changed(i, m, t, r))
            table.setCellWidget(row, 3, combo)
            table.setItem(row, 4, self._status_cell(match))

        layout.addWidget(table, 2)

        notes = [note for note in item.field_plan.target_notes.values()]
        if notes:
            layout.addWidget(style.heading(
                'Destination columns nothing feeds ({0})'.format(len(notes))))
            note_table = style.make_table(['Column', 'What happens', 'Detail'],
                                          stretch_columns=(1, 2))
            note_table.setRowCount(len(notes))
            for row, note in enumerate(notes):
                label = note.name + (' *' if note.required else '')
                note_table.setItem(row, 0, style.read_only_item(
                    label, tooltip='required by the form' if note.required
                    else ''))
                tone = {'default': 'good', 'derived': 'good',
                        'later': 'info'}.get(note.how, 'muted')
                if note.how == 'empty' and note.required:
                    tone = 'warn'
                note_table.setItem(row, 1, style.badge_item(
                    _HOW_LABELS.get(note.how, note.how), tone))
                note_table.setItem(row, 2,
                                   style.read_only_item(note.detail, muted=True))
            layout.addWidget(note_table, 1)
            layout.addWidget(style.hint(
                '* required by the form. Features still import; the form '
                'flags them until the value is filled in.'))

        return page

    def _free_targets(self, item, target_spec):
        if target_spec is None:
            return []
        taken = set(item.field_plan.mapping().values())
        return [name for name in target_spec.fields
                if name not in taken and name.lower() != 'fid']

    @staticmethod
    def _has_comments(target_spec):
        if target_spec is None:
            return False
        return any(name.lower() in ('comments', 'comment')
                   for name in target_spec.fields)

    @staticmethod
    def _status_cell(match):
        label, tone = _TONE.get(match.status, ('', 'muted'))
        if match.is_mapped and not match.type_ok:
            return style.badge_item('Type clash', 'stop', match.type_note)
        if match.type_note:
            return style.badge_item(label, 'warn' if tone == 'good' else tone,
                                    match.type_note)
        return style.badge_item(label, tone, match.reason)

    # -- interaction ---------------------------------------------------

    def _on_target_changed(self, item, match, table, row):
        if self._building:
            return
        combo = table.cellWidget(row, 3)
        chosen = combo.currentData() or ''
        if chosen == '__comments__':
            match.target_name = None
            match.status = match_fields.UNMATCHED
            match.unmatched_action = match_fields.TO_COMMENTS
            match.reason = 'kept in Comments'
        elif not chosen:
            match.target_name = None
            match.status = match_fields.UNMATCHED
            match.unmatched_action = match_fields.DROP
            match.reason = 'not imported'
        else:
            match.target_name = chosen
            match.status = match_fields.ALIAS
            match.unmatched_action = match_fields.DROP
            match.reason = 'chosen by hand'
            source_spec = (self.wizard_ref.state.source_model
                           .layers[item.source.table])
            target_spec = self.wizard_ref.state.target_model.layers.get(
                item.target_layer)
            ok, note = match_fields.types_compatible(
                source_spec.field(match.source_name),
                target_spec.field(chosen) if target_spec else None)
            match.type_ok, match.type_note = ok, note
        table.setItem(row, 4, self._status_cell(match))
        self.wizard_ref.state.plan and self._refresh_summary()

    def _refresh_summary(self):
        plan = self.wizard_ref.state.plan
        if plan is None:
            return
        mapped = review = dropped = 0
        for item in plan.included():
            if item.field_plan is None:
                continue
            for match in item.field_plan.matches.values():
                if match.status == match_fields.IGNORED:
                    continue
                if match.is_mapped:
                    mapped += 1
                    if match.needs_review:
                        review += 1
                else:
                    dropped += 1
        text = '{0} column(s) will be imported, {1} will not.'.format(
            mapped, dropped)
        if review:
            text += '  {0} worth a check.'.format(review)
        self.summary_label.setText(text)

    def validatePage(self):
        """Code decisions depend on the column pairing, so redo them here."""
        plan = self.wizard_ref.state.plan
        if plan is None:
            return False
        for item in plan.included():
            self.wizard_ref.refresh_resolutions(item)
        return True
