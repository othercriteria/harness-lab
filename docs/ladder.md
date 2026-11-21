# Public task ladder

Ceilings are workstation model budgets. They do not measure human effort. Select a task to inspect its public brief.

| Task | Model ceiling | Evidence |
| --- | ---: | --- |
| [Release channel](../tasks/release-channel/public/task.md) | 60 s | [JavaScript pilot and confirmation](release-channel.md) |
| [git-config-backport-smoke-basic](../tasks/git-config-backport-smoke-basic/public/task.md) | 90 s | 5 of 5 reviewed full passes |
| [contract-codec-a](../tasks/contract-codec-a/public/task.md) | 120 s | 2 of 2 reviewed full passes |
| [contract-codec-b](../tasks/contract-codec-b/public/task.md) | 120 s | 2 of 2 reviewed full passes |
| [frame-decoder-focused](../tasks/frame-decoder-focused/public/task.md) | 180 s | 4 of 5 reviewed full passes |
| [event-import-guided-v12](../tasks/event-import-guided-v12/public/task.md) | 300 s | 5 of 5 reviewed full passes |
| [tabreport-diff](../tasks/tabreport-diff/public/task.md) | 450 s | 5 of 5 reviewed full passes |
| [sqlite-migrations-core-guided-v8](../tasks/sqlite-migrations-core-guided-v8/public/task.md) | 600 s | 4 of 5 reviewed full passes |
| [git-config-backport-dual-public-tests](../tasks/git-config-backport-dual-public-tests/public/task.md) | 720 s | 5 of 5 under the original review. A [later exception-propagation check](serial-selection.md#what-the-git-reviewer-found) failed on 4 of those 5 submissions |

The eight historical recipe rows retain their original task selection, timing and review qualifications. The two codec rows use the same selected recipe since feasibility is unknown at dispatch. [Workstation recipes](../configs/frontier-practical-recipes-v1.json)

The JavaScript rung was measured separately. It covers the 60-second budget with an authored task. Ten confirmation attempts produced correct code within the ceiling, and seven earned full handoff acceptance. The retired HCAST Markdown task had a published human-effort label. Only the model-time rung carries over.

For the cost of choosing a different recipe on a short task, see the [historical dispatch backtest](dispatch-backtest.md).
