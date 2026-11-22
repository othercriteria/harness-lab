# Test a source-review objection

Worker’s issue exporter passed both timed code checks. On reading the source, a reviewer noticed that it converted the entire `--issue` argument with `int()`. Would a legal spelling of issue 7 reach the lookup? A second objection went the other way. Aider’s Tabreport writer specified LF record endings. Would it split a field containing a bare carriage return?

Run this from a full Git clone with Python 3.13. It reconstructs the reviewed source trees, reads the recorded observations, evaluates each prediction and checks that substituting the reference tree invalidates the candidate receipt. This path runs on CPU and reads the submitted Python as data.

```sh
python3 -S examples/replaying-review-objections/replay.py
```

| Objection and expected observation | Candidate | Reference | Finding on this input |
| --- | --- | --- | --- |
| 4,500 leading zeroes followed by 7 should produce one lookup for issue 7 and a packet containing issue 7. | Worker seed 19550 raised the 4,300-digit conversion error before any lookup or output. | The integrated exporter exited 0, made one lookup and wrote issue 7. | Confirmed. The original timed machine checks passed. |
| A quoted CSV label containing `Team\rNorth` should survive as one field in one added row, with LF record endings. | Aider seed 19551 exited 0. Strict CSV parsing recovered the header and the expected row. | The reference quoted every cell. Its parsed rows and final LF agreed with the candidate. | Refuted. The original timed machine checks failed on other obligations. |

The CSV candidate also emitted a module-import warning. The witness records the warning and judges the specific prediction about the output file. Output bytes differ between the two implementations because they quote fields differently. [Bound observations and exact output bytes](packet/capture.json) · [Original comparison and grades](../../docs/standard-worker-comparison.md#two-additional-seeds-on-each-of-two-ladder-tasks)

## Repeat the executions

From the Lab dev shell on the reference workstation, give the capture a fresh directory. It runs four disposable CPU sandboxes using the existing external behavioral grader. The fake `gh` records its arguments inside the sandbox. The outer process inspects the output files and retains the inputs, raw results and cleanup receipts under that directory.

```sh
.venv/bin/python examples/replaying-review-objections/replay.py --capture /tmp/review-objections-001
```

For both candidates, the command request and input fixture records in the fresh run matched the archived #55 records. The new capture checks the pinned Python executable and Lab transport manifest and compares the observations to the published packet. A port with a different runtime can still check the packet offline. Runtime changes matter here because the decimal conversion limit and CSV behavior both depend on the interpreter. [Sandbox requirements](../../docs/operations.md#environment) · [Replay and capture](replay.py)

## Record the next objection

1. Name the submission and the source construct under review. Write down the concrete input, the expected product behavior and the specific failure you predict. If execution would be impractical, retain the source finding and label it **source review only**.
2. Give the candidate and an identified reference the same fixture, command and runtime. Record their tree digests, fixture and command identity, runtime identity, and observed outputs together. Keep the expected result and its comparison in the outer process.
3. Confirm the objection when the predicted failure occurs and the reference meets the expectation. Refute it for this input when the candidate meets the expectation. A broken reference, timeout or unrelated exception leaves the objection unresolved. Keep the original timed verdict alongside this later decision.

Here the starter files come from Lab commit `100a717`. The portable packet contains the submitted source changes as text. Their paths and SHA-256 digests must match the corresponding #55 row. The source tree covers the public task files plus those changes. Aider's client logs and private Git state are outside that tree. The exporter comparator is the previously integrated implementation at `c7b7b84`. Tabreport uses the task’s reference implementation. Each original candidate probe receipt also matches its previously published digest. These unsigned records rely on the publisher for the capture. [Original padding receipt](packet/padding/historical.json) · [Original CSV receipt](packet/csv/historical.json)

OpenAI `gpt-6.2-astra` wrote the replay, guide and CI integration. The submitted source exhibits were generated in #55 by Qwen3.8-27B (RANA tensor precision layout, Q4_K_M) running under Worker and Aider. The artifacts retain their original bytes. [Per-run provenance](../../results/harness-comparison-repeats-055.json)
