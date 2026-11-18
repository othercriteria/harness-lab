"""Outer comparisons for event-import; candidate code runs only through Gate.

CLI reports and fresh-process reads are compared here, outside candidate Python.
No database layout is prescribed by the public contract, so persistence is read
through EventStore rather than assuming a particular SQLite schema. Those reads
are still untrusted observations, not a clean data-only database verification.
"""

import json


def same(actual, expected):
    return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(
        expected, sort_keys=True, allow_nan=False
    )


def transport(probe, code=0):
    result = probe.result
    return (
        type(result.get("returncode")) is int
        and result["returncode"] == code
        and result.get("stopped_by") is None
        and (code != 0 or result.get("stderr") == "")
        and (code != 0 or len(result.get("stdout", "").splitlines()) == 1)
    )


def decoded(probe, field="stdout"):
    try:
        return json.loads(probe.result.get(field, ""))
    except (TypeError, ValueError):
        return None


def report_matches(actual, inserted, duplicates, error_lines):
    if not isinstance(actual, dict) or set(actual) != {
        "inserted", "duplicates", "invalid", "errors"
    }:
        return False
    expected = [inserted, duplicates, len(error_lines)]
    counts = [actual[key] for key in ("inserted", "duplicates", "invalid")]
    if not same(counts, expected):
        return False
    errors = actual["errors"]
    return (
        isinstance(errors, list)
        and len(errors) == len(error_lines)
        and all(
            isinstance(error, dict)
            and set(error) == {"line", "message"}
            and type(error["line"]) is int
            and error["line"] == line
            and isinstance(error["message"], str)
            and bool(error["message"])
            for error, line in zip(errors, error_lines)
        )
    )


READ_DRIVER = b'''import json, sys
sys.path.insert(0, "/workspace")
from eventlog.store import EventStore
ids = json.load(open("probe/ids.json", encoding="utf-8"))
store = EventStore("probe/events.db")
try:
    print(json.dumps({"count": store.count(), "rows": [store.get(i) for i in ids]}))
finally:
    store.close()
'''

CLI_READ_FAILURE_DRIVER = b'''import builtins, contextlib, io, json, sys
sys.path.insert(0, "/workspace")
item = json.load(open("probe/event.json", encoding="utf-8"))
class Source:
    closed = False
    def __iter__(self):
        yield json.dumps(item) + "\\n"
        raise OSError("source read failed")
    def close(self): self.closed = True
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
source = Source()
def intercept(original):
    def opened(path, *args, **kwargs):
        if str(path) == "probe/input.jsonl": return source
        return original(path, *args, **kwargs)
    return opened
# Cover ordinary open, pathlib.Path.open, and aliases imported by the CLI.
builtins.open = intercept(builtins.open)
io.open = intercept(io.open)
import eventlog.cli as cli
from eventlog.store import EventStore
out, err = io.StringIO(), io.StringIO()
code, error = None, None
with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
    try:
        code = cli.main(["probe/events.db", "probe/input.jsonl"])
    except SystemExit as exc:
        code = exc.code
    except Exception as exc:
        error = type(exc).__name__
store = EventStore("probe/events.db")
try:
    print(json.dumps({"code": code, "exception": error,
                      "stdout": out.getvalue(), "stderr": err.getvalue(),
                      "source_closed": source.closed,
                      "row": store.get(item["id"]), "count": store.count()}))
finally:
    store.close()
'''


def observe(gate, previous, name, expected):
    probe = gate.step(previous, "python -I -S probe/read.py")
    actual = decoded(probe)
    gate.record(name, transport(probe) and same(actual, expected), {
        "observation_source": "Fresh process calling the submitted EventStore.count and EventStore.get",
        "actual": actual, "expected": expected, "transport": probe.result,
    })
    return probe


def check(gate):
    first, second, third, discarded = ["event-" + gate.token() for _ in range(4)]
    value = gate.number()

    def event(identifier, kind=" Sale ", amount=value, **extra):
        return {"id": identifier, "kind": kind, "value": amount, **extra}

    def lines(items):
        return "\n".join(
            item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            for item in items
        ).encode() + b"\n"

    first_row = event(first, "sale")
    second_row = event(second, "refund", -value)
    # Invalid duplicates must be validated before duplicate classification.
    source = lines([
        " ", event(" " + first + " ", ignored="discard me"),
        event(first, "other", value + 1), event(first, amount=True),
        "{broken", event(second, " ReFuNd ", -value), [],
    ])
    setup = {
        "probe/input.jsonl": source,
        "probe/ids.json": json.dumps([first, second, third, discarded]).encode(),
        "probe/read.py": READ_DRIVER,
    }
    command = "python -m eventlog probe/events.db probe/input.jsonl"
    case = gate.case("event-lenient-normalization", setup, command)
    actual = decoded(case)
    gate.record("event-lenient-report", transport(case)
                and report_matches(actual, 2, 1, [4, 5, 7]),
                {"actual": actual, "transport": case.result})
    before = {"count": 2, "rows": [first_row, second_row, None, None]}
    case = observe(gate, case, "event-persistence-normalization", before)

    strict_source = lines([event(third), " ", event(first, amount=False), event(discarded)])
    case = gate.step(case, command + " --strict", {"probe/input.jsonl": strict_source})
    error = decoded(case, "stderr")
    good_error = (
        isinstance(error, dict) and set(error) == {"line", "message"}
        and type(error["line"]) is int and error["line"] == 3
        and isinstance(error["message"], str) and bool(error["message"])
    )
    gate.record("event-strict-cli-error", transport(case, 2)
                and case.result.get("stdout") == "" and good_error
                and len(case.result.get("stderr", "").splitlines()) == 1,
                {"actual": error, "transport": case.result})
    case = observe(gate, case, "event-strict-rollback", before)

    source = lines([event(first, "changed", value + 10), event(third)])
    case = gate.step(case, "python -m eventlog probe/events.db - --strict < probe/input.jsonl",
                     {"probe/input.jsonl": source})
    actual = decoded(case)
    gate.record("event-recovery-stdin-report", transport(case)
                and report_matches(actual, 1, 1, []),
                {"actual": actual, "transport": case.result})
    after = {"count": 3, "rows": [first_row, second_row, event(third, "sale"), None]}
    case = observe(gate, case, "event-first-wins-across-processes", after)

    missing = gate.step(case, "python -m eventlog probe/events.db probe/does-not-exist")
    stderr = missing.result.get("stderr", "")
    gate.record("event-missing-source", transport(missing, 2)
                and missing.result.get("stdout") == "" and bool(stderr.strip())
                and "Traceback" not in stderr, {"transport": missing.result})

    # Observe incremental insertion and rollback on a source exception. The
    # driver supplies inputs and collects facts; expected values stay outside.
    driver = '''import json, sys
sys.path.insert(0, "/workspace")
from eventlog.store import EventStore
from eventlog.importer import import_events
item = json.load(open("probe/event.json", encoding="utf-8"))
store = EventStore("probe/events.db")
seen = []
class SourceFault(Exception): pass
def source():
    yield json.dumps(item)
    seen.append(store.get(item["id"]))
    raise SourceFault("source failed")
try:
    try:
        import_events(source(), store)
    except BaseException as exc:
        outcome = type(exc).__name__
    else:
        outcome = "returned"
    print(json.dumps({"exception": outcome, "seen": seen,
                      "after": store.get(item["id"]), "count": store.count()}))
finally:
    store.close()
'''
    probe = gate.step(case, "python -I -S probe/stream.py", {
        "probe/stream.py": driver.encode(),
        "probe/event.json": json.dumps(event(discarded, "sale")).encode(),
    })
    actual = decoded(probe)
    expected = {"exception": "SourceFault", "seen": [event(discarded, "sale")],
                "after": None, "count": 3}
    gate.record("event-streaming-source-failure", transport(probe)
                and same(actual, expected),
                {"actual": actual, "expected": expected, "transport": probe.result})
    observe(gate, probe, "event-source-failure-persistence", after)

    # Opening can succeed before reading fails. API propagation alone does not
    # fulfill the CLI's unreadable-source diagnostic and cleanup contract.
    probe = gate.step(probe, "python -I -S probe/cli_read_failure.py", {
        "probe/cli_read_failure.py": CLI_READ_FAILURE_DRIVER,
    })
    actual = decoded(probe)
    expected = {"code": 2, "exception": None, "stdout": "",
                "source_closed": True, "row": None, "count": 3}
    stderr = actual.get("stderr") if isinstance(actual, dict) else None
    facts = {k: v for k, v in actual.items() if k != "stderr"} if isinstance(actual, dict) else None
    gate.record("event-cli-source-read-failure", transport(probe)
                and same(facts, expected) and isinstance(stderr, str)
                and bool(stderr.strip()) and "Traceback" not in stderr,
                {"actual": actual, "expected": expected,
                 "stderr_requirement": "nonempty diagnostic without traceback",
                 "transport": probe.result})
