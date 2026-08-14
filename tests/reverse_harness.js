// Harness: extract the pure-JS WKT line reversal from lgs_companion.qml
// verbatim (the fallback path of the Reverse tool) and check it.
// Run: node reverse_harness.js <path-to-qml>
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

const code = ['reverseWktCoordGroups', 'reverseLineWkt']
  .map(extractFunction).join('\n');
// Indirect eval: runs non-strict in global scope so the extracted
// function declarations become globals.
(0, eval)(code)
const reverseLineWkt = globalThis.reverseLineWkt

let failures = 0
function check(label, ok, detail) {
  if (ok) { console.log('PASS ' + label) }
  else { failures++; console.log('FAIL ' + label + (detail ? '\n  ' + detail : '')) }
}

// --- plain linestring ------------------------------------------------
check('linestring reversed',
  reverseLineWkt('LINESTRING (0 0, 1 1, 2 2)') ===
  'LINESTRING (2 2, 1 1, 0 0)',
  reverseLineWkt('LINESTRING (0 0, 1 1, 2 2)'))

// --- z rides along with its vertex -----------------------------------
check('linestring z preserved per vertex',
  reverseLineWkt('LineStringZ (10 20 100, 11 21 110, 12 22 120)') ===
  'LineStringZ (12 22 120, 11 21 110, 10 20 100)',
  reverseLineWkt('LineStringZ (10 20 100, 11 21 110, 12 22 120)'))

// --- multi-part: each part reversed, part order kept -----------------
check('multilinestring parts reversed in place',
  reverseLineWkt('MULTILINESTRING ((0 0, 1 0, 2 0),(5 5, 6 6))') ===
  'MULTILINESTRING ((2 0, 1 0, 0 0),(6 6, 5 5))',
  reverseLineWkt('MULTILINESTRING ((0 0, 1 0, 2 0),(5 5, 6 6))'))

// --- reversal is its own inverse -------------------------------------
const once = reverseLineWkt('LINESTRING (3.5 -1.25, 400000.1 6500000.9, 7 8)')
check('reversing twice restores the original',
  reverseLineWkt(once) === 'LINESTRING (3.5 -1.25, 400000.1 6500000.9, 7 8)',
  reverseLineWkt(once))

// --- non-line geometries are refused ---------------------------------
check('polygon refused', reverseLineWkt('POLYGON ((0 0, 1 0, 1 1, 0 0))') === '')
check('point refused', reverseLineWkt('POINT (1 2)') === '')
check('empty refused', reverseLineWkt('') === '')

process.exit(failures === 0 ? 0 : 1)
