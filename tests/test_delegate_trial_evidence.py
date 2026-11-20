"""Focused tests for trial_evidence(run, closure) execution facts.

Expected values are constructed independently of the helper: digests are
computed here with hashlib, and the trace files are real temporary files
under fixed outer paths. The helper must report only the four execution
facts (trial, model_request_recorded, summary_sha256,
clean_agent_completion) and never candidate acceptance or verification.
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from delegate_trial_evidence import trial_evidence  # noqa: E402

TRIAL = "experiment/trial-00-delegated-task"
REQUEST = TRIAL + "/request-001.request.json"
SUMMARY = TRIAL + "/summary.json"


def sha256_hex(data):
    """Independent digest of exact bytes, computed without the helper."""
    return hashlib.sha256(data).hexdigest()


def request_bytes():
    return json.dumps(
        {"messages": [{"role": "user", "content": "run the delegated trial"}]}
    ).encode("utf-8")


def summary_bytes(clean):
    return json.dumps(
        {"status": "terminal", "clean_agent_completion": clean},
        sort_keys=True,
    ).encode("utf-8")


class TrialEvidenceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = Path(tmp.name)

    def write_trace(self, name, data):
        path = self.run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def assert_facts(self, closure, expected):
        facts = trial_evidence(self.run_dir, closure)
        self.assertEqual(expected, facts)

    def test_verified_unlaunched_job(self):
        # No trace files exist at all: a verified not-launched closure is the
        # only evidence, and it rules out a recorded model request.
        closure = {"verified": True, "not_launched": True}
        expected = {
            "trial": None,
            "model_request_recorded": False,
            "summary_sha256": None,
            "clean_agent_completion": None,
        }
        self.assert_facts(closure, expected)

    def test_interrupted_request_without_summary(self):
        self.write_trace(REQUEST, request_bytes())
        closure = {"verified": True, "receipts": {}}
        expected = {
            "trial": str(self.run_dir / TRIAL),
            "model_request_recorded": True,
            "summary_sha256": None,
            "clean_agent_completion": None,
        }
        self.assert_facts(closure, expected)

    def test_terminal_summary_matching_closure_digest(self):
        self.write_trace(REQUEST, request_bytes())
        for clean in (True, False):
            with self.subTest(clean=clean):
                summary = summary_bytes(clean)
                self.write_trace(SUMMARY, summary)
                expected_digest = sha256_hex(summary)
                closure = {
                    "verified": True,
                    "receipts": {str(self.run_dir / SUMMARY): expected_digest},
                }
                expected = {
                    "trial": str(self.run_dir / TRIAL),
                    "model_request_recorded": True,
                    "summary_sha256": expected_digest,
                    "clean_agent_completion": clean,
                }
                self.assert_facts(closure, expected)

    def test_replaced_summary_cannot_supply_clean_completion(self):
        # A real request remains, but the summary on disk is a replacement
        # whose bytes do not match the closure receipt digest. It must not
        # supply summary_sha256 or clean_agent_completion.
        self.write_trace(REQUEST, request_bytes())
        replaced = summary_bytes(True)
        self.write_trace(SUMMARY, replaced)
        receipt_digest = sha256_hex(b'{"status":"interrupted"}')
        self.assertNotEqual(receipt_digest, sha256_hex(replaced))
        closure = {
            "verified": True,
            "receipts": {str(self.run_dir / SUMMARY): receipt_digest},
        }
        expected = {
            "trial": str(self.run_dir / TRIAL),
            "model_request_recorded": True,
            "summary_sha256": None,
            "clean_agent_completion": None,
        }
        self.assert_facts(closure, expected)

    def test_missing_evidence_is_unknown(self):
        # Verified closure, but no trace files and no receipts: nothing is
        # known, and a not_launched flag cannot appear without verification.
        self.assertEqual(
            trial_evidence(self.run_dir, {"verified": True, "receipts": {}}),
            {
                "trial": None,
                "model_request_recorded": None,
                "summary_sha256": None,
                "clean_agent_completion": None,
            },
        )
        self.assertEqual(
            trial_evidence(self.run_dir, {"not_launched": True}),
            {
                "trial": None,
                "model_request_recorded": None,
                "summary_sha256": None,
                "clean_agent_completion": None,
            },
        )
        # A receipt pointing at a summary that does not exist stays unknown.
        self.write_trace(REQUEST, request_bytes())
        closure = {
            "verified": True,
            "receipts": {str(self.run_dir / SUMMARY): sha256_hex(summary_bytes(True))},
        }
        self.assert_facts(
            closure,
            {
                "trial": str(self.run_dir / TRIAL),
                "model_request_recorded": True,
                "summary_sha256": None,
                "clean_agent_completion": None,
            },
        )

    def test_acceptance_and_verification_stay_out_of_facts(self):
        # Candidate acceptance/verification fields in the closure are not
        # execution facts and must not appear in the result.
        self.write_trace(REQUEST, request_bytes())
        summary = summary_bytes(False)
        self.write_trace(SUMMARY, summary)
        expected_digest = sha256_hex(summary)
        closure = {
            "verified": True,
            "acceptance": "pending_outer_review",
            "applied": False,
            "candidate_ok": True,
            "receipts": {str(self.run_dir / SUMMARY): expected_digest},
        }
        expected = {
            "trial": str(self.run_dir / TRIAL),
            "model_request_recorded": True,
            "summary_sha256": expected_digest,
            "clean_agent_completion": False,
        }
        self.assert_facts(closure, expected)


if __name__ == "__main__":
    unittest.main()
