"""Repeat the Footsteps #17 CPU browser probe on the original workstation."""

import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from replay import PREDICATE_TYPE, STATEMENT_TYPE, sha256

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from delegate_artifacts import export_candidate, load_snapshot, read_file  # noqa: E402

# The Maintainer reviewed this historical host-side launcher before reusing it.
LAUNCHER = "17dcc66fea19143c270ff8f9cd5e6acc7b6021d106620677c96f74e57bf25af9"
PR_COMMIT = "bdcd7f0c4307ff180ac558b04b56444275edfb96"
PRODUCER = "Harness Lab Maintainer / isolated Footsteps keyboard replay"


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def checked_copy(source, target, expected):
    data = source.read_bytes()
    if sha256(data) != expected:
        raise ValueError(f"Unexpected source bytes in {source}")
    target.write_bytes(data)


def prepare_workspace(study, source, revision, tree):
    # Only the pinned public commit supplies the base. Candidate code stays inert.
    tar = subprocess.check_output(
        ["git", "-C", str(study / "17/pr"), "archive", "--format=tar", revision]
    )
    with tarfile.open(fileobj=io.BytesIO(tar)) as archive:
        if any(not (p.isfile() or p.isdir()) for p in archive):
            raise ValueError("Expected regular source files and directories")
        archive.extractall(tree, filter="data")
    if source is not None:
        for row in source["changes"]:
            name = row["path"]
            data, mode = read_file(source["files"], name, with_mode=True)
            dest = tree / name
            if (
                row["operation"] != "modify"
                or mode != row["executable_bits"]
                or sha256(dest.read_bytes()) != row["before_sha256"]
                or sha256(data) != row["after_sha256"]
            ):
                raise ValueError(f"Archived edit disagrees with manifest: {name}")
            dest.write_bytes(data)
            dest.chmod(0o644 | mode)


def capture(bulk, packet, staging):
    study = bulk / "research/footsteps-transfer-001"
    history = json.loads((ROOT / "results/footsteps-transfer-001.json").read_bytes())
    case = history["cases"][0]
    job = bulk / "delegation/jobs" / case["job_id"] / "artifact"
    manifest = job / "artifact.json"
    if sha256(manifest.read_bytes()) != case["artifact_sha256"]:
        raise ValueError(
            "Original reviewed artifact hash differs from published history"
        )
    snap = study / "17/snapshot"
    snapshot, inputs = load_snapshot(snap)
    if snapshot["snapshot_id"] != case["snapshot_id"]:
        raise ValueError("Unexpected public snapshot")
    original = json.loads(manifest.read_bytes()) | {"files": job / "files"}
    worker_paths = {row["path"] for row in original["changes"]}
    pr_paths = (
        subprocess.check_output(
            [
                "git",
                "-C",
                study / "17/pr",
                "diff",
                "--name-only",
                "-z",
                history["source_revision"],
                PR_COMMIT,
            ],
        )
        .decode()
        .split("\0")
    )
    allowed = set(snapshot["contract"]["allowed_write_paths"])
    if not (worker_paths | set(filter(None, pr_paths))) <= allowed:
        raise ValueError("Candidate changed a path outside the reviewed snapshot")
    (staging / "driver").mkdir()
    checked_copy(study / "isolate.py", staging / "isolate.py", LAUNCHER)
    checked_copy(
        study / "driver/browser.cjs",
        packet / "browser.cjs",
        case["replay_driver_sha256"],
    )
    shutil.copyfile(packet / "browser.cjs", staging / "driver/browser.cjs")
    for name in ("fonts.conf", "chrome"):
        shutil.copy2(study / "driver" / name, staging / "driver" / name)
    python = Path(shutil.which("python3")).resolve()
    node = Path(shutil.which("node")).resolve()
    command = f"/bin/python3 -B -S -m footsteps view examples/crossing.json -o /tmp/crossing.html && exec {node} /driver/browser.cjs"
    verifier = {
        "launcher_sha256": LAUNCHER,
        "browser_driver_sha256": case["replay_driver_sha256"],
        "support_sha256": {
            n: sha256((staging / "driver" / n).read_bytes())
            for n in ("fonts.conf", "chrome")
        },
        "python3": str(python),
        "guest_argv": ["/bin/sh", "-ec", command],
    }
    write_json(packet / "verifier.json", verifier)
    verifier_id = sha256((packet / "verifier.json").read_bytes())
    for label, kind in [("worker", "worker"), ("integrated", "pr")]:
        out = packet / label
        out.mkdir()
        tree = staging / "17" / ("evaluation-" + kind)
        tree.mkdir(parents=True)
        revision = history["source_revision"] if label == "worker" else PR_COMMIT
        prepare_workspace(
            study, original if label == "worker" else None, revision, tree
        )
        # Re-export exactly the public snapshot projection of the tree about to run.
        projection = staging / (label + "-projection")
        for name in inputs:
            dest = projection / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tree / name, dest)
        exported = staging / (label + "-artifact")
        export_candidate(snap, projection, exported)
        for src, dst in [
            ("artifact.json", "artifact.json"),
            ("changes.diff", "changes.patch"),
        ]:
            shutil.copyfile(exported / src, out / dst)
        artifact_id = sha256((out / "artifact.json").read_bytes())
        if label == "worker" and artifact_id != case["artifact_sha256"]:
            raise ValueError(
                "Tested Worker sources do not reproduce the reviewed artifact"
            )
        # isolate.py reuses this existing tree read-only. Its subprocess has no network.
        proc = subprocess.run(
            [sys.executable, staging / "isolate.py", "17", kind], stdout=subprocess.PIPE
        )
        proc.check_returncode()
        observed = proc.stdout
        finished_at = datetime.now(UTC).isoformat()
        if observed != (study / "17" / (kind + "-behavior.log")).read_bytes():
            raise ValueError(
                f"{label}: fresh stdout differs from archived browser observations"
            )
        (out / "stdout.txt").write_bytes(observed)
        facts = {
            "producer": PRODUCER,
            "finished_at": finished_at,
            "checkout_revision": revision,
            "verifier_sha256": verifier_id,
            "launcher_arguments": ["17", kind],
            "exit_code": proc.returncode,
            "stdout_sha256": sha256(observed),
        }
        write_json(
            out / "receipt.json", {"artifact_sha256": artifact_id, "probe": facts}
        )
        write_json(
            out / "statement.json",
            {
                "_type": STATEMENT_TYPE,
                "subject": [
                    {"name": "artifact.json", "digest": {"sha256": artifact_id}}
                ],
                "predicateType": PREDICATE_TYPE,
                "predicate": facts,
            },
        )
    print("Captured both isolated probes; stdout matches both archived logs.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bulk", type=Path)
    parser.add_argument("output", type=Path, help="New packet directory")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="footsteps-binding-") as temp:
        capture(args.bulk.resolve(), args.output.resolve(), Path(temp))
