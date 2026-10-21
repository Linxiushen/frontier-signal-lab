# Actual pretrained caller ledger v2 — producer completes, frozen audit rejects

The same actual CPU training caller completes both preregistered producer
cases: two pinned Pythia-14m loads, sixteen dense AdamW updates in the healthy
case, and a partial-write fault that refuses training release in the second
case. **Frozen saved-byte acceptance remains false.** Our auditor's old complete
raw-file inventory omitted the seven newly added import-progress files.

One original model-execution suite consumed this pass's scientific slot. There
was no retry, deadline extension, seed/LR adjustment or post-outcome change to
any of the 46 frozen source/dependency files. The v1 import timeout is preserved
and its cause remains unknown; successful imports here do not explain that run.

## Caller, resource bounds and integration

`training_ledger_v2` uses the actual retained interpreter's Job membership and
native memory/CPU handles in its held and active training query paths. It keeps
the original provider policy, role census, dense training, final acknowledgment
and cleanup contracts. The separately versioned worker's AST differs from the
immutable duty-v2 worker only at the import call. That call publishes seven
one-use, fsynced progress files binding nonce, PID, creation time, monotonic
clock and cumulative provider receipts. Each file is at most 8192 bytes.

The frozen workload uses checkpoint `cf967c0a9a04383db6f7b1108d86b2962634b4ac`,
seed503, 128 fixed train blocks, batch2×65 and one CPU intra/inter-op thread.
Import/case/suite budgets remain20/60/240seconds. The JSONL sink admits at most
900rows,8192bytes per row,4MiB total. Sampled private bytes above1GiB stop the
caller; this cooperative observation is not a hard memory cap. No compute or
model API was purchased. Immutable `observer_duty_v2` is the rollback entry.

## Saved execution evidence

| Item | Observed result |
| --- | --- |
| Healthy case | 1load,16updates,2048target positions;27.035333s including setup/import/validation/cleanup |
| Dense loop | 3.820993s;535.986targets/s inside the recorded loop boundary;75.753targets/s across the healthy case |
| Import receipts | 7per case,14total,23640bytes;15.186500s and7.700913s, both within unchanged20s budget |
| Healthy trace | 115committed rows,64910bytes;113accepted readings (5held+108active) |
| Partial-pretrain fault | Second load completes, zero updates;3committed rows/1348bytes plus5uncertain bytes; denies release and later query |
| Identity/census/cleanup | 9held inventories; healthy5exits0, fault5exits57347;2emptyJobs, no reported handle-close error |
| Saved acceptance | Frozen healthy1817/1818checks pass; one raw-file inventory check fails; main auditor stops before later acceptance checks |
| Post-outcome preservation | Exact complete raw-file union, all1818projected healthy checks, fault/provider/progress/ledger replay pass; **separate from frozen acceptance** |

The final parameter digest is
`eb98cc941d16772d9938cff71cdd09dde8c887e6cca9811b66e9b0747fc278dc`.
This is a recorded trajectory identity, not independent numerical recomputation
or a model-quality result. The target positions include the sixteen fixed
batches, with training losses recorded after each update; no holdout was opened.

The active observation window lasted3.868586s and used2.375s parent native CPU.
Its108queries took0.025585s combined, while global Toolhelp snapshots took
2.230333s combined; maximum recorded active gap was0.054042s. These are selected
cost components with receipt publication in the real caller. They do not sum to
total instrumentation overhead, establish a causal slowdown or supply a matched
OFF baseline. Observed current maxima were private689381376B/RSS581484544B;
these sampled whole-process lower bounds are not allocator/backward/OS peak
measurements. One healthy case supplies no meaningful p95/p99 or capacity claim.

## Failure preserved and next integration gate

The prefreeze controls exercised marker/provider mutations and the worker AST,
but did not replay the full healthy directory through `audit_files`. That
missed integration test let the legacy inventory compare all new files to a
schema containing only original receipts. Final61focused tests and983full
tests(81skipped,902passed) passed before execution. The initial synthetic fixture
had a wrong provider phase, and an initial full-suite command used `-S`, hiding
NumPy and failing11imports; both failures and the corrected prefreeze commands
are retained in [test receipts](test-receipts.json).

The [frozen rejection](frozen-audit-rejection.json) is unchanged. A separately
written [post-outcome checker](../../scripts/check_training_ledger_v2_preservation.py)
requires the complete original+progress file union, rejects unknown/missing
files, then replays the original healthy subset plus all progress and fault
receipts. Its [result](post-outcome-preservation.json) is preservation evidence,
not a repair of preregistered acceptance. Post-outcome regression tests are
explicitly separate from prefreeze controls. No model/native workload is run by
either saved-byte checker.

After preservation code and archived-directory regressions were added,9portable
import/preservation tests pass, and the final full suite passes986tests
(81skipped,905passed). These post-outcome checks do not retroactively qualify the
frozen experiment.

Before a future model attempt, freeze a new version of this **same actual
caller integration** with complete-directory schema, real archived progress
receipts and unknown/missing-file rejection controls. Keep the stdlib observer
prerequisite closed; do not add another observer-only campaign or enlarge the
timeout. After accepted caller integration, separately preregister matched
dense/bank complete training cost, appropriate memory endpoints and sealed final
quality. All six H1 joint failures, invalid historical parent RSS and unmet
H2–H4 gates remain. No compression benefit, GPU/distributed/production result
follows from this CPU execution or its CI replay.

The [protocol](../../fixtures/training-ledger-v2/protocol.json),
[freeze](../../fixtures/training-ledger-v2/implementation.json),
[pre-execution review](../../fixtures/training-ledger-v2/pre-execution-review.json),
[raw report](raw/report.json), [execution](execution.json),
[metrics](metrics.json) and [byte manifest](selected-manifest.json) retain the
original implementation, workload and observed outcome.
