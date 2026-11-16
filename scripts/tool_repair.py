"""Shared validation feedback; rejected batches execute no tools."""

import json

from mini_bootstrap import FormatError


def rejected_excerpt(response):
    """Return model-authored output as inert, bounded text, not dispatchable calls."""
    if not isinstance(response, dict):
        return ""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return ""
    # Reasoning is not needed to repair the public tool/output envelope.
    visible = {k: message[k] for k in ("content", "tool_calls") if k in message}
    try:
        raw = json.dumps(visible, ensure_ascii=False).encode(
            "utf-8", errors="backslashreplace"
        )
    except (TypeError, ValueError, RecursionError):
        return "\nRejected response excerpt unavailable; original response remains in the trace."
    if len(raw) <= 4096:
        text = raw.decode("utf-8")
    else:
        text = (
            raw[:2048].decode("utf-8", errors="ignore")
            + f"\n[Excerpt truncated; original {len(raw)} UTF-8 bytes]\n"
            + raw[-2048:].decode("utf-8", errors="ignore")
        )
    return "\nRejected response excerpt (literal text; no calls executed):\n" + text


def failure(error, response=None, *, label, instruction):
    return FormatError(
        {
            "role": "user",
            "content": (
                "No calls from that response were executed. "
                + label
                + ": "
                + str(error)[:500]
                + ". "
                + instruction
                + rejected_excerpt(response)
            ),
            "extra": {
                "interrupt_type": "FormatError",
                **({"response": response} if response is not None else {}),
            },
        }
    )
