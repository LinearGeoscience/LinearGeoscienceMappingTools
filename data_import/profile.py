"""
Remembering an import so the next one is three clicks.

A migration profile is every decision the wizard collected: which source layer
went where, which columns paired up, and what each old code became. It is keyed
on the SHAPE of the two ends rather than their filenames, because the same
client sends the same export layout every month under a different name.

Stored per QGIS profile via QgsSettings, not next to the destination file. The
old tool wrote its templates into an `adddata_metadata` folder beside whichever
GeoPackage happened to be the master, so a mapping worked out for one project
was invisible from the next — which is most of the reason nobody reused them.
They can also be exported to a file and handed to a colleague, which is the
other half of the problem: one person works the codes out, everyone else runs
it.
"""

import hashlib
import io
import json
import os
from collections import OrderedDict

try:
    from .domain import fold
    from . import match_fields, match_values
except ImportError:  # flat execution / pure test loader
    from domain import fold
    import match_fields
    import match_values


PREFIX = 'LinearGeoscience/DataImport'
KEY_PROFILES = PREFIX + '/profiles'
KEY_LAST_SOURCE = PREFIX + '/lastSource'
KEY_LAST_DESTINATION = PREFIX + '/lastDestination'

FORMAT_VERSION = 2


def signature(model):
    """A stable fingerprint of a mapping dataset's shape.

    Layer names and their column sets, hashed. Two monthly exports from the
    same client hash the same; a different client's export does not.
    """
    parts = []
    for name in sorted(model.layers):
        spec = model.layers[name]
        columns = ','.join(sorted(fold(field) for field in spec.fields))
        parts.append('{0}|{1}|{2}'.format(fold(name),
                                          spec.geometry_type.upper(), columns))
    digest = hashlib.sha1('\n'.join(parts).encode('utf-8')).hexdigest()
    return digest[:16]


def profile_key(source_model, target_model):
    return '{0}->{1}'.format(signature(source_model), signature(target_model))


# ── capture / apply ───────────────────────────────────────────────────

def capture(plan, name=''):
    """Freeze a plan's decisions into a serialisable profile."""
    layers = OrderedDict()
    fields = OrderedDict()
    values = OrderedDict()

    for item in plan.layer_imports:
        source_name = item.source.table
        if not item.include or not item.target_layer:
            continue
        layers[source_name] = item.target_layer
        if item.field_plan is not None:
            fields[source_name] = OrderedDict(
                (match.source_name, match.target_name or '')
                for match in item.field_plan.matches.values()
                if match.status != match_fields.IGNORED)
        per_field = OrderedDict()
        for target_field, resolutions in item.resolutions.items():
            entries = OrderedDict()
            for value, resolution in resolutions.items():
                # Identity matches carry no information worth storing; keeping
                # them would make a profile grow by 300 useless rows per field,
                # which is what made the old templates unreadable.
                if resolution.status == match_values.EXACT:
                    continue
                entries[value] = resolution.as_profile_entry()
            if entries:
                per_field[target_field] = entries
        if per_field:
            values[source_name] = per_field

    return {
        'version': FORMAT_VERSION,
        'name': name or 'Import profile',
        'source_signature': signature(plan.source_model),
        'target_signature': signature(plan.target_model),
        'source_label': plan.source_model.label,
        'target_label': plan.target_model.label,
        'layers': layers,
        'fields': fields,
        'values': values,
    }


def is_compatible(profile, source_model, target_model):
    """True when a saved profile was made for these two shapes."""
    if not profile:
        return False
    return (profile.get('source_signature') == signature(source_model)
            and profile.get('target_signature') == signature(target_model))


def describe(profile):
    """One line for the picker."""
    if not profile:
        return ''
    layers = len(profile.get('layers') or {})
    values = sum(len(entries)
                 for per_field in (profile.get('values') or {}).values()
                 for entries in per_field.values())
    return '{0} — {1} layer(s), {2} code decision(s)'.format(
        profile.get('name', 'Import profile'), layers, values)


# ── storage ───────────────────────────────────────────────────────────

def _load_all():
    from qgis.core import QgsSettings

    raw = QgsSettings().value(KEY_PROFILES, '')
    if not raw:
        return OrderedDict()
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return OrderedDict()
    return OrderedDict(data) if isinstance(data, dict) else OrderedDict()


def _save_all(profiles):
    from qgis.core import QgsSettings

    QgsSettings().setValue(KEY_PROFILES, json.dumps(profiles, sort_keys=True))


def save(profile):
    """Store a profile under its source->target key. Returns the key."""
    profiles = _load_all()
    key = '{0}->{1}'.format(profile.get('source_signature', ''),
                            profile.get('target_signature', ''))
    profiles[key] = profile
    _save_all(profiles)
    return key


def load_for(source_model, target_model):
    """The stored profile matching these two shapes, or None."""
    return _load_all().get(profile_key(source_model, target_model))


def list_all():
    """[(key, profile)] newest-key-last, for a management list."""
    return list(_load_all().items())


def delete(key):
    profiles = _load_all()
    if key in profiles:
        del profiles[key]
        _save_all(profiles)
        return True
    return False


def export_to_file(profile, path):
    with io.open(path, 'w', encoding='utf-8') as handle:
        json.dump(profile, handle, indent=2, ensure_ascii=False)
    return path


def import_from_file(path):
    """Read a profile a colleague exported. Returns the dict, or None."""
    if not path or not os.path.exists(path):
        return None
    try:
        with io.open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (IOError, ValueError):
        return None
    if not isinstance(data, dict) or 'layers' not in data:
        return None
    return data


def remember_paths(source_path='', destination_path=''):
    from qgis.core import QgsSettings

    settings = QgsSettings()
    if source_path:
        settings.setValue(KEY_LAST_SOURCE, source_path)
    if destination_path:
        settings.setValue(KEY_LAST_DESTINATION, destination_path)


def recall_paths():
    from qgis.core import QgsSettings

    settings = QgsSettings()
    return (settings.value(KEY_LAST_SOURCE, '') or '',
            settings.value(KEY_LAST_DESTINATION, '') or '')
