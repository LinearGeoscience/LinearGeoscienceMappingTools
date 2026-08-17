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
