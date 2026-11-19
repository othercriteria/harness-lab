"""Standard-library tests for resumption_digest.build.

Uses temporary real start/current workspaces and the actual snapshot/identity
logic from run_checks; no shell commands, services, or Git are involved.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "scripts"),
)

from json_text import encoded
from resumption_digest import MAX_BYTES, MAX_FILES, build
from run_checks import identity, snapshot

# "inner original\n" and "inner modified\n" are the same byte length, so a
# same-size edit keeps entries/byte counts identical while changing content.
INNER_ORIGINAL = b"inner original\n"
INNER_MODIFIED = b"inner modified\n"
OUTER_ORIGINAL = b"outer original\n"
OUTER_MODIFIED = b"outer modified\n"


class History:
    """Minimal stand-in for the recorded-check history that build() reads."""

    def __init__(self):
        self.records = {}


def write(path, data):
    with open(path, "wb") as stream:
        stream.write(data)


def record(observation_id, check_id, cwd, after):
    """Shape of a recorded run_checks entry as consumed by build()."""
    return {
        "id": observation_id,
        "command": "python -B -S -m unittest discover -s tests",
        "returncode": 0,
        "originally_truncated": False,
        "check_record": {"id": check_id, "cwd": cwd, "after": after},
    }


class BuildTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.start = os.path.join(tmp.name, "start")
        self.current = os.path.join(tmp.name, "current")
        for root in (self.start, self.current):
            os.makedirs(os.path.join(root, "checked"))
            write(os.path.join(root, "outer.txt"), OUTER_ORIGINAL)
            write(os.path.join(root, "checked", "inner.txt"), INNER_ORIGINAL)
        self.history = History()
        # A passing check recorded at task start, scoped to the subdirectory:
        # its after-snapshot is the real identity of that subdirectory then.
        self.after = snapshot(self.current, "checked")
        self.history.records["o0001"] = record("o0001", "c0001", "checked", self.after)

    def digest(self):
        return build(self.start, self.current, self.history)

    def check_entry(self, digest):
        self.assertEqual(len(digest["recent_checks"]), 1)
        self.assertEqual(digest["recent_checks_omitted"], 0)
        return digest["recent_checks"][0]

    def test_passing_check_scoped_to_subdirectory(self):
        digest = self.digest()
        entry = self.check_entry(digest)
        self.assertEqual(
            (entry["observation_id"], entry["check_id"]), ("o0001", "c0001")
        )
        self.assertEqual(entry["cwd"], "checked")
        self.assertEqual(entry["returncode"], 0)
        self.assertEqual(entry["output_truncated"], False)
        self.assertIs(entry["current_files_match_after_check"], True)
        # No .git in the temporary workspaces: the Git comparison is
        # unavailable, not a measured mismatch.
        self.assertIsNone(entry["current_head_matches_observed_after_check"])
        # No task-start drift yet, and the observable output stays in bound.
        self.assertEqual(digest["file_comparison"], "captured")
        self.assertEqual(digest["changed_files"], [])
        self.assertEqual(digest["changed_files_total"], 0)
        self.assertEqual(digest["changed_files_omitted"], 0)
        self.assertLessEqual(len(encoded(digest).encode()), MAX_BYTES)

    def test_outside_edit_keeps_check_matching(self):
        # Editing outside the checked directory changes the task-start delta,
        # but the subdirectory identity is untouched, so the check still
        # matches.
        write(os.path.join(self.current, "outer.txt"), OUTER_MODIFIED)
        digest = self.digest()
        entry = self.check_entry(digest)
        self.assertIs(entry["current_files_match_after_check"], True)
        self.assertEqual(
            digest["changed_files"],
            [
                {
                    "path": "outer.txt",
                    "path_clipped": False,
                    "change": "modified_from_start",
                }
            ],
        )
        self.assertEqual(digest["changed_files_total"], 1)
        # The whole-workspace tree moved, while the check's subdirectory did
        # not.
        self.assertNotEqual(
            digest["current_tree_sha256"], snapshot(self.start, ".")["tree_sha256"]
        )
        self.assertEqual(
            identity(self.current, "checked")["tree_sha256"],
            self.after["tree_sha256"],
        )
        self.assertLessEqual(len(encoded(digest).encode()), MAX_BYTES)

    def test_same_size_edit_inside_stales_check(self):
        # A same-size edit inside the checked directory leaves entries and
        # byte counts identical, but the content hash moves, so the same
        # passing check is now a measured mismatch: False, not None.
        self.assertEqual(len(INNER_ORIGINAL), len(INNER_MODIFIED))
        write(os.path.join(self.current, "checked", "inner.txt"), INNER_MODIFIED)
        now = identity(self.current, "checked")
        self.assertEqual(now["status"], "captured")
        self.assertEqual(now["entries"], self.after["entries"])
        self.assertEqual(now["bytes"], self.after["bytes"])
        self.assertNotEqual(now["tree_sha256"], self.after["tree_sha256"])
        digest = self.digest()
        entry = self.check_entry(digest)
        self.assertIs(entry["current_files_match_after_check"], False)
        self.assertIsNone(entry["current_head_matches_observed_after_check"])

    def test_unavailable_identity_is_none_not_false(self):
        # Removing the checked directory makes the current identity
        # unavailable; the same record then reports None, which is distinct
        # from the measured mismatch False above.
        os.remove(os.path.join(self.current, "checked", "inner.txt"))
        os.rmdir(os.path.join(self.current, "checked"))
        self.assertEqual(identity(self.current, "checked"), {"status": "unavailable"})
        digest = self.digest()
        entry = self.check_entry(digest)
        self.assertIsNone(entry["current_files_match_after_check"])
        # The task-start delta reports the removal explicitly.
        self.assertIn(
            {
                "path": "checked/inner.txt",
                "path_clipped": False,
                "change": "removed_since_start",
            },
            digest["changed_files"],
        )
        self.assertLessEqual(len(encoded(digest).encode()), MAX_BYTES)

    def test_unavailable_start_marks_comparison_unavailable(self):
        # Without a task-start snapshot the comparison is unavailable, and no
        # changed files are implied.
        digest = build(None, self.current, self.history)
        self.assertEqual(digest["file_comparison"], "unavailable")
        self.assertNotIn("changed_files_total", digest)
        self.assertEqual(digest["changed_files"], [])
        self.assertEqual(digest["changed_files_omitted"], 0)
        # The recorded check is still evaluated against the current tree.
        self.assertTrue(self.check_entry(digest)["current_files_match_after_check"])

    def test_digest_byte_limit_counts_evictions_below_the_file_count_limit(self):
        names = [f"{i:02}-" + "é" * 95 for i in range(MAX_FILES - 1)]
        for name in names:
            write(os.path.join(self.current, name), b"x")
        digest = self.digest()
        shown = digest["changed_files"]
        self.assertEqual(digest["changed_files_total"], len(names))
        self.assertGreater(len(shown), 0)
        self.assertLess(len(shown), len(names))
        self.assertEqual(digest["changed_files_omitted"], len(names) - len(shown))
        self.assertLessEqual(len(encoded(digest).encode()), MAX_BYTES)
        self.assertTrue(all(entry["path_clipped"] for entry in shown))

    def test_omitted_changes_reconcile_with_actual_count(self):
        # More changed files than MAX_FILES forces the bounded digest to omit
        # some; the reported omission reconciles with the actual change count.
        for index in range(MAX_FILES + 1):
            write(os.path.join(self.current, f"extra{index:02d}.txt"), b"x")
        digest = self.digest()
        self.assertEqual(digest["file_comparison"], "captured")
        self.assertEqual(digest["changed_files_total"], MAX_FILES + 1)
        self.assertGreater(digest["changed_files_omitted"], 0)
        self.assertEqual(len(digest["changed_files"]), MAX_FILES)
        self.assertEqual(
            len(digest["changed_files"]) + digest["changed_files_omitted"],
            digest["changed_files_total"],
        )
        # Omitted paths are exactly the lexicographically last ones, and the
        # kept entries are the actual per-file facts, not placeholders.
        kept_paths = [entry["path"] for entry in digest["changed_files"]]
        self.assertEqual(
            kept_paths,
            sorted(f"extra{i:02d}.txt" for i in range(MAX_FILES + 1))[:MAX_FILES],
        )
        self.assertTrue(
            all(
                entry["change"] == "added_since_start"
                and entry["path_clipped"] is False
                for entry in digest["changed_files"]
            )
        )
        # Observable output stays within the size bound.
        self.assertLessEqual(len(encoded(digest).encode()), MAX_BYTES)


if __name__ == "__main__":
    unittest.main()
