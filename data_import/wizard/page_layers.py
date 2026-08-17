"""
Step 2 — which source layer goes into which destination layer.

Usually nothing to do: geometry, the ordinal-tolerant canonical name and the
overlap between the two column sets between them place all four layers of a
real export without help. The page exists for the times they do not, and to
show its working when they do — "85% of fields in common" is checkable in a way
that a silent assignment is not.

Two things it refuses to hide. A geometry mismatch is a hard stop with the
reason spelled out, not a row that quietly writes nothing. And the source's own
code tables are listed as deliberately excluded, because the old tool ticked
them by default and appended fifteen lookup tables plus a pile of duplicate
style rows into people's projects.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox, QTableWidgetItem, QVBoxLayout, QWizardPage,
)

try:
    from .. import match_layers
    from . import style
except ImportError:  # direct (non-package) execution inside QGIS
    from data_import import match_layers
    from data_import.wizard import style


COLUMN_INCLUDE = 0
COLUMN_SOURCE = 1
COLUMN_FEATURES = 2
COLUMN_GEOMETRY = 3
COLUMN_ARROW = 4
COLUMN_TARGET = 5
COLUMN_WHY = 6


class LayersPage(QWizardPage):

    def __init__(self, wizard):
        super().__init__(wizard)
        self.wizard_ref = wizard
        self._building = False

        self.setTitle('Which layers go where?')
        self.setSubTitle('Matched by shape, name and columns. Change any row '
                         'that looks wrong.')

        layout = QVBoxLayout(self)

        self.table = style.make_table(
            ['Import', 'From', 'Features', 'Shape', '', 'Into', 'Why'],
            stretch_columns=(1, 5, 6))
        layout.addWidget(self.table, 1)

        self.summary_label = style.hint('')
        layout.addWidget(self.summary_label)

        self.excluded_label = style.hint('')
        layout.addWidget(self.excluded_label)

        self.table.itemChanged.connect(self._on_item_changed)

    def initializePage(self):
        plan = self.wizard_ref.state.plan
        if plan is None:
            return
        self._build(plan)

    def _build(self, plan):
        self._building = True
        items = plan.layer_imports
        self.table.setRowCount(len(items))

        for row, item in enumerate(items):
            match = item.layer_match
            blocked = bool(match is not None and match.blocked)

            include = QTableWidgetItem('')
            include.setFlags(Qt.ItemFlag.ItemIsEnabled
                             | (Qt.ItemFlag.ItemIsUserCheckable
                                if not blocked else Qt.ItemFlag.NoItemFlags))
            include.setCheckState(
                Qt.CheckState.Checked if item.include and not blocked
                else Qt.CheckState.Unchecked)
            self.table.setItem(row, COLUMN_INCLUDE, include)

            source_spec = plan.source_model.layers.get(item.source.table)
            self.table.setItem(row, COLUMN_SOURCE,
                               style.read_only_item(item.source.label))
            if item.already_present:
                features_text = '{0:,} new of {1:,}'.format(
                    item.expected_new, item.feature_count)
                features_tip = ('{0:,} are already in the destination, matched '
                                'on UUID'.format(item.already_present))
            else:
                features_text = '{0:,}'.format(item.feature_count)
                features_tip = ''
            self.table.setItem(
                row, COLUMN_FEATURES,
                style.read_only_item(features_text, tooltip=features_tip))
            self.table.setItem(
                row, COLUMN_GEOMETRY,
                style.read_only_item(
                    (source_spec.geometry_type if source_spec else '') or '—',
                    muted=True))
            arrow = style.read_only_item('→', muted=True)
            arrow.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, COLUMN_ARROW, arrow)

            combo = QComboBox()
            combo.addItem('— do not import —', '')
            candidates = [name for name, _s, _r in
                          (match.candidates if match else [])]
            for name in candidates:
                combo.addItem(name, name)
            if item.target_layer and item.target_layer not in candidates:
                combo.addItem(item.target_layer, item.target_layer)
            index = combo.findData(item.target_layer or '')
            combo.setCurrentIndex(max(index, 0))
            combo.setEnabled(not blocked)
            combo.currentIndexChanged.connect(
                lambda _index, r=row: self._on_target_changed(r))
            self.table.setCellWidget(row, COLUMN_TARGET, combo)

            if blocked:
                cell = style.badge_item(match.blocked, 'stop')
            elif match is not None and match.confidence == match_layers.AUTO:
                cell = style.badge_item(match.reason, 'good')
            else:
                cell = style.badge_item(
                    (match.reason if match else 'choose a destination'), 'warn')
            self.table.setItem(row, COLUMN_WHY, cell)

        self._building = False
        self._refresh_summary()

        excluded = match_layers.excluded_tables(plan.source_model)
        if excluded:
            self.excluded_label.setText(
                'Not imported: {0} — {1}.'.format(
                    ', '.join(sorted(excluded)),
                    'the destination has its own code tables and styling'))
        else:
            self.excluded_label.setText('')

    # -- interaction ---------------------------------------------------

    def _on_item_changed(self, item):
        if self._building or item.column() != COLUMN_INCLUDE:
            return
        plan = self.wizard_ref.state.plan
        plan.layer_imports[item.row()].include = (
            item.checkState() == Qt.CheckState.Checked)
        self._refresh_summary()
        self.completeChanged.emit()

    def _on_target_changed(self, row):
        if self._building:
            return
        plan = self.wizard_ref.state.plan
        combo = self.table.cellWidget(row, COLUMN_TARGET)
        item = plan.layer_imports[row]
        target = combo.currentData() or ''
        if target == item.target_layer:
            return
        item.target_layer = target or None
        include_cell = self.table.item(row, COLUMN_INCLUDE)
        if not target:
            item.include = False
            include_cell.setCheckState(Qt.CheckState.Unchecked)
        # A different destination means different columns and different code
        # lists, so everything downstream for this layer is rebuilt.
        self.wizard_ref.rebuild_layer(item)
        self._refresh_summary()
        self.completeChanged.emit()

    def _refresh_summary(self):
        plan = self.wizard_ref.state.plan
        if plan is None:
            return
        included = plan.included()
        features = sum(item.feature_count for item in included)
        already = plan.total_already_present()
        if already:
            text = ('{0} layer(s) selected, {1:,} new feature(s) '
                    '({2:,} of {3:,} are already in the destination).').format(
                len(included), plan.total_expected_new(), already, features)
        else:
            text = '{0} layer(s) selected, {1:,} feature(s).'.format(
                len(included), features)
        needs_review = sum(
            1 for item in included
            if item.layer_match is not None and item.layer_match.needs_review)
        if needs_review:
            text += '  {0} row(s) worth a check.'.format(needs_review)
        self.summary_label.setText(text)

    def isComplete(self):
        plan = self.wizard_ref.state.plan
        if plan is None:
            return False
        included = plan.included()
        if not included:
            return False
        return all(item.target_layer for item in included)
