"""Cartographic styling for generated contour layers.

Rule-based renderer and labeling keyed on the 'type' field ('major'/'minor'),
so the distinction is data-driven and survives in the GeoPackage. The built
style is also saved into the .gpkg as the layer default so it travels with
the file.
"""

from qgis.core import (
    Qgis,
    QgsLineSymbol,
    QgsPalLayerSettings,
    QgsRuleBasedLabeling,
    QgsRuleBasedRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont

LABEL_FONT = "Leelawadee UI Semilight"

SCHEMES = {
    "subtle_grey": {
        "label": "Subtle grey",
        "minor_color": "#c8c8c8", "minor_width": 0.13,
        "major_color": "#8c8c8c", "major_width": 0.26,
        "label_color": "#787878",
    },
    "topo_brown": {
        "label": "Classic topo brown",
        "minor_color": "#cda06e", "minor_width": 0.15,
        "major_color": "#a0642d", "major_width": 0.30,
        "label_color": "#8a5a2b",
    },
}
DEFAULT_SCHEME = "subtle_grey"


def apply_contour_style(layer, scheme_key):
    """Renderer + labeling on the loaded layer. Best-effort by contract:
    callers treat styling as cosmetic and must not fail generation on it."""
    scheme = SCHEMES.get(scheme_key, SCHEMES[DEFAULT_SCHEME])
    layer.setRenderer(build_renderer(scheme))
    layer.setLabeling(build_labeling(scheme))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()


def _line_symbol(color, width):
    symbol = QgsLineSymbol.createSimple({})
    sl = symbol.symbolLayer(0)
    sl.setColor(QColor(color))
    sl.setWidth(width)
    sl.setWidthUnit(Qgis.RenderUnit.Millimeters)
    # Round joins matter for perceived smoothness on tight contour bends.
    sl.setPenJoinStyle(Qt.PenJoinStyle.RoundJoin)
    sl.setPenCapStyle(Qt.PenCapStyle.RoundCap)
    return symbol


def build_renderer(scheme):
    root = QgsRuleBasedRenderer.Rule(None)
    minor = QgsRuleBasedRenderer.Rule(
        _line_symbol(scheme["minor_color"], scheme["minor_width"]),
        filterExp="\"type\" = 'minor'", label="Minor contour")
    major = QgsRuleBasedRenderer.Rule(
        _line_symbol(scheme["major_color"], scheme["major_width"]),
        filterExp="\"type\" = 'major'", label="Major contour")
    root.appendChild(minor)
    root.appendChild(major)
    return QgsRuleBasedRenderer(root)


def build_labeling(scheme):
    settings = QgsPalLayerSettings()
    settings.fieldName = "to_string(to_int(round(\"elev\")))"
    settings.isExpression = True
    settings.placement = Qgis.LabelPlacement.Curved

    line_settings = settings.lineSettings()
    line_settings.setPlacementFlags(
        Qgis.LabelLinePlacementFlags(Qgis.LabelLinePlacementFlag.OnLine))
    settings.setLineSettings(line_settings)

    # Paper-distance repeat (not ground units, unlike the Linework layers):
    # contour labels repeating every ~15 cm of screen/paper at any zoom is
    # the standard topo-sheet behaviour, so the deviation is deliberate.
    settings.repeatDistance = 150.0
    settings.repeatDistanceUnit = Qgis.RenderUnit.Millimeters

    fmt = QgsTextFormat()
    font = QFont(LABEL_FONT)
    font.setItalic(True)
    fmt.setFont(font)
    fmt.setSize(7.5)
    fmt.setSizeUnit(Qgis.RenderUnit.Points)
    fmt.setColor(QColor(scheme["label_color"]))

    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(0.8)
    buffer.setSizeUnit(Qgis.RenderUnit.Millimeters)
    buffer.setColor(QColor("#ffffff"))
    fmt.setBuffer(buffer)  # attach to the format BEFORE setFormat
    settings.setFormat(fmt)

    # Below the geology labels on the cross-layer priority ladder.
    settings.priority = 3

    rule = QgsRuleBasedLabeling.Rule(
        settings, filterExp="\"type\" = 'major'",
        description="Major contour elevations")
    root = QgsRuleBasedLabeling.Rule(None)
    root.appendChild(rule)
    return QgsRuleBasedLabeling(root)


def persist_style(layer, layer_name):
    """Save the current style into the GeoPackage as the layer default."""
    try:
        layer.saveStyleToDatabase(layer_name, "LGS contours", True, "")
        return True
    except Exception:
        return False
