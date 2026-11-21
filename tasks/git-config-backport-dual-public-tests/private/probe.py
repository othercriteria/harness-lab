import io
import json
import sys

sys.path.insert(0, "/workspace")
import configparser as cp

import service


class DiagnosticError(ValueError):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return "unspecified"


class Writer:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def write(self, stream):
        self.calls += 1
        raise self.error


def observe_writer(error):
    writer = Writer(error)
    try:
        status = service.export(writer, io.StringIO())
    except Exception as observed:
        return {"calls": writer.calls, "same_exception": observed is error}
    return {"calls": writer.calls, "returned": status}


parser = cp.ConfigParser()
parser.read_dict({"second": {"z": "9", "a": "1"}, "first": {"c": "3"}})
out = io.StringIO()
status = service.export(parser, out)
safe = [out.getvalue(), status, type(status).__name__]
parser.set("first", "bad\rkey", "value")
out = io.StringIO("retain")
out.seek(0, 2)
status = service.export(parser, out)
print(
    json.dumps(
        {
            "safe": safe,
            "invalid": [
                status,
                type(status).__name__,
                out.getvalue(),
                out.tell(),
                out.closed,
            ],
            "writer_errors": {
                "ordinary": observe_writer(ValueError("ordinary failure")),
                "diagnostic": observe_writer(DiagnosticError("ordinary failure")),
            },
        }
    )
)
