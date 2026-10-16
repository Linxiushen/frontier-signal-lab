# New short-history numerical fixture

This original MIT synthetic prose is separate from the earlier training,
gradient and accumulated-state batches. It is a numerical diagnostic, not a
natural-language benchmark or sealed quality holdout.

The pinned tokenizer yields eight train blocks and four audit blocks, each
65 tokens. Inputs 0..63 predict positions 1..64. Each source contributes a
nonoverlapping prefix; unused suffixes are excluded. Exact blocks do not
overlap each other or the previous train/holdout blocks.

The three fixed schedules (101, 211, 307) each run two independent eight-step
histories from the same pretrained weights: dense and norm+attention-preserved
INT8 saves. At steps 4 and 8, each history's own complete parameter/moment/step
anchor is held fixed for dense, norm-only and norm+attention audit policies.
The unchanged joint update gate must pass **all 12 anchors**. Audit updates
are discarded and gradients cleared before the history continues.

Cross-history parameter and moment drift is descriptive. Its normalizations
include the dense cumulative displacement and sum of actual step lengths,
with zero denominators kept undefined. It does not identify a moment-only
cause, prove trajectory quality, or extend SaveScope v0.1's fresh-state API.

`protocol.json` was written before the new experimental implementation and
model run. `implementation.json` binds the reviewed code/tests before execution.
These local timestamps/hashes are not an external preregistration attestation.

Reproduce the fixture in a fresh directory using the pinned tokenizer assets:

```bash
python scripts/prepare_activation_history.py --model-dir local-state/pythia --output reports/history-fixture
```

Run the frozen experiment without overwriting its output:

```bash
python experiments/activation_history_probe.py --model-dir local-state/pythia --output reports/history-reproduction
```

Check either the recorded result or your reproduction without importing model
code or installing Torch/NumPy:

```bash
python -S scripts/audit_activation_history.py --result results/activation-history --output reports/runs/history-audit.json
```

The output path must be new. This checks file pins, state/receipt chains,
sufficient-statistic arithmetic and all 12 gates. It cannot independently
recompute unpublished raw parameter/gradient/moment arrays, native delta norms
or the dense cumulative-displacement denominator. Re-execute the frozen model
probe for numerical reproduction; a receipt audit alone is not a model run.

See [protocol](protocol.json), [manifest](manifest.json),
[results](../../results/activation-history/report.md) and the
[research review](../../research/2026-10-16-short-history-update.md).
