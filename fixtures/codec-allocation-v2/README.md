# Frozen codec allocation v2 fixture

This separate v2 snapshot fixes the failed v1 caller's provider-budget argument
and preserves raw received stages before acceptance. The original v1 files and
negative outcome remain frozen. The new codec suite ran once: eight pinned CPU
model loads, eight forward/backward pairs and zero optimizer updates.

## Portable saved-evidence replay

From the repository root, Python 3.11+ needs no model, Torch, NumPy, account,
network access or Windows process API for these commands:

```bash
python -S scripts/audit_codec_allocation_v2.py --result results/codec-allocation-v2
python -S scripts/check_codec_allocation_v2_controls.py
python -S -m unittest tests.test_codec_allocation_v2 tests.test_codec_allocation_v2_auditor -v
python -S results/codec-allocation-v2/numerical-review/summarize.py --expected-summary results/codec-allocation-v2/numerical-review/numerical-summary.json
```

The frozen audit expects consistency and execution acceptance both true. The
post-outcome control consumer changes disposable copies only and requires all
three preregistered saved-receipt corruptions to be rejected. This is metadata
and file-custody testing, not a second allocator or gradient computation.
The independent numerical script reconstructs pointer epochs, callback
workspace and held owner subsets from raw saved events without importing the
producer/reducer/auditor. Use its help for output options.

- [Protocol](protocol.json): fixed order, seed, batch, model assets, stage
  deadlines, trace identity rules, stop conditions and three rejection controls.
- [Implementation freeze](implementation.json): exact source/dependency/test/
  review-tool/protocol/provider/executable hashes, frozen before execution.
- [Pre-execution review](pre-execution-review.json): 48 guarded pure tests and
  static reviews, no actual model workload before the freeze.
- [Result and limitations](../../results/codec-allocation-v2/report.md),
  [raw suite](../../results/codec-allocation-v2/report.json) and
  [original-file manifest](../../results/codec-allocation-v2/original-manifest.json).

Actual execution is a Windows-specific diagnostic using existing hash-pinned
local executables, urllib3 source and Pythia-14m assets. It is not a portable
one-command model benchmark. The producer CLI documents required paths with
`python -S experiments/codec_allocation_v2.py --help`; inspecting help does not
execute a suite. A future independent actual run needs its own reviewed freeze,
authenticated host assets, declaration and fresh output directory. Do not
overwrite or rerun this saved snapshot to rescue a result.

The selected owner subtotal and CPU allocator requests are not whole-process
or GPU peaks. Same-method observer controls are not a training-quality gate.
The complete suite contains no optimizer update or holdout evaluation; prior
cost/quality failures and invalid old RSS are retained.
