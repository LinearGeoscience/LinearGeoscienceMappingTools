# Adding a lithology to `4 - Basemap`

A new lithology needs three things: a **code** in the lookup table, a **colour rule** in the
renderer, and an entry in the **texture expressions**. Miss the third and the polygon draws in
flat colour with no texture — that is the usual mistake.

Two ways to do it. Use the scripted path unless you are making a throwaway one-off.

---

## Where each piece of data lives

| Thing | Lives in |
|---|---|
| The code itself | `BasemapCodes` table in the gpkg |
| Which colour it draws | **the LIVE template** — see "Colour belongs in the live template" below |
| Which texture, what ink, how heavy | three data-defined expressions on **one** shared symbol layer |
| Code → texture assignment | `Template/patterns/lith_textures.tsv` |
| The texture artwork (generated) | `Template/patterns/*.svg` |
| Texture artwork we authored ourselves | `Template/patterns_authored/*.svg` |
| Stroke width + measured ink coverage per texture | `Template/patterns/stroke_widths.tsv` |
| Mineral ink colours | `Template/patterns/mineral_inks.tsv` |
| Resolved fill + ink per code (output, for review) | `Template/patterns/lith_fills.tsv` |
| Grain-size tile multipliers + texture fill nudges (per feature) | `Template/patterns/texture_modulation.tsv` |
| Mineral → ink-family map for the per-feature ink tint | `Template/patterns/mineral_families.tsv` |

### Colour belongs in the live template

`LGS_MappingTemplate.gpkg` is the source of truth for fill colour.
`inject_basemap_lith_patterns.py` re-copies it wholesale on every run and
`lith_palette.read_code_anchors()` reads each code's colour out of it, so:
**change a colour there, re-run the injector, and both templates agree.**
Editing the patterns copy directly is wiped by the next run.

`scripts/inject_basemap_h_recolour.py` is the worked example — it rewrites the
QML *and* the SLD in lockstep and refuses to touch the patterns copy.

---

## Path A — scripted (recommended)

### 1. Add the code to the lookup table

In QGIS, open the project, expand the **Codes** group, select `BasemapCodes`, toggle editing
and add a row:

| Field | Value | Rules |
|---|---|---|
| `Type` | `Lithology` | must be one of `Lithology`, `Regolith`, `Transported Cover` — these come from `BasemapCategories` |
| `Code` | `FMYN` | short, unique, prefix by family (`F` felsic, `I` intermediate, `M` mafic, `U` ultramafic, `S` sedimentary, `H` metamorphic, `Z` sheared, `V` vein, `R` regolith, `T` transported) |
| `Description` | `FMYN - My New Granite` | **must** be `CODE - Name`. The renderer label and the legend both reuse this string verbatim |
| `UUID` | any uuid4 | |

Leave `fid` to autoincrement. Save the edit.

The `Lithology1` dropdown on the Basemap form is a ValueRelation onto this table, filtered by
`TypeLith1`, so the new code appears in the form as soon as the row is saved.

### 2. Assign a texture

Add one tab-separated line to `Template/patterns/lith_textures.tsv`:

```
FMYN	granite	Lithology	My New Granite	-	kfeldspar	granite
```

| Column | Meaning |
|---|---|
| `code` | must match `BasemapCodes.Code` exactly |
| `texture` | filename (no `.svg`) of a tile in `Template/patterns/` |
| `type` | same as `BasemapCodes.Type` |
| `rock` | plain rock name |
| `note` | free text, `-` if none. Shown on the review sheet |
| `ink` | a name from `mineral_inks.tsv`, or `auto` for a tint of the fill |
| `variety` | a group name if this code is *allowed* to look like others in that group; `-` if it must be distinct |

### 3. Rebuild

```
python scripts\inject_basemap_lith_modulation.py
"C:\OSGeo4W\bin\python-qgis-ltr.bat" scripts\inject_basemap_lith_patterns.py
```

The modulation injector runs FIRST: it bakes the per-feature Lith2/texture/
mineral modulation (virtual fields + the dd fillColor on every class symbol)
into the live template from the current palette, and a code added or
recoloured without re-running it would blend from stale colours. The patterns
injector runs LAST — always — and refuses a half-applied modulation state.

It refuses to run if anything is inconsistent — a code in one table and not the other, a texture
with no tile, an ink that cannot be seen against its fill, or two different rocks that would
render identically. Read the abort message; it names the offending codes.

**Only if you also added a new `.svg` tile**, run these two first:

```
python scripts\prepare_lith_patterns.py                              # repairs + copies tiles
"C:\OSGeo4W\bin\python-qgis-ltr.bat" scripts\calibrate_lith_strokes.py   # per-tile stroke width
```

### 4. Check and deploy

```
"C:\OSGeo4W\bin\python-qgis-ltr.bat" scripts\make_lith_contact_sheet.py out.html
"C:\OSGeo4W\bin\python-qgis-ltr.bat" tests\test_basemap_lith_patterns_qgis.py
```

Then robocopy the plugin folder into both QGIS profiles.

---

## Path B — manual in QGIS

For a single code in a live project, where re-running the scripts is not worth it.

### 1. Add the code

As Path A step 1.

### 2. Duplicate a colour rule

`4 - Basemap` → **Properties → Symbology** (it is a **rule-based** renderer).

1. Right-click the rule of the most similar existing lithology → **Copy**, then **Paste**.
2. Double-click the new rule and set:
   - **Label**: `FMYN - My New Granite` (match `Description`)
   - **Filter**: `"Lithology1" = 'FMYN'`
   - **Symbol → Simple fill → Fill colour**: your colour
3. Leave the Simple line alone. Its colour, width and dash are data-defined off `ContactType`
   and are shared by every rule.

Keep the rule anywhere among the other code rules — order does not matter for these.

### 3. Add the code to the texture expressions

This is the step that gets missed.

The bottom rule, labelled **`Lithology texture`**, has no filter and carries a single
**SVG fill** symbol layer. That one layer textures all 283 lithologies, via three data-defined
overrides. Open it: **Lithology texture → Symbol → SVG fill**, then click the data-defined
button (**ε**) next to each of:

| Control | Stored as | Holds |
|---|---|---|
| the SVG file selector | `file` | `CASE WHEN "Lithology1" IN (...) THEN 'base64:...' ... END` — which tile |
| **Stroke colour** | `outlineColor` | which ink colour |
| **Stroke width** | `outlineWidth` | how heavy, per texture |

(If the labels differ in your QGIS build, the stored names in the second column are what to
look for — they are the keys in the layer's `data_defined_properties`.)

For each of the three, choose **Edit…** and add your code to the `IN ( ... )` list of the branch
you want:

```
WHEN "Lithology1" IN ('F','FGM','FGR','FI','FMYN') THEN 'base64:...'
```

Pick the same branch in all three — the branch of whichever existing lithology you copied. If
you skip this, the code falls to the `ELSE`, which is a deliberately empty tile: flat colour,
no texture.

### 4. Save the style back into the gpkg

**Properties → Style ▾ (bottom left) → Save Style → Save in database (GeoPackage)**, overwriting
the existing default style. Without this the change lives only in the current project file.

---

## Rules that matter

**Never add an SVG fill to an individual colour rule.** QGIS builds every rule's symbol on
every render pass whether or not it is on screen, and a pattern fill builds a raster brush each
time. One SVG fill on the shared rule costs ~0.35 ms per redraw; one per code measured **54 ms**
— a 14× regression that a tablet feels immediately. That is the entire reason the renderer is
shaped this way.

**Keep the `Lithology texture` rule last.** Rules draw in order, so it must come after the
colour rules to sit on top of them.

**Textures are off above 1:6000.** Measured: every texture holds 7–10% ink from 1:500 to
1:4000, then collapses to nothing by 1:8000 as the stroke goes sub-pixel. If you are zoomed out
and see no texture, that is the scale cutoff on the texture rule, not a fault.

**A tile must be a torus, not a picture in a box.** QGIS rasterises one tile and repeats it, so
its right edge butts its own left edge and its bottom butts its own top. Three things break
that, and at 1:200–1:500 the 12 pt tile is drawn 120–300 pt wide, so each reads as a stripe
across the polygon rather than as texture grain:

- a stroke lying **along** an edge — the two halves antialias independently into the brush, so
  the seam line never matches interior line weight;
- a motif **crossing** an edge with nothing completing it on the far side;
- a rhythm that does not **divide** the tile — rows every 4 units in a 24-unit box leaves an
  8-unit blank band once per repeat.

`prepare_lith_patterns.py` repairs the first two automatically (phase shift, then wrap
counterparts); `scripts/lith_tile_seams.py` audits all three and the test enforces it. The third
is a named table (`RELATTICE`, `RESIZE`) because it cannot be detected reliably — four metrics
were built and measured and all four misfire, including on the two tiles that were already
correct. That reasoning is in the module docstring; please read it before building a fifth.
`basalt.svg` and `evaporite.svg` are the hand-authored reference for what seamless looks like,
and the test asserts they keep passing.

**New artwork goes in `Template/patterns_authored/`, never in `Template/patterns/`.** The latter
is generated: `prepare_lith_patterns.py` overwrites it from the OneDrive library and deletes
anything not in `CURATION`, so a hand edit there survives exactly until the next run. A file in
`patterns_authored/` overrides the library source of the same name — that is how `calcrete` got
in, there being no source for it. The OneDrive library itself is never written.

**Texture strength is per texture, not one number.** The contrast target scales inversely with
each tile's measured ink coverage (column 3 of `stroke_widths.tsv`), so a heavy tile is softened
more than a sparse one and both read as the same weight on the page. `INK_BASE` is the dial;
override it for a comparison sweep with the `LGS_INK_BASE` environment variable, not an argv
flag — `calibrate_lith_strokes.py` and the test both import the module and would never see argv.
Which *direction* the ink moves is decided against a separate fixed reference, so turning the
dial down cannot silently flip the dark fills to unreadable dark-on-dark.

**Styles do not propagate to existing projects.** The plugin copies the template per project and
`.qgz` files embed their styles. After changing the template, restart QGIS and create a new
project. To fix an existing project, update its `layer_styles` row from the template.

**The live template and the patterns template differ.** `LGS_MappingTemplate.gpkg` is still a
**categorized** renderer with no textures — Path B step 2 there means adding a *category*, not a
rule, and step 3 does not apply. `LGS_MappingTemplate_Patterns.gpkg` is the rule-based one this
guide describes.

---

## If a script aborts

| Message | Fix |
|---|---|
| `codes in BasemapCodes have no row in lith_textures.tsv` | add the TSV line (Path A step 2) |
| `rows name codes that are not in BasemapCodes` | the TSV has a code the table does not; remove it or add the row |
| `textures with no tile in Template/patterns/` | the `texture` column names a file that is not there |
| `no calibrated stroke width for: …` | re-run `calibrate_lith_strokes.py` |
| `pairs of different rocks render identically` | give one a different texture, or declare them a shared `variety`. This check is **global**, not per family: a chemistry hue or a shared anchor collides across families, never inside one |
| `code … has an ink that cannot separate from its fill` | pick a different ink, or `auto`. The bar scales with that tile's own contrast target, so this means genuinely invisible, not merely soft |
| `no measured ink coverage for: …` | `stroke_widths.tsv` predates the per-texture contrast target; re-run `calibrate_lith_strokes.py` |
| `seam repair could not handle the artwork` | the tile uses a relative path command (lowercase `m`/`l`/`q`); rewrite it with absolute commands |
| a tile still fails the seam audit after `prepare` | add a `PHASE` / `RELATTICE` / `RESIZE` entry for it in `prepare_lith_patterns.py`, or a reasoned entry in `SEAM_ACCEPTED` |
