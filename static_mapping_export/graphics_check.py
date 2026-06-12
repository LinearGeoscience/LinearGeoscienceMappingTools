"""
Pre-export scan for file-based symbol/label graphics that are not embedded
(base64) and not built-in QGIS SVGs - i.e. graphics that will not resolve
on a client's machine and would silently render as default markers.
"""

from qgis.core import (
    QgsApplication, QgsPathResolver, QgsRenderContext, QgsSymbolLayerUtils,
    QgsVectorLayerSimpleLabeling, QgsTextBackgroundSettings,
)
import os

try:
    from qgis.core import QgsRuleBasedLabeling
except ImportError:
    QgsRuleBasedLabeling = None

# Class -> path accessor method name; built defensively so a missing
# binding on older QGIS versions just drops that check
_GRAPHIC_LAYER_TYPES = []
try:
    from qgis.core import QgsSvgMarkerSymbolLayer
    _GRAPHIC_LAYER_TYPES.append((QgsSvgMarkerSymbolLayer, 'path', 'svg'))
except ImportError:
    pass
try:
    from qgis.core import QgsSvgFillSymbolLayer
    _GRAPHIC_LAYER_TYPES.append((QgsSvgFillSymbolLayer, 'svgFilePath', 'svg'))
except ImportError:
    pass
try:
    from qgis.core import QgsRasterMarkerSymbolLayer
    _GRAPHIC_LAYER_TYPES.append((QgsRasterMarkerSymbolLayer, 'path', 'raster'))
except ImportError:
    pass
try:
    from qgis.core import QgsRasterFillSymbolLayer
    _GRAPHIC_LAYER_TYPES.append((QgsRasterFillSymbolLayer, 'imageFilePath', 'raster'))
except ImportError:
    pass

_MAX_SUBSYMBOL_DEPTH = 10


def find_unembedded_graphics(layer):
    """
    Scan a QgsVectorLayer's renderer and labeling for file-based SVG/raster
    graphics that are neither embedded (base64) nor built-in QGIS SVGs.

    Never raises: every traversal step is wrapped defensively, so a scan
    failure can never block an export.

    Returns:
        list[dict]: one dict per unique finding, with keys:
            kind:     'svg' | 'raster'
            context:  'symbology', 'symbology (sub-symbol)',
                      'labeling background', 'labeling background marker'
            path:     raw path stored on the symbol layer
            basename: os.path.basename(path) for display
            exists:   whether the file exists on THIS machine
            reason:   short human string
    """
    findings = []
    seen = set()
    try:
        _scan_renderer(layer, findings, seen)
    except Exception:
        pass
    try:
        _scan_labeling(layer, findings, seen)
    except Exception:
        pass
    return findings


def _add_finding(findings, seen, kind, context, path, reason):
    key = (kind, context, os.path.normcase(path))
    if key in seen:
        return
    seen.add(key)
    exists = False
    try:
        exists = os.path.exists(path)
    except Exception:
        pass
    if not exists:
        reason += ", file missing locally"
    findings.append({
        'kind': kind,
        'context': context,
        'path': path,
        'basename': os.path.basename(path.rstrip('/\\')) or path,
        'exists': exists,
        'reason': reason,
    })


def _classify_svg_path(path):
    """Return None if OK (empty / base64: / built-in QGIS svg), else a reason."""
    if not path or not path.strip():
        return None
    if path.startswith('base64:'):
        return None
    if _is_builtin_svg(path):
        return None
    return "custom SVG path"


def _classify_raster_path(path):
    """Return None if OK (empty / base64:), else a reason. Raster images
    have no built-in library, so any file path is flagged."""
    if not path or not path.strip():
        return None
    if path.startswith('base64:'):
        return None
    return "raster image path"


def _is_builtin_svg(path):
    """True if path resolves under the QGIS install's svg directory.

    Relative names (e.g. 'transport/amenity_airport.svg') are resolved via
    QgsSymbolLayerUtils.svgSymbolNameToPath. Deliberately does NOT treat the
    user-profile svg directory as safe - those files don't exist on a
    client's machine.
    """
    try:
        builtin_dir = os.path.normcase(os.path.normpath(
            os.path.join(QgsApplication.pkgDataPath(), 'svg'))) + os.sep

        resolved = path
        if not os.path.isabs(path):
            try:
                resolved = QgsSymbolLayerUtils.svgSymbolNameToPath(
                    path, QgsPathResolver())
            except Exception:
                resolved = path
            if not resolved:
                return False

        return os.path.normcase(os.path.normpath(resolved)).startswith(builtin_dir)
    except Exception:
        return False


def _walk_symbol(symbol, context, findings, seen, depth=0):
    if symbol is None or depth > _MAX_SUBSYMBOL_DEPTH:
        return
    try:
        symbol_layers = list(symbol.symbolLayers())
    except Exception:
        return
    for sl in symbol_layers:
        try:
            for cls, accessor, kind in _GRAPHIC_LAYER_TYPES:
                if isinstance(sl, cls):
                    path = getattr(sl, accessor)()
                    classify = _classify_svg_path if kind == 'svg' else _classify_raster_path
                    reason = classify(path)
                    if reason:
                        _add_finding(findings, seen, kind, context, path, reason)
                    break
        except Exception:
            pass
        try:
            sub = sl.subSymbol()
        except Exception:
            sub = None
        if sub is not None:
            sub_context = context if context.endswith('(sub-symbol)') \
                else context + ' (sub-symbol)'
            _walk_symbol(sub, sub_context, findings, seen, depth + 1)


def _scan_renderer(layer, findings, seen):
    renderer = layer.renderer()
    if renderer is None:
        return
    try:
        symbols = renderer.symbols(QgsRenderContext())
    except Exception:
        return
    for symbol in symbols:
        _walk_symbol(symbol, 'symbology', findings, seen)


def _scan_labeling(layer, findings, seen):
    labeling = layer.labeling()
    if labeling is None:
        return
    settings_list = []
    if isinstance(labeling, QgsVectorLayerSimpleLabeling):
        try:
            settings_list.append(labeling.settings())
        except Exception:
            pass
    elif QgsRuleBasedLabeling is not None and isinstance(labeling, QgsRuleBasedLabeling):
        try:
            _collect_rule_settings(labeling.rootRule(), settings_list)
        except Exception:
            pass
    for settings in settings_list:
        try:
            _check_label_settings(settings, findings, seen)
        except Exception:
            pass


def _collect_rule_settings(rule, settings_list):
    if rule is None:
        return
    settings = rule.settings()
    if settings is not None:
        settings_list.append(settings)
    for child in rule.children():
        _collect_rule_settings(child, settings_list)


def _check_label_settings(settings, findings, seen):
    if settings is None:
        return
    background = settings.format().background()
    if not background.enabled():
        return
    shape = background.type()
    if shape == QgsTextBackgroundSettings.ShapeSVG:
        reason = _classify_svg_path(background.svgFile())
        if reason:
            _add_finding(findings, seen, 'svg', 'labeling background',
                         background.svgFile(), reason)
    elif shape == getattr(QgsTextBackgroundSettings, 'ShapeMarkerSymbol', None):
        # markerSymbol() added in QGIS 3.20
        marker = getattr(background, 'markerSymbol', lambda: None)()
        _walk_symbol(marker, 'labeling background marker', findings, seen)
