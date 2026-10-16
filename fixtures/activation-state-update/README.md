# Accumulated-state update diagnostic

This is a separate experiment, not an expansion of SaveScope v0.1's fresh-state API.
The protocol was recorded before implementation; `implementation.json` fixes the
four new source/test files after engineering validation and before model execution.
These local timestamps are not an external registration or timestamp attestation.

Use the pinned CPU runtime in `requirements-real-activation.txt` and obtain the
hash-verified public checkpoint with `scripts/download_pythia.py`. No model weights
are bundled. From the repository root:

```bash
python -m unittest discover -s tests -p test_adamw_state_reference.py -v
python -m unittest discover -s tests -p test_activation_state_update.py -v
python experiments/activation_state_update_probe.py --model-dir local-state/models/pythia-14m-cf967c0 --output reports/state-update-reproduction
```

The output directory must not already exist. Do not regenerate the committed freeze
for reproduction. Original local execution is in `results/activation-state-update/`;
CI replay uses a new ignored report directory. No expected numeric hashes are
enforced across operating systems or library implementations; the independent
reference controls and scientific gates are recomputed in the current runtime.

For each of seeds11/29/47, four actual dense AdamW steps generate nonzero state.
The fifth batch supplies one dense, norm-only-compressed and attention-preserved
gradient at identical warmed weights. Each gradient feeds two actual clone steps:
matched moments/step4→5 (primary), and fresh zero moments/step0→1 (secondary).
Fresh success cannot rescue primary failure. The original warmed weights and
optimizer state remain unchanged throughout the six clone steps per worker.

The declared totals are12warmup and9probe backwards,12warmup native updates and
18clone native updates. All76parameter tensors receive finite gradients. Exact CE,
13actual LayerNorm and6actual attention scopes are checked. Native theta/m/v/t
updates are checked against independent NumPy equations with input-scale moment
bounds and a propagated four-corner parameter interval. These numerical controls
are separate from the unchanged10%/0.99/half-baseline scientific gate.

Per-parameter hashes, sufficient statistics and reference receipts are retained;
raw weights, gradients and moments are not published. The receipts do not enable
independent offline recomputation of every raw-array reference. A numerical,
state, scope or budget failure produces an incomplete record, never a completed
scientific gate failure. The worker cap is360seconds and the parent cap420seconds
per worker including startup.

Three overlapping synthetic schedules and four dense warmup steps cannot establish
compression training quality, convergence, hardware performance, memory savings or
general optimizer-history coverage. The earlier fresh-state, training-cost and
synthetic-holdout negative results remain part of the record.
