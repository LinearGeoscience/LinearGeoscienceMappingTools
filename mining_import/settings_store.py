"""
Persisted importer preferences.

Profile-scoped via QgsSettings under LinearGeoscience/MiningImport/*, matching
the key convention in mainplugin.py. Remembering the last folder, output and
CRS is what turns a repeat import after a survey drop into two clicks.
"""

import json

from qgis.core import QgsSettings

PREFIX = 'LinearGeoscience/MiningImport'

KEY_LAST_FOLDER = PREFIX + '/lastFolder'
KEY_LAST_OUTPUT = PREFIX + '/lastOutput'
KEY_LAST_CRS = PREFIX + '/lastCrs'
KEY_POLICY = PREFIX + '/mergePolicy'
KEY_BACKUP = PREFIX + '/makeBackup'
KEY_DEEP_SCAN = PREFIX + '/deepScan'
KEY_CSV_PROFILES = PREFIX + '/csvProfiles'


def get(key, default=None, cast=None):
    value = QgsSettings().value(key, default)
    if value is None:
        return default
    if cast is bool:
        if isinstance(value, bool):
            return value
        return str(value).lower() in ('1', 'true', 'yes')
    if cast is not None:
        try:
            return cast(value)
        except (TypeError, ValueError):
            return default
    return value


def put(key, value):
    QgsSettings().setValue(key, value)


def csv_profiles():
    """{signature: mapping} of remembered column mappings.

    Keyed on header shape rather than filename: filenames vary per level, but
    a given total station's export layout does not.
    """
    raw = get(KEY_CSV_PROFILES, '')
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def save_csv_profile(signature, mapping):
    profiles = csv_profiles()
    profiles[signature] = mapping
    put(KEY_CSV_PROFILES, json.dumps(profiles, sort_keys=True))
