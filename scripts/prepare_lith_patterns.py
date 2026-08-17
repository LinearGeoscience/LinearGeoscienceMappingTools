"""Curate + repair the lithology texture tiles into Template/patterns/.

The authored library (73 tiles, OneDrive "QGIS Patterns/LGS_lith_Patterns")
has two problems this script fixes, writing the results into the repo so
Template/patterns/ becomes the git-tracked source of truth:

1. ZERO-LENGTH LINE DOTS. 21 of the 73 tiles draw stipple as

       <line x1="5" y1="5" x2="5" y2="5" stroke-linecap="round"/>

   The SVG spec says a zero-length subpath with a round linecap paints a
   dot; Qt's QSvgRenderer - which is exactly what QGIS and QField use -
   paints nothing. 15 files render ENTIRELY BLANK (Sandstone,
   Conglomerate, Alluvium, Colluvium, Andesite, Arkose, Dacite, Eclogite,
   Peridotite, Porphyry, Tillite, Phosphorite, Kimberlite, Dunite,
   Siltstone, Hornfels) and 6 more are partly blank.

   Repair: x2 = x1 + 0.001. A hair-length line still paints both round
   caps, so the dot is identical to a <circle> BUT the diameter stays
   driven by stroke-width, i.e. param(outline-width) keeps working.
   Verified through QgsSvgCache: widths 0.4/1.0/2.0/4.0 render 0/0/4/16
   dark px, and param(outline) recolours correctly. A fixed-radius
   <circle> would have rendered the same but gone inert under QGIS's
   stroke-width control.

2. NAMES THAT MISLEAD. The filenames are rock names but the artwork is
   generic motifs, and they collide heavily - Greenschist / Schist /
   Migmatite / Gneiss / Serpentinite / Greenstone / Augen_Gneiss /
   Bentonite are ONE lenticular motif; Limestone / Marl / Chalk /
   Calc_Silicate / Anorthosite are ONE brick motif; ten files are stipple
   at differing densities. CURATION picks one clean representative per
   motif and renames it after what it draws, so the code->texture mapping
   in inject_basemap_lith_patterns.py reads honestly.

Idempotent: re-running with the same source produces byte-identical
output. Safe to run without the source present once Template/patterns/
is populated (it verifies and exits).

Usage:  python scripts/prepare_lith_patterns.py [path\\to\\source\\dir]
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lith_tile_seams as seams          # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(REPO, "Template", "patterns")
# Tiles that cannot come from the library: a motif nobody authored (calcrete),
# or artwork whose band structure a transform cannot fix. Checked FIRST, so an
# entry here overrides the library file named in CURATION.
AUTHORED = os.path.join(REPO, "Template", "patterns_authored")
DEFAULT_SOURCE = os.path.join(
    os.path.expanduser("~"), "OneDrive", "2 - Work", "Linear Geoscience",
    "Q", "QGIS", "QGIS Patterns", "LGS_lith_Patterns")
STROKE_WIDTHS = os.path.join(DEST, "stroke_widths.tsv")

# Texture name -> source file. Names are the vocabulary the per-code mapping
# (Template/patterns/lith_textures.tsv) speaks, so they name the ROCK where
# the artwork genuinely depicts it and the MOTIF where it is generic.
#
# Round 1 used 16 family-level motifs and that was too coarse to be
# defensible: it put a vein hatch on aplite and flattened 20+ separate felsic
# intrusives onto one "cross". Extra textures are effectively free here -
# one data-defined symbol layer serves all of them - so the only real limit
# is how many a mapper can tell apart on a tablet.
#
# That limit was measured, not guessed: rendering all 73 tiles and clustering
# them by cosine distance on their ink maps gives ~48 genuinely distinct
# groups. Everything below is either a singleton or the chosen representative
# of its cluster. Tiles DELIBERATELY LEFT OUT because they are near-duplicates
# of one already here:
#   Augen_Gneiss, Serpentinite   ~ schist
#   Peridotite                   ~ gabbro      (dunite carries the ultramafics)
#   Andesite                     ~ pegmatite   (basalt carries volcanic chevrons)
#   Cataclasite                  ~ slate
#   Obsidian                     ~ phyllite
#   Marble, Shale, Chalk, Marl,
#   Calc_Silicate, Anorthosite,
#   Argillite, Talus, Granulite  ~ limestone / mudstone / iron_formation
#   Komatiite                    ~ porphyry / tonalite
CURATION = [
    # --- felsic intrusive ------------------------------------------------
    ("granite",        "Lit_Granite.svg",      7),  # coarse + and x marks
    ("granodiorite",   "Lit_Granodiorite.svg", 7),  # + with paired dashes
    ("syenite",        "Lit_Syenite.svg",      7),  # dense angled ticks
    # NB named for what it DRAWS, not its source file: this is the fine
    # felsic motif (aplite, microgranite, aplogranite). The rock Tonalite
    # takes "granodiorite"; letting the file name win here is exactly the
    # trap that put a vein hatch on aplite in round 1.
    ("felsic_fine",    "Lit_Tonalite.svg",     2),  # sparse fine + marks
    ("pegmatite",      "Lit_Pegmatite.svg",    5),  # coarse sparse blades
    ("porphyry",       "Lit_Porphyry.svg",     7),  # phenocryst blocks
    # --- intermediate ----------------------------------------------------
    ("diorite",        "Lit_Diorite.svg",      6),  # dashes in pairs
    # --- mafic -----------------------------------------------------------
    ("gabbro",         "Lit_Gabbro.svg",       7),  # paired heavy dashes
    ("dolerite",       "Lit_Dolerite.svg",    11),  # offset broken dashes
    ("amphibolite",    "Lit_Amphibolite.svg",  9),  # crossed needles
    # --- ultramafic ------------------------------------------------------
    ("dunite",         "Lit_Dunite.svg",       4),  # even dot grid
    ("pyroxenite",     "Lit_Pyroxenite.svg",   6),  # short paired bars
    # --- volcanic --------------------------------------------------------
    ("basalt",         "Lit_Basalt.svg",       6),  # v / chevron
    ("rhyolite",       "Lit_Rhyolite.svg",    12),  # flow banding
    ("tuff",           "Lit_Volcanic_Tuff.svg", 9),  # shards and lapilli
    # --- sedimentary -----------------------------------------------------
    ("sandstone",      "Lit_Sandstone.svg",    2),  # scattered dots
    ("greywacke",      "Lit_Greywacke.svg",    6),  # dots and short dashes
    ("conglomerate",   "Lit_Conglomerate.svg", 12),  # outlined clasts
    ("breccia",        "Lit_Breccia.svg",     17),  # angular clasts
    ("mudstone",       "Lit_Mudstone.svg",    12),  # broken horizontal dashes
    ("siltstone",      "Lit_Siltstone.svg",    5),  # fine stipple rows
    ("limestone",      "Lit_Limestone.svg",    9),  # offset brick courses
    ("chert",          "Lit_Chert.svg",       30),  # blocky mosaic
    ("evaporite",      "Lit_Evaporite.svg",   21),  # halite hoppers
    ("iron_formation", "Lit_Iron_Formation.svg", 33),  # heavy bands
    # --- metamorphic -----------------------------------------------------
    ("gneiss",         "Lit_Gneiss.svg",      15),  # lenses and bands
    ("migmatite",      "Lit_Migmatite.svg",   15),  # folded leucosome
    ("schist",         "Lit_Schist.svg",      11),  # wavy foliation
    ("phyllite",       "Lit_Phyllite.svg",    36),  # fine crenulation
    ("slate",          "Lit_Slate.svg",       56),  # close cleavage
    ("quartzite",      "Lit_Quartzite.svg",    6),  # dots and dashes
    ("hornfels",       "Lit_Hornfels.svg",     6),  # fine dense stipple
    ("skarn",          "Lit_Skarn.svg",       14),  # blocky garnet mesh
    ("mylonite",       "Lit_Mylonite.svg",    32),  # drawn-out streaks
    ("eclogite",       "Lit_Eclogite.svg",     6),  # ellipse clusters
    # --- regolith / transported cover ------------------------------------
    ("laterite",       "Lit_Laterite.svg",    16),  # pisolith rings
    ("alluvium",       "Lit_Alluvium.svg",     6),  # dots with dashes
    ("colluvium",      "Lit_Colluvium.svg",   19),  # mixed angular fragments
    ("gravel",         "Lit_Gravel.svg",       4),  # sparse small clasts
    ("claystone",      "Lit_Claystone.svg",   12),  # small square blocks
    # --- veins and structural --------------------------------------------
    ("crosshatch",     "Lit_CrossHatch.svg",  18),  # 45 deg cross-hatch
    # --- round 4: tiles added purely to separate rocks that were rendering
    # identically to a neighbour. 218 of 283 codes shared an identical
    # (fill, ink, tile) triple before these; the carbonates alone were a
    # group of six. Each was checked by eye against the tile it has to
    # separate from - Anorthosite was REJECTED here because its artwork is a
    # plain brick, i.e. a duplicate of Limestone and wrong for the rock.
    ("dolomite",       "Lit_Dolomite.svg",    30),  # brick + dense dots
    ("marble",         "Lit_Marble.svg",      15),  # brick + course marks
    ("marl",           "Lit_Marl.svg",        19),  # brick + dashes
    ("chalk",          "Lit_Chalk.svg",       11),  # brick + sparse dots
    ("stromatolite",   "Lit_Bentonite.svg",   10),  # wavy laminae
    ("granulite",      "Lit_Granulite.svg",   23),  # banded + granular
    ("augen_gneiss",   "Lit_Augen_Gneiss.svg", 17),  # eyes between bands
    ("peridotite",     "Lit_Peridotite.svg",   1),  # sparse paired marks
    ("serpentinite",   "Lit_Serpentinite.svg", 15),  # wavy + lenses
    ("ignimbrite",     "Lit_Ignimbrite.svg",  17),  # flattened shards
    ("dacite",         "Lit_Dacite.svg",      10),  # blocky phenocrysts
    ("arkose",         "Lit_Arkose.svg",       7),  # angular clusters
    ("shale",          "Lit_Shale.svg",       27),  # solid fine laminae
    ("cataclasite",    "Lit_Cataclasite.svg", 52),  # dense angular fragments
    # --- round 6: authored here, no library source ------------------------
    # RCC Calcrete was drawing a regolith carbonate as a bedded marine
    # limestone (and rendering as identical pixels to SLI once the limestone
    # chemical hue was applied on top). A calcrete is nodular, not bedded.
    ("calcrete",       None,                   8),  # carbonate nodules
]

# ---------------------------------------------------------------- seams
# Blank-band repairs (R3). These tiles satisfy the geometric edge rules and
# still show a stripe, because their motif rhythm does not divide their own
# period - siltstone runs 3,3,3,3,3 then 5 at the wrap, laterite 5,5,10. Four
# ways of detecting this automatically were built and measured; all four
# misfire (see scripts/lith_tile_seams.py), so the tiles are named.
#
# RELATTICE re-spaces the rows and preserves row COUNT and every within-row
# offset - those encode the grain size - so ink coverage barely moves.
RELATTICE = {
    "siltstone":  "y",   # 6 dot rows, 3,3,3,3,3 then 5 across the wrap
    "laterite":   "y",   # pisolith rings at y=5,10,15: gaps 5,5,10
    "peridotite": "y",   # same 5,5,10
    "mudstone":   "y",   # dash rows every 4 in a 24 box, 8 at the wrap
}

# RESIZE trims dead space so the wrap gap equals the interior gap. Only the
# repeat length changes: QGIS scales a tile by WIDTH, so height is free.
RESIZE = {
    "breccia": (30.0, 26.0),   # fragments end at y=25 in a 30 box
}

# Phase shifts that move strokes off the tile edges (R1). Computed once with
# lith_tile_seams.suggest_phase() - which places the boundary in the middle of
# the largest gap between stroke positions, i.e. maximum clearance - and STORED
# rather than re-derived, so this script stays byte-reproducible. Only tiles
# needing a non-zero shift are listed; every tile then gets wrap() regardless.
PHASE = {
    "alluvium":       (-5.5, -7.5),
    "arkose":         (-6.0, -5.5),
    "chalk":          (-17.0, -18.5),
    "colluvium":      (-7.0, -18.0),
    "dolomite":       (-7.5, -5.0),
    "dunite":         (-1.0, -2.0),
    "granulite":      (0.0, -4.0),
    "iron_formation": (0.0, -4.0),
    "limestone":      (-7.5, -5.0),
    "marble":         (-7.5, -5.0),
    "marl":           (-7.5, -2.0),
    "migmatite":      (1.0, -2.5),
    "porphyry":       (-4.0, -0.5),
    "shale":          (0.0, -8.3),
    "slate":          (0.0, -1.0),
}

# Tiles knowingly left alone. gneiss / migmatite / phyllite carry a DOUBLET
# band structure (a singlet, a pair, a singlet) that is the motif; relatticing
# them would flatten it into evenly spaced bands and destroy the rock. Their
# edge defects are fixed by wrap(); only the band rhythm is imperfect.
SEAM_ACCEPTED = {
    "gneiss": "doublet band structure is the motif, not a defect",
    "migmatite": "doublet band structure is the motif, not a defect",
    "phyllite": "crenulation spacing is deliberately irregular",
}

# The ELSE branch of the renderer expression needs a real tile: a NULL
# svgFile falls back to the symbol layer's static default instead of
# drawing nothing.
BLANK_NAME = "blank"
BLANK = ('<?xml version="1.0" encoding="UTF-8"?>\n'
         '<svg xmlns="http://www.w3.org/2000/svg" version="1.1"\n'
         '     viewBox="0 0 8 8" width="8pt" height="8pt">\n'
         '  <!-- deliberately empty: unmapped lithologies draw no texture -->\n'
         '  <rect width="8" height="8" fill="none" stroke="none"/>\n'
         '</svg>\n')

LINE_RE = re.compile(r'<line\b[^>]*/>')
ATTR_RE = re.compile(r'\b(x1|y1|x2|y2)\s*=\s*"([^"]*)"')


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def repair_dots(svg):
    """x2 = x1 + 0.001 on every zero-length line. Returns (svg, n_fixed).

    Textual rather than an ElementTree round-trip so comments, formatting
    and attribute order survive and the files stay reviewable in a diff.
    """
    fixed = [0]

    def fix(m):
        el = m.group(0)
        a = dict(ATTR_RE.findall(el))
        if len(a) != 4:
            return el
        try:
            vals = {k: float(v) for k, v in a.items()}
        except ValueError:
            return el
        if vals["x1"] != vals["x2"] or vals["y1"] != vals["y2"]:
            return el
        fixed[0] += 1
        new_x2 = "%s" % round(vals["x1"] + 0.001, 4)
        return re.sub(r'\bx2\s*=\s*"[^"]*"', 'x2="%s"' % new_x2, el, count=1)

    return LINE_RE.sub(fix, svg), fixed[0]


def load_widths():
    """{texture: width_pt} if calibrated yet, else {}.

    The seam repair needs the REAL stroke width, not the 0.1 placeholder in the
    artwork: whether a motif crosses a tile edge depends on how fat its stroke
    is, and these run 0.24 to 2.49 pt. On a first run - no stroke_widths.tsv
    yet - fall back to a width wide enough to be conservative, then
    calibrate_lith_strokes.py and a second prepare settle it.
    """
    out = {}
    if not os.path.exists(STROKE_WIDTHS):
        return out
    with open(STROKE_WIDTHS, encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if line.startswith("#") or len(parts) < 2 or parts[0] == "texture":
                continue
            try:
                out[parts[0]] = float(parts[1])
            except ValueError:
                pass
    return out


def repair_seams(svg, motif, width):
    """Make one tile toroidal. Returns (svg, [notes]).

    Order matters: resize and relattice change where the motif sits, the phase
    shift moves it clear of the edges, and wrap is last because it has to see
    the final positions to know what crosses.
    """
    notes = []
    if motif in RESIZE:
        w2, h2 = RESIZE[motif]
        svg = seams.resize(svg, w2, h2)
        notes.append("repeat trimmed to %gx%g to remove the blank band"
                     % (w2, h2))
    if motif in RELATTICE:
        axis = RELATTICE[motif]
        svg, n = seams.relattice(svg, axis)
        notes.append("%d motif rows re-spaced on %s so the rhythm divides the "
                     "tile" % (n, axis))
    if motif in PHASE:
        dx, dy = PHASE[motif]
        svg = seams.phase_shift(svg, dx, dy)
        notes.append("motif shifted by (%g,%g) to clear the tile edges"
                     % (dx, dy))
    before = len(seams.parse(svg)[2])
    svg = seams.wrap(svg, width)
    after = len(seams.parse(svg)[2])
    if after != before:
        notes.append("%d wrap counterpart(s) added so edge-crossing motifs "
                     "complete across the seam" % (after - before))
    return svg, notes


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE

    names = [n for n, _s, _i in CURATION] + [BLANK_NAME]
    if len(set(names)) != len(names):
        bail("duplicate motif name in CURATION")

    authored = {n for n, s, _i in CURATION if s is None}
    if not os.path.isdir(source) and authored - {
            n for n, _s, _i in CURATION
            if os.path.exists(os.path.join(AUTHORED, n + ".svg"))}:
        bail("authored tiles missing from %s" % AUTHORED)
    if not os.path.isdir(source):
        # Already prepared? then this is a no-op, not a failure.
        missing = [n for n in names
                   if not os.path.exists(os.path.join(DEST, n + ".svg"))]
        if missing:
            bail("source dir not found and %d tiles missing from %s: %s"
                 % (len(missing), DEST, ", ".join(missing)))
        print("source dir absent; all %d tiles already present in %s"
              % (len(names), DEST))
        return

    os.makedirs(DEST, exist_ok=True)
    widths = load_widths()
    if not widths:
        print("note: no stroke_widths.tsv yet - seam repair will use a "
              "conservative width; re-run after calibrate_lith_strokes.py")
    total_fixed = 0
    total_seam = 0
    for motif, src, _ink in CURATION:
        if src is None:
            path = os.path.join(AUTHORED, motif + ".svg")
            origin = "authored (Template/patterns_authored/)"
        else:
            path = os.path.join(AUTHORED, motif + ".svg")
            if os.path.exists(path):
                origin = "authored override of " + src
            else:
                path = os.path.join(source, src)
                origin = src
        if not os.path.exists(path):
            bail("source tile not found: " + path)
        with open(path, encoding="utf-8") as fh:
            svg = fh.read()
        svg, n = repair_dots(svg)
        total_fixed += n
        if "param(outline)" not in svg:
            bail("%s: no param(outline) - artwork is not parameterised, "
                 "QGIS colour control would be inert" % origin)
        try:
            svg, seam_notes = repair_seams(svg, motif, widths.get(motif, 1.0))
        except ValueError as exc:
            bail("%s: seam repair could not handle the artwork: %s"
                 % (motif, exc))
        total_seam += len(seam_notes)
        header = ("<!-- LGS lithology texture: %s\n"
                  "     source: %s\n"
                  "     %s -->\n"
                  % (motif, origin,
                     "\n     ".join(
                         (["%d zero-length dot(s) repaired to x2=x1+0.001 "
                           "(Qt paints nothing for a zero-length subpath)" % n]
                          if n else [])
                         + seam_notes) or "no repair needed"))
        # keep the xml declaration first
        if svg.startswith("<?xml"):
            decl, rest = svg.split("\n", 1)
            out = decl + "\n" + header + rest
        else:
            out = header + svg
        with open(os.path.join(DEST, motif + ".svg"), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write(out)
        bits = (["%d dot(s)" % n] if n else []) + seam_notes
        print("  %-16s <- %-30s %s"
              % (motif, origin, "; ".join(bits)))

    with open(os.path.join(DEST, BLANK_NAME + ".svg"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(BLANK)
    print("  %-16s <- generated" % BLANK_NAME)

    # Drop tiles that have left CURATION. Without this a renamed texture
    # leaves its old file behind, and the next run reports it as "curated
    # but unused" while it silently stays available to the mapping.
    stale = sorted(f for f in os.listdir(DEST)
                   if f.endswith(".svg") and f[:-4] not in names)
    for f in stale:
        os.remove(os.path.join(DEST, f))
        print("  removed stale tile: " + f)

    print("\n%d tiles written to %s (%d zero-length dots repaired, "
          "%d seam repairs applied)"
          % (len(CURATION) + 1, DEST, total_fixed, total_seam))

    # Report, don't enforce: the test owns enforcement. But a silent
    # regression here would be found much later, so say it now.
    widths = load_widths()
    still = {}
    for motif, _src, _ink in CURATION:
        with open(os.path.join(DEST, motif + ".svg"), encoding="utf-8") as fh:
            issues = seams.audit(fh.read(), widths.get(motif, 1.0))
        if issues:
            still[motif] = issues
    if still:
        print("\n%d tile(s) still fail the seam rules:" % len(still))
        for motif, issues in sorted(still.items()):
            print("  %-16s %s" % (motif, issues[0][1]))
    else:
        print("seam audit: all %d tiles are toroidally sound" % len(CURATION))
    if SEAM_ACCEPTED:
        print("band rhythm knowingly left as authored: %s"
              % ", ".join(sorted(SEAM_ACCEPTED)))


if __name__ == "__main__":
    main()
