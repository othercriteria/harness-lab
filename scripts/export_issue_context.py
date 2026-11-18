"""Outer-only export of issue text for a frozen Worker input."""

import argparse
import datetime
import json
import re
import subprocess
from pathlib import Path


def issue_number(value: str) -> str:
    number = value.lstrip("0")
    if not number or not re.fullmatch(r"[0-9]+", value):
        raise argparse.ArgumentTypeError("expected a positive decimal issue number")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", help="GitHub OWNER/REPO")
    parser.add_argument("output", type=Path, help="new JSON file in the staging tree")
    parser.add_argument(
        "--issue",
        action="append",
        type=issue_number,
        metavar="NUMBER",
        help="issue number to include; repeatable, at most 50 distinct issues",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repository):
        parser.error("expected OWNER/REPO")
    fields = "number,state,title,body,url,updatedAt,labels"
    if args.issue:
        numbers = dict.fromkeys(args.issue)
        if len(numbers) > 50:
            parser.error("select at most 50 issues")
        rows = []
        for number in numbers:
            try:
                raw = subprocess.check_output(
                    [
                        "gh",
                        "issue",
                        "view",
                        number,
                        "--repo",
                        args.repository,
                        "--json",
                        fields,
                    ]
                )
                rows.append(json.loads(raw))
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                parser.error(f"lookup failed for issue {number}")
        scope = "Selected issue titles, bodies and label names. Comments and PRs excluded."
    else:
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
        scope = "Open and closed issue titles, bodies and label names. Comments and PRs excluded."
    for row in rows:
        row["labels"] = sorted(label["name"] for label in row["labels"])
    packet = {
        "repository": args.repository,
        "retrieved_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "scope": scope,
        "issues": sorted(rows, key=lambda row: row["number"]),
    }
    data = json.dumps(packet, indent=2, ensure_ascii=False) + "\n"
    if len(data.encode()) > 96 * 1024:
        parser.error("issue packet exceeds 96 KiB; curate a smaller packet")
    with args.output.open("x", encoding="utf-8") as out:
        out.write(data)


if __name__ == "__main__":
    main()
