/*
 * LGS Field Companion — QField project plugin (sidecar).
 *
 * Shipped by the LGS QField exporter as <projectname>.qml next to the
 * exported project file, so QField auto-activates it with the project.
 * Features are individually enabled at export time via the
 * LGS-EXPORT-FLAG lines below (rewritten by z_filter/qfield/write_sidecar);
 * LGS-EXPORT-DATA lines carry export-time data the same way:
 *
 * 1. Z FILTER — filters the four standard LGS mapping layers to one
 *    bench/level elevation by assigning layer.subsetString (a writable Qt
 *    property on QgsVectorLayer — same mechanism as the desktop panel).
 *    State shared with desktop through the lgs_z_* project variables.
 *    Mirrors z_filter/expression.py (clause shapes) and z_filter/levels.py
 *    (level clustering) — keep the implementations in sync.
 *    Extra layers (UG survey points, floor strings) ride along via the
 *    lgs_z_extra variable — authored by the desktop panel only, never
 *    edited on the device. Entries are resolved BY NAME (first match), so
 *    duplicate layer names pick the first; their original subsets persist
 *    under lgs_z_orig_x_<slug>, clear of the canonical lgs_z_orig_0..3.
 *    While active, ▼/▲ pills on the canvas sweep the level numerically by
 *    a step size (lgs_z_step, auto-suggested from the data, editable in
 *    the dialog), and the "Include adjacent levels" switch widens the
 *    subset to the bench below + current + above (device-only clause
 *    shape — the desktop never parses device subsets, they're ephemeral).
 *    The panel (non-modal, docked to the RIGHT edge so the map stays
 *    interactive beside it) has a level ladder listing detected levels
 *    highest-first with their level-name labels (desktop-detected text
 *    field, e.g. "Level", shipped per extra layer in lgs_z_extra); a tap
 *    filters to that level. The slice width is the user's own setting —
 *    rung taps never change it; it auto-fills once from the first scan.
 *
 * 2. SCALE DISPLAY + LOCK — live "1:2 500" pill overlaid on the map
 *    canvas; tap it to lock the map to a fixed scale (presets or custom).
 *    While locked, pinch-zooms snap back to the locked scale (pans stay
 *    free). Uses QgsQuickMapCanvasMap.zoomScale(center, scale) — a public
 *    slot — with a writable mapSettings.extent fallback.
 *
 * 3. LAYER OPACITY — "Opacity" pill opening a per-layer panel in two
 *    grouped columns (rasters left, vectors right; stacked on narrow
 *    screens): each layer gets a 100/50/25/Off row, plus an "All" row
 *    per column when it has several layers. The panel scrolls (a capped
 *    Flickable), so a long layer list stays reachable instead of
 *    growing the dialog past both screen edges. Above the columns sit
 *    FOLDER rows: one per exported layer-tree group with two or more
 *    exported members, setting every member at a tap; a folder carries
 *    its subgroups' layers and is named by its tree path. The layer
 *    names are baked in at export via the LGS-EXPORT-DATA:opacitylayers
 *    (rasters) and LGS-EXPORT-DATA:vectoropacitylayers (spatial vectors
 *    — lookup tables are excluded) lines, and the folders via
 *    LGS-EXPORT-DATA:opacitygroups; there is no reliable way to
 *    enumerate layers, or walk the layer tree, from QML on the device.
 *    Per-layer values persist as a JSON object in lgs_opacity; a legacy
 *    plain number applies to rasters only (it predates vector support).
 *    The '4 - Basemap' row carries a nested "Transported cover"
 *    100/50/25/Off sub-row (mirror of z_filter/expression.py cover_*
 *    helpers + cover_toggle.py — keep in sync). Off hides polygons
 *    whose TypeLith1 is 'Transported Cover' via a subset-string clause,
 *    taking their labels with them; 100/50/25 instead fade the cover
 *    symbols by writing lgs_cover_opacity, which the desktop bakes into
 *    the Basemap renderer as a data-defined symbol opacity
 *    (cover_opacity_expression) — QML has no renderer access of its
 *    own, so an export that predates that bake simply renders cover
 *    fully opaque until Off. Labels stay full-strength on a faded
 *    cover. The hide clause always sits in the baseline subset BENEATH any z clause —
 *    toggling while the z filter owns the layer rewrites the stored
 *    lgs_z_orig_3 baseline too, so z level changes and clears keep the
 *    cover state. State shared with desktop via lgs_cover_hidden; the
 *    field's existence is attempt-and-verified (no field enumeration
 *    from QML), and the sub-row hides on providers that reject it.
 *
 * 4. CLIPPING — "✂ Clip" pill offering the three desktop Map Cleaning
 *    Toolkit clip modes on the LGS polygon layers (ports of
 *    map_cleaning/clipping/clipper_core.py — keep the semantics in
 *    sync): Clip All (tap ONE cutter; every visible polygon it
 *    overlaps loses the overlap — clip_all_intersecting), Isolated
 *    (tap the polygon(s) to KEEP, then the polygon(s) to CUT; the
 *    KEEP footprint is subtracted from the CUT polygons —
 *    clip_isolated) and Smart (tap 2+ polygons; each smaller one is
 *    cut out of the larger ones it overlaps, skipping pairs within 1%
 *    area — clip_small_into_large).
 *    Geometry math runs through the QGIS expression engine via
 *    ExpressionEvaluator (difference/make_valid/union/area), because
 *    QgsGeometry methods are not invokable from QML; results round-trip
 *    as WKT. Bisected polygons become separate features with copied
 *    attributes and fresh UUIDs (fid/id/ogc_fid left to the provider —
 *    same rules as copy_attributes_without_fid). Edits are applied in
 *    one edit session (adds before deletes) with a one-level,
 *    session-only undo. Requires QField 4.x.
 *
 * 5. SPLINE — "~ Spline" pill arming a spline digitizing mode (port of
 *    the desktop Map Cleaning spline tools, map_cleaning/core/
 *    spline_interp.py — keep the Hermite math in sync). While armed,
 *    the companion mirrors the control points the user places and keeps
 *    QField's OWN digitizing rubberband rebuilt to the smoothed curve —
 *    live, including the segment bending toward the crosshair — so the
 *    native +/−/✓/✗ buttons, the feature form, and the reshape editor's
 *    apply all operate on the curve with no interception. The active
 *    model comes from coordinateLocator.rubberbandModel (switches
 *    automatically between digitizing and the geometry editors); the
 *    open/closed choice keys off model.vectorLayer, never geometryType
 *    (the reshape editor types its open cut line as Polygon). The model
 *    is mutated ONLY through its invokables (reset/addVertexFromPoint/
 *    removeVertex) — assigning currentCoordinate from JS would break
 *    the app's crosshair binding. On confirm (model freeze) the curve is
 *    rebuilt from the COMMITTED control points only — the crosshair is
 *    excluded, because QField's confirm tap jiggles the crosshair and
 *    would smear the final vertex. The confirm rebuild happens inside
 *    the ✓ tap, so it is kept fast: a segment cache (warmed while
 *    drawing) makes the full-density math incremental, and an idle-time
 *    full-density model write means ✓ usually only diffs the crosshair
 *    tail. Spline parameters are baked at export
 *    via LGS-EXPORT-DATA:splineparams (tolerance is in map units — LGS
 *    projects are projected mine grids, same assumption as desktop).
 *    Output density is scale-adaptive (v27): the curve is sampled and
 *    pruned to a deviation of roughly a quarter millimetre AT THE
 *    MAPPING SCALE, read off mapSettings.mapUnitsPerPoint and latched
 *    (quantized to octaves) while the user draws, so a boundary drawn
 *    zoomed out no longer saves the thousands of sub-millimetre
 *    vertices that made ✓ slow. Never coarser than the map can show and
 *    never finer than the baked tolerance, so zoomed-in fidelity is
 *    exactly what it always was. The control points themselves always
 *    survive, so they are the floor on the saved vertex count. The
 *    density is anchored to the finer of the mapping scale and the live
 *    zoom (v30), so a boundary drawn zoomed out is still saved dense
 *    enough for the map it belongs to; and the visible KINK at each
 *    node is bounded, so curves keep their nodes where they bend
 *    instead of faceting. Douglas-Peucker alone bounds a vertex's
 *    distance from the curve and says nothing about the corner left
 *    between chords, which is what the eye actually reads.
 *
 * 6. NATIVE CONFIRM FIXUP — always on (no export flag): QField's own
 *    line/polygon digitizing also harvests the floating crosshair vertex
 *    on ✓, with the same tap-jiggle smear. On model freeze (spline not
 *    armed) the floating vertex is dropped, so only +-placed vertices
 *    are saved. Skipped for GNSS-driven crosshairs (positionLocked /
 *    averagedPosition — QField strips the vertex itself after averaged
 *    adds) and below 2 committed vertices (3 for polygons), where the
 *    crosshair vertex is what keeps the geometry valid.
 *
 * 7. RESHAPE — "→ Reshape" pill: multi-polygon reshape (port of
 *    map_cleaning/tools/reshape_spline_tool.py — keep the semantics in
 *    sync). Draw the new edge FREEHAND with the stylus, which is the
 *    default, or tap out points one by one with the Tap pill. Freehand
 *    uses QField's own device gate (a DragHandler that never accepts
 *    TouchScreen), so a finger still pans while the pen draws, and it
 *    is live from the moment the tool opens — a stroke that starts in
 *    the pick step promotes itself to the draw step. While the pen is
 *    down the handler refuses to hand its grab on, so the canvas cannot
 *    turn the second half of a line into a pan; ApprovesCancellation is
 *    kept, or Qt could not cancel the grab and the stroke would never
 *    end. Capture is UNGATED and thinned once on release to the spline
 *    minimum node spacing, which picks the same control points the old
 *    live gate did (pinned by tests/reshape_freehand_harness.js), so
 *    the ink follows the pen without changing the saved curve. A stroke
 *    undoes as ONE action, and one that ends near a screen edge
 *    recentres the map, as QField's own freehand lift does, so a long
 *    edge can be drawn in strokes.
 *
 *    TARGETS: whatever QField has selected when the tool opens — the
 *    multi-select set, the focused feature, or a one-row identify list,
 *    which are three different things in QField's model and only the
 *    last two of which the "I tapped that polygon" case fills. That
 *    selection also picks the layer, and it is latched for a minute,
 *    because QField's identify clears its own model as the form hides.
 *    Otherwise: tap polygons to limit the reshape, or draw straight
 *    away and take every polygon the line crosses. While drawing, a
 *    finger tap or a long press adds or removes a target, and "Clear
 *    targets" releases them all.
 *    Candidates are found through the provider's spatial index over the
 *    line's bounding box (as the desktop tool does), falling back to a
 *    full scan when the CRS pair cannot be trusted — a partly-wrong box
 *    would mean a silent partial reshape. The iterator honours the
 *    layer subsetString either way: reshape what you see. The exact
 *    re-test on what the box returns is read through exprTrue: QGIS
 *    predicates answer with TVL ints, so intersects() comes back as '1',
 *    never 'true' (comparing against the word emptied every v33 scan).
 *
 *    Each target is reshaped by GeometryUtils.reshapeFromRubberband —
 *    the native op behind QField's own single-feature reshape editor —
 *    in one edit session, with a three-rung retry ladder. A polygon
 *    that the line would make invalid is skipped — roll back, exclude,
 *    run again — rather than committed to render as nothing (desktop
 *    parity); one that was already invalid is not made worse and is
 *    not refused. The layer is refused outright if another tool holds
 *    unsaved edits on it, so nobody's half-finished work is committed
 *    or discarded with ours.
 *    Confirming applies immediately: there is no dialog, because the
 *    tool is built to be used over and over and a session undo is the
 *    better safety net. After a reshape the line clears and you are
 *    still drawing, with layer, style, spline arming and targets
 *    intact.
 *
 *    UNDO is a session stack, offered from both steps and never
 *    persisted. Each round restores the pre-reshape geometries by
 *    delete-and-recreate with attributes copied verbatim (UUID
 *    included, so identity survives), one replacement per deleted fid,
 *    then reads back to check the polygon really came back where the
 *    current Z filter can see it.
 *
 *    The line draws on the plugin's OWN RubberbandModel/RubberbandShape
 *    (never QField's digitizing model, so this cannot fight the spline
 *    feature) and is spline-smoothed when the Spline pill is armed,
 *    straight otherwise. Writes diff against the last sequence and peel
 *    only the changed tail, verifying the vertex count afterwards,
 *    because addVertexFromPoint skips an add on two equal consecutive
 *    points and a hidden skip is how the line silently stops short of
 *    exiting the polygon. Only offered in BROWSE mode: the pill hides
 *    while a digitizing/measure session is active
 *    (mainWindow.currentRubberband is non-null then — the app state
 *    machine's own signal), so the native digitizing rubberband and
 *    crosshair never overlap the reshape drawing. The preview renders
 *    through QField's own native mechanism: a RubberbandShape wrapped
 *    in Shape/ShapePath exactly like the app's Rubberband.qml — a bare
 *    RubberbandShape draws nothing, and it must never be anchored or
 *    sized (its C++ transform positions the item to track the map).
 *    Requires QField 4.x.
 *
 * 8. REVERSE — "↔ Reverse" pill: flip the vertex order of a line
 *    feature so asymmetric line symbology (ticks, teeth, dip marks)
 *    renders on the other side. Tap the pill, then tap a line — it
 *    reverses immediately; tap the same line again to flip it back
 *    (reversal is its own undo, so no undo state is kept). Targets are
 *    hit-tested on the active layer first (when it is a line layer),
 *    then the standard LGS line layers; the iterator honours the layer
 *    subsetString — reverse what you see. The reversed geometry comes
 *    from the expression engine (reverse($geometry)) with a pure-JS
 *    WKT fallback for multi-part lines on engines whose reverse() is
 *    curve-only; both preserve Z. Applied as add-before-delete in one
 *    edit session (attributes copied verbatim, UUID preserved — same
 *    identity rules as the reshape undo). Browse mode only, same
 *    gating as Reshape. Requires QField 4.x.
 *
 * 9. COPY ATTRIBUTES — "» Copy" pill: stamp one feature's attributes
 *    onto others. Locked to the ACTIVE layer since v24 — both taps
 *    resolve against the layer selected in the legend (same lock as
 *    Reshape), and entering refuses with a toast when no LGS layer is
 *    active, so a stray tap can never pick up a feature from another
 *    layer. Tap the source, then tap targets — the source stays armed
 *    so several features can be stamped in a row; the first stamp of
 *    a session opens a field panel with a checkbox per field (untick
 *    = never copied this session, keyed by SOURCE field name;
 *    reopenable via the banner's Fields… button), later stamps apply
 *    instantly with the ticked set. Every non-skipped content field
 *    shared by source and target transfers by name (the cross-layer
 *    pair map copyFieldMapFor is dormant while the lock stands).
 *    Only NON-EMPTY source values are written — a copy never blanks
 *    target data — and identity/housekeeping fields never transfer
 *    (fid, UUID, Date&Time, Geologist, Photo*, Sample*, derived
 *    label/coordinate fields, Mapped*, lgs_*, data_added_*; Elevation
 *    stays with the target because its geometry is unchanged). The
 *    target is recreated with its own geometry and UUID in one edit
 *    session (add-before-delete — the sidecar's established write
 *    path), with a one-level undo restoring the last target's
 *    pre-copy attributes. Browse mode only, same gating as Reshape.
 *    Requires QField 4.x.
 *
 * 10. MERGE — "+ Merge" pill: dissolve two or more polygons on one
 *    layer into a single polygon (device-side counterpart of QGIS's
 *    "Merge Selected Features"). Tap polygons to pick/unpick (picks
 *    lock to the first pick's layer; the iterator honours the layer
 *    subsetString — merge what you see), then confirm: the union of
 *    the picks (expression-engine union + make_valid) becomes the new
 *    geometry. The FIRST pick is the keeper — its attributes and UUID
 *    survive on the merged polygon; its empty fields are filled with
 *    the first non-empty value from the other picks in pick order (a
 *    port of the reconcile carry_attrs semantics —
 *    script_adddata/reconcile/lineage.py, keep in sync). Disjoint
 *    picks are refused up front (the union must dissolve into ONE
 *    polygon — the LGS GeoPackage layers are single-polygon).
 *    lgs_merged_from is stamped with the consumed parents' UUIDs via
 *    attempt-and-verify (a no-op until the lineage columns ship to
 *    devices; desktop reconcile detects merges geometrically anyway).
 *    Applied add-before-delete in one edit session with a one-level
 *    undo that restores every parent from its pre-merge WKT (all
 *    original UUIDs preserved). Browse mode only, same gating as
 *    Reshape. Requires QField 4.x.
 *
 * 11. RECENTER HOLD — "📌 Hold" pill: locks out QField's automatic
 *    map recentring after a freehand stroke ends near a screen edge
 *    (qgismobileapp.qml freehandHandler — the mid-drawing jump that
 *    causes mis-placed linework). Works by writing a huge sentinel to
 *    the hidden /QField/Digitizing/FreehandRecenterScreenFraction
 *    settings key: QField reads it live on every stroke (stock
 *    default 5) and the recenter threshold is min(w, h) / fraction,
 *    so the sentinel drives it below one pixel — no QField patching.
 *    Unlocking restores the stock value. QSettings persists across
 *    restarts, so the hold stays locked until toggled off; the pill
 *    re-detects the sentinel at startup.
 *
 * 12. MODE TOGGLE — Browse/Digitise pill (v24): flips QField between
 *    browse and digitize without opening the side dashboard. Visible
 *    in BOTH modes (like Hold; hidden only while a sidecar tool is
 *    mid-flow), showing the current mode ('✏ Draw' inverted while
 *    digitizing, '🔍 Browse' otherwise). Rides QField's own
 *    stateMachine item for display and its toggleDigitizeMode signal
 *    for the flip — QField's handler refuses to leave digitize
 *    mid-feature with its own toast, a guard kept on purpose.
 */

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Shapes
import org.qfield
import org.qgis
import Theme

Item {
  id: plugin

  // Rewritten to true/false by the exporter — do not edit the markers.
  readonly property bool featureZFilter: true // LGS-EXPORT-FLAG:zfilter
  readonly property bool featureScale: true // LGS-EXPORT-FLAG:scale
  readonly property bool featureOpacity: true // LGS-EXPORT-FLAG:opacity
  readonly property bool featureClipping: true // LGS-EXPORT-FLAG:clipping
  readonly property bool featureSpline: true // LGS-EXPORT-FLAG:spline
  readonly property bool featureReshape: true // LGS-EXPORT-FLAG:reshape
  readonly property bool featureReverse: true // LGS-EXPORT-FLAG:reverse
  readonly property bool featureCopyAttrs: true // LGS-EXPORT-FLAG:copyattrs
  readonly property bool featureMerge: true // LGS-EXPORT-FLAG:merge
  readonly property bool featureRecenterHold: true // LGS-EXPORT-FLAG:recenterhold
  readonly property bool featureModeToggle: true // LGS-EXPORT-FLAG:modetoggle
  readonly property bool featureLayerSwitch: true // LGS-EXPORT-FLAG:layerswitch
  // Filled with the exported raster / spatial-vector layer names by the
  // exporter (the opacity panel's two columns).
  readonly property var opacityLayers: [] // LGS-EXPORT-DATA:opacitylayers
  readonly property var vectorOpacityLayers: [] // LGS-EXPORT-DATA:vectoropacitylayers
  // Exported layer-tree folders as [{name, layers}] — the opacity panel's
  // folder rows. Baked by the exporter because QML cannot walk the tree.
  readonly property var opacityGroups: [] // LGS-EXPORT-DATA:opacitygroups
  // [tightness, tolerance (map units), max segments] from desktop settings.
  readonly property var splineParams: [] // LGS-EXPORT-DATA:splineparams
  // Export timestamp + a short hash of this file, stamped by the exporter.
  // A sidecar only reaches the device through a fresh QField export, so
  // without this there is no way to tell which build a tablet is running —
  // and a field report of "still broken" cannot be told apart from "still
  // on the old build".
  readonly property var sidecarBuild: [] // LGS-EXPORT-DATA:build

  property var mainWindow: iface.mainWindow()

  // mirror of lgs_layers.CANONICAL_LAYERS — same names, same ORDER. allTargets
  // derives each layer's lgs_z_orig_<i> key from its index here, so reordering
  // this list re-points stored baselines. Linework and Overlay swapped ordinals
  // in Aug 2026 so lines draw above Overlay's washes.
  readonly property var layerNames: [
    '1 - FieldNotebook', '2 - Linework', '3 - Overlay', '4 - Basemap']
  // Pre-swap spelling for each renamed layer. A project GeoPackage created
  // before the swap keeps the old table names even when exported by a current
  // plugin, so every lookup falls back through here. QML cannot enumerate the
  // project's layers, hence an explicit alias rather than a name sweep.
  readonly property var legacyLayerNames: ({
    '2 - Linework': '3 - Linework',
    '3 - Overlay': '2 - Overlay'
  })
  readonly property string elevationField: 'Elevation'
  readonly property var tolPresets: [1, 2.5, 5, 10]
  // mirror of z_filter/expression.py::FLAT_SPAN — range features flatter
  // than this vote their midpoint in the scan
  readonly property real flatSpan: 2.0
  // mirror of z_filter/levels.py::LEVEL_SPAN_CAP / LABEL_SLACK — wider
  // spans are declines and abstain; a level name's RL may sit just
  // outside its own string envelope
  readonly property real levelSpanCap: 20.0
  readonly property real labelSlack: 2.0

  property var userLevels: []        // persisted (lgs_z_levels) — typed only
  property var suggestions: []       // cluster objects from the last scan
  property var scanInfo: ({})        // {min, max, withElev, blank}
  property real autoTol: 0
  property real stepSize: 5.0        // ▼/▲ sweep increment (lgs_z_step)
  property var transientLevel: undefined  // swept level — never persisted
  property bool scanned: false
  // Ladder populated from the desktop-baked lgs_z_suggest payload (the
  // device-side scan cannot always see the data).
  property bool suggestionsFromDesktop: false
  property string scanIssue: ''      // per-layer device scan failures
  property bool filterActive: false
  // Guard against accidental ▼/▲ taps in the field (lgs_z_step_locked).
  property bool zStepLocked: false

  // ----------------------------------------------------------------
  // Shared-state helpers (lgs_z_* project variables)
  // ----------------------------------------------------------------
  function projVar(name, fallback) {
    try {
      const vars = ExpressionContextUtils.projectVariables(qgisProject)
      const value = vars[name]
      if (value === undefined || value === null || String(value) === '')
        return fallback
      return String(value)
    } catch (error) {
      return fallback
    }
  }

  function saveVar(name, value) {
    try {
      ExpressionContextUtils.setProjectVariable(qgisProject, name, String(value))
    } catch (error) {}
    try {
      // Persist across app restarts (sidecar variable store).
      const info = iface.findItemByObjectName('projectInfo')
      if (info)
        info.saveVariable(name, String(value))
    } catch (error) {}
  }

  function buildLabel() {
    // sidecarBuild is [exportedISO, shortHash], stamped by write_sidecar.
    if (!sidecarBuild || sidecarBuild.length < 2)
      return ''
    return qsTr('Sidecar build %1 · exported %2')
        .arg(sidecarBuild[1]).arg(sidecarBuild[0])
  }

  function toast(message) {
    try {
      mainWindow.displayToast(message)
    } catch (error) {}
  }

  // ----------------------------------------------------------------
  // Expression building (mirror of z_filter/expression.py)
  // ----------------------------------------------------------------
  function fmt(value) {
    return String(Number(value))
  }

  // mirror of z_filter/expression.py::z_clause
  function zClauseField(field, level, tol, showNull) {
    const lo = Number(level) - Number(tol)
    const hi = Number(level) + Number(tol)
    const core = '"' + field + '" >= ' + fmt(lo) +
                 ' AND "' + field + '" <= ' + fmt(hi)
    if (showNull)
      return '("' + field + '" IS NULL OR (' + core + '))'
    return '(' + core + ')'
  }

  // mirror of z_filter/expression.py::z_range_clause — overlap semantics,
  // NULL guard on the max field only
  function zRangeClause(fieldMin, fieldMax, level, tol, showNull) {
    const lo = Number(level) - Number(tol)
    const hi = Number(level) + Number(tol)
    const core = '"' + fieldMax + '" >= ' + fmt(lo) +
                 ' AND "' + fieldMin + '" <= ' + fmt(hi)
    if (showNull)
      return '("' + fieldMax + '" IS NULL OR (' + core + '))'
    return '(' + core + ')'
  }

  // mirror of z_filter/expression.py::clause_for_spec
  function clauseForTarget(t, level, tol, showNull) {
    if (t.mode === 'range')
      return zRangeClause(t.fieldMin, t.fieldMax, level, tol, showNull)
    return zClauseField(t.field || elevationField, level, tol, showNull)
  }

  // Adjacent-levels variant: OR of one window per level, single outer
  // NULL guard. Device-only clause shape — the desktop never parses
  // device subsets (they are ephemeral), so no desktop mirror exists.
  // Delegates for a single level so that output stays byte-identical to
  // clauseForTarget.
  function clauseForTargetMulti(t, levels, tols, showNull) {
    if (levels.length === 1)
      return clauseForTarget(t, levels[0], tols[0], showNull)
    let parts = []
    for (let i = 0; i < levels.length; i++)
      parts.push(clauseForTarget(t, levels[i], tols[i], false))
    const joined = parts.join(' OR ')
    const nullField = t.mode === 'range'
        ? t.fieldMax : (t.field || elevationField)
    if (showNull)
      return '("' + nullField + '" IS NULL OR (' + joined + '))'
    return '(' + joined + ')'
  }

  function combineSubset(orig, clause) {
    if (orig && String(orig).trim() !== '')
      return '(' + orig + ') AND ' + clause
    return clause
  }

  // ----------------------------------------------------------------
  // Level clustering (mirror of z_filter/levels.py — keep in sync)
  // ----------------------------------------------------------------
  readonly property real gapFloor: 2.0
  readonly property real gapFactor: 0.5
  // relative — gaps within this of a threshold count as equal (merge),
  // so float noise never decides a split
  readonly property real gapEps: 1e-6
  readonly property real minTol: 1.0
  readonly property real tolMargin: 0.5
  readonly property real maxTol: 15.0
  readonly property int maxSuggestions: 12
  readonly property real defaultStep: 5.0
  readonly property real stepFloor: 0.5
  readonly property real labelEps: 1e-9

  // mirror of z_filter/levels.py::label_elevation — the RL inside a level
  // name, and only when the name holds exactly one number ('13/42' is a
  // name, not an RL)
  function labelElevation(text) {
    if (text === undefined || text === null)
      return undefined
    const matches = String(text).match(/-?\d+(?:\.\d+)?/g)
    if (matches === null || matches.length !== 1)
      return undefined
    const value = Number(matches[0])
    return isNaN(value) ? undefined : value
  }

  // mirror of z_filter/levels.py::range_vote — the one elevation a feature
  // votes for, or undefined when it abstains
  function rangeVote(zMin, zMax, label) {
    let lo = Number(zMin)
    let hi = Number(zMax)
    if (isNaN(lo) || isNaN(hi))
      return undefined
    if (lo > hi) {
      const swap = lo
      lo = hi
      hi = swap
    }
    if (hi - lo <= flatSpan)
      return (lo + hi) / 2
    const rl = labelElevation(label)
    if (rl !== undefined && lo - labelSlack <= rl && rl <= hi + labelSlack)
      return rl
    if (hi - lo <= levelSpanCap)
      return (lo + hi) / 2
    return undefined
  }

  function medianOf(values) {
    if (values.length === 0)
      return 0
    let ordered = values.slice().sort(function (a, b) { return a - b })
    const mid = Math.floor(ordered.length / 2)
    if (ordered.length % 2)
      return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
  }

  function niceStep(raw) {
    if (raw <= 0)
      return 1
    let magnitude = 1
    while (magnitude * 10 <= raw)
      magnitude *= 10
    while (magnitude > raw)
      magnitude /= 10
    const factors = [1, 2, 5, 10]
    for (const factor of factors) {
      if (magnitude * factor >= raw)
        return magnitude * factor
    }
    return magnitude * 10
  }

  function binContinuous(pairs) {
    const lo = pairs[0][0]
    const hi = pairs[pairs.length - 1][0]
    const step = niceStep((hi - lo) / maxSuggestions)
    let bins = {}
    for (const pair of pairs) {
      const level = Math.round(pair[0] / step) * step
      if (!(level in bins))
        bins[level] = { count: 0, lo: pair[0], hi: pair[0] }
      bins[level].count += pair[1]
      bins[level].lo = Math.min(bins[level].lo, pair[0])
      bins[level].hi = Math.max(bins[level].hi, pair[0])
    }
    const tol = Math.max(minTol, step / 2)
    return Object.keys(bins).map(Number)
        .sort(function (a, b) { return a - b })
        .map(function (level) {
          return { level: level, count: bins[level].count,
                   lo: bins[level].lo, hi: bins[level].hi,
                   suggested_tol: tol }
        })
  }

  function summarizeCluster(pairs) {
    const lo = pairs[0][0]
    const hi = pairs[pairs.length - 1][0]
    let total = 0, weighted = 0
    let modeValue = pairs[0][0], modeCount = pairs[0][1]
    for (const pair of pairs) {
      total += pair[1]
      weighted += pair[0] * pair[1]
      if (pair[1] > modeCount) {
        modeValue = pair[0]
        modeCount = pair[1]
      }
    }
    const level = (modeCount * 2 >= total)
        ? modeValue : Math.round(weighted / total * 10) / 10
    // The tolerance must reach the far edge of the cluster from the level
    // (which may sit off-centre, e.g. a modal value at one end); clusters
    // too wide for that are treated as continuous data instead.
    const needed = Math.max(level - lo, hi - level)
    if (needed + tolMargin > maxTol)
      return binContinuous(pairs)
    const tol = Math.max(minTol, needed + tolMargin)
    return [{ level: level, count: total, lo: lo, hi: hi, suggested_tol: tol }]
  }

  function clusterLevels(valueCounts) {
    let pairs = []
    for (const key in valueCounts) {
      const value = Number(key)
      const count = valueCounts[key]
      if (!isNaN(value) && isFinite(value) && count > 0)
        pairs.push([value, count])
    }
    pairs.sort(function (a, b) { return a[0] - b[0] })
    if (pairs.length === 0)
      return []

    let gaps = []
    for (let i = 1; i < pairs.length; i++)
      gaps.push(pairs[i][0] - pairs[i - 1][0])

    // Discrete fast path: few distinct values, all separated by more than
    // minTol — each distinct value IS a level (typed/snapped RLs), so a
    // minTol window on each is both selective (never reaches a neighbour)
    // and covering (lo == hi == level).
    if (pairs.length <= maxSuggestions && (
        gaps.length === 0
        || Math.min.apply(null, gaps) > minTol * (1 + gapEps))) {
      return pairs.map(function (pair) {
        return { level: pair[0], count: pair[1], lo: pair[0], hi: pair[0],
                 suggested_tol: minTol }
      })
    }

    const threshold = gaps.length
        ? Math.max(gapFloor, gapFactor * medianOf(gaps)) : gapFloor

    let clusters = []
    let current = [pairs[0]]
    for (let i = 1; i < pairs.length; i++) {
      if (pairs[i][0] - pairs[i - 1][0] > threshold * (1 + gapEps)) {
        clusters.push(current)
        current = []
      }
      current.push(pairs[i])
    }
    clusters.push(current)

    let result = []
    for (const cluster of clusters)
      result = result.concat(summarizeCluster(cluster))
    result.sort(function (a, b) { return a.level - b.level })

    // A window may extend at most to the midpoint between adjacent cluster
    // edges, but is never clamped below what covers its own lo..hi: a window
    // that cuts out its own members leaves them unreachable from any chip,
    // which is worse than a little overlap toward a neighbour.
    for (let i = 0; i < result.length; i++) {
      const needed = Math.max(result[i].level - result[i].lo,
                              result[i].hi - result[i].level)
      let allowed = [result[i].suggested_tol]
      if (i > 0)
        allowed.push(result[i].level
                     - (result[i - 1].hi + result[i].lo) / 2)
      if (i < result.length - 1)
        allowed.push((result[i].hi + result[i + 1].lo) / 2
                     - result[i].level)
      result[i].suggested_tol = Math.max(
          minTol, needed, Math.min.apply(null, allowed))
    }
    return result
  }

  function suggestTolerance(clusters) {
    if (clusters.length === 0)
      return 5
    return Math.round(medianOf(clusters.map(function (c) {
      return c.suggested_tol
    })) * 10) / 10
  }

  function topSuggestions(clusters, n) {
    let ranked = clusters.slice().sort(function (a, b) {
      return (b.count - a.count) || (a.level - b.level)
    }).slice(0, n)
    return ranked.sort(function (a, b) { return a.level - b.level })
  }

  // mirror of z_filter/levels.py::_nice_step_nearest
  function niceStepNearest(raw) {
    if (raw <= 0)
      return 1
    let magnitude = 1
    while (magnitude * 10 <= raw)
      magnitude *= 10
    while (magnitude > raw)
      magnitude /= 10
    let best = magnitude
    const factors = [1, 2, 5, 10]
    for (const factor of factors) {
      const candidate = magnitude * factor
      if (Math.abs(candidate - raw) < Math.abs(best - raw))
        best = candidate
    }
    return best
  }

  // mirror of z_filter/levels.py::suggest_step
  function suggestStep(clusters) {
    const levels = clusters.map(function (c) { return c.level })
        .sort(function (a, b) { return a - b })
    if (levels.length < 2)
      return defaultStep
    let gaps = []
    for (let i = 1; i < levels.length; i++)
      gaps.push(levels[i] - levels[i - 1])
    return Math.max(stepFloor, niceStepNearest(medianOf(gaps)))
  }

  // mirror of z_filter/levels.py::attach_labels — decorate suggestions
  // with the modal level-name text; 'label' stays undefined when none.
  function attachLabels(suggestions, valueLabels) {
    for (const s of suggestions) {
      let tally = {}
      for (const key in valueLabels) {
        const value = Number(key)
        if (isNaN(value) || value < s.lo - labelEps ||
            value > s.hi + labelEps)
          continue
        for (const label in valueLabels[key]) {
          const text = String(label).trim()
          if (text === '')
            continue
          tally[text] = (tally[text] || 0) + valueLabels[key][label]
        }
      }
      let best
      for (const label in tally) {
        if (best === undefined || tally[label] > tally[best] ||
            (tally[label] === tally[best] && label < best))
          best = label
      }
      if (best !== undefined)
        s.label = best
    }
    return suggestions
  }

  // mirror of z_filter/expression.py::parse_suggestions — parse the
  // desktop-baked lgs_z_suggest payload; null when unusable. Keep this a
  // plain self-contained function: the node parity harness extracts it
  // verbatim (no plugin properties, no braces inside string literals).
  function parseBakedSuggestions(text) {
    let data
    try {
      data = JSON.parse(text)
    } catch (error) {
      return null
    }
    if (data === null || typeof data !== 'object' || data.v !== 1)
      return null
    if (!Array.isArray(data.levels))
      return null
    const fnum = function (v) {
      if (v === undefined || v === null)
        return NaN
      if (typeof v === 'string' && v.trim() === '')
        return NaN
      return Number(v)
    }
    let suggestions = []
    for (const raw of data.levels) {
      if (raw === null || typeof raw !== 'object')
        continue
      const level = fnum(raw.level)
      const count = fnum(raw.count)
      const lo = fnum(raw.lo)
      const hi = fnum(raw.hi)
      const tol = fnum(raw.tol)
      if (isNaN(level) || isNaN(count) || isNaN(lo) || isNaN(hi) ||
          isNaN(tol))
        continue
      let entry = { level: level, count: Math.trunc(count), lo: lo,
                    hi: hi, suggested_tol: tol }
      if (raw.label)
        entry.label = String(raw.label)
      suggestions.push(entry)
    }
    if (suggestions.length === 0)
      return null
    const optional = function (v) {
      const n = fnum(v)
      return isNaN(n) ? undefined : n
    }
    const counter = function (v) {
      const n = fnum(v)
      return isNaN(n) ? 0 : Math.trunc(n)
    }
    return {
      suggestions: suggestions,
      info: { min: optional(data.min), max: optional(data.max),
              withElev: counter(data.withElev), blank: counter(data.blank),
              spanning: counter(data.spanning) }
    }
  }

  // ----------------------------------------------------------------
  // Layers
  // ----------------------------------------------------------------
  function layerByName(name) {
    try {
      const matches = qgisProject.mapLayersByName(name)
      if (matches && matches.length > 0)
        return matches[0]
    } catch (error) {}
    // Fall back to the pre-swap ordinal so pre-Aug-2026 project GeoPackages
    // still resolve (see legacyLayerNames).
    const legacy = legacyLayerNames[name]
    if (legacy !== undefined) {
      try {
        const old = qgisProject.mapLayersByName(legacy)
        if (old && old.length > 0)
          return old[0]
      } catch (error) {}
    }
    return null
  }

  // "3 - Overlay" / "2 - Overlay" -> "Overlay". Mirror of lgs_layers.base_name,
  // used to key cross-layer maps by identity rather than by ordinal.
  function baseName(name) {
    const match = /^\s*[A-Za-z]?\d+\s*[-_ ]\s*(.+?)\s*$/.exec(String(name || ''))
    return match !== null ? match[1] : String(name || '').trim()
  }

  function slugName(name) {
    return String(name).toLowerCase().replace(/[^a-z0-9]+/g, '_')
  }

  // Extra layers authored by the desktop panel (lgs_z_extra JSON).
  // mirror of z_filter/expression.py::parse_extra_layers
  function extraTargets(includeUnchecked) {
    try {
      const data = JSON.parse(projVar('lgs_z_extra', ''))
      if (!data || !Array.isArray(data.layers))
        return []
      return data.layers.filter(function (e) {
        if (!e || !e.name)
          return false
        if (!includeUnchecked && e.checked === false)
          return false
        // source 'geom' means the desktop has not materialized the Z
        // fields yet (project exported before the first Apply) — there is
        // nothing to filter on; the spec flips to 'attr' after Apply.
        if (!includeUnchecked && e.source === 'geom')
          return false
        if (e.mode === 'range')
          return !!(e.field_min && e.field_max)
        return e.mode === 'single' && !!e.field
      })
    } catch (error) {
      return []
    }
  }

  // Canonical four + extras, each with the project-variable key that
  // stores its pre-filter subset. Extra keys derive from the desktop
  // layer id when present — names can slug-collide ("Level 100" vs
  // "Level-100"), ids cannot. Pass includeUnchecked to also get entries
  // the desktop unchecked (apply/clear must restore those).
  function allTargets(includeUnchecked) {
    let targets = []
    for (let i = 0; i < layerNames.length; i++) {
      targets.push({ name: layerNames[i], mode: 'single', checked: true,
                     field: elevationField, key: 'lgs_z_orig_' + i })
    }
    for (const e of extraTargets(includeUnchecked)) {
      let t = { name: e.name, mode: e.mode, checked: e.checked !== false,
                key: 'lgs_z_orig_x_' + slugName(e.id || e.name) }
      if (e.mode === 'range') {
        t.fieldMin = e.field_min
        t.fieldMax = e.field_max
      } else {
        t.field = e.field
      }
      // Level-name text field, detected + persisted by the desktop panel
      // (QML cannot enumerate a layer's fields itself).
      if (e.label_field)
        t.labelField = e.label_field
      targets.push(t)
    }
    return targets
  }

  // ----------------------------------------------------------------
  // Level list (merged user + suggestions)
  // ----------------------------------------------------------------
  function mergedLevels() {
    let seen = {}
    for (const value of userLevels)
      seen[value] = true
    for (const cluster of suggestions)
      seen[cluster.level] = true
    return Object.keys(seen).map(Number).sort(function (a, b) { return a - b })
  }

  // Ladder rows: capped suggestions, HIGHEST level first (mining
  // convention — matches the desktop ladder widget).
  function ladderModel(clusters) {
    return topSuggestions(clusters || suggestions, maxSuggestions)
        .sort(function (a, b) { return b.level - a.level })
  }

  function rebuildLevelModel(current) {
    const levels = mergedLevels()
    levelCombo.model = levels.map(fmt)
    if (current !== undefined) {
      const index = levels.indexOf(Number(current))
      if (index !== -1)
        levelCombo.currentIndex = index
      // ALWAYS write editText (after currentIndex — assigning the index
      // rewrites it): once the user has typed in the editable combo,
      // editText stops tracking currentIndex, and currentLevel() reads
      // editText — without this, stepping appears dead after any typing.
      levelCombo.editText = fmt(current)
    }
  }

  function loadLevels() {
    let values = {}
    for (const part of projVar('lgs_z_levels', '').split(',')) {
      const number = Number(part)
      if (part.trim() !== '' && !isNaN(number))
        values[number] = true
    }
    userLevels = Object.keys(values).map(Number)
        .sort(function (a, b) { return a - b })
    rebuildLevelModel(undefined)
  }

  function addLevel(value) {
    // Persist only genuinely user-typed levels; suggestions are recomputed
    // from data on every scan.
    if (mergedLevels().indexOf(value) === -1) {
      let list = userLevels.slice()
      list.push(value)
      list.sort(function (a, b) { return a - b })
      userLevels = list
      saveVar('lgs_z_levels', userLevels.map(fmt).join(','))
    }
    rebuildLevelModel(value)
  }

  function currentLevel() {
    const text = levelCombo.editable
        ? levelCombo.editText : levelCombo.currentText
    const value = Number(text)
    if (text === undefined || String(text).trim() === '' || isNaN(value))
      return undefined
    return value
  }

  // Numeric sweep: move the level down/up by stepSize (desktop parity —
  // dockwidget._step_level). Applying also turns the filter ON when off.
  function toggleZStepLock() {
    zStepLocked = !zStepLocked
    saveVar('lgs_z_step_locked', zStepLocked ? '1' : '0')
    toast(zStepLocked ? qsTr('Level locked') : qsTr('Level unlocked'))
  }

  function stepLevel(direction) {
    if (zStepLocked) {
      toast(qsTr('Level locked'))
      return
    }
    const level = currentLevel()
    let target
    if (level === undefined) {
      // Enter the data from the end the user is heading away from:
      // ▼ starts the sweep at the top, ▲ at the bottom.
      if (suggestions.length === 0) {
        toast(qsTr('Scan data or type a level first'))
        return
      }
      const values = suggestions.map(function (c) { return c.level })
      target = direction < 0 ? Math.max.apply(null, values)
                             : Math.min.apply(null, values)
    } else {
      target = level + direction * stepSize
      if (scanInfo.min !== undefined) {
        const lo = scanInfo.min - stepSize
        const hi = scanInfo.max + stepSize
        const clamped = Math.min(Math.max(target, lo), hi)
        if (clamped !== target) {
          // Pill/button taps must never feel dead at the data's ends.
          toast(direction > 0 ? qsTr('Top of data') : qsTr('Bottom of data'))
        }
        target = clamped
      }
    }
    rebuildLevelModel(target)
    transientLevel = target
    applyFilter()
  }

  // Nearest known level strictly below / above, for the adjacent-levels
  // switch: [below?, level, above?] (ends omitted at the list edges).
  function neighbourLevels(level) {
    let below, above
    for (const value of mergedLevels()) {
      if (value < level && (below === undefined || value > below))
        below = value
      if (value > level && (above === undefined || value < above))
        above = value
    }
    let out = []
    if (below !== undefined)
      out.push(below)
    out.push(level)
    if (above !== undefined)
      out.push(above)
    return out
  }

  // Tolerance for a neighbour window: the cluster-fitted value when the
  // scan knows this level, else the user's tolerance — then clamped to
  // half the gap to the nearest other known level so adjacent windows
  // rarely overlap, but (as in clusterLevels) never below what covers the
  // matched cluster's own lo..hi: coverage wins over non-overlap.
  function tolForLevel(level, fallbackTol) {
    let tol = Number(fallbackTol)
    let needed = 0
    for (const cluster of suggestions) {
      if (cluster.level === level) {
        tol = cluster.suggested_tol
        needed = Math.max(cluster.level - cluster.lo,
                          cluster.hi - cluster.level)
        break
      }
    }
    let halfGaps = []
    for (const value of mergedLevels()) {
      if (value !== level)
        halfGaps.push(Math.abs(value - level) / 2)
    }
    if (halfGaps.length)
      tol = Math.min(tol, Math.min.apply(null, halfGaps))
    return Math.max(minTol, needed, tol)
  }

  // ----------------------------------------------------------------
  // Data scan
  // ----------------------------------------------------------------
  // Shared tail of the device-scan and desktop-baked adoption paths.
  function adoptSuggestions(sugs, info, fromDesktop) {
    suggestions = sugs
    autoTol = suggestions.length ? suggestTolerance(suggestions) : 0
    // Auto-set the sweep step from the data, once — a step the user (or
    // the desktop panel) already chose is never clobbered.
    if (projVar('lgs_z_step', '') === '' && suggestions.length) {
      stepSize = suggestStep(suggestions)
      saveVar('lgs_z_step', fmt(stepSize))
    }
    // Same once-only rule for the slice width: a sensible default from
    // the data, then it's the user's until they change it themselves.
    if (projVar('lgs_z_tolerance', '') === '' && autoTol > 0) {
      toleranceField.text = fmt(autoTol)
      saveVar('lgs_z_tolerance', fmt(autoTol))
    }
    scanInfo = info
    scanned = true
    suggestionsFromDesktop = fromDesktop
    rebuildLevelModel(currentLevel())
  }

  function loadBakedSuggestions() {
    const baked = parseBakedSuggestions(projVar('lgs_z_suggest', ''))
    if (baked === null)
      return false
    adoptSuggestions(baked.suggestions, baked.info, true)
    return true
  }

  function scanData() {
    let counts = {}
    let labels = {}
    let withElev = 0
    let blank = 0
    let spanning = 0
    let failed = []
    for (const t of allTargets()) {
      const layer = layerByName(t.name)
      if (layer === null)
        continue
      const fields = t.mode === 'range'
          ? [t.fieldMin, t.fieldMax] : [t.field || elevationField]
      let previous
      let rowsSeen = 0
      try {
        previous = layer.subsetString
        layer.subsetString = ''      // scan ALL rows, not the filtered view
        const consume = function (iterator) {
          try {
            while (iterator.hasNext()) {
              rowsSeen++
              const feature = iterator.next()
              let values = []
              for (const field of fields) {
                const raw = feature.attribute(field)
                const number = Number(raw)
                if (raw === undefined || raw === null ||
                    String(raw) === '' || isNaN(number)) {
                  values = null
                  break
                }
                values.push(number)
              }
              if (values === null) {
                blank++
                continue
              }
              // The level name is read before the vote: it is an input to
              // it, not just decoration (mirror of scan_elevations).
              let text = ''
              if (t.labelField) {
                const rawLabel = feature.attribute(t.labelField)
                text = (rawLabel === undefined || rawLabel === null)
                    ? '' : String(rawLabel).trim()
                if (text.toUpperCase() === 'NULL')
                  text = ''
                text = text.slice(0, 40)
              }
              const value = rangeVote(values[0], values[values.length - 1],
                                      text === '' ? undefined : text)
              if (value === undefined) {
                spanning++   // decline — abstains
                continue
              }
              counts[value] = (counts[value] || 0) + 1
              withElev++
              if (text !== '') {
                if (!(value in labels))
                  labels[value] = {}
                labels[value][text] = (labels[value][text] || 0) + 1
              }
            }
          } finally {
            try { iterator.close() } catch (closeError) {}
          }
        }
        try {
          consume(LayerUtils.createFeatureIterator(layer))
        } catch (error) {
          // Some QField builds may lack/deny the plain iterator — retry
          // via the expression variant. Only when nothing was tallied,
          // so a mid-iteration failure can never double count.
          if (rowsSeen === 0)
            consume(LayerUtils.createFeatureIteratorFromExpression(
                layer, 'TRUE'))
          else
            throw error
        }
      } catch (error) {
        failed.push(t.name + ': ' + error)
      } finally {
        try {
          if (previous !== undefined)
            layer.subsetString = previous
        } catch (error) {}
      }
    }
    // Surface failures instead of swallowing them — this text is the
    // on-device diagnosis for scan problems.
    scanIssue = failed.length
        ? qsTr('Z scan failed on: %1').arg(failed.join('; ')) : ''
    for (const f of failed)
      console.log('LGS z scan: ' + f)
    if (failed.length)
      toast(qsTr('Z scan: %1 layer(s) failed').arg(failed.length))
    // A device scan that saw nothing must never wipe a desktop-baked
    // ladder — that is the exact failure this bake defends against.
    if (Object.keys(counts).length === 0) {
      const baked = parseBakedSuggestions(projVar('lgs_z_suggest', ''))
      if (baked !== null) {
        adoptSuggestions(baked.suggestions, baked.info, true)
        toast(qsTr('Device scan found nothing — showing desktop scan'))
        return
      }
    }
    let info = { withElev: withElev, blank: blank, spanning: spanning }
    const values = Object.keys(counts).map(Number)
    if (values.length) {
      info.min = Math.min.apply(null, values)
      info.max = Math.max.apply(null, values)
    }
    adoptSuggestions(attachLabels(clusterLevels(counts), labels), info,
                     false)
  }

  function summaryText() {
    if (!scanned)
      return qsTr('Not scanned yet.')
    if (scanInfo.min === undefined) {
      // Say why nothing clustered — "no data" and "every feature abstained"
      // look identical otherwise.
      let empty = scanInfo.blank
          ? qsTr('No elevation values yet (%1 blank features)').arg(scanInfo.blank)
          : qsTr('No features found')
      if (scanInfo.spanning)
        empty += '  ·  ' + qsTr('%1 spanning levels').arg(scanInfo.spanning)
      return empty
    }
    let text = (scanInfo.min === scanInfo.max
        ? fmt(scanInfo.min) : fmt(scanInfo.min) + '–' + fmt(scanInfo.max)) + ' m'
    text += '  ·  ' + qsTr('%1 with elevation').arg(scanInfo.withElev)
    if (scanInfo.blank)
      text += '  ·  ' + qsTr('%1 blank').arg(scanInfo.blank)
    if (scanInfo.spanning)
      text += '  ·  ' + qsTr('%1 spanning levels').arg(scanInfo.spanning)
    if (suggestionsFromDesktop)
      text += '  ·  ' + qsTr('desktop scan')
    return text
  }

  // ----------------------------------------------------------------
  // Apply / clear
  // ----------------------------------------------------------------
  function applyFilter() {
    const level = currentLevel()
    if (level === undefined) {
      toast(qsTr('Set a level first'))
      return
    }
    const tol = Number(toleranceField.text)
    const tolerance = isNaN(tol) ? 5 : tol
    // Adjacent switch widens to [below?, level, above?]. The selected
    // level always keeps the user's typed tolerance; only neighbour
    // windows get fitted/clamped ones.
    const levels = adjacentSwitch.checked ? neighbourLevels(level) : [level]
    const tols = levels.map(function (value) {
      return value === level ? tolerance : tolForLevel(value, tolerance)
    })
    let applied = 0

    for (const t of allTargets(true)) {
      const layer = layerByName(t.name)
      if (layer === null)
        continue
      const savedKey = t.key.replace('orig', 'orig_saved')
      if (!t.checked) {
        // Deselected on desktop since we last filtered it — restore.
        restoreTarget(layer, t.key, savedKey)
        continue
      }
      try {
        // First application: remember the pre-filter subset.
        if (projVar(savedKey, '0') !== '1') {
          saveVar(t.key, layer.subsetString || '')
          saveVar(savedKey, '1')
        }
        const original = projVar(t.key, '')
        const combined = combineSubset(
            original,
            clauseForTargetMulti(t, levels, tols, showNullSwitch.checked))
        layer.subsetString = combined
        if (layer.subsetString === combined) {
          layer.triggerRepaint()
          applied++
        } else {
          // Provider rejected the clause (e.g. the fields don't exist on
          // this copy) — put the original back rather than half-filter.
          layer.subsetString = original
          saveVar(savedKey, '0')
        }
      } catch (error) {}
    }

    if (applied === 0) {
      toast(qsTr('Z Filter: no LGS layers found'))
      return
    }

    filterActive = true
    // Swept levels are transient — persisting every ▼/▲ increment would
    // fill lgs_z_levels with noise (desktop parity: dockwidget._apply).
    if (transientLevel !== undefined && level === transientLevel)
      transientLevel = undefined
    else
      addLevel(level)
    saveVar('lgs_z_enabled', '1')
    saveVar('lgs_z_level', fmt(level))
    saveVar('lgs_z_tolerance', fmt(tolerance))
    saveVar('lgs_z_shownull', showNullSwitch.checked ? '1' : '0')
    saveVar('lgs_z_adjacent', adjacentSwitch.checked ? '1' : '0')
    applyRasterZ(levels, tols)
    try {
      iface.mapCanvas().refresh()
    } catch (error) {}
    if (levels.length > 1)
      toast(qsTr('Levels %1 (%2 layers)')
            .arg(levels.map(fmt).join(' · ')).arg(applied))
    else
      toast(qsTr('Level %1 ± %2 m (%3 layers)')
            .arg(fmt(level)).arg(fmt(tolerance)).arg(applied))
  }

  // Restore a layer's pre-filter subset if one was saved. Returns 1 when
  // a restore happened (mirror of controller._restore_layer).
  function restoreTarget(layer, key, savedKey) {
    try {
      if (projVar(savedKey, '0') === '1') {
        layer.subsetString = projVar(key, '')
        layer.triggerRepaint()
        saveVar(savedKey, '0')
        return 1
      }
    } catch (error) {}
    return 0
  }

  function clearFilter() {
    let restored = 0
    // Include desktop-unchecked entries: they may still hold a saved
    // original from an earlier apply on this device.
    for (const t of allTargets(true)) {
      const layer = layerByName(t.name)
      if (layer === null)
        continue
      restored += restoreTarget(layer, t.key,
                                t.key.replace('orig', 'orig_saved'))
    }
    filterActive = false
    saveVar('lgs_z_enabled', '0')
    restoreRasterZ()
    try {
      iface.mapCanvas().refresh()
    } catch (error) {}
    if (restored > 0)
      toast(qsTr('Z filter off'))
  }

  function restoreFromProject() {
    loadLevels()
    // Desktop-baked levels first: the ladder must render even when the
    // device-side scan cannot see the data.
    loadBakedSuggestions()
    toleranceField.text = projVar('lgs_z_tolerance', '5')
    const step = Number(projVar('lgs_z_step', ''))
    if (projVar('lgs_z_step', '') !== '' && !isNaN(step) && step > 0)
      stepSize = step
    showNullSwitch.checked = projVar('lgs_z_shownull', '1') === '1'
    adjacentSwitch.checked = projVar('lgs_z_adjacent', '0') === '1'
    zStepLocked = projVar('lgs_z_step_locked', '0') === '1'
    const level = Number(projVar('lgs_z_level', ''))
    if (!isNaN(level) && projVar('lgs_z_level', '') !== '') {
      rebuildLevelModel(level)
      // Runtime subsets are ephemeral in QField — re-apply the persisted
      // filter when the project (re)opens.
      if (projVar('lgs_z_enabled', '0') === '1')
        applyFilter()
    }
  }

  Component.onCompleted: {
    if (featureZFilter)
      iface.addItemToPluginsToolbar(pluginButton)
    // Always wire up the map settings: the 1:20 zoom-in safety clamp must
    // run even when the scale display feature is disabled at export.
    initScaleSettings()
    if (featureScale || featureZFilter || featureOpacity || featureClipping ||
        featureSpline || featureReshape || featureReverse ||
        featureRecenterHold || featureModeToggle || featureLayerSwitch)
      attachOverlay()
    startupTimer.start()
  }

  Timer {
    id: startupTimer
    interval: 1500
    repeat: false
    onTriggered: {
      if (plugin.featureZFilter)
        plugin.restoreFromProject()
      if (plugin.featureScale)
        plugin.restoreScaleFromProject()
      if (plugin.featureOpacity) {
        plugin.restoreOpacityFromProject()
        // After the z restore (:restoreFromProject) — setCoverHidden
        // needs the z stored-baseline vars to be settled first.
        plugin.restoreCoverFromProject()
      }
      if (plugin.featureClipping)
        plugin.initClipping()
      if (plugin.featureReshape)
        plugin.initReshape()
      if (plugin.featureReverse)
        plugin.initReverse()
      if (plugin.featureCopyAttrs)
        plugin.initCopyAttrs()
      if (plugin.featureMerge)
        plugin.initMerge()
      if (plugin.featureRecenterHold)
        plugin.initRecenterHold()
      if (plugin.featureModeToggle)
        plugin.initModeToggle()
      if (plugin.featureLayerSwitch)
        plugin.initLayerSwitch()
      // Unconditional: the rubberband model machinery also powers the
      // always-on native confirm fixup, not just the spline feature.
      plugin.initSpline()
    }
  }

  // ----------------------------------------------------------------
  // Toolbar button
  // ----------------------------------------------------------------
  QfToolButton {
    id: pluginButton
    bgcolor: plugin.filterActive ? Theme.mainColor : Theme.darkGray
    round: true

    Text {
      anchors.centerIn: parent
      text: 'Z'
      font.bold: true
      font.pointSize: 16
      color: 'white'
    }

    onClicked: {
      // Toggle: the non-modal panel has no scrim to tap-dismiss.
      if (zDialog.visible)
        zDialog.close()
      else
        zDialog.open()
    }
  }

  // ----------------------------------------------------------------
  // Dialog
  // ----------------------------------------------------------------
  Dialog {
    id: zDialog
    parent: mainWindow.contentItem
    // Non-modal right-side panel: no overlay grab and no dim, so the map
    // keeps panning/zooming beside it; the Z button and the header
    // Close button both close.
    modal: false
    dim: false
    closePolicy: Popup.CloseOnEscape
    title: qsTr('Z Filter — Level Mapping')
    x: mainWindow.width - width
    y: 0
    width: Math.min(340, mainWindow.width - 60)
    height: mainWindow.height

    // Close lives top-right: the panel is full height, so a standard
    // footer button would sit at the very bottom of the screen.
    header: RowLayout {
      spacing: 0

      Label {
        text: zDialog.title
        font.bold: true
        elide: Text.ElideRight
        leftPadding: 16
        topPadding: 12
        bottomPadding: 12
        Layout.fillWidth: true
      }

      ToolButton {
        // Plain text with a full-size touch target: the old '✕' glyph
        // (U+2715) is missing from Android's fonts and its default
        // ToolButton hit area was too small to tap reliably there.
        text: qsTr('Close')
        font.bold: true
        topPadding: 12
        bottomPadding: 12
        leftPadding: 16
        rightPadding: 16
        Layout.rightMargin: 4
        onClicked: zDialog.close()
      }
    }

    onOpened: {
      if (!plugin.scanned)
        plugin.scanData()
    }

    ScrollView {
      id: zScroll
      anchors.fill: parent
      clip: true
      contentWidth: availableWidth   // vertical scroll only

      ColumnLayout {
        id: zDialogColumn
        width: zScroll.availableWidth
        spacing: 10

        // The primary control leads (desktop parity): tap toggles the
        // filter on/off — every other control below applies live.
        Button {
          id: zToggle
          Layout.fillWidth: true
          topPadding: 10
          bottomPadding: 10
          text: plugin.filterActive
              ? qsTr('Filter: ON  (%1 ± %2 m)')
                    .arg(levelCombo.editText).arg(toleranceField.text)
              : qsTr('Filter: OFF')
          onClicked: plugin.filterActive
              ? plugin.clearFilter() : plugin.applyFilter()
          background: Rectangle {
            color: plugin.filterActive ? '#2196F3' : 'transparent'
            border.color: plugin.filterActive
                ? '#2196F3' : Theme.secondaryTextColor
            border.width: 1
            radius: 4
          }
          contentItem: Text {
            text: zToggle.text
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            color: plugin.filterActive ? 'white' : Theme.mainTextColor
          }
        }

        Label {
          Layout.fillWidth: true
          text: plugin.summaryText()
          wrapMode: Text.WordWrap
          font.pointSize: 10
          opacity: 0.7
        }

        // On-device diagnosis for scan problems (hidden when clean).
        Label {
          Layout.fillWidth: true
          text: plugin.scanIssue
          visible: plugin.scanIssue !== ''
          wrapMode: Text.WordWrap
          font.pointSize: 9
          color: '#F44336'
        }

        // Level ladder — detected levels, highest first; tap a rung to
        // filter to it with its fitted width.
        ColumnLayout {
          Layout.fillWidth: true
          spacing: 2
          visible: plugin.suggestions.length > 0

          Repeater {
            model: plugin.ladderModel(plugin.suggestions)

            delegate: Rectangle {
              required property var modelData
              readonly property bool isActive:
                  Number(levelCombo.editText) === modelData.level
              readonly property bool inWindow:
                  plugin.filterActive && !isActive &&
                  Math.abs(modelData.level - Number(levelCombo.editText))
                      <= Number(toleranceField.text)
              Layout.fillWidth: true
              height: 40
              radius: 4
              color: isActive ? '#332196F3'
                              : (inWindow ? '#1A2196F3' : 'transparent')
              border.color: isActive ? '#2196F3' : Theme.secondaryTextColor
              border.width: isActive ? 2 : 1

              RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12

                Label {
                  text: plugin.fmt(modelData.level)
                  font.bold: isActive
                }

                Label {
                  text: modelData.label || ''
                  color: Theme.secondaryTextColor
                  elide: Text.ElideRight
                  Layout.fillWidth: true
                }

                Label {
                  text: '(' + modelData.count + ')'
                  color: Theme.secondaryTextColor
                }
              }

              TapHandler {
                // The width is the user's choice — a rung tap only moves
                // the level.
                onTapped: {
                  plugin.rebuildLevelModel(modelData.level)
                  plugin.applyFilter()
                }
              }
            }
          }
        }

        Label {
          text: qsTr('Level (elevation)')
          font.bold: true
        }

        RowLayout {
          Layout.fillWidth: true
          spacing: 6

          RoundButton {
            text: '▼'
            onClicked: plugin.stepLevel(-1)
          }

          ComboBox {
            id: levelCombo
            Layout.fillWidth: true
            editable: true
            validator: DoubleValidator {}
            onAccepted: {
              const value = Number(editText)
              if (!isNaN(value) && String(editText).trim() !== '') {
                plugin.addLevel(value)
                if (plugin.filterActive)
                  plugin.applyFilter()
              }
            }
          }

          RoundButton {
            text: '▲'
            onClicked: plugin.stepLevel(+1)
          }

          Label {
            text: qsTr('Step')
            leftPadding: 4
          }

          TextField {
            id: stepField
            Layout.preferredWidth: 64
            text: plugin.fmt(plugin.stepSize)
            validator: DoubleValidator { bottom: 0.01 }
            inputMethodHints: Qt.ImhFormattedNumbersOnly
            onEditingFinished: {
              const value = Number(text)
              if (!isNaN(value) && value > 0) {
                plugin.stepSize = value
                plugin.saveVar('lgs_z_step', plugin.fmt(value))
              }
              text = plugin.fmt(plugin.stepSize)
            }
          }
        }

        RowLayout {
          Layout.fillWidth: true
          spacing: 6

          Label {
            text: qsTr('Width ±')
          }

          TextField {
            id: toleranceField
            Layout.preferredWidth: 80
            text: '5'
            validator: DoubleValidator { bottom: 0 }
            inputMethodHints: Qt.ImhFormattedNumbersOnly
            onEditingFinished: {
              // Persist immediately: the width is the user's choice and
              // must survive rung taps and project reloads.
              const value = Number(text)
              if (!isNaN(value) && String(text).trim() !== '')
                plugin.saveVar('lgs_z_tolerance', plugin.fmt(value))
              if (plugin.filterActive)
                plugin.applyFilter()
            }
          }

          Label {
            text: qsTr('m')
          }

          Item {
            Layout.fillWidth: true
          }
        }

        // Quick-set ± presets + the data-derived Auto suggestion.
        Flow {
          Layout.fillWidth: true
          spacing: 4

          Repeater {
            model: plugin.tolPresets

            delegate: Button {
              required property var modelData
              flat: true
              topPadding: 4
              bottomPadding: 4
              leftPadding: 10
              rightPadding: 10
              text: '±' + plugin.fmt(modelData)
              background: Rectangle {
                color: 'transparent'
                border.color: Theme.secondaryTextColor
                border.width: 1
                radius: 2
              }
              onClicked: {
                toleranceField.text = plugin.fmt(modelData)
                plugin.saveVar('lgs_z_tolerance', plugin.fmt(modelData))
                if (plugin.filterActive)
                  plugin.applyFilter()
              }
            }
          }

          Button {
            flat: true
            topPadding: 4
            bottomPadding: 4
            leftPadding: 10
            rightPadding: 10
            enabled: plugin.autoTol > 0
            text: plugin.autoTol > 0
                ? qsTr('Auto (±%1)').arg(plugin.fmt(plugin.autoTol)) : qsTr('Auto')
            background: Rectangle {
              color: 'transparent'
              border.color: Theme.secondaryTextColor
              border.width: 1
              radius: 2
            }
            onClicked: {
              toleranceField.text = plugin.fmt(plugin.autoTol)
              plugin.saveVar('lgs_z_tolerance', plugin.fmt(plugin.autoTol))
              if (plugin.filterActive)
                plugin.applyFilter()
            }
          }
        }

        RowLayout {
          Layout.fillWidth: true

          Switch {
            id: showNullSwitch
            checked: true
            onToggled: {
              if (plugin.filterActive)
                plugin.applyFilter()
            }
          }

          Label {
            text: qsTr('Show features with no elevation')
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
          }
        }

        RowLayout {
          Layout.fillWidth: true

          Switch {
            id: adjacentSwitch
            checked: false
            onToggled: {
              plugin.saveVar('lgs_z_adjacent', checked ? '1' : '0')
              if (plugin.filterActive)
                plugin.applyFilter()
            }
          }

          Label {
            text: qsTr('Include adjacent levels')
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
          }
        }

        Button {
          Layout.fillWidth: true
          text: qsTr('Rescan data')
          onClicked: plugin.scanData()
        }

        Label {
          Layout.fillWidth: true
          text: plugin.filterActive
              ? (adjacentSwitch.checked
                 ? qsTr('Filter is ON — selected level and adjacent levels are shown.')
                 : qsTr('Filter is ON — only the selected level is shown.'))
              : qsTr('Filter is off — all data is shown.')
          wrapMode: Text.WordWrap
          font.pointSize: 10
          opacity: 0.7
        }

        // Which build this device is actually running. A sidecar only
        // arrives with a fresh QField export, so without this a field
        // report cannot be told apart from a stale project.
        Label {
          Layout.fillWidth: true
          text: plugin.buildLabel()
          visible: plugin.sidecarBuild.length > 0
          wrapMode: Text.WordWrap
          font.pointSize: 9
          opacity: 0.5
        }
      }
    }
  }

  // ==================================================================
  // SCALE DISPLAY + LOCK
  // ==================================================================
  property var canvas: null          // iface.mapCanvas() QQuickItem
  property var scaleSettings: null   // canvas.mapSettings
  property bool scaleLocked: false
  property real lockedScale: 0
  property bool suppressEnforce: false
  readonly property var scalePresets: [250, 500, 1000, 2500, 5000]
  // QField crashes when zoomed in to extreme scales — never allow the map
  // past 1:minSafeScale. Always active, independent of the scale lock.
  readonly property real minSafeScale: 20

  function formatScale(s) {
    if (!s || !isFinite(s) || s <= 0)
      return '1:–'
    // Round to 3 significant figures, then group digits: "1:2 500".
    const mag = Math.pow(10, Math.max(0, Math.floor(Math.log(s) / Math.LN10) - 2))
    const digits = String(Math.round(Math.round(s / mag) * mag))
    let out = ''
    for (let i = 0; i < digits.length; i++) {
      if (i > 0 && (digits.length - i) % 3 === 0)
        out += ' '
      out += digits.charAt(i)
    }
    return '1:' + out
  }

  function initScaleSettings() {
    try {
      canvas = iface.mapCanvas()
      scaleSettings = canvas ? canvas.mapSettings : null
    } catch (error) {
      canvas = null
      scaleSettings = null
    }
  }

  function attachOverlay() {
    try {
      // Overlay the pill bar on the map canvas (bottom centre — same spot
      // the scale pill lived alone before it grew neighbours).
      if (canvas && canvas.width !== undefined) {
        overlayBar.parent = canvas
        overlayBar.anchors.horizontalCenter = canvas.horizontalCenter
        overlayBar.anchors.bottom = canvas.bottom
        overlayBar.anchors.bottomMargin = 64
        overlayBar.visible = true
        attachLayerSwitch()
        return
      }
    } catch (error) {}
    try {
      // Fallback: live in the plugins toolbar instead.
      overlayBar.visible = true
      iface.addItemToPluginsToolbar(overlayBar)
    } catch (error) {}
  }

  function attachLayerSwitch() {
    // Lower left, a hair off the edge: 8px in leaves QField's dashboard
    // edge-swipe its drag margin, and the bottom margin clears the pill
    // bar (its own bottom 64, plus a pill's height). No plugins-toolbar
    // fallback — a vertical column has no business in a toolbar, so with
    // no canvas the column simply never shows.
    if (!featureLayerSwitch)
      return
    try {
      layerSwitchBar.parent = canvas
      layerSwitchBar.anchors.left = canvas.left
      layerSwitchBar.anchors.leftMargin = 8
      layerSwitchBar.anchors.bottom = canvas.bottom
      layerSwitchBar.anchors.bottomMargin = 96
      layerSwitchAttached = true
    } catch (error) {}
  }

  function setMapScale(target) {
    if (!scaleSettings || !(target > 0))
      return
    suppressEnforce = true
    try {
      const extent = scaleSettings.extent
      const cx = (extent.xMinimum + extent.xMaximum) / 2
      const cy = (extent.yMinimum + extent.yMaximum) / 2
      if (canvas && canvas.mapCanvasWrapper && canvas.mapCanvasWrapper.zoomScale) {
        // zoomScale(center IN MAP COORDS, ABSOLUTE target scale) —
        // public slot on QgsQuickMapCanvasMap.
        canvas.mapCanvasWrapper.zoomScale(Qt.point(cx, cy), target)
      } else {
        // Fallback: mapSettings.extent is a writable property.
        const factor = target / scaleSettings.scale
        const hw = (extent.xMaximum - extent.xMinimum) * factor / 2
        const hh = (extent.yMaximum - extent.yMinimum) * factor / 2
        scaleSettings.extent = GeometryUtils.createRectangleFromPoints(
            GeometryUtils.point(cx - hw, cy - hh),
            GeometryUtils.point(cx + hw, cy + hh))
      }
    } catch (error) {
    } finally {
      suppressEnforce = false
    }
  }

  function lockScale(value) {
    if (!(value > 0))
      return
    value = Math.max(Number(value), minSafeScale)
    scaleLocked = true
    lockedScale = value
    saveVar('lgs_scale_locked', '1')
    saveVar('lgs_scale_value', fmt(value))
    setMapScale(value)
    toast(qsTr('Scale locked at %1').arg(formatScale(value)))
  }

  function unlockScale() {
    scaleLocked = false
    saveVar('lgs_scale_locked', '0')
    toast(qsTr('Scale unlocked'))
  }

  function restoreScaleFromProject() {
    const value = Number(projVar('lgs_scale_value', ''))
    if (projVar('lgs_scale_locked', '0') === '1' && !isNaN(value) && value > 0) {
      scaleLocked = true
      lockedScale = value
      setMapScale(value)
    }
  }

  Connections {
    target: plugin.scaleSettings
    ignoreUnknownSignals: true
    function onExtentChanged() {
      if (plugin.suppressEnforce)
        return
      // Safety clamp first (always on): snap straight back if the map went
      // past 1:minSafeScale — QField crashes at extreme zoom-in.
      if (plugin.scaleSettings &&
          plugin.scaleSettings.scale > 0 &&
          plugin.scaleSettings.scale < plugin.minSafeScale) {
        plugin.setMapScale(plugin.minSafeScale)
        return
      }
      if (!plugin.featureScale || !plugin.scaleLocked)
        return
      if (Math.abs(plugin.scaleSettings.scale - plugin.lockedScale) /
          plugin.lockedScale <= 0.01)
        return  // dead-band: already at the locked scale
      enforceTimer.restart()
    }
  }

  Timer {
    id: enforceTimer
    interval: 300
    repeat: false
    onTriggered: {
      if (!plugin.scaleLocked || !plugin.scaleSettings)
        return
      if (plugin.canvas && plugin.canvas.pinched === true) {
        restart()  // pinch still in progress — wait for it to settle
        return
      }
      if (Math.abs(plugin.scaleSettings.scale - plugin.lockedScale) /
          plugin.lockedScale > 0.01)
        plugin.setMapScale(plugin.lockedScale)
    }
  }

  // Canvas overlay bar: every pill lives here so features never fight
  // over the bottom-centre spot. Invisible pills take no space in a Row.
  Row {
    id: overlayBar
    visible: false
    spacing: 8

    Rectangle {
      id: levelLockPill
      visible: plugin.featureZFilter && plugin.filterActive
      anchors.verticalCenter: parent.verticalCenter
      width: 44
      height: levelLockText.contentHeight + 12
      radius: height / 2
      // Inverted while locked — same active-state language as the
      // spline pill.
      color: plugin.zStepLocked ? '#E6FFFFFF' : '#99000000'

      Text {
        id: levelLockText
        anchors.centerIn: parent
        font.pixelSize: 14
        text: plugin.zStepLocked ? '🔒' : '🔓'
      }

      TapHandler {
        // ReleaseWithinBounds on every pill: the default DragThreshold
        // policy only takes a passive grab, so the same tap ALSO
        // reached QField's canvas handlers underneath — pressing a
        // pill placed a digitising point / selected the feature below.
        // The exclusive grab consumes the tap at the pill.
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: plugin.toggleZStepLock()
      }
    }

    Rectangle {
      id: levelDownPill
      visible: plugin.featureZFilter && plugin.filterActive
      anchors.verticalCenter: parent.verticalCenter
      width: 44
      height: levelDownText.contentHeight + 12
      radius: height / 2
      color: '#99000000'

      Text {
        id: levelDownText
        anchors.centerIn: parent
        font.pixelSize: 14
        color: plugin.zStepLocked ? '#66FFFFFF' : 'white'
        text: '▼'
      }

      TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: plugin.stepLevel(-1)
      }
    }

    Rectangle {
      id: levelUpPill
      visible: plugin.featureZFilter && plugin.filterActive
      anchors.verticalCenter: parent.verticalCenter
      width: 44
      height: levelUpText.contentHeight + 12
      radius: height / 2
      color: '#99000000'

      Text {
        id: levelUpText
        anchors.centerIn: parent
        font.pixelSize: 14
        color: plugin.zStepLocked ? '#66FFFFFF' : 'white'
        text: '▲'
      }

      TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: plugin.stepLevel(+1)
      }
    }

    Rectangle {
      id: scalePill
      visible: plugin.featureScale
      anchors.verticalCenter: parent.verticalCenter
      width: pillRow.width + 24
      height: pillText.contentHeight + 12
      radius: height / 2
      color: '#99000000'   // semi-opaque black; children stay fully opaque

      Row {
        id: pillRow
        anchors.centerIn: parent
        spacing: 6

        Text {
          visible: plugin.scaleLocked
          anchors.verticalCenter: parent.verticalCenter
          text: '🔒'   // padlock
          font.pixelSize: 12
          color: 'white'
        }

        Text {
          id: pillText
          anchors.verticalCenter: parent.verticalCenter
          font.pixelSize: 14
          color: 'white'
          text: plugin.scaleSettings
              ? plugin.formatScale(plugin.scaleSettings.scale) : '1:–'
        }
      }

      TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: scaleDialog.open()
      }
    }

    Rectangle {
      id: imageryPill
      visible: plugin.featureOpacity && plugin.opacitySupported &&
               plugin.resolvedImageryCount + plugin.resolvedVectorCount > 0
      anchors.verticalCenter: parent.verticalCenter
      width: imageryText.contentWidth + 24
      height: imageryText.contentHeight + 12
      radius: height / 2
      color: '#99000000'

      Text {
        id: imageryText
        anchors.centerIn: parent
        font.pixelSize: 14
        color: 'white'
        text: plugin.opacityLabel
      }

      TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: opacityDialog.open()
      }
    }

    Rectangle {
      id: clipPill
      visible: plugin.featureClipping && plugin.clipStep === 0 &&
               plugin.reshapeStep === 0 && plugin.reverseStep === 0 &&
               plugin.copyStep === 0 && plugin.mergeStep === 0 &&
               plugin.clipAvailable
      anchors.verticalCenter: parent.verticalCenter
      width: clipPillText.contentWidth + 24
      height: clipPillText.contentHeight + 12
      radius: height / 2
      color: '#99000000'

      Text {
        id: clipPillText
        anchors.centerIn: parent
        font.pixelSize: 14
        color: 'white'
        text: qsTr('✂ Clip')
      }

      TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: plugin.enterClipMode()
      }
    }

    Rectangle {
      id: splinePill
      // Digitizing only (v32): reshape has its own per-style spline
      // toggle in the reshape banner and no longer shares this switch.
      visible: plugin.featureSpline && plugin.splinePillVisible
      anchors.verticalCenter: parent.verticalCenter
      width: splinePillText.contentWidth + 24
      height: splinePillText.contentHeight + 12
      radius: height / 2
      // Inverted colours while armed — same active-state language as the
      // scale padlock, kept monochrome.
      color: plugin.splineArmed ? '#E6FFFFFF' : '#99000000'

      Text {
        id: splinePillText
        anchors.centerIn: parent
        font.pixelSize: 14
        color: plugin.splineArmed ? 'black' : 'white'
        // ASCII on purpose: '∿' (U+223F) is not in Android's fonts.
        text: qsTr('~ Spline')
      }

      TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: plugin.toggleSplineArmed()
      }
    }

    Rectangle {
      id: reshapePill
      // Browse mode only: hidden while a digitizing/measure session is
      // active so the native rubberband/crosshair never overlap the
      // reshape drawing.
      visible: plugin.featureReshape && plugin.reshapeStep === 0 &&
               plugin.clipStep === 0 && plugin.reverseStep === 0 &&
               plugin.copyStep === 0 && plugin.mergeStep === 0 &&
               !plugin.reshapeEditingActive
      anchors.verticalCenter: parent.verticalCenter
      width: reshapePillText.contentWidth + 24
      height: reshapePillText.contentHeight + 12
      radius: height / 2
      color: '#99000000'

      Text {
        id: reshapePillText
        anchors.centerIn: parent
        font.pixelSize: 14
        color: 'white'
        // Basic arrow on purpose: '⤳' (U+2933) is not in Android's fonts.
        text: qsTr('→ Reshape')
      }

      TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: plugin.enterReshapeMode()
      }
    }

    Rectangle {
      id: reversePill
      // Browse mode only — same gating as Reshape: hidden while a
      // digitizing/measure session or another canvas mode is active.
      visible: plugin.featureReverse && plugin.reverseStep === 0 &&
               plugin.clipStep === 0 && plugin.reshapeStep === 0 &&
               plugin.copyStep === 0 && plugin.mergeStep === 0 &&
               !plugin.reshapeEditingActive && plugin.reverseAvailable
      anchors.verticalCenter: parent.verticalCenter
      width: reversePillText.contentWidth + 24
      height: reversePillText.contentHeight + 12
      radius: height / 2
      color: '#99000000'

      Text {
        id: reversePillText
        anchors.centerIn: parent
        font.pixelSize: 14
        color: 'white'
        // Basic arrow on purpose: '⇄' (U+21C4) is not in Android's fonts.
        text: qsTr('↔ Reverse')
      }

      TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: plugin.enterReverseMode()
      }
    }

    Rectangle {
      id: copyPill
      // Browse mode only — same gating as Reshape: hidden while a
      // digitizing/measure session or another canvas mode is active.
      visible: plugin.featureCopyAttrs && plugin.copyStep === 0 &&
               plugin.clipStep === 0 && plugin.reshapeStep === 0 &&
               plugin.reverseStep === 0 && plugin.mergeStep === 0 &&
               !plugin.reshapeEditingActive && plugin.copyAttrsAvailable
      anchors.verticalCenter: parent.verticalCenter
      width: copyPillText.contentWidth + 24
      height: copyPillText.contentHeight + 12
      radius: height / 2
      color: '#99000000'

      Text {
        id: copyPillText
        anchors.centerIn: parent
        font.pixelSize: 14
        color: 'white'
        // '»' (U+00BB, Latin-1) on purpose — fancier copy glyphs like
        // '⧉' are not in Android's fonts.
        text: qsTr('» Copy')
      }

      TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: plugin.enterCopyMode()
      }
    }

    Rectangle {
      id: mergePill
      // Browse mode only — same gating as Reshape.
      visible: plugin.featureMerge && plugin.mergeStep === 0 &&
               plugin.clipStep === 0 && plugin.reshapeStep === 0 &&
               plugin.reverseStep === 0 && plugin.copyStep === 0 &&
               !plugin.reshapeEditingActive && plugin.mergeAvailable
      anchors.verticalCenter: parent.verticalCenter
      width: mergePillText.contentWidth + 24
      height: mergePillText.contentHeight + 12
      radius: height / 2
      color: '#99000000'

      Text {
        id: mergePillText
        anchors.centerIn: parent
        font.pixelSize: 14
        color: 'white'
        // Plain ASCII on purpose — union glyphs like '∪' are not in
        // Android's fonts.
        text: qsTr('+ Merge')
      }

      TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: plugin.enterMergeMode()
      }
    }

    Rectangle {
      id: holdPill
      // Settings toggle, not a canvas mode — stays visible while
      // digitizing (that is exactly when the freehand recenter bites);
      // hidden only while another sidecar tool is mid-flow.
      // Reshape is not in this list (v33): it recentres on lift, this is
      // the one switch for that, and the tool now stays open for a whole
      // session of edges.
      visible: plugin.featureRecenterHold && plugin.recenterHoldAvailable &&
               plugin.clipStep === 0 &&
               plugin.reverseStep === 0 && plugin.copyStep === 0 &&
               plugin.mergeStep === 0
      anchors.verticalCenter: parent.verticalCenter
      width: holdPillText.contentWidth + 24
      height: holdPillText.contentHeight + 12
      radius: height / 2
      // Inverted while holding — same active-state language as the
      // spline pill.
      color: plugin.recenterHoldActive ? '#E6FFFFFF' : '#99000000'

      Text {
        id: holdPillText
        anchors.centerIn: parent
        font.pixelSize: 14
        color: plugin.recenterHoldActive ? 'black' : 'white'
        // Emoji on purpose — crosshair glyphs like '⌖' (U+2316) are
        // not in Android's fonts.
        text: qsTr('📌 Hold')
      }

      TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: plugin.setRecenterHold(!plugin.recenterHoldActive)
      }
    }

    Rectangle {
      id: modePill
      // Like the Hold pill, visible in BOTH browse and digitize — the
      // whole point is flipping modes without opening the side menu.
      // Hidden only while a sidecar tool is mid-flow.
      visible: plugin.featureModeToggle &&
               plugin.clipStep === 0 && plugin.reshapeStep === 0 &&
               plugin.reverseStep === 0 && plugin.copyStep === 0 &&
               plugin.mergeStep === 0
      anchors.verticalCenter: parent.verticalCenter
      width: modePillText.contentWidth + 24
      height: modePillText.contentHeight + 12
      radius: height / 2
      // Inverted while digitizing — same active-state language as the
      // spline and hold pills.
      color: plugin.mapModeState === 'digitize' ? '#E6FFFFFF' : '#99000000'

      Text {
        id: modePillText
        anchors.centerIn: parent
        font.pixelSize: 14
        color: plugin.mapModeState === 'digitize' ? 'black' : 'white'
        // Emoji on purpose — see the hold pill. Measure/3d render the
        // browse face; a tap still lands in digitize via QField.
        text: plugin.mapModeState === 'digitize'
            ? qsTr('✏ Draw') : qsTr('🔍 Browse')
      }

      TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: plugin.toggleMapMode()
      }
    }
  }

  // ================================================================
  // Layer switch (v28, name pills v31)
  //
  // A stack of layer NAMES down the left edge that set QField's ACTIVE
  // layer without opening the dashboard drawer. The active layer decides
  // which layer the digitise button writes to, and every sidecar tool
  // here (Reshape / Reverse / Copy / Merge) locks onto it at entry —
  // yet reaching it costs a drawer, a scroll and a tap, with the map
  // covered throughout.
  // ================================================================

  property var layerSwitchEntries: []        // [{name, label}], present only
  property string layerSwitchActiveName: ''  // '' = something else is active
  property bool layerSwitchAwake: true       // false once it has dimmed
  property bool layerSwitchSupported: true   // false once a write no-ops
  property bool layerSwitchAttached: false   // parked on the canvas

  // Opacity of one character of a name, so a pill fades off to the right
  // instead of sitting on the map as a solid plate. index 0 is the
  // leftmost character; reveal is 0 at rest and 1 just after a tap.
  //
  // At rest only the head of the name survives — enough to show the
  // control is there — and by reveal 1 every character is solid. The
  // clamp is what makes both of those exact rather than merely close.
  // Kept pure JS — the test harness runs this verbatim.
  function layerSwitchCharAlpha(index, count, reveal) {
    // A one-character name has nowhere to fade to; t stays at the head.
    const t = count <= 1 ? 0 : index / (count - 1)
    const edge = 0.10 + 1.30 * reveal
    const alpha = (edge - t) / 0.35
    return alpha < 0 ? 0 : (alpha > 1 ? 1 : alpha)
  }

  function initLayerSwitch() {
    // Only layers that actually came down in the package get a button —
    // layerByName already falls back through the pre-swap ordinals.
    let names = []
    for (const name of layerNames) {
      if (layerByName(name) !== null)
        names.push(name)
    }
    let entries = []
    for (const name of names)
      entries.push({ name: name, label: baseName(name) })
    layerSwitchEntries = entries
    syncLayerSwitchActive()
    // Start awake so the column is seen at least once, then let it settle
    // to the dimmed resting state on its own.
    wakeLayerSwitch()
  }

  // Match by layer IDENTITY, never by name string: a pre-swap package
  // answers to a legacy ordinal and layerByName knows both spellings.
  function layerSwitchActiveFor(layer) {
    if (layer === null || layer === undefined)
      return ''
    for (const entry of layerSwitchEntries) {
      if (layerByName(entry.name) === layer)
        return entry.name
    }
    return ''
  }

  function syncLayerSwitchActive() {
    layerSwitchActiveName = layerSwitchActiveFor(reshapeActiveLayer())
  }

  function wakeLayerSwitch() {
    layerSwitchAwake = true
    layerSwitchWakeTimer.restart()
  }

  function layerSwitchChangeAllowed() {
    // dashBoard.allowActiveLayerChange (a QField property alias) goes
    // false mid-feature. Unreadable on another build counts as allowed —
    // the write verifies itself anyway.
    try {
      if (reshapeDashboard !== null && reshapeDashboard !== undefined &&
          reshapeDashboard.allowActiveLayerChange === false)
        return false
    } catch (error) {}
    return true
  }

  // dashBoard.activeLayer is a writable property alias in QField, but no
  // QField code ever assigns it — it is only ever read. So write it, read
  // it back and identity-compare, the same attempt-and-verify the layer
  // opacity rows use.
  function writeActiveLayer(layer) {
    let items = []
    if (reshapeDashboard !== null && reshapeDashboard !== undefined)
      items.push(reshapeDashboard)
    for (const name of ['dashBoard', 'projectInfo', 'locatorBridge']) {
      try {
        const item = iface.findItemByObjectName(name)
        if (item !== null && item !== undefined)
          items.push(item)
      } catch (error) {}
    }
    for (const item of items) {
      try {
        item.activeLayer = layer
        if (item.activeLayer === layer) {
          reshapeDashboard = item
          return true
        }
      } catch (error) {}
    }
    return false
  }

  function setActiveLayerByName(name) {
    wakeLayerSwitch()
    const layer = layerByName(name)
    if (layer === null) {
      // Gone since startup — drop the button rather than keep a dud.
      let entries = []
      for (const entry of layerSwitchEntries) {
        if (entry.name !== name)
          entries.push(entry)
      }
      layerSwitchEntries = entries
      toast(qsTr('%1 is not in this project').arg(baseName(name)))
      return
    }
    if (reshapeActiveLayer() === layer) {
      layerSwitchActiveName = name
      toast(qsTr('Active layer: %1').arg(baseName(name)))
      return
    }
    if (!layerSwitchChangeAllowed()) {
      toast(qsTr('Finish the current feature first'))
      return
    }
    if (!writeActiveLayer(layer)) {
      // Silently no-oped on every item we can reach: this build will not
      // let a plugin set the active layer. Retire the column for the
      // session rather than leave dead buttons on the map.
      layerSwitchSupported = false
      toast(qsTr('Layer switching is not supported by this QField build'))
      return
    }
    layerSwitchActiveName = name
    toast(qsTr('Active layer: %1').arg(baseName(name)))
  }

  Timer {
    id: layerSwitchWakeTimer
    // Long enough to read the name just picked, short enough that the
    // stack is not clutter. Each pill's own reveal does the fading.
    interval: 1600
    repeat: false
    onTriggered: plugin.layerSwitchAwake = false
  }

  Connections {
    // The legend can change the active layer behind our back; follow it
    // so the highlight never lies. reshapeDashboard is a plain var, so
    // this target rebinds when the lazy probe finally finds the item.
    target: plugin.reshapeDashboard
    ignoreUnknownSignals: true
    function onActiveLayerChanged() {
      plugin.syncLayerSwitchActive()
      plugin.wakeLayerSwitch()
      plugin.reshapeRelockLayer()
    }
  }

  Column {
    id: layerSwitchBar
    // Hidden while a sidecar tool is mid-flow — those own the screen and
    // have locked their layer already. Fewer than two present layers is
    // nothing to switch between, so the column stays away entirely.
    //
    // Reshape is the exception (v33): it now stays open between lines
    // instead of closing after each one, so hiding the pills for the
    // whole session would take away the very control you would use to
    // reshape on another layer. They come back whenever no line is part
    // drawn, and reshape re-locks itself to whatever you pick.
    visible: plugin.featureLayerSwitch && plugin.layerSwitchAttached &&
             plugin.layerSwitchSupported &&
             plugin.layerSwitchEntries.length > 1 &&
             plugin.clipStep === 0 &&
             (plugin.reshapeStep === 0 ||
              plugin.reshapeControls.length === 0) &&
             plugin.reverseStep === 0 && plugin.copyStep === 0 &&
             plugin.mergeStep === 0
    spacing: 6
    z: 1
    // No opacity here on purpose: each pill fades itself, horizontally,
    // through its own reveal. Dimming the column too would dim twice.

    Repeater {
      model: plugin.layerSwitchEntries

      delegate: Rectangle {
        id: layerSwitchButton
        required property var modelData

        readonly property bool isActive:
            plugin.layerSwitchActiveName === layerSwitchButton.modelData.name

        // 0 at rest, 1 just after a tap or an active-layer change. The
        // ACTIVE pill rests part-revealed, so a glance still names the
        // current layer without lighting the whole stack.
        property real reveal: plugin.layerSwitchAwake
            ? 1.0 : (layerSwitchButton.isActive ? 0.28 : 0.0)

        Behavior on reveal {
          NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
        }

        // Inverted while active — the same state language as the level
        // lock, spline, hold and mode pills.
        readonly property color pad: layerSwitchButton.isActive
            ? Qt.rgba(1, 1, 1, 0.90) : Qt.rgba(0, 0, 0, 0.60)
        readonly property string ink: layerSwitchButton.isActive
            ? 'black' : 'white'

        // Sized off the character Row, not a Text.contentWidth: laying a
        // name out per character loses the kerning pairs and comes out a
        // touch wider, and the pill has to fit what is actually drawn.
        width: nameRow.width + 26
        height: nameRow.height + 18
        radius: height / 2

        // The pill does not end so much as stop being there. Solid at
        // the left so the control stays findable, gone by the right
        // edge, with the solid head growing rightward as reveal rises.
        // Only the ALPHA moves across the stops — holding r/g/b still is
        // what keeps the fade from drifting through some other colour.
        // First use of Gradient in this file; core QtQuick, no import.
        gradient: Gradient {
          orientation: Gradient.Horizontal

          GradientStop {
            position: 0.0
            color: layerSwitchButton.pad
          }

          GradientStop {
            position: 0.18 + 0.62 * layerSwitchButton.reveal
            color: layerSwitchButton.pad
          }

          GradientStop {
            position: 1.0
            color: Qt.rgba(layerSwitchButton.pad.r, layerSwitchButton.pad.g,
                           layerSwitchButton.pad.b, 0)
          }
        }

        // One Text per character. This is the only import-free way to
        // fade a string across its own width: Qt5Compat.GraphicalEffects
        // and QtQuick.Effects are not imported here (and may not ship
        // with QField at all), and a ShaderEffect would want a
        // precompiled .qsb, which cannot ride inside a single sidecar
        // .qml. Thirteen Text items at worst, built once at startup.
        Row {
          id: nameRow
          anchors.left: parent.left
          anchors.leftMargin: 13
          anchors.verticalCenter: parent.verticalCenter
          spacing: 0

          Repeater {
            model: layerSwitchButton.modelData.label.length

            delegate: Text {
              required property int index
              text: layerSwitchButton.modelData.label.charAt(index)
              font.pixelSize: 14
              font.bold: true
              color: layerSwitchButton.ink
              opacity: plugin.layerSwitchCharAlpha(
                  index, layerSwitchButton.modelData.label.length,
                  layerSwitchButton.reveal)
            }
          }
        }

        TapHandler {
          // ReleaseWithinBounds like every other overlay control: the
          // default policy takes only a passive grab, so the tap would
          // ALSO reach QField's canvas handlers underneath and digitise.
          // The whole pill takes the tap, faded tail included — the
          // target size is the point of this revision.
          gesturePolicy: TapHandler.ReleaseWithinBounds
          // And do not approve a take-over (v33): the reshape tool's
          // freehand DragHandler sits on a catcher at this z and has
          // dragThreshold 0, so while reshape is open a pixel of pen
          // jitter on a layer pill would let it take the grab and cancel
          // the tap. Cancellation stays approved so Qt can still clean
          // up.
          grabPermissions: PointerHandler.CanTakeOverFromItems |
                           PointerHandler.CanTakeOverFromHandlersOfDifferentType |
                           PointerHandler.ApprovesCancellation
          onTapped: plugin.setActiveLayerByName(layerSwitchButton.modelData.name)
        }
      }
    }
  }

  Dialog {
    id: scaleDialog
    parent: mainWindow.contentItem
    modal: true
    title: qsTr('Map Scale')
    x: (mainWindow.width - width) / 2
    y: (mainWindow.height - height) / 2
    width: Math.min(mainWindow.width - 40, 420)
    standardButtons: Dialog.Close

    ColumnLayout {
      anchors.fill: parent
      spacing: 12

      Label {
        Layout.fillWidth: true
        text: plugin.scaleSettings
            ? qsTr('Current scale: %1').arg(
                  plugin.formatScale(plugin.scaleSettings.scale))
            : qsTr('Current scale unavailable')
        font.bold: true
      }

      // Preset scales — tap to lock the map at that scale.
      Flow {
        Layout.fillWidth: true
        spacing: 4

        Repeater {
          model: plugin.scalePresets

          delegate: Button {
            required property var modelData
            flat: true
            topPadding: 4
            bottomPadding: 4
            leftPadding: 10
            rightPadding: 10
            text: plugin.formatScale(modelData)
            background: Rectangle {
              color: 'transparent'
              border.color: Theme.secondaryTextColor
              border.width: 1
              radius: 2
            }
            onClicked: plugin.lockScale(modelData)
          }
        }
      }

      RowLayout {
        Layout.fillWidth: true
        spacing: 6

        Label {
          text: qsTr('Custom  1:')
        }

        TextField {
          id: customScaleField
          Layout.fillWidth: true
          validator: DoubleValidator { bottom: 1 }
          inputMethodHints: Qt.ImhFormattedNumbersOnly
          placeholderText: qsTr('e.g. 750')
        }

        Button {
          flat: true
          topPadding: 4
          bottomPadding: 4
          leftPadding: 10
          rightPadding: 10
          text: qsTr('Set')
          background: Rectangle {
            color: 'transparent'
            border.color: Theme.secondaryTextColor
            border.width: 1
            radius: 2
          }
          onClicked: {
            const value = Number(customScaleField.text)
            if (!isNaN(value) && value > 0)
              plugin.lockScale(value)
          }
        }
      }

      RowLayout {
        Layout.fillWidth: true

        Switch {
          checked: plugin.scaleLocked
          onToggled: {
            if (checked) {
              if (plugin.scaleSettings)
                plugin.lockScale(plugin.scaleSettings.scale)
            } else {
              plugin.unlockScale()
            }
          }
        }

        Label {
          Layout.fillWidth: true
          text: plugin.scaleLocked
              ? qsTr('Locked at %1 — pinch zooms snap back; panning is free.')
                    .arg(plugin.formatScale(plugin.lockedScale))
              : qsTr('Lock scale (freeze zoom at the current scale)')
          wrapMode: Text.WordWrap
        }
      }

      Label {
        Layout.fillWidth: true
        text: qsTr('Zoom-in is always capped at %1 (closer zooms crash the app).')
              .arg(plugin.formatScale(plugin.minSafeScale))
        wrapMode: Text.WordWrap
        font.pointSize: 10
        opacity: 0.7
      }
    }
  }

  // ==================================================================
  // IMAGERY OPACITY
  // ==================================================================
  Dialog {
    id: opacityDialog
    parent: mainWindow.contentItem
    modal: true
    title: qsTr('Layer Opacity')
    x: (mainWindow.width - width) / 2
    // Never let the title leave the screen — with enough rows the
    // centring maths would push it past the top edge.
    y: Math.max(20, (mainWindow.height - height) / 2)
    width: Math.min(mainWindow.width - 40,
                    opacityDialog.twoColumns ? 720 : 420)
    standardButtons: Dialog.Close

    // Rasters left, vectors right; columns stack on narrow screens. One
    // row per resolved, supported layer — values are read live from
    // imageryOpacities so button highlights follow taps.
    property var rasterNames: []
    property var vectorNames: []
    // [{name, layers}] — exported layer-tree folders (v25), resolved on
    // open like the name lists.
    property var groupEntries: []
    readonly property bool twoColumns:
        mainWindow.width >= 700 &&
        rasterNames.length > 0 && vectorNames.length > 0

    onAboutToShow: {
      rasterNames = plugin.resolvedImageryNames()
      vectorNames = plugin.resolvedVectorNames()
      groupEntries = plugin.resolvedGroupEntries()
    }

    Flickable {
      // v25: scroll instead of outgrowing the screen. The grid used to
      // anchors.fill the dialog with no height bound, so a long layer
      // list pushed rows past both screen edges with nothing to scroll.
      // Same capped-Flickable idiom as the copy-attributes field panel.
      id: opacityScroll
      anchors.fill: parent
      implicitWidth: opacityGrid.implicitWidth
      implicitHeight: Math.min(opacityGrid.implicitHeight,
                               mainWindow.height - 160)
      contentWidth: width
      contentHeight: opacityGrid.implicitHeight
      clip: true

      GridLayout {
        id: opacityGrid
        width: opacityScroll.width
        columns: opacityDialog.twoColumns ? 2 : 1
        columnSpacing: 24
        rowSpacing: 8

        // Folder rows (v25) — one tap sets every exported layer in a
        // layer-tree group. Spans both columns: a folder may mix rasters
        // and vectors.
        ColumnLayout {
          Layout.fillWidth: true
          Layout.columnSpan: opacityDialog.twoColumns ? 2 : 1
          visible: opacityDialog.groupEntries.length > 0
          spacing: 8

          Label {
            Layout.fillWidth: true
            elide: Text.ElideRight
            text: qsTr('Folders')
            font.bold: true
          }

          Repeater {
            model: opacityDialog.groupEntries

            delegate: RowLayout {
              id: groupOpacityRow
              required property var modelData
              Layout.fillWidth: true
              spacing: 4

              Label {
                Layout.fillWidth: true
                elide: Text.ElideRight
                text: groupOpacityRow.modelData.name
              }

              Repeater {
                model: plugin.opacitySteps

                delegate: Button {
                  id: groupStepButton
                  required property var modelData
                  // Highlighted only when EVERY member sits at this step.
                  readonly property bool current:
                      plugin.groupOpacityCurrent(
                          groupOpacityRow.modelData.layers, modelData)
                  flat: true
                  topPadding: 4
                  bottomPadding: 4
                  leftPadding: 10
                  rightPadding: 10
                  text: modelData === 0 ? qsTr('Off')
                                        : Math.round(modelData * 100)
                  font.bold: current
                  background: Rectangle {
                    color: 'transparent'
                    border.color: groupStepButton.current
                        ? Theme.mainColor : Theme.secondaryTextColor
                    border.width: groupStepButton.current ? 2 : 1
                    radius: 2
                  }
                  onClicked: plugin.applyOpacityToNames(
                                 groupOpacityRow.modelData.layers, modelData,
                                 false)
                }
              }
            }
          }
        }

        ColumnLayout {
          Layout.fillWidth: true
          Layout.alignment: Qt.AlignTop
          visible: opacityDialog.rasterNames.length > 0
          spacing: 8

          Label {
            Layout.fillWidth: true
            elide: Text.ElideRight
            text: qsTr('Rasters')
            font.bold: true
          }

          // One-tap group control, shown only when there is a group.
          RowLayout {
            Layout.fillWidth: true
            visible: opacityDialog.rasterNames.length > 1
            spacing: 4

            Label {
              Layout.fillWidth: true
              elide: Text.ElideRight
              text: qsTr('All rasters')
            }

            Repeater {
              model: plugin.opacitySteps

              delegate: Button {
                required property var modelData
                flat: true
                topPadding: 4
                bottomPadding: 4
                leftPadding: 10
                rightPadding: 10
                text: modelData === 0 ? qsTr('Off')
                                      : Math.round(modelData * 100)
                background: Rectangle {
                  color: 'transparent'
                  border.color: Theme.secondaryTextColor
                  border.width: 1
                  radius: 2
                }
                onClicked: plugin.applyOpacityToNames(
                               opacityDialog.rasterNames, modelData, false)
              }
            }
          }

          Repeater {
            model: opacityDialog.rasterNames

            delegate: RowLayout {
              id: opacityRow
              required property var modelData
              Layout.fillWidth: true
              spacing: 4

              Label {
                Layout.fillWidth: true
                elide: Text.ElideRight
                text: opacityRow.modelData
              }

              Repeater {
                model: plugin.opacitySteps

                delegate: Button {
                  id: stepButton
                  required property var modelData
                  readonly property bool current:
                      Math.abs(plugin.layerOpacityValue(opacityRow.modelData)
                               - modelData) < 0.01
                  flat: true
                  topPadding: 4
                  bottomPadding: 4
                  leftPadding: 10
                  rightPadding: 10
                  text: modelData === 0 ? qsTr('Off')
                                        : Math.round(modelData * 100)
                  font.bold: current
                  background: Rectangle {
                    color: 'transparent'
                    border.color: stepButton.current
                        ? Theme.mainColor : Theme.secondaryTextColor
                    border.width: stepButton.current ? 2 : 1
                    radius: 2
                  }
                  onClicked: plugin.applyLayerOpacity(
                                 opacityRow.modelData, modelData, false)
                }
              }
            }
          }
        }

        ColumnLayout {
          Layout.fillWidth: true
          Layout.alignment: Qt.AlignTop
          visible: opacityDialog.vectorNames.length > 0
          spacing: 8

          Label {
            Layout.fillWidth: true
            elide: Text.ElideRight
            text: qsTr('Vectors')
            font.bold: true
          }

          RowLayout {
            Layout.fillWidth: true
            visible: opacityDialog.vectorNames.length > 1
            spacing: 4

            Label {
              Layout.fillWidth: true
              elide: Text.ElideRight
              text: qsTr('All vectors')
            }

            Repeater {
              model: plugin.opacitySteps

              delegate: Button {
                required property var modelData
                flat: true
                topPadding: 4
                bottomPadding: 4
                leftPadding: 10
                rightPadding: 10
                text: modelData === 0 ? qsTr('Off')
                                      : Math.round(modelData * 100)
                background: Rectangle {
                  color: 'transparent'
                  border.color: Theme.secondaryTextColor
                  border.width: 1
                  radius: 2
                }
                onClicked: plugin.applyOpacityToNames(
                               opacityDialog.vectorNames, modelData, false)
              }
            }
          }

          Repeater {
            model: opacityDialog.vectorNames

            delegate: ColumnLayout {
              id: vectorOpacityRow
              required property var modelData
              Layout.fillWidth: true
              spacing: 2

              RowLayout {
                Layout.fillWidth: true
                spacing: 4

                Label {
                  Layout.fillWidth: true
                  elide: Text.ElideRight
                  text: vectorOpacityRow.modelData
                }

                Repeater {
                  model: plugin.opacitySteps

                  delegate: Button {
                    id: vectorStepButton
                    required property var modelData
                    readonly property bool current:
                        Math.abs(plugin.layerOpacityValue(
                                     vectorOpacityRow.modelData)
                                 - modelData) < 0.01
                    flat: true
                    topPadding: 4
                    bottomPadding: 4
                    leftPadding: 10
                    rightPadding: 10
                    text: modelData === 0 ? qsTr('Off')
                                          : Math.round(modelData * 100)
                    font.bold: current
                    background: Rectangle {
                      color: 'transparent'
                      border.color: vectorStepButton.current
                          ? Theme.mainColor : Theme.secondaryTextColor
                      border.width: vectorStepButton.current ? 2 : 1
                      radius: 2
                    }
                    onClicked: plugin.applyLayerOpacity(
                                   vectorOpacityRow.modelData, modelData, false)
                  }
                }
              }

              // Transported-cover sub-row, nested under the Basemap row.
              // Off still hides via the subset string (features AND labels
              // vanish); 100/50/25 fade the cover symbols through the
              // data-defined opacity the desktop bakes onto the renderer
              // (@lgs_cover_opacity) — QML has no renderer access itself.
              RowLayout {
                Layout.fillWidth: true
                spacing: 4
                visible: vectorOpacityRow.modelData === plugin.coverLayerName &&
                         !plugin.coverUnsupported

                Label {
                  Layout.fillWidth: true
                  Layout.leftMargin: 16
                  elide: Text.ElideRight
                  text: qsTr('Transported cover')
                  color: Theme.secondaryTextColor
                }

                Repeater {
                  model: plugin.opacitySteps

                  delegate: Button {
                    id: coverStepButton
                    required property var modelData
                    readonly property bool current:
                        plugin.coverStepCurrent(modelData)
                    flat: true
                    topPadding: 4
                    bottomPadding: 4
                    leftPadding: 10
                    rightPadding: 10
                    text: modelData === 0 ? qsTr('Off')
                                          : Math.round(modelData * 100)
                    font.bold: current
                    background: Rectangle {
                      color: 'transparent'
                      border.color: coverStepButton.current
                          ? Theme.mainColor : Theme.secondaryTextColor
                      border.width: coverStepButton.current ? 2 : 1
                      radius: 2
                    }
                    onClicked: plugin.setCoverOpacity(modelData)
                  }
                }
              }
            }
          }
        }
      }
    }
  }

  readonly property var opacitySteps: [1, 0.5, 0.25, 0]
  property var imageryOpacities: ({})    // layer name -> current value
  property var opacityUnsupported: ({})  // layer name -> true (row hidden)
  property bool opacitySupported: true   // false once EVERY layer refuses
  property int resolvedImageryCount: 0
  property int resolvedVectorCount: 0
  property string opacityLabel: 'Opacity'

  function resolvedImageryNames() {
    let names = []
    for (const name of opacityLayers) {
      if (layerByName(name) !== null && !opacityUnsupported[name])
        names.push(name)
    }
    return names
  }

  function resolvedVectorNames() {
    let names = []
    for (const name of vectorOpacityLayers) {
      if (layerByName(name) !== null && !opacityUnsupported[name])
        names.push(name)
    }
    return names
  }

  function layerOpacityValue(name) {
    const value = imageryOpacities[name]
    return value === undefined ? 1 : value
  }

  // Layer-tree folders (v25). QML cannot read the project's layer tree,
  // so the exporter bakes {name, layers} entries into opacityGroups;
  // members are resolved by name like every other lookup here. A folder
  // whose exported membership has collapsed below two layers is not
  // worth a row — the layers' own rows already cover it.
  function resolvedGroupEntries() {
    let entries = []
    for (const group of opacityGroups) {
      try {
        let members = []
        for (const name of group.layers) {
          if (layerByName(name) !== null && !opacityUnsupported[name])
            members.push(name)
        }
        if (members.length > 1)
          entries.push({ name: String(group.name), layers: members })
      } catch (error) {}
    }
    return entries
  }

  function groupOpacityCurrent(names, value) {
    // A folder reads as sitting on a step only when EVERY member does;
    // a mixed folder highlights nothing rather than lying about one.
    if (!names || names.length === 0)
      return false
    for (const name of names) {
      if (Math.abs(layerOpacityValue(name) - value) >= 0.01)
        return false
    }
    return true
  }

  function applyLayerOpacity(name, value, quiet) {
    const layer = layerByName(name)
    if (layer === null)
      return false
    let ok = false
    try {
      // opacity is a writable Q_PROPERTY on QgsMapLayer (3.18+) — same
      // mechanism as the Z filter's layer.subsetString assignments.
      layer.opacity = value
      if (Math.abs(Number(layer.opacity) - value) < 0.01)
        ok = true
      layer.triggerRepaint()
    } catch (error) {}
    if (!ok) {
      // Assignment silently no-oped: drop this layer's row; hide the pill
      // entirely once no layer accepts the property. Copy-on-write so the
      // var property emits its change signal (same-reference assignments
      // may not).
      let unsupported = Object.assign({}, opacityUnsupported)
      unsupported[name] = true
      opacityUnsupported = unsupported
      resolvedImageryCount = resolvedImageryNames().length
      resolvedVectorCount = resolvedVectorNames().length
      if (resolvedImageryCount + resolvedVectorCount === 0)
        opacitySupported = false
      if (!quiet)
        toast(qsTr('%1: opacity not supported').arg(name))
      return false
    }
    let values = Object.assign({}, imageryOpacities)
    values[name] = value
    imageryOpacities = values
    saveVar('lgs_opacity', JSON.stringify(values))
    refreshOpacityLabel()
    // A tap on an elevation-tied raster records the user's intent above,
    // but an out-of-window raster must stay Z-hidden (also re-asserts
    // after the startup opacity restore, which runs after the Z restore).
    if (filterActive)
      reassertRasterZFor(name)
    try {
      iface.mapCanvas().refresh()
    } catch (error) {}
    if (!quiet)
      toast(value === 0 ? qsTr('%1 hidden').arg(name)
                        : qsTr('%1 %2%').arg(name).arg(Math.round(value * 100)))
    return true
  }

  // Group control for one dialog column (or any name list).
  function applyOpacityToNames(names, value, quiet) {
    let applied = 0
    for (const name of names) {
      if (applyLayerOpacity(name, value, true))
        applied++
    }
    if (!quiet && applied > 0)
      toast(value === 0 ? qsTr('Layers hidden')
                        : qsTr('Layers %1%').arg(Math.round(value * 100)))
  }

  function refreshOpacityLabel() {
    // "Opacity 50" when every controlled layer (raster and vector) sits
    // on one value, bare "Opacity" when they differ.
    const names = resolvedImageryNames().concat(resolvedVectorNames())
    let shared
    for (const name of names) {
      const value = layerOpacityValue(name)
      if (shared === undefined)
        shared = value
      else if (Math.abs(shared - value) >= 0.01) {
        opacityLabel = qsTr('Opacity')
        return
      }
    }
    if (shared === undefined || Math.abs(shared - 1) < 0.01)
      opacityLabel = qsTr('Opacity')
    else
      opacityLabel = shared === 0
          ? qsTr('Opacity off')
          : qsTr('Opacity %1').arg(Math.round(shared * 100))
  }

  function restoreOpacityFromProject() {
    resolvedImageryCount = resolvedImageryNames().length
    resolvedVectorCount = resolvedVectorNames().length
    const raw = projVar('lgs_opacity', '')
    if (raw === '') {
      refreshOpacityLabel()
      return
    }
    const legacy = Number(raw)
    if (!isNaN(legacy)) {
      // Pre-per-layer exports stored one shared number — for rasters
      // only (the variable predates vector support; a stale value must
      // not suddenly dim the vector layers).
      if (legacy >= 0 && legacy < 1)
        applyOpacityToNames(resolvedImageryNames(), legacy, true)
      refreshOpacityLabel()
      return
    }
    try {
      const values = JSON.parse(raw)
      for (const name of
           resolvedImageryNames().concat(resolvedVectorNames())) {
        const value = Number(values[name])
        if (!isNaN(value) && value >= 0 && value < 1)
          applyLayerOpacity(name, value, true)
      }
    } catch (error) {}
    refreshOpacityLabel()
  }

  // ----------------------------------------------------------------
  // Transported-cover visibility (mirror of z_filter/expression.py
  // cover_* helpers + cover_toggle.py — keep in sync). Hides Basemap
  // polygons whose TypeLith1 is 'Transported Cover' via a subset-string
  // clause; the clause always lives in the baseline subset, beneath any
  // z clause, so the z filter's stored-original bookkeeping keeps
  // working unchanged.
  // ----------------------------------------------------------------
  property bool coverHidden: false
  // Set when the provider rejects the clause (no TypeLith1 on this copy)
  // — hides the dialog sub-row. QML cannot enumerate fields, so support
  // is attempt-and-verified like the z filter's subset writes.
  property bool coverUnsupported: false
  // Percent (v25). 100/50/25 fade the cover symbols through the
  // data-defined opacity the desktop bakes onto the Basemap renderer
  // (it reads @lgs_cover_opacity); 0 is the subset-string hide above.
  // Only meaningful while coverHidden is false.
  property real coverOpacity: 100
  readonly property string coverLayerName: '4 - Basemap'
  // '4 - Basemap' is index 3 of layerNames — the z filter's stored
  // baseline for it lives under these keys (see allTargets).
  readonly property string coverZOrigKey: 'lgs_z_orig_3'
  readonly property string coverZSavedKey: 'lgs_z_orig_saved_3'

  // mirror of z_filter/expression.py::cover_hide_clause — NULL-guarded so
  // un-attributed / mid-digitizing polygons stay visible
  function coverClause() {
    return '("TypeLith1" IS NULL OR "TypeLith1" <> \'Transported Cover\')'
  }

  // mirror of z_filter/expression.py::strip_cover_subset — returns the
  // pre-toggle subset, '' when the whole string was the clause, or the
  // input unchanged when no cover clause is recognized
  function stripCoverSubset(subset) {
    const text = String(subset || '').trim()
    if (text === '')
      return ''
    const clause = '\\(\\s*"TypeLith1"\\s+IS\\s+NULL\\s+OR\\s+"TypeLith1"' +
                   '\\s*<>\\s*\'Transported Cover\'\\s*\\)'
    const combined = new RegExp(
        '^\\(([\\s\\S]*)\\)\\s+AND\\s+' + clause + '$', 'i')
    const match = text.match(combined)
    if (match)
      return match[1]
    if (new RegExp('^' + clause + '$', 'i').test(text))
      return ''
    return String(subset)
  }

  // mirror of z_filter/expression.py::apply_cover_to_subset —
  // strip-then-add, so repeated application never nests clauses
  function applyCoverToSubset(subset, hidden) {
    const base = stripCoverSubset(subset)
    if (hidden)
      return combineSubset(base, coverClause())
    return base
  }

  function setCoverHidden(hidden, quiet) {
    const layer = layerByName(coverLayerName)
    if (layer === null) {
      if (!quiet)
        toast(qsTr('%1 not found').arg(coverLayerName))
      return false
    }
    const live = layer.subsetString || ''
    let zOwns = projVar(coverZSavedKey, '0') === '1'
    let oldBaseline = ''
    let zPart = null
    if (zOwns) {
      // The z filter owns the layer: applyFilter always sets the live
      // subset to combineSubset(storedBaseline, zClause), so recover the
      // z text from that exact shape.
      oldBaseline = projVar(coverZOrigKey, '')
      const prefix = oldBaseline !== '' ? '(' + oldBaseline + ') AND ' : ''
      if (live === oldBaseline)
        zPart = null
      else if (prefix !== '' && live.indexOf(prefix) === 0)
        zPart = live.substring(prefix.length)
      else if (prefix === '' && live !== '')
        zPart = live
      else
        // Unrecognized state — treat the live subset as the baseline;
        // the z filter re-saves its original on the next apply.
        zOwns = false
    }
    let newLive
    let newBaseline = ''
    if (zOwns) {
      newBaseline = applyCoverToSubset(oldBaseline, hidden)
      newLive = zPart !== null
          ? combineSubset(newBaseline, zPart) : newBaseline
    } else {
      newLive = applyCoverToSubset(live, hidden)
    }
    try {
      layer.subsetString = newLive
      if (layer.subsetString !== newLive) {
        // Provider rejected the clause (no TypeLith1 on this copy) —
        // put the original back rather than half-filter.
        layer.subsetString = live
        coverUnsupported = true
        if (!quiet)
          toast(qsTr('%1: no TypeLith1 field').arg(coverLayerName))
        return false
      }
      layer.triggerRepaint()
    } catch (error) {
      return false
    }
    if (zOwns)
      // Keep the z filter's stored baseline in step so its level changes
      // and clears preserve the cover state in both directions.
      saveVar(coverZOrigKey, newBaseline)
    coverHidden = hidden
    saveVar('lgs_cover_hidden', hidden ? '1' : '0')
    try {
      iface.mapCanvas().refresh()
    } catch (error) {}
    if (!quiet)
      toast(hidden ? qsTr('Transported cover hidden')
                   : qsTr('Transported cover visible'))
    return true
  }

  // The dialog's steps are fractions (1 / 0.5 / 0.25 / 0); the cover
  // state is a percent plus the hidden flag.
  function coverStepCurrent(step) {
    if (step === 0)
      return coverHidden
    if (coverHidden)
      return false
    return Math.abs(coverOpacity - step * 100) < 0.5
  }

  function setCoverOpacity(step) {
    if (step === 0) {
      setCoverHidden(true, false)
      return
    }
    // Coming back from hidden has to lift the subset clause first, but
    // quietly — this tap's toast is the opacity one below.
    if (coverHidden && !setCoverHidden(false, true))
      return
    const percent = Math.round(step * 100)
    coverOpacity = percent
    saveVar('lgs_cover_opacity', percent)
    try {
      const layer = layerByName(coverLayerName)
      if (layer !== null)
        layer.triggerRepaint()
      iface.mapCanvas().refresh()
    } catch (error) {}
    toast(qsTr('Transported cover %1%').arg(percent))
  }

  function restoreCoverFromProject() {
    const stored = Number(projVar('lgs_cover_opacity', '100'))
    coverOpacity = isFinite(stored) && stored > 0 ? stored : 100
    const saved = projVar('lgs_cover_hidden', '')
    let hidden = saved === '1'
    if (saved === '') {
      // No variable — a desktop-baked clause may still sit in the
      // datasource (or in the z filter's stored baseline when the z
      // restore has already re-wrapped the live subset).
      try {
        const layer = layerByName(coverLayerName)
        if (layer !== null) {
          const subject = projVar(coverZSavedKey, '0') === '1'
              ? projVar(coverZOrigKey, '')
              : (layer.subsetString || '')
          hidden = stripCoverSubset(subject) !== subject
        }
      } catch (error) {}
    }
    if (hidden)
      setCoverHidden(true, true)  // idempotent — never double-wraps
  }

  // ----------------------------------------------------------------
  // Elevation-tied rasters — authored by the desktop panel into the
  // lgs_z_rasters project variable. QML has no layer-tree access, so
  // "hidden" is opacity 0; the user's chosen opacity (imageryOpacities /
  // lgs_opacity) is what an in-window raster comes back to.
  // ----------------------------------------------------------------
  function rasterZTargets() {
    let targets = []
    try {
      const data = JSON.parse(projVar('lgs_z_rasters', ''))
      for (const e of (data && data.rasters) || []) {
        if (!e || !e.name || e.checked === false)
          continue
        const elevation = Number(e.elevation)
        if (!isFinite(elevation))
          continue
        targets.push({name: String(e.name), elevation: elevation})
      }
    } catch (error) {}
    return targets
  }

  // Opacity write WITHOUT persistence: never touches imageryOpacities /
  // lgs_opacity (the user's choice) and never marks opacityUnsupported —
  // Z-driven hides are transient, not user intent.
  function setLayerOpacityRaw(name, value) {
    const layer = layerByName(name)
    if (layer === null)
      return
    try {
      layer.opacity = value
      layer.triggerRepaint()
    } catch (error) {}
  }

  // Mirror of z_filter/expression.py raster_in_windows — keep in sync.
  function rasterInWindows(elevation, levels, tols) {
    for (let i = 0; i < levels.length; i++) {
      if (elevation >= levels[i] - tols[i] && elevation <= levels[i] + tols[i])
        return true
    }
    return false
  }

  function applyRasterZ(levels, tols) {
    for (const t of rasterZTargets()) {
      setLayerOpacityRaw(t.name,
                         rasterInWindows(t.elevation, levels, tols)
                             ? layerOpacityValue(t.name) : 0)
    }
  }

  // Filter cleared: every tied raster back to the user's opacity.
  function restoreRasterZ() {
    for (const t of rasterZTargets())
      setLayerOpacityRaw(t.name, layerOpacityValue(t.name))
  }

  // Re-assert the Z state for one layer after an opacity-panel change (or
  // the startup opacity restore) touched it: the tap is recorded as the
  // user's intent, but an out-of-window raster must stay hidden.
  function reassertRasterZFor(name) {
    const targets = rasterZTargets()
    let entry = null
    for (const t of targets) {
      if (t.name === name) {
        entry = t
        break
      }
    }
    if (entry === null)
      return
    const level = currentLevel()
    if (level === undefined)
      return
    const tol = Number(toleranceField.text)
    const tolerance = isNaN(tol) ? 5 : tol
    const levels = adjacentSwitch.checked ? neighbourLevels(level) : [level]
    const tols = levels.map(function (value) {
      return value === level ? tolerance : tolForLevel(value, tolerance)
    })
    if (!rasterInWindows(entry.elevation, levels, tols))
      setLayerOpacityRaw(name, 0)
  }

  // ================================================================
  // CLIPPING — ✂ Clip pill with the three desktop Map Cleaning modes
  // (map_cleaning/clipping/clipper_core.py):
  //   Clip All  = clip_all_intersecting (one cutter clips everything
  //               visible that it overlaps)
  //   Isolated  = clip_isolated. Field-friendly wording: KEEP =
  //               desktop "cutter" (stays whole), CUT = desktop
  //               "target" (loses the overlapped area)
  //   Smart     = clip_small_into_large (smaller selected polygons cut
  //               into the larger ones they overlap)
  // The desktop QgsGeometrySnapper step is intentionally skipped —
  // qgis.analysis is not reachable from QML and snapping is cleanup,
  // not correctness.
  // ================================================================

  // Priority order for the tap-to-pick layer lock; mirror of the LGS
  // template polygon layers (singlepart POLYGON, fid PK, UUID field).
  readonly property var clipLayerNames: ['3 - Overlay', '4 - Basemap']
  // mirror of detect_uuid_field (clipper_dockwidget.py)
  readonly property var uuidPatterns: [
    'uuid', 'guid', 'globalid', 'unique_id', 'uniqueid', 'feature_uuid']
  // mirror of MIN_AREA_THRESHOLD (slivers below this are dropped)
  readonly property real minPartArea: 1e-8

  property int clipStep: 0        // 0=off, 1=pick A, 2=pick CUT (isolated), 3=done
  // '' = choosing a mode (clipStep 1), then 'all' | 'isolated' | 'smart'.
  property string clipMode: ''
  property var clipLayer: null    // locked on the first successful hit
  property var keepFeatures: []   // [{id, feature}] — cutter(s) / smart picks
  property var cutFeatures: []    // [{id, feature}] — isolated targets only
  property var clipUndo: null     // one-level undo payload, session-only
  property bool clipAvailable: false
  property string clipResultText: ''
  property string clipCutterWkt: ''    // Clip All: cutter WKT, cached at confirm
  property int clipAllTargetCount: 0   // Clip All: count shown in the dialog

  ExpressionEvaluator {
    id: clipEvaluator
    project: qgisProject
    // Explicit: QField's own instances always set mode, and the template
    // variant would return an expression back as literal text.
    mode: ExpressionEvaluator.ExpressionMode
  }

  // Evaluate a QGIS expression against a layer (+ optional feature).
  // Returns '' on any failure so callers can treat empty as "no result"
  // — never as "empty geometry", which reports as WKT '... EMPTY'.
  function evalExpr(layer, feature, expr) {
    try {
      clipEvaluator.layer = layer
      // The evaluator holds onto its feature, so a layer-only call would
      // otherwise evaluate against whichever feature was set last. Clearing
      // it is best-effort: its own try/catch keeps a rejected null
      // assignment from failing the evaluation itself.
      if (feature !== null && feature !== undefined) {
        clipEvaluator.feature = feature
      } else {
        try {
          clipEvaluator.feature = null
        } catch (error) {}
      }
      clipEvaluator.expressionText = expr
      const raw = clipEvaluator.evaluate()
      if (raw === undefined || raw === null)
        return ''
      const text = String(raw)
      return text === 'undefined' || text === 'null' ? '' : text
    } catch (error) {
      return ''
    }
  }

  // Read a boolean answer from evalExpr. QGIS geometry predicates
  // (intersects, contains, ...) and every comparison / AND / OR operator
  // return TVL ints — QVariant(1) / QVariant(0) — and only plain functions
  // (is_valid, layer_property) return a real bool, so through the
  // evaluator's toString() a truthy answer arrives as '1' OR 'true'. A
  // bare === 'true' on a predicate is ALWAYS false; it silently emptied
  // every v33 box-then-exact-test scan. Pure JS, extracted by
  // tests/reshape_freehand_harness.js.
  function exprTrue(value) {
    return value === 'true' || value === '1'
  }

  function exprFalse(value) {
    return value === 'false' || value === '0'
  }

  function candidateClipLayers() {
    let layers = []
    for (const name of clipLayerNames) {
      const layer = layerByName(name)
      if (layer !== null)
        layers.push(layer)
    }
    return layers
  }

  function initClipping() {
    try {
      clipAvailable = candidateClipLayers().length > 0
    } catch (error) {
      clipAvailable = false
    }
  }

  function clipLayerLabel() {
    try {
      return clipLayer ? String(clipLayer.name) : ''
    } catch (error) {
      return ''
    }
  }

  // ----------------------------------------------------------------
  // Mode lifecycle
  // ----------------------------------------------------------------
  function enterClipMode() {
    try {
      if (!canvas || canvas.width === undefined) {
        toast(qsTr('Clip unavailable — no map canvas'))
        return
      }
      clipCatcher.parent = canvas
      clipCatcher.anchors.fill = canvas
      clipBanner.parent = canvas
      clipBanner.anchors.horizontalCenter = canvas.horizontalCenter
      clipBanner.anchors.top = canvas.top
      clipBanner.anchors.topMargin = 60
      keepFeatures = []
      cutFeatures = []
      clipLayer = null
      clipResultText = ''
      clipMode = ''
      clipCutterWkt = ''
      clipAllTargetCount = 0
      clipStep = 1
      toast(qsTr('Choose clip type'))
    } catch (error) {
      toast(qsTr('Clip unavailable'))
    }
  }

  function chooseClipMode(mode) {
    clipMode = mode
    if (mode === 'all')
      toast(qsTr('Tap ONE cutter polygon'))
    else if (mode === 'smart')
      toast(qsTr('Tap 2 or more polygons'))
    else
      toast(qsTr('Tap the polygons to KEEP'))
  }

  function clipBackToModeSelect() {
    try {
      if (clipLayer !== null)
        clipLayer.removeSelection()
    } catch (error) {}
    keepFeatures = []
    cutFeatures = []
    clipLayer = null
    clipCutterWkt = ''
    clipAllTargetCount = 0
    clipMode = ''
  }

  function exitClipMode() {
    try {
      if (clipLayer !== null)
        clipLayer.removeSelection()
    } catch (error) {}
    clipStep = 0
    clipMode = ''
    keepFeatures = []
    cutFeatures = []
    clipLayer = null
    clipResultText = ''
    clipCutterWkt = ''
    clipAllTargetCount = 0
  }

  // ----------------------------------------------------------------
  // Tap handling / hit-testing
  // ----------------------------------------------------------------
  function clipTapOnUi(pos) {
    // Ignore taps that land on the banner or the pill bar — overlapping
    // TapHandlers may deliver the same tap to the canvas catcher too.
    try {
      const b = clipBanner.mapFromItem(clipCatcher, pos.x, pos.y)
      if (b.x >= 0 && b.y >= 0 &&
          b.x <= clipBanner.width && b.y <= clipBanner.height)
        return true
    } catch (error) {}
    try {
      const o = overlayBar.mapFromItem(clipCatcher, pos.x, pos.y)
      if (o.x >= 0 && o.y >= 0 &&
          o.x <= overlayBar.width && o.y <= overlayBar.height)
        return true
    } catch (error) {}
    try {
      // The Z panel is a non-modal side popup over the canvas edge.
      if (zDialog.visible) {
        const d = mainWindow.contentItem.mapFromItem(
            clipCatcher, pos.x, pos.y)
        if (d.x >= zDialog.x && d.y >= zDialog.y &&
            d.x <= zDialog.x + zDialog.width &&
            d.y <= zDialog.y + zDialog.height)
          return true
      }
    } catch (error) {}
    return false
  }

  function clipTapTolerance() {
    // Finger slop in map units (~12 pt around the tap point).
    try {
      const perPoint = Number(canvas.mapSettings.mapUnitsPerPoint)
      if (!isNaN(perPoint) && perPoint > 0)
        return perPoint * 12
    } catch (error) {}
    try {
      const extent = canvas.mapSettings.extent
      return (extent.xMaximum - extent.xMinimum) / canvas.width * 12
    } catch (error) {}
    return 1
  }

  function findClipHit(pos) {
    // The iterator honours the layer subsetString, so an active Z filter
    // means only VISIBLE polygons are tappable — clip what you see.
    return findHitInLayers(
        clipLayer !== null ? [clipLayer] : candidateClipLayers(), pos)
  }

  // The tap's tolerance box in a layer's own CRS, or null when that
  // cannot be established with confidence — in which case the caller
  // falls back to the expression scan rather than testing a box that
  // might be in the wrong place.
  function tapRectForLayer(layer, pt, tol) {
    try {
      const rect = GeometryUtils.createRectangleFromPoints(
          GeometryUtils.point(pt.x - tol, pt.y - tol),
          GeometryUtils.point(pt.x + tol, pt.y + tol))
      const mapCrs = scaleSettings.destinationCrs
      const layerCrs = layer.crs
      if (mapCrs === undefined || mapCrs === null ||
          layerCrs === undefined || layerCrs === null)
        return null
      if (String(mapCrs.authid) === String(layerCrs.authid))
        return rect
      const out = GeometryUtils.reprojectRectangle(rect, mapCrs, layerCrs)
      return (out === undefined || out === null) ? null : out
    } catch (error) {}
    return null
  }

  function findHitInLayers(layers, pos) {
    const pt = canvas.mapSettings.screenToCoordinate(
        Qt.point(pos.x, pos.y))
    const tol = clipTapTolerance()
    const probe = "intersects($geometry, buffer(geom_from_wkt('POINT(" +
        pt.x + ' ' + pt.y + ")'), " + tol + '))'
    for (const layer of layers) {
      let best = null
      let bestArea = -1
      let iterator = null
      let boxed = false
      try {
        // Every tap used to read the whole layer and evaluate the probe
        // per row (a filter expression derives no spatial index), then
        // ask the expression engine for area() per hit. On a Basemap of
        // any size that is the very first thing the tool does and it is
        // the slowest. The tolerance box goes to the provider's index
        // instead, and the exact test decides among what comes back.
        const rect = tapRectForLayer(layer, pt, tol)
        if (rect !== null) {
          iterator = LayerUtils.createFeatureIteratorFromRectangle(
              layer, rect)
          boxed = true
        }
      } catch (error) {
        iterator = null
        boxed = false
      }
      try {
        if (iterator === null)
          iterator = LayerUtils.createFeatureIteratorFromExpression(
              layer, probe)
        while (iterator.hasNext()) {
          const feature = iterator.next()
          if (boxed && !exprTrue(evalExpr(layer, feature, probe)))
            continue
          // Stacked polygons: the small overlying unit is almost always
          // the intent, so the smallest hit wins.
          const area = Number(evalExpr(layer, feature, 'area($geometry)'))
          if (best === null || (!isNaN(area) &&
                                (bestArea < 0 || area < bestArea))) {
            best = feature
            if (!isNaN(area))
              bestArea = area
          }
        }
      } catch (error) {}
      try {
        if (iterator !== null)
          iterator.close()
      } catch (error) {}
      if (best !== null)
        return { layer: layer, feature: best }
    }
    return null
  }

  function clipPickIndex(list, fid) {
    for (let i = 0; i < list.length; i++) {
      if (list[i].id === fid)
        return i
    }
    return -1
  }

  function toggleClipPick(list, fid, feature) {
    // Copy-on-write so the var property emits its change signal.
    let next = []
    let removed = false
    for (const entry of list) {
      if (entry.id === fid) {
        removed = true
        continue
      }
      next.push(entry)
    }
    if (!removed)
      next.push({ id: fid, feature: feature })
    return next
  }

  function updateClipSelection() {
    if (clipLayer === null)
      return
    let fids = []
    for (const entry of keepFeatures)
      fids.push(entry.id)
    if (clipStep === 2) {
      for (const entry of cutFeatures)
        fids.push(entry.id)
    }
    try {
      if (fids.length === 0) {
        clipLayer.removeSelection()
        return
      }
      LayerUtils.selectFeaturesInLayer(clipLayer, fids)
    } catch (error) {
      try {
        clipLayer.selectByIds(fids)
      } catch (error2) {}
    }
  }

  function handleClipTap(pos) {
    try {
      if (clipStep !== 1 && clipStep !== 2)
        return
      if (clipMode === '')
        return
      if (clipTapOnUi(pos))
        return
      const hit = findClipHit(pos)
      if (hit === null) {
        toast(qsTr('No polygon here'))
        return
      }
      if (clipLayer === null) {
        clipLayer = hit.layer
        toast(qsTr('Using layer: %1').arg(clipLayerLabel()))
      }
      const fid = hit.feature.id
      if (clipMode === 'all') {
        // Single-select: tapping another polygon replaces the cutter,
        // tapping the current one deselects it.
        keepFeatures = clipPickIndex(keepFeatures, fid) !== -1
            ? [] : [{ id: fid, feature: hit.feature }]
      } else if (clipMode === 'smart') {
        keepFeatures = toggleClipPick(keepFeatures, fid, hit.feature)
      } else if (clipStep === 1) {
        if (clipPickIndex(cutFeatures, fid) !== -1) {
          toast(qsTr('Already marked CUT'))
          return
        }
        keepFeatures = toggleClipPick(keepFeatures, fid, hit.feature)
      } else {
        if (clipPickIndex(keepFeatures, fid) !== -1) {
          toast(qsTr('Already marked KEEP'))
          return
        }
        cutFeatures = toggleClipPick(cutFeatures, fid, hit.feature)
      }
      updateClipSelection()
    } catch (error) {}
  }

  // ----------------------------------------------------------------
  // Attribute helpers (mirror of copy_attributes_without_fid)
  // ----------------------------------------------------------------
  function attributeNames(layer, feature) {
    // JSON round-trip through the expression engine — avoids relying on
    // the QgsFields gadget surface.
    try {
      const raw = evalExpr(layer, feature, 'to_json(map_akeys(attributes()))')
      const names = JSON.parse(raw)
      if (Array.isArray(names) && names.length > 0)
        return names
    } catch (error) {}
    try {
      const names = feature.fields.names
      if (names !== undefined && names.length > 0)
        return names
    } catch (error) {}
    return []
  }

  function detectUuidField(names) {
    for (const name of names) {
      const lower = String(name).toLowerCase()
      for (const pattern of uuidPatterns) {
        if (lower.indexOf(pattern) !== -1)
          return name
      }
    }
    return null
  }

  function makeClipUuid(layer) {
    const value = evalExpr(layer, null, "uuid('WithoutBraces')")
    if (value.length === 36)
      return value
    // Fallback: version-4 shape from Math.random (no crypto in QML JS).
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,
        function(c) {
          const r = Math.random() * 16 | 0
          return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
        })
  }

  // Last featureNulls() run: how many fields looked ambiguous and how many
  // turned out to be genuinely NULL. Surfaced in the Reverse toast.
  property int lastProbedFields: 0
  property int lastBlankFields: 0

  function valueIsAmbiguous(value) {
    // Could this JS value be a NULL that lost its identity crossing the
    // QML bridge?
    //
    // QGIS stores an unset attribute as a TYPED null variant —
    // QVariant(double) on a REAL field — and the bridge converts that to
    // the JS number 0 (false on a boolean). A NULL string arrives as ''
    // and isEmptyValue already catches it, so only these collapse into
    // something that looks like real data. Everything else IS real data
    // and must be copied verbatim: on FieldNotebook, Dip = 0 is
    // horizontal and Strike_RHR = 0 is north.
    if (typeof value === 'number')
      return value === 0 || isNaN(value)
    return value === false
  }

  function featureNulls(layer, feature, names) {
    // -> {fieldName: true} for the attributes that are genuinely NULL.
    //
    // Asked of the EXPRESSION ENGINE one field at a time, because nothing
    // else can be trusted. feature.attribute() cannot distinguish a NULL
    // REAL from 0 (see valueIsAmbiguous), and to_json(attributes()) is no
    // better: it serialises a typed null through the same coercion, so a
    // NULL Width_cm comes back as 0 while NULL text fields come back as
    // null — the JSON looks healthy and is silently wrong exactly where
    // it matters. QGIS expression IS NULL uses the engine's own null
    // test, which sees the typed null for what it is.
    //
    // Cost is bounded: only ambiguous fields are probed, and layers carry
    // a handful of numeric columns (Linework 6, Overlay 4).
    let nulls = ({})
    let probed = 0
    try {
      const fields = (names !== undefined && names !== null)
          ? names : attributeNames(layer, feature)
      for (const name of fields) {
        let value = null
        try {
          value = feature.attribute(name)
        } catch (error) {
          continue
        }
        if (!valueIsAmbiguous(value))
          continue
        probed++
        // Stringified result: 'true' on any sane build, '1' if a bool
        // ever arrives as an int.
        const verdict = evalExpr(layer, feature, '"' + name + '" IS NULL')
        if (exprTrue(verdict))
          nulls[name] = true
      }
    } catch (error) {}
    // Reported by the Reverse toast so the guard is visible on device —
    // otherwise every failure mode here is silent.
    lastProbedFields = probed
    lastBlankFields = Object.keys(nulls).length
    return nulls
  }

  function copyClipAttributes(target, source, names, uuidField, freshUuid,
                              layer) {
    // fid/id/ogc_fid stay null so the provider assigns them (GeoPackage
    // UNIQUE PK). Everything else is copied — including Elevation, which
    // deliberately overwrites the auto-stamp default so new pieces keep
    // the source level and stay visible under an active Z filter.
    const nulls = featureNulls(layer, source, names)
    for (const name of names) {
      const lower = String(name).toLowerCase()
      if (lower === 'fid' || lower === 'id' || lower === 'ogc_fid')
        continue
      try {
        if (uuidField !== null && name === uuidField) {
          target.setAttribute(name, freshUuid)
        } else {
          // NULL source values are SKIPPED, not written: a null variant
          // pushed through the QML bridge lands as 0 on numeric fields
          // (0 width, 0 modal % — false data on every recreate/undo),
          // while an untouched attribute on the fresh feature stays
          // NULL (or keeps its default-value stamp). featureNulls is
          // the authority — isEmptyValue cannot see a NULL number,
          // which reaches JS already coerced to 0.
          if (nulls[name] === true)
            continue
          const value = source.attribute(name)
          if (!isEmptyValue(value))
            target.setAttribute(name, value)
        }
      } catch (error) {}
    }
    return target
  }

  // ----------------------------------------------------------------
  // WKT plumbing (results of expression-engine geometry math)
  // ----------------------------------------------------------------
  function wktTopLevelGroups(body) {
    // Depth-0 parenthesis groups: MULTIPOLYGON body -> one per polygon.
    let groups = []
    let depth = 0
    let start = -1
    for (let i = 0; i < body.length; i++) {
      const ch = body.charAt(i)
      if (ch === '(') {
        if (depth === 0)
          start = i
        depth++
      } else if (ch === ')') {
        depth--
        if (depth === 0 && start !== -1) {
          groups.push(body.substring(start, i + 1))
          start = -1
        }
      }
    }
    return groups
  }

  function wktTopLevelMembers(body) {
    // Depth-0 comma split: GEOMETRYCOLLECTION body -> member geometries.
    let members = []
    let depth = 0
    let start = 0
    for (let i = 0; i < body.length; i++) {
      const ch = body.charAt(i)
      if (ch === '(')
        depth++
      else if (ch === ')')
        depth--
      else if (ch === ',' && depth === 0) {
        members.push(body.substring(start, i).trim())
        start = i + 1
      }
    }
    const tail = body.substring(start).trim()
    if (tail !== '')
      members.push(tail)
    return members
  }

  function splitMultiPolygonWkt(wkt) {
    // 'POLYGON (…)' -> [itself]; 'MULTIPOLYGON (…)' -> one POLYGON per
    // part; 'GEOMETRYCOLLECTION (…)' -> recurse keeping polygonal
    // members (mirror of extract_polygon_parts_from_geometry).
    let parts = []
    const text = String(wkt).trim()
    const open = text.indexOf('(')
    if (open === -1)
      return parts
    const kind = text.substring(0, open).trim().toUpperCase()
    const body = text.substring(open + 1, text.lastIndexOf(')'))
    if (kind.indexOf('MULTIPOLYGON') === 0) {
      for (const group of wktTopLevelGroups(body))
        parts.push('POLYGON ' + group)
    } else if (kind.indexOf('GEOMETRYCOLLECTION') === 0) {
      for (const member of wktTopLevelMembers(body))
        parts = parts.concat(splitMultiPolygonWkt(member))
    } else if (kind.indexOf('POLYGON') === 0) {
      parts.push(text)
    }
    return parts
  }

  // ----------------------------------------------------------------
  // Clip engine (mirror of clip_isolated, clipper_core.py:584)
  // ----------------------------------------------------------------
  function buildCutterUnionWkt() {
    // QgsGeometry.unaryUnion equivalent: fold union() over the KEEP
    // geometries in the expression engine, make_valid the result.
    try {
      let expr = null
      for (const entry of keepFeatures) {
        const wkt = evalExpr(clipLayer, entry.feature,
                             'geom_to_wkt($geometry)')
        if (wkt === '')
          continue
        const geomExpr = "geom_from_wkt('" + wkt + "')"
        expr = expr === null
            ? geomExpr : 'union(' + expr + ', ' + geomExpr + ')'
      }
      if (expr === null)
        return ''
      return evalExpr(clipLayer, keepFeatures[0].feature,
                      'geom_to_wkt(make_valid(' + expr + '))')
    } catch (error) {
      return ''
    }
  }

  function clipDifferenceWkt(feature, unionWkt) {
    // buffer(0) normalises make_valid GeometryCollections into pure
    // polygons and drops line/point debris; if it misbehaves fall back
    // to the raw difference and let the WKT splitter cope.
    const core = 'make_valid(difference(make_valid($geometry), ' +
        "geom_from_wkt('" + unionWkt + "')))"
    let wkt = evalExpr(clipLayer, feature,
                       'geom_to_wkt(buffer(' + core + ', 0))')
    if (wkt === '')
      wkt = evalExpr(clipLayer, feature, 'geom_to_wkt(' + core + ')')
    return wkt
  }

  function applyClipEdits(layer, newFeatures, deleteIds) {
    // One edit session, adds strictly before deletes (data-safe order),
    // and BOTH halves verified. Two ways this used to lose data:
    //
    //  - LayerUtils.addFeature returns a bool for exactly this reason (an
    //    addition-locked layer, a constraint, a wkb-type mismatch) and it
    //    was discarded. The deletes then ran and committed anyway, turning
    //    "replace this polygon" into "delete this polygon". Nothing is
    //    deleted now unless every add landed.
    //  - The delete fallback called layer.selectByIds([fid]) and then
    //    deleteSelectedFeatures(). QML cannot convert a JS number to a
    //    QgsFeatureId -- the documented reason
    //    LayerUtils.selectFeaturesInLayer exists -- so selectByIds was a
    //    silent no-op inside its own try and deleteSelectedFeatures then
    //    deleted WHATEVER WAS SELECTED: during a clip the user's own
    //    KEEP/CUT picks, during a merge the merge picks. There is no
    //    fallback now at all (see the delete loop): a delete that fails
    //    rolls the whole session back rather than leaving the original
    //    and its replacements both on the map.
    //
    // A layer already being edited belongs to someone else (a tracking
    // session, another tool): committing would take their half-finished
    // work with ours and rolling back would discard it. Refuse instead.
    // isEditable is not reachable from QML; the expression engine
    // answers, and an unreadable answer is treated as "not editing".
    try {
      const editable = evalExpr(layer, null,
                                "layer_property(@layer, 'is_editable')")
      if (exprTrue(editable)) {
        toast(qsTr('%1 has unsaved edits from another tool — save or discard them first')
              .arg(String(layer.name)))
        return false
      }
    } catch (error) {}
    let ok = false
    try {
      layer.startEditing()
      for (const feature of newFeatures) {
        let landed = false
        try {
          landed = LayerUtils.addFeature(layer, feature) === true
        } catch (error) {
          landed = false
        }
        if (!landed) {
          try {
            layer.rollBack()
          } catch (error2) {}
          return false
        }
      }
      for (const fid of deleteIds) {
        // No second route. deleteFeature returns false only when the
        // layer is not editable, the fid is unknown, or it is already
        // deleted — and in every one of those a selection-based delete
        // fails too, so a fallback could only ever add risk (the previous
        // one deleted whatever happened to be selected). A failed delete
        // is a failed edit: roll the whole session back.
        let deleted = false
        try {
          deleted = layer.deleteFeature(fid) === true
        } catch (error) {}
        if (!deleted) {
          try {
            layer.rollBack()
          } catch (error2) {}
          return false
        }
      }
      ok = layer.commitChanges()
      if (!ok)
        layer.rollBack()
    } catch (error) {
      try {
        layer.rollBack()
      } catch (error2) {}
      ok = false
    }
    return ok
  }

  // Single quotes doubled, so a UUID that carries one cannot end the
  // literal and change the expression it sits in. detectUuidField
  // matches any field whose name merely CONTAINS uuid/guid/unique_id, on
  // any polygon layer the user makes active, so the value reaching these
  // expressions is not something the template controls.
  function sqlLiteral(value) {
    return String(value).split("'").join("''")
  }

  function collectFidsByExpression(layer, expr) {
    let fids = []
    let iterator = null
    try {
      iterator = LayerUtils.createFeatureIteratorFromExpression(layer, expr)
      while (iterator.hasNext())
        fids.push(iterator.next().id)
    } catch (error) {}
    try {
      if (iterator !== null)
        iterator.close()
    } catch (error) {}
    return fids
  }

  function executeClip() {
    if (clipMode === 'all')
      executeClipAll()
    else if (clipMode === 'smart')
      executeClipSmart()
    else
      executeClipIsolated()
  }

  // Split a difference result into single-polygon parts and drop
  // slivers below minPartArea (parts whose area check fails are kept).
  function keptPartsFromWkt(layer, diffWkt) {
    let parts = []
    if (diffWkt !== '' && diffWkt.toUpperCase().indexOf('EMPTY') === -1)
      parts = splitMultiPolygonWkt(diffWkt)
    let kept = []
    for (const part of parts) {
      const area = Number(evalExpr(layer, null,
          "area(geom_from_wkt('" + part + "'))"))
      // Keep the part when the area check itself fails.
      if (isNaN(area) || area > minPartArea)
        kept.push(part)
    }
    return kept
  }

  // Difference between two bare WKTs (no feature context) — same
  // buffer(0) normalisation + raw fallback as clipDifferenceWkt.
  function clipDifferenceWktPair(sourceWkt, cutterWkt) {
    const core = "make_valid(difference(make_valid(geom_from_wkt('" +
        sourceWkt + "')), geom_from_wkt('" + cutterWkt + "')))"
    let wkt = evalExpr(clipLayer, null,
                       'geom_to_wkt(buffer(' + core + ', 0))')
    if (wkt === '')
      wkt = evalExpr(clipLayer, null, 'geom_to_wkt(' + core + ')')
    return wkt
  }

  // Shared tail for all three modes: commit (adds before deletes),
  // read-back verify, arm the one-level undo, report and finish.
  function finalizeClip(layer, names, uuidField, newFeatures, newUuids,
                        deleteIds, undoDeleted, message) {
    if (!applyClipEdits(layer, newFeatures, deleteIds)) {
      toast(qsTr('Clip failed — no changes made'))
      clipResultText = ''
      return false
    }
    // Read-back verification + fids of the new pieces (for undo).
    let addedFids = []
    if (uuidField !== null && newUuids.length > 0) {
      const inList = "'" + newUuids.join("','") + "'"
      addedFids = collectFidsByExpression(layer,
          '"' + uuidField + '" IN (' + inList + ')')
      if (addedFids.length !== newFeatures.length)
        toast(qsTr('Warning: %1 of %2 new pieces verified')
              .arg(addedFids.length).arg(newFeatures.length))
    }
    clipUndo = uuidField === null ? null : {
      layer: layer,
      layerName: clipLayerLabel(),
      deleted: undoDeleted,
      names: names,
      uuidField: uuidField,
      newUuids: newUuids,
      addedFids: addedFids
    }
    try {
      layer.removeSelection()
      layer.triggerRepaint()
      iface.mapCanvas().refresh()
    } catch (error) {}
    clipResultText = message
    toast(message)
    clipStep = 3
    return true
  }

  function executeClipIsolated() {
    try {
      const layer = clipLayer
      if (layer === null || keepFeatures.length === 0 ||
          cutFeatures.length === 0)
        return
      clipResultText = qsTr('Clipping…')
      const names = attributeNames(layer, cutFeatures[0].feature)
      const uuidField = detectUuidField(names)
      const unionWkt = buildCutterUnionWkt()
      if (unionWkt === '') {
        toast(qsTr('Clip failed — could not merge the KEEP polygons'))
        clipResultText = ''
        return
      }
      let deleteIds = []
      let undoDeleted = []      // [{wkt, feature}] captured pre-edit
      let newFeatures = []
      let newUuids = []
      let clippedCount = 0
      let removedCount = 0
      let pieceCount = 0
      let untouchedCount = 0
      let failedCount = 0
      for (const entry of cutFeatures) {
        const feature = entry.feature
        const touches = evalExpr(layer, feature,
            "intersects($geometry, geom_from_wkt('" + unionWkt + "'))")
        if (!exprTrue(touches)) {
          // Non-intersecting targets stay completely untouched
          // (fid and UUID stable — matches desktop).
          untouchedCount++
          continue
        }
        const sourceWkt = evalExpr(layer, feature,
                                   'geom_to_wkt($geometry)')
        const diffWkt = clipDifferenceWkt(feature, unionWkt)
        if (diffWkt === '' && sourceWkt !== '') {
          // Evaluation failed — never treat a failure as "fully
          // covered": leave the feature alone rather than delete it.
          failedCount++
          continue
        }
        const kept = keptPartsFromWkt(layer, diffWkt)
        deleteIds.push(entry.id)
        undoDeleted.push({ wkt: sourceWkt, feature: feature })
        if (kept.length === 0) {
          removedCount++
          continue
        }
        clippedCount++
        for (const part of kept) {
          const geometry = GeometryUtils.createGeometryFromWkt(part)
          let created = FeatureUtils.createFeature(layer, geometry)
          const freshUuid = makeClipUuid(layer)
          copyClipAttributes(created, feature, names, uuidField,
                             freshUuid, layer)
          newFeatures.push(created)
          newUuids.push(freshUuid)
          pieceCount++
        }
      }
      if (deleteIds.length === 0) {
        toast(failedCount > 0
            ? qsTr('Clip failed — geometry error')
            : qsTr('Nothing to clip — the CUT polygons do not touch the KEEP polygons'))
        clipResultText = ''
        return
      }
      let message = qsTr('Cut %1 polygon(s) → %2 piece(s)')
          .arg(clippedCount + removedCount).arg(pieceCount)
      if (removedCount > 0)
        message += qsTr(' — %1 removed entirely').arg(removedCount)
      if (untouchedCount > 0)
        message += qsTr(' — %1 untouched').arg(untouchedCount)
      if (failedCount > 0)
        message += qsTr(' — %1 skipped (geometry error)').arg(failedCount)
      finalizeClip(layer, names, uuidField, newFeatures, newUuids,
                   deleteIds, undoDeleted, message)
    } catch (error) {
      toast(qsTr('Clip failed'))
      clipResultText = ''
    }
  }

  // ----------------------------------------------------------------
  // Clip All — port of the desktop clip_all_intersecting
  // ----------------------------------------------------------------
  // Count the polygons the cutter overlaps and cache the cutter WKT —
  // called before the confirm dialog so it can show the number.
  function countClipAllTargets() {
    try {
      if (clipLayer === null || keepFeatures.length !== 1) {
        clipAllTargetCount = 0
        return 0
      }
      const wkt = evalExpr(clipLayer, keepFeatures[0].feature,
                           'geom_to_wkt(make_valid($geometry))')
      if (wkt === '') {
        clipAllTargetCount = 0
        return 0
      }
      clipCutterWkt = wkt
      const fids = collectFidsByExpression(clipLayer,
          "intersects($geometry, geom_from_wkt('" + wkt + "'))")
      let count = 0
      for (const fid of fids) {
        if (fid !== keepFeatures[0].id)
          count++
      }
      clipAllTargetCount = count
      return count
    } catch (error) {
      clipAllTargetCount = 0
      return 0
    }
  }

  function executeClipAll() {
    try {
      const layer = clipLayer
      if (layer === null || keepFeatures.length !== 1)
        return
      clipResultText = qsTr('Clipping…')
      const cutterId = keepFeatures[0].id
      const cutterWkt = clipCutterWkt !== ''
          ? clipCutterWkt
          : evalExpr(layer, keepFeatures[0].feature,
                     'geom_to_wkt(make_valid($geometry))')
      if (cutterWkt === '') {
        toast(qsTr('Clip failed — could not read the cutter polygon'))
        clipResultText = ''
        return
      }
      // Collect every intersecting feature up front and close the
      // iterator before any editing. The iterator honours the
      // subsetString, so an active Z filter limits the clip to VISIBLE
      // polygons — clip what you see (deliberate desktop divergence).
      let targets = []
      let iterator = null
      try {
        iterator = LayerUtils.createFeatureIteratorFromExpression(layer,
            "intersects($geometry, geom_from_wkt('" + cutterWkt + "'))")
        while (iterator.hasNext()) {
          const feature = iterator.next()
          if (feature.id !== cutterId)
            targets.push(feature)
        }
      } catch (error) {}
      try {
        if (iterator !== null)
          iterator.close()
      } catch (error) {}
      if (targets.length === 0) {
        toast(qsTr('Nothing overlaps the cutter'))
        clipResultText = ''
        return
      }
      const names = attributeNames(layer, targets[0])
      const uuidField = detectUuidField(names)
      let deleteIds = []
      let undoDeleted = []      // [{wkt, feature}] captured pre-edit
      let newFeatures = []
      let newUuids = []
      let clippedCount = 0
      let removedCount = 0
      let pieceCount = 0
      let failedCount = 0
      for (const feature of targets) {
        const sourceWkt = evalExpr(layer, feature,
                                   'geom_to_wkt($geometry)')
        const diffWkt = clipDifferenceWkt(feature, cutterWkt)
        if (diffWkt === '' && sourceWkt !== '') {
          // Evaluation failed — never treat a failure as "fully
          // covered": leave the feature alone rather than delete it.
          failedCount++
          continue
        }
        const kept = keptPartsFromWkt(layer, diffWkt)
        deleteIds.push(feature.id)
        undoDeleted.push({ wkt: sourceWkt, feature: feature })
        if (kept.length === 0) {
          removedCount++
          continue
        }
        clippedCount++
        for (const part of kept) {
          const geometry = GeometryUtils.createGeometryFromWkt(part)
          let created = FeatureUtils.createFeature(layer, geometry)
          const freshUuid = makeClipUuid(layer)
          copyClipAttributes(created, feature, names, uuidField,
                             freshUuid, layer)
          newFeatures.push(created)
          newUuids.push(freshUuid)
          pieceCount++
        }
      }
      if (deleteIds.length === 0) {
        toast(failedCount > 0
            ? qsTr('Clip failed — geometry error')
            : qsTr('Nothing overlaps the cutter'))
        clipResultText = ''
        return
      }
      let message = qsTr('Clip All: cut %1 polygon(s) → %2 piece(s)')
          .arg(clippedCount + removedCount).arg(pieceCount)
      if (removedCount > 0)
        message += qsTr(' — %1 removed entirely').arg(removedCount)
      if (failedCount > 0)
        message += qsTr(' — %1 skipped (geometry error)').arg(failedCount)
      finalizeClip(layer, names, uuidField, newFeatures, newUuids,
                   deleteIds, undoDeleted, message)
    } catch (error) {
      toast(qsTr('Clip failed'))
      clipResultText = ''
    }
  }

  // ----------------------------------------------------------------
  // Smart Clip — port of the desktop clip_small_into_large
  // ----------------------------------------------------------------
  // Pure JS (Node-testable — no evalExpr/QML inside): given
  // [{id, area}], sort ascending by area and pair each polygon with
  // every LARGER one, skipping pairs whose areas are within 1%
  // (small > large * 0.99 — the desktop predicate). Returns
  // [{smallId, largeId}] in processing order, smallest cutter first.
  function smartClipPairs(items) {
    let sorted = items.slice().sort(function(a, b) {
      return a.area - b.area
    })
    let pairs = []
    for (let i = 0; i < sorted.length; i++) {
      for (let j = i + 1; j < sorted.length; j++) {
        if (sorted[i].area > sorted[j].area * 0.99)
          continue
        pairs.push({ smallId: sorted[i].id, largeId: sorted[j].id })
      }
    }
    return pairs
  }

  function executeClipSmart() {
    try {
      const layer = clipLayer
      if (layer === null || keepFeatures.length < 2)
        return
      clipResultText = qsTr('Clipping…')
      // Read geometry + area for every pick; count unreadable ones.
      let items = []
      let itemById = {}
      let failedCount = 0
      for (const entry of keepFeatures) {
        const wkt = evalExpr(layer, entry.feature,
                             'geom_to_wkt($geometry)')
        const area = Number(evalExpr(layer, entry.feature,
                                     'area($geometry)'))
        if (wkt === '' || isNaN(area)) {
          failedCount++
          continue
        }
        items.push({ id: entry.id, area: area })
        itemById[String(entry.id)] = {
          id: entry.id, feature: entry.feature, wkt: wkt, area: area
        }
      }
      if (items.length < 2) {
        toast(qsTr('Clip failed — could not read the selected polygons'))
        clipResultText = ''
        return
      }
      const pairs = smartClipPairs(items)
      // Parts of each large polygon accumulate as successive smaller
      // polygons cut it; the cutter is always the small polygon's
      // ORIGINAL geometry, and slivers are dropped only at final
      // creation — both desktop parity.
      let modifiedParts = {}
      for (const pair of pairs) {
        const small = itemById[String(pair.smallId)]
        const key = String(pair.largeId)
        const currentParts = modifiedParts.hasOwnProperty(key)
            ? modifiedParts[key] : [itemById[key].wkt]
        let newParts = []
        let anyIntersection = false
        for (const part of currentParts) {
          const touches = evalExpr(layer, null,
              "intersects(geom_from_wkt('" + part + "'), " +
              "geom_from_wkt('" + small.wkt + "'))")
          if (!exprTrue(touches)) {
            newParts.push(part)
            continue
          }
          const diffWkt = clipDifferenceWktPair(part, small.wkt)
          if (diffWkt === '') {
            // Evaluation failed — keep the part rather than lose it.
            newParts.push(part)
            failedCount++
            continue
          }
          anyIntersection = true
          if (diffWkt.toUpperCase().indexOf('EMPTY') !== -1)
            continue
          newParts = newParts.concat(splitMultiPolygonWkt(diffWkt))
        }
        if (anyIntersection)
          modifiedParts[key] = newParts
      }
      const modifiedIds = Object.keys(modifiedParts)
      if (modifiedIds.length === 0) {
        toast(qsTr('No overlaps — the smaller polygons do not touch the larger ones'))
        clipResultText = ''
        return
      }
      const names = attributeNames(layer, keepFeatures[0].feature)
      const uuidField = detectUuidField(names)
      let deleteIds = []
      let undoDeleted = []      // [{wkt, feature}] captured pre-edit
      let newFeatures = []
      let newUuids = []
      let clippedCount = 0
      let removedCount = 0
      let pieceCount = 0
      for (const key of modifiedIds) {
        const item = itemById[key]
        let kept = []
        for (const part of modifiedParts[key]) {
          const area = Number(evalExpr(layer, null,
              "area(geom_from_wkt('" + part + "'))"))
          // Keep the part when the area check itself fails.
          if (isNaN(area) || area > minPartArea)
            kept.push(part)
        }
        deleteIds.push(item.id)
        undoDeleted.push({ wkt: item.wkt, feature: item.feature })
        if (kept.length === 0) {
          removedCount++
          continue
        }
        clippedCount++
        // Desktop rule: fresh UUIDs only when the polygon split into
        // more than one piece; a single surviving piece keeps its
        // original UUID. newUuids records whatever UUID was actually
        // stamped so the read-back and undo resolve to the new pieces
        // (the original is deleted in the same commit, so a preserved
        // UUID is unique again afterwards).
        const splitApart = kept.length > 1
        for (const part of kept) {
          const geometry = GeometryUtils.createGeometryFromWkt(part)
          let created = FeatureUtils.createFeature(layer, geometry)
          let stampedUuid = ''
          if (splitApart) {
            stampedUuid = makeClipUuid(layer)
            copyClipAttributes(created, item.feature, names, uuidField,
                               stampedUuid, layer)
          } else {
            copyClipAttributes(created, item.feature, names, null, '',
                               layer)
            if (uuidField !== null) {
              try {
                const original = item.feature.attribute(uuidField)
                if (original !== undefined && original !== null)
                  stampedUuid = String(original)
              } catch (error) {}
            }
          }
          newFeatures.push(created)
          if (stampedUuid !== '')
            newUuids.push(stampedUuid)
          pieceCount++
        }
      }
      let message = qsTr('Smart clip: %1 polygon(s) reshaped → %2 piece(s)')
          .arg(clippedCount + removedCount).arg(pieceCount)
      if (removedCount > 0)
        message += qsTr(' — %1 removed entirely').arg(removedCount)
      if (failedCount > 0)
        message += qsTr(' — %1 skipped (geometry error)').arg(failedCount)
      finalizeClip(layer, names, uuidField, newFeatures, newUuids,
                   deleteIds, undoDeleted, message)
    } catch (error) {
      toast(qsTr('Clip failed'))
      clipResultText = ''
    }
  }

  // ----------------------------------------------------------------
  // Undo (one level, session-only — never persisted)
  // ----------------------------------------------------------------
  function undoLastClip() {
    const undo = clipUndo
    if (undo === null || undo === undefined)
      return
    try {
      let layer = undo.layer
      try {
        if (layer === null || layer.name === undefined)
          layer = layerByName(undo.layerName)
      } catch (error) {
        layer = layerByName(undo.layerName)
      }
      if (layer === null) {
        toast(qsTr('Undo failed — layer not found'))
        return
      }
      // The added pieces, looked up fresh by UUID (fids survive commits
      // but a resync could renumber them).
      let doomed = []
      if (undo.newUuids.length > 0) {
        const inList = "'" + undo.newUuids.join("','") + "'"
        doomed = collectFidsByExpression(layer,
            '"' + undo.uuidField + '" IN (' + inList + ')')
        if (doomed.length === 0)
          doomed = undo.addedFids
      }
      // Rebuild the deleted originals, keeping their original UUIDs —
      // UUID is the stable identity, fids are provider-assigned anew.
      let restored = []
      for (const gone of undo.deleted) {
        const geometry = GeometryUtils.createGeometryFromWkt(gone.wkt)
        let created = FeatureUtils.createFeature(layer, geometry)
        copyClipAttributes(created, gone.feature, undo.names, null, '',
                           layer)
        restored.push(created)
      }
      if (!applyClipEdits(layer, restored, doomed)) {
        toast(qsTr('Undo failed — no changes made'))
        return
      }
      try {
        layer.triggerRepaint()
        iface.mapCanvas().refresh()
      } catch (error) {}
      toast(qsTr('Clip undone'))
      clipUndo = null
    } catch (error) {
      toast(qsTr('Undo failed'))
    }
  }

  // ----------------------------------------------------------------
  // Clip UI: tap catcher + instruction banner + confirm dialog
  // ----------------------------------------------------------------
  Item {
    id: clipCatcher
    visible: (plugin.clipStep === 1 && plugin.clipMode !== '') ||
             plugin.clipStep === 2
    z: 1

    TapHandler {
      // Default DragThreshold gesture policy: passive grab, so pan and
      // pinch on the canvas underneath keep working — only clean taps
      // land here.
      onSingleTapped: function(eventPoint, button) {
        plugin.handleClipTap(eventPoint.position)
      }
    }
  }

  Rectangle {
    id: clipBanner
    visible: plugin.clipStep > 0
    z: 3
    radius: 8
    color: '#CC000000'
    width: Math.min((parent !== null ? parent.width : 444) - 24, 420)
    height: clipBannerColumn.height + 24

    Column {
      id: clipBannerColumn
      anchors.top: parent.top
      anchors.topMargin: 12
      anchors.horizontalCenter: parent.horizontalCenter
      width: parent.width - 24
      spacing: 8

      Text {
        width: parent.width
        font.pixelSize: 15
        font.bold: true
        color: 'white'
        text: plugin.clipStep === 1
            ? (plugin.clipMode === '' ? qsTr('Clip — choose type')
              : plugin.clipMode === 'all' ? qsTr('Clip All — pick the cutter')
              : plugin.clipMode === 'smart' ? qsTr('Smart Clip — pick polygons')
                                            : qsTr('Clip — step 1 of 2'))
            : plugin.clipStep === 2 ? qsTr('Clip — step 2 of 2')
                                    : qsTr('Clip done')
      }

      Text {
        width: parent.width
        wrapMode: Text.WordWrap
        font.pixelSize: 14
        color: 'white'
        text: plugin.clipStep === 1
            ? (plugin.clipMode === ''
              ? qsTr('Clip All: one polygon cuts everything under it. Isolated: pick KEEP then CUT. Smart: smaller polygons cut into larger ones.')
              : plugin.clipMode === 'all'
                ? qsTr('Tap ONE cutter polygon — every polygon it overlaps loses the overlap')
                : plugin.clipMode === 'smart'
                  ? qsTr('Tap 2+ polygons — each smaller one is cut out of the larger ones it overlaps')
                  : qsTr('Tap the polygon(s) to KEEP — they stay whole'))
            : plugin.clipStep === 2
              ? qsTr('Tap the polygon(s) to CUT — the overlap is removed')
              : plugin.clipResultText
      }

      Text {
        visible: (plugin.clipStep === 1 && plugin.clipMode !== '') ||
                 plugin.clipStep === 2
        width: parent.width
        wrapMode: Text.WordWrap
        font.pixelSize: 12
        color: '#CCFFFFFF'
        text: {
          const count = plugin.clipStep === 2
              ? plugin.cutFeatures.length : plugin.keepFeatures.length
          let line = qsTr('%1 selected — tap again to unselect').arg(count)
          if (plugin.clipLayer !== null)
            line += ' · ' + plugin.clipLayerLabel()
          return line
        }
      }

      Flow {
        width: parent.width
        spacing: 8

        Button {
          id: clipModeAllButton
          visible: plugin.clipStep === 1 && plugin.clipMode === ''
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Clip All')
            color: 'white'
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: Theme.mainColor
            border.color: Theme.mainColor
            border.width: 1
            radius: 4
          }
          onClicked: plugin.chooseClipMode('all')
        }

        Button {
          id: clipModeIsolatedButton
          visible: plugin.clipStep === 1 && plugin.clipMode === ''
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Isolated')
            color: 'white'
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: Theme.mainColor
            border.color: Theme.mainColor
            border.width: 1
            radius: 4
          }
          onClicked: plugin.chooseClipMode('isolated')
        }

        Button {
          id: clipModeSmartButton
          visible: plugin.clipStep === 1 && plugin.clipMode === ''
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Smart')
            color: 'white'
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: Theme.mainColor
            border.color: Theme.mainColor
            border.width: 1
            radius: 4
          }
          onClicked: plugin.chooseClipMode('smart')
        }

        Button {
          id: clipCancelButton
          visible: plugin.clipStep === 1 || plugin.clipStep === 2
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Cancel')
            color: 'white'
            font.pixelSize: 14
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: 'transparent'
            border.color: '#AAFFFFFF'
            border.width: 1
            radius: 4
          }
          onClicked: plugin.exitClipMode()
        }

        Button {
          id: clipBackButton
          visible: plugin.clipStep === 2 ||
                   (plugin.clipStep === 1 && plugin.clipMode !== '')
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('◂ Back')
            color: 'white'
            font.pixelSize: 14
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: 'transparent'
            border.color: '#AAFFFFFF'
            border.width: 1
            radius: 4
          }
          onClicked: {
            if (plugin.clipStep === 2) {
              plugin.clipStep = 1
              plugin.updateClipSelection()
            } else {
              plugin.clipBackToModeSelect()
            }
          }
        }

        Button {
          id: clipNextButton
          visible: plugin.clipStep === 1 && plugin.clipMode === 'isolated'
          enabled: plugin.keepFeatures.length > 0
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Next ▸')
            color: clipNextButton.enabled ? 'white' : '#66FFFFFF'
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: clipNextButton.enabled ? Theme.mainColor : 'transparent'
            border.color: clipNextButton.enabled
                ? Theme.mainColor : '#66FFFFFF'
            border.width: 1
            radius: 4
          }
          onClicked: {
            plugin.clipStep = 2
            plugin.updateClipSelection()
            plugin.toast(qsTr('Tap the polygons to CUT'))
          }
        }

        Button {
          id: clipExecuteButton
          visible: plugin.clipStep === 2 ||
                   (plugin.clipStep === 1 &&
                    (plugin.clipMode === 'all' || plugin.clipMode === 'smart'))
          enabled: plugin.clipMode === 'all'
              ? plugin.keepFeatures.length === 1
              : plugin.clipMode === 'smart'
                ? plugin.keepFeatures.length >= 2
                : plugin.cutFeatures.length > 0
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Clip ✓')
            color: clipExecuteButton.enabled ? 'white' : '#66FFFFFF'
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: clipExecuteButton.enabled
                ? Theme.mainColor : 'transparent'
            border.color: clipExecuteButton.enabled
                ? Theme.mainColor : '#66FFFFFF'
            border.width: 1
            radius: 4
          }
          onClicked: {
            if (plugin.clipMode === 'all') {
              // Count first so the dialog can show how many polygons
              // are about to be cut; refuse a no-op clip outright.
              if (plugin.countClipAllTargets() === 0) {
                plugin.toast(qsTr('Nothing overlaps the cutter'))
                return
              }
            }
            clipConfirmDialog.open()
          }
        }

        Button {
          id: clipUndoButton
          visible: plugin.clipStep === 3 ||
                   (plugin.clipStep === 1 && plugin.clipMode === '' &&
                    plugin.clipUndo !== null)
          enabled: plugin.clipUndo !== null
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Undo last clip')
            color: clipUndoButton.enabled ? 'white' : '#66FFFFFF'
            font.pixelSize: 14
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: 'transparent'
            border.color: clipUndoButton.enabled ? '#AAFFFFFF' : '#66FFFFFF'
            border.width: 1
            radius: 4
          }
          onClicked: {
            plugin.undoLastClip()
            if (plugin.clipStep === 3)
              plugin.exitClipMode()
          }
        }

        Button {
          id: clipDoneButton
          visible: plugin.clipStep === 3
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Done')
            color: 'white'
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: Theme.mainColor
            border.color: Theme.mainColor
            border.width: 1
            radius: 4
          }
          onClicked: plugin.exitClipMode()
        }
      }
    }
  }

  Dialog {
    id: clipConfirmDialog
    parent: mainWindow.contentItem
    modal: true
    title: qsTr('Clip polygons')
    x: (mainWindow.width - width) / 2
    y: (mainWindow.height - height) / 2
    width: Math.min(mainWindow.width - 40, 420)
    standardButtons: Dialog.Ok | Dialog.Cancel

    onOpened: {
      try {
        const okButton = clipConfirmDialog.standardButton(Dialog.Ok)
        if (okButton)
          okButton.text = qsTr('Clip now')
      } catch (error) {}
    }

    onAccepted: plugin.executeClip()

    ColumnLayout {
      anchors.fill: parent
      spacing: 8

      Label {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        text: plugin.clipMode === 'all'
            ? qsTr('Cutter: 1 polygon — unchanged.') + '\n' +
              qsTr('All %1 visible polygon(s) it overlaps will have the overlap removed. Pieces that get split apart become separate polygons.').arg(
                  plugin.clipAllTargetCount) + '\n' +
              qsTr('Layer: %1').arg(plugin.clipLayerLabel())
            : plugin.clipMode === 'smart'
            ? qsTr('%1 polygons selected.').arg(
                  plugin.keepFeatures.length) + '\n' +
              qsTr('Each smaller polygon is cut out of every larger selected polygon it overlaps. Pieces that get split apart become separate polygons.') + '\n' +
              qsTr('Layer: %1').arg(plugin.clipLayerLabel())
            : qsTr('KEEP: %1 polygon(s) — unchanged.').arg(
                  plugin.keepFeatures.length) + '\n' +
              qsTr('CUT: %1 polygon(s) — the area under the KEEP polygons is removed. Pieces that get split apart become separate polygons.').arg(
                  plugin.cutFeatures.length) + '\n' +
              qsTr('Layer: %1').arg(plugin.clipLayerLabel())
      }
    }
  }

  // ================================================================
  // SPLINE — port of the desktop spline tools
  // (map_cleaning/core/spline_interp.py). While armed, the companion
  // owns the ACTIVE rubberband model: the control points the user
  // places are mirrored into splineControls and the model is rebuilt
  // to hold the smoothed curve, so every native flow (confirm, cancel,
  // remove-vertex, feature form, reshape apply) operates on the curve.
  // Live preview includes the crosshair segment; the CONFIRMED geometry
  // does not — on freeze the model is rewritten from the committed
  // controls only (see splineOnConfirmFreeze). The same confirm-time
  // crosshair exclusion applies to NATIVE digitizing when spline is not
  // armed (nativeConfirmFreeze, always on), which is why the model
  // acquisition below runs even in spline-disabled sidecars.
  // ================================================================

  // Fallbacks mirror map_cleaning/core/utils.py defaults.
  readonly property real splineTightness:
      splineParams.length > 0 ? Number(splineParams[0]) : 0.5
  readonly property real splineTolerance:
      splineParams.length > 1 ? Number(splineParams[1]) : 0.1
  readonly property int splineMaxSegments:
      splineParams.length > 2 ? Number(splineParams[2]) : 200

  // Freehand digitizing commits a vertex every pointer-move event (1-2 px
  // apart) — without thinning, every one becomes a spline control and the
  // rebuild cost grows with stroke length. Minimum node spacing in SCREEN
  // pixels (converted to map units per add); the live-preview sample cap
  // trades preview smoothness for speed (confirm always uses the full
  // splineMaxSegments, so saved geometry quality is untouched).
  readonly property real splineMinNodePx: 8
  readonly property int splineLiveMaxSegments: 16

  // Scale-adaptive output density. splineTolerance/splineMaxSegments above
  // are an absolute map-unit tolerance and a fixed sample count, so a
  // contact drawn at 1:10000 used to be approximated to 0.1 m — a
  // hundredth of a millimetre on the map — and every one of those
  // invisible vertices was paid for twice: once in QField's per-vertex
  // rubberband signalling, once when the feature saved. These express the
  // same thing the way cartography does, as a deviation AT THE MAPPING
  // SCALE: one point is 1/72 inch, so mapUnitsPerPoint IS the scale
  // denominator in map units, and no reference scale has to reach the
  // device for this to work (it is also correctly degrees-per-point in a
  // geographic CRS).
  //   splineTolPoints           prune deviation, ~0.25 mm on the map
  //   splineSampleSpacingPoints raw sample pitch before pruning
  //   splineMinSamples          floor per segment, so a short segment still
  //                             bends
  // splineTolerance/splineMaxSegments survive as the fallback (no map
  // settings), as the sample-count cap, and as a FLOOR on fidelity — the
  // derived tolerance is never finer than the baked one (see
  // splineEffectiveTolerance), so zoomed-in drawing behaves exactly as it
  // always has and the savings land at the small scales where the big
  // polygons get drawn.
  //
  // v29: 0.7 pt was ~0.25 mm, which is not "well under" the Linework ink —
  // the thinnest common stroke is Contact at 0.8 pt = 0.28 mm, so the
  // tolerance was about equal to the finest line on the map. 0.35 pt is
  // ~0.12 mm: under half that stroke and under a quarter of the most
  // common one (1.46 pt).
  readonly property real splineTolPoints: 0.35
  readonly property real splineSampleSpacingPoints: 1.0
  readonly property int splineMinSamples: 4

  // Douglas-Peucker bounds how far a vertex sits from the true curve and
  // says nothing about the CORNER left between consecutive chords — and a
  // corner is what the eye reads as faceting. v27 pruned a gentle cover
  // boundary drawn zoomed out into chords that cornered by a whole
  // millimetre on the map while every vertex was still legitimately
  // within tolerance.
  //
  // The measure used here is the kink: min(chord)/2 * tan(turn/2), i.e.
  // how far the line visibly corners at a vertex. Unlike a turn angle it
  // is meaningful on its own — five degrees across a 20 mm chord is a
  // glaring facet, five degrees across a half-millimetre chord is
  // invisible — and it self-limits, because halving a chord quarters the
  // kink. 0.25 pt is ~0.09 mm: a third of the thinnest Linework stroke.
  //
  // Expressed as a FRACTION OF THE PRUNE TOLERANCE rather than an
  // absolute size, for two reasons. Both are distances on the map, so the
  // ratio is the honest statement of the rule: corners must stay well
  // inside the positional error already being accepted. And it inherits
  // splineEffectiveTolerance's never-finer-than-baked floor for free, so
  // zooming right in cannot drive the refinement past the detail the
  // legacy path kept -- without that, a deep zoom would demand a kink
  // limit far below the tolerance and hand back more vertices than the
  // fixed algorithm ever produced.
  readonly property real splineMaxKinkRatio: 0.4

  property bool splineArmed: false
  property var splineLocator: null    // the coordinateLocator QQuickItem
  property var splineModel: null      // locator.rubberbandModel (active one)
  property bool splinePillVisible: false
  property var splineControls: []     // [{x,y,z}] control points, in order
  property int splineExpected: -1     // model vertexCount we last produced
  property bool splineMutating: false // re-entrancy guard around rebuilds
  property real splineDensityUnits: 0 // latched map units per point (0 = off)
  property var splineLastCross: null  // crosshair coords used in last rebuild
  property var splineLastSeq: null    // sequence last written to the model
  property bool splineLastSeqFull: false // splineLastSeq is at full density
  property var splineFullCache: ({})  // full-density segment cache
  property var splineWriteStats: null // {mode,prefix,pops,adds} of last write (v26)
  property var splineMarkerPositions: []

  // ----------------------------------------------------------------
  // Pure-JS spline math — extracted verbatim by tests/spline_harness.js,
  // so nothing in these functions may reference plugin/QField symbols.
  // Points are plain {x, y, z} objects; z rides along (NaN when absent)
  // and never influences the XY math.
  // ----------------------------------------------------------------

  // mirror of spline_interp.point_scalar / points_add / points_tangent_scaled
  function splinePointScalar(p, k) {
    return { x: p.x * k, y: p.y * k }
  }

  function splinePointsAdd(a, b) {
    return { x: a.x + b.x, y: a.y + b.y }
  }

  function splineTangent(p1, p2, k) {
    return splinePointScalar({ x: p2.x - p1.x, y: p2.y - p1.y }, k)
  }

  // Perpendicular distance from pt to segment a-b (degenerate a==b falls
  // back to the plain distance) — the Douglas-Peucker metric.
  function splinePerpDist(pt, a, b) {
    const dx = b.x - a.x
    const dy = b.y - a.y
    const len2 = dx * dx + dy * dy
    if (len2 <= 0) {
      const ex = pt.x - a.x
      const ey = pt.y - a.y
      return Math.sqrt(ex * ex + ey * ey)
    }
    return Math.abs(dy * pt.x - dx * pt.y + b.x * a.y - b.y * a.x) /
           Math.sqrt(len2)
  }

  // Stand-in for the desktop QgsGeometry.simplify call (Douglas-Peucker).
  // Iterative so deep sample lists cannot hit recursion limits; endpoints
  // are always kept; tolerance <= 0 returns the input unchanged.
  // Index form of the Douglas-Peucker pass. Split out (v29) so the angle
  // refinement can re-insert points from the ORIGINAL dense block by
  // index; splineSimplify below is the unchanged point-returning wrapper.
  function splineSimplifyIndices(points, tolerance) {
    if (!(tolerance > 0) || points.length < 3) {
      const all = []
      for (let i = 0; i < points.length; i++)
        all.push(i)
      return all
    }
    const keep = new Array(points.length).fill(false)
    keep[0] = true
    keep[points.length - 1] = true
    const stack = [[0, points.length - 1]]
    while (stack.length > 0) {
      const range = stack.pop()
      const first = range[0]
      const last = range[1]
      let maxDist = -1
      let maxIdx = -1
      for (let i = first + 1; i < last; i++) {
        const d = splinePerpDist(points[i], points[first], points[last])
        if (d > maxDist) {
          maxDist = d
          maxIdx = i
        }
      }
      if (maxDist > tolerance && maxIdx > 0) {
        keep[maxIdx] = true
        stack.push([first, maxIdx])
        stack.push([maxIdx, last])
      }
    }
    const out = []
    for (let i = 0; i < points.length; i++) {
      if (keep[i])
        out.push(i)
    }
    return out
  }

  function splineSimplify(points, tolerance) {
    const idx = splineSimplifyIndices(points, tolerance)
    const out = []
    for (let i = 0; i < idx.length; i++)
      out.push(points[idx[i]])
    return out
  }

  // Put nodes back wherever the pruned polyline corners visibly. Points
  // come from the dense block the sampler already built, so nothing new
  // is evaluated; only vertices that actually bend attract insertions, so
  // straight runs are left exactly as the prune left them.
  //
  // Two stages. First an even-spacing floor: a coarse prune can keep
  // NOTHING but the block's two endpoints, and with no interior vertices
  // there is nothing for the walk below to test — all of the segment's
  // turning then piles up at the control-point junction, unrefined and
  // unseen. Splitting a block of length L and total turning T into k
  // intervals leaves a kink of about L*T/(4k^2), so k = sqrt(L*T/(4*max))
  // is the count that brings it under the limit. Then a bisection walk
  // catches whatever is still cornered where curvature is uneven.
  //
  // maxKink <= 0 disables the whole thing (the legacy path).
  function splineRefineAngles(points, kept, maxKink) {
    if (!(maxKink > 0) || points.length < 3)
      return kept

    let totalTurn = 0
    let totalLen = 0
    for (let i = 0; i < points.length - 1; i++) {
      const dx = points[i + 1].x - points[i].x
      const dy = points[i + 1].y - points[i].y
      totalLen += Math.sqrt(dx * dx + dy * dy)
    }
    for (let i = 1; i < points.length - 1; i++) {
      const ax = points[i].x - points[i - 1].x
      const ay = points[i].y - points[i - 1].y
      const bx = points[i + 1].x - points[i].x
      const by = points[i + 1].y - points[i].y
      const la = Math.sqrt(ax * ax + ay * ay)
      const lb = Math.sqrt(bx * bx + by * by)
      if (!(la > 0) || !(lb > 0))
        continue
      let c = (ax * bx + ay * by) / (la * lb)
      c = c > 1 ? 1 : (c < -1 ? -1 : c)
      totalTurn += Math.acos(c)
    }

    let current = kept
    let want = Math.ceil(Math.sqrt(totalLen * totalTurn / (4 * maxKink)))
    if (want > points.length - 1)
      want = points.length - 1
    if (want > current.length - 1) {
      // Pure even spacing, NOT a union with the pruned indices: mixing a
      // uniform grid into an uneven one leaves a long chord beside a
      // short one, and that pairing corners harder than either would
      // alone. Uniform chords give the smallest corner for a node count.
      const even = []
      for (let k = 0; k <= want; k++)
        even.push(Math.round(k * (points.length - 1) / want))
      const dedup = [even[0]]
      for (let k = 1; k < even.length; k++)
        if (even[k] !== even[k - 1])
          dedup.push(even[k])
      current = dedup
    }
    if (current.length < 3)
      return current

    for (let pass = 0; pass < 12; pass++) {
      const insert = {}
      let added = 0
      for (let j = 1; j < current.length - 1; j++) {
        const prev = points[current[j - 1]]
        const here = points[current[j]]
        const next = points[current[j + 1]]
        const ax = here.x - prev.x
        const ay = here.y - prev.y
        const bx = next.x - here.x
        const by = next.y - here.y
        const la = Math.sqrt(ax * ax + ay * ay)
        const lb = Math.sqrt(bx * bx + by * by)
        if (!(la > 0) || !(lb > 0))
          continue  // a zero-length chord has no direction to turn through
        let c = (ax * bx + ay * by) / (la * lb)
        c = c > 1 ? 1 : (c < -1 ? -1 : c)
        const turn = Math.acos(c)
        const kink = (la < lb ? la : lb) / 2 * Math.tan(turn / 2)
        if (!(kink > maxKink))
          continue
        // Split the longer neighbouring gap; that is the chord carrying
        // the corner, and shortening it is what reduces the kink.
        const gapA = current[j] - current[j - 1]
        const gapB = current[j + 1] - current[j]
        const wide = gapA >= gapB ? [current[j - 1], current[j]]
                                  : [current[j], current[j + 1]]
        const narrow = gapA >= gapB ? [current[j], current[j + 1]]
                                    : [current[j - 1], current[j]]
        const pairs = [wide, narrow]
        for (let k = 0; k < pairs.length; k++) {
          if (pairs[k][1] - pairs[k][0] >= 2) {
            const mid = Math.floor((pairs[k][0] + pairs[k][1]) / 2)
            if (insert[mid] !== true) {
              insert[mid] = true
              added++
            }
            break
          }
        }
      }
      if (added === 0)
        return current
      const extra = Object.keys(insert).map(Number).sort(function (x, y) {
        return x - y
      })
      const merged = []
      let at = 0
      for (let k = 0; k < extra.length; k++) {
        while (at < current.length && current[at] < extra[k])
          merged.push(current[at++])
        if (at >= current.length || current[at] !== extra[k])
          merged.push(extra[k])
      }
      while (at < current.length)
        merged.push(current[at++])
      current = merged
    }
    return current
  }

  // Thin a dense point run (freehand strokes): keep a point only when it
  // is at least minDist away from the last KEPT point; the first and last
  // points always survive. minDist <= 0 returns the input unchanged.
  function splineDecimate(points, minDist) {
    if (!(minDist > 0) || points.length < 3)
      return points.slice()
    const minDist2 = minDist * minDist
    const out = [points[0]]
    for (let i = 1; i < points.length - 1; i++) {
      const kept = out[out.length - 1]
      const dx = points[i].x - kept.x
      const dy = points[i].y - kept.y
      if (dx * dx + dy * dy >= minDist2)
        out.push(points[i])
    }
    out.push(points[points.length - 1])
    return out
  }

  // Freehand stroke gate for the reshape tool (v24): append pt to
  // controls only when it clears minDist from the last kept point —
  // the live-capture twin of splineDecimate's after-the-fact thinning.
  // Returns whether it appended. Pure JS, no QML identifiers —
  // extracted verbatim into tests/reshape_freehand_harness.js.
  //
  // v33 no longer calls it: capture is ungated and splineDecimate does
  // the thinning once, on release. It is kept because it IS the
  // reference the harness measures that change against — the proof that
  // capturing raw and decimating picks the same control points as
  // gating every move is an equality between these two functions, and
  // deleting one would delete the proof.
  function reshapeStrokeAppend(controls, pt, minDist) {
    if (controls.length === 0 || !(minDist > 0)) {
      controls.push(pt)
      return true
    }
    const last = controls[controls.length - 1]
    const dx = pt.x - last.x
    const dy = pt.y - last.y
    if (dx * dx + dy * dy < minDist * minDist)
      return false
    controls.push(pt)
    return true
  }

  // ----------------------------------------------------------------
  // Reshape line conditioning (v32). GEOS's reshape is intolerant of
  // what a touch screen produces: coincident vertices, zero-length
  // segments, micro self-loops, and mixed 2D/3D points all make it
  // return NothingHappened with no explanation. These are pure JS —
  // no QML identifiers — extracted verbatim into
  // tests/reshape_condition_harness.js.
  // ----------------------------------------------------------------

  // Drop consecutive points closer than eps. The FIRST and LAST points
  // always survive — they are the line's entry and exit, and losing
  // either is precisely the silent failure this exists to prevent: when
  // the last point crowds the previous kept one, the interior point is
  // dropped, never the endpoint. eps <= 0 still removes exact
  // coincident duplicates.
  function reshapeDedupe(points, eps) {
    if (points.length < 2)
      return points.slice()
    const eps2 = (eps > 0) ? eps * eps : 0
    const out = [points[0]]
    for (let i = 1; i < points.length - 1; i++) {
      const kept = out[out.length - 1]
      const dx = points[i].x - kept.x
      const dy = points[i].y - kept.y
      if (dx * dx + dy * dy > eps2)
        out.push(points[i])
    }
    const last = points[points.length - 1]
    let tail = out[out.length - 1]
    const dx = last.x - tail.x
    const dy = last.y - tail.y
    if (dx * dx + dy * dy <= eps2 && out.length > 1)
      out.pop()
    tail = out[out.length - 1]
    if (last.x !== tail.x || last.y !== tail.y)
      out.push(last)
    return out
  }

  // The splineSeqToWkt hasZ rule, applied to the points themselves: a
  // line is 3D only when EVERY z is finite; one unreadable z makes the
  // whole line 2D (z = NaN throughout) rather than a mixed sequence
  // the geometry engine reads as neither.
  function reshapeForce2DPolicy(points) {
    let allFinite = points.length > 0
    for (const p of points) {
      if (!isFinite(Number(p.z))) {
        allFinite = false
        break
      }
    }
    if (allFinite)
      return points.slice()
    const out = []
    for (const p of points) {
      const q = Object.assign({}, p)
      q.z = NaN
      out.push(q)
    }
    return out
  }

  // Proper interior crossing of segments a-b and c-d, or null. Touches
  // at segment endpoints (t or u exactly 0/1) and collinear overlaps
  // are NOT crossings — a vertex sitting on another segment is normal
  // in a tightly drawn line. z interpolates along a-b when both ends
  // carry one.
  function reshapeSegIntersection(a, b, c, d) {
    const rx = b.x - a.x
    const ry = b.y - a.y
    const sx = d.x - c.x
    const sy = d.y - c.y
    const denom = rx * sy - ry * sx
    if (denom === 0)
      return null
    const t = ((c.x - a.x) * sy - (c.y - a.y) * sx) / denom
    const u = ((c.x - a.x) * ry - (c.y - a.y) * rx) / denom
    if (t <= 0 || t >= 1 || u <= 0 || u >= 1)
      return null
    const az = Number(a.z)
    const bz = Number(b.z)
    const z = (isFinite(az) && isFinite(bz)) ? az + t * (bz - az) : NaN
    return { x: a.x + t * rx, y: a.y + t * ry, z: z }
  }

  // Cut self-loops out of an open polyline: when segment i crosses
  // segment j (j > i+1), everything between is replaced by the
  // crossing point itself, keeping the line's overall run. Restarts
  // from the cut, so nested loops unwind too; the guard bounds the
  // pathological case.
  function reshapeRemoveLoops(points) {
    let pts = points.slice()
    let guard = 0
    for (let i = 0; i + 3 < pts.length && guard < 1000; i++) {
      for (let j = i + 2; j + 1 < pts.length; j++) {
        const hit = reshapeSegIntersection(pts[i], pts[i + 1],
                                           pts[j], pts[j + 1])
        if (hit === null)
          continue
        pts = pts.slice(0, i + 1).concat([hit], pts.slice(j + 1))
        j = i + 1
        guard++
      }
    }
    return pts
  }

  // Prolong the line past its ends along the end tangents — a straight
  // external extension cannot change the visible curve, it lives
  // outside the polygon. Appends new endpoints; the drawn ones stay.
  function reshapeExtendEnds(points, extendFirst, extendLast, dist) {
    if (points.length < 2 || !(dist > 0))
      return points.slice()
    const out = points.slice()
    if (extendFirst) {
      const a = out[0]
      const b = out[1]
      const dx = a.x - b.x
      const dy = a.y - b.y
      const len = Math.sqrt(dx * dx + dy * dy)
      if (len > 0)
        out.unshift({ x: a.x + dx / len * dist, y: a.y + dy / len * dist,
                      z: Number(a.z) })
    }
    if (extendLast) {
      const a = out[out.length - 1]
      const b = out[out.length - 2]
      const dx = a.x - b.x
      const dy = a.y - b.y
      const len = Math.sqrt(dx * dx + dy * dy)
      if (len > 0)
        out.push({ x: a.x + dx / len * dist, y: a.y + dy / len * dist,
                   z: Number(a.z) })
    }
    return out
  }

  // The pipeline: dedupe, then the 2D policy, then loop removal —
  // skipped above loopCap points (the scan is O(n²); a capped skip
  // never costs correctness, only a retry later). loopCap <= 0 means
  // no cap.
  function reshapeConditionSequence(points, eps, loopCap) {
    let out = reshapeForce2DPolicy(reshapeDedupe(points, eps))
    if (!(loopCap > 0) || out.length <= loopCap)
      out = reshapeRemoveLoops(out)
    return out
  }

  // Exact point equality for cache keys: NaN/undefined z equals
  // NaN/undefined z (same rules as splineCommonPrefixLength), and the
  // open-end boundary marker null only equals null.
  function splineSamePoint(a, b) {
    if (a === null || b === null)
      return a === b
    if (a.x !== b.x || a.y !== b.y)
      return false
    const az = a.z
    const bz = b.z
    return az === bz ||
        ((az === undefined || Number.isNaN(az)) &&
         (bz === undefined || Number.isNaN(bz)))
  }

  // Round a map-units-per-point reading to the nearest power of two.
  // Latching an OCTAVE rather than the live value is what keeps this
  // cheap: the segment cache is invalidated by a params mismatch, so an
  // unquantized reading would wipe splineFullCache on every pinch. Pure
  // doubling/halving (no logarithms) so the device and the node harness
  // agree bit for bit. Returns 0 for anything unusable.
  function splineQuantizeUnits(value) {
    if (!(isFinite(value) && value > 1e-12 && value < 1e12))
      return 0
    let q = 1
    while (q > value)
      q = q / 2
    while (q * 2 <= value)
      q = q * 2
    return (value >= q * Math.SQRT2) ? q * 2 : q
  }

  // Douglas-Peucker tolerance to prune a sample block with: the deviation
  // that reads as smooth at this scale, or the baked desktop tolerance
  // when there is no density (no map settings, or an un-started session).
  //
  // NEVER finer than the baked tolerance. Below about 1:400 the derived
  // value drops under the baked 0.1, which would quietly make close-in
  // drawing SLOWER than before this change — the opposite of the point.
  // Clamping keeps zoomed-in fidelity exactly as it has always been and
  // spends the savings where they were asked for, as the map zooms out.
  // It also makes this change a strict improvement: no scale, anywhere,
  // saves more vertices than it used to.
  function splineEffectiveTolerance(tolerance, density) {
    if (density && density.unitsPerPoint > 0 && density.tolPoints > 0)
      return Math.max(tolerance, density.unitsPerPoint * density.tolPoints)
    return tolerance
  }

  // How many raw samples one segment needs. Sampling 200 points per
  // segment and then pruning 195 of them is the cold-confirm cost, so
  // sample by the segment's own on-screen length instead. The cubic's
  // equivalent Bezier control polygon (p0, p0+t0/3, p1-t1/3, p1) is an
  // upper bound on its arc length and tight enough to pitch samples by.
  // Sampling at ~1 point while pruning at ~0.7 leaves ample margin: a
  // feature this sampler could miss needs a curvature radius under half a
  // screen point. No density (or none usable) returns maxSegments — the
  // legacy path, bit for bit.
  function splineSampleCount(p0, p1, t0, t1, maxSegments, density) {
    if (!density || !(density.unitsPerPoint > 0) ||
        !(density.spacingPoints > 0))
      return maxSegments
    const b1x = p0.x + t0.x / 3
    const b1y = p0.y + t0.y / 3
    const b2x = p1.x - t1.x / 3
    const b2y = p1.y - t1.y / 3
    const arc = Math.sqrt((b1x - p0.x) ** 2 + (b1y - p0.y) ** 2) +
                Math.sqrt((b2x - b1x) ** 2 + (b2y - b1y) ** 2) +
                Math.sqrt((p1.x - b2x) ** 2 + (p1.y - b2y) ** 2)
    const floor = density.minSamples > 0 ? density.minSamples : 1
    let wanted = Math.ceil(arc / (density.unitsPerPoint *
                                  density.spacingPoints))
    // Curvature term (v29): the kink refinement can only re-insert points
    // this block actually contains, so a segment that turns a long way has
    // to be sampled finely enough to hold them. Twice the count the
    // refinement will ask for leaves bisection somewhere to land.
    if (density.maxKinkRatio > 0) {
      const la = Math.sqrt(t0.x * t0.x + t0.y * t0.y)
      const lb = Math.sqrt(t1.x * t1.x + t1.y * t1.y)
      if (la > 0 && lb > 0) {
        let cos = (t0.x * t1.x + t0.y * t1.y) / (la * lb)
        cos = cos > 1 ? 1 : (cos < -1 ? -1 : cos)
        const byTurn = 2 * Math.ceil(Math.sqrt(
            arc * Math.acos(cos) / (4 * density.maxKinkRatio *
                                    splineEffectiveTolerance(0, density))))
        if (byTurn > wanted)
          wanted = byTurn
      }
    }
    if (!isFinite(wanted) || wanted < floor)
      return Math.min(floor, maxSegments)
    return Math.min(wanted, maxSegments)
  }

  // Cache-parameter identity for a density ('' = none), so a zoom that
  // crosses an octave resets the cache and one that does not, does not.
  function splineDensityKey(density) {
    if (!density || !(density.unitsPerPoint > 0))
      return ''
    return density.unitsPerPoint + '|' + density.tolPoints + '|' +
           density.spacingPoints + '|' + density.minSamples + '|' +
           density.maxKinkRatio
  }

  // Segment cache for the full-density curves. A segment's pruned sample
  // block is fully determined by four controls (tangent neighbours +
  // endpoints; null marks an open-curve end, where the tangent formula
  // changes) and the parameters, so entries are validated purely by
  // comparing those recorded deps — a stale entry fails the comparison
  // and recomputes, no separate invalidation exists. Hits replay the
  // exact block a previous call computed, so cached output stays
  // bit-identical to the uncached path.
  // Returns the entry array for the requested curve kind ('o' open /
  // 'c' closed), resetting the whole cache when the params changed.
  function splineCacheEntries(cache, kind, tightness, tolerance, maxSegments,
                             density) {
    if (!cache)
      return null
    const key = splineDensityKey(density)
    if (!cache.p || cache.p[0] !== tightness || cache.p[1] !== tolerance ||
        cache.p[2] !== maxSegments || cache.p[3] !== key) {
      cache.p = [tightness, tolerance, maxSegments, key]
      cache.o = []
      cache.c = []
    }
    return cache[kind]
  }

  function splineCacheLookup(entries, i, deps) {
    const entry = entries[i]
    if (!entry)
      return null
    for (let k = 0; k < deps.length; k++) {
      if (!splineSamePoint(entry.deps[k], deps[k]))
        return null
    }
    return entry.block
  }

  // mirror of spline_interp.hermite (open polyline). Control points are
  // interpolated exactly and survive simplification verbatim; the sample
  // blocks between them are pruned per segment, same as the desktop
  // cleanup loop. Operation order matches the Python exactly so the
  // parity fixtures agree to float precision. The optional cache (see
  // splineCacheEntries) skips recomputing segments whose deps are
  // unchanged since a previous call — output is bit-identical.
  function splineHermiteOpen(points, tightness, tolerance, maxSegments, cache,
                            density) {
    const n = points.length
    if (n < 3)
      return points.slice()

    const entries = splineCacheEntries(cache, 'o', tightness, tolerance,
                                       maxSegments, density)
    const effTol = splineEffectiveTolerance(tolerance, density)

    const tangents = [splineTangent(points[0], points[1], tightness)]
    for (let i = 1; i < n - 1; i++)
      tangents.push(splineTangent(points[i - 1], points[i + 1], tightness))
    tangents.push(splineTangent(points[n - 2], points[n - 1], tightness))

    const result = []
    for (let i = 0; i < n - 1; i++) {
      const p0 = points[i]
      const p1 = points[i + 1]
      result.push(p0)

      const deps = [i > 0 ? points[i - 1] : null, p0, p1,
                    i + 1 < n - 1 ? points[i + 2] : null]
      let interior = entries ? splineCacheLookup(entries, i, deps) : null
      if (interior === null) {
        const segs = splineSampleCount(p0, p1, tangents[i], tangents[i + 1],
                                       maxSegments, density)
        const t = 1.0 / segs
        let s = t
        const samples = []
        while (s < 1) {
          const h1p1 = splinePointScalar(p0, (2 * (s ** 3)) - (3 * (s ** 2)) + 1)
          const h2p2 = splinePointScalar(p1, 3 * (s ** 2) - 2 * (s ** 3))
          const h3t1 = splinePointScalar(tangents[i], (s ** 3) - (2 * (s ** 2)) + s)
          const h4t2 = splinePointScalar(tangents[i + 1], (s ** 3) - (s ** 2))
          const tmp = splinePointsAdd(splinePointsAdd(h1p1, h2p2),
                                      splinePointsAdd(h3t1, h4t2))
          tmp.z = p0.z + (p1.z - p0.z) * s   // NaN propagates for 2D input
          samples.push(tmp)
          s = s + t
        }

        const block = [p0].concat(samples).concat([p1])
        const kept = splineRefineAngles(
            block, splineSimplifyIndices(block, effTol),
            density ? density.maxKinkRatio * effTol : 0)
        const pruned = []
        for (let k = 0; k < kept.length; k++)
          pruned.push(block[kept[k]])
        interior = pruned.slice(1, pruned.length - 1)
        if (entries)
          entries[i] = { deps: deps, block: interior }
      }
      for (let j = 0; j < interior.length; j++)
        result.push(interior[j])
    }
    result.push(points[n - 1])
    return result
  }

  // mirror of spline_interp.hermite_closed with two shape changes: input
  // is the UNCLOSED unique ring (the rubberband carries no closing
  // duplicate) and the output stays unclosed too. Returns
  // {points, lastControlIndex} so the caller can rotate the ring.
  function splineHermiteClosed(points, tightness, tolerance, maxSegments, cache,
                              density) {
    const n = points.length
    if (n < 3)
      return { points: points.slice(), lastControlIndex: points.length - 1 }

    const entries = splineCacheEntries(cache, 'c', tightness, tolerance,
                                      maxSegments, density)
    const effTol = splineEffectiveTolerance(tolerance, density)

    const tangents = []
    for (let i = 0; i < n; i++) {
      const prev = points[(i - 1 + n) % n]
      const next = points[(i + 1) % n]
      tangents.push(splineTangent(prev, next, tightness))
    }

    const result = []
    let lastControlIndex = 0
    for (let i = 0; i < n; i++) {
      const p0 = points[i]
      const p1 = points[(i + 1) % n]
      lastControlIndex = result.length
      result.push(p0)

      const deps = [points[(i - 1 + n) % n], p0, p1, points[(i + 2) % n]]
      let interior = entries ? splineCacheLookup(entries, i, deps) : null
      if (interior === null) {
        const segs = splineSampleCount(p0, p1, tangents[i],
                                       tangents[(i + 1) % n], maxSegments,
                                       density)
        const t = 1.0 / segs
        let s = t
        const samples = []
        while (s < 1) {
          const h1p1 = splinePointScalar(p0, (2 * (s ** 3)) - (3 * (s ** 2)) + 1)
          const h2p2 = splinePointScalar(p1, 3 * (s ** 2) - 2 * (s ** 3))
          const h3t1 = splinePointScalar(tangents[i], (s ** 3) - (2 * (s ** 2)) + s)
          const h4t2 = splinePointScalar(tangents[(i + 1) % n], (s ** 3) - (s ** 2))
          const tmp = splinePointsAdd(splinePointsAdd(h1p1, h2p2),
                                      splinePointsAdd(h3t1, h4t2))
          tmp.z = p0.z + (p1.z - p0.z) * s
          samples.push(tmp)
          s = s + t
        }

        const block = [p0].concat(samples).concat([p1])
        const kept = splineRefineAngles(
            block, splineSimplifyIndices(block, effTol),
            density ? density.maxKinkRatio * effTol : 0)
        const pruned = []
        for (let k = 0; k < kept.length; k++)
          pruned.push(block[kept[k]])
        interior = pruned.slice(1, pruned.length - 1)
        if (entries)
          entries[i] = { deps: deps, block: interior }
      }
      for (let j = 0; j < interior.length; j++)
        result.push(interior[j])
    }
    // lastControlIndex still points at points[n-1] — the wrap segment's
    // samples sit after it, closing the ring back to points[0] implicitly.
    return { points: result, lastControlIndex: lastControlIndex }
  }

  // Longest common prefix of two point sequences (exact x/y/z equality;
  // NaN z on both sides counts as equal). Stable curve segments recompute
  // to bit-identical doubles, so exact comparison finds the real reusable
  // prefix between successive rebuilds.
  function splineCommonPrefixLength(a, b) {
    const n = Math.min(a.length, b.length)
    let i = 0
    for (; i < n; i++) {
      if (a[i].x !== b[i].x || a[i].y !== b[i].y)
        break
      const az = a[i].z
      const bz = b[i].z
      const zEqual = az === bz ||
          ((az === undefined || Number.isNaN(az)) &&
           (bz === undefined || Number.isNaN(bz)))
      if (!zEqual)
        break
    }
    return i
  }

  // The vertex sequence the rubberband model should hold. The last input
  // point is the crosshair; the returned sequence always ends on it so it
  // can stay the model's floating vertex:
  //  - open: the curve simply ends at the crosshair;
  //  - closed: the ring is rotated so the crosshair control is last — the
  //    implicit closing edge (floating vertex back to the first vertex)
  //    is then the first sample of the smoothed wrap segment, keeping the
  //    seam curved.
  // Fewer than 3 distinct points pass through unchanged (native straight
  // rubberband behaviour).
  function splineBuildSequence(points, closed, tightness, tolerance, maxSegments, cache, density) {
    const pts = []
    for (let i = 0; i < points.length; i++) {
      const p = points[i]
      if (pts.length === 0 || pts[pts.length - 1].x !== p.x ||
          pts[pts.length - 1].y !== p.y)
        pts.push(p)
    }
    if (pts.length < 3)
      return pts
    if (!closed)
      return splineHermiteOpen(pts, tightness, tolerance, maxSegments, cache,
                               density)
    const ring = splineHermiteClosed(pts, tightness, tolerance, maxSegments,
                                     cache, density)
    const k = ring.lastControlIndex
    return ring.points.slice(k + 1).concat(ring.points.slice(0, k + 1))
  }

  // The vertex sequence to commit when the user confirms: the curve
  // through the COMMITTED control points only — the crosshair takes no
  // part (QField's confirm tap jiggles the crosshair, and the floating
  // vertex it feeds is harvested into the final geometry). Returns null
  // when there are too few distinct controls to form the geometry
  // without the crosshair (< 2 for lines, < 3 for rings) — native
  // behaviour (crosshair as final vertex) is the right fallback there.
  function splineConfirmSequence(controls, closed, tightness, tolerance, maxSegments, cache, density) {
    const pts = []
    for (let i = 0; i < controls.length; i++) {
      const p = controls[i]
      if (pts.length === 0 || pts[pts.length - 1].x !== p.x ||
          pts[pts.length - 1].y !== p.y)
        pts.push(p)
    }
    if (pts.length < (closed ? 3 : 2))
      return null
    if (!closed)
      return splineHermiteOpen(pts, tightness, tolerance, maxSegments, cache,
                               density)
    return splineHermiteClosed(pts, tightness, tolerance, maxSegments,
                               cache, density).points
  }

  // Ring idle-upgrade sequence (v26): the confirm ring (committed
  // controls only) with the crosshair appended as the floating tail.
  // Writing THIS at idle time — instead of the crosshair-rotated live
  // ring — leaves the model's committed vertices bit-identical to the
  // confirm sequence (the segment cache replays identical doubles), so
  // the confirm-time prefix diff collapses to a tail rewrite for rings
  // exactly as it does for open lines. The visible cost: while idle the
  // crosshair is pinned into the ring by two straight seam chords
  // instead of riding the curve — any crosshair move restores the
  // smooth live preview via the normal rebuild. Returns null below 3
  // distinct controls (same fallback as splineConfirmSequence).
  function splineRingIdleSequence(controls, cross, tightness, tolerance, maxSegments, cache, density) {
    const confirm = splineConfirmSequence(controls, true, tightness,
        tolerance, maxSegments, cache, density)
    if (confirm === null)
      return null
    return confirm.concat([cross])
  }

  // WKT for a vertex sequence — LINESTRING (open) or single-ring
  // POLYGON with the closing duplicate appended (closed). Z is emitted
  // only when EVERY vertex carries a finite z (2D layers deliver NaN z,
  // which WKT cannot express). Default JS number formatting round-trips
  // doubles exactly, so the parsed geometry is bit-identical.
  function splineSeqToWkt(seq, closed) {
    if (seq.length === 0)
      return null
    let hasZ = true
    for (let i = 0; i < seq.length; i++) {
      const z = seq[i].z
      if (z === undefined || z === null || !isFinite(z)) {
        hasZ = false
        break
      }
    }
    const coords = []
    for (let i = 0; i < seq.length; i++) {
      const p = seq[i]
      coords.push(hasZ ? p.x + ' ' + p.y + ' ' + p.z
                       : p.x + ' ' + p.y)
    }
    if (closed) {
      if (seq[0].x !== seq[seq.length - 1].x ||
          seq[0].y !== seq[seq.length - 1].y)
        coords.push(coords[0])
      return (hasZ ? 'POLYGON Z ((' : 'POLYGON ((') +
             coords.join(', ') + '))'
    }
    return (hasZ ? 'LINESTRING Z (' : 'LINESTRING (') +
           coords.join(', ') + ')'
  }

  // ----------------------------------------------------------------
  // Model acquisition + session state
  // ----------------------------------------------------------------
  function initSpline() {
    try {
      if (!splineLocator)
        splineLocator = iface.findItemByObjectName('coordinateLocator')
    } catch (error) {
      splineLocator = null
    }
    try {
      if (canvas && canvas.width !== undefined &&
          splineMarkers.parent !== canvas) {
        splineMarkers.parent = canvas
        splineMarkers.anchors.fill = canvas
      }
    } catch (error) {}
    // featureSpline gate: initSpline now runs even in spline-disabled
    // sidecars (for the native confirm fixup) — a stale lgs_spline_armed
    // from a spline-enabled export must not arm the spline handlers.
    splineArmed = featureSpline && projVar('lgs_spline_armed', '0') === '1'
    refreshSplineModel()
    splineWatchTimer.start()
  }

  function refreshSplineModel() {
    let model = null
    try {
      model = splineLocator ? splineLocator.rubberbandModel : null
    } catch (error) {
      model = null
    }
    if (model === undefined)
      model = null
    if (model !== splineModel) {
      // Digitize <-> geometry-editor switch (or model gone): the control
      // points belong to the old context.
      splineModel = model
      splineResetSession()
    }
    updateSplinePill()
  }

  function splineResetSession() {
    splineControls = []
    splineExpected = -1
    splineLastCross = null
    splineLastSeq = null
    splineLastSeqFull = false
    splineFullCache = ({})
    splineRefreshDensity()
    updateSplineMarkers()
  }

  // Whether the active model digitizes a closed ring. The open/closed
  // choice keys off vectorLayer, never geometryType alone — the reshape
  // editor types its open cut line as Polygon. Callers wrap in try/catch
  // (splineModel property reads can throw on a dead model).
  function splineIsClosed() {
    return splineModel.vectorLayer !== null &&
           splineModel.vectorLayer !== undefined &&
           Number(splineModel.geometryType) ===
               Number(Qgis.GeometryType.Polygon)
  }

  function updateSplinePill() {
    let show = false
    try {
      if (featureSpline && splineModel !== null) {
        const gt = Number(splineModel.geometryType)
        show = gt === Number(Qgis.GeometryType.Line) ||
               gt === Number(Qgis.GeometryType.Polygon)
      }
    } catch (error) {
      show = false
    }
    splinePillVisible = show
  }

  function toggleSplineArmed() {
    if (splineArmed) {
      splineRestoreControls()
      splineArmed = false
      saveVar('lgs_spline_armed', '0')
      toast(qsTr('Spline off'))
    } else {
      splineArmed = true
      saveVar('lgs_spline_armed', '1')
      // Adopt anything already digitized in this session as control points.
      splineAdoptCommitted()
      splineRebuildTimer.restart()
      toast(qsTr('Splines digitise better with the freehand tool turned off'))
    }
  }

  // splineMinNodePx converted to map units at the current zoom (0 = gate
  // off when the map settings are unavailable).
  function splineMinNodeMapUnits() {
    try {
      const perPoint = Number(canvas.mapSettings.mapUnitsPerPoint)
      if (isFinite(perPoint) && perPoint > 0)
        return perPoint * splineMinNodePx
    } catch (error) {}
    return 0
  }

  // Re-latch the output density. Called when a session starts and
  // whenever a control point is adopted — that is, while the user is
  // DRAWING — never on zoom alone. Two reasons: panning and zooming to
  // look around must not wipe the segment cache, and a curve drawn at
  // 1:2000 must not be saved at 1:50000 density because the user zoomed
  // out to check their work before tapping the green tick. Quantized, so
  // re-latching is usually a no-op. projVar rebuilds the whole project
  // variable map, which is another reason this is latched and not read
  // per rebuild.
  //
  // ANCHORED TO THE MAPPING SCALE (v29). v27 keyed purely off the zoom
  // the user happened to be drawing at, and big polygons — transported
  // cover especially — are drawn zoomed OUT. The map is then viewed and
  // printed at the project's reference scale, so those curves were
  // permanently too coarse for the scale they actually live at. Density
  // now targets whichever is finer, the reference scale or the live zoom,
  // so drawing zoomed out no longer costs smoothness and deliberately
  // zooming in for detail still buys it.
  //
  // The scale denominator is NOT converted to map units directly — that
  // would assume metres and break in a geographic CRS. Taking it as the
  // ratio referenceScale/liveScale against the live mapUnitsPerPoint
  // cancels the map units out entirely.
  function splineRefreshDensity() {
    let perPoint = 0
    let liveScale = 0
    try {
      perPoint = Number(canvas.mapSettings.mapUnitsPerPoint)
      liveScale = Number(canvas.mapSettings.scale)
    } catch (error) {
      perPoint = 0
      liveScale = 0
    }
    // '' (absent) and '0' (published as "unknown") both fall through to
    // the live zoom, i.e. exactly the v27 behaviour.
    const refScale = Number(projVar('lgs_reference_scale', ''))
    if (isFinite(perPoint) && perPoint > 0 &&
        isFinite(liveScale) && liveScale > 0 &&
        isFinite(refScale) && refScale > 0 && refScale < liveScale)
      perPoint = perPoint * (refScale / liveScale)
    splineDensityUnits = splineQuantizeUnits(perPoint)
  }

  // The density bundle handed to the curve builders. Built once per
  // rebuild and passed down — the builders must never read the map
  // settings themselves, or the idle write and the confirm write could
  // disagree and v26's prefix diff would silently fall back to a full
  // reset. null = no density, i.e. the legacy fixed-tolerance path.
  function splineDensity() {
    if (!(splineDensityUnits > 0))
      return null
    return { unitsPerPoint: splineDensityUnits,
             tolPoints: splineTolPoints,
             spacingPoints: splineSampleSpacingPoints,
             minSamples: splineMinSamples,
             maxKinkRatio: splineMaxKinkRatio }
  }

  // Take the model's committed vertices (all but the floating crosshair
  // vertex) as the control points — used when arming mid-digitize and as
  // the recovery path when the vertex count changes in a way we did not
  // predict. Freehand-dense runs are thinned to the minimum node spacing.
  function splineAdoptCommitted() {
    splineControls = []
    splineLastSeq = null
    splineLastSeqFull = false
    try {
      const verts = splineModel.vertices
      const count = Number(splineModel.vertexCount)
      for (let i = 0; i < count - 1; i++)
        splineControls.push({ x: verts[i].x, y: verts[i].y, z: verts[i].z })
      splineControls = splineDecimate(splineControls, splineMinNodeMapUnits())
      splineRefreshDensity()
      splineExpected = count
    } catch (error) {
      splineControls = []
      splineExpected = -1
    }
    splineControls = splineControls.slice()  // trigger change signal
    updateSplineMarkers()
  }

  // ----------------------------------------------------------------
  // Event choreography — native vertex adds/removes and crosshair moves
  // trigger a coalesced rebuild; our own mutations are guarded out.
  // ----------------------------------------------------------------
  function splineOnCountChanged() {
    if (splineMutating || !splineArmed || splineModel === null)
      return
    let count = 0
    let frozen = false
    try {
      count = Number(splineModel.vertexCount)
      frozen = splineModel.frozen === true
    } catch (error) {
      return
    }
    if (frozen)
      return  // confirm in progress — never touch a frozen model
    if (count <= 1) {
      // Session reset (confirm finished or cancel) — start clean, armed.
      splineResetSession()
      splineExpected = count
      return
    }
    if (splineExpected >= 0 && count === splineExpected + 1) {
      // Native add: the newly committed vertex sits before the floating one.
      // Freehand thinning: a vertex closer than the minimum node spacing to
      // the last control is NOT adopted — the scheduled rebuild rewrites
      // the model from the controls, erasing the raw vertex again.
      try {
        const verts = splineModel.vertices
        const v = verts[count - 2]
        let keep = true
        if (splineControls.length > 0) {
          const minDist = splineMinNodeMapUnits()
          if (minDist > 0) {
            const last = splineControls[splineControls.length - 1]
            const dx = v.x - last.x
            const dy = v.y - last.y
            keep = dx * dx + dy * dy >= minDist * minDist
          }
        }
        if (keep) {
          splineRefreshDensity()
          splineControls.push({ x: v.x, y: v.y, z: v.z })
          splineControls = splineControls.slice()
        }
      } catch (error) {
        splineAdoptCommitted()
      }
    } else if (splineExpected >= 0 && count === splineExpected - 1) {
      // Native remove: desktop Backspace semantics — drop a CONTROL point.
      if (splineControls.length > 0) {
        splineControls.pop()
        splineControls = splineControls.slice()
      }
    } else {
      // Anything else (first vertices of a session, missed signals):
      // resync from the committed vertices.
      splineAdoptCommitted()
    }
    splineExpected = count
    updateSplineMarkers()
    splineScheduleRebuild()
    // Keep the full-density cache warm for the new control set (deferred
    // so the vertex tap itself is never extended by the segment math).
    splineWarmTimer.restart()
  }

  // Throttle, NOT debounce: restart() on every crosshair move would push
  // the timer forever forward during a continuous pan, so the curve would
  // only update after the pan stops. Letting a running timer run means it
  // fires every interval while moves keep arriving, and the move that
  // lands after a fire re-arms it — the final position is always rebuilt
  // within one interval.
  function splineScheduleRebuild() {
    if (!splineRebuildTimer.running)
      splineRebuildTimer.start()
    // Any change invalidates a full-density model write and re-arms the
    // idle upgrade (debounce — it should fire only after a quiet moment).
    splineLastSeqFull = false
    splineIdleTimer.restart()
  }

  function splineOnCrosshairMoved() {
    if (splineMutating || !splineArmed || splineModel === null)
      return
    if (splineControls.length < 2)
      return  // fewer than 3 points with the crosshair — nothing to curve
    let cross = null
    try {
      if (splineModel.frozen === true)
        return
      const cc = splineModel.currentCoordinate
      cross = { x: cc.x, y: cc.y, z: cc.z }
    } catch (error) {
      return
    }
    if (splineLastCross !== null &&
        splineLastCross.x === cross.x && splineLastCross.y === cross.y)
      return
    splineScheduleRebuild()
  }

  // Write seq into the model through the invokables only (never assign
  // currentCoordinate — that would break the app's crosshair binding),
  // with the cheapest available operation. Caller owns splineMutating
  // (and frozen state); returns true when the write landed.
  //
  // Incremental suffix update: between rebuilds only the last couple of
  // segments usually change (the crosshair position and the tangent at
  // the last control), so peel and re-add just the changed tail instead
  // of resetting the whole model — far fewer invokable calls, each of
  // which fires QField-side signal handlers. The model currently holds
  // [splineLastSeq[0..n-2] committed, floating = live crosshair] — the
  // floating vertex is never trusted for the diff.
  // allowBulk (v26): permit the one-call setDataFromGeometry fast path
  // in the full-reset branch — confirm-freeze only, never live rebuilds
  // (a bulk write mid-draw could fight the crosshair binding).
  function splineWriteSequence(seq, allowBulk) {
    splineWriteStats = null
    let prefix = 0
    let modelCount = 0
    try {
      modelCount = Number(splineModel.vertexCount)
    } catch (error) {
      splineLastSeq = null
      return false
    }
    // modelCount >= lastSeq.length also admits a model GROWN by native
    // end-appends (freehand adds land before the floating vertex) — the
    // committed prefix model[0..lastSeq.length-2] is still our own last
    // write. Everything past it (raw freehand commits, the add-mutated
    // slot at lastSeq.length-1, the floating vertex) is untrusted, but the
    // vertex at index `prefix` is always overwritten by the first re-add,
    // so capping prefix at lastSeq.length-1 keeps the peel sound. Shrunk
    // models (native remove) still take the full-reset path.
    if (splineLastSeq !== null && modelCount >= splineLastSeq.length) {
      prefix = splineCommonPrefixLength(splineLastSeq, seq)
      prefix = Math.min(prefix, splineLastSeq.length - 1,
                        modelCount - 1, seq.length - 1)
      if (prefix < 0)
        prefix = 0
    }
    // Peel to length prefix+1 (the vertex at `prefix` becomes the floating
    // one and is overwritten by the first add), append seq[prefix..], then
    // one removeVertex drops the trailing floating duplicate. Fall back to
    // the full reset path whenever it is not actually cheaper.
    const pops = modelCount - (prefix + 1)
    const incrementalCost = pops + (seq.length - prefix) + 1
    const fullCost = seq.length + 2
    try {
      if (prefix > 0 && incrementalCost < fullCost && pops >= 0) {
        for (let i = 0; i < pops; i++)
          splineModel.removeVertex()
        for (let i = prefix; i < seq.length; i++)
          splineModel.addVertexFromPoint(
              GeometryUtils.point(seq[i].x, seq[i].y, seq[i].z))
        splineModel.removeVertex()
        splineWriteStats = { mode: 'tail', prefix: prefix, pops: pops,
                             adds: seq.length - prefix }
      } else if (allowBulk === true && seq.length >= 200 &&
                 splineBulkWrite(seq)) {
        splineWriteStats = { mode: 'bulk', prefix: 0, pops: 0,
                             adds: seq.length }
      } else {
        splineModel.reset(true)
        for (let i = 0; i < seq.length; i++)
          splineModel.addVertexFromPoint(
              GeometryUtils.point(seq[i].x, seq[i].y, seq[i].z))
        splineModel.removeVertex()
        splineWriteStats = { mode: 'reset', prefix: 0, pops: 0,
                             adds: seq.length }
      }
      splineExpected = Number(splineModel.vertexCount)
      splineLastSeq = seq
      return true
    } catch (error) {
      splineLastSeq = null
      return false
    }
  }

  // Bulk fast path (v26): one setDataFromGeometry call instead of
  // seq.length per-vertex invokables (each of which makes QField rebuild
  // its screen rubberband — the O(N^2) that made large cold confirms
  // crawl). The setter is NOT a QField API the sidecar can rely on
  // (neither reference build's QML uses it), so it is feature-detected
  // and the outcome strictly verified; ANY surprise returns false and
  // the caller falls back to reset + the per-vertex loop, costing at
  // most one wasted call on an incompatible build. The sequence is
  // written as a LINESTRING — the model is a flat vertex list, and a
  // 1:1 geometry avoids guessing how a build treats polygon closing
  // duplicates (a build that appends one anyway is detected and healed
  // with a single removeVertex).
  function splineBulkWrite(seq) {
    try {
      if (typeof splineModel.setDataFromGeometry !== 'function')
        return false
      const wkt = splineSeqToWkt(seq, false)
      if (wkt === null)
        return false
      const geom = GeometryUtils.createGeometryFromWkt(wkt)
      splineModel.setDataFromGeometry(geom, splineModel.crs)
      let verts = splineModel.vertices
      if (verts.length === seq.length + 1 &&
          verts[verts.length - 1].x === seq[0].x &&
          verts[verts.length - 1].y === seq[0].y) {
        splineModel.removeVertex()
        verts = splineModel.vertices
      }
      if (verts.length !== seq.length)
        return false
      const first = verts[0]
      const last = verts[verts.length - 1]
      if (first.x !== seq[0].x || first.y !== seq[0].y ||
          last.x !== seq[seq.length - 1].x ||
          last.y !== seq[seq.length - 1].y)
        return false
      return true
    } catch (error) {
      return false
    }
  }

  // Rebuild the model to hold the smoothed curve ending on the crosshair:
  // reset/peel -> addVertexFromPoint for every curve point ->
  // removeVertex() drops the trailing floating duplicate, leaving the
  // last curve point (the crosshair) as the floating vertex.
  function splineRebuildModel() {
    if (!splineArmed || splineModel === null)
      return
    let cross = null
    let closed = false
    try {
      if (splineModel.frozen === true)
        return
      const cc = splineModel.currentCoordinate
      cross = { x: cc.x, y: cc.y, z: cc.z }
      closed = splineIsClosed()
    } catch (error) {
      return
    }
    // Live preview runs on a capped sample density — recomputing the whole
    // curve at the desktop's maxSegments (default 200/segment) every 40 ms
    // tick is what made long freehand strokes lag. Confirm rebuilds at the
    // full density (splineConfirmSequence), so saved quality is untouched.
    const seq = splineBuildSequence(
        splineControls.concat([cross]), closed,
        splineTightness, splineTolerance,
        Math.min(splineMaxSegments, splineLiveMaxSegments),
        null, splineDensity())
    if (seq.length < 2)
      return
    splineMutating = true
    try {
      if (splineWriteSequence(seq))
        splineLastCross = cross
      splineLastSeqFull = false
    } finally {
      splineMutating = false
    }
  }

  // After a quiet moment (no crosshair moves or vertex changes for
  // splineIdleTimer.interval), rewrite the model at the full confirm
  // density: the expensive many-vertex write happens while the user is
  // reaching for ✓, and the confirm rewrite then only has to diff the
  // crosshair tail — a handful of invokable calls instead of the whole
  // curve. Open lines get that for free (idle and confirm curves share
  // everything but the crosshair segment). Closed rings (v26) write the
  // CONFIRM-shaped ring plus the crosshair as floating tail
  // (splineRingIdleSequence) instead of the crosshair-rotated live
  // ring: no rotation of the crosshair-free confirm ring can share a
  // prefix with a sequence that must END on the crosshair, so aligning
  // the idle write to the confirm shape is the only way rings get the
  // tail-only confirm — previously every polygon ✓ was a full
  // reset + per-vertex rewrite, O(N^2) in QField signal handling.
  function splineIdleUpgrade() {
    if (splineMutating || !splineArmed || splineModel === null)
      return
    if (splineLastSeqFull || splineRebuildTimer.running)
      return
    if (splineControls.length < 2)
      return
    let cross = null
    let closed = false
    try {
      if (splineModel.frozen === true)
        return
      const cc = splineModel.currentCoordinate
      cross = { x: cc.x, y: cc.y, z: cc.z }
      closed = splineIsClosed()
    } catch (error) {
      return
    }
    const density = splineDensity()
    let seq = null
    if (closed)
      seq = splineRingIdleSequence(splineControls, cross,
          splineTightness, splineTolerance, splineMaxSegments,
          splineFullCache, density)
    if (seq === null)
      seq = splineBuildSequence(
          splineControls.concat([cross]), closed,
          splineTightness, splineTolerance, splineMaxSegments,
          splineFullCache, density)
    if (seq.length < 2)
      return
    splineMutating = true
    try {
      if (splineWriteSequence(seq)) {
        splineLastCross = cross
        splineLastSeqFull = true
        console.log('LGS spline idle: ' + seq.length + ' pts' +
                    (closed ? ' (ring)' : ''))
      }
    } finally {
      splineMutating = false
    }
  }

  // Pre-compute the full-density segment blocks for the committed
  // controls while the user is still drawing, so the confirm-time curve
  // assembly finds (almost) every segment already cached. The result is
  // discarded — the side effect on splineFullCache is the point.
  function splineWarmCache() {
    if (splineMutating || !splineArmed || splineModel === null ||
        splineControls.length < 3)
      return
    let closed = false
    try {
      if (splineModel.frozen === true)
        return
      closed = splineIsClosed()
    } catch (error) {
      return
    }
    splineConfirmSequence(splineControls, closed, splineTightness,
        splineTolerance, splineMaxSegments, splineFullCache, splineDensity())
  }

  // Confirm fixup. QField's DigitizingToolbar.confirm() freezes the
  // model FIRST and harvests the geometry after — and the harvest
  // (pointSequence) includes the floating crosshair vertex. frozen=true
  // emits frozenChanged synchronously, so this runs before the harvest:
  // rewrite the model to the committed-only curve so the crosshair (and
  // whatever jiggle the confirm tap gave it) never reaches the feature.
  // The invokable write path needs setCurrentCoordinate, which is
  // frozen-guarded, so briefly unfreeze — splineMutating suppresses the
  // nested frozenChanged/vertexCountChanged/currentCoordinateChanged
  // handlers, and refreezing before returning means the confirm flow
  // continues with the state it just set. Once refrozen the same guard
  // pins the floating vertex against any further crosshair movement.
  // (Known gap: with position-averaged vertex adding QField calls
  // removeVertex() after the freeze, which would strip the curve's true
  // endpoint — averaged GNSS adds + spline drawing is not a supported
  // combination.)
  function splineOnConfirmFreeze() {
    if (splineMutating || !splineArmed || splineModel === null)
      return
    let closed = false
    try {
      closed = splineIsClosed()
    } catch (error) {
      return
    }
    // This runs synchronously inside the ✓ tap — it must be FAST or the
    // button feels dead. The segment cache (warmed while drawing) makes
    // the full-density math ~free, and splineWriteSequence prefix-diffs
    // against the idle upgrade's full-density write so lines AND rings
    // (v26: the idle write is confirm-shaped for rings too) only rewrite
    // the crosshair tail. Cold confirms (no idle pause) may take the
    // one-call bulk path instead of the per-vertex loop.
    const started = Date.now()
    const wasWarm = splineLastSeqFull  // read BEFORE the write clears it
    const density = splineDensity()
    const seq = splineConfirmSequence(splineControls, closed,
        splineTightness, splineTolerance, splineMaxSegments,
        splineFullCache, density)
    if (seq === null || seq.length < 2)
      return
    splineMutating = true
    try {
      splineModel.frozen = false
      try {
        splineWriteSequence(seq, true)
        splineLastSeq = null
      } finally {
        splineModel.frozen = true  // relock before confirm() resumes
      }
    } catch (error) {
    } finally {
      splineMutating = false
    }
    // On-device diagnosis line — warm confirms should be 'mode tail'
    // with prefix ≈ pts and a few ms; 'mode reset' + cold on a big ring
    // means the idle upgrade never landed before ✓.
    const stats = splineWriteStats
    console.log('LGS spline confirm: ' + (Date.now() - started) + ' ms, ' +
                seq.length + ' pts, ' + splineControls.length + ' controls' +
                ', tol ' + splineEffectiveTolerance(splineTolerance, density) +
                (stats !== null ? ', mode ' + stats.mode +
                                  ', prefix ' + stats.prefix : '') +
                (wasWarm ? ', warm' : ', cold'))
  }

  // Same confirm fixup for NATIVE (spline-off) line/polygon digitizing —
  // always on while the sidecar is present. Here the model holds exactly
  // [committed vertices..., floating crosshair], so dropping the floating
  // vertex is the whole fix: removeVertex() has no frozen guard (QField
  // itself calls it while frozen in its averaged-position branch) and the
  // frozen setCurrentCoordinate guard then pins the model until harvest.
  // Skipped when the crosshair is GNSS-driven (positionLocked /
  // averagedPosition): the confirm tap cannot jiggle a GNSS crosshair,
  // and QField strips the floating vertex ITSELF after an averaged add
  // (lastAdditionAveraged) — stripping here too would eat a real vertex.
  // (Residual edge: averaged add, then unlock AND disable averaging
  // before ✓ — both flags read false, QField still strips → one vertex
  // short. Accepted as vanishingly rare.)
  function nativeConfirmFreeze() {
    if (splineMutating || splineModel === null)
      return
    try {
      const gt = Number(splineModel.geometryType)
      const isRing = gt === Number(Qgis.GeometryType.Polygon)
      if (!isRing && gt !== Number(Qgis.GeometryType.Line))
        return
      if (splineLocator && (splineLocator.positionLocked === true ||
                            splineLocator.averagedPosition === true))
        return
      // Committed vertices only (floating excluded): below the minimum
      // for a valid shape, keep native behaviour — the crosshair vertex
      // is what makes the geometry valid there.
      const committed = Number(splineModel.vertexCount) - 1
      if (committed < (isRing ? 3 : 2))
        return
      splineMutating = true
      try {
        splineModel.removeVertex()
      } finally {
        splineMutating = false
      }
    } catch (error) {}
  }

  // Put the raw control points back (disarming mid-digitize): committed
  // vertices = the controls, floating vertex re-takes the crosshair on
  // its next move via the app's own binding.
  function splineRestoreControls() {
    if (splineModel === null || splineControls.length === 0) {
      splineResetSession()
      return
    }
    splineMutating = true
    try {
      if (splineModel.frozen === true)
        return
      splineModel.reset(true)
      for (let i = 0; i < splineControls.length; i++)
        splineModel.addVertexFromPoint(GeometryUtils.point(
            splineControls[i].x, splineControls[i].y, splineControls[i].z))
      splineExpected = Number(splineModel.vertexCount)
      splineLastSeq = null
    } catch (error) {
    } finally {
      splineMutating = false
    }
    splineResetSession()
  }

  // ----------------------------------------------------------------
  // Control-point markers (desktop parity: dots at the clicked points)
  // ----------------------------------------------------------------
  function updateSplineMarkers() {
    if (!splineArmed || splineControls.length === 0 ||
        !canvas || !scaleSettings) {
      splineMarkerPositions = []
      return
    }
    // Cap the dot count: replacing the marker array rebuilds the
    // Repeater's delegates every throttled pan tick, so long strokes are
    // index-step-sampled to <= 100 dots (last control always shown).
    const n = splineControls.length
    const step = n > 100 ? Math.ceil(n / 100) : 1
    const out = []
    try {
      for (let i = 0; i < n; i += step) {
        const p = scaleSettings.coordinateToScreen(GeometryUtils.point(
            splineControls[i].x, splineControls[i].y))
        out.push({ x: Number(p.x), y: Number(p.y) })
      }
      if (step > 1 && (n - 1) % step !== 0) {
        const p = scaleSettings.coordinateToScreen(GeometryUtils.point(
            splineControls[n - 1].x, splineControls[n - 1].y))
        out.push({ x: Number(p.x), y: Number(p.y) })
      }
    } catch (error) {
      splineMarkerPositions = []
      return
    }
    splineMarkerPositions = out
  }

  Timer {
    // Coalesces rebuilds: vertex taps and crosshair pans both land here
    // via splineScheduleRebuild() (throttle semantics). The interval is
    // the perf tuning knob — 40 ms ≈ 25 curve updates/second while
    // panning; raise it if a device still stutters.
    id: splineRebuildTimer
    interval: 40
    repeat: false
    onTriggered: plugin.splineRebuildModel()
  }

  Timer {
    // Same throttle for the control-point dots: extentChanged fires every
    // pan frame, and replacing the marker array rebuilds the Repeater's
    // delegates — cap that at the same rate as the curve.
    id: splineMarkerTimer
    interval: 40
    repeat: false
    onTriggered: plugin.updateSplineMarkers()
  }

  Timer {
    // Debounced (restarted by every live change, fires only after a
    // quiet moment) full-density model upgrade — see splineIdleUpgrade().
    id: splineIdleTimer
    interval: 350
    repeat: false
    onTriggered: plugin.splineIdleUpgrade()
  }

  Timer {
    // Deferred segment-cache warming after a committed-control change —
    // see splineWarmCache().
    id: splineWarmTimer
    interval: 80
    repeat: false
    onTriggered: plugin.splineWarmCache()
  }

  Timer {
    // Fallback poll: retries the locator lookup if startup raced QField's
    // component creation, and follows digitize <-> editor model switches
    // even if the change signal is missed.
    id: splineWatchTimer
    interval: 500
    repeat: true
    running: false
    onTriggered: {
      // No featureSpline early-out: the locator/model are also needed by
      // the always-on native confirm fixup.
      if (plugin.splineLocator === null)
        plugin.initSpline()
      else
        plugin.refreshSplineModel()
    }
  }

  Connections {
    target: plugin.splineLocator
    ignoreUnknownSignals: true
    function onRubberbandModelChanged() {
      plugin.refreshSplineModel()
    }
  }

  Connections {
    target: plugin.splineModel
    ignoreUnknownSignals: true
    function onVertexCountChanged() {
      plugin.splineOnCountChanged()
    }
    function onCurrentCoordinateChanged() {
      plugin.splineOnCrosshairMoved()
    }
    function onFrozenChanged() {
      // RubberbandModel.reset() removes the vertices BEFORE it unfreezes,
      // so the count change after a native confirm/cancel arrives while
      // frozen and is ignored — catch the thaw here instead. The FREEZE
      // is the start of a native confirm: rewrite the model to the
      // committed-only curve before the geometry is harvested.
      if (plugin.splineMutating)
        return
      try {
        if (plugin.splineModel && plugin.splineModel.frozen === true) {
          // Exclusive paths: armed = committed-only curve rebuild;
          // native = drop the floating crosshair vertex.
          if (plugin.splineArmed)
            plugin.splineOnConfirmFreeze()
          else
            plugin.nativeConfirmFreeze()
          return
        }
        if (plugin.splineModel && plugin.splineModel.frozen !== true &&
            Number(plugin.splineModel.vertexCount) <= 1)
          plugin.splineResetSession()
      } catch (error) {}
    }
    function onVectorLayerChanged() {
      if (!plugin.splineMutating)
        plugin.splineResetSession()
    }
  }

  Connections {
    // Keep the control-point dots glued to the map while it pans/zooms
    // (throttled — extentChanged fires every pan frame).
    target: plugin.scaleSettings
    ignoreUnknownSignals: true
    function onExtentChanged() {
      if (plugin.splineArmed && plugin.splineControls.length > 0 &&
          !splineMarkerTimer.running)
        splineMarkerTimer.start()
    }
  }

  Item {
    id: splineMarkers
    visible: plugin.featureSpline && plugin.splineArmed &&
             plugin.splineMarkerPositions.length > 0
    z: 1

    Repeater {
      model: plugin.splineMarkerPositions

      delegate: Rectangle {
        required property var modelData
        x: modelData.x - 5
        y: modelData.y - 5
        width: 10
        height: 10
        radius: 5
        color: 'white'
        border.color: 'black'
        border.width: 2
      }
    }
  }

  // ================================================================
  // RESHAPE — multi-polygon reshape on the active layer (port of
  // map_cleaning/tools/reshape_spline_tool.py — keep the semantics in
  // sync). The cut line lives on the plugin's OWN RubberbandModel, so
  // this never touches QField's digitizing model (no interference with
  // the spline feature or the native confirm fixup). The reshape op
  // itself is GeometryUtils.reshapeFromRubberband — the exact native
  // call behind QField's single-feature reshape editor — looped over
  // every targeted polygon inside one edit session.
  // ================================================================

  property int reshapeStep: 0       // 0=off, 1=pick targets, 2=draw
  // True while a digitizing/measure session is active — the app state
  // machine sets mainWindow.currentRubberband (null in browse mode).
  property bool reshapeEditingActive: false
  property var reshapeDashboard: null  // item exposing activeLayer, cached
  property var reshapeLayer: null      // active layer locked on entry
  property var reshapePicks: []        // [{id, feature}] optional target picks
  property var reshapeControls: []     // [{x,y,z}] tapped points, map CRS
  property var reshapeCache: ({})      // spline segment cache, per session
  property var reshapePlan: []         // [{fid, wkt, feature}] at confirm
  // Session undo stack (v33), newest last. It used to be a single
  // payload, reachable only from a step the tool left as soon as you
  // pressed Done — so one tap and the undo was gone with no UI that
  // could ever reach it again. It is also NOT cleared when the tool
  // exits: a digitizing session starting force-exits reshape, and that
  // must not throw away what you already changed.
  property var reshapeHistory: []
  property string reshapeResultText: ''
  // True between the confirm tap and the end of the write. The work runs
  // a turn later (Qt.callLater) so the banner can actually paint it;
  // assigning the text inside the synchronous block, as before, meant
  // "Reshaping…" never appeared at all.
  property bool reshapeBusy: false
  // True while the target set came from QField's own selection rather
  // than from taps inside the tool.
  property bool reshapeLockedSelection: false
  property var reshapeMarkerPositions: []
  // Freehand stroke state (v24) — stylus draws, finger pans.
  property var reshapeUndoStack: []    // points per action: tap=1, stroke=n
  property int reshapeStrokeStart: -1  // -1 idle, -2 ignoring this stroke
  // Raw stroke buffer (v33). Map coordinates, one entry per pointer
  // move, MUTATED IN PLACE and never reassigned while the pen is down:
  // assigning a var property emits its change signal, which re-evaluates
  // the banner text and both button enabled bindings, and .slice()ing it
  // per move made the stroke quadratic on its own. It is thinned to
  // control points exactly once, on release.
  property var reshapeStrokeRaw: []
  // The control spacing, latched at stroke begin. Reading
  // splineMinNodeMapUnits() per move breaks the tool's own rule (the
  // density is latched once per stroke) and cost a C++ property read
  // every sample.
  property real reshapeStrokeGate: 0
  // The sequence reshapeModel currently holds, so the next write can
  // diff against it instead of resetting. null means "do not trust the
  // model's contents" — which is exactly what a live stroke appending
  // straight onto the model leaves behind.
  property var reshapeLastSeq: null
  property var reshapeSettingsItem: null // QField settings (mouseAsTouchScreen)
  property var reshapeFeatureFormItem: null // QField feature form, cached
  property var reshapeSelectionItem: null   // its FeatureListModelSelection
  property var reshapeSelectionModel: null  // its MultiFeatureListModel
  // Last non-empty QField selection seen, {layer, picks}. QField's
  // identify refills that model on every tap and clears it when the form
  // hides, so by the time the user has closed the form and reached the
  // pill a live read can already be empty. The live read still wins; the
  // latch only stands in for it.
  property var reshapeSelectionLatch: null
  // Conditioning constants (v32). Dedupe epsilon in POINTS so it scales
  // with the view like every other drawing tolerance — 0.5 pt is well
  // under the 8 pt stroke gate, so conditioning can only ever remove
  // capture noise, never drawn shape. The loop cap bounds the O(n²)
  // self-intersection scan on the final splined sequence.
  readonly property real reshapeDedupePoints: 0.5
  readonly property int reshapeLoopCap: 2000
  // Auto-repair ladder constants (v32). The probe WKT cap guards the
  // expression parser (a 10k-vertex LINESTRING can defeat it and the
  // scan dies as 'no candidates'); repair decimates at 2 pt; end
  // extension starts at 24 pt on screen and doubles per iteration.
  readonly property int reshapeProbeWktCap: 64000
  // Map/layer CRS authids, read once per reshape session.
  property var reshapeCrsCache: null
  // Segment cache for the repair rung's differently-decimated controls.
  property var reshapeRepairCache: ({})
  // Coarser than the CONTROL spacing, not the capture gate. At 2.0 it
  // was FINER than splineMinNodePx (8), so splineDecimate could never
  // remove a control and rung 2 could never produce a line different
  // from rung 1: the three-attempt ladder was really two. The comment
  // that justified 2.0 had the inequality backwards.
  readonly property real reshapeRepairPoints: 16.0
  readonly property real reshapeExtendStartPoints: 24
  // Three doublings: 24, 48, 96 pt. Six let a stroke that stopped
  // anywhere inside a polygon be shot out in a straight line for up to
  // ~770 pt and reported as "repaired automatically". The case this rung
  // exists for — the pen skidded and stopped a few mm short of the
  // boundary — is covered by the first two.
  readonly property int reshapeExtendMaxIter: 3
  // Digitisation style (v32): 'tap' = point by point, 'free' = stylus
  // freehand. Persisted, and the spline arming is remembered PER STYLE
  // ('freehand + spline' and 'tap + straight' are both coherent working
  // styles a mapper flips between). Reshape stopped sharing the
  // digitizing tool's lgs_spline_armed switch at v32 — that key now
  // only seeds the first read.
  // v33: 'free' is the default. The tool exists to redraw an edge by
  // hand, and opening in Tap put the freehand DragHandler behind two
  // deliberate actions (Draw line, then the Freehand pill) - a user who
  // tapped the pill and drew got a disabled handler and a panning map,
  // which is exactly the "freehand doesn't work" report. A saved
  // lgs_reshape_style still wins, so Tap is one pill away and sticks.
  property string reshapeStyle: 'free'
  property bool reshapeSplineArmed: false

  function reshapeSplineKey() {
    return reshapeStyle === 'free' ? 'lgs_reshape_spline_free'
                                   : 'lgs_reshape_spline_tap'
  }

  // The spline's default is per style, and for freehand it is ON: the
  // pen draws a smooth line, and letting it snap to an 8 pt chord chain
  // on lift (~0.3 mm facets on a 3 mm wiggle) is exactly the faceting
  // the spline exists to prevent. Tap keeps the digitizing tool's
  // setting as its seed, as before. A saved per-style choice wins.
  function reshapeSplineDefault() {
    return reshapeStyle === 'free'
        ? '1' : projVar('lgs_spline_armed', '0')
  }

  function reshapeLoadStyle() {
    reshapeStyle = projVar('lgs_reshape_style', 'free') === 'tap'
        ? 'tap' : 'free'
    reshapeSplineArmed = featureSpline &&
        projVar(reshapeSplineKey(), reshapeSplineDefault()) === '1'
  }

  function setReshapeStyle(style) {
    if (style !== 'tap' && style !== 'free')
      return
    if (reshapeStyle === style)
      return
    reshapeStyle = style
    saveVar('lgs_reshape_style', style)
    reshapeSplineArmed = featureSpline &&
        projVar(reshapeSplineKey(), reshapeSplineDefault()) === '1'
    if (style === 'free')
      toast(qsTr('Freehand — stylus draws, finger pans'))
    // Drawn points are kept across a style switch: controls are
    // style-agnostic and the undo stack is per action either way.
    if (reshapeStep === 2)
      reshapeRebuildPreview()
  }

  function toggleReshapeSpline() {
    if (!featureSpline)
      return
    reshapeSplineArmed = !reshapeSplineArmed
    saveVar(reshapeSplineKey(), reshapeSplineArmed ? '1' : '0')
    if (reshapeStep === 2)
      reshapeRebuildPreview()
  }

  // Dedupe epsilon in map units; 0 (unreadable map settings) degrades
  // to exact-coincident removal only.
  function reshapeConditionEps() {
    try {
      const perPoint = Number(canvas.mapSettings.mapUnitsPerPoint)
      if (isFinite(perPoint) && perPoint > 0)
        return perPoint * reshapeDedupePoints
    } catch (error) {}
    return 0
  }

  RubberbandModel {
    id: reshapeModel
    frozen: false
    geometryType: Qgis.GeometryType.Line
  }

  // Mirror of QField's own Rubberband.qml wrapper: a bare RubberbandShape
  // draws NOTHING — it only computes screen-space `polylines`; the child
  // Shape/ShapePath does the actual drawing. And it must NEVER be
  // anchored or sized: its C++ updateTransform() drives the item's own
  // x/y/scale to keep the baked polyline glued to the map through
  // pan/zoom, and anchors would override that (geometry lands
  // off-screen). Parent it to the canvas and leave the geometry alone.
  RubberbandShape {
    id: reshapeShape
    visible: plugin.reshapeStep === 2
    model: reshapeModel
    mapSettings: plugin.scaleSettings
    geometryType: Qgis.GeometryType.Line
    // Dodger blue, desktop reshape-spline rubber band parity.
    color: '#961E90FF'
    outlineColor: '#64FFFFFF'
    lineWidth: 3
    z: 1

    // Read the polyline ONCE (v33). RubberbandShape recomputes
    // `polylines` on every model change, and both ShapePaths below were
    // reading polylines[0] independently — doubling the conversion on
    // every vertex of every write.
    readonly property var linePath: polylines.length > 0 ? polylines[0] : []

    Shape {
      anchors.fill: parent

      ShapePath {
        strokeColor: reshapeShape.outlineColor
        strokeWidth: reshapeShape.lineWidth / reshapeShape.scale + 2
        strokeStyle: ShapePath.SolidLine
        fillColor: 'transparent'
        joinStyle: ShapePath.RoundJoin
        capStyle: ShapePath.RoundCap

        PathPolyline {
          path: reshapeShape.linePath
        }
      }

      ShapePath {
        strokeColor: reshapeShape.color
        strokeWidth: reshapeShape.lineWidth / reshapeShape.scale
        strokeStyle: ShapePath.SolidLine
        fillColor: 'transparent'
        joinStyle: ShapePath.RoundJoin
        capStyle: ShapePath.RoundCap

        PathPolyline {
          path: reshapeShape.linePath
        }
      }
    }
  }

  function initReshape() {
    try {
      if (reshapeDashboard === null)
        reshapeDashboard = iface.findItemByObjectName('dashBoard')
    } catch (error) {}
    try {
      // Only read for mouseAsTouchScreen — a missing item falls back to
      // accepting the mouse for freehand (desktop convenience).
      if (reshapeSettingsItem === null)
        reshapeSettingsItem = iface.findItemByObjectName('qfieldSettings')
    } catch (error) {}
    try {
      const form = reshapeFeatureForm()
      if (form !== null) {
        if (reshapeSelectionItem === null)
          reshapeSelectionItem = form.selection
        if (reshapeSelectionModel === null) {
          reshapeSelectionModel = reshapeSelectionItem !== null &&
                                  reshapeSelectionItem !== undefined
              ? reshapeSelectionItem.model : form.model
        }
      }
    } catch (error) {}
    updateReshapeEditingActive()
  }

  // ----------------------------------------------------------------
  // QField's selection (v33)
  //
  // It is NOT a QgsVectorLayer selection — nothing in QField ever calls
  // selectByIds or removeSelection on a layer — so layer.selectedFeature
  // Ids(), which is how the desktop tool does this, can never see it. It
  // lives in the feature form's MultiFeatureListModel and is painted by
  // QField's own highlight.
  //
  // And there are TWO things a user means by "selected":
  //   * selectedFeatures/selectedCount — the multi-select set, filled
  //     only by explicitly toggling items into it;
  //   * focusedFeature/focusedLayer — the everyday "I tapped that
  //     polygon and it went pink", where selectedCount is still 0.
  // Reading only the first would have tested as "it still reshapes
  // everything", which is the complaint.
  // ----------------------------------------------------------------
  function reshapeSelectionPicks() {
    const out = { layer: null, picks: [] }
    try {
      const model = reshapeSelectionModel
      if (model !== null && model !== undefined &&
          Number(model.selectedCount) > 0) {
        const features = model.selectedFeatures
        const layer = model.selectedLayer
        if (features !== undefined && features !== null &&
            layer !== undefined && layer !== null) {
          for (let i = 0; i < features.length; i++)
            out.picks.push({ id: features[i].id, feature: features[i] })
          if (out.picks.length > 0) {
            out.layer = layer
            return out
          }
        }
      }
    } catch (error) {}
    try {
      const sel = reshapeSelectionItem
      if (sel !== null && sel !== undefined &&
          Number(sel.focusedItem) >= 0) {
        const feature = sel.focusedFeature
        const layer = sel.focusedLayer
        if (feature !== undefined && feature !== null &&
            layer !== undefined && layer !== null &&
            Number(feature.id) >= 0) {
          out.layer = layer
          out.picks.push({ id: feature.id, feature: feature })
          return out
        }
      }
    } catch (error) {}
    // Third case: QField's default, with the form NOT auto-opened, is a
    // one-row identify LIST — count 1, nothing focused, nothing
    // selected — and that single highlighted polygon is exactly what a
    // user points at and calls "selected". Read it through the model's
    // roles (MultiFeatureListModel::FeatureRole / LayerRole =
    // Qt::UserRole + 4 / + 6, stable in the header). Only one row: two or
    // more identified features is a list to choose from, not a choice.
    try {
      const model = reshapeSelectionModel
      const form = reshapeFeatureForm()
      if (model !== null && model !== undefined &&
          form !== null && form.visible && Number(model.count) === 1) {
        const index = model.index(0, 0)
        const feature = model.data(index, 260)
        const layer = model.data(index, 262)
        if (feature !== undefined && feature !== null &&
            layer !== undefined && layer !== null &&
            Number(feature.id) >= 0) {
          out.layer = layer
          out.picks.push({ id: feature.id, feature: feature })
        }
      }
    } catch (error) {}
    return out
  }

  function latchReshapeSelection() {
    if (reshapeStep !== 0)
      return
    const found = reshapeSelectionPicks()
    if (found.layer !== null && found.picks.length > 0) {
      found.at = Date.now()
      reshapeSelectionLatch = found
    }
  }

  // The latch is a bridge across QField clearing its own model as the
  // form hides — not a memory. A polygon tapped an hour ago, three
  // screens away, must not lock the next reshape and choose its layer
  // (the entry toast is transient and the sub-line is 12 pt; the user
  // would simply see their stroke refused). 60 s covers closing the form
  // and reaching the pill with room to spare.
  readonly property int reshapeSelectionLatchMs: 60000

  function reshapeSelectionLatched() {
    const latch = reshapeSelectionLatch
    if (latch === null || latch === undefined)
      return null
    if (!(Date.now() - Number(latch.at) <= reshapeSelectionLatchMs)) {
      reshapeSelectionLatch = null
      return null
    }
    return latch
  }

  function updateReshapeEditingActive() {
    // mainWindow.currentRubberband is the app state machine's own
    // signal: null in browse, the digitizing/measuring rubberband
    // otherwise. Unreadable (older/newer QField) counts as browse so
    // the pill stays usable.
    let active = false
    try {
      const rb = mainWindow.currentRubberband
      active = rb !== null && rb !== undefined
    } catch (error) {
      active = false
    }
    reshapeEditingActive = active
  }

  // The active layer is not on iface — it is a property of QField's
  // dashboard/project-info QML items (objectNames are QField Main.qml
  // conventions, so probe a few and remember whichever answers).
  function reshapeActiveLayer() {
    if (reshapeDashboard !== null) {
      try {
        const layer = reshapeDashboard.activeLayer
        if (layer !== null && layer !== undefined)
          return layer
      } catch (error) {}
    }
    for (const name of ['dashBoard', 'projectInfo', 'locatorBridge']) {
      try {
        const item = iface.findItemByObjectName(name)
        if (item === null || item === undefined)
          continue
        const layer = item.activeLayer
        if (layer !== null && layer !== undefined) {
          reshapeDashboard = item
          return layer
        }
      } catch (error) {}
    }
    return null
  }

  // Follow a legend/pill layer change while reshape is open but idle.
  // The tool locks its layer on entry and must keep it for the line
  // being drawn, so this only moves between lines — otherwise the line
  // on screen would silently belong to a layer it was not drawn for.
  // A non-polygon layer is ignored rather than breaking the session.
  function reshapeRelockLayer() {
    if (reshapeStep === 0 || reshapeControls.length > 0 || reshapeBusy)
      return
    try {
      const layer = reshapeActiveLayer()
      if (layer === null || layer === reshapeLayer)
        return
      if (evalExpr(layer, null, "layer_property(@layer, 'geometry_type')") !==
          'Polygon')
        return
      try {
        if (reshapeLayer !== null)
          reshapeLayer.removeSelection()
      } catch (error) {}
      reshapeLayer = layer
      reshapePicks = []
      reshapeLockedSelection = false
      reshapeResultText = ''
      reshapeCrsCache = null
      toast(qsTr('Reshape now targets %1').arg(reshapeLayerLabel()))
    } catch (error) {}
  }

  function reshapeLayerLabel() {
    try {
      return reshapeLayer ? String(reshapeLayer.name) : ''
    } catch (error) {
      return ''
    }
  }

  // ----------------------------------------------------------------
  // Mode lifecycle
  // ----------------------------------------------------------------
  function enterReshapeMode() {
    try {
      if (!canvas || canvas.width === undefined) {
        toast(qsTr('Reshape unavailable — no map canvas'))
        return
      }
      updateReshapeEditingActive()
      if (reshapeEditingActive) {
        toast(qsTr('Turn digitizing off first'))
        return
      }
      // A selection points at a layer as surely as the legend does, and
      // more recently — so it wins. Live read first; the latch stands in
      // only when QField has already cleared the model.
      let seeded = reshapeSelectionPicks()
      if (seeded.layer === null) {
        const latched = reshapeSelectionLatched()
        if (latched !== null)
          seeded = latched
      }
      let layer = seeded.layer
      if (layer !== null &&
          evalExpr(layer, null, "layer_property(@layer, 'geometry_type')") !==
              'Polygon') {
        seeded = { layer: null, picks: [] }
        layer = null
      }
      if (layer === null)
        layer = reshapeActiveLayer()
      if (layer === null) {
        toast(qsTr('Reshape unavailable — no active layer (tap one in the legend)'))
        return
      }
      const geomType = evalExpr(layer, null,
                                "layer_property(@layer, 'geometry_type')")
      if (geomType !== 'Polygon') {
        toast(qsTr('Reshape needs a polygon layer active in the legend'))
        return
      }
      // The model CRS decides how reshapeFromRubberband reprojects the
      // line into the layer — bail rather than reshape in a wrong CRS.
      let crsOk = false
      try {
        if (scaleSettings !== null) {
          reshapeModel.crs = scaleSettings.destinationCrs
          crsOk = true
        }
      } catch (error) {}
      if (!crsOk) {
        toast(qsTr('Reshape unavailable — map projection not readable'))
        return
      }
      reshapeLayer = layer
      reshapeCatcher.parent = canvas
      reshapeCatcher.anchors.fill = canvas
      reshapeBanner.parent = canvas
      reshapeBanner.anchors.horizontalCenter = canvas.horizontalCenter
      reshapeBanner.anchors.top = canvas.top
      reshapeBanner.anchors.topMargin = 60
      // No anchors/size on reshapeShape — see the comment on the item.
      reshapeShape.parent = canvas
      reshapeMarkers.parent = canvas
      reshapeMarkers.anchors.fill = canvas
      reshapePicks = []
      reshapeControls = []
      reshapeCache = ({})
      reshapeRepairCache = ({})
      reshapeLastSeq = null
      reshapeCrsCache = null
      reshapePlan = []
      reshapeResultText = ''
      reshapeMarkerPositions = []
      reshapeUndoStack = []
      reshapeStrokeStart = -1
      reshapeStrokeRaw.length = 0
      reshapeLockedSelection = false
      reshapeBusy = false
      reshapeModel.reset(true)
      reshapeLoadStyle()
      if (seeded.layer !== null && seeded.picks.length > 0) {
        // Straight to drawing: the targets are already chosen, and the
        // pick step would only be a screen to tap past.
        reshapePicks = seeded.picks
        reshapeLockedSelection = true
        reshapeSelectionLatch = null
        reshapeStep = 2
        // The selection chose the layer; make QField's active layer (and
        // so the layer-switch pill) say the same, or the legend would
        // contradict the banner for the whole session.
        if (featureLayerSwitch) {
          try {
            writeActiveLayer(layer)
          } catch (error) {}
        }
        updateReshapeSelection()
        splineRefreshDensity()
        toast(qsTr('Limited to the %1 polygon(s) you selected — long-press to change')
              .arg(reshapePicks.length))
      } else {
        reshapeStep = 1
        toast(qsTr('Tap polygons to limit reshape (optional), or just draw'))
      }
    } catch (error) {
      toast(qsTr('Reshape unavailable'))
    }
  }

  function exitReshapeMode() {
    try {
      if (reshapeLayer !== null)
        reshapeLayer.removeSelection()
    } catch (error) {}
    try {
      reshapeModel.reset(true)
    } catch (error) {}
    reshapeStep = 0
    reshapeLayer = null
    reshapePicks = []
    reshapeControls = []
    reshapeCache = ({})
    reshapeRepairCache = ({})
    reshapeLastSeq = null
    reshapeCrsCache = null
    reshapePlan = []
    reshapeResultText = ''
    reshapeMarkerPositions = []
    reshapeUndoStack = []
    reshapeStrokeStart = -1
    reshapeStrokeRaw.length = 0
    reshapeLockedSelection = false
    reshapeBusy = false
    // reshapeHistory deliberately survives: a digitizing session
    // starting force-exits this tool, and that must not throw away
    // reshapes you have already made. It is offered again on re-entry.
  }

  // ----------------------------------------------------------------
  // Tap handling
  // ----------------------------------------------------------------
  function reshapeTapOnUi(pos) {
    // Ignore taps landing on the banner or pill bar — overlapping
    // TapHandlers may deliver the same tap to the canvas catcher too
    // (same guard as clipTapOnUi, which hardcodes the clip items).
    try {
      const b = reshapeBanner.mapFromItem(reshapeCatcher, pos.x, pos.y)
      if (b.x >= 0 && b.y >= 0 &&
          b.x <= reshapeBanner.width && b.y <= reshapeBanner.height)
        return true
    } catch (error) {}
    try {
      const o = overlayBar.mapFromItem(reshapeCatcher, pos.x, pos.y)
      if (o.x >= 0 && o.y >= 0 &&
          o.x <= overlayBar.width && o.y <= overlayBar.height)
        return true
    } catch (error) {}
    try {
      if (layerSwitchBar.visible) {
        const l = layerSwitchBar.mapFromItem(reshapeCatcher, pos.x, pos.y)
        if (l.x >= 0 && l.y >= 0 &&
            l.x <= layerSwitchBar.width && l.y <= layerSwitchBar.height)
          return true
      }
    } catch (error) {}
    try {
      if (zDialog.visible) {
        const d = mainWindow.contentItem.mapFromItem(
            reshapeCatcher, pos.x, pos.y)
        if (d.x >= zDialog.x && d.y >= zDialog.y &&
            d.x <= zDialog.x + zDialog.width &&
            d.y <= zDialog.y + zDialog.height)
          return true
      }
    } catch (error) {}
    // QField's feature form (v33). QField's own canvas handler ignores
    // stylus points landing on it, and disables freehand entirely while
    // it is visible; now that a stroke can begin in the pick step, a pen
    // press over an open form would otherwise draw straight through it.
    try {
      const form = reshapeFeatureForm()
      if (form !== null && form.visible) {
        const f = form.mapFromItem(reshapeCatcher, pos.x, pos.y)
        if (f.x >= 0 && f.y >= 0 &&
            f.x <= form.width && f.y <= form.height)
          return true
      }
    } catch (error) {}
    return false
  }

  // QField's feature form item, probed and remembered - the same idiom
  // as reshapeActiveLayer's dashboard lookup. The objectName is a
  // QField Main.qml convention; a build that does not answer leaves
  // every caller inert rather than failing.
  function reshapeFeatureForm() {
    if (reshapeFeatureFormItem === null) {
      try {
        reshapeFeatureFormItem = iface.findItemByObjectName('featureForm')
      } catch (error) {}
    }
    if (reshapeFeatureFormItem === undefined)
      return null
    return reshapeFeatureFormItem
  }

  function updateReshapeSelection() {
    if (reshapeLayer === null)
      return
    let fids = []
    for (const entry of reshapePicks)
      fids.push(entry.id)
    try {
      if (fids.length === 0) {
        reshapeLayer.removeSelection()
        return
      }
      LayerUtils.selectFeaturesInLayer(reshapeLayer, fids)
    } catch (error) {
      try {
        reshapeLayer.selectByIds(fids)
      } catch (error2) {}
    }
  }

  function handleReshapePickToggle(pos) {
    try {
      if (reshapeStep !== 1 && reshapeStep !== 2)
        return
      if (reshapeTapOnUi(pos))
        return
      const hit = findHitInLayers([reshapeLayer], pos)
      if (hit === null) {
        toast(qsTr('No polygon here'))
        return
      }
      const before = reshapePicks.length
      reshapePicks = toggleClipPick(reshapePicks, hit.feature.id,
                                    hit.feature)
      // Once the user has edited the set by hand it is theirs, not
      // QField's, and the banner should stop calling it a selection.
      if (reshapePicks.length === 0)
        reshapeLockedSelection = false
      updateReshapeSelection()
      toast(reshapePicks.length > before
          ? qsTr('%1 target(s)').arg(reshapePicks.length)
          : qsTr('%1 target(s) left').arg(reshapePicks.length))
    } catch (error) {}
  }

  // Was this tap made with a finger? Unknown (an eventPoint without a
  // readable device) reads as "not a pen" on purpose: in freehand mode
  // that makes the tap inert rather than placing a stray point, which is
  // the behaviour v32 chose for finger taps and the safe direction.
  function reshapeTapIsTouch(eventPoint) {
    try {
      const device = eventPoint.device
      if (device === undefined || device === null)
        return null
      return device.type === PointerDevice.TouchScreen
    } catch (error) {}
    return null
  }

  function handleReshapeTap(pos, isTouch) {
    try {
      if (reshapeStep !== 1 && reshapeStep !== 2)
        return
      if (reshapeTapOnUi(pos))
        return
      if (reshapeStep === 2 && reshapeStyle === 'free') {
        // Freehand: the pen draws and places, the finger picks. An
        // unknown device does nothing — never a stray point.
        if (isTouch === true) {
          handleReshapePickToggle(pos)
          return
        }
        if (isTouch !== false)
          return
      }
      if (reshapeStep === 1) {
        const hit = findHitInLayers([reshapeLayer], pos)
        if (hit === null) {
          toast(qsTr('No polygon here'))
          return
        }
        reshapePicks = toggleClipPick(reshapePicks, hit.feature.id,
                                      hit.feature)
        updateReshapeSelection()
        return
      }
      const pt = canvas.mapSettings.screenToCoordinate(
          Qt.point(pos.x, pos.y))
      let next = reshapeControls.slice()
      next.push({ x: Number(pt.x), y: Number(pt.y), z: Number(pt.z) })
      reshapeControls = next
      reshapeUndoStack = reshapeUndoStack.concat([1])
      // Latch on draw actions, never on zoom — same rule as digitizing (v32).
      splineRefreshDensity()
      reshapeRebuildPreview()
    } catch (error) {}
  }

  // ----------------------------------------------------------------
  // Freehand stroke capture (v24) — stylus draws, finger pans. The
  // DragHandler on reshapeCatcher feeds these. A clean stylus tap
  // never activates it (dragThreshold 0 needs movement), so it falls
  // through to the TapHandler and tap placement keeps working.
  // ----------------------------------------------------------------
  // One line per stroke, so a device round trip can tell the three
  // candidate causes of "freehand does not draw" apart without
  // guessing: a handler that is not even enabled (wrong style or step),
  // a pointer QField never routes here (a pen reporting as a touch
  // screen), or a grab the canvas took away mid-stroke (which shows up
  // as a stroke that ends with a handful of points).
  function reshapeLogStroke(handler) {
    let device = '?'
    try {
      const d = handler.centroid.device
      if (d !== null && d !== undefined)
        device = String(d.type !== undefined ? d.type : d)
    } catch (error) {}
    console.log('LGS reshape stroke: begin, style ' + reshapeStyle +
                ', step ' + reshapeStep +
                ', enabled ' + handler.enabled +
                ', active ' + handler.active +
                ', device ' + device)
  }

  function reshapeStrokeBegin(pos) {
    // v33: a stroke may START in the pick step and promotes itself to
    // the draw step. Picking targets is optional, so requiring the
    // Draw line button first meant the pen did nothing at all on the
    // screen the tool opens on. A tap still picks in step 1; a drag
    // draws.
    if ((reshapeStep !== 1 && reshapeStep !== 2) || reshapeTapOnUi(pos)) {
      reshapeStrokeStart = -2
      return
    }
    if (reshapeStep === 1)
      reshapeStep = 2
    reshapeStrokeStart = reshapeControls.length
    // Latch once per stroke, never per move — every rebuild must agree
    // on one density or the segment cache thrashes (v32), and the same
    // rule now covers the capture spacing (v33).
    splineRefreshDensity()
    reshapeStrokeGate = splineMinNodeMapUnits()
    reshapeStrokeRaw.length = 0
    // Re-lay the committed line with its floating tail intact, so the
    // first stroke sample overwrites the duplicate and not a real point.
    try {
      reshapeWriteModel(reshapeSequence(), true)
    } catch (error) {}
    // AFTER that write, and not before it: the stroke then appends
    // straight onto the model, behind the prefix diff's back, so the
    // record the write just left would describe a model that has since
    // grown. The plan copes with a grown model, but the release write
    // should take the reset path deterministically rather than rely on
    // it.
    reshapeLastSeq = null
    reshapeStrokeMove(pos)
  }

  // O(1) per pointer move, and deliberately so: one screen-to-map
  // conversion, one push onto a buffer mutated IN PLACE, and one append
  // to the rubberband so the ink follows the pen. That is exactly what
  // QField's own freehand digitizing does. Everything that used to
  // happen here — a whole-array copy, a var property assignment that
  // re-evaluated the banner and both button bindings, and a 40 ms timer
  // that re-conditioned, re-splined at FULL density and rewrote every
  // vertex of the model — now happens once, on release.
  //
  // Capture is UNGATED. The spacing is applied on release by
  // splineDecimate, which picks the same control points the live gate
  // picked (tests/reshape_freehand_harness.js pins that prefix for
  // prefix on 800/1600/3200-move strokes), so the saved curve is
  // unchanged and only the ink is new.
  function reshapeStrokeMove(pos) {
    if (reshapeStrokeStart < 0 || reshapeStep !== 2)
      return
    try {
      const pt = canvas.mapSettings.screenToCoordinate(
          Qt.point(pos.x, pos.y))
      const x = Number(pt.x)
      const y = Number(pt.y)
      const n = reshapeStrokeRaw.length
      // Coincident samples only — a pen resting still reports moves.
      if (n > 0 && reshapeStrokeRaw[n - 1].x === x &&
          reshapeStrokeRaw[n - 1].y === y)
        return
      const z = Number(pt.z)
      reshapeStrokeRaw.push({ x: x, y: y, z: z })
      reshapeModel.addVertexFromPoint(isFinite(z)
          ? GeometryUtils.point(x, y, z)
          : GeometryUtils.point(x, y))
    } catch (error) {}
  }

  function reshapeStrokeEnd() {
    const start = reshapeStrokeStart
    reshapeStrokeStart = -1
    if (start < 0 || reshapeStep !== 2) {
      reshapeStrokeRaw.length = 0
      return
    }
    // Thin the raw stroke to control points, once. splineDecimate always
    // keeps the last sample, so the true end of the stroke — the point
    // where the line has to leave the polygon — can no longer be gated
    // away, which the live gate could do.
    let thinned = splineDecimate(reshapeStrokeRaw, reshapeStrokeGate)
    reshapeStrokeRaw.length = 0
    if (thinned.length === 0) {
      reshapeRebuildPreview()
      return
    }
    // A pen tap with a pixel or two of jitter arrives here as a
    // two-sample "stroke" whose whole extent is under the control
    // spacing. That is a single point, not two near-coincident controls
    // with two overlapping dots.
    if (thinned.length === 2 && reshapeStrokeGate > 0) {
      const dx = thinned[1].x - thinned[0].x
      const dy = thinned[1].y - thinned[0].y
      if (dx * dx + dy * dy < reshapeStrokeGate * reshapeStrokeGate)
        thinned = [thinned[0]]
    }
    // fh marks stroke interiors: no white marker dot each (a stroke
    // would spawn hundreds). The two ends stay untagged so they keep
    // theirs. The spline math never reads the tag.
    let next = reshapeControls.slice()
    for (let i = 0; i < thinned.length; i++) {
      const p = thinned[i]
      const node = { x: p.x, y: p.y, z: p.z }
      if (i > 0 && i < thinned.length - 1)
        node.fh = true
      next.push(node)
    }
    reshapeControls = next
    // The whole stroke undoes as ONE action.
    reshapeUndoStack = reshapeUndoStack.concat([thinned.length])
    reshapeRebuildPreview()
    reshapeRecenterAfterStroke()
  }

  // Recentre when a stroke ends near the edge of the screen, so a long
  // edge can be drawn in strokes without stopping to pan — QField does
  // the same on its own freehand lift, off the same setting key. It is
  // gated on the recenter-hold feature as well as its pill: an export
  // that withheld that flag has no way to turn this off, so it does not
  // get it. Screen coordinates come from the catcher, which fills the
  // canvas, and the canvas carries right/bottom margins for the feature
  // form — so the thresholds are measured in window space.
  function reshapeRecenterAfterStroke() {
    if (!featureRecenterHold || recenterHoldActive)
      return
    try {
      const n = reshapeControls.length
      if (n === 0)
        return
      const last = reshapeControls[n - 1]
      const p = scaleSettings.coordinateToScreen(
          GeometryUtils.point(last.x, last.y))
      const w = mainWindow.contentItem.mapFromItem(reshapeCatcher, p.x, p.y)
      let fraction = 5
      try {
        if (typeof settings !== 'undefined' && settings !== null)
          fraction = Number(settings.value(recenterHoldKey, 5))
      } catch (error) {}
      if (!(fraction > 0))
        fraction = 5
      const threshold = Math.min(mainWindow.width, mainWindow.height) / fraction
      if (w.x < threshold || w.x > mainWindow.width - threshold ||
          w.y < threshold || w.y > mainWindow.height - threshold)
        scaleSettings.setCenter(GeometryUtils.point(last.x, last.y))
    } catch (error) {}
  }

  // ----------------------------------------------------------------
  // Line building (spline-armed = smoothed, otherwise straight)
  // ----------------------------------------------------------------
  // The reshape line's density bundle (v32). Before this existed the
  // splineConfirmSequence call below silently dropped the density
  // argument, so a spline-armed reshape line was built on the legacy
  // path: 200 raw Hermite samples per control segment pruned only at
  // the absolute tolerance. GEOS's reshape needs a clean line entering
  // and exiting the ring; that dense, jittery polyline defeated it and
  // every feature came back NothingHappened.
  function reshapeDensity() {
    return splineDensity()
  }

  function reshapeSequence() {
    // Condition the CONTROLS, not just the output: capture jitter must
    // never become a spline control point (v32). Loop removal here is
    // cheap — controls are already gated at 8 pt spacing.
    //
    // v33: the cap is reshapeLoopCap here too, not 0. The confirm path
    // conditioned with the cap and this one without, so the two splined
    // DIFFERENT control arrays and reshapeCache missed on every confirm
    // — a cold full-density spline each time. Above the cap neither
    // removes loops, which is the point: preview and saved line agree.
    const controls = reshapeConditionSequence(reshapeControls,
        reshapeConditionEps(), reshapeLoopCap)
    if (reshapeSplineArmed) {
      const seq = splineConfirmSequence(controls, false,
          splineTightness, splineTolerance, splineMaxSegments, reshapeCache,
          reshapeDensity())
      if (seq !== null)
        return seq
    }
    return controls
  }

  // The write PLAN, pure JS so tests/reshape_freehand_harness.js can
  // extract it: given the sequence the model is believed to hold, the
  // one we want, and the model's real vertex count, decide between
  // peeling the changed tail and rewriting from scratch.
  //
  // Successive writes differ only in their last segments (one more
  // control point, one more stroke), so the shared prefix is nearly the
  // whole line. Every addVertexFromPoint is a cross-language call that
  // makes QField rebuild the rubberband's screen polyline, which is what
  // made a long line cost O(N^2) to draw. Same idea, same arithmetic and
  // the same fallback rule as splineWriteSequence.
  function reshapeWritePlan(lastSeq, seq, modelCount, prefixLength) {
    let prefix = 0
    if (lastSeq !== null && lastSeq !== undefined &&
        isFinite(modelCount) && modelCount >= lastSeq.length) {
      prefix = prefixLength
      prefix = Math.min(prefix, lastSeq.length - 1, modelCount - 1,
                        seq.length - 1)
      if (prefix < 0)
        prefix = 0
    }
    const pops = modelCount - (prefix + 1)
    const incremental = pops + (seq.length - prefix) + 1
    const full = seq.length + 2
    if (prefix > 0 && pops >= 0 && incremental < full)
      return { mode: 'tail', prefix: prefix, pops: pops }
    return { mode: 'reset', prefix: 0, pops: 0 }
  }

  // The one writer of reshapeModel's geometry (v32/v33).
  //
  // The model keeps a floating tail vertex after every add, hence the
  // final removeVertex — but addVertexFromPoint SKIPS an add when two
  // consecutive points are exactly equal, and an unconditional remove
  // then eats the last REAL point: the line silently stops just short of
  // exiting the polygon. So the tail comes off only when the count says
  // it is really there, and the tail-diff branch VERIFIES the count
  // afterwards and rewrites from scratch if it does not agree. That
  // check is not optional: the diff is exactly the shape of write that
  // can hide a skipped add.
  //
  // keepFloating (v33) leaves the trailing floating vertex in place. The
  // model always keeps one, and addVertexFromPoint OVERWRITES it before
  // appending a fresh one — so a live stroke appending straight onto a
  // trimmed model would eat the last real control point (the junction
  // with the previous stroke or tap, exactly where a kink shows).
  // Leaving the duplicate means the first stroke sample overwrites the
  // duplicate instead.
  function reshapeWriteModel(seq, keepFloating) {
    let modelCount = NaN
    try {
      modelCount = Number(reshapeModel.vertexCount)
    } catch (error) {}
    const plan = reshapeWritePlan(reshapeLastSeq, seq, modelCount,
        reshapeLastSeq === null ? 0
            : splineCommonPrefixLength(reshapeLastSeq, seq))
    // Suppress the rubberband's screen rebuild for the duration of the
    // write: it is dirtied by every single vertex signal, and both
    // ShapePaths redraw from it. Imperative and read back, never a
    // binding — a build without the property just pays the old cost.
    let frozen = false
    try {
      if (reshapeShape.freeze !== undefined) {
        reshapeShape.freeze = true
        frozen = reshapeShape.freeze === true
      }
    } catch (error) {}
    try {
      if (plan.mode === 'tail') {
        for (let i = 0; i < plan.pops; i++)
          reshapeModel.removeVertex()
        reshapeAddPoints(seq, plan.prefix)
        if (keepFloating !== true)
          reshapeModel.removeVertex()
        let after = NaN
        try {
          after = Number(reshapeModel.vertexCount)
        } catch (error) {}
        const want = keepFloating === true ? seq.length + 1 : seq.length
        if (!isFinite(after) || after !== want)
          reshapeWriteModelReset(seq, keepFloating)
      } else {
        reshapeWriteModelReset(seq, keepFloating)
      }
      reshapeLastSeq = seq
    } catch (error) {
      reshapeLastSeq = null
    }
    if (frozen) {
      try {
        reshapeShape.freeze = false
        // Whether clearing freeze marks the shape dirty is not
        // knowable from the headers. Nudge the model once so the write
        // shows regardless: re-adding the last point overwrites the
        // floating vertex with itself and appends a new one, and the
        // remove takes it off again — the model ends exactly as it was,
        // and the shape has been told. NOT after a keepFloating write:
        // there the floating vertex already equals the last point, so
        // addVertex would skip the add (its double-vertex rule) and the
        // remove would eat the floating vertex the stroke is about to
        // rely on. The stroke's own first sample repaints that case.
        const n = seq.length
        if (n > 0 && keepFloating !== true) {
          const z = Number(seq[n - 1].z)
          reshapeModel.addVertexFromPoint(isFinite(z)
              ? GeometryUtils.point(seq[n - 1].x, seq[n - 1].y, z)
              : GeometryUtils.point(seq[n - 1].x, seq[n - 1].y))
          reshapeModel.removeVertex()
        }
      } catch (error) {}
    }
  }

  function reshapeAddPoints(seq, from) {
    for (let i = from; i < seq.length; i++) {
      const z = Number(seq[i].z)
      reshapeModel.addVertexFromPoint(isFinite(z)
          ? GeometryUtils.point(seq[i].x, seq[i].y, z)
          : GeometryUtils.point(seq[i].x, seq[i].y))
    }
  }

  function reshapeWriteModelReset(seq, keepFloating) {
    reshapeModel.reset(true)
    reshapeAddPoints(seq, 0)
    if (seq.length > 0 && keepFloating !== true) {
      let count = NaN
      try {
        count = Number(reshapeModel.vertexCount)
      } catch (error) {}
      if (!isFinite(count) || count > seq.length)
        reshapeModel.removeVertex()
    }
  }

  function reshapeRebuildPreview() {
    try {
      reshapeWriteModel(reshapeSequence())
    } catch (error) {}
    updateReshapeMarkers()
  }

  function reshapeUndoVertex() {
    if (reshapeControls.length === 0)
      return
    // Pop one ACTION, not one point — a freehand stroke pushed its
    // whole point count as a single stack entry (v24).
    let n = 1
    if (reshapeUndoStack.length > 0) {
      const stack = reshapeUndoStack.slice()
      n = Number(stack.pop())
      reshapeUndoStack = stack
    }
    if (!(n >= 1))
      n = 1
    if (n > reshapeControls.length)
      n = reshapeControls.length
    reshapeControls = reshapeControls.slice(0, reshapeControls.length - n)
    reshapeRebuildPreview()
  }

  function reshapeBackToPicks() {
    reshapeControls = []
    reshapeMarkerPositions = []
    reshapeUndoStack = []
    reshapeStrokeStart = -1
    reshapeLastSeq = null
    try {
      reshapeModel.reset(true)
    } catch (error) {}
    reshapeStep = 1
    updateReshapeSelection()
  }

  function reshapeLineWkt(seq) {
    // XY only — this WKT feeds the 2D intersects probe; the reshape op
    // reads its geometry (with Z) from the rubberband model directly.
    if (seq === undefined || seq === null)
      seq = reshapeSequence()
    if (seq.length < 2)
      return ''
    let coords = []
    for (const p of seq)
      coords.push(p.x + ' ' + p.y)
    return 'LINESTRING (' + coords.join(', ') + ')'
  }

  // The map and layer CRS authids, read ONCE per session. Two expression
  // evaluations each with their own parse and context build, and
  // reshapeEndNeedsExtend can ask for them up to fourteen times per
  // feature that refuses the line.
  function reshapeCrsPair() {
    if (reshapeCrsCache !== null)
      return reshapeCrsCache
    let pair = { layerCrs: '', mapCrs: '', readable: false }
    try {
      pair.layerCrs = evalExpr(reshapeLayer, null,
                               "layer_property(@layer, 'crs')")
      pair.mapCrs = evalExpr(reshapeLayer, null, '@project_crs')
      pair.readable = pair.layerCrs !== '' && pair.mapCrs !== ''
    } catch (error) {}
    reshapeCrsCache = pair
    return pair
  }

  // Wrap a geometry term (in map CRS) with the map→layer transform when
  // the layer disagrees. Unreadable authids skip the transform (LGS
  // exports are single-CRS mine grids) — worst case 0 candidates.
  function reshapeCrsTerm(term) {
    const pair = reshapeCrsPair()
    if (pair.readable && pair.layerCrs !== pair.mapCrs)
      return "transform(" + term + ", '" + pair.mapCrs + "', '" +
             pair.layerCrs + "')"
    return term
  }

  // The pad the candidate box needs beyond the sequence's own extent.
  // Zero for the normal probe; on the over-cap branch the probe is the
  // CONTROL polyline buffered by half its longest chord, which reaches
  // that far outside the sequence box — and under-padding there would
  // silently drop legitimate targets on exactly the long lines that
  // branch exists for.
  property real reshapeProbePad: 0

  function reshapeProbeExpr(seq) {
    const wkt = reshapeLineWkt(seq)
    reshapeProbePad = 0
    if (wkt === '')
      return ''
    let term = "geom_from_wkt('" + wkt + "')"
    if (wkt.length > reshapeProbeWktCap) {
      // A LINESTRING this long can defeat the expression parser, and
      // the whole scan then dies as 'no candidates'. Fall back to the
      // conditioned CONTROL polyline buffered by half its longest
      // chord — a superset of the real candidates (the spline never
      // strays further from its control polygon than that); the extras
      // just come back unchanged from the reshape itself (v32).
      const controls = reshapeConditionSequence(reshapeControls,
          reshapeConditionEps(), reshapeLoopCap)
      if (controls.length >= 2) {
        let coords = []
        let maxChord = 0
        for (let i = 0; i < controls.length; i++) {
          coords.push(controls[i].x + ' ' + controls[i].y)
          if (i > 0) {
            const dx = controls[i].x - controls[i - 1].x
            const dy = controls[i].y - controls[i - 1].y
            const chord = Math.sqrt(dx * dx + dy * dy)
            if (chord > maxChord)
              maxChord = chord
          }
        }
        term = "buffer(geom_from_wkt('LINESTRING (" + coords.join(', ') +
               ")'), " + (maxChord / 2) + ')'
        reshapeProbePad = maxChord / 2
      }
    }
    return 'intersects($geometry, ' + reshapeCrsTerm(term) + ')'
  }

  // ----------------------------------------------------------------
  // Target collection + execution
  // ----------------------------------------------------------------
  // The candidate box: the drawn line's extent, padded, in LAYER CRS.
  // Returns null when it cannot be built with confidence — including
  // when the two CRSs disagree and the reprojection is not certain,
  // because a partly-wrong box returns SOME features, the exact test
  // then filters them, and the result is a silent partial reshape. That
  // is worse than being slow, so an uncertain box falls back to the
  // whole-layer scan instead. (reshapeCrsTerm can degrade quietly
  // because a wrong transform there yields zero candidates and a loud
  // failure.)
  function reshapeSequenceRect(seq, pad) {
    if (seq.length < 2)
      return null
    let minX = seq[0].x, maxX = seq[0].x, minY = seq[0].y, maxY = seq[0].y
    for (let i = 1; i < seq.length; i++) {
      const p = seq[i]
      if (p.x < minX) minX = p.x
      if (p.x > maxX) maxX = p.x
      if (p.y < minY) minY = p.y
      if (p.y > maxY) maxY = p.y
    }
    let d = (maxX - minX + maxY - minY) * 0.01 + reshapeConditionEps()
    if (pad > d)
      d = pad
    try {
      let rect = GeometryUtils.createRectangleFromPoints(
          GeometryUtils.point(minX - d, minY - d),
          GeometryUtils.point(maxX + d, maxY + d))
      const pair = reshapeCrsPair()
      if (pair.readable && pair.layerCrs !== pair.mapCrs) {
        rect = GeometryUtils.reprojectRectangle(
            rect, scaleSettings.destinationCrs, reshapeLayer.crs)
        if (rect === null || rect === undefined)
          return null
      } else if (!pair.readable) {
        return null
      }
      return rect
    } catch (error) {}
    return null
  }

  function collectReshapeTargets() {
    reshapePlan = []
    const layer = reshapeLayer
    if (layer === null || reshapeControls.length < 2)
      return 0
    const seq = reshapeSequence()
    const probe = reshapeProbeExpr(seq)
    if (probe === '')
      return 0
    let pickFids = null
    if (reshapePicks.length > 0) {
      pickFids = {}
      for (const entry of reshapePicks)
        pickFids[entry.id] = true
    }
    let plan = []
    let failed = 0
    let iterator = null
    let scanFailed = false
    let boxed = false
    try {
      // A filter EXPRESSION derives no spatial index: the iterator reads
      // EVERY row in the layer and rebuilds the cut line in GEOS for each
      // one, so the scan cost the layer size times the line length —
      // seconds on a real Basemap, paid before anything appeared on
      // screen. The line's bounding box is a strict superset of what it
      // can touch, so let the provider's index hand back the handful and
      // keep the exact test for those. This is also what the desktop tool
      // has always done (QgsFeatureRequest(reshape_line.boundingBox())).
      // Feature-detected: a build without the rectangle iterator, or a
      // CRS pair we cannot trust, falls back to the v32 scan.
      const rect = reshapeSequenceRect(seq, reshapeProbePad)
      if (rect !== null) {
        try {
          iterator = LayerUtils.createFeatureIteratorFromRectangle(layer, rect)
          boxed = true
        } catch (error) {
          iterator = null
          boxed = false
        }
      }
      // The iterator honours the layer subsetString either way, so an
      // active Z filter means only VISIBLE polygons reshape — reshape
      // what you see.
      if (iterator === null)
        iterator = LayerUtils.createFeatureIteratorFromExpression(layer, probe)
      while (iterator.hasNext()) {
        const feature = iterator.next()
        if (pickFids !== null && pickFids[feature.id] !== true)
          continue
        // The box is a superset, so the exact test still decides. It is
        // affordable now precisely because it only ever runs on what the
        // index returned rather than on every row in the layer, and
        // running it for picks too keeps "none of the picked polygons
        // cross the line" an honest message.
        if (boxed && !exprTrue(evalExpr(layer, feature, probe)))
          continue
        // Pre-reshape snapshot, for the undo. QgsFeature.geometry is
        // readable straight from QML (QField reads it that way itself),
        // so take the value rather than serialising every candidate to
        // WKT through the expression engine — on cover polygons that
        // was the single most expensive thing the scan did. WKT stays
        // as the fallback for a build that will not hand it over.
        let geometry = null
        try {
          const g = feature.geometry
          if (g !== undefined && g !== null && g.isNull !== true)
            geometry = g
        } catch (error) {}
        let wkt = ''
        if (geometry === null) {
          wkt = evalExpr(layer, feature, 'geom_to_wkt($geometry)')
          if (wkt === '') {
            failed++
            continue
          }
        }
        plan.push({ fid: feature.id, geometry: geometry, wkt: wkt,
                    feature: feature })
      }
    } catch (error) {
      // A dead iterator is NOT 'no candidates' — reporting it as such
      // sends the user off redrawing a perfectly good line (v32).
      scanFailed = true
    }
    try {
      if (iterator !== null)
        iterator.close()
    } catch (error) {}
    if (failed > 0)
      toast(qsTr('%1 polygon(s) skipped (geometry read failed)').arg(failed))
    reshapePlan = plan
    if (scanFailed && plan.length === 0)
      return -1
    return plan.length
  }

  // ----------------------------------------------------------------
  // Auto-repair ladder (v32). Three attempts per feature, stopping at
  // the first Success: the line as drawn; the line rebuilt from
  // harder-decimated controls; the line with its ends extended past
  // the boundary of the specific polygon that refused it.
  // ----------------------------------------------------------------
  // Re-read a feature from the layer, edit buffer included, by fid.
  function reshapeFeatureById(layer, fid) {
    let iterator = null
    let found = null
    try {
      iterator = LayerUtils.createFeatureIteratorFromExpression(
          layer, '$id = ' + fid)
      if (iterator.hasNext())
        found = iterator.next()
    } catch (error) {}
    try {
      if (iterator !== null)
        iterator.close()
    } catch (error) {}
    return found
  }

  // Is the reshaped polygon still a valid geometry? An unreadable answer
  // counts as valid: this guard exists to catch a specific, visible
  // failure, not to block a reshape because a probe would not run.
  function reshapeResultIsValid(layer, fid) {
    try {
      // get_feature_by_id issues a fid request, which the provider
      // answers from its index and which still sees the edit buffer. A
      // filter expression on $id is not compiled to SQL by the OGR
      // provider, so the iterator below would read every row — one whole
      // layer per reshaped polygon, on the confirm path.
      const direct = evalExpr(layer, null,
          'is_valid(geometry(get_feature_by_id(@layer_id, ' + fid + ')))')
      if (exprTrue(direct))
        return true
      if (exprFalse(direct))
        return false
      const feature = reshapeFeatureById(layer, fid)
      if (feature === null)
        return true
      const answer = evalExpr(layer, feature, 'is_valid($geometry)')
      return !exprFalse(answer)
    } catch (error) {
      return true
    }
  }

  function reshapeApplyOnce(layer, fid) {
    try {
      return Number(GeometryUtils.reshapeFromRubberband(
          layer, fid, reshapeModel))
    } catch (error) {
      return -1
    }
  }

  // Attempt 2: decimate the controls at reshapeRepairPoints, re-spline
  // and condition the result. Its own cache, kept for the session: the
  // controls differ from the main line's so they must not pollute
  // reshapeCache, but a fresh ({}) per call meant every repair paid for
  // a cold full-density spline.
  function reshapeRepairedSequence() {
    const eps = reshapeConditionEps()
    let minDist = 0
    try {
      const perPoint = Number(canvas.mapSettings.mapUnitsPerPoint)
      if (isFinite(perPoint) && perPoint > 0)
        minDist = perPoint * reshapeRepairPoints
    } catch (error) {}
    const controls = splineDecimate(
        reshapeConditionSequence(reshapeControls, eps, 0), minDist)
    let seq = controls
    if (reshapeSplineArmed) {
      const s = splineConfirmSequence(controls, false, splineTightness,
          splineTolerance, splineMaxSegments, reshapeRepairCache,
          reshapeDensity())
      if (s !== null)
        seq = s
    }
    return reshapeConditionSequence(seq, eps, reshapeLoopCap)
  }

  // Does this end of the line sit inside the SNAPSHOT feature, or graze
  // its boundary within eps? The snapshot matters: the live geometry
  // may already have been reshaped by an earlier feature this session.
  // eps is in map units; boundary distance evaluates in layer units —
  // same thing on the single-CRS mine grids LGS exports.
  function reshapeEndNeedsExtend(layer, feature, p, eps) {
    const term = reshapeCrsTerm('make_point(' + p.x + ', ' + p.y + ')')
    const expr = 'intersects($geometry, ' + term + ')' +
        (eps > 0 ? ' OR distance(boundary($geometry), ' + term + ') <= ' +
                   eps : '')
    return exprTrue(evalExpr(layer, feature, expr))
  }

  // Attempt 3: extend whichever ends land inside (or graze) the target,
  // doubling the extension until both ends probe clear or the iteration
  // cap. Extension appends straight external points — it cannot change
  // the drawn curve.
  function reshapeExtendedSequence(layer, feature, seq, eps) {
    if (seq.length < 2)
      return null
    const extFirst = reshapeEndNeedsExtend(layer, feature, seq[0], eps)
    const extLast = reshapeEndNeedsExtend(layer, feature,
                                          seq[seq.length - 1], eps)
    if (!extFirst && !extLast)
      return null
    let dist = 0
    try {
      const perPoint = Number(canvas.mapSettings.mapUnitsPerPoint)
      if (isFinite(perPoint) && perPoint > 0)
        dist = perPoint * reshapeExtendStartPoints
    } catch (error) {}
    if (!(dist > 0))
      dist = eps > 0 ? eps * 48 : 1
    let out = seq
    for (let i = 0; i < reshapeExtendMaxIter; i++) {
      out = reshapeExtendEnds(seq, extFirst, extLast, dist)
      const firstClear = !extFirst ||
          !reshapeEndNeedsExtend(layer, feature, out[0], eps)
      const lastClear = !extLast ||
          !reshapeEndNeedsExtend(layer, feature, out[out.length - 1], eps)
      if (firstClear && lastClear)
        break
      dist = dist * 2
    }
    return out
  }

  // The confirm tap, one event-loop turn later so the busy state has
  // painted. Scan, refuse a no-op, then write.
  function runReshape() {
    try {
      const count = collectReshapeTargets()
      if (count < 0) {
        toast(qsTr('Reshape scan failed — try again or simplify the line'))
        return
      }
      if (count === 0) {
        // Desktop parity: "nothing was crossed" and "nothing you picked
        // was crossed" are different problems and used to read the same.
        toast(reshapePicks.length > 0
            ? qsTr('None of the picked polygons cross the line')
            : qsTr('The line does not cross any polygon'))
        return
      }
      executeReshape()
    } catch (error) {
      toast(qsTr('Reshape failed'))
    } finally {
      reshapeBusy = false
    }
  }

  function executeReshape() {
    try {
      const layer = reshapeLayer
      if (layer === null || reshapePlan.length === 0)
        return
      const started = Date.now()
      reshapeResultText = qsTr('Reshaping…')
      // A layer that is ALREADY being edited belongs to someone else — a
      // tracking session, another tool — and editing inside their buffer
      // would either commit their half-finished work with ours or throw
      // it away when we roll back. Refuse rather than guess.
      // QgsVectorLayer::isEditable is not reachable from QML, so the
      // expression engine answers; an answer we cannot read is treated as
      // "not editing", which is what every build before this one assumed.
      let editable = ''
      try {
        editable = evalExpr(layer, null,
                            "layer_property(@layer, 'is_editable')")
      } catch (error) {}
      if (exprTrue(editable)) {
        toast(qsTr('%1 has unsaved edits from another tool — save or discard them first')
              .arg(reshapeLayerLabel()))
        reshapeResultText = ''
        return
      }
      const names = attributeNames(layer, reshapePlan[0].feature)
      const uuidField = detectUuidField(names)
      const eps = reshapeConditionEps()
      const seqBase = reshapeConditionSequence(reshapeSequence(), eps,
                                               reshapeLoopCap)
      // Rung 2 is built on FIRST refusal, not up front. It is a complete
      // second spline — decimate the controls harder, re-spline, condition
      // again — and every reshape that worked first time was paying for
      // it and throwing it away. Its cache is session-scoped rather than
      // a fresh ({}) per call, which forced a cold full-density build
      // each time it was asked for.
      let repairedBuilt = false
      let seqRepaired = null
      function repairedSeq() {
        if (repairedBuilt)
          return seqRepaired
        repairedBuilt = true
        try {
          const seq = reshapeRepairedSequence()
          // Same line, differently derived, is no second attempt. An
          // O(n) prefix walk says so without serialising both arrays.
          if (seq.length !== seqBase.length ||
              splineCommonPrefixLength(seq, seqBase) !== seqBase.length)
            seqRepaired = seq
        } catch (error) {
          seqRepaired = null
        }
        return seqRepaired
      }
      let written = null
      function writeAttempt(tag, seq) {
        if (written === tag)
          return
        reshapeWriteModel(seq)
        written = tag
      }
      // Validity is judged as a TRANSITION, not a state. A polygon that
      // was already invalid before the line was drawn (a bow-tie from an
      // import is common on transposed basemaps) is not made worse by
      // the reshape and must not veto it — the first version refused any
      // invalid result and so could never reshape anything near such a
      // polygon. The snapshot is tested here, once, off the feature we
      // already hold: no layer read.
      function wasValid(target) {
        try {
          return !exprFalse(
              evalExpr(layer, target.feature, 'is_valid($geometry)'))
        } catch (error) {
          return true
        }
      }
      // The desktop tool skips a feature whose result would be invalid
      // and carries on with the rest. Nothing can revert one feature
      // inside an open buffer here (changeGeometry is not reachable from
      // QML), so the equivalent is a second pass: roll back, exclude the
      // offenders, run again. One retry — the excluded set can only grow.
      let excluded = {}
      let undoEntries = []
      let unchanged = 0
      let failed = 0
      let repaired = 0
      let skipped = 0
      for (let pass = 0; pass < 2; pass++) {
        undoEntries = []
        unchanged = 0
        failed = 0
        repaired = 0
        written = null
        let offenders = []
        try {
          layer.startEditing()
        } catch (error) {}
        for (const target of reshapePlan) {
          if (excluded[target.fid] === true)
            continue
          let attempts = []
          writeAttempt('base', seqBase)
          let result = reshapeApplyOnce(layer, target.fid)
          attempts.push(result)
          if (result === 1000 && repairedSeq() !== null) {
            writeAttempt('repaired', repairedSeq())
            result = reshapeApplyOnce(layer, target.fid)
            attempts.push(result)
          }
          if (result === 1000) {
            let seqExt = null
            try {
              seqExt = reshapeExtendedSequence(layer, target.feature,
                  repairedSeq() !== null ? repairedSeq() : seqBase, eps)
            } catch (error) {
              seqExt = null
            }
            if (seqExt !== null) {
              writeAttempt('ext' + target.fid, seqExt)
              result = reshapeApplyOnce(layer, target.fid)
              attempts.push(result)
            }
          }
          console.log('LGS reshape: fid ' + target.fid + ' attempts [' +
                      attempts.join(', ') + ']')
          if (result === 0 && wasValid(target) &&
              !reshapeResultIsValid(layer, target.fid)) {
            // Would render as nothing, which in the field is
            // indistinguishable from a deletion. Desktop parity says skip
            // it (isGeosValid before changeGeometry in the desktop tool);
            // the second pass below is how this code skips.
            offenders.push(target.fid)
            continue
          }
          if (result === 0) {                 // GeometryUtils.Success
            if (attempts.length > 1)
              repaired++
            // Reshape mutates in place — fid and UUID stay stable, so the
            // undo can find the feature again by either.
            let uuid = ''
            if (uuidField !== null) {
              try {
                const value = target.feature.attribute(uuidField)
                if (value !== undefined && value !== null)
                  uuid = String(value)
              } catch (error) {}
            }
            undoEntries.push({ fid: target.fid, uuid: uuid,
                               geometry: target.geometry, wkt: target.wkt,
                               feature: target.feature })
          } else if (result === 1000) {       // GeometryUtils.NothingHappened
            unchanged++
          } else {
            failed++
          }
        }
        if (offenders.length === 0)
          break
        // Roll back the whole pass — it is our session, opened above on a
        // layer we checked was not being edited — and go again without
        // the offenders.
        try {
          layer.rollBack()
        } catch (error) {}
        for (const fid of offenders)
          excluded[fid] = true
        skipped += offenders.length
        if (pass === 1) {
          toast(qsTr('Reshape failed — a polygon would become invalid'))
          reshapeResultText = ''
          return
        }
      }
      if (undoEntries.length > 0) {
        let ok = false
        try {
          ok = layer.commitChanges()
        } catch (error) {
          ok = false
        }
        if (!ok) {
          try {
            layer.rollBack()
          } catch (error) {}
          toast(qsTr('Reshape failed — no changes made'))
          reshapeResultText = ''
          return
        }
      } else {
        // Nothing of ours is in the buffer (reshapeFromRubberband writes
        // nothing unless it succeeds), and the session is ours to close:
        // the layer was checked not to be editing before we opened it.
        try {
          layer.rollBack()
        } catch (error) {}
      }
      if (undoEntries.length > 0) {
        reshapeHistory = reshapeHistory.concat([{
          layer: layer,
          layerName: reshapeLayerLabel(),
          names: names,
          uuidField: uuidField,
          entries: undoEntries
        }])
      }
      try {
        layer.removeSelection()
        layer.triggerRepaint()
        iface.mapCanvas().refresh()
      } catch (error) {}
      let message = qsTr('Reshaped %1 polygon(s)').arg(undoEntries.length)
      if (repaired > 0)
        message += qsTr(' — %1 repaired automatically').arg(repaired)
      if (skipped > 0)
        message += qsTr(' — %1 skipped (would become invalid)').arg(skipped)
      if (unchanged > 0)
        message += qsTr(' — %1 unchanged (the line must enter and exit through the boundary)').arg(unchanged)
      if (failed > 0)
        message += qsTr(' — %1 failed').arg(failed)
      console.log('LGS reshape confirm: ' + (Date.now() - started) +
                  ' ms, ' + reshapePlan.length + ' target(s), ' +
                  seqBase.length + ' pts, ' + reshapeControls.length +
                  ' controls, repaired ' + repaired + ', skipped ' +
                  skipped + ', unchanged ' + unchanged + ', failed ' +
                  failed)
      reshapeResultText = message
      toast(message)
      if (undoEntries.length > 0) {
        // Stay in the draw step with the line cleared, so the next edge
        // is one stroke away instead of a trip back through the pill.
        // The layer, style, spline arming and the target picks all
        // survive; the picks are re-highlighted because the selection
        // was dropped above, and keeping them while wiping their
        // highlight would silently filter the next line with nothing on
        // screen to explain it.
        reshapeClearLine()
      }
      // When nothing changed the LINE STAYS: the message tells the user
      // the line must enter and exit the polygon, and wiping it would
      // take away the very thing they need to extend.
      updateReshapeSelection()
    } catch (error) {
      toast(qsTr('Reshape failed'))
      reshapeResultText = ''
    }
  }

  // Everything about the drawn line, and nothing about the session.
  function reshapeClearLine() {
    reshapeControls = []
    reshapeMarkerPositions = []
    reshapeUndoStack = []
    reshapeStrokeStart = -1
    reshapeStrokeRaw.length = 0
    reshapeLastSeq = null
    reshapeCache = ({})
    reshapeRepairCache = ({})
    reshapePlan = []
    try {
      reshapeModel.reset(true)
    } catch (error) {}
  }

  // ----------------------------------------------------------------
  // Undo (session-only — never persisted). One round per press, newest
  // first; the stack survives leaving and re-entering the tool.
  // ----------------------------------------------------------------
  function undoLastReshape() {
    if (reshapeHistory.length === 0)
      return
    const undo = reshapeHistory[reshapeHistory.length - 1]
    if (undo === null || undo === undefined) {
      reshapeHistory = reshapeHistory.slice(0, reshapeHistory.length - 1)
      return
    }
    try {
      let layer = undo.layer
      try {
        if (layer === null || layer.name === undefined)
          layer = layerByName(undo.layerName)
      } catch (error) {
        layer = layerByName(undo.layerName)
      }
      if (layer === null) {
        toast(qsTr('Undo failed — layer not found'))
        return
      }
      // The reshaped features, looked up by the fid we recorded and, when
      // the layer carries one, checked against the UUID we recorded too.
      // NEVER redirected: the old code looked a UUID up and deleted
      // whatever answered, and a UUID is not unique in the template —
      // duplicating a feature copies it — so with the original hidden by
      // a level filter the one visible match was an untouched sibling on
      // another bench, and undo deleted it. A recorded fid is current
      // because every successful undo remaps the fids in the rounds still
      // on the stack (below); a fid that no longer answers fails loudly
      // instead of guessing.
      const uuidTerm = function(entry) {
        return undo.uuidField !== null && entry.uuid !== ''
            ? ' AND "' + undo.uuidField + "\" = '" + sqlLiteral(entry.uuid) +
              "'"
            : ''
      }
      let doomed = []
      let restored = []
      let before = {}
      for (const entry of undo.entries) {
        const found = collectFidsByExpression(layer,
            '$id = ' + entry.fid + uuidTerm(entry))
        if (found.length !== 1) {
          toast(qsTr('Undo failed — the reshaped polygon is not visible (check the level filter)'))
          return
        }
        // Rebuild the original from the geometry snapshot taken before
        // the reshape (WKT only where the geometry could not be read),
        // all attributes copied verbatim — the UUID included, so
        // identity is restored and not merely replaced.
        let geometry = null
        if (entry.geometry !== null && entry.geometry !== undefined)
          geometry = entry.geometry
        else if (entry.wkt !== '')
          geometry = GeometryUtils.createGeometryFromWkt(entry.wkt)
        if (geometry === null) {
          toast(qsTr('Undo failed — the original geometry was not kept'))
          return
        }
        // Every fid that carries this UUID right now, so the recreated
        // feature can be told apart from a duplicate sibling afterwards.
        if (undo.uuidField !== null && entry.uuid !== '') {
          before[entry.fid] = collectFidsByExpression(layer,
              '"' + undo.uuidField + "\" = '" + sqlLiteral(entry.uuid) + "'")
        }
        doomed.push(entry.fid)
        let created = FeatureUtils.createFeature(layer, geometry)
        copyClipAttributes(created, entry.feature, undo.names, null, '',
                           layer)
        restored.push(created)
      }
      if (!applyClipEdits(layer, restored, doomed)) {
        toast(qsTr('Undo failed — no changes made'))
        return
      }
      // Read-back verify, the way finalizeClip does, and the fid remap.
      // applyClipEdits can only report that its own edits committed; it
      // cannot know the restored polygon came back where the current Z
      // filter can see it, and an Elevation default stamped onto a
      // rebuilt feature can put it outside the active subsetString.
      // Present but invisible reads exactly like still-deleted, so say so
      // rather than toasting success. The recreated feature is the UUID
      // match that was not there before; older rounds on the stack and
      // the target picks are pointed at it, otherwise the next undo would
      // look for a fid that no longer exists and the next line would be
      // filtered by one.
      let verified = 0
      let remap = {}
      for (const entry of undo.entries) {
        if (undo.uuidField === null || entry.uuid === '')
          continue
        const after = collectFidsByExpression(layer,
            '"' + undo.uuidField + "\" = '" + sqlLiteral(entry.uuid) + "'")
        const seen = {}
        for (const fid of before[entry.fid] || [])
          seen[fid] = true
        let fresh = null
        for (const fid of after) {
          if (seen[fid] !== true && fid !== entry.fid)
            fresh = fid
        }
        if (fresh !== null) {
          verified++
          remap[entry.fid] = fresh
        }
      }
      const canVerify = undo.uuidField !== null
      if (canVerify) {
        let rounds = reshapeHistory.slice(0, reshapeHistory.length - 1)
        for (let r = 0; r < rounds.length; r++) {
          let entries = rounds[r].entries.slice()
          for (let e = 0; e < entries.length; e++) {
            if (remap[entries[e].fid] !== undefined)
              entries[e] = Object.assign({}, entries[e],
                                         { fid: remap[entries[e].fid] })
          }
          rounds[r] = Object.assign({}, rounds[r], { entries: entries })
        }
        reshapeHistory = rounds
        let picks = []
        let dropped = 0
        for (const pick of reshapePicks) {
          if (remap[pick.id] !== undefined)
            picks.push({ id: remap[pick.id], feature: pick.feature })
          else if (doomed.indexOf(pick.id) >= 0)
            dropped++
          else
            picks.push(pick)
        }
        reshapePicks = picks
        if (dropped > 0)
          toast(qsTr('%1 target(s) dropped — could not follow them through the undo').arg(dropped))
      } else {
        reshapeHistory = reshapeHistory.slice(0, reshapeHistory.length - 1)
        // No UUID to follow the recreated features with: any pick that
        // pointed at a deleted fid is gone.
        let picks = []
        for (const pick of reshapePicks) {
          if (doomed.indexOf(pick.id) < 0)
            picks.push(pick)
        }
        reshapePicks = picks
      }
      if (reshapePicks.length === 0)
        reshapeLockedSelection = false
      updateReshapeSelection()
      try {
        layer.triggerRepaint()
        iface.mapCanvas().refresh()
      } catch (error) {}
      if (canVerify && verified < undo.entries.length) {
        toast(qsTr('Undo restored %1 of %2 — check the level filter')
              .arg(verified).arg(undo.entries.length))
      } else {
        toast(qsTr('Reshape undone'))
      }
    } catch (error) {
      toast(qsTr('Undo failed'))
    }
  }

  // ----------------------------------------------------------------
  // Control-point markers (desktop parity: dots at the tapped points)
  // ----------------------------------------------------------------
  function updateReshapeMarkers() {
    // Nothing a marker shows can change while the pen is down, and the
    // guard has to live HERE rather than at the call site: the pan
    // throttle on onExtentChanged schedules this too, and the recentre
    // at the end of a stroke fires exactly that signal. Rebuilding the
    // Repeater's model destroys and recreates every delegate.
    if (reshapeStrokeStart >= 0)
      return
    if (reshapeStep !== 2 || reshapeControls.length === 0 ||
        !canvas || !scaleSettings) {
      reshapeMarkerPositions = []
      return
    }
    const out = []
    try {
      for (let i = 0; i < reshapeControls.length; i++) {
        // Freehand stroke interiors carry no dot — hundreds per stroke.
        if (reshapeControls[i].fh === true)
          continue
        const p = scaleSettings.coordinateToScreen(GeometryUtils.point(
            reshapeControls[i].x, reshapeControls[i].y))
        out.push({ x: Number(p.x), y: Number(p.y) })
      }
    } catch (error) {
      reshapeMarkerPositions = []
      return
    }
    reshapeMarkerPositions = out
  }

  Timer {
    // Same pan-throttle as the spline dots: extentChanged fires every
    // frame, and replacing the marker array rebuilds the Repeater.
    id: reshapeMarkerTimer
    interval: 40
    repeat: false
    onTriggered: plugin.updateReshapeMarkers()
  }

  Connections {
    target: plugin.scaleSettings
    ignoreUnknownSignals: true
    function onExtentChanged() {
      if (plugin.reshapeStep === 2 && plugin.reshapeControls.length > 0 &&
          !reshapeMarkerTimer.running)
        reshapeMarkerTimer.start()
    }
  }

  Timer {
    id: reshapeRunTimer
    interval: 50
    repeat: false
    onTriggered: plugin.runReshape()
  }

  Connections {
    // Latch QField's selection while the tool is closed. Its identify
    // refills the model on every tap and clears it when the form hides,
    // so the last non-empty state is what the user means by "the polygon
    // I selected" by the time they reach the pill.
    target: plugin.reshapeSelectionModel
    ignoreUnknownSignals: true
    function onSelectedCountChanged() {
      plugin.latchReshapeSelection()
    }
    function onCountChanged() {
      plugin.latchReshapeSelection()
    }
  }

  Connections {
    target: plugin.reshapeSelectionItem
    ignoreUnknownSignals: true
    function onFocusedItemChanged() {
      plugin.latchReshapeSelection()
    }
  }

  Connections {
    // Track the app state machine: currentRubberband flips non-null
    // when a digitizing/measure session starts. Hide the pill then, and
    // abandon an in-progress reshape — the two modes fight over taps.
    target: plugin.mainWindow
    ignoreUnknownSignals: true
    function onCurrentRubberbandChanged() {
      plugin.updateReshapeEditingActive()
      if (plugin.reshapeEditingActive &&
          (plugin.reshapeStep === 1 || plugin.reshapeStep === 2)) {
        plugin.exitReshapeMode()
        plugin.toast(qsTr('Reshape cancelled — digitizing started'))
      }
      if (plugin.reshapeEditingActive && plugin.reverseStep === 1) {
        plugin.exitReverseMode()
        plugin.toast(qsTr('Reverse cancelled — digitizing started'))
      }
      // Mode changes ride the same signal — a cheap resync in case the
      // startup find of the state machine came up empty.
      if (plugin.featureModeToggle)
        plugin.initModeToggle()
      // Same cheap resync for the layer switch: entering digitize mode
      // is exactly when QField settles on an active layer.
      if (plugin.featureLayerSwitch)
        plugin.syncLayerSwitchActive()
    }
  }

  Item {
    id: reshapeMarkers
    visible: plugin.reshapeStep === 2 &&
             plugin.reshapeMarkerPositions.length > 0
    z: 1

    Repeater {
      model: plugin.reshapeMarkerPositions

      delegate: Rectangle {
        required property var modelData
        x: modelData.x - 5
        y: modelData.y - 5
        width: 10
        height: 10
        radius: 5
        color: 'white'
        border.color: 'black'
        border.width: 2
      }
    }
  }

  // ----------------------------------------------------------------
  // Reshape UI: tap catcher + instruction banner + confirm dialog
  // ----------------------------------------------------------------
  Item {
    id: reshapeCatcher
    visible: plugin.reshapeStep === 1 || plugin.reshapeStep === 2
    z: 1

    TapHandler {
      // ReleaseWithinBounds (v32): the exclusive grab consumes the tap
      // so it stops leaking through to QField's identify underneath —
      // same policy, same reason as every pill. Movement past the drag
      // threshold still hands the grab to the canvas's pan/pinch (the
      // default grabPermissions approve the take-over); revert this one
      // line if pan feel regresses on device. In freehand mode the
      // accepted devices narrow to the drawing devices: a finger tap is
      // inert (a real stray-point hazard once freehand is an explicit
      // mode) while a clean stylus tap still places a single precise
      // point.
      gesturePolicy: TapHandler.ReleaseWithinBounds
      // v33: every device is accepted and the DEVICE decides what a tap
      // means, instead of narrowing acceptedDevices in freehand mode.
      // Narrowing left a finger tap unconsumed, so it fell through to
      // QField's identify: the feature form opened over the map in the
      // middle of a reshape and the selection model churned. Now a
      // finger tap in freehand mode picks a target — one tap, no hold —
      // and a pen tap still places a single precise point.
      acceptedDevices: PointerDevice.AllDevices
      // Same threshold as the long-press handler below. With the
      // platform default (~0.8 s) a press released between 0.6 and 0.8 s
      // fired BOTH: the pick toggled and a stray point landed where the
      // pen sat, or the pick toggled straight back. A handler that has
      // long-pressed does not tap.
      longPressThreshold: 0.6
      onSingleTapped: function(eventPoint, button) {
        plugin.handleReshapeTap(eventPoint.position,
                                plugin.reshapeTapIsTouch(eventPoint))
      }
    }

    TapHandler {
      // Long-press adds or removes a target while you are drawing, so a
      // locked selection stays editable without leaving the line. It
      // needs its OWN handler because the one above narrows its accepted
      // devices to the pen in freehand mode -- which is right for
      // placing a point and wrong for this, since a long press is a
      // finger gesture as much as a pen one. Passive grab (the default
      // DragThreshold policy), so it cannot fight the tap handler above
      // or the canvas; and free in both styles, because dragThreshold 0
      // means a press that never moves cannot start a stroke either.
      longPressThreshold: 0.6
      onLongPressed: plugin.handleReshapePickToggle(point.position)
    }

    DragHandler {
      // Stylus freehand (v24) — the exact device gate of QField's own
      // freehand digitizing: TouchScreen is never accepted, so a
      // finger drag still pans the canvas underneath; the mouse draws
      // on desktop unless the user runs it as a touchscreen.
      // dragThreshold 0 means a clean stylus tap never activates this
      // handler and falls through to the TapHandler above — inherent
      // tap/stroke dedupe. grabPermissions omits CanTakeOverFromItems
      // so banner Buttons keep their stylus taps.
      // v32: strokes only exist in freehand mode — Tap mode fully
      // disables this handler.
      // v33: live in the pick step too - reshapeStrokeBegin promotes -
      // so the pen draws on the screen the tool opens on. dragThreshold
      // 0 is also what wins the grab race: this catcher is a CHILD of
      // the canvas, which Qt offers the press to first, and the canvas
      // pan needs its whole drag threshold before it can even ask.
      id: reshapeFreehandDrag
      enabled: (plugin.reshapeStep === 1 || plugin.reshapeStep === 2) &&
               plugin.reshapeStyle === 'free'
      acceptedDevices: plugin.reshapeSettingsItem !== null &&
                       plugin.reshapeSettingsItem.mouseAsTouchScreen
          ? PointerDevice.Stylus
          : PointerDevice.Stylus | PointerDevice.Mouse
      // While a stroke is actually being recorded, refuse to hand the
      // grab on: the canvas must not be able to turn the second half of
      // a drawn line into a pan. ApprovesCancellation is kept and is NOT
      // optional - it lives inside the ApprovesTakeOverByAnything (0xF0)
      // mask, and without it Qt cannot cancel our exclusive grab (window
      // deactivate, a popup opening, a touch cancel), so
      // onActiveChanged(false) would never fire and reshapeStrokeEnd
      // would never run: the stroke would hang forever.
      // Outside a live stroke the permissive mask is restored, so a
      // press the tool has already decided to ignore (reshapeStrokeStart
      // === -2, e.g. one landing on the banner) still falls through to
      // the canvas pan. CanTakeOverFromItems stays off either way, so
      // banner Buttons keep their stylus taps.
      grabPermissions: plugin.reshapeStrokeStart >= 0
          ? (PointerHandler.CanTakeOverFromHandlersOfSameType |
             PointerHandler.CanTakeOverFromHandlersOfDifferentType |
             PointerHandler.ApprovesCancellation)
          : (PointerHandler.CanTakeOverFromHandlersOfSameType |
             PointerHandler.CanTakeOverFromHandlersOfDifferentType |
             PointerHandler.ApprovesTakeOverByAnything)
      dragThreshold: 0
      // No target: the default is the parent item, and a DragHandler
      // moves its target on every sample. The catcher's anchors snapped
      // it straight back, but that was geometry churn per sample and a
      // hazard the moment the anchors change. QField sets this on every
      // canvas handler.
      target: null
      onActiveChanged: {
        if (active) {
          plugin.reshapeStrokeBegin(centroid.position)
          plugin.reshapeLogStroke(reshapeFreehandDrag)
        } else {
          plugin.reshapeStrokeEnd()
        }
      }
      onCentroidChanged: {
        // QField guards the same signal. A centroid update can report
        // (0,0) as a second point arrives or leaves, or on the
        // activation edge; without the guard that sample lands as a
        // control point at the map's top-left corner and drags the whole
        // line across the canvas.
        if (active && (centroid.position.x !== 0 || centroid.position.y !== 0))
          plugin.reshapeStrokeMove(centroid.position)
      }
    }
  }

  Rectangle {
    id: reshapeBanner
    visible: plugin.reshapeStep > 0
    z: 3
    radius: 8
    color: '#CC000000'
    width: Math.min((parent !== null ? parent.width : 444) - 24, 420)
    height: reshapeBannerColumn.height + 24

    Column {
      id: reshapeBannerColumn
      anchors.top: parent.top
      anchors.topMargin: 12
      anchors.horizontalCenter: parent.horizontalCenter
      width: parent.width - 24
      spacing: 8

      // Digitisation style toggles (v32) — Tap / Freehand, plus the
      // reshape's own per-style Spline toggle. Same monochrome
      // active-state language as the bottom pills: inverted while on.
      Row {
        visible: plugin.reshapeStep === 1 || plugin.reshapeStep === 2
        spacing: 8

        Rectangle {
          id: reshapeStyleTapPill
          width: reshapeStyleTapText.contentWidth + 24
          height: reshapeStyleTapText.contentHeight + 12
          radius: height / 2
          color: plugin.reshapeStyle === 'tap' ? '#E6FFFFFF' : 'transparent'
          border.color: plugin.reshapeStyle === 'tap'
              ? '#E6FFFFFF' : '#AAFFFFFF'
          border.width: 1

          Text {
            id: reshapeStyleTapText
            anchors.centerIn: parent
            font.pixelSize: 14
            color: plugin.reshapeStyle === 'tap' ? 'black' : 'white'
            text: qsTr('Tap')
          }

          TapHandler {
            gesturePolicy: TapHandler.ReleaseWithinBounds
            // Do not approve a take-over: the freehand DragHandler on the
            // catcher below has dragThreshold 0, and a pixel of pen jitter
            // on a pill tap would otherwise let it take the grab and
            // cancel the tap.
            grabPermissions: PointerHandler.CanTakeOverFromItems |
                             PointerHandler.CanTakeOverFromHandlersOfDifferentType |
                             PointerHandler.ApprovesCancellation
            onTapped: plugin.setReshapeStyle('tap')
          }
        }

        Rectangle {
          id: reshapeStyleFreePill
          width: reshapeStyleFreeText.contentWidth + 24
          height: reshapeStyleFreeText.contentHeight + 12
          radius: height / 2
          color: plugin.reshapeStyle === 'free' ? '#E6FFFFFF' : 'transparent'
          border.color: plugin.reshapeStyle === 'free'
              ? '#E6FFFFFF' : '#AAFFFFFF'
          border.width: 1

          Text {
            id: reshapeStyleFreeText
            anchors.centerIn: parent
            font.pixelSize: 14
            color: plugin.reshapeStyle === 'free' ? 'black' : 'white'
            // Real emoji on purpose — exotic symbols are tofu on Android.
            text: qsTr('Freehand ✏')
          }

          TapHandler {
            gesturePolicy: TapHandler.ReleaseWithinBounds
            grabPermissions: PointerHandler.CanTakeOverFromItems |
                             PointerHandler.CanTakeOverFromHandlersOfDifferentType |
                             PointerHandler.ApprovesCancellation
            onTapped: plugin.setReshapeStyle('free')
          }
        }

        Rectangle {
          id: reshapeSplinePill
          visible: plugin.featureSpline
          width: reshapeSplineText.contentWidth + 24
          height: reshapeSplineText.contentHeight + 12
          radius: height / 2
          color: plugin.reshapeSplineArmed ? '#E6FFFFFF' : 'transparent'
          border.color: plugin.reshapeSplineArmed
              ? '#E6FFFFFF' : '#AAFFFFFF'
          border.width: 1

          Text {
            id: reshapeSplineText
            anchors.centerIn: parent
            font.pixelSize: 14
            color: plugin.reshapeSplineArmed ? 'black' : 'white'
            // ASCII on purpose: '∿' (U+223F) is not in Android's fonts.
            text: qsTr('~ Spline')
          }

          TapHandler {
            gesturePolicy: TapHandler.ReleaseWithinBounds
            grabPermissions: PointerHandler.CanTakeOverFromItems |
                             PointerHandler.CanTakeOverFromHandlersOfDifferentType |
                             PointerHandler.ApprovesCancellation
            onTapped: plugin.toggleReshapeSpline()
          }
        }
      }

      Text {
        width: parent.width
        font.pixelSize: 15
        font.bold: true
        color: 'white'
        text: plugin.reshapeStep === 1
            ? qsTr('Reshape — pick targets (optional)')
            : qsTr('Reshape — draw the new edge')
      }

      Text {
        width: parent.width
        wrapMode: Text.WordWrap
        font.pixelSize: 14
        color: 'white'
        text: {
          if (plugin.reshapeBusy)
            return qsTr('Reshaping…')
          // After a reshape the result stands in for the hint until the
          // next line starts, so it is readable without a dead step to
          // park it in.
          if (plugin.reshapeStep === 2 && plugin.reshapeControls.length === 0 &&
              plugin.reshapeResultText !== '')
            return plugin.reshapeResultText
          if (plugin.reshapeStep === 1)
            return qsTr('Tap polygons to limit the reshape, or just start drawing — with no picks every polygon the line crosses is reshaped')
          return plugin.reshapeStyle === 'free'
              ? qsTr('Draw the new edge with the stylus — finger pans, a stylus tap adds a single point; the line must enter and exit each polygon it reshapes')
              : qsTr('Tap along the new edge — the line must enter and exit each polygon it reshapes')
        }
      }

      Text {
        width: parent.width
        wrapMode: Text.WordWrap
        font.pixelSize: 12
        color: '#CCFFFFFF'
        text: {
          if (plugin.reshapeStep === 1) {
            let line = qsTr('%1 selected — tap again to unselect')
                .arg(plugin.reshapePicks.length)
            return line + ' · ' + plugin.reshapeLayerLabel()
          }
          let line = qsTr('%1 point(s)').arg(plugin.reshapeControls.length)
          line += ' · ' + (plugin.reshapeStyle === 'free'
              ? qsTr('freehand') : qsTr('tap'))
          line += ' · ' + (plugin.reshapeSplineArmed ? qsTr('smoothed')
                                                     : qsTr('straight'))
          if (plugin.reshapePicks.length > 0) {
            line += ' · ' + (plugin.reshapeLockedSelection
                ? qsTr('%1 selected — long-press a polygon to add/remove')
                    .arg(plugin.reshapePicks.length)
                : qsTr('%1 picked — long-press a polygon to add/remove')
                    .arg(plugin.reshapePicks.length))
          }
          return line + ' · ' + plugin.reshapeLayerLabel()
        }
      }

      Flow {
        width: parent.width
        spacing: 8

        Button {
          id: reshapeDrawButton
          visible: plugin.reshapeStep === 1
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Draw line ▸')
            color: 'white'
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: Theme.mainColor
            border.color: Theme.mainColor
            border.width: 1
            radius: 4
          }
          onClicked: {
            plugin.reshapeStep = 2
            plugin.splineRefreshDensity()
            plugin.toast(qsTr('Tap along the new edge — at least 2 points'))
          }
        }

        Button {
          id: reshapeUndoPointButton
          visible: plugin.reshapeStep === 2
          enabled: plugin.reshapeControls.length > 0
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            // One action per press: a tapped point OR a whole stroke.
            text: plugin.reshapeStyle === 'free' ? qsTr('Undo stroke')
                                                 : qsTr('Undo point')
            color: reshapeUndoPointButton.enabled ? 'white' : '#66FFFFFF'
            font.pixelSize: 14
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: 'transparent'
            border.color: reshapeUndoPointButton.enabled
                ? '#AAFFFFFF' : '#66FFFFFF'
            border.width: 1
            radius: 4
          }
          onClicked: plugin.reshapeUndoVertex()
        }

        Button {
          // Persisting picks across a confirm is right for the next edge
          // of the SAME polygon and wrong for the next polygon; without
          // this, releasing cost a long-press per pick.
          id: reshapeClearPicksButton
          visible: plugin.reshapePicks.length > 0
          enabled: !plugin.reshapeBusy
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Clear targets')
            color: 'white'
            font.pixelSize: 14
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: 'transparent'
            border.color: '#AAFFFFFF'
            border.width: 1
            radius: 4
          }
          onClicked: {
            plugin.reshapePicks = []
            plugin.reshapeLockedSelection = false
            plugin.updateReshapeSelection()
            plugin.toast(qsTr('Every polygon the line crosses will be reshaped'))
          }
        }

        Button {
          id: reshapeBackButton
          visible: plugin.reshapeStep === 2 &&
                   plugin.reshapeControls.length > 0
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('◂ Back')
            color: 'white'
            font.pixelSize: 14
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: 'transparent'
            border.color: '#AAFFFFFF'
            border.width: 1
            radius: 4
          }
          onClicked: plugin.reshapeBackToPicks()
        }

        Button {
          id: reshapeCancelButton
          visible: plugin.reshapeStep === 1 || plugin.reshapeStep === 2
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            // "Cancel" is a lie once a reshape has landed: there is
            // nothing left to cancel, you are just leaving.
            text: plugin.reshapeHistory.length > 0 ||
                  plugin.reshapeResultText !== ''
                ? qsTr('Done') : qsTr('Cancel')
            color: 'white'
            font.pixelSize: 14
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: 'transparent'
            border.color: '#AAFFFFFF'
            border.width: 1
            radius: 4
          }
          onClicked: plugin.exitReshapeMode()
        }

        Button {
          id: reshapeExecuteButton
          visible: plugin.reshapeStep === 2
          enabled: plugin.reshapeControls.length >= 2 && !plugin.reshapeBusy
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: plugin.reshapeBusy ? qsTr('Reshaping…') : qsTr('Apply ✓')
            color: reshapeExecuteButton.enabled ? 'white' : '#66FFFFFF'
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: reshapeExecuteButton.enabled
                ? Theme.mainColor : 'transparent'
            border.color: reshapeExecuteButton.enabled
                ? Theme.mainColor : '#66FFFFFF'
            border.width: 1
            radius: 4
          }
          // No confirmation dialog (v33). It stood between every line
          // and its result, and the tool is now built to be used over and
          // over; a complete session undo is the better safety net. The
          // work is deferred one turn so the banner and this button can
          // repaint as busy first — assigning the text inside the
          // synchronous block meant it never showed at all.
          onClicked: {
            if (plugin.reshapeBusy)
              return
            plugin.reshapeBusy = true
            // A Timer, not Qt.callLater: callLater posts a queued call,
            // and posted events run BEFORE the scene graph's update timer
            // fires, so the busy frame was never rendered before the work
            // began. One tick past a frame is enough.
            reshapeRunTimer.start()
          }
        }

        Button {
          id: reshapeUndoButton
          visible: plugin.reshapeHistory.length > 0
          enabled: !plugin.reshapeBusy
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Undo reshape (%1)').arg(plugin.reshapeHistory.length)
            color: reshapeUndoButton.enabled ? 'white' : '#66FFFFFF'
            font.pixelSize: 14
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: 'transparent'
            border.color: reshapeUndoButton.enabled
                ? '#AAFFFFFF' : '#66FFFFFF'
            border.width: 1
            radius: 4
          }
          // Undoing no longer leaves the tool: a failed undo used to
          // drop you out with the payload stranded, and a second press
          // now pops the round before it.
          onClicked: plugin.undoLastReshape()
        }

      }
    }
  }

  // ================================================================
  // REVERSE (v19) — flip a line feature's vertex order so asymmetric
  // line symbology (ticks, teeth, dip marks) renders on the other
  // side. Tap-per-line, applies immediately; reversal is its own
  // inverse, so tapping the line again IS the undo — no undo state.
  // ================================================================

  property int reverseStep: 0        // 0=off, 1=tap lines
  property bool reverseAvailable: false
  property var reverseLayers: []     // hit-test order, locked on entry
  property int reverseCount: 0       // flips this session (banner)

  function initReverse() {
    // Pill availability from the standard layers only — the active
    // layer is re-probed on entry (the dashboard may not exist yet).
    try {
      reverseAvailable = candidateReverseLayers().length > 0
    } catch (error) {
      reverseAvailable = false
    }
  }

  function layerIsLine(layer) {
    if (layer === null || layer === undefined)
      return false
    return evalExpr(layer, null,
                    "layer_property(@layer, 'geometry_type')") === 'Line'
  }

  function candidateReverseLayers() {
    // Active layer first — reverse what you're working on — then the
    // standard LGS layers that hold lines (normally '2 - Linework').
    let layers = []
    try {
      const active = reshapeActiveLayer()
      if (layerIsLine(active))
        layers.push(active)
    } catch (error) {}
    for (const name of layerNames) {
      const layer = layerByName(name)
      if (layer === null || !layerIsLine(layer))
        continue
      let seen = false
      for (const known of layers) {
        try {
          if (known === layer)
            seen = true
        } catch (error) {}
      }
      if (!seen)
        layers.push(layer)
    }
    return layers
  }

  // ----------------------------------------------------------------
  // Mode lifecycle
  // ----------------------------------------------------------------
  function enterReverseMode() {
    try {
      if (!canvas || canvas.width === undefined) {
        toast(qsTr('Reverse unavailable — no map canvas'))
        return
      }
      updateReshapeEditingActive()
      if (reshapeEditingActive) {
        toast(qsTr('Turn digitizing off first'))
        return
      }
      const layers = candidateReverseLayers()
      if (layers.length === 0) {
        toast(qsTr('Reverse unavailable — no line layer found'))
        return
      }
      reverseLayers = layers
      reverseCatcher.parent = canvas
      reverseCatcher.anchors.fill = canvas
      reverseBanner.parent = canvas
      reverseBanner.anchors.horizontalCenter = canvas.horizontalCenter
      reverseBanner.anchors.top = canvas.top
      reverseBanner.anchors.topMargin = 60
      reverseCount = 0
      reverseStep = 1
      toast(qsTr('Tap a line to reverse its direction'))
    } catch (error) {
      toast(qsTr('Reverse unavailable'))
    }
  }

  function exitReverseMode() {
    reverseStep = 0
    reverseLayers = []
    reverseCount = 0
  }

  // ----------------------------------------------------------------
  // Tap handling
  // ----------------------------------------------------------------
  function reverseTapOnUi(pos) {
    // Ignore taps landing on the banner or pill bar — overlapping
    // TapHandlers may deliver the same tap to the canvas catcher too
    // (same guard as clipTapOnUi / reshapeTapOnUi).
    try {
      const b = reverseBanner.mapFromItem(reverseCatcher, pos.x, pos.y)
      if (b.x >= 0 && b.y >= 0 &&
          b.x <= reverseBanner.width && b.y <= reverseBanner.height)
        return true
    } catch (error) {}
    try {
      const o = overlayBar.mapFromItem(reverseCatcher, pos.x, pos.y)
      if (o.x >= 0 && o.y >= 0 &&
          o.x <= overlayBar.width && o.y <= overlayBar.height)
        return true
    } catch (error) {}
    try {
      if (zDialog.visible) {
        const d = mainWindow.contentItem.mapFromItem(
            reverseCatcher, pos.x, pos.y)
        if (d.x >= zDialog.x && d.y >= zDialog.y &&
            d.x <= zDialog.x + zDialog.width &&
            d.y <= zDialog.y + zDialog.height)
          return true
      }
    } catch (error) {}
    return false
  }

  function handleReverseTap(pos) {
    try {
      if (reverseStep !== 1)
        return
      if (reverseTapOnUi(pos))
        return
      // The iterator honours the layer subsetString, so an active Z
      // filter means only VISIBLE lines are tappable — reverse what
      // you see.
      const hit = findHitInLayers(reverseLayers, pos)
      if (hit === null) {
        toast(qsTr('No line here'))
        return
      }
      reverseFeature(hit.layer, hit.feature)
    } catch (error) {}
  }

  // ----------------------------------------------------------------
  // WKT reversal (pure JS fallback for the expression engine)
  // ----------------------------------------------------------------
  function reverseWktCoordGroups(text) {
    // Reverse the comma-separated vertex list inside every innermost
    // parenthesis group; whole vertex tokens move, so Z/M ride along.
    // Works for LINESTRING [ZM] and each part of MULTILINESTRING.
    return text.replace(/\(([^()]*)\)/g, function(match, body) {
      if (body.indexOf(',') === -1)
        return match
      const coords = body.split(',')
      let out = []
      for (let i = coords.length - 1; i >= 0; i--)
        out.push(coords[i].trim())
      return '(' + out.join(', ') + ')'
    })
  }

  function reverseLineWkt(wkt) {
    const text = String(wkt).trim()
    const kind = text.substring(0, text.indexOf('(') === -1
        ? text.length : text.indexOf('(')).trim().toUpperCase()
    if (kind.indexOf('LINESTRING') === -1 &&
        kind.indexOf('MULTILINESTRING') === -1)
      return ''
    return reverseWktCoordGroups(text)
  }

  // ----------------------------------------------------------------
  // Execution — add-before-delete in one edit session, attributes
  // copied verbatim (UUID preserved: identity kept, same rules as the
  // reshape undo).
  // ----------------------------------------------------------------
  function reverseFeature(layer, feature) {
    try {
      const wkt = evalExpr(layer, feature, 'geom_to_wkt($geometry)')
      if (wkt === '') {
        toast(qsTr('Reverse failed — geometry unreadable'))
        return
      }
      // reverse() is curve-only on some engine versions (NULL for
      // multi-part lines) — the JS WKT fallback covers those.
      let reversed = evalExpr(layer, feature,
                              'geom_to_wkt(reverse($geometry))')
      if (reversed === '' || reversed.toUpperCase().indexOf('EMPTY') !== -1)
        reversed = reverseLineWkt(wkt)
      if (reversed === '') {
        toast(qsTr('Reverse failed — not a line geometry'))
        return
      }
      const names = attributeNames(layer, feature)
      const geometry = GeometryUtils.createGeometryFromWkt(reversed)
      let created = FeatureUtils.createFeature(layer, geometry)
      copyClipAttributes(created, feature, names, null, '', layer)
      if (!applyClipEdits(layer, [created], [feature.id])) {
        toast(qsTr('Reverse failed — no changes made'))
        return
      }
      try {
        layer.triggerRepaint()
        iface.mapCanvas().refresh()
      } catch (error) {}
      reverseCount++
      // Naming the preserved blanks makes the NULL guard visible on the
      // device — every failure path inside featureNulls is otherwise
      // silent, so a width that turns into 0 would look identical to a
      // guard that never ran.
      if (lastBlankFields > 0) {
        toast(qsTr('Direction reversed — %1 blank field(s) preserved')
              .arg(lastBlankFields))
      } else {
        toast(qsTr('Direction reversed — tap the line again to flip back'))
      }
    } catch (error) {
      toast(qsTr('Reverse failed'))
    }
  }

  // ----------------------------------------------------------------
  // Reverse UI: tap catcher + instruction banner
  // ----------------------------------------------------------------
  Item {
    id: reverseCatcher
    visible: plugin.reverseStep === 1
    z: 1

    TapHandler {
      // Default DragThreshold gesture policy: passive grab, so pan and
      // pinch on the canvas underneath keep working — only clean taps
      // land here.
      onSingleTapped: function(eventPoint, button) {
        plugin.handleReverseTap(eventPoint.position)
      }
    }
  }

  Rectangle {
    id: reverseBanner
    visible: plugin.reverseStep === 1
    z: 3
    radius: 8
    color: '#CC000000'
    width: Math.min((parent !== null ? parent.width : 444) - 24, 420)
    height: reverseBannerColumn.height + 24

    Column {
      id: reverseBannerColumn
      anchors.top: parent.top
      anchors.topMargin: 12
      anchors.horizontalCenter: parent.horizontalCenter
      width: parent.width - 24
      spacing: 8

      Text {
        width: parent.width
        font.pixelSize: 15
        font.bold: true
        color: 'white'
        text: qsTr('Reverse line direction')
      }

      Text {
        width: parent.width
        wrapMode: Text.WordWrap
        font.pixelSize: 14
        color: 'white'
        text: qsTr('Tap a line to flip its direction — tap it again to flip it back')
      }

      Text {
        visible: plugin.reverseCount > 0
        width: parent.width
        wrapMode: Text.WordWrap
        font.pixelSize: 12
        color: '#CCFFFFFF'
        text: qsTr('%1 reversed').arg(plugin.reverseCount)
      }

      Flow {
        width: parent.width
        spacing: 8

        Button {
          id: reverseDoneButton
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Done')
            color: 'white'
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: Theme.mainColor
            border.color: Theme.mainColor
            border.width: 1
            radius: 4
          }
          onClicked: plugin.exitReverseMode()
        }
      }
    }
  }

  // ================================================================
  // COPY ATTRIBUTES (v21, active-layer-only since v24) — stamp one
  // feature's attributes onto others. Tap the source, then tap
  // targets; the source stays armed for rapid multi-stamping. Only
  // non-empty source values are written; the target keeps its own
  // geometry, UUID and housekeeping fields. Both taps resolve against
  // the ACTIVE layer only — a stray tap can no longer pick up a
  // feature from a layer the geologist is not working in.
  // ================================================================

  property int copyStep: 0           // 0=off, 1=pick source, 2=stamp targets
  property var copyLayer: null       // the active layer, locked on entry (v24)
  property var copySourceLayer: null
  property var copySourceFeature: null
  property string copySourceLabel: ''
  property int copyCount: 0          // stamps this session (banner)
  property var copyUndo: null        // last target's pre-copy snapshot
  property bool copyAttrsAvailable: false
  property bool copyConfirmedThisSession: false
  property var copyPendingHit: null  // target awaiting the confirm dialog
  property var copyPendingPlan: []
  property string copyPlanSummary: ''
  property var copyExcludedFields: ({}) // source-field name -> true (session)
  property var copyDialogEntries: []    // rows shown by the field panel
  property var copyDialogChecks: ({})   // source-field name -> ticked

  // ----------------------------------------------------------------
  // Pure helpers — no QML identifiers, extracted verbatim into the
  // Node harness (tests/copy_fieldmap_harness.js). Mirrors of the
  // desktop skip rules (reconcile snapshot.py HOUSEKEEPING_PREFIXES,
  // clipper uuid detection) — keep in sync.
  // ----------------------------------------------------------------
  function isEmptyValue(value) {
    // Port of reconcile is_empty: null / '' / literal 'NULL' are empty;
    // 0 and false are real values.
    if (value === null || value === undefined)
      return true
    const text = String(value).trim()
    return text === '' || text.toUpperCase() === 'NULL'
  }

  function copyFieldIsSkipped(name) {
    // Identity, housekeeping and derived fields never transfer.
    // Elevation stays with the target (its geometry is unchanged —
    // the opposite call to the clip tool, which copies Elevation so
    // new pieces stay visible under an active Z filter). Geologist
    // stays with the target too: authorship, not content.
    const lower = String(name).toLowerCase()
    const exact = ['fid', 'id', 'ogc_fid', 'date&time', 'datetime',
                   'geologist', 'photo', 'photoid', 'sampleid', 'label',
                   'legend', 'symbolsuffix', 'easting', 'northing',
                   'elevation']
    if (exact.indexOf(lower) !== -1)
      return true
    if (lower.indexOf('uuid') !== -1 || lower.indexOf('guid') !== -1)
      return true
    const prefixes = ['mapped', 'lgs_', 'data_added_']
    for (const prefix of prefixes) {
      if (lower.indexOf(prefix) === 0)
        return true
    }
    return false
  }

  function copyFieldMapFor(srcLayerName, dstLayerName) {
    // Dormant since v24: the UI locks both taps to the active layer, so
    // only the same-layer identity branch of buildCopyPairs is reachable.
    // Kept verbatim (with its harness extraction) in case cross-layer
    // stamping returns.
    // Declarative cross-layer pair map, keyed 'src>dst' by BASE name (no
    // "N - " ordinal). Keying on identity rather than numbering means the map
    // survives a layer renumbering and works against pre-swap project
    // GeoPackages; a miss here degrades silently to the Comments/Confidence
    // whitelist in buildCopyPairs, which is why it must not depend on ordinals.
    // Pairs are kept only when both fields exist in the live schemas, so
    // entries for fields that have not been injected yet are harmless.
    const maps = {
      'Basemap>FieldNotebook': [
        ['Lithology1', 'Lithology'],
        ['Lithology2', 'Lithology2'],
        ['Lith1Mineral1', 'Mineral'],
        ['Lith1Mineral2', 'Mineral2'],
        ['Lith1Mineral3', 'Mineral3'],
        ['Lith1Mineral1Pct', 'MineralPct'],
        ['Lith1Mineral2Pct', 'Mineral2Pct'],
        ['Lith1Mineral3Pct', 'Mineral3Pct'],
        ['Lith1Texture1', 'Texture'],
        ['Lith1Texture2', 'Texture2']
      ],
      // No Lithology->Lithology1: Basemap's Lithology1 is
      // ValueRelation-filtered by TypeLith1 and the notebook has no
      // TypeLith source — a copied code could contradict the target's
      // TypeLith1.
      'FieldNotebook>Basemap': [
        ['Mineral', 'Lith1Mineral1'],
        ['Mineral2', 'Lith1Mineral2'],
        ['Mineral3', 'Lith1Mineral3'],
        ['MineralPct', 'Lith1Mineral1Pct'],
        ['Mineral2Pct', 'Lith1Mineral2Pct'],
        ['Mineral3Pct', 'Lith1Mineral3Pct'],
        ['Texture', 'Lith1Texture1'],
        ['Texture2', 'Lith1Texture2']
      ],
      // Linework's single Percent was retired for per-mineral
      // percentages (inject_linework_mineral_pcts.py); Overlay keeps
      // one Percent, so it pairs with Mineral 1's percentage.
      'Overlay>Linework': [
        ['Mineral1', 'Mineral1'],
        ['Percent', 'Mineral1Pct'],
        ['Weight', 'Weight']
      ],
      'Linework>Overlay': [
        ['Mineral1', 'Mineral1'],
        ['Mineral1Pct', 'Percent'],
        ['Weight', 'Weight']
      ]
    }
    const key = baseName(srcLayerName) + '>' + baseName(dstLayerName)
    return maps[key] !== undefined ? maps[key] : null
  }

  function buildCopyPairs(srcNames, dstNames, srcLayerName, dstLayerName) {
    // -> [{from, to}] against the live schemas. Same layer: identity
    // pairs for every non-skipped shared name. Cross layer: the pair
    // map plus the shared Comments/Confidence whitelist.
    let pairs = []
    let dstSet = {}
    for (const name of dstNames)
      dstSet[name] = true
    if (String(srcLayerName) === String(dstLayerName)) {
      for (const name of srcNames) {
        if (copyFieldIsSkipped(name))
          continue
        if (dstSet[name] !== true)
          continue
        pairs.push({ from: name, to: name })
      }
      return pairs
    }
    let srcSet = {}
    for (const name of srcNames)
      srcSet[name] = true
    let taken = {}
    const mapped = copyFieldMapFor(srcLayerName, dstLayerName)
    if (mapped !== null) {
      for (const entry of mapped) {
        if (srcSet[entry[0]] !== true || dstSet[entry[1]] !== true)
          continue
        pairs.push({ from: entry[0], to: entry[1] })
        taken[entry[1]] = true
      }
    }
    for (const name of ['Comments', 'Confidence']) {
      if (srcSet[name] === true && dstSet[name] === true &&
          taken[name] !== true)
        pairs.push({ from: name, to: name })
    }
    return pairs
  }

  // ----------------------------------------------------------------
  // Availability / layer plumbing
  // ----------------------------------------------------------------
  function initCopyAttrs() {
    try {
      copyAttrsAvailable = candidateCopyLayers().length > 0
    } catch (error) {
      copyAttrsAvailable = false
    }
  }

  function candidateCopyLayers() {
    // Since v24 this is only an availability probe (does any LGS layer
    // exist?) — taps resolve against the locked active layer instead.
    let layers = []
    for (const name of ['1 - FieldNotebook', '2 - Linework',
                        '3 - Overlay', '4 - Basemap']) {
      const layer = layerByName(name)
      if (layer !== null)
        layers.push(layer)
    }
    return layers
  }

  function copyLayerLabel(layer) {
    try {
      return layer ? String(layer.name) : ''
    } catch (error) {
      return ''
    }
  }

  function copyLayerIsLgs(layer) {
    // Identity compare against the canonical lookups — layerByName
    // already falls back through legacyLayerNames, so pre-swap
    // GeoPackages resolve too.
    if (layer === null || layer === undefined)
      return false
    for (const name of layerNames) {
      try {
        if (layerByName(name) === layer)
          return true
      } catch (error) {}
    }
    return false
  }

  // ----------------------------------------------------------------
  // Mode lifecycle
  // ----------------------------------------------------------------
  function enterCopyMode() {
    try {
      if (!canvas || canvas.width === undefined) {
        toast(qsTr('Copy unavailable — no map canvas'))
        return
      }
      updateReshapeEditingActive()
      if (reshapeEditingActive) {
        toast(qsTr('Turn digitizing off first'))
        return
      }
      if (candidateCopyLayers().length === 0) {
        toast(qsTr('Copy unavailable — no LGS layers found'))
        return
      }
      // v24: both taps are locked to the ACTIVE layer, mirroring the
      // reshape tool. No fallback sweep — a wrong-layer pick defeats
      // the point of the lock.
      const activeLayer = reshapeActiveLayer()
      if (activeLayer === null) {
        toast(qsTr('Copy unavailable — no active layer (tap one in the legend)'))
        return
      }
      if (!copyLayerIsLgs(activeLayer)) {
        toast(qsTr('Select an LGS layer first — copy works on the active layer'))
        return
      }
      copyLayer = activeLayer
      copyCatcher.parent = canvas
      copyCatcher.anchors.fill = canvas
      copyBanner.parent = canvas
      copyBanner.anchors.horizontalCenter = canvas.horizontalCenter
      copyBanner.anchors.top = canvas.top
      copyBanner.anchors.topMargin = 60
      copySourceLayer = null
      copySourceFeature = null
      copySourceLabel = ''
      copyCount = 0
      copyUndo = null
      copyConfirmedThisSession = false
      copyPendingHit = null
      copyPendingPlan = []
      copyPlanSummary = ''
      copyExcludedFields = {}
      copyDialogEntries = []
      copyDialogChecks = {}
      copyStep = 1
      toast(qsTr('Tap the feature to copy FROM (%1)')
            .arg(copyLayerLabel(copyLayer)))
    } catch (error) {
      toast(qsTr('Copy unavailable'))
    }
  }

  function exitCopyMode() {
    try {
      if (copySourceLayer !== null)
        copySourceLayer.removeSelection()
    } catch (error) {}
    copyStep = 0
    copyLayer = null
    copySourceLayer = null
    copySourceFeature = null
    copySourceLabel = ''
    copyCount = 0
    copyUndo = null
    copyConfirmedThisSession = false
    copyPendingHit = null
    copyPendingPlan = []
    copyPlanSummary = ''
    copyExcludedFields = {}
    copyDialogEntries = []
    copyDialogChecks = {}
  }

  // ----------------------------------------------------------------
  // Tap handling
  // ----------------------------------------------------------------
  function copyTapOnUi(pos) {
    // Same guard as clipTapOnUi / reverseTapOnUi — overlapping
    // TapHandlers may deliver the same tap to the canvas catcher too.
    try {
      const b = copyBanner.mapFromItem(copyCatcher, pos.x, pos.y)
      if (b.x >= 0 && b.y >= 0 &&
          b.x <= copyBanner.width && b.y <= copyBanner.height)
        return true
    } catch (error) {}
    try {
      const o = overlayBar.mapFromItem(copyCatcher, pos.x, pos.y)
      if (o.x >= 0 && o.y >= 0 &&
          o.x <= overlayBar.width && o.y <= overlayBar.height)
        return true
    } catch (error) {}
    try {
      if (zDialog.visible) {
        const d = mainWindow.contentItem.mapFromItem(
            copyCatcher, pos.x, pos.y)
        if (d.x >= zDialog.x && d.y >= zDialog.y &&
            d.x <= zDialog.x + zDialog.width &&
            d.y <= zDialog.y + zDialog.height)
          return true
      }
    } catch (error) {}
    return false
  }

  function handleCopyTap(pos) {
    try {
      if (copyStep !== 1 && copyStep !== 2)
        return
      if (copyTapOnUi(pos))
        return
      // The iterator honours the layer subsetString, so an active Z
      // filter means only VISIBLE features are tappable. Locked to the
      // active layer since v24 — one call site covers both taps.
      const hit = findHitInLayers([copyLayer], pos)
      if (hit === null) {
        toast(qsTr('No feature here'))
        return
      }
      if (copyStep === 1) {
        copySourceLayer = hit.layer
        copySourceFeature = hit.feature
        copySourceLabel = copyLayerLabel(hit.layer)
        try {
          LayerUtils.selectFeaturesInLayer(copySourceLayer,
                                           [hit.feature.id])
        } catch (error) {
          try {
            copySourceLayer.selectByIds([hit.feature.id])
          } catch (error2) {}
        }
        copyStep = 2
        toast(qsTr('Source armed — now tap a feature to copy TO'))
        return
      }
      let sameFeature = false
      try {
        sameFeature = hit.layer === copySourceLayer &&
                      hit.feature.id === copySourceFeature.id
      } catch (error) {}
      if (sameFeature) {
        toast(qsTr('That is the source feature'))
        return
      }
      const plan = buildCopyPlan(hit.layer, hit.feature)
      if (plan.length === 0) {
        toast(qsTr('No compatible fields between %1 and %2')
              .arg(copySourceLabel).arg(copyLayerLabel(hit.layer)))
        return
      }
      if (!copyConfirmedThisSession) {
        // First stamp of the session opens the field panel; later
        // stamps apply instantly with the ticked set — that is the
        // rapid-stamping win.
        copyPendingHit = hit
        copyPendingPlan = plan
        copyPlanSummary = copyPlanSummaryText(plan, hit)
        openCopyFieldPanel(plan)
        return
      }
      applyCopyPlan(hit.layer, hit.feature, plan)
    } catch (error) {}
  }

  // ----------------------------------------------------------------
  // Plan building / execution
  // ----------------------------------------------------------------
  function buildCopyPlan(dstLayer, dstFeature) {
    // -> [{name, value}] against the TARGET schema. Source-empty
    // values are dropped so a copy never blanks target data.
    try {
      const srcNames = attributeNames(copySourceLayer, copySourceFeature)
      const dstNames = attributeNames(dstLayer, dstFeature)
      const pairs = buildCopyPairs(srcNames, dstNames, copySourceLabel,
                                   copyLayerLabel(dstLayer))
      // A NULL number reaches JS as 0 (see featureNulls) — without this
      // the plan would offer, and stamp, 'Width_cm = 0' from a source
      // whose width was never recorded.
      const srcNulls = featureNulls(copySourceLayer, copySourceFeature,
                                    srcNames)
      let plan = []
      for (const pair of pairs) {
        if (srcNulls[pair.from] === true)
          continue
        let value = null
        try {
          value = copySourceFeature.attribute(pair.from)
        } catch (error) {
          continue
        }
        if (isEmptyValue(value))
          continue
        // Session field choices from the checkbox panel, keyed by the
        // SOURCE field so they hold across same- and cross-layer stamps.
        if (copyExcludedFields[pair.from] === true)
          continue
        plan.push({ from: pair.from, name: pair.to, value: value })
      }
      return plan
    } catch (error) {
      return []
    }
  }

  function copyPlanSummaryText(plan, hit) {
    // The checkbox rows list the fields themselves — the summary just
    // names the direction.
    return qsTr('%1 field(s) from %2 to %3 — untick anything you do not want copied.')
        .arg(plan.length).arg(copySourceLabel)
        .arg(copyLayerLabel(hit.layer))
  }

  function copySourceFieldList() {
    // The armed source's copyable fields (non-empty, non-skipped) —
    // the panel rows when reopened from the banner, so previously
    // unticked fields can be re-ticked.
    let list = []
    try {
      const names = attributeNames(copySourceLayer, copySourceFeature)
      const srcNulls = featureNulls(copySourceLayer, copySourceFeature, names)
      for (const name of names) {
        if (copyFieldIsSkipped(name))
          continue
        if (srcNulls[name] === true)
          continue
        let value = null
        try {
          value = copySourceFeature.attribute(name)
        } catch (error) {
          continue
        }
        if (isEmptyValue(value))
          continue
        list.push({ from: name, label: name + ' = ' + String(value) })
      }
    } catch (error) {}
    return list
  }

  function openCopyFieldPanel(plan) {
    // plan !== null: first-stamp confirm (rows = the pending plan).
    // plan === null: reopened via the banner's Fields… button.
    let entries = []
    if (plan !== null) {
      for (const entry of plan)
        entries.push({ from: entry.from,
                       label: entry.name + ' = ' + String(entry.value) })
    } else {
      entries = copySourceFieldList()
      copyPlanSummary = qsTr('Source: %1 — ticked fields copy on each stamp.')
          .arg(copySourceLabel)
    }
    if (entries.length === 0) {
      toast(qsTr('No copyable fields on the source'))
      return
    }
    let checks = {}
    for (const entry of entries)
      checks[entry.from] = copyExcludedFields[entry.from] !== true
    copyDialogChecks = checks   // before entries: delegates bind on create
    copyDialogEntries = entries
    copyConfirmDialog.open()
  }

  function foldCopyDialogChecks() {
    // Merge the panel's checkbox state into the session exclusions —
    // fields not shown this time keep their previous setting.
    let excluded = {}
    for (const name in copyExcludedFields)
      excluded[name] = true
    for (const entry of copyDialogEntries) {
      if (copyDialogChecks[entry.from] === false)
        excluded[entry.from] = true
      else
        delete excluded[entry.from]
    }
    copyExcludedFields = excluded
  }

  function applyCopyPlan(dstLayer, dstFeature, plan) {
    // The sidecar's established write path: recreate the target with
    // its own geometry + UUID (add-before-delete, same as Reverse),
    // then overlay the plan values.
    try {
      const wkt = evalExpr(dstLayer, dstFeature, 'geom_to_wkt($geometry)')
      if (wkt === '') {
        toast(qsTr('Copy failed — target geometry unreadable'))
        return
      }
      const names = attributeNames(dstLayer, dstFeature)
      const uuidField = detectUuidField(names)
      let priorUuid = ''
      if (uuidField !== null) {
        try {
          priorUuid = String(dstFeature.attribute(uuidField))
        } catch (error) {}
      }
      const geometry = GeometryUtils.createGeometryFromWkt(wkt)
      let created = FeatureUtils.createFeature(dstLayer, geometry)
      copyClipAttributes(created, dstFeature, names, null, '', dstLayer)
      for (const entry of plan) {
        try {
          created.setAttribute(entry.name, entry.value)
        } catch (error) {}
      }
      if (!applyClipEdits(dstLayer, [created], [dstFeature.id])) {
        toast(qsTr('Copy failed — no changes made'))
        return
      }
      if (uuidField !== null && priorUuid !== '' && priorUuid !== 'NULL') {
        const fids = collectFidsByExpression(dstLayer,
            '"' + uuidField + '" = \'' + priorUuid + '\'')
        if (fids.length !== 1)
          toast(qsTr('Warning: copied feature not verified'))
      }
      copyUndo = {
        layer: dstLayer,
        layerName: copyLayerLabel(dstLayer),
        names: names,
        uuidField: uuidField,
        uuid: priorUuid,
        wkt: wkt,
        feature: dstFeature
      }
      try {
        dstLayer.triggerRepaint()
        iface.mapCanvas().refresh()
      } catch (error) {}
      copyCount++
      toast(qsTr('Copied %1 field(s) — tap another feature or Done')
            .arg(plan.length))
    } catch (error) {
      toast(qsTr('Copy failed'))
    }
  }

  function undoLastCopy() {
    // One level: restore the LAST target's pre-copy attributes from
    // the snapshot (delete stamped + recreate, UUID preserved — same
    // shape as undoLastReshape).
    try {
      const undo = copyUndo
      if (undo === null)
        return
      let layer = undo.layer
      let alive = false
      try {
        alive = layer !== null && layer.name !== undefined
      } catch (error) {}
      if (!alive)
        layer = layerByName(undo.layerName)
      if (layer === null) {
        toast(qsTr('Undo failed — layer not found'))
        return
      }
      // Locate the stamped feature fresh by UUID (fids survive
      // commits but a resync could renumber them).
      let doomed = []
      if (undo.uuidField !== null && undo.uuid !== '' &&
          undo.uuid !== 'NULL')
        doomed = collectFidsByExpression(layer,
            '"' + undo.uuidField + '" = \'' + undo.uuid + '\'')
      if (doomed.length === 0) {
        toast(qsTr('Undo failed — copied feature not found'))
        return
      }
      const geometry = GeometryUtils.createGeometryFromWkt(undo.wkt)
      let restored = FeatureUtils.createFeature(layer, geometry)
      copyClipAttributes(restored, undo.feature, undo.names, null, '',
                         layer)
      if (!applyClipEdits(layer, [restored], doomed)) {
        toast(qsTr('Undo failed — no changes made'))
        return
      }
      try {
        layer.triggerRepaint()
        iface.mapCanvas().refresh()
      } catch (error) {}
      copyUndo = null
      if (copyCount > 0)
        copyCount--
      toast(qsTr('Copy undone'))
    } catch (error) {
      toast(qsTr('Undo failed'))
    }
  }

  // ----------------------------------------------------------------
  // Copy UI: tap catcher + banner + confirm dialog
  // ----------------------------------------------------------------
  Item {
    id: copyCatcher
    visible: plugin.copyStep > 0
    z: 1

    TapHandler {
      // Default DragThreshold gesture policy: passive grab, so pan and
      // pinch on the canvas underneath keep working.
      onSingleTapped: function(eventPoint, button) {
        plugin.handleCopyTap(eventPoint.position)
      }
    }
  }

  Rectangle {
    id: copyBanner
    visible: plugin.copyStep > 0
    z: 3
    radius: 8
    color: '#CC000000'
    width: Math.min((parent !== null ? parent.width : 444) - 24, 420)
    height: copyBannerColumn.height + 24

    Column {
      id: copyBannerColumn
      anchors.top: parent.top
      anchors.topMargin: 12
      anchors.horizontalCenter: parent.horizontalCenter
      width: parent.width - 24
      spacing: 8

      Text {
        width: parent.width
        font.pixelSize: 15
        font.bold: true
        color: 'white'
        text: qsTr('Copy attributes')
      }

      Text {
        width: parent.width
        wrapMode: Text.WordWrap
        font.pixelSize: 14
        color: 'white'
        text: plugin.copyStep === 1
            ? qsTr('Tap the feature to copy FROM · %1')
                  .arg(plugin.copyLayerLabel(plugin.copyLayer))
            : qsTr('Tap features to copy TO — the source stays armed. Only non-empty source values are written.')
      }

      Text {
        visible: plugin.copyStep === 2
        width: parent.width
        wrapMode: Text.WordWrap
        font.pixelSize: 12
        color: '#CCFFFFFF'
        text: plugin.copyCount > 0
            ? qsTr('%1 copied from %2 — Undo covers the last one')
                  .arg(plugin.copyCount).arg(plugin.copySourceLabel)
            : qsTr('Source: %1').arg(plugin.copySourceLabel)
      }

      Flow {
        width: parent.width
        spacing: 8

        Button {
          visible: plugin.copyStep === 2
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Fields…')
            color: 'white'
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: '#66000000'
            border.color: 'white'
            border.width: 1
            radius: 4
          }
          onClicked: plugin.openCopyFieldPanel(null)
        }

        Button {
          visible: plugin.copyUndo !== null
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Undo')
            color: 'white'
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: '#66000000'
            border.color: 'white'
            border.width: 1
            radius: 4
          }
          onClicked: plugin.undoLastCopy()
        }

        Button {
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Done')
            color: 'white'
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: Theme.mainColor
            border.color: Theme.mainColor
            border.width: 1
            radius: 4
          }
          onClicked: plugin.exitCopyMode()
        }
      }
    }
  }

  Dialog {
    id: copyConfirmDialog
    parent: mainWindow.contentItem
    modal: true
    title: qsTr('Copy attributes')
    x: (mainWindow.width - width) / 2
    y: (mainWindow.height - height) / 2
    width: Math.min(mainWindow.width - 40, 420)
    standardButtons: Dialog.Ok | Dialog.Cancel

    onOpened: {
      try {
        const okButton = copyConfirmDialog.standardButton(Dialog.Ok)
        if (okButton)
          okButton.text = qsTr('Copy now')
      } catch (error) {}
    }

    onAccepted: {
      // Later stamps this session skip the dialog and reuse the
      // ticked set (reopenable via the banner's Fields… button).
      plugin.copyConfirmedThisSession = true
      plugin.foldCopyDialogChecks()
      const hit = plugin.copyPendingHit
      let plan = plugin.copyPendingPlan
      plugin.copyPendingHit = null
      plugin.copyPendingPlan = []
      if (hit !== null) {
        plan = plan.filter(function(entry) {
          return plugin.copyExcludedFields[entry.from] !== true
        })
        if (plan.length > 0)
          plugin.applyCopyPlan(hit.layer, hit.feature, plan)
        else
          plugin.toast(qsTr('No fields ticked — nothing copied'))
      }
    }

    onRejected: {
      plugin.copyPendingHit = null
      plugin.copyPendingPlan = []
    }

    ColumnLayout {
      anchors.fill: parent
      spacing: 8

      Label {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        text: plugin.copyPlanSummary
      }

      Flickable {
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(copyFieldColumn.height,
                                         mainWindow.height * 0.45)
        contentHeight: copyFieldColumn.height
        clip: true

        Column {
          id: copyFieldColumn
          width: parent.width

          Repeater {
            model: plugin.copyDialogEntries

            CheckBox {
              width: copyFieldColumn.width
              text: modelData.label
              checked: plugin.copyDialogChecks[modelData.from] === true
              onToggled: plugin.copyDialogChecks[modelData.from] = checked
            }
          }
        }
      }

      Label {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        font.pixelSize: 12
        opacity: 0.7
        text: qsTr('Ticked fields copy on every stamp this session — reopen with Fields… on the banner. Undo covers the last stamp.')
      }
    }
  }

  // ================================================================
  // MERGE (v22) — dissolve 2+ polygons on one layer into a single
  // polygon. The FIRST pick keeps its attributes and UUID; its empty
  // fields are filled from the other picks (carry_attrs semantics).
  // Disjoint picks are refused — the union must be ONE polygon.
  // ================================================================

  property int mergeStep: 0          // 0=off, 1=picking, 2=done
  property var mergeLayer: null      // locked by the first pick
  property var mergeFeatures: []     // [{id, feature}] in PICK ORDER
  property var mergeUndo: null
  property bool mergeAvailable: false
  property string mergeResultText: ''
  property string mergePendingWkt: ''

  // ----------------------------------------------------------------
  // Pure helper — extracted into tests/merge_carry_harness.js.
  // ----------------------------------------------------------------
  function mergeCarryValues(keeperValues, parentValuesList, names) {
    // Port of reconcile carry_attrs (lineage.py): fill the keeper's
    // EMPTY content fields from the other parents — first non-empty
    // value in pick order wins; keeper values are never overwritten;
    // identity/housekeeping fields are never carried.
    let fills = {}
    for (const name of names) {
      if (copyFieldIsSkipped(name))
        continue
      if (!isEmptyValue(keeperValues[name]))
        continue
      for (const parentValues of parentValuesList) {
        const value = parentValues[name]
        if (isEmptyValue(value))
          continue
        fills[name] = value
        break
      }
    }
    return fills
  }

  // ----------------------------------------------------------------
  // Availability / layer plumbing
  // ----------------------------------------------------------------
  function initMerge() {
    // Pill availability from the standard polygon layers only — the
    // active layer is re-probed on entry (the dashboard may not exist
    // yet at startup).
    try {
      mergeAvailable = false
      for (const name of clipLayerNames) {
        if (layerByName(name) !== null) {
          mergeAvailable = true
          break
        }
      }
    } catch (error) {
      mergeAvailable = false
    }
  }

  function layerIsPolygon(layer) {
    if (layer === null || layer === undefined)
      return false
    return evalExpr(layer, null,
                    "layer_property(@layer, 'geometry_type')") === 'Polygon'
  }

  function candidateMergeLayers() {
    // Active layer first — merge what you're working on — then the
    // standard LGS polygon layers.
    let layers = []
    try {
      const active = reshapeActiveLayer()
      if (layerIsPolygon(active))
        layers.push(active)
    } catch (error) {}
    for (const name of clipLayerNames) {
      const layer = layerByName(name)
      if (layer === null || !layerIsPolygon(layer))
        continue
      let seen = false
      for (const known of layers) {
        try {
          if (known === layer)
            seen = true
        } catch (error) {}
      }
      if (!seen)
        layers.push(layer)
    }
    return layers
  }

  function mergeLayerLabel() {
    try {
      return mergeLayer ? String(mergeLayer.name) : ''
    } catch (error) {
      return ''
    }
  }

  // ----------------------------------------------------------------
  // Mode lifecycle
  // ----------------------------------------------------------------
  function enterMergeMode() {
    try {
      if (!canvas || canvas.width === undefined) {
        toast(qsTr('Merge unavailable — no map canvas'))
        return
      }
      updateReshapeEditingActive()
      if (reshapeEditingActive) {
        toast(qsTr('Turn digitizing off first'))
        return
      }
      if (candidateMergeLayers().length === 0) {
        toast(qsTr('Merge unavailable — no polygon layer found'))
        return
      }
      mergeCatcher.parent = canvas
      mergeCatcher.anchors.fill = canvas
      mergeBanner.parent = canvas
      mergeBanner.anchors.horizontalCenter = canvas.horizontalCenter
      mergeBanner.anchors.top = canvas.top
      mergeBanner.anchors.topMargin = 60
      mergeLayer = null
      mergeFeatures = []
      mergeUndo = null
      mergeResultText = ''
      mergePendingWkt = ''
      mergeStep = 1
      toast(qsTr('Tap 2 or more polygons to merge — the first keeps its attributes'))
    } catch (error) {
      toast(qsTr('Merge unavailable'))
    }
  }

  function exitMergeMode() {
    try {
      if (mergeLayer !== null)
        mergeLayer.removeSelection()
    } catch (error) {}
    mergeStep = 0
    mergeLayer = null
    mergeFeatures = []
    mergeResultText = ''
    mergePendingWkt = ''
  }

  function mergeBackToPicks() {
    // 'Merge more' from the done step — keep the undo armed.
    mergeLayer = null
    mergeFeatures = []
    mergeResultText = ''
    mergePendingWkt = ''
    mergeStep = 1
    toast(qsTr('Tap 2 or more polygons to merge'))
  }

  // ----------------------------------------------------------------
  // Tap handling
  // ----------------------------------------------------------------
  function mergeTapOnUi(pos) {
    // Same guard as clipTapOnUi / reverseTapOnUi.
    try {
      const b = mergeBanner.mapFromItem(mergeCatcher, pos.x, pos.y)
      if (b.x >= 0 && b.y >= 0 &&
          b.x <= mergeBanner.width && b.y <= mergeBanner.height)
        return true
    } catch (error) {}
    try {
      const o = overlayBar.mapFromItem(mergeCatcher, pos.x, pos.y)
      if (o.x >= 0 && o.y >= 0 &&
          o.x <= overlayBar.width && o.y <= overlayBar.height)
        return true
    } catch (error) {}
    try {
      if (zDialog.visible) {
        const d = mainWindow.contentItem.mapFromItem(
            mergeCatcher, pos.x, pos.y)
        if (d.x >= zDialog.x && d.y >= zDialog.y &&
            d.x <= zDialog.x + zDialog.width &&
            d.y <= zDialog.y + zDialog.height)
          return true
      }
    } catch (error) {}
    return false
  }

  function handleMergeTap(pos) {
    try {
      if (mergeStep !== 1)
        return
      if (mergeTapOnUi(pos))
        return
      // Picks lock to the first pick's layer — same-layer merges only.
      // The iterator honours the layer subsetString: merge what you see.
      const hit = findHitInLayers(
          mergeLayer !== null ? [mergeLayer] : candidateMergeLayers(), pos)
      if (hit === null) {
        toast(mergeLayer !== null
            ? qsTr('No polygon here on %1').arg(mergeLayerLabel())
            : qsTr('No polygon here'))
        return
      }
      if (mergeLayer === null) {
        mergeLayer = hit.layer
        toast(qsTr('Using layer: %1 — the first pick keeps its attributes')
              .arg(mergeLayerLabel()))
      }
      mergeFeatures = toggleClipPick(mergeFeatures, hit.feature.id,
                                     hit.feature)
      if (mergeFeatures.length === 0) {
        // Everything unpicked — unlock so picking can restart on any
        // candidate layer.
        try {
          mergeLayer.removeSelection()
        } catch (error) {}
        mergeLayer = null
        return
      }
      updateMergeSelection()
    } catch (error) {}
  }

  function updateMergeSelection() {
    if (mergeLayer === null)
      return
    let fids = []
    for (const entry of mergeFeatures)
      fids.push(entry.id)
    try {
      if (fids.length === 0) {
        mergeLayer.removeSelection()
        return
      }
      LayerUtils.selectFeaturesInLayer(mergeLayer, fids)
    } catch (error) {
      try {
        mergeLayer.selectByIds(fids)
      } catch (error2) {}
    }
  }

  // ----------------------------------------------------------------
  // Geometry / execution
  // ----------------------------------------------------------------
  function buildMergeUnionWkt() {
    // QgsGeometry.unaryUnion equivalent: fold union() over the picked
    // geometries in the expression engine, make_valid the result
    // (same shape as buildCutterUnionWkt).
    try {
      let expr = null
      for (const entry of mergeFeatures) {
        const wkt = evalExpr(mergeLayer, entry.feature,
                             'geom_to_wkt($geometry)')
        if (wkt === '')
          continue
        const geomExpr = "geom_from_wkt('" + wkt + "')"
        expr = expr === null
            ? geomExpr : 'union(' + expr + ', ' + geomExpr + ')'
      }
      if (expr === null)
        return ''
      return evalExpr(mergeLayer, mergeFeatures[0].feature,
                      'geom_to_wkt(make_valid(' + expr + '))')
    } catch (error) {
      return ''
    }
  }

  function requestMerge() {
    // 'Merge ✓' button: union first so the confirm dialog only opens
    // for a merge that will actually produce ONE polygon.
    try {
      if (mergeFeatures.length < 2)
        return
      const unionWkt = buildMergeUnionWkt()
      if (unionWkt === '' ||
          unionWkt.toUpperCase().indexOf('EMPTY') !== -1) {
        toast(qsTr('Merge failed — could not combine the polygons'))
        return
      }
      const parts = splitMultiPolygonWkt(unionWkt)
      if (parts.length !== 1) {
        // The LGS GeoPackage layers are single-polygon; committing a
        // MultiPolygon is unproven on-device, and an upfront refusal
        // beats a silent rollback mid-field.
        toast(qsTr('Polygons must touch — merging these would leave %1 separate parts')
              .arg(parts.length === 0 ? 2 : parts.length))
        return
      }
      mergePendingWkt = parts[0]
      mergeConfirmDialog.open()
    } catch (error) {
      toast(qsTr('Merge failed'))
    }
  }

  function executeMerge() {
    try {
      const layer = mergeLayer
      if (layer === null || mergeFeatures.length < 2 ||
          mergePendingWkt === '')
        return
      const keeper = mergeFeatures[0]
      const names = attributeNames(layer, keeper.feature)
      const uuidField = detectUuidField(names)
      let keeperUuid = ''
      if (uuidField !== null) {
        try {
          keeperUuid = String(keeper.feature.attribute(uuidField))
        } catch (error) {}
      }
      // Pre-edit snapshots (undo) + attribute maps (carry fills).
      let parents = []
      let deleteIds = []
      let keeperValues = ({})
      let parentValuesList = []
      let otherUuids = []
      for (let i = 0; i < mergeFeatures.length; i++) {
        const entry = mergeFeatures[i]
        const wkt = evalExpr(layer, entry.feature,
                             'geom_to_wkt($geometry)')
        if (wkt === '') {
          toast(qsTr('Merge failed — a polygon geometry is unreadable'))
          return
        }
        parents.push({ wkt: wkt, feature: entry.feature })
        deleteIds.push(entry.id)
        // NULL is written into the map explicitly: read straight off
        // the feature a NULL number arrives as 0 (see featureNulls),
        // and mergeCarryValues would then treat it as a real value —
        // filling the keeper with 0 or refusing to be filled itself.
        const parentNulls = featureNulls(layer, entry.feature, names)
        let values = ({})
        for (const name of names) {
          try {
            values[name] = parentNulls[name] === true
                ? null : entry.feature.attribute(name)
          } catch (error) {}
        }
        if (i === 0) {
          keeperValues = values
        } else {
          parentValuesList.push(values)
          if (uuidField !== null) {
            try {
              const parentUuid = String(entry.feature.attribute(uuidField))
              if (parentUuid !== '' && parentUuid !== 'NULL')
                otherUuids.push(parentUuid)
            } catch (error) {}
          }
        }
      }
      const geometry = GeometryUtils.createGeometryFromWkt(mergePendingWkt)
      let created = FeatureUtils.createFeature(layer, geometry)
      // Keeper attributes verbatim, UUID preserved — identity
      // continuity, same rules as Reverse / the reshape undo.
      copyClipAttributes(created, keeper.feature, names, null, '', layer)
      const fills = mergeCarryValues(keeperValues, parentValuesList, names)
      for (const name in fills) {
        try {
          created.setAttribute(name, fills[name])
        } catch (error) {}
      }
      // Reconcile lineage stamp — attempt-and-verify: the column does
      // not exist on today's device exports so this is a silent no-op;
      // it activates if the lgs_* lineage columns ever ship. Desktop
      // reconcile detects the merge geometrically either way (keep in
      // sync: script_adddata/reconcile/lineage.py).
      if (otherUuids.length > 0) {
        try {
          created.setAttribute('lgs_merged_from', otherUuids.join(','))
        } catch (error) {}
      }
      if (!applyClipEdits(layer, [created], deleteIds)) {
        toast(qsTr('Merge failed — no changes made'))
        return
      }
      // Read-back verify by the keeper UUID (it survives on the
      // merged polygon).
      if (uuidField !== null && keeperUuid !== '' &&
          keeperUuid !== 'NULL') {
        const fids = collectFidsByExpression(layer,
            '"' + uuidField + '" = \'' + keeperUuid + '\'')
        if (fids.length !== 1)
          toast(qsTr('Warning: merged polygon not verified'))
      }
      mergeUndo = {
        layer: layer,
        layerName: mergeLayerLabel(),
        names: names,
        uuidField: uuidField,
        keeperUuid: keeperUuid,
        parents: parents
      }
      try {
        layer.removeSelection()
        layer.triggerRepaint()
        iface.mapCanvas().refresh()
      } catch (error) {}
      mergeResultText = qsTr('%1 polygons merged into one')
          .arg(parents.length)
      mergeFeatures = []
      mergePendingWkt = ''
      mergeStep = 2
      toast(mergeResultText)
    } catch (error) {
      toast(qsTr('Merge failed'))
    }
  }

  function undoLastMerge() {
    // Restore every parent from its pre-merge WKT (all original UUIDs
    // preserved), delete the merged polygon — one edit session, adds
    // before deletes.
    try {
      const undo = mergeUndo
      if (undo === null)
        return
      let layer = undo.layer
      let alive = false
      try {
        alive = layer !== null && layer.name !== undefined
      } catch (error) {}
      if (!alive)
        layer = layerByName(undo.layerName)
      if (layer === null) {
        toast(qsTr('Undo failed — layer not found'))
        return
      }
      let doomed = []
      if (undo.uuidField !== null && undo.keeperUuid !== '' &&
          undo.keeperUuid !== 'NULL')
        doomed = collectFidsByExpression(layer,
            '"' + undo.uuidField + '" = \'' + undo.keeperUuid + '\'')
      if (doomed.length === 0) {
        toast(qsTr('Undo failed — merged polygon not found'))
        return
      }
      let restored = []
      for (const parent of undo.parents) {
        const geometry = GeometryUtils.createGeometryFromWkt(parent.wkt)
        let feature = FeatureUtils.createFeature(layer, geometry)
        copyClipAttributes(feature, parent.feature, undo.names, null, '',
                           layer)
        restored.push(feature)
      }
      if (!applyClipEdits(layer, restored, doomed)) {
        toast(qsTr('Undo failed — no changes made'))
        return
      }
      try {
        layer.triggerRepaint()
        iface.mapCanvas().refresh()
      } catch (error) {}
      mergeUndo = null
      mergeResultText = ''
      toast(qsTr('Merge undone'))
    } catch (error) {
      toast(qsTr('Undo failed'))
    }
  }

  // ----------------------------------------------------------------
  // Merge UI: tap catcher + banner + confirm dialog
  // ----------------------------------------------------------------
  Item {
    id: mergeCatcher
    visible: plugin.mergeStep === 1
    z: 1

    TapHandler {
      // Passive grab — pan and pinch keep working under the catcher.
      onSingleTapped: function(eventPoint, button) {
        plugin.handleMergeTap(eventPoint.position)
      }
    }
  }

  Rectangle {
    id: mergeBanner
    visible: plugin.mergeStep > 0
    z: 3
    radius: 8
    color: '#CC000000'
    width: Math.min((parent !== null ? parent.width : 444) - 24, 420)
    height: mergeBannerColumn.height + 24

    Column {
      id: mergeBannerColumn
      anchors.top: parent.top
      anchors.topMargin: 12
      anchors.horizontalCenter: parent.horizontalCenter
      width: parent.width - 24
      spacing: 8

      Text {
        width: parent.width
        font.pixelSize: 15
        font.bold: true
        color: 'white'
        text: qsTr('Merge polygons')
      }

      Text {
        width: parent.width
        wrapMode: Text.WordWrap
        font.pixelSize: 14
        color: 'white'
        text: plugin.mergeStep === 1
            ? qsTr('Tap 2 or more polygons on one layer — the FIRST keeps its attributes and identity; its empty fields are filled from the others. Tap a polygon again to unpick it.')
            : plugin.mergeResultText
      }

      Text {
        visible: plugin.mergeStep === 1 && plugin.mergeFeatures.length > 0
        width: parent.width
        wrapMode: Text.WordWrap
        font.pixelSize: 12
        color: '#CCFFFFFF'
        text: qsTr('%1 picked on %2 — first pick is the keeper')
              .arg(plugin.mergeFeatures.length).arg(plugin.mergeLayerLabel())
      }

      Flow {
        width: parent.width
        spacing: 8

        Button {
          visible: plugin.mergeStep === 1
          enabled: plugin.mergeFeatures.length >= 2
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Merge ✓')
            color: parent.enabled ? 'white' : '#66FFFFFF'
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: parent.enabled ? Theme.mainColor : '#33000000'
            border.color: parent.enabled ? Theme.mainColor : '#33000000'
            border.width: 1
            radius: 4
          }
          onClicked: plugin.requestMerge()
        }

        Button {
          visible: plugin.mergeStep === 2
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Merge more')
            color: 'white'
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: '#66000000'
            border.color: 'white'
            border.width: 1
            radius: 4
          }
          onClicked: plugin.mergeBackToPicks()
        }

        Button {
          visible: plugin.mergeStep === 2 && plugin.mergeUndo !== null
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: qsTr('Undo last merge')
            color: 'white'
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: '#66000000'
            border.color: 'white'
            border.width: 1
            radius: 4
          }
          onClicked: {
            plugin.undoLastMerge()
            plugin.exitMergeMode()
          }
        }

        Button {
          flat: true
          topPadding: 8
          bottomPadding: 8
          leftPadding: 14
          rightPadding: 14
          contentItem: Text {
            text: plugin.mergeStep === 1 ? qsTr('Cancel') : qsTr('Done')
            color: 'white'
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
          }
          background: Rectangle {
            color: Theme.mainColor
            border.color: Theme.mainColor
            border.width: 1
            radius: 4
          }
          onClicked: plugin.exitMergeMode()
        }
      }
    }
  }

  Dialog {
    id: mergeConfirmDialog
    parent: mainWindow.contentItem
    modal: true
    title: qsTr('Merge polygons')
    x: (mainWindow.width - width) / 2
    y: (mainWindow.height - height) / 2
    width: Math.min(mainWindow.width - 40, 420)
    standardButtons: Dialog.Ok | Dialog.Cancel

    onOpened: {
      try {
        const okButton = mergeConfirmDialog.standardButton(Dialog.Ok)
        if (okButton)
          okButton.text = qsTr('Merge now')
      } catch (error) {}
    }

    onAccepted: plugin.executeMerge()

    onRejected: plugin.mergePendingWkt = ''

    ColumnLayout {
      anchors.fill: parent
      spacing: 8

      Label {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        text: {
          let lines = qsTr('%1 polygons will merge into one on %2.')
              .arg(plugin.mergeFeatures.length)
              .arg(plugin.mergeLayerLabel())
          lines += '\n' + qsTr('The first polygon you tapped keeps its attributes and identity; its empty fields are filled from the others.')
          lines += '\n' + qsTr('The other %1 polygon(s) are deleted.')
              .arg(Math.max(plugin.mergeFeatures.length - 1, 0))
          return lines
        }
      }
    }
  }

  // ================================================================
  // RECENTER HOLD (v23)
  //
  // QField's freehand digitizing recenters the map whenever a stroke
  // ends near a screen edge (qgismobileapp.qml freehandHandler
  // onActiveChanged), yanking the canvas mid-drawing. The trigger
  // distance is min(width, height) / screenFraction, with
  // screenFraction read LIVE on every stroke from the hidden settings
  // key below (stock default 5). Writing a huge sentinel drives the
  // threshold below one pixel so the recenter never fires; restoring
  // the stock value brings QField's behaviour back. No QField
  // patching, effective immediately. The key lives in QSettings, so
  // the hold persists across QField restarts — initRecenterHold()
  // re-detects the sentinel to restore the pill state. Unlocking
  // writes the stock default rather than a saved prior value: the key
  // is hidden and nobody hand-tunes it.
  // ================================================================

  property bool recenterHoldAvailable: false
  property bool recenterHoldActive: false
  readonly property string recenterHoldKey:
      '/QField/Digitizing/FreehandRecenterScreenFraction'
  readonly property real recenterHoldSentinel: 1000000
  readonly property real recenterHoldStockFraction: 5

  function initRecenterHold() {
    // `settings` is a root-context property of the QField engine (a
    // QSettings wrapper) — absent on hosts that don't expose it.
    if (typeof settings === 'undefined' || !settings)
      return
    try {
      const fraction = Number(settings.value(
          recenterHoldKey, recenterHoldStockFraction))
      recenterHoldActive = fraction >= recenterHoldSentinel / 2
      recenterHoldAvailable = true
    } catch (error) {
      // Leave the pill hidden rather than offer a dead toggle.
    }
  }

  function setRecenterHold(on) {
    try {
      settings.setValue(recenterHoldKey,
          on ? recenterHoldSentinel : recenterHoldStockFraction)
    } catch (error) {
      toast(qsTr('Could not change the recenter setting'))
      return
    }
    recenterHoldActive = on
    toast(on ? qsTr('Map hold ON — drawing will not recentre the map')
             : qsTr('Map hold off — QField recentring restored'))
  }

  // ================================================================
  // MODE TOGGLE (v24) — an always-visible Browse/Digitise pill, so
  // the geologist can flip modes without opening the side dashboard.
  // Rides QField's own state machine (objectName 'stateMachine',
  // states browse/digitize/measure/3d) and its toggleDigitizeMode
  // signal — chosen over changeMode('...') because QField's handler
  // refuses to leave digitize mid-feature and says so with its own
  // toast, a guard worth keeping.
  // ================================================================

  property var modeStateMachine: null
  property string mapModeState: 'browse'

  function initModeToggle() {
    // Lazy find, same pattern as splineLocator / reshapeDashboard —
    // idempotent, so the rubberband Connections above can re-probe.
    try {
      if (modeStateMachine === null)
        modeStateMachine = iface.findItemByObjectName('stateMachine')
    } catch (error) {}
    refreshMapModeState()
  }

  function refreshMapModeState() {
    // Unreadable (older/newer QField) counts as browse — the pill then
    // still toggles correctly, it just may not show the armed face.
    let state = 'browse'
    try {
      if (modeStateMachine !== null && modeStateMachine !== undefined &&
          modeStateMachine.state !== undefined)
        state = String(modeStateMachine.state)
    } catch (error) {}
    mapModeState = state
  }

  function toggleMapMode() {
    try {
      mainWindow.toggleDigitizeMode()
    } catch (error) {
      toast(qsTr('Could not switch mode'))
    }
    refreshMapModeState()
  }

  Connections {
    // A null target is legal and inert, so this is safe before (or
    // without) a successful initModeToggle find.
    target: plugin.modeStateMachine
    ignoreUnknownSignals: true
    function onStateChanged() {
      plugin.refreshMapModeState()
    }
  }
}
