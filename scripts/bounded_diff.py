"""Bounded linear-work review diffs; complete files remain the source of truth.

Use one changed-span hunk per file rather than quadratic sequence matching.
Distant edits may therefore produce a larger, non-minimal hunk. Large files and
output beyond the display budget receive explicit manifest-backed omissions.
"""

import hashlib
import json
import re

MAX_FILE_INPUT_BYTES = 256 * 1024
MAX_FILE_LINES = 8192
MAX_DIFF_BYTES = 1024 * 1024


def metadata(old, new):
    return {
        side: None
        if data is None
        else {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for side, data in (("before", old), ("after", new))
    }


def span_range(start, length):
    begin = start + 1 if length else start
    return str(begin) if length == 1 else f"{begin},{length}"


def lf_lines(data):
    # Unified diffs use LF lines; str.splitlines also splits several controls.
    parts = data.decode("utf-8").split("\n")
    return [line + "\n" for line in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def file_diff(name, old, new):
    if old == new:
        return "", False
    info = json.dumps(metadata(old, new))
    try:
        for data in (old, new):
            if data is not None and b"\0" in data:
                raise UnicodeError("NUL in file")
        if sum(len(x) for x in (old, new) if x is not None) > MAX_FILE_INPUT_BYTES:
            return f"Diff omitted (input limit) for {json.dumps(name)}: {info}\n", True
        if any(data.count(b"\n") > MAX_FILE_LINES for data in (old, new) if data):
            return f"Diff omitted (line limit) for {json.dumps(name)}: {info}\n", True
        a = lf_lines(old or b"")
        b = lf_lines(new or b"")
    except UnicodeError:
        return f"Binary file {json.dumps(name)} changed: {info}\n", True
    if not re.fullmatch(r"[a-zA-Z0-9_./-]{1,512}", name):
        return (
            f"Diff omitted (nonliteral filename) for {json.dumps(name)}: {info}\n",
            True,
        )
    common = 0
    while common < min(len(a), len(b)) and a[common] == b[common]:
        common += 1
    suffix = 0
    while (
        suffix < min(len(a), len(b)) - common
        and a[len(a) - suffix - 1] == b[len(b) - suffix - 1]
    ):
        suffix += 1
    start = max(0, common - 3)
    a_end, b_end = len(a) - suffix, len(b) - suffix
    context_end = min(suffix, 3)
    out = [
        f"--- before/{name}\n",
        f"+++ after/{name}\n",
        f"@@ -{span_range(start, a_end + context_end - start)} "
        f"+{span_range(start, b_end + context_end - start)} @@\n",
    ]
    for marker, lines in (
        (" ", a[start:common]),
        ("-", a[common:a_end]),
        ("+", b[common:b_end]),
        (" ", a[a_end : a_end + context_end]),
    ):
        for line in lines:
            out.append(marker + line)
            if not line.endswith("\n"):
                out.append("\n\\ No newline at end of file\n")
    return "".join(out), False


class DiffView:
    def __init__(self):
        self.parts = []
        self.bytes = 0
        self.omitted_files = 0
        self.fallback_files = 0

    def add(self, name, old, new):
        if old == new:
            return
        # Reserve a little space for the final explicit truncation marker.
        if self.bytes >= MAX_DIFF_BYTES - 256:
            self.omitted_files += 1
            return
        text, fallback = file_diff(name, old, new)
        size = len(text.encode("utf-8"))
        if self.bytes + size > MAX_DIFF_BYTES - 256:
            self.omitted_files += 1
            return
        self.parts.append(text)
        self.bytes += size
        self.fallback_files += int(fallback)

    def render(self):
        tail = (
            (
                f"\nDiff display truncated: {self.omitted_files} changed file(s) omitted; "
                "inspect complete files and manifests.\n"
            )
            if self.omitted_files
            else ""
        )
        return "".join(self.parts) + tail
