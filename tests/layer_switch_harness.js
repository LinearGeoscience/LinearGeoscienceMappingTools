// Harness: extract the pure-JS half of the layer switch (v31) from
// lgs_companion.qml verbatim and check it. The pills are drawn from QML
// primitives -- what is testable here is the label each layer resolves
// to, and the per-character opacity ramp that fades a pill off to the
// right.
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

const code = [extractFunction('baseName'),
              extractFunction('layerSwitchCharAlpha')].join('\n');
// Indirect eval: runs non-strict in global scope so the extracted
// declarations become globals.
(0, eval)(code)
const baseName = globalThis.baseName
const alpha = globalThis.layerSwitchCharAlpha

let failures = 0
function check(label, ok, detail) {
  if (ok) { console.log('PASS ' + label) }
  else { failures++; console.log('FAIL ' + label + (detail ? '\n  ' + detail : '')) }
}
function same(label, got, want) {
  check(label, JSON.stringify(got) === JSON.stringify(want),
        'got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want))
}

// --- the label on each pill ------------------------------------------
// The pill shows the ordinal-free name, the same string the toasts use.
const CANONICAL = ['1 - FieldNotebook', '2 - Linework', '3 - Overlay',
                   '4 - Basemap']
same('canonical four give their bare names', CANONICAL.map(baseName),
     ['FieldNotebook', 'Linework', 'Overlay', 'Basemap'])

// A GeoPackage made before the Aug 2026 Linework/Overlay swap keeps the
// old table names; the label must not move with the ordinal.
same('legacy ordinals give the same names',
     ['1 - FieldNotebook', '3 - Linework', '2 - Overlay',
      '4 - Basemap'].map(baseName),
     ['FieldNotebook', 'Linework', 'Overlay', 'Basemap'])

check('baseName strips the ordinal',
      baseName('3 - Overlay') === 'Overlay', baseName('3 - Overlay'))
check('baseName leaves an unprefixed name alone',
      baseName('Overlay') === 'Overlay', baseName('Overlay'))

// --- the fade ramp ----------------------------------------------------
// reveal 0 is the resting state, 0.28 is where the ACTIVE pill rests,
// 1 is just after a tap.
const REVEALS = [0, 0.28, 1]
const COUNTS = []
for (let n = 1; n <= 20; n++) COUNTS.push(n)

// Nothing may ever leave the 0..1 an opacity accepts -- out of range
// either clips to a hard edge or throws away the fade entirely.
let ranged = true, rangeDetail = ''
for (const reveal of REVEALS) {
  for (const n of COUNTS) {
    for (let i = 0; i < n; i++) {
      const a = alpha(i, n, reveal)
      if (!(a >= 0 && a <= 1)) {
        ranged = false
        rangeDetail = 'alpha(' + i + ',' + n + ',' + reveal + ') = ' + a
      }
    }
  }
}
check('every alpha stays within 0..1', ranged, rangeDetail)

// count 1 divides by (count - 1) unless the guard holds.
let finite = true, finiteDetail = ''
for (const reveal of REVEALS) {
  const a = alpha(0, 1, reveal)
  if (!isFinite(a)) { finite = false; finiteDetail = 'reveal ' + reveal + ' -> ' + a }
}
check('a one-character name is finite, not NaN', finite, finiteDetail)

// The fade runs one way only: left is never dimmer than right.
let monoIndex = true, monoIndexDetail = ''
for (const reveal of REVEALS) {
  for (const n of COUNTS) {
    for (let i = 1; i < n; i++) {
      if (alpha(i, n, reveal) > alpha(i - 1, n, reveal) + 1e-12) {
        monoIndex = false
        monoIndexDetail = 'n=' + n + ' reveal=' + reveal + ' at i=' + i
      }
    }
  }
}
check('alpha never rises left to right', monoIndex, monoIndexDetail)

// Revealing must never dim a character that was already showing.
let monoReveal = true, monoRevealDetail = ''
for (const n of COUNTS) {
  for (let i = 0; i < n; i++) {
    for (let r = 0; r < 1; r += 0.05) {
      if (alpha(i, n, r + 0.05) < alpha(i, n, r) - 1e-12) {
        monoReveal = false
        monoRevealDetail = 'n=' + n + ' i=' + i + ' r=' + r
      }
    }
  }
}
check('alpha never falls as reveal rises', monoReveal, monoRevealDetail)

// Fully revealed means fully readable -- the whole point of the tap.
let allSolid = true, solidDetail = ''
for (const n of COUNTS) {
  for (let i = 0; i < n; i++) {
    if (alpha(i, n, 1) !== 1) {
      allSolid = false
      solidDetail = 'n=' + n + ' i=' + i + ' -> ' + alpha(i, n, 1)
    }
  }
}
check('at reveal 1 every character is solid', allSolid, solidDetail)

// At rest the head survives and the tail is gone: findable, but not four
// name plates sitting on the map. This is the ask, pinned.
let restOk = true, restDetail = ''
for (const n of COUNTS) {
  if (n < 2) continue
  if (!(alpha(0, n, 0) > 0)) {
    restOk = false
    restDetail = 'head n=' + n + ' -> ' + alpha(0, n, 0)
  }
  if (alpha(n - 1, n, 0) !== 0) {
    restOk = false
    restDetail = 'tail n=' + n + ' -> ' + alpha(n - 1, n, 0)
  }
}
check('at rest the head shows and the tail is gone', restOk, restDetail)

// The active pill rests part-revealed, so its name is still identifiable
// at a glance while the others are ghosts.
const ACTIVE_N = 'FieldNotebook'.length
check('the active pill rests with a readable head',
      alpha(0, ACTIVE_N, 0.28) === 1 && alpha(3, ACTIVE_N, 0.28) > 0.3,
      'first ' + alpha(0, ACTIVE_N, 0.28) + ' fourth ' + alpha(3, ACTIVE_N, 0.28))
check('the active pill still fades out by its tail',
      alpha(ACTIVE_N - 1, ACTIVE_N, 0.28) === 0,
      String(alpha(ACTIVE_N - 1, ACTIVE_N, 0.28)))

// An idle non-active pill must be fainter than the active one, or the
// highlight says nothing.
check('a resting pill is fainter than the active one',
      alpha(0, ACTIVE_N, 0) < alpha(0, ACTIVE_N, 0.28),
      alpha(0, ACTIVE_N, 0) + ' vs ' + alpha(0, ACTIVE_N, 0.28))

process.exit(failures === 0 ? 0 : 1)
