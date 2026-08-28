"""Move the Transported Cover family off the sandstone cream, onto pale grey.

SUPERSEDED BY ROUND 2 - kept for the record, not for re-running.
inject_cover_mechanism.py has since moved these same 21 codes off the grey
ladder onto mechanism-tinted family hues (and added 13 more codes beside
them), so this script's guards no longer hold against the current template:
it counts 21 cover codes where there are now 34, and expects the cream this
template no longer carries. Run it and it aborts, by design. The greys it
wrote survive as cover_palette.ROUND1_GREY, which is what round 2 checks
its own idempotency against.

THE PROBLEM
-----------
20 of the 21 Transported Cover codes shared ONE cream anchor, `#efe8ce`
(TDLP sat beside it on `#ffefdb`), within a CIE76 dE of 1.5-5.4 of the
sandstone family (SST resolves to #eee8c7, SSTM to #efebd0). TCO and TALL
were byte-identical, separated only by their stipple tile. On the map,
transported cover read as bedrock.

The injector's separation gates never caught this because `distinct()`
declares two codes distinct as soon as their tiles differ - the colour is
never compared - and cover is exempt from every hue rule in `lith_palette`
(CHEMICAL_HUE excludes the Regolith and Transported Cover types on purpose).

WHAT THIS DOES
--------------
Recolours all 21 cover codes in `4 - Basemap` onto a pale near-neutral grey
family, so cover reads as a receding veil over the coloured bedrock -
figure-ground: bedrock is the subject, cover is what hides it. One family
hue teaches the eye "grey = cover"; within the family, sub-groups whisper
apart (cool for clay/evaporite, an olive cast for colluvium, warm for
duricrust) and lightness rungs + the tile separate the codes.

Every code gets a UNIQUE anchor on purpose: `lith_palette.build()` hands a
unique anchor that no rule touches back byte-for-byte (no slot offsets, no
muting), so the patterns template will agree with this one exactly.

Deliberately NOT touched:
  * Regolith (the 20 R* residual codes) stays cream - in-situ residuum keeps
    the earthy convention, which now also does figure-ground work against
    the grey cover.
  * SSL siltstone keeps its neutral #dedede even though it sits near the new
    corridor - its tile differs from every close cover grey.
  * The ContactType dashed outline is data-defined and shared by every rule;
    nothing here goes near it.

Colour lives in the live template because `lith_palette.read_code_anchors()`
reads it from here: change it here, re-run `inject_basemap_lith_patterns.py`,
and both templates agree. Editing the patterns copy directly is wiped on the
next injector run.

Also repairs two pre-existing SLD defects found on the way in (the QML was
always right; only the SLD mirror had drifted): TRSLM never received an SLD
rule when it was added, and an orphan rule for HSP - a code no longer in
BasemapCodes - was left behind. The TRSLM rule is cloned from TRSL's on the
shared cream, then recoloured through the same path as everything else; the
HSP orphan is dropped, but only after confirming the code really is gone.

Idempotent: each code must be either fully on its old cream or fully on its
new grey, in the QML and the SLD alike. Anything else aborts without writing.

Usage:  python scripts/inject_basemap_cover_recolour.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import shutil
import sqlite3
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lith_palette

LAYER = "4 - Basemap"
TABLE = "BasemapCodes"

# The shared cream every cover code carries today.
CREAM = (0xef, 0xe8, 0xce)            # #efe8ce
OLD = {"TDLP": (0xff, 0xef, 0xdb)}    # the one exception

# code -> new fill. Grouped by how the cover formed, not by letter. Ladder
# spans L* 74-97 at near-zero chroma; every same-tile non-variety pair
# clears dE 7 and every code clears dE 7 from the sandstone creams.
RECOLOUR = {
    # Alluvial - the freshest, most water-worked cover: palest neutrals.
    "TALL": (0xe9, 0xeb, 0xea),       # Alluvium
    # Sandy cover, graded coarse->fine by darkening rungs.
    "TSA":  (0xf2, 0xf2, 0xf0),       # Sand
    "TCOS": (0xdc, 0xdd, 0xd7),       # Colluvium, Sands
    "TSAC": (0xc9, 0xc9, 0xc8),       # Clayey Sand
    "TRSS": (0xb5, 0xb7, 0xb2),       # Residual Soil, Sandy

    # Colluvial / scree - a faint olive cast for the hillslope family.
    "TCO":  (0xe7, 0xe7, 0xe2),       # Colluvium
    "TCOC": (0xe1, 0xe1, 0xdc),       # Colluvium, Coarse (variety pair w/ TCO)
    "TLSC": (0xcb, 0xcd, 0xc6),       # Lithic Scree
    "TRSL": (0xb7, 0xb8, 0xb1),       # Residual Soil, Lithic Fragments

    # Gravel / lag - neutral, darker than the sands they armour.
    "TGRV": (0xd6, 0xd8, 0xd3),       # Gravel
    "TLG":  (0xc2, 0xc3, 0xbd),       # Lag

    # Clay / loam / hardpan - a cool cast for the fine, wet-formed cover.
    "TCY":  (0xe4, 0xe9, 0xec),       # Clay
    "TRSLM": (0xd9, 0xd9, 0xd2),      # Residual Soil, Loam (warm loam)
    "TCOD": (0xcd, 0xd2, 0xd7),       # Colluvium, Fine silt & Clay
    "THP":  (0xb2, 0xb7, 0xb9),       # Hard Pan

    # Silt - between the sands and the clays, dead neutral.
    "TSI":  (0xc6, 0xc7, 0xc4),       # Silt

    # Evaporitic - salt pan near-white, gypsum cool, evaporites green-grey.
    "TSP":  (0xf7, 0xf6, 0xf4),       # Salt Pan
    "TGYP": (0xde, 0xe5, 0xea),       # Gypsum dunes, Kopai
    "TEVS": (0xcc, 0xd0, 0xcd),       # Evaporitic Sediments

    # Duricrust / pisoliths - the one warm whisper, for the ferruginous lags.
    "TDLP": (0xd7, 0xd3, 0xc8),       # Duricrust of Transported Pisoliths
    "TLTP": (0xc2, 0xbe, 0xb2),       # Transported Pisoliths
}

# Codes whose colour must be untouched afterwards, as a guard that this
# script has not reached further than intended. Snapshot before, compare
# after - no hardcoded expectation to rot.
KEEP = ["SST", "SSTM", "SSTS", "SSLS", "SSL", "SEV", "RSLS", "RARZ", "RCC",
        "NULL"]

# The plan's dE floor: same as the patterns injector's MIN_FILL_DE.
MIN_FILL_DE = 7.0
SANDSTONE_CREAMS = ["SST", "SSTL", "SSTM", "SSTS"]

BACKUP_NAME = "LGS_MappingTemplate_pre-cover-recolour_2026-08-28.gpkg"


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def rgb_hex(rgb):
    return "#%02x%02x%02x" % rgb


def qml_colour(rgb):
    """QGIS's own serialisation: 'r,g,b,a,rgb:R,G,B,A' with float channels."""
    r, g, b = rgb
    return "%d,%d,%d,255,rgb:%s,%s,%s,1" % (
        r, g, b, repr(r / 255.0), repr(g / 255.0), repr(b / 255.0))


def triple_of(value):
    m = re.match(r'\s*(\d+),(\d+),(\d+)', value)
    return tuple(int(x) for x in m.groups()) if m else None


def symbol_block(qml, name):
    """(start, end) of <symbol name="..."> ... </symbol>, nesting-aware."""
    m = re.search(r'<symbol\b[^>]*\bname="%s"[^>]*>' % re.escape(name), qml)
    if not m:
        bail("symbol %r not found" % name)
    depth = 0
    for t in re.finditer(r'<symbol\b|</symbol>', qml[m.start():]):
        depth += 1 if t.group(0) == '<symbol' else -1
        if depth == 0:
            return m.start(), m.start() + t.end()
    bail("unbalanced symbol %r" % name)


def symbol_for_value(qml, value):
    cm = re.search(r'<category[^>]*value="%s"[^>]*/>' % re.escape(value), qml)
    if not cm:
        bail("category %r not found in %s" % (value, LAYER))
    return re.search(r'symbol="(\d+)"', cm.group(0)).group(1)


def block_colours(block):
    """Every colour Option value in a symbol block, as (match, triple)."""
    out = []
    for m in re.finditer(r'<Option name="(?:color|line_color)" '
                         r'type="QString" value="([^"]*)"', block):
        t = triple_of(m.group(1))
        if t:
            out.append((m, t))
    return out


def code_fill(qml, code):
    """The SimpleFill colour of a category - the palette's anchor for it,
    matching lith_palette.read_code_anchors()."""
    s, e = symbol_block(qml, symbol_for_value(qml, code))
    c = re.search(r'class="SimpleFill".*?<Option name="color" '
                  r'type="QString" value="(\d+),(\d+),(\d+)', qml[s:e], re.S)
    if not c:
        bail("%s: no SimpleFill colour found" % code)
    return tuple(int(x) for x in c.groups())


def code_colours(qml, code):
    """Every colour option in a category's symbol, for the KEEP snapshot."""
    s, e = symbol_block(qml, symbol_for_value(qml, code))
    return sorted({t for _m, t in block_colours(qml[s:e])})


def all_anchors(qml):
    """{code: SimpleFill rgb} for every category - the same scrape (and the
    same ANCHOR_OVERRIDE) as lith_palette.read_code_anchors(), run against
    the edited QML so the uniqueness guard sees what build() will see."""
    sym = {}
    for m in re.finditer(r'<symbol[^>]*name="(\d+)"', qml):
        seg = qml[m.start():m.start() + 2500]
        c = re.search(r'class="SimpleFill".*?<Option name="color" '
                      r'type="QString" value="(\d+),(\d+),(\d+)', seg, re.S)
        if c:
            sym[m.group(1)] = tuple(int(x) for x in c.groups())
    out = {}
    for m in re.finditer(r'<category([^>]*)\>', qml):
        a = m.group(1)
        v = re.search(r'value="([^"]*)"', a)
        s = re.search(r'symbol="(\d+)"', a)
        if not (v and s) or s.group(1) not in sym:
            continue
        code = v.group(1)
        if not code or code == "NULL":
            continue
        out[code] = sym[s.group(1)]
    out.update(lith_palette.ANCHOR_OVERRIDE)
    return out


def recolour_symbol(qml, code, old, rgb):
    """Repaint one category's symbol. Returns (qml, state) where state is
    'applied', 'already' or aborts."""
    s, e = symbol_block(qml, symbol_for_value(qml, code))
    block = qml[s:e]
    cols = block_colours(block)
    if not cols:
        bail("%s: symbol carries no colour options" % code)
    triples = {t for _m, t in cols}
    if triples == {rgb}:
        return qml, "already"
    if triples != {old}:
        bail("%s: symbol colours are %s, expected all %s (old) or "
             "all %s (target) - refusing to guess"
             % (code, sorted(triples), old, rgb))
    new = qml_colour(rgb)
    out, last = [], 0
    for m, _t in cols:
        out.append(block[last:m.start(1)])
        out.append(new)
        last = m.end(1)
    out.append(block[last:])
    return qml[:s] + "".join(out) + qml[e:], "applied"


def sld_rule_span(sld, code):
    needle = "<ogc:Literal>%s</ogc:Literal>" % code
    for m in re.finditer(r'<se:Rule>.*?</se:Rule>', sld, re.S):
        if needle in m.group(0):
            return m
    return None


def repair_sld(sld, cur):
    """Heal the SLD's two known drifts from the QML before recolouring.

    Returns (sld, notes). Both repairs are no-ops on a healed template, so
    the script stays idempotent."""
    notes = []

    if sld_rule_span(sld, "TRSLM") is None:
        desc = cur.execute(
            "SELECT Description FROM %s WHERE Code='TRSLM'"
            % TABLE).fetchone()
        if not desc:
            bail("TRSLM missing from SLD and from %s alike" % TABLE)
        model = sld_rule_span(sld, "TRSL")
        if model is None:
            bail("cannot synthesize TRSLM's SLD rule: TRSL rule not found")
        rule = model.group(0)
        old_name = re.search(r'<se:Name>([^<]*)</se:Name>', rule).group(1)
        clone = (rule
                 .replace("<ogc:Literal>TRSL</ogc:Literal>",
                          "<ogc:Literal>TRSLM</ogc:Literal>")
                 .replace(old_name, desc[0]))
        sld = sld[:model.end()] + "\n    " + clone + sld[model.end():]
        notes.append("synthesized the missing TRSLM rule from TRSL's")

    if "<ogc:Literal>HSP</ogc:Literal>" in sld:
        if cur.execute("SELECT 1 FROM %s WHERE Code='HSP'"
                       % TABLE).fetchone():
            bail("SLD carries an HSP rule and HSP exists in %s - it is not "
                 "an orphan, refusing to drop it" % TABLE)
        m = sld_rule_span(sld, "HSP")
        sld = sld[:m.start()] + sld[m.end():]
        notes.append("dropped the orphan HSP rule (code no longer exists)")

    return sld, notes


def recolour_sld(sld, code, old, rgb):
    m = sld_rule_span(sld, code)
    if m is None:
        bail("SLD rule for %r not found" % code)
    rule = m.group(0)
    found = set(re.findall(r'<se:SvgParameter name="(?:fill|stroke)">'
                           r'(#[0-9a-fA-F]{6})</se:SvgParameter>', rule))
    want, was = rgb_hex(rgb), rgb_hex(old)
    if found == {want}:
        return sld, "already"
    if found != {was}:
        bail("%s: SLD colours are %s, expected all %s or all %s"
             % (code, sorted(found), was, want))
    new_rule = re.sub(r'(<se:SvgParameter name="(?:fill|stroke)">)'
                      r'#[0-9a-fA-F]{6}(</se:SvgParameter>)',
                      r'\g<1>%s\g<2>' % want, rule)
    return sld[:m.start()] + new_rule + sld[m.end():], "applied"


# ---- CIE76, same maths as inject_basemap_lith_patterns.delta_e ----------
def _lab(rgb):
    def f(u):
        u /= 255.0
        return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def k(t):
        return t ** (1 / 3.0) if t > 0.008856 else 7.787 * t + 16 / 116.0
    fx, fy, fz = k(x), k(y), k(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(a, b):
    la, lb = _lab(a), _lab(b)
    return sum((x - y) ** 2 for x, y in zip(la, lb)) ** 0.5


def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default = os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail("gpkg not found: %s" % gpkg)
    if "_Patterns" in os.path.basename(gpkg):
        bail("that is the generated patterns template - colour belongs in the "
             "live template; run inject_basemap_lith_patterns.py afterwards")

    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    # ---------------- guards ------------------------------------------
    rows = dict(cur.execute(
        "SELECT Code, Type FROM %s WHERE Code IN (%s)"
        % (TABLE, ",".join("?" * len(RECOLOUR))), sorted(RECOLOUR)))
    missing = sorted(set(RECOLOUR) - set(rows))
    if missing:
        bail("codes not in %s: %s" % (TABLE, missing))
    not_cover = sorted(c for c, t in rows.items() if t != "Transported Cover")
    if not_cover:
        bail("codes not typed 'Transported Cover' in %s: %s - this script "
             "must only move cover" % (TABLE, not_cover))
    n_cover = cur.execute(
        "SELECT COUNT(*) FROM %s WHERE Type='Transported Cover'"
        % TABLE).fetchone()[0]
    if n_cover != len(RECOLOUR):
        bail("%s holds %d Transported Cover codes but RECOLOUR lists %d - "
             "a cover code is missing from the ladder" % (TABLE, n_cover,
                                                          len(RECOLOUR)))

    row = cur.execute(
        "SELECT styleQML, styleSLD FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()
    if not row or not row[0] or not row[1]:
        bail("styleQML/styleSLD missing for %r" % LAYER)
    qml, sld = row
    keep_before = {c: code_colours(qml, c) for c in KEEP}

    # ---------------- edit --------------------------------------------
    sld, repairs = repair_sld(sld, cur)
    for note in repairs:
        print("  SLD repair: " + note)
    states = {}
    for code in sorted(RECOLOUR):
        rgb = RECOLOUR[code]
        old = OLD.get(code, CREAM)
        qml, q_state = recolour_symbol(qml, code, old, rgb)
        sld, s_state = recolour_sld(sld, code, old, rgb)
        if q_state != s_state:
            bail("%s: QML says %r but SLD says %r - templates half-applied"
                 % (code, q_state, s_state))
        states[code] = q_state
        print("  %-6s %s -> %s   %s"
              % (code, rgb_hex(old), rgb_hex(rgb), q_state))

    if set(states.values()) == {"already"} and not repairs:
        print("already applied (no change)")
    elif len(set(states.values())) > 1:
        bail("partially applied: %s"
             % sorted(c for c, s in states.items() if s == "already"))
    else:
        # Never persist a style that no longer parses.
        try:
            ET.fromstring(qml)
            ET.fromstring(sld)
        except ET.ParseError as exc:
            bail("edited style no longer parses, not writing: %s" % exc)
        if not os.path.exists(os.path.join(repo, "Template", "Backup",
                                           BACKUP_NAME)):
            shutil.copy2(gpkg, os.path.join(repo, "Template", "Backup",
                                            BACKUP_NAME))
            print("backup -> Template/Backup/%s" % BACKUP_NAME)
        cur.execute("UPDATE layer_styles SET styleQML=?, styleSLD=? "
                    "WHERE f_table_name=?", (qml, sld, LAYER))
        assert cur.rowcount == 1
        con.commit()
        print("styleQML + styleSLD updated (%d codes)" % len(RECOLOUR))

    # ---------------- round-trip validation ---------------------------
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    final_qml, final_sld = cur.execute(
        "SELECT styleQML, styleSLD FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()
    root = ET.fromstring(final_qml)
    ET.fromstring(final_sld)

    rend = re.search(r'<renderer-v2\b[^>]*>', final_qml).group(0)
    assert 'type="categorizedSymbol"' in rend and 'attr="Lithology1"' in rend
    assert 'referencescale="5000"' in rend
    cats = root.find(".//renderer-v2/categories").findall("category")
    assert len(cats) == 287, len(cats)
    assert len(re.findall(r'<se:Rule>', final_sld)) == 288

    for code, rgb in sorted(RECOLOUR.items()):
        assert code_fill(final_qml, code) == rgb, code
        rule = sld_rule_span(final_sld, code).group(0)
        assert set(re.findall(r'<se:SvgParameter name="(?:fill|stroke)">'
                              r'(#[0-9a-fA-F]{6})</se:SvgParameter>',
                              rule)) == {rgb_hex(rgb)}, code
    for code, was in keep_before.items():
        assert code_colours(final_qml, code) == was, (
            code, "colour moved but this script must not touch it")

    # Anchor uniqueness: build() only passes a colour through untouched when
    # no other code shares the anchor - a collision would silently engage the
    # slot offsets and drift the patterns-template colour off this ladder.
    fills = {}
    for code, rgb in all_anchors(final_qml).items():
        fills.setdefault(rgb, []).append(code)
    shared = {rgb_hex(RECOLOUR[c]): fills[RECOLOUR[c]]
              for c in RECOLOUR if len(fills.get(RECOLOUR[c], [c])) > 1}
    assert not shared, "cover anchors shared with other codes: %s" % shared

    # ---------------- dE audit ----------------------------------------
    # Enforced here: cover-vs-cover on the SAME tile (these anchors pass
    # through build() untouched, so anchor-space IS resolved-space), and
    # cover vs the sandstone creams. Cover vs OTHER bedrock is only printed:
    # bedrock anchors can move in the palette, so the authoritative
    # cross-type gate lives in inject_basemap_lith_patterns.py, in resolved
    # space.
    tex = lith_palette.read_texture_map()
    worst = None
    for i, a in enumerate(sorted(RECOLOUR)):
        for b in sorted(RECOLOUR)[i + 1:]:
            if tex[a][0] != tex[b][0]:
                continue
            va, vb = tex[a][1], tex[b][1]
            if va and va == vb:
                continue              # declared variety pair
            de = delta_e(RECOLOUR[a], RECOLOUR[b])
            if worst is None or de < worst[0]:
                worst = (de, a, b)
            assert de >= MIN_FILL_DE, (
                "%s / %s share tile %s at fill dE %.1f < %.1f"
                % (a, b, tex[a][0], de, MIN_FILL_DE))
    print("same-tile cover pairs: closest %s / %s at dE %.1f (floor %.1f)"
          % (worst[1], worst[2], worst[0], MIN_FILL_DE))

    for s_code in SANDSTONE_CREAMS:
        s_fill = code_fill(final_qml, s_code)
        near = min((delta_e(rgb, s_fill), c) for c, rgb in RECOLOUR.items())
        assert near[0] >= MIN_FILL_DE, (
            "%s sits dE %.1f from %s" % (near[1], near[0], s_code))
        print("vs %-5s %s: nearest cover %s at dE %.1f"
              % (s_code, rgb_hex(s_fill), near[1], near[0]))

    for o_code in ("SSL", "SEV", "RCC"):
        o_fill = code_fill(final_qml, o_code)
        near = min((delta_e(rgb, o_fill), c) for c, rgb in RECOLOUR.items())
        print("advisory  vs %-4s %s: nearest cover %s at dE %.1f "
              "(different tiles separate these)"
              % (o_code, rgb_hex(o_fill), near[1], near[0]))

    print("\nround-trip ok: %d cover codes on unique grey anchors, %d guard "
          "codes untouched. Re-run inject_basemap_lith_patterns.py to bake "
          "the patterns template." % (len(RECOLOUR), len(KEEP)))
    con.close()


if __name__ == "__main__":
    main()
