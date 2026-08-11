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
    ENTRY_SHOW_NULL,
    ENTRY_SLOT_IDS,
    ENTRY_TOLERANCE,
    FLAT_SPAN,
    SCOPE,
    VAR_ENABLED,
    VAR_EXTRA,
    VAR_LEVEL,
    VAR_LEVELS,
    VAR_SHOW_NULL,
    VAR_TOLERANCE,
    clause_for_spec,
    combine,
    format_extra_layers,
    format_levels,
    format_number,
    parse_extra_layers,
    parse_levels,
    spec_field_names,
)


# Spec used when a caller passes a bare layer instead of a (layer, spec)
# target — the canonical mapping layers filter on Elevation.
DEFAULT_SPEC = {'mode': 'single', 'field': ELEVATION_FIELD}


def normalize_targets(items):
    """Promote bare layers to (layer, spec) targets; pass targets through."""
    targets = []
    for item in items or []:
        if isinstance(item, tuple):
            layer, spec = item
        else:
            layer, spec = item, DEFAULT_SPEC
        if layer is not None:
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

        Range-mode targets vote their midpoint when the feature is flat
        (span <= FLAT_SPAN); spanning features (ramps) are counted in
        'spanning' but stay out of the histogram so mid-ramp values never
        become level suggestions.

        Returns {
            'value_counts': {float: int},   # global, across all layers
            'per_layer': [{'name', 'total', 'with_elev', 'blank',
                           'spanning'}, ...],
            'with_elev': int, 'blank': int, 'total': int, 'spanning': int,
            'truncated': [layer names skipped],
        }
        """
        value_counts = Counter()
        per_layer = []
        truncated = []
        with suspended_filters():
            for layer, spec in normalize_targets(layers):
                indexes = [layer.fields().indexOf(f)
                           for f in spec_field_names(spec)]
                if -1 in indexes:
                    continue
                total = layer.featureCount()
                if feature_cap is not None and total > feature_cap:
                    truncated.append(layer.name())
                    continue
                request = QgsFeatureRequest()
                request.setFlags(Qgis.FeatureRequestFlag.NoGeometry)
                request.setSubsetOfAttributes(indexes)
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
                        if len(values) == 2 and \
                                abs(values[1] - values[0]) > FLAT_SPAN:
                            spanning += 1  # ramp — abstains from histogram
                            continue
                        value_counts[sum(values) / len(values)] += 1
                        with_elev += 1
                except Exception as e:  # provider hiccup — skip this layer
                    _log(f"Z filter scan failed on {layer.name()}: {e}",
                         Qgis.MessageLevel.Warning)
                    continue
                per_layer.append({'name': layer.name(), 'total': total,
                                  'with_elev': with_elev, 'blank': blank,
                                  'spanning': spanning})
        return {
            'value_counts': dict(value_counts),
            'per_layer': per_layer,
            'with_elev': sum(entry['with_elev'] for entry in per_layer),
            'blank': sum(entry['blank'] for entry in per_layer),
            'total': sum(entry['total'] for entry in per_layer),
            'spanning': sum(entry['spanning'] for entry in per_layer),
            'truncated': truncated,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def persisted_state(self):
        """Read the persisted panel state for restore-on-open/project-load."""
        project = QgsProject.instance()
        enabled, _ = project.readBoolEntry(SCOPE, ENTRY_ENABLED, False)
        level, _ = project.readEntry(SCOPE, ENTRY_LEVEL, "")
        tolerance_text, _ = project.readEntry(SCOPE, ENTRY_TOLERANCE, "5")
        try:
            tolerance = float(tolerance_text)
        except ValueError:
            tolerance = 5.0
        show_null, _ = project.readBoolEntry(SCOPE, ENTRY_SHOW_NULL, True)
        levels_csv, _ = project.readEntry(SCOPE, ENTRY_LEVELS, "")
        # Slot combos persist separately from the applied-layer set; fall
        # back to the old shared key for projects saved before the split.
        layer_ids, have_slots = project.readEntry(SCOPE, ENTRY_SLOT_IDS, "")
        if not have_slots:
            layer_ids, _ = project.readEntry(SCOPE, ENTRY_LAYER_IDS, "")
        checked, _ = project.readEntry(SCOPE, ENTRY_LAYER_CHECKED, "")
        extra_json, _ = project.readEntry(SCOPE, ENTRY_EXTRA_LAYERS, "")
        return {
            'enabled': enabled,
            'level': float(level) if level else None,
            'tolerance': tolerance,
            'show_null': show_null,
            'levels': parse_levels(levels_csv),
            'layer_ids': [lid for lid in layer_ids.split(',') if lid],
            'layer_checked': [c == '1' for c in checked.split(',') if c],
            'extra_layers': parse_extra_layers(extra_json),
        }

    def persist_levels(self, levels):
        project = QgsProject.instance()
        project.writeEntry(SCOPE, ENTRY_LEVELS, format_levels(levels))
        QgsExpressionContextUtils.setProjectVariable(
            project, VAR_LEVELS, format_levels(levels))

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
