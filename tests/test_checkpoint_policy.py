"""Focused tests for scripts/checkpoint_policy.allow_finalization."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from checkpoint_policy import CheckpointResponses, allow_finalization


def eligible_limits():
    """A minimal configuration that satisfies every eligibility rule."""
    return {
        "structured_finalization": True,
        "fresh_context": {
            "trigger": "context_headroom",
            "summary_checkpoint": True,
        },
    }


class AllowFinalizationTests(unittest.TestCase):
    def test_validated_choices_follow_the_current_scope(self):
        choices = CheckpointResponses.from_limits(eligible_limits())
        self.assertIs(choices, CheckpointResponses.CHECKPOINT_OR_FINISH)
        self.assertFalse(choices.allows_finalization(scoped=True))
        self.assertTrue(choices.allows_finalization(scoped=False))

    def test_positive_case_omitted_continuation_mode(self):
        self.assertIs(allow_finalization(eligible_limits()), True)

    def test_positive_case_explicit_continue(self):
        limits = eligible_limits()
        limits["fresh_context"]["continuation_mode"] = "continue"
        self.assertIs(allow_finalization(limits), True)

    def test_extra_keys_do_not_change_meaning(self):
        limits = eligible_limits()
        limits["other_option"] = {"anything": [1, 2, 3]}
        limits["fresh_context"]["headroom_tokens"] = 4096
        limits["fresh_context"]["max_resets"] = 2
        limits["fresh_context"]["announce_review"] = False
        self.assertIs(allow_finalization(limits), True)

    def test_scoped_true_is_ineligible(self):
        self.assertIs(allow_finalization(eligible_limits(), scoped=True), False)

    def test_scoped_other_supplied_values_are_ineligible(self):
        for scoped in (1, 0, None, "False", []):
            with self.subTest(scoped=scoped):
                self.assertIs(allow_finalization(eligible_limits(), scoped=scoped), False)

    def test_limits_must_be_a_dict(self):
        for limits in (None, "limits", [eligible_limits()], 1):
            with self.subTest(limits=limits):
                self.assertIs(allow_finalization(limits), False)

    def test_structured_finalization_disabled_or_missing(self):
        limits = eligible_limits()
        del limits["structured_finalization"]
        self.assertIs(allow_finalization(limits), False)
        for value in (False, 0, None, "True"):
            with self.subTest(value=value):
                limits = eligible_limits()
                limits["structured_finalization"] = value
                self.assertIs(allow_finalization(limits), False)

    def test_structured_finalization_integer_one_is_not_true(self):
        limits = eligible_limits()
        limits["structured_finalization"] = 1
        self.assertIs(allow_finalization(limits), False)

    def test_fresh_context_absent_or_malformed(self):
        for value in (None, "context_headroom", ["context_headroom"], True, 7):
            with self.subTest(value=value):
                limits = eligible_limits()
                limits["fresh_context"] = value
                self.assertIs(allow_finalization(limits), False)
        limits = eligible_limits()
        del limits["fresh_context"]
        self.assertIs(allow_finalization(limits), False)

    def test_summary_checkpoint_must_be_exactly_true(self):
        for value in (False, 0, None, 1, "True"):
            with self.subTest(value=value):
                limits = eligible_limits()
                limits["fresh_context"]["summary_checkpoint"] = value
                self.assertIs(allow_finalization(limits), False)
        limits = eligible_limits()
        del limits["fresh_context"]["summary_checkpoint"]
        self.assertIs(allow_finalization(limits), False)

    def test_each_excluded_trigger_is_ineligible(self):
        for trigger in ("elapsed", "first_submission", "review", "headroom", None):
            with self.subTest(trigger=trigger):
                limits = eligible_limits()
                limits["fresh_context"]["trigger"] = trigger
                self.assertIs(allow_finalization(limits), False)
        limits = eligible_limits()
        del limits["fresh_context"]["trigger"]
        self.assertIs(allow_finalization(limits), False)

    def test_review_continuation_mode_is_ineligible(self):
        limits = eligible_limits()
        limits["fresh_context"]["continuation_mode"] = "review"
        self.assertIs(allow_finalization(limits), False)

    def test_other_continuation_mode_values_are_ineligible(self):
        for mode in ("Continue", "continue ", "resume", 1, None):
            with self.subTest(mode=mode):
                limits = eligible_limits()
                limits["fresh_context"]["continuation_mode"] = mode
                self.assertIs(allow_finalization(limits), False)

    def test_inputs_are_left_unchanged(self):
        limits = eligible_limits()
        limits["fresh_context"]["continuation_mode"] = "continue"
        policy = limits["fresh_context"]
        snapshot = copy.deepcopy(limits)
        allow_finalization(limits)
        allow_finalization(limits, scoped=True)
        self.assertIs(limits["fresh_context"], policy)
        self.assertEqual(limits, snapshot)


if __name__ == "__main__":
    unittest.main()
