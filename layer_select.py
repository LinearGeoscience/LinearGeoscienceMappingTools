"""
Shared layer-selection helpers.

Projects often contain multiple copies of the same geopackage, so layer
names alone are ambiguous. These helpers give every tool a consistent way
to present layers as "Name (Folder/File.gpkg)", auto-match the most likely
layer by name, and resolve combo selections back to layers by ID.
"""

import os

from qgis.core import QgsProject, QgsMapLayerType, QgsWkbTypes, QgsMessageLog, Qgis

try:
    from thefuzz import fuzz
    HAS_FUZZY = True
except ImportError:
    try:
        from .vendor.fuzzywuzzy import fuzz
        HAS_FUZZY = True
    except Exception:
        fuzz = None
        HAS_FUZZY = False


def layer_display_name(layer, max_tail_chars=50):
    """Display string for a layer: "Name (Folder/File.gpkg)".

    The source filename is always shown in full; only the directory part is
    shortened when the tail exceeds max_tail_chars. Memory layers show
    "(temporary layer)" and layers with no usable path fall back to a short
    layer-id suffix so duplicates stay distinguishable.
    """
    layer_name = layer.name()

    try:
        provider = layer.providerType()
    except Exception:
        provider = ''
    if provider == 'memory':
        return f"{layer_name} (temporary layer)"

    source_path = layer.source() or ''
    # QGIS appends parameters after a pipe (e.g. |layername=table)
    if '|' in source_path:
        source_path = source_path.split('|')[0]
    source_path = source_path.strip()

    # Memory/service sources look like "Point?crs=..." — no real path
    if source_path and '?' not in source_path:
        parent_dir = os.path.basename(os.path.dirname(source_path))
        file_name = os.path.basename(source_path)
        if file_name:
            tail = f"{parent_dir}/{file_name}" if parent_dir else file_name
            if len(tail) > max_tail_chars:
                # Never cut the filename — drop/shorten the directory instead
                tail = f"…/{file_name}"
            return f"{layer_name} ({tail})"

    short_id = layer.id()[:8]
    return f"{layer_name} [{short_id}]"


def find_best_match(target_name, layer_names):
    """Find the index of the best name match for target_name.

    Scoring: exact (100) > target substring of name (90) > name substring of
    target (80) > fuzzy ratio (if thefuzz/fuzzywuzzy available, threshold 60).
    Returns (index, score) or (None, 0).
    """
    if not target_name:
        return None, 0
    target_lower = target_name.lower()
    best_index, best_score = None, 0

    for i, name in enumerate(layer_names):
        name_lower = name.lower()
        if target_lower == name_lower:
            return i, 100
        if target_lower in name_lower:
            score = 90
        elif name_lower in target_lower:
            score = 80
        elif HAS_FUZZY:
            ratio = fuzz.ratio(target_lower, name_lower)
            score = ratio if ratio >= 60 else 0
        else:
            score = 0
        if score > best_score:
            best_index, best_score = i, score

    return best_index, best_score


def layer_candidates(geometry=None, required_fields=None, non_spatial=False,
                     predicate=None):
    """Vector layers from the project, filtered and sorted by name.

    geometry: a QgsWkbTypes.GeometryType to require (Point/Line/Polygon).
    non_spatial: require NullGeometry (attribute-only tables).
    required_fields: field names that must all exist on the layer.
    predicate: extra callable(layer) -> bool filter.
    """
    result = []
    for layer in QgsProject.instance().mapLayers().values():
        if layer.type() != QgsMapLayerType.VectorLayer:
            continue
        if non_spatial:
            if layer.geometryType() != QgsWkbTypes.NullGeometry:
                continue
        elif geometry is not None:
            if layer.geometryType() != geometry:
                continue
        if required_fields:
            fields = layer.fields()
            if any(fields.indexFromName(f) < 0 for f in required_fields):
                continue
        if predicate and not predicate(layer):
            continue
        result.append(layer)
    result.sort(key=lambda l: l.name().lower())
    return result


def populate_layer_combo(combo, layers, placeholder=None, target_name=None,
                         select_layer_id=None):
    """Fill a QComboBox with layers (display name as text, layer id as data).

    Pre-selects select_layer_id if present, otherwise the best name match
    for target_name. Returns the selected layer or None. Signals are blocked
    during population so repopulating never fires selection handlers.
    """
    blocked = combo.blockSignals(True)
    try:
        combo.clear()
        if placeholder is not None:
            combo.addItem(placeholder, None)
        offset = combo.count()
        for layer in layers:
            combo.addItem(layer_display_name(layer), layer.id())

        if select_layer_id:
            for i in range(offset, combo.count()):
                if combo.itemData(i) == select_layer_id:
                    combo.setCurrentIndex(i)
                    return layers[i - offset]

        if target_name and layers:
            index, score = find_best_match(
                target_name, [l.name() for l in layers])
            if index is not None and score > 0:
                combo.setCurrentIndex(offset + index)
                QgsMessageLog.logMessage(
                    f"Auto-matched layer '{layers[index].name()}' for "
                    f"'{target_name}' (score {score})",
                    'Linear Geoscience', Qgis.Info)
                return layers[index]
    finally:
        combo.blockSignals(blocked)

    if placeholder is None and layers:
        return layers[0]
    return None


def combo_current_layer(combo):
    """Resolve the combo's current layer-id data back to a layer (or None)."""
    layer_id = combo.currentData()
    if not layer_id:
        return None
    return QgsProject.instance().mapLayer(layer_id)
