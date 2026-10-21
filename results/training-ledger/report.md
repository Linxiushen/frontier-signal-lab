# Actual pretrained caller / ledger integration v1 — failed

The separately frozen actual training caller attempt stops while waiting for
`postimport-ready.json`. Its original 20-second import-stage deadline expires.
The model loader is behind the unreached postimport continuation gate: **zero
model loads and zero optimizer updates** occurred. One experiment slot was
reserved and consumed; there was no second native/model attempt.

## Actual caller and integration

The new `experiments/training_ledger_integration.py` injects a bounded JSONL
ledger into the held and active parent query paths of the pinned CPU Pythia
training caller. It reuses the immutable `observer_duty_v2` worker, provider,
role, control and final-acknowledgment validators. Each query uses current Job
membership and the retained **actual interpreter** handle. The venv launcher
remains a distinct identity. A trace failure stops further query/release paths;
native termination, empty-Job verification and handle closes remain mandatory.

This is a real caller integration attempt, not another stdlib observer study.
The intended two arms were one healthy pinned Pythia-14m load/16 dense AdamW
updates and a partial-write fault after a second load but before training
release. Same seed503,128train blocks,batch2×65, one CPU intra/inter-op thread,
60-second case/240-second suite and four-second cleanup budgets were frozen.
Trace limits are900rows/8192bytes per row/4MiB total. An observed actual-process
private-byte value above1GiB stops the caller; this sampled stop is not a hard
OS limit and may overshoot or miss peaks. No resource was purchased.

## What actually ran

| Stage or control | Observed result |
| --- | --- |
| Healthy arm | Fails after20.8892119s waiting for postimport receipt |
| Actual interpreter binding | Distinct launcher/worker; exact current image/path pins |
| Held preimport sample | One native memory/CPU sample, following current membership, matches one ledger row |
| Trace | Two contiguous committed rows,776bytes, no uncertain tail or I/O fault |
| Held inventories | Before native3processes; preimport5processes including both consoles |
| Cleanup | All5retained identities exit57347; Job active count0; no reported close error; cleanup0.0420168s |
| ML import completion/model load/training | Completion receipt absent; model load and training unreached |
| Partial-pretrain fault arm | Unrun; stopped after first unexpected failure |

No postimport-ready or worker-failure receipt was emitted. The stalled import
location and cause are unknown. Metadata preflight observed that the base Python
executable hash differs from the historical pin, while Python3.12.14/cpython312,
its path, launcher/native/conhost, provider and selected ML files match their
reviewed contracts. The current executable and two Python DLLs were pinned
**before** this new freeze. That change is not established as the timeout cause
and these results are not a same-environment cost comparison with older runs.

The frozen saved-byte auditor still rejects the producer failure. The separate
[post-outcome preservation review](post-outcome-preservation.json) verifies the
saved rows, identities, raw controls, withheld model gates and cleanup; it does
not turn failure into acceptance. All41frozen source/dependency hashes remain
unchanged. The first prefreeze test run exposed an archive-path error and a
wrong guessed JSON prefix; both were corrected before freeze. Final90focused
tests and977full tests(81skipped,896passed) pass, but did not predict this native
import timeout. No frozen source or deadline was repaired after execution.

## Evidence and next gate

The [protocol](../../fixtures/training-ledger/protocol.json),
[implementation freeze](../../fixtures/training-ledger/implementation.json),
[pre-execution review](../../fixtures/training-ledger/pre-execution-review.json),
[raw report](raw/report.json), [execution](execution.json),
[frozen rejection](frozen-audit-rejection.json) and
[byte manifest](selected-manifest.json) preserve this original attempt.

Keep the same actual pretrained caller as the target. Before another attempt,
separately preregister a version retaining bounded import-progress evidence with
the same exact identity/provider/cleanup controls. Do not blindly increase the
deadline or start another observer-only prerequisite. The native stdlib v3
prerequisite stays closed; this actual caller integration remains unaccepted.

No training throughput, training p95/p99, optimizer trajectory, quality, bank
compression, observation overhead, training peak memory, GPU, distributed or
production result is available from this attempt. The six H1 cost/final-quality
failures, invalid historical parent RSS and other unmet scientific gates remain.
Matched dense/bank full cost, appropriate memory endpoints and sealed final
quality still require a separate protocol after caller acceptance. Immutable
`observer_duty_v2` remains the rollback entry point; no global monkeypatch is used.
