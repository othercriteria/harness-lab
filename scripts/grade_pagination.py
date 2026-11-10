"""External observations for the existing pagination contract."""

import json

DRIVER = b"""import json,sys
sys.path.insert(0,"/workspace")
from api import Page
from records import iter_records
data=json.load(open("probe/inputs.json"));values=data["values"]
r={};calls=[];consumed=[]
def items():
    for value in values[:2]:
        consumed.append(value);yield value
def fetch(cursor):
    calls.append(cursor)
    if cursor is None:return Page(items(),"")
    if cursor=="":return Page(iter([]),0)
    if cursor==0:return Page(iter(values[2:]))
    raise RuntimeError("unexpected cursor")
stream=iter_records(fetch)
r["construction_lazy"]=[list(calls),list(consumed)]
one=next(stream);r["incremental_items"]=[one,list(calls),list(consumed)]
two=next(stream);r["page_transition_lazy"]=[two,list(calls),list(consumed)]
rest=list(stream);r["generators_and_falsey_cursors"]=[rest,calls,consumed]
r["empty_terminal"]=list(iter_records(lambda cursor:Page(iter([]))))
requests=[]
def cyclic(cursor):
    requests.append(cursor)
    if len(requests)>3:raise RuntimeError("duplicate fetch")
    return Page([cursor],"a" if cursor in (None,"b") else "b")
stream=iter_records(cyclic);prefix=[next(stream) for _ in range(3)]
try:next(stream);failure=None
except Exception as exc:failure=type(exc).__name__
r["cycle_before_refetch"]=[prefix,failure,requests]
requests=[];original=RuntimeError(data["message"])
def failed(cursor):requests.append(cursor);raise original
try:next(iter_records(failed));failure=None;same=False
except Exception as exc:failure=type(exc).__name__;same=exc is original
r["callback_exception"]=[failure,same,requests]
class NoneAlias:
    def __hash__(self):return hash(None)
    def __eq__(self,other):return other is None or isinstance(other,NoneAlias)
requests=[];alias=NoneAlias()
def equal_initial(cursor):
    requests.append("initial" if cursor is None else "alias")
    if len(requests)>1:raise RuntimeError("equal initial cursor fetched again")
    return Page([],alias)
try:list(iter_records(equal_initial));failure=None
except Exception as exc:failure=type(exc).__name__
r["initial_cursor_equality"]=[failure,requests]
requests=[]
def equal_builtin(cursor):
    requests.append(cursor)
    if len(requests)>2:raise RuntimeError("equal cursor fetched again")
    return Page([],0 if cursor is None else False)
try:list(iter_records(equal_builtin));failure=None
except Exception as exc:failure=type(exc).__name__
r["cross_type_cursor_equality"]=[failure,requests]
class OpaqueCursor:
    def __hash__(self):return 123
    def __eq__(self,other):return self is other
    def __repr__(self):raise RuntimeError("representation unavailable")
    def __str__(self):raise RuntimeError("string unavailable")
opaque=OpaqueCursor();requests=[]
def opaque_repeat(cursor):
    requests.append(cursor is None)
    if len(requests)>2:raise RuntimeError("repeated cursor fetched")
    return Page([len(requests)],opaque)
try:list(iter_records(opaque_repeat));failure=None
except Exception as exc:failure=type(exc).__name__
r["repeat_without_diagnostic_formatting"]=[failure,requests]
print(json.dumps(r))
"""


def check(gate):
    values = ["record-" + gate.token() for _ in range(4)]
    data = {"values": values, "message": gate.token()}
    probe = gate.case(
        "lazy-pagination",
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
    expected = {
        "construction_lazy": [[], []],
        "incremental_items": [values[0], [None], values[:1]],
        "page_transition_lazy": [values[1], [None], values[:2]],
        "generators_and_falsey_cursors": [values[2:], [None, "", 0], values[:2]],
        "empty_terminal": [],
        "cycle_before_refetch": [[None, "a", "b"], "ValueError", [None, "a", "b"]],
        "callback_exception": ["RuntimeError", True, [None]],
        "initial_cursor_equality": ["ValueError", ["initial"]],
        "cross_type_cursor_equality": ["ValueError", [None, 0]],
        "repeat_without_diagnostic_formatting": ["ValueError", [True, False]],
    }
    for name, value in expected.items():
        observed = actual.get(name) if isinstance(actual, dict) else None
        gate.record(
            name, good and observed == value, {"expected": value, "actual": observed}
        )
