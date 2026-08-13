"""
Z-filter controller: owns every setSubsetString call and all persistence.

UI-free — the dock calls in, results come back as report dicts and the dock
decides how to show them. Module-level helpers (active_z_filter_summary,
suspended_filters) work from project entries alone so full-table readers
(reconcile, append, exports) can guard themselves without the panel ever
having been opened this session.

Persisted state lives in two places:
- QgsProject custom entries (scope "LinearGeoscience", z_filter/...) — the
  desktop source of truth.
- Project variables (lgs_z_*) — mirrored for the QField sidecar plugin,
  which reads and updates them on the device.
"""

from collections import Counter
from contextlib import contextmanager

from qgis.core import (
    Qgis,
    QgsExpressionContextUtils,
    QgsFeatureRequest,
    QgsMessageLog,
    QgsProject,
)
from qgis.PyQt.QtCore import QObject

from .expression import (
    ELEVATION_FIELD,
    ENTRY_ENABLED,
    ENTRY_EXTRA_LAYERS,
    ENTRY_LAYER_CHECKED,
    ENTRY_LAYER_IDS,
    ENTRY_LEVEL,
    ENTRY_LEVELS,
    ENTRY_ORIG_SUBSET_PREFIX,
    ENTRY_RASTERS,
    ENTRY_SHOW_NULL,
    ENTRY_SLOT_IDS,
    ENTRY_STEP,
    ENTRY_TOLERANCE,
    SCOPE,
    VAR_ENABLED,
    VAR_EXTRA,
    VAR_LEVEL,
    VAR_LEVELS,
    VAR_RASTERS,
    VAR_SHOW_NULL,
    VAR_STEP,
    VAR_SUGGEST,
    VAR_TOLERANCE,
    clause_for_spec,
    combine,
    format_extra_layers,
    format_levels,
    format_number,
    format_rasters,
    format_suggestions,
    parse_extra_layers,
    parse_levels,
    parse_rasters,
    raster_in_windows,
    spec_field_names,
)
from .levels import range_vote, value_range
from . import auto_layers, detect


# Spec used when a caller passes a bare layer instead of a (layer, spec)
# target — the canonical mapping layers filter on Elevation.
DEFAULT_SPEC = {'mode': 'single', 'field': ELEVATION_FIELD}


def normalize_targets(items):
    """Promote bare layers to (layer, spec) targets; pass targets through.

    Deduplicated by layer id, first spec wins: an unmatched slot combo can
    land on a layer another slot already holds, and filtering it twice or
    counting its features twice in the scan both skew the result.
    """
    targets = []
    seen = set()
    for item in items or []:
        if isinstance(item, tuple):
            layer, spec = item
        else:
            layer, spec = item, DEFAULT_SPEC
        if layer is None:
            continue
        layer_id = layer.id()
        if layer_id in seen:
            continue
        seen.add(layer_id)
        targets.append((layer, spec or DEFAULT_SPEC))
    return targets


def _log(message, level=Qgis.MessageLevel.Info):
    QgsMessageLog.logMessage(message, 'Linear Geoscience', level)


def _stored_layer_ids(project):
    value, _ = project.readEntry(SCOPE, ENTRY_LAYER_IDS, "")
    return [lid for lid in value.split(',') if lid]


def _stored_original(project, layer_id):
    value, ok = project.readEntry(SCOPE, ENTRY_ORIG_SUBSET_PREFIX + layer_id, "")
    return value if ok else ""


def active_z_filter_summary(project=None):
    """Human-readable description of the persisted filter, or None if off.

    Reads project entries only, so it works without the panel being open —
    used by full-table readers (reconcile/append/export) to warn the user.
    """
    project = project or QgsProject.instance()
    enabled, _ = project.readBoolEntry(SCOPE, ENTRY_ENABLED, False)
    if not enabled:
        return None
    level, _ = project.readEntry(SCOPE, ENTRY_LEVEL, "?")
    tol, _ = project.readEntry(SCOPE, ENTRY_TOLERANCE, "?")
    count = len(_stored_layer_ids(project))
    return f"level {level} ± {tol} m on {count} layer(s)"


@contextmanager
def suspended_filters(project=None):
    """Temporarily restore original subset strings for the guarded block.

    Layers return to their pre-z-filter subsets on entry and get the filtered
    subset back on exit, whatever happens inside. No-op when the filter is
    off or layers are gone.
    """
    project = project or QgsProject.instance()
    reapply = []  # (layer, filtered subset to restore)
    enabled, _ = project.readBoolEntry(SCOPE, ENTRY_ENABLED, False)
    if enabled:
        for layer_id in _stored_layer_ids(project):
            layer = project.mapLayer(layer_id)
            if layer is None:
                continue
            original = _stored_original(project, layer_id)
            current = layer.subsetString() or ""
            if current != original:
                reapply.append((layer, current))
                layer.setSubsetString(original)
    try:
        yield
    finally:
        for layer, filtered in reapply:
            try:
                layer.setSubsetString(filtered)
            except RuntimeError:
                pass  # layer deleted inside the guarded block


class ZFilterController(QObject):
    """Applies/clears the elevation filter across the selected layers."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------
    def apply_filter(self, layers, level, tolerance, show_null):
        """Filter each target to level ± tolerance. Accepts bare layers or
        (layer, spec) targets (see normalize_targets). Returns a report dict:
        applied / skipped (name, reason) / errors (name, message)."""
        project = QgsProject.instance()
        report = {'applied': [], 'skipped': [], 'errors': []}
        applied_ids = []

        for layer, spec in normalize_targets(layers):
            fields = spec_field_names(spec)
            missing = [f for f in fields
                       if layer.fields().indexOf(f) == -1]
            if missing:
                report['skipped'].append(
                    (layer.name(),
                     'no ' + '/'.join(f'"{f}"' for f in missing) + ' field'))
                continue
            clause = clause_for_spec(spec, level, tolerance, show_null)
            if layer.isEditable():
                buf = layer.editBuffer()
                if buf and buf.isModified():
                    report['skipped'].append(
                        (layer.name(), 'unsaved edits — save first'))
                    continue
                # Clean session left open; close it so the provider filter
                # change is safe.
                layer.commitChanges()

            key = ENTRY_ORIG_SUBSET_PREFIX + layer.id()
            _, have_orig = project.readEntry(SCOPE, key, "")
            if not have_orig:
                # First application on this layer: remember what was there.
                project.writeEntry(SCOPE, key, layer.subsetString() or "")
            original = _stored_original(project, layer.id())

            if layer.setSubsetString(combine(original, clause)):
                layer.triggerRepaint()
                report['applied'].append(layer.name())
                applied_ids.append(layer.id())
            else:
                report['errors'].append(
                    (layer.name(), 'provider rejected the filter'))

        # Drop stored originals for layers no longer filtered (deselected).
        for layer_id in _stored_layer_ids(project):
            if layer_id not in applied_ids:
                self._restore_layer(project, layer_id)

        self._persist_state(project, applied_ids, level, tolerance, show_null,
                            enabled=bool(applied_ids))
        self._sync_raster_visibility(
            project, [(level, tolerance)] if applied_ids else None)
        if report['applied']:
            _log(f"Z filter applied ({format_number(level)} ± "
                 f"{format_number(tolerance)} m): {', '.join(report['applied'])}")
        return report

    def clear_filters(self):
        """Restore every filtered layer to its original subset string."""
        project = QgsProject.instance()
        restored = []
        for layer_id in _stored_layer_ids(project):
            name = self._restore_layer(project, layer_id)
            if name:
                restored.append(name)
        self._persist_state(project, [], None, None, None, enabled=False)
        self._sync_raster_visibility(project, None)
        if restored:
            _log(f"Z filter cleared: {', '.join(restored)}")
        return restored

    def scan_elevations(self, layers, feature_cap=250_000):
        """Count the elevation values across the targets (unfiltered view).

        Accepts bare layers or (layer, spec) targets. Filtered layers are
        temporarily restored to their original subset so every row is seen,
        then re-filtered. Layers whose feature count alone exceeds
        feature_cap are skipped whole and reported in 'truncated' (pass
        feature_cap=None for a manual, uncapped rescan).

        Each feature votes one elevation via levels.range_vote: flat
        features their value/midpoint, undulating survey strings the RL in
        their level name (or their midpoint), and declines abstain — those
        are counted in 'spanning' and stay out of the histogram so a
        mid-ramp value never becomes a level suggestion.

        Returns {
            'value_counts': {float: int},   # global, across all layers
            'value_labels': {float: {str: int}},  # level-name texts seen
            'per_layer': [{'name', 'total', 'with_elev', 'blank',
                           'spanning'}, ...],
            'with_elev': int, 'blank': int, 'total': int, 'spanning': int,
            'truncated': [layer names skipped],
            'skipped': [{'name', 'reason'}],   # layers the scan could not read
        }
        """
        value_counts = Counter()
        value_labels = {}
        per_layer = []
        truncated = []
        skipped = []
        with suspended_filters():
            for layer, spec in normalize_targets(layers):
                names = spec_field_names(spec)
                indexes = [layer.fields().indexOf(f) for f in names]
                if -1 in indexes:
                    missing = [f for f, i in zip(names, indexes) if i < 0]
                    skipped.append({
                        'name': layer.name(),
                        'reason': "no " + "/".join(missing) + " field"})
                    continue
                total = layer.featureCount()
                if feature_cap is not None and total > feature_cap:
                    truncated.append(layer.name())
                    continue
                # Level-name text field ("000 Level", "13/42"): the spec's
                # persisted choice, else detected on the fly so canonical
                # layers get labels zero-config too. Display-only — never
                # part of the filter clause. An empty-but-present key is
                # the user's explicit "(none)" — no fallback re-detection.
                label_field = (spec['label_field']
                               if 'label_field' in spec
                               else detect.match_label_field(
                                   auto_layers.string_field_names(layer)))
                label_idx = (layer.fields().indexOf(label_field)
                             if label_field else -1)
                request = QgsFeatureRequest()
                request.setFlags(Qgis.FeatureRequestFlag.NoGeometry)
                request.setSubsetOfAttributes(
                    indexes + ([label_idx] if label_idx >= 0 else []))
                with_elev = blank = spanning = 0
                try:
                    # Iterate the layer (not the provider) so edit-buffer
                    # values are counted the same way the filter sees them.
                    for feature in layer.getFeatures(request):
                        try:
                            values = [float(feature.attribute(idx))
                                      for idx in indexes]
                        except (TypeError, ValueError):
                            blank += 1  # NULL / non-numeric
                            continue
                        # The level name is read before the vote: it is an
                        # input to it, not just decoration.
                        text = ''
                        if label_idx >= 0:
                            raw = feature.attribute(label_idx)
                            text = '' if raw is None else str(raw).strip()
                            if text.upper() == 'NULL':
                                text = ''
                            text = text[:40]
                        key = range_vote(values[0], values[-1], text or None)
                        if key is None:
                            spanning += 1  # decline — abstains
                            continue
                        value_counts[key] += 1
                        with_elev += 1
                        if text:
                            bucket = value_labels.setdefault(key, {})
                            bucket[text] = bucket.get(text, 0) + 1
                except Exception as e:  # provider hiccup — skip this layer
                    _log(f"Z filter scan failed on {layer.name()}: {e}",
                         Qgis.MessageLevel.Warning)
                    skipped.append({'name': layer.name(),
                                    'reason': 'read failed'})
                    continue
                per_layer.append({'name': layer.name(), 'total': total,
                                  'with_elev': with_elev, 'blank': blank,
                                  'spanning': spanning})
        return {
            'value_counts': dict(value_counts),
            'value_labels': value_labels,
            'per_layer': per_layer,
            'with_elev': sum(entry['with_elev'] for entry in per_layer),
            'blank': sum(entry['blank'] for entry in per_layer),
            'total': sum(entry['total'] for entry in per_layer),
            'spanning': sum(entry['spanning'] for entry in per_layer),
            'truncated': truncated,
            'skipped': skipped,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def persisted_state(self):
        """Read the persisted panel state for restore-on-open/project-load."""
        project = QgsProject.instance()
        enabled, _ = project.readBoolEntry(SCOPE, ENTRY_ENABLED, False)
        level, _ = project.readEntry(SCOPE, ENTRY_LEVEL, "")
        # None (not a default) = never set; the dock auto-initializes the
        # width from the first scan only in that case (mirror of 'step').
        tolerance_text, _ = project.readEntry(SCOPE, ENTRY_TOLERANCE, "")
        try:
            tolerance = float(tolerance_text) if tolerance_text else None
        except ValueError:
            tolerance = None
        show_null, _ = project.readBoolEntry(SCOPE, ENTRY_SHOW_NULL, True)
        # None (not a default) = never set; the dock auto-initializes the
        # step from the first scan only in that case.
        step_text, _ = project.readEntry(SCOPE, ENTRY_STEP, "")
        try:
            step = float(step_text) if step_text else None
        except ValueError:
            step = None
        levels_csv, _ = project.readEntry(SCOPE, ENTRY_LEVELS, "")
        # Slot combos persist separately from the applied-layer set; fall
        # back to the old shared key for projects saved before the split.
        layer_ids, have_slots = project.readEntry(SCOPE, ENTRY_SLOT_IDS, "")
        if not have_slots:
            layer_ids, _ = project.readEntry(SCOPE, ENTRY_LAYER_IDS, "")
        checked, _ = project.readEntry(SCOPE, ENTRY_LAYER_CHECKED, "")
        extra_json, _ = project.readEntry(SCOPE, ENTRY_EXTRA_LAYERS, "")
        rasters_json, _ = project.readEntry(SCOPE, ENTRY_RASTERS, "")
        return {
            'enabled': enabled,
            'level': float(level) if level else None,
            'tolerance': tolerance,
            'step': step,
            'show_null': show_null,
            'levels': parse_levels(levels_csv),
            'layer_ids': [lid for lid in layer_ids.split(',') if lid],
            'layer_checked': [c == '1' for c in checked.split(',') if c],
            'extra_layers': parse_extra_layers(extra_json),
            'rasters': parse_rasters(rasters_json),
        }

    def persist_levels(self, levels):
        project = QgsProject.instance()
        project.writeEntry(SCOPE, ENTRY_LEVELS, format_levels(levels))
        QgsExpressionContextUtils.setProjectVariable(
            project, VAR_LEVELS, format_levels(levels))

    def persist_step(self, value):
        """Persist the stepper increment immediately (it never enters the
        clause, so it does not belong to _persist_state's apply-time write)."""
        project = QgsProject.instance()
        project.writeEntry(SCOPE, ENTRY_STEP, format_number(value))
        QgsExpressionContextUtils.setProjectVariable(
            project, VAR_STEP, format_number(value))

    def persist_tolerance(self, value):
        """Persist the slice width immediately: 'never set' vs 'user chose
        this' is what keeps rung clicks from clobbering a chosen width.
        (_persist_state's apply-time write remains, harmlessly redundant.)"""
        project = QgsProject.instance()
        project.writeEntry(SCOPE, ENTRY_TOLERANCE, format_number(value))
        QgsExpressionContextUtils.setProjectVariable(
            project, VAR_TOLERANCE, format_number(value))

    def persist_suggestions(self, suggestions, scan):
        """Bake the scan's suggestions into lgs_z_suggest for QField, whose
        device-side scan cannot always see the data. Never writes an empty
        bake (would clobber a good one with the failure mode this defends
        against) and skips the write when the payload is unchanged, so
        routine auto-scans do not dirty the project. Returns True when a
        write happened."""
        if not suggestions:
            return False
        summary = {'with_elev': scan.get('with_elev'),
                   'blank': scan.get('blank'),
                   'spanning': scan.get('spanning')}
        span = value_range(scan.get('value_counts') or {})
        if span:
            summary['min'], summary['max'] = span[0], span[1]
        payload = format_suggestions(suggestions, summary)
        project = QgsProject.instance()
        current = QgsExpressionContextUtils.projectScope(
            project).variable(VAR_SUGGEST)
        if (current or '') == payload:
            return False
        QgsExpressionContextUtils.setProjectVariable(
            project, VAR_SUGGEST, payload)
        return True

    def persist_layer_selection(self, layer_ids, checked_flags):
        project = QgsProject.instance()
        # ENTRY_LAYER_IDS is deliberately not written here — it now means
        # "currently filtered layers" and belongs to _persist_state.
        project.writeEntry(SCOPE, ENTRY_SLOT_IDS, ','.join(layer_ids))
        project.writeEntry(SCOPE, ENTRY_LAYER_CHECKED,
                           ','.join('1' if c else '0' for c in checked_flags))

    def persist_extra_layers(self, entries):
        """Persist the extra-layer specs (entry + lgs_z_extra mirror)."""
        project = QgsProject.instance()
        payload = format_extra_layers(entries)
        project.writeEntry(SCOPE, ENTRY_EXTRA_LAYERS, payload)
        QgsExpressionContextUtils.setProjectVariable(project, VAR_EXTRA,
                                                     payload)

    def persist_rasters(self, entries):
        """Persist the raster elevation ties (entry + lgs_z_rasters mirror)."""
        project = QgsProject.instance()
        payload = format_rasters(entries)
        project.writeEntry(SCOPE, ENTRY_RASTERS, payload)
        QgsExpressionContextUtils.setProjectVariable(project, VAR_RASTERS,
                                                     payload)

    def sync_rasters_now(self):
        """Re-sync raster visibility from the persisted filter state.

        Called by the dock when a raster row changes, so a spinbox edit
        takes effect without re-applying the vector subsets.
        """
        project = QgsProject.instance()
        enabled, _ = project.readBoolEntry(SCOPE, ENTRY_ENABLED, False)
        windows = None
        if enabled:
            level, _ = project.readEntry(SCOPE, ENTRY_LEVEL, "")
            tol, _ = project.readEntry(SCOPE, ENTRY_TOLERANCE, "")
            try:
                windows = [(float(level), float(tol))]
            except (TypeError, ValueError):
                windows = None
        self._sync_raster_visibility(project, windows)

    def _sync_raster_visibility(self, project, windows):
        """Show/hide elevation-tied rasters against the filter windows.

        windows: [(level, tol)] while the filter is ON, None when it is off
        (every checked raster becomes visible again). Checked rasters are
        fully managed; unchecked/unresolvable entries are left alone.
        """
        entries = parse_rasters(
            project.readEntry(SCOPE, ENTRY_RASTERS, "")[0])
        if not entries:
            return
        root = project.layerTreeRoot()
        if root is None:
            return
        for entry in entries:
            if not entry['checked']:
                continue
            layer = project.mapLayer(entry['id']) if entry['id'] else None
            if layer is None:
                matches = project.mapLayersByName(entry['name'])
                layer = matches[0] if matches else None
            if layer is None:
                continue
            node = root.findLayer(layer.id())
            if node is None:
                continue
            node.setItemVisibilityChecked(
                windows is None
                or raster_in_windows(entry['elevation'], windows))

    def _persist_state(self, project, applied_ids, level, tolerance, show_null,
                       enabled):
        project.writeEntry(SCOPE, ENTRY_ENABLED, enabled)
        if enabled:
            project.writeEntry(SCOPE, ENTRY_LEVEL, format_number(level))
            # writeEntry has no float overload in the bindings — store as text.
            project.writeEntry(SCOPE, ENTRY_TOLERANCE, format_number(tolerance))
            project.writeEntry(SCOPE, ENTRY_SHOW_NULL, bool(show_null))
            project.writeEntry(SCOPE, ENTRY_LAYER_IDS, ','.join(applied_ids))

        # Mirror for the QField sidecar plugin.
        set_var = QgsExpressionContextUtils.setProjectVariable
        set_var(project, VAR_ENABLED, '1' if enabled else '0')
        if enabled:
            set_var(project, VAR_LEVEL, format_number(level))
            set_var(project, VAR_TOLERANCE, format_number(tolerance))
            set_var(project, VAR_SHOW_NULL, '1' if show_null else '0')

    def _restore_layer(self, project, layer_id):
        """Put a layer back to its stored original subset; drop the entry.
        Returns the layer name if a restore happened."""
        key = ENTRY_ORIG_SUBSET_PREFIX + layer_id
        _, have_orig = project.readEntry(SCOPE, key, "")
        if not have_orig:
            return None
        original = _stored_original(project, layer_id)
        project.removeEntry(SCOPE, key)
        layer = project.mapLayer(layer_id)
        if layer is None:
            return None
        if layer.isEditable():
            buf = layer.editBuffer()
            if buf and buf.isModified():
                # Leave the filter in place rather than lose edits; the entry
                # is re-created on the next apply if needed.
                project.writeEntry(SCOPE, key, original)
                return None
            layer.commitChanges()
        if layer.subsetString() != original:
            layer.setSubsetString(original)
            layer.triggerRepaint()
        return layer.name()
