"""Trusted isolated object reader. Never imports or executes submitted code.

Invoked in grade mode. Discards submitted Git config, hooks, replacement refs,
grafts, attributes and external object stores before reading graph/tree objects.
Only regular blobs are exported, never checkout filters or archive attributes.
"""

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import zlib
from pathlib import Path

LIMIT = 16 * 1024 * 1024
MAX_ENTRIES = 2048


def main():
    spec = json.loads(Path("/evaluation/spec.json").read_text())
    original = Path("/workspace/repo")
    submitted = original / ".git"
    if not submitted.is_dir() or submitted.is_symlink():
        raise ValueError("Expected a self-contained repository")
    for name in (
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "rebase-merge",
        "rebase-apply",
        "sequencer",
        "BISECT_LOG",
    ):
        if (submitted / name).exists():
            raise ValueError("Unfinished Git operation: " + name)
    if (submitted / "objects/info/alternates").exists():
        raise ValueError("External Git object stores are not allowed")
    safe = Path("/tmp/safe.git")
    safe.mkdir()
    for name in ("objects", "refs"):
        shutil.copytree(submitted / name, safe / name)
    for name in ("HEAD", "packed-refs", "index"):
        if (submitted / name).exists():
            shutil.copyfile(submitted / name, safe / name)
    (safe / "config").write_text("[core]\n bare = true\n")
    env = {
        **os.environ,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_OPTIONAL_LOCKS": "0",
    }

    def git(*args):
        return subprocess.check_output(
            ["/bin/git", "--no-replace-objects", "--git-dir=" + str(safe), *args],
            env=env,
            stderr=subprocess.PIPE,
            timeout=3,
        )

    # Object paths and refs are candidate-controlled. cat-file/rev-parse alone
    # can return substituted loose bytes under a pinned object's original ID.
    # Validate the full sanitized database before trusting any anchored graph or
    # protected-file comparison. This also checks packed objects; no candidate
    # config, hooks, replacement refs or external object stores are enabled.
    try:
        git("fsck", "--full", "--strict", "--no-reflogs")
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace")[:2048]
        raise ValueError("Git object integrity rejected: " + detail) from error

    def oid(ref):
        result = git("rev-parse", "--verify", ref + "^{commit}").decode().strip()
        if not re.fullmatch("[0-9a-f]{40}", result):
            raise ValueError("Invalid object identity")
        return result

    def tree(commit):
        entries = git("ls-tree", "-rz", "--full-tree", commit).split(b"\0")
        files, total = {}, 0
        for entry in filter(None, entries):
            attrs, raw_path = entry.split(b"\t", 1)
            mode, kind, blob = attrs.decode("ascii").split()
            name = raw_path.decode("utf-8")
            path = Path(name)
            if (
                mode not in ("100644", "100755")
                or kind != "blob"
                or path.is_absolute()
                or any(p in (".", "..", ".git") for p in path.parts)
            ):
                raise ValueError("Unsupported tree entry: " + name)
            data = git("cat-file", "blob", blob)
            total += len(data)
            if total > LIMIT or len(files) >= MAX_ENTRIES:
                raise ValueError("Export storage limit")
            files[name] = {
                "data": base64.b64encode(data).decode(),
                "mode": mode,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        return files

    if oid("refs/heads/main") != spec["main"]:
        raise ValueError("Main branch changed")
    for name, expected in spec["tags"].items():
        # No tags may be retargeted, including via a different annotated tag.
        actual = git("rev-parse", "--verify", "refs/tags/" + name).decode().strip()
        if actual != expected:
            raise ValueError("Tag changed: " + name)
    checked_out = git("symbolic-ref", "--short", "HEAD").decode().strip()
    if checked_out not in spec["branches"]:
        raise ValueError("Final checkout must be a target branch")
    if git("write-tree").strip() != git("rev-parse", "HEAD^{tree}").strip():
        raise ValueError("Staged index differs from final commit")
    delivery_errors = []
    try:
        handoff = json.loads(Path("/workspace/handoff.json").read_text())
        if not isinstance(handoff, dict) or not isinstance(
            handoff.get("branches"), dict
        ):
            raise ValueError("Expected a branches object")
    except (OSError, ValueError, UnicodeError) as error:
        delivery_errors.append(f"Invalid handoff: {error}")
        handoff = {"branches": {}}
    if set(handoff["branches"]) != set(spec["branches"]):
        delivery_errors.append("Handoff must identify all and only target branches")
    branches = {}
    for branch, base in spec["branches"].items():
        final = oid("refs/heads/" + branch)
        git("merge-base", "--is-ancestor", base, final)
        if final == base or git("rev-list", "--merges", base + ".." + final).strip():
            raise ValueError("Target must have new non-merge commits")
        evidence = handoff["branches"].get(branch)
        if (
            not isinstance(evidence, dict)
            or evidence.get("commit") != final
            or evidence.get("verification_command")
            != "python -m unittest discover -s tests"
        ):
            delivery_errors.append(
                f"{branch}: handoff revision or verification command mismatch"
            )
        before, after = tree(base), tree(final)
        protected = {
            name for name in before if name not in ("configparser.py", "service.py")
        }
        if any(after.get(name) != before[name] for name in protected):
            raise ValueError("Original protected file changed")
        changed = {
            name
            for name in set(before) | set(after)
            if before.get(name) != after.get(name)
        }
        if any(
            name not in ("configparser.py", "service.py")
            and not name.startswith("tests/")
            for name in changed
        ):
            raise ValueError("Changed file outside permitted paths")
        if spec.get("require_added_tests", True) and not any(
            name.startswith("tests/") and name not in before for name in after
        ):
            raise ValueError("Missing committed regression test addition")
        branches[branch] = {
            "commit": final,
            "base": base,
            "files": after,
            "changed_files": sorted(changed),
        }
    # Compare the final working tree directly. Never run submitted fsmonitor,
    # diff drivers, clean/smudge filters or hooks. The sanitized index was checked
    # against HEAD above; actual working bytes are compared independently here.
    expected = branches[checked_out]["files"]
    actual = {}
    for path in original.rglob("*"):
        rel = path.relative_to(original)
        if (
            ".git" in rel.parts
            or "__pycache__" in rel.parts
            or path.suffix in (".pyc", ".pyo", ".pyd")
        ):
            continue
        if path.is_file():
            actual[rel.as_posix()] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "mode": "100755" if path.stat().st_mode & 0o100 else "100644",
            }
    if actual != {
        name: {key: value[key] for key in ("sha256", "mode")}
        for name, value in expected.items()
    }:
        raise ValueError(
            "Final working tree differs from submitted commit or has extra files"
        )
    blobs = {}
    for branch in branches.values():
        for info in branch["files"].values():
            blobs.setdefault(info["sha256"], info.pop("data"))
    payload = json.dumps(
        {
            "passed": True,
            "checked_out": checked_out,
            "branches": branches,
            "blobs": blobs,
            "delivery": {"passed": not delivery_errors, "errors": delivery_errors},
        }
    ).encode()
    print(base64.b64encode(zlib.compress(payload)).decode())


if __name__ == "__main__":
    main()
