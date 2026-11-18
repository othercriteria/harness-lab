import sqlite3
import tempfile
import unittest
from pathlib import Path

from migrator.discovery import discover
from migrator.engine import apply
from migrator.sql import split_sql


class PublicTests(unittest.TestCase):
    def test_empty_discovery(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(discover(root), [])

    def test_basic_apply(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "0001_create.sql").write_text(
                "CREATE TABLE example (value TEXT);"
            )
            connection = sqlite3.connect(":memory:")
            self.addCleanup(connection.close)
            self.assertEqual(
                apply(connection, discover(root)), {"applied": [1], "current": 1}
            )
            connection.execute("SELECT * FROM example")

    def test_split_quoted_semicolon(self):
        self.assertEqual(len(split_sql("SELECT 'a;b'; SELECT 1; -- tail")), 2)
