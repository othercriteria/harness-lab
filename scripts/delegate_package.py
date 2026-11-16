"""Outer-only registration of reviewed public work and a pinned local recipe.

This is not a solver tool. A package includes private evaluator and harness bytes;
only runtime/tasks/delegated-task/public may be mounted into the solver.
"""

import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

from delegate_artifacts import create_snapshot, digest, encoded, load_snapshot
from delegate_verify import validate_plan
from protocol import load_protocol, require_task_protocol

PROJECT = Path(__file__).resolve().parents[1]
STORE = Path("/bulk/dlk/local-harness/delegation")
TASK = "delegated-task"


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_manifest(root):
    result = {}
    for p in sorted(root.rglob("*")):
        if ".venv" in p.relative_to(root).parts or "__pycache__" in p.parts:
            continue
        if p.is_symlink():
            raise ValueError(f"Symlink in outer package: {p}")
        if p.is_file():
            result[p.relative_to(root).as_posix()] = sha(p)
    return result


def package_path(identifier, store=STORE):
    if not isinstance(identifier, str) or not re.fullmatch("[a-f0-9]{64}", identifier):
        raise ValueError("Invalid package ID")
    path = store / "packages" / identifier
    if path.is_symlink():
        raise ValueError("Package aliases are forbidden")
    return path


def public_contract_id(snapshot_id, brief):
    return digest(
        encoded({"snapshot_id": snapshot_id, "brief_sha256": digest(brief.encode())})
    )


def verify_package(identifier, store=STORE):
    root = package_path(identifier, store)
    record = read(root / "package.json")
    if hashlib.sha256(encoded(record)).hexdigest() != identifier:
        raise ValueError("Package identity mismatch")
    actual = file_manifest(root)
    actual.pop("package.json")
    if actual != record["files"]:
        raise ValueError("Package file integrity mismatch")
    for name, expected_digest in record["runtime_dependencies"].items():
        if sha(name) != expected_digest:
            raise ValueError(f"Changed harness dependency: {name}")
    snapshot, _ = load_snapshot(root / "source")
    if snapshot["snapshot_id"] != record["snapshot_id"]:
        raise ValueError("Registered snapshot mismatch")
    if (root / "runtime/.venv").resolve() != Path(record["venv"]).resolve():
        raise ValueError("Changed runtime environment link")
    return root, record


def register(specification, *, project=PROJECT, store=STORE):
    """Prepare only; no GPU/service/network/model activity or candidate execution."""
    required = {
        "label",
        "input_files",
        "allowed_write_paths",
        "brief",
        "recipe_task",
        "task_seconds",
        "verification_seconds",
        "checks",
        "check_files",
        "admission",
    }
    if not isinstance(specification, dict) or set(specification) != required:
        raise ValueError("Invalid outer job specification")
    s = specification
    if not isinstance(s["label"], str) or not 1 <= len(s["label"]) <= 120:
        raise ValueError("Invalid job label")
    if not isinstance(s["brief"], str) or not 1 <= len(s["brief"].encode()) <= 32768:
        raise ValueError("Invalid public brief")
    seconds, reserve = s["task_seconds"], s["verification_seconds"]
    if type(seconds) is not int or not 30 <= seconds <= 600:
        raise ValueError("Invalid delegated task ceiling")
    if type(reserve) is not int or not 5 <= reserve <= min(120, seconds // 2):
        raise ValueError("Invalid independent verification reserve")
    admission = s["admission"]
    if not isinstance(admission, dict) or admission.get("approved") is not True:
        raise ValueError("Outer public-contract admission required")
    # These are outer-owned attestations, not candidate-provided claims.
    for key in ("blind_review", "sealed_solution"):
        entry = admission.get(key, {})
        if set(entry) != {"path", "sha256"} or sha(entry["path"]) != entry["sha256"]:
            raise ValueError("Missing or changed blind admission evidence")
    validate_plan({"version": 1, "checks": s["checks"]})
    if not isinstance(s["check_files"], dict) or len(s["check_files"]) > 32:
        raise ValueError("Invalid private check selection")
    for name in s["check_files"]:
        if (
            not re.fullmatch(r"[a-zA-Z0-9_-]+\.(py|json|txt)", name)
            or name == "checks.json"
        ):
            raise ValueError("Invalid private check filename")
    recipes = read(project / "configs/frontier-practical-recipes-v1.json")["recipes"]
    choices = [r for r in recipes if r["task"] == s["recipe_task"]]
    if len(choices) != 1:
        raise ValueError("Select one registered practical recipe")
    recipe = choices[0]
    for path_key, digest_key in [
        ("server_config_path", "server_config_sha256"),
        ("protocol_path", "protocol_sha256"),
    ]:
        if sha(recipe[path_key]) != recipe[digest_key]:
            raise ValueError("Recipe source changed")
    freeze = read(project / recipe["runtime_freeze"])
    if sha(project / recipe["runtime_freeze"]) != recipe["runtime_freeze_sha256"]:
        raise ValueError("Recipe freeze changed")
    packages = store / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    pending = packages / (".preparing-" + uuid.uuid4().hex)
    pending.mkdir()
    try:
        snapshot = create_snapshot(
            project, s["input_files"], s["allowed_write_paths"], pending / "source"
        )
        if admission.get("public_contract_sha256") != public_contract_id(
            snapshot["snapshot_id"], s["brief"]
        ):
            raise ValueError("Blind admission describes a different public contract")
        runtime = pending / "runtime"
        (runtime / "scripts").mkdir(parents=True)
        for p in sorted((project / "scripts").glob("*.py")):
            if p.is_symlink():
                raise ValueError("Untrusted harness source alias")
            shutil.copyfile(p, runtime / "scripts" / p.name)
        (runtime / "configs/protocols").mkdir(parents=True)
        for name in ("agent.json", "python-test-libraries.json"):
            shutil.copyfile(project / "configs" / name, runtime / "configs" / name)
        for name in ("uv.lock", "flake.lock", "pyproject.toml"):
            shutil.copyfile(project / name, runtime / name)
        profile = read(recipe["server_config_path"])[recipe["profile"]]
        (runtime / "configs/servers.json").write_bytes(
            encoded({recipe["profile"]: profile})
        )
        limits = read(recipe["protocol_path"])
        limits.pop("behavioral_gate", None)
        limits.pop("python_test_library", None)
        limits.update(
            protocol="delegated-v1",
            status="Real delegated work; outer review required",
            task_wall_seconds=seconds,
            agent_wall_seconds=seconds - reserve,
            verification_reserve_seconds=reserve,
            request_timeout_seconds=seconds - reserve,
            success="Outer reviewed useful patch; no benchmark canonical score",
            budget_note="New-task setup is charged in job total; no prefix warmup",
        )
        (runtime / "configs/protocols/delegated-v1.json").write_bytes(encoded(limits))
        task = runtime / "tasks" / TASK
        shutil.copytree(pending / "source/public", task / "public")
        (task / "public/task.md").write_text(s["brief"])
        (task / "private").mkdir()
        # The export policy is outer-only. Check it before running any evaluator.
        shutil.copytree(pending / "source", task / "private/snapshot")
        (task / "private/checks.json").write_bytes(
            encoded({"version": 1, "checks": s["checks"]})
        )
        for name, source in s["check_files"].items():
            p = Path(source)
            if p.is_symlink() or p.stat().st_size > 1024 * 1024:
                raise ValueError("Invalid outer check file")
            shutil.copyfile(p, task / "private" / name)
        metadata = {
            "name": TASK,
            "kind": "delegated-repository",
            "origin": "delegated",
            "split": "development",
            "admission_status": "admitted",
            "requires_outer_review": True,
        }
        (task / "task.json").write_bytes(encoded(metadata))
        require_task_protocol(metadata, load_protocol("delegated-v1", runtime))
        record = {
            "version": 1,
            "label": s["label"],
            "snapshot_id": snapshot["snapshot_id"],
            "profile": recipe["profile"],
            "protocol": "delegated-v1",
            "task_seconds": seconds,
            "recipe_source": recipe,
            "admission": admission,
            "venv": str(project / ".venv"),
            "runtime_dependencies": freeze["runtime_dependencies"],
            "files": file_manifest(pending),
        }
        identifier = hashlib.sha256(encoded(record)).hexdigest()
        (pending / "package.json").write_bytes(encoded(record) + b"\n")
        (runtime / ".venv").symlink_to(project / ".venv")
        destination = package_path(identifier, store)
        if destination.exists():
            verify_package(identifier, store)
            shutil.rmtree(pending)
        else:
            pending.rename(destination)
        verify_package(identifier, store)
        return {
            "package_id": identifier,
            "label": s["label"],
            "snapshot_id": snapshot["snapshot_id"],
        }
    except BaseException:
        shutil.rmtree(pending, ignore_errors=True)
        raise
