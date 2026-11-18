# Local Harness Lab positioning and comparisons

Working naming proposal and demonstration planning, 2026-11-17.

**Local Harness Lab is a single-workstation testbed for qualifying local coding
agents and using them for bounded, supervised repository work.** Its strongest
public artifact is an inspectable systems case study: which combinations of
model, inference settings, tools, context policy and verification produce useful
work under a fixed hardware budget, and what supervision that work still needs.

A demonstration should establish this contribution before showing a successful
patch. Local inference, delegation, sandboxing, tests, context recovery and trace
viewers all have substantial precedents. The comparative advantage of this
particular implementation remains an empirical question.

External capabilities below come from official documentation or project READMEs
consulted on this date. OpenCode's current documentation describes V2. These are
architecture and workflow comparisons, not measurements on our ladder or security
audits of other implementations. A future run must pin an actual release and
configuration rather than treating these moving documentation pages as a freeze.

## Comparison landscape

The relevant alternatives occupy several layers. A coding assistant competes
with the Worker and the overall user workflow; an evaluation framework competes
with Trials and Observatory. Some components could become dependencies or
interoperate rather than competing for the same role.

| Layer | Relevant alternatives | Question the demonstration should answer |
|---|---|---|
| Coding and delegated work | Aider, OpenCode, Amp | Why use this workflow rather than a mature coding tool? |
| Agent implementation | mini-SWE-agent, OpenHands SDK | What was reused, and what did the adaptations buy? |
| Evaluation and task environments | Harbor / Terminal-Bench, Inspect | Why maintain a bespoke experimental runner and task ladder? |
| Evidence inspection | Inspect View, agent-native transcripts | What does Observatory make easier to verify? |
| Local delegation bridges | m-555/Apprentice, local-vibes | What goes beyond connecting a hosted supervisor to local inference? |
| Hardware-aware local model evaluation | Local Agent Bench | What does repository work reveal beyond controlled tool-call exercises? |

### Aider

Aider is a close practical baseline for file editing with a local model. It
supports Ollama and OpenAI-compatible endpoints, so local execution alone does
not distinguish the Worker. Its repository map supplies selected structural
context; automatic lint/test feedback helps repair edits; its CLI can perform
one scripted assignment and exit. These are relevant alternatives to our curated
input selection and custom editing loop. [Local models](https://aider.chat/docs/llms/ollama.html),
[compatible endpoints](https://aider.chat/docs/llms/openai-compat.html),
[repository map](https://aider.chat/docs/repomap.html),
[linting and testing](https://aider.chat/docs/usage/lint-test.html),
[scripting](https://aider.chat/docs/scripting.html).

Architect mode separates solution reasoning from edit production, potentially
using different models. On one GPU, model residency and switching costs would
need measurement; the design itself is an existing precedent. Aider also has
its own code-editing benchmarks, so it would be wrong to portray it as lacking
an evaluation culture. Its benchmark scores are not comparable to our customized
repository tasks without matched experiments. [Chat modes](https://aider.chat/docs/usage/modes.html),
[benchmark methodology](https://aider.chat/docs/benchmarks.html).

**Comparison to make:** the current Worker versus a sensible, pinned Aider
configuration on the same local backend and public task. Give Aider its native
editing interface. Judge submitted artifacts through the same outer acceptance
process; do not demand our custom finish tool from it.

### OpenCode

OpenCode is the strongest first candidate for the broader local-agent baseline.
It exposes a coding agent through terminal, desktop and web interfaces; supports
local runtimes and custom compatible providers; and has configurable agent
profiles, permissions and compaction. It also offers noninteractive `opencode run`.
These features substantially overlap our agent-facing machinery. [Overview](https://opencode.ai/docs/),
[providers](https://opencode.ai/docs/providers/),
[agents](https://opencode.ai/docs/agents/),
[permissions](https://opencode.ai/docs/permissions/),
[compaction](https://opencode.ai/docs/compaction/),
[CLI](https://opencode.ai/docs/cli/).

This is a reason to test the Worker as a replaceable component. We can retain
experimental controls, isolated grading and reviewed application even if a
standard agent becomes the preferred solver. Permission prompts and rules are a
different enforcement layer from operating-system process/filesystem isolation;
a fair security comparison would specify both tools' actual deployment boundaries.
The documentation alone does not establish that one deployment is safer.

**Comparison to make:** identical local weights, backend and hardware, with
matched effective inference settings where supported. Record native prompts,
tools, compaction, context accounting and defaults as part of the treatment.
OpenCode's advertised custom-endpoint support is not yet proof that every current
reasoning-budget or cache setting reaches our backend unchanged.

### Amp

Amp is an important user-experience and complete-system reference. Its documented
model-specific agents, focused Task subagents, persistent threads, CLI automation
and managed development environments illustrate the experience an outside reader
may expect. Ordinary Task subagents currently use the parent's model and effort;
custom plugins can define different agents. [Introduction](https://ampcode.com/docs),
[models and subagents](https://ampcode.com/docs/models-and-subagents),
[execute mode](https://ampcode.com/docs/cli/execute-mode).

The deployment distinction matters. Amp documents custom provider connections,
but model requests originate from Amp's servers. Its self-hosted orbs run tools
on the user's infrastructure while sending tool outputs to Amp; self-hosting an
orb is not the same claim as keeping the agent loop and inference entirely on
this workstation. [Model routing](https://ampcode.com/docs/customize/model-routing),
[self-hosted orbs](https://ampcode.com/docs/orbs/self-hosted#what-leaves-your-network).

**Comparison to make:** eventual complete-workflow quality, elapsed time and
review effort. A default Amp run would mix model, serving and harness effects,
so it should not be presented as an isolated harness comparison. For now it is a
workflow reference; no account integration, external run or network exposure is
needed to establish that role.

### Research and infrastructure comparators

**mini-SWE-agent is a dependency as well as a baseline.** The repository pins
2.4.6 and imports its `DefaultAgent`; the local model/environment adapters and
additional tools sit around it. Upstream already provides a minimal agent,
sandbox environment integrations and recorded trajectories with an inspector.
Credit that lineage visibly. [Upstream](https://mini-swe-agent.com/latest/),
[trajectory format](https://mini-swe-agent.com/latest/usage/output_files/),
[local dependency](../pyproject.toml), [adapter](../scripts/coding_agent.py).

**OpenHands SDK** is a broader alternative for building programmable coding
agents. Its documented Python/REST interfaces, execution tools, remote agent
server and context compression overlap several layers here. That makes it a
credible reuse option if the project later needs a general SDK; it is not a
reason to migrate before measuring a specific benefit. [SDK](https://docs.openhands.dev/sdk).

**Harbor** directly overlaps the experiment runner: sandboxed tasks, agent
integrations, verifiers, results and a trajectory interchange format. It already
integrates Aider, OpenCode and mini-SWE-agent, and supports a separate verifier
environment. Separation of solver and verifier is therefore not a novelty claim.
Task and trajectory export are worth assessing before inventing a public format.
[Framework](https://docs.harborframework.com/),
[agents](https://docs.harborframework.com/agents/pre-integrated-agents),
[separate verifier](https://docs.harborframework.com/tasks/separate-verifier),
[ATIF](https://docs.harborframework.com/agents/atif).

**Inspect and Inspect View** overlap evaluation and observability. Inspect has
agents, scorers and sandbox integrations; its viewer exposes messages, scoring
and metadata and can bundle logs for standalone viewing. Observatory's potential
value is the way it joins hardware/lifecycle evidence, experimental conditions,
model claims, checks, outer acceptance and application—not merely displaying a
tool-call timeline. A small public evidence export may matter more than further
visual polish. [Inspect](https://inspect.aisi.org.uk/),
[viewer and bundles](https://inspect.aisi.org.uk/log-viewer).

### Especially close smaller projects

The README for **m-555/Apprentice** describes a strong orchestrator delegating to
local or hosted models, mechanical verification, correction and retrieval of
prior lessons. Its current version uses OpenCode; it also describes isolated
build copies and verification limits. This is a close conceptual comparator,
not just a naming collision. Its advertised behavior has not been independently
validated here. [Apprentice](https://github.com/m-555/Apprentice).

**local-vibes** provides an MCP delegation tool, a local agent loop, configurable
backend and concurrency, and returned summaries/change reports. Its README's
sandbox and concurrency claims are not a substitute for a threat-model audit.
Its existence nevertheless rules out treating a local delegate bridge as a
novel architecture. [local-vibes](https://github.com/OpenSourceWTF/local-vibes).

**Local Agent Bench** documents a hardware-aware benchmark using deterministic
mock tools. Its 100 tasks simulate assistant work; the tools do not send real
email or modify real files. This is adjacent empirical work with a different
workload: our tasks exercise executable repository changes, branch integration,
regression checks and supervised delivery. Neither score substitutes for the
other. [Methodology](https://localagentbench.com/methodology/).

## Positioning supported by the current evidence

The useful question is: **What repository work can a local model complete on
this workstation, under which recipe and deadline, and what evidence and review
are needed before its output is accepted?**

The public contribution can combine four things already present:

- A sequence of controlled engineering investigations tied to exact artifacts,
  including useful negative findings. The [scope experiment](scoped-continuations-experiment.md)
  is a recent example; it tests an attractive mechanism and records why it stays
  disabled.
- Hardware-aware recipe qualification extending beyond decoding speed to
  bounded task outcomes, context/reasoning costs and session-wide GPU ownership.
- A supervised repository workflow with selected input snapshots, declared edits,
  isolated execution/checks and reviewed application. The [preparation guide](delegate-preparation.md)
  makes the outer work explicit.
- Evidence that separates model completion, recorded execution, tested behavior,
  semantic acceptance and actual application. [Execution receipts](handoff-receipts.md)
  and the delegated-job view expose these distinctions.

This is a systems case study and reusable testbed with a working apprentice
workflow. It does not currently establish a better general coding assistant,
a cheaper total workflow, or novel individual mechanisms. The full workflow
includes a hosted outer maintainer and strong-model review; only the local worker
path is self-hosted. Our wall-clock task ceilings are not measured human task
horizons. Existing tests and red-team controls support specific containment
claims, while [scoring-integrity and application limits](isolation.md#remaining-limits)
remain material.

For calibration, the latest common nine-assignment development screen had seven
full Qwen results. That supports a supervised demonstration with preserved
failures; it is not an independently held-out reliability estimate. Extensive
outer effort helped construct and tune the ladder. A public account should show
that contribution rather than attributing the whole result to autonomous local
inference. [Qualification results](../results/delegate-model-characterization-conclusions-001.json).

## Proposed names

Use **Local Harness Lab** for the umbrella and **local-harness** as the existing
technical identifier. It is descriptive, preserves continuity, and fits both
experimentation and practical use. The subtitle can be *Local coding agents under
measured resource and verification constraints*. This proposal changes vocabulary,
not repository paths, CLI names or historical identifiers.

Avoid a standalone **Apprentice** brand because a directly related project already
uses it. **Workcell** also has closely related agent-workspace uses. Keep
*apprentice* as the familiar role description. The naming check is sufficient to
avoid those obvious collisions; it does not establish exclusive availability of
a public name. [Apprentice](https://github.com/m-555/Apprentice),
[Workcell](https://workcell.dev/).

| Name in explanations | Meaning | Current implementation |
|---|---|---|
| **Local Harness Lab** | Whole repository, evidence and experimental method | This repository; sibling inference investigation remains separately credited |
| **Worker** | Inner coding/review agent, using a selected local model | mini-SWE-agent plus `coding_agent.py`, tool and recovery adapters |
| **Trials** | Controlled task execution and campaign measurements | `run_trial.py`, `serve_trial.py`, task fixtures and frozen campaign plans |
| **Delegate** | Durable packaging, dispatch, result collection and reviewed application for real repository jobs | `delegate_package.py`, `delegate_job.py`, `delegate_artifacts.py`, `delegate_apply.py` |
| **Verifier** | Separate canonical/behavioral/delegated checks | `verify*.py`, `delegate_verify.py`; semantic outer review remains distinct |
| **Observatory** | Read-only evidence and run/job viewer | `observe.py`, `observe_jobs.py`, web UI |
| **Recipes** | Pinned model, backend, harness, context/reasoning and budget choices | Versioned configuration files and `model_registry.py` |
| **Maintainer** | Trusted human/hosted-agent role preparing work, operating the host and reviewing results | Current outer workflow; not an autonomous local component |

Use qualified forms such as **Local Harness Lab Worker** only when comparing
across projects. These are component labels, not promises of separately packaged
products. In particular, Delegate's current public surface is a CLI/Python
interface, not an implemented MCP service. A model name identifies weights; it
does not name the Worker or the whole system.

## Changes to the demonstration plan

My earlier recommendation moved too quickly to assembling a walkthrough. The
comparison changes the order of work:

1. **Choose the claim and audience.** Lead with a systems-engineering case study
   for engineers evaluating local agents. A user seeking the quickest route to
   an everyday coding assistant should also be pointed toward the established
   tools. State why each custom layer exists and what would make us replace it.
2. **Run a small standard-harness screen before comparative promotion.** Prefer
   OpenCode first, then Aider, on the same resident Qwen recipe. One short edit
   and one moderate repository task, with two seeds per condition, would give
   twelve total attempts across our Worker and the two alternatives. This is a
   proposed compatibility/friction screen, not a reliability competition. Stop
   or narrow it if safe packaging costs exceed the information value.
3. **Use common outcomes with native interfaces.** Match public task semantics,
   starting state, backend and total budget; preserve each agent's native tools.
   Separate cold/warm timing and record effective reasoning/context parameters.
   Evaluate exported artifacts with common checks and outer review, recording
   missing or incomparable handoff evidence. Task briefs that mention our custom
   tools need neutral revisions and the usual blind admission before comparison.
   Reserve fresh tasks before making comparative quality claims.
4. **Compare complete workflows separately.** An eventual Amp comparison would
   answer a different question, including its chosen models, serving and review
   burden. Keep model and harness attribution separate. Measure preparation and
   acceptance effort in our own workflow before calling delegation economical.
5. **Build the evidence path around the decision.** Show one useful contribution,
   one rejection/repair, and one controlled engineering choice. Attribute upstream
   components and outer corrections. Assess a minimal portable evidence bundle
   and Harbor/ATIF compatibility before adding a new public trace schema or more
   Observatory features.

The screen may favor a standard Worker implementation. That would strengthen the
Lab's value as a qualification and supervision system while reducing maintenance
of a custom inner loop. If the current Worker wins selected cases, retain the
measured scope of that result. If setup and review dominate, prioritize those
costs over another model or context feature.

No external product was installed or benchmarked during this step. No GPU workload,
service, runtime configuration or public repository was changed. Naming and the
next experimental campaign remain proposals for discussion.
