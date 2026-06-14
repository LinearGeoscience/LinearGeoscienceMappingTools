#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Reconcile / Merge Field Data dialog (the MVP UI).

A self-contained, preview-then-apply tool:
- pick the master GeoPackage and a working QField template,
- (one-off) verify/migrate the master for reconcile,
- Build Preview -> three-way classification grouped per layer/operation,
- Apply -> commit clean inserts/updates/deletes in one transaction per layer,
  advance the base snapshot (so re-syncing applies further edits), and log it.

Conflicts (a feature changed on both sides) are shown but NOT applied in the
MVP — they are left for the Phase 2 resolution UI.

Runs synchronously on the GUI thread with processEvents() for progress: the
commit uses a QgsVectorLayer edit session, which must run on the main thread.
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFileDialog, QGroupBox, QProgressBar, QTreeWidget, QTreeWidgetItem,
    QMessageBox, QApplication, QWidget, QComboBox)

from qgis.core import QgsMessageLog, Qgis

try:
    from . import engine
    from . import migrate
    from . import checkout
    from . import reconcile as rc
except ImportError:  # pragma: no cover
    from script_adddata.reconcile import engine, migrate, checkout
    from script_adddata.reconcile import reconcile as rc


# Resolution choices offered per conflict, in display order. The field-merge
# option is only shown when a field-level merge is available for that conflict.
_RES_LABELS = [
    (rc.RES_FIELD_MERGE, "Field-merge (working wins clashes)"),
    (rc.RES_TAKE_WORKING, "Take working"),
    (rc.RES_TAKE_MASTER, "Take master"),
    (rc.RES_SKIP, "Skip (leave for next time)"),
]

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


_UUID_PREVIEW_LIMIT = 100


class ReconcileDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.master_gpkg = None
        self.template_gpkg = None
        self.build = None

        self.setWindowTitle("Reconcile / Merge Field Data")
        self.resize(720, 640)
        try:
            self.setStyleSheet(dialog_style())
        except Exception:
            pass

        layout = QVBoxLayout(self)

        intro = QLabel(
            "<b>Three-way reconcile</b> between a working QField template and "
            "the master GeoPackage. Propagates adds, edits and deletes, and "
            "re-syncs an edited template without losing edits. Changes are "
            "previewed before anything is written.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # --- GeoPackages ---
        gp = QGroupBox("GeoPackages")
        try:
            gp.setStyleSheet(group_box_style())
        except Exception:
            pass
        gpl = QVBoxLayout(gp)
        self.master_edit, master_row = self._file_row(
            "Master GeoPackage:", self._pick_master)
        self.template_edit, template_row = self._file_row(
            "Working template:", self._pick_template)
        gpl.addLayout(master_row)
        gpl.addLayout(template_row)

        mapper_row = QHBoxLayout()
        mapper_row.addWidget(QLabel("Mapper ID:"))
        self.mapper_edit = QLineEdit()
        self.mapper_edit.setPlaceholderText("e.g. HW (who collected this data)")
        mapper_row.addWidget(self.mapper_edit)
        gpl.addLayout(mapper_row)
        layout.addWidget(gp)

        # --- Setup / migrate ---
        setup = QGroupBox("One-off setup")
        try:
            setup.setStyleSheet(group_box_style())
        except Exception:
            pass
        sl = QHBoxLayout(setup)
        self.migrate_btn = QPushButton("Verify / migrate master")
        self.migrate_btn.clicked.connect(self._run_migrate)
        self._style(self.migrate_btn, primary=False)
        sl.addWidget(self.migrate_btn)
        self.setup_status = QLabel("Adds lgs_* columns, backfills UUIDs, "
                                   "seeds a baseline. Safe to re-run.")
        self.setup_status.setWordWrap(True)
        sl.addWidget(self.setup_status, 1)
        layout.addWidget(setup)

        # --- Preview ---
        prev = QGroupBox("Preview")
        try:
            prev.setStyleSheet(group_box_style())
        except Exception:
            pass
        pvl = QVBoxLayout(prev)
        btn_row = QHBoxLayout()
        self.preview_btn = QPushButton("Build preview")
        self.preview_btn.clicked.connect(self._build_preview)
        self._style(self.preview_btn, primary=False)
        btn_row.addWidget(self.preview_btn)
        btn_row.addStretch()
        pvl.addLayout(btn_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Layer / operation", "Count / resolution",
                                   "Detail"])
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 230)
        pvl.addWidget(self.tree)
        # Maps "<layer>\x1f<uuid>" -> (ConflictRecord, QComboBox) for apply time.
        self._conflict_widgets = {}
        # [(SplitGroup|MergeGroup, QTreeWidgetItem)] for accept/reject checkboxes.
        self._lineage_items = []

        self.summary = QLabel("No preview yet.")
        self.summary.setWordWrap(True)
        pvl.addWidget(self.summary)
        layout.addWidget(prev, 1)

        # --- Progress + actions ---
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.status = QLabel("Ready")
        layout.addWidget(self.status)

        actions = QHBoxLayout()
        actions.addStretch()
        self.apply_btn = QPushButton("Apply reconcile")
        self.apply_btn.clicked.connect(self._apply)
        self.apply_btn.setEnabled(False)
        self._style(self.apply_btn, primary=True)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        self._style(close_btn, primary=False)
        actions.addWidget(self.apply_btn)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

    # ----------------------------------------------------------------- helpers
    def _style(self, btn, primary=True):
        try:
            btn.setStyleSheet(action_button_style(primary=primary))
        except Exception:
            pass

    def _file_row(self, label, slot):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        edit = QLineEdit()
        edit.setReadOnly(True)
        btn = QPushButton("Browse…")
        btn.clicked.connect(slot)
        row.addWidget(edit, 1)
        row.addWidget(btn)
        return edit, row

    def _pick_master(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select master GeoPackage", "", "GeoPackage (*.gpkg)")
        if path:
            self.master_gpkg = path
            self.master_edit.setText(path)
            self._prefill_mapper()
            self._reset_preview()

    def _pick_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select working template GeoPackage", "", "GeoPackage (*.gpkg)")
        if path:
            self.template_gpkg = path
            self.template_edit.setText(path)
            self._prefill_mapper()
            self._reset_preview()

    def _prefill_mapper(self):
        """Pull the recorded mapper for this template, if any."""
        if not (self.master_gpkg and self.template_gpkg):
            return
        if self.mapper_edit.text().strip():
            return
        try:
            tid = checkout.template_id_from_path(self.template_gpkg)
            entry = checkout.CheckoutRegistry(self.master_gpkg).get(tid)
            if entry and entry.get("mapper"):
                self.mapper_edit.setText(entry["mapper"])
        except Exception:
            pass

    def _reset_preview(self):
        self.build = None
        self.tree.clear()
        self.summary.setText("No preview yet.")
        self.apply_btn.setEnabled(False)

    def _on_progress(self, pct, msg):
        self.progress.setValue(int(pct))
        self.status.setText(msg)
        QApplication.processEvents()

    def _require_paths(self):
        if not self.master_gpkg or not os.path.exists(self.master_gpkg):
            QMessageBox.warning(self, "Reconcile", "Select a master GeoPackage.")
            return False
        if not self.template_gpkg or not os.path.exists(self.template_gpkg):
            QMessageBox.warning(self, "Reconcile", "Select a working template.")
            return False
        return True

    # ----------------------------------------------------------------- actions
    def _run_migrate(self):
        if not self.master_gpkg or not os.path.exists(self.master_gpkg):
            QMessageBox.warning(self, "Reconcile", "Select a master GeoPackage first.")
            return
        self.migrate_btn.setEnabled(False)
        try:
            report = migrate.run_migration(self.master_gpkg, progress_cb=self._on_progress)
            added = sum(len(v.get("columns_added", []))
                        for v in report.get("layers", {}).values()
                        if isinstance(v, dict))
            filled = sum(v.get("uuids_filled", 0)
                         for v in report.get("layers", {}).values()
                         if isinstance(v, dict))
            if report.get("ok"):
                self.setup_status.setText(
                    f"Migrated. lgs_* columns added: {added}; UUIDs backfilled: "
                    f"{filled}. UUID defaults: {report.get('uuid_defaults')}")
            else:
                self.setup_status.setText(
                    "Migration finished with issues: "
                    + "; ".join(report.get("errors", [])))
        except Exception as exc:
            QgsMessageLog.logMessage(f"reconcile migrate failed: {exc}",
                                     "Linear Geoscience", Qgis.Critical)
            QMessageBox.critical(self, "Reconcile", f"Migration failed:\n{exc}")
        finally:
            self.migrate_btn.setEnabled(True)
            self.progress.setValue(0)
            self.status.setText("Ready")

    def _build_preview(self):
        if not self._require_paths():
            return
        self._reset_preview()
        self.preview_btn.setEnabled(False)
        try:
            self.build = engine.build_plans(
                self.master_gpkg, self.template_gpkg, progress_cb=self._on_progress)
            self._populate_tree(self.build)
        except Exception as exc:
            QgsMessageLog.logMessage(f"reconcile preview failed: {exc}",
                                     "Linear Geoscience", Qgis.Critical)
            QMessageBox.critical(self, "Reconcile", f"Preview failed:\n{exc}")
        finally:
            self.preview_btn.setEnabled(True)
            self.progress.setValue(0)
            self.status.setText("Ready")

    def _populate_tree(self, build):
        self.tree.clear()
        self._conflict_widgets = {}
        self._lineage_items = []
        plans = build.get("plans", [])
        tot = {"inserts": 0, "updates": 0, "deletes": 0, "auto_merges": 0,
               "conflicts": 0, "splits": 0, "merges": 0, "skipped": 0}

        for plan in plans:
            s = plan.summary()
            for k in tot:
                tot[k] += s.get(k, 0)
            top = QTreeWidgetItem([plan.layer, "", ""])
            if plan.base_was_synthesized:
                top.setText(2, "no recorded base — synthesized")
            self.tree.addTopLevelItem(top)

            self._op_node(top, "Adds", [o.uuid for o in plan.clean_inserts])
            self._op_node(top, "Updates", [o.uuid for o in plan.clean_updates])
            self._op_node(top, "Deletes", [o.uuid for o in plan.clean_deletes])
            self._op_node(top, "Auto-merged (disjoint edits)",
                          [o.uuid for o in plan.auto_merges])
            self._conflict_node(top, plan)
            self._lineage_node(top, "Splits (1 → many)", plan.splits, "split")
            self._lineage_node(top, "Merges (many → 1)", plan.merges, "merge")
            self._op_node(top, "Skipped / no-op",
                          [u for u, _ in plan.skipped], collapsed=True)
            top.setExpanded(True)

        # setItemWidget must run after items are in the tree.
        self._attach_conflict_widgets()

        missing = build.get("missing_layers", [])
        parts = [f"{tot['inserts']} adds", f"{tot['updates']} updates",
                 f"{tot['deletes']} deletes",
                 f"{tot['auto_merges']} auto-merged",
                 f"{tot['conflicts']} conflicts"]
        msg = "Preview: " + ", ".join(parts) + "."
        if tot["conflicts"]:
            msg += (" Choose a resolution per conflict (default shown); "
                    "those left on 'Skip' re-surface next sync.")
        if missing:
            msg += (" Layers not in master (use Append to create first): "
                    + ", ".join(missing) + ".")
        self.summary.setText(msg)
        self._refresh_apply_enabled()

    def _op_node(self, parent, label, uuids, collapsed=False):
        node = QTreeWidgetItem([label, str(len(uuids)), ""])
        parent.addChild(node)
        for u in uuids[:_UUID_PREVIEW_LIMIT]:
            node.addChild(QTreeWidgetItem(["", "", u]))
        if len(uuids) > _UUID_PREVIEW_LIMIT:
            node.addChild(QTreeWidgetItem(
                ["", "", f"… and {len(uuids) - _UUID_PREVIEW_LIMIT} more"]))
        node.setExpanded(not collapsed and 0 < len(uuids) <= 12)

    def _conflict_node(self, parent, plan):
        conflicts = plan.conflicts
        node = QTreeWidgetItem(["Conflicts", str(len(conflicts)), ""])
        parent.addChild(node)
        for c in conflicts[:_UUID_PREVIEW_LIMIT]:
            item = QTreeWidgetItem([c.uuid, "", c.type])
            node.addChild(item)
            self._add_conflict_detail(item, c)
            # Defer the combo until the item is attached to the tree.
            key = f"{plan.layer}\x1f{c.uuid}"
            c.resolution = c.default_resolution
            self._conflict_widgets[key] = (c, item)
        if len(conflicts) > _UUID_PREVIEW_LIMIT:
            node.addChild(QTreeWidgetItem(
                ["", "", f"… and {len(conflicts) - _UUID_PREVIEW_LIMIT} more "
                 "(resolve the rest after applying these)"]))
        node.setExpanded(bool(conflicts))

    def _add_conflict_detail(self, item, c):
        """Field-level child rows: which field clashes and the rival values."""
        for fname in c.hard_fields:
            vals = c.field_values.get(fname, {})
            item.addChild(QTreeWidgetItem(
                [f"  ⚑ {fname}", "clash",
                 f"working='{vals.get('working', '')}'  vs  "
                 f"master='{vals.get('master', '')}'"]))
        for fname in c.work_fields:
            item.addChild(QTreeWidgetItem(
                [f"  {fname}", "working-only edit", ""]))
        for fname in c.master_fields:
            item.addChild(QTreeWidgetItem(
                [f"  {fname}", "master-only edit", ""]))
        if c.geom_conflict:
            item.addChild(QTreeWidgetItem(
                ["  geometry", "clash", "edited on both sides"]))
        if not (c.hard_fields or c.work_fields or c.master_fields):
            item.addChild(QTreeWidgetItem(["", "", c.reason]))

    def _attach_conflict_widgets(self):
        for key, (c, item) in self._conflict_widgets.items():
            combo = QComboBox()
            for res, label in _RES_LABELS:
                if res == rc.RES_FIELD_MERGE and c.merge is None:
                    continue          # field-merge needs a field-level merge
                combo.addItem(label, res)
            idx = combo.findData(c.effective_resolution())
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.currentIndexChanged.connect(
                lambda _i, cc=c, cb=combo: self._on_resolution_changed(cc, cb))
            self.tree.setItemWidget(item, 1, combo)

    def _on_resolution_changed(self, conflict, combo):
        conflict.resolution = combo.currentData()
        self._refresh_apply_enabled()

    def _refresh_apply_enabled(self):
        plans = (self.build or {}).get("plans", [])
        applicable = any(p.has_applicable_changes() for p in plans)
        self.apply_btn.setEnabled(applicable)

    def _lineage_node(self, parent, label, groups, kind):
        node = QTreeWidgetItem([label, str(len(groups)), ""])
        parent.addChild(node)
        for g in groups:
            if kind == "split":
                detail = (f"parent {g.parent_uuid} → {len(g.child_uuids)} "
                          f"children ({int(g.cover_frac * 100)}% covered)")
            else:
                detail = (f"{len(g.parent_uuids)} parents → {g.survivor_uuid} "
                          f"({int(g.cover_frac * 100)}% covered)")
            item = QTreeWidgetItem(["accept", "", detail])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked)   # default-accept (passed threshold)
            node.addChild(item)
            self._lineage_items.append((g, item))
        node.setExpanded(bool(groups))

    def _sync_lineage_acceptance(self):
        for g, item in self._lineage_items:
            g.accepted = (item.checkState(0) == Qt.Checked)

    def _apply(self):
        if not self.build:
            return
        plans = self.build.get("plans", [])
        unresolved = sum(1 for p in plans for c in p.conflicts
                         if c.effective_resolution() == rc.RES_SKIP)
        resolved = sum(1 for p in plans for c in p.conflicts
                       if c.effective_resolution() != rc.RES_SKIP)
        auto = sum(len(p.auto_merges) for p in plans)
        self._sync_lineage_acceptance()
        splits = sum(1 for g, _ in self._lineage_items
                     if getattr(g, "accepted", True) and hasattr(g, "child_uuids"))
        merges = sum(1 for g, _ in self._lineage_items
                     if getattr(g, "accepted", True) and hasattr(g, "parent_uuids"))

        confirm = ("Apply to the master?\n\n"
                   f"Auto-merged disjoint edits: {auto}\n"
                   f"Conflicts resolved (will apply): {resolved}\n"
                   f"Conflicts skipped (re-surface next sync): {unresolved}\n"
                   f"Splits accepted: {splits}   Merges accepted: {merges}")
        if QMessageBox.question(self, "Apply reconcile", confirm,
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self._run_apply(force_lock=False)

    def _run_apply(self, force_lock):
        mapper = self.mapper_edit.text().strip()
        self.apply_btn.setEnabled(False)
        self._sync_lineage_acceptance()
        try:
            result = engine.apply_plans(
                self.master_gpkg, self.template_gpkg, self.build,
                mapper=mapper, force_lock=force_lock,
                progress_cb=self._on_progress)
            t = result["totals"]

            if result.get("aborted"):
                self._handle_abort(result)
                return

            if result.get("ok"):
                self._reload_master_layers()
                extra = ""
                if result.get("unresolved_conflicts"):
                    extra += (f"\n{result['unresolved_conflicts']} conflict(s) "
                              "left unresolved — they will re-appear next sync.")
                if result.get("tombstones_written"):
                    extra += (f"\n{result['tombstones_written']} deleted "
                              "feature(s) saved as recoverable tombstones.")
                QMessageBox.information(
                    self, "Reconcile",
                    f"Applied {t['inserted']} adds, {t['updated']} updates, "
                    f"{t['deleted']} deletes.\nBatch: {result['batch_id']}{extra}"
                    "\n\nThe base snapshot has been advanced — re-syncing this "
                    "template will apply further edits, not lose them.")
                self._reset_preview()
            else:
                QMessageBox.warning(
                    self, "Reconcile",
                    "Reconcile completed with errors (failed layers kept their "
                    "previous base for retry):\n"
                    + "\n".join(result.get("errors", []))
                    + f"\n\nApplied: {t}")
                self.apply_btn.setEnabled(True)
        except Exception as exc:
            QgsMessageLog.logMessage(f"reconcile apply failed: {exc}",
                                     "Linear Geoscience", Qgis.Critical)
            QMessageBox.critical(self, "Reconcile", f"Apply failed:\n{exc}")
            self.apply_btn.setEnabled(True)
        finally:
            self.progress.setValue(0)
            self.status.setText("Ready")

    def _handle_abort(self, result):
        """Version-guard / lock aborts: offer rebuild or override."""
        if result.get("lock_holder") is not None:
            holder = result["lock_holder"]
            who = holder.get("mapper") or "another user"
            since = holder.get("acquired_utc") or "?"
            override = QMessageBox.question(
                self, "Reconcile locked",
                f"A reconcile is already in progress ({who}, since {since}).\n\n"
                "Override the lock and apply anyway? Only do this if you are "
                "sure no one else is mid-reconcile.",
                QMessageBox.Yes | QMessageBox.No)
            if override == QMessageBox.Yes:
                self._run_apply(force_lock=True)
            else:
                self.apply_btn.setEnabled(True)
            return
        # Otherwise the master moved since the preview was built.
        QMessageBox.warning(
            self, "Reconcile out of date",
            "\n".join(result.get("errors", []))
            + "\n\nClick 'Build preview' again to refresh, then apply.")
        self._reset_preview()

    def _reload_master_layers(self):
        """Refresh any loaded master layers so the map reflects the merge."""
        try:
            from qgis.core import QgsProject
            for lyr in QgsProject.instance().mapLayers().values():
                src = lyr.source() if hasattr(lyr, "source") else ""
                if self.master_gpkg and self.master_gpkg in src:
                    lyr.reload()
                    lyr.triggerRepaint()
        except Exception:
            pass


def run_reconcile_tool_dialog(iface):
    """Entry point used by mainplugin.py."""
    parent = iface.mainWindow() if iface else None
    dlg = ReconcileDialog(iface, parent)
    dlg.setAttribute(Qt.WA_DeleteOnClose)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg
