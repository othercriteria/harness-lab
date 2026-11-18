"""Outer comparisons of lease-pool observations; candidate code stays isolated."""

import json

DRIVER = b"""import json,sys
sys.path.insert(0, "/workspace")
from lease_pool import LeasePool
data=json.load(open("probe/inputs.json"))
class Clock:
    def __init__(self): self.now=data["now"]; self.calls=0
    def __call__(self): self.calls+=1; return self.now
c=Clock();p=LeasePool(c);a,b=data["keys"]
def typed(v):return {"type":type(v).__name__,"value":v}
r={}
one=p.acquire(a,2);conflict=p.acquire(a,10);two=p.acquire(b,5)
r["acquire_and_conflict"]=[typed(one),typed(conflict),typed(two),c.calls]
r["strict_tokens"]=[typed(p.renew(a,True,1)),typed(p.release(a,1.0))]
c.now+=2
three=p.acquire(a,4)
r["boundary_and_fencing"]=[typed(three),typed(p.renew(a,one,1)),typed(p.release(a,one)),p.snapshot()]
c.now+=1
renewed=p.renew(a,three,0.5)
r["renew_from_now"]=[typed(renewed),p.snapshot()]
c.now+=0.5
r["expired_snapshot"]=p.snapshot()
before=p.snapshot();calls=c.calls;errors=[]
for fn in [lambda:p.acquire(a,False),lambda:p.renew(b,999,0),lambda:p.release('',two)]:
    try:fn();errors.append(None)
    except Exception as exc:errors.append(type(exc).__name__)
r["validation_atomicity"]=[errors,c.calls-calls,p.snapshot()==before]
snap=p.snapshot();snap[b]["token"]=999;snap[b]["remaining"]=999;snap.clear()
r["detach_and_reacquire"]=[typed(p.release(b,two)),typed(p.acquire(b,1)),typed(LeasePool(c).acquire(a,1))]
print(json.dumps(r))
"""


def check(gate):
    a, b = "job-" + gate.token(), "job-" + gate.token()
    data = {"keys": [a, b], "now": gate.number()}
    probe = gate.case(
        "lease-lifecycle",
        {"probe/driver.py": DRIVER, "probe/inputs.json": json.dumps(data).encode()},
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

    def typed(value):
        return {"type": type(value).__name__, "value": value}

    expected = {
        "acquire_and_conflict": [typed(1), typed(None), typed(2), 3],
        "strict_tokens": [typed(False), typed(False)],
        "boundary_and_fencing": [
            typed(3),
            typed(False),
            typed(False),
            {a: {"token": 3, "remaining": 4}, b: {"token": 2, "remaining": 3}},
        ],
        "renew_from_now": [
            typed(True),
            {a: {"token": 3, "remaining": 0.5}, b: {"token": 2, "remaining": 2}},
        ],
        "expired_snapshot": {b: {"token": 2, "remaining": 1.5}},
        "validation_atomicity": [["ValueError"] * 3, 0, True],
        "detach_and_reacquire": [typed(True), typed(4), typed(1)],
    }
    for name, value in expected.items():
        observed = actual.get(name) if isinstance(actual, dict) else None
        gate.record(
            name, good and observed == value, {"expected": value, "actual": observed}
        )
