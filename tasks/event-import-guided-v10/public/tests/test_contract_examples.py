import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from eventlog.cli import main
from eventlog.importer import import_events
from eventlog.store import EventStore


class ContractExamples(unittest.TestCase):
    def test_strict_rollback_preserves_prior_import_and_store_usability(self):
        from eventlog.importer import ImportFailure

        store = EventStore(":memory:")
        self.addCleanup(store.close)
        import_events([json.dumps({"id": " old ", "kind": " SALE ", "value": 7})], store)
        with self.assertRaises(ImportFailure) as caught:
            import_events([
                json.dumps({"id": "new", "kind": "sale", "value": 8}),
                "   ",
                json.dumps({"id": "old", "kind": "sale", "value": True}),
            ], store, strict=True)
        self.assertEqual(caught.exception.line, 3)
        self.assertIsInstance(caught.exception.message, str)
        self.assertTrue(caught.exception.message)
        self.assertEqual(store.count(), 1)
        self.assertIsNone(store.get("new"))
        self.assertEqual(store.get("old"), {"id": "old", "kind": "sale", "value": 7})
        report = import_events([
            json.dumps({"id": "old", "kind": "other", "value": 99}),
            json.dumps({"id": "old", "kind": "sale", "value": False}),
            json.dumps({"id": "new", "kind": "sale", "value": 8}),
        ], store)
        self.assertEqual(set(report), {"inserted", "duplicates", "invalid", "errors"})
        self.assertEqual([report[k] for k in ("inserted", "duplicates", "invalid")], [1, 1, 1])
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(report["errors"][0]["line"], 2)
        self.assertTrue(report["errors"][0]["message"])
        self.assertEqual(store.get("old")["value"], 7)
        self.assertEqual(store.count(), 2)

    def test_cli_source_failure_after_a_line_rolls_back_and_reports_diagnostic(self):
        class UnreadableTail(io.TextIOBase):
            def __init__(self):
                self.pending = '{"id":"new","kind":"sale","value":8}\n'

            def read(self, size=-1):
                if size == 0:
                    return ""
                if size < 0 or not self.pending:
                    raise OSError("source became unreadable")
                text, self.pending = self.pending[:size], self.pending[size:]
                return text

            def readline(self, size=-1):
                if size == 0:
                    return ""
                if not self.pending:
                    raise OSError("source became unreadable")
                return self.read(len(self.pending) if size < 0 else size)

        with tempfile.TemporaryDirectory() as tmp:
            database = str(Path(tmp) / "events.db")
            store = EventStore(database)
            try:
                import_events(['{"id":"old","kind":"sale","value":7}'], store)
            finally:
                store.close()
            out, err = io.StringIO(), io.StringIO()
            with patch("sys.stdin", UnreadableTail()), redirect_stdout(out), redirect_stderr(err):
                code = main([database, "-"])
            self.assertEqual(code, 2)
            self.assertEqual(out.getvalue(), "")
            self.assertTrue(err.getvalue().strip())
            self.assertNotIn("Traceback", err.getvalue())
            store = EventStore(database)
            try:
                self.assertEqual(store.count(), 1)
                self.assertIsNone(store.get("new"))
                self.assertEqual(store.get("old")["value"], 7)
            finally:
                store.close()
