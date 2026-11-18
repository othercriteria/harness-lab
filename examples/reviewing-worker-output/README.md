# Review two Worker submissions

One Worker wrote a change that landed. Another produced a reasonable review whose handoff the Maintainer rejected. Follow the evidence for each decision. You can read both cases on GitHub. To run the first check, use a full clone, Git, and Python 3.13 on Linux. This example follows the version rehearsed on 18 November 2026. Its evidence links point to files at that revision.

From the root of a current clone, you can check the bytes of three recorded
evidence files against the example inventory before entering the historical
checkout. A missing or changed file produces its own entry and exit status 1.
This checks consistency with the supplied inventory. The review below explains
how to evaluate the claims in those files.

```sh
python3 examples/check_evidence.py examples/reviewing-worker-output/files.json
```

From the root of your clone, create a separate checkout at the recorded commit and enter it:

```sh
git worktree add --detach ../local-harness-walkthrough 8f98938c546be353de613bebd042445a71ca3180
cd ../local-harness-walkthrough
```

Run the commands below in that directory. You can also open the files at the same paths in this checkout.

## Would you apply this patch?

A session approaching its context limit can save a note and start a fresh context. Sometimes the work is already finished. The [assignment](https://github.com/othercriteria/local-harness-lab/blob/8f98938c546be353de613bebd042445a71ca3180/examples/reviewing-worker-output/accepted/brief.txt) asked Worker for the small function that decides when the harness can offer submission at that boundary. A pending explicit review, for example, must still take place.

Inspect the change as it landed, check that your interpreter reports Python 3.13.x, and run the tests:

```sh
git show 3aaf108 -- scripts/checkpoint_policy.py
python3 --version
python3 -B -S -m unittest -v tests/test_checkpoint_policy.py
```

The [policy function](https://github.com/othercriteria/local-harness-lab/blob/8f98938c546be353de613bebd042445a71ca3180/scripts/checkpoint_policy.py) reads configuration and returns a boolean. Offering submission still leaves the ordinary handoff checks to the caller. Expect 14 passing tests in the checkout that accompanies this example. One checks that a Worker inside a scoped subtask cannot take this exit. [Worker’s tests](https://github.com/othercriteria/local-harness-lab/blob/8f98938c546be353de613bebd042445a71ca3180/tests/test_checkpoint_policy.py)

Worker wrote those tests too. What evidence did the Maintainer bring? Read the [independent check outcomes](https://github.com/othercriteria/local-harness-lab/blob/8f98938c546be353de613bebd042445a71ca3180/examples/reviewing-worker-output/accepted/verification.json). The submitted function passed 31 cases. The same checker rejected an always-true substitute on malformed input and an always-false substitute on an eligible configuration. The [outer review](https://github.com/othercriteria/local-harness-lab/blob/8f98938c546be353de613bebd042445a71ca3180/examples/reviewing-worker-output/accepted/outer-review.json) accepted both files. The [landing receipt](https://github.com/othercriteria/local-harness-lab/blob/8f98938c546be353de613bebd042445a71ca3180/results/checkpoint-finalization-worker-landing-001.json) records application without repairs. The commit message credits Worker for the predicate and tests. The Maintainer integrated the caller separately. [Landing commit](https://github.com/othercriteria/local-harness-lab/commit/3aaf1082703d7e85feb1f7c2cce590ec48e319f6)

## Would you accept this handoff?

In a later run, the [brief](https://github.com/othercriteria/local-harness-lab/blob/8f98938c546be353de613bebd042445a71ca3180/examples/reviewing-worker-output/rejected/brief.txt) asked Worker to compare a documentation change with its supporting sources and report only checks it actually ran. Its [submitted review](https://github.com/othercriteria/local-harness-lab/blob/8f98938c546be353de613bebd042445a71ca3180/examples/reviewing-worker-output/rejected/worker-review.json) found no actionable defects. In the [final handoff](https://github.com/othercriteria/local-harness-lab/blob/8f98938c546be353de613bebd042445a71ca3180/examples/reviewing-worker-output/rejected/handoff.json), Worker cited observation `o0013` for a script that it said checked whether all three Markdown links resolved, including a README heading anchor.

Before opening the verdict, read the [complete command](https://github.com/othercriteria/local-harness-lab/blob/8f98938c546be353de613bebd042445a71ca3180/examples/reviewing-worker-output/rejected/o0013-command.txt) and its [stdout](https://github.com/othercriteria/local-harness-lab/blob/8f98938c546be353de613bebd042445a71ca3180/examples/reviewing-worker-output/rejected/o0013-output.txt). Which operation would fail, or print a diagnostic, if a link pointed at a missing heading?

<details>
<summary>Compare your judgment with the Maintainer’s</summary>

The script reads four documents and looks for backticked terms in their text. Its final line extracts link destinations with a regular expression and prints them. It never opens the extracted destinations or looks up a heading. The command ran successfully, but its output establishes only which link strings it found.

The [outer review](https://github.com/othercriteria/local-harness-lab/blob/8f98938c546be353de613bebd042445a71ca3180/examples/reviewing-worker-output/rejected/outer-review.json) accepted the substantive finding that the guide was sound. It rejected the full result because the handoff attributed a stronger check to that command. The campaign recorded a clean submission, passing structural checks, accepted source, and a rejected handoff for job `8118601576284efa88ed3caaa9cec04f`. [Campaign record](https://github.com/othercriteria/local-harness-lab/blob/8f98938c546be353de613bebd042445a71ca3180/results/checkpoint-finalization-conclusions-001.json)

</details>

## What you can verify here

Git contains the patch, the runnable Worker tests, the two briefs, the submitted review and the exact disputed command and output. You can reach your own conclusion about the link-check claim by inspection. The independent evaluator results, service cleanup and model timings are historical observations. Repeating those runs takes the original frozen packages, model, evaluator and workstation services. The [operator guide](https://github.com/othercriteria/local-harness-lab/blob/8f98938c546be353de613bebd042445a71ca3180/docs/operations.md) describes that environment.

The two `brief.txt` files contain the original specification’s `brief` field. Each `outer-review.json` is the original decision file. The accepted verification excerpt preserves the condition, return code and output for each independent check. The rejected case includes the original proposed `review.json`, the `handoff` field from the terminal receipt, and the command and stdout of tool call 13. Absolute paths inside the original records identify workstation artifacts.

When you finish, return to your original clone and run `git worktree remove ../local-harness-walkthrough` to remove the example checkout.
