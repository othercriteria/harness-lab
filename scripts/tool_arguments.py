"""Decode JSON tool arguments with unique keys and no NaN or Infinity literals."""

import json


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("Nonfinite JSON constant")


def load_arguments(raw):
    return json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
