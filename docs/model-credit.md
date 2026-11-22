# Crediting models in Git history

When a model writes code, tests or prose that lands, record its identity and contribution in the receiving repository. Use the same credit on the topic commit, in the PR and on the commit that enters the default branch. Start with new work. Existing commits retain their original messages.

## What goes in the commit

Use one `Model-Author` trailer per contributing model. The first literal ` | ` separates its identity from a one-line description of the part that survived review. For a local Worker, read the target model and variant from the run profile and retain the frozen recipe pointer. For a hosted author, use the provider and the release identifier reported for that turn. If the runner exposes only a family or product, give that name and say “release unknown.” Record reasoning effort separately if relevant.

Keep the Git author and committer identities set by the contributor's workflow. Name substantive human repairs in the body. Use `Co-authored-by: Name <email>` for an additional author with an appropriate, documented identity and an address approved for that use. The model trailer works with or without such an identity. A model name or service account alone supplies no email address. [GitHub co-author guidance](https://docs.github.com/en/pull-requests/how-tos/commit-changes/creating-a-commit-with-multiple-authors)

Point to evidence with `Delegate-Review` for a Worker job, or `Model-Evidence` for a hosted-only change. A path is relative to the receiving repository at the landing commit. Use a commit permalink for a file in another repository. Keep the six Worker trailers, including job, package and recipe. [Worker landing checklist](operations.md#attribution-for-landed-worker-contributions)

In the PR, one sentence per author plus an evidence link usually suffices. In a JSON receipt, `model_authors` is an array of objects with `model` and `contribution` strings matching the trailers. Record the identity source next to them. For Worker, include the recipe, its frozen profile or versioned registry pointer, and the target weight digest when available. Describe verification, application and any withheld reference separately. If part of a reference solution actually ships, credit its author for that part.

## Three examples

**Worker patch applied as submitted.** On Footsteps #111, Worker fixed event ownership and wrote both regressions. The Maintainer reproduced the failures, verified the patch and applied it as submitted. A hosted reference stayed sealed. The run profile records the local Qwen variant below. The historical PR and topic commit predate the convention. A new PR could say “Qwen3.8-27B (RANA tensor precision layout, Q4_K_M) wrote the event snapshot and both regression tests. The Maintainer verified and applied the patch as submitted.” Add the review link and use this trailer alongside the six delegation trailers. [Topic commit](https://github.com/othercriteria/footsteps/commit/f1fe212f08c55a6b77632573fb114250d0f3b4be) · [PR and review](https://github.com/othercriteria/footsteps/pull/111) · [Recipe registry at a fixed revision](https://github.com/othercriteria/harness-lab/blob/8b396fed749dad23a874f9a08bf52ac9d6048234/configs/delegate-recipes-v1.json)

```text
Model-Author: Qwen3.8-27B (RANA tensor precision layout, Q4_K_M) | event snapshot and both regression tests
```

**Worker patch with substantive repairs.** In the verifier coverage landing, the local model supplied the fixtures, recording evaluator and outcome checks. The hosted Maintainer consolidated seven tests into five, extended the fixture and registered the suite in CI. The public receipt identifies the local target and describes the repairs. It doesn't record the hosted release. A message composed from that evidence could include the following lines in its final trailer block. [Landing commit](https://github.com/othercriteria/harness-lab/commit/8b396fed749dad23a874f9a08bf52ac9d6048234) · [Review receipt](../results/worker-delegate-verification-tests-001.json)

```text
Model-Author: Qwen3.8-27B (RANA tensor precision layout, Q4_K_M) | verifier fixtures, recording evaluator and outcome tests
Model-Author: hosted Maintainer (release unknown) | consolidated tests, unchanged-input case and portable CI registration
Delegate-Repairs: consolidated tests, removed wording assertions, included an unchanged file
```

**Hosted author.** The current Codex turn reports `gpt-6.2-astra`. The user selected the issue and asked to start using the convention. The hosted model wrote this guide and the operator instructions. The same two lines work in the topic and squash commits. [Landing receipt](../results/model-credit-pilot-001.json)

```text
Model-Author: OpenAI gpt-6.2-astra | model credit guide, operator instructions and pilot receipt
Model-Evidence: results/model-credit-pilot-001.json
```

## Check what landed

On a direct commit, inspect the landed SHA. With a merge commit, the topic commit is reachable on the default branch even when the merge message contains only the PR title. A squash creates a new commit with its own message. Before merging, put the credit for everything retained across the PR in the **final squash message**, including the evidence and Worker trailers. The GitHub merge dialog accepts edits, and `gh pr merge --squash --body-file <file>` takes the prepared body. Repository defaults vary. [GitHub squash settings](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/configuring-commit-squashing-for-pull-requests)

After fetching the receiving repository's default branch, use the credited commit's SHA in these commands. Check that the scoped authors and evidence agree with the accepted diff and that the receipt opens at that revision.

```sh
git merge-base --is-ancestor "$sha" origin/main
git log -1 "$sha"
git show -s --format=%B "$sha" | git interpret-trailers --parse
```

For a first look at how tools have contributed over time, run `git log --grep='^Model-Author:'` and read the scopes. A repaired patch can credit two models on the same commit. Counts describe recorded landings and depend on when a repository adopted the convention.
