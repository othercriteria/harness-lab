"""Replay the portable reader on the recorded packet and two damaged copies."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from examples.evidence_files import check_files

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
PACKET = EXAMPLES / "reviewing-worker-output"


class PortableEvidenceTests(unittest.TestCase):
    def test_reader_from_another_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "packet"
            shutil.copytree(PACKET, copy)
            manifest = copy / "files.json"
            names = sorted(json.loads(manifest.read_text()))
            self.assertEqual(check_files(manifest), [(name, "ok") for name in names])

            def report():
                result = subprocess.run(
                    [
                        sys.executable,
                        str(EXAMPLES / "check_evidence.py"),
                        "packet/files.json",
                    ],
                    cwd=directory,
                    capture_output=True,
                )
                self.assertEqual(result.stderr, b"")
                return result.returncode, json.loads(result.stdout)

            self.assertEqual(report(), (0, {"ok": names, "changed": [], "missing": []}))
            damaged, absent = names[:2]
            (copy / damaged).write_bytes(b"\xff\r\n")
            (copy / absent).unlink()
            self.assertEqual(
                report(),
                (1, {"ok": names[2:], "changed": [damaged], "missing": [absent]}),
            )
