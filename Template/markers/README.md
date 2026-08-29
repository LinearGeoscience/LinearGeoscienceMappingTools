# Linework marker sources

Source SVGs for the "2 - Linework" ornament markers, embedded into the
template by `scripts/inject_linework_marker_decorations.py`.

Conventions (see the injector docstring for the full contract):

* Canvas is always 500 units wide; QML `size` = rendered width in the
  spec's unit.  Height carries the aspect (fixedAspectRatio stays 0).
* **The line is the horizontal centerline `y = H/2`** and the QML marker
  offset is always `0,0` - anchoring lives in the geometry, so a glyph
  that must sit ON the line touches the centerline and one that stands
  off gets that gap drawn as empty canvas.  Markers can then never
  detach from (or bury into) the stroke at any Weight.
* Colours ride `param(fill)` / `param(outline)` (default #131313);
  stroke weight rides `param(outline-width)`.  Arrowheads are pure
  filled polygons (no stroke) so they stay razor sharp at any size.
* `slip_dextral` has no file: the injector mirrors `slip_sinistral.svg`
  (`x -> 500 - x`) at run time so the pair can never misregister.

Edit a file, re-run the injector, and the template picks it up.
