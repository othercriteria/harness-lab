"""Bounded capacity shared by call budgets and attempt-local evidence stores."""

MAX_CALLS = 512
MAX_OBSERVATION_BYTES = 128 * 1024 * 1024


def recommended_limit(agent_seconds):
    """Prospective recipe helper; never silently rewrite a frozen allowance."""
    if type(agent_seconds) is not int or agent_seconds <= 0:
        raise ValueError("Expected positive integer agent_seconds")
    # Two seconds per call, rounded up to 32; retain the established 128 floor.
    return min(MAX_CALLS, max(128, ((agent_seconds + 63) // 64) * 32))
