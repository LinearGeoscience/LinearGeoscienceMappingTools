"""
Mining survey data import dialog.

Zero-config flow: pick a folder, everything importable underneath is
discovered, compared against what the output GeoPackage already holds, and
only the new or changed files come pre-checked. Pick the output, Import.

Deliberately monochrome — plain 1px borders, no colour accents.

Threading shape (structural, not incidental): sniffing and fingerprinting
read files, so the scan is its own background task; lgs_tasks workers may not
touch widgets, so anything that needs to ask the user happens on the main
thread between the two tasks; the import is a second task.
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from qgis.core import QgsCoordinateReferenceSystem, QgsProject
from qgis.gui import QgsProjectionSelectionWidget

try:
    from ..lgs_tasks import run_in_task
    from .. import plugin_theme as theme
    from . import gpkg, importer, merge, scan, schema, settings_store
except ImportError:  # direct (non-package) execution inside QGIS
    from lgs_tasks import run_in_task
    import plugin_theme as theme
    from mining_import import (gpkg, importer, merge, scan, schema,
                               settings_store)

_COL_FILE, _COL_FORMAT, _COL_LEVEL, _COL_STATUS = range(4)


def _dialog_style():
    return f"""
        QDialog {{ background-color: #FFFFFF; }}
        QLabel {{
            font-family: {theme.FONT_FAMILY};
            color: {theme.TEXT_PRIMARY};
        }}
        QGroupBox {{
            font-family: {theme.FONT_FAMILY};
            font-weight: bold;
            color: {theme.TEXT_PRIMARY};
            border: 1px solid {theme.BORDER_DARK};
            border-radius: 2px;
            margin-top: 8px;
            padding-top: 12px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 4px;
        }}
        QPushButton {{
            font-family: {theme.FONT_FAMILY};
            background-color: #FFFFFF;
            color: {theme.TEXT_PRIMARY};
            border: 1px solid {theme.BORDER_DARK};
            border-radius: 2px;
            padding: 5px 14px;
        }}
        QPushButton:hover {{ background-color: {theme.HOVER}; }}
        QPushButton:pressed {{ background-color: {theme.BORDER}; }}
        QPushButton:disabled {{
            color: {theme.TEXT_SECONDARY};
            background-color: {theme.BG_PRIMARY};
        }}
        QLineEdit, QTableWidget, QComboBox {{
            font-family: {theme.FONT_FAMILY};
            border: 1px solid {theme.BORDER_DARK};
            border-radius: 2px;
            background-color: #FFFFFF;
            padding: 2px;
        }}
        QCheckBox {{
            font-family: {theme.FONT_FAMILY};
            color: {theme.TEXT_PRIMARY};
        }}
        QProgressBar {{
            border: 1px solid {theme.BORDER_DARK};
            border-radius: 2px;
            text-align: center;
            background-color: #FFFFFF;
        }}
        QProgressBar::chunk {{ background-color: {theme.BORDER_DARK}; }}
    """


class MiningImportDialog(QDialog):

    def __init__(self, parent=None, owner=None):
        super().__init__(parent)
        self._owner = owner
        self._task = None
        self._entries = []
        self._root = ''
        self._scan_result = {}
        self.setWindowTitle("Import Mining Survey Data")
        self.resize(720, 620)
        self.setStyleSheet(_dialog_style())

        layout = QVBoxLayout(self)

        # --- Source --------------------------------------------------------
        source_group = QGroupBox("Source")
        source_layout = QVBoxLayout(source_group)
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText(
            "Folder of survey files (searched recursively), or pick files")
        folder_btn = QPushButton("Add folder…")
        folder_btn.clicked.connect(self._browse_folder)
        files_btn = QPushButton("Add files…")
        files_btn.clicked.connect(self._browse_files)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(folder_btn)
        folder_row.addWidget(files_btn)
        source_layout.addLayout(folder_row)
        layout.addWidget(source_group)

        # --- Discovered files ---------------------------------------------
        files_group = QGroupBox("Files to import")
        files_layout = QVBoxLayout(files_group)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["File", "Format", "Level", "Status"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_FILE, QHeaderView.ResizeMode.Stretch)
        for col in (_COL_FORMAT, _COL_LEVEL, _COL_STATUS):
            header.setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._update_ready)
        files_layout.addWidget(self.table)

        select_row = QHBoxLayout()
        for label, handler in (("Select all", self._select_all),
                               ("Select none", self._select_none),
                               ("Only new and changed", self._select_pending)):
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            select_row.addWidget(btn)
        select_row.addStretch(1)
        files_layout.addLayout(select_row)
        layout.addWidget(files_group, 1)

        # --- Options -------------------------------------------------------
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)

        crs_row = QHBoxLayout()
        crs_row.addWidget(QLabel("CRS of the files:"))
        self.crs_selector = QgsProjectionSelectionWidget()
        remembered = settings_store.get(settings_store.KEY_LAST_CRS, '')
        crs = QgsCoordinateReferenceSystem(remembered) if remembered \
            else QgsProject.instance().crs()
        self.crs_selector.setCrs(
            crs if crs.isValid() else QgsProject.instance().crs())
        crs_row.addWidget(self.crs_selector, 1)
        options_layout.addLayout(crs_row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output GeoPackage:"))
        self.output_edit = QLineEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setPlaceholderText("New or existing .gpkg")
        self.output_edit.setText(
            settings_store.get(settings_store.KEY_LAST_OUTPUT, ''))
        out_btn = QPushButton("Browse…")
        out_btn.clicked.connect(self._browse_output)
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(out_btn)
        options_layout.addLayout(out_row)

        policy_row = QHBoxLayout()
        policy_row.addWidget(QLabel("When re-importing:"))
        self.policy_combo = QComboBox()
        for policy in merge.POLICIES:
            self.policy_combo.addItem(merge.POLICY_LABELS[policy], policy)
        saved_policy = settings_store.get(
            settings_store.KEY_POLICY, merge.POLICY_REPLACE_SOURCE)
        index = self.policy_combo.findData(saved_policy)
        self.policy_combo.setCurrentIndex(max(index, 0))
        self.policy_combo.currentIndexChanged.connect(self._policy_changed)
        policy_row.addWidget(self.policy_combo, 1)
        options_layout.addLayout(policy_row)

        self.policy_hint = QLabel()
        self.policy_hint.setWordWrap(True)
        self.policy_hint.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-family: {theme.FONT_FAMILY};")
        options_layout.addWidget(self.policy_hint)

        self.backup_check = QCheckBox(
            "Back up the GeoPackage before writing")
        self.backup_check.setChecked(
            settings_store.get(settings_store.KEY_BACKUP, True, cast=bool))
        options_layout.addWidget(self.backup_check)

        layout.addWidget(options_group)

        # --- Progress / actions -------------------------------------------
        bar_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        bar_row.addWidget(self.progress_bar, 1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._cancel_task)
        self.cancel_button.setVisible(False)
        bar_row.addWidget(self.cancel_button)
        layout.addLayout(bar_row)

        self.status_label = QLabel("Select a folder of survey files")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-family: {theme.FONT_FAMILY};")
        layout.addWidget(self.status_label)

        self.import_button = QPushButton("Import")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self._start_import)
        layout.addWidget(self.import_button)

        self._policy_changed()
        last_folder = settings_store.get(settings_store.KEY_LAST_FOLDER, '')
        if last_folder and os.path.isdir(last_folder):
            self.folder_edit.setText(last_folder)

    # --- UI plumbing ------------------------------------------------------

    def _policy_changed(self, *_args):
        policy = self.policy_combo.currentData()
        self.policy_hint.setText(merge.POLICY_HINTS.get(policy, ''))

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select folder containing survey files",
            self.folder_edit.text() or "")
        if not folder:
            return
        self.folder_edit.setText(folder)
        settings_store.put(settings_store.KEY_LAST_FOLDER, folder)
        if not self.output_edit.text():
            self.output_edit.setText(os.path.join(
                folder, os.path.basename(folder) + "_survey.gpkg"))
        self._start_scan(folder=folder)

    def _browse_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select survey files", self.folder_edit.text() or "",
            "Survey files (*.str);;All files (*)")
        if not paths:
            return
        self.folder_edit.setText(
            "{0} file(s) selected".format(len(paths)))
        self._start_scan(paths=paths)

    def _browse_output(self):
        start = self.output_edit.text() or self.folder_edit.text() or ""
        path, _ = QFileDialog.getSaveFileName(
            self, "Output GeoPackage", start, "GeoPackage (*.gpkg)",
            options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return
        if not path.lower().endswith('.gpkg'):
            path += '.gpkg'
        self.output_edit.setText(path)
        settings_store.put(settings_store.KEY_LAST_OUTPUT, path)
        # The target decides what counts as new or changed, so re-scan.
        if self._entries:
            self._rescan()
        self._update_ready()

    # --- scan -------------------------------------------------------------

    def _rescan(self):
        folder = self.folder_edit.text()
        if self._entries and not os.path.isdir(folder):
            self._start_scan(paths=[e.path for e in self._entries])
        elif os.path.isdir(folder):
            self._start_scan(folder=folder)

    def _start_scan(self, folder=None, paths=None):
        if self._task is not None:
            return
        gpkg_path = self.output_edit.text() or None
        self.import_button.setEnabled(False)
        self.cancel_button.setVisible(True)
        self.progress_bar.setValue(0)
        self._task = run_in_task(
            "Scan survey files",
            lambda cb: importer.scan_sources(
                folder=folder, paths=paths, gpkg_path=gpkg_path,
                progress_cb=cb),
            on_finished=self._scan_done,
            on_error=self._task_failed,
            on_cancelled=self._task_cancelled,
            owner=self, bar=self.progress_bar, label=self.status_label)

    def _scan_done(self, result):
        self._finish_task_ui()
        self.progress_bar.setValue(100)
        self._scan_result = result
        self._entries = result['entries']
        self._root = result['root']
        self._populate_table()

        if result.get('legacy_layers'):
            QMessageBox.information(
                self, "Older layers found",
                "This GeoPackage contains {0} from an earlier build of the "
                "importer.\n\nThose layers are left untouched; this import "
                "writes to {1}. You can safely remove the old ones once "
                "you've confirmed the new import.".format(
                    ' and '.join(result['legacy_layers']),
                    ', '.join(schema.LAYER_ORDER[:2])))

        if result.get('duplicates'):
            QMessageBox.warning(
                self, "Duplicate file names",
                "These files resolve to the same identity, so importing them "
                "together would make each one delete the other's data:\n\n"
                "{0}\n\nImport them from a common parent folder instead, so "
                "their folder names tell them apart.".format(
                    '\n'.join(result['duplicates'])))

        relink = result.get('relink') or {}
        if relink:
            self._offer_relink(relink)
        self._update_ready()

    def _offer_relink(self, mapping):
        answer = QMessageBox.question(
            self, "Files have moved",
            "{0} file(s) in this GeoPackage were imported from a different "
            "folder layout and now look like new files.\n\nRelink them, so "
            "re-importing updates the existing data instead of duplicating "
            "it?".format(len(mapping)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            gpkg.relink_log_keys(self.output_edit.text(), mapping)
        except Exception as exc:
            QMessageBox.warning(self, "Relink failed", str(exc))
            return
        self._rescan()

    def _populate_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            label = entry.key if entry.key else os.path.basename(entry.path)
            file_item = QTableWidgetItem(label)
            file_item.setToolTip(entry.path)
            file_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                               | Qt.ItemFlag.ItemIsEnabled)
            # Zero-config bias: only work that still needs doing comes checked.
            file_item.setCheckState(
                Qt.CheckState.Checked
                if entry.status in (scan.STATUS_NEW, scan.STATUS_CHANGED)
                else Qt.CheckState.Unchecked)
            self.table.setItem(row, _COL_FILE, file_item)

            fmt_item = QTableWidgetItem(entry.fmt_key or '—')
            fmt_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            if entry.companions:
                fmt_item.setText('{0} +{1}'.format(
                    entry.fmt_key,
                    ''.join(sorted(entry.companions))))
                fmt_item.setToolTip('Companion file(s): {0}'.format(
                    ', '.join(os.path.basename(p)
                              for p in entry.companions.values())))
            self.table.setItem(row, _COL_FORMAT, fmt_item)

            self.table.setItem(row, _COL_LEVEL, QTableWidgetItem(entry.level))

            status_item = QTableWidgetItem(
                scan.STATUS_LABELS.get(entry.status, entry.status))
            status_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            status_item.setToolTip(entry.note)
            self.table.setItem(row, _COL_STATUS, status_item)
        self.table.blockSignals(False)

    def _set_all_checked(self, predicate):
        self.table.blockSignals(True)
        for row, entry in enumerate(self._entries):
            item = self.table.item(row, _COL_FILE)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked if predicate(entry)
                                   else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self._update_ready()

    def _select_all(self):
        self._set_all_checked(lambda _e: True)

    def _select_none(self):
        self._set_all_checked(lambda _e: False)

    def _select_pending(self):
        self._set_all_checked(
            lambda e: e.status in (scan.STATUS_NEW, scan.STATUS_CHANGED))

    def _checked_entries(self):
        checked = []
        for row, entry in enumerate(self._entries):
            item = self.table.item(row, _COL_FILE)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            level_item = self.table.item(row, _COL_LEVEL)
            level = (level_item.text().strip() if level_item else '') \
                or entry.level
            checked.append(entry._replace(level=level))
        return checked

    def _update_ready(self, *_args):
        if self._task is not None:
            return
        checked = self._checked_entries()
        ready = bool(checked) and bool(self.output_edit.text())
        self.import_button.setEnabled(ready)
        if not self._entries:
            self.status_label.setText("Select a folder of survey files")
            return
        counts = {}
        for entry in self._entries:
            counts[entry.status] = counts.get(entry.status, 0) + 1
        parts = ['{0} {1}'.format(counts[s], scan.STATUS_LABELS[s].lower())
                 for s in (scan.STATUS_NEW, scan.STATUS_CHANGED,
                           scan.STATUS_UNCHANGED) if counts.get(s)]
        msg = '{0} file(s) found — {1}. {2} selected.'.format(
            len(self._entries), ', '.join(parts) or 'nothing to do',
            len(checked))
        missing = self._scan_result.get('missing') or []
        if missing:
            msg += (' {0} previously imported file(s) are no longer on '
                    'disk.'.format(len(missing)))
        self.status_label.setText(msg)

    # --- import -----------------------------------------------------------

    def _start_import(self):
        entries = self._checked_entries()
        if not entries:
            return
        crs = self.crs_selector.crs()
        if not crs.isValid():
            QMessageBox.warning(self, "Invalid CRS",
                                "Select a valid CRS for the survey files.")
            return
        gpkg_path = self.output_edit.text()
        policy = self.policy_combo.currentData()
        make_backup = self.backup_check.isChecked()

        if policy == merge.POLICY_REPLACE_ALL:
            answer = QMessageBox.question(
                self, "Replace the whole layer?",
                "Everything already in the target layers will be removed, "
                "including data from files you are not importing now.\n\n"
                "Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return

        settings_store.put(settings_store.KEY_LAST_OUTPUT, gpkg_path)
        settings_store.put(settings_store.KEY_LAST_CRS, crs.authid())
        settings_store.put(settings_store.KEY_POLICY, policy)
        settings_store.put(settings_store.KEY_BACKUP, make_backup)

        root = self._root
        transform_context = QgsProject.instance().transformContext()

        self.import_button.setEnabled(False)
        self.cancel_button.setVisible(True)
        self.progress_bar.setValue(0)
        self._task = run_in_task(
            "Import mining survey data",
            lambda cb: importer.import_sources(
                gpkg_path, crs, transform_context, entries, root,
                policy=policy, make_backup=make_backup, progress_cb=cb),
            on_finished=self._import_done,
            on_error=self._task_failed,
            on_cancelled=self._task_cancelled,
            owner=self, bar=self.progress_bar, label=self.status_label)

    def _cancel_task(self):
        if self._task is not None:
            self._task.cancel()
            self.status_label.setText("Cancelling…")

    def _finish_task_ui(self):
        self._task = None
        self.cancel_button.setVisible(False)

    def _import_done(self, report):
        self._finish_task_ui()
        self.progress_bar.setValue(100)
        layers = report.get('layers', [])
        gpkg_path = self.output_edit.text()
        importer.load_into_project(gpkg_path, layers)
        self._refresh_z_filter_panel()

        parts = []
        for name in layers:
            stats = report['written'][name]
            if stats['added'] or stats['removed']:
                parts.append('{0} {1}'.format(
                    stats['added'], schema.LAYERS[name]['label'].lower()))
        replaced = sum(s['removed'] for s in report['written'].values())
        summary = 'Imported {0} from {1} file(s)'.format(
            ', '.join(parts) or 'nothing', report.get('sources', 0))
        if replaced:
            summary += ', replacing {0} superseded feature(s)'.format(replaced)
        if report.get('degenerate'):
            summary += '; {0} degenerate line(s) skipped'.format(
                report['degenerate'])
        self.status_label.setText(summary)

        # Re-scan so the table reflects the import that just happened.
        self._rescan()

        if report.get('warnings'):
            self.status_label.setToolTip('\n'.join(report['warnings']))
            QMessageBox.information(
                self, "Import finished with notes",
                summary + "\n\n" + '\n'.join(report['warnings'][:20]))
        try:
            from qgis.utils import iface
            iface.messageBar().pushSuccess("Mining import", summary)
        except Exception:
            pass

    def _task_failed(self, exc, _tb):
        self._finish_task_ui()
        self.progress_bar.setValue(0)
        self.status_label.setText("Error: {0}".format(exc))
        self._update_ready()
        QMessageBox.critical(self, "Import failed", str(exc))

    def _task_cancelled(self):
        self._finish_task_ui()
        self.progress_bar.setValue(0)
        self.status_label.setText("Cancelled")
        self._update_ready()

    def _refresh_z_filter_panel(self):
        panel = getattr(self._owner, 'z_filter_panel', None)
        if panel is None:
            return
        try:
            panel.sync_from_project()
        except (RuntimeError, AttributeError):
            pass
