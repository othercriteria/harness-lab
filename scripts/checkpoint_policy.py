"""Eligibility predicate for offering a structured finalization response.

This helper only determines which response choices may be offered. It does
not validate all limits, certify work complete, grant additional budget,
execute a tool, or replace handoff validation. It never mutates its inputs.
"""

from enum import Enum, auto


class CheckpointResponses(Enum):
    """Responses the configuration permits when the Worker is outside a scope."""

    CHECKPOINT_ONLY = auto()
    CHECKPOINT_OR_FINISH = auto()

    @classmethod
    def from_limits(cls, limits: object) -> "CheckpointResponses":
        """Parse the finalization-related fields from live or archived JSON."""
        if isinstance(limits, dict) and limits.get("structured_finalization") is True:
            policy = limits.get("fresh_context")
            if (
                isinstance(policy, dict)
                and policy.get("trigger") == "context_headroom"
                and policy.get("summary_checkpoint") is True
                and policy.get("continuation_mode", "continue") == "continue"
            ):
                return cls.CHECKPOINT_OR_FINISH
        return cls.CHECKPOINT_ONLY

    def allows_finalization(self, *, scoped: bool = False) -> bool:
        return self is CheckpointResponses.CHECKPOINT_OR_FINISH and scoped is False


def allow_finalization(limits: object, *, scoped: object = False) -> bool:
    """Check raw settings. Only the exact boolean False denotes an inactive scope."""
    return (
        scoped is False
        and CheckpointResponses.from_limits(limits).allows_finalization()
    )
