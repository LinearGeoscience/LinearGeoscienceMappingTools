"""Inject per-feature Weight scaling into the template's Linework/Overlay symbology.

Adds data-defined overrides so the "Weight" field (Major / Moderate / Minor)
scales every stroke width and marker/SVG size in a symbol:

    <static value> * CASE WHEN "Weight" = 'Major' THEN 1.5
                          WHEN "Weight" = 'Minor' THEN 0.5
                          ELSE 1 END

Moderate (or NULL) renders at the symbol's authored size; intervals, offsets
and dash patterns are deliberately NOT scaled (matches the pre-Weight
Major/Minor symbol convention).

Scope: every symbol in the "3 - Linework" renderer; only the Structure zone
symbols in "2 - Overlay" (infrastructure untouched).
Existing data-defined properties (e.g. the OverlayStrike-driven lineAngle on
zone hatches) are preserved.

Also injects "Intensity" (1-5) scaling into the Overlay Alteration/Weathering
stipple symbols: marker size grows and stipple spacing tightens with intensity
(3 or NULL = authored look). Weight is deliberately NOT applied to those
symbols - Intensity replaces it for alteration/weathering.

Idempotent and re-runnable: expressions are rebuilt from each layer's CURRENT
static values, so re-run this script after restyling symbols in QGIS to keep
the overrides in step with the new base sizes.

Usage:  python scripts/inject_weight_scaling.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from collections import Counter

FACTORS = {"Major": "1.5", "Minor": "0.5"}  # Moderate/NULL -> 1 (ELSE branch)

# static option name -> dd collection key, per symbol layer class
SCALED_PROPS = {
    "SimpleLine":   {"line_width": "outlineWidth"},
    "RasterLine":   {"line_width": "outlineWidth"},
    "SimpleMarker": {"size": "size", "outline_width": "outlineWidth"},
    "SvgMarker":    {"size": "size", "outline_width": "outlineWidth"},
    "FontMarker":   {"size": "size", "outline_width": "outlineWidth"},
    "SimpleFill":   {"outline_width": "outlineWidth"},
}

# Intensity (1-5) scaling for Overlay alteration/weathering symbols; 3/NULL -> authored look.
# The ramp is deliberately gentle: the wash opacity carries most of the signal so even
# Intensity 5 leaves the underlying mapping readable.
# Linear ramp: dot density is proportional to Intensity (spacing factor = sqrt(3/k),
# dot size constant), and wash alpha steps evenly (7,13,20,26,33).
INTENSITY_DIST_FACTORS = {"1": "1.732", "2": "1.225", "4": "0.866", "5": "0.775"}
INTENSITY_WASH_ALPHA = {"1": "7", "2": "13", "4": "26", "5": "33"}  # else 20 (= static)

# Structure-zone Weight ramp: Major is deliberately subtle (the old Moderate look),
# Moderate/Minor progressively lighter from there.
OVERLAY_ZONE_FACTORS = {"Major": "1.32", "Minor": "0.65"}

INTENSITY_PROPS = {
    "PointPatternFill": {"distance_x": "distanceX", "distance_y": "distanceY"},
    "SimpleFill": {"color": "fillColor"},
}

OVERLAY_ZONE_CODES = [
    "Fault Zone", "Shear Zone", "Breccia Zone", "Mylonite Zone",
    "Stockwork Zone", "Vein Array Zone", "Damage Zone", "Fold Hinge Zone",
    "Crackle Breccia Zone",
]


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def weight_expression(dd_key, base):
    try:
        if float(base) <= 0:
            return None
    except ValueError:
        return None
    return (f"{base} * CASE WHEN \"Weight\" = 'Major' THEN {FACTORS['Major']} "
            f"WHEN \"Weight\" = 'Minor' THEN {FACTORS['Minor']} ELSE 1 END")


def zone_weight_expression(dd_key, base):
    try:
        if float(base) <= 0:
            return None
    except ValueError:
        return None
    return (f"{base} * CASE WHEN \"Weight\" = 'Major' THEN {OVERLAY_ZONE_FACTORS['Major']} "
            f"WHEN \"Weight\" = 'Minor' THEN {OVERLAY_ZONE_FACTORS['Minor']} ELSE 1 END")


def intensity_expression(dd_key, base):
    if dd_key == "fillColor":
        parts = base.split(",")
        if len(parts) < 3:
            return None
        r, g, b = parts[0], parts[1], parts[2]
        branches = " ".join(f"WHEN \"Intensity\" = {k} THEN {v}"
                            for k, v in INTENSITY_WASH_ALPHA.items())
        return f"color_rgba({r},{g},{b}, CASE {branches} ELSE 33 END)"
    try:
        if float(base) <= 0:
            return None
    except ValueError:
        return None
    if dd_key not in ("distanceX", "distanceY"):
        return None
    branches = " ".join(f"WHEN \"Intensity\" = {k} THEN {v}"
                        for k, v in INTENSITY_DIST_FACTORS.items())
    return f"{base} * CASE {branches} ELSE 1 END"


def rebuild_dd_block(dd_xml, new_props):
    """Merge new_props {key: expression} into a <data_defined_properties> block."""
    root = ET.fromstring(dd_xml)
    outer = root.find("Option")
    if outer is None:
        outer = ET.SubElement(root, "Option", {"type": "Map"})
    props = None
    for opt in outer.findall("Option"):
        if opt.get("name") == "properties":
            props = opt
    if props is None:
        props = ET.SubElement(outer, "Option", {"name": "properties"})
    props.set("type", "Map")
    props.attrib.pop("value", None)
    existing = {opt.get("name"): opt for opt in props.findall("Option")}
    for key, expr in new_props.items():
        if key in existing:
            props.remove(existing[key])
        entry = ET.SubElement(props, "Option", {"name": key, "type": "Map"})
        ET.SubElement(entry, "Option", {"name": "active", "type": "bool", "value": "true"})
        ET.SubElement(entry, "Option", {"name": "expression", "type": "QString", "value": expr})
        ET.SubElement(entry, "Option", {"name": "type", "type": "int", "value": "3"})
    return ET.tostring(root, encoding="unicode")


def inject_into_scope(scope, stats, prop_map=SCALED_PROPS, expr_fn=weight_expression):
    """Process every <layer class=...> block inside the scope string."""
    out = []
    pos = 0
    layer_tags = list(re.finditer(r'<layer\b[^>]*\bclass="(\w+)"[^>]*>', scope))
    for i, lt in enumerate(layer_tags):
        cls = lt.group(1)
        dd_m = re.search(r'<data_defined_properties>.*?</data_defined_properties>',
                         scope[lt.end():], re.S)
        if not dd_m:
            continue
        statics_region = scope[lt.end():lt.end() + dd_m.start()]
        mapping = prop_map.get(cls, {})
        new_props = {}
        for static_name, dd_key in mapping.items():
            vm = re.search(r'<Option name="%s" type="QString" value="([^"]+)"' % static_name,
                           statics_region)
            if not vm:
                continue
            expr = expr_fn(dd_key, vm.group(1))
            if expr is None:
                continue
            new_props[dd_key] = expr
        if not new_props:
            continue
        dd_start = lt.end() + dd_m.start()
        dd_end = lt.end() + dd_m.end()
        out.append((dd_start, dd_end, rebuild_dd_block(scope[dd_start:dd_end], new_props)))
        for k in new_props:
            stats[f"{cls}.{k}"] += 1
    for s, e, repl in reversed(out):
        scope = scope[:s] + repl + scope[e:]
    return scope


def symbol_block(q, name):
    m = re.search(r'<symbol\b[^>]*\bname="%s"[^>]*>' % re.escape(name), q)
    if not m:
        bail(f"symbol {name!r} not found")
    depth = 0
    for t in re.finditer(r'<symbol\b|</symbol>', q[m.start():]):
        depth += 1 if t.group(0) == '<symbol' else -1
        if depth == 0:
            return m.start(), m.start() + t.end()
    bail(f"unbalanced symbol {name!r}")


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    # 3 - Linework: whole renderer
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name='3 - Linework'")
    qml = cur.fetchone()[0]
    rm = re.search(r'<renderer-v2\b.*?</renderer-v2>', qml, re.S)
    if not rm:
        bail("Linework renderer-v2 not found")
    stats = Counter()
    new_renderer = inject_into_scope(rm.group(0), stats)
    qml = qml[:rm.start()] + new_renderer + qml[rm.end():]
    cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name='3 - Linework'", (qml,))
    assert cur.rowcount == 1
    print("3 - Linework:", dict(stats))

    # 2 - Overlay: zone symbols only
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name='2 - Overlay'")
    qml = cur.fetchone()[0]
    stats = Counter()
    for code in OVERLAY_ZONE_CODES:
        cm = re.search(r'<category[^>]*value="%s"[^>]*/>' % re.escape(code), qml)
        if not cm:
            bail(f"Overlay category {code!r} not found")
        sym = re.search(r'symbol="(\d+)"', cm.group(0)).group(1)
        s, e = symbol_block(qml, sym)
        qml = qml[:s] + inject_into_scope(qml[s:e], stats,
                                          expr_fn=zone_weight_expression) + qml[e:]
    print("2 - Overlay zones:", dict(stats))

    # 2 - Overlay: Intensity scaling on Alteration/Weathering stipples
    stats = Counter()
    cur.execute("SELECT Code FROM OverlayCodes WHERE Type IN ('Alteration','Weathering')")
    stipple_codes = [r[0] for r in cur.fetchall()]
    if not stipple_codes:
        bail("no Alteration/Weathering codes found in OverlayCodes")
    for code in stipple_codes:
        cm = re.search(r'<category[^>]*value="%s"[^>]*/>' % re.escape(code), qml)
        if not cm:
            bail(f"Overlay category {code!r} not found")
        sym = re.search(r'symbol="(\d+)"', cm.group(0)).group(1)
        s, e = symbol_block(qml, sym)
        qml = qml[:s] + inject_into_scope(qml[s:e], stats, INTENSITY_PROPS,
                                          intensity_expression) + qml[e:]
    cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name='2 - Overlay'", (qml,))
    assert cur.rowcount == 1
    print(f"2 - Overlay intensity ({len(stipple_codes)} stipple symbols):", dict(stats))

    con.commit()
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    for layer in ["3 - Linework", "2 - Overlay"]:
        cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (layer,))
        ET.fromstring(cur.fetchone()[0])
        print(f"QML parses: {layer}")
    con.close()


if __name__ == "__main__":
    main()
