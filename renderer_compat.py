"""Read a layer's symbology classes whether it is categorized or rule-based.

The mapping template ships '4 - Basemap' as a categorized renderer on
Lithology1. The experimental patterns template
(LGS_MappingTemplate_Patterns.gpkg) ships the same 283 lithologies as a
RULE-BASED renderer instead, because the SVG texture fill has to live on
exactly ONE symbol layer to stay cheap - see
scripts/inject_basemap_lith_patterns.py for the measurements. A categorized
renderer cannot do that: it would need the SVGFill repeated on all 284
category symbols, and QGIS builds every category symbol on every render
pass whether or not anything is on screen.

So both renderer shapes are now in play, and code that used to assume
`isinstance(r, QgsCategorizedSymbolRenderer)` silently did nothing on the
patterns template - pruning stopped pruning, legends came out empty. These
helpers give one answer for both.

The texture rule is filter-less and carries no lithology value, so it must
never be treated as a class: not offered to the legend, and never pruned
(pruning it would delete the textures for every lithology at once).
"""
import re

try:
    from qgis.core import (QgsCategorizedSymbolRenderer, QgsRuleBasedRenderer,
                           QgsRendererCategory)
except ImportError:  # allows import in non-QGIS test contexts
    QgsCategorizedSymbolRenderer = QgsRuleBasedRenderer = None
    QgsRendererCategory = None

# Set by scripts/inject_basemap_lith_patterns.py; matched exactly.
PATTERN_RULE_LABEL = "Lithology texture"

# How far past the project's mapping scale the lithology texture keeps
# drawing.
#
# QGIS multiplies paper-unit symbol sizes by referenceScale/mapScale, so the
# scale at which the texture goes sub-pixel is LINEAR in the
# reference scale. A fixed cutoff is therefore only ever correct for one
# mapping scale: the old hard-coded 1:6000 was right for the baked 1:5000
# reference and wrong for every other entry in Set Mapping Scale's list,
# which runs 1:50 to 1:250000. Map at 1:200 and the tile is 25x smaller on
# paper, so the ink dies around 1:240 while the rule went on rasterising
# tiles that drew nothing all the way to 1:6000.
#
# Lives here rather than in the injector because both the bake
# (scripts/inject_basemap_lith_patterns.py) and the runtime rescale
# (script_setmapping.py set_reference_scale) have to agree on it.
SCALE_GATE_RATIO = 5

# How far past the project's mapping scale a LABEL keeps drawing.
#
# Separate from SCALE_GATE_RATIO on purpose, even though the two are equal
# today. They answer different questions: the texture gate is about ink going
# sub-pixel, this one is about lettering staying readable, and the sizes
# behave differently on the way out. Label text does NOT fade away when you
# zoom out - inject_label_size_scaling.PAPER_F clamps it at GROWTH_FLOOR, so
# it settles at 0.85x its authored size and stays perfectly legible however
# far back you go. A 1:5000 project viewed at 1:250,000 therefore draws every
# label it has ever had, at full size, in a solid mat of text. Nothing else
# turns them off: minFeatureSize takes the reference-scale multiplier itself,
# so it gets LESS selective as you pull back.
#
# Held here rather than in the injector because the bake
# (scripts/inject_label_scale_gate.py) and the runtime FieldNotebook rebuild
# (script_setmapping.build_structural_labeling) must agree on it - the same
# reason SCALE_GATE_RATIO lives here. Tuning one must not silently move the
# other, so they get one constant each.
LABEL_GATE_RATIO = 5

# Major and Regional linework - the axial traces and the named regional
# structures - are the framework you still want named on an overview, so they
# hold on for twice as long as everything else (user decision, 2 Sep 2026).
# Tier names are the ones inject_label_size_scaling.WEIGHT_F already ramps on.
LINEWORK_PERSIST_FACTOR = 2
LINEWORK_PERSIST_WEIGHTS = ("Major", "Regional")

# The reference scale reaches an expression two ways, and both have to work:
# the @lgs_reference_scale project variable (published by the plugin) and the
# literal baked into the style by script_setmapping.bake_reference_scale_into
# _styles(), which is what keeps a project working with the plugin disabled.
# Byte-identical with inject_label_size_scaling.REF_SCALE and matched by
# script_setmapping.REFERENCE_SCALE_LITERAL_RE - do not reformat one alone.
_LABEL_GATE_REF = "coalesce(to_real(@lgs_reference_scale), 0)"


def label_scale_gate_expression(persist_major=False):
    """The most zoomed-OUT map scale at which a label still draws.

    Feeds the data-defined QgsPalLayerSettings 'MinimumScale', which despite
    the name holds the LARGER denominator: QGIS names these for the view, so
    the "minimum" scale is the most zoomed-out one still shown. Writing it to
    MaximumScale instead gives an empty range and no labels anywhere - the
    same inversion that once cost the lithology textures. Confirmed for
    labels: setting the API's minimumScale = 25000 serialises as QML
    scaleMax="25000".

    A zero or missing reference scale yields 0, which QGIS reads as "no
    limit", so an unknown scale means every label draws exactly as it did
    before the gate existed. That direction is not negotiable - see the
    doctrine at script_setmapping.REFERENCE_SCALE_LITERAL_RE. A gate that
    fires when it does not know the scale would blank a whole map.
    """
    if not persist_major:
        return "%s * %s" % (_LABEL_GATE_REF, LABEL_GATE_RATIO)
    weights = ", ".join("'%s'" % w for w in LINEWORK_PERSIST_WEIGHTS)
    return ("CASE WHEN \"Weight\" IN (%s) THEN %s * %s ELSE %s * %s END"
            % (weights, _LABEL_GATE_REF,
               LABEL_GATE_RATIO * LINEWORK_PERSIST_FACTOR,
               _LABEL_GATE_REF, LABEL_GATE_RATIO))

# What QgsRuleBasedRenderer.convertFromRenderer() emits per category, i.e.
# QgsExpression::createFieldEqualityExpression: "Field" = 'value'
_EQ_RE = re.compile(r'^\s*"(?P<field>(?:[^"]|"")+)"\s*=\s*'
                    r"'(?P<value>(?:[^']|'')*)'\s*$")
_NULL_RE = re.compile(r'^\s*"(?P<field>(?:[^"]|"")+)"\s+IS\s+NULL\s*$', re.I)


def _is_else(rule):
    """True for a catch-all rule.

    QgsRuleBasedRenderer.convertFromRenderer() turns a categorized
    renderer's NULL / 'all other values' category into an ELSE rule, whose
    filterExpression() is the literal string 'ELSE'. It is a class, not
    decoration - treating it as decoration silently drops the catch-all.
    """
    if rule is None:
        return False
    try:
        if rule.isElse():
            return True
    except AttributeError:
        pass
    return (rule.filterExpression() or "").strip().upper() == "ELSE"


def is_pattern_rule(rule):
    """True for the filter-less SVG texture rule."""
    if rule is None:
        return False
    if rule.label() == PATTERN_RULE_LABEL:
        return True
    if _is_else(rule):
        return False
    # Defensive: any filter-less rule that carries a symbol but no value is
    # decoration, not a class.
    return (not rule.filterExpression()) and rule.symbol() is not None


def rule_value(rule):
    """Recover the class value a converted category rule filters on.

    Returns the value string, None for the catch-all (the converted NULL /
    'all other values' category, and the IS NULL form), or False when the
    rule is not a class rule at all.

    None mirrors what the categorized path yields for that same category,
    so both templates prune and legend-build identically.
    """
    if _is_else(rule):
        return None
    expr = (rule.filterExpression() or "").strip()
    if not expr:
        return False
    m = _EQ_RE.match(expr)
    if m:
        return m.group("value").replace("''", "'")
    if _NULL_RE.match(expr):
        return None
    return False


def is_supported(renderer):
    """True if renderer_classes() can read this renderer."""
    return isinstance(renderer, (QgsCategorizedSymbolRenderer,
                                 QgsRuleBasedRenderer))


def class_attribute(renderer):
    """Field the renderer classifies on, or '' if it cannot be determined."""
    if isinstance(renderer, QgsCategorizedSymbolRenderer):
        return renderer.classAttribute()
    if isinstance(renderer, QgsRuleBasedRenderer):
        for rule in renderer.rootRule().children():
            if is_pattern_rule(rule):
                continue
            expr = (rule.filterExpression() or "").strip()
            for rx in (_EQ_RE, _NULL_RE):
                m = rx.match(expr)
                if m:
                    return m.group("field").replace('""', '"')
    return ""


def renderer_classes(renderer):
    """[(value, symbol), ...] for either renderer type.

    `value` is the raw class value (None for the NULL class). The texture
    rule and any group/container rules are skipped. Symbols are the live
    objects, not clones - clone at the call site if you intend to keep them.
    """
    out = []
    if isinstance(renderer, QgsCategorizedSymbolRenderer):
        for cat in renderer.categories():
            out.append((cat.value(), cat.symbol()))
    elif isinstance(renderer, QgsRuleBasedRenderer):
        for rule in renderer.rootRule().children():
            if is_pattern_rule(rule):
                continue
            val = rule_value(rule)
            if val is False:
                continue
            out.append((val, rule.symbol()))
    return out


def prune_classes(renderer, keep_predicate):
    """Drop classes where keep_predicate(value) is False.

    Returns (removed_count, kept_count, new_renderer_or_None). new_renderer
    is None when nothing was removed, so callers can skip the swap. The
    texture rule is always kept - it is not a class, and removing it would
    strip the textures from every lithology at once.
    """
    if isinstance(renderer, QgsCategorizedSymbolRenderer):
        kept, removed = [], 0
        for cat in renderer.categories():
            if keep_predicate(cat.value()):
                kept.append(cat)
            else:
                removed += 1
        if not removed:
            return 0, len(kept), None
        new = QgsCategorizedSymbolRenderer(renderer.classAttribute(), kept)
        new.setReferenceScale(renderer.referenceScale())
        new.setOrderBy(renderer.orderBy())
        new.setOrderByEnabled(renderer.orderByEnabled())
        return removed, len(kept), new

    if isinstance(renderer, QgsRuleBasedRenderer):
        new = renderer.clone()
        root = new.rootRule()
        removed, kept = 0, 0
        for rule in list(root.children()):
            if is_pattern_rule(rule):
                continue
            val = rule_value(rule)
            if val is False:
                continue
            if keep_predicate(val):
                kept += 1
            else:
                root.removeChild(rule)
                removed += 1
        if not removed:
            return 0, kept, None
        return removed, kept, new

    return 0, 0, None
