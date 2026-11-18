"""Compare isolated decoder observations with independently constructed outer expectations."""

import json

DRIVER = b"""import json,sys
sys.path.insert(0, "/workspace")
from frame_decoder import FrameDecoder
data=json.load(open("probe/inputs.json"))
def typed(value):
    if value is None:return {"type":"NoneType"}
    if type(value) is list:return {"type":"list","items":[{"type":type(x).__name__,"hex":x.hex() if type(x) is bytes else None} for x in value]}
    return {"type":type(value).__name__}
result={}
for case in data:
    decoder=FrameDecoder(case["max"])
    observed=[]
    for action in case["actions"]:
        try:
            value=decoder.feed(bytes.fromhex(action[1])) if action[0]=="feed" else decoder.finish()
            observed.append(typed(value))
        except Exception as exc:observed.append({"error":type(exc).__name__})
    result[case["name"]]=observed
print(json.dumps(result))
"""


def check(gate):
    def frames(values):
        return {
            "type": "list",
            "items": [{"type": "bytes", "hex": p.hex()} for p in values],
        }

    nil = {"type": "NoneType"}
    error = {"error": "ValueError"}
    cases, expected = [], {}

    def add(name, maximum, actions, outputs):
        cases.append({"name": name, "max": maximum, "actions": actions})
        expected[name] = outputs

    payloads = [b"", bytes.fromhex(gate.token()), b"\0" * 5, b"\xff\x80", b""]
    stream = b"".join(len(p).to_bytes(4, "big") + p for p in payloads)
    ends = []
    end = 0
    for payload in payloads:
        end += 4 + len(payload)
        ends.append(end)
    actions, outputs, offset, emitted = [], [], 0, 0
    sizes = [1, 0, 2, 7, 3, 0, 1, 9, 4]
    index = 0
    while offset < len(stream):
        size = sizes[index % len(sizes)]
        index += 1
        chunk = stream[offset : offset + size]
        offset += len(chunk)
        complete = sum(boundary <= offset for boundary in ends)
        actions.append(["feed", chunk.hex()])
        outputs.append(frames(payloads[emitted:complete]))
        emitted = complete
    add(
        "arbitrary_chunking",
        8,
        actions + [["finish"], ["finish"]],
        outputs + [nil, nil],
    )
    add(
        "finished_state",
        0,
        [["feed", "00000000"], ["finish"], ["feed", ""], ["finish"]],
        [frames([b""]), nil, error, nil],
    )
    add(
        "oversize_immediate_and_sticky",
        2,
        [
            ["feed", "000000"],
            ["feed", "03"],
            ["feed", "616263"],
            ["feed", ""],
            ["finish"],
        ],
        [frames([]), error, error, error, error],
    )
    add(
        "valid_then_bad_same_call",
        1,
        [["feed", "0000000161"], ["feed", "000000016200000002"], ["finish"]],
        [frames([b"a"]), error, error],
    )
    add(
        "partial_header_at_finish",
        2,
        [["feed", "0000"], ["finish"], ["feed", "0000"], ["finish"]],
        [frames([]), error, error, error],
    )
    add(
        "partial_payload_at_finish",
        2,
        [["feed", "0000000261"], ["finish"], ["feed", "62"], ["finish"]],
        [frames([]), error, error, error],
    )
    probe = gate.case(
        "frame-streams",
        {"probe/driver.py": DRIVER, "probe/inputs.json": json.dumps(cases).encode()},
        "python -I -S probe/driver.py",
    )
    try:
        actual = gate.json(probe)
    except (ValueError, TypeError):
        actual = None
    good = (
        probe.result.get("ok") is True
        and probe.result.get("stderr") == ""
        and isinstance(actual, dict)
    )
    for name, value in expected.items():
        observed = actual.get(name) if isinstance(actual, dict) else None
        gate.record(
            name, good and observed == value, {"expected": value, "actual": observed}
        )
