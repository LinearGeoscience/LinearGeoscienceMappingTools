"""
Declarative table of supported source formats, plus a lazy loader.

The table holds STRINGS, never module objects: nothing under formats/ is
imported until load() is called for a format the user actually selected.
That is what lets this module — and every reader — be unit-tested outside
QGIS, and it keeps plugin startup free of import cost for formats nobody
touches.

Extension alone is not decisive: '.str' is both a Surpac string file and a
plain text file some packages use for their own string format, and '.asc'
is claimed by several. formats_for_extension() therefore returns every
candidate in priority order and scan.py disambiguates by asking each
candidate's sniffer to look at the first few lines.

Pure python — stdlib only.
"""

import importlib
import os
from collections import namedtuple

# key              stable id, stored in the Format column and the import log
# label            human-facing name for the dialog
# module           module name under mining_import/formats/
# extensions       lowercase extensions this reader claims, with the dot
# companion_exts   extensions pulled in alongside a matched file (Surpac
#                  .dtm beside its .str) — never scanned as sources
# reader           attribute name of read_file(path, **options) -> ParsedFile
# sniffer          attribute name of sniff(path) -> float confidence 0..1
# needs_column_map True when the reader may need user-supplied column roles,
#                  which can force the main-thread mapping step
# binary           True when the file is not line-oriented text
# min_confidence   sniffer score below which a file is NOT claimed at all.
#                  Zero for an extension only this format uses; above zero for
#                  generic ones — '.txt' otherwise drags every readme and set
#                  of notes in a survey folder into the import list.
# fingerprint_companions
#                  True when companion files carry data the source file does
#                  not (a shapefile's .dbf holds every attribute), so change
#                  detection must fold them into the size/mtime fingerprint.
#                  Off for surpac: folding the .dtm in would flip every
#                  already-logged .str to "Changed" once for no reason.
FormatSpec = namedtuple(
    'FormatSpec',
    'key label module extensions companion_exts reader sniffer '
    'needs_column_map binary min_confidence fingerprint_companions')
FormatSpec.__new__.__defaults__ = (False,)

FORMATS = (
    FormatSpec('surpac', 'Surpac string', 'surpac',
               ('.str',), ('.dtm',), 'read_file', 'sniff', False, False, 0.0),
    FormatSpec('delimited', 'CSV / XYZ text', 'delimited',
               ('.csv', '.txt', '.xyz', '.pts'), (), 'read_file', 'sniff',
               True, False, 0.5),
    FormatSpec('dxf', 'AutoCAD DXF', 'dxf',
               ('.dxf',), (), 'read_file', 'sniff', False, False, 0.0),
    FormatSpec('shapefile', 'ESRI Shapefile', 'ogrvector',
               ('.shp',), ('.dbf', '.shx', '.prj', '.cpg', '.qmd'),
               'read_file', 'sniff_shp', False, True, 0.0,
               fingerprint_companions=True),
    # min_confidence 0.2, NOT 0.0, on purpose: sniff_gpkg returns 0.0 for a
    # GeoPackage that is this importer's own output (it contains the import
    # log table), and scan._resolve_format claims a unique-extension format
    # with a zero floor even when its sniffer scores 0. Lowering this floor
    # to zero would silently re-ingest our own output GeoPackages.
    FormatSpec('geopackage', 'GeoPackage', 'ogrvector',
               ('.gpkg',), (), 'read_file', 'sniff_gpkg', False, True, 0.2),
)

# Formats landing in later stages, listed here so the dialog can say "not yet
# supported" rather than silently ignoring a file the user clearly wants:
PLANNED = (
    ('.12da', '12d Model ASCII'),
    ('.dm', 'Datamine'),
    ('.asc', 'Datamine / grid ASCII'),
    ('.dwg', 'AutoCAD DWG (re-export as DXF)'),
)


class UnknownFormat(KeyError):
    """Raised for a format key with no FormatSpec."""


def spec(key):
    for fmt in FORMATS:
        if fmt.key == key:
            return fmt
    raise UnknownFormat(key)


def all_specs():
    return FORMATS


def source_extensions():
    """Every extension that makes a file a candidate source (not a companion)."""
    out = set()
    for fmt in FORMATS:
        out.update(fmt.extensions)
    return out


def companion_extensions():
    out = set()
    for fmt in FORMATS:
        out.update(fmt.companion_exts)
    return out


def formats_for_extension(ext):
    """Candidate specs for a file extension, in FORMATS order.

    ext may be given with or without the leading dot, any case.
    """
    if not ext:
        return ()
    ext = ext.lower()
    if not ext.startswith('.'):
        ext = '.' + ext
    return tuple(f for f in FORMATS if ext in f.extensions)


def formats_for_path(path):
    return formats_for_extension(os.path.splitext(path)[1])


def planned_label(path):
    """Label of a format that is recognised but not implemented yet, else None."""
    ext = os.path.splitext(path)[1].lower()
    if formats_for_extension(ext):
        return None
    for planned_ext, label in PLANNED:
        if ext == planned_ext:
            return label
    return None


def load(fmt, attr):
    """Import fmt's module and return one of its callables by attribute name.

    Resolved package-relative first, then flat. The flat fallback is what
    keeps readers loadable when this file has been loaded directly by path
    (tests): __package__ is then None and the relative import raises
    TypeError rather than ImportError.
    """
    module = None
    if __package__:
        try:
            module = importlib.import_module(
                '.formats.' + fmt.module, package=__package__)
        except ImportError:
            module = None
    if module is None:
        try:
            module = importlib.import_module('formats.' + fmt.module)
        except ImportError:
            module = importlib.import_module(fmt.module)
    return getattr(module, attr)


def reader_for(fmt):
    return load(fmt, fmt.reader)


def sniffer_for(fmt):
    return load(fmt, fmt.sniffer)
