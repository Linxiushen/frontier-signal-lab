# AdamW update fidelity protocol

This single predeclared diagnostic adds a real AdamW first step to the existing three attention save policies. It keeps the pretrained model fixed, applies each gradient to disjoint parameter and zero-state clones, and compares actual float32 parameter changes to dense changes. Every native parameter/moment update is checked against independent NumPy equations with explicit float32 rounding bounds.

The protocol is written before implementation, tests, or new model execution. The three paired synthetic batches are the same fixed batches as the attention diagnostic. They overlap and contain 320 unique target positions.

All three batches must meet three conditions: update relative L2 error at most 0.10; update cosine at least 0.99; and error at most half the norm-only baseline with cosine no worse. A valid failure is published. Broken controls stop execution without a completed result.

AdamW uses learning rate 1e-4, betas (0.9, 0.999), epsilon 1e-8 and decoupled weight decay 0.01 for every parameter. Previous training used weight decay zero; this diagnostic does not revise that training result. There is no clipping, schedule, warmup, holdout evaluation or accumulated optimizer state. Stateful AdamW remains a later, separately declared question.

The comparison retains dense gradients/updates and creates weight/moment clones and NumPy references. Their cost makes runtime and memory descriptive. Passing this diagnostic does not establish training quality, convergence, lower cost, GPU performance, AttnRes or learned routing.

After the new implementation is frozen, run the script with the pinned local model, data, training manifest, this protocol and a fresh output directory. A different runtime must first replay the existing attention protocol and pass that same-runtime report through --attention-reference. The default reference is the untouched committed attention report.
