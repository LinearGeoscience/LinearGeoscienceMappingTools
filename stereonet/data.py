"""
Structure classification data and related constants for stereonet analysis.

This module contains all the structural geology classification codes and 
their corresponding types (planar/linear) used throughout the stereonet plugin.
"""

# Structure classification mapping: code -> type
# 'p'/'P' = planar, 'l'/'L' = linear
structure_classification = {
    "BAX": "l",
    "BO": "p",
    "CT": "P",
    "FAP": "P", "FAP1": "P", "FAP2": "P", "FAP3": "P", "FAP4": "P", "FAP5": "P", "FAPK": "P",
    "FAX": "L", "FAX1": "L", "FAX2": "L", "FAX3": "L", "FAX4": "L", "FAX5": "L", "FAXCR": "L", "FAXK": "L",
    "FAXSZ": "L",
    "FB": "p", "FCT": "p", "FO": "p", "FT": "p", "FTD": "p", "FTN": "p", "FTR": "p", "FTS": "p", "FTT": "p",
    "LAY": "p", "LME": "L", "LNI": "L", "LNISC": "L", "LNS": "L",
    "S0": "p", "S0T": "p", "S1": "p", "S2": "p", "S3": "p", "S4": "p", "S5": "p", "STR": "l",
    "SZB": "p", "SZC": "p", "SZCD": "p", "SZCN": "p", "SZCR": "p", "SZCS": "p", "SZS": "p",
    "VL": "p", "VN": "p", "VS": "p", "VT": "p", "VX": "p"
}


def normalize_structure_type(t):
    """
    Normalize structure type string to standard format.
    
    Args:
        t (str): Structure type ('p', 'P', 'l', 'L')
        
    Returns:
        str or None: 'plane' for planar structures, 'line' for linear structures,
                     None for unrecognized types
    """
    t = t.lower()
    if t == 'p':
        return 'plane'
    elif t == 'l':
        return 'line'
    return None


# Create normalized classification dictionary
normalized_classification = {}
for code, ctype in structure_classification.items():
    c = normalize_structure_type(ctype)
    if c:
        normalized_classification[code] = c

# Extract planar and linear codes from structure_classification
planar_codes = []
linear_codes = []

for code, ctype in structure_classification.items():
    ctype_lower = ctype.lower()
    if ctype_lower == 'p':
        planar_codes.append(code)
    elif ctype_lower == 'l':
        linear_codes.append(code)

# Ensure ALL codes in normalized_classification are properly categorized
for code, ctype in normalized_classification.items():
    if ctype == 'plane' and code not in planar_codes:
        planar_codes.append(code)
    elif ctype == 'line' and code not in linear_codes:
        linear_codes.append(code)