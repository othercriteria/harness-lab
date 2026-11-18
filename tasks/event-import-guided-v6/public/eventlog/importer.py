import json

from .model import normalize_event


class ImportFailure(ValueError):
    def __init__(self, line, message):
        self.line = line
        self.message = message
        super().__init__(message)


def import_events(lines, store, *, strict=False):
    report = {"inserted": 0, "duplicates": 0, "invalid": 0, "errors": []}
    for number, line in enumerate(lines, 1):
        if line.strip():
            event = normalize_event(json.loads(line))
            store.insert(event)
            report["inserted"] += 1
    return report
