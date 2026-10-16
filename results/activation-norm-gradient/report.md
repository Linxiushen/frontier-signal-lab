# Fixed-parameter LayerNorm saved-operand diagnostic

The predeclared LayerNorm-save dominance gate **failed in all three seed batches**. Preserving every save created inside the model's 13 named `torch.nn.LayerNorm.forward` calls left full-parameter gradient relative-L2 errors at **4.053–7.700**, compared with **4.038–7.688** when their eligible saves were also compressed. The error ratios were **1.0015–1.0037**, above the required maximum of 0.5, and cosine became slightly worse in every batch. This intervention did not repair the large gradient discrepancy at these fixed points. It does not establish that normalization saves are universally harmless, identify the remaining operation responsible, or explain an optimizer trajectory.

This follows the [failed CE-save diagnostic](../activation-gradient/report.md). It uses the same Apache-2.0 `EleutherAI/pythia-14m`, immutable revision `cf967c0a9a04383db6f7b1108d86b2962634b4ac`, with seven local hash-verified model/tokenizer assets, including safetensors weights. There are **no optimizer steps, parameter updates or holdout forward/evaluation**. The shared loader validates both committed data splits; model computation uses only training tokens. Every backward produced finite gradients for all **76 parameter tensors / 14,067,712 elements**.

The [protocol](../../fixtures/activation-norm-gradient/protocol.json) was frozen at **2026-10-16 06:44:27.234292 UTC**, before tests and actual model comparison. Three fresh CPU workers ran sequentially with seeds 11, 29 and 47, selecting `batch_schedule(8, 24, 2, seed)[0]`. Their block pairs were `[3,1]`, `[5,3]` and `[7,0]`. Each policy scores **128 next-token targets** per worker from two 65-token blocks, with 64 input tokens predicting positions 1–64. Across batches there are 384 scored positions per policy but **320 unique target positions**, because block 3 is reused. These are overlapping fixed batches, not statistical replicates.

Every worker used this fixed order at identical pretrained weights:

1. `dense`: identity saves throughout model forward; CE is outside all hooks. Detached cloned parameter gradients become the reference.
2. `model_saved_int8`: the existing int8 codec covers eligible model saves, including those made by LayerNorm; CE remains exact.
3. `model_except_norm_saved_int8`: the same codec covers other eligible model saves, while saves made inside each named LayerNorm forward remain exact; CE remains exact.

The unchanged codec accepts finite CPU float32 saves with at least 256 elements, excludes parameter-backed storage aliases, and uses symmetric per-last-dimension max-absolute scaling with round/clamp to int8. Forward values remain dense float32. Backward uses reconstructed saved operands without an identity STE.

All three policies instrument actual `torch.nn.LayerNorm` modules through temporary instance-forward wrappers. Each wrapper calls the original bound method under a nested saved-tensor hook; the inner hook selects the policy at save time. The wrapper is restored in `finally`, before CE and backward. Scope follows actual module execution rather than a tensor-shape heuristic. It includes six layers' input and post-attention LayerNorms plus the final LayerNorm, and does not cover every possible normalization operation.

The wrapped `dense` and `model_saved_int8` baselines **exactly match their earlier unsplit counterparts** for every seed: logits hashes, forward losses, observed logits-gradient hashes, and the complete per-parameter gradient comparisons/hashes are identical. This checks that splitting the instrumentation did not change the reference computation or int8 baseline.

Let `g` be the dense parameter gradient and `q` a candidate. Relative L2 is `||q-g||₂ / ||g||₂`, cosine is `dot(g,q)/(||g||₂||q||₂)`, and maximum error is `max(abs(q-g))`. These are full ordered-vector metrics accumulated from per-parameter float64 sums. They are not averages of per-parameter ratios. The raw [report.json](report.json) retains every parameter's shape, element count, hashes, squared norms, dot product and errors. Dense self-comparisons have exactly zero difference and cosine one to numerical precision.

| Seed | Policy | Dense gradient L2 | Candidate gradient L2 | Relative L2 error | Cosine | Maximum absolute error |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 11 | Model saved int8 | 63.105356613 | 485.779906509 | 7.602381606 | 0.159896898 | 28.718709961 |
| 11 | Exact LayerNorm saves | 63.105356613 | 486.492458924 | 7.613840378 | 0.159637405 | 28.846044555 |
| 29 | Model saved int8 | 63.871464856 | 496.943464865 | 7.687965395 | 0.156117654 | 25.621435359 |
| 29 | Exact LayerNorm saves | 63.871464856 | 497.667065691 | 7.699570461 | 0.155752231 | 25.722194865 |
| 47 | Model saved int8 | 62.358022957 | 260.353763969 | 4.038287820 | 0.254370119 | 13.574050188 |
| 47 | Exact LayerNorm saves | 62.358022957 | 261.233786295 | 4.053039952 | 0.253355384 | 13.658115625 |

The gate required **norm-preserved / model-saved relative-L2 error ≤ 0.5, with cosine no worse, in every seed**. A zero or undefined denominator also fails; neither occurred here.

| Seed | Error ratio | Norm-preserved cosine no worse? | Gate |
| --- | ---: | --- | --- |
| 11 | 1.001507261 | No | Failed |
| 29 | 1.001509511 | No | Failed |
| 47 | 1.003653066 | No | Failed |

All 13 named LayerNorms were called once per policy, with five save calls and five unpack calls apiece. Each had one eligible activation save, two excluded parameter-storage saves, and two saves below the size/shape threshold. The baseline compressed and decoded all 13 eligible norm saves; the treatment retained them exactly. The other model scope was identical across the two int8 arms: 85 eligible saves, all compressed and decoded.

| Policy | Other-model save / unpack calls | Other-model eligible / compressed saves | LayerNorm save / unpack calls | LayerNorm eligible / compressed saves |
| --- | ---: | ---: | ---: | ---: |
| Dense | 111 / 111 | 85 / 0 | 65 / 65 | 13 / 0 |
| Model saved int8 | 111 / 111 | 85 / 85 | 65 / 65 | 13 / 13 |
| Exact LayerNorm saves | 111 / 111 | 85 / 85 | 65 / 65 | 13 / 0 |

These are per-worker hook event counts, not distinct tensors or total backward memory. They split LayerNorm saves from the outer model inventory and exclude every unhooked CE save. Retained dense gradient references and temporary arrays also affect allocation. The counts support no peak-memory, practical savings or efficiency claim.

All three policies produced **exactly identical logits, forward loss and observed logits-gradient hashes** within each seed. Forward NLLs were `5.246664524078369`, `5.782718658447266` and `5.636452674865723`. The independent loss-boundary control compares the observed gradient with `(softmax(logits) - onehot(target)) / 128`. All policies passed the fixed analytic relative-L2 tolerance of **1e-5**: errors were `2.138418527e-8`, `2.135782095e-8` and `2.455409686e-8` for the three seeds, with maximum elementwise error `4.656612873e-10`. Observed row-sum maxima were `2.538091952e-7`, `2.538091952e-7` and `2.259326675e-7`; float32 rounding leaves small residuals even in the analytic control.

Every method cleared gradients before backward. Dense references were detached clones. Every before/after parameter hash equaled the shared pretrained hash `20db486869e839f80554c84da5d405b831de170a49841a85b3af3c530bcabd04`. Finite gradients and exact forward/CE controls do not imply that the approximate parameter gradients are faithful.

Workers' comparison loops ran at `06:46:11.433138–06:46:15.035065`, `06:46:25.336270–06:46:29.027887` and `06:46:39.148062–06:46:42.822666 UTC` on 2026-10-16. Their observed loop times were 3.603, 3.692 and 3.674 seconds. Each worker ran once, with a 180-second loop watchdog after model loading and a 300-second parent subprocess cap. Fixed order, instrumentation and retained references make timing descriptive only.

Runtime was Windows AMD64, Python 3.12.14, torch 2.9.1+cpu, NumPy 2.3.5 and Transformers 4.57.3; CPU float32 eager attention, zero dropout, one numerical-library/torch thread and deterministic algorithms. The six focused tests and full **107-test** suite passed before the actual comparison, without skips or source/protocol changes. Tests include an independent NumPy LayerNorm forward/VJP calculation, exact wrapped-versus-unsplit baseline gradient hashes, restoration after successful and failing forwards, repeated backward without accumulation, scope/provenance rejection and failed/degenerate gate controls. There was no actual-model retry, tuning or result selection.

To reproduce, obtain the seven pinned public model assets using [download_pythia.py](../../scripts/download_pythia.py) and the optional versions in [requirements-real-activation.txt](../../requirements-real-activation.txt), including the CPU torch wheel from its official index. The comparison itself uses offline local loading, rejects loader overrides, and performs no downloads or remote-code execution. From the repository root, choose a fresh output directory:

```shell
python experiments/activation_norm_gradient_probe.py --model-dir local-state/models/pythia-14m-cf967c0 --data fixtures/activation-training/data.json --manifest fixtures/activation-training/manifest.json --protocol fixtures/activation-norm-gradient/protocol.json --output reports/runs/my-activation-norm-gradient
```

| Provenance record | SHA256 |
| --- | --- |
| Predeclared protocol file | `048f232f2d5367bbe548ccc334c81903db14d3d950bfb4ca1ec8a4703d8e9869` |
| Configuration | `f069874076035b8301168f572a98b3e7b8408a244df90f843391bdcef135e1de` |
| Data file | `321e3c8113a5490f078c9b6c8f0d8dc9877e52d2b47a1295669b28814d820580` |
| Training manifest file | `1ef9779024091875d28959165c84c7ac390875df3bb9ea8b5a892dc43db17280` |
| Frozen experiment source | `bdf88b38aaf338cd4578c520731b822f02cb10c403dd23fc70f8089a15131ba1` |
| Frozen test source | `598752baae9b258fecf3de8dd12a594a16dea2c12e9ae859c96b08bb0fe620c5` |
| Stable numerical payload | `5bfdec9147453be22eb53d6e967d243d3beba7bea1334c598a287eccfc9461b0` |
| Observation payload, excluding its own hash | `b0ad48f4476e1cbb894a755ad5a22b1d061da60b4cce5127af802adff5a538dc` |
| Published report JSON file bytes | `3b04e1f200735ed4db302da33f4da10c6fbd3656acd5e2feaa90738224a43c2f` |

The finding is confined to this named-module save intervention at three overlapping synthetic-prose batches and one pretrained checkpoint. Interactions between approximate operands can cancel or reinforce errors, so this negative intervention cannot assign a universal cause or exonerate an individual operand. It tests no optimizer-update fidelity, trained language quality, useful-scale deployment, GPU behavior, AttnRes or learned depth routing. Activation-compressed training is established related work, including [ActNN](https://arxiv.org/abs/2104.14129); this is a bounded diagnostic rather than a new algorithm or reproduction of that method.
