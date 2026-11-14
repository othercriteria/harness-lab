"""Cleanup covers interruption while acquiring a later CLI resource."""
import builtins
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eventlog.cli import main


class AcquisitionCleanup(unittest.TestCase):
    def test_acquired_connections_close_when_source_open_is_interrupted(self):
        for error_type in (KeyboardInterrupt, SystemExit):
            with self.subTest(error_type=error_type.__name__), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "events.jsonl"
                source.write_text('{"id":"a","kind":"sale","value":1}\n')
                connections = []
                connect = sqlite3.connect

                def tracked_connect(*args, **kwargs):
                    connection = connect(*args, **kwargs)
                    connections.append(connection)
                    return connection

                def interrupted(opener):
                    def opening(*args, **kwargs):
                        name = args[0] if args else kwargs.get("file")
                        if name == str(source) or name == source:
                            raise error_type("source acquisition interrupted")
                        return opener(*args, **kwargs)
                    return opening

                try:
                    with patch("sqlite3.connect", side_effect=tracked_connect), \
                         patch("builtins.open", side_effect=interrupted(builtins.open)), \
                         patch("io.open", side_effect=interrupted(io.open)):
                        try:
                            main([str(Path(tmp) / "events.db"), str(source)])
                        except (KeyboardInterrupt, SystemExit):
                            pass  # No new interruption-reporting policy.
                    # Source-first acquisition may never open a database.
                    # Alternative opening APIs are allowed but not observed.
                    for connection in connections:
                        with self.assertRaises(sqlite3.ProgrammingError):
                            connection.execute("SELECT 1")
                finally:
                    for connection in connections:
                        connection.close()
