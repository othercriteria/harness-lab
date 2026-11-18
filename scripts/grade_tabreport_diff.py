"""Draft CLI checks: candidate executes only through the existing isolated Gate."""

import csv
import io
import json

FIELDS = [
    "team",
    "item",
    "kind",
    "before_minutes",
    "after_minutes",
    "before_status",
    "after_status",
    "delta_minutes",
]


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    return stream.getvalue().encode()


def csv_equal(observed, expected):
    if not isinstance(observed, bytes):
        return False
    try:
        text = observed.decode("utf-8")
        # Outside quoted fields, record endings must be LF rather than CRLF.
        quoted = False
        for char in text:
            if char == '"':
                quoted = not quoted
            elif char == "\r" and not quoted:
                return False
        return (
            not quoted
            and text.endswith("\n")
            and list(csv.reader(io.StringIO(text, newline=""), strict=True))
            == list(
                csv.reader(
                    io.StringIO(expected.decode("utf-8"), newline=""), strict=True
                )
            )
        )
    except (UnicodeError, csv.Error):
        return False


def check(gate):
    token = gate.token()
    header = ["team", "item", "minutes", "status"]
    before = csv_bytes(
        [header, ["A", token, "1:02", "open"], ["gone", token, "0", "done"]]
    )
    after = csv_bytes([header, ["A", token, "3", "done"], ["new", token, "4", "open"]])
    expected = [
        dict(zip(FIELDS, ["A", token, "modified", 62, 3, "open", "done", -59])),
        dict(zip(FIELDS, ["gone", token, "removed", 0, None, "done", None, 0])),
        dict(zip(FIELDS, ["new", token, "added", None, 4, None, "open", 4])),
    ]
    for name, command in (
        ("file-json", "python -m tabreport.diff probe/before.csv probe/after.csv"),
        (
            "stdin-before",
            "python -m tabreport.diff - probe/after.csv < probe/before.csv",
        ),
    ):
        probe = gate.case(
            name, {"probe/before.csv": before, "probe/after.csv": after}, command
        )
        try:
            observed = json.loads(probe.result.get("stdout", ""))
        except ValueError:
            observed = None
        gate.record(
            name,
            probe.result.get("returncode") == 0 and observed == expected,
            {"expected": expected, "observed": probe.result},
        )

    label = 'Ω,"' + token + "\nnext"
    probe = gate.case(
        "csv-output",
        {
            "probe/before.csv": csv_bytes([header]),
            "probe/after.csv": csv_bytes([header, [label, "x", "00:07", "open"]]),
        },
        "python -m tabreport.diff probe/before.csv probe/after.csv --format csv --output probe/result.csv",
    )
    expected_csv = csv_bytes([FIELDS, [label, "x", "added", "", 7, "", "open", 7]])
    output = (
        None
        if gate.absent(probe, "probe/result.csv")
        else gate.read(probe, "probe/result.csv")
    )
    gate.record(
        "csv-output",
        probe.result.get("returncode") == 0
        and probe.result.get("stdout") == ""
        and csv_equal(output, expected_csv),
        {
            "expected_hex": expected_csv.hex(),
            "observed": probe.result,
            "output_hex": output.hex() if output is not None else None,
        },
    )

    probe = gate.case(
        "duplicate-preserves-output",
        {
            "probe/before.csv": csv_bytes([header]),
            "probe/after.csv": csv_bytes(
                [header, ["A", token, 1, "open"], ["A", token, 1, "open"]]
            ),
            "probe/result.json": b"previous report",
        },
        "python -m tabreport.diff probe/before.csv probe/after.csv --output probe/result.json",
    )
    output = (
        None
        if gate.absent(probe, "probe/result.json")
        else gate.read(probe, "probe/result.json")
    )
    gate.record(
        "duplicate-preserves-output",
        probe.result.get("returncode") == 2
        and probe.result.get("stdout") == ""
        and bool(probe.result.get("stderr"))
        and output == b"previous report",
        {"observed": probe.result, "preserved": output == b"previous report"},
    )

    probe = gate.case(
        "empty-csv",
        {
            "probe/before.csv": csv_bytes([header]),
            "probe/after.csv": csv_bytes([header]),
        },
        "python -m tabreport.diff probe/before.csv probe/after.csv --format csv",
    )
    gate.record(
        "empty-csv",
        probe.result.get("returncode") == 0
        and csv_equal(probe.result.get("stdout", "").encode(), csv_bytes([FIELDS])),
        {"observed": probe.result},
    )
