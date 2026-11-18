import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eventlog.importer import import_events
from eventlog.store import EventStore


class CommitContract(unittest.TestCase):
    def test_failed_commit_rolls_back_current_import_and_store_remains_usable(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = str(Path(tmp) / 'events.db')
            connect = sqlite3.connect

            def no_wait_connect(*args, **kwargs):
                if len(args) > 1:
                    args = (args[0], 0, *args[2:])
                    kwargs.pop('timeout', None)
                else:
                    kwargs['timeout'] = 0
                return connect(*args, **kwargs)

            # Keep the example fast: SQLite reports an incompatible reader lock
            # immediately, rather than spending the usual busy timeout waiting.
            with patch('sqlite3.connect', side_effect=no_wait_connect):
                store = EventStore(database)
            try:
                event = lambda identifier: json.dumps({'id': identifier, 'kind': 'test', 'value': 1})
                import_events([event('old')], store)
                reader = connect(database)
                try:
                    reader.execute('BEGIN')
                    reader.execute('SELECT name FROM sqlite_master').fetchall()
                    with self.assertRaises(sqlite3.OperationalError):
                        import_events([event('pending')], store)
                finally:
                    reader.rollback()
                    reader.close()
                self.assertEqual(store.count(), 1)
                self.assertIsNone(store.get('pending'))
                self.assertIsNotNone(store.get('old'))
                report = import_events([event('next')], store)
                self.assertEqual(report['inserted'], 1)
                self.assertEqual(store.count(), 2)
                self.assertIsNone(store.get('pending'))
            finally:
                store.close()
            reopened = EventStore(database)
            try:
                self.assertEqual(reopened.count(), 2)
                self.assertIsNone(reopened.get('pending'))
            finally:
                reopened.close()
