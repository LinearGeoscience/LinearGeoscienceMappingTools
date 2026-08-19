"""Retire Linework codes: table row, renderer category, symbol and SLD rule.

Codes accumulate. `Vein - Epidote` and `Vein - Mineralised` are rare enough in
practice that they cost more as pick-list clutter than they earn as options,
so they come out - the first time this template has removed a code with a
committed script. The Aug 2026 audit removed five (Dome, Basin, Formline -
Fine, Tenement Boundary, Fault - Geophysical) with throwaway scripts that were
never kept, which is why there was nothing to reuse here.

Four things have to go, together, or the layer is left inconsistent:

    LineworkCodes row       the pick list, desktop and QField
    <category>              the renderer class
    <symbol>                the artwork it pointed at, sub-symbols included
    <se:Rule>               the SLD twin

SYMBOLS ARE NOT RENUMBERED. Categories reference symbols by NAME, so a hole is
harmless, and the template already carries 21 of them (1, 3, 12, 13, 15, ...);
the Aug 2026 deletion left holes at 23/67/68/131 and moved no survivor. Every
injector allocates from max+1 and steps over the gaps.

SLD rules are matched on <ogc:Literal>, never on <se:Name>: 24 rules carry an
se:Name that is not a category value (Foliation Formline x10, Reverse Fault
x2, ...), so the name is not a key. One rule has no se:Name at all.

Removal is not reversible from here - features already typed with a retired
code keep their value and draw uncategorised. That is the deliberate choice
(the repo has no alias/retired map for code VALUES; data_import/fuzzy.py
documents the position that a retired code earns a human-confirmed suggestion,
not a silent alias).

Idempotent: a code already absent from all four places is reported and
skipped. A code present in some but not all of them aborts without writing -
that is a half-finished previous run, not something to guess at.

Usage:  python scripts/remove_linework_codes.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import shutil
import sqlite3
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

LAYER = "2 - Linework"
TABLE = "LineworkCodes"
BACKUP_DATE = "2026-08-19"
BACKUP_NAME = "LGS_MappingTemplate_pre-vein-code-removal_%s.gpkg" % BACKUP_DATE

# Code -> the Type it must belong to, asserted before deleting so a typo
# cannot take out a same-named row from another category.
CODES = {
    "Vein - Epidote": "Veins",
    "Vein - Mineralised": "Veins",
}


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def back_up(repo, gpkg):
    if os.path.abspath(gpkg) == os.path.abspath(
            os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")):
        dest = os.path.join(repo, "Template", "Backup", BACKUP_NAME)
    else:
        stem, ext = os.path.splitext(gpkg)
        dest = "%s_pre-vein-code-removal_%s%s" % (stem, BACKUP_DATE, ext)
    if not os.path.exists(dest):
        shutil.copy2(gpkg, dest)
    return dest


def refuse_if_open(gpkg):
    """Bail if QGIS still has the gpkg open.

    The -wal check MUST come first and MUST NOT be preceded by a connection of
    our own: connecting and closing cleanly checkpoints and DELETES the -wal,
    destroying the evidence.  QGIS holds layer_styles in memory and writes its
    own copy back on the next project save, so an edit under it vanishes.
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


def symbol_span(q, name):
    """Byte range of the balanced <symbol name="..."> block.

    Balanced, not regex-to-first-close: sub-symbols are <symbol> elements too
    (@95@1 lives inside symbol 95), and taking only up to the first </symbol>
    would sever the parent and leave the child behind.
    """
    m = re.search(r'<symbol\b[^>]*\bname="%s"[^>]*>' % re.escape(name), q)
    if not m:
        bail("symbol %r not found" % name)
    depth = 0
    for t in re.finditer(r'<symbol\b|</symbol>', q[m.start():]):
        depth += 1 if t.group(0) == '<symbol' else -1
        if depth == 0:
            return m.start(), m.start() + t.end()
    bail("unbalanced symbol %r" % name)


def category_match(renderer, code):
    return re.search(r'<category[^>]*\bvalue=%s[^>]*/>'
                     % re.escape(quoteattr(code)), renderer)


def sld_rule_for(sld, code):
    """The <se:Rule> whose filter literal is this code.

    Matched on <ogc:Literal> because <se:Name> is not a key here - see the
    module docstring.
    """
    needle = "<ogc:Literal>%s</ogc:Literal>" % escape(code)
    for m in re.finditer(r'<se:Rule>.*?</se:Rule>', sld, re.S):
        if needle in m.group(0):
            return m
    return None


def counts(cur, qml, sld):
    root = ET.fromstring(qml)
    renderer = root.find(".//renderer-v2")
    return {
        "rows": cur.execute("SELECT COUNT(*) FROM %s" % TABLE).fetchone()[0],
        "categories": len(renderer.find("categories")),
        "symbols": len(renderer.find("symbols")),
        "sld_rules": len(re.findall(r'<se:Rule>', sld)),
    }


def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default = os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail("gpkg not found: %s" % gpkg)
    if "_Patterns" in os.path.basename(gpkg):
        bail("that is the generated patterns template - remove the code from "
             "the live template and re-run inject_basemap_lith_patterns.py")

    refuse_if_open(gpkg)
    print("backed up to %s" % back_up(repo, gpkg))

    con = sqlite3.connect(gpkg)
    cur = con.cursor()
    row = cur.execute("SELECT styleQML, styleSLD FROM layer_styles "
                      "WHERE f_table_name=?", (LAYER,)).fetchone()
    if not row or not row[0]:
        bail("no styleQML for %r" % LAYER)
    qml, sld = row
    original = (qml, sld)
    before = counts(cur, qml, sld)

    rm = re.search(r'<renderer-v2\b.*?</renderer-v2>', qml, re.S)
    if not rm:
        bail("Linework renderer-v2 not found")
    renderer = rm.group(0)

    removed = []
    for code, code_type in sorted(CODES.items()):
        in_table = cur.execute(
            "SELECT COUNT(*) FROM %s WHERE Type=? AND Code=?" % TABLE,
            (code_type, code)).fetchone()[0]
        cat = category_match(renderer, code)
        rule = sld_rule_for(sld, code)
        present = [bool(in_table), cat is not None, rule is not None]

        if not any(present):
            print("%s: already removed" % code)
            continue
        if not all(present):
            bail("%s: half-removed already (table=%s category=%s sld=%s) - a "
                 "previous run stopped part way; fix by hand, not by guessing"
                 % (code, in_table, cat is not None, rule is not None))
        if in_table != 1:
            bail("%s: %d rows in %s, expected exactly 1"
                 % (code, in_table, TABLE))

        sym_name = re.search(r'symbol="(\d+)"', cat.group(0)).group(1)
        s, e = symbol_span(renderer, sym_name)
        # Symbol first, then the category: cutting the category first would
        # invalidate the span offsets computed above.
        renderer = renderer[:s] + renderer[e:]
        cat = category_match(renderer, code)      # re-find, offsets moved
        renderer = renderer[:cat.start()] + renderer[cat.end():]
        sld = sld[:rule.start()] + sld[rule.end():]
        cur.execute("DELETE FROM %s WHERE Type=? AND Code=?" % TABLE,
                    (code_type, code))
        if cur.rowcount != 1:
            bail("%s: delete removed %d rows" % (code, cur.rowcount))
        removed.append((code, sym_name))
        print("%s: row + category + symbol %s + SLD rule removed"
              % (code, sym_name))

    if not removed:
        con.rollback()
        print("nothing to do")
        con.close()
        return

    qml = qml[:rm.start()] + renderer + qml[rm.end():]

    # Validate BEFORE writing: never persist a QML that no longer parses.
    for name, blob in (("QML", qml), ("SLD", sld)):
        try:
            ET.fromstring(blob)
        except ET.ParseError as exc:
            bail("edited %s no longer parses, aborting without write: %s"
                 % (name, exc))

    if (qml, sld) != original:
        cur.execute("UPDATE layer_styles SET styleQML=?, styleSLD=? "
                    "WHERE f_table_name=?", (qml, sld, LAYER))
        if cur.rowcount != 1:
            bail("styleQML update hit %d rows" % cur.rowcount)
    con.commit()

    # --- Round-trip validation -------------------------------------------
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    row = cur.execute("SELECT styleQML, styleSLD FROM layer_styles "
                      "WHERE f_table_name=?", (LAYER,)).fetchone()
    qml, sld = row
    after = counts(cur, qml, sld)
    n = len(removed)
    for key in ("rows", "categories", "symbols", "sld_rules"):
        assert after[key] == before[key] - n, \
            "%s: %d -> %d, expected -%d" % (key, before[key], after[key], n)

    root = ET.fromstring(qml)
    renderer = root.find(".//renderer-v2")
    values = {c.get("value") for c in renderer.find("categories")}
    names = {s.get("name") for s in renderer.find("symbols")}
    used = {c.get("symbol") for c in renderer.find("categories")}
    for code, sym_name in removed:
        assert code not in values, "%s still a category" % code
        assert sym_name not in names, "symbol %s survived" % sym_name
        assert code not in qml, "%s still appears in the QML" % code
        assert escape(code) not in sld, "%s still appears in the SLD" % code
        assert not cur.execute(
            "SELECT 1 FROM %s WHERE Code=?" % TABLE, (code,)).fetchone(), \
            "%s still in %s" % (code, TABLE)
    # Nothing dangling either way - the point of not renumbering.
    assert used <= names, "categories point at missing symbols: %s" % (used - names)
    assert names <= used, "orphaned symbols left behind: %s" % (names - used)
    print("round-trip ok: %d code(s) removed; %s"
          % (n, ", ".join("%s %d->%d" % (k, before[k], after[k])
                          for k in ("rows", "categories", "symbols", "sld_rules"))))
    print("NOW: trim the same codes from inject_confidence_system.SOLID_CODES "
          "and inject_vein_generation_selvedge.LW_VEIN_CODES, then re-run the "
          "injector chain.")
    con.close()


if __name__ == "__main__":
    main()
