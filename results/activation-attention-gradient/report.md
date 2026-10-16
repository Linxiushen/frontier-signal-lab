# Actual attention-forward save diagnostic

All3 predeclared half-error/cosine gates passed. The experiment retains exact CE
and all saves from13 actual LayerNorm forward scopes in every arm, then preserves saves within6 actual
GPTNeoXAttention forwards. Full-scope sensitivity does not identify an operand,
faithful optimizer updates, training quality or practical memory savings.

| Seed | 仅保留 norm 相对 L2 | 再保留 attention 相对 L2 | 后者/前者 | Cosine：原 → 保留 attention | 判据 |
| --- | ---: | ---: | ---: | --- | --- |
| 11 | 7.613840 | 0.040762 | 0.005354 | 0.159637 → 0.999169 | 通过 |
| 29 | 7.699570 | 0.040662 | 0.005281 | 0.155752 → 0.999173 | 通过 |
| 47 | 4.053040 | 0.034482 | 0.008508 | 0.253355 → 0.999406 | 通过 |

Three fresh sequential CPU workers,3policies each;fixed pretrained Pythia-14m
revision`cf967c0a9a04383db6f7b1108d86b2962634b4ac`,float32,eager,1thread.
First training batches[3,1]/[5,3]/[7,0],128targets each,320unique overlapping
positions across batches. No optimizer,holdout forward,tuning or second experiment.
Each of76 parameter tensors/14,067,712elements has finite gradients. Identical
logits/loss and immutable parameter hashes hold. Analytical CE controls pass.
Dense and norm-only full per-parameter metrics/hashes exactly match the prior
LayerNorm diagnostic on this platform. Per-module save/restore coverage is in JSON.

Design registered`2026-10-16T08:41:03.534775+00:00`;source/protocol frozen
`2026-10-16T08:45:40.125525+00:00` before tests or model comparison. Parent comparison
`2026-10-16T08:50:00.317167+00:00`–`2026-10-16T08:50:43.942540+00:00`.
Six new tests and full113 tests passed without skips. Independent result review:
`7613`checks,without recomputing gradients.

```bash
python experiments/activation_attention_gradient_probe.py --model-dir local-state/models/pythia-14m-cf967c0 --data fixtures/activation-training/data.json --manifest fixtures/activation-training/manifest.json --protocol fixtures/activation-attention-gradient/protocol.json --output reports/runs/my-attention-gradient
```

Use a fresh output directory and the pinned CPU dependencies/model assets from
the repository README. Source/config/data/worker hashes are in[report.json](report.json).
Protocol SHA256:`46d29186eecdb17369004bac921cc65a8077086779dc0b79961b34f57e9096e3`.
Stable result SHA256:`b5051eae772617e4fc30a18727936cb74fc30c3629c670f83526691edf033e66`.
Observation SHA256:`d1c12347cca354944905083d55714f0d474a6c2e46570681a3f3831a45be6766`.

Scope includes QKV,RoPE,causal attention and output projection. Independent
NumPy tiny-attention VJP covers input and both projection weights/biases with
identityRoPE,not a general rotary reference or full-network proof. Split save
inventories exclude CE and are not total storage or peak allocation. Prior
training time/peak and holdout negatives remain; next gate is actual optimizer
update fidelity before more training. No GPU,AttnRes,learned-routing or novelty claim.
