"""Check maintained Markdown prose for accidentally joined words and numbers."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# These are historical source documents. The status archive is byte-preserved.
HISTORY = {"development-history-2026-11-02.md", "status-history-2026-11-17.md"}
LITERALS = re.compile(r"`+[^`\n]+`+|\]\([^)]+\)|https?://\S+")
JOIN = re.compile(
    r"(?<![\w./-])(?:and|across|after|all|at|below|completed|from|median|of|"
    r"only|passed|reached|retained|returned|took|to|was|were|with|tested|test)"
    r"(?=\d)|(?<=\d)(?:tokens|resets|tests|trials|seconds|layers)\b|"
    r"(?<=\d)(?:ms|s|min|MiB|KiB)(?=remaining\b)",
    re.IGNORECASE,
)


def findings(path):
    fence = ""
    for number, line in enumerate(path.read_text().splitlines(), 1):
        stripped = line.strip()
        if fence:
            if stripped.rstrip(fence[0]) == "" and len(stripped) >= len(fence):
                fence = ""
            continue
        opening = re.match(r"(`{3,}|~{3,})", stripped)
        if opening:
            fence = opening[1]
            continue
        if JOIN.search(LITERALS.sub(" ", line)):
            yield f"{path.relative_to(ROOT)}:{number}: check spacing: {line.strip()}"


if __name__ == "__main__":
    paths = [*ROOT.glob("*.md"), *(ROOT / "docs").rglob("*.md")]
    errors = [
        message
        for path in sorted(paths)
        if path.name not in HISTORY and "archive" not in path.relative_to(ROOT).parts
        for message in findings(path)
    ]
    for message in errors:
        print(message, file=sys.stderr)
    sys.exit(bool(errors))
