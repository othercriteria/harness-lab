"""Outer-only fixed-world continuation adapter for the declared experiment."""

import copy
import shutil
from pathlib import Path

from check_fixtures import manifest
from evidence import read_archived_message
from mini_bootstrap import DefaultAgent
from sandbox import write_json
from scoped_context import ledger
from scoped_runtime import ScopeRuntime
from stage_scoped_case import bounded_copy_file, copy_initial_tree, read, sha


def archive_boundary_history(source, output, through):
    """Validate closed historical tool boundaries without replay or fake receipts."""
    from read_file import verify_receipt
    from scoped_runtime import verify_return_receipt

    directory = output / "historical-boundaries"
    directory.mkdir()
    files = {}
    for number in range(1, through + 1):
        prefix = directory / f"tool-{number:03d}"
        for suffix in ("request", "result", "cleanup"):
            name = f"tool-{number:03d}.{suffix}.json"
            original = source / name
            if original.exists():
                bounded_copy_file(original, directory / name)
                files[name] = sha(directory / name)
        request = read(prefix.with_suffix(".request.json"))
        result = read(prefix.with_suffix(".result.json"))
        if request.get("mode") == "adapter-read":
            verify_receipt(prefix)
        elif request.get("mode") == "adapter-control":
            if request.get("name") == "return_scope":
                verify_return_receipt(prefix)
            elif not (
                request.get("executed") is False
                and result.get("ok") is True
                and result.get("executed") is False
                and result.get("cleanup_required") is False
                and "terminal_control" not in result
                and (
                    request.get("name") == "checkpoint_context"
                    and result.get("checkpoint_control") == "summary_saved"
                    or request.get("name") == "finish_attempt"
                    and result.get("review_control") == "fresh_context_requested"
                )
            ):
                raise ValueError("Invalid historical native boundary")
        else:
            receipt = read(prefix.with_suffix(".cleanup.json"))
            if receipt.get("verified") is not True:
                raise ValueError("Historical process cleanup is unverified")
    write_json(
        directory / "manifest.json",
        {
            "scope": "Outer-only closed historical prefix; never a new execution receipt",
            "source": str(source),
            "through_tool_call": through,
            "files": files,
        },
    )
    return through


def load_case(directory):
    directory = Path(directory).resolve()
    if not directory.is_relative_to("/bulk/dlk/local-harness/research"):
        raise ValueError("Continuation case must be a staged project-bulk artifact")
    info = read(directory / "manifest.json")
    for relative, expected in info["files"].items():
        p = directory / relative
        if (
            not p.resolve().is_relative_to(directory)
            or p.is_symlink()
            or sha(p) != expected
        ):
            raise ValueError("Continuation fixture binding mismatch")
    source = Path(info["source_trial"]).resolve()
    if not source.is_relative_to("/bulk/dlk/local-harness/runs"):
        raise ValueError("Unexpected historical source")
    summary = read(source / "summary.json")
    if sha(source / "summary.json") != info["source_summary_sha256"]:
        raise ValueError("Historical source summary changed")
    task = source / "inputs/task"
    if manifest(task) != summary["fixture"]:
        raise ValueError("Historical task differs from its evaluated fixture")
    limits = read(directory / "source-limits.json")
    seconds = info["budget"]["remaining_agent_seconds_at_resume"]
    if seconds > info["original_remaining_wall_seconds"]:
        raise ValueError("Continuation wall allowance increased")
    if limits["fresh_context"]["trigger"] != "context_headroom":
        raise ValueError("This experiment restores only context-triggered recovery")
    limits["agent_wall_seconds"] = seconds
    limits["task_wall_seconds"] = seconds + limits["verification_reserve_seconds"]
    return {
        "directory": directory,
        "info": info,
        "source": source,
        "source_task": task,
        "task_name": summary["task"],
        "limits": limits,
        "source_summary": summary,
    }


def seed_attempt(case, model, env, arm):
    directory = case["directory"]
    info = case["info"]
    output = model.output
    budget = info["budget"]
    model.calls = budget["model_calls_already_spent"]
    model.completion_tokens = budget["completion_tokens_already_spent"]
    model.prompt_tokens = sum(
        read(case["source"] / f"request-{n:03d}.response.bin")["usage"]["prompt_tokens"]
        for n in range(1, model.calls + 1)
    )
    budget = {**budget, "prompt_tokens_already_spent": model.prompt_tokens}
    env.calls = budget["tool_calls_already_spent"]
    env.initial_workspace = directory / "task-start-workspace"
    if env.scratch is None:
        raise ValueError("Continuation requires retained scratch")
    # Replace only the fresh empty controller-owned scratch generation.
    shutil.rmtree(env.scratch.current)
    copy_initial_tree(directory / "scratch", env.scratch.current)
    records = read(directory / "observations/manifest.json")["observations"]
    for record in records:
        for name in (record["message_file"], record["output_file"]):
            bounded_copy_file(
                directory / "observations" / name, model.history.root / name
            )
        model.history.records[record["id"]] = copy.deepcopy(record)
        model.history.visible_messages[record["id"]] = read_archived_message(
            model.history.root, record, max_bytes=4 * 1024 * 1024
        )
    model.history.save_manifest()
    if env.checks is None:
        raise ValueError("Continuation requires check records")
    for path in (directory / "checks").iterdir():
        bounded_copy_file(path, env.checks / path.name, limit=256 * 1024)
    history_name = info["history_archive"]
    if history_name:
        history = output / history_name
        history.mkdir()
        for path in (directory / history_name).iterdir():
            bounded_copy_file(path, history / path.name)
        env.history_archive = history
    if model.fresh_context:
        model.fresh_context.historical_boundary_through = archive_boundary_history(
            case["source"], output, env.calls
        )
        resets = [
            read(p)
            for p in case["source"].glob("fresh-context-reset-*.json")
            if read(p)["model_calls"] <= model.calls
            and read(p)["tool_calls"] <= env.calls
        ]
        model.fresh_context.reset_count = len(resets)
        model.fresh_context.sequence = len(resets) + 1
        # Existing resets consumed global allowance; prefix projection is owned by
        # the fixed controller until the next real parent recovery.
    driver = ScopeRuntime(model, env, arm=arm)
    model.scope_runtime = env.scope_runtime = driver
    write_json(
        output / "continuation.json",
        {
            "kind": "controlled fixed-world continuation, not a whole-task timing comparison",
            "case": info["case"],
            "arm": arm,
            "stage_manifest_sha256": sha(directory / "manifest.json"),
            "source_trial": str(case["source"]),
            "spent_counters": budget,
            "workspace_retained": True,
            "scratch_retained": True,
            "source_outcome_exposed": False,
            "stage_directory": str(directory),
        },
    )
    return driver


class ContinuationAgent(DefaultAgent):
    def __init__(self, *args, continuation, **kwargs):
        self.continuation = continuation
        self._installed = False
        super().__init__(*args, **kwargs)
        self.n_calls = continuation["info"]["budget"]["model_calls_already_spent"]

    def add_messages(self, *messages):
        if not self._installed:
            if (
                self.messages
                or len(messages) != 2
                or [m["role"] for m in messages] != ["system", "user"]
            ):
                raise ValueError("Expected initial system/task installation")
            directory = self.continuation["directory"]
            prefix = read(directory / "outer-prefix.json")
            if [m["content"] for m in messages] != [m["content"] for m in prefix[:2]]:
                raise ValueError("Continuation task authority differs")
            self.messages = copy.deepcopy(prefix)
            self.model.scope_runtime.controller.install_fixed_return(
                self.messages,
                read(directory / "parent.json"),
                read(directory / "full.json"),
                read(directory / "return.json"),
                ledger(self.model, self.env),
            )
            self._installed = True
            return self.messages
        return super().add_messages(*messages)
