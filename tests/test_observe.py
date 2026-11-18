import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from observe import NATIVE_CASES, Evidence


class ObservatoryTests(unittest.TestCase):
    def test_comparison_review_is_bound_and_cannot_promote_failed_checks(self):
        summary = {"task": "example", "seed": 1, "success": True,
                   "source_handoff_review": "pending_outer_review"}
        raw = json.dumps(summary)
        (self.trial / "summary.json").write_text(raw)
        self.assertIsNone(self.data.run("campaign")["trials"][0]["passed"])
        review = {"status": "reviewed", "task": "example", "seed": 1,
                  "raw_summary_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                  "source_accepted": True, "handoff_accepted": True, "full_acceptance": True}
        path = self.trial / "acceptance-review.json"
        path.write_text(json.dumps(review))
        self.assertTrue(self.data.run("campaign")["trials"][0]["passed"])
        summary["success"] = False
        raw = json.dumps(summary)
        (self.trial / "summary.json").write_text(raw)
        self.assertIsNone(self.data.run("campaign")["trials"][0]["passed"])
        review["raw_summary_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
        path.write_text(json.dumps(review))
        self.assertFalse(self.data.run("campaign")["trials"][0]["passed"])
        invalid = {"classification": "operationally_invalid", "model_quality_inference": False,
                   "cause": "Transport defect", "raw_summary_sha256": review["raw_summary_sha256"]}
        (self.trial / "outer-adjudication.json").write_text(json.dumps(invalid))
        row = self.data.run("campaign")["trials"][0]
        self.assertIsNone(row["passed"])
        self.assertEqual(row["state"], "operationally invalid")
        self.assertEqual(self.data.trace("campaign", self.trial.name)["comparison_review"]["status"],
                         "operationally_invalid")

    def test_continuation_review_requires_checks_and_exact_summary_binding(self):
        summary = {
            "task": "delegated-task",
            "work_kind": "delegated_repository",
            "continuation": {"arm": "full"},
            "success": False,
            "task_adjudication": {"status": "pending_outer_review"},
            "independent_checks_passed": True,
            "clean_agent_halt": True,
            "clean_agent_completion": True,
            "within_budget": True,
            "agent_outcome": {"exit_status": "Submitted"},
        }
        raw = json.dumps(summary)
        (self.trial / "summary.json").write_text(raw)
        trial = self.data.run("campaign")["trials"][0]
        self.assertIsNone(trial["passed"])
        self.assertEqual(trial["state"], "awaiting outer adjudication")
        verdict = {
            "version": 1,
            "task": "delegated-task",
            "status": "adjudicated",
            "review_kind": "continuation_contract",
            "disposition": "verified_coding",
            "coding_correctness": True,
            "task_handling_correctness": True,
            "rationale": "Bounded review meets the supplied contract.",
            "evidence": ["changes.diff"],
            "raw_summary_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        }
        (self.trial / "outer-adjudication.json").write_text(json.dumps(verdict))
        self.assertTrue(self.data.run("campaign")["trials"][0]["passed"])
        summary["independent_checks_passed"] = False
        raw = json.dumps(summary)
        (self.trial / "summary.json").write_text(raw)
        self.assertIsNone(self.data.outer_adjudication(self.trial, summary))
        verdict["raw_summary_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
        (self.trial / "outer-adjudication.json").write_text(json.dumps(verdict))
        self.assertIsNone(self.data.outer_adjudication(self.trial, summary))

    def test_scoped_continuation_is_labeled_and_return_is_not_finalization(self):
        continuation = {
            "case": "example",
            "arm": "restored",
            "spent_counters": {"model_calls_already_spent": 12},
        }
        fixtures = {
            "continuation.json": continuation,
            "tool-013.request.json": {
                "mode": "adapter-control",
                "name": "return_scope",
                "executed": False,
                "arguments": {"findings": "Unverified finding"},
            },
            "tool-013.result.json": {
                "ok": True,
                "executed": False,
                "cleanup_required": False,
                "scope_control": "return_recorded",
            },
            "scope-return-s0001.json": {"transition": "returned", "scope_id": "s0001"},
        }
        for index, (name, value) in enumerate(fixtures.items()):
            path = self.trial / name
            path.write_text(json.dumps(value))
            os.utime(path, (index + 1, index + 1))
        run = self.data.run("campaign")
        self.assertEqual(run["kind"], "continuation")
        self.assertEqual(run["trials"][0]["continuation"], continuation)
        trace = self.data.trace("campaign", self.trial.name)
        self.assertEqual(trace["continuation"], continuation)
        events = trace["events"]
        self.assertEqual([e["kind"] for e in events], ["context", "tool", "context"])
        self.assertEqual(events[0]["phase"], "continuation")
        self.assertTrue(events[1]["adapter_control"])
        self.assertFalse(events[1]["executed"])
        self.assertIsNone(events[1]["terminal_control"])
        self.assertEqual(events[1]["scope_control"], "return_recorded")
        self.assertEqual(events[2]["phase"], "scope")
        self.assertIn("unverified", events[2]["state"])
        self.assertIn("continuation.json", trace["artifacts"])
        self.assertFalse(self.data.allowed_artifact("scopes/committed.json"))

    def test_delegated_job_is_not_a_failed_benchmark(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "runs"
            identifier = "a" * 32
            run = root / ("delegate-" + identifier)
            trial = run / "experiment/trial-00-delegated-task"
            trial.mkdir(parents=True)
            (run / "command.json").write_text("[]")
            (trial / "summary.json").write_text(
                json.dumps(
                    {
                        "work_kind": "delegated_repository",
                        "success": False,
                        "canonical_correctness": None,
                        "clean_agent_completion": True,
                        "task_adjudication": {"status": "pending_outer_review"},
                    }
                )
            )
            job = base / "delegation/jobs" / identifier
            (job / "events").mkdir(parents=True)
            (job / "state.json").write_text(
                json.dumps(
                    {
                        "label": "Useful real work",
                        "state": "completed",
                        "cleanup_verified": True,
                        "job_id": identifier,
                        "package_id": "bound-package",
                        "owner": None,
                    }
                )
            )
            data = Evidence(root).run(run.name)
            self.assertEqual(data["kind"], "delegated")
            self.assertEqual(data["trials"][0]["state"], "awaiting outer review")
            self.assertIsNone(data["trials"][0]["passed"])
            self.assertEqual(data["delegation"]["label"], "Useful real work")
            # Both paginated list and detail follow the later bound outer review,
            # without turning a delegate into a scored benchmark trial.
            (job / "artifact").mkdir()
            artifact = b'{"changes": []}'
            (job / "artifact/artifact.json").write_bytes(artifact)
            review = {
                "job_id": identifier,
                "package_id": "bound-package",
                "artifact": "artifact",
                "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
                "decision": "accepted",
            }
            def assert_label(label):
                for details in (False, True):
                    item = Evidence(root).run(run.name, details)["trials"][0]
                    self.assertEqual(item["state"], label)
                    self.assertIsNone(item["passed"])
                page = Evidence(root).runs()
                self.assertEqual(page["runs"][0]["trials"][0]["state"], label)

            for decision in ("accepted", "accepted_with_repairs", "rejected"):
                review["decision"] = decision
                (job / "review.json").write_text(json.dumps(review))
                assert_label("outer review " + decision.replace("_", " "))
            review["decision"] = "accepted"
            raw = json.dumps(review).encode()
            (job / "review.json").write_bytes(raw)
            application = {
                "job_id": identifier, "state": "applying", "applied": False,
                "review_sha256": hashlib.sha256(raw).hexdigest(),
                "artifact_sha256": review["artifact_sha256"],
            }
            (job / "application.json").write_text(json.dumps(application))
            assert_label("outer review accepted")
            application.update(state="applied", applied=True)
            (job / "application.json").write_text(json.dumps(application))
            assert_label("outer review accepted · applied")
            application["review_sha256"] = "stale"
            (job / "application.json").write_text(json.dumps(application))
            assert_label("outer review accepted")
            for field in ("job_id", "package_id", "artifact_sha256"):
                altered = dict(review, **{field: "wrong"})
                (job / "review.json").write_text(json.dumps(altered))
                assert_label("outer review needs reconciliation")

    def test_rejected_checkpoint_and_summaryless_reset_are_timeline_events(self):
        fixtures = [
            ("request-001.request.json", {}),
            ("context-checkpoint-request-001.json", {"status": "requested"}),
            ("request-002.request.json", {}),
            (
                "context-checkpoint-response-001.json",
                {
                    "status": "rejected_response",
                    "error": "Duplicate JSON field",
                    "executed": False,
                },
            ),
            (
                "fresh-context-reset-001.json",
                {
                    "status": "applied",
                    "summary_checkpoint": {"status": "fallback_without_summary"},
                },
            ),
        ]
        for index, (name, data) in enumerate(fixtures):
            path = self.trial / name
            path.write_text(json.dumps(data))
            os.utime(path, (index + 1, index + 1))
        trace = self.data.trace("campaign", self.trial.name)
        self.assertEqual(
            [e["id"] for e in trace["events"]],
            [
                name.removesuffix(".request.json").removesuffix(".json")
                for name, _ in fixtures
            ],
        )
        recovery = [e for e in trace["events"] if e["kind"] == "context"]
        self.assertEqual(
            [e["state"] for e in recovery],
            [
                "checkpoint requested",
                "checkpoint rejected",
                "context reset / no summary",
            ],
        )
        self.assertEqual(recovery[1]["reason"], "Duplicate JSON field")
        self.assertEqual(trace["event_window"]["total_events"], 5)
        self.assertEqual(trace["event_window"]["total_requests"], 2)
        for event in recovery:
            self.assertIn(event["artifact"], trace["artifacts"])
            artifact = self.data.artifact(
                "campaign", self.trial.name, event["artifact"]
            )
            self.assertEqual(json.loads(artifact["text"]), event["lifecycle"])

    def test_context_lifecycle_is_paginated_and_distinguishes_retained_summary(self):
        for index in range(85):
            path = self.trial / f"context-checkpoint-request-{index:03}.json"
            path.write_text('{"status":"requested"}')
            os.utime(path, (index + 1, index + 1))
        latest = self.data.trace("campaign", self.trial.name)
        self.assertEqual(len(latest["events"]), 80)
        self.assertEqual(latest["events"][0]["id"], "context-checkpoint-request-005")
        first = self.data.trace("campaign", self.trial.name, start=0)
        self.assertEqual(first["event_window"]["newer_start"], 80)
        for index, (name, payload, state) in enumerate(
            [
                (
                    "context-checkpoint-response-085.json",
                    {"status": "valid_response"},
                    "checkpoint accepted / unverified memory",
                ),
                (
                    "context-checkpoint-response-086.json",
                    {"status": "valid_response", "accepted_tool": "finish_attempt"},
                    "final handoff accepted for dispatch / unverified",
                ),
                (
                    "fresh-context-reset-085.json",
                    {"status": "applied", "summary_checkpoint": {"status": "retained"}},
                    "context reset / summary retained (unverified)",
                ),
                (
                    "fresh-context-bypassed-086.json",
                    {"status": "bypassed"},
                    "context reset bypassed",
                ),
                (
                    "fresh-context-refused-087.json",
                    {"status": "refused"},
                    "context reset refused",
                ),
            ]
        ):
            path = self.trial / name
            path.write_text(json.dumps(payload))
            os.utime(path, (90 + index, 90 + index))
            self.assertEqual(
                self.data.trace("campaign", self.trial.name)["events"][-1]["state"],
                state,
            )
        self.assertEqual(
            first["events"],
            self.data.trace("campaign", self.trial.name, start=0)["events"],
        )
        (self.trial / "fresh-context-reset-999.json").symlink_to(
            self.trial / "fresh-context-reset-085.json"
        )
        self.assertNotIn(
            "fresh-context-reset-999",
            [e["id"] for e in self.data.trace("campaign", self.trial.name)["events"]],
        )

    def test_input_probe_disagreement_does_not_establish_coding_correctness(self):
        summary = {
            "task": "probe",
            "diagnostic_kind": "input-probe",
            "coding_goal_credit": 0,
            "success": False,
            "verified_correctness": None,
            "clean_agent_halt": True,
            "clean_agent_completion": True,
            "within_budget": True,
            "agent_outcome": {"exit_status": "Submitted"},
            "task_adjudication": {"status": "pending_outer_rubric"},
        }
        path = self.trial / "summary.json"
        path.write_text(json.dumps(summary))
        verdict = {
            "version": 1,
            "status": "adjudicated",
            "task": "probe",
            "raw_summary_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "disposition": "reviewed_diagnostic",
            "coding_correctness": None,
            "task_handling_correctness": None,
            "diagnostic_results": {
                "format_valid": True,
                "inputs_valid": True,
                "deterministic": True,
                "difference_found": True,
            },
        }
        review = self.trial / "outer-adjudication.json"
        review.write_text(json.dumps(verdict))
        trial = self.data.run("campaign")["trials"][0]
        self.assertEqual(trial["diagnostic_kind"], "input-probe")
        self.assertEqual(trial["state"], "diagnostic reviewed")
        self.assertIsNone(trial["passed"])
        self.assertIsNone(trial["correct"])
        for change in (
            {"coding_correctness": True},
            {
                "diagnostic_results": {
                    "inputs_valid": True,
                    "deterministic": True,
                    "difference_found": "yes",
                }
            },
            {"raw_summary_sha256": "stale"},
        ):
            review.write_text(json.dumps(verdict | change))
            self.assertIsNone(self.data.outer_adjudication(self.trial, summary))
        # Reviewing a timeout records diagnostic evidence, never coding success.
        summary.update(
            clean_agent_halt=False,
            clean_agent_completion=False,
            agent_outcome={},
            agent_error={"type": "DeadlineExceeded"},
        )
        path.write_text(json.dumps(summary))
        verdict["raw_summary_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        verdict["diagnostic_results"].update(
            format_valid=False, deterministic=False, difference_found=False
        )
        review.write_text(json.dumps(verdict))
        trial = self.data.run("campaign")["trials"][0]
        self.assertEqual(trial["state"], "diagnostic reviewed")
        self.assertFalse(trial["clean"])
        self.assertIsNone(trial["correct"])

    def test_test_author_review_cannot_become_a_coding_pass(self):
        summary = {
            "task": "author",
            "diagnostic_kind": "independent-test-author",
            "coding_goal_credit": 0,
            "success": False,
            "verified_correctness": None,
            "clean_agent_halt": True,
            "clean_agent_completion": True,
            "within_budget": True,
            "agent_outcome": {"exit_status": "Submitted"},
            "task_adjudication": {"status": "pending_outer_rubric"},
        }
        path = self.trial / "summary.json"
        path.write_text(json.dumps(summary))
        verdict = {
            "version": 1,
            "status": "adjudicated",
            "task": "author",
            "raw_summary_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "disposition": "reviewed_diagnostic",
            "coding_correctness": None,
            "task_handling_correctness": None,
            "diagnostic_results": {
                "sound_on_controls": True,
                "incorrect_controls_detected": 1,
                "incorrect_controls_total": 3,
            },
        }
        review = self.trial / "outer-adjudication.json"
        review.write_text(json.dumps(verdict))
        run = self.data.run("campaign")
        self.assertEqual(run["kind"], "diagnostic")
        self.assertEqual(run["trials"][0]["state"], "diagnostic reviewed")
        self.assertIsNone(run["trials"][0]["passed"])
        self.assertIsNone(run["trials"][0]["correct"])
        self.assertEqual(
            self.data.trace("campaign", self.trial.name)["kind"], "diagnostic"
        )
        for changes in (
            {
                "disposition": "verified_coding",
                "coding_correctness": True,
                "task_handling_correctness": True,
            },
            {"raw_summary_sha256": "stale"},
            {
                "diagnostic_results": {
                    "sound_on_controls": True,
                    "incorrect_controls_detected": 4,
                    "incorrect_controls_total": 3,
                }
            },
        ):
            with self.subTest(changes=changes):
                review.write_text(json.dumps(verdict | changes))
                self.assertIsNone(self.data.outer_adjudication(self.trial, summary))
        review.write_text(json.dumps(verdict))
        ordinary = {k: v for k, v in summary.items() if k != "diagnostic_kind"}
        self.assertIsNone(self.data.outer_adjudication(self.trial, ordinary))

    def test_progress_measurement_is_attached_to_its_checkpoint_tool(self):
        (self.trial / "tool-001.request.json").write_text(
            json.dumps(
                {
                    "mode": "adapter-control",
                    "name": "checkpoint_context",
                    "executed": False,
                    "arguments": {
                        "summary": "Continue",
                        "progress": {"change": "uncertain"},
                    },
                }
            )
        )
        measurement = {"status": "unverified_model_report", "report_utf8_bytes": 320}
        (self.trial / "context-checkpoint-001.json").write_text(
            json.dumps(
                {
                    "tool_call": 1,
                    "progress_measurement": measurement,
                }
            )
        )
        event = next(
            e
            for e in self.data.trace("campaign", "trial-00-task")["events"]
            if e["id"] == "tool-001"
        )
        self.assertEqual(event["progress_measurement"], measurement)
        self.assertEqual(event["arguments"]["progress"]["change"], "uncertain")
        self.assertIsNone(event["terminal_control"])

    def test_checkpoint_is_nonterminal_unverified_memory(self):
        (self.trial / "tool-001.request.json").write_text(
            json.dumps(
                {
                    "mode": "adapter-control",
                    "name": "checkpoint_context",
                    "executed": False,
                    "arguments": {"summary": "Tests still fail."},
                }
            )
        )
        (self.trial / "tool-001.result.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "executed": False,
                    "cleanup_required": False,
                    "checkpoint_control": "summary_saved",
                }
            )
        )
        event = self.data.trace("campaign", "trial-00-task")["events"][0]
        self.assertEqual(event["state"], "checkpoint saved / unverified memory")
        self.assertEqual(event["arguments"], {"summary": "Tests still fail."})
        self.assertTrue(event["adapter_control"])
        self.assertFalse(event["executed"])
        self.assertIsNone(event["terminal_control"])

    def test_provisional_review_is_not_displayed_as_terminal_submission(self):
        (self.trial / "tool-001.request.json").write_text(
            json.dumps(
                {
                    "mode": "adapter-control",
                    "name": "finish_attempt",
                    "executed": False,
                    "arguments": {"disposition": "submitted"},
                }
            )
        )
        (self.trial / "tool-001.result.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "executed": False,
                    "cleanup_required": False,
                    "review_control": "fresh_context_requested",
                }
            )
        )
        event = self.data.trace("campaign", "trial-00-task")["events"][0]
        self.assertEqual(event["state"], "review requested / not submitted")
        self.assertEqual(event["review_control"], "fresh_context_requested")
        self.assertIsNone(event["terminal_control"])
        self.assertFalse(event["executed"])
        self.assertIsNone(event["cleanup"])
        self.assertIsNone(self.data.run("campaign")["trials"][0]["correct"])

    def test_closed_tools_without_receipts_are_not_still_running(self):
        for index, (mode, name) in enumerate(
            [
                ("adapter-control", "checkpoint_context"),
                ("adapter-read", "read_file"),
                ("tool", "bash"),
            ],
            1,
        ):
            (self.trial / f"tool-{index:03}.request.json").write_text(
                json.dumps({"mode": mode, "name": name, "arguments": {}})
            )
        events = self.data.trace("campaign", "trial-00-task")["events"]
        self.assertEqual(
            {e["state"] for e in events}, {"adapter pending", "reading", "executing"}
        )
        (self.trial / "summary.json").write_text(json.dumps({"success": False}))
        events = self.data.trace("campaign", "trial-00-task")["events"]
        self.assertEqual(
            {e["state"] for e in events}, {"attempt ended / tool receipt unavailable"}
        )

    def test_trace_reports_omitted_and_unreadable_requests(self):
        for index in range(83):
            path = self.trial / f"request-{index:03}.request.json"
            path.write_text("{}" if index < 82 else "{")
            os.utime(path, (index + 1, index + 1))
        trace = self.data.trace("campaign", "trial-00-task")
        self.assertEqual(
            trace["event_window"],
            {
                "total_requests": 83,
                "total_events": 83,
                "start": 3,
                "end": 83,
                "limit": 80,
                "latest": True,
                "older_start": 0,
                "newer_start": None,
                "unreadable_requests": 1,
                "unreadable_events": 1,
            },
        )
        self.assertEqual(len(trace["events"]), 79)
        self.assertIn("request-000.request.json", trace["artifacts"])

    def test_event_pagination_is_bounded_and_stable_on_append(self):
        def append(index):
            path = self.trial / f"request-{index:03}.request.json"
            path.write_text("{}")
            os.utime(path, (index + 1, index + 1))

        for index in range(205):
            append(index)
        with patch.object(self.data, "read", wraps=self.data.read) as read:
            latest = self.data.trace("campaign", "trial-00-task")
        requests_read = [
            c for c in read.call_args_list if c.args[0].name.endswith(".request.json")
        ]
        self.assertEqual(len(requests_read), 80)
        self.assertEqual(latest["events"][0]["id"], "request-125")
        older_start = latest["event_window"]["older_start"]
        older = self.data.trace("campaign", "trial-00-task", start=older_start)
        self.assertEqual(older["events"][0]["id"], "request-045")
        self.assertEqual(older["events"][-1]["id"], "request-124")
        append(205)
        refreshed = self.data.trace("campaign", "trial-00-task", start=older_start)
        self.assertEqual(older["events"], refreshed["events"])
        self.assertFalse(refreshed["event_window"]["latest"])
        self.assertEqual(refreshed["event_window"]["total_requests"], 206)
        latest = self.data.trace("campaign", "trial-00-task")
        self.assertEqual(latest["events"][0]["id"], "request-126")
        self.assertEqual(latest["events"][-1]["id"], "request-205")
        first = self.data.trace("campaign", "trial-00-task", start=0)
        self.assertIsNone(first["event_window"]["older_start"])
        seen = [e["id"] for e in first["events"]]
        while first["event_window"]["newer_start"] is not None:
            first = self.data.trace(
                "campaign", "trial-00-task", start=first["event_window"]["newer_start"]
            )
            seen.extend(e["id"] for e in first["events"])
        self.assertEqual(seen, [f"request-{i:03}" for i in range(206)])
        self.assertEqual(len(first["events"]), 46)
        beyond = self.data.trace("campaign", "trial-00-task", start=999)
        self.assertEqual(beyond["event_window"]["start"], 205)
        self.assertEqual(len(beyond["events"]), 1)

    def test_event_pagination_validates_start_and_handles_empty_trial(self):
        for invalid in [-1, True, 1.5, "0", 10**9 + 1]:
            with self.subTest(start=invalid), self.assertRaises(ValueError):
                self.data.trace("campaign", "trial-00-task", start=invalid)
        for start in [None, 0, 80]:
            trace = self.data.trace("campaign", "trial-00-task", start=start)
            self.assertEqual(trace["events"], [])
            self.assertEqual(trace["event_window"]["start"], 0)
            self.assertEqual(trace["event_window"]["end"], 0)
            self.assertIsNone(trace["event_window"]["newer_start"])
            self.assertIsNone(trace["event_window"]["older_start"])

    def test_history_page_does_not_misattribute_final_request_timeout(self):
        for index in range(81):
            path = self.trial / f"request-{index:03}.request.json"
            path.write_text("{}")
            os.utime(path, (index + 1, index + 1))
        (self.trial / "summary.json").write_text(
            json.dumps({"success": False, "agent_error": {"type": "TimeoutError"}})
        )
        older = self.data.trace("campaign", "trial-00-task", start=0)
        self.assertEqual(
            {e["state"] for e in older["events"]},
            {"attempt ended / response unavailable"},
        )
        latest = self.data.trace("campaign", "trial-00-task")
        self.assertEqual(latest["events"][-1]["state"], "request timed out")

    def test_posthoc_contract_failure_qualifies_but_does_not_rewrite_frozen_pass(self):
        summary = {
            "task": "sample",
            "success": True,
            "verified_correctness": True,
            "canonical_correctness": True,
            "behavioral_correctness": True,
            "clean_agent_completion": True,
            "clean_agent_halt": True,
            "within_budget": True,
            "agent_outcome": {"exit_status": "Submitted"},
        }
        path = self.trial / "summary.json"
        path.write_text(json.dumps(summary))
        original = path.read_bytes()
        verdict = {
            "version": 1,
            "status": "adjudicated",
            "task": "sample",
            "raw_summary_sha256": hashlib.sha256(original).hexdigest(),
            "review_kind": "posthoc_contract",
            "disposition": "failed_coding",
            "coding_correctness": False,
            "task_handling_correctness": False,
            "rationale": "Isolated probe confirms a public-contract violation.",
            "evidence": [{"path": "diagnostic/summary.json"}],
        }
        review = self.trial / "outer-adjudication.json"
        review.write_text(json.dumps(verdict))
        trial = self.data.run("campaign")["trials"][0]
        self.assertEqual(trial["state"], "failed")
        self.assertIs(trial["correct"], False)
        trace = self.data.trace("campaign", "trial-00-task")
        self.assertTrue(trace["summary"]["success"])
        self.assertEqual(trace["outer_adjudication"], verdict)
        self.assertEqual(path.read_bytes(), original)
        for changes in (
            {"raw_summary_sha256": "stale"},
            {"review_kind": "unspecified"},
            {"rationale": ""},
            {"evidence": []},
            {
                "disposition": "verified_coding",
                "coding_correctness": True,
                "task_handling_correctness": True,
            },
        ):
            with self.subTest(changes=changes):
                review.write_text(json.dumps({**verdict, **changes}))
                self.assertIsNone(self.data.outer_adjudication(self.trial, summary))

    def test_posthoc_handoff_failure_preserves_code_success_and_rejects_promotion(self):
        summary = {
            "task": "sample",
            "success": True,
            "verified_correctness": True,
            "canonical_correctness": True,
            "clean_agent_completion": True,
            "clean_agent_halt": True,
            "within_budget": True,
            "agent_outcome": {"exit_status": "Submitted"},
        }
        path = self.trial / "summary.json"
        path.write_text(json.dumps(summary))
        original = path.read_bytes()
        verdict = {
            "version": 1,
            "status": "adjudicated",
            "task": "sample",
            "raw_summary_sha256": hashlib.sha256(original).hexdigest(),
            "review_kind": "posthoc_handoff",
            "disposition": "verified_coding_bad_handoff",
            "coding_correctness": True,
            "task_handling_correctness": False,
            "rationale": "Final handoff cites a failing observation as successful.",
            "evidence": [{"path": "sealed-source-review.json"}],
        }
        review = self.trial / "outer-adjudication.json"
        review.write_text(json.dumps(verdict))
        trial = self.data.run("campaign")["trials"][0]
        self.assertEqual(trial["state"], "correct code / handoff failed")
        self.assertTrue(trial["correct"])
        self.assertFalse(trial["passed"])
        self.assertEqual(path.read_bytes(), original)
        for field in (
            "canonical_correctness",
            "verified_correctness",
            "clean_agent_completion",
            "within_budget",
        ):
            changed = {**summary, field: False}
            path.write_text(json.dumps(changed))
            review.write_text(
                json.dumps(
                    {
                        **verdict,
                        "raw_summary_sha256": hashlib.sha256(
                            path.read_bytes()
                        ).hexdigest(),
                    }
                )
            )
            self.assertIsNone(self.data.outer_adjudication(self.trial, changed))
        path.write_bytes(original)
        for change in (
            {"raw_summary_sha256": "stale"},
            {"evidence": []},
            {"disposition": "verified_coding", "task_handling_correctness": True},
        ):
            review.write_text(json.dumps({**verdict, **change}))
            self.assertIsNone(self.data.outer_adjudication(self.trial, summary))

    def test_runtime_nonconformance_rejects_pass_without_calling_code_incorrect(self):
        summary = {
            "task": "sample",
            "success": True,
            "canonical_correctness": True,
            "behavioral_correctness": True,
            "clean_agent_completion": True,
            "within_budget": True,
            "agent_outcome": {"exit_status": "Submitted"},
        }
        path = self.trial / "summary.json"
        path.write_text(json.dumps(summary))
        original = path.read_bytes()
        verdict = {
            "version": 1,
            "status": "adjudicated",
            "task": "sample",
            "raw_summary_sha256": hashlib.sha256(original).hexdigest(),
            "review_kind": "posthoc_protocol",
            "disposition": "nonconforming_run",
            "coding_correctness": None,
            "task_handling_correctness": False,
            "protocol_conforming": False,
            "rationale": "Agent-only library entered behavioral evaluator.",
            "evidence": [{"path": "behavioral/step-001/command.invocation.json"}],
        }
        review = self.trial / "outer-adjudication.json"
        review.write_text(json.dumps(verdict))
        trial = self.data.run("campaign")["trials"][0]
        self.assertEqual(trial["state"], "runtime nonconformance")
        self.assertIs(trial["passed"], False)
        self.assertIsNone(trial["correct"])
        self.assertEqual(trial["adjudication"], verdict)
        self.assertEqual(path.read_bytes(), original)
        for changes in (
            {"raw_summary_sha256": "stale"},
            {"coding_correctness": True},
            {"protocol_conforming": True},
            {"rationale": ""},
            {"evidence": []},
            {"disposition": "verified_coding"},
            {"review_kind": "posthoc_contract"},
        ):
            with self.subTest(changes=changes):
                review.write_text(json.dumps({**verdict, **changes}))
                self.assertIsNone(self.data.outer_adjudication(self.trial, summary))

    def test_campaign_list_includes_old_campaigns_beyond_one_hundred(self):
        for index in range(105):
            campaign = self.root / f"older-{index:03}"
            campaign.mkdir()
            (campaign / "command.json").write_text("[]")
            os.utime(campaign / "command.json", (index + 1, index + 1))
        (self.root / "not-a-campaign").mkdir()
        (self.root / "campaign-alias").symlink_to(self.run, target_is_directory=True)
        with patch.object(self.data, "run", wraps=self.data.run) as load:
            page = self.data.runs()
            self.assertEqual(load.call_count, 20)
        self.assertEqual(page["total"], 106)
        self.assertEqual(page["matching"], 106)
        self.assertEqual(page["pages"], 6)
        self.assertEqual(page["runs"][0]["name"], "campaign")
        self.assertEqual(page["newest"], "campaign")
        with patch.object(self.data, "run", wraps=self.data.run) as load:
            oldest = self.data.runs(page=999)
            self.assertEqual(load.call_count, 6)
        self.assertEqual(oldest["page"], 6)
        self.assertEqual(oldest["runs"][-1]["name"], "older-000")
        names = [
            r["name"] for page in range(1, 7) for r in self.data.runs(page=page)["runs"]
        ]
        self.assertEqual(len(set(names)), 106)
        with patch.object(self.data, "run", wraps=self.data.run) as load:
            found = self.data.runs(query="OLDER-000", page=6)
            self.assertEqual(load.call_count, 1)
        self.assertEqual(found["total"], 106)
        self.assertEqual(found["matching"], 1)
        self.assertEqual(found["page"], 1)
        self.assertEqual(found["runs"][0]["name"], "older-000")
        self.assertEqual(found["newest"], "campaign")
        # Direct selection is independent of the current page/filter.
        self.assertEqual(self.data.run("older-001")["name"], "older-001")
        with patch.object(self.data, "run", wraps=self.data.run) as load:
            empty = self.data.runs(query="absent")
            load.assert_not_called()
        self.assertEqual(
            (empty["total"], empty["matching"], empty["pages"]), (106, 0, 1)
        )
        self.assertEqual(empty["runs"], [])

    def test_campaign_pagination_validates_bounds(self):
        for args in (
            {"page": 0},
            {"page": -1},
            {"page": True},
            {"page_size": 0},
            {"page_size": 51},
            {"page_size": False},
            {"query": "x" * 201},
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.data.runs(**args)

    def test_campaign_pages_refresh_index_and_verdicts_without_cache(self):
        self.assertEqual(
            self.data.runs()["runs"][0]["state"], "unfinished / owner not observed"
        )
        (self.run / "background").mkdir()
        (self.run / "background/summary.json").write_text('{"ok": true}')
        self.assertEqual(self.data.runs()["runs"][0]["state"], "complete")
        other = self.root / "another"
        other.mkdir()
        (other / "command.json").write_text("[]")
        stamp = (self.run / "command.json").stat().st_mtime
        os.utime(other / "command.json", (stamp, stamp))
        page = self.data.runs(page_size=1)
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["newest"], "another")  # stable name tiebreak
        (other / "command.json").unlink()
        self.assertEqual(self.data.runs()["total"], 1)

    def test_campaign_page_reports_unavailable_rows(self):
        with patch.object(self.data, "run", side_effect=ValueError("publishing")):
            page = self.data.runs()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["matching"], 1)
        self.assertEqual(page["runs"], [])
        self.assertEqual(page["unavailable"], ["campaign"])

    def test_posthoc_failure_can_qualify_timeout_but_cannot_promote_it(self):
        for within_budget in (True, False):
            with self.subTest(within_budget=within_budget):
                summary = {
                    "task": "sample",
                    "success": False,
                    "canonical_correctness": True,
                    "verified_correctness": True,
                    "clean_agent_completion": False,
                    "clean_agent_halt": False,
                    "within_budget": within_budget,
                    "agent_outcome": None,
                    "agent_error": {"type": "DeadlineExceeded"},
                }
                path = self.trial / "summary.json"
                path.write_text(json.dumps(summary))
                original = path.read_bytes()
                verdict = {
                    "version": 1,
                    "status": "adjudicated",
                    "task": "sample",
                    "raw_summary_sha256": hashlib.sha256(original).hexdigest(),
                    "review_kind": "posthoc_contract",
                    "disposition": "failed_coding",
                    "coding_correctness": False,
                    "task_handling_correctness": False,
                    "rationale": "Isolated probe found an untested contract violation.",
                    "evidence": [{"path": "probe/summary.json"}],
                }
                review = self.trial / "outer-adjudication.json"
                review.write_text(json.dumps(verdict))
                self.assertEqual(
                    self.data.outer_adjudication(self.trial, summary), verdict
                )
                shown = self.data.run("campaign")["trials"][0]
                self.assertIs(shown["correct"], False)
                self.assertIs(shown["passed"], False)
                self.assertEqual(path.read_bytes(), original)
                review.write_text(
                    json.dumps(
                        {
                            **verdict,
                            "disposition": "verified_coding",
                            "coding_correctness": True,
                            "task_handling_correctness": True,
                        }
                    )
                )
                self.assertIsNone(self.data.outer_adjudication(self.trial, summary))

    def test_negative_outer_reviews_require_matching_disposition_and_hash(self):
        for disposition, terminal, state in (
            ("unsupported_blocker", "Blocked", "unsupported blocker"),
            ("failed_coding", "Submitted", "failed"),
        ):
            with self.subTest(disposition=disposition):
                summary = {
                    "task": "sample",
                    "success": False,
                    "verified_correctness": False,
                    "canonical_correctness": False,
                    "clean_agent_completion": terminal == "Submitted",
                    "clean_agent_halt": True,
                    "within_budget": True,
                    "agent_outcome": {"exit_status": terminal},
                    "task_adjudication": {"status": "pending_outer_rubric"},
                }
                path = self.trial / "summary.json"
                path.write_text(json.dumps(summary))
                verdict = {
                    "version": 1,
                    "status": "adjudicated",
                    "task": "sample",
                    "raw_summary_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "disposition": disposition,
                    "coding_correctness": False,
                    "task_handling_correctness": False,
                }
                review = self.trial / "outer-adjudication.json"
                review.write_text(json.dumps(verdict))
                trial = self.data.run("campaign")["trials"][0]
                self.assertEqual(trial["state"], state)
                self.assertIs(trial["passed"], False)
                self.assertIs(trial["correct"], False)
                self.assertEqual(json.loads(path.read_text()), summary)
                for field, wrong in (
                    ("raw_summary_sha256", "stale"),
                    ("task_handling_correctness", True),
                    ("coding_correctness", None),
                    (
                        "disposition",
                        "failed_coding"
                        if terminal == "Blocked"
                        else "unsupported_blocker",
                    ),
                ):
                    review.write_text(json.dumps({**verdict, field: wrong}))
                    self.assertIsNone(self.data.run("campaign")["trials"][0]["correct"])

    def test_pending_and_hash_bound_outer_verdicts(self):
        summary = {
            "task": "sample",
            "success": False,
            "verified_correctness": False,
            "canonical_correctness": True,
            "clean_agent_completion": True,
            "clean_agent_halt": True,
            "within_budget": True,
            "agent_outcome": {"exit_status": "Submitted"},
            "task_adjudication": {"status": "pending_outer_rubric", "correct": None},
        }
        path = self.trial / "summary.json"
        path.write_text(json.dumps(summary))
        trial = self.data.run("campaign")["trials"][0]
        self.assertIsNone(trial["correct"])
        self.assertEqual(trial["state"], "awaiting outer adjudication")
        verdict = {
            "version": 1,
            "status": "adjudicated",
            "task": "sample",
            "raw_summary_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "disposition": "verified_coding",
            "coding_correctness": True,
            "task_handling_correctness": True,
        }
        review = self.trial / "outer-adjudication.json"
        review.write_text(json.dumps(verdict))
        trial = self.data.run("campaign")["trials"][0]
        self.assertTrue(trial["correct"])
        self.assertEqual(trial["state"], "passed")
        verdict.update(
            disposition="verified_coding_bad_handoff",
            task_handling_correctness=False,
        )
        review.write_text(json.dumps(verdict))
        trial = self.data.run("campaign")["trials"][0]
        self.assertTrue(trial["correct"])
        self.assertFalse(trial["passed"])
        self.assertEqual(trial["state"], "correct code / handoff failed")
        verdict.update(disposition="verified_coding", task_handling_correctness=True)
        review.write_text(json.dumps(verdict))
        self.assertFalse(
            self.data.trace("campaign", "trial-00-task")["summary"]["success"]
        )
        path.write_text(json.dumps(summary) + "\n")
        self.assertIsNone(self.data.run("campaign")["trials"][0]["correct"])
        summary["agent_outcome"]["exit_status"] = "Blocked"
        summary["clean_agent_completion"] = False
        path.write_text(json.dumps(summary))
        verdict.update(
            raw_summary_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            disposition="supported_blocker",
            coding_correctness=None,
        )
        review.write_text(json.dumps(verdict))
        trial = self.data.run("campaign")["trials"][0]
        self.assertEqual(trial["state"], "supported blocker")
        self.assertIsNone(trial["correct"])
        self.assertIsNone(trial["passed"])
        self.assertFalse(trial["clean"])
        verdict.update(
            disposition="supported_blocker_bad_handoff",
            task_handling_correctness=False,
        )
        review.write_text(json.dumps(verdict))
        trial = self.data.run("campaign")["trials"][0]
        self.assertEqual(trial["state"], "supported blocker / handoff failed")
        self.assertIsNone(trial["correct"])
        self.assertFalse(trial["passed"])
        self.assertFalse(trial["adjudication"]["task_handling_correctness"])
        verdict["task_handling_correctness"] = True
        review.write_text(json.dumps(verdict))
        self.assertIsNone(self.data.outer_adjudication(self.trial, summary))
        summary["unsafe_cleanup"] = "fatal"
        path.write_text(json.dumps(summary))
        verdict["raw_summary_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        review.write_text(json.dumps(verdict))
        self.assertEqual(
            self.data.run("campaign")["trials"][0]["state"], "unsafe cleanup / stopped"
        )

    def test_standard_worker_trace_uses_backend_and_command_receipts_once(self):
        backend = self.trial / "backend"
        native = self.trial / "native"
        backend.mkdir()
        native.mkdir()
        request = {"messages": [{"role": "user", "content": "public brief"}], "max_tokens": 32768}
        (backend / "request-001.request.json").write_text(json.dumps(request))
        (native / "request-001.request.json").write_text(json.dumps(request))
        response = {"choices": [{"message": {"content": "Done"}, "finish_reason": "stop"}], "usage": {"completion_tokens": 3}}
        (backend / "request-001.response.bin").write_text(json.dumps(response))
        (backend / "request-001.timing.json").write_text('{"seconds": 2.5}')
        (native / "tool-001.request.json").write_text(json.dumps({"name": "execute", "arguments": {"command": "python -m unittest"}}))
        (native / "tool-001.result.json").write_text('{"returncode": 0, "stdout": "OK"}')
        (native / "native.stdout.bin").write_text("native log")
        (self.trial / "summary.json").write_text('{"condition":"opencode","success":true}')
        trace = self.data.trace("campaign", self.trial.name)
        self.assertEqual(trace["kind"], "coding")
        self.assertEqual(trace["native_worker"], "opencode")
        self.assertEqual(trace["event_window"]["total_requests"], 2)
        events = {event["id"]: event for event in trace["events"]}
        self.assertEqual(events["backend/request-001"]["seconds"], 2.5)
        self.assertEqual(events["native/tool-001"]["command"], "python -m unittest")
        self.assertIn("native/native.stdout.bin", trace["artifacts"])
        self.assertEqual(self.data.artifact("campaign", self.trial.name, "native/native.stdout.bin")["text"], "native log")
        self.assertIsNone(trace["cost_breakdown"])
        self.assertFalse(self.data.allowed_artifact("backend/../summary.json"))
        self.assertFalse(self.data.allowed_artifact("native/settings/secrets.json"))
        (backend / "request-002.request.json").symlink_to(native / "request-001.request.json")
        self.assertEqual(len(self.data.request_files(self.trial)), 2)
        with self.assertRaises(ValueError):
            self.data.artifact("campaign", self.trial.name, "backend/request-002.request.json")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "campaign"
        self.trial = self.run / "experiment/trial-00-task"
        self.trial.mkdir(parents=True)
        (self.run / "command.json").write_text("[]")
        self.data = Evidence(self.root)

    def test_exact_edit_is_isolated_typed_work(self):
        args = {"path": "a.py", "old_text": "before", "new_text": "after"}
        (self.trial / "tool-001.request.json").write_text(
            json.dumps(
                {"mode": "tool", "name": "edit_file", "arguments": args, "timeout": 2}
            )
        )
        (self.trial / "tool-001.result.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "returncode": 0,
                    "stdout": '{"changed":true}',
                    "stderr": "",
                }
            )
        )
        (self.trial / "tool-001.cleanup.json").write_text(
            json.dumps({"verified": True})
        )
        event = self.data.trace("campaign", "trial-00-task")["events"][0]
        self.assertEqual(event["tool_name"], "edit_file")
        self.assertEqual(event["arguments"], args)
        self.assertFalse(event["adapter_control"])
        self.assertIsNone(event["command"])
        self.assertTrue(event["cleanup"]["verified"])

    def test_file_write_is_isolated_typed_work(self):
        args = {"path": "a.py", "content": "after\n"}
        (self.trial / "tool-001.request.json").write_text(
            json.dumps(
                {"mode": "tool", "name": "write_file", "arguments": args, "timeout": 2}
            )
        )
        (self.trial / "tool-001.result.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "returncode": 0,
                    "stdout": '{"changed":true}',
                    "stderr": "",
                }
            )
        )
        (self.trial / "tool-001.cleanup.json").write_text(
            json.dumps({"verified": True})
        )
        event = self.data.trace("campaign", "trial-00-task")["events"][0]
        self.assertEqual(event["tool_name"], "write_file")
        self.assertEqual(event["arguments"], args)
        self.assertFalse(event["adapter_control"])
        self.assertIsNone(event["command"])
        self.assertTrue(event["cleanup"]["verified"])

    def test_read_file_preserves_arguments_text_and_read_only_status(self):
        args = {"path": "a.py", "start_line": 4, "max_lines": 20, "reread": False}
        (self.trial / "tool-001.request.json").write_text(
            json.dumps(
                {
                    "mode": "adapter-read",
                    "name": "read_file",
                    "executed": False,
                    "arguments": args,
                    "workspace_generation": "0001",
                }
            )
        )
        event = self.data.trace("campaign", "trial-00-task")["events"][0]
        self.assertEqual(event["state"], "reading")
        self.assertEqual(event["arguments"], args)
        self.assertTrue(event["read_only"])
        self.assertFalse(event["adapter_control"])
        self.assertFalse(event["executed"])
        self.assertIsNone(event["command"])
        self.assertIsNone(event["cleanup"])
        for ok, output, file_read in [
            (True, "4: print('<img src=x>')\n", {"contents_returned": True}),
            (
                True,
                "Unchanged requested range at o0001",
                {"contents_returned": False, "context_observation_id": "o0001"},
            ),
            (False, "File does not exist", {}),
        ]:
            with self.subTest(ok=ok, file_read=file_read):
                visible = {
                    "returncode": 0 if ok else 1,
                    "output": output,
                    "file_read": file_read,
                }
                (self.trial / "tool-001.result.json").write_text(
                    json.dumps(
                        {
                            "ok": ok,
                            "executed": False,
                            "read_only": True,
                            "cleanup_required": False,
                            "wall_seconds": 0.0003,
                            "visible": visible,
                        }
                    )
                )
                event = self.data.trace("campaign", "trial-00-task")["events"][0]
                self.assertEqual(
                    event["state"], "read returned" if ok else "read failed"
                )
                self.assertEqual(event["result"]["visible"], visible)
                self.assertFalse(event["cleanup_required"])

    def test_unknown_tool_retains_its_arguments(self):
        (self.trial / "tool-001.request.json").write_text(
            json.dumps(
                {
                    "name": "future_tool",
                    "arguments": {"query": "inspect this"},
                }
            )
        )
        event = self.data.trace("campaign", "trial-00-task")["events"][0]
        self.assertEqual(event["tool_name"], "future_tool")
        self.assertEqual(event["arguments"], {"query": "inspect this"})

    def test_unfinished_is_not_called_live(self):
        self.assertEqual(
            self.data.run("campaign")["state"], "unfinished / owner not observed"
        )
        self.assertEqual(
            self.data.runs()["runs"][0]["trials"][0]["state"], "unfinished"
        )

    def test_path_and_symlink_escape_rejected(self):
        for name in ("../secret", "/etc/passwd", "..", "a/b"):
            with self.assertRaises(ValueError):
                self.data.run(name)
        (self.trial / "summary.json").symlink_to("/etc/passwd")
        with self.assertRaises(ValueError):
            self.data.artifact("campaign", "trial-00-task", "summary.json")
        with self.assertRaises(ValueError):
            self.data.artifact("campaign", "trial-00-task", "../../secret")
        with self.assertRaises(ValueError):
            self.data.artifact("campaign", "trial-00-task", "private.py")

    def test_partial_json_and_failed_transport_preserved(self):
        (self.trial / "summary.json").write_text("{")
        (self.trial / "tool-001.request.json").write_text(
            json.dumps({"arguments": {"command": "echo hello"}, "timeout": 10})
        )
        (self.trial / "tool-001.cleanup.json").write_text(
            json.dumps({"verified": True})
        )
        (self.trial / "tool-001.stderr.bin").write_text("terminated")
        trace = self.data.trace("campaign", "trial-00-task")
        self.assertIsNone(trace["summary"])
        self.assertEqual(trace["events"][0]["state"], "transport stopped")
        self.assertEqual(trace["events"][0]["transport_stderr"], "terminated")

    def test_model_truncation_usage_and_seed_visible(self):
        (self.trial / "request-001.request.json").write_text(
            json.dumps(
                {
                    "seed": 43,
                    "max_tokens": 2048,
                    "messages": [{"role": "user", "content": "task"}],
                }
            )
        )
        text = '<script>throw new Error("untrusted")</script>'
        (self.trial / "request-001.response.bin").write_text(
            json.dumps(
                {
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {"reasoning_content": text},
                        }
                    ],
                    "usage": {"completion_tokens": 2048},
                }
            )
        )
        event = self.data.trace("campaign", "trial-00-task")["events"][0]
        self.assertEqual(
            (event["seed"], event["finish"], event["reasoning"]), (43, "length", text)
        )
        self.assertEqual(event["usage"]["completion_tokens"], 2048)

    def test_reads_are_bounded_and_tail_is_current(self):
        path = self.trial / "changes.diff"
        path.write_text("a" * 200000 + "END")
        artifact = self.data.artifact("campaign", "trial-00-task", "changes.diff")
        self.assertTrue(artifact["truncated"])
        self.assertEqual(len(artifact["text"]), 131072)
        self.assertEqual(self.data.tail(path, 3), "END")

    def test_parser_control_result_is_not_a_coding_failure(self):
        summary = {
            "kind": "parser-only integration control",
            "commands_executed": 0,
            "cases": [],
            "completed": True,
            "passed": True,
            "elapsed_seconds": 33.96,
            "interpretation": "Technical control; no quality claim.",
        }
        (self.trial / "summary.json").write_text(json.dumps(summary))
        run = self.data.run("campaign")
        trial = run["trials"][0]
        self.assertEqual(run["kind"], "control")
        self.assertEqual(trial["state"], "passed")
        self.assertEqual(trial["seconds"], 33.96)
        self.assertEqual(trial["commands_executed"], 0)
        self.assertIsNone(trial["correct"])
        self.assertIsNone(trial["clean"])
        summary["passed"] = False
        (self.trial / "summary.json").write_text(json.dumps(summary))
        self.assertEqual(self.data.run("campaign")["trials"][0]["state"], "failed")

    def test_control_client_failure_overrides_partial_pass_flag(self):
        for fields in [
            {"completed": False},
            {"error": {"type": "FileExistsError"}},
            {"cancelled": True},
        ]:
            with self.subTest(fields=fields):
                raw = {
                    "kind": "inert timing control",
                    "passed": True,
                    "cases": [],
                    **fields,
                }
                (self.trial / "summary.json").write_text(json.dumps(raw))
                run = self.data.run("campaign")
                self.assertFalse(run["trials"][0]["passed"])
                self.assertEqual(run["trials"][0]["state"], "failed")
                self.assertEqual(
                    self.data.trace("campaign", self.trial.name)["summary"], raw
                )

    def test_named_controls_exclude_measurements_and_preserve_negative_case(self):
        names = ["unrestricted", "bounded64", "insufficient", "long_prefix_bounded64"]
        cases = []
        for name in names:
            request = {"seed": 42, "max_tokens": 1024, "messages": []}
            (self.trial / f"{name}.request.json").write_text(json.dumps(request))
            finish = "length" if name == "insufficient" else "tool_calls"
            response = {
                "choices": [{"finish_reason": finish, "message": {"content": ""}}],
                "usage": {"prompt_tokens": 20568, "completion_tokens": 97},
            }
            (self.trial / f"{name}.response.bin").write_text(json.dumps(response))
            cases.append(
                {
                    "name": name,
                    "elapsed_seconds": 203.7,
                    "parse_valid": finish != "length",
                }
            )
        for name in ("measure-00.template", "measure-00.tokens", "bounded64.template"):
            (self.trial / f"{name}.request.json").write_text(json.dumps(request))
        (self.trial / "summary.json").write_text(
            json.dumps(
                {
                    "kind": "inert long-prefix CPU40 control",
                    "cases": cases,
                    "commands_executed": 0,
                    "completed": True,
                    "passed": True,
                }
            )
        )
        trace = self.data.trace("campaign", "trial-00-task")
        self.assertEqual(trace["kind"], "control")
        self.assertEqual({e["id"] for e in trace["events"]}, set(names))
        self.assertEqual(self.data.run("campaign")["trials"][0]["events"], 4)
        for event in trace["events"]:
            self.assertEqual(event["kind"], "model")
            self.assertEqual(event["seconds"], 203.7)
            self.assertEqual(event["state"], "returned")
            self.assertEqual(event["usage"]["prompt_tokens"], 20568)
        negative = next(e for e in trace["events"] if e["id"] == "insufficient")
        self.assertEqual(negative["finish"], "length")
        self.assertFalse(negative["control_case"]["parse_valid"])
        self.assertEqual(self.data.run("campaign")["trials"][0]["state"], "passed")
        self.assertNotIn("measure-00.template.request.json", trace["artifacts"])
        self.assertIn("long_prefix_bounded64.response.bin", trace["artifacts"])
        raw = self.data.artifact(
            "campaign", "trial-00-task", "long_prefix_bounded64.response.bin"
        )
        self.assertEqual(json.loads(raw["text"])["usage"]["prompt_tokens"], 20568)

    def test_live_control_named_request_before_summary(self):
        (self.trial / "long_prefix_bounded64.request.json").write_text(
            json.dumps({"model": "local", "messages": [], "max_tokens": 1024})
        )
        trial = self.data.run("campaign")["trials"][0]
        self.assertEqual(trial["kind"], "control")
        self.assertIsNone(trial["passed"])
        self.assertIsNone(trial["commands_executed"])
        trace = self.data.trace("campaign", "trial-00-task")
        self.assertEqual(trace["events"][0]["state"], "awaiting response")

    def test_nested_native_cases_preserve_responses_and_negative_results(self):
        cases = []
        for name in NATIVE_CASES:
            directory = self.trial / name
            directory.mkdir()
            payloads = {
                "request-001.request.json": {
                    "messages": [{"role": "system", "content": "Parser control"}],
                    "seed": 42,
                },
                "request-001.response.bin": {
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "reasoning_content": "Inspect the contract",
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "bash"
                                            if name == "contract_blocked"
                                            else "finish_attempt"
                                        }
                                    }
                                ],
                            },
                        }
                    ],
                    "usage": {"completion_tokens": 123},
                },
                "request-001.timing.json": {"wall_seconds": 4.5},
                "context-001.json": {"policy": "none"},
                "context-001.usage.json": {"remaining": 100},
                "control-result.json": {
                    "name": name,
                    "passed": name != "contract_blocked",
                    "commands_executed": 0,
                },
                "supplied-history.json": [],
                "context-001.before.tokenize.request.json": {
                    "content": "not an inference"
                },
                "expected-handoff.json": {"not": "model output"},
            }
            for filename, payload in payloads.items():
                (directory / filename).write_text(json.dumps(payload))
            cases.append(payloads["control-result.json"])
        (self.trial / "summary.json").write_text(
            json.dumps(
                {
                    "kind": "structured-finalization parser-only native control",
                    "cases": cases,
                    "passed": False,
                    "commands_executed": 0,
                }
            )
        )
        trace = self.data.trace("campaign", "trial-00-task")
        self.assertEqual(len(trace["events"]), 4)
        self.assertEqual(self.data.run("campaign")["trials"][0]["events"], 4)
        self.assertEqual(trace["kind"], "control")
        for event in trace["events"]:
            self.assertEqual(event["kind"], "model")
            self.assertEqual(event["seconds"], 4.5)
            self.assertEqual(event["context_usage"], {"remaining": 100})
            self.assertEqual(event["initial_prompt"][0]["content"], "Parser control")
            self.assertEqual(event["reasoning"], "Inspect the contract")
        failed = next(
            e for e in trace["events"] if e["id"] == "contract_blocked/request-001"
        )
        self.assertFalse(failed["control_case"]["passed"])
        self.assertEqual(failed["tool_calls"][0]["function"]["name"], "bash")
        self.assertEqual(failed["control_case"]["commands_executed"], 0)
        for artifact in trace["artifacts"]:
            self.assertNotIn("tokenize", artifact)
            self.assertNotIn("expected-handoff", artifact)
            self.assertFalse(
                self.data.artifact("campaign", "trial-00-task", artifact)["truncated"]
            )
        self.assertIn("contract_blocked/request-001.response.bin", trace["artifacts"])

    def test_recovery_cases_include_local_tool_results_and_reject_escape(self):
        for name in ("case-a", "case-b"):
            directory = self.trial / name
            directory.mkdir()
            (directory / "request-001.request.json").write_text('{"messages": []}')
            (directory / "summary.json").write_text(
                json.dumps({"passed": name == "case-a"})
            )
        directory = self.trial / "case-a"
        (directory / "tool-001.request.json").write_text(
            json.dumps({"arguments": {"command": "cat /workspace/sentinel.txt"}})
        )
        (directory / "tool-001.result.json").write_text(
            json.dumps({"returncode": 0, "stdout": "amber\n"})
        )
        (directory / "tool-001.cleanup.json").write_text('{"verified": true}')
        (self.trial / "tool-001.result.json").write_text(
            '{"stdout": "wrong root result"}'
        )
        trace = self.data.trace("campaign", "trial-00-task")
        self.assertEqual(trace["kind"], "control")
        self.assertEqual(len(trace["events"]), 3)
        tool = next(e for e in trace["events"] if e["kind"] == "tool")
        self.assertEqual(tool["result"]["stdout"], "amber\n")
        self.assertTrue(tool["cleanup"]["verified"])
        b = next(e for e in trace["events"] if e["id"] == "case-b/request-001")
        self.assertFalse(b["control_case"]["passed"])
        self.assertIn("case-a/tool-001.result.json", trace["artifacts"])
        self.assertIn(
            "amber",
            self.data.artifact(
                "campaign", "trial-00-task", "case-a/tool-001.result.json"
            )["text"],
        )
        for name in (
            "case-a/../summary.json",
            "case-c/summary.json",
            "case-a/private.py",
        ):
            with self.assertRaises(ValueError):
                self.data.artifact("campaign", "trial-00-task", name)
        result = directory / "tool-001.result.json"
        result.unlink()
        result.symlink_to("/etc/passwd")
        with self.assertRaises(ValueError):
            self.data.artifact(
                "campaign", "trial-00-task", "case-a/tool-001.result.json"
            )
        bdir = self.trial / "case-b"
        for file in bdir.iterdir():
            file.unlink()
        bdir.rmdir()
        bdir.symlink_to(self.run, target_is_directory=True)
        self.assertFalse(
            any(p.parent.name == "case-b" for p in self.data.request_files(self.trial))
        )

    def test_nested_native_live_and_path_guards(self):
        directory = self.trial / "contract_blocked"
        directory.mkdir()
        request = directory / "request-001.request.json"
        request.write_text('{"messages": []}')
        trace = self.data.trace("campaign", "trial-00-task")
        self.assertEqual(trace["kind"], "control")
        self.assertEqual(trace["events"][0]["state"], "awaiting response")
        for name in (
            "../contract_blocked/request-001.request.json",
            "contract_blocked/../summary.json",
            "contract_blocked/private.py",
            "arbitrary/request-001.request.json",
            "contract_blocked/context-001.before.tokenize.request.json",
        ):
            with self.assertRaises(ValueError):
                self.data.artifact("campaign", "trial-00-task", name)
        request.unlink()
        request.symlink_to("/etc/passwd")
        self.assertEqual(self.data.trace("campaign", "trial-00-task")["events"], [])
        with self.assertRaises(ValueError):
            self.data.artifact(
                "campaign", "trial-00-task", "contract_blocked/request-001.request.json"
            )
        request.unlink()
        directory.rmdir()
        directory.symlink_to(self.run, target_is_directory=True)
        self.assertEqual(self.data.trace("campaign", "trial-00-task")["events"], [])
        with self.assertRaises(ValueError):
            self.data.artifact(
                "campaign", "trial-00-task", "contract_blocked/request-001.request.json"
            )

    def test_control_artifact_allowlist_and_symlink_guards(self):
        for name in (
            "../bounded64.request.json",
            "secret.request.json",
            "bounded64.template.request.json",
            "bounded64.tokens.response.bin",
        ):
            with self.assertRaises(ValueError):
                self.data.artifact("campaign", "trial-00-task", name)
        path = self.trial / "bounded64.request.json"
        path.symlink_to("/etc/passwd")
        self.assertEqual(self.data.trace("campaign", "trial-00-task")["events"], [])
        with self.assertRaises(ValueError):
            self.data.artifact("campaign", "trial-00-task", path.name)

    def test_coding_summary_still_uses_verified_correctness_and_task_time(self):
        (self.trial / "summary.json").write_text(
            json.dumps(
                {
                    "success": False,
                    "canonical_correctness": True,
                    "verified_correctness": False,
                    "clean_agent_completion": True,
                    "task_wall_seconds": 123.0,
                }
            )
        )
        trial = self.data.run("campaign")["trials"][0]
        self.assertEqual(trial["kind"], "coding")
        self.assertEqual(trial["state"], "failed")
        self.assertFalse(trial["correct"])
        self.assertTrue(trial["clean"])
        self.assertEqual(trial["seconds"], 123.0)

    def test_unanswered_request_distinguishes_live_and_attempt_deadline(self):
        request = self.trial / "request-001.request.json"
        request.write_text(json.dumps({"messages": [], "max_tokens": 32768}))
        event = self.data.trace("campaign", "trial-00-task")["events"][0]
        self.assertEqual(event["state"], "awaiting response")
        self.assertIsNone(event["request_end"])
        (self.trial / "summary.json").write_text(
            json.dumps(
                {
                    "agent_error": {
                        "type": "DeadlineExceeded",
                        "message": "Whole-stage wall deadline expired",
                    },
                    "success": False,
                }
            )
        )
        event = self.data.trace("campaign", "trial-00-task")["events"][0]
        self.assertEqual(event["state"], "attempt deadline reached")
        self.assertIn("omit it", event["request_end"]["accounting"])
        self.assertIsNone(event["usage"])
        self.assertIsNone(event["seconds"])

    def test_ended_request_reasons_do_not_confuse_context_and_wall_limits(self):
        (self.trial / "request-001.request.json").write_text('{"messages": []}')
        for error, expected in (
            (
                {
                    "type": "DeadlineExceeded",
                    "message": "No context headroom after observation policy",
                },
                "attempt ended / response unavailable",
            ),
            ({"type": "TimeoutError", "message": "timed out"}, "request timed out"),
            (
                {"type": "ValueError", "message": "invalid JSON"},
                "attempt ended / response unavailable",
            ),
        ):
            with self.subTest(error=error):
                (self.trial / "summary.json").write_text(
                    json.dumps({"agent_error": error})
                )
                event = self.data.trace("campaign", "trial-00-task")["events"][0]
                self.assertEqual(event["state"], expected)
                self.assertEqual(event["request_end"]["reason"], error["message"])

    def test_deadline_is_not_attributed_to_earlier_missing_or_returned_response(self):
        for index in (1, 2):
            path = self.trial / f"request-{index:03}.request.json"
            path.write_text('{"messages": []}')
            os.utime(path, (index, index))
        (self.trial / "summary.json").write_text(
            json.dumps(
                {
                    "agent_error": {
                        "type": "DeadlineExceeded",
                        "message": "Whole-stage wall deadline expired",
                    },
                }
            )
        )
        events = self.data.trace("campaign", "trial-00-task")["events"]
        self.assertEqual(events[0]["state"], "attempt ended / response unavailable")
        self.assertEqual(events[1]["state"], "attempt deadline reached")
        (self.trial / "request-002.response.bin").write_text(
            json.dumps(
                {
                    "choices": [{"finish_reason": "tool_calls", "message": {}}],
                    "usage": {"completion_tokens": 12},
                }
            )
        )
        events = self.data.trace("campaign", "trial-00-task")["events"]
        self.assertEqual(events[1]["state"], "returned")
        self.assertIsNone(events[1]["request_end"])
        self.assertEqual(events[1]["usage"]["completion_tokens"], 12)

    def test_nested_control_timeout_uses_its_own_end_evidence(self):
        directory = self.trial / NATIVE_CASES[0]
        directory.mkdir()
        (directory / "request-001.request.json").write_text('{"messages": []}')
        (directory / "control-result.json").write_text(
            json.dumps(
                {
                    "passed": False,
                    "error": {"type": "TimeoutError", "message": "timed out"},
                }
            )
        )
        event = self.data.trace("campaign", "trial-00-task")["events"][0]
        self.assertEqual(event["state"], "request timed out")
