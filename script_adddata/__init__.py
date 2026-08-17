#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Reconcile / Merge Field Data, plus the shared UUID-field detection.

The GeoPackage append tool that gave this package its name was replaced by
data_import/ — a guided importer that treats bringing old mapping into a current
template as the migration it now is, rather than a row copy. What stayed is the
three-way reconcile system, which is a different feature that happened to live
here, and utils.detect_uuid_field, which hardcode_data and reconcile both need.

The package keeps its name because six test modules and the reconcile engine
resolve `script_adddata/reconcile` by path; renaming it is churn for no gain.
"""

from .utils import detect_uuid_field

__all__ = ['detect_uuid_field']
