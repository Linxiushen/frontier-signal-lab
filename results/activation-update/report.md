# AdamW first-step update fidelity

One fixed-point diagnostic; zero optimizer state and weight decay 0.01. The model remains unchanged.

| Seed | Norm-only update relative L2 | Attention-preserved update relative L2 | Treatment cosine | Error ratio | Joint gate |
| --- | --- | --- | --- | --- | --- |
| 11 | 0.486322468 | 0.119295001 | 0.992884281 | 0.245300206 | False |
| 29 | 0.492400504 | 0.11672208 | 0.993187794 | 0.237047036 | False |
| 47 | 0.489170148 | 0.108970792 | 0.99406273 | 0.222766644 | False |

All three batches pass: **False**.

All native parameter/moment updates passed independent NumPy rounding bounds. All 76 gradient records matched the same-runtime attention diagnostic in every arm. The 3 batches overlap (320 unique target positions).

The joint gate requires treatment update relative L2 <= 0.10, cosine >= 0.99, and at most half the norm-only error with cosine no worse in every batch. A failed scientific gate is retained without retuning.

No accumulated optimizer state, holdout evaluation, convergence, training quality, lower cost, GPU or AttnRes conclusion. Full parameter/moment clones and retained dense references add diagnostic cost.

Stable SHA-256: `7774616b29f3cf7756b328a00f78add1a48fde874dae98690d1f1da962ae0c06`
Observation SHA-256: `63038ac915790b29cbedd04b0f170482611ed71a46a99e0aabcc9f5f39d6ec93`
