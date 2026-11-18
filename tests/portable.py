"""The Python unittest selection shared by portable CI and local coverage runs."""

import unittest

CASES = (
    "tests.test_example_evidence",
    "tests.test_export_issue_context",
    "tests.test_delegate_artifacts",
    "tests.test_delegate_apply",
    "tests.test_checkpoint_policy",
    "tests.test_observe",
    "tests.test_observe_costs",
    "tests.test_delegate_job.DelegateJobTests.test_dispatch_records_only_explicit_classification",
    "tests.test_memory_scope.MemoryScopeTests",
    "tests.test_delegate_job.DelegateJobTests.test_missing_trial_result_needs_scope_closure_and_every_tool_receipt",
)


def load_tests(
    loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: str | None
):
    return loader.loadTestsFromNames(CASES)
