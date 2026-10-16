# Fixed-point backward diagnostic

The protocol was written before this experiment's backward runs. It reuses the
immutable training tokens and manifest from `../activation-training/`; it does
not read the holdout split for evaluation, update parameters or select a model.
The shared data loader validates both split structures and file hashes.

Three fixed first-batch selections compare dense saved tensors, int8 saves
around model plus cross-entropy, and int8 saves around model forward only.
The latter leaves cross-entropy's saved operands exact. Normalization saves
remain compressed, so this is a loss-boundary ablation, not a normalization
study. The full pretrained weights stay unchanged between methods.

The predeclared gate requires preserving loss saves to cut parameter-gradient
relative L2 error by at least half without worsening cosine in all three
batches. Passing would support that narrow explanation at these points; failing
must be retained. Neither outcome proves training quality or practical savings.
The prior training holdout regressions remain a separate, unchanged result.

All original protocol/code uses MIT. Model assets retain the Pythia Apache-2.0
provenance and size/SHA256 pins in the real-activation fixture; weights and full
gradient arrays are not committed.
