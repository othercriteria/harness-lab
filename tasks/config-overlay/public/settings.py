"""Configuration loading for batch jobs."""

from merge import merge

DEFAULTS = {"worker": {"retries": 3, "labels": ["batch"]}, "enabled": True}


def load_settings(overrides):
    return merge(DEFAULTS, overrides)
