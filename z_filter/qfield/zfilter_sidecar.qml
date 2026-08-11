/*
 * LGS Z Filter — QField project plugin (sidecar).
 *
 * Shipped by the LGS QField exporter as <projectname>.qml next to the
 * exported project file, so QField auto-activates it with the project.
 *
 * Filters the four standard LGS mapping layers to one bench/level
 * elevation by assigning layer.subsetString (a writable Qt property on
 * QgsVectorLayer — the same mechanism as the desktop Z Filter panel).
 * State is shared with desktop through the lgs_z_* project variables.
 *
 * Mirrors z_filter/expression.py — keep the clause shapes in sync.
 */

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.qfield
import org.qgis
import Theme

Item {
  id: plugin

  property var mainWindow: iface.mainWindow()

  readonly property var layerNames: [
    '1 - FieldNotebook', '2 - Overlay', '3 - Linework', '4 - Basemap']
  readonly property string elevationField: 'Elevation'

  property var knownLevels: []       // sorted numbers
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

  function zClause(level, tol, showNull) {
    const lo = Number(level) - Number(tol)
    const hi = Number(level) + Number(tol)
    const core = '"' + elevationField + '" >= ' + fmt(lo) +
                 ' AND "' + elevationField + '" <= ' + fmt(hi)
    if (showNull)
      return '("' + elevationField + '" IS NULL OR (' + core + '))'
    return '(' + core + ')'
  }

  function combineSubset(orig, clause) {
    if (orig && String(orig).trim() !== '')
      return '(' + orig + ') AND ' + clause
    return clause
  }

  // ----------------------------------------------------------------
  // Layers
  // ----------------------------------------------------------------
  function targetLayers() {
    let layers = []
    for (const name of layerNames) {
      try {
        const matches = qgisProject.mapLayersByName(name)
        if (matches && matches.length > 0)
          layers.push({ name: name, layer: matches[0] })
      } catch (error) {}
    }
    return layers
  }

  // ----------------------------------------------------------------
  // Level list
  // ----------------------------------------------------------------
  function loadLevels() {
    let values = {}
    for (const part of projVar('lgs_z_levels', '').split(',')) {
      const number = Number(part)
      if (part.trim() !== '' && !isNaN(number))
        values[number] = true
    }
    setLevels(Object.keys(values).map(Number))
  }

  function setLevels(list) {
    list.sort(function (a, b) { return a - b })
    knownLevels = list
    levelCombo.model = knownLevels.map(fmt)
  }

  function addLevel(value) {
    if (knownLevels.indexOf(value) === -1) {
      let list = knownLevels.slice()
      list.push(value)
      setLevels(list)
      saveVar('lgs_z_levels', knownLevels.map(fmt).join(','))
    }
    levelCombo.currentIndex = knownLevels.indexOf(value)
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
    if (knownLevels.length === 0)
      return
    const level = currentLevel()
    let target
    if (level === undefined) {
      target = direction > 0
          ? knownLevels[0] : knownLevels[knownLevels.length - 1]
    } else {
      let candidates = knownLevels.filter(function (v) {
        return direction > 0 ? v > level : v < level
      })
      if (candidates.length === 0)
        return
      target = direction > 0 ? candidates[0] : candidates[candidates.length - 1]
    }
    levelCombo.currentIndex = knownLevels.indexOf(target)
    if (filterActive)
      applyFilter()
  }

  function harvestLevels() {
    let values = {}
    for (const existing of knownLevels)
      values[existing] = true
    let scanned = 0
    for (const entry of targetLayers()) {
      const layer = entry.layer
      let previous
      try {
        previous = layer.subsetString
        layer.subsetString = ''      // scan ALL rows, not the filtered view
        let iterator = LayerUtils.createFeatureIterator(layer)
        while (iterator.hasNext()) {
          const feature = iterator.next()
          const raw = feature.attribute(elevationField)
          const number = Number(raw)
          if (raw !== undefined && raw !== null && !isNaN(number)) {
            values[number] = true
            scanned++
          }
        }
      } catch (error) {
      } finally {
        try {
          if (previous !== undefined)
            layer.subsetString = previous
        } catch (error) {}
      }
    }
    setLevels(Object.keys(values).map(Number))
    saveVar('lgs_z_levels', knownLevels.map(fmt).join(','))
    toast(qsTr('%1 level(s) known').arg(knownLevels.length))
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
    const clause = zClause(level, tolerance, showNullSwitch.checked)
    let applied = 0

    for (let i = 0; i < layerNames.length; i++) {
      const matches = (function () {
        try { return qgisProject.mapLayersByName(layerNames[i]) }
        catch (error) { return [] }
      })()
      if (!matches || matches.length === 0)
        continue
      const layer = matches[0]
      try {
        // First application: remember the pre-filter subset.
        if (projVar('lgs_z_orig_saved_' + i, '0') !== '1') {
          saveVar('lgs_z_orig_' + i, layer.subsetString || '')
          saveVar('lgs_z_orig_saved_' + i, '1')
        }
        const original = projVar('lgs_z_orig_' + i, '')
        layer.subsetString = combineSubset(original, clause)
        layer.triggerRepaint()
        applied++
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
    try {
      iface.mapCanvas().refresh()
    } catch (error) {}
    toast(qsTr('Level %1 ± %2 m (%3 layers)')
          .arg(fmt(level)).arg(fmt(tolerance)).arg(applied))
  }

  function clearFilter() {
    let restored = 0
    for (let i = 0; i < layerNames.length; i++) {
      const matches = (function () {
        try { return qgisProject.mapLayersByName(layerNames[i]) }
        catch (error) { return [] }
      })()
      if (!matches || matches.length === 0)
        continue
      try {
        if (projVar('lgs_z_orig_saved_' + i, '0') === '1') {
          matches[0].subsetString = projVar('lgs_z_orig_' + i, '')
          matches[0].triggerRepaint()
          saveVar('lgs_z_orig_saved_' + i, '0')
          restored++
        }
      } catch (error) {}
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
    const level = Number(projVar('lgs_z_level', ''))
    if (!isNaN(level) && projVar('lgs_z_level', '') !== '') {
      addLevel(level)
      // Runtime subsets are ephemeral in QField — re-apply the persisted
      // filter when the project (re)opens.
      if (projVar('lgs_z_enabled', '0') === '1')
        applyFilter()
    }
  }

  Component.onCompleted: {
    iface.addItemToPluginsToolbar(pluginButton)
    startupTimer.start()
  }

  Timer {
    id: startupTimer
    interval: 1500
    repeat: false
    onTriggered: plugin.restoreFromProject()
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

    ColumnLayout {
      anchors.fill: parent
      spacing: 12

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

      Button {
        Layout.fillWidth: true
        text: qsTr('Scan data for levels')
        onClicked: plugin.harvestLevels()
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
            ? qsTr('Filter is ON — only the selected level is shown.')
            : qsTr('Filter is off — all data is shown.')
        wrapMode: Text.WordWrap
        font.pointSize: 10
        opacity: 0.7
      }
    }
  }
}
