// Harness: extract the pure-JS carry_attrs port of the Merge tool from
// lgs_companion.qml verbatim and check it (keeper-empty fields filled
// from the other parents, first non-empty in pick order wins).
// Run: node merge_carry_harness.js <path-to-qml>
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

const code = ['isEmptyValue', 'copyFieldIsSkipped', 'mergeCarryValues']
  .map(extractFunction).join('\n');
// Indirect eval: runs non-strict in global scope so the extracted
// function declarations become globals.
(0, eval)(code)
const mergeCarryValues = globalThis.mergeCarryValues

let failures = 0
function check(label, ok, detail) {
  if (ok) { console.log('PASS ' + label) }
  else { failures++; console.log('FAIL ' + label + (detail ? '\n  ' + detail : '')) }
}

const names = ['fid', 'UUID', 'Lithology1', 'Comments', 'Confidence',
               'Lith1Mineral1', 'Lith1Mineral1Pct', 'Geologist',
               'lgs_merged_from', 'Elevation']

// --- keeper values are never overwritten -------------------------------
let fills = mergeCarryValues(
  { Lithology1: 'BAS', Comments: 'keeper note' },
  [{ Lithology1: 'AND', Comments: 'parent note' }],
  names)
check('keeper non-empty never overwritten',
  fills.Lithology1 === undefined && fills.Comments === undefined,
  JSON.stringify(fills))

// --- empty keeper fields fill from the first non-empty parent ----------
fills = mergeCarryValues(
  { Lithology1: '', Comments: null, Lith1Mineral1: 'NULL' },
  [{ Lithology1: '', Comments: 'from parent 1', Lith1Mineral1: '' },
   { Lithology1: 'AND', Comments: 'from parent 2', Lith1Mineral1: 'Qz' }],
  names)
check('first non-empty parent wins in pick order',
  fills.Comments === 'from parent 1' && fills.Lithology1 === 'AND' &&
  fills.Lith1Mineral1 === 'Qz',
  JSON.stringify(fills))

// --- zero is a real value, carried and kept ------------------------------
fills = mergeCarryValues(
  { Lith1Mineral1Pct: null },
  [{ Lith1Mineral1Pct: 0 }, { Lith1Mineral1Pct: 40 }],
  names)
check('zero percent carries (0 is not empty)',
  fills.Lith1Mineral1Pct === 0, JSON.stringify(fills))
fills = mergeCarryValues(
  { Lith1Mineral1Pct: 0 },
  [{ Lith1Mineral1Pct: 40 }],
  names)
check('keeper zero is kept (not overwritten)',
  fills.Lith1Mineral1Pct === undefined, JSON.stringify(fills))

// --- skip-listed names are never carried ---------------------------------
fills = mergeCarryValues(
  {},
  [{ fid: 99, UUID: 'parent-uuid', Geologist: 'HW',
     lgs_merged_from: 'x,y', Elevation: 1234, Comments: 'note' }],
  names)
check('identity/housekeeping never carried',
  fills.fid === undefined && fills.UUID === undefined &&
  fills.Geologist === undefined && fills.lgs_merged_from === undefined &&
  fills.Elevation === undefined && fills.Comments === 'note',
  JSON.stringify(fills))

// --- all-empty stays empty ------------------------------------------------
fills = mergeCarryValues(
  { Comments: '' },
  [{ Comments: null }, { Comments: 'NULL' }],
  names)
check('all-empty stays empty', fills.Comments === undefined,
  JSON.stringify(fills))

// --- no parents -> no fills -----------------------------------------------
fills = mergeCarryValues({ Comments: '' }, [], names)
check('no parents -> no fills', Object.keys(fills).length === 0,
  JSON.stringify(fills))

process.exit(failures === 0 ? 0 : 1)
