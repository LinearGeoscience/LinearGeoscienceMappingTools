"""
Unit tests for z_filter/qfield/__init__.py write_sidecar (pure python).

Run from the plugin root:
    python -m unittest discover tests
"""

import importlib.util
import itertools
import json
import os
import re
import tempfile
import unittest

# Load the module directly — importing the z_filter package would pull in qgis
# (the qfield submodule itself is qgis-free by design).
_path = os.path.join(os.path.dirname(__file__), '..',
                     'z_filter', 'qfield', '__init__.py')
_spec = importlib.util.spec_from_file_location('z_qfield', _path)
z_qfield = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(z_qfield)

write_sidecar = z_qfield.write_sidecar
SIDECAR_SOURCE = z_qfield.SIDECAR_SOURCE


def _flag_values(text):
    """Extract {marker_name: 'true'/'false'} from a sidecar's flag lines."""
    values = {}
    for match in re.finditer(
            r'^\s*readonly property bool \w+: (true|false) '
            r'// LGS-EXPORT-FLAG:(\w+)$', text, re.MULTILINE):
        values[match.group(2)] = match.group(1)
    return values


def _data_values(text):
    """Extract {marker_name: json_text} from a sidecar's data lines."""
    values = {}
    for match in re.finditer(
            r'^\s*readonly property var \w+: (\[.*\]) '
            r'// LGS-EXPORT-DATA:(\w+)$', text, re.MULTILINE):
        values[match.group(2)] = match.group(1)
    return values


class TestWriteSidecar(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _write(self, **kwargs):
        path = write_sidecar(self.tmp.name, "proj", **kwargs)
        with open(path, encoding="utf-8") as fh:
            return path, fh.read()

    def test_source_has_all_markers_true(self):
        with open(SIDECAR_SOURCE, encoding="utf-8") as fh:
            source = fh.read()
        self.assertEqual(_flag_values(source),
                         {'zfilter': 'true', 'scale': 'true',
                          'opacity': 'true', 'clipping': 'true',
                          'spline': 'true', 'reshape': 'true',
                          'reverse': 'true', 'copyattrs': 'true',
                          'merge': 'true', 'recenterhold': 'true',
                          'modetoggle': 'true',
                          'layerswitch': 'true'})
        # Data lines ship empty in source; the exporter fills them.
        self.assertEqual(_data_values(source),
                         {'opacitylayers': '[]',
                          'vectoropacitylayers': '[]',
                          'opacitygroups': '[]',
                          'splineparams': '[]',
                          'build': '[]'})

    def test_all_flag_combinations(self):
        names = ('zfilter', 'scale', 'opacity', 'clipping', 'spline',
                 'reshape', 'reverse', 'copyattrs', 'merge', 'recenterhold',
                 'modetoggle', 'layerswitch')
        for combo in itertools.product((True, False), repeat=len(names)):
            kwargs = dict(zip(names, combo))
            path, text = self._write(**kwargs)
            flags = _flag_values(text)
            for name, enabled in kwargs.items():
                self.assertEqual(flags[name], str(enabled).lower(), kwargs)

    def test_output_path_uses_project_stem(self):
        path, _text = self._write()
        self.assertEqual(os.path.basename(path), "proj.qml")

    def test_only_flag_and_build_lines_differ_from_source(self):
        # opacity_layers/spline_params=None rewrite those data lines to [] —
        # identical to source — so only the twelve flag lines and the build
        # stamp (always filled, that is its whole point) may differ.
        _path, text = self._write(zfilter=False, scale=False, opacity=False,
                                  clipping=False, spline=False,
                                  reshape=False, reverse=False,
                                  copyattrs=False, merge=False,
                                  recenterhold=False, modetoggle=False,
                                  layerswitch=False)
        with open(SIDECAR_SOURCE, encoding="utf-8") as fh:
            source = fh.read()
        diff = [(a, b) for a, b in zip(source.splitlines(), text.splitlines())
                if a != b]
        self.assertEqual(len(diff), 13, diff)
        self.assertTrue(
            all('LGS-EXPORT-FLAG' in a or 'LGS-EXPORT-DATA:build' in a
                for a, _b in diff), diff)

    def test_build_stamp_identifies_the_source(self):
        # The stamp is [date, short hash of the UNMODIFIED source], so two
        # exports with different feature picks report the same build and any
        # edit to lgs_companion.qml reports a different one. Without this
        # there is no way to tell which sidecar a tablet is running.
        _p1, all_on = self._write()
        _p2, all_off = self._write(zfilter=False, scale=False, opacity=False,
                                   clipping=False, spline=False,
                                   reshape=False, reverse=False,
                                   copyattrs=False, merge=False,
                                   recenterhold=False, modetoggle=False,
                                   layerswitch=False)
        stamp_on = json.loads(_data_values(all_on)['build'])
        stamp_off = json.loads(_data_values(all_off)['build'])
        self.assertEqual(stamp_on, stamp_off)
        self.assertEqual(len(stamp_on), 2, stamp_on)
        self.assertRegex(stamp_on[0], r'^\d{4}-\d{2}-\d{2}$')
        self.assertRegex(stamp_on[1], r'^[0-9a-f]{8}$')
        with open(SIDECAR_SOURCE, encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotEqual(
            z_qfield.sidecar_build_stamp(source)[1],
            z_qfield.sidecar_build_stamp(source + '\n')[1])

    def test_opacity_layers_data_line(self):
        names = ['Ortho 2024', 'Say "hi"']
        vectors = ['3 - Overlay', 'Pit "A" walls']
        _path, text = self._write(opacity_layers=names, vector_layers=vectors)
        data = _data_values(text)
        self.assertEqual(data['opacitylayers'], json.dumps(names))
        self.assertEqual(data['vectoropacitylayers'], json.dumps(vectors))
        # Round-trips through JSON despite the embedded quotes.
        self.assertEqual(json.loads(data['opacitylayers']), names)
        self.assertEqual(json.loads(data['vectoropacitylayers']), vectors)

    def test_spline_params_data_line(self):
        _path, text = self._write(spline_params=[0.5, 0.1, 200])
        data = _data_values(text)
        self.assertEqual(data['splineparams'], json.dumps([0.5, 0.1, 200]))
        # Default (None) keeps the empty source form.
        _path, text = self._write()
        self.assertEqual(_data_values(text)['splineparams'], '[]')

    def test_missing_marker_raises(self):
        broken = os.path.join(self.tmp.name, "broken.qml")
        with open(broken, "w", encoding="utf-8") as fh:
            fh.write("Item {}\n")
        original = z_qfield.SIDECAR_SOURCE
        z_qfield.SIDECAR_SOURCE = broken
        try:
            with self.assertRaises(ValueError):
                write_sidecar(self.tmp.name, "proj")
        finally:
            z_qfield.SIDECAR_SOURCE = original

    def test_qml_braces_balanced(self):
        # Cheap parse smoke test on the shipped QML.
        with open(SIDECAR_SOURCE, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text.count('{'), text.count('}'))

    def test_qml_mirrors_extra_layer_support(self):
        # Drift tripwires for the hand-synced JS mirror of expression.py:
        # extra layers arrive via lgs_z_extra and range layers need the
        # range clause. If these disappear, the desktop panel and the
        # device disagree about what gets filtered.
        with open(SIDECAR_SOURCE, encoding="utf-8") as fh:
            text = fh.read()
        for needle in ('lgs_z_extra', 'zRangeClause', 'clauseForTarget',
                       'flatSpan', 'lgs_z_orig_x_',
                       # Adjacent-levels, opacity toggle and level stepping:
                       'lgs_z_adjacent', 'clauseForTargetMulti',
                       'lgs_opacity', 'opacityLayers', 'stepLevel',
                       # Per-layer opacity panel (v6) + vector column:
                       'opacityDialog', 'applyLayerOpacity',
                       'vectorOpacityLayers', 'resolvedVectorNames',
                       'applyOpacityToNames',
                       # Clip Isolated tool (v7):
                       'featureClipping', 'clipPill', 'executeClip',
                       'buildCutterUnionWkt', 'splitMultiPolygonWkt',
                       'undoLastClip', 'detectUuidField',
                       # Clip All + Smart Clip (v9):
                       'clipMode', 'chooseClipMode', 'executeClipAll',
                       'executeClipSmart', 'smartClipPairs',
                       'clipDifferenceWktPair', 'clipAllTargetCount',
                       'finalizeClip',
                       # Spline draw/reshape (v8):
                       'featureSpline', 'splineParams', 'splinePill',
                       'splineBuildSequence', 'splineHermiteOpen',
                       'splineHermiteClosed', 'splineSimplify',
                       'splineRebuildModel', 'addVertexFromPoint',
                       'coordinateLocator', 'lgs_spline_armed',
                       # Confirm excludes the crosshair (freeze fixup),
                       # spline AND native drawing (always-on):
                       'splineConfirmSequence', 'splineOnConfirmFreeze',
                       'nativeConfirmFreeze', 'positionLocked',
                       'averagedPosition',
                       # Freehand perf: node thinning + live sample cap:
                       'splineDecimate', 'splineMinNodePx',
                       'splineLiveMaxSegments',
                       # Elevation-tied rasters (v15):
                       'lgs_z_rasters', 'rasterZTargets', 'applyRasterZ',
                       'setLayerOpacityRaw', 'restoreRasterZ',
                       'rasterInWindows', 'reassertRasterZFor',
                       # Reshape tool (v18):
                       'featureReshape', 'reshapePill', 'enterReshapeMode',
                       'reshapeCatcher', 'reshapeBanner', 'executeReshape',
                       'reshapeFromRubberband', 'collectReshapeTargets',
                       'undoLastReshape', 'reshapeSequence', 'reshapeModel',
                       'findHitInLayers', 'layer_property',
                       # Reshape round 2: browse-mode gating + native
                       # Shape-wrapped rubberband rendering:
                       'currentRubberband', 'reshapeEditingActive',
                       'PathPolyline',
                       # Z level lock + Android glyph fixes:
                       'zStepLocked', 'lgs_z_step_locked',
                       'levelLockPill',
                       # Line direction reverse tool (v19):
                       'featureReverse', 'reversePill', 'enterReverseMode',
                       'reverseCatcher', 'reverseBanner', 'reverseFeature',
                       'candidateReverseLayers', 'reverseLineWkt',
                       'reverseWktCoordGroups', 'handleReverseTap',
                       # Attribute copy tool (v21):
                       'featureCopyAttrs', 'copyPill', 'enterCopyMode',
                       'copyCatcher', 'copyBanner', 'handleCopyTap',
                       'isEmptyValue', 'copyFieldIsSkipped',
                       'copyFieldMapFor', 'buildCopyPairs',
                       'buildCopyPlan', 'applyCopyPlan', 'undoLastCopy',
                       'copyConfirmDialog',
                       # Polygon merge tool (v22):
                       'featureMerge', 'mergePill', 'enterMergeMode',
                       'mergeCatcher', 'mergeBanner', 'handleMergeTap',
                       'buildMergeUnionWkt', 'mergeCarryValues',
                       'requestMerge', 'executeMerge', 'undoLastMerge',
                       'lgs_merged_from',
                       # Freehand recenter hold (v23):
                       'featureRecenterHold', 'holdPill',
                       'initRecenterHold', 'setRecenterHold',
                       'FreehandRecenterScreenFraction',
                       # v24: active-layer copy lock, mode-toggle pill,
                       # stylus freehand reshape:
                       'copyLayerIsLgs', 'featureModeToggle', 'modePill',
                       'initModeToggle', 'toggleMapMode',
                       'toggleDigitizeMode', 'reshapeStrokeAppend',
                       'reshapeStrokeBegin', 'reshapeStrokeEnd',
                       'reshapeUndoStack', 'PointerDevice.Stylus',
                       # v25: scrolling opacity panel, folder rows,
                       # graded transported cover:
                       'opacityScroll', 'opacityGrid', 'opacityGroups',
                       'resolvedGroupEntries', 'groupOpacityCurrent',
                       'setCoverOpacity', 'coverStepCurrent',
                       'lgs_cover_opacity',
                       # v28 layer switch, v31 name pills:
                       'featureLayerSwitch', 'layerSwitchBar',
                       'layerSwitchCharAlpha', 'initLayerSwitch',
                       'setActiveLayerByName', 'writeActiveLayer',
                       'layerSwitchChangeAllowed',
                       'syncLayerSwitchActive', 'layerSwitchAwake',
                       'attachLayerSwitch',
                       # v32 reshape refactor: density regression guard
                       # (reshapeDensity's only call site is the 7th
                       # argument of reshape's splineConfirmSequence
                       # call), line conditioning, retry ladder,
                       # digitisation-style toolbar + persistence:
                       'reshapeDensity', 'reshapeConditionSequence',
                       'reshapeDedupe', 'reshapeForce2DPolicy',
                       'reshapeRemoveLoops', 'reshapeExtendEnds',
                       'reshapeWriteModel', 'reshapeApplyOnce',
                       'reshapeRepairedSequence',
                       'reshapeExtendedSequence',
                       'reshapeEndNeedsExtend', 'reshapeCrsTerm',
                       'reshapeStyle', 'lgs_reshape_style',
                       'lgs_reshape_spline_tap',
                       'lgs_reshape_spline_free',
                       'reshapeSplineArmed', 'toggleReshapeSpline',
                       'setReshapeStyle', 'reshapeLoadStyle',
                       # v33 reshape rework. Reachability (the freehand
                       # handler live in the pick step, on a named
                       # handler so a device log can name it), the
                       # in-place raw stroke buffer and its latched
                       # gate, the prefix-diff writer and its pure plan,
                       # QField's own selection as the target set, the
                       # session undo stack, the bounding-box scans and
                       # the geometry-validity refusal:
                       'reshapeFreehandDrag', 'reshapeLogStroke',
                       'ApprovesCancellation', 'reshapeFeatureForm',
                       'reshapeStrokeRaw', 'reshapeStrokeGate',
                       'reshapeRecenterAfterStroke',
                       'reshapeLastSeq', 'reshapeWritePlan',
                       'reshapeWriteModelReset', 'linePath',
                       'reshapeSelectionPicks', 'latchReshapeSelection',
                       'reshapeLockedSelection', 'focusedFeature',
                       'selectedFeatures', 'onLongPressed',
                       'handleReshapePickToggle', 'reshapeRelockLayer',
                       'reshapeHistory', 'reshapeBusy', 'runReshape',
                       'reshapeClearLine', 'sqlLiteral',
                       'reshapeResultIsValid', 'reshapeFeatureById',
                       'is_valid', 'is_editable',
                       'createFeatureIteratorFromRectangle',
                       'reprojectRectangle', 'reshapeSequenceRect',
                       'tapRectForLayer', 'reshapeCrsPair',
                       # v33 review round: the device decides what a tap
                       # means, the latch expires, the busy frame gets a
                       # real timer, validity is a transition probed by
                       # fid request, targets can be released in one tap:
                       'reshapeTapIsTouch', 'reshapeSelectionLatched',
                       'reshapeSelectionLatchMs', 'reshapeRunTimer',
                       'get_feature_by_id', 'reshapeSplineDefault',
                       'reshapeClearPicksButton', 'wasValid',
                       # Truth-value fix: predicates answer '1', not 'true'.
                       'exprTrue', 'exprFalse',
                       # Spline-armed strokes keep their shape, not the ink.
                       'reshapeStrokeControls', 'reshapeStrokeSmoothPoints',
                       # Only the targets change: QField's topological
                       # reshape differenced stacked neighbours to nothing.
                       'reshapeSuppressTopology', 'topologicalEditing',
                       'avoidIntersectionsMode',
                       # Canvas taps belong to the open tool.
                       'installCanvasHandler', 'removeCanvasHandler',
                       'registerHandler', 'deregisterHandler',
                       'canvasToolActive', 'Component.onDestruction',
                       # v34 banner kit: one language for every tool.
                       'component LgsBanner', 'component LgsPill',
                       'component LgsHeader', 'component LgsStatus',
                       'component LgsActions', 'switchClipMode',
                       'clipSavedMode', 'lgs_clip_mode',
                       'copyRearmSource'):
            self.assertIn(needle, text, needle)

    def test_qml_never_reads_a_predicate_as_the_string_true(self):
        # QGIS geometry predicates (intersects, ...) and comparison
        # operators return TVL ints -- QVariant(1)/QVariant(0) -- so
        # through ExpressionEvaluator.evaluate().toString() a truthy
        # answer is '1', never 'true'. A bare === 'true' on such a result
        # is always false: it silently emptied every box-then-exact-test
        # scan in the field ("The line does not cross any polygon"). Every
        # boolean read goes through exprTrue/exprFalse; the helpers
        # themselves are the only lines allowed to spell the literals.
        with open(SIDECAR_SOURCE, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        offenders = []
        for number, line in enumerate(lines, 1):
            code = line.split('//', 1)[0]
            if re.search(r"[!=]==\s*'(true|false)'", code) and \
                    'return value ===' not in code:
                offenders.append('%d: %s' % (number, line.strip()))
        self.assertEqual(offenders, [], '\n'.join(offenders))


if __name__ == '__main__':
    unittest.main()
