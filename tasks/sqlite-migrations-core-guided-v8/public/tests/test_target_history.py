import hashlib
import sqlite3
import unittest

from migrator.discovery import Migration
from migrator.engine import apply
from migrator.planner import plan


class TargetHistoryExample(unittest.TestCase):
    def test_target_selection_respects_already_applied_history(self):
        def migration(version):
            sql = f"CREATE TABLE item_{version}(value INTEGER);"
            return Migration(version, f"{version:04d}_item.sql", sql,
                             hashlib.sha256(sql.encode("utf-8")).hexdigest())

        migrations = [migration(1), migration(3)]
        for options in ({}, {"autocommit": True}):
            connection = sqlite3.connect(":memory:", **options)
            try:
                for current, newly_applied in ((1, [1]), (3, [3])):
                    with self.subTest(options=options, current=current):
                        self.assertEqual(
                            apply(connection, migrations, target=current),
                            {"applied": newly_applied, "current": current},
                        )
                        before = list(connection.iterdump())
                        changes_before = connection.total_changes
                        history = [m.version for m in migrations
                                   if m.version <= current]
                        # Zero selects no migrations only when history is empty.
                        # With recorded history, every lower target is a downgrade.
                        for target in (v for v in (0, 1) if v < current):
                            for operation in (plan, apply):
                                with self.subTest(target=target,
                                                  operation=operation.__name__):
                                    with self.assertRaises(ValueError):
                                        operation(connection, migrations, target=target)
                                    self.assertFalse(connection.in_transaction)
                                    self.assertEqual(list(connection.iterdump()), before)
                                    self.assertEqual(connection.total_changes, changes_before)
                        self.assertEqual(
                            plan(connection, migrations, target=current),
                            {"applied": history, "pending": [], "target": current},
                        )
                        self.assertEqual(
                            apply(connection, migrations, target=current),
                            {"applied": [], "current": current},
                        )
                        self.assertFalse(connection.in_transaction)
                        self.assertEqual(list(connection.iterdump()), before)
                        self.assertEqual(connection.total_changes, changes_before)
            finally:
                connection.close()
