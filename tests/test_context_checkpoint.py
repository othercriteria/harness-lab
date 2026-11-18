"""Metered continuation memory with no candidate code execution on the host."""

import copy
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from checkpoint_evidence import verify_checkpoint_evidence
from coding_agent import IsolatedEnvironment, LocalModel
from context_checkpoint import action, validate
from control import DeadlineExceeded, UnsafeCleanup
from fresh_context import FreshContext, validate_history_archive, validate_policy
from mini_bootstrap import DefaultAgent, FormatError
from observations import ObservationHistory

POLICY = {
    "after_elapsed_agent_fraction": 0.5,
    "min_remaining_agent_seconds": 180,
    "summary_checkpoint": True,
}
SUMMARY = "Observed o0001: tests fail. Next: fix engine.py and save regression tests."


def call(name, value, identifier="call-1"):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": identifier,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(value)},
            }
        ],
    }


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = IsolatedEnvironment(
            SimpleNamespace(manifest={"mock": True}),
            self.root,
            self.root,
            10,
            tool_call_limit=8,
            structured_finalization=True,
        )
        self.env.agent_deadline = time.monotonic() + 350
        self.limits = {
            "total_completion_token_limit": 8000,
            "max_completion_tokens_per_request": 4096,
            "reasoning_budget_tokens": 4096,
            "request_timeout_seconds": 1,
            "context_capacity_tokens": 32768,
            "step_limit": 8,
            "structured_finalization": True,
            "plain_tool_observations": True,
            "time_budget_feedback": True,
            "context_policy": {
                "mode": "none",
                "keep_recent": 8,
                "trigger_tokens": 22000,
                "safety_tokens": 256,
            },
            "fresh_context": dict(POLICY),
        }
        self.model = LocalModel(
            "http://127.0.0.1:18080", "fake", {}, self.limits, self.root
        )
        self.model.history = ObservationHistory(
            self.root,
            self.limits["context_policy"],
            expose_ids=True,
        )
        self.env.history = self.model.history
        self.controller = FreshContext(self.root, POLICY, self.env, model=self.model)
        self.model.fresh_context = self.env.fresh_context = self.controller
        self.controller.start(self.env.agent_deadline, 705)
        self.model.count_tokens = lambda *args: 100
        self.requests = []
        self.perform_options = []

    def input_tokens_for_headroom(self, remaining):
        return (
            self.limits["context_capacity_tokens"]
            - self.limits["context_policy"]["safety_tokens"]
            - remaining
        )

    def read(self, name):
        return json.loads((self.root / name).read_text())

    def use_headroom(self, mode="continue", max_resets=2):
        policy = {
            "trigger": "context_headroom", "min_remaining_agent_seconds": 180,
            "headroom_tokens": 8192, "max_resets": max_resets, "summary_checkpoint": True,
            "continuation_mode": mode,
        }
        self.limits["fresh_context"] = policy
        self.controller = FreshContext(self.root, policy, self.env, model=self.model)
        self.model.fresh_context = self.env.fresh_context = self.controller
        self.controller.start(self.env.agent_deadline, 705)
        self.model.count_tokens = lambda *args: 26000

    def terminal_call(self):
        return call("finish_attempt", {
            "disposition": "submitted", "summary": "Ready for independent review",
            "evidence": [], "unverified": ["Independent checks pending"], "blocker": None,
        }, "final")

    def checkpoint_audit(self):
        return verify_checkpoint_evidence(self.root, self.limits)["checkpoints"][0]

    def test_pressure_checkpoint_can_finalize_without_reset_or_budget_renewal(self):
        self.use_headroom()
        deadline = self.env.agent_deadline
        self.run_sequence(checkpoint=self.terminal_call(), prompt_tokens=26000)
        self.assertEqual((self.model.calls, self.model.completion_tokens, self.env.calls), (2, 10, 2))
        self.assertEqual(self.env.agent_deadline, deadline)
        self.assertEqual(len(self.perform_options), 1)
        self.assertEqual(self.requests[1]["max_tokens"], 2048)
        self.assertEqual(self.requests[1]["reasoning_budget_tokens"], 256)
        self.assertFalse(list(self.root.glob("fresh-context-reset-*.json")))
        self.assertFalse((self.root / "context-checkpoint-001.json").exists())
        self.assertEqual(self.read("tool-002.result.json")["terminal_control"], "Submitted")
        audit = self.checkpoint_audit()
        self.assertEqual(audit["status"], "finalized")
        self.assertEqual(audit["summary_completion_tokens"], 0)
        self.assertEqual(audit["finalization_completion_tokens"], 5)

    def test_pressure_checkpoint_finalization_uses_ordinary_evidence_validation_and_repair(self):
        self.use_headroom()
        bad = self.terminal_call()
        value = json.loads(bad["tool_calls"][0]["function"]["arguments"])
        value["evidence"] = [{"kind": "observation", "observation_id": "o9999"}]
        bad["tool_calls"][0]["function"]["arguments"] = json.dumps(value)
        self.run_sequence(checkpoint=bad, repair=self.terminal_call(), prompt_tokens=26000)
        self.assertEqual((self.model.calls, self.env.calls), (3, 2))
        self.assertEqual(len(self.perform_options), 1)
        audit = self.checkpoint_audit()
        self.assertEqual(audit["status"], "finalized")
        self.assertEqual(audit["initial_attempt"]["status"], "rejected")

    def test_pressure_checkpoint_rejects_mixed_terminal_and_execution_batch(self):
        self.use_headroom()
        bad = self.terminal_call()
        bad["tool_calls"] += call("bash", {"command": "must not execute"}, "bad")["tool_calls"]
        self.run_sequence(checkpoint=bad, repair=self.terminal_call(), prompt_tokens=26000)
        self.assertEqual(len(self.perform_options), 1)
        self.assertEqual(self.checkpoint_audit()["initial_attempt"]["status"], "rejected")

    def test_pressure_checkpoint_second_bad_finalization_falls_back_without_extra_retry(self):
        self.use_headroom()
        bad = call("finish_attempt", {"summary": "missing required fields"})
        self.run_sequence(checkpoint=bad, repair=bad, prompt_tokens=26000)
        self.assertEqual(self.model.calls, 5)
        self.assertEqual(self.checkpoint_audit()["status"], "rejected")
        self.assertEqual(self.read("fresh-context-reset-001.json")["summary_checkpoint"]["status"],
                         "fallback_without_summary")
        self.assertEqual(len(list(self.root.glob("context-checkpoint-repair-request-*.json"))), 1)

    def test_review_mode_cannot_finalize_instead_of_checkpoint(self):
        self.use_headroom("review", max_resets=1)
        self.assertFalse(self.controller.checkpoint_finalization_allowed)
        self.run_sequence(checkpoint=self.terminal_call(),
                          repair=call("checkpoint_context", {"summary": SUMMARY}), prompt_tokens=26000)
        self.assertEqual(self.model.calls, 5)
        self.assertEqual(self.checkpoint_audit()["status"], "saved")
        self.assertTrue((self.root / "fresh-context-reset-001.json").exists())

    def test_pressure_checkpoint_can_report_an_ordinary_supported_blocker(self):
        self.use_headroom()
        blocked = call("finish_attempt", {
            "disposition": "blocked", "summary": "Conflicting requirements",
            "evidence": [{"kind": "public_contract", "public_clause": "Return zero and one",
                          "supports": "The same result cannot equal both"}],
            "unverified": [],
            "blocker": {"category": "contradictory_requirements", "argument": "Both results required",
                        "necessary_change": "Choose one result"},
        })
        self.run_sequence(checkpoint=blocked, prompt_tokens=26000)
        self.assertEqual(self.read("tool-002.result.json")["terminal_control"], "Blocked")
        self.assertEqual(self.checkpoint_audit()["disposition"], "blocked")
        self.assertFalse(list(self.root.glob("fresh-context-reset-*.json")))

    def test_truncated_terminal_response_at_checkpoint_is_rejected_then_repaired(self):
        self.use_headroom()
        self.run_sequence(checkpoint=self.terminal_call(), finish_reason="length",
                          repair=self.terminal_call(), prompt_tokens=26000)
        audit = self.checkpoint_audit()
        self.assertEqual(audit["status"], "finalized")
        self.assertEqual(audit["initial_attempt"]["status"], "rejected")
        self.assertEqual(len(self.perform_options), 1)

    def test_active_scope_disables_checkpoint_finalization(self):
        self.use_headroom()
        self.model.scope_runtime = SimpleNamespace(active=True)
        self.assertFalse(self.controller.checkpoint_finalization_allowed)
        self.controller.checkpoint_requested = True
        with self.assertRaisesRegex(ValueError, "Ineligible"):
            self.controller.checkpoint_response(accepted=True, accepted_tool="finish_attempt")

    def test_deadline_between_terminal_response_and_dispatch_is_not_submission(self):
        self.use_headroom()
        now = time.monotonic()
        with patch("time.monotonic", return_value=now) as clock:
            def advance(n):
                if n == 2:
                    clock.return_value = self.env.agent_deadline + 1
            with self.assertRaises(DeadlineExceeded):
                self.run_sequence(checkpoint=self.terminal_call(), after_response=advance, prompt_tokens=26000)
        self.assertFalse((self.root / "final-handoff.json").exists())
        self.assertEqual(self.checkpoint_audit()["status"], "valid_finalization_not_dispatched")

    def test_terminal_checkpoint_audit_rejects_forged_receipts_and_later_activity(self):
        self.use_headroom()
        self.run_sequence(checkpoint=self.terminal_call(), prompt_tokens=26000)
        for name, key, value in [
            ("tool-002.result.json", "terminal_control", "Blocked"),
            ("context-checkpoint-response-001.json", "accepted_tool", "checkpoint_context"),
            ("final-handoff.json", "handoff", {"summary": "forged"}),
        ]:
            path = self.root / name
            original = path.read_bytes()
            altered = json.loads(original)
            altered[key] = value
            path.write_text(json.dumps(altered))
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.checkpoint_audit()
            path.write_bytes(original)
        (self.root / "tool-003.request.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "Continued tools"):
            self.checkpoint_audit()
        (self.root / "tool-003.request.json").unlink()
        (self.root / "tool-002.result.json").unlink()
        self.assertEqual(self.checkpoint_audit()["status"], "finalization_dispatch_incomplete")
        (self.root / "summary.json").write_text('{"clean_agent_completion":true}')
        with self.assertRaisesRegex(ValueError, "without result"):
            self.checkpoint_audit()

    def run_sequence(
        self,
        checkpoint=None,
        finish_reason="tool_calls",
        after_response=None,
        read_diagnostic=False,
        repair=None,
        finish_at=None,
        response_plan=None,
        prompt_tokens=100,
    ):
        def response(request, **kwargs):
            self.requests.append(json.loads(request.data))
            n = len(self.requests)
            if response_plan is not None:
                message = response_plan[n - 1]
            elif n == 2:
                message = checkpoint or call(
                    "checkpoint_context", {"summary": SUMMARY}, "call-2"
                )
            elif n == 3 and repair is not None:
                message = repair
            elif n == (finish_at or (5 if repair is not None else 4)):
                message = call(
                    "finish_attempt",
                    {
                        "disposition": "submitted",
                        "summary": "Work ready.",
                        "evidence": [],
                        "unverified": ["Independent checks pending."],
                        "blocker": None,
                    },
                    "call-4",
                )
            else:
                message = (
                    call("read_file", {"path": "module.py"}, f"call-{n}")
                    if read_diagnostic
                    else call("bash", {"command": "echo diagnostic"}, f"call-{n}")
                )
            if after_response:
                after_response(n)
            return io.BytesIO(
                json.dumps(
                    {
                        "usage": {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": 5,
                        },
                        "choices": [
                            {
                                "finish_reason": finish_reason
                                if n == 2
                                else "tool_calls",
                                "message": message,
                            }
                        ],
                    }
                ).encode()
            )

        self.model.opener = SimpleNamespace(open=response)

        def perform(runtime, workspace, name, arguments, timeout, prefix, **options):
            self.perform_options.append(options)
            prefix.with_suffix(".cleanup.json").write_text('{"verified":true}')
            return {"ok": True, "returncode": 0, "stdout": "diagnostic"}, workspace

        agent = DefaultAgent(
            self.model,
            self.env,
            system_template="SYSTEM",
            instance_template="TASK {{task}}",
            step_limit=8,
            wall_time_limit_seconds=10000,
            output_path=self.root / "trajectory.json",
        )
        with patch("coding_agent.perform_tool", side_effect=perform):
            agent.run(task="same task")
        return agent

    def test_summary_is_metered_nonexecuting_memory_with_stable_prefix(self):
        deadline, workspace = self.env.agent_deadline, self.env.workspace
        self.run_sequence()
        self.assertEqual(
            (self.model.calls, self.model.completion_tokens, self.env.calls), (4, 20, 4)
        )
        self.assertEqual(
            (self.env.agent_deadline, self.env.workspace), (deadline, workspace)
        )
        self.assertEqual(len(self.perform_options), 2)
        self.assertIsNone(self.perform_options[0].get("history_archive"))
        self.assertEqual(
            self.perform_options[1]["history_archive"], self.root / "history"
        )
        self.assertEqual(
            [r["max_tokens"] for r in self.requests], [4096, 2048, 4096, 4096]
        )
        self.assertEqual(
            [r["reasoning_budget_tokens"] for r in self.requests],
            [4096, 256, 4096, 4096],
        )
        self.assertTrue(
            all(r["tools"] == self.requests[0]["tools"] for r in self.requests)
        )
        view = self.requests[2]["messages"]
        self.assertEqual(view[:2], self.requests[0]["messages"][:2])
        self.assertEqual(len(view), 3)
        self.assertIn(SUMMARY, view[2]["content"])
        self.assertIn("unverified memory", view[2]["content"])
        self.assertFalse(self.read("tool-002.result.json")["executed"])
        self.assertFalse((self.root / "tool-002.cleanup.json").exists())
        self.assertEqual(
            self.read("context-checkpoint-response-001.json")["completion_tokens"], 10
        )
        self.assertEqual(
            self.read("fresh-context-reset-001.json")["summary_checkpoint"]["status"],
            "retained",
        )
        archive = validate_history_archive(
            self.root / "history", self.root / "tool-003"
        )
        manifest = self.read("history/manifest.json")
        saved = [
            json.loads((archive / r["file"]).read_text()) for r in manifest["messages"]
        ]
        self.assertEqual(
            saved[5]["tool_calls"][0]["function"]["name"], "checkpoint_context"
        )
        self.assertTrue((self.root / "final-handoff.json").exists())
        audit = verify_checkpoint_evidence(self.root, self.limits)
        self.assertEqual(audit["status"], "saved")
        self.assertEqual(audit["summary_completion_tokens"], 5)
        self.assertEqual(audit["known_completion_tokens"], 20)
        changed = self.read("context-checkpoint-001.json")
        changed["summary"] = "Fabricated success"
        (self.root / "context-checkpoint-001.json").write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "Saved memory differs"):
            verify_checkpoint_evidence(self.root, self.limits)

    def test_shared_evidence_survives_reset_with_original_outcome_and_same_budgets(
        self,
    ):
        from evidence import resolve
        from finish_attempt import envelope

        self.limits["shared_evidence"] = True
        # Only the solver workspace belongs in the factual digest; outer run
        # artifacts (including the sentinel below) must not be enumerated.
        workspace = self.root / "workspaces/0000"
        workspace.mkdir(parents=True)
        (workspace / "provided.py").write_text("public source data")
        self.env.workspace = self.env.initial_workspace = workspace
        (self.root / "private-sentinel").write_text("PRIVATE_EVALUATOR_DATA")
        evidence = [
            {
                "kind": "observation",
                "observation_id": "o0001",
                "supports": "The diagnostic command printed its output.",
            }
        ]
        self.run_sequence(
            checkpoint=call(
                "checkpoint_context",
                {
                    "summary": SUMMARY,
                    "evidence": evidence,
                },
                "call-2",
            )
        )
        saved = self.read("context-checkpoint-001.json")
        self.assertEqual(saved["observations"], resolve(evidence, self.model.history))
        terminal = envelope(
            {
                "disposition": "submitted",
                "summary": "Done",
                "evidence": evidence,
                "unverified": [],
                "blocker": None,
            },
            self.model.history,
        )
        self.assertEqual(terminal["observations"], saved["observations"])
        resumed = self.requests[2]["messages"][-1]["content"]
        self.assertIn('"status": "historical_only"', resumed)
        self.assertIn("o0001", resumed)
        self.assertIn("diagnostic", resumed)
        self.assertIn("Harness-recorded file/check facts", resumed)
        self.assertNotIn("private-sentinel", resumed)
        self.assertNotIn("PRIVATE_EVALUATOR_DATA", resumed)
        facts = self.read("fresh-context-reset-001.json")["resumption_digest"]
        self.assertEqual(facts["changed_files_total"], 0)
        self.assertEqual(facts["recent_checks"], [])  # bash observations are not checks
        self.assertEqual((self.model.calls, self.env.calls), (4, 4))
        self.assertEqual(len(self.perform_options), 2)
        self.assertEqual(
            verify_checkpoint_evidence(self.root, self.limits)["status"], "saved"
        )
        saved["observations"][0]["record"]["returncode"] = 7
        (self.root / "context-checkpoint-001.json").write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError, "Saved observations differ"):
            verify_checkpoint_evidence(self.root, self.limits)

    def test_unknown_shared_reference_uses_existing_fallback_without_extra_execution(
        self,
    ):
        self.limits["shared_evidence"] = True
        self.run_sequence(
            checkpoint=call(
                "checkpoint_context",
                {
                    "summary": SUMMARY,
                    "evidence": [
                        {
                            "kind": "observation",
                            "observation_id": "o0099",
                            "supports": "Unknown result",
                        }
                    ],
                },
                "call-2",
            )
        )
        self.assertFalse((self.root / "context-checkpoint-001.json").exists())
        self.assertEqual(len(self.perform_options), 1)
        self.assertEqual(
            self.read("fresh-context-reset-001.json")["summary_checkpoint"]["status"],
            "fallback_without_summary",
        )
        verify_checkpoint_evidence(self.root, self.limits)

    def test_progress_survives_reset_with_historical_evidence_and_no_new_budget(self):
        from evidence import resolve

        self.limits["shared_evidence"] = True
        self.limits["checkpoint_progress"] = True
        report = {
            "change": "uncertain",
            "implemented": [],
            "checks": [{"result": "unknown", "summary": "Diagnostic only"}],
            "remaining": ["Verify required behavior"],
            "obstacle": "",
            "next_action": "Inspect the relevant implementation",
            "evidence": [
                {
                    "kind": "observation",
                    "observation_id": "o0001",
                    "supports": "Historical diagnostic, not correctness",
                }
            ],
        }
        self.run_sequence(
            checkpoint=call(
                "checkpoint_context", {"summary": SUMMARY, "progress": report}, "call-2"
            )
        )
        saved = self.read("context-checkpoint-001.json")
        self.assertEqual(saved["progress"], report)
        self.assertEqual(
            saved["observations"], resolve(report["evidence"], self.model.history)
        )
        self.assertEqual(
            saved["progress_measurement"]["status"], "unverified_model_report"
        )
        resumed = self.requests[2]["messages"][-1]["content"]
        self.assertIn('"progress"', resumed)
        self.assertIn('"status": "historical_only"', resumed)
        self.assertEqual((self.model.calls, self.env.calls), (4, 4))
        self.assertEqual(len(self.perform_options), 2)
        self.assertEqual(
            verify_checkpoint_evidence(self.root, self.limits)["status"], "saved"
        )
        saved["progress"]["change"] = "advanced"
        (self.root / "context-checkpoint-001.json").write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError, "Saved progress differs"):
            verify_checkpoint_evidence(self.root, self.limits)

    def test_missing_progress_can_be_repaired_without_execution_or_budget_reset(self):
        self.limits["shared_evidence"] = True
        self.limits["checkpoint_progress"] = True
        report = {
            "change": "uncertain",
            "implemented": [],
            "checks": [],
            "remaining": [],
            "obstacle": "",
            "next_action": "Inspect code",
            "evidence": [],
        }
        original_deadline = self.env.agent_deadline
        self.run_sequence(
            checkpoint=call("checkpoint_context", {"summary": SUMMARY}, "bad"),
            repair=call(
                "checkpoint_context",
                {"summary": SUMMARY, "progress": report},
                "repaired",
            ),
            finish_at=5,
        )
        self.assertEqual(self.env.agent_deadline, original_deadline)
        self.assertEqual(self.read("context-checkpoint-001.json")["progress"], report)
        self.assertEqual(
            verify_checkpoint_evidence(self.root, self.limits)["status"], "saved"
        )
        self.assertEqual(len(self.perform_options), 2)

    def test_progress_is_explicit_and_cannot_smuggle_a_parallel_evidence_field(self):
        report = {
            "change": "uncertain",
            "implemented": [],
            "checks": [],
            "remaining": [],
            "obstacle": "",
            "next_action": "Inspect code",
            "evidence": [],
        }
        with self.assertRaises(ValueError):
            validate({"summary": SUMMARY, "progress": report}, shared=True)
        with self.assertRaisesRegex(ValueError, "requires a progress"):
            validate({"summary": SUMMARY}, shared=True, progress=True)
        with self.assertRaises(ValueError):
            validate(
                {"summary": SUMMARY, "progress": report, "evidence": []},
                shared=True,
                progress=True,
            )
        with self.assertRaisesRegex(ValueError, "requires shared evidence"):
            validate({"summary": SUMMARY, "progress": report}, progress=True)
        self.assertEqual(
            validate(
                {"summary": SUMMARY, "progress": report}, shared=True, progress=True
            )["progress"],
            report,
        )

    def test_read_file_checkpoint_boundary_and_real_context_reset_force_contents(self):
        self.env.workspace = self.root / "workspace"
        self.env.workspace.mkdir()
        (self.env.workspace / "module.py").write_text("value = 7\n" * 40)
        self.env.read_file = self.env.deduplicate_file_reads = True
        self.limits.update(
            read_file=True, deduplicate_file_reads=True, shared_evidence=True
        )
        evidence = [
            {
                "kind": "observation",
                "observation_id": "o0001",
                "supports": "Read module.py",
            }
        ]
        self.run_sequence(
            checkpoint=call(
                "checkpoint_context",
                {
                    "summary": "Continue from unchanged files",
                    "evidence": evidence,
                },
                "call-2",
            ),
            read_diagnostic=True,
        )
        self.assertEqual(len(self.perform_options), 0)
        self.assertEqual(self.env.read_tools, {1, 3})
        self.assertTrue(
            self.read("tool-003.result.json")["visible"]["file_read"][
                "contents_returned"
            ]
        )
        self.assertIn(
            "Historical evidence", self.requests[2]["messages"][-1]["content"]
        )
        self.assertEqual(
            verify_checkpoint_evidence(self.root, self.limits)["status"], "saved"
        )
        self.assertEqual(self.model.calls, 4)

    def test_wrong_tool_is_charged_but_not_executed_then_plain_reset(self):
        self.run_sequence(
            checkpoint=call("bash", {"command": "must not execute"}, "call-2")
        )
        self.assertEqual(
            (self.model.calls, self.model.completion_tokens, self.env.calls), (4, 20, 2)
        )
        self.assertEqual(len(self.perform_options), 1)
        self.assertEqual(
            self.read("context-checkpoint-response-001.json")["status"],
            "rejected_response",
        )
        self.assertEqual(
            self.read("fresh-context-reset-001.json")["summary_checkpoint"]["status"],
            "fallback_without_summary",
        )
        self.assertEqual(len(self.requests[3]["messages"]), 3)
        self.assertFalse((self.root / "context-checkpoint-001.json").exists())
        self.assertEqual(
            verify_checkpoint_evidence(self.root, self.limits)["status"], "rejected"
        )
        self.assertEqual(
            self.read("context-checkpoint-repair-response-001.json")["status"],
            "rejected_response",
        )

    def test_prose_checkpoint_can_be_repaired_without_renewing_budgets(self):
        at_cutoff = self.input_tokens_for_headroom(2560)
        self.model.count_tokens = lambda payload, phase: at_cutoff
        deadline = self.env.agent_deadline
        self.run_sequence(
            checkpoint={"role": "assistant", "content": SUMMARY},
            finish_reason="stop",
            repair=call("checkpoint_context", {"summary": SUMMARY}, "repair-1"),
            prompt_tokens=at_cutoff,
        )
        self.assertEqual(
            (self.model.calls, self.model.completion_tokens, self.env.calls), (5, 25, 4)
        )
        self.assertEqual(len(self.perform_options), 2)
        self.assertEqual(self.env.agent_deadline, deadline)
        self.assertIn(
            "Repair the rejected checkpoint",
            self.requests[2]["messages"][-1]["content"],
        )
        self.assertEqual(self.requests[2]["max_tokens"], 2048)
        self.assertEqual(self.requests[2]["reasoning_budget_tokens"], 256)
        self.assertIn(SUMMARY, self.requests[3]["messages"][-1]["content"])
        audit = verify_checkpoint_evidence(self.root, self.limits)
        self.assertEqual(audit["status"], "saved")
        self.assertEqual(audit["initial_attempt"]["status"], "rejected")
        self.assertEqual(audit["known_completion_tokens"], 25)
        self.assertEqual(self.read("context-checkpoint-001.json")["model_call"], 3)
        decision = self.read("context-checkpoint-repair-request-001.json")
        self.assertEqual(decision["context"]["available_completion_tokens"], 2560)
        self.assertEqual(decision["context"]["required_completion_headroom"], 2560)
        decision["timing"]["original_agent_deadline_monotonic"] += 100
        (self.root / "context-checkpoint-repair-request-001.json").write_text(
            json.dumps(decision)
        )
        with self.assertRaisesRegex(ValueError, "deadline"):
            verify_checkpoint_evidence(self.root, self.limits)

    def test_duplicate_fields_are_rejected_then_repaired_not_silently_coerced(self):
        bad = call("checkpoint_context", {"summary": SUMMARY})
        bad["tool_calls"][0]["function"]["arguments"] = (
            '{"summary":"one","summary":"two"}'
        )
        self.run_sequence(
            checkpoint=bad,
            repair=call("checkpoint_context", {"summary": SUMMARY}, "repair"),
        )
        self.assertIn(
            "Duplicate JSON field",
            self.read("context-checkpoint-response-001.json")["error"],
        )
        self.assertEqual(self.read("context-checkpoint-001.json")["summary"], SUMMARY)
        self.assertEqual(
            verify_checkpoint_evidence(self.root, self.limits)["status"], "saved"
        )

    def test_repair_is_skipped_when_fresh_context_measurement_is_too_large(self):
        self.model.count_tokens = lambda payload, phase: (
            self.input_tokens_for_headroom(2559) if phase == "checkpoint-repair" else 100
        )
        self.run_sequence(checkpoint=call("bash", {"command": "must not execute"}))
        self.assertEqual(len(self.perform_options), 2)
        decision = self.read("context-checkpoint-repair-decision-001.json")
        self.assertEqual(decision["context"]["available_completion_tokens"], 2559)
        self.assertEqual(decision["context"]["required_completion_headroom"], 2560)
        self.assertEqual(decision["reason"], "insufficient measured context headroom")
        self.assertFalse(
            (self.root / "context-checkpoint-repair-request-001.json").exists()
        )
        self.assertEqual(
            verify_checkpoint_evidence(self.root, self.limits)["status"], "rejected"
        )

    def test_repair_reserves_completion_tokens_for_continuation(self):
        self.limits["total_completion_token_limit"] = 2058
        self.run_sequence(checkpoint=call("bash", {"command": "must not execute"}))
        self.assertEqual(
            self.read("context-checkpoint-repair-decision-001.json")["reason"],
            "insufficient remaining completion tokens",
        )
        self.assertEqual(self.model.calls, 4)
        verify_checkpoint_evidence(self.root, self.limits)

    def test_repair_reserves_a_model_call_for_continuation(self):
        self.limits["step_limit"] = 3
        self.run_sequence(
            checkpoint=call("bash", {"command": "must not execute"}), finish_at=3
        )
        self.assertIn(
            "remaining calls",
            self.read("context-checkpoint-repair-decision-001.json")["reason"],
        )
        self.assertEqual(self.model.calls, 3)
        verify_checkpoint_evidence(self.root, self.limits)

    def test_repair_time_check_preserves_original_deadline(self):
        deadline = self.env.agent_deadline

        def late_response(n):
            if n == 2:
                self.controller.minimum_remaining = 400

        self.run_sequence(
            checkpoint=call("bash", {"command": "must not execute"}),
            after_response=late_response,
        )
        self.assertEqual(
            self.read("context-checkpoint-repair-decision-001.json")["reason"],
            "minimum remaining time",
        )
        self.assertFalse(
            (self.root / "context-checkpoint-repair-request-001.json").exists()
        )
        self.assertEqual(self.env.agent_deadline, deadline)

    def test_each_context_reset_gets_one_repair_with_separate_receipts(self):
        policy = {
            "trigger": "context_headroom",
            "min_remaining_agent_seconds": 180,
            "headroom_tokens": 8192,
            "max_resets": 2,
            "summary_checkpoint": True,
        }
        self.limits["fresh_context"] = policy
        self.controller = FreshContext(self.root, policy, self.env, model=self.model)
        self.model.fresh_context = self.env.fresh_context = self.controller
        self.controller.start(self.env.agent_deadline, 705)
        self.model.count_tokens = lambda *args: 26000
        final = call(
            "finish_attempt",
            {
                "disposition": "submitted",
                "summary": "Ready",
                "evidence": [],
                "unverified": ["Independent checks pending"],
                "blocker": None,
            },
            "final",
        )
        self.run_sequence(
            prompt_tokens=26000,
            response_plan=[
                call("bash", {"command": "echo diagnostic"}, "a"),
                {"role": "assistant", "content": SUMMARY},
                call("checkpoint_context", {"summary": SUMMARY}, "b"),
                call("bash", {"command": "echo diagnostic"}, "c"),
                {"role": "assistant", "content": SUMMARY},
                call("checkpoint_context", {"summary": SUMMARY}, "d"),
                final,
            ],
        )
        self.assertEqual(self.controller.reset_count, 2)
        self.assertEqual((self.model.calls, self.model.completion_tokens), (7, 35))
        self.assertEqual(len(self.perform_options), 2)
        audit = verify_checkpoint_evidence(self.root, self.limits)
        self.assertEqual(audit["checkpoint_requests"], [2, 3, 5, 6])
        self.assertEqual(
            [r["status"] for r in audit["checkpoints"]], ["saved", "saved"]
        )
        self.assertTrue(
            all(
                r["initial_attempt"]["status"] == "rejected"
                for r in audit["checkpoints"]
            )
        )

    def test_unknown_final_usage_does_not_skip_prior_checkpoint_receipts(self):
        self.run_sequence()
        (self.root / "request-004.response.bin").unlink()
        audit = verify_checkpoint_evidence(self.root, self.limits)
        self.assertEqual(audit["status"], "saved")
        self.assertEqual(audit["known_completion_tokens"], 15)
        self.assertFalse(audit["all_usage_known"])
        self.assertEqual(audit["unknown_requests"], [4])
        self.assertEqual(audit["summary_completion_tokens"], 5)
        (self.root / "tool-002.result.json").unlink()
        with self.assertRaises(OSError):
            verify_checkpoint_evidence(self.root, self.limits)

    def test_unknown_usage_before_later_request_is_not_recoverable_accounting(self):
        self.run_sequence()
        (self.root / "request-003.response.bin").unlink()
        with self.assertRaisesRegex(
            ValueError, "Continued after unknown request usage"
        ):
            verify_checkpoint_evidence(self.root, self.limits)

    def test_truncated_checkpoint_repair_is_bounded(self):
        self.run_sequence(finish_reason="length")
        self.assertEqual(self.env.calls, 2)
        self.assertEqual(self.controller.decision, "applied")
        self.assertFalse((self.root / "context-checkpoint-001.json").exists())
        self.assertEqual(
            verify_checkpoint_evidence(self.root, self.limits)["status"], "rejected"
        )

    def test_nonlist_calls_are_rejected_without_adapter_execution(self):
        self.run_sequence(
            checkpoint={"role": "assistant", "content": "", "tool_calls": 7}
        )
        self.assertEqual(self.env.calls, 2)
        self.assertEqual(len(self.perform_options), 1)
        self.assertEqual(
            verify_checkpoint_evidence(self.root, self.limits)["status"], "rejected"
        )

    def test_premature_checkpoint_is_charged_but_does_not_start_reset(self):
        response = {
            "usage": {"prompt_tokens": 100, "completion_tokens": 5},
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": call("checkpoint_context", {"summary": SUMMARY}),
                }
            ],
        }
        self.model.opener = SimpleNamespace(
            open=lambda *a, **k: io.BytesIO(json.dumps(response).encode())
        )
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "T"},
        ]
        with self.assertRaises(FormatError):
            self.model.query(messages)
        self.assertEqual(
            (self.model.calls, self.model.completion_tokens, self.env.calls), (1, 5, 0)
        )
        self.assertFalse(self.controller.checkpoint_requested)
        self.assertFalse(self.controller.checkpoint_attempted)
        self.assertFalse(list(self.root.glob("context-checkpoint-*.json")))

    def test_late_summary_does_not_renew_deadline_or_force_reset(self):
        now = time.monotonic()

        def advance(n):
            if n == 2:
                clock.return_value = self.env.agent_deadline - 179

        with patch("time.monotonic", return_value=now) as clock:
            self.run_sequence(after_response=advance)
        self.assertEqual(self.controller.decision, "bypassed")
        self.assertFalse((self.root / "history").exists())
        self.assertGreater(len(self.requests[2]["messages"]), 3)
        self.assertIsNone(self.perform_options[1].get("history_archive"))
        self.assertEqual(
            verify_checkpoint_evidence(self.root, self.limits)["status"], "saved"
        )

    def test_forged_control_receipt_cannot_skip_cleanup(self):
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "T"},
        ]
        self.controller.checkpoint_requested = True
        self.controller.checkpoint_response(accepted=True)
        self.env.execute(
            {"tool": "checkpoint_context", "payload": {"summary": SUMMARY}}
        )
        (self.root / "tool-001.result.json").write_text('{"executed": true}')
        self.controller.completed_cycle({}, [{}])
        with self.assertRaises(UnsafeCleanup):
            self.controller.before_query(messages, self.model)
        self.assertIsNone(self.controller.boundary)

    def test_no_allowance_for_continuation_bypasses_checkpoint(self):
        self.model.calls = 7
        self.controller.completed_cycle({}, [{}])
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "T"},
        ]
        self.assertFalse(self.controller.before_query(messages, self.model))
        self.assertFalse(self.controller.checkpoint_pending)
        self.assertEqual(self.controller.decision, "bypassed")

    def test_policy_rejects_incompatible_modes(self):
        validate_policy(self.limits)
        for change in (
            {"structured_finalization": False},
            {"fresh_context": {**POLICY, "summary_checkpoint": 1}},
            {
                "fresh_context": {
                    "trigger": "first_submission",
                    "min_remaining_agent_seconds": 180,
                    "continuation_mode": "review",
                    "summary_checkpoint": True,
                }
            },
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_policy({**self.limits, **change})

    def test_strict_bounded_payload_and_single_requested_call(self):
        valid = call("checkpoint_context", {"summary": SUMMARY})
        self.assertEqual(
            action(valid, {}, "tool_calls", requested=True)[0]["payload"],
            {"summary": SUMMARY},
        )
        for value in (
            {"summary": ""},
            {"summary": "é" * 2049},
            {"summary": "ok", "command": "evil"},
        ):
            with self.subTest(value=str(value)[:30]), self.assertRaises(ValueError):
                validate(value)
        for raw in ('{"summary":"a","summary":"b"}', '{"summary":NaN}', "{"):
            malformed = copy.deepcopy(valid)
            malformed["tool_calls"][0]["function"]["arguments"] = raw
            with self.subTest(raw=raw), self.assertRaises(FormatError):
                action(malformed, {}, "tool_calls", requested=True)
        mixed = copy.deepcopy(valid)
        mixed["tool_calls"] += call("bash", {"command": "evil"})["tool_calls"]
        for message, requested in (
            (valid, False),
            (mixed, True),
            ({"tool_calls": None}, True),
        ):
            with self.assertRaises(FormatError):
                action(message, {}, "tool_calls", requested=requested)


if __name__ == "__main__":
    unittest.main()
