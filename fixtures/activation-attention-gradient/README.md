# Actual attention-forward saved operands

This diagnostic follows failed CE-save and LayerNorm-save half-error gates.
Every arm keeps CE outside all saved-tensor hooks and retains exact saves from
all13 actual `torch.nn.LayerNorm` forwards. At the same pretrained Pythia-14m
parameters and fixed first training batches, compare dense, the prior
norm-preserved int8 baseline, and int8 with exact saves from all6 actual
`GPTNeoXAttention.forward` executions.

Temporary instance wrappers select the actual attention class, independent of
module names or tensor shapes. All arms receive identical instrumentation;
nested hooks retain or compress the attention-forward saves as prescribed.
The scope includes QKV projection, RoPE, causal attention and output projection.
It cannot attribute a result to a single operation or operand. Original instance
attributes are restored in `finally`. Named LayerNorm and attention inventories
are separate from other model saves; unhooked CE saves are excluded. These
inventories are not total backward storage or measured peak memory.

The predeclared gate requires full-gradient relative L2 error to halve without
lower cosine in all3 overlapping batches. Undefined, zero or nonfinite baseline
errors fail the gate. Controls require exact logits/loss, unchanged parameters,
all76 finite parameter gradients, analytic CE agreement, scope coverage and
unchanged dense/norm-only gradient records versus the previous diagnostic.
An independent NumPy tiny-attention forward/VJP checks input and QKV/output
projection parameter gradients, using the real interleaved QKV layout, identity
RoPE, causal masking and zero dropout. It validates a local reference, not the
entire pretrained network.

No optimizer, holdout evaluation, tuning or efficiency comparison runs here.
The3 first batches share examples and cover320 unique target positions; they
are not statistical replicates. Success or failure does not establish trained
quality, faithful optimizer updates, practical memory savings, GPU performance,
AttnRes, learned routing or novelty. Reuse the pinned training tokens, manifest
and7 hash-verified model assets. Original code/protocol MIT; Pythia assets
Apache-2.0. Weights and full gradient arrays are not committed.
