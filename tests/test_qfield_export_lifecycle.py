"""
Tests for the exporter's thread lifecycle — the crash class of 2026-09-03.

Two real crashes, one root shape: run_qfield_export holds the dialog in a
local, so the moment exec() returns the dialog (and its QThread member)
is garbage-collected — and destroying a running QThread aborts the whole
of QGIS. Closing the dialog mid-export did it directly; cancelling did it
indirectly, because the converter's cancel path returned WITHOUT emitting
finished, wedging the UI on "Cancelling..." until the user closed it.

The contracts pinned here (qgis-free, ast/source-level like the other
exporter tests):

1. OfflineConverter.export() emits finished(bool) on every exit, exactly
   once — the body lives in _export(), which never touches the signal.
2. The dialog never closes while the worker runs: reject() (Esc) and
   closeEvent() (the X) both divert to a cancel request and defer the
   close to _on_export_finished.
3. A thread that will not stop is parked out of the GC's reach, never
   deleteLater'd while running.
4. A cancelled export is reported as cancelled, not as a failure.

Run from the plugin root:
    python -m unittest discover tests
"""

import ast
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIALOG = os.path.join(_ROOT, 'qfield_export', 'gui', 'export_dialog.py')
_CONVERTER = os.path.join(_ROOT, 'qfield_export', 'core',
                          'offline_converter.py')


def _read(path):
    with open(path, encoding='utf-8') as handle:
        return handle.read()


def _method_source(path, class_name, method_name):
    source = _read(path)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if (isinstance(item, (ast.FunctionDef,
                                      ast.AsyncFunctionDef))
                        and item.name == method_name):
                    return ast.get_source_segment(source, item)
    raise AssertionError(
        '{0}.{1} not found in {2}'.format(class_name, method_name, path))


class TestConverterAlwaysFinishes(unittest.TestCase):
    """finished(bool) must fire on EVERY exit of export()."""

    def test_export_is_a_thin_wrapper_emitting_finished_once(self):
        src = _method_source(_CONVERTER, 'OfflineConverter', 'export')
        self.assertEqual(src.count('self.finished.emit'), 1,
                         'export() must emit finished exactly once')
        self.assertIn('self._export()', src,
                      'the body lives in _export(), behind the emit')
        self.assertIn('except', src,
                      'an exception must still reach the emit')

    def test_the_body_never_touches_the_signal(self):
        src = _method_source(_CONVERTER, 'OfflineConverter', '_export')
        self.assertNotIn(
            'finished.emit', src,
            '_export() returning is the ONLY way to signal completion; '
            'an emit inside it would double-fire')

    def test_cancel_state_is_readable(self):
        source = _read(_CONVERTER)
        self.assertIn('def was_cancelled', source,
                      'the dialog needs to tell cancelled from failed')


class TestDialogNeverClosesMidExport(unittest.TestCase):
    """X, Esc and Cancel must all become a cancel request, never a close
    of a dialog whose QThread is still running."""

    def test_reject_guards_the_running_thread(self):
        src = _method_source(_DIALOG, 'ExportDialog', 'reject')
        self.assertIn('_export_running()', src)
        self.assertIn('_close_requested', src)
        self.assertIn('_request_cancel()', src)

    def test_close_event_guards_and_ignores(self):
        src = _method_source(_DIALOG, 'ExportDialog', 'closeEvent')
        self.assertIn('_export_running()', src)
        self.assertIn('event.ignore()', src)
        self.assertIn('_request_cancel()', src)

    def test_deferred_close_is_honoured_after_the_thread_stops(self):
        src = _method_source(_DIALOG, 'ExportDialog', '_on_export_finished')
        self.assertIn('_close_requested', src)
        self.assertIn('self.reject', src)

    def test_cancelled_is_not_reported_as_failure(self):
        src = _method_source(_DIALOG, 'ExportDialog', '_on_export_finished')
        self.assertIn('was_cancelled', src)
        self.assertIn('Export cancelled', src)


class TestNoRunningThreadIsEverDestroyed(unittest.TestCase):
    """Destroying a running QThread is a hard QGIS crash; a thread that
    misses its wait() deadline must be parked, not deleted."""

    def test_parking_exists(self):
        source = _read(_DIALOG)
        self.assertIn('_ORPHAN_EXPORTS', source)
        self.assertIn('def _park_running_export', source)

    def test_cleanup_parks_instead_of_deleting(self):
        src = _method_source(_DIALOG, 'ExportDialog', '_cleanup_export')
        self.assertIn('_park_running_export', src)

    def test_finish_handler_parks_instead_of_deleting(self):
        src = _method_source(_DIALOG, 'ExportDialog', '_on_export_finished')
        self.assertIn('_park_running_export', src)

    def test_converter_is_released_not_deletelaterd(self):
        """deleteLater posted to an object whose thread's event loop has
        quit is never processed — the reference drop is the cleanup."""
        for method in ('_cleanup_export', '_on_export_finished'):
            src = _method_source(_DIALOG, 'ExportDialog', method)
            self.assertNotIn('self.converter.deleteLater', src, method)


if __name__ == '__main__':
    unittest.main()
