import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from eventlog.cli import main
from eventlog.importer import ImportFailure, import_events
from eventlog.model import normalize_event
from eventlog.store import EventStore


def line(identifier="a", kind="sale", value=1):
    return json.dumps({"id": identifier, "kind": kind, "value": value}) + "\n"


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.store = EventStore(":memory:")
        self.addCleanup(self.store.close)

    def test_normalization_no_mutation(self):
        original = {"id": "  A  ", "kind": " Sale ", "value": 0, "extra": [1]}
        self.assertEqual(
            normalize_event(original), {"id": "A", "kind": "sale", "value": 0}
        )
        self.assertEqual(original["id"], "  A  ")
        self.assertEqual(original["extra"], [1])

    def test_validation_and_physical_lines(self):
        lines = [
            "\n",
            "bad\n",
            "[]\n",
            line(" "),
            line(kind=" "),
            line(value=True),
            line(value=1.2),
            "{}\n",
            line("ok"),
        ]
        r = import_events(iter(lines), self.store)
        self.assertEqual(set(r), {"inserted", "duplicates", "invalid", "errors"})
        self.assertEqual((r["inserted"], r["duplicates"], r["invalid"]), (1, 0, 7))
        self.assertEqual([e["line"] for e in r["errors"]], list(range(2, 9)))
        self.assertTrue(
            all(
                set(e) == {"line", "message"}
                and isinstance(e["message"], str)
                and e["message"]
                for e in r["errors"]
            )
        )

    def test_duplicates_are_validated_and_first_wins(self):
        r = import_events(
            [line(" a ", value=3), line("a", value=8), line("a", value=False)],
            self.store,
        )
        self.assertEqual((r["inserted"], r["duplicates"], r["invalid"]), (1, 1, 1))
        self.assertEqual(self.store.get("a"), {"id": "a", "kind": "sale", "value": 3})

    def test_reopen_and_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "log.db")
            one = EventStore(path)
            try:
                import_events([line()], one)
            finally:
                one.close()
            two = EventStore(path)
            try:
                r = import_events([line(), line("b")], two)
                self.assertEqual(
                    (r["inserted"], r["duplicates"], two.count()), (1, 1, 2)
                )
            finally:
                two.close()

    def test_strict_rollback_prior_commit_survives(self):
        import_events([line("old")], self.store)
        with self.assertRaises(ImportFailure) as ctx:
            import_events([line("new"), "\n", "broken"], self.store, strict=True)
        self.assertEqual(ctx.exception.line, 3)
        self.assertTrue(ctx.exception.message)
        self.assertEqual(self.store.count(), 1)
        self.assertIsNone(self.store.get("new"))
        self.assertEqual(import_events([line("later")], self.store)["inserted"], 1)

    def test_streaming_iterator_failure_rolls_back(self):
        class Broken:
            def __iter__(self):
                yield line("new")
                raise RuntimeError("upstream failed")

        with self.assertRaisesRegex(RuntimeError, "upstream failed"):
            import_events(Broken(), self.store)
        self.assertEqual(self.store.count(), 0)
        self.assertEqual(import_events([line("later")], self.store)["inserted"], 1)

    def test_store_error_is_not_invalid_data(self):
        original = self.store.insert

        def insert(event):
            if event["id"] == "b":
                raise ValueError("storage failure")
            return original(event)

        with patch.object(self.store, "insert", side_effect=insert):
            with self.assertRaisesRegex(ValueError, "storage failure"):
                import_events([line("a"), line("b")], self.store)
        self.assertEqual(self.store.count(), 0)

    def test_single_pass_incremental_and_no_close(self):
        owner = self

        class Single:
            closed = False
            started = False

            def close(self):
                self.closed = True

            def __iter__(self):
                if self.started:
                    raise AssertionError("iterated twice")
                self.started = True
                yield line("one")
                owner.assertIsNotNone(
                    owner.store.get("one"), "must process before requesting next line"
                )
                yield line("two")

        lines = Single()
        self.assertEqual(import_events(lines, self.store)["inserted"], 2)
        self.assertFalse(lines.closed)
        self.assertEqual(self.store.count(), 2)

    def test_cli_stdin_and_strict_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "log.db")
            out, err = io.StringIO(), io.StringIO()
            source = io.StringIO(line("a") + "bad\n")
            with patch("sys.stdin", source), redirect_stdout(out), redirect_stderr(err):
                rc = main([path, "-", "--strict"])
            self.assertEqual(rc, 2)
            self.assertEqual(out.getvalue(), "")
            data = json.loads(err.getvalue())
            self.assertEqual(set(data), {"line", "message"})
            self.assertEqual(data["line"], 2)
            self.assertTrue(data["message"])
            self.assertFalse(source.closed)
            store = EventStore(path)
            try:
                self.assertEqual(store.count(), 0)
            finally:
                store.close()
            out, err = io.StringIO(), io.StringIO()
            with (
                patch("sys.stdin", io.StringIO(line("b") + "bad\n")),
                redirect_stdout(out),
                redirect_stderr(err),
            ):
                rc = main([path, "-"])
            self.assertEqual(rc, 0)
            self.assertEqual(err.getvalue(), "")
            self.assertEqual(json.loads(out.getvalue())["invalid"], 1)

    def test_cli_missing_file_is_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = main([str(Path(tmp) / "log.db"), str(Path(tmp) / "missing")])
            self.assertEqual(rc, 2)
            self.assertEqual(out.getvalue(), "")
            self.assertTrue(err.getvalue().strip())
            self.assertNotIn("Traceback", err.getvalue())
