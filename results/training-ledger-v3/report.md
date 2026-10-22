# Actual pretrained caller ledger v3: integration accepted

One separately frozen two-case local Windows CPU suite passes the complete saved-byte acceptance. It uses the **unchanged actual v2 producer and worker**, not a new observer-only harness. Two pinned Pythia-14m loads complete; the healthy caller performs 16 dense AdamW updates and the injected partial-write case refuses release before its first update. All ten retained process identities exit and both Jobs are empty.

This closes the bounded ledger→actual training caller integration gate. The six historical H1 joint cost/final-quality failures, invalid old parent RSS, v1 unexplained import timeout and v2 frozen raw-inventory rejection remain unchanged. No compression benefit or scientific quality gate is established here.

## What changed before execution

V2's actual producer completed, but its frozen auditor compared the full raw directory with an older payload inventory that omitted seven new import markers. V3 separately freezes the **exact suite directory and full original-plus-progress case schema**, then composes it with the original identity/provider/training/ledger/cleanup checks. Fault-only acceptance receipts also get exact schema, counter and monotonic-order checks.

Seven new preparation tests replayed the **complete real archived v2 directories** before this attempt. They reject every missing progress file in both cases, missing original files, unknown JSON, pending/suite extras, progress identity/provider changes, altered ledger bytes and a wrong fault-control counter. Another control preserves v2's frozen rejection. These are pre-execution preparation controls for v3; they do not retroactively accept v2.

`training_ledger_v3.run` is AST-identical to v2's run function and directly calls the same `training_ledger_v2.run_case`. The worker, trace, provider permission, role admission, acknowledgment, seed, model/data/optimizer schedule and deadlines are unchanged. The new version has no global monkeypatch. Selecting the immutable predecessor entry point is the rollback.

## Frozen workload and actual outcome

The workload remains local `EleutherAI/pythia-14m` revision `cf967c0a9a04383db6f7b1108d86b2962634b4ac`, seed503, CPU float32, one worker and one intra/inter-op thread. The healthy arm uses the fixed16×2×64 target schedule; the fault arm loads the same pretrained model with fresh optimizer state and stops at the pretrain query. Import20s, case60s, suite240s, sampled-private stop1GiB, trace4MiB/900rows and20ms target sampling were frozen before execution. No deadline renewal, retry, seed/LR change or additional model run occurred.

| Measured endpoint | Observed result |
| --- | --- |
| Producer cases / frozen saved-byte audit | 2/2; complete schema and 1914 original healthy payload checks pass |
| Model loads / dense updates / target positions | 2 /16 /2048; fault updates0 |
| Healthy accepted readings | 125 =5held +120active |
| Total ledger | 127 readings /130 committed rows /73075 bytes |
| Injected pretrain write | 3 committed rows/1345bytes +5uncertain bytes; training release and later query refused |
| Import progress | 14markers /23640bytes across both actual interpreters |
| Healthy / fault case wall | 16.304227s /11.066171s |
| Dense loop / throughput | 3.275093s; 625.326 targets/s |
| Healthy full case throughput | 125.612 targets/s, including load/import/holds/cleanup |
| Active window / parent native CPU | 3.330857s /2.187500s |
| Active query / Toolhelp wall sum | 0.025766s /2.115969s; selected operations only |
| Largest recorded active sample gap | 0.050343s, below frozen0.5s bound |
| Sampled current private / resident maxima | 689430528 /581636096 bytes |
| Held censuses / retained exits / empty Jobs | 9 /10 /2 |

Healthy exits are5×0; fault termination exits are5×57347. Ledger samples bind the retained actual interpreter, distinct from the venv launcher, to the held and active reads. The partial sink remains poisoned after its uncertain tail; no committed-row claim includes those5bytes. An independent direct JSONL/census/exit review agrees with the saved-byte auditor.

The final parameter SHA256 is `eb98cc941d16772d9938cff71cdd09dde8c887e6cca9811b66e9b0747fc278dc`. It and all16 recorded training losses match the prior pinned v2 healthy trajectory. This is a deterministic integration control, not an independent heldout quality score. One healthy run cannot support tail percentiles; its loop/case throughput and observation costs are descriptive. Different version import/wall times are not a controlled speed comparison or an explanation of v1's timeout.

## Reusable code and offline verification

- Caller: `experiments/training_ledger_v3.py`, reusing `training_ledger_v2.run_case` and its actual worker.
- Complete-directory auditor: `scripts/audit_training_ledger_v3.py`.
- Pre-execution full-directory controls: `tests/test_training_ledger_v3.py`.
- [Protocol](../../fixtures/training-ledger-v3/protocol.json), [50-file freeze](../../fixtures/training-ledger-v3/implementation.json), [pre-execution review](../../fixtures/training-ledger-v3/pre-execution-review.json), [unaltered raw outcome](raw/report.json), [frozen acceptance](frozen-acceptance.json), [independent review](independent-review.json), [metrics](metrics.json), [test receipts](test-receipts.json).

```bash
python -S -m scripts.audit_training_ledger_v3 --output results/training-ledger-v3/raw --protocol fixtures/training-ledger-v3/protocol.json --freeze fixtures/training-ledger-v3/implementation.json
python -S -m unittest tests.test_training_ledger_v3
```

These commands only parse saved receipts and run guarded archive tests; they do not execute a model or native workload. The prefreeze focused selection passes38tests; the full suite passes912tests with81skips (993total). Review caught omitted runner imports before freeze; the final runner's global bindings and unchanged-run AST were verified. All50 frozen source hashes and all46 predecessor v2 source hashes remain intact.

## Remaining engineering and scientific gates

This establishes one local Windows CPU actual-caller integration with an exclusive bounded sink, exact boundary admission and retained cleanup. It does not establish continuous isolation, arbitrary blocking-sink liveness, durable/fsync ledger commits, GPU/multinode behavior or production capacity. Whole-process sampled current maxima are lower bounds, not full training/allocator/GPU peaks; the sampled stop can overshoot. Query wall sums are not a causal total observer overhead estimate.

**Stop expanding observer-only prerequisites.** The next H1 experiment must be separately preregistered on this same actual caller: matched dense/bank complete training cost with fixed model/data/initial optimizer state, equal-token and equal-time budgets, all packing/retrieval/data/observer work, suitable native memory endpoints and a sealed final-quality evaluation. Report effective throughput with final quality, failures, end-to-end timing, resource limits and observation cost. Preserve the existing negative settings; no seed/LR rescue. No second scientific/model suite was run in this pass.
