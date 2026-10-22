# Complete training cost: launch failed before native execution

The one frozen launch on 2026-10-22 at 04:07:54–04:07:55 UTC
(12:07 Beijing time) failed in our CLI path handling. **No native Job,
model import/load, optimizer update or evaluation ran.** All 12 training
cases are unrun. There is no training cost, memory or quality comparison.
The attempt consumed this pass's single reserved scientific suite; no retry
was made.

Our wrapper supplied a relative `--output`. The frozen runner compared it
with an absolute repository root using `output.relative_to(ROOT)`, which
raised `ValueError` before `output.mkdir()` or `run_case()`. This is a local
integration defect in our code. See the [failure record](failure.json) and
[sanitized launch traceback](launch-error.txt); the record retains the hash
of the original stderr. No raw output directory or partial checkpoint exists.

The [accepted actual-caller ledger v3](../training-ledger-v3/report.md) remains
accepted and closed. This failed launch adds no observer acceptance or
scientific result. The six historical H1 joint failures and invalid historical
parent RSS remain unchanged.

## Prepared engineering integration

The new [caller](../../experiments/native_training_cost.py) directly adapts the
accepted actual pretrained caller's identity, provider guard, retained native
handles, role policy, acknowledgment barriers, ledger and cleanup. It does not
modify or globally patch the predecessor. Selecting the existing caller is the
rollback. The following workload and measurement support is **prepared but
unexecuted**:

| Item | Frozen scope |
| --- | --- |
| Real caller / load | Pinned Pythia-14m, local CPU float32/eager, one thread; Alice 128 training blocks, batch 2 × 64 target positions |
| Matched arms | Existing dense vs saved-activation INT8 excluding norm/attention; seeds 503/701/907, fresh AdamW at original LR 1e-4; 12 fixed jobs / six pairs |
| Bottleneck / integration point | Compression pack/retrieve and retained activation lifetime inside actual forward/backward/optimizer execution; complete cost and final quality remain unestablished |
| Budgets | Equal 64 updates or original 60-second loop with at most 1-second atomic overshoot; case 180s, suite 1200s, evaluator 300s; sampled actual-process private stop 1 GiB, not a hard allocation quota |
| Useful throughput / latency | Target positions per loop and complete-case second; data, zero-grad, forward, backward, optimizer and loss-record timings; nearest-rank p50/p95/p99 step latency with sample count; first step and remaining steps separately |
| Complete boundary | Case wall includes import/load, hook/codec setup, training, held measurements, validation/checkpoint and cleanup; fixed-time budget applies to the loop, not a service SLA |
| Memory endpoint | Retained actual interpreter's OS lifetime working-set high-water at held postloop, before validation/checkpoint; includes import/load/holds/observation. Current resident/private maxima are sampled lower bounds |
| Observation cost | Same 20ms-target memory/CPU ledger queries in both arms; query wall and parent CPU descriptive only. No active-window Toolhelp and no OFF arm or causal total-overhead estimate |
| Final evaluation | Only after all 12 hashed checkpoints are sealed, separate evaluator loads baseline and each endpoint once; training refuses `holdout.json` opens |
| Quality boundary | Original public, previously evaluated LookingGlass 64-block fixture: procedural seal only, no fresh/generalization or pretraining-cleanliness claim |

The INT8 control is **not a learned residual-bank architecture**. This local
CPU workload cannot establish GPU, distributed or production scalability.
No compilation or communication work is performed. The suite's resource and
sampling rules, exact order and strict directional screens are in the
[protocol](../../fixtures/native-training-cost/protocol.json). A completed
suite would report the six quality/cost screens including failures; it would
not turn these short fixed-order comparisons into significance or causal
performance claims.

## Freeze and correction

| Artifact | SHA256 |
| --- | --- |
| [Original implementation freeze](../../fixtures/native-training-cost/implementation.json) | `a9b38fdc341769bb29700a86a1ef920cbc891a641af8beb5da6fe607e18b681e` |
| [Original protocol](../../fixtures/native-training-cost/protocol.json) | `68a161ff62c24451f976b8542667c60a072543db058cd2c51f04c9e913aeacc7` |

All 49 frozen source files and all 50 predecessor v3 frozen source files
remain unchanged. The failure is preserved rather than repaired in place.

A separate post-outcome [entrypoint](../../scripts/run_native_training_cost.py)
resolves all CLI paths before calling the frozen runner. It also requires its
own hash in a **new** freeze, so the old freeze cannot authorize that entrypoint.
Its [regressions](../../tests/test_native_training_cost_launcher.py) exercise
the real argument parser with relative paths and refuse missing/changed
entrypoint hashes. The expensive runner is mocked; these checks do not
execute or accept the native/model integration.

## Validation and next gate

Before freezing, 30 focused controls passed. The full portable suite ran
998 tests: 917 passed and 81 skipped. Those checks missed the wrapper's actual
CLI boundary. After the outcome, seven cost/entrypoint controls passed; the
final full suite ran **1000 tests: 919 passed, 81 skipped**. The normal-site
test invocation and receipt hashes are in [validation.json](validation.json).
These tests supply no native/model training evidence.

Two preparation failures are retained in the failure record: an initial
`-S` full-test command could not import installed NumPy, and an unfortunately
named local `inspect.py` helper shadowed stdlib `inspect` during freeze
preparation. Both were corrected before the actual launch; neither launched
a native/model workload. The latter rewrote only an unchanged local screening
description, and did not change frozen sources.

Next pass: separately preregister the corrected entrypoint and full same-caller
workload, include the exact invocation/path boundary in the prelaunch controls,
then permit at most one original matched suite. Keep the accepted ledger gate
closed and return directly to full training cost, endpoint-appropriate memory
and procedurally sealed final evaluation. Do not add observer-only prerequisites,
change seeds/LR/thresholds after outcomes, or treat this failed attempt as a
cost or quality result. All work in this pass used background CLI/API without
mouse, keyboard, visible-browser or desktop automation.
