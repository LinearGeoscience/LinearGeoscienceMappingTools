"""Scale Linework dash patterns with the Weight tier.

Stroke widths have scaled with Weight since inject_weight_scaling.py
(Very Minor x0.3 .. Regional x2.25), but every dash array stayed a fixed
constant - a deliberate choice at the time ("intervals, offsets and dash
patterns are deliberately NOT scaled").  Reversed 29 Aug 2026 at the
user's request: a Regional fault at 5.1 pt still drew the 38;7 dash
tuned for its 2.26 pt base and read nearly solid, while a Very Minor
fault read as sparse hairline dots.  The 21 SOLID confidence codes
already behaved proportionally (their Inferred look is Qt's built-in
'dash', whose pattern is specified in units of the pen width), so this
also removes the inconsistency between the two confidence mechanisms.

Rule: a SimpleLine's dash scales with Weight iff its width does - i.e.
the layer already carries a Weight outlineWidth override.  In the live
template that is every dashed Linework stroke (94 layers), Point and MM
units alike (the factor is unitless).  Moderate/NULL keeps the authored
dash byte-for-byte, so default data renders pixel-identical.

Two shapes, both flat CASEs over precomputed literal strings (constant
parse cost - see the parser-nesting trap):

  * 62 static dashes (use_custom_dash="1"):  gain a dd customDash
        CASE WHEN "Weight" = 'Regional' THEN '85.5;15.75' ... ELSE '38;7' END
    The statics are untouched, so inject_linework_dash_order.py's
    re-run assertions on customdash/capstyle keep holding.  (A dd
    customDash applies even with use_custom_dash="0", but here the
    static stays "1" and the ELSE mirrors it - either way the authored
    look survives.)
  * 32 confidence flips (inject_confidence_system.py FLIP codes):  the
        CASE WHEN "Confidence" IN (...) THEN '<dash>' ELSE '100000;1' END
    becomes Confidence-outer / Weight-inner (6 branches); the inner
    ELSE keeps the authored dash for Moderate/NULL and the outer ELSE
    keeps MEGA_DASH unscaled (it is a solid stand-in - scaling it is
    pointless bytes).  Reaches the Shear Zone Boundary flip nested
    inside its wave GeometryGenerator like any other layer.

Dot patterns (the axial-trace 22;7;0.5;7 family, round caps) scale
proportionally with no floor: the rendered dot is dash element + cap
overhang (half the line width) and both terms scale by the same factor,
so the dot:line ratio is invariant and a Very Minor dot still renders
~0.6 Point.

Re-run interactions: inject_weight_scaling merges only outlineWidth /
size keys, preserving customDash; inject_confidence_system.apply_flip
skips any layer already carrying customDash + MEGA_DASH; capstyle and
tweak_dash_pattern_on_corners are pen-level statics the dash source
does not disturb.

Never point this at LGS_MappingTemplate_Patterns.gpkg - that file is
re-baked wholesale by inject_basemap_lith_patterns.py.

Idempotent and re-runnable: like inject_weight_scaling, expressions are
rebuilt from each layer's CURRENT customdash static (the flip layers
keep theirs - apply_flip never clears it), so re-run this script after
retuning a dash in inject_linework_dash_order.py or QGIS.  The run must
find exactly 94 dash-bearing strokes (62 static + 32 flips); a
byte-identical rebuild is a no-op.

Usage:
    python scripts/inject_dash_weight_scaling.py [path\\to\\file.gpkg]
"""

import os
import re
import shutil
import sqlite3
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inject_weight_scaling import FACTORS  # noqa: E402  (tiers can never drift)

LW = "2 - Linework"
MEGA_DASH = "100000;1"
INFERRED_TEST = "\"Confidence\" IN ('Inferred','Queried')"

EXPECT_STATIC = 62
EXPECT_FLIPS = 32

BACKUP_DATE = "2026-08-29"
BACKUP_NAME = "LGS_MappingTemplate_pre-dash-weight_%s.gpkg" % BACKUP_DATE

FLIP_RE = re.compile(
    r"^CASE WHEN \"Confidence\" IN \('Inferred','Queried'\) "
    r"THEN '([\d.;]+)' ELSE '100000;1' END$")


def bail(msg):
    raise SystemExit("ABORT: " + msg)


# ---------------------------------------------------------------------------
# Expression builders
# ---------------------------------------------------------------------------

def scaled_dash(dash, f):
    """"38;7", 2.25 -> "85.5;15.75"  (unitless factor, 3-decimal round)."""
    return ";".join("%g" % round(float(x) * f, 3) for x in dash.split(";"))


def dash_weight_case(dash):
    """Flat CASE over Weight; ELSE = authored (Moderate/NULL)."""
    branches = " ".join(
        "WHEN \"Weight\" = '%s' THEN '%s'" % (t, scaled_dash(dash, float(f)))
        for t, f in FACTORS.items())
    return "CASE %s ELSE '%s' END" % (branches, dash)


def flip_weight_case(dash):
    """Confidence-outer / Weight-inner; MEGA_DASH stays unscaled."""
    return ("CASE WHEN %s THEN %s ELSE '%s' END"
            % (INFERRED_TEST, dash_weight_case(dash), MEGA_DASH))


# ---------------------------------------------------------------------------
# File guards (shape from inject_linework_shear_wave.py)
# ---------------------------------------------------------------------------

def back_up(repo, gpkg):
    if os.path.abspath(gpkg) == os.path.abspath(
            os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")):
        dest = os.path.join(repo, "Template", "Backup", BACKUP_NAME)
    else:
        stem, ext = os.path.splitext(gpkg)
        dest = "%s_pre-dash-weight_%s%s" % (stem, BACKUP_DATE, ext)
    if not os.path.exists(dest):
        shutil.copy2(gpkg, dest)
    return dest


def refuse_if_open(gpkg):
    """Bail if QGIS still has the gpkg open (see inject_linework_shear_wave)."""
    if os.path.exists(gpkg + "-wal"):
        bail("%s has an active -wal alongside it, so something still has it "
             "open. Close the project in QGIS first." % os.path.basename(gpkg))
    try:
        con = sqlite3.connect(gpkg, timeout=1.0)
        con.execute("BEGIN IMMEDIATE")
        con.execute("ROLLBACK")
        con.close()
    except sqlite3.OperationalError as exc:
        bail("%s is locked (%s) - close the project in QGIS and re-run"
             % (os.path.basename(gpkg), exc))


# ---------------------------------------------------------------------------
# QML surgery (shapes from inject_confidence_system.py)
# ---------------------------------------------------------------------------

def simpleline_layers(scope):
    """Yield (start, end) for each complete SimpleLine <layer> block."""
    for lm in re.finditer(r'<layer\b[^>]*class="SimpleLine"[^>]*>', scope):
        depth = 0
        for t in re.finditer(r'<layer\b|</layer>', scope[lm.start():]):
            depth += 1 if t.group(0) == '<layer' else -1
            if depth == 0:
                yield lm.start(), lm.start() + t.end()
                break


def merge_dd_into_layer_xml(layer_xml, new_props):
    """Merge properties into the layer's dd block (string in, string out)."""
    ddm = re.search(r'<data_defined_properties>.*?</data_defined_properties>',
                    layer_xml, re.S)
    if not ddm:
        bail("layer without data_defined_properties")
    root = ET.fromstring(ddm.group(0))
    outer = root.find("Option")
    if outer is None:
        outer = ET.SubElement(root, "Option", {"type": "Map"})
    props = None
    for o in outer.findall("Option"):
        if o.get("name") == "properties":
            props = o
    if props is None:
        props = ET.SubElement(outer, "Option", {"name": "properties"})
    props.set("type", "Map")
    props.attrib.pop("value", None)
    existing = {o.get("name"): o for o in props.findall("Option")}
    for key, expr in new_props.items():
        if key in existing:
            props.remove(existing[key])
        entry = ET.SubElement(props, "Option", {"name": key, "type": "Map"})
        ET.SubElement(entry, "Option", {"name": "active", "type": "bool",
                                        "value": "true"})
        ET.SubElement(entry, "Option", {"name": "expression", "type": "QString",
                                        "value": expr})
        ET.SubElement(entry, "Option", {"name": "type", "type": "int",
                                        "value": "3"})
    return (layer_xml[:ddm.start()] + ET.tostring(root, encoding="unicode")
            + layer_xml[ddm.end():])


def dd_expressions(layer_xml):
    """{dd key: expression} for the layer's own dd block, unescaped."""
    ddm = re.search(r'<data_defined_properties>.*?</data_defined_properties>',
                    layer_xml, re.S)
    if not ddm:
        return {}
    out = {}
    root = ET.fromstring(ddm.group(0))
    outer = root.find("Option")
    if outer is None:
        return {}
    for props in outer.findall("Option"):
        if props.get("name") != "properties":
            continue
        for entry in props.findall("Option"):
            for o in entry.findall("Option"):
                if o.get("name") == "expression":
                    out[entry.get("name")] = o.get("value")
    return out


def statics_of(layer_xml):
    ddm = re.search(r'<data_defined_properties>', layer_xml)
    region = layer_xml[:ddm.start()] if ddm else layer_xml
    def val(name):
        m = re.search(r'name="%s" type="QString" value="([^"]*)"' % name,
                      region)
        return m.group(1) if m else None
    return val


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default = os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail("gpkg not found: %s" % gpkg)
    if "_Patterns" in os.path.basename(gpkg):
        bail("never point this at the Patterns gpkg - it is re-baked "
             "wholesale by inject_basemap_lith_patterns.py")

    refuse_if_open(gpkg)

    con = sqlite3.connect(gpkg)
    cur = con.cursor()
    row = cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                      (LW,)).fetchone()
    if not row or not row[0]:
        bail("no styleQML for %r" % LW)
    qml = row[0]

    rm = re.search(r'<renderer-v2\b.*?</renderer-v2>', qml, re.S)
    if not rm:
        bail("Linework renderer-v2 not found")
    renderer = rm.group(0)

    edits = []          # (start, end, replacement)
    n_static = n_flip = n_done = 0
    for s, e in simpleline_layers(renderer):
        lx = renderer[s:e]
        dd = dd_expressions(lx)
        val = statics_of(lx)
        custom = dd.get("customDash")
        authored = val("customdash")
        if custom is None and val("use_custom_dash") != "1":
            continue  # solid stroke (incl. the SOLID-code outlineStyle dd)
        if not authored or not re.match(r"^[\d.;]+$", authored):
            bail("dash-bearing layer with unusable customdash static %r"
                 % authored)
        if "outlineWidth" not in dd or '"Weight"' not in dd["outlineWidth"]:
            bail("dashed layer (customdash %r) without a Weight "
                 "outlineWidth - the dash-scales-iff-width-scales rule "
                 "has no answer here" % authored)
        if custom is not None and not FLIP_RE.match(custom)                 and '"Weight"' not in custom:
            bail("unrecognised customDash expression %r - neither the "
                 "confidence-flip shape nor already weight-scaled" % custom)
        is_flip = custom is not None and MEGA_DASH in custom
        target = (flip_weight_case(authored) if is_flip
                  else dash_weight_case(authored))
        if is_flip:
            n_flip += 1
        else:
            n_static += 1
        if custom == target:
            n_done += 1
            continue
        edits.append((s, e, merge_dd_into_layer_xml(lx,
                                                    {"customDash": target})))

    if (n_static, n_flip) != (EXPECT_STATIC, EXPECT_FLIPS):
        bail("found %d static + %d flip dash strokes; expected exactly "
             "(%d, %d) - the template is not in the shape this injector "
             "understands"
             % (n_static, n_flip, EXPECT_STATIC, EXPECT_FLIPS))
    if not edits:
        print("already applied: %d weight-scaled dashes - nothing to do"
              % n_done)
        con.close()
        return
    print("rebuilding %d dash ramp(s) (%d already current)"
          % (len(edits), n_done))

    for s, e, repl in reversed(edits):
        renderer = renderer[:s] + repl + renderer[e:]
    new_qml = qml[:rm.start()] + renderer + qml[rm.end():]

    try:
        ET.fromstring(new_qml)
    except ET.ParseError as exc:
        bail("edited QML no longer parses, aborting before write: %s" % exc)

    dest = back_up(repo, gpkg)
    print("backup: %s" % dest)

    cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                (new_qml, LW))
    assert cur.rowcount == 1
    con.commit()
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])

    # ---------------- round-trip validation ----------------------------
    q, = cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                     (LW,)).fetchone()
    con.close()
    rr = re.search(r'<renderer-v2\b.*?</renderer-v2>', q, re.S).group(0)
    scaled = flips = 0
    for s, e in simpleline_layers(rr):
        dd = dd_expressions(rr[s:e])
        custom = dd.get("customDash")
        if custom is None:
            continue
        assert '"Weight"' in custom, "unscaled customDash survived"
        scaled += 1
        if MEGA_DASH in custom:
            flips += 1
            assert custom.startswith("CASE WHEN %s THEN " % INFERRED_TEST)
    assert scaled == EXPECT_STATIC + EXPECT_FLIPS, scaled
    assert flips == EXPECT_FLIPS, flips
    print("done: %d static dashes + %d confidence flips now scale with "
          "Weight" % (EXPECT_STATIC, EXPECT_FLIPS))


if __name__ == "__main__":
    main()
