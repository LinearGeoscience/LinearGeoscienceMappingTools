# Viewing your mapping in 3D — desktop and field

One DEM becomes the project's **terrain**, and from then on both QGIS and QField drape your
mapping over it. Everything below is about getting that one setting right; the rest is
buttons.

Two tools, both in **Mapsheets & Layouts → Terrain**:

| Tool | What it does |
|---|---|
| **View in 3D** | Opens the 3D view, picks the DEM, live vertical exaggeration, Surface / Pit / Underground modes |
| **Pit Surface to DEM** | Turns a Surpac `.str`+`.dtm` or DXF pit shell into a DEM GeoTIFF |

---

## The one rule

**The terrain lives on the project, not on the view.**

`Project ▸ Properties ▸ Terrain` holds a DEM raster. QGIS's 3D view reads it. QField 4.1+
reads it. Set it once — *View in 3D* does this for you — and both are configured.

The corollary: **one project per site.** A project has exactly one terrain, so a regional
mapping project and a pit project are separate `.qgz` files with separate DEMs. See the
worked example below, where mixing them is not merely untidy but impossible.

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
| `260606_FF_Pit_transparent_mosaic_group1.tif` | **Drape only, never terrain** (it is RGBA imagery). ⚠️ **211 MB with zero overviews** — see "The ortho is the real problem". |
| `260606_ff_pit_ss.2dm` | Not supported. It is an SMS mesh, and the `.str`/`.dtm` pair carries the same surface — use those. |
| `*_hillshade.tif`, `*_slope.tif` | Derived products. Pointless in 3D — the 3D view does its own shading. Leave them out of the export. |

**The two datasets are 788 km apart, in different UTM zones (50 vs 51) and different datums
(GDA2020 vs GDA94).** They are two different projects. The regional DEM cannot serve as
terrain for the Fingals pit, and *View in 3D* will not offer it if you keep the projects
separate — which is the point of the rule above.

---

## Sizing a DEM for the field

Measured on the real Fingals surface (2.29 M triangles):

| Cell size | Grid | GeoTIFF | Use for |
|---|---|---|---|
| 0.5 m | 1823 × 2031 | 9.28 MB | Desktop detail work |
| **1.0 m** | 912 × 1016 | **2.43 MB** | **Field default — bench faces still read clearly** |
| 2.0 m | 457 × 509 | 0.64 MB | Big pit, old tablet |

Repacking the existing 0.79 m pit DEM from Float64/uncompressed to Float32 + LZW takes it
from **11.85 MB → 2.85 MB** with no loss that matters (elevations are metres, not microns):

```
gdal_translate -ot Float32 -co COMPRESS=LZW -co TILED=YES -co PREDICTOR=3 \
  260606_ff_pit_ss_dem.tif 260606_ff_pit_ss_dem_f32.tif
```

### The ortho is the real problem

The drone mosaic is 211 MB with **no overviews**, meaning every pan and zoom re-reads
full-resolution tiles. On a tablet that is the difference between usable and unusable — and
it hurts far more than the DEM ever will. Build overviews (adds ~30 %, pays for itself
immediately):

```
gdaladdo -r average --config COMPRESS_OVERVIEW JPEG 260606_FF_Pit_transparent_mosaic_group1.tif 2 4 8 16 32
```

Better still, make it a Cloud-Optimised GeoTIFF, which is overviews plus tiling in one file:

```
gdal_translate -of COG -co COMPRESS=JPEG -co QUALITY=85 \
  260606_FF_Pit_transparent_mosaic_group1.tif FF_Pit_ortho_cog.tif
```

JPEG compression on a 4-band RGBA ortho may drop the alpha band; if transparency around the
survey edge matters, use `-co COMPRESS=DEFLATE` instead and accept a larger file.

---

## Workflow A — regional mapping in 3D

1. Open your mapping project and load the DEM (`1_Second_DEM_Smoothed.tif`).
2. **Mapsheets & Layouts → Terrain → View in 3D.**
   The DEM is auto-detected, becomes the project terrain, and the 3D view opens over your
   current 2D extent with all visible layers draped.
3. Tick **Vertical exaggeration** and set 2× — subtle regional relief becomes readable.
   Untick to return to true scale. Both apply live.
4. Navigate:

   | Action | Control |
   |---|---|
   | Move over the ground | Left-drag |
   | Zoom | Wheel, or right-drag up/down (`Ctrl`+wheel for fine) |
   | Tilt | Middle-drag forward/back, or `Shift`+`↑`/`↓` |
   | Rotate | Middle-drag left/right, or `Shift`+`←`/`→` |
   | Look around without moving | `Ctrl`+arrow keys |
   | Camera height | `Page Up` / `Page Down` |

5. Save the project. The terrain setting is saved with it.

## Workflow B — pit mapping in 3D

1. **If you already have a pit DEM** (`260606_ff_pit_ss_dem.tif`), just load it. Skip to 3.
2. **If you only have the shell** (the stage-3 case):
   **Terrain → Pit Surface to DEM** → browse to `260607_ff_stage3.str`
   (the `.dtm` beside it is picked up automatically) → set **Cell size 1.0 m** → **Create DEM**.
   Writes `260607_ff_stage3_dem.tif` beside the source, adds it to the project, and tags it as
   a pit surface so the 3D view prefers it from then on.
3. Load the drone ortho too — it drapes onto the bench faces and is what makes a pit 3D view
   worth having.
4. **View in 3D** → mode **Pit**. The view frames the pit surface.
5. Exaggeration **1.0× (off)** for pits. A pit already has 60 m of relief over 900 m; 2×
   turns a batter into a cliff and makes bench widths lie.

**Bench filtering comes free.** If the Z Filter is on, its bench subset applies to the 3D
view too — the 3D view honours the same provider filters as the 2D canvas, so you can view
one bench in isolation without any extra setting.

## Workflow C — underground

1. Import development with **Import Mining Survey Data** (creates `MineStrings`,
   `MineStations`).
2. **View in 3D** → mode **Underground**.
   Terrain is hidden and the mine survey layers stand at their true RL.

Two things to know:
- Imports with no elevation are held back automatically (they would otherwise plot at sea
  level). Nothing to configure.
- **Exaggeration affects terrain only**, so in Underground mode it does nothing. Leave it off.
- Desktop only — see the QField limits below.

Leaving Underground mode, or closing the panel, restores every layer filter and 3D style the
mode borrowed.

---

## Taking 3D to the field (QField)

**Requires QField 4.1 or newer.** The 3D map view did not exist before 4.1 (March 2026);
older versions simply will not show the button. Check **QField ▸ Settings ▸ About**.

1. Get the desktop 3D view right first — the export inherits that DEM.
2. **Export to QField.** In the dialog you will see:

   > ☑ **Bake 3D terrain: `<your DEM>` (QField 4.1+)**    Exaggeration: `1.0x`

   It is ticked automatically when a DEM is found, and the DEM is added to the export even if
   you did not tick it in the layer list — otherwise the terrain would point at a file that is
   not on the tablet.
3. Set exaggeration **now**. Unlike the desktop it **cannot be changed on the device** — it
   is baked into the exported project. For two looks, do two exports.
4. Copy the export folder to the tablet as usual.
5. In QField, open the project, open the **dashboard** (the panel with the layer list), and tap
   the **3D cube icon** in its row of round buttons — next to the measuring-tool icon. Your
   mapping is draped on the pit.

**If you skip the bake**, QField falls back to global 30 m online tiles — useless at pit scale
and requiring a signal you probably do not have. The bake is what makes it work offline.

### What works in the field

- Terrain from your own DEM, fully offline
- All mapping layers draped as texture
- Tap a feature on the 3D terrain to identify it
- Your GNSS position shown on the terrain, and tracking drawn as a 3D tube

### What does not

- **No underground view.** QField's 3D is a terrain surface; it cannot show workings below
  it. Underground stays a desktop tool.
- **No live exaggeration toggle** (baked at export, as above).
- **No 3D editing.** Digitise in 2D, then switch to 3D to check context.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| "No local rasters in project" | No DEM loaded, or the only raster is a web basemap (excluded deliberately). Load a DEM, or run Pit Surface to DEM. |
| Panel asks you to pick a DEM | Two or more equally plausible candidates. It will not guess. Pick one; the choice is saved to the project. |
| 3D view is flat | Project terrain never got set — reopen **View in 3D** rather than QGIS's own 3D menu, which does not configure terrain. |
| Terrain has holes or spikes | Nodata not declared on the DEM (`gdalinfo` shows `NoData Value=`). Set it: `gdal_edit -a_nodata -9999 dem.tif`. |
| Pit looks like a mountain range | Exaggeration is on. Turn it off for pits. |
| No 3D cube icon in the QField dashboard | QField older than 4.1. |
| QField 3D shows generic hills, not your pit | The export was not baked — re-export with **Bake 3D terrain** ticked. |
| Underground mode greyed out | No `MineStrings` layer; run the mining survey import first. |
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
