import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from eventlog.importer import import_events
from eventlog.store import EventStore


class StorageErrorExample(unittest.TestCase):
    def test_full_database_preserves_original_error_and_store_usability(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(str(Path(tmp) / "events.db"))
            try:
                event = lambda identifier: json.dumps(
                    {"id": identifier, "kind": "test", "value": 1}
                )
                import_events([event("prior")], store)
                # Bound allocation to provoke a real storage error quickly.
                # SQLITE_FULL can itself roll back SQLite's transaction.
                pages = store.connection.execute("PRAGMA page_count").fetchone()[0]
                store.connection.execute(f"PRAGMA max_page_count={pages + 1}")
                with self.assertRaises(sqlite3.Error) as caught:
                    import_events([event("pending"), event("x" * 30000)], store)
                self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_FULL)
                self.assertFalse(store.connection.in_transaction)
                self.assertEqual(store.count(), 1)
                self.assertIsNotNone(store.get("prior"))
                self.assertIsNone(store.get("pending"))
                report = import_events([event("next")], store)
                self.assertEqual(report["inserted"], 1)
                self.assertEqual(store.count(), 2)
            finally:
                store.close()
