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
    QMessageBox, QApplication, QWidget)

from qgis.core import QgsMessageLog, Qgis

try:
    from . import engine
    from . import migrate
    from . import checkout
except ImportError:  # pragma: no cover
    from script_adddata.reconcile import engine, migrate, checkout

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
        self.tree.setHeaderLabels(["Layer / operation", "Count", "Detail"])
        self.tree.setColumnWidth(0, 320)
        pvl.addWidget(self.tree)

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
        plans = build.get("plans", [])
        tot = {"inserts": 0, "updates": 0, "deletes": 0, "conflicts": 0,
               "skipped": 0}

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
            self._conflict_node(top, plan.conflicts)
            self._op_node(top, "Skipped / no-op",
                          [u for u, _ in plan.skipped], collapsed=True)
            top.setExpanded(True)

        missing = build.get("missing_layers", [])
        parts = [f"{tot['inserts']} adds", f"{tot['updates']} updates",
                 f"{tot['deletes']} deletes", f"{tot['conflicts']} conflicts"]
        msg = "Preview: " + ", ".join(parts) + "."
        if tot["conflicts"]:
            msg += (" Conflicts are shown but NOT applied in this version — "
                    "they are left for manual handling.")
        if missing:
            msg += (" Layers not in master (use Append to create first): "
                    + ", ".join(missing) + ".")
        self.summary.setText(msg)

        has_clean = (tot["inserts"] + tot["updates"] + tot["deletes"]) > 0
        self.apply_btn.setEnabled(has_clean)

    def _op_node(self, parent, label, uuids, collapsed=False):
        node = QTreeWidgetItem([label, str(len(uuids)), ""])
        parent.addChild(node)
        for u in uuids[:_UUID_PREVIEW_LIMIT]:
            node.addChild(QTreeWidgetItem(["", "", u]))
        if len(uuids) > _UUID_PREVIEW_LIMIT:
            node.addChild(QTreeWidgetItem(
                ["", "", f"… and {len(uuids) - _UUID_PREVIEW_LIMIT} more"]))
        node.setExpanded(not collapsed and 0 < len(uuids) <= 12)

    def _conflict_node(self, parent, conflicts):
        node = QTreeWidgetItem(["Conflicts (not applied)",
                                str(len(conflicts)), ""])
        parent.addChild(node)
        for c in conflicts[:_UUID_PREVIEW_LIMIT]:
            node.addChild(QTreeWidgetItem(["", c.type, f"{c.uuid} — {c.reason}"]))
        node.setExpanded(bool(conflicts))

    def _apply(self):
        if not self.build:
            return
        plans = self.build.get("plans", [])
        n_conflicts = sum(len(p.conflicts) for p in plans)
        mapper = self.mapper_edit.text().strip()

        confirm = (f"Apply clean changes to the master?\n\n"
                   f"Conflicts left for manual handling: {n_conflicts}")
        if QMessageBox.question(self, "Apply reconcile", confirm,
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        self.apply_btn.setEnabled(False)
        try:
            result = engine.apply_plans(
                self.master_gpkg, self.template_gpkg, self.build,
                mapper=mapper, progress_cb=self._on_progress)
            t = result["totals"]
            if result.get("ok"):
                self._reload_master_layers()
                QMessageBox.information(
                    self, "Reconcile",
                    f"Applied {t['inserted']} adds, {t['updated']} updates, "
                    f"{t['deleted']} deletes.\nBatch: {result['batch_id']}\n\n"
                    "The base snapshot has been advanced — re-syncing this "
                    "template will apply further edits, not lose them.")
                self._reset_preview()
            else:
                QMessageBox.warning(
                    self, "Reconcile",
                    "Reconcile did not complete cleanly (no base advance):\n"
                    + "\n".join(result.get("errors", []))
                    + f"\n\nApplied so far: {t}")
                self.apply_btn.setEnabled(True)
        except Exception as exc:
            QgsMessageLog.logMessage(f"reconcile apply failed: {exc}",
                                     "Linear Geoscience", Qgis.Critical)
            QMessageBox.critical(self, "Reconcile", f"Apply failed:\n{exc}")
            self.apply_btn.setEnabled(True)
        finally:
            self.progress.setValue(0)
            self.status.setText("Ready")

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
