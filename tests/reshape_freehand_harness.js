// Harness: extract the pure-JS freehand stroke gate of the reshape tool
// (v24) from lgs_companion.qml verbatim and check it, alongside the
// splineDecimate thinning it mirrors.
//
// v33 added the capture-neutrality invariant. The stroke now captures
// UNGATED and thins once on release, instead of gating every pointer
// move, so the ink can follow the pen. The two must select the same
// control points or the saved curve changes -- that is what the
// "capture ungated then decimate" block below pins, on jittered strokes
// of 800/1600/3200 moves. If it ever fails, the capture change is not
// geometry-neutral and must be reverted.
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

const code = ['reshapeStrokeAppend', 'splineDecimate',
              'splineCommonPrefixLength', 'reshapeWritePlan',
              'exprTrue', 'exprFalse', 'splinePerpDist',
              'splineSimplifyIndices', 'splineSimplify',
              'reshapeStrokeControls']
  .map(extractFunction).join('\n');
// Indirect eval: runs non-strict in global scope so the extracted
// function declarations become globals.
(0, eval)(code)
const reshapeStrokeAppend = globalThis.reshapeStrokeAppend
const splineDecimate = globalThis.splineDecimate
const splineCommonPrefixLength = globalThis.splineCommonPrefixLength
const reshapeWritePlan = globalThis.reshapeWritePlan
const exprTrue = globalThis.exprTrue
const exprFalse = globalThis.exprFalse
const splineSimplify = globalThis.splineSimplify
const reshapeStrokeControls = globalThis.reshapeStrokeControls

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

// --- capture ungated then decimate == today's live gate (v33) ---------
// The whole justification for capturing raw. A deterministic jittered
// stroke stands in for a hand: no Math.random, so a failure is
// reproducible.
function jitteredStroke(moves) {
  const out = []
  let x = 0, y = 0
  for (let i = 0; i < moves; i++) {
    // Two incommensurate sines: a curving run with fine tremor on top,
    // the shape a stylus actually produces.
    x += 0.9 + 0.6 * Math.sin(i * 0.11)
    y += 1.4 * Math.sin(i * 0.017) + 0.25 * Math.sin(i * 0.9)
    out.push({ x: x, y: y, z: NaN })
  }
  return out
}

for (const moves of [800, 1600, 3200]) {
  const raw = jitteredStroke(moves)
  const gate = 8
  const live = []
  for (const p of raw)
    reshapeStrokeAppend(live, p, gate)
  const decimated = splineDecimate(raw, gate)

  // splineDecimate always keeps the final point; the live gate cannot
  // know which sample is final, so it keeps it only when it clears the
  // gate. Every other choice must agree exactly.
  const tail = raw[raw.length - 1]
  const liveKeptTail = live.length > 0 &&
      live[live.length - 1].x === tail.x && live[live.length - 1].y === tail.y
  const expected = liveKeptTail ? live : live.concat([tail])
  check('capture-neutral at ' + moves + ' moves: decimate == live gate',
        JSON.stringify(decimated) === JSON.stringify(expected),
        'live ' + live.length + ' decimate ' + decimated.length +
        ' liveKeptTail ' + liveKeptTail)

  // And the one deliberate difference: the true end of the stroke always
  // survives. Today's live gate can drop it, which is the "line stops
  // short of exiting the polygon" hazard in miniature.
  const last = decimated[decimated.length - 1]
  check('capture-neutral at ' + moves + ' moves: stroke end survives',
        last.x === tail.x && last.y === tail.y)

  // A prefix relationship, stated separately so a failure says which
  // half broke.
  let prefixOk = live.length <= decimated.length
  for (let i = 0; prefixOk && i < live.length; i++)
    prefixOk = live[i].x === decimated[i].x && live[i].y === decimated[i].y
  check('capture-neutral at ' + moves + ' moves: live is a prefix',
        prefixOk)
}

// --- write-cost simulation: reset-per-tick vs one write (v33) ---------
// Today the 40 ms timer rebuilds the whole model every tick: one reset,
// one addVertexFromPoint per vertex, one removeVertex. The invokable
// count is therefore quadratic in stroke length. Capturing into a plain
// buffer and writing once on release is linear. The signature of that
// fix is that the RATIO grows with the stroke, so assert the growth, not
// a fixed number.
function tickWriteCost(raw, gate, movesPerTick) {
  // Cost of the v32 live path: rebuild from scratch on every tick.
  const live = []
  let cost = 0
  for (let i = 0; i < raw.length; i++) {
    reshapeStrokeAppend(live, raw[i], gate)
    if ((i + 1) % movesPerTick === 0)
      cost += 2 + live.length          // reset + N adds + removeVertex
  }
  return { cost: cost, controls: live.length }
}

const ratios = []
for (const moves of [800, 1600, 3200]) {
  const raw = jitteredStroke(moves)
  const perTick = tickWriteCost(raw, 8, 4)   // ~40 ms at ~100 Hz
  const onceOnRelease = 2 + perTick.controls // the single release write
  ratios.push(perTick.cost / onceOnRelease)
}
check('write cost: per-tick rebuild is >=10x one release write at 800 moves',
      ratios[0] >= 10, 'ratio ' + ratios[0].toFixed(1))
check('write cost: the ratio rises with stroke length (quadratic tell)',
      ratios[1] > ratios[0] && ratios[2] > ratios[1],
      ratios.map(function(r) { return r.toFixed(1) }).join(' -> '))

// --- prefix-diff write plan arithmetic (v33) --------------------------
// What reshapeWriteModel does on a tap: the new sequence shares a long
// prefix with the last one, so peel the changed tail instead of
// resetting. Mirrors splineWriteSequence's cost test.
{
  const a = []
  for (let i = 0; i < 500; i++)
    a.push({ x: i, y: 0, z: NaN })
  const b = a.slice(0, 480)
  for (let i = 0; i < 25; i++)
    b.push({ x: 480 + i, y: 7, z: NaN })
  const prefix = splineCommonPrefixLength(a, b)
  check('prefix diff finds the shared head', prefix === 480,
        'got ' + prefix)
  const modelCount = a.length
  const pops = modelCount - (prefix + 1)
  const incremental = pops + (b.length - prefix) + 1
  const full = b.length + 2
  check('prefix diff is cheaper than a full reset here',
        incremental < full, incremental + ' vs ' + full)
  check('an unrelated sequence falls back to the full reset',
        splineCommonPrefixLength(a, b.slice().reverse()) === 0)
}

// --- reshapeWritePlan (v33) -------------------------------------------
// The real decision function, extracted from the QML rather than
// re-modelled here.
function plan(lastSeq, seq, modelCount) {
  const prefix = lastSeq === null ? 0
      : splineCommonPrefixLength(lastSeq, seq)
  return reshapeWritePlan(lastSeq, seq, modelCount, prefix)
}
function seqOf(n, yTailFrom, y) {
  const out = []
  for (let i = 0; i < n; i++)
    out.push({ x: i, y: (yTailFrom !== undefined && i >= yTailFrom) ? y : 0,
               z: NaN })
  return out
}
{
  const a = seqOf(500)
  // One more point on the end: the classic tap.
  const b = a.concat([{ x: 500, y: 0, z: NaN }])
  const p = plan(a, b, a.length + 1)
  check('write plan: an appended point takes the tail path',
        p.mode === 'tail' && p.prefix === 499 && p.pops === 1,
        JSON.stringify(p))
}
{
  const a = seqOf(500)
  const b = seqOf(500, 480, 7)
  const p = plan(a, b, a.length + 1)
  check('write plan: a changed tail takes the tail path',
        p.mode === 'tail' && p.prefix === 480, JSON.stringify(p))
  check('write plan: the tail path really is cheaper',
        p.pops + (b.length - p.prefix) + 1 < b.length + 2)
}
{
  const a = seqOf(500)
  const b = seqOf(500).reverse()
  check('write plan: an unrelated sequence resets',
        plan(a, b, a.length + 1).mode === 'reset')
}
{
  const b = seqOf(50)
  check('write plan: no record means reset',
        plan(null, b, 0).mode === 'reset')
  check('write plan: an unreadable vertex count means reset',
        plan(seqOf(50), b, NaN).mode === 'reset')
  check('write plan: a SHRUNK model means reset',
        plan(seqOf(50), b, 10).mode === 'reset',
        'modelCount below lastSeq.length cannot be diffed')
}
{
  // A model GROWN behind the diff's back (a live stroke appending
  // straight onto it) must not be trusted into a tail write that pops
  // the wrong number of vertices.
  const a = seqOf(50)
  const b = seqOf(60)
  const p = plan(a, b, 400)
  const survives = p.mode === 'reset' ||
      (p.pops === 400 - (p.prefix + 1) && p.prefix <= a.length - 1)
  check('write plan: a grown model still pops back to the shared prefix',
        survives, JSON.stringify(p))
}

// --- exprTrue / exprFalse (v33 fix) ------------------------------------
// QGIS predicates (intersects, ...) and comparison operators return TVL
// ints, QVariant(1)/QVariant(0), which QField's evaluator stringifies as
// '1'/'0'; only plain functions (is_valid, layer_property) come back as
// 'true'/'false'. Reading a predicate with === 'true' is always false --
// that emptied every box-then-exact-test scan in the field. Verified
// against QGIS 3.40 with the expression engine directly.
{
  check("exprTrue accepts a TVL int '1'", exprTrue('1') === true)
  check("exprTrue accepts a bool 'true'", exprTrue('true') === true)
  check("exprTrue rejects '0', 'false', '', 'NULL' and 'TRUE'",
        !exprTrue('0') && !exprTrue('false') && !exprTrue('') &&
        !exprTrue('NULL') && !exprTrue('TRUE') && !exprTrue(undefined))
  check("exprFalse accepts a TVL int '0' and a bool 'false'",
        exprFalse('0') === true && exprFalse('false') === true)
  check("exprFalse rejects '1', 'true' and '' (unknown is not false)",
        !exprFalse('1') && !exprFalse('true') && !exprFalse(''))
}

// --- reshapeStrokeControls: spline-armed strokes keep their SHAPE ------
// Freehand alone keeps the ink (a control every gate); freehand with the
// spline reads the ink as intent: Douglas-Peucker at the smoothing
// tolerance, then a half-gate floor. The point of the change is that the
// two now differ -- so pin that they do, and pin what the smoothing may
// and may not throw away.
{
  const gate = 8, tol = 3
  let seed = 7
  function jitter() { seed = (seed * 9301 + 49297) % 233280; return (seed / 233280 - 0.5) * 2 }
  // A wobbly "straight" line, 1200 samples, +-1.5 pt of hand tremor.
  const straight = []
  for (let i = 0; i < 1200; i++)
    straight.push({ x: i * 0.5, y: jitter() * 1.5, z: NaN })
  const inkControls = splineDecimate(straight, gate)
  const shapeControls = reshapeStrokeControls(straight, gate, tol)
  check('smoothing: a wobbly straight stroke becomes its two ends',
        shapeControls.length === 2 &&
        shapeControls[0] === straight[0] &&
        shapeControls[1] === straight[straight.length - 1],
        shapeControls.length + ' controls')
  check('smoothing: ink controls stay dense (the styles now differ)',
        inkControls.length > 60, inkControls.length + ' ink controls')

  // A semicircle of radius 200 with the same tremor.
  const arc = []
  for (let i = 0; i <= 1000; i++) {
    const a = Math.PI * i / 1000
    const r = 200 + jitter() * 1.5
    arc.push({ x: r * Math.cos(a), y: r * Math.sin(a), z: NaN })
  }
  const arcInk = splineDecimate(arc, gate)
  const arcShape = reshapeStrokeControls(arc, gate, tol)
  check('smoothing: an arc keeps a handful of controls, not one per gate',
        arcShape.length >= 4 && arcShape.length < arcInk.length / 3,
        arcShape.length + ' vs ' + arcInk.length)
  // Every raw sample sits within tol of the control polyline.
  let worst = 0
  for (const s of arc) {
    let best = Infinity
    for (let i = 1; i < arcShape.length; i++)
      best = Math.min(best, globalThis.splinePerpDist(s, arcShape[i - 1], arcShape[i]))
    worst = Math.max(worst, best)
  }
  check('smoothing: no raw sample strays further than the tolerance',
        worst <= tol + 1e-9, 'worst ' + worst)
  check('smoothing: ends always survive',
        arcShape[0] === arc[0] && arcShape[arcShape.length - 1] === arc[arc.length - 1])

  // An L: a deliberate corner must land where the pen turned.
  const ell = []
  for (let i = 0; i <= 400; i++) ell.push({ x: i * 0.5, y: jitter() * 1.0, z: NaN })
  for (let i = 1; i <= 400; i++) ell.push({ x: 200 + jitter() * 1.0, y: i * 0.5, z: NaN })
  const ellShape = reshapeStrokeControls(ell, gate, tol)
  let nearest = Infinity
  for (const c of ellShape)
    nearest = Math.min(nearest, Math.hypot(c.x - 200, c.y - 0))
  check('smoothing: a drawn corner keeps a control within the tremor of it',
        nearest <= 2, 'nearest control to the corner ' + nearest)
  // And no two controls closer than half the gate.
  let minGap = Infinity
  for (let i = 1; i < ellShape.length; i++)
    minGap = Math.min(minGap, Math.hypot(ellShape[i].x - ellShape[i - 1].x,
                                         ellShape[i].y - ellShape[i - 1].y))
  check('smoothing: the half-gate floor holds between controls',
        minGap >= gate / 2, 'min gap ' + minGap)
  check('smoothing: tolerance 0 degrades to the plain ink controls',
        reshapeStrokeControls(arc, gate, 0).length === splineDecimate(arc, gate / 2).length)
}

process.exit(failures === 0 ? 0 : 1)
