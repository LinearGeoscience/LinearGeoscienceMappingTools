// Harness: extract the pure-JS reshape line conditioning pipeline (v32)
// from lgs_companion.qml verbatim and check it. These functions exist
// because GEOS's reshape silently returns NothingHappened on coincident
// vertices, micro self-loops, and mixed 2D/3D sequences.
// Run: node reshape_condition_harness.js <path-to-qml>
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

const code = ['reshapeDedupe', 'reshapeForce2DPolicy',
              'reshapeSegIntersection', 'reshapeRemoveLoops',
              'reshapeExtendEnds', 'reshapeConditionSequence']
  .map(extractFunction).join('\n');
// Indirect eval: runs non-strict in global scope so the extracted
// function declarations become globals.
(0, eval)(code)
const reshapeDedupe = globalThis.reshapeDedupe
const reshapeForce2DPolicy = globalThis.reshapeForce2DPolicy
const reshapeSegIntersection = globalThis.reshapeSegIntersection
const reshapeRemoveLoops = globalThis.reshapeRemoveLoops
const reshapeExtendEnds = globalThis.reshapeExtendEnds
const reshapeConditionSequence = globalThis.reshapeConditionSequence

let failures = 0
function check(label, ok, detail) {
  if (ok) { console.log('PASS ' + label) }
  else { failures++; console.log('FAIL ' + label + (detail ? '\n  ' + detail : '')) }
}

function pt(x, y, z) { return { x: x, y: y, z: z === undefined ? NaN : z } }
function xs(points) { return points.map(function(p) { return p.x + ',' + p.y }).join(' ') }

// --- reshapeDedupe -----------------------------------------------------
{
  const out = reshapeDedupe([pt(0, 0), pt(0, 0), pt(10, 0), pt(10, 0),
                             pt(20, 0)], 0)
  check('eps 0 removes exact coincident duplicates',
        xs(out) === '0,0 10,0 20,0', 'got ' + xs(out))
}
{
  const out = reshapeDedupe([pt(0, 0), pt(0.3, 0), pt(10, 0), pt(10.2, 0.2),
                             pt(20, 0)], 1)
  check('sub-epsilon jitter is dropped',
        xs(out) === '0,0 10,0 20,0', 'got ' + xs(out))
}
{
  const out = reshapeDedupe([pt(0, 0), pt(9.5, 0), pt(10, 0)], 1)
  check('a crowded LAST point survives; the interior point is dropped',
        xs(out) === '0,0 10,0', 'got ' + xs(out))
}
{
  const out = reshapeDedupe([pt(0, 0), pt(0.4, 0)], 1)
  check('two points closer than eps both survive (entry and exit)',
        xs(out) === '0,0 0.4,0', 'got ' + xs(out))
}
{
  const input = [pt(0, 0), pt(10, 0), pt(20, 5)]
  const out = reshapeDedupe(input, 1)
  check('clean input passes through untouched',
        xs(out) === xs(input) && out.length === 3)
  check('dedupe copies, never mutates the input',
        input.length === 3 && out !== input)
}

// --- reshapeForce2DPolicy ----------------------------------------------
{
  const out = reshapeForce2DPolicy([pt(0, 0, 100), pt(10, 0, 105)])
  check('all-finite z is kept verbatim',
        out[0].z === 100 && out[1].z === 105)
}
{
  const out = reshapeForce2DPolicy([pt(0, 0, 100), pt(10, 0), pt(20, 0, 105)])
  check('one non-finite z strips the whole line to 2D',
        Number.isNaN(out[0].z) && Number.isNaN(out[1].z) &&
        Number.isNaN(out[2].z))
  check('2D policy keeps xy untouched',
        xs(out) === '0,0 10,0 20,0')
}

// --- reshapeSegIntersection --------------------------------------------
{
  const hit = reshapeSegIntersection(pt(0, 0), pt(10, 10),
                                     pt(0, 10), pt(10, 0))
  check('proper crossing found at the midpoint',
        hit !== null && hit.x === 5 && hit.y === 5)
}
{
  check('parallel segments do not intersect',
        reshapeSegIntersection(pt(0, 0), pt(10, 0),
                               pt(0, 1), pt(10, 1)) === null)
  check('endpoint touch is not a crossing',
        reshapeSegIntersection(pt(0, 0), pt(10, 0),
                               pt(10, 0), pt(20, 10)) === null)
  check('vertex resting ON a segment is not a crossing',
        reshapeSegIntersection(pt(0, 0), pt(10, 0),
                               pt(5, 0), pt(5, 10)) === null)
}
{
  const hit = reshapeSegIntersection(pt(0, 0, 0), pt(10, 10, 10),
                                     pt(0, 10), pt(10, 0))
  check('z interpolates along the first segment',
        hit !== null && hit.z === 5)
}

// --- reshapeRemoveLoops ------------------------------------------------
{
  // Bowtie: 0,0 -> 10,0 -> 10,10 -> 5,-5; the return segment crosses
  // the base at y=0, u=2/3 along it: x = 10 - 5*(2/3) = 20/3.
  const out = reshapeRemoveLoops([pt(0, 0), pt(10, 0), pt(10, 10),
                                  pt(5, -5)])
  check('bowtie loop is cut at the crossing point',
        out.length === 3 && out[1].y === 0 &&
        Math.abs(out[1].x - 20 / 3) < 1e-9,
        'got ' + xs(out))
}
{
  const input = [pt(0, 0), pt(10, 0), pt(20, 3), pt(30, 0)]
  const out = reshapeRemoveLoops(input)
  check('loop-free input comes back bit-identical',
        JSON.stringify(out) === JSON.stringify(input))
}
{
  // Two independent loops in one line both unwind.
  const out = reshapeRemoveLoops([
    pt(0, 0), pt(10, 0), pt(10, 5), pt(5, -2),   // first loop
    pt(20, -2), pt(20, 6), pt(30, 6),
    pt(30, 10), pt(25, 2)])                       // second loop
  let crossings = 0
  for (let i = 0; i + 3 < out.length; i++)
    for (let j = i + 2; j + 1 < out.length; j++)
      if (reshapeSegIntersection(out[i], out[i + 1], out[j], out[j + 1]))
        crossings++
  check('multiple loops all removed', crossings === 0,
        'still ' + crossings + ' crossing(s): ' + xs(out))
}

// --- reshapeExtendEnds -------------------------------------------------
{
  const out = reshapeExtendEnds([pt(0, 0), pt(10, 0)], true, true, 5)
  check('both ends extend along the end tangents',
        xs(out) === '-5,0 0,0 10,0 15,0', 'got ' + xs(out))
  check('extension appends, the drawn endpoints stay',
        out.length === 4 && out[1].x === 0 && out[2].x === 10)
}
{
  const out = reshapeExtendEnds([pt(0, 0), pt(3, 4)], false, true, 10)
  check('single-ended extension is exact over a 3-4-5 diagonal',
        out.length === 3 && out[2].x === 9 && out[2].y === 12,
        'got ' + xs(out))
}
{
  const input = [pt(0, 0), pt(10, 0)]
  check('dist 0 is a passthrough',
        xs(reshapeExtendEnds(input, true, true, 0)) === xs(input))
  check('no-op flags are a passthrough',
        xs(reshapeExtendEnds(input, false, false, 5)) === xs(input))
}

// --- reshapeConditionSequence ------------------------------------------
{
  // Duplicates + a loop, conditioned in one pass.
  const out = reshapeConditionSequence(
      [pt(0, 0), pt(0, 0), pt(10, 0), pt(10, 10), pt(5, -5)], 0, 0)
  check('pipeline dedupes then cuts loops',
        out.length === 3 && out[1].y === 0 &&
        Math.abs(out[1].x - 20 / 3) < 1e-9,
        'got ' + xs(out))
}
{
  // Above the loop cap the O(n^2) scan is skipped, dedupe still runs.
  const out = reshapeConditionSequence(
      [pt(0, 0), pt(0, 0), pt(10, 0), pt(10, 10), pt(5, -5)], 0, 3)
  check('loop cap skips the scan but keeps the dedupe',
        xs(out) === '0,0 10,0 10,10 5,-5', 'got ' + xs(out))
}
{
  // THE SMOOTHNESS INVARIANT: conditioning a clean drawn curve must not
  // move a single surviving point — it may only remove. A gentle arc
  // with sub-epsilon capture noise: every output point must be one of
  // the input points, coordinates untouched.
  const input = []
  for (let i = 0; i <= 40; i++) {
    const a = i / 40 * Math.PI
    input.push(pt(Math.cos(a) * 100, Math.sin(a) * 50, NaN))
    if (i % 7 === 3)  // capture noise: a near-duplicate every few samples
      input.push(pt(Math.cos(a) * 100 + 0.01, Math.sin(a) * 50, NaN))
  }
  const out = reshapeConditionSequence(input, 0.5, 0)
  let allFromInput = out.length > 30
  for (const q of out) {
    let found = false
    for (const p of input)
      if (p.x === q.x && p.y === q.y) { found = true; break }
    if (!found) { allFromInput = false; break }
  }
  check('conditioning a smooth curve only removes, never moves, points',
        allFromInput, out.length + ' of ' + input.length + ' survive')
}

process.exit(failures === 0 ? 0 : 1)
