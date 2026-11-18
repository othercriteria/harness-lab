"""Opt-in thinking only after a committed first-submission review boundary."""


def validate(limits):
    enabled = limits.get("review_reasoning_only", False)
    if type(enabled) is not bool:
        raise ValueError("review_reasoning_only must be a boolean")
    if not enabled:
        return
    review = limits.get("fresh_context") or {}
    if not (
        isinstance(review, dict)
        and review.get("trigger") == "first_submission"
        and review.get("continuation_mode") == "review"
        and limits.get("structured_finalization") is True
        and "reasoning_budget_tokens" in limits
        and "reasoning_deadline" in limits
    ):
        raise ValueError(
            "review_reasoning_only requires first-submission review and bounded thinking"
        )


def select(controller):
    """An offer, failed archive or bypass is not a committed thinking review."""
    if controller is None or controller.trigger != "first_submission":
        raise ValueError("Missing first-submission review controller")
    applied = controller.decision == "applied"
    if applied != (controller.boundary is not None):
        raise ValueError("Inconsistent committed review boundary")
    return {
        "phase": "review" if applied else "draft",
        "enable_thinking": applied,
        "review_decision": controller.decision,
        "boundary_messages": controller.boundary,
    }
