# Separate self-path identity from the retained OS image

The new, separately frozen Windows dual-identity census passes its two bounded engineering controls. It distinguishes a worker's self-reported `sys.executable` from the executable image obtained through its retained OS process handle. This resolves the new declaration's identity contract; the earlier frozen census remains rejected and the failed training and scientific results remain unchanged.

The [protocol and reproduction guide](../fixtures/dual-identity-census/README.md), [raw result](../results/dual-identity-census/report.json), [result summary](../results/dual-identity-census/report.md) and [independent saved-result review](../results/dual-identity-census/independent-result-review.json) are public. The tooling uses the Python standard library. Its portable auditor checks saved evidence without launching processes or importing a model.

## One frozen execution

The final protocol was declared at `2026-10-17T02:58:21.556080+00:00`; the implementation freeze was written at `02:59:49.045055+00:00`. The only suite ran from `03:00:34.298764` to `03:00:35.681458+00:00`, taking 1.382908100 seconds. There was no retry or post-result threshold change. Before freezing, the protocol clarified that existing repository CPU numerical, tiny random-model and auditor-CLI regression tests were separate from guarded new-census preflight. The original draft timestamp and [clarification receipt](../results/dual-identity-census/protocol-prefreeze-clarification.json) are retained.

| Measurement | Recorded result |
| --- | --- |
| Fixed cases | Graceful native census; same-image Python helper rejection |
| Held snapshots | Five, with sizes 3/5 and 3/5/7 |
| Retained process identities | Twelve; all have exit receipts |
| Final Job membership | Zero in both cases |
| Portable frozen receipt audit | 430/430 checks |
| Local audit including executable-file rehash | 431/431 checks |
| Repository regression suite | 419 tests passed in 53.202 seconds |
| Pretrained model loads / optimizer updates | 0 / 0 |

The worker's self executable matches the frozen venv launcher file and opaque canonical path digest. Its retained OS image independently matches the frozen base Python file and path digest. The helper's self executable and OS image each match the base Python role, but its PID/creation identity is outside the fixed admitted roles: it remains unapproved and the Job is terminated. Identified `conhost.exe` extras also remain unapproved. Equal executable bytes alone cannot admit another process; the auditor does not require self and OS descriptions to be equal or different.

Both producer and independent auditor were frozen before execution, along with source tests, dependencies and executable file/path hashes. The [artifact manifest](../results/dual-identity-census/artifact-manifest.json) binds published result bytes; the [trace manifest](../results/dual-identity-census/trace-manifest.json) binds thirteen raw JSON traces. Receipt consistency is distinct from fresh OS measurement and cannot authenticate coherently rewritten evidence.

## Boundaries and next test

These are five held snapshots, with bounded depth/count and before/after Job counts. They do not establish continuous child coverage, loaded DLL integrity, provider custody or production reliability. File/path hashes describe queried files at observation time. Synchronous OS and file calls cannot be hard-preempted; late return fails the declared acceptance budget.

The [previous child-image census](../results/child-image-census/report.md) retains its original two failed self-hash checks. The eight children from the still earlier training attempt never had their images recorded; new observations cannot retrospectively identify them. Historical parent RSS remains invalid, the pretrained integration remains failed before import, and all six joint natural-text cost/final-quality screens remain failed. SaveScope v0.1's fresh-state API is unchanged.

The next engineering gate is a separately declared narrow role policy that preserves unknown-child and same-image-helper rejection. A later actual pretrained integration must independently test the pinned loader, thread/native/provider behavior, two optimizer updates, healthy and precise import-failure controls, busy timeout, private-memory threshold, sampler overhead and verified cleanup. This pass performs no such training experiment and grants no training admission.

## Public-source coverage

This pass sampled seven people and ten repositories with a seven-day overlap. Scan observation ran `02:49:10.398387–02:53:16.372032Z`, with event cutoff `02:49:10.394386+00:00`. The overlapping 24h/72h/7d windows contain 153/220/235 primary records; 35 identities are current-only and six changed at the same identity. All 35 current-only records have event activity after the previous cutoff. Mutable issue/PR activity is distinct from proposal creation, and prior-only records are sampling differences rather than deletions.

Both snapshots pass five integrity/regeneration checks. The bounded scan has fourteen truncated endpoints and disabled discussions remain gaps. No newly created original repository was found in the sampled author pages. A supported-browser check separately read Nathan Chen's same four newest visible original posts and the full English departure post: it announces leaving Kimi, with no verified next employer. A prior Bay Area reply is neither a new post nor employer evidence. The other six X timelines were not read; the scanner does not cover X or blogs.

Selected upstream source facts, authorship, read times, hashes and CI limits are retained in the [reviewed evidence receipt](receipts/20261017T024821Z-reviewed-sources.json). They inform subsequent falsifiable tests; upstream source assertions and CI metadata do not count as local model, kernel or agent execution.

## Three selected source signals

[FLA draft PR1497](https://github.com/fla-org/flash-linear-attention/pull/1497), authored by Aphelios183, proposes per-sequence scalar rotary-cache bounds for packed inputs in CUDA and Ascend wrappers. For lengths `[3,5]`, offset 2 and cache length 7, the proposal accepts each sequence rather than requiring ten positions for the combined packed buffer. Parent/head rotary source bytes and patch reconstruction were checked. Numerical kernels are unchanged. The draft's new numerical/gradient and CPU rejection assertions are source evidence; the L40 pass counts, graph coverage and timings remain author reports. Of eight exact-head workflow records, five were successful, one queued and two running when read; H100 success metadata has no inspected jobs/logs. This is an H1 input-semantics/dispatch test lead, not Nathan Chen's contribution, a landed change or a training speed/memory result.

[OpenClaw PR174935](https://github.com/openclaw/openclaw/pull/174935), authored by steipete and merged at `02:11:23Z`, distinguishes confirmed absence from failed inspection of managed executable files and sandbox leases. Only executable `ENOENT` means absent; permission/I/O errors propagate. Lease handling distinguishes exact-ID absence from process/provider/parse/identity failure and checks inspection success before interpreting recovery JSON. All six PR patches match the actual-parent-to-landed inventory. Exact prepared-head CI remains failed: 54 jobs contain 23 successes, 29 skips and two failures, with 419 step metadata records. Logs were not downloaded. The claimed inherited mock-export failure and interrupted baseline preparation are author reports, and the premerge review's missing shipped-command/base-fail/head-pass proof remains a gap. The H2 test should verify no unauthorized replacement, reprovision or retirement under a failed probe while preserving bytes and original redacted errors.

[OpenClaw PR174947](https://github.com/openclaw/openclaw/pull/174947), also authored by steipete and merged at `02:27:48Z`, separates durable message append from failed post-commit transcript notification. The proposed guarded publisher preserves the saved append receipt and emits a content-free warning; it does not automatically replay notifications. The landed scope has five files, including mock export/baseline changes, so green CI cannot be attributed solely to the publisher guard. Four patches match PR metadata exactly; the baseline edit has the same context/add/remove lines but a shifted hunk and different landed blob. Prepared-head CI success is metadata only. Author-reported owner/publisher checks and test counts were not locally reproduced, and the author reports a final dry-run scanner SIGILL with full changed checks unexecuted. The H2 test should retain distinct saved-message, current-authority and notification-delivery receipts across actual packaged sync/async calls and two restarts, with no duplicate append or automatic notification replay.

Both repositories were publicly readable with MIT metadata. Twenty-four bounded source GETs returned 200; the independent local receipt review passed 70 checks while preserving the explicit patch, CI and runtime limits. This pass copied no upstream implementation and executed no upstream tests. These signals refine our test contracts without asserting private research plans, a new affiliation or endorsement.
