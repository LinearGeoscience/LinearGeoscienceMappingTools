"""
Source discovery and change detection.

Walks a folder (or takes a hand-picked file list), works out which reader
each file belongs to, derives the stable key the merge engine deletes by,
fingerprints each file, and compares it against what the target GeoPackage's
import log says was imported last time. The result drives the dialog's
New / Changed / Unchanged / Missing column, which is what makes re-importing
after a fresh survey drop a one-click operation.

Pure python — stdlib only. Format knowledge lives in the readers; this module
only ever reaches them through registry.load().
"""

import hashlib
import os
import re
from collections import namedtuple
from datetime import datetime, timezone

try:  # package context
    from . import registry
except ImportError:  # loaded directly by path (tests, non-package execution)
    import registry

# Files at or above this size are fingerprinted from their head and tail
# rather than in full — hashing a 200 MB DXF on every folder scan is not
# worth the certainty.
PARTIAL_HASH_THRESHOLD = 32 * 1024 * 1024
_PARTIAL_CHUNK = 64 * 1024
_PARTIAL_PREFIX = 'p:'

STATUS_NEW = 'new'
STATUS_CHANGED = 'changed'
STATUS_UNCHANGED = 'unchanged'
STATUS_MISSING = 'missing'

STATUS_LABELS = {
    STATUS_NEW: 'New',
    STATUS_CHANGED: 'Changed',
    STATUS_UNCHANGED: 'Unchanged',
    STATUS_MISSING: 'Missing',
}

# One discovered source file.
#   path        absolute path
#   key         merge identity, see source_key()
#   fmt_key     registry format key, or None when nothing claims it
#   companions  {'.dtm': path} for files a reader consumes alongside this one
#   level       level label parsed from the filename (editable in the dialog)
#   size        bytes
#   mtime_utc   ISO8601
#   status      one of the STATUS_* values, filled in by classify()
#   note        why it has that status, shown as a tooltip
Entry = namedtuple(
    'Entry',
    'path key fmt_key companions level size mtime_utc status note')
Entry.__new__.__defaults__ = (None, STATUS_NEW, '')


def parse_level_from_filename(filename):
    """Level name from a filename: the trailing digit group of the stem
    ('mga_floor_1164.str' -> '1164'). No trailing digits -> the stem itself,
    so the file stays importable under a sensible label."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    match = re.search(r'(\d+)$', stem)
    return match.group(1) if match else stem


def normalise_root(root):
    return os.path.normpath(os.path.abspath(root))


def source_key(path, scan_root):
    """Stable merge identity: path relative to scan_root, '/'-joined, folded.

    Relative-to-root is the right identity because it survives the whole
    survey tree being moved, renamed or landing at a different absolute path
    on another machine — while still telling '1164/floor.str' apart from
    '1218/floor.str', which a basename key would silently conflate into a
    destructive overwrite.

    A path outside scan_root falls back to its basename rather than producing
    a key full of '..' segments.
    """
    abs_path = os.path.normpath(os.path.abspath(path))
    root = normalise_root(scan_root)
    try:
        rel = os.path.relpath(abs_path, root)
    except ValueError:  # different drive on Windows
        return os.path.basename(abs_path).lower()
    if rel.startswith(os.pardir):
        return os.path.basename(abs_path).lower()
    return rel.replace('\\', '/').lower()


def derive_root(paths):
    """Scan root for a hand-picked file list: their deepest common folder.

    Picking a single file therefore keys it by basename, which is documented
    and acceptable — the relink path in classify() covers the case where a
    later folder scan produces different keys for the same files.
    """
    abs_paths = [os.path.normpath(os.path.abspath(p)) for p in paths]
    if not abs_paths:
        return ''
    if len(abs_paths) == 1:
        return os.path.dirname(abs_paths[0])
    try:
        common = os.path.commonpath(abs_paths)
    except ValueError:  # mixed drives
        return os.path.dirname(abs_paths[0])
    if os.path.isfile(common):
        common = os.path.dirname(common)
    return common


def _iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def file_fingerprint(path, deep=False):
    """(size, mtime_utc, content_hash) for path; content_hash None unless deep.

    Size and mtime are free and settle almost every comparison. The hash is
    computed only when a caller explicitly asks — on a full rescan of a large
    survey tree, hashing every file would dominate the scan.

    Files at or above PARTIAL_HASH_THRESHOLD hash size + head + tail and the
    digest is prefixed 'p:', so a partial hash is never compared as equal to
    a full one over the same bytes.
    """
    stat = os.stat(path)
    size = stat.st_size
    mtime = _iso(stat.st_mtime)
    if not deep:
        return (size, mtime, None)
    return (size, mtime, content_hash(path, size))


def content_hash(path, size=None):
    if size is None:
        size = os.path.getsize(path)
    digest = hashlib.sha1()
    digest.update(str(size).encode('ascii'))
    if size >= PARTIAL_HASH_THRESHOLD:
        with open(path, 'rb') as fh:
            digest.update(fh.read(_PARTIAL_CHUNK))
            fh.seek(-_PARTIAL_CHUNK, os.SEEK_END)
            digest.update(fh.read(_PARTIAL_CHUNK))
        return _PARTIAL_PREFIX + digest.hexdigest()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def hashes_comparable(a, b):
    """False when one hash is partial and the other is full over the same file."""
    if not a or not b:
        return False
    return a.startswith(_PARTIAL_PREFIX) == b.startswith(_PARTIAL_PREFIX)


def _resolve_format(path, candidates, sniff=True):
    """Pick the reader for a file. Extension first; sniff only to break ties.

    A sniffer that raises is treated as "not mine" — a malformed file should
    fall through to the next candidate, not abort the whole scan.
    """
    if not candidates:
        return None
    if len(candidates) == 1 or not sniff:
        return candidates[0].key
    best_key, best_score = candidates[0].key, -1.0
    for candidate in candidates:
        try:
            score = registry.sniffer_for(candidate)(path)
        except Exception:
            continue
        if score > best_score:
            best_key, best_score = candidate.key, score
    return best_key


def discover(folder, sniff=True):
    """Recursively find importable files under folder.

    Companion files (a .dtm beside its .str) are attached to their source
    rather than listed separately, so the dialog shows one row per thing the
    user thinks of as a file.

    Returns [Entry] sorted by (level, basename), with status left at NEW —
    call classify() against an import log to fill that in.
    """
    root = normalise_root(folder)
    entries = []
    companion_exts = registry.companion_extensions()
    for dirpath, _dirs, files in os.walk(root):
        by_lower = {f.lower(): f for f in files}
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            candidates = registry.formats_for_extension(ext)
            if not candidates:
                continue
            path = os.path.join(dirpath, fname)
            fmt_key = _resolve_format(path, candidates, sniff=sniff)
            if fmt_key is None:
                continue
            stem = os.path.splitext(fname)[0]
            companions = {}
            for comp_ext in companion_exts:
                match = by_lower.get(stem.lower() + comp_ext)
                if match:
                    companions[comp_ext] = os.path.join(dirpath, match)
            size, mtime, _ = file_fingerprint(path)
            entries.append(Entry(
                path=path,
                key=source_key(path, root),
                fmt_key=fmt_key,
                companions=companions,
                level=parse_level_from_filename(fname),
                size=size,
                mtime_utc=mtime,
            ))
    entries.sort(key=lambda e: (e.level, os.path.basename(e.path).lower()))
    return entries


def discover_paths(paths, sniff=True):
    """Same as discover() but over a hand-picked file list.

    The scan root is their common folder, so keys stay consistent with a
    later folder scan of that same folder.
    """
    root = derive_root(paths)
    entries = []
    companion_exts = registry.companion_extensions()
    for path in paths:
        path = os.path.normpath(os.path.abspath(path))
        if not os.path.isfile(path):
            continue
        candidates = registry.formats_for_path(path)
        if not candidates:
            continue
        fmt_key = _resolve_format(path, candidates, sniff=sniff)
        if fmt_key is None:
            continue
        stem, _ext = os.path.splitext(path)
        companions = {}
        for comp_ext in companion_exts:
            for cased in (stem + comp_ext, stem + comp_ext.upper()):
                if os.path.isfile(cased):
                    companions[comp_ext] = cased
                    break
        size, mtime, _ = file_fingerprint(path)
        entries.append(Entry(
            path=path,
            key=source_key(path, root),
            fmt_key=fmt_key,
            companions=companions,
            level=parse_level_from_filename(path),
            size=size,
            mtime_utc=mtime,
        ))
    entries.sort(key=lambda e: (e.level, os.path.basename(e.path).lower()))
    return entries, root


def duplicate_keys(entries):
    """Keys claimed by more than one entry, sorted.

    Only reachable when files are hand-picked from folders that collapse to
    the same relative path; the dialog warns rather than silently letting one
    file's import delete another's data.
    """
    seen = {}
    for entry in entries:
        seen.setdefault(entry.key, []).append(entry.path)
    return sorted(k for k, paths in seen.items() if len(paths) > 1)


def classify(entries, log_rows, deep=False):
    """Tag each entry New / Changed / Unchanged against the import log.

    log_rows: {source_key: {'file_size', 'file_mtime_utc', 'content_hash'}}
    as read back from the target GeoPackage.

    Size or mtime differing is enough to call something changed. They only
    agree spuriously when a file was rewritten byte-identically, in which
    case re-importing it would be a no-op anyway. deep=True additionally
    hashes to catch a same-size same-mtime rewrite, at real cost.
    """
    out = []
    for entry in entries:
        row = log_rows.get(entry.key)
        if row is None:
            out.append(entry._replace(status=STATUS_NEW,
                                      note='Not yet imported'))
            continue
        if row.get('file_size') != entry.size:
            out.append(entry._replace(
                status=STATUS_CHANGED, note='Size differs from last import'))
            continue
        if row.get('file_mtime_utc') != entry.mtime_utc:
            out.append(entry._replace(
                status=STATUS_CHANGED,
                note='Modified since last import'))
            continue
        if deep:
            logged = row.get('content_hash')
            current = content_hash(entry.path, entry.size)
            if hashes_comparable(logged, current) and logged != current:
                out.append(entry._replace(
                    status=STATUS_CHANGED, note='Contents differ'))
                continue
        imported = row.get('imported_at_utc') or 'a previous run'
        out.append(entry._replace(
            status=STATUS_UNCHANGED,
            note='Unchanged since {0}'.format(imported)))
    return out


def missing_sources(entries, log_rows):
    """Log keys with no file on disk in this scan.

    Either the survey file was deleted, or the scan root moved and every key
    shifted — which is why the dialog offers relink rather than purge as the
    first suggestion when *everything* comes back missing.
    """
    present = {entry.key for entry in entries}
    return sorted(key for key in log_rows if key not in present)


def relink_candidates(entries, log_rows):
    """Match orphaned log keys to discovered files after a scan-root change.

    Matches on content hash first, then basename + size. Returns
    {old_key: new_key} for the dialog to confirm — never applied silently,
    because a wrong relink deletes the wrong features.
    """
    missing = missing_sources(entries, log_rows)
    if not missing:
        return {}
    unmatched = [e for e in entries if e.key not in log_rows]
    if not unmatched:
        return {}

    by_hash = {}
    by_name_size = {}
    for entry in unmatched:
        basename = os.path.basename(entry.path).lower()
        by_name_size.setdefault((basename, entry.size), []).append(entry)

    mapping = {}
    claimed = set()
    for old_key in missing:
        row = log_rows[old_key]
        logged_hash = row.get('content_hash')
        match = None
        if logged_hash:
            for entry in unmatched:
                if entry.key in claimed:
                    continue
                if entry.key not in by_hash:
                    by_hash[entry.key] = content_hash(entry.path, entry.size)
                if hashes_comparable(logged_hash, by_hash[entry.key]) and \
                        by_hash[entry.key] == logged_hash:
                    match = entry
                    break
        if match is None:
            basename = (row.get('source_file') or '').lower()
            for entry in by_name_size.get((basename, row.get('file_size')), ()):
                if entry.key not in claimed:
                    match = entry
                    break
        if match is not None:
            mapping[old_key] = match.key
            claimed.add(match.key)
    return mapping
