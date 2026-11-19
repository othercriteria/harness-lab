"""The bounded read contract as seen by a tool caller."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import read_file


class BoundedReadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.file = self.root / "notes.txt"

    def read(self, start, count):
        args = {"path": "/workspace/notes.txt", "start_line": start, "max_lines": count}
        call = {"id": "read-1", "function": {"arguments": json.dumps(args)}}
        return read_file.read(self.root, read_file.action(call)["arguments"])

    def test_exact_range_and_identity_of_whole_file(self):
        for heading in ("café", "updated"):
            data = (heading + "\r\n  indented\n\nend").encode()
            self.file.write_bytes(data)
            result = self.read(2, 3)
            meta = result["file_read"]
            self.assertEqual(result["output"], "  indented\n\nend")
            self.assertEqual(
                (meta["start_line"], meta["last_returned_line"], meta["total_lines"]),
                (2, 4, 4),
            )
            self.assertFalse(meta["range_clipped"])
            self.assertEqual(meta["file_bytes"], len(data))
            self.assertEqual(meta["file_sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(self.read(1, 1)["output"], heading + "\r\n")

    def test_past_eof_and_clipped_line_have_different_metadata(self):
        self.file.write_text("x" * (read_file.MAX_OUTPUT_CHARS + 1))
        past = self.read(2, 1)
        self.assertEqual(past["output"], "")
        self.assertIsNone(past["file_read"]["last_returned_line"])
        self.assertFalse(past["truncated"])
        clipped = self.read(1, 1)
        self.assertEqual(clipped["output"], "x" * read_file.MAX_OUTPUT_CHARS)
        self.assertEqual(clipped["file_read"]["last_returned_line"], 1)
        self.assertTrue(clipped["file_read"]["partial_last_line"])
        self.assertTrue(clipped["truncated"])

    def test_malformed_arguments_rejected_before_read(self):
        for raw, error in [
            ('{"path":"notes.txt","path":"notes2.txt"}', "Duplicate JSON field"),
            ('{"path":"notes.txt","start_line":NaN}', "Nonfinite JSON constant"),
            ('{"path":"notes.txt","max_lines":false}', "Invalid max_lines"),
        ]:
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, error):
                read_file.action({"id": "read-1", "function": {"arguments": raw}})
