# When should Worker hand off?

The last useful action differed even between two attempts on the same assignment. One documentation reviewer wrote the correct verdict with 4.7 seconds left and then validated the JSON. It timed out without a handoff. The other had 29.7 seconds left with a valid JSON report on disk. Both blind readers identified the same unsupported finding in that report. Worker validated its shape and submitted it unchanged. The Maintainer rejected the verdict.

This archive study supports giving Worker a realistic estimate of what a handoff costs. It gives little support for the harness deciding when the work is ready.

## How the comparison worked

We froze the sample and decision points before giving the packets to two fresh hosted readers. The ten attempts comprise all four recorded stage timeouts on the incumbent Worker recipe, the other attempts needed to cover two packages with both timeout and clean outcomes, and two clean incumbent controls from other packages. We selected the controls by time remaining at submission, without consulting acceptance. Seven attempts used the named incumbent recipe. Three older runs used the same model on one frozen package. Five attempts timed out and five finished cleanly by design.

At the first ordinary request with at most 45 seconds remaining, one reader saw the messages Worker had at that point, including its public task, observations, and any checkpoint material still in context. A different reader did the same for 12 seconds. Each saw the available tool names and clock, under shuffled aliases, and chose **submit**, **run one specific check**, or **continue implementation**. Submission could disclose unfinished work. Neither reader saw the response to that request, subsequent actions, or outer review. The Maintainer knew some historical outcomes and joined the sealed decisions to the traces afterward.

| Decision points | Submit | One check | Implement |
| --- | ---: | ---: | ---: |
| Actually reached 45 seconds or less | 1 | 0 | 7 |
| Actually reached 12 seconds or less | 3 | 1 | 1 |
| Last eligible request when the 45-second threshold was never reached | 2 | 0 | 0 |
| Last eligible request when the 12-second threshold was never reached | 4 | 0 | 1 |

Two early finishes contributed the same request to both fallback rows. There were 20 readings of 18 distinct points. The five attempts that reached the 12-second window all timed out. The readers differed between windows, so the counts cannot isolate the effect of the clock. These selected cases also cannot estimate a deployment failure rate.

## What happened next

| Assignment | What the blind reading and subsequent trace tell us |
| --- | --- |
| Footsteps keyboard navigation | At 41.9 seconds the reader wanted implementation to continue. Worker used two requests to add and correct the browser test. With 16.4 seconds left it compiled the test, ran five Python viewer tests and checked the export. At 11.7 seconds the reader wanted the new browser test attempted. Worker instead inspected Git state, got empty output, and lost the final request to the deadline. Outer review accepted the recovered patch and qualified its keyboard coverage. The earlier failed executable lookup had established only that the lookup command was unavailable. |
| Visitor README memo | Both readers identified the word-limit miss and proposed a substantial cut. Worker kept editing. Counts of 411 and then 409 established that the memo still missed the under-400 requirement. The Maintainer accepted its advice with that qualification. |
| Documentation review, same package, two seeds | The timeout produced a usable correct verdict after extensive rereading. The clean finish preserved a wrong verdict. A check of JSON structure added evidence about the file in both cases and could not adjudicate the reviewer's substantive finding. |
| Compact diff hunks | Late submission could have communicated the incomplete state. The helper still emitted a corrupt patch and the requested test file was absent. Independent verification rejected it. |
| Finite-number checks, same package, three seeds | In the timeout, late probes and edits reduced six test failures and one error to one error. Even after the late reader proposed partial submission, the next check usefully exposed the remaining error. Its shell pipeline returned zero. Two siblings handed off with ample time and passing focused tests. Both shared a test-stub integration problem. One was accepted after a separate repair and the other was rejected. |
| CPU walkthrough README | At 42.7 seconds the reader identified the checkout-link defect later repaired by the Maintainer. Worker repeated structural checks. Its first handoff exceeded a field limit by four bytes. The late reader recommended a shorter retry, which is how Worker finished. |
| Observatory comparison badges | At 42.4 seconds a working JavaScript runtime remained unavailable and the Python mirror had already run. Both readers favored qualified submission. Worker repeated the mirror and located expected strings before handing off with the limitation. Independent JavaScript verification accepted both files unchanged. |

Five attempts still changed the bytes of their eventual deliverables after the earlier cut. All five were deadline cases. Of the three late **submit** recommendations inside 12 seconds, two explicitly offered unfinished work and one offered the correct documentation review. A timely, candid account would have helped the Maintainer in all three. Only the documentation case had a usable result on disk.

## The time a handoff takes

Across **all 64 clean incumbent submissions** in the archive, the final model request took a median of **9.3 seconds**, a 90th percentile of **16.2 seconds**, and a range of **4.1–21.6 seconds**. All 64 had a single submitted finish call in their final response. Seven started with at most 45 seconds left. None started with 12 seconds or less. These are observed completed request times, excluding outer verification and cleanup. Response lengths vary and unfinished requests supply no comparable payload. The recipe's 15-second reserve reduces the reasoning allowance as time runs low. It does not reserve a separate turn for submission.

This changes how to read the Footsteps recommendation. A two-second browser command still requires a model turn to issue it and another to submit. With 11.7 seconds remaining, that sequence had little demonstrated margin. The trace supports dropping the empty Git inspection. It leaves open whether immediate submission, or one more check followed by submission, would actually have finished. The unanswered last request does not tell us what tool Worker intended to call.

## A small experiment worth running

We subsequently ran the paired pilot. The design below records the proposal made before dispatch. [Pilot results](#what-happened-when-worker-saw-the-timing)

Test a single piece of information on the incumbent recipe. At the first ordinary request with roughly 30–45 seconds left, show the measured median and 90th percentile for generating a final handoff. Let Worker choose whether a remaining edit or check would change the result or the claims it can make. The present prompt already asks it to disclose gaps and avoid duplicate checks. The new information is the cost of its next decision. Keep the hard deadline, tool choices, and verifier identical. If a request jumps across the window, record that the cue never appeared.

Use paired seeds on fresh internal packages with two situations represented: work already checked as far as the available tools allow, and a concrete outstanding defect a late operation can still repair or expose. Compare artifact acceptance, accuracy of the handoff, and clean completion separately. Record missed repairs, useful checks displaced, terminal requests without a response, and any Maintainer recovery work. Count every assigned attempt, including missed cues. A gain confined to clean receipts while artifacts or claims get worse is a reason to drop the change. The Footsteps, memo, and diff-hunk cases are diagnostic examples for designing the comparison.

I would attach this probe to the next batch of internal Worker assignments. At the study cutoff, the exact recipe had 69 terminal trial summaries. The original inventory counted 68 jobs with collected results and missed one unclean attempt whose artifact collection failed. The four stage deadlines and 64 clean final requests are unchanged. Even eliminating every one would recover at most four missing handoffs in that archive, and two of those four artifacts still missed requirements or failed verification. The immediate payoff is learning whether a cheap cue helps without displacing a useful final edit.

The [case index](../results/worker-handoff-decisions-001.json) records the exact job, package, seed, request and packet hashes, sealed choices, observed next tools and independent outcome. Its file comparison matches the bytes of terminal changed paths against the archived workspace before a request. That establishes when those bytes were present. Checks can add valuable evidence afterward, and incorrect bytes may persist all the way to review. Full packets stay in the local trace archive.

## What happened when Worker saw the timing

Eight live Worker jobs tested the cue in four same-seed pairs. Each pair used the same starter, brief, 75-second Worker budget, 20-second verification reserve and model settings. Arm order was balanced. One case asked for a review of an already-correct fence checker. The other had a one-operator defect that suppressed diagnostics after a longer closing fence. Both required a short report citing a real example. Fresh blind readers independently solved both cases, and the isolated checker accepted their sealed solutions.

At the first ordinary request with 30–45 seconds remaining, the treatment added this message once. We checked the actual request bytes for delivery.

> Historical timing on this setup: across 64 completed submissions, the final model request had a median duration of 9.3 seconds and a 90th percentile of 16.2 seconds. These figures describe completed requests only. Your next request may take a different amount of time.

| Outcome | Usual clock | Clock plus historical timing |
| --- | ---: | ---: |
| Assigned | 4 | 4 |
| Had a request inside the window | 2 | 2 |
| Actually saw the cue | 0 | 2 |
| Passed isolated fence behavior and report-presence checks | 2 | 3 |
| Accepted original artifact after review | 0 | 0 |
| Clean final handoff | 0 | 0 |

One control left four scratch fixtures in the submitted workspace. Export rejected it before the independent check, so the usual-clock arm had two passes, one failure and one unavailable check. All assigned attempts stay in the table. The first model request alone took 24.3–27.4 seconds. At seed 19610 all four jobs crossed from above 45 to below 30 seconds between requests. The extra green check in the treatment arm came from a Worker that **never saw the message**. Its report described a repair to an already-correct starter and cited a diagnostic the probe did not produce.

The two exposures both occurred at seed 19611, with about 45 seconds left.

- **Intact source.** After receiving the cue, Worker continued probing. It resolved a scratch-path problem and obtained an actual line 5 diagnostic. The next request started with 1.6 seconds left. The source remained intact, but Worker left no review file or handoff. Its matched control also left no review file and was the attempt refused at export.
- **Defective source.** Worker made exactly the required one-line repair. Its primary example reported line 1 before the fix and lines 1 and 5 afterward. It then reported an additional fixture had emitted a diagnostic despite an explicit check finding no match. It saved the report and timed out. The matched control also fixed the defect and timed out, but it made an additional change to indented openers that the task did not call for.

No recorded response contained a finish call. An unanswered terminal request reveals no intended tool. We cannot tell how the cue affected either exposed Worker's choice, or whether an individual finish would have fit. The report files and observable actions supply no evidence that Worker treated the historical percentile as a guarantee.

The brief contributed a second difficulty. Both independent readers interpreted indented openers as outside the assignment. Several Workers treated the words *in scope are flush-left* as a reason to change them. After the first four jobs missed the cue window, we prepared a separate four-job delivery check with a wider window and an explicit scope clarification. Its predeclared trigger was a task state with zero exposures in the original panel. Both states received the original cue, so no follow-up jobs were dispatched.

The cue remains experimental. Every control timed out, and the run showed no clean handoff gain from adding the timing message. A more informative repeat would use an internal job where the incumbent sometimes finishes cleanly and sometimes leaves a useful artifact without a handoff. The implementation was confined to frozen campaign packages. No default changed. The [case-level pilot results](../results/handoff-latency-cue-001.json) include the contract, package identities, per-request clock readings, delivered cues, and independent decisions.
