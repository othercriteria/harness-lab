import json
import os


def validate_state(state):
    return state


def load_state(path):
    try:
        with open(path, encoding="utf-8") as stream:
            return validate_state(json.load(stream))
    except FileNotFoundError:
        return {"version": 2, "completed": {}}


def replace_file(source, destination):
    """Publication hook; callers may replace this hook for auditing/fault tests."""
    os.replace(source, destination)


def save_state(path, state):
    validate_state(state)
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(state, stream)
