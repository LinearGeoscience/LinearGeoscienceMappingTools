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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(REPO, "Template", "patterns")
DEFAULT_SOURCE = os.path.join(
    os.path.expanduser("~"), "OneDrive", "2 - Work", "Linear Geoscience",
    "Q", "QGIS", "QGIS Patterns", "LGS_lith_Patterns")

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
]

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


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE

    names = [n for n, _s, _i in CURATION] + [BLANK_NAME]
    if len(set(names)) != len(names):
        bail("duplicate motif name in CURATION")

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
    total_fixed = 0
    for motif, src, _ink in CURATION:
        path = os.path.join(source, src)
        if not os.path.exists(path):
            bail("source tile not found: " + path)
        with open(path, encoding="utf-8") as fh:
            svg = fh.read()
        svg, n = repair_dots(svg)
        total_fixed += n
        if "param(outline)" not in svg:
            bail("%s: no param(outline) - artwork is not parameterised, "
                 "QGIS colour control would be inert" % src)
        header = ("<!-- LGS lithology texture: %s\n"
                  "     source: %s\n"
                  "     %s -->\n"
                  % (motif, src,
                     "%d zero-length dot(s) repaired to x2=x1+0.001 "
                     "(Qt paints nothing for a zero-length subpath)" % n
                     if n else "no dot repair needed"))
        # keep the xml declaration first
        if svg.startswith("<?xml"):
            decl, rest = svg.split("\n", 1)
            out = decl + "\n" + header + rest
        else:
            out = header + svg
        with open(os.path.join(DEST, motif + ".svg"), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write(out)
        print("  %-16s <- %-24s %s"
              % (motif, src, "repaired %d dot(s)" % n if n else ""))

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

    print("\n%d tiles written to %s (%d zero-length dots repaired)"
          % (len(CURATION) + 1, DEST, total_fixed))


if __name__ == "__main__":
    main()
