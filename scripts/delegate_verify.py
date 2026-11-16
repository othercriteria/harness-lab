"""Independent isolated checks for real delegated work, without benchmark scores."""

import json
import time

from control import deadline


def validate_plan(plan):
    if (
        not isinstance(plan, dict)
        or set(plan) != {"version", "checks"}
        or plan["version"] != 1
        or not isinstance(plan["checks"], list)
        or len(plan["checks"]) > 16
    ):
        raise ValueError("Invalid delegated verification plan")
    names = set()
    for check in plan["checks"]:
        if not isinstance(check, dict) or set(check) != {"name", "argv", "timeout"}:
            raise ValueError("Invalid delegated check")
        name = check["name"]
        if not isinstance(name, str) or not name or len(name) > 100 or name in names:
            raise ValueError("Invalid or duplicate check name")
        names.add(name)
        argv = check["argv"]
        if (
            not isinstance(argv, list)
            or not 1 <= len(argv) <= 128
            or any(not isinstance(a, str) or "\0" in a for a in argv)
            or sum(len(a.encode()) for a in argv) > 32768
            or argv[0] not in {"/bin/python3", "/bin/bash"}
        ):
            raise ValueError("Invalid isolated check command")
        if type(check["timeout"]) is not int or not 1 <= check["timeout"] <= 120:
            raise ValueError("Invalid delegated check timeout")
    return plan


def verify(runtime, workspace, task, output, remaining):
    """Run trusted check commands in fresh evaluator sandboxes, never on host."""
    data = (task / "private/checks.json").read_bytes()
    if len(data) > 128 * 1024:
        raise ValueError("Delegated verification plan too large")
    plan = validate_plan(json.loads(data))
    end = time.monotonic() + remaining
    checks = []
    for index, check in enumerate(plan["checks"]):
        available = end - time.monotonic()
        with deadline(available):
            result, _ = runtime.sandbox(
                workspace,
                {
                    "mode": "grade",
                    "argv": check["argv"],
                    "timeout": min(check["timeout"], available),
                },
                output / f"delegated-check-{index:02d}",
                evaluation=(task / "private", "/evaluation"),
            )
        checks.append(
            {
                "name": check["name"],
                "passed": result.get("ok") is True,
                "transport": result,
            }
        )
    return {
        "kind": "delegated_checks",
        "passed": all(c["passed"] for c in checks) if checks else None,
        "checks": checks,
        "authority": "Outer-selected commands in independent isolated evaluators",
        "qualification": "Observed checks are evidence, not complete correctness or outer acceptance. No checks means unverified, not passed.",
    }


def pending_review(report):
    """Worker completion and observed checks never turn into outer acceptance."""
    report["work_kind"] = "delegated_repository"
    report["independent_checks_passed"] = report.get("verification", {}).get("passed")
    report["canonical_correctness"] = None
    report["verified_correctness"] = None
    report["success"] = False
    report["outer_acceptance"] = "pending"
    report["applied"] = False
    report["task_adjudication"] = {
        "status": "pending_outer_review",
        "correct": None,
        "authority": "Outer source/claim review and separately observed check evidence",
    }
    report["limitations"] = [
        "Real delegated work, not a named benchmark correctness score",
        "Worker time excludes setup; delegated job owner reports total dispatch time",
        "Independent checks and model claims do not authorize application",
    ]
