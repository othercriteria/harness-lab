"""Compare CLI outputs outside candidate namespaces for the editing diagnostic."""

import csv
import io


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerows(rows)
    return stream.getvalue().encode()


def check(gate):
    token = gate.token()
    prefix = "team,rows,minutes,done,open\n"
    source = csv_bytes([
        ["team", "item", "minutes", "status"],
        ["Straße", token, "1:03", "done"],
        ["STRASSE", token, "1:04", "done"],
        ["Straße", token, "9:00", "open"],
        ["other", token, "8:00", "done"],
    ]) + b" , ,,,,\n"
    probe = gate.case("combined-selection-and-effort", {"probe/input.csv": source},
                      "python -m tabreport probe/input.csv --format csv --team strasse --status done --sort minutes")
    expected = prefix + "STRASSE,1,64,1,0\nStraße,1,63,1,0\nTOTAL,2,127,2,0\n"
    gate.record("combined-selection-and-effort", probe.result.get("returncode") == 0
                and probe.result.get("stdout") == expected and probe.result.get("stderr") == "",
                {"expected_stdout": expected, "observed": probe.result})

    label = "A\\|" + token + "\r\nB"
    source = csv_bytes([["team", "item", "minutes", "status"], [label, "x", "00:09", "open"]])
    probe = gate.case("markdown-file-output", {"probe/input.csv": source},
                      "python -m tabreport probe/input.csv --format markdown --no-total --output probe/result.md")
    expected = ("| Team | Rows | Minutes | Done | Open |\n"
                "| :--- | ---: | ---: | ---: | ---: |\n"
                "| A\\\\\\|" + token + "<br>B | 1 | 9 | 0 | 1 |\n").encode()
    gate.record("markdown-file-output", probe.result.get("returncode") == 0
                and probe.result.get("stdout") == "" and gate.read(probe, "probe/result.md") == expected,
                {"expected_hex": expected.hex(), "observed": probe.result})

    labels = ["TOTAL", "b", "a", "A", 'x,"' + token]
    source = csv_bytes([["team", "item", "minutes", "status"]]
                       + [[name, "x", "1:00", "done"] for name in labels]
                       + [["b", "y", "00:01", "open"]])
    expected = csv_bytes([["team", "rows", "minutes", "done", "open"],
                          ["b", 2, 61, 1, 1], ["A", 1, 60, 1, 0], ["a", 1, 60, 1, 0],
                          ["TOTAL", 1, 60, 1, 0], ['x,"' + token, 1, 60, 1, 0]])
    probe = gate.case("csv-ties-and-no-total", {"probe/input.csv": source},
                      "python -m tabreport - --sort minutes --format csv --no-total < probe/input.csv")
    gate.record("csv-ties-and-no-total", probe.result.get("returncode") == 0
                and probe.result.get("stdout", "").encode() == expected,
                {"expected_hex": expected.hex(), "observed": probe.result})

    for name, source in [
        ("bad-duration", b"team,item,minutes,status\nA,x,1,done\nB,y,1:60,open\n"),
        ("whitespace-header", b" , , , \nteam,item,minutes,status\n"),
    ]:
        probe = gate.case(name, {"probe/input.csv": source}, "python -m tabreport probe/input.csv --format csv")
        gate.record(name, probe.result.get("returncode") == 2
                    and probe.result.get("stdout") == ""
                    and probe.result.get("stderr", "").startswith("error:"),
                    {"observed": probe.result})

    probe = gate.case("header-only", {"probe/input.csv": b"team,item,minutes,status\n , , \n"},
                      "python -m tabreport probe/input.csv --format csv --sort minutes")
    expected = prefix + "TOTAL,0,0,0,0\n"
    gate.record("header-only", probe.result.get("returncode") == 0
                and probe.result.get("stdout") == expected,
                {"expected_stdout": expected, "observed": probe.result})
