"""The Python unittest selection shared by portable CI and local coverage runs."""

import unittest

CASES = (
    "tests.test_example_evidence",
    "tests.test_export_issue_context",
    "tests.test_delegate_artifacts",
    "tests.test_delegate_runtime",
    "tests.test_delegate_apply",
    "tests.test_checkpoint_policy",
    "tests.test_elapsed_context",
    "tests.test_resumption_digest",
    "tests.test_progress_reminder",
    "tests.test_submission_review_evidence",
    "tests.test_check_fixtures",
    "tests.test_observe",
    "tests.test_observe_example",
    "tests.test_observe_costs",
    "tests.test_summarize_runs",
    "tests.test_progress_reports",
    "tests.test_initial_repository",
    "tests.test_read_file",
    "tests.test_read_file_evidence",
    "tests.test_file_mutations",
    "tests.test_read_observations",
    "tests.test_check_records",
    "tests.test_host_memory",
    "tests.test_model_registry",
    "tests.test_prefix_warmup.PrefixWarmupTests",
    "tests.test_campaign_startup",
    "tests.test_delegate_job",
    "tests.test_delegate_trial_evidence",
    "tests.test_worker_residency",
    "tests.test_backtest_dispatch",
    "tests.test_memory_scope.MemoryScopeTests",
    "tests.test_retired_protocol",
)


def load_tests(
    loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: str | None
):
    return loader.loadTestsFromNames(CASES)
