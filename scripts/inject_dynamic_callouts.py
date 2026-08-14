"""Inject dynamic callouts into the FieldNotebook comment label rules.

Rewrites the "Regolith Note" and "Fallback Labels (Comments/Labels)" rules
in the template's "1 - FieldNotebook" labeling so comment labels are
engine-arranged instead of pinned at a fixed offset:

    - OrderedPositionsAroundPoint placement: 8 candidate orientations.
    - dist=37.5 / maximumDistance=187.5 map units (1x / 5x the
      scale-5000 callout ring unit, callout_dist_for_scale): labels
      pushed further out only when closer spots are taken -> variable
      callout length, PreferCloser.
    - overlapHandling=AllowOverlapIfRequired: a label that truly cannot
      fit is drawn anyway instead of hidden - comments never vanish.
    - Callout enabled on both rules (grey dashed leader), minLength 1 MM
      so no stub is drawn when the label sits at its nominal ring.
    - The Fallback rule's fixed data-defined OffsetXY ('120,-60') is
      removed (inert under around-point placement).

Must stay in step with script_setmapping.build_structural_labeling(),
which regenerates this block when Set Mapping Scale runs; the values
here mirror apply_dynamic_comment_placement() at scale 5000 (the
template's symbologyReferenceScale).

Idempotent and re-runnable. The labeling block is parsed and edited with
ElementTree (this region of the QML jams tags onto shared lines, so
regex editing is unsafe); the first run therefore also normalises the
block's whitespace formatting - semantics are unchanged and validated.

Usage:  python scripts/inject_dynamic_callouts.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import copy
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

LAYER = "1 - FieldNotebook"
RULES = ("Regolith Note", "Fallback Labels (Comments/Labels)")

U = 37.5  # callout_dist_for_scale(5000) = 0.0075 * 5000 map units
PLACEMENT_ATTRS = {
    "placement": "6",              # OrderedPositionsAroundPoint
    "offsetType": "1",             # FromSymbolBounds
    "dist": "37.5",                # 1 x U
    "distUnits": "MapUnit",
    "maximumDistance": "187.5",    # 5 x U
    "maximumDistanceUnit": "MapUnit",
    "overlapHandling": "AllowOverlapIfRequired",
}
CALLOUT_OPTS = {
    "enabled": "1",
    "minLength": "1",
    "offsetFromAnchor": "0.5",
    "offsetFromLabel": "1",
}


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    row = cur.fetchone()
    if not row or not row[0]:
        bail(f"no styleQML for {LAYER!r}")
    qml = row[0]

    m = re.search(r'<labeling type="rule-based">.*?</labeling>', qml, re.S)
    if not m:
        bail("rule-based <labeling> block not found")
    lab = ET.fromstring(m.group(0))

    rules = {r.get("description"): r for r in lab.iter("rule")}
    missing = [d for d in RULES if d not in rules]
    if missing:
        bail(f"labeling rules not found: {missing}")

    fallback_callout = None
    for desc in RULES:
        settings = rules[desc].find("settings")
        placement = settings.find("placement")
        for k, v in PLACEMENT_ATTRS.items():
            if placement.get(k) != v:
                placement.set(k, v)
                print(f"{desc}: placement {k} -> {v}")

        callout = settings.find("callout")
        opts = {o.get("name"): o for o in callout.iter("Option") if o.get("name")}
        for k, v in CALLOUT_OPTS.items():
            if opts[k].get("value") != v:
                opts[k].set("value", v)
                print(f"{desc}: callout {k} -> {v}")

        if desc == "Fallback Labels (Comments/Labels)":
            fallback_callout = callout
            dd = settings.find("dd_properties")
            props = next((o for o in dd.iter("Option")
                          if o.get("name") == "properties"), None)
            offset_xy = next((o for o in props.iter("Option")
                              if o.get("name") == "OffsetXY"), None) \
                if props is not None else None
            if offset_xy is not None:
                props.remove(offset_xy)
                print(f"{desc}: dd OffsetXY removed")

    # Regolith's dormant callout still carries the old solid line symbol -
    # adopt the Fallback callout wholesale (same dashed grey leader).
    regolith_settings = rules["Regolith Note"].find("settings")
    regolith_callout = regolith_settings.find("callout")
    if ET.tostring(regolith_callout) != ET.tostring(fallback_callout):
        idx = list(regolith_settings).index(regolith_callout)
        regolith_settings.remove(regolith_callout)
        regolith_settings.insert(idx, copy.deepcopy(fallback_callout))
        print("Regolith Note: callout symbol adopted from Fallback")

    new_block = ET.tostring(lab, encoding="unicode")
    new_qml = qml[:m.start()] + new_block + qml[m.end():]

    # Validate BEFORE writing: never persist a QML that no longer parses.
    try:
        ET.fromstring(new_qml)
    except ET.ParseError as exc:
        bail(f"edited QML no longer parses, aborting without write: {exc}")

    if new_qml != qml:
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (new_qml, LAYER))
        assert cur.rowcount == 1
        con.commit()
        print("styleQML updated")
    else:
        print("already applied (no change)")

    # Validate: gpkg intact, QML parses, target config round-trips.
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    root = ET.fromstring(cur.fetchone()[0])
    print(f"QML parses: {LAYER}")

    checked = 0
    for rule in root.iter("rule"):
        if rule.get("description") not in RULES:
            continue
        settings = rule.find("settings")
        placement = settings.find("placement")
        for k, v in PLACEMENT_ATTRS.items():
            assert placement.get(k) == v, \
                f"{rule.get('description')}: {k}={placement.get(k)!r}, want {v!r}"
        opts = {o.get("name"): o.get("value")
                for o in settings.find("callout").iter("Option") if o.get("name")}
        for k, v in CALLOUT_OPTS.items():
            assert opts[k] == v, f"callout {k}={opts[k]!r}, want {v!r}"
        assert "OffsetXY" not in ET.tostring(settings.find("dd_properties"),
                                             encoding="unicode")
        checked += 1
    assert checked == 2, f"expected 2 rules verified, got {checked}"
    # Untouched rules keep their config.
    descs = {r.get("description") for r in root.iter("rule")}
    assert {"Dip Labels", "SymbolSuffix Labels"} <= descs
    print("round-trip ok: placement, callout, dd removal on both comment rules")
    con.close()


if __name__ == "__main__":
    main()
