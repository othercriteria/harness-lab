"""Outer-only export of issue text for a frozen Worker input."""

import argparse
import datetime
import json
import re
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", help="GitHub OWNER/REPO")
    parser.add_argument("output", type=Path, help="new JSON file in the staging tree")
    args = parser.parse_args()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repository):
        parser.error("expected OWNER/REPO")
    fields = "number,state,title,body,url,updatedAt"
    # Request an extra row to distinguish a complete snapshot from a capped page.
    raw = subprocess.check_output(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            args.repository,
            "--state",
            "all",
            "--limit",
            "51",
            "--json",
            fields,
        ]
    )
    rows = json.loads(raw)
    if len(rows) > 50:
        parser.error("more than 50 issues; curate a smaller issue packet")
    packet = {
        "repository": args.repository,
        "retrieved_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "scope": "Open and closed issue titles and bodies. Comments and PRs excluded.",
        "issues": sorted(rows, key=lambda row: row["number"]),
    }
    data = json.dumps(packet, indent=2, ensure_ascii=False) + "\n"
    if len(data.encode()) > 96 * 1024:
        parser.error("issue packet exceeds 96 KiB; curate a smaller packet")
    with args.output.open("x", encoding="utf-8") as out:
        out.write(data)


if __name__ == "__main__":
    main()
