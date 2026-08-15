// Harness: extract the pure-JS field-map/skip-list helpers of the Copy
// Attributes tool from lgs_companion.qml verbatim and check them.
// Run: node copy_fieldmap_harness.js <path-to-qml>
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

const code = ['isEmptyValue', 'copyFieldIsSkipped', 'copyFieldMapFor',
              'buildCopyPairs']
  .map(extractFunction).join('\n');
// Indirect eval: runs non-strict in global scope so the extracted
// function declarations become globals.
(0, eval)(code)
const isEmptyValue = globalThis.isEmptyValue
const copyFieldIsSkipped = globalThis.copyFieldIsSkipped
const buildCopyPairs = globalThis.buildCopyPairs

let failures = 0
function check(label, ok, detail) {
  if (ok) { console.log('PASS ' + label) }
  else { failures++; console.log('FAIL ' + label + (detail ? '\n  ' + detail : '')) }
}

function pairString(pairs) {
  return pairs.map(function(p) { return p.from + '>' + p.to }).join(', ')
}

function hasPair(pairs, from, to) {
  return pairs.some(function(p) { return p.from === from && p.to === to })
}

// --- isEmptyValue truth table (mirror of reconcile is_empty) ----------
check('null is empty', isEmptyValue(null) === true)
check('undefined is empty', isEmptyValue(undefined) === true)
check('blank string is empty', isEmptyValue('') === true)
check('whitespace is empty', isEmptyValue('   ') === true)
check("literal 'NULL' is empty", isEmptyValue('NULL') === true)
check("lowercase 'null' is empty", isEmptyValue('null') === true)
check('zero is NOT empty', isEmptyValue(0) === false)
check("string '0' is NOT empty", isEmptyValue('0') === false)
check('false is NOT empty', isEmptyValue(false) === false)
check('text is NOT empty', isEmptyValue('Qz') === false)

// --- skip list ---------------------------------------------------------
for (const name of ['fid', 'FID', 'id', 'ogc_fid', 'UUID', 'feature_uuid',
                    'GlobalGuid', 'Date&Time', 'Geologist', 'Photo',
                    'PhotoID', 'SampleID', 'Label', 'Legend',
                    'SymbolSuffix', 'Easting', 'Northing', 'Elevation',
                    'MappedEasting', 'MappedScale', 'lgs_version',
                    'lgs_merged_from', 'data_added_timestamp']) {
  check('skips ' + name, copyFieldIsSkipped(name) === true)
}
for (const name of ['Lithology1', 'Lith1Mineral1', 'Lith1Mineral1Pct',
                    'Comments', 'Confidence', 'Type', 'Weight',
                    'Mineral', 'Texture', 'Vein %', 'Width_cm']) {
  check('keeps ' + name, copyFieldIsSkipped(name) === false)
}

// --- same-layer copy: identity pairs minus the skip list ---------------
const basemapNames = ['fid', 'TypeLith1', 'Lithology1', 'Lith1Mineral1',
                      'Lith1Mineral1Pct', 'Comments', 'Confidence', 'UUID',
                      'Geologist', 'Elevation', 'Date&Time',
                      'MappedScale', 'Label']
const same = buildCopyPairs(basemapNames, basemapNames,
                            '4 - Basemap', '4 - Basemap')
check('same-layer keeps content fields',
  hasPair(same, 'TypeLith1', 'TypeLith1') &&
  hasPair(same, 'Lithology1', 'Lithology1') &&
  hasPair(same, 'Lith1Mineral1', 'Lith1Mineral1') &&
  hasPair(same, 'Lith1Mineral1Pct', 'Lith1Mineral1Pct') &&
  hasPair(same, 'Comments', 'Comments') &&
  hasPair(same, 'Confidence', 'Confidence'),
  pairString(same))
check('same-layer drops identity/housekeeping',
  !hasPair(same, 'fid', 'fid') && !hasPair(same, 'UUID', 'UUID') &&
  !hasPair(same, 'Geologist', 'Geologist') &&
  !hasPair(same, 'Elevation', 'Elevation') &&
  !hasPair(same, 'Date&Time', 'Date&Time') &&
  !hasPair(same, 'MappedScale', 'MappedScale') &&
  !hasPair(same, 'Label', 'Label'),
  pairString(same))
// TypeLith1 travelling with Lithology1 is what keeps the ValueRelation
// filter consistent on same-layer Basemap copies.
check('same-layer TypeLith1 travels with Lithology1',
  hasPair(same, 'TypeLith1', 'TypeLith1'), pairString(same))

// --- Basemap -> FieldNotebook: the explicit pair map --------------------
const bmSrc = ['fid', 'TypeLith1', 'Lithology1', 'Lithology2',
               'Lith1Mineral1', 'Lith1Mineral2', 'Lith1Mineral3',
               'Lith1Mineral1Pct', 'Lith1Mineral2Pct', 'Lith1Mineral3Pct',
               'Lith1Texture1', 'Lith1Texture2', 'Comments', 'Confidence',
               'UUID', 'Geologist', 'Elevation']
const fnDst = ['fid', 'Lithology', 'Lithology2', 'Mineral', 'Mineral2',
               'Mineral3', 'MineralPct', 'Mineral2Pct', 'Mineral3Pct',
               'Texture', 'Texture2', 'Texture3', 'Comments', 'Confidence',
               'UUID', 'Geologist', 'Elevation', 'Vein %']
const bmFn = buildCopyPairs(bmSrc, fnDst, '4 - Basemap', '1 - FieldNotebook')
check('Basemap->FieldNotebook maps lithology/minerals/pcts/textures',
  hasPair(bmFn, 'Lithology1', 'Lithology') &&
  hasPair(bmFn, 'Lithology2', 'Lithology2') &&
  hasPair(bmFn, 'Lith1Mineral1', 'Mineral') &&
  hasPair(bmFn, 'Lith1Mineral2', 'Mineral2') &&
  hasPair(bmFn, 'Lith1Mineral3', 'Mineral3') &&
  hasPair(bmFn, 'Lith1Mineral1Pct', 'MineralPct') &&
  hasPair(bmFn, 'Lith1Mineral2Pct', 'Mineral2Pct') &&
  hasPair(bmFn, 'Lith1Mineral3Pct', 'Mineral3Pct') &&
  hasPair(bmFn, 'Lith1Texture1', 'Texture') &&
  hasPair(bmFn, 'Lith1Texture2', 'Texture2'),
  pairString(bmFn))
check('Basemap->FieldNotebook adds the shared whitelist',
  hasPair(bmFn, 'Comments', 'Comments') &&
  hasPair(bmFn, 'Confidence', 'Confidence'),
  pairString(bmFn))
check('Basemap->FieldNotebook never carries identity fields',
  !bmFn.some(function(p) { return p.to === 'UUID' || p.to === 'Geologist' ||
                                  p.to === 'Elevation' || p.to === 'fid' }),
  pairString(bmFn))

// --- Pct pairs drop out cleanly on a pre-injector schema ----------------
const fnOld = fnDst.filter(function(n) { return n.indexOf('Pct') === -1 })
const bmFnOld = buildCopyPairs(bmSrc, fnOld,
                               '4 - Basemap', '1 - FieldNotebook')
check('missing target fields drop their pairs',
  !bmFnOld.some(function(p) { return p.to.indexOf('Pct') !== -1 }) &&
  hasPair(bmFnOld, 'Lith1Mineral1', 'Mineral'),
  pairString(bmFnOld))

// --- FieldNotebook -> Basemap: no Lithology pair -------------------------
const fnBm = buildCopyPairs(fnDst, bmSrc, '1 - FieldNotebook', '4 - Basemap')
check('FieldNotebook->Basemap maps minerals back',
  hasPair(fnBm, 'Mineral', 'Lith1Mineral1') &&
  hasPair(fnBm, 'MineralPct', 'Lith1Mineral1Pct') &&
  hasPair(fnBm, 'Texture', 'Lith1Texture1'),
  pairString(fnBm))
check('FieldNotebook->Basemap has NO Lithology pair (TypeLith filter)',
  !fnBm.some(function(p) { return p.from === 'Lithology' }),
  pairString(fnBm))

// --- unmapped cross-layer pair falls back to the whitelist --------------
const ovNames = ['fid', 'Type', 'SubType1', 'Mineral1', 'Percent',
                 'Weight', 'Comments', 'Confidence', 'UUID']
const ovFn = buildCopyPairs(ovNames, fnDst, '2 - Overlay',
                            '1 - FieldNotebook')
check('unmapped pair -> whitelist only',
  ovFn.length === 2 && hasPair(ovFn, 'Comments', 'Comments') &&
  hasPair(ovFn, 'Confidence', 'Confidence'),
  pairString(ovFn))

// --- Overlay <-> Linework vein map ---------------------------------------
const lwNames = ['fid', 'Type', 'Category', 'Mineral1', 'Mineral2',
                 'Percent', 'Weight', 'Comments', 'Confidence', 'UUID']
const ovLw = buildCopyPairs(ovNames, lwNames, '2 - Overlay', '3 - Linework')
check('Overlay->Linework maps mineral/percent/weight',
  hasPair(ovLw, 'Mineral1', 'Mineral1') &&
  hasPair(ovLw, 'Percent', 'Percent') &&
  hasPair(ovLw, 'Weight', 'Weight') &&
  hasPair(ovLw, 'Comments', 'Comments'),
  pairString(ovLw))

// --- empty inputs -> no pairs --------------------------------------------
check('no shared fields -> empty plan',
  buildCopyPairs(['A'], ['B'], 'X', 'Y').length === 0)

process.exit(failures === 0 ? 0 : 1)
