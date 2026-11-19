"""Portable unittest coverage for the check receipts in scripts/run_checks.py.

These tests exercise the receipt logic directly: real before/after tree
identities are captured from a temporary workspace, ``save`` is called with
them, and the returned summary and the persisted /checks record are asserted.
No shell, Git subprocess, model call, or real check execution is involved.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_checks  # noqa: E402

MARKER = "\n[... check output middle omitted ...]\n"


def make_output(text, returncode, limit=12000):
    """Build the output payload the executor hands to ``save``."""
    clipped, window = run_checks.bounded_output(text, limit)
    return {
        "output": clipped,
        "truncated": len(clipped) != len(text),
        "returncode": returncode,
        "exception_info": "",
        "output_window": window,
    }


class CheckReceiptTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.workspace = Path(self._temp.name) / "workspace"
        self.checks = Path(self._temp.name) / "checks"
        self.workspace.mkdir()
        self.checks.mkdir()

    def write(self, relative, content):
        path = self.workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def save_receipt(self, number, cwd, before, after, output):
        arguments = {"command": "python -m unittest discover -s tests", "cwd": cwd}
        summary = run_checks.save(self.checks, number, arguments, before, after, output)
        record = json.loads(
            (self.checks / f"c{number:04d}.json").read_text(encoding="utf-8")
        )
        return summary, record

    def assert_summary_matches_record(self, summary, record):
        for key in (
            "id",
            "record_path",
            "cwd",
            "before",
            "after",
            "files_unchanged_by_command",
            "returncode",
            "exception_info",
        ):
            with self.subTest(field=key):
                self.assertEqual(summary[key], record[key])

    def test_unchanged_files_compare_true(self):
        self.write("app/main.txt", "alpha\n")
        self.write("app/nested/notes.txt", "beta\n")
        before = run_checks.identity(str(self.workspace), "app")
        after = run_checks.identity(str(self.workspace), "app")
        self.assertEqual(before["status"], "captured")
        self.assertEqual(after["status"], "captured")
        self.assertEqual(before["tree_sha256"], after["tree_sha256"])

        output = make_output("OK (3 tests)\n", 0)
        summary, record = self.save_receipt(7, "app", before, after, output)

        self.assertIs(summary["files_unchanged_by_command"], True)
        self.assertEqual(summary["id"], "c0007")
        self.assertEqual(summary["record_path"], "/checks/c0007.json")
        self.assertEqual(summary["cwd"], "app")
        # The recorded exit status is the command's status, not a file verdict.
        self.assertEqual(summary["returncode"], 0)
        self.assert_summary_matches_record(summary, record)
        self.assertEqual(record["command"], "python -m unittest discover -s tests")
        self.assertEqual(record["output"], "OK (3 tests)\n")
        self.assertIs(record["truncated"], False)
        self.assertEqual(
            record["output_window"],
            {"mode": "complete_capture", "captured_characters": len("OK (3 tests)\n")},
        )

    def test_same_size_edit_in_selected_directory_compares_false(self):
        self.write("app/data.txt", "abcdef\n")
        before = run_checks.identity(str(self.workspace), "app")
        self.write("app/data.txt", "ghijkl\n")  # same size, different content
        after = run_checks.identity(str(self.workspace), "app")
        self.assertEqual(before["status"], "captured")
        self.assertEqual(after["status"], "captured")
        self.assertNotEqual(before["tree_sha256"], after["tree_sha256"])

        for rc, text in [(0, "OK"), (1, "FAILED")]:
            with self.subTest(returncode=rc):
                summary, record = self.save_receipt(
                    8 + rc, "app", before, after, make_output(text, rc)
                )
                self.assertIs(summary["files_unchanged_by_command"], False)
                self.assertEqual(summary["returncode"], rc)
                self.assert_summary_matches_record(summary, record)

    def test_unavailable_identity_comparison_is_none(self):
        self.write("app/main.txt", "alpha\n")
        before = run_checks.identity(str(self.workspace), "missing")
        after = run_checks.identity(str(self.workspace), "missing")
        self.assertEqual(before, {"status": "unavailable"})
        self.assertEqual(after, {"status": "unavailable"})

        output = make_output("command could not start\n", 127)
        summary, record = self.save_receipt(9, "missing", before, after, output)

        self.assertIsNone(summary["files_unchanged_by_command"])
        self.assertIsNone(record["files_unchanged_by_command"])
        self.assertEqual(summary["returncode"], 127)
        self.assert_summary_matches_record(summary, record)

    def test_selected_tree_ignores_edits_outside_directory(self):
        self.write("app/main.txt", "alpha\n")
        self.write("outside/other.txt", "gamma\n")
        before = run_checks.identity(str(self.workspace), "app")
        # Edits outside the selected cwd must not move the selected tree hash.
        self.write("outside/other.txt", "delta\n")
        self.write("root.txt", "epsilon\n")
        after = run_checks.identity(str(self.workspace), "app")
        self.assertEqual(before["status"], "captured")
        self.assertEqual(after["status"], "captured")
        self.assertEqual(before["tree_sha256"], after["tree_sha256"])

        output = make_output("OK\n", 0)
        summary, record = self.save_receipt(10, "app", before, after, output)

        self.assertIs(summary["files_unchanged_by_command"], True)
        self.assertIs(record["files_unchanged_by_command"], True)
        self.assert_summary_matches_record(summary, record)

    def test_bounded_output_keeps_both_ends(self):
        head = "FAIL: test_widget (test_app) "
        filler = " " + "x" * 400 + " "
        tail = "AssertionError: expected 1 == 2"
        text = head + filler + tail
        limit = 200
        self.assertGreater(len(text), limit)

        clipped, window = run_checks.bounded_output(text, limit)
        head_chars = window["head_characters"]
        tail_chars = window["tail_characters"]
        self.assertLess(len(head), head_chars)
        self.assertLess(len(tail), tail_chars)

        # Both ends of the diagnostic survive: the failing test name up front
        # and the assertion failure at the tail remain visible.
        self.assertEqual(clipped, text[:head_chars] + MARKER + text[-tail_chars:])
        self.assertTrue(clipped.startswith(head))
        self.assertTrue(clipped.endswith(tail))
        self.assertIn(MARKER, clipped)
        self.assertEqual(len(clipped), limit)
        self.assertEqual(window["mode"], "head_tail")
        self.assertEqual(window["captured_characters"], len(text))
        self.assertEqual(
            window["head_characters"] + window["tail_characters"],
            limit - len(MARKER),
        )
        self.assertEqual(
            window["omitted_characters"], len(text) - (limit - len(MARKER))
        )

        # Short diagnostics pass through untouched.
        small = "OK (3 tests)\n"
        self.assertEqual(
            run_checks.bounded_output(small, limit),
            (small, {"mode": "complete_capture", "captured_characters": len(small)}),
        )


if __name__ == "__main__":
    unittest.main()
