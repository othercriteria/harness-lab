"""Check a submitted Observatory UI suite and its old-renderer control in isolation."""

import argparse
import hashlib
from pathlib import Path

from delegate_artifacts import read_file
from sandbox import Runtime, write_json

RENDERER = "observatory/app.js"
SUITE = "tests/test_observe_ui.js"


def check(candidate, baseline, assertion, output):
    output.mkdir(parents=True, exist_ok=False)
    runtime = Runtime(node=True)
    write_json(output / "runtime.json", runtime.manifest)
    suite = read_file(candidate, SUITE)
    cases = {}
    for label, source in (("candidate", candidate), ("baseline", baseline)):
        renderer = read_file(source, RENDERER)
        workspace = output / label
        for name, data in ((SUITE, suite), (RENDERER, renderer)):
            path = workspace / name
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
        result, _ = runtime.sandbox(
            workspace,
            {"mode": "grade", "argv": ["/bin/node", SUITE], "timeout": 15},
            output / label,
        )
        cases[label] = {
            "renderer_sha256": hashlib.sha256(renderer).hexdigest(),
            "returncode": result["returncode"],
            "matched": result["ok"]
            if label == "candidate"
            else (
                result["returncode"] == 1
                and result.get("stopped_by") is None
                and "AssertionError [ERR_ASSERTION]" in result["stderr"]
                and assertion in result["stderr"]
            ),
        }
    summary = {
        "suite_sha256": hashlib.sha256(suite).hexdigest(),
        "expected_assertion_text": assertion,
        "cases": cases,
        "passed": all(row["matched"] for row in cases.values()),
    }
    write_json(output / "summary.json", summary)
    return summary["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "baseline", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument(
        "--assertion",
        required=True,
        help="Distinctive expected baseline assertion text",
    )
    args = parser.parse_args()
    if not args.assertion.strip():
        parser.error("Supply the expected assertion")
    raise SystemExit(
        0 if check(args.candidate, args.baseline, args.assertion, args.output) else 1
    )
