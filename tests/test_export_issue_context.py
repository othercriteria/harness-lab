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


def issue(number):
    labels = [
        name
        for name, include in (("z", number % 11 != 0), ("a", number % 3 != 0))
        if include
    ]
    return {
        "number": number,
        "state": "OPEN" if number % 2 else "CLOSED",
        "title": f"Issue {number}",
        "body": "",
        "url": f"https://github.com/example/repo/issues/{number}",
        "updatedAt": "2026-11-15T12:00:00Z",
        "labels": [{"name": name} for name in labels],
    }


class IssuePacketTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name) / "issues.json"
        self.calls = []
        self.issues = [issue(n) for n in range(66, 0, -1)]
        self.comment = {
            "id": 42,
            "user": {"login": "reviewer"},
            "body": "Use the revised acceptance criteria.",
            "html_url": "https://github.com/example/repo/issues/7#issuecomment-42",
            "updated_at": "2026-11-16T13:30:00Z",
        }

    def gh(self, args):
        self.calls.append(args)
        if args[:3] == ["gh", "issue", "list"]:
            state = args[args.index("--state") + 1]
            labels = {args[i + 1] for i, flag in enumerate(args) if flag == "--label"}
            limit = int(args[args.index("--limit") + 1])
            rows = [
                r
                for r in self.issues
                if (state == "all" or r["state"].lower() == state)
                and labels <= {label["name"] for label in r["labels"]}
            ]
            return json.dumps(rows[:limit]).encode()
        if args[:3] == ["gh", "issue", "view"]:
            for row in self.issues:
                if str(row["number"]) == args[3]:
                    return json.dumps(row).encode()
        if args == ["gh", "api", "repos/example/repo/issues/comments/42"]:
            return json.dumps(self.comment).encode()
        raise subprocess.CalledProcessError(1, args)

    def export(self, *flags):
        self.stderr = io.StringIO()
        with (
            patch.object(
                sys, "argv", ["export", "example/repo", str(self.output), *flags]
            ),
            patch.object(exporter.subprocess, "check_output", side_effect=self.gh),
            contextlib.redirect_stderr(self.stderr),
        ):
            exporter.main()
        return json.loads(self.output.read_bytes())

    def refused(self, message, *flags):
        with self.assertRaises(SystemExit):
            self.export(*flags)
        self.assertIn(message, self.stderr.getvalue())
        self.assertFalse(self.output.exists())

    def test_explicit_issue_numbers_are_normalized_and_deduplicated(self):
        packet = self.export(
            "--issue", "11", "--issue", "0" * 4500 + "7", "--issue", "07"
        )
        self.assertEqual(
            [c[:4] for c in self.calls],
            [["gh", "issue", "view", "11"], ["gh", "issue", "view", "7"]],
        )
        self.assertEqual([r["number"] for r in packet["issues"]], [7, 11])
        self.assertEqual(packet["issues"][0]["labels"], ["a", "z"])
        self.assertTrue(packet["scope"].startswith("Selected issue"))

    def test_default_requires_a_complete_snapshot(self):
        self.refused("more than 50 issues match")
        self.issues = self.issues[:50]
        packet = self.export()
        self.assertEqual(len(packet["issues"]), 50)
        self.assertEqual({r["state"] for r in packet["issues"]}, {"OPEN", "CLOSED"})
        self.assertFalse(packet["selection"]["more_matches"])
        self.assertIn("Comments and PRs excluded", packet["scope"])
        self.assertEqual(len(self.calls), 2)

    def test_filtered_listing_on_large_tracker(self):
        packet = self.export(
            "--state", "open", "--label", "a", "--label", "a", "--limit", "3"
        )
        self.assertEqual([r["number"] for r in packet["issues"]], [59, 61, 65])
        self.assertEqual(
            packet["selection"],
            {"state": "open", "labels": ["a"], "limit": 3, "more_matches": True},
        )
        self.assertIn("omitted", packet["scope"])
        self.output.unlink()
        packet = self.export("--label", "a", "--label", "z")
        self.assertEqual(len(packet["issues"]), 40)
        self.assertEqual(packet["selection"]["labels"], ["a", "z"])
        self.assertFalse(packet["selection"]["more_matches"])

    def test_reject_before_fetch(self):
        for flags in (
            ["--issue", "7", "--issue", "00"],
            ["--issue", "+7"],
            ["--issue", "７"],
            [x for n in range(1, 52) for x in ("--issue", str(n))],
            ["--limit", "0"],
            ["--limit", "51"],
            ["--issue", "7", "--state", "open"],
            ["--comment", self.comment["html_url"].replace("example/", "unrelated/")],
        ):
            with self.subTest(flags=flags), self.assertRaises(SystemExit):
                self.export(*flags)
            self.assertFalse(self.output.exists())
            self.assertEqual(self.calls, [])

    def test_explicit_pull_request_is_refused(self):
        row = self.issues[0]
        row["url"] = row["url"].replace("/issues/", "/pull/")
        self.refused("is not an issue", "--issue", str(row["number"]))

    def test_comment_count_is_bounded_before_fetch(self):
        flags = [flag for i in range(1, 52) for flag in ("--comment", str(i))]
        self.refused("at most 50 distinct comments", *flags)
        self.assertEqual(self.calls, [])

    def test_late_lookup_failure_creates_no_packet(self):
        self.refused("lookup failed for issue 404", "--issue", "8", "--issue", "404")
        self.refused(
            "lookup failed for comment 404",
            "--issue",
            "7",
            "--comment",
            "42",
            "--comment",
            "404",
        )

    def test_only_chosen_comment_is_attached_once_with_its_source(self):
        packet = self.export(
            "--state", "open", "--comment", "042", "--comment", self.comment["html_url"]
        )
        (issue7,) = [r for r in packet["issues"] if "comments" in r]
        self.assertEqual(
            (issue7["number"], issue7["url"]),
            (7, "https://github.com/example/repo/issues/7"),
        )
        self.assertEqual(
            issue7["comments"],
            [
                {
                    "id": 42,
                    "author": "reviewer",
                    "body": self.comment["body"],
                    "url": self.comment["html_url"],
                    "updatedAt": self.comment["updated_at"],
                }
            ],
        )
        self.assertEqual(len(self.calls), 2)
        self.assertIn("Only explicitly selected comments", packet["scope"])

    def test_comment_must_belong_to_the_selected_issue_and_match_its_link(self):
        self.refused("unselected issue 7", "--issue", "8", "--comment", "42")
        self.refused(
            "unselected issue 7", "--issue", "8", "--comment", self.comment["html_url"]
        )
        wrong = self.comment["html_url"].replace("/7#", "/8#")
        self.refused("does not match", "--issue", "8", "--comment", wrong)
        self.calls.clear()
        self.refused(
            "conflicting issue numbers",
            "--comment",
            wrong,
            "--comment",
            self.comment["html_url"],
        )
        self.assertEqual(self.calls, [])

    def test_byte_limit_includes_comment_utf8(self):
        self.comment["body"] = "é" * (49 * 1024)
        self.refused("exceeds 96 KiB", "--issue", "7", "--comment", "42")

    def test_existing_output_survives_even_a_successful_lookup(self):
        self.output.write_bytes(b"prior packet")
        with self.assertRaises(SystemExit):
            self.export("--issue", "7", "--comment", "42")
        self.assertIn("already exists", self.stderr.getvalue())
        self.assertEqual(self.output.read_bytes(), b"prior packet")
