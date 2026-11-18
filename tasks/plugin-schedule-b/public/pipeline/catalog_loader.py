import json
from pathlib import Path

def load_catalog():
    result = {}
    for path in sorted((Path(__file__).parent / "catalog").glob("*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            result[entry["id"]] = entry["dependencies"]
    return result
