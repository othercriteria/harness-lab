import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from eventlog.cli import main
from eventlog.importer import import_events
from eventlog.store import EventStore


class PublicTests(unittest.TestCase):
    def test_simple_import(self):
        store = EventStore(":memory:")
        try:
            report = import_events(['{"id":"a","kind":"sale","value":4}\n'], store)
            self.assertEqual(report["inserted"], 1)
            self.assertEqual(store.get("a")["value"], 4)
        finally:
            store.close()

    def test_empty(self):
        store = EventStore(":memory:")
        try:
            self.assertEqual(
                import_events([], store),
                {"inserted": 0, "duplicates": 0, "invalid": 0, "errors": []},
            )
        finally:
            store.close()

    def test_cli_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input.jsonl"
            source.write_text('{"id":"b","kind":"sale","value":9}\n')
            out = io.StringIO()
            with redirect_stdout(out):
                code = main([str(Path(tmp) / "events.db"), str(source)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue())["inserted"], 1)
