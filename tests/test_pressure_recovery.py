"""Repeated recovery through the actual agent loop; fake backend, inert tool stub."""

import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from checkpoint_evidence import verify_checkpoint_evidence
from fresh_context import FreshContext, validate_history_archive
from mini_bootstrap import DefaultAgent
from pressure_recovery_evidence import verify_pressure_recovery

from tests import test_context_checkpoint as checkpoint
from tests.test_context_checkpoint import call


class PressureRecoveryTests(unittest.TestCase):
    setUp = checkpoint.CheckpointTests.setUp
    read = checkpoint.CheckpointTests.read

    input_tokens_for_headroom = checkpoint.CheckpointTests.input_tokens_for_headroom

    def pressure(self, *, max_resets=2):
        policy = dict(
            trigger="context_headroom",
            headroom_tokens=8192,
            max_resets=max_resets,
            min_remaining_agent_seconds=30,
            summary_checkpoint=True,
        )
        self.limits["fresh_context"] = policy
        self.controller = FreshContext(self.root, policy, self.env, model=self.model)
        self.model.fresh_context = self.env.fresh_context = self.controller
        self.controller.start(self.env.agent_deadline, 705)

    def sequence(
        self,
        *,
        fallback=False,
        pressure_input_tokens=25000,
        finish_at=5,
        reasoning=False,
    ):
        self.pressure()
        if reasoning:
            self.limits["reasoning_deadline"] = dict(
                decode_tokens_per_second=80,
                reasoning_fraction=0.75,
                response_reserve_seconds=15,
            )
            self.model.agent_deadline = self.env.agent_deadline
        self.limits.update(agent_wall_seconds=705, tool_call_limit=8)

        def count_tokens(payload, phase):
            if fallback:
                pressured = self.model.calls == 1 and (
                    self.controller.boundary is None or phase == "reset-before"
                )
            else:
                pressured = self.model.calls in (1, 3, 5) or phase == "reset-before"
            value = pressure_input_tokens if pressured else 100

            path = (
                self.root
                / f"context-{self.model.calls + 1:03d}.{phase}.tokenize.response.json"
            )
            path.write_text(json.dumps({"tokens": [1] * value}))
            return value

        self.model.count_tokens = count_tokens

        def response(request, **kwargs):
            self.requests.append(json.loads(request.data))
            n = len(self.requests)
            if (fallback and n == 2) or n == finish_at:
                message = call(
                    "finish_attempt",
                    dict(
                        disposition="submitted",
                        summary="Ready",
                        evidence=[],
                        unverified=["Unchecked"],
                        blocker=None,
                    ),
                    f"c{n}",
                )
            elif n in (2, 4):
                message = call(
                    "checkpoint_context",
                    {"summary": f"Memory {n}; unfinished check."},
                    f"c{n}",
                )
            else:
                message = call("bash", {"command": "echo inert"}, f"c{n}")
            return io.BytesIO(
                json.dumps(
                    dict(
                        usage=dict(
                            prompt_tokens=self.read(f"context-{n:03d}.json")[
                                "input_tokens_after"
                            ],
                            completion_tokens=5,
                        ),
                        choices=[dict(finish_reason="tool_calls", message=message)],
                    )
                ).encode()
            )

        self.model.opener = SimpleNamespace(open=response)

        def perform(runtime, workspace, name, arguments, timeout, prefix, **options):
            self.perform_options.append(options)
            prefix.with_suffix(".cleanup.json").write_text(
                json.dumps({"verified": True})
            )
            return {"ok": True, "returncode": 0, "stdout": "inert"}, workspace

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

    def test_repeated_measured_recovery_preserves_budgets_and_history(self):
        deadline = self.env.agent_deadline
        self.sequence(pressure_input_tokens=self.input_tokens_for_headroom(2560))
        self.assertEqual(self.env.agent_deadline, deadline)
        self.assertEqual(
            (self.model.calls, self.model.completion_tokens, self.env.calls), (5, 25, 5)
        )
        self.assertEqual(len(self.perform_options), 2)
        self.assertEqual(len(list(self.root.glob("fresh-context-reset-*.json"))), 2)
        for n in (1, 2):
            reset = self.read(f"fresh-context-reset-{n:03d}.json")
            self.assertEqual(
                reset["timing"]["original_agent_deadline_monotonic"], deadline
            )
            self.assertEqual(
                reset["context_pressure"]["available_completion_tokens"], 2560
            )
            self.assertGreater(
                self.read(f"fresh-context-measurement-{n:03d}.json")[
                    "rendered_tokens_reclaimed"
                ],
                0,
            )
        view = self.requests[4]["messages"]
        self.assertEqual(view[:2], self.requests[0]["messages"][:2])
        self.assertIn("Memory 4", view[2]["content"])
        self.assertNotIn("Memory 2", view[2]["content"])
        self.assertEqual(len(view), 3)
        for name in ("history", "history-002"):
            validate_history_archive(self.root / name, self.root / "tool-005")
        self.assertIn(
            "Memory 2", (self.root / "history-002" / "m0006.json").read_text()
        )
        self.assertTrue(
            all(r["tools"] == self.requests[0]["tools"] for r in self.requests)
        )
        reset_evidence = verify_pressure_recovery(
            self.root,
            self.limits,
            {"usage": self.model.serialize()["info"]["local_model"]},
        )
        self.assertEqual(len(reset_evidence["resets"]), 2)
        evidence = verify_checkpoint_evidence(self.root, self.limits)
        self.assertEqual(evidence["checkpoint_requests"], [2, 4])
        self.assertEqual(evidence["known_completion_tokens"], 25)
        receipt = self.root / "context-checkpoint-response-002.json"
        bad = json.loads(receipt.read_text())
        bad["completion_tokens"] = 0
        receipt.write_text(json.dumps(bad))
        with self.assertRaises(ValueError):
            verify_checkpoint_evidence(self.root, self.limits)

    def test_large_observation_skips_summary_but_recovers(self):
        self.sequence(
            fallback=True, pressure_input_tokens=self.input_tokens_for_headroom(2559)
        )
        self.assertEqual(self.model.calls, 2)
        reset = self.read("fresh-context-reset-001.json")
        self.assertEqual(reset["context_pressure"]["available_completion_tokens"], 2559)
        self.assertTrue(reset["summary_skipped_insufficient_headroom"])
        evidence = verify_pressure_recovery(
            self.root,
            self.limits,
            {"usage": self.model.serialize()["info"]["local_model"]},
        )
        self.assertEqual(len(evidence["resets"]), 1)
        self.assertEqual(
            reset["summary_checkpoint"]["status"], "fallback_without_summary"
        )
        self.assertFalse(list(self.root.glob("context-checkpoint-request-*.json")))
        self.assertTrue((self.root / "fresh-context-measurement-001.json").exists())

    def test_reset_limit_does_not_replenish_or_loop(self):
        self.sequence(finish_at=7)
        self.assertEqual(self.model.calls, 7)
        self.assertEqual(len(list(self.root.glob("fresh-context-reset-*.json"))), 2)
        self.assertEqual(self.read("context-006.json")["input_tokens_after"], 25000)

    def test_rebuilding_pressure_request_preserves_unsent_reasoning_allocation(self):
        self.sequence(reasoning=True)
        self.assertEqual(self.model.calls, 5)
        for index in (2, 4):
            original = self.read(f"context-{index:03d}.pressure.reasoning-budget.json")
            sent = self.read(f"request-{index:03d}.reasoning-budget.json")
            self.assertEqual(original["configured_reasoning_cap"], 4096)
            self.assertEqual(sent["configured_reasoning_cap"], 256)
            self.assertEqual(
                original["agent_deadline_monotonic"], sent["agent_deadline_monotonic"]
            )
        verify_pressure_recovery(
            self.root,
            self.limits,
            {"usage": self.model.serialize()["info"]["local_model"]},
        )
