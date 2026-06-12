"""
Reusable widgets for the Recode & Restyle Workflow wizard.

CollapsibleSection     – expand/collapse panel with status badge
DataPreviewTable       – first-5-row preview with toggle
StepButton             – sidebar nav button with coloured status icon
TableComparisonWidget  – three DataPreviewTable instances side-by-side
LayerCheckList         – themed QListWidget with checkboxes for categorized layers
FieldGroupManager      – create named groups of fields for legend builder
"""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton,
    QLineEdit, QDialog, QDialogButtonBox, QFrame,
    QComboBox, QTableWidget, QTableWidgetItem, QSizePolicy,
    QCheckBox,
)
from qgis.PyQt.QtGui import (
    QCursor, QColor, QIcon, QPixmap, QPainter, QBrush, QPen,
)

try:
    from ..ui_scaling import get_scale_manager
except ImportError:
    from ui_scaling import get_scale_manager

try:
    from .. import plugin_theme as theme
except ImportError:
    import plugin_theme as theme

try:
    from ..layer_select import layer_display_name
except ImportError:
    from layer_select import layer_display_name


# ── Helper ─────────────────────────────────────────────────────────

def _create_status_pixmap(color_hex, check=False, size=16):
    """Create a small coloured circle or checkmark pixmap."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    if check:
        pen_w = max(2, size // 8)
        painter.setPen(QPen(QColor(color_hex), pen_w))
        painter.drawLine(size // 5, size // 2, size * 2 // 5, size * 3 // 4)
        painter.drawLine(size * 2 // 5, size * 3 // 4, size * 4 // 5, size // 4)
    else:
        painter.setBrush(QBrush(QColor(color_hex)))
        painter.setPen(Qt.NoPen)
        m = size // 5
        painter.drawEllipse(m, m, size - 2 * m, size - 2 * m)
    painter.end()
    return pixmap


# ── CollapsibleSection ─────────────────────────────────────────────

class CollapsibleSection(QWidget):
    """Expandable / collapsible section with header bar and status badge."""

    def __init__(self, title, parent=None, expanded=True):
        super().__init__(parent)
        self._title = title
        self._expanded = expanded
        self._s = get_scale_manager()
        self._build()

    # ── construction ──

    def _build(self):
        s = self._s
        main = QVBoxLayout(self)
        main.setContentsMargins(0, s.dimension(4), 0, s.dimension(4))
        main.setSpacing(0)

        # Header
        self._header = QWidget()
        self._header.setCursor(QCursor(Qt.PointingHandCursor))
        h = QHBoxLayout(self._header)
        pad = s.dimension(10)
        h.setContentsMargins(pad, s.dimension(8), pad, s.dimension(8))
        h.setSpacing(s.dimension(8))

        self._arrow = QLabel("▼" if self._expanded else "▶")
        self._arrow.setFixedWidth(s.dimension(16))
        self._arrow.setStyleSheet(
            f"font-size: {s.font_size(10)}px; color: {theme.TEXT_SECONDARY}; "
            "border: none; background: transparent;"
        )
        h.addWidget(self._arrow)

        self._title_label = QLabel(self._title)
        self._title_label.setStyleSheet(
            f"font-weight: bold; font-size: {s.font_size(12)}px; "
            f"font-family: {theme.FONT_FAMILY}; color: {theme.TEXT_PRIMARY}; "
            "border: none; background: transparent;"
        )
        h.addWidget(self._title_label, 1)

        self._badge = QLabel()
        self._badge.setVisible(False)
        h.addWidget(self._badge)

        br = s.dimension(6)
        self._header.setStyleSheet(
            f"background-color: {theme.BG_PRIMARY}; "
            f"border: 1px solid {theme.BORDER}; border-radius: {br}px;"
        )
        main.addWidget(self._header)

        # Content
        self._content_widget = QWidget()
        self._content_lay = QVBoxLayout(self._content_widget)
        cp = s.dimension(12)
        self._content_lay.setContentsMargins(cp, cp, cp, cp)
        self._content_lay.setSpacing(s.dimension(8))

        self._content_widget.setStyleSheet(
            f"background-color: {theme.BG_CARD}; "
            f"border: 1px solid {theme.BORDER}; border-top: none; "
            f"border-bottom-left-radius: {br}px; "
            f"border-bottom-right-radius: {br}px;"
        )
        self._content_widget.setVisible(self._expanded)
        main.addWidget(self._content_widget)

        self._header.mousePressEvent = lambda _e: self.toggle()

    # ── public API ──

    def content_layout(self):
        """Return the QVBoxLayout inside the content area."""
        return self._content_lay

    def set_status(self, status, text=""):
        """Update the badge.  status: 'none'|'loaded'|'required'|'warning'|'error'."""
        if status == "none" or not text:
            self._badge.setVisible(False)
            return
        s = self._s
        colours = {
            "loaded":   (theme.PRIMARY,       "#E8F5E9"),
            "required": (theme.TEXT_SECONDARY, theme.BG_PRIMARY),
            "warning":  ("#FF9800",            "#FFF3E0"),
            "error":    ("#F44336",            "#FFEBEE"),
        }
        tc, bg = colours.get(status, (theme.TEXT_SECONDARY, "transparent"))
        self._badge.setText(text)
        self._badge.setStyleSheet(
            f"color: {tc}; background-color: {bg}; "
            f"padding: {s.dimension(2)}px {s.dimension(8)}px; "
            f"border-radius: {s.dimension(8)}px; "
            f"font-size: {s.font_size(10)}px; font-weight: bold; "
            f"font-family: {theme.FONT_FAMILY}; border: none;"
        )
        self._badge.setVisible(True)

    def toggle(self):
        self._expanded = not self._expanded
        self._content_widget.setVisible(self._expanded)
        self._arrow.setText("▼" if self._expanded else "▶")

    def set_expanded(self, expanded):
        if self._expanded != expanded:
            self.toggle()

    def is_expanded(self):
        return self._expanded


# ── DataPreviewTable ───────────────────────────────────────────────

class DataPreviewTable(QWidget):
    """Collapsible data preview showing first N rows with summary."""

    MAX_ROWS = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._s = get_scale_manager()
        self._shown = False
        self._build()

    def _build(self):
        s = self._s
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(s.dimension(4))

        hdr = QHBoxLayout()
        self._summary = QLabel("No data loaded")
        self._summary.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {s.font_size(11)}px; "
            f"font-family: {theme.FONT_FAMILY};"
        )
        hdr.addWidget(self._summary)
        hdr.addStretch()

        self._toggle_btn = QPushButton("Show Preview")
        self._toggle_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._toggle_btn.setStyleSheet(
            f"color: {theme.PRIMARY}; border: none; background: transparent; "
            f"font-size: {s.font_size(11)}px; font-family: {theme.FONT_FAMILY}; "
            "text-decoration: underline;"
        )
        self._toggle_btn.clicked.connect(self._toggle)
        self._toggle_btn.setVisible(False)
        hdr.addWidget(self._toggle_btn)
        lay.addLayout(hdr)

        self._table = QTableWidget()
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.NoSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setMaximumHeight(s.dimension(150))
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setDefaultSectionSize(s.dimension(24))
        self._table.setStyleSheet(
            f"QTableWidget {{ border: 1px solid {theme.BORDER}; "
            f"  border-radius: {s.dimension(4)}px; "
            f"  font-size: {s.font_size(10)}px; font-family: {theme.FONT_FAMILY}; "
            f"  alternate-background-color: {theme.BG_PRIMARY}; }} "
            f"QHeaderView::section {{ background-color: {theme.BG_PRIMARY}; "
            f"  padding: {s.dimension(4)}px; border: 1px solid {theme.BORDER}; "
            f"  font-weight: bold; font-size: {s.font_size(10)}px; }}"
        )
        self._table.setVisible(False)
        lay.addWidget(self._table)

    # ── public API ──

    def set_data(self, df):
        """Populate with first 5 rows of *df*."""
        if df is None or len(df) == 0:
            self.clear()
            return
        total = len(df)
        preview = df.head(self.MAX_ROWS)
        cols = list(preview.columns)
        self._table.setRowCount(len(preview))
        self._table.setColumnCount(len(cols))
        self._table.setHorizontalHeaderLabels(cols)
        for r, (_, row) in enumerate(preview.iterrows()):
            for c, col in enumerate(cols):
                val = row[col]
                self._table.setItem(r, c, QTableWidgetItem("" if val is None else str(val)))
        self._table.resizeColumnsToContents()
        self._summary.setText(f"{total:,} rows × {len(cols)} columns")
        self._toggle_btn.setVisible(True)

    def clear(self):
        self._table.clear()
        self._table.setRowCount(0)
        self._table.setColumnCount(0)
        self._table.setVisible(False)
        self._summary.setText("No data loaded")
        self._toggle_btn.setVisible(False)
        self._shown = False

    def _toggle(self):
        self._shown = not self._shown
        self._table.setVisible(self._shown)
        self._toggle_btn.setText("Hide Preview" if self._shown else "Show Preview")


# ── StepButton ─────────────────────────────────────────────────────

class StepButton(QPushButton):
    """Sidebar button with coloured status icon for workflow steps."""

    _STATUS_COLOURS = {
        "not_started": "#9AA0A6",
        "in_progress": "#FF9E00",
        "complete":    "#34A853",
    }

    def __init__(self, step_number, text, is_workflow=True, parent=None):
        super().__init__(text, parent)
        self._step_number = step_number
        self._is_workflow = is_workflow
        self._status = "not_started"

        s = get_scale_manager()
        self.setCheckable(True)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setMinimumHeight(s.dimension(38))
        self.setStyleSheet(theme.nav_button_style())

        if is_workflow:
            self._update_icon()

    def set_step_status(self, status):
        """Set status: 'not_started' | 'in_progress' | 'complete'."""
        if status in self._STATUS_COLOURS and self._is_workflow:
            self._status = status
            self._update_icon()

    def _update_icon(self):
        s = get_scale_manager()
        sz = s.dimension(16)
        colour = self._STATUS_COLOURS.get(self._status, "#9AA0A6")
        check = self._status == "complete"
        pixmap = _create_status_pixmap(colour, check=check, size=sz)
        self.setIcon(QIcon(pixmap))
        self.setIconSize(s.icon_size(16))


# ── TableComparisonWidget ─────────────────────────────────────────

class TableComparisonWidget(QWidget):
    """Three DataPreviewTable instances side-by-side: Current | Incoming | Preview."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._s = get_scale_manager()
        self._build()

    def _build(self):
        s = self._s
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(s.dimension(8))

        self.current_table = self._make_panel("Current Data")
        self.incoming_table = self._make_panel("Incoming CSV")
        self.preview_table = self._make_panel("Final Preview")

        layout.addWidget(self.current_table['widget'], 1)
        layout.addWidget(self.incoming_table['widget'], 1)
        layout.addWidget(self.preview_table['widget'], 1)

    def _make_panel(self, title):
        s = self._s
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(s.dimension(4))

        lbl = QLabel(title)
        lbl.setStyleSheet(
            f"font-weight: bold; font-size: {s.font_size(11)}px; "
            f"font-family: {theme.FONT_FAMILY}; color: {theme.TEXT_PRIMARY};"
        )
        lay.addWidget(lbl)

        table = DataPreviewTable()
        lay.addWidget(table)

        return {'widget': w, 'label': lbl, 'table': table}

    def set_current(self, df):
        self.current_table['table'].set_data(df)

    def set_incoming(self, df):
        self.incoming_table['table'].set_data(df)

    def set_preview(self, df):
        self.preview_table['table'].set_data(df)

    def clear_all(self):
        self.current_table['table'].clear()
        self.incoming_table['table'].clear()
        self.preview_table['table'].clear()


# ── LayerCheckList ────────────────────────────────────────────────

class LayerCheckList(QWidget):
    """Themed QListWidget with checkboxes for categorized vector layers."""

    checks_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._s = get_scale_manager()
        self._build()
        self._list.itemChanged.connect(lambda _item: self.checks_changed.emit())

    def _build(self):
        s = self._s
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(s.dimension(4))

        self._list = QListWidget()
        self._list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {theme.BORDER}; "
            f"  border-radius: {s.dimension(4)}px; "
            f"  font-size: {s.font_size(11)}px; font-family: {theme.FONT_FAMILY}; "
            f"  background-color: {theme.BG_CARD}; }}"
            f"QListWidget::item {{ padding: {s.dimension(4)}px; }}"
            f"QListWidget::item:hover {{ background-color: {theme.HOVER}; }}"
        )
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(s.dimension(6))

        btn_all = QPushButton("Select All")
        btn_all.setCursor(QCursor(Qt.PointingHandCursor))
        btn_all.setStyleSheet(theme.action_button_style(primary=False))
        btn_all.clicked.connect(self.select_all)

        btn_none = QPushButton("Select None")
        btn_none.setCursor(QCursor(Qt.PointingHandCursor))
        btn_none.setStyleSheet(theme.action_button_style(primary=False))
        btn_none.clicked.connect(self.select_none)

        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def set_layers(self, layers, unchecked_ids=None):
        """Populate with layer objects. Each gets a checkbox storing the layer id.

        unchecked_ids: layer ids to populate unchecked (layers not listed
        default to checked, so newly added layers are included).
        """
        unchecked = set(unchecked_ids or [])
        self._list.blockSignals(True)
        self._list.clear()
        for layer in layers:
            item = QListWidgetItem(layer_display_name(layer))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Unchecked if layer.id() in unchecked else Qt.Checked)
            item.setData(Qt.UserRole, layer.id())
            self._list.addItem(item)
        self._list.blockSignals(False)
        self.checks_changed.emit()

    def checked_layer_ids(self):
        """Return list of layer IDs for checked items."""
        ids = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        return ids

    def unchecked_layer_ids(self):
        """Return list of layer IDs for unchecked items."""
        ids = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() != Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        return ids

    def select_all(self):
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.Checked)

    def select_none(self):
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.Unchecked)


# ── FieldGroupManager ────────────────────────────────────────────

class _FieldPickerDialog(QDialog):
    """Modal dialog to pick fields for a group via checkboxes.

    When populated_fields is given, fields with no data are marked
    '(empty)' and hidden by default behind a 'Hide empty fields' toggle —
    already-checked fields are always shown.
    """

    def __init__(self, available_fields, already_checked=None,
                 populated_fields=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Fields for Group")
        s = get_scale_manager()
        self.setMinimumSize(s.dimension(300), s.dimension(350))
        self.setStyleSheet(theme.dialog_style())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*s.margins(12, 12, 12, 12))
        layout.setSpacing(s.dimension(8))

        lbl = QLabel("Check the fields to include in this group:")
        lbl.setStyleSheet(
            f"font-size: {s.font_size(11)}px; font-family: {theme.FONT_FAMILY}; "
            f"color: {theme.TEXT_PRIMARY};"
        )
        layout.addWidget(lbl)

        already_checked = set(already_checked or [])
        self._empty_fields = (
            {f for f in available_fields if f not in populated_fields}
            if populated_fields is not None else set())

        if self._empty_fields:
            self._hide_empty = QCheckBox("Hide empty fields")
            self._hide_empty.setChecked(True)
            self._hide_empty.toggled.connect(self._apply_empty_filter)
            layout.addWidget(self._hide_empty)
        else:
            self._hide_empty = None

        self._list = QListWidget()
        self._list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {theme.BORDER}; "
            f"  border-radius: {s.dimension(4)}px; "
            f"  font-size: {s.font_size(11)}px; font-family: {theme.FONT_FAMILY}; "
            f"  background-color: {theme.BG_CARD}; }}"
            f"QListWidget::item {{ padding: {s.dimension(4)}px; }}"
            f"QListWidget::item:hover {{ background-color: {theme.HOVER}; }}"
        )
        for field in available_fields:
            label = (f"{field} (empty)" if field in self._empty_fields
                     else field)
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, field)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if field in already_checked else Qt.Unchecked)
            self._list.addItem(item)
        layout.addWidget(self._list, 1)
        self._apply_empty_filter()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.setStyleSheet(theme.action_button_style(primary=False))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply_empty_filter(self, *_args):
        hide = bool(self._hide_empty and self._hide_empty.isChecked())
        for i in range(self._list.count()):
            item = self._list.item(i)
            field = item.data(Qt.UserRole)
            is_empty = field in self._empty_fields
            keep = (not is_empty or not hide
                    or item.checkState() == Qt.Checked)
            item.setHidden(not keep)

    def checked_fields(self):
        result = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.Checked:
                result.append(item.data(Qt.UserRole))
        return result


class FieldGroupManager(QWidget):
    """Widget for creating/editing named field groups (legend sections).

    Each group is a dict: {'name', 'fields', 'subdivide_by', 'display',
    'lookup'} where display is 'auto'/'symbols'/'text' and lookup is
    {'table': {'id','name'}, 'key_column', 'value_column'} or None.
    A value field can only belong to one group at a time.
    """

    groups_changed = pyqtSignal()

    DISPLAY_CHOICES = [
        ("Auto (symbols, text overflow)", 'auto'),
        ("Symbols only", 'symbols'),
        ("Text only", 'text'),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._s = get_scale_manager()
        self._all_fields = []
        self._populated_fields = None  # set of fields with data, or None
        self._groups = []  # list of group dicts (see class docstring)
        self._build()

    @staticmethod
    def _make_group(name, fields=None, subdivide_by=None,
                    display='auto', lookup=None):
        return {'name': name, 'fields': list(fields or []),
                'subdivide_by': subdivide_by, 'display': display,
                'lookup': lookup}

    def _build(self):
        s = self._s
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(s.dimension(6))

        # Group list container
        self._group_container = QVBoxLayout()
        self._group_container.setSpacing(s.dimension(4))
        layout.addLayout(self._group_container)

        # Add group button
        btn_row = QHBoxLayout()
        btn_row.setSpacing(s.dimension(6))
        btn_add = QPushButton("+ Add Group")
        btn_add.setCursor(QCursor(Qt.PointingHandCursor))
        btn_add.setStyleSheet(theme.action_button_style(primary=False))
        btn_add.clicked.connect(self._add_group)
        btn_row.addWidget(btn_add)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def set_available_fields(self, field_names):
        """Set the full list of fields available for grouping."""
        self._all_fields = list(field_names)
        self._populated_fields = None
        # Clear existing groups
        self._groups.clear()
        self._rebuild_group_widgets()

    def set_populated_fields(self, field_names):
        """Mark which fields contain data (None = unknown, no filtering)."""
        self._populated_fields = (set(field_names)
                                  if field_names is not None else None)

    def restore_groups(self, groups):
        """Restore a previously saved group configuration.

        Accepts group dicts or legacy (name, fields, subdivide_by) tuples.
        Validates that fields still exist in the current field list.
        """
        valid_fields = set(self._all_fields)
        restored = []
        for group in groups:
            if isinstance(group, dict):
                g = self._make_group(
                    group.get('name', ''), group.get('fields'),
                    group.get('subdivide_by'),
                    group.get('display', 'auto'), group.get('lookup'))
                if group.get('id'):
                    g['id'] = group['id']  # preserve section identity
            else:
                name, fields, sub = group
                g = self._make_group(name, fields, sub)
            g['fields'] = [f for f in g['fields'] if f in valid_fields]
            if g['subdivide_by'] and g['subdivide_by'] not in valid_fields:
                g['subdivide_by'] = None
            restored.append(g)
        self._groups = restored
        self._rebuild_group_widgets()

    def get_field_groups(self):
        """Return the list of group dicts (copies)."""
        return [dict(g, fields=list(g['fields'])) for g in self._groups]

    def _used_fields(self, exclude_index=None):
        """Return set of fields already assigned to any group."""
        used = set()
        for i, group in enumerate(self._groups):
            if i != exclude_index:
                used.update(group['fields'])
        return used

    def _available_for_group(self, group_index):
        """Fields available for a specific group (unassigned + already in this group)."""
        used = self._used_fields(exclude_index=group_index)
        return [f for f in self._all_fields if f not in used]

    def _add_group(self):
        idx = len(self._groups)
        self._groups.append(self._make_group(f"Group {idx + 1}"))
        self._rebuild_group_widgets()
        self.groups_changed.emit()

    def _remove_group(self, index):
        if 0 <= index < len(self._groups):
            self._groups.pop(index)
            self._rebuild_group_widgets()
            self.groups_changed.emit()

    def _edit_fields(self, index):
        if index < 0 or index >= len(self._groups):
            return
        group = self._groups[index]
        available = self._available_for_group(index)
        dlg = _FieldPickerDialog(available, group['fields'],
                                 populated_fields=self._populated_fields,
                                 parent=self)
        if dlg.exec() == QDialog.Accepted:
            group['fields'] = dlg.checked_fields()
            self._rebuild_group_widgets()
            self.groups_changed.emit()

    def _rename_group(self, index, new_name):
        if 0 <= index < len(self._groups):
            self._groups[index]['name'] = new_name
            self.groups_changed.emit()

    def _set_subdivide(self, index, field_name):
        """Set the subdivide-by field for a group."""
        if 0 <= index < len(self._groups):
            self._groups[index]['subdivide_by'] = field_name or None
            self.groups_changed.emit()

    def _set_display(self, index, mode):
        if 0 <= index < len(self._groups):
            self._groups[index]['display'] = mode
            self.groups_changed.emit()

    @staticmethod
    def _lookup_tables():
        """Non-spatial vector layers in the project (lookup tables)."""
        from qgis.core import QgsProject, QgsMapLayerType
        tables = []
        for lyr in sorted(QgsProject.instance().mapLayers().values(),
                          key=lambda l: l.name()):
            if (lyr.type() == QgsMapLayerType.VectorLayer
                    and not lyr.isSpatial()):
                tables.append(lyr)
        return tables

    def _set_lookup(self, index, table_id):
        """Assign a lookup table to a group (auto-detecting columns)."""
        if not (0 <= index < len(self._groups)):
            return
        if not table_id:
            self._groups[index]['lookup'] = None
            self.groups_changed.emit()
            return
        from qgis.core import QgsProject
        try:
            from .legend_builder import detect_lookup_columns
        except ImportError:
            from legend_builder import detect_lookup_columns
        table = QgsProject.instance().mapLayer(table_id)
        if not table:
            return
        key_col, val_col = detect_lookup_columns(table)
        self._groups[index]['lookup'] = {
            'table': {'id': table.id(), 'name': table.name()},
            'key_column': key_col,
            'value_column': val_col,
        }
        self.groups_changed.emit()

    def _edit_lookup_columns(self, index):
        """Mini dialog to override the lookup key/value columns."""
        if not (0 <= index < len(self._groups)):
            return
        lookup = self._groups[index]['lookup']
        if not lookup:
            return
        from qgis.core import QgsProject
        table = QgsProject.instance().mapLayer(lookup['table'].get('id', ''))
        if not table:
            matches = QgsProject.instance().mapLayersByName(
                lookup['table'].get('name', ''))
            table = matches[0] if matches else None
        if not table:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Lookup Columns")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Key (code) column:"))
        key_combo = QComboBox()
        lay.addWidget(key_combo)
        lay.addWidget(QLabel("Value (description) column:"))
        val_combo = QComboBox()
        lay.addWidget(val_combo)
        for f in table.fields():
            key_combo.addItem(f.name())
            val_combo.addItem(f.name())
        ki = key_combo.findText(lookup.get('key_column', ''))
        if ki >= 0:
            key_combo.setCurrentIndex(ki)
        vi = val_combo.findText(lookup.get('value_column', ''))
        if vi >= 0:
            val_combo.setCurrentIndex(vi)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        if dlg.exec() == QDialog.Accepted:
            lookup['key_column'] = key_combo.currentText()
            lookup['value_column'] = val_combo.currentText()
            self.groups_changed.emit()

    def _rebuild_group_widgets(self):
        """Tear down and rebuild all group row widgets."""
        s = self._s
        _NONE_LABEL = "(None — flat list)"

        combo_style = (
            f"font-size: {s.font_size(10)}px; font-family: {theme.FONT_FAMILY}; "
            f"color: {theme.TEXT_PRIMARY}; background-color: {theme.BG_CARD}; "
            f"border: 1px solid {theme.BORDER}; border-radius: {s.dimension(3)}px; "
            f"padding: {s.dimension(2)}px;"
        )

        # Clear existing widgets from container
        while self._group_container.count():
            item = self._group_container.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for i, group in enumerate(self._groups):
            name = group['name']
            fields = group['fields']
            subdivide_by = group['subdivide_by']
            row = QFrame()
            row.setStyleSheet(
                f"QFrame {{ background-color: {theme.BG_CARD}; "
                f"border: 1px solid {theme.BORDER}; "
                f"border-radius: {s.dimension(4)}px; }}"
            )
            row_lay = QVBoxLayout(row)
            row_lay.setContentsMargins(*s.margins(8, 6, 8, 6))
            row_lay.setSpacing(s.dimension(4))

            # Top row: name + buttons
            top = QHBoxLayout()
            top.setSpacing(s.dimension(6))

            name_edit = QLineEdit(name)
            name_edit.setStyleSheet(
                f"font-size: {s.font_size(11)}px; font-family: {theme.FONT_FAMILY}; "
                f"font-weight: bold; color: {theme.TEXT_PRIMARY}; "
                f"background-color: {theme.BG_CARD}; border: 1px solid {theme.BORDER}; "
                f"border-radius: {s.dimension(3)}px; padding: {s.dimension(3)}px;"
            )
            idx = i  # capture for lambda
            name_edit.textChanged.connect(lambda text, ix=idx: self._rename_group(ix, text))
            top.addWidget(name_edit, 1)

            btn_edit = QPushButton("Edit Fields")
            btn_edit.setCursor(QCursor(Qt.PointingHandCursor))
            btn_edit.setStyleSheet(theme.action_button_style(primary=False))
            btn_edit.clicked.connect(lambda checked, ix=idx: self._edit_fields(ix))
            top.addWidget(btn_edit)

            btn_remove = QPushButton("Remove")
            btn_remove.setCursor(QCursor(Qt.PointingHandCursor))
            btn_remove.setStyleSheet(theme.action_button_style(primary=False))
            btn_remove.clicked.connect(lambda checked, ix=idx: self._remove_group(ix))
            top.addWidget(btn_remove)

            row_lay.addLayout(top)

            # Field summary label
            if fields:
                field_text = "Value fields: " + ", ".join(fields)
            else:
                field_text = "(no fields assigned — click Edit Fields)"
            field_lbl = QLabel(field_text)
            field_lbl.setWordWrap(True)
            field_lbl.setStyleSheet(
                f"font-size: {s.font_size(10)}px; font-family: {theme.FONT_FAMILY}; "
                f"color: {theme.TEXT_SECONDARY}; border: none; padding: 0;"
            )
            row_lay.addWidget(field_lbl)

            # Subdivide-by row
            sub_row = QHBoxLayout()
            sub_row.setSpacing(s.dimension(6))
            sub_lbl = QLabel("Subdivide by:")
            sub_lbl.setStyleSheet(
                f"font-size: {s.font_size(10)}px; font-family: {theme.FONT_FAMILY}; "
                f"color: {theme.TEXT_SECONDARY}; border: none; padding: 0;"
            )
            sub_row.addWidget(sub_lbl)

            sub_combo = QComboBox()
            sub_combo.setStyleSheet(combo_style)
            sub_combo.addItem(_NONE_LABEL, None)
            for field in self._all_fields:
                sub_combo.addItem(field, field)
            # Set current selection
            if subdivide_by:
                combo_idx = sub_combo.findData(subdivide_by)
                if combo_idx >= 0:
                    sub_combo.setCurrentIndex(combo_idx)
            sub_combo.currentIndexChanged.connect(
                lambda ci, ix=idx, cb=sub_combo: self._set_subdivide(ix, cb.currentData())
            )
            sub_row.addWidget(sub_combo, 1)
            row_lay.addLayout(sub_row)

            # Display mode + lookup table row
            disp_row = QHBoxLayout()
            disp_row.setSpacing(s.dimension(6))

            disp_lbl = QLabel("Display as:")
            disp_lbl.setStyleSheet(
                f"font-size: {s.font_size(10)}px; font-family: {theme.FONT_FAMILY}; "
                f"color: {theme.TEXT_SECONDARY}; border: none; padding: 0;"
            )
            disp_row.addWidget(disp_lbl)

            disp_combo = QComboBox()
            disp_combo.setStyleSheet(combo_style)
            for label, mode in self.DISPLAY_CHOICES:
                disp_combo.addItem(label, mode)
            di = disp_combo.findData(group.get('display', 'auto'))
            if di >= 0:
                disp_combo.setCurrentIndex(di)
            disp_combo.currentIndexChanged.connect(
                lambda ci, ix=idx, cb=disp_combo: self._set_display(ix, cb.currentData())
            )
            disp_row.addWidget(disp_combo, 1)

            lk_lbl = QLabel("Lookup:")
            lk_lbl.setStyleSheet(
                f"font-size: {s.font_size(10)}px; font-family: {theme.FONT_FAMILY}; "
                f"color: {theme.TEXT_SECONDARY}; border: none; padding: 0;"
            )
            disp_row.addWidget(lk_lbl)

            lk_combo = QComboBox()
            lk_combo.setStyleSheet(combo_style)
            lk_combo.addItem("(None)", None)
            for table in self._lookup_tables():
                lk_combo.addItem(table.name(), table.id())
            lookup = group.get('lookup')
            if lookup:
                li = lk_combo.findData(lookup['table'].get('id'))
                if li < 0:
                    li = lk_combo.findText(lookup['table'].get('name', ''))
                if li >= 0:
                    lk_combo.setCurrentIndex(li)
            lk_combo.currentIndexChanged.connect(
                lambda ci, ix=idx, cb=lk_combo: self._set_lookup(ix, cb.currentData())
            )
            disp_row.addWidget(lk_combo, 1)

            btn_cols = QPushButton("Columns…")
            btn_cols.setCursor(QCursor(Qt.PointingHandCursor))
            btn_cols.setStyleSheet(theme.action_button_style(primary=False))
            btn_cols.clicked.connect(
                lambda checked, ix=idx: self._edit_lookup_columns(ix))
            disp_row.addWidget(btn_cols)

            row_lay.addLayout(disp_row)

            self._group_container.addWidget(row)
