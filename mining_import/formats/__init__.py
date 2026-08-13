"""
Source-format readers.

Every module here is pure python: no qgis imports, and no imports of a
sibling reader. They reach the shared IR through the dual-import idiom
(try relative, fall back to flat) so each file can also be loaded directly
by path outside QGIS for unit testing.

This package's __init__ must stay empty of imports — registry.load() pulls
in exactly the one reader a scan needs, and importing readers eagerly here
would drag every format into plugin startup.
"""
