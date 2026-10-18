# Saved-tensor INT8: allocation lifetime and callback cost

One separately frozen, eight-worker CPU suite completed once. All eight cases
pass the original acceptance gates; the frozen saved-receipt auditor passes
739/739 checks. Each worker loads pinned Pythia-14m and runs one exact-loss
forward/backward, with **zero optimizer updates**. The failed
[v1 preimport attempt](../codec-allocation/report.md) remains unchanged.

The useful result is a measured tradeoff: INT8 replaces selected saved backing
at the forward boundary, while packing and decoding allocate temporary storage
and take time. This is a narrow allocator diagnostic, not a training benefit.

## Observed quantities

| Quantity | Hooked dense | INT8 |
|---|---:|---:|
| Selected registered backing after forward + cross entropy | 37,321,728 B | 34,628,096 B |
| Same subset after backward, loss/logits deletion, and zero_grad | 30,487,552 B | 30,487,552 B |
| Eligible outer saved-source backing | 3,604,480 B | 3,604,480 B |
| Returned outer code/scale backing | aliases original source | 910,848 B |
| New outer decoded float backing during backward | none | 3,604,480 B |
| Largest single pack callback temporary requested-live subtotal | 0 B | 524,800 B |
| Largest single unpack callback temporary requested-live subtotal | 0 B | 262,144 B |
| Full ON trace cumulative positive allocator requests | 510,189,936 B | 539,068,051 B |

Both ON occurrences of each method agree on these values. The forward subset
difference is 2,693,632 B. It includes exact and parameter backing and covers
only registered owners; it is not a pure residual-bank total, whole-process
memory, OS capacity returned, or a CPU/GPU peak. Cumulative requests count
repeated allocations and are not simultaneously live memory.

All 19 eligible INT8 source storages have been freed and their strong owners
have expired by the after-forward probe; 38 code/scale storages remain live
then and expire by after-backward. The 19 decoded storages are created and
freed during backward. They are not registered yet at after-forward, so that
boundary provides no decoded-owner expiry observation. Dense payloads alias
the original sources: their bytes must not be added twice.

The INT8 pack temporary maximum of 524,800 B differs from its largest callback's
**cumulative** created requests, 1,575,089 B. Returned payload/decoded backing
is excluded from temporary workspace. These values concern reported allocator
requests and weak StorageImpl ownership, not physical pages.

| Descriptive operator-time ratio | First pair | Second pair | Geometric mean |
|---|---:|---:|---:|
| Dense ON/OFF | 1.215474 | 1.199024 | 1.207221 |
| INT8 ON/OFF | 1.173315 | 1.235819 | 1.204161 |
| OFF INT8/dense | 1.108977 | 1.076496 | 1.092616 |

Operator time sums forward + exact cross entropy and backward timers. It
excludes the intervening owner snapshot and subsequent validation/deletion/
gradient hashing/zero_grad. Each ratio has two observations on one host in
fixed OFF dense/INT8/INT8/dense, then ON dense/INT8/INT8/dense order. All OFF
workers precede ON workers. These are descriptive ratios, without randomization,
replication, confidence intervals or a causal total observer-overhead estimate.
OFF callback timings and owner/allocator results are absent, not zero.

## Configuration and evidence

The [protocol](../../fixtures/codec-allocation-v2/protocol.json) pins seed 503,
batch indices [116, 73], shape [2, 65], CPU float32/eager, one intra/inter-op
thread, and Pythia-14m revision
`cf967c0a9a04383db6f7b1108d86b2962634b4ac`.
The implementation froze at 2026-10-18 01:18:00.846048 UTC. The sole actual
suite ran 01:18:08.096713–01:19:48.409758 UTC, 100.313605 s including setup and
cleanup. No retry, holdout access, optimizer update or upstream execution.

V2 fixes v1's budget/count confusion: the existing provider validator expects
budget 1 even at preimport, where observed count is separately 0. It retains
every raw received stage before gate evaluation and records named predicates.
The codec, numerical controls and measurement interface are unchanged. The
provider guard is a Python audit policy, not an OS network sandbox; no active
memory sampler or hard native private-memory cap is present.

- [Original suite](report.json), [original-file manifest](original-manifest.json)
  and [summary](summary.json): 173 unchanged raw files, 40 accepted stages,
  48 controls with acknowledgments, 24 retained process exits all exit0 and
  eight empty Jobs.
- [Frozen receipt audit](saved-receipt-audit.json): 739/739. Same-method OFF/ON
  loss, gradient digests, initial parameters and batch digests agree. Dense
  and INT8 gradient digests differ; equality across observer settings is not
  a compression accuracy or model-quality gate. Gradient bytes were not saved
  for independent rehashing.
- [Independent saved-evidence review](independent-review.json): 13,925/13,925,
  without importing the producer, frozen auditor, provider validator or
  reducer. Four traces' pointer epochs, reference bindings, boundary owner
  subsets and callback arithmetic agree. Native allocation IDs are absent;
  each trace retains 78 right-censored allocations / 56,271,904 requested B.
- [Independent numerical methods and tables](numerical-review/methods.md):
  19,478/19,478 saved-evidence recomputations, including individual storage
  lifetimes and raw-file hashes. Its reusable script is post-outcome.
- [Three saved-receipt rejection controls](rejection-controls.json): a raw-byte
  trace mutation, stale poststudy operation hash, and a changed gradient digest
  with refreshed outer hashes are rejected. Disposable metadata/file mutations
  do not execute changed gradients or additional models.
- [Validation profile](validation.json): 48 guarded prefreeze tests; later
  portable discovery with NumPy and no ML libraries runs 915 tests, 67 skipped,
  zero failures/errors. Earlier failed environment/harness attempts and a
  time-dependent false positive in an unchanged legacy test are recorded.

Audit and reproduce the saved rejection controls with Python 3.11+ and stdlib:

```bash
python -S scripts/audit_codec_allocation_v2.py --result results/codec-allocation-v2
python -S scripts/check_codec_allocation_v2_controls.py
python -S results/codec-allocation-v2/numerical-review/summarize.py --expected-summary results/codec-allocation-v2/numerical-review/numerical-summary.json
```

These commands inspect saved evidence; they do not repeat the model suite.
[Fixture instructions](../../fixtures/codec-allocation-v2/README.md) distinguish
portable replay from host-specific actual execution. File hashes are listed
in [SHA256SUMS](SHA256SUMS).

## Remaining research gate

The prior six failed natural-text joint cost/final-quality screens and invalid
historical parent RSS remain unchanged. No GPU, full training peak, final
quality, learned routing, AttnRes, production reliability or novelty result
follows. Before claiming a benefit, separately predeclare a matched dense/bank
training study with authenticated worker measurement, packing/retrieval cost,
independent fixed data, sealed final-quality evaluation and observer controls.
Do not rescue the old result with a seed/lr/threshold sweep.
