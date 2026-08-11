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
  // Filled with the exported raster layer names by the exporter.
  readonly property var opacityLayers: [] // LGS-EXPORT-DATA:opacitylayers

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
    if (featureScale || featureZFilter || featureOpacity)
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
}
