"""Exercise the issue packet CLI with offline GitHub responses."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import export_issue_context as exporter


class IssuePacketTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name) / "issues.json"
        self.calls = []

    def gh(self, args):
        self.calls.append(args)
        listing = args[:3] == ["gh", "issue", "list"]
        number = 11 if listing else int(args[3])
        if number == 404:
            raise subprocess.CalledProcessError(1, args)
        row = {
            "number": number,
            "state": "CLOSED",
            "labels": [{"name": "z"}, {"name": "a"}],
        }
        return json.dumps([row] if listing else row).encode()

    def export(self, *numbers):
        argv = ["export", "example/repo", str(self.output)]
        for number in numbers:
            argv.extend(("--issue", number))
        with (
            patch.object(sys, "argv", argv),
            patch.object(exporter.subprocess, "check_output", side_effect=self.gh),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            exporter.main()

    def test_selected_and_unfiltered(self):
        self.export("0" * 4500 + "7", "11", "07")
        packet = json.loads(self.output.read_text())
        self.assertCountEqual(
            [call[:4] for call in self.calls],
            [
                ["gh", "issue", "view", "7"],
                ["gh", "issue", "view", "11"],
            ],
        )
        self.assertEqual([row["number"] for row in packet["issues"]], [7, 11])
        self.assertEqual(packet["issues"][0]["labels"], ["a", "z"])
        self.assertTrue(packet["scope"].startswith("Selected issue"))
        self.output.unlink()
        self.export()
        self.assertEqual(self.calls[-1][:3], ["gh", "issue", "list"])
        self.assertEqual(json.loads(self.output.read_text())["issues"][0]["number"], 11)

    def test_reject_before_fetch(self):
        for selection in (["7", "00"], ["+7"], ["７"], [str(i) for i in range(1, 52)]):
            with self.subTest(selection=selection), self.assertRaises(SystemExit):
                self.export(*selection)
            self.assertFalse(self.output.exists())
            self.assertEqual(self.calls, [])

    def test_late_lookup_failure_creates_no_packet(self):
        with self.assertRaises((subprocess.CalledProcessError, SystemExit)):
            self.export("8", "404")
        self.assertFalse(self.output.exists())
