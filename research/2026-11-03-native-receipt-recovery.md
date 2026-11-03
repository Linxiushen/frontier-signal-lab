# Preserve receipts in the actual native recovery caller

The [receipt-monotonic dispatcher repair](2026-11-03-monotonic-effect-receipts.md)
now has a separately preregistered native integration result. One complete suite
invoked two overlapping public `reconcile()` calls on each of two reopened paused
Harness/SQLite Sessions, using actual GenerationTask/ToolTask checkpoints,
official deterministic local Faux and a real independent loopback HTTP store.
It passed once, with zero retries and zero real-model loads.

The concrete failure boundary is an obsolete genuine HTTP observation delivered
after another callback has persisted a receipt. Service0 delayed a GET404 until
after acknowledgement and host-authority withdrawal. Service1 obtained a real
POST403 before any create, held the reply, temporarily restored authority for
the first POST201 acknowledgement, revoked again and delivered the old denial.
Both callbacks preserved the committed receipt and returned existing. The
server returns existing receipts before checking current authority, so the
refusal had to precede the actual create; no response was fabricated.

Two actual native process kills/reopens then exercised durable postcommit
cancellation and exact native preabort. Six eligible fixture effects retain
count1, two fresh refusal/cancellation negatives have no effect, all16 native
tasks terminate and active reservations drain to0. Twelve arrivals produce8
admissions/4overloads, plus2exact retries/2changed-content conflicts. The two
cancelled recovered pairs end aborted/unanswered with historical receipts;
the live cancelled negative returns aborted tool output but completes its
native tasks and ends done. These are distinct outcomes.

[The result](../results/pi-receipt-recovery/report.md) includes preregistered
workload, native joins, independent stopped-SQL/HTTP checks, all97 raw files and
measured latency/resource/communication/observation costs. Suite time7.813s and
fullCLI40.609s have different scopes; offer-to-observed-terminal p50/p95/max is
116/5218/5218ms, including imposed holds/restarts. There is no comparison
baseline, causal speedup, model-quality or production claim.

The finite same-owner public-recovery boundary is CLOSED. The original factory
is the rollback, and all167 older frozen sources/3782 prior fixture-result files
remain unchanged. The earlier concurrent acceptance stays failed. H1/H3/H4 and
negative results retain their original status. Further work needs another
concrete actual caller/defect and a separate full preregistration, rather than
an unchanged rerun or additional isolated observer work.
