"""Eligibility predicate for offering a structured finalization response.

This helper only determines which response choices may be offered. It does
not validate all limits, certify work complete, grant additional budget,
execute a tool, or replace handoff validation. It never mutates its inputs.
"""


def allow_finalization(limits, *, scoped=False):
    """Return True exactly when a context-headroom summary checkpoint is eligible.

    Eligible means all of the following hold:

    - ``limits`` is a dict and ``limits["structured_finalization"]`` is
      exactly the boolean ``True`` (the integer ``1`` is not accepted).
    - ``limits["fresh_context"]`` is a dict whose ``trigger`` is
      ``"context_headroom"``, whose ``summary_checkpoint`` is exactly the
      boolean ``True``, and whose ``continuation_mode`` is ``"continue"``
      or omitted (omission means ``"continue"``).
    - ``scoped`` is exactly ``False``; ``True`` or any other supplied value
      does not permit this option.

    Absent, malformed or ineligible settings return ``False``. Extra
    configuration keys are accepted without changing their meaning.
    Explicit ``"review"`` continuations and ``"first_submission"`` or
    ``"elapsed"`` triggers are ineligible.
    """
    if scoped is not False:
        return False
    if not isinstance(limits, dict):
        return False
    if limits.get("structured_finalization") is not True:
        return False
    policy = limits.get("fresh_context")
    if not isinstance(policy, dict):
        return False
    if policy.get("trigger") != "context_headroom":
        return False
    if policy.get("summary_checkpoint") is not True:
        return False
    if policy.get("continuation_mode", "continue") != "continue":
        return False
    return True
