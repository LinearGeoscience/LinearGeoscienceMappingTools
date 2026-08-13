"""
Surpac description-field ("d-field") layouts, shared by the readers.

A site's Surpac exports use different d-field layouts for different kinds of
data, so there is no single universal mapping. The two seen in real exports:

    string  (6 fields)  survey pickup / floor strings
    station (15 fields) survey-control database export

The same layouts appear in the CSV exports of the same data — `mga_all_stations.csv`
carries literal `d1..d15` column headers — which is why this lives here rather
than inside formats/surpac.py: readers must not import each other.

Getting the profile wrong is cosmetic, never lossy. Every d-field is also
stored under its positional `D<n>` key, so the raw export survives verbatim in
the Attributes JSON column and a mis-detection leaves data un-promoted rather
than destroyed. The dialog's "Import as" override re-reads the file with the
other profile.

Pure python — stdlib only.
"""

PROFILE_STRING = 'string'
PROFILE_STATION = 'station'

# A None entry means "keep in Attributes JSON only": d7 is always 0.000 and
# d11-d14 are padding in the station layout.
D_FIELDS = {
    PROFILE_STRING: ('PointId', 'SurveyDate', 'Surveyor', 'Instrument',
                     'InstrSerial', 'JobCode'),
    PROFILE_STATION: ('PointId', 'SurveyDate', 'Level', 'Domain', 'SetupCode',
                      'LocalRL', None, 'Bearing', 'Surveyor', 'ObsDate',
                      None, None, None, None, 'SurveyType'),
}

# d4 of the station layout is the mine domain, and it is the cheapest positive
# signal that a file uses that layout rather than the string one.
DOMAIN_TOKENS = ('ug', 'surf', 'oc', 'op', 'underground', 'surface')

# Below this many d-fields a record cannot be the 15-field station layout.
_STATION_MIN_FIELDS = 10


def looks_like_level(value):
    """True for a plausible level label: '1182', '1200', 'SURF', 'OP2'.

    Guards the promotion of d3 to Level — an implausible value stays in D3 and
    leaves the filename-derived level in place rather than replacing it with
    noise.
    """
    if not value:
        return False
    text = str(value).strip()
    if not text or len(text) > 12:
        return False
    if text.replace('.', '', 1).isdigit():
        return True
    return text.isalnum() and len(text) <= 6


def detect_profile(counts):
    """Pick the layout from the shape of a file's records.

    counts: [(d_field_count, d4_value)] over real records.

    Uses the MODAL count so the handful of ragged records in a real export
    (three surface points carry 4 d-fields where the other 99 carry 15) cannot
    swing the decision.
    """
    lengths = [c for c, _d4 in counts]
    if not lengths:
        return PROFILE_STRING
    modal = max(set(lengths), key=lengths.count)
    if modal < _STATION_MIN_FIELDS:
        return PROFILE_STRING
    domains = [(d4 or '').strip().lower()
               for c, d4 in counts if c >= _STATION_MIN_FIELDS]
    if domains and sum(1 for d in domains if d in DOMAIN_TOKENS) >= \
            len(domains) * 0.5:
        return PROFILE_STATION
    return PROFILE_STRING


def parse(fields, profile=PROFILE_STRING):
    """Map trailing description fields to named attrs.

    Every field is kept under its positional 'D<n>' key as well as any named
    one. Empty fields are dropped rather than stored as '', so a sparse record
    does not overwrite a populated one when attrs are merged.
    """
    names = D_FIELDS.get(profile, D_FIELDS[PROFILE_STRING])
    attrs = {}
    for index, value in enumerate(fields):
        value = (value or '').strip()
        if not value:
            continue
        attrs['D{0}'.format(index + 1)] = value
        named = names[index] if index < len(names) else None
        if not named:
            continue
        if named == 'Level' and not looks_like_level(value):
            continue
        attrs[named] = value
    return attrs
