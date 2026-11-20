"""Outer-only export of issue text for a frozen Worker input."""

import argparse
import datetime
import json
import re
import subprocess
from pathlib import Path

MAX_ISSUES = 50
MAX_COMMENTS = 50
MAX_BYTES = 96 * 1024
ISSUE_FIELDS = "number,state,title,body,url,updatedAt,labels"
COMMENT_LINK = re.compile(
    r"https://github\.com/(?P<repo>[\w.-]+/[\w.-]+)/issues/"
    r"(?P<issue>[1-9][0-9]*)#issuecomment-(?P<id>[1-9][0-9]*)"
)


def issue_number(value: str) -> str:
    number = value.lstrip("0")
    if not number or not re.fullmatch(r"[0-9]+", value):
        raise argparse.ArgumentTypeError("expected a positive decimal issue number")
    return number


def selected_comments(parser, repository, refs):
    """Normalize aliases before fetching. Keep permalink parents for validation."""
    comments = {}
    for ref in refs:
        link = COMMENT_LINK.fullmatch(ref)
        if link and link["repo"].casefold() == repository.casefold():
            comment_id, issue = link["id"], link["issue"]
        elif re.fullmatch(r"0*[1-9][0-9]*", ref):
            comment_id, issue = ref.lstrip("0"), None
        else:
            parser.error(
                "expected a numeric comment ID or an issue comment permalink in this repository"
            )
        previous = comments.get(comment_id)
        if previous and issue and previous != issue:
            parser.error(f"conflicting issue numbers for comment {comment_id}")
        comments[comment_id] = previous or issue
    if len(comments) > MAX_COMMENTS:
        parser.error(f"select at most {MAX_COMMENTS} distinct comments")
    return comments


def fetch(parser, description, *args):
    try:
        return json.loads(subprocess.check_output(["gh", *args]))
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        parser.error(f"lookup failed for {description}: {exc}")


def attach_comments(parser, repository, rows, comments):
    by_number = {str(row["number"]): row for row in rows}
    for comment_id, expected_issue in comments.items():
        if expected_issue and expected_issue not in by_number:
            parser.error(
                f"comment {comment_id} belongs to unselected issue {expected_issue}"
            )
        comment = fetch(
            parser,
            f"comment {comment_id}",
            "api",
            f"repos/{repository}/issues/comments/{comment_id}",
        )
        link = COMMENT_LINK.fullmatch(comment["html_url"])
        if (
            not link
            or link["repo"].casefold() != repository.casefold()
            or link["id"] != comment_id
            or str(comment["id"]) != comment_id
            or (expected_issue and link["issue"] != expected_issue)
        ):
            parser.error(
                f"returned permalink does not match requested comment {comment_id}"
            )
        if link["issue"] not in by_number:
            parser.error(
                f"comment {comment_id} belongs to unselected issue {link['issue']}"
            )
        by_number[link["issue"]].setdefault("comments", []).append(
            {
                "id": comment["id"],
                "url": comment["html_url"],
                "author": (comment["user"] or {}).get("login"),
                "body": comment["body"],
                "updatedAt": comment["updated_at"],
            }
        )


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
    parser.add_argument(
        "--state",
        choices=("open", "closed", "all"),
        help="list issues in this state (default: all)",
    )
    parser.add_argument(
        "--label",
        action="append",
        default=[],
        help="list issues with this label; repeat to require all named labels",
    )
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="include only the first N matching issues in GitHub list order (1–50)",
    )
    parser.add_argument(
        "--comment",
        action="append",
        default=[],
        metavar="ID_OR_PERMALINK",
        help="include a specific comment on a selected issue; at most 50 distinct comments",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repository):
        parser.error("expected OWNER/REPO")
    if args.issue and (args.state or args.label or args.limit is not None):
        parser.error("--issue cannot be combined with --state, --label or --limit")
    if args.limit is not None and not 1 <= args.limit <= MAX_ISSUES:
        parser.error(f"--limit must be between 1 and {MAX_ISSUES}")
    comments = selected_comments(parser, args.repository, args.comment)
    if args.issue:
        numbers = dict.fromkeys(args.issue)
        if len(numbers) > MAX_ISSUES:
            parser.error("select at most 50 issues")
        rows = []
        for number in numbers:
            row = fetch(
                parser,
                f"issue {number}",
                "issue",
                "view",
                number,
                "--repo",
                args.repository,
                "--json",
                ISSUE_FIELDS,
            )
            # gh issue view also succeeds for a pull request number.
            if row["url"].rsplit("/", 2)[-2:] != ["issues", number]:
                parser.error(f"#{number} is not an issue: {row['url']}")
            rows.append(row)
        selection = {"numbers": [row["number"] for row in rows]}
        scope = "Selected issue titles, bodies and label names."
    else:
        limit = args.limit or MAX_ISSUES
        state = args.state or "all"
        labels = list(dict.fromkeys(args.label))
        label_flags = [flag for label in labels for flag in ("--label", label)]
        # gh handles pagination. One extra matching issue proves there are omissions.
        rows = fetch(
            parser,
            "issue list",
            "issue",
            "list",
            "--repo",
            args.repository,
            "--state",
            state,
            *label_flags,
            "--limit",
            str(limit + 1),
            "--json",
            ISSUE_FIELDS,
        )
        more = len(rows) > limit
        if more and args.limit is None:
            parser.error(
                "more than 50 issues match; narrow the selection or pass --limit to allow omissions"
            )
        rows = rows[:limit]
        selection = {
            "state": state,
            "labels": labels,
            "limit": limit,
            "more_matches": more,
        }
        scope = "Listed issue titles, bodies and label names."
        if more:
            scope += " Additional matching issues omitted at the requested limit."
    if comments:
        attach_comments(parser, args.repository, rows, comments)
        scope += " Only explicitly selected comments included. PRs excluded."
    else:
        scope += " Comments and PRs excluded."
    for row in rows:
        row["labels"] = sorted(label["name"] for label in row["labels"])
    packet = {
        "repository": args.repository,
        "retrieved_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "scope": scope,
        "selection": selection,
        "issues": sorted(rows, key=lambda row: row["number"]),
    }
    data = (json.dumps(packet, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if len(data) > MAX_BYTES:
        parser.error(
            f"issue packet exceeds 96 KiB ({len(data)} bytes); curate a smaller packet"
        )
    try:
        with args.output.open("xb") as out:
            out.write(data)
    except FileExistsError:
        parser.error(f"output already exists: {args.output}")


if __name__ == "__main__":
    main()
