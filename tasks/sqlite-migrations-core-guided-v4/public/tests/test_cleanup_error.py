import hashlib
import sqlite3
import unittest

from migrator.discovery import Migration
from migrator.engine import apply


class CleanupErrorExample(unittest.TestCase):
    def test_secondary_rollback_error_preserves_original_sql_error(self):
        sql = "INSERT INTO missing_table VALUES (1);"
        migration = Migration(1, "0001_bad.sql", sql,
                              hashlib.sha256(sql.encode("utf-8")).hexdigest())
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)

        def authorize(action, arg1, arg2, database, trigger):
            if action == sqlite3.SQLITE_TRANSACTION and arg1 == "ROLLBACK":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        try:
            with self.assertRaises(sqlite3.OperationalError) as caught:
                apply(connection, [migration])
            self.assertIn("no such table: missing_table", str(caught.exception))
        finally:
            # The caller removes its own restriction and cleans up; apply must
            # neither replace the primary error nor reconfigure this connection.
            connection.set_authorizer(None)
            connection.rollback()
