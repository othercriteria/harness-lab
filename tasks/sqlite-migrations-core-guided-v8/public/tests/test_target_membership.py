import hashlib
import sqlite3
import unittest

from migrator.discovery import Migration
from migrator.engine import apply
from migrator.planner import plan


class TargetMembershipExample(unittest.TestCase):
    def test_target_must_be_zero_or_an_available_version(self):
        def migration(version):
            sql = f"CREATE TABLE item_{version}(value INTEGER);"
            return Migration(version, f"{version:04d}_item.sql", sql,
                             hashlib.sha256(sql.encode("utf-8")).hexdigest())

        migrations = [migration(1), migration(3)]
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        for target in (2, 4, -1, True, False, "1"):
            for operation in (plan, apply):
                with self.subTest(target=target, operation=operation.__name__):
                    with self.assertRaises(ValueError):
                        operation(connection, migrations, target=target)
        self.assertEqual(connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall(), [])
        self.assertFalse(connection.in_transaction)
        self.assertEqual(plan(connection, migrations, target=0),
                         {"applied": [], "pending": [], "target": 0})
        self.assertEqual(plan(connection, migrations, target=1),
                         {"applied": [], "pending": [1], "target": 1})
        self.assertEqual(plan(connection, migrations, target=3),
                         {"applied": [], "pending": [1, 3], "target": 3})
