// Harness: extract the transported-cover subset helpers from
// lgs_companion.qml verbatim (JS mirrors of z_filter/expression.py's
// cover_* helpers) and check them, including byte-parity of the clause
// with the Python side (tests/test_cover_subset.py uses the same
// EXPECTED constant).
// Run: node cover_harness.js <path-to-qml>
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

const code = ['combineSubset', 'coverClause', 'stripCoverSubset',
              'applyCoverToSubset']
  .map(extractFunction).join('\n');
// Indirect eval: runs non-strict in global scope so the extracted
// function declarations become globals.
(0, eval)(code)
const coverClause = globalThis.coverClause
const stripCoverSubset = globalThis.stripCoverSubset
const applyCoverToSubset = globalThis.applyCoverToSubset
const combineSubset = globalThis.combineSubset

let failures = 0
function check(label, ok, detail) {
  if (ok) { console.log('PASS ' + label) }
  else { failures++; console.log('FAIL ' + label + (detail ? '\n  ' + detail : '')) }
}

// Byte-parity with z_filter/expression.py::cover_hide_clause.
const EXPECTED =
  '("TypeLith1" IS NULL OR "TypeLith1" <> \'Transported Cover\')'
check('clause byte-parity with python', coverClause() === EXPECTED,
      coverClause())

// --- strip ------------------------------------------------------------
check('strip empty', stripCoverSubset('') === '')
check('strip whole clause', stripCoverSubset(coverClause()) === '')
check('strip combined returns original',
  stripCoverSubset(combineSubset('"Geologist" = \'HW\'', coverClause())) ===
  '"Geologist" = \'HW\'')
check('strip unrecognized unchanged',
  stripCoverSubset('"Elevation" > 5') === '"Elevation" > 5')
check('strip case/whitespace tolerant',
  stripCoverSubset('(  "TypeLith1"  is  null  OR "TypeLith1" <>' +
                   " 'Transported Cover' )") === '')

// --- apply ------------------------------------------------------------
check('hide on empty', applyCoverToSubset('', true) === coverClause())
check('show on empty', applyCoverToSubset('', false) === '')

const base = '"Geologist" = \'HW\''
const hidden = applyCoverToSubset(base, true)
check('round trip', applyCoverToSubset(hidden, false) === base,
      applyCoverToSubset(hidden, false))
check('idempotent', applyCoverToSubset(hidden, true) === hidden,
      applyCoverToSubset(hidden, true))

// --- z interplay: cover stays in the baseline, z clause outermost ------
const zClause = '("Elevation" IS NULL OR ' +
                '("Elevation" >= 1245 AND "Elevation" <= 1255))'
const live = combineSubset(hidden, zClause)
check('z outermost shape',
  live === '(' + hidden + ') AND ' + zClause, live)
const newBaseline = applyCoverToSubset(hidden, false)
check('toggle off under z recombines cleanly',
  combineSubset(newBaseline, zClause) ===
  '(' + base + ') AND ' + zClause)

process.exit(failures === 0 ? 0 : 1)
