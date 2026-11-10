# Fix configuration overlays

`settings.load_settings` combines defaults with per-job overrides. Currently a
partial nested override loses unrelated defaults, and returned values can alias
the caller's dictionaries. Fix this through `settings.merge` while preserving
the public API.

Contract: merge dictionaries recursively when both values are dictionaries.
Otherwise the override replaces the default, including lists, `None`, and falsey
values. Return independent copies of all nested dictionaries/lists, including
keys present in only one input. Never mutate either input. Inputs are acyclic
JSON-compatible dictionaries. Do not introduce external dependencies.

Run the public tests with `python -m unittest discover -s tests` and add useful
regressions. Keep changes focused on this contract.
