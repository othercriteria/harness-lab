"""Prefill a declared initial prompt with no generation or a one-token stub.

This is an explicit outer control, not a scored trial. Callers must bind the
request to public fixture bytes and the selected recipe before using its cache.
"""

import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from coding_agent import NoRedirect
from control import cancellation, deadline
from sandbox import write_json

BYTE_CAP = 4 * 1024 * 1024


def initial_request(value):
    """Reject solution/history replay; retain the exact template inputs."""
    if not isinstance(value, dict):
        raise ValueError("Warm-up request must be an object")
    messages = value.get("messages")
    if not isinstance(messages, list) or len(messages) != 2:
        raise ValueError(
            "Warm-up requires exactly the initial system and user messages"
        )
    for message, role in zip(messages, ("system", "user"), strict=True):
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or message["role"] != role
            or not isinstance(message["content"], str)
        ):
            raise ValueError("Warm-up cannot contain assistant history or observations")
    if len(json.dumps(value).encode()) > BYTE_CAP:
        raise ValueError("Warm-up request exceeds byte cap")
    return value


def warm(request, post, *, max_generated_tokens=0):
    """Render once, then verify reuse; generated stub text is never executed."""
    if type(max_generated_tokens) is not int or max_generated_tokens not in (0, 1):
        raise ValueError("Warm-up permits only zero or one token per request")
    request = initial_request(request)
    rendered = post("apply-template", request).get("prompt")
    if not isinstance(rendered, str) or not rendered:
        raise ValueError("Backend did not render the initial prompt")
    tokens = post(
        "tokenize",
        {"content": rendered, "add_special": True, "parse_special": True},
    ).get("tokens")
    if (
        not isinstance(tokens, list)
        or not tokens
        or any(type(t) is not int for t in tokens)
    ):
        raise ValueError("Backend did not provide integer prompt tokens")
    payload = {
        "prompt": tokens,
        "n_predict": max_generated_tokens,
        "cache_prompt": True,
        "stream": False,
    }
    responses = []
    for _ in range(2):
        response = post("completion", payload)
        generated = response.get("tokens_predicted")
        content = response.get("content")
        if (
            type(generated) is not int
            or not 0 <= generated <= max_generated_tokens
            or response.get("timings", {}).get("predicted_n") != generated
            or not isinstance(content, str)
            or (generated == 0 and content != "")
        ):
            raise ValueError("Backend did not honor the warm-up generation limit")
        responses.append(response)
    retained = responses[-1].get("timings", {}).get("cache_n")
    if type(retained) is not int or retained < 0 or retained > len(tokens):
        raise ValueError("Missing or invalid retained-prefix measurement")
    return {
        "prompt_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
        "tokens_sha256": hashlib.sha256(json.dumps(tokens).encode()).hexdigest(),
        "prompt_tokens": len(tokens),
        "verified_cached_tokens": retained,
        # Backends may reevaluate different suffix lengths. Their actual cost
        # belongs to the scored request; do not demand identical cache tails.
        "cache_reused": retained > 0,
        "uncached_prompt_tokens": len(tokens) - retained,
        "cached_fraction": retained / len(tokens),
        "generated_tokens": sum(r["tokens_predicted"] for r in responses),
        "max_generated_tokens_per_request": max_generated_tokens,
        "generated_output_policy": "Discarded; never executed or added to scored messages",
        "scope": "full declared initial public prompt; no solution or tool observations",
        "qualification": "Next scored request must match this prefix and demonstrate reuse; this control alone does not prove its cache hit.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-generated-tokens", type=int, choices=(0, 1), default=0)
    args = parser.parse_args()
    parsed = urllib.parse.urlsplit(args.origin)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or not parsed.port
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or not 1 <= args.timeout <= 300
    ):
        raise ValueError("Expected a local explicit port and bounded timeout")
    raw = args.request.read_bytes()
    if len(raw) > BYTE_CAP:
        raise ValueError("Warm-up request exceeds byte cap")
    request = initial_request(json.loads(raw))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "initial.request.json").write_bytes(raw)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    started = time.monotonic()
    calls = 0

    def post(endpoint, payload):
        nonlocal calls
        calls += 1
        stem = args.output / f"{calls:02d}-{endpoint}"
        write_json(stem.with_suffix(".request.json"), payload)
        before = time.monotonic()
        body = json.dumps(payload).encode()
        if len(body) > BYTE_CAP:
            raise ValueError("Warm-up HTTP request exceeds byte cap")
        req = urllib.request.Request(
            args.origin.rstrip("/") + "/" + endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with opener.open(req, timeout=args.timeout) as response:
                result = response.read(BYTE_CAP + 1)
            if len(result) > BYTE_CAP:
                raise ValueError("Warm-up response exceeds byte cap")
            stem.with_suffix(".response.bin").write_bytes(result)
            return json.loads(result)
        finally:
            write_json(
                stem.with_suffix(".timing.json"),
                {"wall_seconds": time.monotonic() - before},
            )

    report = {"kind": "initial-prefix warm-up control", "passed": False}
    try:
        with cancellation(), deadline(args.timeout):
            report.update(
                warm(request, post, max_generated_tokens=args.max_generated_tokens),
                passed=True,
            )
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        report.update(
            wall_seconds=time.monotonic() - started,
            initial_request_sha256=hashlib.sha256(raw).hexdigest(),
            scored_trial=False,
        )
        write_json(args.output / "result.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
