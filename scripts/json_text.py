"""Bounded JSON string sizing helpers for public-file digests.

Dependency-free: standard library only, no filesystem, subprocess, or
network operations.
"""

import json


def encoded(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def text_field(text, limit=256):
    """Return the longest prefix of ``text`` whose encoded JSON string is at
    most ``limit`` UTF-8 bytes, quotes and JSON escapes included.

    Prefixes are measured in Python string characters, not bytes; Unicode,
    lone surrogates, quotes, backslashes, and control characters are handled
    through :func:`encoded`. The input is returned unchanged when it already
    fits. The search is a binary search over prefix lengths: the encoded size
    grows strictly with prefix length, so no linear sequence of candidates is
    tried.
    """
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    if type(limit) is not int or limit < 2:
        raise ValueError("limit must be an exact built-in int >= 2")
    if len(encoded(text).encode("utf-8")) <= limit:
        return text
    # Invariant: text[:lo] fits (lo == 0 encodes to the two quote bytes and
    # limit >= 2), text[:hi] does not fit.
    lo, hi = 0, len(text)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if len(encoded(text[:mid]).encode("utf-8")) <= limit:
            lo = mid
        else:
            hi = mid
    return text[:lo]
