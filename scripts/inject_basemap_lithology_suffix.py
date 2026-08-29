"""A free-text suffix on the Basemap label, drawn on its own line.

The Basemap layer has carried a LithologyPrefix since long before the
injectors: TEXT(100), rendered hard against the front of the unit code as
'* H-FGR'.  There has never been an equivalent at the other end.  Comments
exists but never reaches the map, and UncodedLithology REPLACES the whole
label rather than adding to it, so a mapper who wanted to hang a sentence
off a coded unit - 'sheared and boudinaged, strong limonite on joints' -
had nowhere to put it that a reader would ever see.

    LithologySuffix   TEXT(500)   free text, single-line TextEdit

500 characters comes from the column width and nothing else: QML carries no
length option, so QGIS takes the cap straight from the OGR field.  It is the
same width Comments, UncodedLithology and Description already use.

IT IS A LINE, NOT A TOKEN.  The prefix is part of the unit's name and reads
as one word with it; a suffix long enough to be a sentence cannot be, so it
drops below both lithology lines and wears the same brackets, italic and
70% size the mineral/texture parentheticals wear.  That lettering already
means 'aside' on this layer, which is exactly what this is.

It is appended OUTSIDE the UncodedLithology override, so an uncoded feature
keeps its note.

Run order:

    inject_basemap_mineral_pcts.py    owns the Basemap label wholesale.  If
                                      it is ever re-run, this script must be
                                      re-run after it (with the rest of the
                                      replay chain) or the suffix line is
                                      dropped.
    inject_label_cartography.py       run BEFORE this script.  Order is not
                                      load-bearing - see MARKUP below - but
                                      keeping it means weight_split() only
                                      ever sees the shape it authored.
    inject_basemap_lithology_suffix.py   <- this script
    inject_basemap_lith_patterns.py   re-bakes LGS_MappingTemplate_Patterns.gpkg

MARKUP - two literals here are load-bearing.  inject_label_cartography
counts the label's own markup to decide whether it has already run, and the
golden-table test asserts the same contract:

  * the suffix div MUST carry a style attribute.  cartography's DIV is the
    bare literal "'<div>'" and test_label_grammar_qgis asserts no plain
    <div> survived the weight split.  '<div style="...">' does not contain
    it, so the count stays at N_DIV = 3.
  * the italic style MUST be the font-weight:400 variant.  The bare
    'font-style:italic;font-size:70%;' is what weight_split() counts, and
    SPAN is not a substring of SPAN_LIGHT, so the count stays at N_SPAN = 2.
    Same rule, same reason, as inject_vein_generation_selvedge's vein tag.

Get either wrong and cartography bails on its next run rather than
half-applying.  With them right, N_DIV/N_SPAN need no change and this script
is order-independent with respect to cartography.

WRAPPING is done IN THE EXPRESSION, not by autoWrapLength.  500 characters
would otherwise draw as one very wide strip, and there are two ways to break
it; measured, both wrap identically, but they differ in blast radius:

  * settings.autoWrapLength = 40 wraps the WHOLE label.  A busy unit line
    already runs to 38 characters ('* H-FGR (Qtz(60%)-Fsp-Gn(5%), Bnd-Fol)'),
    so a third mineral or a vein tag would start breaking code lines that
    render fine today - it would silently re-lay-out existing maps.
  * wordwrap() in the expression touches this field and nothing else.

So the suffix carries its own wordwrap, and no whole-layer label setting is
changed at all.  The break MUST be '<br>': allowHtml is on for this label,
and a raw newline inside the HTML is collapsed to a space (rendered and
checked - the line came out unwrapped).

If anyone does reach for the whole-layer wrap later: autoWrapLength lives on
<settings><text-format>, NOT on <text-style>.  Setting it on <text-style>
parses, saves, round-trips, and does nothing at all - QGIS reads back 0.

Usage:
    python scripts/inject_basemap_lithology_suffix.py [path\\to\\template.gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import shutil
import sqlite3
import sys
import xml.etree.ElementTree as ET

BM = "4 - Basemap"
FIELD = "LithologySuffix"
SQLTYPE = "TEXT(500)"
ALIAS = ""            # LithologyPrefix carries none either

BACKUP_DATE = "2026-08-29"
BACKUP_NAME = "LGS_MappingTemplate_pre-lith-suffix_%s.gpkg" % BACKUP_DATE

# The anchor the new field's form entry sits beneath.  A bare
# attributeEditorField in the General tab, not a gated GroupBox - the vein
# fields' container_block() shape would be wrong here.
FORM_ANCHOR = "LithologyPrefix"

# The label's own markup.  Mirrors inject_label_cartography.SPAN_LIGHT; see
# MARKUP in the module docstring for why it may not be the bare variant.
SUFFIX_STYLE = "font-style:italic;font-weight:400;font-size:70%;"
SUFFIX_DIV = "'<div style=\"%s\">('" % SUFFIX_STYLE

# Characters per line before the note breaks.  See WRAPPING above for why
# this lives in the expression rather than in settings.autoWrapLength.
WRAP_CHARS = 40
WRAPPED = ("replace(wordwrap(\"%s\", %d), '\\n', '<br>')"
           % (FIELD, WRAP_CHARS))

# The expression is owned by inject_basemap_mineral_pcts and layered on by
# four other injectors, so this appends at the tail rather than rewriting -
# a rewrite would drag in the whole replay chain.
LABEL_TAIL = "end\r\n\r\n  end\r\n"
LABEL_FRAGMENT = (
    " ||\r\n"
    "\r\n"
    "-- Lithology suffix: free-text note on its own line, italic 70% in\r\n"
    "-- brackets, wrapped at " + str(WRAP_CHARS) + " characters ('<br>', not a\r\n"
    "-- newline - the label is HTML and would swallow a newline)\r\n"
    "case \r\n"
    "  when coalesce(\"" + FIELD + "\",'') != '' then\r\n"
    "    " + SUFFIX_DIV + " || " + WRAPPED + " || ')</div>'\r\n"
    "  else '' \r\n"
    "end\r\n"
)


def bail(msg):
    raise SystemExit("ABORT: " + msg)


# ---------------------------------------------------------------------------
# File guards (lifted from inject_vein_generation_selvedge.py)
# ---------------------------------------------------------------------------

def back_up(repo, gpkg):
    """Snapshot beside the file being edited, not always into the repo."""
    if os.path.abspath(gpkg) == os.path.abspath(
            os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")):
        dest = os.path.join(repo, "Template", "Backup", BACKUP_NAME)
    else:
        stem, ext = os.path.splitext(gpkg)
        dest = "%s_pre-lith-suffix_%s%s" % (stem, BACKUP_DATE, ext)
    if not os.path.exists(dest):
        shutil.copy2(gpkg, dest)
    return dest


def refuse_if_open(gpkg):
    """Bail if QGIS still has the gpkg open.

    The quiet hazard is the second one: SQLite may let the write through,
    but QGIS holds layer_styles in memory and writes its own copy back on
    the next project save - so the change appears to work, then vanishes.

    The -wal check MUST come first and MUST NOT be preceded by a connection
    of our own: connecting and closing cleanly checkpoints and DELETES the
    -wal, destroying the evidence.
    """
    if os.path.exists(gpkg + "-wal"):
        bail("%s has an active -wal alongside it, so something still has it "
             "open. Close the project in QGIS first: styles live in "
             "layer_styles, and QGIS would write its in-memory copy straight "
             "back over this edit on the next save."
             % os.path.basename(gpkg))
    try:
        con = sqlite3.connect(gpkg, timeout=1.0)
        con.execute("BEGIN IMMEDIATE")
        con.execute("ROLLBACK")
        con.close()
    except sqlite3.OperationalError as exc:
        bail("%s is locked (%s) - close the project in QGIS and re-run"
             % (os.path.basename(gpkg), exc))


# ---------------------------------------------------------------------------
# QML surgery
# ---------------------------------------------------------------------------

def insert_before(qml, closing_tag, fragment):
    i = qml.find(closing_tag)
    if i < 0 or qml.find(closing_tag, i + 1) >= 0:
        bail("%r not found or not unique" % closing_tag)
    return qml[:i] + fragment + qml[i:]


def widget_block(field):
    """TextEdit, single line - byte-identical config to LithologyPrefix."""
    root = ET.Element("field")
    root.set("name", field)
    root.set("configurationFlags", "NoFlag")
    ew = ET.SubElement(root, "editWidget")
    ew.set("type", "TextEdit")
    cfg = ET.SubElement(ew, "config")
    m = ET.SubElement(cfg, "Option", {"type": "Map"})
    ET.SubElement(m, "Option",
                  {"name": "IsMultiline", "type": "bool", "value": "false"})
    ET.SubElement(m, "Option",
                  {"name": "UseHtml", "type": "bool", "value": "false"})
    return ET.tostring(root, encoding="unicode")


def form_field_block(field, index):
    """A bare attributeEditorField, cloning LithologyPrefix's labelStyle."""
    f = ET.Element("attributeEditorField")
    for k, v in [("name", field), ("index", str(index)),
                 ("horizontalStretch", "0"), ("showLabel", "1"),
                 ("verticalStretch", "0")]:
        f.set(k, v)
    ls = ET.SubElement(f, "labelStyle")
    for k, v in [("overrideLabelFont", "0"),
                 ("labelColor", "0,0,0,255,rgb:0,0,0,1"),
                 ("overrideLabelColor", "0")]:
        ls.set(k, v)
    lf = ET.SubElement(ls, "labelFont")
    for k, v in [("style", ""), ("strikethrough", "0"), ("bold", "0"),
                 ("description", "MS Shell Dlg 2,8,-1,5,50,0,0,0,0,0"),
                 ("italic", "0"), ("underline", "0")]:
        lf.set(k, v)
    return ET.tostring(f, encoding="unicode")


def add_column(cur, gpkg_unused=None):
    cols = [r[1] for r in cur.execute('PRAGMA table_info("%s")' % BM)]
    if FIELD in cols:
        print("  column %s: already present" % FIELD)
    else:
        cur.execute('ALTER TABLE "%s" ADD COLUMN "%s" %s'
                    % (BM, FIELD, SQLTYPE))
        print("  column %s: added (%s)" % (FIELD, SQLTYPE))
    # Recompute AFTER the ALTER - form indexes are QGIS field indexes, i.e.
    # table columns minus geom.
    cols = [r[1] for r in cur.execute('PRAGMA table_info("%s")' % BM)]
    return [c for c in cols if c != "geom"].index(FIELD)


def add_field_config(qml, index):
    """The 11 per-field QML tags every injected field carries."""
    if '<field name="%s" configurationFlags' % FIELD in qml:
        print("  %s: config already present" % FIELD)
        return qml
    qml = insert_before(qml, "</fieldConfiguration>", widget_block(FIELD))
    qml = insert_before(qml, "</aliases>",
                        '<alias name="%s" index="%d" field="%s"/>'
                        % (ALIAS, index, FIELD))
    qml = insert_before(qml, "</splitPolicies>",
                        '<policy policy="Duplicate" field="%s"/>' % FIELD)
    qml = insert_before(qml, "</duplicatePolicies>",
                        '<policy policy="Duplicate" field="%s"/>' % FIELD)
    qml = insert_before(qml, "</defaults>",
                        '<default expression="" applyOnUpdate="0" '
                        'field="%s"/>' % FIELD)
    qml = insert_before(qml, "</constraints>",
                        '<constraint constraints="0" notnull_strength="0" '
                        'field="%s" unique_strength="0" exp_strength="0"/>'
                        % FIELD)
    qml = insert_before(qml, "</constraintExpressions>",
                        '<constraint desc="" field="%s" exp=""/>' % FIELD)
    qml = insert_before(qml, "</columns>",
                        '<column name="%s" type="field" hidden="0" '
                        'width="-1"/>' % FIELD)
    qml = insert_before(qml, "</editable>",
                        '<field name="%s" editable="1"/>' % FIELD)
    qml = insert_before(qml, "</labelOnTop>",
                        '<field name="%s" labelOnTop="0"/>' % FIELD)
    qml = insert_before(qml, "</reuseLastValue>",
                        '<field reuseLastValue="0" name="%s"/>' % FIELD)
    print("  %s: config injected" % FIELD)
    return qml


def add_form_entry(qml, index):
    """Sit the field directly beneath LithologyPrefix in the General tab."""
    if '<attributeEditorField name="%s"' % FIELD in qml:
        print("  %s: form entry already present" % FIELD)
        return qml
    m = re.search(r'<attributeEditorField[^>]*\bname="%s"[^>]*>'
                  % re.escape(FORM_ANCHOR), qml)
    if not m:
        bail("form entry for %r not found" % FORM_ANCHOR)
    if re.search(r'<attributeEditorField[^>]*\bname="%s"[^>]*>'
                 % re.escape(FORM_ANCHOR), qml[m.end():]):
        bail("form entry for %r is not unique" % FORM_ANCHOR)
    close = "</attributeEditorField>"
    end = qml.find(close, m.end())
    if end < 0:
        bail("form entry for %r is not closed" % FORM_ANCHOR)
    end += len(close)
    print("  %s: form entry injected after %r" % (FIELD, FORM_ANCHOR))
    return qml[:end] + form_field_block(FIELD, index) + qml[end:]


def splice_label(qml):
    """Append the suffix line to the label expression, in place.

    The expression is OWNED by inject_basemap_mineral_pcts, so this only
    ever appends at a checked tail - it never rewrites it.  Appending past
    the Confidence '?' is safe here and only here: the '?' closes the
    Lithology 1 line, and this opens a new <div> below both lith lines.
    """
    lm = re.search(r'<labeling type="simple">.*?</labeling>', qml, re.S)
    if not lm:
        bail("%s: simple labeling block not found" % BM)
    lab = ET.fromstring(lm.group(0))
    ts = lab.find(".//text-style")
    if ts is None:
        bail("%s: no text-style in the labeling block" % BM)
    if ts.get("isExpression") != "1":
        bail("%s: label is not an expression - has the owning injector run?"
             % BM)
    expr = ts.get("fieldName") or ""

    if SUFFIX_DIV in expr:
        print("  label: already applied")
        return qml
    if not expr.endswith(LABEL_TAIL):
        bail("%s: the label does not end with the expected outer 'end' - "
             "has inject_basemap_mineral_pcts.py been re-run since? "
             "(tail was %r)" % (BM, expr[-40:]))
    ts.set("fieldName", expr + LABEL_FRAGMENT)
    print("  label: suffix line appended, wrapped at %d chars" % WRAP_CHARS)
    return (qml[:lm.start()] + ET.tostring(lab, encoding="unicode")
            + qml[lm.end():])


# ---------------------------------------------------------------------------

def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default = os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail("gpkg not found: %s" % gpkg)
    if "_Patterns" in os.path.basename(gpkg):
        bail("that is the generated patterns template - this belongs in the "
             "live template; run inject_basemap_lith_patterns.py after")

    refuse_if_open(gpkg)
    print("backed up to %s" % back_up(repo, gpkg))

    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    print("== %s" % BM)
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (BM,))
    row = cur.fetchone()
    if not row or not row[0]:
        bail("no styleQML for %r" % BM)
    qml = original = row[0]

    index = add_column(cur)
    qml = add_field_config(qml, index)
    qml = add_form_entry(qml, index)
    qml = splice_label(qml)

    # Validate BEFORE writing: never persist a QML that no longer parses.
    try:
        ET.fromstring(qml)
    except ET.ParseError as exc:
        bail("%s: edited QML no longer parses, aborting without write: %s"
             % (BM, exc))
    if qml != original:
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, BM))
        assert cur.rowcount == 1
        print("  styleQML updated")
    else:
        print("  styleQML: no change")
    con.commit()

    # --- Round-trip validation -------------------------------------------
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])

    cols = [r[1] for r in cur.execute('PRAGMA table_info("%s")' % BM)]
    assert FIELD in cols, "column missing after commit"
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (BM,))
    root = ET.fromstring(cur.fetchone()[0])

    widgets = {f.get("name"): f.find("editWidget")
               for f in root.find("fieldConfiguration")}
    assert widgets[FIELD].get("type") == "TextEdit", "wrong widget type"
    multiline = [o.get("value") for o in widgets[FIELD].iter("Option")
                 if o.get("name") == "IsMultiline"]
    assert multiline == ["false"], multiline

    for tag, attr in (("aliases", "field"), ("splitPolicies", "field"),
                      ("duplicatePolicies", "field"), ("defaults", "field"),
                      ("constraints", "field"),
                      ("constraintExpressions", "field"),
                      ("editable", "name"), ("labelOnTop", "name"),
                      ("reuseLastValue", "name")):
        block = root.find(".//" + tag)
        assert block is not None, tag
        assert sum(1 for e in block if e.get(attr) == FIELD) == 1, \
            "%s: expected exactly one %s entry" % (tag, FIELD)

    form = root.find(".//attributeEditorForm")
    entries = [e.get("name") for e in form.iter("attributeEditorField")]
    assert entries.count(FIELD) == 1, entries
    assert entries[entries.index(FORM_ANCHOR) + 1] == FIELD, \
        "%s is not directly beneath %s on the form" % (FIELD, FORM_ANCHOR)

    ts = root.find(".//labeling/settings/text-style")
    expr = ts.get("fieldName")
    assert expr.count(SUFFIX_DIV) == 1, "suffix div is not in the label once"
    assert expr.count(WRAPPED) == 1, "the note is not wordwrapped"
    # The whole-layer wrap must stay OFF - see WRAPPING in the docstring.
    # It lives on <settings><text-format>, NOT on <text-style>: setting it
    # on the latter parses, saves, and does absolutely nothing.
    text = root.find(".//labeling/settings/text-format")
    assert text is not None, "no <text-format> under the labeling settings"
    assert text.get("autoWrapLength") in (None, "0"), \
        ("autoWrapLength is %r; it would re-wrap the unit code lines too"
         % text.get("autoWrapLength"))
    # The contract inject_label_cartography counts on - see MARKUP above.
    plain_div = "'<div>'"
    div_bold = "'<div style=\"font-weight:600;\">'"
    plain_span = "font-style:italic;font-size:70%;"
    assert expr.count(div_bold) == 3, \
        "semibold div count moved to %d - cartography counts 3" % expr.count(div_bold)
    assert plain_div not in expr.replace(div_bold, ""), \
        "a plain <div> survived - cartography would miscount"
    assert plain_span not in expr.replace(SUFFIX_STYLE, "").replace(
        "font-style:italic;font-weight:400;font-size:70%;", ""), \
        "a plain span survived - cartography's weight_split would miscount"

    print("round-trip ok: %s - 1 field, suffix line, wordwrap at %d chars"
          % (BM, WRAP_CHARS))
    con.close()
    print('\nNOW RUN: "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" '
          "scripts/inject_basemap_lith_patterns.py   (re-bakes the Patterns gpkg)")


if __name__ == "__main__":
    main()
