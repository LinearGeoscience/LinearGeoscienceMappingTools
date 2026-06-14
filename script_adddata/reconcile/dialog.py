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
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFileDialog, QGroupBox, QProgressBar, QTreeWidget, QTreeWidgetItem,
    QMessageBox, QApplication, QWidget, QComboBox)

from qgis.core import (QgsMessageLog, Qgis, QgsGeometry, QgsRectangle,
                       QgsVectorLayer, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsProject)

# Flash colours: the template (working) version vs the master version.
_FLASH_TEMPLATE = QColor(255, 170, 0)   # amber
_FLASH_MASTER = QColor(110, 110, 110)   # grey

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
        self._template_prepared = False

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

        # --- Prepare field data (hardcode the working template) ---
        prep = QGroupBox("Prepare field data")
        try:
            prep.setStyleSheet(group_box_style())
        except Exception:
            pass
        prl = QVBoxLayout(prep)

        meta_row = QHBoxLayout()
        meta_row.addWidget(QLabel("Project ID:"))
        self.project_id_edit = QLineEdit()
        self.project_id_edit.setPlaceholderText("e.g. P12345")
        meta_row.addWidget(self.project_id_edit, 1)
        meta_row.addWidget(QLabel("Mapped scale:"))
        self.mapped_scale_edit = QLineEdit()
        self.mapped_scale_edit.setPlaceholderText("e.g. 1:2500")
        meta_row.addWidget(self.mapped_scale_edit, 1)
        prl.addLayout(meta_row)

        prep_row = QHBoxLayout()
        self.hardcode_btn = QPushButton("Hardcode / prepare working template")
        self.hardcode_btn.clicked.connect(self._run_hardcode)
        self._style(self.hardcode_btn, primary=False)
        prep_row.addWidget(self.hardcode_btn)
        prep_row.addStretch()
        prl.addLayout(prep_row)

        self.prep_status = QLabel(
            "Fills UUIDs, legends, coordinates and lgs_* columns in the "
            "template (empty cells only). Run before building the preview.")
        self.prep_status.setWordWrap(True)
        prl.addWidget(self.prep_status)
        layout.addWidget(prep)

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
        # Click a feature row -> zoom + flash it on the map canvas.
        self.tree.itemClicked.connect(self._on_tree_clicked)
        self._crs_cache = {}
        flash_hint = QLabel(
            "Tip: click a feature to zoom and flash it on the map — "
            "<b><span style='color:#ffaa00'>amber = template version</span></b>, "
            "<b><span style='color:#6e6e6e'>grey = master version</span></b>.")
        flash_hint.setWordWrap(True)
        pvl.addWidget(flash_hint)
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
            self._prefill_metadata()
            self._reset_preview()

    def _pick_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select working template GeoPackage", "", "GeoPackage (*.gpkg)")
        if path:
            self.template_gpkg = path
            self.template_edit.setText(path)
            self._template_prepared = False
            self._prefill_mapper()
            self._prefill_metadata()
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

    def _prefill_metadata(self):
        """Prefill Project ID / Mapped scale from the master's features."""
        if not (self.master_gpkg and os.path.exists(self.master_gpkg)):
            return
        if (self.project_id_edit.text().strip()
                and self.mapped_scale_edit.text().strip()):
            return
        try:
            pid, scale = self._read_master_metadata()
        except Exception:
            return
        if pid and not self.project_id_edit.text().strip():
            self.project_id_edit.setText(pid)
        if scale and not self.mapped_scale_edit.text().strip():
            self.mapped_scale_edit.setText(scale)

    def _read_master_metadata(self):
        """First non-empty (ProjectID, MappedScale) across the master layers."""
        from .migrate import LGS_LAYERS

        def _clean(value):
            if value is None:
                return None
            text = str(value).strip()
            return text if text and text != "NULL" else None

        pid = scale = None
        for name in LGS_LAYERS:
            lyr = QgsVectorLayer(f"{self.master_gpkg}|layername={name}",
                                 name, "ogr")
            if not lyr.isValid():
                continue
            names = [f.name() for f in lyr.fields()]
            has_pid = "ProjectID" in names
            has_scale = "MappedScale" in names
            if not (has_pid or has_scale):
                continue
            for i, feat in enumerate(lyr.getFeatures()):
                if i > 2000:
                    break
                if pid is None and has_pid:
                    pid = _clean(feat["ProjectID"])
                if scale is None and has_scale:
                    scale = _clean(feat["MappedScale"])
                if pid and scale:
                    break
            if pid and scale:
                break
        return pid, scale

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

    def _run_hardcode(self):
        """Hardcode the working template in place (empty-only) before preview."""
        if not self._require_paths():
            return
        try:
            from ...hardcode_data.runner import hardcode_geopackage
        except Exception:  # pragma: no cover - standalone import fallback
            from hardcode_data.runner import hardcode_geopackage

        project_id = self.project_id_edit.text().strip()
        mapped_scale = self.mapped_scale_edit.text().strip()
        if not project_id or not mapped_scale:
            if QMessageBox.question(
                    self, "Prepare field data",
                    "Project ID and/or Mapped scale are blank, so those "
                    "standard fields won't be filled. UUIDs, legends and "
                    "coordinates will still be prepared.\n\nContinue?",
                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return

        self.hardcode_btn.setEnabled(False)
        try:
            report = hardcode_geopackage(
                self.template_gpkg, project_id=project_id,
                mapped_scale=mapped_scale,
                lookup_sources=[self.template_gpkg, self.master_gpkg],
                progress_cb=self._on_progress)
        except Exception as exc:
            QgsMessageLog.logMessage(f"reconcile hardcode failed: {exc}",
                                     "Linear Geoscience", Qgis.Critical)
            QMessageBox.critical(self, "Prepare field data",
                                 f"Preparation failed:\n{exc}")
            return
        finally:
            self.hardcode_btn.setEnabled(True)
            self.progress.setValue(0)
            self.status.setText("Ready")

        self._template_prepared = True
        self._show_hardcode_summary(report)
        # The template changed on disk; any prior preview is now stale.
        self._reset_preview()

    def _show_hardcode_summary(self, report):
        layers = report.get("layers", {})
        totals = report.get("totals", {})
        lines = []
        for name, info in layers.items():
            if not info.get("present"):
                continue
            bits = [f"{info.get('applied', 0)} cells filled"]
            if info.get("uuids_filled"):
                bits.append(f"{info['uuids_filled']} UUIDs")
            if info.get("legend_skipped"):
                bits.append(f"legend skipped ({info['legend_skipped']})")
            lines.append(f"• {name}: " + ", ".join(bits))

        msg = ("Prepared the working template (empty cells only).\n\n"
               f"Total cells filled: {totals.get('applied', 0)}; "
               f"UUIDs backfilled: {totals.get('uuids_filled', 0)}.\n\n"
               + "\n".join(lines))

        missing = sorted({c for info in layers.values()
                          for c in info.get("missing_codes", [])})
        if missing:
            shown = ", ".join(missing[:20])
            extra = (f" … (+{len(missing) - 20} more)"
                     if len(missing) > 20 else "")
            msg += ("\n\n⚠ Legend codes with no lookup entry (their Legend/"
                    "Description was left blank): " + shown + extra
                    + "\nAdd them to the lookup table and re-run prepare.")

        dups = sorted({d for info in layers.values()
                       for d in info.get("duplicate_uuids", [])})
        if dups:
            msg += (f"\n\n⚠ {len(dups)} duplicate UUID value(s) found (left "
                    "unchanged — fix before applying the reconcile).")

        if report.get("errors"):
            msg += "\n\nErrors:\n" + "\n".join(report["errors"])

        if missing or dups or report.get("errors"):
            QMessageBox.warning(self, "Prepare field data", msg)
        else:
            QMessageBox.information(self, "Prepare field data", msg)

        status = (f"Prepared: {totals.get('applied', 0)} cells filled, "
                  f"{totals.get('uuids_filled', 0)} UUIDs backfilled.")
        if missing:
            status += f"  ⚠ {len(missing)} missing legend code(s)."
        self.prep_status.setText(status)

    def _confirm_prepare(self):
        """Offer to hardcode before previewing. Returns True to continue."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Prepare field data first?")
        box.setText(
            "The working template hasn't been hardcoded yet. Preparing it "
            "fills UUIDs, legends and coordinates so features reconcile "
            "cleanly instead of as blanking conflicts.")
        prep_btn = box.addButton("Prepare && continue", QMessageBox.AcceptRole)
        box.addButton("Build without preparing", QMessageBox.DestructiveRole)
        cancel_btn = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(prep_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel_btn:
            return False
        if clicked is prep_btn:
            self._run_hardcode()
            # Only proceed if preparation actually succeeded.
            return self._template_prepared
        return True  # "Build without preparing"

    def _build_preview(self):
        if not self._require_paths():
            return
        if not self._template_prepared and not self._confirm_prepare():
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

            self._op_node(top, "Adds", [o.uuid for o in plan.clean_inserts],
                          layer=plan.layer)
            self._op_node(top, "Updates", [o.uuid for o in plan.clean_updates],
                          layer=plan.layer)
            self._op_node(top, "Deletes", [o.uuid for o in plan.clean_deletes],
                          layer=plan.layer)
            self._op_node(top, "Auto-merged (disjoint edits)",
                          [o.uuid for o in plan.auto_merges], layer=plan.layer)
            self._conflict_node(top, plan)
            self._lineage_node(top, "Splits (1 → many)", plan.splits, "split")
            self._lineage_node(top, "Merges (many → 1)", plan.merges, "merge")
            self._op_node(top, "Skipped / no-op",
                          [u for u, _ in plan.skipped], collapsed=True,
                          layer=plan.layer)
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

    def _op_node(self, parent, label, uuids, collapsed=False, layer=None):
        node = QTreeWidgetItem([label, str(len(uuids)), ""])
        parent.addChild(node)
        for u in uuids[:_UUID_PREVIEW_LIMIT]:
            leaf = QTreeWidgetItem(["", "", u])
            if layer is not None:
                leaf.setData(0, Qt.UserRole, ("feature", layer, u))
            node.addChild(leaf)
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
            item.setData(0, Qt.UserRole, ("feature", plan.layer, c.uuid))
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
            if kind == "split":
                item.setData(0, Qt.UserRole,
                             ("split", g.layer, g.parent_uuid,
                              list(g.child_uuids)))
            else:
                item.setData(0, Qt.UserRole,
                             ("merge", g.layer, g.survivor_uuid,
                              list(g.parent_uuids)))
            node.addChild(item)
            self._lineage_items.append((g, item))
        node.setExpanded(bool(groups))

    def _sync_lineage_acceptance(self):
        for g, item in self._lineage_items:
            g.accepted = (item.checkState(0) == Qt.Checked)

    # --------------------------------------------------------------- map flash
    def _on_tree_clicked(self, item, column):
        """Zoom + flash the clicked feature(s): template (amber) vs master (grey)."""
        data = item.data(0, Qt.UserRole)
        if not data or not self.build or self.iface is None:
            return
        kind = data[0]
        captures = self.build.get("captures") or {}
        master_captures = self.build.get("master_captures") or {}
        template_geoms, master_geoms, layer = [], [], None
        try:
            if kind == "feature":
                _, layer, uuid = data
                wg = self._geom(captures, layer, uuid)
                mg = self._geom(master_captures, layer, uuid)
                if wg:
                    template_geoms.append(wg)
                if mg:
                    master_geoms.append(mg)
            elif kind == "split":
                _, layer, parent, children = data
                pg = self._geom(master_captures, layer, parent)
                if pg:
                    master_geoms.append(pg)
                template_geoms += [g for g in
                                   (self._geom(captures, layer, c) for c in children)
                                   if g]
            elif kind == "merge":
                _, layer, survivor, parents = data
                sg = self._geom(captures, layer, survivor)
                if sg:
                    template_geoms.append(sg)
                master_geoms += [g for g in
                                 (self._geom(master_captures, layer, p) for p in parents)
                                 if g]
            else:
                return
        except Exception as exc:  # pragma: no cover - defensive UI path
            QgsMessageLog.logMessage(f"reconcile flash lookup failed: {exc}",
                                     "Linear Geoscience", Qgis.Warning)
            return

        if not (template_geoms or master_geoms):
            self.status.setText("No geometry to show for this feature "
                                "(non-spatial or empty).")
            return
        self._zoom_and_flash(layer, template_geoms, master_geoms)

    def _geom(self, captures, layer, uuid):
        """Build a QgsGeometry (master CRS) from a captured payload, or None."""
        payload = (captures.get(layer) or {}).get(uuid)
        wkb = getattr(payload, "wkb", None) if payload is not None else None
        if not wkb:
            return None
        g = QgsGeometry()
        g.fromWkb(wkb)
        return g if (not g.isNull() and not g.isEmpty()) else None

    def _layer_crs(self, layer):
        """CRS of a master layer (cached). Captured geometries are in this CRS."""
        if layer in self._crs_cache:
            return self._crs_cache[layer]
        crs = None
        try:
            lyr = QgsVectorLayer(f"{self.master_gpkg}|layername={layer}",
                                 layer, "ogr")
            if lyr.isValid():
                crs = lyr.crs()
        except Exception:
            crs = None
        self._crs_cache[layer] = crs
        return crs

    def _zoom_and_flash(self, layer, template_geoms, master_geoms):
        canvas = self.iface.mapCanvas()
        if canvas is None:
            return
        src_crs = self._layer_crs(layer) or QgsCoordinateReferenceSystem()
        dst_crs = canvas.mapSettings().destinationCrs()

        # Union extent (in source CRS), transformed to the canvas CRS, with margin.
        rect = QgsRectangle()
        rect.setMinimal()
        for g in template_geoms + master_geoms:
            rect.combineExtentWith(g.boundingBox())
        try:
            if src_crs.isValid() and dst_crs.isValid() and src_crs != dst_crs:
                xform = QgsCoordinateTransform(src_crs, dst_crs,
                                               QgsProject.instance())
                rect = xform.transformBoundingBox(rect)
        except Exception:
            pass
        if not rect.isEmpty():
            rect.scale(1.6)            # breathing room around the feature
            canvas.setExtent(rect)
            canvas.refresh()

        # Flash: template amber, master grey (flashGeometries transforms the CRS).
        try:
            clear = QColor(0, 0, 0, 0)
            if template_geoms:
                canvas.flashGeometries(template_geoms, src_crs,
                                       _FLASH_TEMPLATE, clear, 3, 650)
            if master_geoms:
                canvas.flashGeometries(master_geoms, src_crs,
                                       _FLASH_MASTER, clear, 3, 650)
        except Exception as exc:  # pragma: no cover - some canvas states
            QgsMessageLog.logMessage(f"reconcile flash failed: {exc}",
                                     "Linear Geoscience", Qgis.Warning)
        self.status.setText(
            f"{layer}: flashed {len(template_geoms)} template + "
            f"{len(master_geoms)} master geometr"
            f"{'y' if len(template_geoms)+len(master_geoms) == 1 else 'ies'}.")

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
