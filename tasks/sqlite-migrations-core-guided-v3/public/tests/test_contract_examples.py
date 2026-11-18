import sqlite3
import tempfile
import unittest
from pathlib import Path

from migrator.discovery import discover
from migrator.engine import apply
from migrator.planner import plan


class ContractExamples(unittest.TestCase):
    def test_autocommit_connection_rolls_back_whole_failed_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "0001_fresh.sql").write_text("CREATE TABLE fresh(value INTEGER);", encoding="utf-8")
            Path(tmp, "0002_fail.sql").write_text("INSERT INTO absent_table VALUES (1);", encoding="utf-8")
            connection = sqlite3.connect(":memory:", autocommit=True)
            self.addCleanup(connection.close)
            connection.execute("CREATE TABLE baseline(value INTEGER)")
            connection.execute("INSERT INTO baseline VALUES (7)")
            with self.assertRaises(sqlite3.Error):
                apply(connection, discover(tmp))
            self.assertFalse(connection.in_transaction)
            self.assertIs(connection.autocommit, True)
            self.assertEqual(connection.execute("SELECT value FROM baseline").fetchall(), [(7,)])
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("fresh", names)
            self.assertNotIn("schema_migrations", names)

    def test_planning_preserves_caller_transaction_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "0001_fresh.sql").write_text("CREATE TABLE fresh(value INTEGER);", encoding="utf-8")
            connection = sqlite3.connect(":memory:")
            self.addCleanup(connection.close)
            connection.execute("CREATE TABLE baseline(value INTEGER)")
            connection.commit()
            connection.execute("INSERT INTO baseline VALUES (9)")
            self.assertTrue(connection.in_transaction)
            self.assertEqual(plan(connection, discover(tmp)), {"applied": [], "pending": [1], "target": 1})
            self.assertTrue(connection.in_transaction)
            self.assertIsNone(connection.row_factory)
            self.assertIs(connection.text_factory, str)
            self.assertEqual(connection.execute("SELECT value FROM baseline").fetchall(), [(9,)])
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(names, {"baseline"})
            connection.rollback()
            self.assertEqual(connection.execute("SELECT value FROM baseline").fetchall(), [])

    def test_apply_orders_reversed_valid_input_without_mutating_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "0001_create.sql").write_text("CREATE TABLE items(value INTEGER);", encoding="utf-8")
            Path(tmp, "0002_insert.sql").write_text("INSERT INTO items VALUES (7);", encoding="utf-8")
            migrations = list(reversed(discover(tmp)))
            connection = sqlite3.connect(":memory:")
            self.addCleanup(connection.close)
            self.assertEqual(plan(connection, migrations), {"applied": [], "pending": [1, 2], "target": 2})
            self.assertEqual(apply(connection, migrations), {"applied": [1, 2], "current": 2})
            self.assertEqual(connection.execute("SELECT value FROM items").fetchall(), [(7,)])
            self.assertEqual([m.version for m in migrations], [2, 1])
            self.assertFalse(connection.in_transaction)

    def test_existing_empty_ledger_is_an_empty_history(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL)")
        connection.commit()
        self.assertEqual(plan(connection, []), {"applied": [], "pending": [], "target": 0})
        self.assertEqual(apply(connection, []), {"applied": [], "current": 0})
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "0001_fresh.sql").write_text("CREATE TABLE fresh(value INTEGER);", encoding="utf-8")
            migrations = discover(tmp)
            self.assertEqual(plan(connection, migrations), {"applied": [], "pending": [1], "target": 1})
            self.assertEqual(apply(connection, migrations), {"applied": [1], "current": 1})
            self.assertEqual(apply(connection, migrations), {"applied": [], "current": 1})
        self.assertFalse(connection.in_transaction)
