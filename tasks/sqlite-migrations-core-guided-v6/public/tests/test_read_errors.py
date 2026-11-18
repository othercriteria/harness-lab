import hashlib
import sqlite3
import unittest

from migrator.discovery import Migration
from migrator.planner import plan


class ReadErrors(unittest.TestCase):
    def test_interrupted_existing_ledger_read_propagates(self):
        sql = "CREATE TABLE one(value INTEGER);"
        migration = Migration(1, "0001_one.sql", sql, hashlib.sha256(sql.encode()).hexdigest())
        connection = sqlite3.connect(":memory:", cached_statements=0)
        self.addCleanup(connection.close)
        connection.execute(sql)
        connection.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL)")
        row = (migration.version, migration.name, migration.checksum)
        connection.execute("INSERT INTO schema_migrations VALUES (?, ?, ?)", row)
        connection.commit()
        expected = {"applied": [1], "pending": [], "target": 1}
        self.assertEqual(plan(connection, [migration]), expected)
        # Allow catalog lookup; cancel when the actual ledger-row query runs.
        state = {"ledger_read": False, "cancelled": False}

        def authorize(action, table, column, database, trigger):
            if action == sqlite3.SQLITE_READ and table == "schema_migrations":
                state["ledger_read"] = True
            return sqlite3.SQLITE_OK

        def progress():
            if state["ledger_read"]:
                state["cancelled"] = True
                return 1
            return 0

        connection.set_authorizer(authorize)
        connection.set_progress_handler(progress, 1)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                plan(connection, [migration])
        finally:
            connection.set_progress_handler(None, 0)
            connection.set_authorizer(None)
        self.assertTrue(state["ledger_read"])
        self.assertTrue(state["cancelled"])
        self.assertFalse(connection.in_transaction)
        self.assertEqual(connection.execute("SELECT version, name, checksum FROM schema_migrations").fetchall(), [row])
        self.assertEqual(plan(connection, [migration]), expected)
