# Original text for a bounded training-cost diagnostic

The training source is the existing original prose in
`../real-activation/source.txt` (SHA256 recorded by the preparation script).
`holdout.txt` is separate original model-written prose created before any run of
this experiment. Both use the repository MIT license. They are synthetic text,
not an independent natural-language benchmark or evidence of general capability.

The fixed tokenizer selects eight nonoverlapping 65-token training blocks and
eight nonoverlapping 65-token holdout blocks, without padding or special tokens.
Each block has64input positions and64next-token targets; the final token is
target-only. Split membership is defined by file, not a random token split.
Unused source suffixes are excluded. There is no document-boundary joining.

This fixture is intended for actual pretrained-model fine-tuning with equal
training-token budgets and a small fixed synthetic holdout evaluated before and
after training. It does not establish
equal wall-clock performance, held-out generalization beyond this artificial
sample, training efficiency at scale, GPU memory savings, or an AttnRes model.

The preparation manifest records source/tokenizer hashes, token IDs and the
predeclared run configuration. Model weights remain in the ignored local cache;
their Apache-2.0 provenance is retained in the real-activation fixture.

To reproduce training, install CPU Torch and the pinned dependencies and run
the downloader and training command in the main README. Training reads the
committed token IDs and manifest. To independently rebuild token IDs from the
two original source files, run from the repository root into a new directory:

```bash
python scripts/prepare_activation_training.py --model-dir local-state/models/pythia-14m-cf967c0 --output reports/runs/my-training-data
```

The rebuilt data bytes/hash should match this fixture. Preparation timestamps
and environment fields change the new manifest hash; do not overwrite the
original predeclared manifest or claim its preparation timestamp for a replay.
