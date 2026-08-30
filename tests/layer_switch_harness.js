// Harness: extract the pure-JS button-letter derivation of the layer
// switch (v28) from lgs_companion.qml verbatim and check it.
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

const code = ['baseName', 'layerSwitchLetters']
  .map(extractFunction).join('\n');
// Indirect eval: runs non-strict in global scope so the extracted
// function declarations become globals.
(0, eval)(code)
const baseName = globalThis.baseName
const layerSwitchLetters = globalThis.layerSwitchLetters

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
same('canonical four give F L O B',
     layerSwitchLetters(CANONICAL), ['F', 'L', 'O', 'B'])

// --- pre-swap ordinals read the same ---------------------------------
// A GeoPackage made before the Aug 2026 Linework/Overlay swap keeps the
// old table names; the letters must not move with the ordinal.
same('legacy ordinals give the same letters',
     layerSwitchLetters(['1 - FieldNotebook', '3 - Linework', '2 - Overlay',
                         '4 - Basemap']),
     ['F', 'L', 'O', 'B'])

// --- only the layers present in the package --------------------------
same('a package without Overlay drops only its letter',
     layerSwitchLetters(['1 - FieldNotebook', '2 - Linework', '4 - Basemap']),
     ['F', 'L', 'B'])
same('a single layer still gets its initial',
     layerSwitchLetters(['2 - Linework']), ['L'])
same('no layers, no letters', layerSwitchLetters([]), [])

// --- a name with no ordinal prefix -----------------------------------
same('unprefixed names work', layerSwitchLetters(['Linework', 'Overlay']),
     ['L', 'O'])

// --- shared initials widen to the DIVERGING character ----------------
// 'Li' + 'Li' would be two identical buttons; the rule must reach the
// first character at which the names actually differ.
same('Linework and Lithology diverge at n/t',
     layerSwitchLetters(['2 - Linework', '5 - Lithology']), ['Ln', 'Lt'])
same('Linework and Lodes diverge at the second character',
     layerSwitchLetters(['2 - Linework', '9 - Lodes']), ['Li', 'Lo'])
same('a shared initial does not widen the others',
     layerSwitchLetters(['2 - Linework', '5 - Lithology', '3 - Overlay']),
     ['Ln', 'Lt', 'O'])

const widened = layerSwitchLetters(['2 - Linework', '5 - Lithology'])
check('widened letters are distinct', widened[0] !== widened[1],
      JSON.stringify(widened))

// --- lower-case and spaced names -------------------------------------
same('initials are upper-cased, the widening character is not',
     layerSwitchLetters(['1 - notes', '2 - nodes']), ['Nt', 'Nd'])
same('spaces in a base name survive',
     layerSwitchLetters(['2 - Field Notebook']), ['F'])

// --- baseName itself, the shared mirror of lgs_layers.base_name ------
check('baseName strips the ordinal',
      baseName('3 - Overlay') === 'Overlay', baseName('3 - Overlay'))
check('baseName leaves an unprefixed name alone',
      baseName('Overlay') === 'Overlay', baseName('Overlay'))

process.exit(failures === 0 ? 0 : 1)
