# LayerNorm saved-operand isolation

This protocol follows the failed CE-save dominance diagnostic in
`../activation-gradient/`. Every arm now computes cross-entropy outside all
saved-tensor hooks. At identical pretrained parameters and first training
batches, compare dense, model int8 saves, and model int8 saves with all saves
created inside named `torch.nn.LayerNorm.forward` calls retained exactly.

Temporary instance-forward wrappers identify execution scope, rather than
guessing normalization operands from their shapes. They invoke the unchanged
original bound method and restore instance attributes in `finally`. Each named
LayerNorm has its own saved-tensor inventory; other model saves are counted
separately. CE's unhooked saves are not counted, so these inventories are not
total backward memory or peak allocation measurements.

The predeclared gate asks whether exact LayerNorm saves halve full-parameter
gradient relative L2 error without reducing cosine in all three seed batches.
It tests this implementation boundary at these fixed points. Neither success
nor failure establishes a universal cause, faithful optimizer updates, trained
quality, practical savings, AttnRes or GPU behavior. No optimizer or holdout
forward/evaluation runs here. The shared loader validates both data splits.

Reuse the original training tokens, manifest and seven immutable Pythia model
assets. Original protocol/code is MIT; model assets retain Apache-2.0
provenance. Weights and full gradient arrays are not committed.
