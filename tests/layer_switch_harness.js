// Harness: extract the pure-JS glyph lookup of the layer switch (v29)
// from lgs_companion.qml verbatim and check it. The marks themselves are
// drawn from QML Rectangles -- what is testable here is which KIND of
// mark each layer resolves to.
// Run: node layer_switch_harness.js <path-to-qml>
'use strict'
const fs = require('fs')

const qmlPath = process.argv[2]
const qml = fs.readFileSync(qmlPath, 'utf8')

function extractFunction(name) {
  const start = qml.indexOf('function ' + name + '(')
  if (start === -1) throw new Error('function not found: ' + name)
  let depth = 0, i = qml.indexOf('{', start)
  const bodyStart = i
  for (; i < qml.length; i++) {
    if (qml[i] === '{') depth++
    else if (qml[i] === '}') { depth--; if (depth === 0) break }
  }
  return 'function ' + name + qml.slice(qml.indexOf('(', start), bodyStart) +
         qml.slice(bodyStart, i + 1)
}

// The glyph table is a property, not a function -- lift it out of the QML
// the same verbatim way, so a rename or a retyped kind fails this test.
function extractGlyphTable() {
  const start = qml.indexOf('readonly property var layerSwitchGlyphs: ({')
  if (start === -1) throw new Error('layerSwitchGlyphs not found')
  const open = qml.indexOf('{', start)
  const close = qml.indexOf('})', open)
  if (close === -1) throw new Error('layerSwitchGlyphs not closed')
  return 'var layerSwitchGlyphs = ' + qml.slice(open, close + 1)
}

const code = [extractGlyphTable(),
              extractFunction('baseName'),
              extractFunction('layerSwitchGlyphForBase')].join('\n');
// Indirect eval: runs non-strict in global scope so the extracted
// declarations become globals.
(0, eval)(code)
const baseName = globalThis.baseName
const layerSwitchGlyphForBase = globalThis.layerSwitchGlyphForBase

// What the QML delegate does with a name, minus the geometry fallback
// (which needs a live layer and so cannot run here).
function glyphFor(name) {
  return layerSwitchGlyphForBase(baseName(name))
}

let failures = 0
function check(label, ok, detail) {
  if (ok) { console.log('PASS ' + label) }
  else { failures++; console.log('FAIL ' + label + (detail ? '\n  ' + detail : '')) }
}
function same(label, got, want) {
  check(label, JSON.stringify(got) === JSON.stringify(want),
        'got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want))
}

// --- the canonical four ----------------------------------------------
const CANONICAL = ['1 - FieldNotebook', '2 - Linework', '3 - Overlay',
                   '4 - Basemap']
same('canonical four give point/line/wash/fill',
     CANONICAL.map(glyphFor), ['point', 'line', 'wash', 'fill'])

// --- pre-swap ordinals read the same ---------------------------------
// A GeoPackage made before the Aug 2026 Linework/Overlay swap keeps the
// old table names; the marks must not move with the ordinal.
same('legacy ordinals give the same marks',
     ['1 - FieldNotebook', '3 - Linework', '2 - Overlay',
      '4 - Basemap'].map(glyphFor),
     ['point', 'line', 'wash', 'fill'])

// --- the two polygon layers must NOT collide -------------------------
// Both are polygons, so geometry alone cannot separate them; the whole
// point of the table is that they read differently.
check('Overlay and Basemap get different marks',
      glyphFor('3 - Overlay') !== glyphFor('4 - Basemap'),
      glyphFor('3 - Overlay') + ' vs ' + glyphFor('4 - Basemap'))

// --- only the layers present in the package --------------------------
same('a package without Overlay keeps the rest',
     ['1 - FieldNotebook', '2 - Linework', '4 - Basemap'].map(glyphFor),
     ['point', 'line', 'fill'])
same('a single layer still gets its mark',
     ['2 - Linework'].map(glyphFor), ['line'])

// --- a name with no ordinal prefix -----------------------------------
same('unprefixed names work', ['Linework', 'Overlay'].map(glyphFor),
     ['line', 'wash'])

// --- an unknown layer abstains, so the caller asks the geometry -------
check('an unknown base returns empty, not a guess',
      glyphFor('7 - Geochemistry') === '', glyphFor('7 - Geochemistry'))
check('a near-miss name does not fuzzy-match',
      glyphFor('2 - Linework Draft') === '', glyphFor('2 - Linework Draft'))

// --- every kind the table emits must be one the delegate can draw ----
// The delegate gates four inline marks on these exact strings; a kind it
// does not know would render an empty button.
const DRAWN = ['point', 'line', 'wash', 'fill']
for (const base in globalThis.layerSwitchGlyphs) {
  const kind = globalThis.layerSwitchGlyphs[base]
  check('the delegate can draw ' + base + ' -> ' + kind,
        DRAWN.indexOf(kind) !== -1, kind)
}

// --- baseName itself, the shared mirror of lgs_layers.base_name ------
check('baseName strips the ordinal',
      baseName('3 - Overlay') === 'Overlay', baseName('3 - Overlay'))
check('baseName leaves an unprefixed name alone',
      baseName('Overlay') === 'Overlay', baseName('Overlay'))

process.exit(failures === 0 ? 0 : 1)
