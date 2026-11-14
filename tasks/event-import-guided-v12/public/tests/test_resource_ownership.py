import builtins
import io
from contextlib import redirect_stderr, redirect_stdout
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eventlog.cli import main


class CliResourceOwnership(unittest.TestCase):
    def test_already_opened_source_is_closed_when_database_cannot_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input.jsonl"
            source.write_text('{"id":"a","kind":"sale","value":1}\n')
            database = Path(tmp) / "absent-parent" / "events.db"
            opened = []
            real_open = builtins.open

            def tracked_open(*args, **kwargs):
                stream = real_open(*args, **kwargs)
                name = args[0] if args else kwargs.get("file")
                if name == str(source) or name == source:
                    opened.append(stream)
                return stream

            try:
                with patch("builtins.open", side_effect=tracked_open):
                    try:
                        main([str(database), str(source)])
                    except sqlite3.Error:
                        # This example does not prescribe database-error output.
                        pass
                # Store-first acquisition may fail before any source is opened.
                # Source-first acquisition must close the file it already owns.
                self.assertTrue(all(stream.closed for stream in opened))
            finally:
                for stream in opened:
                    stream.close()

    def test_stdin_remains_open_in_lenient_and_strict_modes(self):
        for strict in (False, True):
            with self.subTest(strict=strict):
                source = io.StringIO("bad\n")
                self.addCleanup(source.close)
                args = [":memory:", "-"] + (["--strict"] if strict else [])
                with patch("sys.stdin", source), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(main(args), 2 if strict else 0)
                self.assertFalse(source.closed)
