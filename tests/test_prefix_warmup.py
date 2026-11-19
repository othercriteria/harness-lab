"""The outer warm-up never generates a solution or accepts replayed history."""

import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prefix_warmup import (
    initial_request,
    scored_cache_usage,
    verify_scored_prefix,
    warm,
)


class PrefixWarmupTests(unittest.TestCase):
    def setUp(self):
        self.request = {
            "messages": [
                {"role": "system", "content": "Use the provided tools."},
                {"role": "user", "content": "Public starter task."},
            ],
            "tools": [{"type": "function", "function": {"name": "execute"}}],
            "tool_choice": "required",
            "chat_template_kwargs": {"enable_thinking": False},
        }

    def test_rejects_prior_model_output_and_observations(self):
        for extra in (
            {"role": "assistant", "content": "A previous solution"},
            {"role": "tool", "content": "Previous output"},
        ):
            value = copy.deepcopy(self.request)
            value["messages"].append(extra)
            with self.assertRaises(ValueError):
                initial_request(value)
        value = copy.deepcopy(self.request)
        value["messages"][1]["tool_calls"] = []
        with self.assertRaises(ValueError):
            initial_request(value)

    def backend(self, *, cache=3, generated=0, requested=0):
        calls = []

        def post(endpoint, payload):
            calls.append((endpoint, payload))
            if endpoint == "apply-template":
                self.assertEqual(payload, self.request)
                return {"prompt": "Rendered initial public prompt"}
            if endpoint == "tokenize":
                return {"tokens": [10, 11, 12, 13]}
            self.assertEqual(endpoint, "completion")
            self.assertEqual(payload["prompt"], [10, 11, 12, 13])
            self.assertEqual(payload["n_predict"], requested)
            self.assertTrue(payload["cache_prompt"])
            return {
                "content": "" if generated == 0 else "unexpected output",
                "tokens_predicted": generated,
                "timings": {"predicted_n": generated, "cache_n": cache},
            }

        return post, calls

    def test_preserves_template_and_verifies_prefix_without_generation(self):
        post, calls = self.backend()
        report = warm(self.request, post)
        self.assertTrue(report["cache_reused"])
        self.assertEqual(report["uncached_prompt_tokens"], 1)
        self.assertEqual(report["generated_tokens"], 0)
        self.assertEqual(
            [c[0] for c in calls],
            ["apply-template", "tokenize", "completion", "completion"],
        )

    def test_nonretaining_backend_is_explicitly_cold(self):
        post, _ = self.backend(cache=0)
        report = warm(self.request, post)
        self.assertFalse(report["cache_reused"])
        self.assertEqual(report["verified_cached_tokens"], 0)

    def test_backend_ignoring_zero_generation_is_rejected_immediately(self):
        post, calls = self.backend(generated=1)
        with self.assertRaisesRegex(ValueError, "generation limit"):
            warm(self.request, post)
        self.assertEqual(len(calls), 3)

    def test_explicit_one_token_stub_is_bounded_and_discarded(self):
        post, calls = self.backend(generated=1, requested=1)
        report = warm(self.request, post, max_generated_tokens=1)
        self.assertEqual(report["generated_tokens"], 2)
        self.assertTrue(report["cache_reused"])
        self.assertEqual(calls[2][1], calls[3][1])
        self.assertNotIn("unexpected output", str(calls))
        post, _ = self.backend(generated=2, requested=1)
        with self.assertRaisesRegex(ValueError, "generation limit"):
            warm(self.request, post, max_generated_tokens=1)

    def test_partial_retention_reports_remaining_work(self):
        post, _ = self.backend(cache=2)
        report = warm(self.request, post)
        self.assertTrue(report["cache_reused"])
        self.assertEqual(report["uncached_prompt_tokens"], 2)
        self.assertEqual(report["cached_fraction"], 0.5)

    def test_scored_prompt_must_match_even_when_warm_control_passed(self):
        prompt = "Same public prompt and tool schema"
        receipt = {
            "passed": True,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        }
        self.assertTrue(
            verify_scored_prefix(self.request, receipt, prompt)["matches_warmup"]
        )
        for wrong in (prompt + " stale tools", "different task"):
            with self.assertRaisesRegex(ValueError, "does not match"):
                verify_scored_prefix(self.request, receipt, wrong)
        with self.assertRaises(ValueError):
            verify_scored_prefix(self.request, {**receipt, "passed": False}, prompt)

    def test_actual_cache_usage_is_separate_from_warmup_capability(self):
        for cached, status in ((0, "cold"), (3, "reused")):
            response = {
                "usage": {
                    "prompt_tokens": 4,
                    "prompt_tokens_details": {"cached_tokens": cached},
                }
            }
            self.assertEqual(scored_cache_usage(response)["cache_status"], status)
        self.assertEqual(
            scored_cache_usage({"usage": {"prompt_tokens": 4}})["cache_status"],
            "unmeasured",
        )
        self.assertEqual(
            scored_cache_usage(
                {"usage": {"prompt_tokens": 4}, "timings": {"cache_n": 3}}
            )["observed_cached_tokens"],
            3,
        )

    def test_nullable_cache_telemetry_preserves_scored_response(self):
        usage = {
            "prompt_tokens": 8,
            "completion_tokens": 2,
            "prompt_tokens_details": None,
        }
        for timings, expected in [
            (None, None),
            ({"cache_n": 0}, 0),
            ({"cache_n": 5}, 5),
        ]:
            with self.subTest(timings=timings):
                result = scored_cache_usage({"usage": usage, "timings": timings})
                self.assertEqual(result["observed_cached_tokens"], expected)
                if expected is None:
                    self.assertEqual(result["cache_status"], "unmeasured")
                else:
                    self.assertEqual(result["uncached_prompt_tokens"], 8 - expected)

    def test_campaign_stops_on_missing_match_receipt(self):
        from serve_trial import require_safe_trial

        with tempfile.TemporaryDirectory() as tmp:
            trial = Path(tmp)
            (trial / "summary.json").write_text(json.dumps({"prefix_warmup": {}}))
            with self.assertRaisesRegex(RuntimeError, "not verified"):
                require_safe_trial(trial, 1)
            (trial / "prefix-warmup-match.json").write_text(
                json.dumps({"matches_warmup": True})
            )
            require_safe_trial(trial, 1)


class ScoredRequestTests(unittest.TestCase):
    def test_missing_optional_telemetry_allows_scored_request_to_finish(self):
        # This integration check runs in the locked mini-SWE-agent environment.
        from coding_agent import LocalModel

        rendered = "Public task prompt"
        usage = {
            "prompt_tokens": 8,
            "completion_tokens": 2,
            "prompt_tokens_details": None,
        }
        messages = [
            {"role": "system", "content": "Use tools."},
            {"role": "user", "content": "Public task"},
        ]
        answer = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "a",
                    "type": "function",
                    "function": {"name": "bash", "arguments": '{"command":"pwd"}'},
                }
            ],
        }
        response = {
            "usage": usage,
            "choices": [{"finish_reason": "tool_calls", "message": answer}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            model = LocalModel(
                "http://127.0.0.1:1234",
                "test",
                {},
                {
                    "total_completion_token_limit": 100,
                    "max_completion_tokens_per_request": 100,
                    "request_timeout_seconds": 5,
                },
                output,
            )
            model.prefix_warmup = {
                "passed": True,
                "prompt_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
            }
            model.context_post = Mock(return_value={"prompt": rendered})
            model.opener = Mock()
            model.opener.open.return_value = io.BytesIO(json.dumps(response).encode())
            result = model.query(messages)
            self.assertEqual(result["extra"]["actions"][0]["command"], "pwd")
            self.assertEqual((model.prompt_tokens, model.completion_tokens), (8, 2))
            self.assertEqual(
                json.loads((output / "prefix-warmup-usage.json").read_bytes()),
                {
                    "cache_status": "unmeasured",
                    "observed_cached_tokens": None,
                },
            )


if __name__ == "__main__":
    unittest.main()
