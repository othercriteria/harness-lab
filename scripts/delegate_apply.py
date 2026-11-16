"""Outer-only reviewed application. Never execute a model-authored patch or hook.

Writes are atomic per file with a durable progress journal, not a repository-wide
atomic transaction. Cooperating applications share a lock. Unexpected partial
application requires explicit outer reconciliation; concurrent human edits are
never automatically rolled back.
"""

import argparse
import fcntl
import json
import os
import uuid

from delegate_artifacts import (
    check_application_base,
    digest,
    encoded,
    export_candidate,
    read_file,
)
from delegate_job import STORE, TERMINAL, atomic, job_path, read
from delegate_package import PROJECT, verify_package


def publish_review(identifier, review, store=STORE):
    """Cooperating review writers cannot revoke/replace an applying decision."""
    job = job_path(identifier, store)
    with (store / "application.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (job / "application.json").exists():
            raise ValueError(
                "Application journal exists; preserve review and reconcile explicitly"
            )
        if review.get("job_id") != identifier:
            raise ValueError("Review belongs to another job")
        atomic(job / "review.json", review)


def apply(identifier, repo=PROJECT, store=STORE):
    job = job_path(identifier, store)
    state = read(job / "state.json")
    if state["state"] not in TERMINAL or state.get("cleanup_verified") is not True:
        raise ValueError("Job execution and cleanup must be closed")
    review_bytes = read_file(job, "review.json", limit=1024 * 1024)
    review_digest = digest(review_bytes)
    review = json.loads(review_bytes)
    if review.get("decision") not in {"accepted", "accepted_with_repairs"} or not all(
        isinstance(review.get(k), str) and review[k].strip()
        for k in ("reviewer", "notes", "verification")
    ):
        raise ValueError("Explicit independent outer review required")
    if (
        review.get("job_id") != identifier
        or review.get("package_id") != state["package_id"]
    ):
        raise ValueError("Review belongs to another job/package")
    kind = review.get("artifact", "artifact")
    if kind not in {"artifact", "reviewed-artifact"}:
        raise ValueError("Unapproved review artifact location")
    source = job / kind
    manifest_bytes = read_file(source, "artifact.json", limit=4 * 1024 * 1024)
    if digest(manifest_bytes) != review.get("artifact_sha256"):
        raise ValueError("Reviewed artifact changed")
    manifest = json.loads(manifest_bytes)
    package, _ = verify_package(state["package_id"], store)
    from delegate_artifacts import load_snapshot

    snapshot, before = load_snapshot(package / "source")
    if manifest.get("snapshot_id") != snapshot["snapshot_id"]:
        raise ValueError("Artifact uses another snapshot")
    # Reconstruct the complete proposed workspace and re-run the export policy.
    # This verifies paths, modes, hashes and untouched dependencies independently
    # of any assertions in the untrusted artifact manifest.
    staged = job / ("application-stage-" + uuid.uuid4().hex)
    staged.mkdir()
    for name, data in before.items():
        target = staged / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o644 | snapshot["contract"]["executable_bits"][name])
    seen = set()
    changes = manifest.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ValueError("No reviewed changes to apply")
    for row in changes:
        name = row["path"]
        if name in seen or name not in snapshot["contract"]["allowed_write_paths"]:
            raise ValueError("Unapproved or duplicate changed path")
        seen.add(name)
        target = staged / name
        if row["after_sha256"] is None:
            target.unlink()
        else:
            data = read_file(source / "files", name)
            if digest(data) != row["after_sha256"]:
                raise ValueError("Reviewed content hash mismatch")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o644 | row["executable_bits"])
    normalized = export_candidate(
        package / "source", staged, staged.with_name(staged.name + "-export")
    )
    if encoded(normalized) != encoded(manifest):
        raise ValueError("Artifact does not match normalized proposed changes")
    with (store / "application.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if digest(read_file(job, "review.json", limit=1024 * 1024)) != review_digest:
            raise ValueError("Review changed while preparing application")
        if (job / "application.json").exists():
            raise ValueError(
                "Application already started; reconcile its journal instead of retrying"
            )
        check_application_base(package / "source", repo)
        journal = {
            "job_id": identifier,
            "applied": False,
            "state": "applying",
            "review_sha256": review_digest,
            "artifact_sha256": digest(manifest_bytes),
            "paths": [],
            "qualification": "Atomic per file, cooperating-writer lock; no automatic rollback of concurrent edits.",
        }
        atomic(job / "application.json", journal)
        for row in changes:
            name = row["path"]
            current = read_file(repo, name, missing=True, with_mode=True)
            expected = snapshot["contract"]["base"][name]
            if (digest(current[0]) if current else None) != expected or (
                current[1] if current else None
            ) != snapshot["contract"]["executable_bits"].get(name):
                raise ValueError("Base changed during application; reconcile journal")
            # Resolve each parent without following links. Root is the trusted
            # outer-selected checkout, never a candidate-provided destination.
            fd = os.open(repo, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            temp = None
            try:
                parts = name.split("/")
                for part in parts[:-1]:
                    try:
                        os.mkdir(part, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                    child = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                    )
                    os.close(fd)
                    fd = child
                if row["after_sha256"] is None:
                    os.unlink(parts[-1], dir_fd=fd)
                else:
                    temp = ".delegate-" + uuid.uuid4().hex
                    out = os.open(
                        temp,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=fd,
                    )
                    with os.fdopen(out, "wb") as stream:
                        stream.write(read_file(staged, name))
                        stream.flush()
                        os.fchmod(stream.fileno(), 0o644 | row["executable_bits"])
                        os.fsync(stream.fileno())
                    os.replace(temp, parts[-1], src_dir_fd=fd, dst_dir_fd=fd)
                    temp = None
                os.fsync(fd)
            finally:
                if temp is not None:
                    os.unlink(temp, dir_fd=fd)
                os.close(fd)
            journal["paths"].append({"path": name, "after_sha256": row["after_sha256"]})
            atomic(job / "application.json", journal)
        journal.update(applied=True, state="applied")
        atomic(job / "application.json", journal)
        return journal


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    print(json.dumps(apply(parser.parse_args().job_id)))
