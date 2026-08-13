"""
Merge policies: what happens to data already in the GeoPackage when the same
ground is imported again.

Expression building lives here, in a pure module, so the quoting and the
empty-set handling can be unit-tested without QGIS. gpkg.py only executes
what it is handed.

Pure python — stdlib only.
"""

# Re-importing a file removes exactly what that file contributed last time,
# then writes it fresh. Predictable across every format, handles strings that
# were renamed or deleted between surveys, and needs no level concept — which
# DXF and CSV do not have. The default.
POLICY_REPLACE_SOURCE = 'replace_source'

# Delete every feature tagged with a Level being re-imported, regardless of
# which file it came from. Correct when one level is assembled from several
# files that are always imported together.
POLICY_REPLACE_LEVEL = 'replace_level'

# Never delete. Idempotence is the caller's problem.
POLICY_APPEND = 'append'

# Empty the target layer before writing. A rebuild, not a merge.
POLICY_REPLACE_ALL = 'replace_all'

POLICIES = (POLICY_REPLACE_SOURCE, POLICY_REPLACE_LEVEL, POLICY_APPEND,
            POLICY_REPLACE_ALL)

POLICY_LABELS = {
    POLICY_REPLACE_SOURCE: "Replace each file's previous data",
    POLICY_REPLACE_LEVEL: "Replace every level being imported",
    POLICY_APPEND: "Append only (never delete)",
    POLICY_REPLACE_ALL: "Replace the whole layer",
}

POLICY_HINTS = {
    POLICY_REPLACE_SOURCE:
        "Re-importing a file removes what it contributed last time. Other "
        "files are untouched.",
    POLICY_REPLACE_LEVEL:
        "Removes all features of every level being imported, whichever file "
        "they came from. Re-import a level's files together.",
    POLICY_APPEND:
        "Nothing is ever removed. Re-importing the same file duplicates it.",
    POLICY_REPLACE_ALL:
        "Everything already in the target layer is removed first.",
}


def quote(value):
    """Single-quote a value for a QGIS expression, doubling embedded quotes.

    Mirrors QgsExpression.quotedValue so this module stays qgis-free; the
    behaviour is asserted against the real thing in the QGIS script tests.
    """
    if value is None:
        return 'NULL'
    return "'" + str(value).replace("'", "''") + "'"


def _in_clause(field, values):
    """`"field" IN (...)` over de-duplicated values, or None when empty.

    Returning None rather than `IN ()` is load-bearing: an empty IN list is a
    syntax error on some backends and matches everything on others, so an
    import with nothing to supersede would silently empty the layer.
    """
    unique = []
    seen = set()
    for value in values or ():
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    if not unique:
        return None
    quoted = ', '.join(quote(v) for v in unique)
    return '"{0}" IN ({1})'.format(field, quoted)


def delete_expression(policy, source_keys=(), levels=(), exclude_batch=None):
    """QGIS expression selecting the features this import supersedes.

    Returns None when nothing should be deleted — callers must treat None as
    "skip the delete", never as "delete everything".

    exclude_batch protects the rows this run just wrote. Features are appended
    before the supersede delete runs (see gpkg.write_features), so without the
    guard the delete would remove the new data along with the old.
    """
    if policy == POLICY_APPEND:
        return None

    if policy == POLICY_REPLACE_ALL:
        base = 'TRUE'
    elif policy == POLICY_REPLACE_SOURCE:
        base = _in_clause('SourceKey', source_keys)
    elif policy == POLICY_REPLACE_LEVEL:
        base = _in_clause('Level', levels)
    else:
        raise ValueError('unknown merge policy: {0!r}'.format(policy))

    if base is None:
        return None
    if exclude_batch is None:
        return base
    guard = '("BatchId" IS NULL OR "BatchId" <> {0})'.format(
        quote(exclude_batch))
    return '({0}) AND {1}'.format(base, guard)


def batch_expression(batch_id):
    """Expression selecting exactly the features written by one run.

    Used by the compensating cleanup when a multi-layer import fails partway.
    """
    return '"BatchId" = {0}'.format(quote(batch_id))
