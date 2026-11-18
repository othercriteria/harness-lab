"""Build the public example offline, optionally registering it on the lab host."""

import argparse
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from delegate_artifacts import create_snapshot, digest, encoded, load_snapshot
from delegate_job import validate_request
from delegate_package import public_contract_id, register, task_text
from delegate_verify import validate_plan

FILES = ["observatory/app.js", "tests/test_observe_ui.js"]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", type=Path, help="new directory for the prepared inputs"
    )
    parser.add_argument(
        "--register-for",
        metavar="SESSION",
        help="also register on the lab workstation and write its dispatch request",
    )
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(exist_ok=False)
    with tempfile.TemporaryDirectory() as tmp:
        for name in FILES:
            target = Path(tmp) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((HERE / "starter" / name).read_bytes())
            target.chmod(0o644)
        create_snapshot(Path(tmp), FILES, FILES, out / "source")
    snapshot, _ = load_snapshot(out / "source")
    brief = (HERE / "brief.md").read_text()
    contract_id = public_contract_id(snapshot["snapshot_id"], brief)
    spec = {
        "label": "Observatory Use label for unclassified delegated jobs",
        "input_files": FILES,
        "allowed_write_paths": FILES,
        "brief": brief,
        "recipe_id": "apprentice-qwen-32k-v1",
        "task_seconds": 240,
        "verification_seconds": 15,
        "checks": [
            {
                "name": "both requested files edited",
                "argv": ["/bin/python3", "-I", "-S", "/evaluation/changed.py"],
                "timeout": 5,
            }
        ],
        "check_files": {"changed.py": str(HERE / "changed.py")},
        "admission": {
            "mode": "outer_only_experimental",
            "approved": True,
            "public_contract_sha256": contract_id,
            "reason": "Maintainer-authorized apprentice assignment on a reviewed issue. No blind pre-review or sealed reference. Outer review includes separate rendering checks.",
        },
    }
    validate_plan({"version": 1, "checks": spec["checks"]})
    record = json.loads((HERE / "run.json").read_text())
    request = json.loads((HERE / "request.json").read_text())
    validate_request(request, store=out)
    # A checkout's absolute path varies. Bind each private checker by content.
    portable_spec = {
        **spec,
        "check_files": {
            name: digest(Path(path).read_bytes())
            for name, path in spec["check_files"].items()
        },
    }
    task = task_text(brief, snapshot)
    for field, actual in (
        ("snapshot_id", snapshot["snapshot_id"]),
        ("public_contract_sha256", contract_id),
        ("task_sha256", digest(task.encode())),
        ("portable_spec_sha256", digest(encoded(portable_spec))),
        ("package_id", request["package_id"]),
        ("request_sha256", digest(encoded(request))),
    ):
        if record[field] != actual:
            raise ValueError(f"Prepared example differs from the recorded {field}")
    write_json(out / "spec.json", spec)
    (out / "task.md").write_text(task)
    print(f"Snapshot {snapshot['snapshot_id']}\nPublic contract {contract_id}")
    if args.register_for:
        registered = register(spec, source_project=out / "source/public")
        request = {
            "package_id": registered["package_id"],
            "idempotency_key": f"observatory-label-replay-{args.register_for}-{registered['package_id']}",
            "session_id": args.register_for,
            "classification": "diagnostic_replay",
            "seed": 19012,
            "total_seconds": 900,
        }
        validate_request(request)
        write_json(out / "request.json", request)
        print(f"Registered {request['package_id']}")


if __name__ == "__main__":
    main()
