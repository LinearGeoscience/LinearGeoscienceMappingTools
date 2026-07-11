"""Profile-aware settings for the Linear Geoscience plugin.

QgsSettings behaves like QSettings but stores per QGIS user profile. Existing
values were written with a bare QSettings() (shared across profiles); a
one-time migration copies them into the current profile so nothing is lost.
"""

from qgis.PyQt.QtCore import QSettings
from qgis.core import QgsSettings

# Marker so the copy only runs once per profile.
_MIGRATED_KEY = "LinearGeoscience/settingsMigratedV1"

# Keys previously written with a bare QSettings(). Kept verbatim so the only
# thing that changes is the storage backend (profile-aware).
_MIGRATE_KEYS = [
    "LinearGeoscience/lastPage",
    "LinearGeoscience/dialogGeometry",
    "LinearGeoscience/lastExportDir",
    "LinearGeosciencePlugin/MapCleaning/tightness",
    "LinearGeosciencePlugin/MapCleaning/tolerance",
    "LinearGeosciencePlugin/MapCleaning/max_segments",
    "LinearGeosciencePlugin/MapCleaning/spline_type",
    "LinearGeosciencePlugin/MapCleaning/min_sliver_area",
    "LinearGeosciencePlugin/MapCleaning/sliver_snap_tolerance",
]


def migrate_qsettings_once():
    """Copy legacy bare-QSettings values into the current QGIS profile once.

    Non-destructive: existing profile values win and the old values are left
    in place. Safe to call on every plugin load.
    """
    qs = QgsSettings()
    if qs.value(_MIGRATED_KEY, False, type=bool):
        return
    legacy = QSettings()
    for key in _MIGRATE_KEYS:
        if qs.contains(key):
            continue  # already set for this profile
        val = legacy.value(key)
        if val is not None:
            qs.setValue(key, val)
    qs.setValue(_MIGRATED_KEY, True)
