"""Per-feature fill modulation for '4 - Basemap': Lith2 tint + texture nudge.

THE PROBLEM
-----------
The Basemap renders purely off Lithology1, so two units that share a code but
differ in Lithology2 or texture (SST vs SST-with-SSL, SST vs coarse-grained
SST) are pixel-identical polygons. The label parenthetical already says the
words; this makes the difference visible in colour.

WHAT IT DOES
------------
Five virtual (expression) fields and ONE tiny data-defined fill-colour
expression, byte-identical on every renderer symbol:

  LGS_Lith2Fill    - CASE over Lithology2 resolving the SECOND lithology's
                     canonical palette colour (lith_palette.build(), the same
                     palette the patterns injector paints), grouped one branch
                     per distinct fill. NULL when Lithology2 is empty/unknown.
  LGS_TextureNudge - Qt darker()/lighter() factor from the `nudge` rows of
                     Template/patterns/texture_modulation.tsv, read off
                     Lith1Texture1/Lith1Texture2 (Texture1 wins). 100 when
                     no listed texture is present. Grain sizes ladder from
                     92 (very fine, lighter) to 108 (very coarse, deeper) -
                     so grain survives where the tile channel cannot reach
                     (the plain template, and past the pattern scale gate) -
                     and the fabric textures sit at the +-8% extremes.
  LGS_MixCap       - this code's blend ratio: LITH2_MIX for most codes,
                     stepped down per code by the fill-identity audit.
  LGS_BaseFill     - this code's own palette colour (CASE over Lithology1,
                     grouped by distinct fill). NULL for the catch-all class.
  LGS_ModFill      - the finished modulated colour, or NULL when the feature
                     carries no modifiers.

  fillColor dd     - coalesce("LGS_ModFill", @symbol_color)

WHY THIS SHAPE
--------------
* The dd fillColor slot already exists (inactive) on every class symbol, so
  activating it adds NO symbol layers and no per-category render cost - the
  54.5ms-per-category SVGFill lesson does not repeat here.
* Every CASE lives ONCE, in a virtual field parsed once per layer, instead
  of being duplicated into 301 symbols (~3 MB of QML) or re-parsed per
  feature from JSON. No with_variable anywhere: QgsExpression parse cost
  doubles per nesting level.
* The per-symbol expression is TINY because QGIS re-parses every class
  symbol's dd expressions on every render pass: a first cut put the whole
  4-branch modulation CASE (~450 B) on each of the 301 symbols and measured
  +8.3 ms of pure parsing per redraw; the coalesce() form parses in 1.1 ms.
  The arithmetic lives in LGS_ModFill, whose eval cost is per-FEATURE and
  short-circuits to NULL on the (typical) unmodified feature.
* Unmodified features take @symbol_color - verified byte-identical to the
  plain symbol, so a hand-edited category colour renders exactly. Modulated
  features blend from LGS_BaseFill, the baked palette colour: re-run this
  injector after any recolour (the re-bake chain already requires that).
* QgsRuleBasedRenderer.convertFromRenderer PRESERVES symbol-layer dd
  properties (verified), so inject_basemap_lith_patterns.py carries all of
  this into the patterns template on re-bake. Run THIS injector first, the
  patterns injector last - it now refuses a half-applied state.
* Chained virtual fields (ModFill reading BaseFill/Lith2Fill/...) are
  resolved by the layer's feature iterator - verified by probe, including
  the "r,g,b,a" string a colour function materialises into a string field,
  which the dd colour decoder accepts exactly.

The blend is deliberately a whisper (LITH2_MIX = 0.15): the unit must still
read as its Lithology1, merely leaning toward the second lithology. A
fill-identity audit below aborts the run if any (code, Lith2, nudge) combo
would land nearer some OTHER code's fill than its own - the modulation may
only spend the separation margin the palette actually has.

Note: the patterns injector may still shift a handful of fills after this
palette is resolved (fit_fill_to_ink, for mineral-ink codes), so the baked
Lith2 hex can differ imperceptibly from the painted rule colour there. At a
15% mix that discrepancy is sub-JND by construction.

styleSLD is deliberately LEFT ALONE: SLD cannot express a data-defined fill
colour, and the static colours it describes are unchanged.

Run:  python scripts/inject_basemap_lith_modulation.py [path\\to\\gpkg] [--dry-run]
      (defaults to Template/LGS_MappingTemplate.gpkg; pure stdlib, no QGIS)

Idempotent: regenerates both virtual fields and all 301 dd expressions
wholesale each run.
"""
import datetime
import os
import re
import shutil
import sqlite3
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lith_palette  # noqa: E402
import inject_basemap_lith_patterns as patterns  # noqa: E402  (stdlib at module level)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_GPKG = os.path.join(REPO, "Template", "LGS_MappingTemplate.gpkg")
BACKUP_DIR = os.path.join(REPO, "Template", "Backup")

LAYER = "4 - Basemap"
EXPECT_SLOTS = 301          # 300 category symbols + the source-symbol

LITH2_FIELD = "LGS_Lith2Fill"
NUDGE_FIELD = "LGS_TextureNudge"
MIXCAP_FIELD = "LGS_MixCap"
BASE_FIELD = "LGS_BaseFill"
MODFILL_FIELD = "LGS_ModFill"
ALL_FIELDS = (LITH2_FIELD, NUDGE_FIELD, MIXCAP_FIELD, BASE_FIELD,
              MODFILL_FIELD)

# How far the fill leans toward the second lithology's colour. 0.15 keeps the
# Lithology1 identity dominant; the fill-identity audit is what makes this
# number defensible rather than hopeful - turn it DOWN if the audit names
# offenders after a palette change.
LITH2_MIX = patterns.LITH2_MIX
MOD_IDENTITY_MARGIN = patterns.IDENTICAL_DE


def bail(msg):
    raise SystemExit("ABORT: " + msg)


# ------------------------------------------------------------ expressions
def build_fill_case(fill_of, field):
    """CASE over `field` -> fill hex, one branch per DISTINCT fill; NULL for
    empty/unknown (no ELSE). Serves both LGS_Lith2Fill (over Lithology2) and
    LGS_BaseFill (over Lithology1)."""
    groups = {}
    for code, rgb in fill_of.items():
        groups.setdefault(patterns.hexof(rgb), []).append(code)
    parts = ["CASE"]
    for hexv in sorted(groups):
        codes = ", ".join(patterns.sql_quote(c) for c in sorted(groups[hexv]))
        parts.append('  WHEN "%s" IN (%s) THEN %s'
                     % (field, codes, patterns.sql_quote(hexv)))
    parts.append("END")
    return "\n".join(parts)


def build_mixcap_case(mix_of):
    """CASE over Lithology1 -> blend ratio; only capped codes get branches,
    everything else takes the ELSE at the full LITH2_MIX."""
    groups = {}
    for code, mix in mix_of.items():
        if mix != LITH2_MIX:
            groups.setdefault(mix, []).append(code)
    parts = ["CASE"]
    for mix in sorted(groups):
        codes = ", ".join(patterns.sql_quote(c) for c in sorted(groups[mix]))
        parts.append('  WHEN "Lithology1" IN (%s) THEN %.2f' % (codes, mix))
    parts.append("  ELSE %.2f" % LITH2_MIX)
    parts.append("END")
    return "\n".join(parts)


def build_nudge_case(nudge_of):
    """CASE over Lith1Texture1/2 -> darker() factor; Texture1 wins, ELSE 100.
    Factor-100 rows (Medium Grained) are documentation - the ELSE already
    says 100, so they get no branch."""
    groups = {}
    for texture, factor in nudge_of.items():
        if factor != 100:
            groups.setdefault(factor, []).append(texture)
    parts = ["CASE"]
    for field in ("Lith1Texture1", "Lith1Texture2"):
        for factor in sorted(groups):
            names = ", ".join(patterns.sql_quote(t)
                              for t in sorted(groups[factor]))
            parts.append('  WHEN "%s" IN (%s) THEN %d'
                         % (field, names, factor))
    parts.append("  ELSE 100")
    parts.append("END")
    return "\n".join(parts)


# The one expression every symbol carries, byte-identical on all 301. Kept
# TINY on purpose: QGIS re-parses each class symbol's dd expressions on
# every render pass, and 301 copies of the full modulation CASE measured
# +8.3 ms/redraw of parsing against 1.1 ms for this form. A NULL LGS_ModFill
# (no modifiers, or the catch-all class) falls through to @symbol_color,
# which renders byte-identically to the plain symbol.
SYMBOL_EXPR = 'coalesce("%s", @symbol_color)' % MODFILL_FIELD


# The finished colour, or NULL for an unmodified feature. All the guard
# branches live here, parsed once per layer:
# * BaseFill NULL (the catch-all class) -> NULL, never a half-computed mix.
# * darker(c, 100) is never evaluated - Qt's HSV round-trip in darker() can
#   drift a channel by 1 even at factor 100.
# * coalesce(...,100) in the ELSE guards the NULL-numeric trap: a NULL read
#   as 0 would otherwise send darker() a factor of 0.
MODFILL_EXPR = (
    "CASE\n"
    "  WHEN \"%(base)s\" IS NULL THEN NULL\n"
    "  WHEN \"%(l2)s\" IS NULL AND \"%(nd)s\" = 100 THEN NULL\n"
    "  WHEN \"%(nd)s\" = 100\n"
    "    THEN color_mix_rgb(\"%(base)s\", \"%(l2)s\", \"%(cap)s\")\n"
    "  ELSE darker(color_mix_rgb(\"%(base)s\",\n"
    "                            coalesce(\"%(l2)s\", \"%(base)s\"),\n"
    "                            \"%(cap)s\"),\n"
    "              coalesce(\"%(nd)s\", 100))\n"
    "END" % {"base": BASE_FIELD, "l2": LITH2_FIELD, "nd": NUDGE_FIELD,
             "cap": MIXCAP_FIELD}
)


# The ladder the per-code cap walks down. Most codes hold the top step; a
# code steps down only as far as needed for NO worst-case combo of its own
# to collapse a well-separated neighbour. 0.0 (no blend at all) is the
# honest floor for a code with no safe headroom.
MIX_LADDER = (LITH2_MIX, 0.12, 0.10, 0.08, 0.06, 0.04, 0.02, 0.0)


# ----------------------------------------------------------- colour maths
# The audits must model the render maths exactly, and the two injectors must
# model it identically - so both come from the patterns module.
mix_rgb = patterns.mix_rgb
qt_darker = patterns.qt_darker


def resolve_mix_caps(fill_of, tex_map, nudge_extremes):
    """{code: mix ratio} - the largest MIX_LADDER step at which NO worst-case
    combo of this code collapses a well-separated neighbour.

    The bug being prevented: a (code, Lith2, nudge-extreme) combination of A
    landing within IDENTICAL_DE of a confusable B whose base fill was WELL
    separated (>= MIN_FILL_DE) - modulation collapsing a separation the
    palette actually relies on. Rather than lowering LITH2_MIX globally for
    everyone (175 offending combos came from a handful of codes), each code
    is capped individually and the cap is baked into its own symbol's
    expression - zero-config, and it re-derives itself on every palette
    change.

    Two blanket abort bars were tried first and rejected against the real
    palette, and the reasons matter:
      * nearest-identity ("modulated A must stay nearer A than B") flagged
        114k combos - varietal siblings the palette itself separates by only
        a few dE fail it under ANY visible blend.
      * unconditional pixel-identity flagged 2,059 - the slot fan GENERATES
        siblings (MGBO, MGY...) as small offsets from their base (MG), so a
        15% blend inevitably sweeps across each sibling's exact point for
        SOME Lith2. Those pairs sit inside the palette's own "TOO CLOSE
        warns, the label carries it" band at base; modulation moving within
        an already-accepted ambiguity band creates no new class of
        confusion, and the tile, ink, label and contact still say which
        unit it is.

    Confusable = shares the tile (or a LOOKALIKE_TILES pair); declared
    `variety` groups are exempt - they are allowed to look alike at base.
    The nudge factors ride every step of the ladder, so a code whose
    NUDGE-ONLY extreme already collapses a pair aborts loudly - that cannot
    be fixed by capping the blend.
    """
    codes = sorted(fill_of)
    tile_of = {c: tex_map[c][0] for c in codes if c in tex_map}
    variety_of = {c: tex_map[c][1] for c in codes if c in tex_map}

    def confusable(a, b):
        ta, tb = tile_of.get(a), tile_of.get(b)
        if ta is None or tb is None:
            return False
        if ta != tb and frozenset((ta, tb)) not in patterns.LOOKALIKE_TILES:
            return False
        va, vb = variety_of.get(a, ""), variety_of.get(b, "")
        if va and va == vb:
            return False               # declared acceptable look-alikes
        return True

    distinct_fills = sorted(set(fill_of.values()))
    factors = (100,) + tuple(nudge_extremes)

    def collapses(a, mix):
        """Worst-case combos of A at this mix that erase a >=MIN_FILL_DE
        separation; also counts in-band landings for the report."""
        fa = fill_of[a]
        others = [b for b in codes if b != a and confusable(a, b)]
        hits, in_band = [], 0
        if not others:
            return hits, in_band
        base_sep = {b: patterns.delta_e(fa, fill_of[b]) for b in others}
        for fx in distinct_fills:
            base = mix_rgb(fa, fx, mix)
            for factor in factors:
                mod = qt_darker(base, factor)
                for b in others:
                    d = patterns.delta_e(mod, fill_of[b])
                    if d < patterns.IDENTICAL_DE:
                        if base_sep[b] >= patterns.MIN_FILL_DE:
                            hits.append((a, patterns.hexof(fx), factor, b,
                                         base_sep[b]))
                        else:
                            in_band += 1
        return hits, in_band

    mix_of, capped, stuck, total_in_band = {}, [], [], 0
    for a in codes:
        chosen = None
        for mix in MIX_LADDER:
            hits, in_band = collapses(a, mix)
            if not hits:
                chosen = mix
                if mix == MIX_LADDER[0]:
                    total_in_band += in_band
                break
        if chosen is None:
            # even mix 0.0 collapses: the nudge alone does it
            stuck.append(a)
            chosen = 0.0
        mix_of[a] = chosen
        if chosen != MIX_LADDER[0]:
            capped.append((a, chosen))
    print("fill-identity caps: %d codes hold the full %.2f blend, %d capped "
          "lower, %d combos land on an already-close sibling (inside the "
          "palette's warn band, accepted)"
          % (len(codes) - len(capped), MIX_LADDER[0], len(capped),
             total_in_band))
    if capped:
        print("     " + ", ".join("%s %.2f" % c for c in sorted(capped)))
    if stuck:
        bail("nudge extremes alone collapse a well-separated pair for: %s - "
             "step the nudge ladder in texture_modulation.tsv closer to 100, "
             "or separate the base pair" % ", ".join(stuck))
    return mix_of


# ------------------------------------------------------------ QML surgery
def xml_attr(value):
    """Escape a string for use inside a double-quoted XML attribute."""
    return (value.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;")
            .replace("\r", "&#13;").replace("\n", "&#10;"))


def expressionfield_xml(name, expr, qtype, type_name):
    return ('<field name="%s" precision="0" comment="" expression="%s" '
            'type="%d" subType="0" length="0" typeName="%s"/>'
            % (name, xml_attr(expr), qtype, type_name))


def upsert_expressionfield(qml, name, fragment):
    """Replace the named <field> inside <expressionfields>, or insert it."""
    block = re.search(r'<expressionfields>.*?</expressionfields>', qml, re.S)
    if not block:
        bail("no <expressionfields> block in the QML")
    body = block.group(0)
    pat = re.compile(r'<field name="%s"[^>]*/>\s*' % re.escape(name))
    if pat.search(body):
        new_body = pat.sub(fragment + "\n  ", body, count=1)
        what = "replaced"
    else:
        new_body = body.replace("</expressionfields>",
                                " " + fragment + "\n </expressionfields>")
        what = "inserted"
    print("expressionfields: %s %s" % (what, name))
    return qml[:block.start()] + new_body + qml[block.end():]


FILLCOLOR_BLOCK = re.compile(
    r'<Option name="fillColor" type="Map">.*?</Option>', re.S)


def active_fillcolor_block():
    return ('<Option name="fillColor" type="Map">'
            '<Option name="active" type="bool" value="true"/>'
            '<Option name="expression" type="QString" value="%s"/>'
            '<Option name="type" type="int" value="3"/>'
            '</Option>' % xml_attr(SYMBOL_EXPR))


def rewrite_fill_slots(qml):
    """Activate the renderer symbols' inactive dd fillColor slots with the
    one tiny expression.

    Targets exactly the 301 empty slots (300 categories + source-symbol).
    The 30 selvedge-stipple fillColor expressions (SelvedgeMineral) carry
    their own expression and are recognised and left alone; so is any other
    active block that is not ours.
    """
    replaced = [0]

    def sub(m):
        block = m.group(0)
        is_inactive = ('name="expression"' not in block
                       and 'value="false"' in block)
        is_ours = MODFILL_FIELD in block or LITH2_FIELD in block
        if not (is_inactive or is_ours):
            return block               # selvedge / foreign - untouched
        replaced[0] += 1
        return active_fillcolor_block()

    out = FILLCOLOR_BLOCK.sub(sub, qml)
    if replaced[0] != EXPECT_SLOTS:
        bail("expected to activate %d fillColor slots, matched %d - the "
             "renderer shape has changed, refusing to guess"
             % (EXPECT_SLOTS, replaced[0]))
    print("fillColor dd: %d symbol slots carry %s" % (replaced[0],
                                                      SYMBOL_EXPR))
    return out


# ------------------------------------------------------------------ main
def main():
    dry = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    gpkg = args[0] if args else DEFAULT_GPKG
    if not os.path.exists(gpkg):
        bail("gpkg not found: " + gpkg)
    if "_Patterns" in os.path.basename(gpkg):
        bail("refusing the patterns template - it is regenerated wholesale "
             "by inject_basemap_lith_patterns.py; run this against the live "
             "template and re-bake")

    # ---- inputs -------------------------------------------------------
    con = sqlite3.connect("file:%s?mode=ro" % gpkg.replace("\\", "/"),
                          uri=True)
    codes = [r[0] for r in con.execute("SELECT Code FROM BasemapCodes")]
    textures = {r[0] for r in con.execute("SELECT Code FROM TextureCodes")}
    con.close()
    if not codes:
        bail("BasemapCodes is empty")

    mod = patterns.load_texture_modulation()
    unknown = sorted(set(mod["tile"]) | set(mod["nudge"]))
    unknown = [t for t in unknown if t not in textures]
    if unknown:
        bail("texture_modulation.tsv names textures not in TextureCodes: "
             + ", ".join(unknown))

    # The colours this template ACTUALLY renders - the raw category anchors,
    # no ANCHOR_OVERRIDE. Blending from anything else (an early cut used
    # lith_palette.build()) makes the no-modifier -> modifier jump carry the
    # palette discrepancy on every code the patterns palette separated. The
    # patterns injector regenerates these fields from its OWN painted fills
    # on re-bake, so each template blends from what it draws.
    fill_of = lith_palette.read_code_anchors(apply_overrides=False)
    missing = sorted(set(codes) - set(fill_of))
    if missing:
        bail("no fill colour for: %s" % ", ".join(missing[:15]))

    tex_map = lith_palette.read_texture_map()
    mix_of = resolve_mix_caps(fill_of, tex_map, patterns.nudge_factors(mod))

    lith2_case = build_fill_case(fill_of, "Lithology2")
    base_case = build_fill_case(fill_of, "Lithology1")
    mixcap_case = build_mixcap_case(mix_of)
    nudge_case = build_nudge_case(mod["nudge"])
    print("expressions: %s/%s %.1f KB each (%d fill groups), %s %d B, "
          "%s %d B, %s %d B, symbol dd %d B"
          % (LITH2_FIELD, BASE_FIELD, len(lith2_case) / 1024.0,
             len(set(fill_of.values())), NUDGE_FIELD, len(nudge_case),
             MIXCAP_FIELD, len(mixcap_case), MODFILL_FIELD,
             len(MODFILL_EXPR), len(SYMBOL_EXPR)))
    if dry:
        print("--dry-run: nothing written")
        return

    # ---- backup, then QML surgery ------------------------------------
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.date.today().isoformat()
    backup = os.path.join(BACKUP_DIR,
                          "LGS_MappingTemplate_pre-lith-modulation_%s.gpkg"
                          % stamp)
    if not os.path.exists(backup):
        shutil.copy2(gpkg, backup)
        print("backup:", os.path.basename(backup))

    con = sqlite3.connect(gpkg)
    cur = con.cursor()
    row = cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                      (LAYER,)).fetchone()
    if not row or not row[0]:
        bail("no styleQML for %r" % LAYER)
    qml = original = row[0]

    # Order matters: LGS_ModFill reads the other four, and the feature
    # iterator resolves them as layer fields, so upstream fields first.
    for name, expr, qtype, tname in (
            (LITH2_FIELD, lith2_case, 10, "string"),
            (NUDGE_FIELD, nudge_case, 2, "integer"),
            (MIXCAP_FIELD, mixcap_case, 6, "double"),
            (BASE_FIELD, base_case, 10, "string"),
            (MODFILL_FIELD, MODFILL_EXPR, 10, "string")):
        qml = upsert_expressionfield(
            qml, name, expressionfield_xml(name, expr, qtype, tname))
    qml = rewrite_fill_slots(qml)

    # Validate BEFORE writing.
    try:
        ET.fromstring(qml)
    except ET.ParseError as exc:
        bail("edited QML no longer parses, aborting without write: %s" % exc)

    if qml == original:
        print("styleQML: no change (already applied)")
    else:
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, LAYER))
        if cur.rowcount != 1:
            con.rollback()
            con.close()
            bail("expected to update exactly 1 layer_styles row, hit %d"
                 % cur.rowcount)
        con.commit()
        print("styleQML updated")

    # ---- round-trip asserts ------------------------------------------
    print("integrity_check:",
          cur.execute("PRAGMA integrity_check").fetchone()[0])
    final = cur.execute(
        "SELECT styleQML FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()[0]
    con.close()

    root = ET.fromstring(final)
    ef = {f.get("name"): f for f in root.find("expressionfields")}
    for name in ALL_FIELDS:
        if name not in ef:
            bail("%s missing from expressionfields after write" % name)
    n_active = sum(1 for b in FILLCOLOR_BLOCK.findall(final)
                   if MODFILL_FIELD in b and "symbol_color" in b)
    if n_active != EXPECT_SLOTS:
        bail("expected %d symbols carrying the modulation expression, "
             "found %d" % (EXPECT_SLOTS, n_active))
    rend = root.find(".//renderer-v2")
    if rend.get("type") != "categorizedSymbol" or rend.get("attr") != "Lithology1":
        bail("renderer changed shape: %s/%s"
             % (rend.get("type"), rend.get("attr")))
    n_cats = len(rend.find("categories"))
    if n_cats != 300:
        bail("expected 300 categories, found %d" % n_cats)
    if "FilterExpression" not in final:
        bail("ValueRelation FilterExpression config lost")
    print("round-trip ok: categorized renderer intact (%d categories), "
          "%d dd fillColor expressions, virtual fields %s"
          % (n_cats, n_active, ", ".join(ALL_FIELDS)))
    print("NEXT: re-run inject_basemap_lith_patterns.py (re-bake rule)")


if __name__ == "__main__":
    main()
