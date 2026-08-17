"""
Step 4 — what each old code becomes.

This is the step the old tool could not do at all. Its value recoding read the
list of allowed values out of the destination's FEATURE table, so on a fresh
template — the exact case this whole tool exists for — the list was empty and
every code had to be typed by hand, one field at a time, behind two dialogs.

Here the allowed values come from the destination's own lookup tables, every
coded field is in one list, and the great majority of rows arrive already
decided: matched outright, matched through a rename, matched by name, or split
into a code plus a Weight. What is left is genuinely a judgement call, and each
one offers the same three answers — use an existing code, add this one to the
project's code table, or leave it blank.

Fuzzy suggestions are shown but never pre-applied. On the real Abra Linework
data the closest match to 'Fault - Minor' is 'Fault - Normal'; applying that
silently would put a normal fault on the map where a minor one belongs.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSplitter, QVBoxLayout, QWidget, QWizardPage,
)

try:
    from .. import match_values
    from . import style
except ImportError:  # direct (non-package) execution inside QGIS
    from data_import import match_values
    from data_import.wizard import style


BLANK_OPTION = '— leave blank —'
COMMENTS_OPTION = '— leave blank, keep original in Comments —'
ADD_OPTION = '— add "{0}" to {1} —'

_TONE = {
    match_values.EXACT: 'good',
    match_values.RENAMED: 'good',
    match_values.DESCRIPTION: 'good',
    match_values.SPELLING: 'good',
    match_values.SPLIT: 'good',
    match_values.MEANING_CHANGED: 'warn',
    match_values.SUGGESTED: 'warn',
    match_values.UNRESOLVED: 'stop',
    match_values.MANUAL: 'info',
    match_values.ADD_CODE: 'info',
    match_values.BLANK: 'muted',
}


class CodesPage(QWizardPage):

    def __init__(self, wizard):
        super().__init__(wizard)
        self.wizard_ref = wizard
        self._building = False
        self._entries = []          # [(layer_import, target_field)]
        self._current = None

        self.setTitle('What do the old codes become?')
        self.setSubTitle('Most are worked out already. Anything marked in red '
                         'needs your call before the import can run.')

        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.field_list = QListWidget()
        self.field_list.currentRowChanged.connect(self._on_field_selected)
        splitter.addWidget(self.field_list)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        controls = QHBoxLayout()
        self.filter_combo = QComboBox()
        self.filter_combo.addItem('Show everything', 'all')
        self.filter_combo.addItem('Only what needs me', 'attention')
        self.filter_combo.currentIndexChanged.connect(self._refresh_table)
        controls.addWidget(self.filter_combo)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('Search values...')
        self.search_edit.textChanged.connect(self._refresh_table)
        controls.addWidget(self.search_edit, 1)
        self.add_all_button = QPushButton('Add all remaining as new codes')
        self.add_all_button.clicked.connect(self._add_all_remaining)
        controls.addWidget(self.add_all_button)
        self.blank_all_button = QPushButton('Leave all remaining blank')
        self.blank_all_button.clicked.connect(self._blank_all_remaining)
        controls.addWidget(self.blank_all_button)
        right_layout.addLayout(controls)

        self.table = style.make_table(
            ['Old value', 'Features', 'What happened', 'Becomes', 'Notes'],
            stretch_columns=(0, 3, 4))
        right_layout.addWidget(self.table, 1)

        self.field_hint = style.hint('')
        right_layout.addWidget(self.field_hint)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([style.scaled(260, 0)[0], style.scaled(760, 0)[0]])
        layout.addWidget(splitter, 1)

        self.summary_label = style.hint('')
        layout.addWidget(self.summary_label)

    # -- page lifecycle ------------------------------------------------

    def initializePage(self):
        plan = self.wizard_ref.state.plan
        if plan is None:
            return
        self._building = True
        self._entries = []
        self.field_list.clear()
        for item in plan.included():
            for target_field, resolutions in item.resolutions.items():
                if not resolutions:
                    continue
                self._entries.append((item, target_field))
                self.field_list.addItem(QListWidgetItem(''))
        self._refresh_field_list()
        self._building = False
        if self._entries:
            self.field_list.setCurrentRow(self._first_needing_attention())
        else:
            self.field_hint.setText(
                'No coded columns are being imported, so there is nothing to '
                'decide here.')
        self._refresh_summary()

    def _first_needing_attention(self):
        for index, (item, target_field) in enumerate(self._entries):
            if any(resolution.needs_attention
                   for resolution in item.resolutions[target_field].values()):
                return index
        return 0

    def _refresh_field_list(self):
        for index, (item, target_field) in enumerate(self._entries):
            resolutions = item.resolutions[target_field]
            undecided = sum(1 for r in resolutions.values() if not r.decided)
            attention = sum(1 for r in resolutions.values()
                            if r.needs_attention)
            label = '{0}  ·  {1}'.format(item.target_layer, target_field)
            if undecided:
                label += '   ({0} to decide)'.format(undecided)
            elif attention:
                label += '   ({0} to check)'.format(attention)
            list_item = self.field_list.item(index)
            list_item.setText(label)
            if undecided:
                list_item.setForeground(Qt.GlobalColor.darkRed)
            else:
                list_item.setForeground(Qt.GlobalColor.black)

    # -- table ---------------------------------------------------------

    def _on_field_selected(self, row):
        if row < 0 or row >= len(self._entries):
            self._current = None
            return
        self._current = self._entries[row]
        self._refresh_table()

    def _visible_resolutions(self):
        if self._current is None:
            return []
        item, target_field = self._current
        resolutions = list(item.resolutions[target_field].values())
        if self.filter_combo.currentData() == 'attention':
            resolutions = [r for r in resolutions if r.needs_attention]
        needle = self.search_edit.text().strip().lower()
        if needle:
            resolutions = [r for r in resolutions
                           if needle in r.value.lower()
                           or needle in (r.code or '').lower()]
        return resolutions

    def _refresh_table(self, *_args):
        if self._current is None:
            self.table.setRowCount(0)
            return
        item, target_field = self._current
        target_spec = self.wizard_ref.state.target_model.layers.get(
            item.target_layer)
        domain_ = target_spec.domain(target_field) if target_spec else None
        if domain_ is None:
            self.table.setRowCount(0)
            return

        self._building = True
        resolutions = self._visible_resolutions()
        self.table.setRowCount(len(resolutions))
        for row, resolution in enumerate(resolutions):
            self.table.setItem(row, 0, style.read_only_item(resolution.value))
            self.table.setItem(row, 1, style.read_only_item(
                '{0:,}'.format(resolution.count)))
            self.table.setItem(row, 2, style.badge_item(
                resolution.label, _TONE.get(resolution.status, 'muted'),
                resolution.note))
            self.table.setCellWidget(row, 3,
                                     self._decision_combo(resolution, domain_))
            self.table.setItem(row, 4, style.read_only_item(
                self._note_for(resolution, domain_), muted=True))
        self._building = False

        total = len(item.resolutions[target_field])
        hidden = total - len(resolutions)
        table_name = domain_.table or 'the template'
        self.field_hint.setText(
            '{0} distinct value(s) in {1}; allowed codes come from {2}.{3}'
            .format(total, target_field, table_name,
                    '  {0} hidden by the filter.'.format(hidden) if hidden
                    else ''))
        self.add_all_button.setEnabled(bool(domain_.table))

    def _decision_combo(self, resolution, domain_):
        combo = QComboBox()
        combo.addItem(BLANK_OPTION, ('blank', ''))
        combo.addItem(COMMENTS_OPTION, ('comments', ''))
        if domain_.table:
            combo.addItem(ADD_OPTION.format(resolution.value, domain_.table),
                          ('add', resolution.value))
        combo.insertSeparator(combo.count())

        # Suggestions first, so the likely answers are one click away, then
        # the whole code list grouped by its parent.
        for code, description, score in resolution.suggestions:
            combo.addItem('{0} — {1}  ({2}% alike)'.format(
                code, description or code, score), ('code', code))
        if resolution.suggestions:
            combo.insertSeparator(combo.count())

        for parent, entries in domain_.entries_by_parent().items():
            if parent:
                combo.addItem('— {0} —'.format(parent), ('header', ''))
                index = combo.count() - 1
                combo.model().item(index).setEnabled(False)
            for code, description in entries:
                label = code if not description or description == code \
                    else '{0} — {1}'.format(code, description)
                combo.addItem(label, ('code', code))

        combo.setCurrentIndex(self._index_for(combo, resolution))
        combo.setEditable(True)
        combo.lineEdit().setReadOnly(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.currentIndexChanged.connect(
            lambda _i, c=combo, r=resolution, d=domain_:
            self._on_decision(c, r, d))
        return combo

    @staticmethod
    def _index_for(combo, resolution):
        if resolution.status == match_values.BLANK:
            return 1 if resolution.to_comments else 0
        if resolution.status == match_values.ADD_CODE:
            return max(combo.findData(('add', resolution.value)), 0)
        if resolution.code:
            index = combo.findData(('code', resolution.code))
            if index >= 0:
                return index
        return -1 if not resolution.code else 0

    def _note_for(self, resolution, domain_):
        if resolution.status == match_values.ADD_CODE:
            return 'new code in {0}{1}'.format(
                domain_.table,
                ', under ' + resolution.new_code_parent
                if resolution.new_code_parent else '')
        if resolution.extras:
            return ', '.join('{0} = {1}'.format(field, value)
                             for field, value in resolution.extras.items())
        if resolution.code:
            description = domain_.description_of(resolution.code)
            if description and description != resolution.code:
                return description
        return resolution.note

    # -- interaction ---------------------------------------------------

    def _on_decision(self, combo, resolution, domain_):
        if self._building:
            return
        data = combo.currentData()
        if not isinstance(data, tuple):
            return
        kind, payload = data
        if kind == 'blank':
            resolution.leave_blank(to_comments=False)
        elif kind == 'comments':
            resolution.leave_blank(to_comments=True)
        elif kind == 'add':
            resolution.add_as_new_code(
                parent=self._parent_for_new_code(resolution, domain_),
                description=resolution.new_code_description or resolution.value)
        elif kind == 'code':
            extras = dict(resolution.extras)
            resolution.choose(payload, extras)
        else:
            return
        self._after_change()

    def _parent_for_new_code(self, resolution, domain_):
        """Which group a hand-added code joins.

        The static-filter case decides itself: FieldNotebook's Alteration only
        ever shows OverlayCodes rows of type Alteration or Weathering, so a new
        one belongs to the first of those. Otherwise the commonest parent among
        the codes already resolved on this field is the best available guess,
        and the user can see and change it on the review step.
        """
        if resolution.new_code_parent:
            return resolution.new_code_parent
        if domain_.allowed_parents:
            return domain_.allowed_parents[0]
        if self._current is None:
            return ''
        item, target_field = self._current
        tally = {}
        for other in item.resolutions[target_field].values():
            if other is resolution or not other.code:
                continue
            parent = domain_.parent_of(other.code)
            if parent:
                tally[parent] = tally.get(parent, 0) + other.count
        if not tally:
            return ''
        return max(tally.items(), key=lambda pair: pair[1])[0]

    def _add_all_remaining(self):
        if self._current is None:
            return
        item, target_field = self._current
        target_spec = self.wizard_ref.state.target_model.layers.get(
            item.target_layer)
        domain_ = target_spec.domain(target_field)
        if domain_ is None or not domain_.table:
            return
        for resolution in item.resolutions[target_field].values():
            if not resolution.decided:
                resolution.add_as_new_code(
                    parent=self._parent_for_new_code(resolution, domain_),
                    description=(resolution.new_code_description
                                 or resolution.value))
        self._after_change(rebuild_table=True)

    def _blank_all_remaining(self):
        if self._current is None:
            return
        item, target_field = self._current
        for resolution in item.resolutions[target_field].values():
            if not resolution.decided:
                resolution.leave_blank(to_comments=True)
        self._after_change(rebuild_table=True)

    def _after_change(self, rebuild_table=False):
        self._refresh_field_list()
        self._refresh_summary()
        if rebuild_table:
            self._refresh_table()
        else:
            self._refresh_badges()
        self.completeChanged.emit()

    def _refresh_badges(self):
        resolutions = self._visible_resolutions()
        for row, resolution in enumerate(resolutions):
            if row >= self.table.rowCount():
                break
            self.table.setItem(row, 2, style.badge_item(
                resolution.label, _TONE.get(resolution.status, 'muted'),
                resolution.note))

    def _refresh_summary(self):
        plan = self.wizard_ref.state.plan
        if plan is None:
            return
        undecided = plan.undecided_count()
        totals = plan.status_totals()
        auto = sum(count for status, count in totals.items()
                   if status in match_values.AUTO_STATUSES)
        text = '{0} of {1} value(s) worked out automatically.'.format(
            auto, sum(totals.values()))
        new_codes = len(plan.new_codes())
        if new_codes:
            text += '  {0} new code(s) will be added.'.format(new_codes)
        if undecided:
            text += '  {0} still to decide.'.format(undecided)
        self.summary_label.setText(text)

    def isComplete(self):
        plan = self.wizard_ref.state.plan
        return plan is not None and plan.undecided_count() == 0
