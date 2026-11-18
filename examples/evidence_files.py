"""Check files listed in a portable example packet."""

import hashlib
import json
from pathlib import Path


def check_files(manifest):
    """Report the status of every file listed in a manifest.

    ``manifest`` is a path to a UTF-8 JSON object mapping relative POSIX
    filenames to lowercase SHA-256 hex digests. Filenames are resolved
    relative to the directory containing the manifest. Returns a list of
    ``(filename, status)`` tuples sorted by filename, where status is
    ``"ok"``, ``"missing"`` or ``"changed"``.
    """
    manifest = Path(manifest)
    base = manifest.parent
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    results = []
    for name, expected in entries.items():
        target = base / name
        if not target.is_file():
            status = "missing"
        else:
            digest = hashlib.sha256()
            with target.open("rb") as handle:
                for chunk in iter(lambda: handle.read(65536), b""):
                    digest.update(chunk)
            status = "ok" if digest.hexdigest() == expected else "changed"
        results.append((name, status))
    results.sort(key=lambda item: item[0])
    return results
