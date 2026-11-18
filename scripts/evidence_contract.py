"""Dependency-free validation helpers shared by evidence and handoff checks.

Standard library only: no agent framework, no spec_blocker import.
"""


def bounded_text(value, bound, field):
    """Report actionable sizes without reflecting arbitrary model text."""
    if isinstance(value, str):
        size = len(value.encode("utf-8"))
        if size > bound:
            raise ValueError(
                f"{field} is {size} UTF-8 bytes; maximum is {bound}. "
                f"Shorten it substantially (aim below {bound // 2} bytes)"
            )
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")
    if len(value.encode("utf-8")) > bound or any(
        ord(c) < 32 and c not in "\n\t" for c in value
    ):
        raise ValueError(f"{field} exceeds its text limit")


def require_fields(value, fields, label):
    """Name missing contract fields without reflecting untrusted key text."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    expected = set(fields)
    missing = expected - set(value)
    extra = set(value) - expected
    if missing or extra:
        details = []
        if missing:
            details.append("missing: " + ", ".join(sorted(missing)))
        if extra:
            details.append(f"unexpected fields: {len(extra)}")
        raise ValueError(
            f"{label}: "
            + "; ".join(details)
            + ". Required fields: "
            + ", ".join(fields)
        )
