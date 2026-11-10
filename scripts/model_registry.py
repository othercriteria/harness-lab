"""Outer-owned local model evidence; catalog definitions stay in servers.json."""

import argparse
import datetime
import hashlib
import json
import os
import stat
import tempfile
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
REGISTRY = Path("/bulk/dlk/local-harness/registry/v1")


def identity(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def publish(path, data):
    """Readers see complete records, including after interruption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
            temporary = Path(f.name)
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def fingerprint(info):
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Weight is not a regular file")
    return {
        key: getattr(info, "st_" + key)
        for key in ("dev", "ino", "size", "mtime_ns", "ctime_ns")
    }


def verify_weight(
    path, expected, *, mode="full", registry=REGISTRY, guard=lambda: None
):
    """Metadata reuse is weaker evidence, never a claim of a fresh hash scan."""
    if mode not in ("full", "metadata"):
        raise ValueError("Unknown weight verification mode")
    path = Path(path)
    started = time.monotonic()
    key = {
        "path": str(path.absolute()),
        "resolved_path": str(path.resolve()),
        "sha256": expected["sha256"],
        "size": expected["size"],
    }
    receipt_path = registry / "weights" / (identity(key) + ".json")
    before = fingerprint(path.stat())
    if before["size"] != expected["size"]:
        raise RuntimeError("Weight size mismatch: " + str(path))
    baseline = None
    if mode == "metadata":
        try:
            candidate = read(receipt_path)
            if (
                candidate.get("version") == 1
                and candidate.get("method") == "full"
                and candidate.get("identity") == key
                and candidate.get("stat") == before
            ):
                baseline = candidate
        except (OSError, ValueError, TypeError, AttributeError):
            pass  # Absent/malformed/stale cache requires full verification.
    if baseline is None:
        digest = hashlib.sha256()
        last_check = time.monotonic()
        with path.open("rb") as stream:
            if fingerprint(os.fstat(stream.fileno())) != before:
                raise RuntimeError("Weight changed before hashing")
            while chunk := stream.read(8 * 1024**2):
                digest.update(chunk)
                if time.monotonic() - last_check > 2:
                    guard()
                    last_check = time.monotonic()
            after = fingerprint(os.fstat(stream.fileno()))
        if after != before or fingerprint(path.stat()) != before:
            raise RuntimeError("Weight changed during hashing")
        if digest.hexdigest() != expected["sha256"]:
            raise RuntimeError("Weight hash mismatch: " + str(path))
        baseline = {
            "version": 1,
            "method": "full",
            "identity": key,
            "stat": before,
            "verified_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        publish(receipt_path, baseline)
        method = "full"
    else:
        method = "metadata"
    if (
        fingerprint(path.stat()) != before
        or str(path.resolve()) != key["resolved_path"]
    ):
        raise RuntimeError("Weight changed during verification")
    return {
        "path": str(path),
        "sha256": expected["sha256"],
        "size": before["size"],
        "requested_mode": mode,
        "method": method,
        "stat": before,
        "full_verification": baseline,
        "full_verification_id": identity(baseline),
        "seconds": time.monotonic() - started,
        "assurance": "Fresh SHA-256 scan"
        if method == "full"
        else "Metadata matches an earlier full scan; content not rehashed",
    }


def record_campaign(campaign, registry=REGISTRY):
    """Import raw timing observations, not source acceptance or routing decisions."""
    campaign = Path(campaign).resolve()
    exp = campaign / "experiment"
    summary = read(exp / "summary.json")
    profile = read(exp / "profile.json")
    protocol = read(exp / "protocol.json")
    inputs = read(campaign / "inputs.json")["files"]
    harness = {
        k: v
        for k, v in inputs.items()
        if k.startswith("scripts/") or k in ("uv.lock", "flake.lock", "pyproject.toml")
    }
    trial_files = sorted(exp.glob("trial-*/summary.json"))
    template_path = exp / "props.json"
    # Startup can fail before the backend exposes its template. Do not invent
    # a recipe identity for that case or silently tolerate it for actual trials.
    template = (
        read(template_path)["chat_template"]
        if trial_files or template_path.exists()
        else None
    )
    recipes = {}
    rows = []
    for file in trial_files:
        raw = read(file)
        config = {
            "profile": profile,
            "protocol": {k: v for k, v in protocol.items() if k != "seed"},
            "agent": read(file.parent / "agent-config.json"),
            "harness_files": harness,
            "runtime_template_sha256": hashlib.sha256(template.encode()).hexdigest(),
        }
        recipe = identity(config)
        recipes[recipe] = config
        responses = []
        for response in sorted(file.parent.glob("request-*.response.bin")):
            try:
                data = read(response)
                responses.append(
                    {
                        "file": response.name,
                        "usage": data.get("usage"),
                        "timings": data.get("timings"),
                    }
                )
            except (OSError, ValueError, AttributeError):
                responses.append(
                    {"file": response.name, "usage": None, "timings": None}
                )
        rows.append(
            {
                "trial": str(file.parent),
                "summary_sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                "recipe": recipe,
                "task": raw["task"],
                "fixture": raw["fixture"]["sha256"],
                "seed": raw["seed"],
                "split": raw["split"],
                "raw_success": raw["success"],
                "source_acceptance": "not imported",
                "task_seconds": raw["task_wall_seconds"],
                "agent_seconds": raw.get("agent_wall_seconds"),
                "verification_seconds": raw.get("verification_wall_seconds"),
                "request_count": len(list(file.parent.glob("request-*.request.json"))),
                "responses": responses,
            }
        )
    evidence = {
        "version": 1,
        "campaign": str(campaign),
        "stage": "trials" if rows else "startup",
        "profile": profile,
        "protocol": protocol,
        "harness_files": harness,
        "runtime_template_sha256": hashlib.sha256(template.encode()).hexdigest()
        if template is not None
        else None,
        "experiment_summary": summary,
        "experiment_summary_sha256": hashlib.sha256(
            (exp / "summary.json").read_bytes()
        ).hexdigest(),
        "weight_verification": read(exp / "verified-weights.json")
        if trial_files or (exp / "verified-weights.json").exists()
        else None,
        "recipes": recipes,
        "trials": rows,
        "qualification": "Observed on this workstation; warm-server task times, load and verification separate. Cache/order and incomplete responses retained. Raw outcomes are not source acceptance. No cross-hardware prediction or automatic routing.",
    }
    if "draft_artifact" in profile:
        draft_receipt = exp / "verified-draft-weights.json"
        evidence["draft_weight_verification"] = (
            read(draft_receipt) if trial_files or draft_receipt.exists() else None
        )
    destination = registry / "observations" / (identity(evidence) + ".json")
    publish(destination, evidence)
    return {
        "observation": str(destination),
        "trials": len(rows),
        "recipes": list(recipes),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    verify = sub.add_parser("verify")
    verify.add_argument("--profile", required=True)
    verify.add_argument("--mode", choices=("full", "metadata"), default="full")
    record = sub.add_parser("record")
    record.add_argument("campaign", type=Path)
    args = parser.parse_args(argv)
    profiles = read(PROJECT / "configs/servers.json")
    if args.action == "list":
        result = {
            "profiles": {
                name: {"model": p["artifact"]["id"], "profile_sha256": identity(p)}
                for name, p in profiles.items()
            },
            "registry": str(REGISTRY),
            "weight_records": len(list((REGISTRY / "weights").glob("*.json"))),
            "timing_observations": len(
                list((REGISTRY / "observations").glob("*.json"))
            ),
        }
    elif args.action == "verify":
        from serve_trial import verify_profile_weights

        if args.profile not in profiles:
            parser.error("Unknown profile")
        weights = verify_profile_weights(profiles[args.profile], mode=args.mode)
        result = weights if "draft" in weights else weights["target"]
    else:
        result = record_campaign(args.campaign)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
