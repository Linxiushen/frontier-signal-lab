# Pending authority and cancellation across two native process reopens

One separately frozen H2 suite passed on 2026-11-02 at 03:03Z. The same optional
`Harness → Conversation.submit → GenerationTask → official local Faux → ToolTask`
service consumed durable permission revocation and cancellation after process loss.
Two independent SQLite Sessions, each with two conversations and capacity two,
ran in three worker processes with two forced kills and reopens. No installed
runtime files changed, and no real model or network provider ran.

There were 18 unique arrivals: 12 durable host admissions and six overload
refusals. Two host-only reservations lost current authority and two acquired
durable cancellation; none of those four created a native submission or called
the provider. Eight inputs reached the actual native generation/tool lifecycle.
Two were cancelled before effect, two after effect and four completed normally.
All 12 host records terminated, all 16 native tasks terminated (eight completed,
eight aborted), and active capacity returned to zero. Six local transactional
effects each retained count one.

At the first kill each Session held a revoked host-only reservation and a
pre-effect native request with its cancellation mark committed before native
abort. At the second each held a cancelled host-only reservation and a marked
post-effect native request. Eight reservations recovered; original native task
identities were retained and no tool execution re-entered after reopening.
Reconciliation precedes the worker's explicit `resume`, but native `abort`
itself resumes the scheduler internally. This experiment does not establish a
globally paused scheduler or arbitrary crash safety.

The [protocol](../../experiments/pi_generation_cancellation_protocol.json),
[13-source implementation freeze](../../fixtures/pi-generation-cancellation/implementation.json)
and [pre-execution reviews](../../fixtures/pi-generation-cancellation/pre-execution-review.json)
preceded this single attempt. The unchanged original 1 GiB disk gate was met;
12,765 runtime files (79,754,718 bytes), Node and 54 previous source hashes were
verified. Nineteen Python and seven Node preparation tests passed; fake Harness
and historical graph tests are preparation evidence. No suite retry occurred.
All 50 raw files (1,496,032 bytes) are retained verbatim in the
[inventory](raw-manifest.json). The portable checker verifies saved evidence:

```bash
python -B scripts/check_pi_generation_cancellation.py
```

The measured suite, including worker stages, copies and frozen acceptance, took
4.437 seconds: six effects / suite time = 1.352 effects/s. Mixed-cohort terminal
latencies include deliberate holds and reopens: n=12, nearest-rank p50 1,373 ms,
p95/p99 1,486 ms. There is no matched baseline or observer-OFF arm. **The outer
controller's monotonic wall time, including runtime authentication, was not
captured**, so full-cost throughput is unavailable; a redirected log's filesystem
timestamp span is only an observation. These numbers prove no speedup or SLO.

Across stages, sampled private maxima were 104,742,912 / 85,917,696 / 85,549,056
bytes; observed OS working-set high-water values were 80,842,752 / 78,823,424 /
78,589,952 bytes. There were 58 / 45 / 40 memory samples, with maximum interior
gaps 32 / 46 / 47 ms and unobserved start/end intervals. Sampled private maxima
are lower bounds, distinct from OS working-set peaks or GPU memory. Callback
recording totalled 1.107 ms and JSONL flushes 2.178 ms, excluding other observation
and database-copy costs. [Structured metrics](report.json) retain exact values.

Scope is one trusted Windows host, official deterministic local Faux and local
SQLite effects. Logs flush before controlled kills; histories grow and hosts
must explicitly reconcile/reap. Authority checking and native submission use
separate commits. Concurrent owners/permission changes, independent tenant
authentication, real HTTP/model behavior, external exactly-once effects, general
capacity, distributed/GPU and production behavior remain unverified.

This finite pending-authority/cancel-mark fixture is closed. Return to the same
service for a separate complete preregistration of genuine native busy,
submit-error and request-ID/content-collision cases, with exact identity,
reservation capacity disposition, current permission/cancel intent, bounded
settlement and two process reopens. Wrapper duplicate/conflict probes and fake
Harness tests do not establish those native cells. Do not expand observer
prerequisites. Prior accepted slices, failed attempts, H1's original 5 GiB gate
and all H1/H3/H4 scientific states remain unchanged.
