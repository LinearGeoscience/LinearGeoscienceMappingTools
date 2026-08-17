#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Guards on the canonical mapping-layer names and their mirrors.

Linework and Overlay swapped ordinals in Aug 2026 ("2 - Linework", "3 - Overlay")
so lines draw above Overlay's washes. Two things that swap depends on had no
test before and were enforced only by comments:

  1. The QField sidecar re-declares the layer list in JS and derives each
     layer's lgs_z_orig_<i> project-variable key from its INDEX in that list.
     If it drifts from CANONICAL_LAYERS, stored baselines silently re-point.
  2. Layer matching has to stay ordinal-insensitive, because GeoPackages
     written before the swap keep the old numbering and there is no migration.

Neither failure mode is loud at runtime, hence these assertions.
"""
import os
import re
import sys
import unittest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import lgs_layers  # noqa: E402

SIDECAR = os.path.join(REPO_ROOT, "z_filter", "qfield", "lgs_companion.qml")

LEGACY = {
    "2 - Linework": "3 - Linework",
    "3 - Overlay": "2 - Overlay",
}


def _sidecar_layer_names():
    """The sidecar's `layerNames` array, in declaration order."""
    text = open(SIDECAR, encoding="utf-8").read()
    match = re.search(
        r"readonly\s+property\s+var\s+layerNames\s*:\s*\[(.*?)\]", text, re.S)
    assert match, "layerNames array not found in lgs_companion.qml"
    return re.findall(r"'([^']+)'", match.group(1))


class TestCanonicalNames(unittest.TestCase):

    def test_canonical_order_is_the_numbering(self):
        # The "N - " prefix IS the draw order, so the list must sort by it.
        self.assertEqual(lgs_layers.CANONICAL_LAYERS,
                         sorted(lgs_layers.CANONICAL_LAYERS))
        self.assertEqual(lgs_layers.CANONICAL_LAYERS,
                         ["1 - FieldNotebook", "2 - Linework",
                          "3 - Overlay", "4 - Basemap"])

    def test_sidecar_mirrors_canonical_layers_exactly(self):
        # Same names AND same order: allTargets() keys on the index.
        self.assertEqual(_sidecar_layer_names(), lgs_layers.CANONICAL_LAYERS)

    def test_basemap_is_still_index_three(self):
        # coverZOrigKey is the literal 'lgs_z_orig_3' in the sidecar.
        self.assertEqual(lgs_layers.CANONICAL_LAYERS.index(lgs_layers.BASEMAP), 3)
        text = open(SIDECAR, encoding="utf-8").read()
        self.assertIn("coverZOrigKey: 'lgs_z_orig_3'", text)


class TestOrdinalTolerance(unittest.TestCase):

    def test_base_name_strips_any_ordinal(self):
        for current, legacy in LEGACY.items():
            self.assertEqual(lgs_layers.base_name(current),
                             lgs_layers.base_name(legacy))

    def test_legacy_names_match_their_current_layer(self):
        for current, legacy in LEGACY.items():
            self.assertTrue(lgs_layers.same_layer(current, legacy),
                            f"{legacy!r} should resolve to {current!r}")
            self.assertTrue(lgs_layers.is_canonical(legacy))

    def test_distinct_layers_never_collide(self):
        # The whole point of the swap is that "2" means different things
        # before and after; matching must key on identity, not the number.
        self.assertFalse(lgs_layers.same_layer("2 - Linework", "2 - Overlay"))
        self.assertFalse(lgs_layers.same_layer("3 - Overlay", "3 - Linework"))

    def test_lookup_accepts_legacy_keys(self):
        config = {name: name for name in lgs_layers.CANONICAL_LAYERS}
        for current, legacy in LEGACY.items():
            self.assertEqual(lgs_layers.lookup(config, legacy), current)

    def test_non_canonical_layers_are_left_alone(self):
        for name in ("Level 100", 'Pit "A" walls', "Roads", "DEM"):
            self.assertEqual(lgs_layers.base_name(name), name)
            self.assertFalse(lgs_layers.is_canonical(name))

    def test_unnumbered_user_layers_are_not_ours(self):
        """A bare "Basemap"/"Overlay" belongs to the user, not the template.

        is_canonical decides what the z filter excludes from its extra-layer
        list and what run_add_elevation_field injects a field into, so treating
        an unnumbered lookalike as canonical would silently hide or mutate the
        user's own layer. Tolerance is for "same layer, different number".
        """
        for name in ("Basemap", "Overlay", "Linework", "FieldNotebook",
                     "basemap", "Google Basemap"):
            self.assertFalse(lgs_layers.is_canonical(name),
                             f"{name!r} is a user layer, not a mapping layer")
            self.assertFalse(lgs_layers.has_ordinal(name))

    def test_any_ordinal_spelling_is_recognised(self):
        for name in ("1 - FieldNotebook", "2 - Linework", "3 - Overlay",
                     "4 - Basemap", "2 - Overlay", "3 - Linework",
                     "1_Basemap", "2 Overlay"):
            self.assertTrue(lgs_layers.is_canonical(name), name)

    def test_sidecar_declares_the_legacy_aliases(self):
        # QML cannot enumerate project layers, so it carries an explicit map.
        text = open(SIDECAR, encoding="utf-8").read()
        match = re.search(r"legacyLayerNames\s*:\s*\(\{(.*?)\}\)", text, re.S)
        self.assertIsNotNone(match, "legacyLayerNames not found in the sidecar")
        pairs = dict(re.findall(r"'([^']+)'\s*:\s*'([^']+)'", match.group(1)))
        self.assertEqual(pairs, LEGACY)


class TestMirrors(unittest.TestCase):
    """The other modules that re-export the canonical list must not fork."""

    def test_reconcile_and_z_filter_agree(self):
        # z_filter's package __init__ pulls in qgis; only assert where it loads.
        try:
            from z_filter import expression
        except ImportError as exc:  # pragma: no cover - depends on interpreter
            self.skipTest(f"qgis not available: {exc}")
        self.assertEqual(expression.Z_LAYERS, lgs_layers.CANONICAL_LAYERS)

    def test_no_stale_ordinals_in_source(self):
        """No module still hardcodes the pre-swap spellings.

        Nothing fails loudly on a leftover — find_best_match would fuzzy-match
        it and the sidecar's copy map would quietly return fewer pairs — so a
        grep is the only reliable check.
        """
        # Legitimate mentions: the rename script performs the migration, and
        # the two modules that implement backward compatibility must name the
        # old spellings to recognise them.
        exempt_files = {
            "rename_swap_linework_overlay.py",   # the migration itself
            "lgs_layers.py",                     # documents the swap
            "lgs_companion.qml",                 # legacyLayerNames alias map
            "layer_select.py",                   # documents the 95 match tier
            "test_layer_canon.py",               # this file
            "copy_fieldmap_harness.js",          # asserts legacy tolerance
        }
        skip_dirs = {".git", "__pycache__", "Template", "vendor"}
        stale = re.compile(r"2 - Overlay|3 - Linework")

        offenders = []
        for root, dirs, files in os.walk(REPO_ROOT):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for name in files:
                if not name.endswith((".py", ".qml", ".js")):
                    continue
                if name in exempt_files:
                    continue
                path = os.path.join(root, name)
                try:
                    text = open(path, encoding="utf-8").read()
                except (OSError, UnicodeDecodeError):
                    continue
                for number, line in enumerate(text.splitlines(), 1):
                    if stale.search(line):
                        rel = os.path.relpath(path, REPO_ROOT)
                        offenders.append(f"{rel}:{number}: {line.strip()}")

        self.assertEqual(offenders, [], "stale pre-swap layer names:\n" +
                         "\n".join(offenders))


if __name__ == "__main__":
    unittest.main(verbosity=2)
