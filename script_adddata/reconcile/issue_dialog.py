#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Issue Field Copy dialog: hand a mapper a properly-stamped working copy.

Thin UI over issue.issue_copy (which does the copy/blank/clip + embedded
stamping). Layout and task plumbing mirror ReconcileDialog: theme styles,
run_in_task background execution, an owner-retained reference so slots
survive garbage collection.

The clip AOI is zero-config: grab the current canvas extent, or the union
of the selected features of the active layer - both converted to the
master's CRS on the main thread.
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFileDialog, QGroupBox, QProgressBar, QMessageBox, QRadioButton,
    QButtonGroup)

from qgis.core import (QgsMessageLog, Qgis, QgsGeometry, QgsProject,
                       QgsCoordinateTransform)

try:
    from . import engine
    from . import migrate
    from . import issue
except ImportError:  # pragma: no cover
    from script_adddata.reconcile import engine, migrate, issue

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

try:
    from ...lgs_tasks import run_in_task
except Exception:  # pragma: no cover - standalone fallback
    from lgs_tasks import run_in_task

_BANNER_ERROR = ("QLabel { background: #7a1f1f; color: white; padding: 6px; "
                 "border-radius: 3px; }")


class IssueCopyDialog(QDialog):
    def __init__(self, iface, parent=None, master=None, mapper=None):
        super().__init__(parent)
        self.iface = iface
        self.master_gpkg = master
        self.area_wkt = ""
        self._task = None
        self._dest_touched = False

        self.setWindowTitle("Issue Field Copy")
        self.resize(640, 480)
        try:
            self.setStyleSheet(dialog_style())
        except Exception:
            pass

        layout = QVBoxLayout(self)
        intro = QLabel(
            "<b>Issue a working copy of the master</b> for field mapping. "
            "The copy is stamped with a checkout identity and base snapshot "
            "so it reconciles back cleanly - deletes, splits and merges "
            "included. Re-issue after a master clean-up so mappers continue "
            "on the current state.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # --- Source ---
        src = QGroupBox("Source")
        try:
            src.setStyleSheet(group_box_style())
        except Exception:
            pass
        sl = QVBoxLayout(src)
        master_row = QHBoxLayout()
        master_row.addWidget(QLabel("Master GeoPackage:"))
        self.master_edit = QLineEdit()
        self.master_edit.setReadOnly(True)
        master_row.addWidget(self.master_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_master)
        self._style(browse, primary=False)
        master_row.addWidget(browse)
        sl.addLayout(master_row)

        self.migrate_banner = QLabel()
        self.migrate_banner.setWordWrap(True)
        self.migrate_banner.setStyleSheet(_BANNER_ERROR)
        self.migrate_banner.setVisible(False)
        migrate_row = QHBoxLayout()
        migrate_row.addWidget(self.migrate_banner, 1)
        self.migrate_btn = QPushButton("Migrate now")
        self.migrate_btn.clicked.connect(self._run_migrate)
        self.migrate_btn.setVisible(False)
        self._style(self.migrate_btn, primary=False)
        migrate_row.addWidget(self.migrate_btn)
        sl.addLayout(migrate_row)

        mapper_row = QHBoxLayout()
        mapper_row.addWidget(QLabel("Mapper ID:"))
        self.mapper_edit = QLineEdit()
        self.mapper_edit.setPlaceholderText("e.g. HW (who gets this copy)")
        if mapper:
            self.mapper_edit.setText(mapper)
        self.mapper_edit.textChanged.connect(self._suggest_destination)
        mapper_row.addWidget(self.mapper_edit)
        sl.addLayout(mapper_row)
        layout.addWidget(src)

        # --- What the copy contains ---
        what = QGroupBox("What the copy contains")
        try:
            what.setStyleSheet(group_box_style())
        except Exception:
            pass
        wl = QVBoxLayout(what)
        self.mode_group = QButtonGroup(self)
        self.full_radio = QRadioButton(
            "Full copy of the master (mapper sees all existing mapping)")
        self.blank_radio = QRadioButton(
            "Blank template (schema, styles and lookups; no features)")
        self.clip_radio = QRadioButton(
            "Clipped area of the master (this mapper's area only)")
        self.full_radio.setChecked(True)
        for i, radio in enumerate(
                (self.full_radio, self.blank_radio, self.clip_radio)):
            self.mode_group.addButton(radio, i)
            wl.addWidget(radio)
            radio.toggled.connect(self._mode_changed)

        clip_row = QHBoxLayout()
        clip_row.addSpacing(24)
        self.canvas_btn = QPushButton("Use current canvas extent")
        self.canvas_btn.clicked.connect(self._aoi_from_canvas)
        self._style(self.canvas_btn, primary=False)
        clip_row.addWidget(self.canvas_btn)
        self.selection_btn = QPushButton("Use selected feature(s)")
        self.selection_btn.setToolTip(
            "Union of the selected features of the active layer")
        self.selection_btn.clicked.connect(self._aoi_from_selection)
        self._style(self.selection_btn, primary=False)
        clip_row.addWidget(self.selection_btn)
        clip_row.addStretch()
        wl.addLayout(clip_row)
        self.aoi_status = QLabel("No clip area set.")
        self.aoi_status.setWordWrap(True)
        wl.addWidget(self.aoi_status)
        layout.addWidget(what)

        # --- Destination ---
        dest = QGroupBox("Destination")
        try:
            dest.setStyleSheet(group_box_style())
        except Exception:
            pass
        dl = QHBoxLayout(dest)
        dl.addWidget(QLabel("New working copy:"))
        self.dest_edit = QLineEdit()
        self.dest_edit.textEdited.connect(
            lambda _t: setattr(self, "_dest_touched", True))
        dl.addWidget(self.dest_edit, 1)
        dest_btn = QPushButton("Browse…")
        dest_btn.clicked.connect(self._pick_destination)
        self._style(dest_btn, primary=False)
        dl.addWidget(dest_btn)
        layout.addWidget(dest)

        # --- Progress + actions ---
        prog_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        prog_row.addWidget(self.progress, 1)
        layout.addLayout(prog_row)
        self.status = QLabel("Ready")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        actions = QHBoxLayout()
        actions.addStretch()
        self.issue_btn = QPushButton("Issue copy")
        self.issue_btn.clicked.connect(self._issue)
        self._style(self.issue_btn, primary=True)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        self._style(close_btn, primary=False)
        actions.addWidget(self.issue_btn)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        self._mode_changed()
        if self.master_gpkg:
            self.master_edit.setText(self.master_gpkg)
            self._check_migration()
            self._suggest_destination()

    # ----------------------------------------------------------------- helpers
    def _style(self, btn, primary=True):
        try:
            btn.setStyleSheet(action_button_style(primary=primary))
        except Exception:
            pass

    def _mode(self):
        if self.blank_radio.isChecked():
            return issue.MODE_BLANK
        if self.clip_radio.isChecked():
            return issue.MODE_CLIP
        return issue.MODE_FULL

    def _mode_changed(self, _checked=None):
        clip = self.clip_radio.isChecked()
        for w in (self.canvas_btn, self.selection_btn, self.aoi_status):
            w.setEnabled(clip)

    def _pick_master(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select master GeoPackage", "", "GeoPackage (*.gpkg)")
        if path:
            self.master_gpkg = path
            self.master_edit.setText(path)
            self._check_migration()
            self._suggest_destination()

    def _pick_destination(self):
        start = self.dest_edit.text().strip() or (
            os.path.dirname(self.master_gpkg) if self.master_gpkg else "")
        path, _ = QFileDialog.getSaveFileName(
            self, "New working copy", start, "GeoPackage (*.gpkg)")
        if path:
            if not path.lower().endswith(".gpkg"):
                path += ".gpkg"
            self.dest_edit.setText(path)
            self._dest_touched = True

    def _suggest_destination(self, _text=None):
        if self._dest_touched or not self.master_gpkg:
            return
        self.dest_edit.setText(issue.default_destination(
            self.master_gpkg, self.mapper_edit.text().strip()))

    def _check_migration(self):
        try:
            migrated = bool(
                migrate.migration_status(self.master_gpkg).get("migrated"))
        except Exception:
            migrated = True   # can't tell -> issue_copy re-checks anyway
        self.migrate_banner.setVisible(not migrated)
        self.migrate_btn.setVisible(not migrated)
        if not migrated:
            self.migrate_banner.setText(
                "⚠ This master has NOT been migrated for reconcile - a copy "
                "issued now could not be merged back. Migrate first "
                "(one-off, safe to re-run).")
        self.issue_btn.setEnabled(migrated)

    # ------------------------------------------------------------------- AOI
    def _master_crs(self):
        for name in migrate.LGS_LAYERS:
            lyr = engine._open(self.master_gpkg, name)
            if lyr is not None and lyr.crs().isValid():
                return lyr.crs()
        return None

    def _set_aoi(self, geom, source_crs, label):
        """Store an AOI geometry, transformed to the master CRS."""
        if not self.master_gpkg:
            QMessageBox.warning(self, "Issue Field Copy",
                                "Select a master GeoPackage first.")
            return
        mcrs = self._master_crs()
        try:
            if (mcrs is not None and source_crs is not None
                    and source_crs.isValid() and source_crs != mcrs):
                geom = QgsGeometry(geom)
                geom.transform(QgsCoordinateTransform(
                    source_crs, mcrs, QgsProject.instance()))
        except Exception as exc:
            QMessageBox.warning(self, "Issue Field Copy",
                                f"Could not transform the area: {exc}")
            return
        if geom is None or geom.isNull() or geom.isEmpty():
            QMessageBox.warning(self, "Issue Field Copy", "Empty area.")
            return
        self.area_wkt = geom.asWkt(3)
        self.aoi_status.setText(f"Clip area set from {label}.")

    def _aoi_from_canvas(self):
        if self.iface is None:
            return
        canvas = self.iface.mapCanvas()
        rect = canvas.extent()
        self._set_aoi(QgsGeometry.fromRect(rect),
                      canvas.mapSettings().destinationCrs(),
                      "the current canvas extent")

    def _aoi_from_selection(self):
        if self.iface is None:
            return
        layer = self.iface.activeLayer()
        feats = layer.selectedFeatures() if hasattr(
            layer, "selectedFeatures") else []
        geoms = [f.geometry() for f in feats
                 if f.geometry() is not None and not f.geometry().isNull()]
        if not geoms:
            QMessageBox.warning(
                self, "Issue Field Copy",
                "Select one or more features on the active layer first.")
            return
        union = QgsGeometry.unaryUnion(geoms)
        self._set_aoi(union, layer.crs(),
                      f"{len(geoms)} selected feature(s) of '{layer.name()}'")

    # ---------------------------------------------------------------- actions
    def _run_migrate(self):
        master = self.master_gpkg
        if not master:
            return
        self._busy(True, "Migrating master…")
        run_in_task("Migrate master GeoPackage",
                    lambda cb: migrate.run_migration(master, progress_cb=cb),
                    on_finished=self._migrate_done,
                    on_error=self._task_error, owner=self,
                    bar=self.progress, label=self.status)

    def _migrate_done(self, report):
        self._busy(False)
        if not report.get("ok"):
            QMessageBox.warning(
                self, "Issue Field Copy",
                "Migration finished with issues:\n"
                + "\n".join(report.get("errors", [])))
        self._check_migration()

    def _busy(self, busy, note=None):
        for w in (self.issue_btn, self.migrate_btn):
            w.setEnabled(not busy)
        if note:
            self.status.setText(note)
        elif not busy:
            self.status.setText("Ready")
            self.progress.setValue(0)
            self._check_migration()

    def _task_error(self, exc, tb):
        self._busy(False)
        QgsMessageLog.logMessage(f"Issue field copy failed: {tb}",
                                 "Linear Geoscience",
                                 Qgis.MessageLevel.Critical)
        QMessageBox.critical(self, "Issue Field Copy", f"Failed:\n{exc}")

    def _issue(self):
        master = self.master_gpkg
        dest = self.dest_edit.text().strip()
        mapper = self.mapper_edit.text().strip()
        mode = self._mode()
        if not master or not os.path.exists(master):
            QMessageBox.warning(self, "Issue Field Copy",
                                "Select a master GeoPackage.")
            return
        if not dest:
            QMessageBox.warning(self, "Issue Field Copy",
                                "Set a destination for the new copy.")
            return
        if mode == issue.MODE_CLIP and not self.area_wkt:
            QMessageBox.warning(self, "Issue Field Copy",
                                "Set a clip area (canvas extent or "
                                "selected features).")
            return
        if not mapper:
            if QMessageBox.question(
                    self, "Issue Field Copy",
                    "No Mapper ID set - the checkout will be anonymous "
                    "until its first reconcile. Continue?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No) \
                    != QMessageBox.StandardButton.Yes:
                return

        area = self.area_wkt if mode == issue.MODE_CLIP else ""
        ctx = QgsProject.instance().transformContext()
        self._busy(True, "Issuing copy…")
        run_in_task(
            "Issue field copy",
            lambda cb: issue.issue_copy(
                master, dest, mode=mode, mapper=mapper, area_wkt=area,
                progress_cb=cb, transform_context=ctx),
            on_finished=self._issue_done, on_error=self._task_error,
            owner=self, bar=self.progress, label=self.status)

    def _issue_done(self, result):
        self._busy(False)
        if result.get("ok"):
            counts = result.get("feature_counts", {})
            lines = [f"• {name}: {n} feature(s)"
                     for name, n in counts.items()]
            msg = (f"Issued {os.path.basename(result['dest_path'])} "
                   f"({result['mode']}).\n"
                   f"Checkout: {(result.get('checkout_id') or '')[:8]}…\n\n"
                   + "\n".join(lines))
            skipped = result.get("skipped_no_uuid", {})
            if skipped:
                total = sum(skipped.values())
                msg += (f"\n\n⚠ {total} feature(s) had no UUID and are NOT "
                        "in the base - run Verify/migrate master and "
                        "re-issue.")
            msg += ("\n\nHand this file to the mapper. It reconciles back "
                    "through Reconcile / Merge whenever they sync.")
            QMessageBox.information(self, "Issue Field Copy", msg)
            self._dest_touched = False
            self._suggest_destination()
        else:
            QMessageBox.warning(
                self, "Issue Field Copy",
                "Could not issue the copy:\n"
                + "\n".join(result.get("errors", [])))


def run_issue_dialog(iface, owner=None, master=None, mapper=None):
    """Entry point (owner-retained like run_reconcile_tool_dialog)."""
    existing = getattr(owner, "issue_dialog", None) if owner else None
    if existing is not None:
        try:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return existing
        except RuntimeError:
            owner.issue_dialog = None

    parent = iface.mainWindow() if iface else None
    dlg = IssueCopyDialog(iface, parent, master=master, mapper=mapper)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    if owner is not None:
        dlg.destroyed.connect(lambda: setattr(owner, "issue_dialog", None))
        owner.issue_dialog = dlg
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg
