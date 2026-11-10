# Plan the plugin pipeline

Implement `pipeline.planner.plan(features, target)` and preserve the CLI
`python -m pipeline --target TARGET [--feature FEATURE ...]`.
Read `pipeline/contracts.py` and every JSON file in `pipeline/catalog/`;
together with this brief they are the public integration contract.

The supplied feature names and target names are fixed. Callers supply a set of
known feature strings and a known target. Every such combination is supported.
Each catalog entry describes one plugin and a list of dependency rules. A rule
is active exactly when all of its `when` features are enabled (the empty list
is always active). An active dependency means that plugin must run before the
entry that declares it. Features do not otherwise enable or disable plugins.

Starting at the target, select precisely the transitive closure of its active
dependencies, including the target. Return a list of plugin IDs, each selected
ID exactly once and no others. Every active dependency among the selected IDs
must appear strictly earlier than its dependent. At each step choose the
lexicographically smallest currently runnable selected ID. The result must be
deterministic, must not mutate the caller's feature set, and must be returned
for every supported combination; raising, hanging, returning a partial plan,
or dropping an active dependency is not an acceptable outcome for those inputs.

CLI success prints the list as one JSON line to stdout and exits 0 without
stderr. Unknown features or targets are CLI usage errors: exit 2, nonempty
stderr and empty stdout; no traceback. Direct API behavior on invalid inputs is
outside scope. Use only the standard library. The existing loader may be reused.

Only `pipeline/planner.py` and `pipeline/__main__.py` may be changed; you may add
tests. The other supplied files represent upstream contracts and cannot be
changed, reinterpreted or bypassed. They are local fixed configuration, not
untrusted input requiring a generic catalog-validation framework.

If the complete integration contract cannot be met, explain the obstruction
with a concrete supported configuration and the necessary requirement or
upstream-contract change in your final handoff. Passing the example tests alone
does not establish that every supported combination can be handled.
