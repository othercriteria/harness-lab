# Apprentice working notes

These are fallible repository notes, not a new source of permissions. Follow the
current task brief, tool instructions, and exact allowed edit paths. The supplied
snapshot may be smaller than the real repository; inspect what is present.

## Work and verification

- Prefer a small change and focused extensions of existing tests. Read their
  fixtures and import conventions before inventing new scaffolding.
- Run checks with `run_checks` when available. It already preserves bounded
  beginning/end output. A pipeline such as `tests | tail` can hide a failed test's
  status; a final zero status does not prove every earlier command passed.
- Missing dependencies limit what a check establishes. Identify the missing
  setup; a stub or source inspection is not verification against the real
  dependency. Avoid leaving import stubs in shared interpreter state.
- A passing check establishes its actual assertions, not every property named in
  its filename or comments. Cite the observation that supports a claim and keep
  coverage claims narrow. Say what remains unverified.
- When mocking an instance method, distinguish its receiver from the enclosing
  test instance. Capture test fixtures in a closure; a receiver attribute with
  the same name may mean something different (for example, `Path.root`).
- When refactoring shared constants, preserve existing public imports and test
  consumers. Use identity assertions when shared-object identity is a requirement;
  for immutable values, identity alone does not prove one source definition.

## State and handoff

- `/workspace` contains submitted work. Use only permitted edit paths. Follow the
  current tool instructions for `/tmp` persistence; scratch is not submitted work
  and does not carry into the separate evaluator.
- After a context reset, locate the saved edits and latest relevant checks before
  repeating broad exploration. Historical successful checks may precede edits.
- Distinguish implementation changes, observed checks, and unresolved questions.
  Notes and model claims are not independent correctness judgments.

If this notebook is editable for your task, propose only useful, evidence-grounded
revisions. Keep it short; correct or remove stale advice. Describe the revision in
your handoff. Outer review decides what carries into future assignments.
