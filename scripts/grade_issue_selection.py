"""Independent comparison of issue-export subprocess effects."""

import json

FAKE = b"""#!/bin/python3
import json,sys
from pathlib import Path
a=sys.argv[1:]
with Path('probe/calls').open('a') as f:f.write(json.dumps(a)+'\\n')
if a[:2]!=['issue','view'] or '--repo' not in a or a[a.index('--repo')+1]!='example/repo':sys.exit(4)
if set(a[a.index('--json')+1].split(','))!=set('number,state,title,body,url,updatedAt,labels'.split(',')):sys.exit(5)
n=int(a[2])
if n==113:sys.exit(3)
print(json.dumps(dict(number=n,state='CLOSED',title=str(n),body='record',labels=[dict(name='z'),dict(name='a')],url='u',updatedAt='t')))
"""


def check(gate):
    setup = {"probe/gh": FAKE}
    for name, args, valid in [
        ("selected", ["09", "12", "9"], True),
        ("missing", ["5", "113"], False),
        ("zero", ["3", "00"], False),
        ("unicode", ["７"], False),
        ("too-many", list(map(str, range(1, 52))), False),
    ]:
        words = " ".join("--issue " + a for a in args)
        # Python makes the test fixture executable; the candidate only sees its CLI.
        prefix = "python -c \"import os; os.chmod('probe/gh',0o755)\" && "
        case = gate.case(
            name,
            setup,
            prefix
            + "PATH=/workspace/probe:/bin python scripts/export_issue_context.py example/repo probe/out "
            + words,
        )
        calls = (
            []
            if gate.absent(case, "probe/calls")
            else [json.loads(s) for s in gate.read(case, "probe/calls").splitlines()]
        )
        if valid:
            pkt = (
                json.loads(gate.read(case, "probe/out"))
                if not gate.absent(case, "probe/out")
                else {}
            )
            ok = (
                case.result.get("ok")
                and sorted(c[2] for c in calls) == ["12", "9"]
                and [r["number"] for r in pkt.get("issues", [])] == [9, 12]
                and all(
                    r["labels"] == ["a", "z"] and r["state"] == "CLOSED"
                    for r in pkt.get("issues", [])
                )
            )
        else:
            ok = (
                not case.result.get("ok")
                and gate.absent(case, "probe/out")
                and (
                    any(c[:3] == ["issue", "view", "113"] for c in calls)
                    if name == "missing"
                    else not calls
                )
            )
        gate.record(name, ok, {"calls": calls, "exit": case.result.get("returncode")})
