#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Checkouts dashboard: who has a working copy out, and who has merged back.

A read-mostly view over CheckoutRegistry.entries() for one master, with
best-effort enrichment from each entry's working file (does it still exist
at its recorded path, and does its embedded stamp still match?). Launched
from the Reconcile dialog; "Reconcile this…" hands the selected copy back
to it and "Re-issue…" opens the Issue Field Copy dialog prefilled.
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTreeWidget,
    QTreeWidgetItem)

try:
    from . import checkout
    from .checkout import describe_entry
except ImportError:  # pragma: no cover
    from script_adddata.reconcile import checkout
    from script_adddata.reconcile.checkout import describe_entry

try:
    from ...plugin_theme import (action_button_style, group_box_style,
                                 dialog_style)
except Exception:  # pragma: no cover - theme is optional
    try:
        from plugin_theme import (action_button_style, group_box_style,
                                  dialog_style)
    except Exception:
        action_button_style = lambda primary=True: ""
        group_box_style = lambda: ""
        dialog_style = lambda: ""


_FILE_STATE_LABEL = {
    "ok": "✓",
    "moved": "file moved / not found",
    "restamped": "superseded (file re-stamped)",
    "unknown": "",
}


class CheckoutsDialog(QDialog):
    def __init__(self, iface, master_gpkg, parent=None, reconcile_dialog=None):
        super().__init__(parent)
        self.iface = iface
        self.master_gpkg = master_gpkg
        self.reconcile_dialog = reconcile_dialog

        self.setWindowTitle("Checkouts — who has a working copy")
        self.resize(860, 420)
        try:
            self.setStyleSheet(dialog_style())
        except Exception:
            pass

        layout = QVBoxLayout(self)
        self.header = QLabel()
        self.header.setWordWrap(True)
        layout.addWidget(self.header)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(
            ["Working copy", "Mapper", "Issued", "Source", "Last sync",
             "Status", "Base", "File"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        for col, width in ((0, 220), (1, 70), (2, 90), (3, 70), (4, 90),
                           (5, 90), (6, 80)):
            self.tree.setColumnWidth(col, width)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.tree, 1)

        actions = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        self._style(refresh, primary=False)
        actions.addWidget(refresh)
        actions.addStretch()
        self.reconcile_btn = QPushButton("Reconcile this…")
        self.reconcile_btn.setEnabled(False)
        self.reconcile_btn.clicked.connect(self._reconcile_selected)
        self._style(self.reconcile_btn, primary=True)
        actions.addWidget(self.reconcile_btn)
        self.reissue_btn = QPushButton("Re-issue…")
        self.reissue_btn.setEnabled(False)
        self.reissue_btn.clicked.connect(self._reissue_selected)
        self._style(self.reissue_btn, primary=False)
        actions.addWidget(self.reissue_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        self._style(close_btn, primary=False)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        self.refresh()

    def _style(self, btn, primary=True):
        try:
            btn.setStyleSheet(action_button_style(primary=primary))
        except Exception:
            pass

    def refresh(self):
        self.tree.clear()
        try:
            entries = checkout.CheckoutRegistry(self.master_gpkg).entries()
        except Exception:
            entries = []
        out = sum(1 for e in entries if e.get("status") == "out")
        self.header.setText(
            f"<b>{os.path.basename(self.master_gpkg)}</b> — "
            f"{len(entries)} checkout(s), {out} still out. A copy is 'out' "
            "until its first reconcile; re-syncing the same copy keeps "
            "working after that.")
        for entry in entries:
            row = describe_entry(entry)
            item = QTreeWidgetItem([
                row["name"], row["mapper"], row["issued"], row["source"],
                row["last_sync"], row["status"], row["base"],
                _FILE_STATE_LABEL.get(row["file_state"], "")])
            if row["path"]:
                item.setToolTip(0, row["path"])
            item.setData(0, Qt.ItemDataRole.UserRole, (entry, row))
            self.tree.addTopLevelItem(item)

    def _selected(self):
        items = self.tree.selectedItems()
        if not items:
            return None, None
        return items[0].data(0, Qt.ItemDataRole.UserRole)

    def _selection_changed(self):
        entry, row = self._selected()
        usable = bool(row and row["path"] and os.path.exists(row["path"]))
        self.reconcile_btn.setEnabled(usable
                                      and self.reconcile_dialog is not None)
        self.reissue_btn.setEnabled(entry is not None)

    def _reconcile_selected(self):
        entry, row = self._selected()
        dlg = self.reconcile_dialog
        if not (entry and row and dlg):
            return
        try:
            dlg.template_gpkg = row["path"]
            dlg.template_edit.setText(row["path"])
            dlg._template_prepared = False
            if entry.get("mapper") and not dlg.mapper_edit.text().strip():
                dlg.mapper_edit.setText(entry["mapper"])
            dlg._reset_preview()
            dlg.show()
            dlg.raise_()
        except RuntimeError:
            pass
        self.close()

    def _reissue_selected(self):
        entry, _row = self._selected()
        if entry is None:
            return
        try:
            from .issue_dialog import run_issue_dialog
        except ImportError:  # pragma: no cover
            from script_adddata.reconcile.issue_dialog import run_issue_dialog
        run_issue_dialog(self.iface, owner=self.parent() or self,
                         master=self.master_gpkg,
                         mapper=entry.get("mapper") or "")


def run_checkouts_dialog(iface, master_gpkg, owner=None,
                         reconcile_dialog=None):
    """Entry point (owner-retained like run_reconcile_tool_dialog)."""
    existing = getattr(owner, "checkouts_dialog", None) if owner else None
    if existing is not None:
        try:
            existing.master_gpkg = master_gpkg
            existing.refresh()
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return existing
        except RuntimeError:
            owner.checkouts_dialog = None

    parent = iface.mainWindow() if iface else None
    dlg = CheckoutsDialog(iface, master_gpkg, parent,
                          reconcile_dialog=reconcile_dialog)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    if owner is not None:
        dlg.destroyed.connect(lambda: setattr(owner, "checkouts_dialog", None))
        owner.checkouts_dialog = dlg
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg
