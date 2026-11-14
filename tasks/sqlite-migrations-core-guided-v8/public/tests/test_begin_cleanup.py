"""An interrupted BEGIN can fail after opening the transaction."""
import hashlib
import sqlite3
import unittest

from migrator.discovery import Migration
from migrator.engine import apply


class BeginCleanupExample(unittest.TestCase):
    def test_interrupted_begin_preserves_error_and_cleans_transaction(self):
        for mode in (sqlite3.LEGACY_TRANSACTION_CONTROL, True):
            with self.subTest(autocommit=mode):
                connection = sqlite3.connect(":memory:", autocommit=mode)
                try:
                    connection.execute("CREATE TABLE baseline(value INTEGER)")
                    connection.execute("INSERT INTO baseline VALUES(7)")
                    connection.commit()
                    state = {"armed": False, "interruptions": 0}

                    def authorize(action, first, second, database, trigger):
                        if action == sqlite3.SQLITE_TRANSACTION and first == "BEGIN":
                            state["armed"] = True
                        return sqlite3.SQLITE_OK

                    def progress():
                        if state["armed"] and connection.in_transaction:
                            state["armed"] = False
                            state["interruptions"] += 1
                            return 1
                        return 0

                    sql = "CREATE TABLE fresh(value INTEGER);"
                    migration = Migration(
                        1, "0001_fresh.sql", sql,
                        hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                    )
                    connection.set_authorizer(authorize)
                    connection.set_progress_handler(progress, 1)
                    try:
                        with self.assertRaises(sqlite3.OperationalError) as raised:
                            apply(connection, [migration])
                    finally:
                        connection.set_progress_handler(None, 0)
                        connection.set_authorizer(None)
                    self.assertEqual(raised.exception.sqlite_errorcode, sqlite3.SQLITE_INTERRUPT)
                    self.assertEqual(state["interruptions"], 1)
                    self.assertFalse(connection.in_transaction)
                    self.assertEqual(connection.execute("SELECT value FROM baseline").fetchall(), [(7,)])
                    self.assertEqual(
                        connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),
                        [("baseline",)],
                    )
                    self.assertEqual(apply(connection, [migration]), {"applied": [1], "current": 1})
                finally:
                    connection.close()
