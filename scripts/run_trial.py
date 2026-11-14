"""One bounded coding trial, followed by independent isolated verification."""

import argparse
import base64
import difflib
import hashlib
import json
import os
import shlex
import shutil
import sys
import time
from pathlib import Path

import sandbox
from check_fixtures import manifest
from coding_agent import IsolatedEnvironment, LocalModel
from control import RunCancelled, UnsafeCleanup, cancellation, deadline
from mini_bootstrap import DefaultAgent
from observations import ObservationHistory
from protocol import admit_tasks, load_protocol, protocols, require_task_protocol
from sandbox import Runtime, write_json

ENTRY_STARTED = float(os.environ.get("HARNESS_DISPATCH_MONOTONIC", time.monotonic()))
PROJECT = Path(__file__).resolve().parents[1]
GRADE = """
import io,json,sys,unittest
sys.path.insert(0, '/workspace')
suite=unittest.defaultTestLoader.discover('/evaluation', pattern='test_*.py')
log=io.StringIO()
result=unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
print(json.dumps({'passed':result.wasSuccessful(), 'tests_run':result.testsRun,
                  'skipped':len(result.skipped), 'failures':len(result.failures),
                  'errors':len(result.errors), 'log':log.getvalue()}))
"""


class ReferenceModel(LocalModel):
    """CPU integration control; explicitly not an evaluated model result."""

    def __init__(self, task, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep this trusted integration control within the same command cap as
        # evaluated models, including for larger multi-file references.
        self.commands = []
        for path in sorted((task / "private/reference").rglob("*.py")):
            relative = str(path.relative_to(task / "private/reference"))
            raw = path.read_bytes()
            for offset in range(0, max(1, len(raw)), 4000):
                encoded = base64.b64encode(raw[offset : offset + 4000]).decode()
                mode = "wb" if offset == 0 else "ab"
                code = (
                    "from pathlib import Path; import base64; "
                    f"p=Path({relative!r}); p.parent.mkdir(parents=True, exist_ok=True); "
                    f"p.open({mode!r}).write(base64.b64decode({encoded!r}))"
                )
                self.commands.append("python -c " + shlex.quote(code))
        self.commands.extend(
            [
                "python -m unittest discover -s tests",
                "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
            ]
        )

    def query(self, messages):
        command = self.commands[self.calls]
        self.calls += 1
        identifier = f"control-{self.calls}"
        if (
            self.limits.get("structured_finalization", False)
            and command == "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
        ):
            from finalization_api import SUBMIT, actions, split
            from finish_attempt import NAME

            value = {
                "disposition": "submitted",
                "summary": "Trusted reference copied; public checks attempted.",
                "evidence": [],
                "unverified": [
                    "Reference control does not claim external verification."
                ],
                "blocker": None,
            }
            name = NAME
            if split(self.limits):
                name = SUBMIT
                value = {
                    "summary": value["summary"],
                    "checks": [],
                    "remaining": value["unverified"],
                }
            message = {
                "role": "assistant",
                "content": "Trusted integration control",
                "tool_calls": [
                    {
                        "id": identifier,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(value)},
                    }
                ],
            }
            message["extra"] = {
                "cost": 0,
                "actions": actions(
                    message,
                    None,
                    self.history,
                    finish_reason="tool_calls",
                    split_enabled=split(self.limits),
                ),
            }
            return message
        return {
            "role": "assistant",
            "content": "Trusted integration control",
            "tool_calls": [
                {
                    "id": identifier,
                    "type": "function",
                    "function": {
                        "name": "bash",
                        "arguments": json.dumps({"command": command}),
                    },
                }
            ],
            "extra": {
                "cost": 0,
                "actions": [{"command": command, "tool_call_id": identifier}],
            },
        }


def freeze(output, task):
    inputs = output / "inputs"
    inputs.mkdir()
    shutil.copytree(task, inputs / "task", ignore=shutil.ignore_patterns("__pycache__"))
    (inputs / "scripts").mkdir()
    for path in (PROJECT / "scripts").glob("*.py"):
        shutil.copyfile(path, inputs / "scripts" / path.name)
    shutil.copytree(PROJECT / "configs", inputs / "configs")
    for name in ("uv.lock", "pyproject.toml", "flake.lock"):
        shutil.copyfile(PROJECT / name, inputs / name)
    write_json(output / "inputs.json", manifest(inputs))
    return inputs


def verify(runtime, workspace, task, output, remaining):
    metadata = json.loads((task / "task.json").read_text())
    evaluator = metadata.get("evaluator")
    if evaluator == "hcast-orm-unittest-v1":
        from imported_orm import verify as verify_orm

        return verify_orm(runtime, workspace, task, output, remaining)
    if evaluator == "hcast-plain-functions-v1":
        from imported_fixtures import admitted
        from verify_markdown import verify as verify_imported

        admitted(task)
        return verify_imported(runtime, workspace, task, output, remaining)
    if (
        evaluator is not None
        or metadata.get("origin") == "imported"
        or "upstream" in metadata
    ):
        raise ValueError("Unsupported imported evaluator; refusing fallback")
    evaluation = output / "evaluation"
    evaluation.mkdir()
    public_tests = sorted((task / "public/tests").glob("test_*.py"))
    if not public_tests or any(
        path.name == "test_acceptance.py" for path in public_tests
    ):
        raise ValueError("Canonical public tests missing or collide with private suite")
    for path in public_tests:
        shutil.copyfile(path, evaluation / path.name)
    shutil.copyfile(
        task / "private/test_acceptance.py", evaluation / "test_acceptance.py"
    )
    expected = sum(json.loads((task / "task.json").read_text())["test_counts"].values())
    with deadline(remaining):
        result, _ = runtime.sandbox(
            workspace,
            {
                "mode": "grade",
                "argv": ["/bin/python3", "-I", "-S", "-c", GRADE],
                "timeout": min(10, remaining),
            },
            output / "verification",
            evaluation=(evaluation, "/evaluation"),
        )
    decoded = json.loads(result.get("stdout", ""))
    passed = (
        result["ok"]
        and decoded["passed"]
        and decoded["tests_run"] == expected
        and decoded["skipped"] == 0
    )
    return {
        "passed": passed,
        "expected_tests": expected,
        "tests": decoded,
        "transport": result,
    }


def save_diff(before, after, path):
    names = sorted(
        {
            str(p.relative_to(root))
            for root in (before, after)
            for p in root.rglob("*")
            if p.is_file()
        }
    )
    with path.open("w") as stream:
        for name in names:
            left, right = before / name, after / name
            old = left.read_bytes() if left.is_file() else None
            new = right.read_bytes() if right.is_file() else None
            if old == new:
                continue
            try:
                if any(b"\0" in data for data in (old, new) if data is not None):
                    raise ValueError("NUL in file")
                a = (old or b"").decode("utf-8").splitlines(True)
                b = (new or b"").decode("utf-8").splitlines(True)
            except (UnicodeDecodeError, ValueError):
                # Complete bytes remain in the sealed workspace and manifest.
                # Avoid turning binary artifacts into misleading replacement text.
                metadata = {
                    side: None
                    if data is None
                    else {
                        "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                    for side, data in (("before", old), ("after", new))
                }
                stream.write(
                    f"Binary file {json.dumps(name)} changed: {json.dumps(metadata)}\n"
                )
                continue
            stream.writelines(
                difflib.unified_diff(
                    a, b, fromfile="before/" + name, tofile="after/" + name
                )
            )


def configure_agent(config, limits, protocol):
    """Render the frozen protocol's model-visible environment contract."""
    config = dict(config)
    config["step_limit"] = limits["step_limit"]
    config["wall_time_limit_seconds"] = limits["agent_wall_seconds"]
    config["system_template"] += (
        "\n\nWork in /workspace with the provided tools and minimal Python/Unix runtime."
        " There is no network or package installation. Every response must include"
        " a tool call. Bash commands start fresh shells in /workspace."
    )
    if limits.get("persistent_scratch", False):
        config["system_template"] += (
            " Files under /workspace and /tmp (including HOME) persist between calls"
            " within this attempt. /tmp is scratch storage, limited to 16 MiB and"
            " 2048 regular-file/directory entries; it is not submitted to the evaluator."
            " Shell variables, working-directory changes and background processes do not persist."
        )
    elif limits.get("workspace_persistence_feedback", False):
        config["system_template"] += (
            " Only file changes under /workspace persist between calls. /tmp (including HOME),"
            " shell variables, working-directory changes and background processes do not."
            " Keep reusable scratch files in /workspace."
        )
    else:
        config["system_template"] += " Workspace file changes persist."
    if limits.get("python_test_library") is not None:
        from python_test_library import INSTRUCTION, validate

        validate(limits["python_test_library"])
        config["system_template"] += INSTRUCTION
    blocker_available = limits.get("structured_finalization") or limits.get(
        "spec_blocker_exit"
    )
    if blocker_available:
        config["system_template"] += (
            "\n\nCheck that the public requirements can hold together before implementing."
            " An established blocker takes priority over implementation and test writing,"
            " except where an explicit open-problem policy permits a bounded attempt."
            " Passing examples cannot override a contradictory requirement. Investigate"
            " uncertainty; uncertainty alone is not a blocker."
        )
    config["instance_template"] += (
        f"\n\nTotal task ceiling: {limits['task_wall_seconds']} seconds, including verification."
        f" Agent allowance: {limits['agent_wall_seconds']} seconds."
        " Run the task's checks; the default Python command is"
        " python -m unittest discover -s tests."
    )
    if limits.get("work_policy_feedback", False):
        if limits.get("contract_first_checks", False):
            config["system_template"] += (
                "\n\nBefore modifying implementation, save a small rerunnable set of checks"
                " derived from the public contract and relevant interfaces. Include"
                " explicit examples, exclusions, and interacting requirements where"
                " applicable. Derive expected results independently of your proposed"
                " solution. Run these checks, then implement in small, coherent steps."
                " Prefer focused edits; rerun the checks and supplied tests."
                " Model-written checks can be wrong: inspect a failing assertion's setup"
                " and contract basis before changing code or expectations."
            )
        else:
            config["system_template"] += (
                "\n\nForm a brief checklist of the public requirements; implement and run the"
                " supplied tests. Add regressions when required or when a specific"
                " uncovered risk warrants a small check, using"
                " expected results derived from the contract, not your implementation."
                " Do not impose expectations on explicitly excluded inputs. When a check"
                " fails, inspect both the code and the test's assumptions before changing either."
                " Save rerunnable regression tests when requested by the task."
            )
        config["system_template"] += (
            " For unittest discovery, use unittest.TestCase subclasses or provide load_tests;"
            " plain pytest-style functions are not discovered. Check the reported test count."
        )
        if limits.get("evidence_audit_feedback", False):
            config["system_template"] += (
                " Before submitting, review public requirements that lack direct evidence."
                " For each selected check, identify the exact clause, implementation"
                " location, and observed result; mark unchecked claims unverified."
                " Resolve concrete discrepancies, then submit; avoid repeatedly"
                " restating already checked behavior."
            )
        else:
            config["system_template"] += (
                " Before submission, compare the final change against the requirements"
                " and observed checks. Resolve discrepancies and report remaining gaps;"
                " do not repeat checks without a concrete reason."
            )
    if limits.get("patch_edit_feedback", False):
        config["system_template"] += (
            " Initial implementations and substantial module rewrites are allowed when"
            " required. For a small follow-up fix, use patch or a Python exact-text"
            " replacement that asserts the old text occurs once, preserving unaffected"
            " lines rather than emitting the whole file again."
        )
    if limits.get("context_budget_feedback", False):
        config["system_template"] += (
            " The harness may issue one near-limit context/token notice; its counts"
            " precede the notice. Leave room for checks and the final handoff."
        )
    if limits.get("time_budget_feedback", False):
        finishing_seconds = min(60, max(5, (limits["task_wall_seconds"] + 9) // 10))
        config["system_template"] += (
            " Tool results report remaining_agent_seconds, excluding the verifier reserve."
            f" With under {finishing_seconds} seconds left, prioritize an accurate final"
            " handoff over more optional work. Include unresolved work and observed failures."
            f" Bash commands are limited to {limits.get('max_command_bytes', 8192)} bytes."
        )
    if limits.get("progress_reminder") is not None:
        from progress_reminder import INSTRUCTION as PROGRESS_INSTRUCTION

        config["system_template"] += PROGRESS_INSTRUCTION
    if limits.get("max_tool_calls_per_response") == 1:
        config["system_template"] += (
            " Use exactly one tool call per response; each bash call requires a string command."
        )
    elif "max_tool_calls_per_response" in limits:
        config["system_template"] += (
            f" Use at most {limits['max_tool_calls_per_response']} tool calls per response;"
            " each bash call requires a string command. Split additional calls across"
            " responses. Calls in a batch execute in order; you see their results afterward."
        )
    elif limits.get("recover_tool_limit_errors", False):
        config["system_template"] += (
            " Use at most four tool calls per response; each bash call requires a string command."
            " Calls in a batch execute in order; you see their results afterward."
        )
    if limits.get("max_tool_calls_per_response", 4) > 1:
        config["system_template"] += (
            " Ordinary command/edit failures do not cancel later queued calls. Put a"
            " dependent step in a later response when you need to inspect the earlier result."
        )
    policy = limits.get("context_policy")
    if policy is not None and policy["mode"] != "none":
        config["system_template"] += (
            " Older bulky tool outputs may be replaced by historical observation metadata."
            f" The most recent {policy['keep_recent']} tool observations remain available verbatim."
            " Historical output is not the current workspace state; reread current files when needed."
        )
        if policy["mode"] == "recoverable":
            config["system_template"] += (
                " You may retrieve omitted observations with bash from read-only /observations/."
                " manifest.json lists short IDs, commands, exit status, sizes and filenames."
                " Each entry's output_file contains the displayed output; message_file"
                " contains the complete displayed tool message. Use cat, sed, grep"
                " or Python to read all or part. Nothing beyond the original output truncation"
                " is available. Retrieval uses normal tool and time budgets."
            )
    if limits.get("spec_blocker_exit", False):
        from spec_blocker import INSTRUCTION, OPEN_PROBLEM_INSTRUCTIONS

        if not limits.get("structured_finalization", False):
            config["system_template"] += INSTRUCTION
    if "open_problem_policy" in limits:
        from spec_blocker import OPEN_PROBLEM_INSTRUCTIONS

        config["system_template"] += OPEN_PROBLEM_INSTRUCTIONS[
            limits["open_problem_policy"]
        ]
    if limits.get("structured_finalization", False):
        from finalization_api import (
            INSTRUCTION as SPLIT_INSTRUCTION,
        )
        from finalization_api import (
            adapt_notice,
            split,
        )
        from finish_attempt import INSTRUCTION

        config["system_template"] += SPLIT_INSTRUCTION if split(limits) else INSTRUCTION
        review_policy = limits.get("fresh_context") or {}
        if review_policy.get("trigger") == "first_submission" and review_policy.get(
            "announce_review", True
        ):
            from fresh_context import SUBMISSION_REVIEW_INSTRUCTION

            config["system_template"] += adapt_notice(
                SUBMISSION_REVIEW_INSTRUCTION, split(limits)
            )
        if limits.get("terminal_semantics_feedback", False) and not split(limits):
            from finish_attempt import TERMINAL_SEMANTICS_INSTRUCTION

            config["system_template"] += TERMINAL_SEMANTICS_INSTRUCTION
        if limits.get("concise_finalization", False) and not split(limits):
            from finish_attempt import CONCISE_INSTRUCTION

            config["system_template"] += CONCISE_INSTRUCTION
    else:
        from finish_attempt import ECHO

        config["system_template"] += (
            " When finished, submit with one bash tool call alone using exactly: "
            + ECHO
        )
    if limits.get("exact_text_edit", False):
        from edit_file import instruction as edit_instruction

        config["system_template"] += edit_instruction(
            limits.get("whole_file_write", False)
        )
    if limits.get("whole_file_write", False):
        from write_file import INSTRUCTION as WRITE_INSTRUCTION

        config["system_template"] += WRITE_INSTRUCTION
    if "handoff_phase" in limits:
        from finalization_api import adapt_notice, split
        from handoff_phase import INSTRUCTION as HANDOFF_INSTRUCTION

        config["system_template"] += adapt_notice(HANDOFF_INSTRUCTION, split(limits))
    if limits.get("self_test_feedback", False):
        config["system_template"] += (
            " Keep added checks rerunnable in the workspace. Use small checks with"
            " independently initialized inputs. Give each assertion a unique label and"
            " report expected and actual values on failure. Derive expected values from"
            " the public contract, not implementation helpers or agreement between your"
            " own outputs. Run each new check before adding more. When a check fails,"
            " identify the exact assertion and inspect its setup before changing"
            " implementation or expectations. Preserve useful checks for the handoff."
        )
    if (limits.get("fresh_context") or {}).get("summary_checkpoint", False):
        from context_checkpoint import INSTRUCTION as CHECKPOINT_INSTRUCTION

        config["system_template"] += CHECKPOINT_INSTRUCTION
    return config


def run(args):
    output = args.output.resolve()
    if not output.is_relative_to("/bulk/dlk/local-harness/runs"):
        raise ValueError("Trial output must be a fresh project bulk run directory")
    output.mkdir(parents=True, exist_ok=False)
    admit_tasks([args.task], args.split)
    task = PROJECT / "tasks" / args.task
    inputs = freeze(output, task)
    task = inputs / "task"
    limits = load_protocol(args.protocol, inputs)
    limits["seed"] = args.seed
    metadata = json.loads((task / "task.json").read_text())
    require_task_protocol(metadata, limits)
    if (
        metadata.get("origin") == "imported"
        or "upstream" in metadata
        or "evaluator" in metadata
    ):
        from imported_fixtures import admitted, require_protocol

        admitted(task)
        require_protocol(limits)
    config = json.loads((inputs / "configs/agent.json").read_text())
    config = configure_agent(config, limits, args.protocol)
    policy = limits.get("context_policy")
    sampling = json.loads(args.sampling.read_text()) if args.sampling else {}
    if "seed" in sampling:
        raise ValueError("Seed must be declared separately from sampling")
    write_json(output / "agent-config.json", config)
    write_json(output / "sampling.json", sampling)
    sandbox.WORKER = inputs / "scripts/sandbox_worker.py"
    report = {
        "task": args.task,
        "split": args.split,
        "seed": args.seed,
        "mode": args.mode,
        "human_interventions": 0,
        "model": args.model,
        "origin": args.origin,
        "limits": limits,
        "fixture": manifest(task),
        "task_provenance": {
            "origin": metadata.get("origin", "authored"),
            "upstream": metadata.get("upstream"),
        },
        "canonical_correctness": False,
        "behavioral_correctness": None,
        "verified_correctness": False,
        "clean_agent_completion": False,
        "within_budget": False,
        "success": False,
        "limitations": [
            metadata.get("origin", "authored").capitalize()
            + " "
            + args.split
            + " fixture; small sample, not a general benchmark",
            "Warm ready server; model load excluded and reported by lifecycle owner",
            "Verifier is host-isolated but not an adversarial anti-cheating evaluator",
        ],
    }
    started = ENTRY_STARTED
    end = started + limits["task_wall_seconds"]
    workspace = output / "workspaces/0000"
    shutil.copytree(task / "public", workspace)
    runtime = (
        Runtime(
            python_test_library=limits["python_test_library"],
            library_catalog=inputs / "configs/python-test-libraries.json",
        )
        if "python_test_library" in limits
        else Runtime()
    )
    env = IsolatedEnvironment(
        runtime,
        workspace,
        output,
        limits["tool_timeout_seconds"],
        limits["tool_call_limit"],
        max_command_bytes=limits["max_command_bytes"],
        spec_blocker_exit=limits.get("spec_blocker_exit", False),
        structured_finalization=limits.get("structured_finalization", False),
        exact_text_edit=limits.get("exact_text_edit", False),
        whole_file_write=limits.get("whole_file_write", False),
        persistent_scratch=limits.get("persistent_scratch", False),
    )
    model_class = ReferenceModel if args.mode == "reference" else LocalModel
    extra_args = (task,) if args.mode == "reference" else ()
    model = model_class(*extra_args, args.origin, args.model, sampling, limits, output)
    if getattr(args, "prefix_warmup_receipt", None):
        if args.mode != "model":
            raise ValueError("Prefix warm-up is only meaningful for model trials")
        model.prefix_warmup = json.loads(args.prefix_warmup_receipt.read_text())
        write_json(output / "prefix-warmup-receipt.json", model.prefix_warmup)
        report["prefix_warmup"] = {
            "receipt": "prefix-warmup-receipt.json",
            "scope": "full initial public prompt; repeated-task ready-server timing",
            "cost_in_task_seconds": False,
            "cache_evidence": "prefix-warmup-usage.json when first response completed",
        }
    env.handoff_phase = model.handoff_phase
    if policy is not None:
        model.history = ObservationHistory(
            output, policy, expose_ids=limits.get("structured_finalization", False)
        )
        env.history = model.history
        if policy["mode"] == "recoverable":
            env.observations = model.history.root
    if limits.get("fresh_context") is not None:
        from fresh_context import FreshContext

        model.fresh_context = FreshContext(
            output, limits["fresh_context"], env, model=model
        )
        env.fresh_context = model.fresh_context
    if limits.get("progress_reminder") is not None:
        from progress_reminder import ProgressReminder

        model.progress_reminder = ProgressReminder(output, limits, env)
    agent = DefaultAgent(model, env, **config, output_path=output / "trajectory.json")
    try:
        with cancellation():
            agent_started = time.monotonic()
            try:
                budget = min(
                    limits["agent_wall_seconds"],
                    end - time.monotonic() - limits["verification_reserve_seconds"],
                )
                if limits.get("time_budget_feedback", False):
                    env.agent_deadline = time.monotonic() + budget
                    model.agent_deadline = env.agent_deadline
                    if model.fresh_context is not None:
                        model.fresh_context.start(env.agent_deadline, budget)
                    if model.progress_reminder is not None:
                        model.progress_reminder.start(env.agent_deadline, budget)
                with deadline(budget):
                    from initial_repository import build_task

                    task_text, initial = build_task(
                        task, limits.get("initial_repository")
                    )
                    if initial is not None:
                        write_json(output / "initial-repository.json", initial)
                        (output / "initial-task.txt").write_text(task_text)
                    outcome = agent.run(task_text)
                report["agent_outcome"] = outcome
                if (
                    limits.get("spec_blocker_exit", False)
                    and env.spec_blocker_claim is not None
                ):
                    report["spec_blocker_claim"] = env.spec_blocker_claim
                report["clean_agent_completion"] = (
                    outcome.get("exit_status") == "Submitted"
                )
            except Exception as error:
                report["agent_error"] = {
                    "type": type(error).__name__,
                    "message": str(error),
                }
            report["agent_wall_seconds"] = time.monotonic() - agent_started
            verify_started = time.monotonic()
            try:
                report["verification"] = verify(
                    runtime, env.workspace, task, output, end - time.monotonic()
                )
                report["canonical_correctness"] = report["verification"]["passed"]
                if limits.get("behavioral_gate"):
                    from behavioral_grade import verify_behavior

                    with deadline(end - time.monotonic()):
                        report["behavioral_verification"] = verify_behavior(
                            runtime, env.workspace, args.task, output / "behavioral"
                        )
                    report["behavioral_correctness"] = report[
                        "behavioral_verification"
                    ]["passed"]
                    write_json(
                        output / "behavioral-verification.json",
                        report["behavioral_verification"],
                    )
            except Exception as error:
                report["verification_error"] = {
                    "type": type(error).__name__,
                    "message": str(error),
                }
            report["verification_wall_seconds"] = time.monotonic() - verify_started
    except UnsafeCleanup as error:
        report["unsafe_cleanup"] = str(error)
    except RunCancelled as error:
        report["cancelled"] = str(error)
    finally:
        report["task_wall_seconds"] = time.monotonic() - started
        report["within_budget"] = (
            report["task_wall_seconds"] <= limits["task_wall_seconds"]
        )
        report["verified_correctness"] = report["canonical_correctness"] and (
            not limits.get("behavioral_gate")
            or report["behavioral_correctness"] is True
        )
        report["success"] = (
            report["verified_correctness"]
            and report["clean_agent_completion"]
            and report["within_budget"]
            and "cancelled" not in report
            and "unsafe_cleanup" not in report
        )
        if limits.get("spec_blocker_exit", False):
            from spec_blocker import finalize_report

            finalize_report(report)
        if limits.get("structured_finalization", False):
            from finish_attempt import compact_handoff

            report["final_handoff"] = (
                compact_handoff(env.final_handoff) if env.final_handoff else None
            )
            report["clean_agent_halt"] = report.get("agent_outcome", {}).get(
                "exit_status"
            ) in ("Submitted", "Blocked") and not any(
                key in report for key in ("agent_error", "cancelled", "unsafe_cleanup")
            )
            if report.get("agent_outcome", {}).get("exit_status") == "Blocked":
                report["task_adjudication"] = {
                    "status": "pending_outer_rubric",
                    "correct": None,
                    "authority": "separate trusted evaluator/reviewer; model claim is not a verdict",
                }
                report["verified_correctness"] = False
                report["success"] = False
        report["final_workspace"] = str(env.workspace)
        report["usage"] = model.serialize()["info"]["local_model"]
        report["tool_calls"] = env.calls
        report["runtime"] = runtime.manifest
        report["agent_source_sha256"] = hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest()
        agent.save(output / "trajectory.json")
        save_diff(task / "public", env.workspace, output / "changes.diff")
        if limits.get("structured_finalization", False):
            write_json(
                output / "finalization-review.json",
                {
                    "source": "outer-harness",
                    "model_handoff": "final-handoff.json"
                    if env.final_handoff
                    else None,
                    "changes_diff_sha256": hashlib.sha256(
                        (output / "changes.diff").read_bytes()
                    ).hexdigest(),
                    "final_workspace_manifest": manifest(env.workspace),
                    "canonical_correctness": report["canonical_correctness"],
                    "behavioral_correctness": report["behavioral_correctness"],
                    "verified_correctness": report["verified_correctness"],
                    "note": "Diff and evaluator outcomes are independent of model claims; full raw results retained separately.",
                },
            )
        write_json(output / "summary.json", report)
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "task",
                    "mode",
                    "success",
                    "canonical_correctness",
                    "clean_agent_completion",
                    "task_wall_seconds",
                )
            }
        )
    )
    return 2 if "unsafe_cleanup" in report else (0 if report["success"] else 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task", choices=[p.name for p in (PROJECT / "tasks").iterdir()], required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["model", "reference"], default="model")
    parser.add_argument("--origin", default="http://127.0.0.1:18080")
    parser.add_argument("--model", default="local-pilot")
    parser.add_argument("--sampling", type=Path)
    parser.add_argument("--prefix-warmup-receipt", type=Path)
    parser.add_argument("--protocol", choices=protocols(), default="mvp")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--split", choices=["development", "reserved"], default="development"
    )
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
