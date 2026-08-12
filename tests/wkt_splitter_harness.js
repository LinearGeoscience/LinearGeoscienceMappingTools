// Harness: extract the pure-JS clip functions from lgs_companion.qml
// verbatim — the WKT splitter (exercised against realistic geom_to_wkt
// outputs) and the Smart Clip pairing logic (smartClipPairs).
// Run: node wkt_splitter_harness.js <path-to-qml>
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

const code = ['wktTopLevelGroups', 'wktTopLevelMembers', 'splitMultiPolygonWkt',
              'smartClipPairs']
  .map(extractFunction).join('\n');
// Indirect eval: runs non-strict in global scope so the extracted
// function declarations become globals.
(0, eval)(code)
const splitMultiPolygonWkt = globalThis.splitMultiPolygonWkt
const smartClipPairs = globalThis.smartClipPairs

let failures = 0
function check(label, actual, expected) {
  const a = JSON.stringify(actual), e = JSON.stringify(expected)
  if (a === e) { console.log('PASS ' + label) }
  else { failures++; console.log('FAIL ' + label + '\n  got      ' + a + '\n  expected ' + e) }
}

// Plain polygon (QGIS geom_to_wkt casing)
check('single polygon',
  splitMultiPolygonWkt('Polygon ((0 0, 4 0, 4 4, 0 4, 0 0))'),
  ['Polygon ((0 0, 4 0, 4 4, 0 4, 0 0))'])

// Polygon with a hole — the hole ring must stay inside the one part
check('polygon with hole',
  splitMultiPolygonWkt('Polygon ((0 0, 9 0, 9 9, 0 9, 0 0),(2 2, 3 2, 3 3, 2 3, 2 2))'),
  ['Polygon ((0 0, 9 0, 9 9, 0 9, 0 0),(2 2, 3 2, 3 3, 2 3, 2 2))'])

// MultiPolygon -> two parts
check('multipolygon two parts',
  splitMultiPolygonWkt('MultiPolygon (((0 0, 1 0, 1 1, 0 1, 0 0)),((5 5, 6 5, 6 6, 5 6, 5 5)))'),
  ['POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))', 'POLYGON ((5 5, 6 5, 6 6, 5 6, 5 5))'])

// MultiPolygon where the first part has a hole
check('multipolygon part with hole',
  splitMultiPolygonWkt('MultiPolygon (((0 0, 9 0, 9 9, 0 9, 0 0),(2 2, 3 2, 3 3, 2 3, 2 2)),((20 20, 21 20, 21 21, 20 21, 20 20)))'),
  ['POLYGON ((0 0, 9 0, 9 9, 0 9, 0 0),(2 2, 3 2, 3 3, 2 3, 2 2))',
   'POLYGON ((20 20, 21 20, 21 21, 20 21, 20 20))'])

// GeometryCollection: keep polygonal members, drop line/point debris
check('geometrycollection mixed',
  splitMultiPolygonWkt('GeometryCollection (Polygon ((0 0, 1 0, 1 1, 0 1, 0 0)),LineString (0 0, 1 1),Point (3 3),MultiPolygon (((5 5, 6 5, 6 6, 5 6, 5 5))))'),
  ['Polygon ((0 0, 1 0, 1 1, 0 1, 0 0))', 'POLYGON ((5 5, 6 5, 6 6, 5 6, 5 5))'])

// Empty / degenerate inputs
check('empty string', splitMultiPolygonWkt(''), [])
check('polygon empty', splitMultiPolygonWkt('Polygon EMPTY'), [])
check('geometrycollection empty', splitMultiPolygonWkt('GeometryCollection EMPTY'), [])

// Z-coordinate variant (PolygonZ) still recognised as polygonal
check('polygonz passthrough',
  splitMultiPolygonWkt('PolygonZ ((0 0 100, 1 0 100, 1 1 100, 0 1 100, 0 0 100))'),
  ['PolygonZ ((0 0 100, 1 0 100, 1 1 100, 0 1 100, 0 0 100))'])

// MultiPolygonZ -> parts keep Z, tagged POLYGON (harmless for geom_from_wkt)
check('multipolygonz parts',
  splitMultiPolygonWkt('MultiPolygonZ (((0 0 5, 1 0 5, 1 1 5, 0 0 5)),((2 2 5, 3 2 5, 3 3 5, 2 2 5)))'),
  ['POLYGON ((0 0 5, 1 0 5, 1 1 5, 0 0 5))', 'POLYGON ((2 2 5, 3 2 5, 3 3 5, 2 2 5))'])

// --- smartClipPairs (Smart Clip pairing order + 1% similarity skip) ---

// Three distinct areas: smallest cuts both larger, middle cuts largest.
check('smart pairs three distinct',
  smartClipPairs([{ id: 1, area: 1 }, { id: 2, area: 10 }, { id: 3, area: 100 }]),
  [{ smallId: 1, largeId: 2 }, { smallId: 1, largeId: 3 },
   { smallId: 2, largeId: 3 }])

// Areas within 1% of each other -> pair skipped (small > large * 0.99).
check('smart pairs within one percent skipped',
  smartClipPairs([{ id: 1, area: 99.5 }, { id: 2, area: 100 }]),
  [])

// Exactly at the boundary (small === large * 0.99) -> NOT skipped
// (desktop predicate is strictly greater-than).
check('smart pairs exact boundary kept',
  smartClipPairs([{ id: 1, area: 99 }, { id: 2, area: 100 }]),
  [{ smallId: 1, largeId: 2 }])

// Input order must not matter — pairing follows sorted areas.
check('smart pairs input order irrelevant',
  smartClipPairs([{ id: 3, area: 100 }, { id: 1, area: 1 }, { id: 2, area: 10 }]),
  [{ smallId: 1, largeId: 2 }, { smallId: 1, largeId: 3 },
   { smallId: 2, largeId: 3 }])

// Equal areas -> no pairs at all.
check('smart pairs equal areas',
  smartClipPairs([{ id: 1, area: 50 }, { id: 2, area: 50 }]),
  [])

process.exit(failures === 0 ? 0 : 1)
