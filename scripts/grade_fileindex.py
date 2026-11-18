"""External CLI/catalog observations for the existing file-index contract."""

import hashlib
import json


def _json(gate, probe):
    try:
        return gate.json(probe)
    except (ValueError, TypeError):
        return None


def _success(probe):
    result = probe.result
    return (
        type(result.get("returncode")) is int
        and result["returncode"] == 0
        and result.get("stopped_by") is None
        and not result.get("stderr")
    )


def _bytes(gate, probe, name):
    try:
        return gate.read(probe, name)
    except (OSError, ValueError):
        return None


def check(gate):
    token = gate.token().encode()
    files = {
        ".hidden": token,
        "sub/a.bin": b"\x00\xff" + token,
        "empty": b"",
        "remove.dat": b"remove",
    }
    setup = {"probe/tree/" + name: value for name, value in files.items()}
    catalog = "probe/catalog.json"
    command = "python -m fileindex probe/tree " + catalog
    first = gate.case("index_fresh", setup, command)
    expected = {"added": sorted(files), "removed": [], "changed": []}
    gate.record(
        "index_fresh_result",
        _success(first) and _json(gate, first) == expected,
        {"actual": first.result, "expected": expected},
    )
    raw = _bytes(gate, first, catalog)
    try:
        decoded = json.loads(raw) if raw is not None else None
    except (ValueError, UnicodeError):
        decoded = None
    valid = (
        isinstance(decoded, dict)
        and set(decoded) == {"version", "files"}
        and type(decoded["version"]) is int
        and decoded["version"] == 1
    )
    entries = decoded.get("files") if valid else None
    valid = valid and isinstance(entries, dict) and set(entries) == set(files)
    if valid:
        for name, data in files.items():
            entry = entries[name]
            valid = (
                valid
                and isinstance(entry, dict)
                and set(entry) == {"size", "mtime_ns", "sha256"}
            )
            if not valid:
                break
            valid = (
                type(entry["size"]) is int
                and entry["size"] == len(data)
                and type(entry["mtime_ns"]) is int
                and entry["mtime_ns"] >= 0
                and entry["sha256"] == hashlib.sha256(data).hexdigest()
            )
            if not valid:
                break
    gate.record(
        "index_catalog_bytes",
        _success(first) and valid,
        {"observed": decoded, "expected_paths": sorted(files)},
    )
    if raw is None:
        raw = b"{}"  # Keep all later failure observations; never fabricate a passing baseline.
    changed = gate.step(
        first,
        "rm probe/tree/remove.dat && " + command,
        {"probe/tree/sub/a.bin": b"changed-" + token, "probe/tree/new": b"new"},
    )
    expected = {"added": ["new"], "removed": ["remove.dat"], "changed": ["sub/a.bin"]}
    gate.record(
        "index_incremental_diff",
        _success(changed) and _json(gate, changed) == expected,
        {"actual": changed.result, "expected": expected},
    )
    unchanged = gate.step(first, command)
    empty = {"added": [], "removed": [], "changed": []}
    gate.record(
        "index_noop",
        _success(unchanged) and _json(gate, unchanged) == empty,
        {"actual": unchanged.result},
    )
    dry = gate.step(first, command + " --dry-run", {"probe/tree/new": token})
    expected = {"added": ["new"], "removed": [], "changed": []}
    gate.record(
        "index_dry_existing",
        _success(dry)
        and _json(gate, dry) == expected
        and _bytes(gate, dry, catalog) == raw,
        {"actual": dry.result},
    )
    dry_missing = gate.case("index_dry_missing", setup, command + " --dry-run")
    expected = {"added": sorted(files), "removed": [], "changed": []}
    gate.record(
        "index_dry_missing",
        _success(dry_missing)
        and _json(gate, dry_missing) == expected
        and gate.absent(dry_missing, catalog),
        {"actual": dry_missing.result},
    )
    for label, contents in (
        ("bad_json", b"{broken"),
        ("bad_version", b'{"version":true,"files":{}}'),
    ):
        bad = gate.case("index_" + label, {**setup, catalog: contents}, command)
        result = bad.result
        valid = (
            type(result.get("returncode")) is int
            and result["returncode"] == 2
            and not result.get("stdout")
            and bool(result.get("stderr"))
            and "Traceback" not in result["stderr"]
            and result.get("stopped_by") is None
            and _bytes(gate, bad, catalog) == contents
        )
        gate.record("index_" + label, valid, {"actual": result})
