import json

from .model import normalize_event


class ImportFailure(ValueError):
    def __init__(self, line, message):
        self.line = line
        self.message = message
        super().__init__(message)


def import_events(lines, store, *, strict=False):
    report = {"inserted": 0, "duplicates": 0, "invalid": 0, "errors": []}
    with store.connection:
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                event = normalize_event(json.loads(line))
            except (ValueError, TypeError) as error:
                if strict:
                    raise ImportFailure(number, str(error)) from error
                report["invalid"] += 1
                report["errors"].append({"line": number, "message": str(error)})
                continue
            report["inserted" if store.insert(event) else "duplicates"] += 1
    return report
