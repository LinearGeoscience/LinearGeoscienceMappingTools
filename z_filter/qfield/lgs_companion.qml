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
 *    While active, ▼/▲ pills on the canvas step between known levels, and
 *    the "Include adjacent levels" switch widens the subset to the bench
 *    below + current + above (device-only clause shape — the desktop
 *    never parses device subsets, they're ephemeral).
 *
 * 2. SCALE DISPLAY + LOCK — live "1:2 500" pill overlaid on the map
 *    canvas; tap it to lock the map to a fixed scale (presets or custom).
 *    While locked, pinch-zooms snap back to the locked scale (pans stay
 *    free). Uses QgsQuickMapCanvasMap.zoomScale(center, scale) — a public
 *    slot — with a writable mapSettings.extent fallback.
 *
 * 3. IMAGERY OPACITY — "Opacity" pill opening a per-raster panel: each
 *    exported raster gets a 100/50/25/Off row (plus an "All layers" row
 *    when there are several), for drawing linework over imagery. The
 *    raster layer names are baked in at export via the
 *    LGS-EXPORT-DATA:opacitylayers line (no reliable way to enumerate
 *    rasters from QML on the device). Per-layer values persist as a JSON
 *    object in lgs_opacity; a legacy plain number applies to all layers.
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
 * 5. SPLINE — "∿ Spline" pill arming a spline digitizing mode (port of
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
 *    would smear the final vertex. Spline parameters are baked at export
 *    via LGS-EXPORT-DATA:splineparams (tolerance is in map units — LGS
 *    projects are projected mine grids, same assumption as desktop).
 *
 * 6. NATIVE CONFIRM FIXUP — always on (no export flag): QField's own
 *    line/polygon digitizing also harvests the floating crosshair vertex
 *    on ✓, with the same tap-jiggle smear. On model freeze (spline not
 *    armed) the floating vertex is dropped, so only +-placed vertices
 *    are saved. Skipped for GNSS-driven crosshairs (positionLocked /
 *    averagedPosition — QField strips the vertex itself after averaged
 *    adds) and below 2 committed vertices (3 for polygons), where the
 *    crosshair vertex is what keeps the geometry valid.
 */

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
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
  // Filled with the exported raster layer names by the exporter.
  readonly property var opacityLayers: [] // LGS-EXPORT-DATA:opacitylayers
  // [tightness, tolerance (map units), max segments] from desktop settings.
  readonly property var splineParams: [] // LGS-EXPORT-DATA:splineparams

  property var mainWindow: iface.mainWindow()

  readonly property var layerNames: [
    '1 - FieldNotebook', '2 - Overlay', '3 - Linework', '4 - Basemap']
  readonly property string elevationField: 'Elevation'
  readonly property var tolPresets: [1, 2.5, 5, 10]
  // mirror of z_filter/expression.py::FLAT_SPAN — range features flatter
  // than this vote in the scan, wider spans (ramps) abstain
  readonly property real flatSpan: 2.0

  property var userLevels: []        // persisted (lgs_z_levels) — typed only
  property var suggestions: []       // cluster objects from the last scan
  property var scanInfo: ({})        // {min, max, withElev, blank}
  property real autoTol: 0
  property bool scanned: false
  property bool filterActive: false

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
  readonly property real minTol: 1.0
  readonly property real tolMargin: 0.5
  readonly property real maxTol: 15.0
  readonly property int maxSuggestions: 12

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
    const span = hi - lo
    if (span / 2 + tolMargin > maxTol)
      return binContinuous(pairs)
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
    const tol = Math.min(maxTol, Math.max(minTol, span / 2 + tolMargin))
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
    const threshold = gaps.length
        ? Math.max(gapFloor, gapFactor * medianOf(gaps)) : gapFloor

    let clusters = []
    let current = [pairs[0]]
    for (let i = 1; i < pairs.length; i++) {
      if (pairs[i][0] - pairs[i - 1][0] > threshold) {
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

    // Neighbour clamp: windows must never overlap.
    for (let i = 0; i < result.length; i++) {
      let halfGaps = []
      if (i > 0)
        halfGaps.push((result[i].level - result[i - 1].level) / 2)
      if (i < result.length - 1)
        halfGaps.push((result[i + 1].level - result[i].level) / 2)
      if (halfGaps.length)
        result[i].suggested_tol = Math.max(
            minTol, Math.min(result[i].suggested_tol, Math.min.apply(null, halfGaps)))
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

  // ----------------------------------------------------------------
  // Layers
  // ----------------------------------------------------------------
  function layerByName(name) {
    try {
      const matches = qgisProject.mapLayersByName(name)
      if (matches && matches.length > 0)
        return matches[0]
    } catch (error) {}
    return null
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

  function rebuildLevelModel(current) {
    const levels = mergedLevels()
    levelCombo.model = levels.map(fmt)
    if (current !== undefined) {
      const index = levels.indexOf(Number(current))
      if (index !== -1)
        levelCombo.currentIndex = index
      else
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

  function stepLevel(direction) {
    const levels = mergedLevels()
    if (levels.length === 0)
      return
    const level = currentLevel()
    let target
    if (level === undefined) {
      target = direction > 0 ? levels[0] : levels[levels.length - 1]
    } else {
      let candidates = levels.filter(function (v) {
        return direction > 0 ? v > level : v < level
      })
      if (candidates.length === 0) {
        // Overlay pill taps must never feel dead at the list ends.
        toast(direction > 0 ? qsTr('No higher level') : qsTr('No lower level'))
        return
      }
      target = direction > 0 ? candidates[0] : candidates[candidates.length - 1]
    }
    rebuildLevelModel(target)
    if (filterActive)
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
  // half the gap to the nearest other known level (same rule as
  // clusterLevels) so adjacent windows never overlap.
  function tolForLevel(level, fallbackTol) {
    let tol = Number(fallbackTol)
    for (const cluster of suggestions) {
      if (cluster.level === level) {
        tol = cluster.suggested_tol
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
    return Math.max(minTol, tol)
  }

  // ----------------------------------------------------------------
  // Data scan
  // ----------------------------------------------------------------
  function scanData() {
    let counts = {}
    let withElev = 0
    let blank = 0
    let spanning = 0
    for (const t of allTargets()) {
      const layer = layerByName(t.name)
      if (layer === null)
        continue
      const fields = t.mode === 'range'
          ? [t.fieldMin, t.fieldMax] : [t.field || elevationField]
      let previous
      try {
        previous = layer.subsetString
        layer.subsetString = ''      // scan ALL rows, not the filtered view
        let iterator = LayerUtils.createFeatureIterator(layer)
        while (iterator.hasNext()) {
          const feature = iterator.next()
          let values = []
          for (const field of fields) {
            const raw = feature.attribute(field)
            const number = Number(raw)
            if (raw === undefined || raw === null || String(raw) === '' ||
                isNaN(number)) {
              values = null
              break
            }
            values.push(number)
          }
          if (values === null) {
            blank++
            continue
          }
          // Range features vote their midpoint only when flat; spanning
          // ramps abstain (mirror of controller.scan_elevations).
          if (values.length === 2 &&
              Math.abs(values[1] - values[0]) > flatSpan) {
            spanning++
            continue
          }
          const value = values.length === 2
              ? (values[0] + values[1]) / 2 : values[0]
          counts[value] = (counts[value] || 0) + 1
          withElev++
        }
      } catch (error) {
      } finally {
        try {
          if (previous !== undefined)
            layer.subsetString = previous
        } catch (error) {}
      }
    }
    suggestions = clusterLevels(counts)
    autoTol = suggestions.length ? suggestTolerance(suggestions) : 0
    let info = { withElev: withElev, blank: blank, spanning: spanning }
    const values = Object.keys(counts).map(Number)
    if (values.length) {
      info.min = Math.min.apply(null, values)
      info.max = Math.max.apply(null, values)
    }
    scanInfo = info
    scanned = true
    rebuildLevelModel(currentLevel())
  }

  function summaryText() {
    if (!scanned)
      return qsTr('Not scanned yet.')
    if (scanInfo.min === undefined) {
      return scanInfo.blank
          ? qsTr('No elevation values yet (%1 blank features)').arg(scanInfo.blank)
          : qsTr('No features found')
    }
    let text = (scanInfo.min === scanInfo.max
        ? fmt(scanInfo.min) : fmt(scanInfo.min) + '–' + fmt(scanInfo.max)) + ' m'
    text += '  ·  ' + qsTr('%1 with elevation').arg(scanInfo.withElev)
    if (scanInfo.blank)
      text += '  ·  ' + qsTr('%1 blank').arg(scanInfo.blank)
    if (scanInfo.spanning)
      text += '  ·  ' + qsTr('%1 spanning levels').arg(scanInfo.spanning)
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
    addLevel(level)
    saveVar('lgs_z_enabled', '1')
    saveVar('lgs_z_level', fmt(level))
    saveVar('lgs_z_tolerance', fmt(tolerance))
    saveVar('lgs_z_shownull', showNullSwitch.checked ? '1' : '0')
    saveVar('lgs_z_adjacent', adjacentSwitch.checked ? '1' : '0')
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
    try {
      iface.mapCanvas().refresh()
    } catch (error) {}
    if (restored > 0)
      toast(qsTr('Z filter off'))
  }

  function restoreFromProject() {
    loadLevels()
    toleranceField.text = projVar('lgs_z_tolerance', '5')
    showNullSwitch.checked = projVar('lgs_z_shownull', '1') === '1'
    adjacentSwitch.checked = projVar('lgs_z_adjacent', '0') === '1'
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
        featureSpline)
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
      if (plugin.featureOpacity)
        plugin.restoreOpacityFromProject()
      if (plugin.featureClipping)
        plugin.initClipping()
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
      zDialog.open()
    }
  }

  // ----------------------------------------------------------------
  // Dialog
  // ----------------------------------------------------------------
  Dialog {
    id: zDialog
    parent: mainWindow.contentItem
    modal: true
    title: qsTr('Z Filter — Level Mapping')
    x: (mainWindow.width - width) / 2
    y: (mainWindow.height - height) / 2
    width: Math.min(mainWindow.width - 40, 420)
    standardButtons: Dialog.Close

    onOpened: {
      if (!plugin.scanned)
        plugin.scanData()
    }

    ColumnLayout {
      anchors.fill: parent
      spacing: 12

      Label {
        Layout.fillWidth: true
        text: plugin.summaryText()
        wrapMode: Text.WordWrap
        font.pointSize: 10
        opacity: 0.7
      }

      // Suggested levels — tap to set level + fitted tolerance and filter.
      Flow {
        Layout.fillWidth: true
        spacing: 4
        visible: plugin.suggestions.length > 0

        Repeater {
          model: plugin.topSuggestions(plugin.suggestions, plugin.maxSuggestions)

          delegate: Button {
            required property var modelData
            flat: true
            topPadding: 4
            bottomPadding: 4
            leftPadding: 10
            rightPadding: 10
            text: plugin.fmt(modelData.level) + ' (' + modelData.count + ')'
            background: Rectangle {
              color: 'transparent'
              border.color: Theme.secondaryTextColor
              border.width: 1
              radius: 2
            }
            onClicked: {
              plugin.rebuildLevelModel(modelData.level)
              toleranceField.text = plugin.fmt(modelData.suggested_tol)
              if (plugin.filterActive)
                plugin.applyFilter()
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
          text: '▼'
          onClicked: plugin.stepLevel(-1)
        }

        RoundButton {
          text: '▲'
          onClicked: plugin.stepLevel(+1)
        }
      }

      RowLayout {
        Layout.fillWidth: true
        spacing: 6

        Label {
          text: qsTr('Tolerance ±')
        }

        TextField {
          id: toleranceField
          Layout.preferredWidth: 80
          text: '5'
          validator: DoubleValidator { bottom: 0 }
          inputMethodHints: Qt.ImhFormattedNumbersOnly
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

      RowLayout {
        Layout.fillWidth: true
        spacing: 6

        Button {
          Layout.fillWidth: true
          text: qsTr('Apply filter')
          highlighted: true
          onClicked: plugin.applyFilter()
        }

        Button {
          Layout.fillWidth: true
          text: qsTr('Filter off')
          enabled: plugin.filterActive
          onClicked: plugin.clearFilter()
        }
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
        return
      }
    } catch (error) {}
    try {
      // Fallback: live in the plugins toolbar instead.
      overlayBar.visible = true
      iface.addItemToPluginsToolbar(overlayBar)
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
        color: 'white'
        text: '▼'
      }

      TapHandler {
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
        color: 'white'
        text: '▲'
      }

      TapHandler {
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
        onTapped: scaleDialog.open()
      }
    }

    Rectangle {
      id: imageryPill
      visible: plugin.featureOpacity && plugin.opacitySupported &&
               plugin.resolvedImageryCount > 0
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
        onTapped: opacityDialog.open()
      }
    }

    Rectangle {
      id: clipPill
      visible: plugin.featureClipping && plugin.clipStep === 0 &&
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
        onTapped: plugin.enterClipMode()
      }
    }

    Rectangle {
      id: splinePill
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
        text: qsTr('∿ Spline')
      }

      TapHandler {
        onTapped: plugin.toggleSplineArmed()
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
    title: qsTr('Imagery Opacity')
    x: (mainWindow.width - width) / 2
    y: (mainWindow.height - height) / 2
    width: Math.min(mainWindow.width - 40, 420)
    standardButtons: Dialog.Close

    // [{name}] — one row per resolved, supported raster. Values are read
    // live from imageryOpacities so button highlights follow taps.
    property var rasterNames: []

    onAboutToShow: rasterNames = plugin.resolvedImageryNames()

    ColumnLayout {
      anchors.fill: parent
      spacing: 8

      // One-tap group control, shown only when there is a group.
      RowLayout {
        Layout.fillWidth: true
        visible: opacityDialog.rasterNames.length > 1
        spacing: 4

        Label {
          Layout.fillWidth: true
          elide: Text.ElideRight
          text: qsTr('All layers')
          font.bold: true
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
            onClicked: plugin.applyAllOpacity(modelData)
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
  }

  readonly property var opacitySteps: [1, 0.5, 0.25, 0]
  property var imageryOpacities: ({})    // layer name -> current value
  property var opacityUnsupported: ({})  // layer name -> true (row hidden)
  property bool opacitySupported: true   // false once EVERY layer refuses
  property int resolvedImageryCount: 0
  property string opacityLabel: 'Opacity'

  function resolvedImageryNames() {
    let names = []
    for (const name of opacityLayers) {
      if (layerByName(name) !== null && !opacityUnsupported[name])
        names.push(name)
    }
    return names
  }

  function layerOpacityValue(name) {
    const value = imageryOpacities[name]
    return value === undefined ? 1 : value
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
      if (resolvedImageryCount === 0)
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
    try {
      iface.mapCanvas().refresh()
    } catch (error) {}
    if (!quiet)
      toast(value === 0 ? qsTr('%1 hidden').arg(name)
                        : qsTr('%1 %2%').arg(name).arg(Math.round(value * 100)))
    return true
  }

  function applyAllOpacity(value, quiet) {
    let applied = 0
    for (const name of resolvedImageryNames()) {
      if (applyLayerOpacity(name, value, true))
        applied++
    }
    if (!quiet && applied > 0)
      toast(value === 0 ? qsTr('Imagery hidden')
                        : qsTr('Imagery %1%').arg(Math.round(value * 100)))
  }

  function refreshOpacityLabel() {
    // "Opacity 50" when every raster sits on one value, bare "Opacity"
    // when they differ.
    const names = resolvedImageryNames()
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
    const raw = projVar('lgs_opacity', '')
    if (raw === '') {
      refreshOpacityLabel()
      return
    }
    const legacy = Number(raw)
    if (!isNaN(legacy)) {
      // Pre-per-layer exports stored one shared number.
      if (legacy >= 0 && legacy < 1)
        applyAllOpacity(legacy, true)
      refreshOpacityLabel()
      return
    }
    try {
      const values = JSON.parse(raw)
      for (const name of resolvedImageryNames()) {
        const value = Number(values[name])
        if (!isNaN(value) && value >= 0 && value < 1)
          applyLayerOpacity(name, value, true)
      }
    } catch (error) {}
    refreshOpacityLabel()
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
  readonly property var clipLayerNames: ['2 - Overlay', '4 - Basemap']
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
  }

  // Evaluate a QGIS expression against a layer (+ optional feature).
  // Returns '' on any failure so callers can treat empty as "no result"
  // — never as "empty geometry", which reports as WKT '... EMPTY'.
  function evalExpr(layer, feature, expr) {
    try {
      clipEvaluator.layer = layer
      if (feature !== null && feature !== undefined)
        clipEvaluator.feature = feature
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
    const pt = canvas.mapSettings.screenToCoordinate(
        Qt.point(pos.x, pos.y))
    const tol = clipTapTolerance()
    const probe = "intersects($geometry, buffer(geom_from_wkt('POINT(" +
        pt.x + ' ' + pt.y + ")'), " + tol + '))'
    // The iterator honours the layer subsetString, so an active Z filter
    // means only VISIBLE polygons are tappable — clip what you see.
    const layers = clipLayer !== null ? [clipLayer] : candidateClipLayers()
    for (const layer of layers) {
      let best = null
      let bestArea = -1
      let iterator = null
      try {
        iterator = LayerUtils.createFeatureIteratorFromExpression(
            layer, probe)
        while (iterator.hasNext()) {
          const feature = iterator.next()
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

  function copyClipAttributes(target, source, names, uuidField, freshUuid) {
    // fid/id/ogc_fid stay null so the provider assigns them (GeoPackage
    // UNIQUE PK). Everything else is copied — including Elevation, which
    // deliberately overwrites the auto-stamp default so new pieces keep
    // the source level and stay visible under an active Z filter.
    for (const name of names) {
      const lower = String(name).toLowerCase()
      if (lower === 'fid' || lower === 'id' || lower === 'ogc_fid')
        continue
      try {
        if (uuidField !== null && name === uuidField)
          target.setAttribute(name, freshUuid)
        else
          target.setAttribute(name, source.attribute(name))
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
    // One edit session, adds strictly before deletes (data-safe order).
    let ok = false
    try {
      layer.startEditing()
      for (const feature of newFeatures)
        LayerUtils.addFeature(layer, feature)
      for (const fid of deleteIds) {
        let deleted = false
        try {
          deleted = layer.deleteFeature(fid)
        } catch (error) {}
        if (!deleted) {
          // Fallback: selection-based deletion (both invokable).
          try {
            layer.selectByIds([fid])
            layer.deleteSelectedFeatures()
          } catch (error2) {}
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
        if (touches !== 'true' && touches !== '1') {
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
          copyClipAttributes(created, feature, names, uuidField, freshUuid)
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
          copyClipAttributes(created, feature, names, uuidField, freshUuid)
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
          if (touches !== 'true' && touches !== '1') {
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
                               stampedUuid)
          } else {
            copyClipAttributes(created, item.feature, names, null, '')
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
        copyClipAttributes(created, gone.feature, undo.names, null, '')
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

  property bool splineArmed: false
  property var splineLocator: null    // the coordinateLocator QQuickItem
  property var splineModel: null      // locator.rubberbandModel (active one)
  property bool splinePillVisible: false
  property var splineControls: []     // [{x,y,z}] control points, in order
  property int splineExpected: -1     // model vertexCount we last produced
  property bool splineMutating: false // re-entrancy guard around rebuilds
  property var splineLastCross: null  // crosshair coords used in last rebuild
  property var splineLastSeq: null    // sequence last written to the model
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
  function splineSimplify(points, tolerance) {
    if (!(tolerance > 0) || points.length < 3)
      return points.slice()
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
        out.push(points[i])
    }
    return out
  }

  // mirror of spline_interp.hermite (open polyline). Control points are
  // interpolated exactly and survive simplification verbatim; the sample
  // blocks between them are pruned per segment, same as the desktop
  // cleanup loop. Operation order matches the Python exactly so the
  // parity fixtures agree to float precision.
  function splineHermiteOpen(points, tightness, tolerance, maxSegments) {
    const n = points.length
    if (n < 3)
      return points.slice()

    const tangents = [splineTangent(points[0], points[1], tightness)]
    for (let i = 1; i < n - 1; i++)
      tangents.push(splineTangent(points[i - 1], points[i + 1], tightness))
    tangents.push(splineTangent(points[n - 2], points[n - 1], tightness))

    const result = []
    for (let i = 0; i < n - 1; i++) {
      const p0 = points[i]
      const p1 = points[i + 1]
      result.push(p0)

      const t = 1.0 / maxSegments
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
      const pruned = splineSimplify(block, tolerance)
      for (let j = 1; j < pruned.length - 1; j++)
        result.push(pruned[j])
    }
    result.push(points[n - 1])
    return result
  }

  // mirror of spline_interp.hermite_closed with two shape changes: input
  // is the UNCLOSED unique ring (the rubberband carries no closing
  // duplicate) and the output stays unclosed too. Returns
  // {points, lastControlIndex} so the caller can rotate the ring.
  function splineHermiteClosed(points, tightness, tolerance, maxSegments) {
    const n = points.length
    if (n < 3)
      return { points: points.slice(), lastControlIndex: points.length - 1 }

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

      const t = 1.0 / maxSegments
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
      const pruned = splineSimplify(block, tolerance)
      for (let j = 1; j < pruned.length - 1; j++)
        result.push(pruned[j])
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
  function splineBuildSequence(points, closed, tightness, tolerance, maxSegments) {
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
      return splineHermiteOpen(pts, tightness, tolerance, maxSegments)
    const ring = splineHermiteClosed(pts, tightness, tolerance, maxSegments)
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
  function splineConfirmSequence(controls, closed, tightness, tolerance, maxSegments) {
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
      return splineHermiteOpen(pts, tightness, tolerance, maxSegments)
    return splineHermiteClosed(pts, tightness, tolerance, maxSegments).points
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
    updateSplineMarkers()
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

  // Take the model's committed vertices (all but the floating crosshair
  // vertex) as the control points — used when arming mid-digitize and as
  // the recovery path when the vertex count changes in a way we did not
  // predict.
  function splineAdoptCommitted() {
    splineControls = []
    splineLastSeq = null
    try {
      const verts = splineModel.vertices
      const count = Number(splineModel.vertexCount)
      for (let i = 0; i < count - 1; i++)
        splineControls.push({ x: verts[i].x, y: verts[i].y, z: verts[i].z })
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
      try {
        const verts = splineModel.vertices
        const v = verts[count - 2]
        splineControls.push({ x: v.x, y: v.y, z: v.z })
        splineControls = splineControls.slice()
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

  // Rebuild the model to hold the smoothed curve ending on the crosshair.
  // Mutations go through the invokables only (never assign
  // currentCoordinate — that would break the app's crosshair binding):
  // reset(true) -> addVertexFromPoint for every curve point ->
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
      closed = splineModel.vectorLayer !== null &&
               splineModel.vectorLayer !== undefined &&
               Number(splineModel.geometryType) ===
                   Number(Qgis.GeometryType.Polygon)
    } catch (error) {
      return
    }
    const seq = splineBuildSequence(
        splineControls.concat([cross]), closed,
        splineTightness, splineTolerance, splineMaxSegments)
    if (seq.length < 2)
      return

    // Incremental suffix update: between crosshair-move rebuilds only the
    // last couple of segments change (the crosshair position and the
    // tangent at the last control), so peel and re-add just the changed
    // tail instead of resetting the whole model — far fewer invokable
    // calls, each of which fires QField-side signal handlers. The model
    // currently holds [splineLastSeq[0..n-2] committed, floating = live
    // crosshair] — the floating vertex is never trusted for the diff.
    let prefix = 0
    let modelCount = 0
    try {
      modelCount = Number(splineModel.vertexCount)
    } catch (error) {
      return
    }
    if (splineLastSeq !== null && modelCount === splineLastSeq.length) {
      prefix = splineCommonPrefixLength(splineLastSeq, seq)
      prefix = Math.min(prefix, modelCount - 1, seq.length - 1)
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
    splineMutating = true
    try {
      if (prefix > 0 && incrementalCost < fullCost && pops >= 0) {
        for (let i = 0; i < pops; i++)
          splineModel.removeVertex()
        for (let i = prefix; i < seq.length; i++)
          splineModel.addVertexFromPoint(
              GeometryUtils.point(seq[i].x, seq[i].y, seq[i].z))
        splineModel.removeVertex()
      } else {
        splineModel.reset(true)
        for (let i = 0; i < seq.length; i++)
          splineModel.addVertexFromPoint(
              GeometryUtils.point(seq[i].x, seq[i].y, seq[i].z))
        splineModel.removeVertex()
      }
      splineExpected = Number(splineModel.vertexCount)
      splineLastSeq = seq
      splineLastCross = cross
    } catch (error) {
      splineLastSeq = null
    } finally {
      splineMutating = false
    }
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
      closed = splineModel.vectorLayer !== null &&
               splineModel.vectorLayer !== undefined &&
               Number(splineModel.geometryType) ===
                   Number(Qgis.GeometryType.Polygon)
    } catch (error) {
      return
    }
    const seq = splineConfirmSequence(splineControls, closed,
        splineTightness, splineTolerance, splineMaxSegments)
    if (seq === null || seq.length < 2)
      return
    splineMutating = true
    try {
      splineModel.frozen = false
      try {
        splineModel.reset(true)
        for (let i = 0; i < seq.length; i++)
          splineModel.addVertexFromPoint(
              GeometryUtils.point(seq[i].x, seq[i].y, seq[i].z))
        splineModel.removeVertex()
        splineExpected = Number(splineModel.vertexCount)
        splineLastSeq = null
      } finally {
        splineModel.frozen = true  // relock before confirm() resumes
      }
    } catch (error) {
    } finally {
      splineMutating = false
    }
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
    const out = []
    try {
      for (let i = 0; i < splineControls.length; i++) {
        const p = scaleSettings.coordinateToScreen(GeometryUtils.point(
            splineControls[i].x, splineControls[i].y))
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
}
