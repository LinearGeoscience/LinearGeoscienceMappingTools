# Reconcile / Merge — Quick Start

Plain-English steps for merging field mapping back into the master
GeoPackage. For the full story see `RECONCILE_GUIDE.md`.

**The one big rule: nothing changes until you click *Apply reconcile* and
answer Yes.** Build as many previews as you like.

---

## Words used here

| Word | Meaning |
|---|---|
| **Master** | The central GeoPackage — the truth. |
| **Working copy** | The file a mapper edits in QField (a hand-out of the master). |
| **Base** | A hidden record *inside the working copy* of what it looked like when it was handed out. This is how the tool knows who changed what. |
| **Checkout** | One issued working copy, tracked against the master. |

---

## Before your first ever reconcile (once per master)

1. **Back up the master** (copy the .gpkg somewhere safe).
2. Open **Reconcile / Merge** (left sidebar), pick the master, click
   **Verify / migrate master**. Wait for the green summary.
   The tool will refuse to build previews until this has run.

---

## Handing out copies

Use either of these — both stamp the copy so it merges back properly:

- **Export for QField** — just export as normal; mapping layers are
  registered automatically.
- **Reconcile / Merge → Issue field copy…** — pick full copy, blank
  template, or the mapper's clipped area; set their Mapper ID; Issue.

⚠ **Don't hand out plain Windows copies of the master.** They work in
QField, but the tool can't tell their deletes and splits apart from office
changes — you'll see a big red *NO RECORDED BASE* warning at sync time.

---

## Syncing a copy back in (every time)

1. Open **Reconcile / Merge**.
2. **Master GeoPackage** → the master. **Working template** → the mapper's
   file. Mapper ID fills itself in.
3. Click **Build preview**. Say **Prepare & continue** if asked.
4. Read the tree. Per layer you'll see:

| Group | Means | Will apply? |
|---|---|---|
| Adds | New features from the field | Yes |
| Updates | Edits to existing features | Yes |
| Deletes | Features removed in the field | Yes (recoverable) |
| Auto-merged | Both sides edited different fields — combined | Yes |
| Conflicts | Both sides edited the same thing | Your call |
| Splits / Merges | One polygon became many / many became one | If ticked |
| Skipped / no-op | Nothing to do (incl. office-side changes) | No |

5. **Click any row to flash it on the map** — amber = field version,
   grey = master version.
6. For each **conflict**, pick from the drop-down (the default is usually
   right). *Skip* just means "ask me again next sync".
7. **Red rows or banners mean a setup problem** — read them; they name the
   remedy (usually "re-issue the copy").
8. Click **Apply reconcile** → Yes. Done. The copy can go straight back to
   the field and sync again later.

---

## After the office cleans up the master

Merged away small polygons? Deleted junk? Your cleanup is safe — the old
features in mappers' copies are recognised and **not** re-imported. But do
**re-issue** each mapper a fresh copy (Issue field copy…) so they map
forward from the cleaned state and the preview noise disappears.

**View checkouts…** shows who has a copy out and who has merged back.

---

## Messages you might see

| Message | What it means | What to do |
|---|---|---|
| *Master has NOT been migrated* | One-off setup not done | Click Verify / migrate master |
| *NO RECORDED BASE* | The copy was never stamped | Apply only obvious adds, then re-issue the copy |
| *N feature(s) the master never held* | The copy's base was recorded after mapping started | Re-issue the copy; import the listed features with Import Mapping Data if they matter |
| *Issued from a different master* | Wrong master picked (or wrong copy) | Pick the matching pair |
| *Reconcile out of date — rebuild* | Someone changed the master meanwhile | Click Build preview again |
| *A reconcile is already in progress* | Someone else is mid-apply | Wait, or override if you're sure |

---

## Golden rules

- ✅ Migrate each master once, before anything else.
- ✅ Hand out copies through Export for QField or Issue field copy — never
  plain file-copies.
- ✅ Always sync through Reconcile, never through Import Mapping Data, once
  features are being edited.
- ✅ Re-issue copies after big office clean-ups.
- ✅ Back up the master before big syncs.

**Escape hatch:** nothing is written until Apply; deleted features are kept
as tombstones beside the master; and your pre-sync backup is always the
final word.
