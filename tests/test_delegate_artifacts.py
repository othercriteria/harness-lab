"""Delegation exports are bounded untrusted data, never executable patches."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import delegate_artifacts as artifacts


class DelegateArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        (self.repo / "scripts/a.py").write_text("VALUE = 2\n")
        (self.repo / "README.md").write_text("Instructions\n")
        self.snapshot = self.root / "snapshot"
        self.names = ["scripts/a.py", "README.md"]
        self.writable = ["scripts/a.py", "docs/new.md"]

    def prepare(self):
        return artifacts.create_snapshot(
            self.repo, self.names, self.writable, self.snapshot
        )

    def workspace(self):
        self.prepare()
        workspace = self.root / "workspace"
        shutil.copytree(self.snapshot / "public", workspace)
        return workspace

    def test_explicit_snapshot_copies_no_other_repository_material(self):
        (self.repo / ".git").mkdir()
        (self.repo / ".git/config").write_text("host-only metadata")
        (self.repo / "unselected.txt").write_text("not public")
        record = self.prepare()
        loaded, files = artifacts.load_snapshot(self.snapshot)
        self.assertEqual(record, loaded)
        self.assertEqual(set(files), set(self.names))
        self.assertIsNone(record["contract"]["base"]["docs/new.md"])
        self.assertFalse((self.snapshot / "public/.git").exists())

    def test_snapshot_identity_is_order_independent(self):
        first = self.prepare()
        other = artifacts.create_snapshot(
            self.repo, self.names[::-1], self.writable[::-1], self.root / "other"
        )
        self.assertEqual(first, other)

    def test_executable_inputs_are_preserved_and_mode_changes_are_stale(self):
        source = self.repo / "scripts/a.py"
        source.chmod(0o755)
        workspace = self.workspace()
        self.assertEqual((workspace / "scripts/a.py").stat().st_mode & 0o777, 0o755)
        (workspace / "scripts/a.py").write_text("VALUE = 3\n")
        out = self.root / "export"
        result = artifacts.export_candidate(self.snapshot, workspace, out)
        self.assertEqual(result["changes"][0]["executable_bits"], 0o111)
        self.assertEqual((out / "files/scripts/a.py").stat().st_mode & 0o777, 0o755)
        source.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "Stale"):
            artifacts.check_application_base(self.snapshot, self.repo)

    def test_candidate_chmod_only_change_is_rejected(self):
        workspace = self.workspace()
        (workspace / "scripts/a.py").chmod(0o755)
        with self.assertRaisesRegex(ValueError, "Executable-mode"):
            artifacts.export_candidate(self.snapshot, workspace, self.root / "export")

    def test_unapproved_paths_and_metadata_are_rejected(self):
        for name in [
            "/etc/passwd",
            "../secret",
            "a/../secret",
            "a//b",
            "a/./b",
            ".git/config",
            ".env",
            "x/.env.local",
            ".ssh/id_rsa",
            "tasks/example/private/test.py",
            "results/run.json",
            "bad\nname",
            "a\\b",
            "",
            None,
        ]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                artifacts.relative_path(name)

    def test_existing_writable_file_must_be_a_visible_input(self):
        (self.repo / "hidden.py").write_text("existing")
        with self.assertRaisesRegex(ValueError, "included as inputs"):
            artifacts.create_snapshot(
                self.repo, self.names, ["hidden.py"], self.snapshot
            )
        self.assertFalse(self.snapshot.exists())

    def test_symlink_ancestor_and_hardlink_cannot_be_inputs(self):
        (self.repo / "alias").symlink_to(
            self.repo / "scripts", target_is_directory=True
        )
        with self.assertRaises(OSError):
            artifacts.read_file(self.repo, "alias/a.py")
        os.link(self.repo / "scripts/a.py", self.repo / "linked.py")
        with self.assertRaisesRegex(ValueError, "single-link"):
            artifacts.read_file(self.repo, "linked.py")

    def test_fifo_input_does_not_block(self):
        os.mkfifo(self.repo / "pipe")
        with self.assertRaisesRegex(ValueError, "regular"):
            artifacts.read_file(self.repo, "pipe")

    def test_selected_total_bytes_and_file_count_are_bounded(self):
        with patch.object(artifacts, "MAX_BYTES", 12):
            with self.assertRaisesRegex(ValueError, "Snapshot byte"):
                self.prepare()
        with patch.object(artifacts, "MAX_FILES", 1):
            with self.assertRaisesRegex(ValueError, "bounded"):
                self.prepare()
        self.assertFalse(self.snapshot.exists())

    def test_modified_or_added_snapshot_content_is_detected(self):
        self.prepare()
        path = self.snapshot / "public/README.md"
        path.write_text("changed")
        with self.assertRaisesRegex(ValueError, "input integrity"):
            artifacts.load_snapshot(self.snapshot)
        path.write_bytes((self.repo / "README.md").read_bytes())
        (self.snapshot / "public/extra.py").write_text("injected")
        with self.assertRaisesRegex(ValueError, "input integrity"):
            artifacts.load_snapshot(self.snapshot)

    def test_snapshot_policy_tampering_is_detected(self):
        self.prepare()
        path = self.snapshot / "snapshot.json"
        record = json.loads(path.read_text())
        record["contract"]["allowed_write_paths"].append("README.md")
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "contract integrity"):
            artifacts.load_snapshot(self.snapshot)

    def test_candidate_exports_modify_add_delete_without_applying(self):
        workspace = self.workspace()
        (workspace / "scripts/a.py").unlink()
        (workspace / "docs").mkdir()
        (workspace / "docs/new.md").write_text("New documentation\n")
        brief = b"Explicit public brief\n"
        (workspace / "task.md").write_bytes(brief)
        out = self.root / "export"
        result = artifacts.export_candidate(self.snapshot, workspace, out, brief=brief)
        self.assertEqual(
            {r["path"]: r["operation"] for r in result["changes"]},
            {"scripts/a.py": "delete", "docs/new.md": "add"},
        )
        self.assertFalse(result["applied"])
        self.assertEqual(result["acceptance"], "pending_outer_review")
        self.assertEqual((self.repo / "scripts/a.py").read_text(), "VALUE = 2\n")
        self.assertFalse((self.repo / "docs/new.md").exists())

    def test_disallowed_changes_rejected_before_any_export(self):
        workspace = self.workspace()
        (workspace / "README.md").write_text("unauthorized edit")
        out = self.root / "export"
        with self.assertRaisesRegex(ValueError, "unapproved paths"):
            artifacts.export_candidate(self.snapshot, workspace, out)
        self.assertFalse(out.exists())

    def test_changed_brief_or_candidate_symlink_rejected(self):
        workspace = self.workspace()
        (workspace / "task.md").write_text("changed brief")
        with self.assertRaisesRegex(ValueError, "brief"):
            artifacts.export_candidate(
                self.snapshot, workspace, self.root / "export", brief=b"original"
            )
        (workspace / "task.md").unlink()
        (workspace / "scripts/a.py").unlink()
        (workspace / "scripts/a.py").symlink_to(self.repo / "README.md")
        with self.assertRaisesRegex(ValueError, "symlink"):
            artifacts.export_candidate(self.snapshot, workspace, self.root / "export")

    def test_binary_candidate_rejected(self):
        workspace = self.workspace()
        (workspace / "scripts/a.py").write_bytes(b"hello\0world")
        with self.assertRaisesRegex(ValueError, "Binary"):
            artifacts.export_candidate(self.snapshot, workspace, self.root / "export")

    def test_diff_preserves_no_final_newline_information(self):
        workspace = self.workspace()
        (workspace / "scripts/a.py").write_text("VALUE = 3")
        out = self.root / "export"
        result = artifacts.export_candidate(self.snapshot, workspace, out)
        self.assertIn(
            "+VALUE = 3\n\\ No newline at end of file\n",
            (out / "changes.diff").read_text(),
        )
        self.assertEqual(result["changes"][0]["operation"], "modify")
        self.assertEqual((out / "files/scripts/a.py").read_bytes(), b"VALUE = 3")

    def test_stale_base_checks_unchanged_dependencies_and_new_path_collisions(self):
        self.prepare()
        self.assertTrue(
            artifacts.check_application_base(self.snapshot, self.repo)["base_matches"]
        )
        (self.repo / "README.md").write_text("concurrent edit to dependency")
        with self.assertRaisesRegex(ValueError, "Stale.*README"):
            artifacts.check_application_base(self.snapshot, self.repo)
        (self.repo / "README.md").write_text("Instructions\n")
        (self.repo / "docs").mkdir()
        (self.repo / "docs/new.md").write_text("concurrent new file")
        with self.assertRaisesRegex(ValueError, "Stale.*docs/new"):
            artifacts.check_application_base(self.snapshot, self.repo)

    def test_output_path_file_directory_collisions_and_reserved_brief_rejected(self):
        for paths in [
            ["docs", "docs/new.md"],
            ["scripts/a.py", "scripts/a.py/new"],
            ["task.md"],
            ["scripts/a.py", "scripts/a.py"],
        ]:
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                artifacts.create_snapshot(self.repo, self.names, paths, self.snapshot)
        self.assertFalse(self.snapshot.exists())


if __name__ == "__main__":
    unittest.main()
