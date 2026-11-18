"""External behavioral verdicts; submitted code runs only in disposable sandboxes.

This supplements, rather than replaces, the original in-process acceptance suite.
Expected values and authoritative comparisons never enter candidate namespaces.
"""

import hashlib
import json
import random
import shutil
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from control import UnsafeCleanup
from sandbox import perform_tool, write_json


def require_cleanup(prefix, role):
    """Fail closed on unreadable receipts without replacing an existing fatal error."""
    # Runtime's fatal error may identify the exact owned unit and cleanup stage.
    # A secondary receipt failure must not replace that recovery information.
    if isinstance(sys.exception(), UnsafeCleanup):
        return
    path = prefix.with_suffix(".cleanup.json")
    try:
        receipt = json.loads(path.read_text())
    except (OSError, ValueError, UnicodeError) as error:
        raise UnsafeCleanup(
            f"External gate cannot verify {role} cleanup: {prefix}; "
            f"unreadable cleanup receipt ({type(error).__name__})"
        ) from error
    if not isinstance(receipt, dict) or receipt.get("verified") is not True:
        raise UnsafeCleanup(
            f"External gate cannot verify {role} cleanup: {prefix}; receipt={receipt!r}"
        )


@dataclass
class Probe:
    result: dict
    workspace: Path


class Gate:
    def __init__(self, runtime, submission, output):
        if output.resolve().is_relative_to(submission.resolve()):
            raise ValueError("Gate output must be outside the submission tree")
        self.runtime = (
            runtime.for_evaluation()
            if getattr(runtime, "test_library", None) is not None
            else runtime
        )
        self.submission = submission
        self.output = output
        self.output.mkdir(exist_ok=False)
        self.rng = random.Random(20261102)
        self.calls = 0
        self.records = []
        self.started = time.monotonic()
        write_json(
            output / "protocol.json",
            {
                "version": 1,
                "fixture_generator_seed": 20261102,
                "limits": "Ordinary solver resource limits; no private tests or observations mounted",
                "authority": "Outer comparisons, never candidate test-report fields",
            },
        )

    def token(self):
        return f"{self.rng.getrandbits(64):016x}"

    def number(self):
        return self.rng.randint(10000, 99999)

    @staticmethod
    def path(workspace, relative):
        path = Path(relative)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError("Invalid probe-relative path")
        result = workspace / path
        if result.is_symlink() or not result.resolve().is_relative_to(
            workspace.resolve()
        ):
            raise ValueError("Probe path escaped workspace")
        return result

    def invoke(self, source, command, setup, fresh=False):
        self.calls += 1
        if self.calls > 32:
            raise RuntimeError("External gate sandbox-call limit exceeded")
        directory = self.output / f"step-{self.calls:03d}"
        workspace = directory / "workspaces/0000"
        for item in source.rglob("*"):
            if not (
                stat.S_ISDIR(item.lstat().st_mode) or stat.S_ISREG(item.lstat().st_mode)
            ):
                raise ValueError("Submission contains a non-regular snapshot entry")
        shutil.copytree(source, workspace)
        if fresh:
            # Model-written scratch files must not contaminate evaluator inputs.
            # Clear only explicitly evaluator-owned roots in this disposable copy.
            roots = {Path(name).parts[0] for name in setup}
            for root in roots:
                if root != "probe" and not root.startswith("probe_"):
                    raise ValueError("Gate setup needs its own probe namespace")
                target = self.path(workspace, root)
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
        for name, content in setup.items():
            if not isinstance(content, bytes) or len(content) > 1024 * 1024:
                raise ValueError("Probe setup must contain bounded bytes")
            path = self.path(workspace, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        write_json(
            directory / "setup.json",
            {
                name: {"sha256": hashlib.sha256(data).hexdigest(), "hex": data.hex()}
                for name, data in setup.items()
            },
        )
        prefix = directory / "command"
        try:
            result, updated = perform_tool(
                self.runtime, workspace, "execute", {"command": command}, 3, prefix
            )
        finally:
            require_cleanup(prefix, "candidate")
        return Probe(result, updated)

    def case(self, name, setup, command):
        write_json(
            self.output / f"case-{len(list(self.output.glob('case-*.json'))):03d}.json",
            {"name": name, "first_step": self.calls + 1},
        )
        return self.invoke(self.submission, command, setup, fresh=True)

    def step(self, previous, command, setup=None):
        return self.invoke(previous.workspace, command, setup or {})

    def read(self, probe, relative):
        path = self.path(probe.workspace, relative)
        if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("Missing or oversized probe artifact")
        return path.read_bytes()

    def absent(self, probe, relative):
        return not self.path(probe.workspace, relative).exists()

    @staticmethod
    def json(probe):
        return json.loads(probe.result.get("stdout", ""))

    def record(self, name, passed, details):
        record = {"name": name, "passed": bool(passed), "details": details}
        write_json(self.output / f"check-{len(self.records):03d}.json", record)
        self.records.append(record)

    def observe_sqlite(self, probe, relative, queries):
        """Inspect untrusted database bytes in a clean, data-only verifier."""
        self.calls += 1
        if self.calls > 32:
            raise RuntimeError("External gate sandbox-call limit exceeded")
        directory = self.output / f"observer-{self.calls:03d}"
        workspace = directory / "data"
        workspace.mkdir(parents=True)
        for suffix in ("", "-wal", "-shm"):
            if suffix and self.absent(probe, relative + suffix):
                continue
            (workspace / ("database" + suffix)).write_bytes(
                self.read(probe, relative + suffix)
            )
        # No candidate Python, libraries, tests, or startup hooks enter this sandbox.
        code = (
            "import json,sqlite3\n"
            "c=sqlite3.connect('file:/workspace/database?mode=ro',uri=True)\n"
            "c.execute('PRAGMA trusted_schema=OFF')\n"
            "c.execute('PRAGMA query_only=ON')\n"
            f"queries={queries!r}\n"
            "print(json.dumps([c.execute(q).fetchall() for q in queries]))\n"
            "c.close()\n"
        )
        prefix = directory / "observe"
        try:
            result, _ = self.runtime.sandbox(
                workspace,
                {
                    "mode": "grade",
                    "argv": ["/bin/python3", "-I", "-S", "-c", code],
                    "timeout": 3,
                },
                prefix,
            )
        finally:
            require_cleanup(prefix, "observer")
        if not result.get("ok") or result.get("stderr"):
            raise ValueError("Clean SQLite observer failed")
        return json.loads(result["stdout"])

    def finish(self):
        report = {
            "passed": bool(self.records) and all(r["passed"] for r in self.records),
            "checks": self.records,
            "sandbox_calls": self.calls,
            "wall_seconds": time.monotonic() - self.started,
            "limitations": [
                "Supplemental behavioral coverage; does not replace full canonical tests",
                "No claim of adversarial trust in assertions inside candidate interpreters",
                "Finite deterministic cases; not a proof against task-specific behavioral spoofing",
            ],
        }
        write_json(self.output / "summary.json", report)
        return report


def verify_behavior(runtime, submission, task, output):
    gate = Gate(runtime, submission, output)
    if task == "build-flow":
        from grade_buildflow import check
    elif task in {
        "build-flow-artifacts",
        "build-flow-engine",
        "build-flow-engine-v2",
        "build-flow-core",
        "build-flow-persistence",
        "build-flow-persistence-v2",
    }:
        from grade_artifacts import check
    elif task == "tabreport-maintenance":
        from grade_tabreport import check
    elif task == "tabreport-diff":
        from grade_tabreport_diff import check
    elif task in {"lease-pool", "lease-pool-guided", "lease-pool-focused"}:
        from grade_lease_pool import check
    elif task in {"frame-decoder", "frame-decoder-focused"}:
        from grade_frame_decoder import check
    elif task == "bundle-reader":
        from grade_bundle_reader import check
    elif task in {"pagination", "pagination-guided", "pagination-focused"}:
        from grade_pagination import check
    elif task in {"file-index", "file-index-scan-guided"}:
        from grade_fileindex import check
    elif task in {"event-import", "event-import-guided", "event-import-guided-v2", "event-import-guided-v3", "event-import-guided-v4", "event-import-guided-v5", "event-import-guided-v6", "event-import-guided-v7", "event-import-guided-v8", "event-import-guided-v9", "event-import-guided-v10", "event-import-guided-v11", "event-import-guided-v12"}:
        from grade_events import check
    elif task in {"sqlite-migrations-v5", "sqlite-migrations-v5-guided", "sqlite-migrations-core-guided", "sqlite-migrations-core-guided-v2", "sqlite-migrations-core-guided-v3", "sqlite-migrations-core-guided-v4", "sqlite-migrations-core-guided-v5", "sqlite-migrations-core-guided-v6", "sqlite-migrations-core-guided-v7", "sqlite-migrations-core-guided-v8"}:
        from grade_migrations_v5 import check
    elif task in {
        "sqlite-migrations-v2",
        "sqlite-migrations-v3",
        "sqlite-migrations-v4",
    }:
        from grade_migrations import check
    else:
        raise ValueError(f"No external behavioral gate for {task}")
    try:
        check(gate)
        if task in {"build-flow-core", "build-flow-persistence-v2"}:
            from grade_output_paths import check as check_output_paths
            from grade_preflight import check as check_preflight

            check_preflight(gate, require_plan=task == "build-flow-persistence-v2")
            check_output_paths(gate)
    except UnsafeCleanup as error:
        gate.record("unsafe-cleanup", False, {"message": str(error)})
        gate.finish()
        raise
    except Exception as error:
        gate.record(
            "gate-error", False, {"type": type(error).__name__, "message": str(error)}
        )
    return gate.finish()
