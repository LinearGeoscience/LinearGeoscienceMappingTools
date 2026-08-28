"""Bake the cross-layer label placement ladder.

At dense mapping scales labels from different layers fought for the same
space with near-uniform priorities, so the placement order was arbitrary
and lithology/annotation text landed on top of the structure lettering.
This bakes one explicit ladder (higher priority = wins space in PAL
conflict resolution):

    10  FieldNotebook "Dip Labels"       (unchanged - fixed, always drawn)
     8  FieldNotebook "SymbolSuffix"     (was 5)
     6  Basemap lithology                (inject_basemap_label_placement.py)
     5  Linework                         (unchanged)
     4  Overlay zones                    (was 5)
     3  FieldNotebook "Fallback" comments (was 5)
     2  FieldNotebook "Regolith Note"    (was 5)

plus two behaviour changes:

    - Linework overlapHandling PreventOverlap -> AllowOverlapIfRequired:
      a vein width like "20cm" is a measurement; it must slide along its
      line to the clearest spot and only overlap as a last resort, never
      silently vanish (user decision 2026-08-29).
    - every FieldNotebook rule's obstacleFactor 1 -> 2: structure
      lettering repels other layers' movable text harder than a default
      obstacle (the dip numbers themselves never move or hide).

Mirrors script_setmapping.py (build_structural_labeling / OBSTACLE_FACTOR):
any FieldNotebook value baked here but not built there is silently
reverted by the next Set Mapping Scale - tests/test_label_code_template_qgis.py
enforces the contract.

Untouched: label expressions, fonts, callouts, dd_properties (auxiliary
storage moves and injected Color/Size expressions), placement geometry,
renderers. Only individual XML attributes are edited, never whole blocks.

Run against BOTH Template/LGS_MappingTemplate.gpkg (default) and
Template/LGS_MappingTemplate_Patterns.gpkg (same reasoning as
inject_basemap_label_placement.py).

Idempotent and re-runnable; ElementTree edits with parse-validate before
write, per the established injector pattern.

Usage:  python scripts/inject_label_priority_ladder.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

OBSTACLE_FACTOR = "2"  # script_setmapping.OBSTACLE_FACTOR

# FieldNotebook: {rule description: {element: {attr: value}}}
FIELDNOTEBOOK_RULES = {
    "Dip Labels": {
        "rendering": {"obstacleFactor": OBSTACLE_FACTOR},
    },
    "SymbolSuffix Labels": {
        "placement": {"priority": "8"},
        "rendering": {"obstacleFactor": OBSTACLE_FACTOR},
    },
    "Fallback Labels (Comments/Labels)": {
        "placement": {"priority": "3"},
        "rendering": {"obstacleFactor": OBSTACLE_FACTOR},
    },
    "Regolith Note": {
        "placement": {"priority": "2"},
        "rendering": {"obstacleFactor": OBSTACLE_FACTOR},
    },
}
SIMPLE_LAYERS = {
    "2 - Linework": {
        "placement": {"overlapHandling": "AllowOverlapIfRequired",
                      "priority": "5"},
    },
    "3 - Overlay": {
        "placement": {"priority": "4"},
    },
}
FIELDNOTEBOOK = "1 - FieldNotebook"


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


def apply_attrs(settings, wanted, label):
    """Set individual attributes on named child elements of <settings>."""
    changed = False
    for elem_name, attrs in wanted.items():
        elem = settings.find(elem_name)
        if elem is None:
            bail(f"{label}: <{elem_name}> not found")
        for k, v in attrs.items():
            if elem.get(k) != v:
                elem.set(k, v)
                print(f"{label}: {elem_name} {k} -> {v}")
                changed = True
    return changed


def assert_attrs(settings, wanted, label):
    for elem_name, attrs in wanted.items():
        elem = settings.find(elem_name)
        for k, v in attrs.items():
            assert elem.get(k) == v, \
                f"{label}: {elem_name} {k}={elem.get(k)!r}, want {v!r}"


def edit_labeling(qml, kind, editor):
    """Run editor() over the layer's <labeling> block; return the new QML."""
    m = re.search(r'<labeling type="%s">.*?</labeling>' % kind, qml, re.S)
    if not m:
        bail(f'{kind} <labeling> block not found')
    lab = ET.fromstring(m.group(0))
    editor(lab)
    return qml[:m.start()] + ET.tostring(lab, encoding="unicode") + qml[m.end():]


def fieldnotebook_rules(lab):
    """{description: <settings> element} for every labelled rule."""
    found = {}
    for rule in lab.iter("rule"):
        desc = rule.get("description")
        settings = rule.find("settings")
        if desc and settings is not None:
            found[desc] = settings
    return found


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    def load(layer):
        cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                    (layer,))
        row = cur.fetchone()
        if not row or not row[0]:
            bail(f"no styleQML for {layer!r}")
        return row[0]

    def store(layer, qml, old):
        # Validate BEFORE writing: never persist a QML that no longer parses.
        try:
            ET.fromstring(qml)
        except ET.ParseError as exc:
            bail(f"{layer}: edited QML no longer parses, aborting: {exc}")
        if qml != old:
            cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                        (qml, layer))
            assert cur.rowcount == 1
            con.commit()
            print(f"{layer}: styleQML updated")
        else:
            print(f"{layer}: already applied (no change)")

    # FieldNotebook (rule-based)
    qml = load(FIELDNOTEBOOK)

    def edit_fn(lab):
        rules = fieldnotebook_rules(lab)
        missing = set(FIELDNOTEBOOK_RULES) - set(rules)
        if missing:
            bail(f"FieldNotebook rules not found: {sorted(missing)} "
                 f"(have {sorted(rules)})")
        for desc, wanted in FIELDNOTEBOOK_RULES.items():
            apply_attrs(rules[desc], wanted, desc)

    store(FIELDNOTEBOOK, edit_labeling(qml, "rule-based", edit_fn), qml)

    # Linework / Overlay (simple)
    for layer, wanted in SIMPLE_LAYERS.items():
        qml = load(layer)

        def edit_simple(lab, wanted=wanted, layer=layer):
            settings = lab.find("settings")
            if settings is None:
                bail(f"{layer}: labeling <settings> not found")
            apply_attrs(settings, wanted, layer)

        store(layer, edit_labeling(qml, "simple", edit_simple), qml)

    # Validate: gpkg intact, every QML parses, target attrs round-trip,
    # dd bindings and expressions undisturbed.
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])

    final = load(FIELDNOTEBOOK)
    ET.fromstring(final)
    lab = ET.fromstring(re.search(
        r'<labeling type="rule-based">.*?</labeling>', final, re.S).group(0))
    rules = fieldnotebook_rules(lab)
    for desc, wanted in FIELDNOTEBOOK_RULES.items():
        assert_attrs(rules[desc], wanted, desc)
    # Dip placement untouched: fixed data-defined offsets, top priority.
    dip = rules["Dip Labels"]
    assert dip.find("placement").get("priority") == "10"
    assert dip.find("placement").get("overlapHandling") == "AllowOverlapAtNoCost"
    dd = ET.tostring(dip.find("dd_properties"), encoding="unicode")
    assert "OffsetXY" in dd, "dip OffsetXY dd binding lost"

    for layer, wanted in SIMPLE_LAYERS.items():
        final = load(layer)
        ET.fromstring(final)
        settings = ET.fromstring(re.search(
            r'<labeling type="simple">.*?</labeling>', final, re.S).group(0)
        ).find("settings")
        assert_attrs(settings, wanted, layer)
        assert settings.find("text-style").get("fieldName"), \
            f"{layer}: label expression lost"
    print("round-trip ok: ladder priorities, overlap handling, obstacle factors")
    con.close()


if __name__ == "__main__":
    main()
