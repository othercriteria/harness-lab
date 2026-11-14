import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from eventlog.cli import main


class SourceOpenErrors(unittest.TestCase):
    def test_unopenable_source_is_a_clean_cli_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for source in (root / "missing.jsonl", root):
                with self.subTest(source=source):
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = main([str(root / "events.db"), str(source)])
                    self.assertEqual(code, 2)
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertTrue(stderr.getvalue().strip())
                    self.assertNotIn("Traceback (most recent call last)", stderr.getvalue())
