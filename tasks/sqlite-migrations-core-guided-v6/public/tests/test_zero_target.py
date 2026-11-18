import hashlib
import sqlite3
import unittest

from migrator.discovery import Migration
from migrator.engine import apply
from migrator.planner import plan


class ZeroTargetExample(unittest.TestCase):
    def test_zero_target_is_a_noop_before_any_migration_is_applied(self):
        sql = "CREATE TABLE future(value INTEGER);"
        migration = Migration(3, "0003_future.sql", sql,
                              hashlib.sha256(sql.encode("utf-8")).hexdigest())
        for options in ({}, {"autocommit": True}):
            for existing_ledger in (False, True):
                for migrations in ([], [migration]):
                    with self.subTest(options=options, ledger=existing_ledger,
                                      supplied=len(migrations)):
                        connection = sqlite3.connect(":memory:", **options)
                        try:
                            if existing_ledger:
                                connection.execute(
                                    "CREATE TABLE schema_migrations "
                                    "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
                                    "checksum TEXT NOT NULL)"
                                )
                                connection.commit()
                            changes_before = connection.total_changes
                            # Explicit zero selects no migrations, even when
                            # future versions are available. It is not an
                            # unknown version; an empty history permits it.
                            self.assertEqual(
                                plan(connection, migrations, target=0),
                                {"applied": [], "pending": [], "target": 0},
                            )
                            self.assertFalse(connection.in_transaction)
                            self.assertEqual(
                                apply(connection, migrations, target=0),
                                {"applied": [], "current": 0},
                            )
                            self.assertFalse(connection.in_transaction)
                            self.assertEqual(connection.total_changes, changes_before)
                            names = {row[0] for row in connection.execute(
                                "SELECT name FROM sqlite_master WHERE type='table'"
                            )}
                            self.assertEqual(
                                names, {"schema_migrations"} if existing_ledger else set()
                            )
                        finally:
                            connection.close()
