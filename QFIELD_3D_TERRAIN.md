# 3D terrain in QField

The QField exporter bakes one DEM into the exported project as its **terrain**, and QField
4.1+ drapes your mapping over it — fully offline. Everything below is about getting that
one DEM right; the rest is a checkbox in the export dialog.

There is no desktop 3D view in this plugin. QGIS's native 3D implementation proved too
unstable to build on; 3D lives on the device, where QField's terrain renderer is solid.

The supporting tools live on the **Field / Pit / UG** page:

| Tool | Group | What it does |
|---|---|---|
| **Pit Surface to DEM** | Terrain | Turns a Surpac `.str`+`.dtm` or DXF pit shell into a DEM GeoTIFF |
| **Generate Contours** | Terrain | Smooth, styled contours from a DEM |
| **Optimise Imagery for Field** | Imagery | Repacks a big ortho so it performs on a tablet — see below |
| **Import Mining Survey Data** | Mine Survey Data | Surpac / DXF / CSV survey strings and stations |
| **Z Filter**, **Add Elevation Field** | Level Filtering | Show one bench or level at a time |

---

## The one rule

**The terrain is one DEM per project.**

A project has exactly one terrain, so a regional mapping project and a pit project are
separate files with separate DEMs. In the worked example below, mixing them is not merely
untidy but impossible — the two datasets are 788 km apart in different UTM zones and
datums.

The exporter's **Terrain DEM** selector sets it. Your pick is saved with the project and
also written to `Project ▸ Properties ▸ Terrain`, so a project that reaches a device by
any other route (QFieldCloud, manual copy) carries the same terrain.

---

## Choosing the terrain DEM in the exporter

The export dialog has one terrain row:

> ☑ **Bake 3D terrain (QField 4.1+)**   Terrain DEM: `pit_ss_dem (pit)` ▾   Exaggeration: `1.0x`

- **The selector lists only plausible terrain.** Orthophotos (multi-band imagery) and DEM
  derivatives (hillshade, slope, aspect, contours) are not elevation and are not listed.
- **The right DEM is usually pre-selected**, by this ladder: your saved pick for the
  project → a Pit-Surface-to-DEM output (tagged, shown as **(pit)**) → a raster whose name
  says pit/bench/drone → the only local raster. Only a genuinely ambiguous project makes
  you pick — baking stays off until you do, so an export never silently ships without the
  terrain you thought was there.
- **Your pick is remembered with the project** and preferred on every later export.
- **The DEM is added to the export automatically** even if unticked in the layer list —
  otherwise the terrain would point at a file that is not on the tablet.
- **Set exaggeration now.** It is baked into the exported project and cannot be changed on
  the device. `1.0x` for pits (a pit already has real relief; 2x turns a batter into a
  cliff); `2x` can help subtle regional topography read. For two looks, do two exports.

---

## Will my GeoTIFFs work?

A DEM works as terrain if it is:

| Requirement | Why |
|---|---|
| **Projected CRS in metres** (MGA/UTM, not lat-long degrees) | QField's 3D refuses degree CRSs; exaggeration maths needs Z and XY in the same unit |
| Local file (GeoTIFF, `.img`, `.vrt`) | WMS/XYZ rasters are excluded from DEM detection — a web basemap has no single elevation |
| Single band, float or int elevation | Not an RGB image |
| Nodata declared | Undeclared voids render as spikes to sea level |

Two checked datasets, as examples of "yes, and" and "yes, but":

### Regional topography — `1_Second_DEM_Smoothed.tif` ✅ use as-is

```
CRS      EPSG:7850  GDA2020 / MGA zone 50   (projected, metres)  ✅
Size     2773 × 798, ~29 m pixels, Float32, LZW, 8.5 MB
Z range  488 – 742 m
Area     118.32°E  24.63°S   (Murchison, WA)
```

Nothing to fix. It is already projected (the Geoscience Australia original ships in
geographic degrees, so someone has reprojected this one — that step is what makes it usable).
At 8.5 MB it goes to a tablet without complaint.

### Pit — `BasemapJune/` ✅ works, but repack before the field

```
CRS      EPSG:28351  GDA94 / MGA zone 51   (projected, metres)   ✅
Area     121.90°E  30.97°S   (Fingals)
```

| File | Verdict |
|---|---|
| `260606_ff_pit_ss_dem.tif` | **Works.** Existing 0.79 m pit DEM, Z 352–412 m. But Float64 and **uncompressed**: 11.85 MB where 2.85 MB would do (see below). Nodata is `NaN` — declared, so fine. |
| `260606_ff_pit_ss.str` + `.dtm` | **Works.** 1.14 M vertices / 2.29 M triangles — *Pit Surface to DEM* reads it in 9 s and rasterizes in 40–50 s. |
| `260607_ff_stage3.str` + `.dtm` | **Works.** The stage-3 design shell, 842 k triangles, ~21 s end to end. No DEM exists for this one yet — this is the file that most needs the tool. |
| `260606_FF_Pit_transparent_mosaic_group1.tif` | **Drape only, never terrain** (it is RGBA imagery, and the selector will not offer it). ⚠️ **211 MB with zero overviews** — see "The ortho is the real problem". |
| `260606_ff_pit_ss.2dm` | Not supported. It is an SMS mesh, and the `.str`/`.dtm` pair carries the same surface — use those. |
| `*_hillshade.tif`, `*_slope.tif` | Derived products. Pointless in 3D — QField's view does its own shading. Leave them out of the export. |

**The two datasets are 788 km apart, in different UTM zones (50 vs 51) and different datums
(GDA2020 vs GDA94).** They are two different projects. The regional DEM cannot serve as
terrain for the Fingals pit, and the exporter will not offer it if you keep the projects
separate — which is the point of the rule above.

---

## Sizing a DEM for the field

Measured on the real Fingals surface (2.29 M triangles):

| Cell size | Grid | GeoTIFF | Use for |
|---|---|---|---|
| 0.5 m | 1823 × 2031 | 9.28 MB | Detail work |
| **1.0 m** | 912 × 1016 | **2.43 MB** | **Field default — bench faces still read clearly** |
| 2.0 m | 457 × 509 | 0.64 MB | Big pit, old tablet |

Repacking the existing 0.79 m pit DEM from Float64/uncompressed to Float32 + LZW takes it
from **11.85 MB → 2.85 MB** with no loss that matters (elevations are metres, not microns):

```
gdal_translate -ot Float32 -co COMPRESS=LZW -co TILED=YES -co PREDICTOR=3 \
  260606_ff_pit_ss_dem.tif 260606_ff_pit_ss_dem_f32.tif
```

### The ortho is the real problem — use Optimise Imagery for Field

The drone mosaic is 211 MB with **no overviews**, so every pan and zoom re-decodes the
full-resolution image. On a tablet that is the difference between usable and unusable, and it
hurts far more than the DEM ever will.

**Field / Pit / UG → Imagery → Optimise Imagery for Field** fixes it. Pick the raster, accept
the default profile, press Optimise. Measured on this exact ortho:

```
212 MB, 9177 × 10224, 4 bands, 0 overviews
   ->  37 MB, full resolution, 6 overview levels        (5.8x smaller, ~6 seconds)
```

Resolution is never reduced — the saving is compression plus pyramids.

| Profile | When |
|---|---|
| **COG + JPEG, keep transparency** *(default)* | Almost always. The clear margin around the survey stays clear. |
| COG + JPEG, drop transparency | Smallest, but the margin turns black. |
| COG + WEBP | Smaller again at the same visual quality. |
| COG + DEFLATE | Lossless, for imagery that must stay evidential. |
| Plain GeoTIFF + overviews | When it has to remain an ordinary TIFF. Still gets pyramids. |

**On transparency:** JPEG cannot carry a fourth band, so the default profile writes three
colour bands plus an internal mask. The output reports "3 bands" and that is correct — the
transparency is intact, verified against the source alpha.

**On tiling:** very large images are split into a grid of same-resolution tiles, because
QField pans more smoothly across several moderate tiles than one enormous file. Tiles are
named `_r01c02` with zero padding so they always sort in grid order, and they load into a
single layer group so the QField export treats them as one imagery layer. Aim for about
100 MB per tile; below that a single file is produced. This ortho needs no tiling at 37 MB.

The original is never modified — output is written alongside it. JPEG and WEBP are lossy, so
keep the original as the archive copy.

---

## Making a DEM when none exists — Pit Surface to DEM

The stage-3 case: you have the design shell, no DEM.

1. **Field / Pit / UG → Terrain → Pit Surface to DEM** → browse to `260607_ff_stage3.str`
   (the `.dtm` beside it is picked up automatically) → set **Cell size 1.0 m** →
   **Create DEM**.
2. It writes `260607_ff_stage3_dem.tif` beside the source, adds it to the project, and tags
   it as a pit surface — the exporter's terrain selector prefers it from then on.
3. Load the drone ortho too. It drapes onto the bench faces and is what makes a pit 3D view
   worth having.

---

## Taking 3D to the field

**Requires QField 4.1 or newer.** The 3D map view did not exist before 4.1 (March 2026);
older versions simply will not show the button. Check **QField ▸ Settings ▸ About**.

1. **Export to QField.** Confirm the terrain row: bake ticked, the right DEM selected,
   exaggeration set (it is fixed once exported).
2. Copy the export folder to the tablet as usual.
3. In QField, open the project, open the **dashboard** (the panel with the layer list), and
   tap the **3D cube icon** in its row of round buttons — next to the measuring-tool icon.
   Your mapping is draped on the pit.

**If you skip the bake**, QField falls back to global 30 m online tiles — useless at pit
scale and requiring a signal you probably do not have. The bake is what makes it work
offline.

### What works in the field

- Terrain from your own DEM, fully offline
- All mapping layers draped as texture
- Tap a feature on the 3D terrain to identify it
- Your GNSS position shown on the terrain, and tracking drawn as a 3D tube

### What does not

- **No underground view.** QField's 3D is a terrain surface; it cannot show workings below
  it.
- **No live exaggeration toggle** (baked at export, as above).
- **No 3D editing.** Digitise in 2D, then switch to 3D to check context.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Terrain row says "No DEM raster in project" | No DEM loaded, or the only raster is a web basemap (excluded deliberately). Load a DEM, or run Pit Surface to DEM. |
| Bake box disabled, selector on "Select a DEM…" | Two or more equally plausible candidates. It will not guess. Pick one; the choice is saved to the project. |
| Terrain has holes or spikes | Nodata not declared on the DEM (`gdalinfo` shows `NoData Value=`). Set it: `gdal_edit -a_nodata -9999 dem.tif`. |
| Pit looks like a mountain range | Exaggeration was set at export. Re-export at 1.0x. |
| No 3D cube icon in the QField dashboard | QField older than 4.1. |
| QField 3D shows generic hills, not your pit | The export was not baked — re-export with **Bake 3D terrain** ticked. |
| QField 3D shows the wrong surface | The wrong DEM was selected at export — pick the right one and re-export. |
| Tablet crawls when panning | The ortho, not the DEM. Build overviews (see above). |

**Sanity check any DEM before trusting it:**

```
gdalinfo -stats your_dem.tif
```

Confirm a projected CRS in metres, a sensible Z range in `Minimum=/Maximum=`, and a declared
`NoData Value=`.

---

## Notes

- Pit Surface to DEM assumes the **project CRS**, because Surpac and DXF files carry none.
  Set the project CRS before running it (EPSG:28351 for Fingals). This matches how the mining
  survey importer already behaves.
- Surpac coordinates are `northing, easting, RL`; the reader handles the swap.
- A source with strings but no triangulation cannot make a DEM — you need the `.dtm`, or a
  DXF with 3DFACE/polyface meshes.
- Output is written beside the source, never into the mapping template.
- Rasterizing runs in the background; QGIS stays usable.
