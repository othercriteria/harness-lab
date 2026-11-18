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
