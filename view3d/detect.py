"""
Pure-python DEM choice heuristics for the 3D view.

No qgis imports. The qgis adapter (view3d/terrain.py) builds plain row
dicts off the project's rasters and feeds them here, so the preference
ladder stays unit-testable without QGIS (same split as z_filter/detect.py).

A row is {'id': str, 'name': str, 'role': str, 'tied': bool}:
  role  layer custom property 'lgs/dem_role' ('' when unset; 'pit' is
        written by Pit Surface to DEM and by an explicit user pick)
  tied  True when the raster has a Z-filter elevation tie (an existing
        pit signal — per-bench imagery is registered there)
"""

# Name tokens marking a raster as a pit / as-built surface rather than
# regional topography. Matched case-insensitively as substrings.
PIT_TOKENS = ('pit', 'bench', 'asbuilt', 'as_built', 'as-built',
              'eom', 'end_of_month', 'drone', 'survey')

# Rasters DERIVED from a DEM. They are single-band and numeric, so nothing
# but the name gives them away — and a hillshade used as terrain would
# render 0-255 "metres" of nonsense relief. Orthophotos are excluded by
# band count instead (see is_dem_candidate).
DERIVED_TOKENS = ('hillshade', 'shaded_relief', 'shadedrelief', 'slope',
                  'aspect', 'roughness', 'ruggedness', 'contour')

ROLE_PIT = 'pit'


def is_dem_candidate(row):
    """Could this raster be terrain at all?

    Multi-band rasters are imagery (an RGB/RGBA orthophoto has no single
    elevation per pixel), and DEM derivatives are not elevation either.
    A role stamp overrides both — an explicit pick beats a guess.
    """
    if row.get('role') == ROLE_PIT:
        return True
    if (row.get('bands') or 1) > 1:
        return False
    name = (row.get('name') or '').lower()
    return not any(token in name for token in DERIVED_TOKENS)


def classify(row):
    """'pit' or 'regional' for one row."""
    if row.get('role') == ROLE_PIT or row.get('tied'):
        return 'pit'
    name = (row.get('name') or '').lower()
    if any(token in name for token in PIT_TOKENS):
        return 'pit'
    return 'regional'


def choose_dem(rows, pinned_id=None):
    """Pick the DEM the 3D view should use, or explain why it can't.

    Returns (row_or_None, reason):
      'pinned'     the user's persisted pick still exists
      'role'       exactly one role-stamped pit surface
      'pit'        exactly one pit-classified candidate
      'single'     only one local raster in the project
      'ambiguous'  several equally plausible candidates -> user picks
      'none'       no local rasters at all

    Preference ladder: pinned > role-stamped > pit-classified > the only
    raster. Pit beats regional because pit mapping is the case where the
    wrong DEM is useless. Ambiguity never guesses (fuzzy-never-decides).
    """
    # A pinned pick wins even if it would otherwise be filtered out: the
    # user has overruled the heuristic on purpose.
    for row in rows:
        if pinned_id and row.get('id') == pinned_id:
            return row, 'pinned'
    rows = [r for r in rows if is_dem_candidate(r)]
    if not rows:
        return None, 'none'
    stamped = [r for r in rows if r.get('role') == ROLE_PIT]
    if len(stamped) == 1:
        return stamped[0], 'role'
    if len(stamped) > 1:
        return None, 'ambiguous'
    pits = [r for r in rows if classify(r) == 'pit']
    if len(pits) == 1:
        return pits[0], 'pit'
    if len(pits) > 1:
        return None, 'ambiguous'
    if len(rows) == 1:
        return rows[0], 'single'
    return None, 'ambiguous'


def default_mode(chosen_row):
    """Initial view mode for the chosen DEM: pit surfaces open in Pit."""
    if chosen_row is not None and classify(chosen_row) == 'pit':
        return 'pit'
    return 'surface'
