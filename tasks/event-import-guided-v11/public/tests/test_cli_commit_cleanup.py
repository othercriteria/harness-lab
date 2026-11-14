"""Owned CLI inputs must close even when SQLite cannot commit the import."""
import builtins
import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from eventlog.cli import main
from eventlog.store import EventStore


class CliCommitCleanup(unittest.TestCase):
    def test_owned_source_closes_after_failed_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = str(Path(tmp) / "events.db")
            source = Path(tmp) / "events.jsonl"
            source.write_text('{"id":"new","kind":"sale","value":1}\n')
            store = EventStore(database)
            store.close()
            connect = sqlite3.connect
            reader = connect(database)
            opened = []

            def no_wait_connect(*args, **kwargs):
                if len(args) > 1:
                    args = (args[0], 0, *args[2:])
                    kwargs.pop("timeout", None)
                else:
                    kwargs["timeout"] = 0
                return connect(*args, **kwargs)

            def tracked(opener):
                def opening(*args, **kwargs):
                    stream = opener(*args, **kwargs)
                    name = args[0] if args else kwargs.get("file")
                    if name == str(source) or name == source:
                        opened.append(stream)
                    return stream
                return opening

            try:
                reader.execute("BEGIN")
                reader.execute("SELECT name FROM sqlite_master").fetchall()
                with patch("sqlite3.connect", side_effect=no_wait_connect), \
                     patch("builtins.open", side_effect=tracked(builtins.open)), \
                     patch("io.open", side_effect=tracked(io.open)), \
                     redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    try:
                        main([database, str(source)])
                    except sqlite3.Error:
                        # Storage-error exit/diagnostic behavior is unspecified.
                        pass
                # Retained references let us observe explicit cleanup; do not
                # rely on reference-counting to close an abandoned owned file.
                # Other opening APIs are allowed and simply not observed here.
                self.assertTrue(all(stream.closed for stream in opened))
            finally:
                for stream in opened:
                    stream.close()
                reader.rollback()
                reader.close()
