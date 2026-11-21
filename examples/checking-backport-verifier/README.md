# Replay the two-branch Git backport reference

From the repository root in the configured Lab shell, run the replay with a fresh output directory.

```sh
.venv/bin/python examples/checking-backport-verifier/replay.py /tmp/backport-reference-v6
```

This CPU-only check restores the public starter, fetches the two sealed reference commits from an incremental bundle, and runs the public tests on each tip. The Git verifier then independently checks the graph, handoff revisions, canonical suite and observed behavior. Git operations and candidate Python run in the Lab sandbox. The caller retains the receipts in the output directory. [Workstation requirements](../../docs/operations.md)

The positive reference came from a fresh reviewer who saw the public task and starter. On legacy, the parser raises an exact built-in `ValueError` and attaches a private token to that instance. The service inspects the exception’s stored attributes and checks the token by identity. A third-party exception’s fallback for missing attributes cannot supply that token. On stable the reference preserves the release’s dedicated exception type. Both tips passed 9 public tests and 19 canonical tests each, plus the external behavior check. [Reference commits](../../tasks/git-config-backport-dual-public-tests/private/reference-handoff.json)

## What revision 6 checks

A writer with only a `write(stream)` method raises an exception from inside that call. One case uses an ordinary `ValueError`. The other uses a subclass that returns a diagnostic default when asked for a missing attribute. The external probe records how often the writer was called and whether the caller received the original exception object. If the service returns normally, the probe records the returned status. Expected observations stay with the outer verifier. The existing safe-output and invalid-key observations run in the same process on each branch. The ladder recipe gates verified correctness on both canonical and behavioral results.

| Archived submissions | Pass graph, delivery, canonical and behavior under v5 | Pass the same gates under v6 |
| --- | ---: | ---: |
| Ten progress-confirmation seeds, 16810–16819 | 6/10 | 0/10 |
| Five ladder seeds, 14660–14664 | 5/5 | 1/5 |

Six legacy implementations in the first cohort and four in the second converted the diagnostic exception to status 2. The four other submissions in the first cohort had already failed canonical checks. All 15 stable submissions passed the new case. A separate negative control added a truthy-attribute check to the reference on stable alone. It passed v5 and both canonical suites, then failed v6 on stable while legacy passed.

These are new evaluator results on saved submissions. Original trial times and handoff judgments retain their recorded meaning. The public brief, starter bundle and public tests have identical bytes in both versions. The blind reviewer flagged a possible difference in interpretation for an independently created stable `InvalidWriteError`. Revision 6 exercises unrelated `ValueError` objects and leaves that case open. [Per-seed results and artifact digests](../../results/git-backport-evaluator-v6-001.json) · [Original selection study](../../docs/serial-selection.md#what-the-git-reviewer-found)
