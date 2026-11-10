import copy
import json
import re


def valid_id(value):
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value) is not None
    )


def safe_path(value):
    return (
        isinstance(value, str)
        and "\\" not in value
        and all(part not in ("", ".", "..") for part in value.split("/"))
    )


def parse_spec(data):
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "steps"}
        or type(data["version"]) is not int
        or data["version"] != 1
        or not isinstance(data["steps"], list)
    ):
        raise ValueError("invalid specification")
    result = {}
    for item in data["steps"]:
        if (
            not isinstance(item, dict)
            or not {"id", "command"} <= set(item)
            or set(item) - {"id", "command", "deps", "inputs"}
        ):
            raise ValueError("invalid step")
        name = item["id"]
        if not valid_id(name) or name in result:
            raise ValueError("invalid or duplicate id")
        command = item["command"]
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(x, str) or not x for x in command)
        ):
            raise ValueError("invalid command")
        values = {}
        for key, validator in [("deps", valid_id), ("inputs", safe_path)]:
            value = item.get(key, [])
            if (
                not isinstance(value, list)
                or any(not validator(x) for x in value)
                or len(set(value)) != len(value)
            ):
                raise ValueError("invalid " + key)
            values[key] = sorted(value)
        result[name] = {"id": name, "command": list(command), **values}
    for step in result.values():
        if any(dep not in result for dep in step["deps"]):
            raise ValueError("unknown dependency")
    visiting, done = set(), set()

    def visit(name):
        if name in visiting:
            raise ValueError("dependency cycle")
        if name in done:
            return
        visiting.add(name)
        for dep in result[name]["deps"]:
            visit(dep)
        visiting.remove(name)
        done.add(name)

    for name in result:
        visit(name)
    return copy.deepcopy(result)


def load_spec(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)
