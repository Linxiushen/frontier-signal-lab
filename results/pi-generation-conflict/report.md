# Native busy and request identity across two process reopens

One separately frozen H2 native suite passed on 2026-11-02 at 11:20Z. The same
optional `Harness → Conversation → GenerationTask → official local Faux → ToolTask`
caller retained reservations after genuine native busy errors and quarantined
native type/content collisions. Two SQLite Sessions, each with two conversations
and host capacity two, ran in three worker PIDs with two actual forced kills and
reopens. The pinned runtime was unchanged; no real model or HTTP provider ran.

There were 18 arrivals: 14 durable host reservations and four overload refusals.
The 14 host dispositions were **four normal final native completions, two
cancellations after a local effect, two cancellations before an effect, one
busy reservation denied by current authority, one busy reservation cancelled,
and four native identity quarantines**. All 14 reached their intended disposition
and final active capacity was zero. The two busy requests created no native row.
Twelve native submissions included two display-only writes; the ten native
inputs produced ten GenerationTasks, ten ToolTasks and ten Faux calls. All 20
tasks terminated: 12 aborted and eight completed. Six local transactional
effects, including the two post-effect cancellation controls, each had count one.

The native contract was observed directly: two new reject-when-busy inputs raised
`ConversationBusy`, two input requests colliding with a same-ID write raised the
native type error, and two changed-content same-ID input requests returned the
existing native identity. Content reuse is native contract evidence, not by
itself an upstream bug. Host reconciliation verified the original input bytes,
conversation, request ID and type. Four quarantines permanently retired only
host reservations, retained the host identity and recorded the foreign native
ID/type; they neither adopted that native ID nor automatically aborted its chain.
For both foreign input fixtures, the placed native record was identical before
and after host cancellation. Only after that observation did the fixture owner
explicitly invoke Conversation-wide abort and wait on the exact original handle.
Native placed-input cancellation is not a per-ID abort operation.

At kill zero, each Session held two host reservations and no effects: one
cancel-marked native control and one busy reservation. Current authority was
revoked in service zero; the service-one busy request was durably cancelled.
At kill one, each held one original post-effect control with its cancellation
mark committed and one local effect. Six reservations recovered across the two
reopens; no tool execution re-entered. Reconciliation preceded the worker's
explicit `harness.resume`, while native `Conversation.abort` itself enables the
scheduler. This is finite no-replay evidence, not a global pause guarantee.

The [protocol](../../experiments/pi_generation_conflict_protocol.json),
[eight-source freeze](../../fixtures/pi-generation-conflict/implementation.json)
and [pre-execution reviews](../../fixtures/pi-generation-conflict/pre-execution-review.json)
preceded this single attempt. Node, 12,765 runtime files
(79,754,718 bytes) and
63 inherited source pins were authenticated.
Independent preparation review ran 11 fake-Harness/pure Node tests and six
synthetic-freeze/auditor Python tests; these are preparation evidence. A pure
regression also protects semantically equivalent foreign JSON after quarantine.
That stronger JSON case has **no native experiment evidence**: this native
collision workload used foreign payload bytes and held the ToolTask before effect.

All 56 raw files (1,545,013 bytes), including SQLite,
WAL/SHM artifacts, logs, snapshots and execution records, are copied verbatim in
the [raw inventory](raw-manifest.json). The separate
[outer CLI receipt](execution-receipts/h2-native-CLI.receipt.json) and captured
stdout/stderr are outside `raw`; the original outcome directory was not modified.
Saved evidence can be checked without invoking native workers or a provider:

```bash
python -B scripts/check_pi_generation_conflict.py
```

The suite took **5.000 s** including workers, kills/reopens,
SQLite copies and frozen audit. Runtime/source authentication took
**39.032 s**. The internal controller clock,
starting before authentication, was **44.032 s**; the complete
external CLI clock, including interpreter startup/imports and exit, was
**44.328 s**. Six effects therefore yielded **1.200 effects/s
over suite time**, **0.136 over controller time**, and
**0.135 over complete CLI time**. Complete CLI excludes preparation,
independent reviews and later publication/checking. Four normal final native
completions are a separate success category; six effects include cancelled-after-
effect controls. There is no matched baseline, observer-OFF arm or quality test.
These measurements establish no speedup or SLO.

Mixed host-disposition latency includes deliberate holds/restarts/quarantines:
n=14, nearest-rank p50 **57 ms**,
p95/p99 **1674 ms**. Sampled worker private maxima
by stage were 85,942,272 /
85,221,376 /
104,710,144 bytes. Observed OS peak working
sets were 86,433,792 /
86,913,024 /
89,030,656 bytes. There were
64 / 49 /
39 samples, with maximum interior gaps
32 /
47 /
47 ms and unobserved
start/end intervals. Sampled private maxima are lower bounds and differ from OS
working-set high-water or GPU memory. Callback recording totalled
1.143 ms and JSONL flushes 2.449 ms;
other observation/copy costs are not isolated. Controller/launcher memory and
communication were not benchmarked. Exact values are in [report.json](report.json).

Committed-state callbacks were checked for their recorded invariants. Because
`checkpointWhen` checkpoints every service document revision, each saved stage
copy retains its latest service revision; the intermediate callback events cannot
all be independently rejoined to historical database revisions. Each stage's
full SQL endpoint, latest sequence/state and stopped-source/copy equality were
checked separately. Callback observations are not a durable database proof of
every intermediate state.

The unchanged limits were 90 s suite / 20 s process / 8 s condition, 128 MiB Node
old-space, 256 MiB polled private bytes, 20 MiB observed output, and 1 GiB free
disk. Polls and SQLite callbacks do not interrupt arbitrary OS I/O or capture
unsampled instantaneous peaks. Scope is a serial, trusted single Windows host,
two native SQLite Sessions and deterministic official Faux. Logs flushed before
controlled kills; arbitrary crash-log durability and native storage failure were
not tested. Authority checking and native submission remain separate commits;
concurrent permission/owner/cancellation races and independent tenant authority
are untested. Histories grow and reconciliation/reaping are explicit. No real
model, HTTP transport, independently persisted/external effect, exactly-once,
distributed/GPU or production conclusion follows.

**This finite busy/error/collision caller is CLOSED.** Do not repeat it or expand
isolated diagnostic/observer prerequisites. Next H2 work requires a separate
preregistration at the same native ToolTask boundary for a recoverable,
independently persisted effect and free local HTTP transport, with current
authority/idempotency, admission/cancellation, two process restarts and fixed
latency/resource/observation budgets. This remains a local integration gate,
not a real-model or production result. All prior failed/accepted H2 evidence,
H1 negative results and its original 5 GiB gate, and H3/H4 objects remain intact.

Independent saved-byte outcome review passed with no findings. It rechecked all six copied SQLite endpoints, exact host/native chains and dispositions, source/runtime pins and resource/time scopes without running native workers again. [Review](review/independent-outcome-review.json).
