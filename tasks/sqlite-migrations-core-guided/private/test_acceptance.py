import contextlib
import dataclasses
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from migrator.cli import main
from migrator.discovery import Migration, discover, validate_migrations
from migrator.engine import apply
from migrator.planner import plan


def migration(version, sql, slug="change"):
    return Migration(
        version,
        f"{version:04d}_{slug}.sql",
        sql,
        hashlib.sha256(sql.encode()).hexdigest(),
    )


class Acceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "sql"
        self.directory.mkdir()
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)

    def write(self, item):
        (self.directory / item.name).write_bytes(item.sql.encode())

    def cli(self, *options):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main([str(self.directory), str(self.root / "db.sqlite"), *options])
        return status, stdout.getvalue(), stderr.getvalue()

    def tables(self):
        return [
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]

    def test_cli_closes_owned_connections(self):
        self.write(migration(1, "SELECT 1;"))
        connect = sqlite3.connect
        for label, options, expected_status in (
            ("dry_missing", ("--dry-run",), 0),
            ("success", (), 0),
            ("dry_existing", ("--dry-run",), 0),
            ("sql_failure", (), 2),
        ):
            with self.subTest(case=label):
                if label == "sql_failure":
                    self.write(migration(2, "SELECT * FROM missing_table;"))
                owned = []

                def tracked_connect(*args, **kwargs):
                    connection = connect(*args, **kwargs)
                    owned.append(connection)
                    self.addCleanup(connection.close)
                    return connection

                # Retain real handles to observe explicit closure, without
                # changing their behavior or depending on garbage collection.
                with patch.object(sqlite3, "connect", tracked_connect):
                    status, _, _ = self.cli(*options)
                self.assertEqual(status, expected_status)
                self.assertTrue(owned)
                for connection in owned:
                    with self.assertRaises(sqlite3.ProgrammingError):
                        connection.execute("SELECT 1")

    def test_discovery_preserves_bytes_and_orders_gaps(self):
        items = [
            migration(9, "-- café\r\nCREATE TABLE later (x);\r\n"),
            migration(2, "SELECT 'é';\n"),
        ]
        for item in items:
            self.write(item)
        (self.directory / "notes.txt").write_text("ignored")
        (self.directory / "nested").mkdir()
        (self.directory / "nested/0001_hidden.sql").write_text("SELECT 1;")
        self.assertEqual(discover(self.directory), list(reversed(items)))

    def test_discovery_rejects_invalid_entries(self):
        for name, content in [
            ("0000_zero.sql", b"SELECT 1;"),
            ("1_short.sql", b"SELECT 1;"),
            ("0001_UP.sql", b"SELECT 1;"),
            ("0001_ok.sql", b"\xff"),
            ("0001_ok.sql", b" \n"),
            ("0001_ok.sql", b"SELECT '\x00';"),
        ]:
            with self.subTest(name=name, content=content):
                path = self.directory / name
                path.write_bytes(content)
                with self.assertRaises((ValueError, OSError)):
                    discover(self.directory)
                path.unlink()
        self.write(migration(1, "SELECT 1;", "one"))
        self.write(migration(1, "SELECT 2;", "two"))
        with self.assertRaises(ValueError):
            discover(self.directory)
        for path in self.directory.iterdir():
            path.unlink()
        path = self.directory / "0001_link.sql"
        path.symlink_to(self.root / "missing")
        with self.assertRaises((ValueError, OSError)):
            discover(self.directory)
        path.unlink()
        path.mkdir()
        with self.assertRaises((ValueError, OSError)):
            discover(self.directory)
        link = self.root / "link"
        link.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            discover(link)

    def test_validation_rejects_bad_objects_without_mutation(self):
        first, later = migration(1, "SELECT 1;"), migration(3, "SELECT 3;")
        original = [later, first]
        result = validate_migrations(original)
        self.assertEqual(result, [first, later])
        self.assertEqual(original, [later, first])
        self.assertIsNot(result, original)
        bad = [
            dataclasses.replace(first, version=True),
            dataclasses.replace(first, name="0002_wrong.sql"),
            dataclasses.replace(first, checksum="0" * 64),
            dataclasses.replace(first, sql=""),
            dataclasses.replace(first, sql="\x00"),
            object(),
        ]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(ValueError):
                validate_migrations([item])
        for items in [(first,), [first, first], None]:
            with self.assertRaises(ValueError):
                validate_migrations(items)

    def test_validation_rejects_terminal_newline_in_name(self):
        valid = migration(1, "SELECT 1;")
        self.assertEqual(validate_migrations([valid]), [valid])
        invalid = dataclasses.replace(valid, name=valid.name + "\n")
        with self.assertRaises(ValueError):
            validate_migrations([invalid])

    def test_plan_is_read_only_even_inside_caller_transaction(self):
        item = migration(1, "CREATE TABLE changed(x);")
        self.assertEqual(
            plan(self.connection, [item]), {"applied": [], "pending": [1], "target": 1}
        )
        self.assertEqual(self.tables(), [])
        self.assertFalse(self.connection.in_transaction)
        self.connection.execute("CREATE TABLE keep(x)")
        self.connection.execute("INSERT INTO keep VALUES (7)")
        self.assertTrue(self.connection.in_transaction)
        plan(self.connection, [item])
        self.assertTrue(self.connection.in_transaction)
        self.assertEqual(self.tables(), ["keep"])
        self.assertEqual(
            self.connection.execute("SELECT x FROM keep").fetchall(), [(7,)]
        )

    def test_targets_and_noop_do_not_create_ledger(self):
        items = [migration(1, "SELECT 1;"), migration(3, "SELECT 3;")]
        self.assertEqual(
            plan(self.connection, items, 1),
            {"applied": [], "pending": [1], "target": 1},
        )
        for target in [True, False, -1, 2, 1.0, "1"]:
            with self.subTest(target=target), self.assertRaises(ValueError):
                plan(self.connection, items, target)
        self.assertEqual(
            apply(self.connection, items, 0), {"applied": [], "current": 0}
        )
        self.assertEqual(apply(self.connection, []), {"applied": [], "current": 0})
        self.assertEqual(self.tables(), [])

    def test_apply_resume_and_idempotency(self):
        items = [
            migration(1, "CREATE TABLE values_(x); INSERT INTO values_ VALUES (1);"),
            migration(3, "INSERT INTO values_ VALUES (3);"),
        ]
        self.assertEqual(
            apply(self.connection, items, 1), {"applied": [1], "current": 1}
        )
        self.assertEqual(
            plan(self.connection, items), {"applied": [1], "pending": [3], "target": 3}
        )
        self.assertEqual(apply(self.connection, items), {"applied": [3], "current": 3})
        self.assertEqual(apply(self.connection, items), {"applied": [], "current": 3})
        self.assertEqual(
            self.connection.execute("SELECT x FROM values_ ORDER BY x").fetchall(),
            [(1,), (3,)],
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT version,name,checksum FROM schema_migrations ORDER BY version"
            ).fetchall(),
            [(m.version, m.name, m.checksum) for m in items],
        )
        self.assertFalse(self.connection.in_transaction)
        with self.assertRaises(ValueError):
            plan(self.connection, items, 1)

    def test_history_drift_and_unknown_versions(self):
        first = migration(1, "CREATE TABLE original(x);")
        apply(self.connection, [first])
        for items in [
            [],
            [migration(1, "SELECT 1;")],
            [dataclasses.replace(first, name="0001_renamed.sql")],
            [migration(2, "SELECT 2;")],
        ]:
            with self.subTest(items=items), self.assertRaises(ValueError):
                plan(self.connection, items)
        self.assertEqual(self.tables(), ["original", "schema_migrations"])
        with self.assertRaises(ValueError):
            plan(
                self.connection,
                [first, dataclasses.replace(migration(3, "SELECT 3;"), checksum="bad")],
                1,
            )

    def test_skipped_prefix_is_invalid_but_numeric_gaps_are_valid(self):
        first, later = migration(1, "SELECT 1;"), migration(3, "SELECT 3;")
        apply(self.connection, [later])
        with self.assertRaises(ValueError):
            plan(self.connection, [first, later])
        self.assertEqual(
            plan(self.connection, [later]), {"applied": [3], "pending": [], "target": 3}
        )

    def test_failed_batch_rolls_back_ddl_data_and_new_ledger(self):
        self.connection.execute("CREATE TABLE keep(x)")
        self.connection.execute("INSERT INTO keep VALUES (8)")
        self.connection.commit()
        items = [
            migration(1, "CREATE TABLE new_table(x); INSERT INTO keep VALUES (9);"),
            migration(2, "INSERT INTO absent VALUES (1);"),
        ]
        with self.assertRaises(sqlite3.Error):
            apply(self.connection, items)
        self.assertEqual(self.tables(), ["keep"])
        self.assertEqual(
            self.connection.execute("SELECT x FROM keep").fetchall(), [(8,)]
        )
        self.assertFalse(self.connection.in_transaction)

    def test_failed_resume_preserves_previous_commits(self):
        first = migration(1, "CREATE TABLE keep(x); INSERT INTO keep VALUES (1);")
        apply(self.connection, [first])
        items = [
            first,
            migration(2, "INSERT INTO keep VALUES (2); CREATE TABLE transient(x);"),
            migration(3, "SELECT missing_column FROM keep;"),
        ]
        with self.assertRaises(sqlite3.Error):
            apply(self.connection, items)
        self.assertEqual(self.tables(), ["keep", "schema_migrations"])
        self.assertEqual(
            self.connection.execute("SELECT x FROM keep").fetchall(), [(1,)]
        )
        self.assertEqual(plan(self.connection, items)["applied"], [1])
        self.assertFalse(self.connection.in_transaction)

    def test_commit_failure_rolls_back_batch_and_preserves_prior_data(self):
        for autocommit in (sqlite3.LEGACY_TRANSACTION_CONTROL, True):
            with self.subTest(autocommit=autocommit):
                connection = sqlite3.connect(":memory:", autocommit=autocommit)
                self.addCleanup(connection.close)
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("CREATE TABLE keep(x)")
                connection.execute("INSERT INTO keep VALUES (7)")
                if connection.in_transaction:
                    connection.execute("COMMIT")
                settings = (connection.autocommit, connection.isolation_level)
                # A real deferred constraint succeeds during execution and
                # fails at COMMIT. No transaction-control or PRAGMA appears
                # inside the migration script, and no connection is mocked.
                item = migration(
                    1,
                    "CREATE TABLE parent(id INTEGER PRIMARY KEY); "
                    "CREATE TABLE child(parent_id INTEGER REFERENCES parent(id) "
                    "DEFERRABLE INITIALLY DEFERRED); "
                    "INSERT INTO keep VALUES (8); "
                    "INSERT INTO child VALUES (99);",
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    apply(connection, [item])
                self.assertFalse(connection.in_transaction)
                self.assertEqual(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                    ).fetchall(),
                    [("keep",)],
                )
                self.assertEqual(
                    connection.execute("SELECT x FROM keep").fetchall(), [(7,)]
                )
                self.assertEqual(
                    (connection.autocommit, connection.isolation_level), settings
                )
                self.assertEqual(
                    connection.execute("PRAGMA foreign_keys").fetchone(), (1,)
                )

    def test_caller_transaction_is_preserved(self):
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("CREATE TABLE keep(x)")
        self.connection.execute("INSERT INTO keep VALUES (7)")
        with self.assertRaises(ValueError):
            apply(self.connection, [migration(1, "CREATE TABLE changed(x);")])
        self.assertTrue(self.connection.in_transaction)
        self.assertEqual(
            self.connection.execute("SELECT x FROM keep").fetchall(), [(7,)]
        )
        self.assertEqual(
            self.connection.execute("PRAGMA foreign_keys").fetchone(), (1,)
        )
        self.assertEqual(self.tables(), ["keep"])

    def test_triggers_and_quoted_semicolons(self):
        items = [
            migration(
                1,
                "CREATE TABLE source(x); CREATE TABLE log(x); -- comment ;\nCREATE TRIGGER record AFTER INSERT ON source BEGIN INSERT INTO log VALUES (new.x); INSERT INTO log VALUES ('semi;colon'); END;",
            ),
            migration(
                2,
                "/* before ; */ INSERT INTO source VALUES ('value;two'); -- trailing\n",
            ),
        ]
        apply(self.connection, items)
        self.assertEqual(
            self.connection.execute("SELECT x FROM log").fetchall(),
            [("value;two",), ("semi;colon",)],
        )

    def test_invalid_selected_sql_rolls_back_and_future_sql_is_not_executed(self):
        first = migration(1, "CREATE TABLE keep(x);")
        for text in ["-- only a comment\n", "INSERT INTO keep VALUES (2)"]:
            with self.subTest(text=text):
                items = [first, migration(2, text)]
                with self.assertRaises(ValueError):
                    apply(self.connection, items)
                self.assertEqual(self.tables(), [])
                self.assertFalse(self.connection.in_transaction)
        items = [first, migration(2, "not valid sql;")]
        self.assertEqual(apply(self.connection, items, 1)["applied"], [1])
        self.assertEqual(items, [first, migration(2, "not valid sql;")])

    def test_cli_dry_run_does_not_create_or_modify_database(self):
        self.write(migration(1, "not valid sql;"))
        status, stdout, stderr = self.cli("--dry-run")
        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual(
            json.loads(stdout), {"applied": [], "pending": [1], "target": 1}
        )
        database = self.root / "db.sqlite"
        self.assertFalse(database.exists())
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE keep(x)")
        before = database.read_bytes()
        self.assertEqual(self.cli("--dry-run")[0], 0)
        self.assertEqual(database.read_bytes(), before)

    def test_cli_commits_before_success_and_failure_preserves_database(self):
        self.write(migration(1, "CREATE TABLE keep(x); INSERT INTO keep VALUES (1);"))
        status, stdout, stderr = self.cli()
        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual(json.loads(stdout), {"applied": [1], "current": 1})
        self.write(migration(2, "INSERT INTO keep VALUES (2);"))
        self.write(migration(3, "INSERT INTO absent VALUES (3);"))
        status, stdout, stderr = self.cli()
        self.assertEqual((status, stdout), (2, ""))
        self.assertTrue(stderr.strip())
        self.assertNotIn("Traceback", stderr)
        with sqlite3.connect(self.root / "db.sqlite") as connection:
            self.assertEqual(
                connection.execute("SELECT x FROM keep").fetchall(), [(1,)]
            )
            self.assertEqual(
                connection.execute("SELECT version FROM schema_migrations").fetchall(),
                [(1,)],
            )
        status, stdout, stderr = self.cli("--target", "9999")
        self.assertEqual((status, stdout), (2, ""))
        self.assertTrue(stderr.strip())

    def test_autocommit_true_success_commits_and_preserves_configuration(self):
        database = self.root / "autocommit-success.sqlite"
        connection = sqlite3.connect(
            database, autocommit=True, isolation_level="IMMEDIATE"
        )
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            settings = (connection.autocommit, connection.isolation_level)
            item = migration(
                1, "CREATE TABLE durable(x); INSERT INTO durable VALUES (7);"
            )
            self.assertEqual(apply(connection, [item]), {"applied": [1], "current": 1})
            self.assertFalse(connection.in_transaction)
            self.assertEqual(
                (connection.autocommit, connection.isolation_level), settings
            )
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone(), (1,))
            self.assertEqual(apply(connection, [item]), {"applied": [], "current": 1})
            self.assertFalse(connection.in_transaction)
        finally:
            connection.close()
        with sqlite3.connect(database) as reopened:
            self.assertEqual(
                reopened.execute("SELECT x FROM durable").fetchall(), [(7,)]
            )
            self.assertEqual(
                reopened.execute("SELECT version FROM schema_migrations").fetchall(),
                [(1,)],
            )

    def test_autocommit_true_failure_rolls_back_and_preserves_configuration(self):
        connection = sqlite3.connect(
            ":memory:", autocommit=True, isolation_level="IMMEDIATE"
        )
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("CREATE TABLE keep(x)")
            connection.execute("INSERT INTO keep VALUES (8)")
            settings = (connection.autocommit, connection.isolation_level)
            items = [
                migration(1, "CREATE TABLE transient(x); INSERT INTO keep VALUES (9);"),
                migration(2, "INSERT INTO absent VALUES (1);"),
            ]
            with self.assertRaises(sqlite3.Error):
                apply(connection, items)
            self.assertFalse(connection.in_transaction)
            self.assertEqual(
                (connection.autocommit, connection.isolation_level), settings
            )
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone(), (1,))
            self.assertEqual(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall(),
                [("keep",)],
            )
            self.assertEqual(
                connection.execute("SELECT x FROM keep").fetchall(), [(8,)]
            )
        finally:
            connection.close()

    def test_apply_rejects_nonlist_containers_without_sql(self):
        item = migration(1, "CREATE TABLE changed(x);")
        for items in ((item,), iter([item]), {1: item}, None, "", ()): 
            with self.subTest(kind=type(items).__name__):
                statements = []
                self.connection.set_trace_callback(statements.append)
                try:
                    with self.assertRaises(ValueError):
                        apply(self.connection, items)
                finally:
                    self.connection.set_trace_callback(None)
                self.assertEqual(statements, [])
                self.assertFalse(self.connection.in_transaction)
                self.assertEqual(self.tables(), [])

    def test_apply_invalid_container_preserves_caller_transaction(self):
        self.connection.execute("CREATE TABLE keep(x)")
        self.connection.execute("INSERT INTO keep VALUES (7)")
        item = migration(1, "CREATE TABLE changed(x);")
        for items in ((item,), iter([item]), {1: item}, None):
            with self.subTest(kind=type(items).__name__):
                statements = []
                self.connection.set_trace_callback(statements.append)
                try:
                    with self.assertRaises(ValueError):
                        apply(self.connection, items)
                finally:
                    self.connection.set_trace_callback(None)
                self.assertEqual(statements, [])
                self.assertTrue(self.connection.in_transaction)
                self.assertEqual(self.tables(), ["keep"])
                self.assertEqual(self.connection.execute("SELECT x FROM keep").fetchall(), [(7,)])
