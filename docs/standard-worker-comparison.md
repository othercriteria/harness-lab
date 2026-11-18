# Worker, OpenCode and Aider on the same local model

## Checking a portable evidence packet

All four harnesses implemented the two-file evidence reader and passed
independent source and handoff review. On a single fresh seed, Aider, Worker
and OpenCode finished within three seconds of one another. Upstream mini took
about twice as long. The [reader example](../examples/reviewing-worker-output/README.md)
uses the exact two Python files submitted by Worker. The Maintainer verified
the inventory against the existing example files and added a regression test
that changes one file and removes another.

| Harness | Seconds through verification | Model requests | Generated tokens | Observed workflow |
|---|---:|---:|---:|---|
| Aider | 48.1 | 1 | 2,592 | Both editable files supplied. One edit response, then automatic tests. |
| Worker | 50.1 | 4 | 4,277 | Repository contents preloaded, two file writes, two check receipts and a structured handoff. |
| OpenCode | 50.7 | 8 | 3,032 | Five reads, two writes and five shell calls. A Python check followed an unavailable shell utility. |
| Upstream mini-SWE-agent | 97.0 | 13 | 6,904 | Twenty-three bash calls, including six before the first edit and a final attempt to identify changed files by timestamp. |

The task required a library and command to agree about exact file bytes,
manifest-relative paths, sorted status lists and mixed or empty inventories.
Each submission passed four canonical tests and three external command
probes. A fresh blind reviewer solved the public task before seeing either
grader; the unchanged starter failed both. The model, 32k context, 2k thinking
cap, seed 19116 and 240-second primary ceiling were shared. Model loading and
public-prefix warmup were excluded from the clock. All four first scored
requests had four uncached prompt tokens.

Mini used the pinned upstream 2.4.6 `DefaultAgent`, bundled `mini.yaml`,
bash schema, action parser and observation formatting. The Lab supplied the
local inference transport, command isolation, resource limits and independent
grading. Its terminal echo records submission; Worker additionally binds its
handoff to specific observations. Aider received its usual source-file
selection, and Worker received its repository preload. The results compare
those workflows together. Upstream documentation describes the components
used in the control. [Mini-SWE-agent](https://mini-swe-agent.com/latest/)

The two fresh tasks tell different stories. On issue selection Worker used
14,095 generated tokens, ran nine extra tests and still shared the other
agents' defect. Here its two check calls covered the supplied tests plus a
mixed and empty packet, and every citation checked out. Keep Worker as the
default. A useful next experiment if lengthy verification recurs is to ask
Worker for a single discriminating edge-case check once the public suite
passes. Compare accepted output, time and handoff accuracy on a reserved task
before changing its usual verification behavior.

[Per-run measurements, trace excerpts and artifact identities](../results/standard-workers-evidence-check-001.json)

### Aider history allowance on Tabreport

On the ordered pair, raising the allowance from 2,048 to 8,192 tokens cut
warm time through verification from **185.6 to 156.2 seconds** (15.8%).
The backend received identical first requests and returned identical first
edit text. Both arms then repaired their own regression tests and ended with
identical Python source and test bytes. The default sent three additional
summary requests totaling 41.6 backend seconds. Time through verification
fell by 29.4 seconds; summary duration alone overstates the saving.

The exploratory pair had suggested a much larger gain, from 188.7 to 78.7
seconds. Inspecting the first requests showed that Aider had presented the
source files in different orders. The faster arm got a working patch on its
first edit. The repeat set `PYTHONHASHSEED=0` in both native clients and
compared actual payloads. Prefer 8,192 for this pinned Aider recipe at 32k,
and pin file ordering for future comparisons. One task and one controlled
seed establish a working configuration; longer histories can change the
tradeoff.

## Selecting GitHub issues for a Worker packet

On a fresh in-repo task, each harness added a repeatable `--issue NUMBER`
option to the Maintainer's issue exporter. All three passed six canonical tests
and five external checks. All three also used Python's integer conversion on
the original input. A post-run check found the same defect in all three:
`7` with 4,500 leading zeroes is a valid spelling of an ordinary issue number
under the public brief, but each program failed before looking it up.

| Harness | Task time through verification | What the trace shows |
|---|---:|---|
| OpenCode 1.18.25 | 96.0 s | Reworked a failed scratch probe and checked the 50-issue boundary. Shared packet formatting between both modes. |
| Aider 0.86.1 | 106.5 s | Automatic lint caught a syntax error after the first edit. The second edit passed the public suite. A history summary occupied 21.9 s of backend time. |
| Lab Worker | 166.8 s | Wrote and ran nine scratch tests and cited their output separately from the three public tests. The extra coverage still missed the shared defect. |

Each ran once at seed 19100 with the same Qwen weights, 32k context, 2k thinking
cap and 240-second ceiling. All three finished cleanly and gave supported
handoffs. Strict source review required a repair in every case. The
Maintainer adopted OpenCode's edit, replaced integer conversion with text
normalization, and verified a real export of issues 34 and 35. One earlier
OpenCode launcher error occurred before inference. The comparison uses the
pinned first-screen harness versions. Raw traces live on Skaia.

This result motivated the multi-file evidence task above and the historical
Aider history-allowance comparison. Its five earlier Tabreport summary requests
had used 94.9 s of backend time.

[Issue-selection measurements and provenance](../results/standard-workers-issue-selection-001.json)

## First screen on Markdown and Tabreport

**Retain our Worker, and keep OpenCode as a credible alternative.** All three
systems solved both known development tasks on the same local Qwen backend.
This screen does not support a general claim that our custom agent loop is better.
The Lab's more defensible contribution is qualification, resource control,
independent verification and reviewed delivery.

[Conclusions](../results/standard-workers-conclusions-001.json) ·
[All valid and invalid rows](../results/standard-workers-screen-001.json) ·
[Completion audit](../results/standard-workers-completion-audit-001.json) ·
[Positioning and comparison landscape](positioning-and-comparisons.md).

| Coding harness | Markdown seconds, seeds 18100 / 18101 | Tabreport seconds, seeds 18100 / 18101 | Code checks | Strict full results |
|---|---:|---:|---:|---:|
| Local Harness Lab Worker | 23.6 / 32.4 | 197.6 / 145.3 | 4/4 | 4/4 |
| OpenCode 1.18.25 | 28.9 / 33.4 | 139.1 / 145.1 | 4/4 | 3/4 |
| Aider 0.86.1, adapted non-Git workflow | 39.8 / 40.2 | 208.9 / 143.5 | 4/4 | 4/4 |

Every valid trial passed canonical and external checks, source review, clean
completion and its ceiling (120 s Markdown; 450 s Tabreport). OpenCode's second
Tabreport handoff correctly reported 40 passing tests but incorrectly described
31 existing plus 9 new tests; the files contain 21 existing plus 19 new. Its code
passes; the frozen honest-handoff criterion fails. This is a reporting defect,
not evidence of deliberate deception. No rerun erased it.

Official task time includes preparation, command/native cleanup and verification,
but excludes declared initial-prefix warmup and model loading. All 12 first scored
responses reused their public prefix with only four uncached prompt tokens.
Native warmup is per trial; Worker warmup is per two-trial cell. The ledger retains
those costs and model-load timings separately. Raw four-trial sums are Worker
398.9 s, OpenCode 346.6 s and Aider 432.4 s; OpenCode's sum includes the reporting-failure
row. These are not failure-adjusted utility scores or reliable speed rankings.

There were **17 actual attempts: 12 valid trials plus five operationally invalid
attempts** preserved below. Both tasks were unchanged, previously exposed
development tasks. Two seeds, fixed run order and integration corrections limit
inference. No held-out or broad reliability claim is made.

## Integration failures and prospective corrections

[Original freeze](../configs/standard-workers-screen-v1.json) ·
[V2 logging correction](../configs/standard-workers-screen-v2.json) ·
[V3 Git refresh correction](../configs/standard-workers-screen-v3.json) ·
[V4 Aider new-file adaptation](../configs/standard-workers-screen-v4.json).
Raw frozen bytes/scores remain unchanged; each correction governs later attempts.

Two original OpenCode attempts are **operationally invalid**, not coding failures:
the outer adapter used exclusive file creation for a repeatedly updated usage
ledger. The second response produced a 502; the native client retried the same
request. The first attempt exhausted retries, and the second was deliberately
stopped after diagnosis, with verified cleanup. V2 writes per-request usage/error
receipts. A multi-request control, cancellation control and both replacement
Markdown trials pass. Original bytes and failures remain intact. The two Worker
rows and two one-response Aider rows are retained with their original V1 identity;
the corrected path was never exercised twice in those Aider attempts.

OpenCode Tabreport seed 18101 exposed a second
adapter integration defect: ordinary `git status` rewrote cached index statistics,
which the immutable-metadata import gate rejected. This is Git's documented
[optional index refresh](https://git-scm.com/docs/git-status#_background_refresh).
Only `.git/index` changed; no implementation had been produced. That attempt and
its verification failures remain recorded as operationally invalid. The
[V3 amendment](../configs/standard-workers-screen-v3.json) sets
`GIT_OPTIONAL_LOCKS=0` for native shell commands; repeated status reads pass, while
explicit `git add` remains rejected. Only the invalid seed is replaced; valid rows
retain their original identities. Unstarted Aider moderate trials use V3.

Aider's first moderate pair exposed a third integration defect: its native file
admission calls `git add` for new files even when auto/dirty commits are disabled.
The immutable index prevented patch application before lint/tests. Both native
clients returned 0, illustrating why process exit is not acceptance. Both attempts
remain operationally invalid. The [V4 amendment](../configs/standard-workers-screen-v4.json)
omits automatic staging only in this explicit no-commit screen: new files remain
real workspace/chat files, and Git stays immutable. A scripted control creates a
file, edits an existing file, passes isolated lint/tests and verifies unchanged
Git metadata. Both seeds are replaced; existing-file Markdown rows are unaffected.

## Reproducible tools and useful Worker work

The existing locked nixpkgs supplies OpenCode **1.18.25** and Aider **0.86.1**.
They are now in `flake.nix`; Python 3.13.15 and the Worker's Python dependencies
are unchanged. Package realization used cached Nix outputs. Both version probes
passed in empty, network-isolated namespaces; a real dev-shell probe confirmed
all three versions. The user has resumed in that environment.

Earlier manual downloads of OpenCode 1.19.6 and Aider 0.86.0 were source-inspection
artifacts, not experimental conditions. Source inspection for subsequent adapters
uses the exact Nix package sources; package patches and dependency choices remain
part of the eventual treatment. Current web documentation is not a release pin.

Three small real Worker assignments have been independently reviewed, applied,
and attributed, without outer source repairs:

| Assignment | Dispatch time | Landing commit | Delegate job |
|---|---:|---|---|
| README and Delegate preparation vocabulary | 230 s | `b8d4697` | `fae9695bff1c4e66b9e4afbd19f307eb` |
| Nix comparison packages and description | 60 s | `0b4e2d0` | `0fb781b9f7964faf95f3b932647bb249` |
| Observatory and CLI display labels | 67 s | `044fdda` | `ded7a674dcd74a1fb0476fca965e1002` |

These used explicitly recorded `outer_only_experimental` preparation. There was
no blind benchmark admission or sealed reference. Documentation/display changes
received independent exact-diff and structural review; the Nix candidate also
received actual isolated evaluation against the locked inputs. The Nix brief
supplied package names and versions, and the Worker accurately disclosed that it
could not execute Nix. One small guided success is not broad Nix qualification.
Full reviews/applications are in each job's bulk delegation directory.

## Native transport probes

The preparation controls below used scripted responses, before local model trials. Evidence and
prototype code live under
`/bulk/dlk/local-harness/research/standard-workers-001/`.

- **Aider API smoke:** its packaged CLI completed a request to a compatible local
  mock. With an unknown model alias it selected whole-file edits and temperature 0.
  It attempted remote price metadata retrieval; the isolated namespace prevented
  that and it used fallback data. Subsequent scripted controls qualified explicit model metadata/settings before
  the comparison.
- **OpenCode API smoke:** the first attempt exhausted the prototype's 64-task
  cgroup limit. The preserved retry with a bounded 256-task allowance completed.
  It advertised native editing, search, shell, subagent and web-fetch tools and
  requested streaming output. The probe's 4096 output cap was a fixture choice,
  not a selected comparative budget.
- **Command-boundary prototype:** a read-only transport shim gives the native
  client a private loopback API, forwarding requests to an outer Unix-socket
  broker. The actual command runner and backend client stay outside the
  native namespace. Generated shell work goes through our existing isolated
  Runtime; it receives neither bridge access nor native client state. Native
  configuration, dependencies and selected files are distinct from evaluator
  and outer evidence files.
- **Aider packaging mismatch:** Nix Python's `shell=True` uses an absolute
  Nix-store shell. Replacing `/bin/sh` therefore failed to intercept its test
  execution. A scripted probe caught this (`aider-boundary-smoke-002`; 003 repeated
  the old configuration after preparation failed). No real model-generated code
  ran. An explicit Python entry adapter now routes shell subprocesses and direct
  flake8 calls toward the command runner, while permitting only immutable Git as
  a native subprocess for this non-Git screen. Interactive execution is excluded.
- **Filesystem coherence:** retain Runtime's bounded snapshot transport. Native
  client state lives under `/state`; attempt scratch is shared logically through
  validated snapshot export/import under `/tmp`. Native scope freezing prevents
  concurrent writes during transfer. `scratch-boundary-smoke-003` checks repeated
  reads/writes plus empty-directory creation/removal; `opencode-interface-001`
  confirms OpenCode's actual write → shell → read tools see the same bytes.
- **Actual lint and diff workflow:** the packaged Aider invokes a flake8 executable
  directly, so routing only `python -m flake8` was insufficient. The adapter now
  supports both forms. `aider-qualified-001` uses configured diff edits, receives
  an F821 undefined-name diagnostic, repairs it, passes lint, then passes its
  configured assertion. Two scripted responses, three isolated commands, clean
  completion, independently inspected final source. The earlier blocked lint
  probe is retained, including its repeated repair attempts and deadline.
- **Rejected requests and cleanup:** malformed broker packets, unsafe working
  directories and workspace symlinks are rejected. Socket creation and access to
  client state/bridge/config are denied in command namespaces. A forked sleeping
  descendant is reaped; task deadline and owner cancellation controls close both
  native and command scopes. Cancellation during a command took about 10.6 s to
  finish cleanup. `native-alias-001` has a historical over-broad `unsafe_cleanup`
  label despite verified cleanup; the current adapter separates transport failure.
- **OpenCode extension import finding:** project plugin top-level code executed
  in `opencode-project-config-001` through 003 despite both disable flags being
  present. Run 003 records the flags and an import stack; the precise upstream loader
  path remains unresolved. Read-only masking of project/global configuration and
  extension directories prevents this in 004; ordinary command execution remains
  functional. The marker was scripted, inside the disposable native namespace,
  with no live model or host credentials. Do not infer that `--pure` alone provides
  an isolation boundary. Aider project/global dotenv and settings paths are also
  masked; its poisoned-config control still reaches the intended mock endpoint.
- **Effective native settings:** `opencode-settings-001` and `aider-settings-003`
  emit temperature 0.6, top_p 0.95, the declared seed, 2048 reasoning tokens and
  cache_prompt=true. Aider receives explicit 32k model metadata and uses diff edits
  with its repository map instead of unknown-model fallback. OpenCode requests
  max_tokens 32000 and streaming with usage; Aider requests 32768 without streaming.
  The later live adapter imposed and recorded the remaining sampling controls
  and cumulative budgets at the outer backend boundary before comparison.

The consolidated offline receipt is
`/bulk/dlk/local-harness/research/standard-workers-001/boundary-preparation-receipt-v2.json`.
It records 12 controls plus cancellation and points to the latest hashed prototype
source snapshot. Earlier controls used earlier adapter revisions; later attempts
copy/hash their adapter source. No claim that every control used identical bytes.

Other preserved setup failures include missing musl runtime libraries, a
main-thread requirement in Runtime's signal-safe launcher, and Aider requesting
Git identity writes against immutable fixture metadata. These changed the adapter
or fixture setup; they are not model failures. The native prototype currently
uses a read-only, preinitialized Git view and disables automatic commits for these
non-Git tasks. It does not qualify either agent for our Git ladder tasks.

## Measured conditions and lessons

The frozen native runtime uses bounded outer inference and the existing guarded
GPU lifecycle. It applies common sampling, a 2048 reasoning cap with the established
deadline heuristic, 32768 per-request and 65536 cumulative completion tokens, 64 model
requests and 128 isolated command calls. Native prompts, editing interfaces and
context recovery remain part of each treatment. OpenCode has explicit 32k input
capacity and 8192 reserved tokens: omitting the input limit with a large output
allowance would make its automatic compaction trigger prematurely.

The outer transport buffers one backend JSON completion and converts it to SSE
when OpenCode requests streaming; this does not offer incremental token display.
Aider's pinned client/linter use Python 3.14; generated commands and evaluation use
our common Python 3.13 runtime. Configuration/extension masks, immutable Git metadata
and command transport adaptation are explicit experimental restrictions. This is
not qualification for unrestricted installations or the Git task ladder.

The backend, sampler and reasoning ceiling match across conditions. Prompts,
context selection, editing, output headroom and recovery remain treatment-specific:
Worker clamps each response to its remaining context headroom, while the native
adapter enforces the common 32768-token response ceiling. No observed response
approached that ceiling. Target and draft were fully offloaded in the recorded
server logs (65/65 and 6/6 layers).

Aider's automatic lint/test feedback successfully repaired a syntax error and
incorrect expectations in its own added tests. Generated tests still need review:
for example, one test named for output-file success only exercised errors. Similar
incorrect expectations arose under other harnesses; the unchanged canonical tests
and external CLI checks remained separate authorities.

The pinned Aider model code computes chat-history allowance as input capacity/16,
clamped to 1024–8192 tokens. With this metadata that is 2048. Its first Tabreport
trial used three coding/repair responses and three summary responses; the summaries
alone took 61.4 s of the 208.9 s task time. Across the two moderate trials, five summary
requests took 94.9 s. The [next harness comparison](https://github.com/othercriteria/local-harness-lab/issues/16) tracks a matched history-allowance experiment. OpenCode also compacted on both moderate trials;
its two summary requests totaled 52.8 s. The native agents used this same resident
model for summaries; there was no cheap concurrent helper backend.

Retain the current Worker for supervised work because its existing broader ladder,
structured evidence and Delegate integration remain useful. Keep OpenCode as the
first alternative for a future fresh-task comparison; these timings justify taking
it seriously without justifying a migration. Keep Aider as an editing baseline;
its automated feedback loop worked, with configuration-sensitive overhead.

For a technically curious visitor, show a useful reviewed contribution, a preserved
failure, and a matched standard-agent comparison. Attribute mini-SWE-agent and the
other upstream components. Defer a new general framework, native Git qualification
and a large reliability sweep. The [portable evidence issue](https://github.com/othercriteria/local-harness-lab/issues/18) tracks export and Harbor/ATIF coverage.

Observatory now discovers native backend requests and isolated command receipts,
without double-counting the native relay's copy of each model request. Raw native
logs and actual backend settings remain inspectable. Existing detailed Worker cost
classification is not applied to native traces with different event semantics.
The display update passes 49 focused Python checks, offline UI regressions and
live loopback checks. Bound outer receipts distinguish full acceptance, pending
review and operational invalidity without rewriting raw test scores. It does
not alter the frozen comparison runtimes. Source/handoff review receipts and a
filtered source diff accompany all valid trials; raw diffs retain fixture
Git and native-client bookkeeping for completeness.

Research owners and launch plans live under
`/bulk/dlk/local-harness/research/standard-workers-001/`; freezes are
`/bulk/dlk/local-harness/freezes/standard-workers-screen-v1` through `-v4`.
Per-cell launch plans bind scripts, fixtures, dependencies, packages and settings.
`run_cell.py` refuses an existing run directory. Reproduction requires a fresh run
identity, preserving the old evidence. Current GPU owner and restoration pointer
are in the [handoff](outer-handoff.md).

## Reproduction and closure

On this workstation, `research/standard-workers-001/screen-launches-v*.json` in
the bulk root records exact argv and source-freeze identity. `run_cell.py` validates
the frozen source/dependency hashes and refuses an existing run directory.
`collect_screen.py` records the retention/replacement rules; `closeout.py` checks
summary-bound reviews, unchanged public tests, effective requests, cache reuse and
lifecycle closure. Their outputs are the linked ledger and completion audit.

A deliberate replay needs a **fresh run identity and current session restoration
record**: copy the relevant cell into a new launch plan, change only its output/run
paths, keep the intended freeze/dependency identity, establish current session GPU
ownership, then run it through the recorded wrapper chain. Never reuse session 030's
restoration plan for a later session. Realize the locked flake and Python dependencies
first; metadata weight checks rely on the previously verified artifact. Reproducing
on another machine requires packaging the bulk sources/evidence and relocating
paths; that portable release has not been built or claimed here.

All nine launched GPU cells have closed clients/backends and verified scope cleanup.
Session 030's `restoration-verification.json` confirms the original `gpu-voice` and
`ollama-background` state was restored. There is no active comparison owner and
no further flake/direnv restart required. The interim ledger is historical; use the
completed ledger above.
