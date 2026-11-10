import copy
import json


def parse_spec(data):
    """Return detached normalized steps keyed by id; see task.md."""
    return {
        step["id"]: {
            "id": step["id"],
            "command": list(step["command"]),
            "deps": list(step.get("deps", [])),
            "inputs": list(step.get("inputs", [])),
        }
        for step in copy.deepcopy(data)["steps"]
    }


def load_spec(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)
