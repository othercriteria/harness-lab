# Worker, Aider and OpenCode on the same local model

The Lab ran two seeds on each of two known development tasks with three coding harnesses. All used the same local Qwen backend. One task repaired a Markdown library and the other changed a Python tabular reporting tool. Task time includes time spent by the harness during the attempt. The ceilings were 120 and 450 seconds.

| Coding harness | Markdown seconds, seeds 18100 / 18101 | Tabreport seconds, seeds 18100 / 18101 | Code checks | Strict full results |
|---|---:|---:|---:|---:|
| Local Harness Lab Worker | 23.6 / 32.4 | 197.6 / 145.3 | 4/4 | 4/4 |
| OpenCode 1.18.25 | 28.9 / 33.4 | 139.1 / 145.1 | 4/4 | 3/4 |
| Aider 0.86.1, adapted non-Git workflow | 39.8 / 40.2 | 208.9 / 143.5 | 4/4 | 4/4 |

Five earlier attempts encountered integration problems and were excluded from the 12 valid trials. The second OpenCode Tabreport run passed code checks but misstated how many tests it added. The review therefore rejected its handoff. This small sample supports comparison on these tasks and seeds. The Markdown task is retired from this distribution. [Recorded comparison and qualifications](../results/standard-workers-conclusions-001.json)
