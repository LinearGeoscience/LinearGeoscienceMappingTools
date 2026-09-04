# Reconcile / Merge Field Data — User Guide

> Covers the **Reconcile / Merge Field Data** tool (left sidebar → *Reconcile /
> Merge*, or *Data Management → Modify and Merge Data → Reconcile / Merge Field
> Data*) and its companions **Issue Field Copy** and the **Checkouts** dashboard.

---

## 1. What it is, and when to use it

When one or more geologists map in QField, each works on their own copy of the
mapping GeoPackage and you later fold their edits back into the **master**.
The **Import Mapping Data** tool only ever *inserts* new features —
re-importing an edited copy silently skips the edits, deletes never propagate,
and split/merged polygons lose their lineage.

**Reconcile** is a **UUID-keyed three-way merge** (like Git, but for
features). It propagates **adds, edits, and deletes**, merges edits from
different people on the same feature, detects **splits/merges**, and lets you
**re-sync the same edited copy without losing edits**.

| Use **Import Mapping Data** when… | Use **Reconcile** when… |
|---|---|
| One-off bulk import of brand-new features | Ongoing two-way sync of copies ↔ master |
| You never edit features after import | People edit, delete, split or merge existing features |
| You don't need conflict handling | Two+ people touched the same area |

---

## 2. The mental model

- **Identity is the `UUID`**, never the per-file `fid`. QField generates it via
  the `uuid('WithoutBraces')` default.
- **Master GeoPackage** = the central truth.
- **Working copy** = a mapper's QField copy (a template, a full copy, or a
  clipped area of the master).
- **Base snapshot** = the *common ancestor* — what the copy looked like when it
  was issued, **and after each accepted sync**. The merge compares **working vs
  base** and **master vs base** to decide what each side changed. **This is the
  single most important concept** — delete detection, split/merge lineage and
  the polygon-cleanup scenario in §13 only work because the base records what
  has already been synced.
- **Re-sync without loss:** after every accepted reconcile the base advances to
  the agreed state, so the next sync sees further edits as **updates**.

### Where the base lives: inside the copy

Every properly issued working copy **carries its own base** in hidden tables
inside the GeoPackage (`lgs_checkout` = who/when/which master;
`lgs_base` = per-feature fingerprints). They are invisible to QField and QGIS.
Because the copy is self-describing you can rename it, move it, e-mail it, or
edit it on any platform — reconcile still knows exactly what it started from,
and two mappers with same-named files can never clobber each other's base.

Copies get stamped **automatically** at the only moment a base is valid —
creation time — by:

- **Export for QField** (any exported mapping gpkg, zero-config),
- **Issue Field Copy** (deliberate hand-outs and re-issues, §4),
- **New Mapping Template**'s change-tracking option.

A plain Windows file-copy of the master carries no stamp. The preview then
shows a loud **NO RECORDED BASE** banner: adds still flow, but deletes and
split/merge lineage **cannot be detected**. If you see that banner, apply only
what is clearly safe, then re-issue the copy properly.

A legacy JSON sidecar base (`adddata_metadata/<master>_<copy>_base.json`) is
still read as a fallback for copies issued before the embedded store existed,
and is kept up to date as a recovery mirror (if the working file is locked at
sync time, the sidecar carries the advanced base; the newer capture wins next
build).

---

## 3. One-time setup per master — "Verify / migrate master"

Before the first reconcile against a master, click **Verify / migrate master**
(idempotent, safe to re-run). It:

- adds the `lgs_*` tracking columns to the four standard layers,
- backfills blank UUIDs and **reports duplicates** (never changes existing UUIDs),
- verifies the `uuid('WithoutBraces')` default on each layer,
- stamps a stable **master identity** (`lgs_master` table) so a copy issued
  from a *different* master is refused instead of silently merged.

The dialog checks this when you pick a master and **won't build a preview**
until it has run. The Issue Field Copy tool and the QField exporter check it
too (the exporter warns and skips stamping; the issue tool refuses).

> **Duplicate UUIDs:** migrate reports them but leaves them alone. Fix them
> before reconciling (regenerate `uuid('WithoutBraces')` on all but one row of
> each group) — UUID is the identity key and duplicates are silently dropped
> from the merge.

---

## 4. Issuing working copies (and re-issuing after clean-ups)

**Reconcile / Merge → Issue field copy…** creates a stamped hand-out from the
master. Pick what the copy contains:

- **Full copy** — the mapper sees all existing mapping.
- **Blank template** — schema, styles and lookup tables; no features.
- **Clipped area** — only features intersecting an AOI, taken from the current
  canvas extent or the selected features of the active layer. The AOI is
  recorded on the checkout.

Set the **Mapper ID**, accept the suggested destination
(`<master>/handouts/<master>_<mapper>_<date>.gpkg`), click **Issue copy**.
The copy is stamped and registered before it leaves the building.

This is also the **re-issue** operation: after the master has been cleaned up
(small polygons merged, stray features deleted), issue the mapper a fresh copy
so they map forward from the cleaned state (§13 explains why this matters).

**Export for QField** covers the everyday path automatically: every exported
mapping gpkg from a migrated master is stamped as an `export`-mode checkout
with no extra clicks (checkbox under *QField Plugin Tools* if you ever need to
export reference data that will never come back).

**View checkouts…** lists every copy issued against the master — mapper,
issue date, source mode, last sync, out / reconciled, and whether the file is
still where it was issued — with shortcuts to reconcile or re-issue one.

---

## 5. Step-by-step sync

1. **Sidebar → Reconcile / Merge** (or the Data Management page).
2. Pick the **Master GeoPackage** and the **Working copy**. Mapper ID
   pre-fills from the copy's stamp.
3. First time on this master: **Verify / migrate master** (the dialog insists).
4. Say yes when offered **Prepare field data** (hardcode): it fills blank
   UUIDs, legends and coordinates so features reconcile cleanly.
5. **Build preview** — classifies every feature, grouped per layer. Nothing is
   written yet. The summary line says which base was used
   (*embedded / legacy sidecar / NONE — synthesized*).
6. Resolve each **conflict**; tick/untick each **split/merge** proposal; read
   any red warning rows (§7).
7. **Apply reconcile** — commits in one transaction per layer, advances the
   base (in the copy **and** the sidecar), logs it.
8. The same copy can go straight back to the field and re-sync later.

---

## 6. Reading the preview

| Group | Meaning | Applied? |
|---|---|---|
| **Adds** | New in the copy (not in master) | Yes |
| **Updates** | Edited in the copy, untouched in master | Yes |
| **Deletes** | Removed in the copy (saved as a tombstone) | Yes |
| **Auto-merged** | Edited on **both** sides in **different fields** — combined | Yes |
| **Conflicts** | Same field (or geometry) edited on both — needs a decision | Only if resolved |
| **Splits / Merges** | 1→many or many→1 (geometry overlap) | Only if ticked |
| **Skipped / no-op** | Converged, or master-only changes | No |

**See it on the map.** Click any feature row and the canvas **zooms and
flashes** it — the **copy's version in amber** and the **master version in
grey** — so you can tell exactly which polygon a row refers to and what
changed. Clicking a **Split** flashes the parent (grey) + children (amber); a
**Merge** flashes the survivor (amber) + parents (grey).

---

## 7. The warning rows (setup guards)

| Warning | Meaning | Remedy |
|---|---|---|
| **NO RECORDED BASE** (red banner + row) | The copy was never stamped — deletes and lineage undetectable this sync | Apply only clear adds, then re-issue the copy |
| **N feature(s) the master never held** | The base contains features the master has never seen — the signature of a base recorded *after* field edits; they are being held back as "master deletes" every sync | Re-issue the copy, or bring them in with Import Mapping Data |
| **N feature(s) with no UUID** | Invisible to reconcile entirely | Run *Prepare field data*, rebuild the preview |
| **Issued from a different master** (blocking) | The copy's stamp names another master — applying would merge unrelated maps | Pick the right master |

---

## 8. Resolving conflicts

Each conflict shows the clashing field(s) and each side's value. Choose:

- **Field-merge** *(default when possible)* — keep both sides' independent
  edits; the copy wins a true same-field clash.
- **Take working** — the copy's version wins entirely (attributes **and**
  geometry).
- **Take master** — keep master as-is this sync.
- **Skip** — decide later.

> **By design:** because working copies are only ever written to by the base
> refresh, **Take master** and **Skip** write nothing *and the conflict
> re-appears next sync* — until the copy itself changes. To make "keep master"
> stick, re-issue the copy.

**Blanking guard:** an update whose *only* effect is emptying fields that hold
values in master is held back as a **"blanking" conflict** instead of silently
wiping data (protects, e.g., attributes carried onto split children).

---

## 9. What "Apply" does

- Commits each layer's ops in a single edit session (rolls that layer back on
  any error; a failed layer keeps its old base for a clean retry).
- Stamps `lgs_*` provenance (§10).
- **Advances the base** per-feature — first the sidecar, then the embedded
  `lgs_base` inside the working copy — so re-sync applies further edits.
  Skipped/unresolved conflicts keep their old base so they re-surface.
- Writes a **tombstone** per deleted feature (recoverable).
- Appends a **changelog** entry (JSON sidecar + a mirrored `lgs_changelog`
  table inside the gpkg), tagged with the copy's checkout id.
- **Two-people-at-once guard:** an advisory lock plus an optimistic
  master-version check. If the master moved since your preview, Apply aborts
  and asks you to rebuild; if a lock is held you can wait or override.

---

## 10. The `lgs_*` provenance columns

| Column | Meaning |
|---|---|
| `lgs_version` | bumped each accepted change (1 on insert) |
| `lgs_last_modified` | UTC timestamp |
| `lgs_author` / `lgs_editor` | Mapper ID of creator / last editor |
| `lgs_feature_hash` | content fingerprint (drives change detection) |
| `lgs_parent_uuid` | parent on a split |
| `lgs_merged_from` | comma-separated parents on a merge |

---

## 11. Where things live (audit & recovery)

Inside each **working copy** (hidden tables): `lgs_checkout` (identity),
`lgs_base` + `lgs_base_meta` (the ancestor). Inside the **master**:
`lgs_master` (identity), `lgs_changelog` (history mirror).

Beside the master, in `…/adddata_metadata/`:

- `<master>_checkouts.json` — every issued copy, mapper, status.
- `<master>_lgs_changelog.json` — append-only reconcile history.
- `<master>_tombstones.json` — every deleted feature's attributes + geometry.
- `<master>_<copy>_base.json` — legacy/recovery base sidecars.

---

## 12. Multi-geologist workflow

1. **Once:** migrate the master.
2. **Per mapper:** *Issue field copy* (full, blank or their clipped area) —
   or just Export for QField, which stamps automatically.
3. Everyone maps on their own copy; copies are independent (identity is the
   embedded checkout id, so same-named files are fine).
4. **Syncs happen one at a time**, in any order: the second mapper's preview
   simply sees the first mapper's merged work as master-side changes; genuine
   overlaps surface as conflicts or auto-merges.
5. **View checkouts…** shows who is still out.
6. After an office clean-up, **re-issue** copies so mappers continue from the
   cleaned state.

Reconcile is one-directional (field → master). A mapper never receives the
office's work or another mapper's work except by being handed a fresh copy.

---

## 13. The headline scenario: small polygons merged/cleaned on the master while the field copy still has the small ones

1. **First sync.** The copy has small polygons **P1…P5**; reconcile lands them
   in the master; the base advances to record them.
2. **Office clean-up.** In QGIS you merge P1…P5 into one polygon **BIG** and
   delete P1…P5.
3. **The mapper keeps going on their old copy** — still holding P1…P5, plus a
   new **P6** and an edit to **P2**.
4. **Second sync**, base {P1…P5} × working {P1…P5, P6, P2′} × master {BIG}:

| Feature | Copy vs base | Master vs base | Classified as | Result |
|---|---|---|---|---|
| P1, P3–P5 | unchanged | **deleted** | Skipped — master-only delete | Stay deleted. **Not re-added.** |
| P2 (edited) | **updated** | **deleted** | **Conflict — update/delete** | You decide |
| P6 (new) | **inserted** | absent | **Adds** | Flows into master ✅ |
| BIG | absent | **inserted** | Skipped — master-only insert | Kept ✅ |

Your cleanup is preserved, new work imports, and an edit to a merged-away
polygon is **surfaced, not lost**. This only works because the base recorded
P1…P5 — with **no base** the smalls would re-insert and undo the merge (the
preview now warns you loudly before that can happen).

The old smalls linger in the copy as harmless "Skipped" rows on every sync.
To clear the noise: **re-issue the copy** from the cleaned master — that is
exactly what *Issue field copy* is for.

---

## 14. Testing (developer note)

Pure logic (no QGIS): `python tests/reconcile/test_reconcile_core.py`,
`…store.py`, `…lineage.py`, `…basestore.py`.

QGIS-bound, from a terminal:
`C:\OSGeo4W\bin\python-qgis-ltr.bat tests\reconcile\run_headless_qgis.py
tests\reconcile\test_reconcile_qgis.py` (also `test_reconcile_issue_qgis.py`,
`test_qfield_export_stamp_qgis.py`, `test_hardcode_prepare_qgis.py`), or
`exec(open(r"…").read())` in the QGIS console.
