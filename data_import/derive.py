"""
Filling in what the source could not say.

Two things happen here. The first is back-filling cascade parents: the current
template drives `Subtype1` from `Type`, `Type` from `Category`, `Lithology1`
from `TypeLith1`. Data mapped before those parents existed has the child code
and nothing above it, so the form's dropdown filters to an empty list and the
feature looks broken even though its code is fine. Every code in the template's
grouped tables belongs to exactly one parent, so the parent is recoverable
without asking anyone — tests/test_import_domain.py pins that property, because
the day it stops being true this has to start asking.

The second is type coercion. The old tool read every recoded value out of a text
box and wrote it straight into whatever column it was aimed at, so a '3' landed
in an integer field as the string '3'. Values are converted to the destination
column's type here, and anything that will not convert is reported rather than
written.
"""

import re
from collections import OrderedDict

try:
    from .domain import is_blank, normalise
except ImportError:  # flat execution / pure test loader
    from domain import is_blank, normalise


_INT_RE = re.compile(r'^[+-]?\d+$')
_NUM_RE = re.compile(r'^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$')
_PERCENT_RE = re.compile(r'^\s*([+-]?[\d.]+)\s*%\s*$')


class ParentFill(object):
    """One cascade parent worked out from a child code."""

    __slots__ = ('parent_field', 'child_field', 'value', 'replaced')

    def __init__(self, parent_field, child_field, value, replaced=None):
        self.parent_field = parent_field
        self.child_field = child_field
        self.value = value
        self.replaced = replaced

    @property
    def is_conflict(self):
        """True when the source already held a different parent value."""
        return bool(self.replaced) and normalise(self.replaced) != normalise(self.value)

    def __repr__(self):
        return 'ParentFill({0}={1!r} from {2})'.format(
            self.parent_field, self.value, self.child_field)


def cascade_pairs(layer_spec):
    """[(parent_field, child_field, child_domain)] for every cascade on a layer.

    Ordered so a parent with several children (Overlay's Type feeds SubType1,
    SubType2 and SubType3) is filled from the first child that has a value.
    """
    pairs = []
    for child_field, domain in layer_spec.code_domains.items():
        if domain.parent_field and domain.parent_column:
            pairs.append((domain.parent_field, child_field, domain))
    return pairs


def fill_parents(layer_spec, attributes):
    """Set every cascade parent from its child's code. Returns [ParentFill].

    `attributes` is mutated in place. The derived value wins over whatever the
    source carried, because the pair has to agree for the form and the renderer
    to work; disagreements come back in the return value so they can be counted
    and reported rather than hidden.
    """
    fills = []
    for parent_field, child_field, domain in cascade_pairs(layer_spec):
        if parent_field not in layer_spec.fields:
            continue
        code = normalise(attributes.get(child_field))
        if not code:
            continue
        parent_value = domain.parent_of(code)
        if not parent_value:
            continue
        existing = attributes.get(parent_field)
        if normalise(existing) == normalise(parent_value):
            continue
        fills.append(ParentFill(parent_field, child_field, parent_value,
                                replaced=existing))
        attributes[parent_field] = parent_value
    return fills


def coerce(value, field_spec):
    """(converted_value, error) for writing `value` into `field_spec`.

    Returns (None, '') for an empty value so the destination's own default
    expression gets its chance, and (None, reason) when the value cannot be
    represented — which is reported, never silently dropped.
    """
    if field_spec is None:
        return value, ''
    if is_blank(value):
        return None, ''
    text = normalise(value)

    target = field_spec.base_type

    if target == 'text':
        return text, ''

    if target in ('int', 'real'):
        percent = _PERCENT_RE.match(text)
        if percent:
            text = percent.group(1)
        if target == 'int':
            if _INT_RE.match(text):
                return int(text), ''
            if _NUM_RE.match(text):
                return int(round(float(text))), ''
            return None, '{0!r} is not a whole number'.format(value)
        if _NUM_RE.match(text):
            return float(text), ''
        return None, '{0!r} is not a number'.format(value)

    if target == 'datetime':
        # Left as text: OGR and QGIS both parse ISO and the common
        # dd/mm/yyyy forms on write, and reformatting here would be one more
        # place for a timezone to go missing.
        return value, ''

    return value, ''


def apply_resolutions(field_mapping, resolutions_by_field, source_attributes,
                      target_spec):
    """Turn one source feature's attributes into destination attributes.

    `field_mapping` is {source_field: target_field}; `resolutions_by_field` is
    {target_field: {source_value: ValueResolution}}. Returns
    (attributes, extras_applied, unresolved_fields).
    """
    attributes = OrderedDict()
    extras_applied = []
    unresolved = []

    for source_field, target_field in field_mapping.items():
        raw = source_attributes.get(source_field)
        resolutions = resolutions_by_field.get(target_field)
        if resolutions is None:
            attributes[target_field] = raw
            continue

        if is_blank(raw):
            attributes[target_field] = None
            continue
        key = normalise(raw)

        resolution = resolutions.get(key)
        if resolution is None:
            unresolved.append((target_field, key))
            attributes[target_field] = None
            continue

        attributes[target_field] = resolution.code
        for extra_field, extra_value in resolution.extras.items():
            if extra_field in target_spec.fields:
                attributes[extra_field] = extra_value
                extras_applied.append((extra_field, extra_value))

    return attributes, extras_applied, unresolved


def comment_suffix(source_attributes, comment_fields):
    """'Float: yes | Lith1Feature: Chl-k altered' from the dropped columns.

    Appended to Comments so a retired free-text column is preserved in a form a
    geologist can still read, rather than being thrown away or forced into a
    code list it never belonged in.
    """
    parts = []
    for name in comment_fields:
        raw = source_attributes.get(name)
        if not is_blank(raw):
            parts.append('{0}: {1}'.format(name, normalise(raw)))
    return ' | '.join(parts)


def merge_comments(existing, suffix):
    """Append `suffix` to a Comments value without duplicating it."""
    existing = normalise(existing)
    if not suffix:
        return existing or None
    if not existing:
        return suffix
    if suffix in existing:
        return existing
    return existing + ' | ' + suffix
