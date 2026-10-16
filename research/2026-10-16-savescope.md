# From a gradient result to a usable audit tool

SaveScope turns this repository's saved-operand diagnostics into an installable
CPU toolkit and a portable interactive report. The new research measurement is
one predeclared **fresh-state AdamW first-step** diagnostic, not a new training
run. The model itself remains fixed; optimizer steps operate on detached clones.

## The useful failure

Keeping the six actual attention-forward save scopes exact previously passed
the gradient intervention gate on all three batches. That did not establish
faithful optimizer updates. The next protocol was written at
2026-10-16T09:12:01.039779Z, before implementation, tests, or new model execution.

| Seed | Gradient cosine | Actual update relative L2 | Actual update cosine | Joint update gate |
| --- | --- | --- | --- | --- |
| 11 | 0.999168945 | 0.119295001 | 0.992884281 | Failed |
| 29 | 0.999173077 | 0.116722080 | 0.993187794 | Failed |
| 47 | 0.999405660 | 0.108970792 | 0.994062730 | Failed |

The joint gate required error <=0.10, cosine >=0.99, and at most half the
norm-only baseline error with cosine no worse, in every batch. Only the absolute
error condition failed. The attention-preserved intervention improved update
error relative to the norm-only baseline, but all three joint gates failed.
No thresholds or policies were changed after observing this result.

This uses the identical checkpoint, training batch schedule, exact CE, 13 actual
LayerNorm scopes and six actual attention scopes from the previous diagnostic.
All 76 parameter-gradient records match that same-runtime diagnostic exactly.
Nine native AdamW steps used fresh zero moments, lr1e-4, betas(.9,.999), eps1e-8
and weight decay0.01. Independent NumPy equations checked parameters, moments
and step counters within explicit float32 rounding bounds. The original model
parameters remained unchanged. The six optimizer contract tests include wrong
epsilon placement, coupled decay, and `grad=None` versus explicit zero controls.

See the [protocol](../fixtures/activation-update/protocol.json),
[result](../results/activation-update/report.md), and
[raw records](../results/activation-update/report.json).
Stable result SHA256:
`7774616b29f3cf7756b328a00f78add1a48fde874dae98690d1f1da962ae0c06`.

## Product behavior

The package exposes `audit(model, forward_fn, loss_fn, ...)`, an offline `replay`,
and an actually executed `demo`. The report compares both gradients and actual
parameter changes and filters the worst individual parameters. Replay bundles
only metrics and provenance, not weights or gradients. The generic API has its
own engineering contract tests; it is independent of the frozen experiment
implementations. A tiny-demo output is not a repetition of the Pythia experiment.

The product entry point is [SAVESCOPE.md](../SAVESCOPE.md). Channel-specific
materials and verified channel limitations are in
[distribution](../distribution/README.md). Preparation, repository publishing
and actual external posting must be distinguished in any status update.

## Interpretation and next gate

The observation supports auditing actual updates even after a close gradient
cosine. Fresh-state AdamW's sign/epsilon sensitivity is an explanation to test,
not a measured coordinate-level causal attribution here. Three batches overlap
and have 320 unique target positions; they are not independent statistical
replicates. The broad attention scope does not isolate one saved operand.

The next scientific gate is separately predeclared **accumulated-state** update
fidelity with matched cloned states and an independent update reference. It has
not been run. Do not retune these three batches or start another training run
based solely on the gradient result. Larger data, general rotary backward,
learned depth routing/AttnRes, matched-time training, sealed quality evaluation,
and measured GPU allocator/throughput checks remain open.

Preserve the earlier [negative training result](../results/activation-training/report.md):
higher CPU time and process peak memory, with both synthetic holdouts regressing.
No novelty, speed, memory, quality, affiliation, endorsement or researcher
attention claim follows from this release.
