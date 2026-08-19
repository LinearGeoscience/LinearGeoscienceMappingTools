"""One grammar for every map label, so a value says what it belongs to.

Labels grew a value at a time, each addition appended with a space, until a
vein read

    10cm Brt slv 10cm Afs

- two widths and two minerals with nothing binding a value to the thing it
measures.  The grammar is now:

    group        := [measurement] item[-item...]
    named group  := Name: group
    label        := group[, group...][?]
    item         := CODE[(value)]

so the same vein reads `10cm Brt, Slv: 10cm Afs`, and with everything
recorded, `V2 10cm Qz(60%)-Py(5%), Slv: 10cm Afs, lens?`.

WHAT THIS SCRIPT OWNS

  1. The `2 - Linework` label ASSEMBLY.  The pieces still belong to the
     injectors that made them - WIDTH_TEXT to inject_linework_vein_fields,
     the mineral tokens to inject_linework_mineral_pcts, the generation and
     selvedge to inject_vein_generation_selvedge, the detail-scope gate to
     inject_linework_detail_scope, the Confidence '?' to
     inject_confidence_system - and every one is embedded here VERBATIM,
     which is what keeps those five injectors idempotent and their pinned
     counts intact.  Only the joining changed: the flat space-separated
     array became a nested one, so the vein's own group is a single element
     and the selvedge is a named group beside it.

  2. Two branches of the `3 - Overlay` label, which no script owned - they
     were authored by hand in QGIS and baked:
       - Mineralisation: `Stringer Zone Gn 12%` -> `Stringer Zone, Gn(12%)`
         (the constant lives in inject_overlay_mineralisation and is
         imported, so the two cannot drift).
       - the ELSE branch, which was a raw three-way concat and emitted two
         TRAILING BLANK LINES on every Weathering and Infrastructure
         polygon - `Oxidised\\n\\n`.  Now a joined array, so it prints
         `Oxidised`.  Structure and Mineralisation also stop silently
         discarding SubType2/SubType3.

  `4 - Basemap` is NOT here: its label is owned wholesale by
  inject_basemap_mineral_pcts.py, so its grammar changes are made there and
  replayed through the documented chain instead.

Overlay is plain text - that layer has allowHtml=0, so none of the Basemap
div/span weight-splitting is available.

Run order: AFTER inject_confidence_system (its '?' has to be the last
term already) and BEFORE inject_vein_generation_selvedge - this script
INSTALLS the current generation and selvedge fragments into the Linework
label, so the selvedge injector finds them there and no-ops rather than
splicing an old wording back in.  Then inject_label_cartography, then
inject_label_size_scaling.

Idempotent and re-runnable; every expression is checked for balanced quotes
and brackets, and the QML is parse-validated BEFORE anything is written.

Usage:  python scripts/inject_label_grammar.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import shutil
import sqlite3
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inject_linework_mineral_pcts as _lw_min       # noqa: E402
import inject_linework_vein_fields as _lw_vein       # noqa: E402
import inject_linework_detail_scope as _lw_scope     # noqa: E402
import inject_vein_generation_selvedge as _slv       # noqa: E402
import inject_confidence_system as _conf             # noqa: E402
import inject_overlay_mineralisation as _ovl_min     # noqa: E402

LW = "2 - Linework"
OVL = "3 - Overlay"
BACKUP_DATE = "2026-08-19"
BACKUP_NAME = "LGS_MappingTemplate_pre-label-grammar_%s.gpkg" % BACKUP_DATE

GROUP_SEP = ", "        # between groups
ITEM_SEP = " "          # within a group, measurement then items

# --- 2 - Linework ----------------------------------------------------------
# The vein's own group: generation, then width, then the mineral assemblage.
# Width leads because that is how the team writes it on paper ("10cm HYV GA
# vn 5%"), and because a group carries at most one measurement, so nothing
# in it can be mistaken for anything else.
LW_VEIN_GROUP = (
    "array_to_string(array_remove_all(array(%s, %s, %s), ''), '%s')"
    % (_slv.LW_GEN_TEXT, _lw_vein.WIDTH_TEXT, _lw_min.NEW_MINERALS_TEXT,
       ITEM_SEP))

# The whole tag: the vein group, the named selvedge group, then whatever the
# geologist typed.  array_remove_all drops the empties, so a fault with only
# a width and a name renders '2m, F1' and a bare formline renders 'S1'.
LW_LABEL = (
    "CASE WHEN %s THEN array_to_string(array_remove_all(array(%s, %s, %s), "
    "''), '%s') ELSE \"Label\" END || %s"
    % (_lw_scope.DETAIL_VIS, LW_VEIN_GROUP, _slv.LW_SLV_TEXT,
       "coalesce(\"Label\",'')", GROUP_SEP, _conf.QUERIED_SUFFIX))

# --- 3 - Overlay -----------------------------------------------------------
# Subtypes chain with '-' the way mineral assemblages do on the other two
# layers.  Owned by inject_overlay_mineralisation (the only script that owns
# an Overlay branch) and imported, so the branches cannot drift apart.
#
# Four of the 125 Alteration codes contain a space and two contain a hyphen
# ('Skarn - Prograde'), so a chained pair of those reads a little oddly -
# renaming the codes would break existing project data for a cosmetic gain
# in a rare combination, so it is left alone.
OVL_SUBTYPES = _ovl_min.SUBTYPES

# The branch that had no grammar at all.  concat() does not drop its
# separators when an argument is empty, so `concat(S1,'\n',S2,'\n',S3)` on a
# Weathering polygon with one subtype emitted 'Oxidised' followed by two
# blank lines - which is why Overlay labels sat high in their polygons.
OVL_OLD_ELSE = "ELSE concat(\"SubType1\",'\\n',\"SubType2\",'\\n',\"SubType3\") END"
OVL_NEW_ELSE = "ELSE %s END" % OVL_SUBTYPES

# Structure and Mineralisation read SubType1 only and silently drop anything
# recorded in SubType2/3.  Alteration already chains all three; these two
# now do the same.
OVL_EDITS = [
    # Alteration already chained all three subtypes, but by its own hand-built
    # coalesce/nullif route.  Point it at the shared chain so one expression
    # does not say the same thing two ways.
    ("Alteration uses the shared subtype chain",
     "WHEN \"Type\" = 'Alteration' THEN \"SubType1\" || "
     "coalesce('-' || nullif(\"SubType2\",''), '') || "
     "coalesce('-' || nullif(\"SubType3\",''), '') || ' ('",
     "WHEN \"Type\" = 'Alteration' THEN %s || ' ('" % OVL_SUBTYPES),
    ("Structure honours SubType2/3",
     "WHEN \"Type\" = 'Structure' THEN \"SubType1\" || ' ('",
     "WHEN \"Type\" = 'Structure' THEN %s || ' ('" % OVL_SUBTYPES),
    # One edit for the whole Mineralisation branch, replaced by the constant
    # that owns it - so this script cannot describe it differently.
    ("Mineralisation binds its mineral and percent",
     "WHEN \"Type\" = 'Mineralisation' THEN \"SubType1\" || "
     "coalesce(' ' || nullif(\"Mineral1\",''), '') || "
     "CASE WHEN coalesce(\"Percent\", 0) > 0 THEN ' ' || \"Percent\" || '%' "
     "ELSE '' END",
     _ovl_min.NEW_LABEL_BRANCH),
    ("Weathering and Infrastructure stop emitting blank lines",
     OVL_OLD_ELSE, OVL_NEW_ELSE),
]


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def back_up(repo, gpkg):
    if os.path.abspath(gpkg) == os.path.abspath(
            os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")):
        dest = os.path.join(repo, "Template", "Backup", BACKUP_NAME)
    else:
        stem, ext = os.path.splitext(gpkg)
        dest = "%s_pre-label-grammar_%s%s" % (stem, BACKUP_DATE, ext)
    if not os.path.exists(dest):
        shutil.copy2(gpkg, dest)
    return dest


def refuse_if_open(gpkg):
    """Bail if QGIS still has the gpkg open.

    The -wal check MUST come first and MUST NOT be preceded by a connection
    of our own: connecting and closing cleanly checkpoints and DELETES the
    -wal.  QGIS holds layer_styles in memory and writes its own copy back on
    the next project save, so an edit made underneath it vanishes.
    """
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


def well_formed(expr, where):
    """Cheap structural check on an expression we assembled.

    Not a parser - this script deliberately runs without QGIS - but it
    catches the class of mistake that matters here: an unbalanced bracket or
    quote from splicing fragments together.  A malformed expression is
    dropped by QGIS in SILENCE, leaving the label blank.
    """
    if expr.count("'") % 2:
        bail("%s: odd number of single quotes" % where)
    depth = 0
    quoted = False
    for ch in expr:
        if ch == "'":
            quoted = not quoted
        elif not quoted:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    bail("%s: a ')' closes nothing" % where)
    if depth:
        bail("%s: %d bracket(s) left open" % (where, depth))


def text_style(qml, where):
    lm = re.search(r'<labeling type="simple">.*?</labeling>', qml, re.S)
    if not lm:
        bail("%s: simple labeling block not found" % where)
    lab = ET.fromstring(lm.group(0))
    ts = lab.find(".//text-style")
    if ts is None or ts.get("isExpression") != "1":
        bail("%s: label is not an expression - has its owner run?" % where)
    return lm, lab, ts


def write_back(qml, lm, lab):
    return qml[:lm.start()] + ET.tostring(lab, encoding="unicode") + qml[lm.end():]


def apply_linework(qml):
    lm, lab, ts = text_style(qml, LW)
    if ts.get("fieldName") == LW_LABEL:
        print("  %s: already applied" % LW)
        return qml, False
    expr = ts.get("fieldName")
    # Every contribution must already be in the expression, or the injector
    # that owns it has not run and we would be silently dropping it.
    #
    # Checked by the FIELD each one reads, not by the fragment's own text:
    # this script exists precisely because some of those fragments changed
    # wording, so matching them verbatim would fail on the very run that is
    # meant to install the new wording.  The field is the stable part.
    for name, marker in (("detail scope", '"Category" IN'),
                         ("width", '"Width_cm"'),
                         ("minerals", '"Mineral1Pct"'),
                         ("generation", '"VeinGen"'),
                         ("selvedge", '"SelvedgeMineral"'),
                         ("confidence", '"Confidence"')):
        if marker not in expr:
            bail("%s: nothing in the current label reads %s, so the %s "
                 "injector has not run - it would be lost here"
                 % (LW, marker, name))
    ts.set("fieldName", LW_LABEL)
    print("  %s: groups re-joined (%r between groups, %r within one)"
          % (LW, GROUP_SEP, ITEM_SEP))
    return write_back(qml, lm, lab), True


def apply_overlay(qml):
    lm, lab, ts = text_style(qml, OVL)
    expr = ts.get("fieldName")
    done = [name for name, _old, new in OVL_EDITS if new in expr]
    if len(done) == len(OVL_EDITS):
        print("  %s: already applied" % OVL)
        return qml, False
    if done:
        bail("%s: partial prior state - %d of %d edits already present (%s); "
             "not writing" % (OVL, len(done), len(OVL_EDITS), ", ".join(done)))
    for name, old, new in OVL_EDITS:
        if expr.count(old) != 1:
            bail("%s: %r matches %d times, expected 1 - the baked expression "
                 "is not in the shape this script was written against"
                 % (OVL, name, expr.count(old)))
        expr = expr.replace(old, new, 1)
    # The Confidence suffix must stay the final || term, or a re-run of
    # inject_confidence_system appends a second '?'.
    if not expr.rstrip().endswith(_conf.QUERIED_SUFFIX):
        bail("%s: the Confidence suffix is no longer last" % OVL)
    ts.set("fieldName", expr)
    print("  %s: %d branch edits applied" % (OVL, len(OVL_EDITS)))
    return write_back(qml, lm, lab), True


def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default = os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail("gpkg not found: %s" % gpkg)
    if "_Patterns" in os.path.basename(gpkg):
        bail("that is the generated patterns template - edit the live one and "
             "re-run inject_basemap_lith_patterns.py")

    well_formed(LW_LABEL, "assembled Linework label")
    well_formed(OVL_NEW_ELSE, "assembled Overlay ELSE branch")

    refuse_if_open(gpkg)
    print("backed up to %s" % back_up(repo, gpkg))

    con = sqlite3.connect(gpkg)
    cur = con.cursor()
    changed = False
    for layer, apply in ((LW, apply_linework), (OVL, apply_overlay)):
        row = cur.execute("SELECT styleQML FROM layer_styles "
                          "WHERE f_table_name=?", (layer,)).fetchone()
        if not row or not row[0]:
            bail("no styleQML for %r" % layer)
        qml, did = apply(row[0])
        if not did:
            continue
        try:
            ET.fromstring(qml)
        except ET.ParseError as exc:
            bail("%s: edited QML no longer parses, aborting without write: %s"
                 % (layer, exc))
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, layer))
        if cur.rowcount != 1:
            bail("%s: update hit %d rows" % (layer, cur.rowcount))
        changed = True
    con.commit()

    # --- Round-trip validation -------------------------------------------
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])

    root = ET.fromstring(cur.execute(
        "SELECT styleQML FROM layer_styles WHERE f_table_name=?",
        (LW,)).fetchone()[0])
    got = root.find(".//labeling/settings/text-style").get("fieldName")
    assert got == LW_LABEL, "Linework label did not round-trip"
    assert got.rstrip().endswith(_conf.QUERIED_SUFFIX), \
        "the Confidence suffix must stay the last || term"
    # The fragments the other injectors look for on re-run.
    for name, frag in (("detail scope", _lw_scope.DETAIL_VIS),
                       ("width", _lw_vein.WIDTH_TEXT),
                       ("generation", _slv.LW_GEN_TEXT),
                       ("selvedge", _slv.LW_SLV_TEXT)):
        assert frag in got, "%s fragment lost" % name
    for n in (1, 2, 3):
        assert got.count(_lw_min.mineral_piece(n)) == 1, \
            "mineral %d token is not present exactly once" % n

    root = ET.fromstring(cur.execute(
        "SELECT styleQML FROM layer_styles WHERE f_table_name=?",
        (OVL,)).fetchone()[0])
    got = root.find(".//labeling/settings/text-style").get("fieldName")
    for name, _old, new in OVL_EDITS:
        assert new in got, "Overlay edit %r did not stick" % name
    assert "concat(" not in got, "the raw concat survived - blank lines remain"
    assert _ovl_min.NEW_LABEL_BRANCH in got, \
        "inject_overlay_mineralisation.NEW_LABEL_BRANCH no longer matches the " \
        "template - update that constant in lockstep"
    assert _ovl_min.OLD_LABEL_TAIL in got, \
        "inject_overlay_mineralisation.OLD_LABEL_TAIL no longer matches - it " \
        "is the anchor that script splices against, update it in lockstep"
    assert "'Alteration'" in got, \
        "inject_overlay_label_placement.py asserts this literal survives"
    print("round-trip ok: %s"
          % ("both layers rewritten" if changed else "no change"))
    con.close()


if __name__ == "__main__":
    main()
