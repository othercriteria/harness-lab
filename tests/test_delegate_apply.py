"""Reviewed application checks data and stale inputs without executing candidates."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import delegate_apply as application
from delegate_artifacts import create_snapshot, digest, export_candidate
from delegate_job import atomic, read


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "guide.md").write_text("original")
        (self.repo / "context.md").write_text("context")
        self.package = self.root / "package"
        self.package.mkdir()
        create_snapshot(
            self.repo, ["guide.md", "context.md"], ["guide.md"], self.package / "source"
        )
        self.work = self.root / "candidate"
        shutil.copytree(self.repo, self.work)
        (self.work / "guide.md").write_text("reviewed replacement")
        self.store = self.root / "store"
        self.identifier = "1" * 32
        self.job = self.store / "jobs" / self.identifier
        self.job.mkdir(parents=True)
        export_candidate(self.package / "source", self.work, self.job / "artifact")
        atomic(
            self.job / "state.json",
            {"state": "completed", "cleanup_verified": True, "package_id": "2" * 64},
        )
        atomic(
            self.job / "review.json",
            {
                "decision": "accepted",
                "reviewer": "outer test reviewer",
                "notes": "data only",
                "verification": "static check",
                "job_id": self.identifier,
                "package_id": "2" * 64,
                "artifact_sha256": digest(
                    (self.job / "artifact/artifact.json").read_bytes()
                ),
            },
        )
        self.stub = patch.object(
            application, "verify_package", return_value=(self.package, {})
        )
        self.stub.start()
        self.addCleanup(self.stub.stop)

    def apply(self):
        return application.apply(self.identifier, self.repo, self.store)

    def test_applies_only_reviewed_path_and_records_receipt(self):
        result = self.apply()
        self.assertTrue(result["applied"])
        self.assertEqual((self.repo / "guide.md").read_text(), "reviewed replacement")
        self.assertEqual((self.repo / "context.md").read_text(), "context")
        self.assertEqual(result, read(self.job / "application.json"))
        with self.assertRaisesRegex(ValueError, "already started"):
            self.apply()

    def test_changed_readonly_dependency_blocks_application(self):
        (self.repo / "context.md").write_text("concurrent change")
        with self.assertRaisesRegex(ValueError, "Stale"):
            self.apply()
        self.assertEqual((self.repo / "guide.md").read_text(), "original")
        self.assertFalse((self.job / "application.json").exists())

    def test_modified_candidate_bytes_are_rejected(self):
        (self.job / "artifact/files/guide.md").write_text("not reviewed")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.apply()
        self.assertEqual((self.repo / "guide.md").read_text(), "original")

    def test_review_cannot_authorize_another_package(self):
        r = read(self.job / "review.json")
        r["package_id"] = "3" * 64
        atomic(self.job / "review.json", r)
        with self.assertRaisesRegex(ValueError, "another job/package"):
            self.apply()

    def test_pending_review_cannot_apply(self):
        r = read(self.job / "review.json")
        r["decision"] = "pending"
        atomic(self.job / "review.json", r)
        with self.assertRaisesRegex(ValueError, "outer review required"):
            self.apply()

    def test_review_revocation_during_staging_blocks_application(self):
        def changed(*args):
            review = read(self.job / "review.json")
            review["decision"] = "rejected"
            atomic(self.job / "review.json", review)
            return self.package, {}

        with patch.object(application, "verify_package", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "Review changed"):
                self.apply()
        self.assertEqual((self.repo / "guide.md").read_text(), "original")
        self.assertFalse((self.job / "application.json").exists())

    def test_mode_change_after_initial_preflight_blocks_application(self):
        original = application.check_application_base

        def changed(*args):
            result = original(*args)
            (self.repo / "guide.md").chmod(0o755)
            return result

        with patch.object(application, "check_application_base", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "Base changed"):
                self.apply()
        self.assertEqual((self.repo / "guide.md").read_text(), "original")
        self.assertFalse(read(self.job / "application.json")["applied"])

    def test_review_cannot_be_rewritten_after_application_begins(self):
        review = read(self.job / "review.json")
        application.publish_review(self.identifier, review, self.store)
        self.apply()
        with self.assertRaisesRegex(ValueError, "journal exists"):
            application.publish_review(
                self.identifier, review | {"decision": "rejected"}, self.store
            )

    def test_symlink_live_target_does_not_overwrite_destination(self):
        other = self.root / "other"
        other.write_text("untouched")
        (self.repo / "guide.md").unlink()
        (self.repo / "guide.md").symlink_to(other)
        with self.assertRaises(OSError):
            self.apply()
        self.assertEqual(other.read_text(), "untouched")


if __name__ == "__main__":
    unittest.main()
