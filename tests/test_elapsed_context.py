"""Trusted clock/data controls; no candidate, subprocess, backend or sandbox runs."""

# ruff: noqa: E402
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fresh_context as fresh
import resumption_digest
import run_checks
from control import DeadlineExceeded
from observations import ObservationHistory

POLICY = {"after_elapsed_agent_fraction": 0.5, "min_remaining_agent_seconds": 180}


class ElapsedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 1000.0
        self.clock = patch.object(
            fresh, "time", SimpleNamespace(monotonic=lambda: self.now)
        )
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.env = SimpleNamespace(
            agent_deadline=1705.0,
            calls=0,
            tool_call_limit=20,
            history_archive=None,
            final_handoff=None,
            spec_blocker_claim=None,
            workspace=self.root / "current",
        )
        self.model = SimpleNamespace(
            calls=0,
            completion_tokens=0,
            prompt_tokens=0,
            limits={"total_completion_token_limit": 1000, "step_limit": 10},
        )
        self.messages = [
            {"role": "system", "content": "exact original system"},
            {"role": "user", "content": "exact original public task"},
        ]
        self.reset = fresh.FreshContext(self.root, POLICY, self.env)
        self.reset.start(self.env.agent_deadline, 705)
        self.reset.project(self.messages)

    def cycle(self, count=1):
        calls, observations = [], []
        for _ in range(count):
            self.env.calls += 1
            identifier = str(self.env.calls)
            calls.append(
                {
                    "id": identifier,
                    "type": "function",
                    "function": {
                        "name": "bash",
                        "arguments": '{"command":"echo inert"}',
                    },
                }
            )
            observations.append(
                {
                    "role": "tool",
                    "tool_call_id": identifier,
                    "content": "originally formatted output",
                }
            )
            (self.root / f"tool-{self.env.calls:03d}.cleanup.json").write_text(
                '{"verified":true}'
            )
        message = {"role": "assistant", "content": "", "tool_calls": calls}
        self.messages.extend([message, *observations])
        self.reset.completed_cycle(message, observations)
        self.model.calls += 1
        self.model.completion_tokens += 7
        return message, observations

    def test_half_original_allocation_exact_crossing_and_single_reset(self):
        self.cycle()
        self.now = 1352.499
        self.assertFalse(self.reset.before_query(self.messages, self.model))
        self.cycle()
        self.now = 1352.5
        identity = (
            id(self.env),
            id(self.model),
            self.env.workspace,
            self.env.agent_deadline,
            self.env.calls,
            self.model.calls,
            self.model.completion_tokens,
        )
        original = copy.deepcopy(self.messages)
        self.assertTrue(self.reset.before_query(self.messages, self.model))
        event = json.loads((self.root / "fresh-context-reset-001.json").read_text())
        self.assertEqual(event["timing"]["nominal_elapsed_seconds"], 352.5)
        self.assertEqual(event["timing"]["actual_elapsed_seconds"], 352.5)
        self.assertEqual(event["timing"]["overshoot_seconds"], 0)
        self.assertEqual(event["timing"]["remaining_agent_seconds"], 352.5)
        self.assertEqual(self.messages[:-1], original)
        self.assertEqual(
            identity,
            (
                id(self.env),
                id(self.model),
                self.env.workspace,
                self.env.agent_deadline,
                self.env.calls,
                self.model.calls,
                self.model.completion_tokens,
            ),
        )
        self.cycle()
        self.now = 1500
        self.assertFalse(self.reset.before_query(self.messages, self.model))
        self.assertEqual(len(list(self.root.glob("fresh-context-reset-*.json"))), 1)

    def test_resumed_view_reports_stale_root_check_from_one_current_snapshot(self):
        start = self.root / "start"
        current = self.env.workspace
        self.env.initial_workspace = start
        for workspace in (start, current):
            workspace.mkdir()
            (workspace / "status").write_text("draft")
        checks = self.root / "checks"
        checks.mkdir()
        ident = run_checks.identity(current, ".")
        visible = {
            "returncode": 0,
            "output": "OK",
            "exception_info": "",
            "truncated": False,
        }
        visible["check_record"] = run_checks.save(
            checks, 1, {"command": "test", "cwd": "."}, ident, ident, visible
        )
        self.model.limits["shared_evidence"] = True
        self.model.history = ObservationHistory(self.root, None, expose_ids=True)
        self.cycle()
        self.messages[-1]["content"] = json.dumps(visible)
        self.model.history.record(self.messages[-1], "test")
        (current / "status").write_text("final")
        self.now = 1352.5

        # Count actual content scans, including scans requested by identity().
        with (
            patch.object(run_checks, "snapshot", wraps=run_checks.snapshot) as scan,
            patch.object(resumption_digest, "snapshot", scan),
        ):
            self.assertTrue(self.reset.before_query(self.messages, self.model))
        self.assertEqual(
            [c.args for c in scan.call_args_list], [(start, "."), (current, ".")]
        )
        event = json.loads((self.root / "fresh-context-reset-001.json").read_bytes())
        view = self.reset.project(self.messages)
        self.assertEqual(view, [*self.messages[:2], event["notice"]])
        _, marker, payload = view[-1]["content"].partition(
            "\nHarness-recorded file/check facts:\n"
        )
        self.assertTrue(marker)
        facts = json.loads(payload)
        self.assertEqual(facts, event["resumption_digest"])
        self.assertEqual([row["path"] for row in facts["changed_files"]], ["status"])
        (check,) = facts["recent_checks"]
        self.assertEqual(
            (check["observation_id"], check["check_id"], check["returncode"]),
            ("o0001", "c0001", 0),
        )
        self.assertIs(check["current_files_match_after_check"], False)

    def test_malformed_only_retry_after_crossing_does_not_trigger(self):
        self.cycle()
        self.now = 1350
        self.assertFalse(self.reset.before_query(self.messages, self.model))
        self.messages.append({"role": "user", "content": "malformed response, retry"})
        self.now = 1400
        self.assertFalse(self.reset.before_query(self.messages, self.model))
        self.assertFalse(self.reset.attempted)
        self.cycle()
        self.assertTrue(self.reset.before_query(self.messages, self.model))

    def test_multi_action_cycle_waits_for_all_results_and_records_overshoot(self):
        self.now = 1400
        self.assertFalse(self.reset.before_query(self.messages, self.model))
        message, observations = self.cycle(3)
        self.assertEqual(self.reset.cycles, 1)
        self.assertEqual(self.env.calls, 3)
        self.assertTrue(self.reset.before_query(self.messages, self.model))
        event = json.loads((self.root / "fresh-context-reset-001.json").read_text())
        self.assertEqual(event["timing"]["overshoot_seconds"], 47.5)
        manifest = json.loads((self.root / "history/manifest.json").read_text())
        self.assertEqual(len(manifest["messages"]), 2 + 1 + len(observations))
        self.assertEqual(message["tool_calls"][2]["id"], "3")

    def test_late_crossing_bypasses_once_without_touching_full_view(self):
        self.cycle()
        original = copy.deepcopy(self.messages)
        self.now = 1525.001
        self.assertFalse(self.reset.before_query(self.messages, self.model))
        event = json.loads((self.root / "fresh-context-bypassed-001.json").read_text())
        self.assertEqual(event["status"], "bypassed")
        self.assertAlmostEqual(event["timing"]["overshoot_seconds"], 172.501)
        self.assertEqual(event["projection_tokens_reclaimed"], 0)
        self.assertEqual(self.messages, original)
        self.assertEqual(self.reset.project(self.messages), original)
        self.assertIsNone(self.env.history_archive)
        self.assertEqual(self.env.agent_deadline, 1705)
        self.cycle()
        self.assertFalse(self.reset.before_query(self.messages, self.model))
        self.assertEqual(len(list(self.root.glob("fresh-context-bypassed-*"))), 1)

    def test_floor_exactly_180_is_allowed(self):
        self.cycle()
        self.now = 1525
        self.assertTrue(self.reset.before_query(self.messages, self.model))

    def test_archive_cost_cannot_lower_floor_or_leave_exposed_history(self):
        self.cycle()
        original = copy.deepcopy(self.messages)
        self.now = 1524.9
        real_rename = fresh.os.rename

        def slow_publication(*args):
            real_rename(*args)
            self.now = 1525.1

        with patch.object(fresh.os, "rename", side_effect=slow_publication):
            self.assertFalse(self.reset.before_query(self.messages, self.model))
        event = json.loads((self.root / "fresh-context-bypassed-001.json").read_text())
        self.assertEqual(event["phase"], "after_archive_publication")
        self.assertEqual(self.messages, original)
        self.assertFalse((self.root / "history").exists())
        self.assertIsNone(self.env.history_archive)

    def test_expired_original_deadline_is_fatal_and_never_extended(self):
        self.cycle()
        self.now = 1705
        with self.assertRaises(DeadlineExceeded):
            self.reset.before_query(self.messages, self.model)
        self.assertEqual(self.env.agent_deadline, 1705)
        self.assertFalse((self.root / "history").exists())

    def test_clock_cannot_be_started_twice_or_changed(self):
        with self.assertRaises(ValueError):
            self.reset.start(1705, 705)
        self.cycle()
        self.env.agent_deadline += 1
        with self.assertRaisesRegex(ValueError, "changed"):
            self.reset.before_query(self.messages, self.model)
