// Harness: extract the pure-JS freehand stroke gate of the reshape tool
// (v24) from lgs_companion.qml verbatim and check it, alongside the
// splineDecimate thinning it mirrors.
// Run: node reshape_freehand_harness.js <path-to-qml>
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

const code = ['reshapeStrokeAppend', 'splineDecimate']
  .map(extractFunction).join('\n');
// Indirect eval: runs non-strict in global scope so the extracted
// function declarations become globals.
(0, eval)(code)
const reshapeStrokeAppend = globalThis.reshapeStrokeAppend
const splineDecimate = globalThis.splineDecimate

let failures = 0
function check(label, ok, detail) {
  if (ok) { console.log('PASS ' + label) }
  else { failures++; console.log('FAIL ' + label + (detail ? '\n  ' + detail : '')) }
}

function pt(x, y) { return { x: x, y: y, z: NaN, fh: true } }

// --- basic gate behaviour ---------------------------------------------
{
  const controls = []
  check('first point is always kept',
        reshapeStrokeAppend(controls, pt(0, 0), 5) === true &&
        controls.length === 1)
  check('sub-min-dist point is rejected',
        reshapeStrokeAppend(controls, pt(3, 0), 5) === false &&
        controls.length === 1)
  check('rejection leaves the kept anchor in place',
        controls[0].x === 0 && controls[0].y === 0)
  check('point at exactly min-dist is kept',
        reshapeStrokeAppend(controls, pt(5, 0), 5) === true &&
        controls.length === 2)
  check('distance is euclidean, not per-axis',
        reshapeStrokeAppend(controls, pt(8, 4), 5) === true &&
        controls.length === 3,
        '3-4-5 triangle from (5,0) must clear minDist 5')
  check('diagonal jitter below min-dist is rejected',
        reshapeStrokeAppend(controls, pt(10, 6), 5) === false &&
        controls.length === 3,
        'sqrt(8) < 5 from (8,4)')
}

// --- degenerate minDist -----------------------------------------------
{
  const controls = [pt(0, 0)]
  check('minDist 0 is a passthrough',
        reshapeStrokeAppend(controls, pt(0, 0), 0) === true &&
        controls.length === 2)
  check('negative minDist is a passthrough',
        reshapeStrokeAppend(controls, pt(0, 0), -1) === true &&
        controls.length === 3)
  check('NaN minDist is a passthrough',
        reshapeStrokeAppend(controls, pt(0, 0), NaN) === true &&
        controls.length === 4)
}

// --- the gate measures from the last KEPT point, not the last seen ----
{
  const controls = []
  // A slow drift: every sample 2 units on from the last SEEN point
  // would pass a last-seen gate, but must accumulate against the kept
  // anchor and only land every ceil(5/2) = 3rd sample.
  for (let x = 0; x <= 12; x += 2)
    reshapeStrokeAppend(controls, pt(x, 0), 5)
  check('slow drift accumulates against the kept anchor',
        controls.map(function(p) { return p.x }).join(',') === '0,6,12',
        'got ' + controls.map(function(p) { return p.x }).join(','))
}

// --- live gate agrees with splineDecimate's after-the-fact thinning ---
{
  // splineDecimate always keeps the final point; the live gate cannot
  // know which point is final, so compare on a run whose last sample
  // clears the gate anyway.
  const dense = []
  for (let x = 0; x <= 100; x += 1)
    dense.push({ x: x, y: 0 })
  const live = []
  for (const p of dense)
    reshapeStrokeAppend(live, p, 10)
  const after = splineDecimate(dense, 10)
  check('live gate matches splineDecimate on a clean run',
        JSON.stringify(live) === JSON.stringify(after),
        'live ' + live.length + ' vs decimate ' + after.length)
}

// --- undo-slice arithmetic (mirror of reshapeUndoVertex v24) ----------
{
  // Actions: tap(1), stroke(4), tap(1) -> stack [1,4,1] over 6 points.
  let controls = [pt(0, 0), pt(10, 0), pt(20, 0), pt(30, 0), pt(40, 0),
                  pt(50, 0)]
  let stack = [1, 4, 1]
  function undo() {
    let n = stack.length > 0 ? Number(stack.pop()) : 1
    if (!(n >= 1)) n = 1
    if (n > controls.length) n = controls.length
    controls = controls.slice(0, controls.length - n)
  }
  undo()
  check('undo pops the last tap alone', controls.length === 5)
  undo()
  check('undo pops a whole stroke as one action', controls.length === 1)
  undo()
  check('undo pops the first tap', controls.length === 0)
  undo()
  check('undo on empty stack and controls is safe', controls.length === 0)
}

process.exit(failures === 0 ? 0 : 1)
