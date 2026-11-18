"""Read-only review of complete changed-span patches emitted by bounded_diff."""

import difflib
import re

from bounded_diff import span_range

# Share the matching budget across all files in each 64 KiB preview.
MATCH_PAIRS_PER_PREVIEW = 64 * 1024
HEADER = re.compile(
    r"@@ -([0-9]{1,9})(?:,([0-9]{1,9}))? \+([0-9]{1,9})(?:,([0-9]{1,9}))? @@\n"
)
BEFORE = re.compile(r"--- before/([a-zA-Z0-9_./-]{1,512})\n")


def _compact_hunks(old, new, old_start, new_start):
    """Render grouped edits at their original coordinates; caller bounds matching."""
    parts = []
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for group in matcher.get_grouped_opcodes(3):
        first, last = group[0], group[-1]
        left = span_range(old_start - 1 + first[1], last[2] - first[1])
        right = span_range(new_start - 1 + first[3], last[4] - first[3])
        parts.append(f"@@ -{left} +{right} @@\n")
        for tag, a1, a2, b1, b2 in group:
            if tag == "equal":
                parts.extend(" " + line for line in old[a1:a2])
            if tag in ("replace", "delete"):
                parts.extend("-" + line for line in old[a1:a2])
            if tag in ("replace", "insert"):
                parts.extend("+" + line for line in new[b1:b2])
    return "".join(parts)


def review_diff(recorded, truncated):
    """Return display text and its format. The raw artifact stays addressable."""
    if truncated:
        return recorded, "recorded_truncated"
    if not recorded or not recorded.endswith("\n"):
        return recorded, "recorded"

    # Stored body lines are LF-delimited. CR and Unicode separators are content.
    lines = [line + "\n" for line in recorded[:-1].split("\n")]
    pos = compact = unchanged = 0
    remaining_pairs = MATCH_PAIRS_PER_PREVIEW
    result = []
    while pos < len(lines):
        start = pos
        before = BEFORE.fullmatch(lines[pos])
        if (
            not before
            or pos + 2 >= len(lines)
            or lines[pos + 1] != f"+++ after/{before[1]}\n"
        ):
            return recorded, "recorded"
        header = HEADER.fullmatch(lines[pos + 2])
        if not header:
            return recorded, "recorded"
        old_start, old_count, new_start, new_count = map(int, header.groups("1"))
        pos += 3
        old, new = [], []
        while len(old) < old_count or len(new) < new_count:
            if pos == len(lines) or lines[pos][0] not in " +-":
                return recorded, "recorded"
            marker, content = lines[pos][0], lines[pos][1:]
            if marker in " -":
                old.append(content)
            if marker in " +":
                new.append(content)
            if len(old) > old_count or len(new) > new_count:
                return recorded, "recorded"
            pos += 1

        cost = old_count * new_count
        replacement = None
        if old_start and new_start and 0 < cost <= remaining_pairs:
            remaining_pairs -= cost
            replacement = _compact_hunks(old, new, old_start, new_start)
        original = "".join(lines[start + 2 : pos])
        if replacement and len(replacement.encode()) < len(original.encode()):
            result.extend((lines[start], lines[start + 1], replacement))
            compact += 1
        else:
            result.extend(lines[start:pos])
            unchanged += 1

    if not compact:
        return recorded, "recorded"
    return "".join(result), "mixed" if unchanged else "compact"
