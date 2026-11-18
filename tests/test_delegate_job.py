"""Outer lifecycle proof with harmless CPU children; no model or service calls."""

import contextlib
import hashlib
import json
import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import delegate_job as jobs
import with_ollama_released as lifecycle
from delegate_artifacts import create_snapshot, encoded, export_candidate


class DelegateJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.identifier = "a" * 32
        self.job = self.root / "jobs" / self.identifier
        (self.job / "events").mkdir(parents=True)
        jobs.atomic(
            self.job / "state.json",
            {
                "state": "accepted",
                "cleanup_verified": False,
                "submitted_monotonic": time.monotonic(),
                "owner": None,
                "run": str(self.root / "run"),
            },
        )

    def execute(self, code="pass", timeout=3, close=None):
        return jobs.execute_owned(
            self.job,
            [sys.executable, "-I", "-S", "-c", code],
            timeout,
            None,
            close or (lambda: {"verified": True}),
            lambda: {"acceptance": "pending"},
            shutdown_seconds=1,
        )

    def test_real_child_completion_keeps_acceptance_pending(self):
        result = self.execute()
        self.assertEqual(result["state"], "completed")
        self.assertTrue(result["cleanup_verified"])
        evidence = jobs.read(self.job / "result.json")
        self.assertEqual(evidence["acceptance"], "pending")
        self.assertFalse(evidence["applied"])
        child = jobs.read(self.job / "child.json")["pid"]
        self.assertFalse(lifecycle.live_group_members(child))

    def test_dispatch_records_only_explicit_classification(self):
        request = dict(
            package_id="b" * 64,
            session_id="2026-11-18-gpu-quiet-040",
            total_seconds=900,
            seed=1,
            idempotency_key="sample",
        )
        with self.assertRaisesRegex(ValueError, "classification"):
            jobs.validate_request({**request, "classification": "other"})
        for kind in (None, "diagnostic_replay", "lifecycle_acceptance", "useful_work"):
            store = self.root / str(kind)
            payload = request if kind is None else {**request, "classification": kind}
            with (
                self.subTest(kind=kind),
                patch.object(jobs, "STORE", store),
                patch.object(
                    lifecycle,
                    "gpu_experiment_lock",
                    return_value=contextlib.nullcontext(Mock()),
                ),
                patch.object(
                    jobs,
                    "verify_package",
                    return_value=(store, {"label": "job", "snapshot_id": "snapshot"}),
                ),
                patch.object(jobs, "require_quiet_session", return_value={}),
                patch.object(jobs.subprocess, "Popen"),
            ):
                admitted = jobs.submit(payload, store)
                receipt = store / "jobs" / admitted["job_id"] / "classification.json"
                if kind is None:
                    self.assertFalse(receipt.exists())
                else:
                    self.assertEqual(
                        jobs.read(receipt),
                        {
                            "job_id": admitted["job_id"],
                            "kind": kind,
                            "source": "dispatch",
                        },
                    )

    def test_real_child_deadline_reaps_owned_group(self):
        result = self.execute("import time; time.sleep(20)", timeout=0.1)
        self.assertEqual(result["state"], "timed_out")
        self.assertTrue(result["cleanup_verified"])
        self.assertFalse(
            lifecycle.live_group_members(jobs.read(self.job / "child.json")["pid"])
        )

    def test_real_child_can_cancel_worker_and_cleanup_is_verified(self):
        result = self.execute(
            "import os, signal, time; os.kill(os.getppid(), signal.SIGTERM); time.sleep(20)"
        )
        self.assertEqual(result["state"], "cancelled")
        self.assertFalse(
            lifecycle.live_group_members(jobs.read(self.job / "child.json")["pid"])
        )

    def test_precancel_does_not_launch_or_call_cleanup(self):
        jobs.atomic(self.job / "cancel.json", {"reason": "test"})
        close = Mock()
        result = self.execute(close=close)
        self.assertEqual(result["state"], "cancelled")
        self.assertFalse((self.job / "launch-intent.json").exists())
        close.assert_not_called()

    def test_uncertain_cleanup_latches_and_blocks_new_admission(self):
        close = Mock(side_effect=RuntimeError("missing receipt"))
        result = self.execute(close=close)
        self.assertEqual(result["state"], "recovery_required")
        self.assertFalse(result["cleanup_verified"])
        with self.assertRaisesRegex(RuntimeError, "recovery"):
            jobs.require_no_unclosed_jobs(self.root)
        with self.assertRaisesRegex(RuntimeError, "recovery"):
            lifecycle.require_delegation_closed(self.root / "jobs")

    def test_missing_owner_is_uncertainty_not_success(self):
        result = jobs.status(self.identifier, self.root)
        self.assertEqual(result["state"], "recovery_required")
        self.assertEqual(result["recorded_state"], "accepted")

    def test_inaccessible_host_identity_is_not_reported_dead(self):
        jobs.update(self.job, "running", owner=jobs.process_identity(os.getpid()))
        with patch.object(
            jobs, "process_identity", side_effect=PermissionError("restricted proc")
        ):
            result = jobs.status(self.identifier, self.root)
            self.assertEqual(result["state"], "running")
            self.assertEqual(result["owner_inspection"], "unavailable")
            with self.assertRaisesRegex(RuntimeError, "inspection unavailable"):
                jobs.recover(self.identifier, self.root)

    def test_cancel_never_signals_submitter(self):
        jobs.update(
            self.job,
            "accepted",
            owner=jobs.process_identity(os.getpid()),
            owner_role="submitter",
        )
        with patch.object(signal, "pidfd_send_signal") as send:
            result = jobs.cancel(self.identifier, "test", self.root)
        send.assert_not_called()
        self.assertTrue(result["cancel_requested"])

    def test_old_boot_owner_is_not_signalled_even_if_pid_tuple_matches(self):
        identity = jobs.process_identity(os.getpid()) | {"boot_id": "previous-boot"}
        jobs.update(self.job, "running", owner=identity, owner_role="worker")
        with patch.object(signal, "pidfd_send_signal") as send:
            jobs.cancel(self.identifier, "stale owner", self.root)
        send.assert_not_called()
        self.assertFalse(jobs.live(identity))

    def test_recovery_before_launch_needs_fresh_lease(self):
        with patch.object(
            lifecycle, "gpu_experiment_lock", return_value=contextlib.nullcontext()
        ) as lock:
            result = jobs.recover(self.identifier, self.root)
        lock.assert_called_once_with(recovering_delegation=True)
        self.assertEqual(result["state"], "failed")
        self.assertTrue(result["cleanup_verified"])
        self.assertTrue(jobs.read(self.job / "closure.json")["not_launched"])

    def test_live_owner_cannot_be_recovered(self):
        jobs.update(self.job, "running", owner=jobs.process_identity(os.getpid()))
        with patch.object(lifecycle, "gpu_experiment_lock") as lock:
            with self.assertRaisesRegex(RuntimeError, "still live"):
                jobs.recover(self.identifier, self.root)
        lock.assert_not_called()

    def test_recovery_preserves_precommit_result_and_reconciles_state(self):
        jobs.atomic(
            self.job / "result.json",
            {"execution_state": "completed", "result": {"artifact": "retained"}},
        )
        with patch.object(
            lifecycle, "gpu_experiment_lock", return_value=contextlib.nullcontext()
        ):
            state = jobs.recover(self.identifier, self.root)
        self.assertEqual(state["state"], "failed")
        self.assertEqual(
            jobs.read(self.job / "result.json")["execution_state"], "failed"
        )
        self.assertEqual(
            jobs.read(self.job / "result.json")["result"], {"artifact": "retained"}
        )
        self.assertEqual(
            jobs.read(self.job / "pre-recovery-result.json")["execution_state"],
            "completed",
        )

    def test_shared_gate_blocks_experiments_after_os_lock_is_free(self):
        original = lifecycle.require_delegation_closed
        with patch.object(
            lifecycle,
            "require_delegation_closed",
            side_effect=lambda: original(self.root / "jobs"),
        ):
            with self.assertRaisesRegex(RuntimeError, "recovery"):
                with lifecycle.gpu_experiment_lock(self.root):
                    self.fail("uncertain job admitted a fresh experiment")
            with lifecycle.gpu_experiment_lock(self.root, recovering_delegation=True):
                pass

    def receipts(self):
        run = self.root / "run"
        for path, record in {
            "background/summary.json": {"restored": True},
            "voice/result.json": {"states_verified": True},
            "ollama/result.json": {"service_unchanged": True},
            "memory/cleanup.json": {"verified": True},
            "experiment/summary.json": {"server_stopped": True, "client_stopped": True},
            "experiment/trial-00-delegated-task/summary.json": {},
            "experiment/trial-00-delegated-task/tool-001.invocation.json": {
                "unit": "owned.scope"
            },
            "experiment/trial-00-delegated-task/tool-001.cleanup.json": {
                "unit": "owned.scope",
                "verified": True,
                "owned_process_reaped": True,
            },
        }.items():
            target = run / path
            target.parent.mkdir(parents=True, exist_ok=True)
            jobs.atomic(target, record)
        return run

    def test_closure_binds_each_invocation_and_trial(self):
        run = self.receipts()
        self.assertTrue(jobs.closure(run)["verified"])
        receipt = run / "experiment/trial-00-delegated-task/tool-001.cleanup.json"
        original = receipt.read_bytes()
        receipt.unlink()
        with self.assertRaises(FileNotFoundError):
            jobs.closure(run)
        receipt.write_bytes(original)
        record = json.loads(original)
        jobs.atomic(receipt, record | {"unit": "different.scope"})
        with self.assertRaisesRegex(RuntimeError, "cleanup unverified"):
            jobs.closure(run)
        receipt.write_bytes(original)
        jobs.atomic(receipt.parent / "summary.json", {"unsafe_cleanup": "lost scope"})
        with self.assertRaisesRegex(RuntimeError, "unsafe cleanup"):
            jobs.closure(run)

    def test_missing_experiment_summary_is_not_success(self):
        run = self.receipts()
        (run / "experiment/summary.json").unlink()
        with self.assertRaises(FileNotFoundError):
            jobs.closure(run)

    def test_missing_trial_result_needs_scope_closure_and_every_tool_receipt(self):
        run = self.receipts()
        (run / "experiment/trial-00-delegated-task/summary.json").unlink()
        with self.assertRaisesRegex(RuntimeError, "whole-scope"):
            jobs.closure(run)
        jobs.atomic(
            run / "memory/cleanup.json",
            {"verified": True, "cgroup_empty_or_absent": True},
        )
        evidence = jobs.closure(run)
        self.assertTrue(evidence["verified"])
        self.assertFalse(evidence["trial_results_complete"])
        (run / "experiment/trial-00-delegated-task/tool-001.cleanup.json").unlink()
        with self.assertRaises(FileNotFoundError):
            jobs.closure(run)

    def test_check_evidence_must_match_exported_artifact(self):
        package = self.root / "package"
        package.mkdir()
        source = self.root / "source"
        source.mkdir()
        (source / "guide.md").write_text("before")
        create_snapshot(source, ["guide.md"], ["guide.md"], package / "source")
        public = package / "runtime/tasks/delegated-task/public"
        public.mkdir(parents=True)
        (public / "task.md").write_text("Improve guide")
        run = self.root / "run"
        trial = run / "experiment/trial-00-delegated-task"
        workspace = trial / "workspaces/final"
        workspace.mkdir(parents=True)
        (workspace / "guide.md").write_text("after")
        (workspace / "task.md").write_text("Improve guide")
        artifact = export_candidate(
            package / "source", workspace, self.root / "sealed", brief=b"Improve guide"
        )
        summary = {
            "final_workspace": str(workspace),
            "verification": {
                "artifact_sha256": hashlib.sha256(encoded(artifact)).hexdigest()
            },
        }
        jobs.atomic(trial / "summary.json", summary)
        result = jobs.collect(self.job, package, run)
        self.assertEqual(result["artifact"]["changed_files"], 1)
        self.assertNotIn("changes", result["artifact"])
        self.assertEqual(result["acceptance"], "pending")
        otherjob = self.root / "other-job"
        otherjob.mkdir()
        (workspace / "guide.md").write_text("unverified replacement")
        with self.assertRaisesRegex(ValueError, "different artifact"):
            jobs.collect(otherjob, package, run)

    def test_direct_child_cleanup_failure_cannot_be_overruled_by_receipts(self):
        with patch.object(
            lifecycle,
            "run_owned",
            side_effect=lifecycle.OwnedCleanupFailed("group survived"),
        ):
            result = self.execute()
        self.assertEqual(result["state"], "recovery_required")
        self.assertFalse(result["cleanup_verified"])


if __name__ == "__main__":
    unittest.main()
