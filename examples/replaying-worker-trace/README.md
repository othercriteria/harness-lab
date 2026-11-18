# Replay a reviewed Worker trace

An Observatory assignment asked Worker to distinguish a missing handoff at timeout
from an already submitted handoff. Read the commands and their recorded responses
in order. Which inputs did Worker try? Which additional input affected acceptance,
and how do you know which version the Maintainer reviewed?

From the repository root, run the following with Python 3. The replay reads JSON
and prints evidence. The historical commands and submitted Python stay inert.

```sh
python3 -S examples/replaying-worker-trace/replay.py
```

## What traveled with the trace

| Evidence | Where to look |
| --- | --- |
| Original user message and starting source | [ATIF trajectory](packet/agent/trajectory.json), step 1 |
| Worker's proposed source, test script, recorded check and final submission | Steps 2 through 5. The original assistant turn number is in each step's `extra`. Match responses to calls using `source_call_id`. |
| Reviewed file and exact byte identity | [Original artifact manifest](packet/artifact.json). The replay hashes the source in step 2 and compares it with the submitted change and both check inputs. |
| Prepared evaluator and later Maintainer probe | [Lab receipt](packet/receipt.json). The later probe includes its inputs, caught exception and process status. |
| Acceptance and its binding to the artifact | [Original outer review](packet/review.json) and [previously committed campaign record](../../results/worker-trial-label-effort-001.json). The absolute path in the historical review identifies the original archive. |

The packet selects four of nine assistant turns and preserves their original action
arguments, message text and model-visible tool responses. The final submission
ended the attempt. Its historical `exit` record produced no subsequent model-visible
tool response. The export omits the system prompt, reasoning, timing, token counts
and intervening turns. The prepared evaluator's command and result are included.
Its private checker is outside the packet. Inspect the later probe to see its exact
inputs. Replaying these records checks their consistency with the committed history.
It does not re-execute the job or independently attest to its isolation.

## What the rehearsal established

A fresh reader followed project navigation in a clean clone at `a3c6ffc`.
They distinguished Worker's 28 passing cases from the prepared evaluator and
identified the conflicting fields behind the rejection. The summary said
`Submitted`, but the review supplied `agent_outcome: null`. Worker's code
displayed a missing handoff at timeout. The reader also spotted why the later
probe exited zero even when a malformed status raised `TypeError`. The probe
caught the exception and printed its type.

The reader flagged a qualification. The brief explicitly assigns the acceptance
booleans to the receipt, but leaves the precedence of duplicate terminal fields
implicit. The probe documents the Maintainer's interpretation of that case.
The archived [comparison](../../results/worker-trial-label-effort-001.json) also
gives the separately sealed implementation's outputs on those inputs.

## Where ATIF helped

ATIF v1.8 represents the action, arguments, call ID and response in a form another
consumer can parse. The Lab receipt carries measurements by two observers outside
the conversation. Adding those as Worker turns would give a reader the false
impression that Worker saw them before it submitted. The immutable review names
the artifact digest, and the campaign record anchors both that digest and the
review bytes. The newly exported projection relies on the repository revision
for integrity. [Harbor ATIF specification](https://github.com/harbor-framework/harbor/blob/ea50d3e803796faec7c878b8cc8cc2c9440773c3/rfcs/0001-trajectory-format.md)

The example supports a repeatable export for a *selected decision*. Choosing the
relevant turns and locating the independent probe required knowledge of this
assignment. Keep that selection explicit for a second job before generalizing
the exporter. A consumer rehearsal and a task-packaging trial are tracked
separately.

The exporter hashes the archived verification inputs when assembling the
packet. The original review stored a path to the post-run probe results.
Recording that binding when the probe runs would simplify a future export.


## Archive reproduction

On the original workstation, point the exporter at the bulk archive and a new
output directory. A reader with only a clone starts with the replay above.

```sh
python3 -S examples/replaying-worker-trace/export.py /bulk/dlk/local-harness /tmp/worker-14-export
diff -r examples/replaying-worker-trace/packet /tmp/worker-14-export
```

The comparison used Harbor's upstream trajectory validator at revision
`ea50d3e803796faec7c878b8cc8cc2c9440773c3` with Pydantic 2.14.3.
The validator accepted the committed excerpt and rejected a copy with a
response assigned to an unrelated call ID. The Lab replay separately rejected
a copy whose Maintainer probe named a different input digest. Re-exporting
from the archive reproduced all four files byte for byte. The four action
payloads matched the recorded API responses, and the three returned tool
messages matched those sent in the following API requests. The clean-clone
replay also ran in a network-isolated namespace with no bulk archive mounted.
With the Harbor checkout's `src` directory on the Python path, run the validator as follows.

```sh
python -m harbor.utils.trajectory_validator examples/replaying-worker-trace/packet/agent/trajectory.json
```
