"""A failed transaction start must leave the importer ready for another call."""

import json
import sqlite3
import unittest

from eventlog.importer import import_events
from eventlog.store import EventStore


class TransactionStartCleanup(unittest.TestCase):
    def test_interrupted_start_preserves_prior_data_and_allows_next_import(self):
        store = EventStore(":memory:")
        self.addCleanup(store.close)
        baseline = {"id": "baseline", "kind": "keep", "value": 7}
        import_events([json.dumps(baseline)], store)
        connection = store.connection
        state = {"armed": False, "interruptions": 0}

        def authorizer(action, arg1, arg2, database, trigger):
            if action == sqlite3.SQLITE_TRANSACTION and arg1 == "BEGIN":
                state["armed"] = True
            return sqlite3.SQLITE_OK

        def progress():
            if state["armed"] and connection.in_transaction:
                state["armed"] = False
                state["interruptions"] += 1
                return 1
            return 0

        connection.set_authorizer(authorizer)
        connection.set_progress_handler(progress, 1)
        try:
            with self.assertRaises(sqlite3.OperationalError) as caught:
                import_events(
                    [json.dumps({"id": "new", "kind": "add", "value": 1})], store
                )
            self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_INTERRUPT)
            self.assertEqual(state["interruptions"], 1)
            self.assertFalse(connection.in_transaction)
        finally:
            connection.set_progress_handler(None, 0)
            connection.set_authorizer(None)

        self.assertEqual(store.get("baseline"), baseline)
        self.assertIsNone(store.get("new"))
        later = {"id": "later", "kind": "add", "value": 2}
        result = import_events([json.dumps(later)], store)
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(store.get("later"), later)
        self.assertFalse(connection.in_transaction)
