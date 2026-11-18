# Prepare a Worker package

Observatory used to say **USEFUL WORK** when a job had no recorded purpose. A diagnostic replay could therefore look like a shipped improvement. The Maintainer gave Worker the renderer, its existing regression test and a short assignment to fix that label. This example reconstructs exactly what Worker could read and edit, then follows its patch through review and application. [Original issue](https://github.com/othercriteria/local-harness-lab/issues/12)

## Rebuild the assignment

From the root of a full Git clone, use Linux, Git and Python 3.13. The following commands run offline with the standard library. The output goes into a new directory outside the checkout.

```sh
scratch=$(mktemp -d)
python3 -S examples/preparing-worker-package/prepare.py "$scratch/assignment"
cat "$scratch/assignment/task.md"
```

The generator reads two Git blobs from commit `0deaaef5`, builds the snapshot with Delegate's own code, and checks the snapshot, public contract, spec and historical dispatch request against the recorded identities. A successful run prints a snapshot beginning `b1b9242a` and a public contract beginning `ac5fc85e`. A shallow clone needs the history containing the starter commit.

| Open | What to look for |
| --- | --- |
| `$scratch/assignment/source/public/` | Worker received only `observatory/app.js` and `tests/test_observe_ui.js`. It could edit either file. |
| `$scratch/assignment/task.md` | The public brief and the edit scope derived from the snapshot. |
| `$scratch/assignment/spec.json` | The Maintainer selected the recipe, a 240-second task ceiling, a 15-second verification reserve, the private structural check and experimental admission. This small project assignment had no blind pre-review or sealed reference solution. |
| [Private check](changed.py) | The Verifier checked that both requested files changed and contained nonempty content. Rendering required a separate behavioral check. |
| [Historical dispatch request](request.json) | The original session, registered package, seed, idempotency key and 900-second end-to-end ceiling. The original request omitted classification. |
| [Run and review record](run.json) | The model's handoff and its limits, the review decision, the applied file hashes and the landing commit. |

## Inspect the result

```sh
git show 4a99ddb -- observatory/app.js tests/test_observe_ui.js
```

Worker retained the labels for the three recognized kinds and used **UNCLASSIFIED** for everything else. It exercised the classifications through the delegated run view. Worker reported static inspection and a Python simulation. It explicitly left the JavaScript suite for the reviewer.

The Maintainer ran the submitted suite in a separate networkless Node evaluator, then exercised nine cases using the original suite plus reviewer-authored assertions for Use, acceptance and application. Both suites passed on the candidate. Both failed on the old renderer at the missing-classification case, which still displayed **USEFUL WORK**. The first independent fixture had a faulty DOM lookup on both implementations. The reviewer corrected the fixture and repeated both arms. Delegate applied the original two-file artifact after comparing its identity and source base with the reviewed versions. [Landed Worker patch](https://github.com/othercriteria/local-harness-lab/commit/4a99ddb38432f9041ed525f6f69ee05b8211fee5)

The live records illustrate why Observatory keeps three fields separate. The original job in this example has no classification, an accepted review and a bound application receipt. Historical diagnostic replay `edeb69ceabfc482e86ab94936fc968cb` also earned acceptance and has no application receipt.

## Replay on a configured workstation

Registration is the boundary where the workstation's bulk storage, frozen recipe files and pinned runtime become necessary. Submission also requires local weights, an available GPU and an active quiet session with a restoration plan. An operator with that session already open can use the commands below. Set `session` to its ID. The historical session is closed. [Session management and review](../../docs/operations.md)

```sh
.venv/bin/python examples/preparing-worker-package/prepare.py "$scratch/replay" --register-for "$session"
.venv/bin/python scripts/delegate_job.py submit "$scratch/replay/request.json"
```

Registration writes the package and builds a new request using the returned package ID. The request records `diagnostic_replay` before launch. Use the job ID returned by submit to follow execution with `scripts/delegate_job.py status JOB_ID` and retrieve the artifact location with `scripts/delegate_job.py result JOB_ID`, both under `.venv/bin/python`. A terminal result still needs independent review. The starter is pinned to the pre-fix renderer, so the original landing has already changed the base on current main. [How to review Worker output](../reviewing-worker-output/README.md)

## What the handoff cost

For this job, package design and preparation took roughly 2–3 minutes including selecting the two files, writing the brief and choosing the check. Registration itself took less than one second using the existing recipe. Dispatch through artifact production took 199.5 seconds, including 174.8 seconds of Worker task time. Another 171 seconds elapsed from job completion to the recorded acceptance decision. The latter includes review, checking the original failure and correcting the review fixture. These are observations from one job. Some evaluator setup overlapped inference, and elapsed time includes operator and tool latency.

The CLI already returned a job ID while the job ran in the background. An MCP submit/status interface could make that handoff easier for a caller. Here the work that needed judgment was deciding which evidence would establish the fix and then obtaining it. A reusable isolated Node rendering check would address that cost directly. [Isolated Node checks](https://github.com/othercriteria/local-harness-lab/issues/15) · [MCP investigation](https://github.com/othercriteria/local-harness-lab/issues/11)
