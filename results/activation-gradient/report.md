# Fixed-parameter model/CE saved-gradient diagnostic

The predeclared loss-save dominance gate **failed in all three seed batches**. Moving cross-entropy (CE) outside the int8 saved-tensor hooks restored the logits gradient to the dense/analytic control, but left full-model parameter-gradient relative-L2 errors at **4.038–7.688**. Those errors were **0.987–1.007 times** the all-saved-int8 errors, rather than the required ratio of at most 0.5. These fixed points do not support the proposed CE-save explanation for most of the parameter-gradient error. They do not identify which remaining model operation causes it or explain the earlier training trajectory.

This is an actual backward diagnostic on Apache-2.0 `EleutherAI/pythia-14m`, immutable revision `cf967c0a9a04383db6f7b1108d86b2962634b4ac`, using local hash-verified safetensors assets. It contains **no optimizer steps, parameter updates or holdout forward/evaluation**. The shared data loader validates both committed split structures and hashes; model computation uses only the training split. All **76 parameter tensors / 14,067,712 elements** had finite gradients in all nine backward passes.

The [protocol](../../fixtures/activation-gradient/protocol.json) was frozen at **2026-10-16 04:43:13.189651 UTC**, before tests and the actual comparison. Three fresh CPU workers ran sequentially. Each selected `batch_schedule(8, 24, 2, seed)[0]` from the existing fixed training data: seed 11 used blocks `[3,1]`, seed 29 `[5,3]`, seed 47 `[7,0]`. Each policy scored the same **128 next-token targets** per worker from two nonoverlapping 65-token blocks: 64 inputs predict positions 1–64. Across seed batches there are 384 scored positions per policy, with block 3 reused; these are **320 unique target positions**, not independent data replicates.

Every worker used this fixed order at identical pretrained parameters:

1. `dense`: identity saved-tensor hooks around model forward and CE; detached cloned parameter gradients become the reference.
2. `all_saved_int8`: the existing backward-only int8 codec encloses model forward and CE.
3. `model_saved_int8`: the same codec encloses model forward only; CE is computed after leaving the hook context.

The codec eligibility and quantizer are unchanged from [the training diagnostic](../activation-training/report.md): finite CPU float32 saves with at least 256 elements, per-last-dimension symmetric max-absolute scaling, round/clamp to int8, and parameter-backed storage aliases excluded. Forward values remain dense float32; backward uses reconstructed saved operands with no identity STE. Both int8 policies still compress normalization and other model saves. All-saved compressed 100 saves; model-only compressed 98 and omitted the four CE-path saves from its hook inventory. That inventory omits the exact, unhooked CE saves and cannot represent total backward memory.

Let `g` be the dense parameter gradient and `q` a candidate. Relative L2 is `||q-g||₂ / ||g||₂`, cosine is `dot(g,q)/(||g||₂||q||₂)`, and maximum error is `max(abs(q-g))`. Values cover the full ordered parameter vector, accumulated from per-parameter float64 sums rather than averaging per-parameter ratios. The raw [report.json](report.json) also retains each named parameter's shape, element count, gradient hashes, squared norms, dot product and errors. Dense self-comparison has exactly zero difference; its cosine is one to numerical precision.

| Seed | Policy | Dense gradient L2 | Candidate gradient L2 | Relative L2 error | Cosine | Maximum absolute error |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 11 | All saved int8 | 63.105356613 | 482.428524353 | 7.549238255 | 0.160379177 | 28.379505172 |
| 11 | Model saved int8 | 63.105356613 | 485.779906509 | 7.602381606 | 0.159896898 | 28.718709961 |
| 29 | All saved int8 | 63.871464856 | 494.420753533 | 7.648299598 | 0.156609842 | 25.280105785 |
| 29 | Model saved int8 | 63.871464856 | 496.943464865 | 7.687965395 | 0.156117654 | 25.621435359 |
| 47 | All saved int8 | 62.358022957 | 263.573901054 | 4.093264807 | 0.249703692 | 12.799192667 |
| 47 | Model saved int8 | 62.358022957 | 260.353763969 | 4.038287820 | 0.254370119 | 13.574050188 |

The gate required **model-only / all-saved relative-L2 error ≤ 0.5, with cosine no worse, in every seed**. Zero/undefined denominator cases also fail the gate; none occurred here.

| Seed | Error ratio | Model-only cosine no worse? | Gate |
| --- | ---: | --- | --- |
| 11 | 1.007039565 | No | Failed |
| 29 | 1.005186224 | No | Failed |
| 47 | 0.986568915 | Yes | Failed |

The independent loss-boundary control uses mean CE's analytic derivative `(softmax(logits) - onehot(target)) / 128`. The actual diagnostic computes that formula using float32 torch softmax; the focused tiny test independently uses NumPy stable softmax. Dense and model-only observed logits-gradient relative L2 had to be at most **1e-5**. Both passed every seed, and their observed logits-gradient hashes were **identical** within each seed. All-saved discrepancy was measured rather than subjected to that fidelity rejection gate.

| Seed | Dense and model-only analytic relative L2 | All-saved analytic relative L2 | Dense/model-only observed row-sum max abs | All-saved observed row-sum max abs |
| --- | ---: | ---: | ---: | ---: |
| 11 | 2.138418527e-8 | 0.028279667 | 2.538091952e-7 | 9.496019474e-4 |
| 29 | 2.135782095e-8 | 0.023916836 | 2.538091952e-7 | 9.496019474e-4 |
| 47 | 2.455409686e-8 | 0.028002228 | 2.259326675e-7 | 8.498904660e-4 |

Dense/model-only analytic maximum elementwise error was `4.656612873e-10` for every seed, with cosine within floating-point precision of one. All-saved analytic maximum errors were `9.496505372e-4`, `9.496505372e-4` and `8.641518652e-4`, with cosines `0.999600074`, `0.999714182` and `0.999611921`. Row sums are diagnostics: even the analytic float32 vectors retain rounding residuals around `2.26–2.54e-7` with this 50,304-class output. Restoring this boundary control did not repair the much larger full-parameter gradient discrepancy.

All three policies produced **exactly identical logits hashes and forward losses** within each seed. Forward NLLs were `5.246664524078369`, `5.782718658447266` and `5.636452674865723` for seeds 11, 29 and 47. Every method cleared gradients first; dense references were detached clones, preventing accumulation or alias overwrite. All before/after parameter hashes in all three workers matched the common initial value `20db486869e839f80554c84da5d405b831de170a49841a85b3af3c530bcabd04`. This establishes the fixed parameter state and finite coverage, not faithful approximate gradients.

Comparison loops started/ended at `04:47:09.666978–04:47:13.563217`, `04:47:23.623727–04:47:27.478201` and `04:47:37.638030–04:47:41.553813 UTC` on 2026-10-16. All three completed once, with loop observations of 3.896, 3.855 and 3.916 seconds. The watchdog capped the comparison loop at 180 seconds after loading; the parent subprocess cap was 300 seconds. Dense gradient references and temporary gradient/logit arrays affect allocation and order. These times and hook inventories support **no memory or efficiency claim**.

Runtime was Windows AMD64, Python 3.12.14, torch 2.9.1+cpu, NumPy 2.3.5 and Transformers 4.57.3; CPU float32 eager attention, zero dropout, one numerical-library/torch thread and deterministic algorithms. The first pre-run full suite passed 100/101 tests: the tiny four-target analytic test asserted zero row sums with absolute tolerance `2e-8`, while float32 rounding produced `2.98023224e-8`; its independent NumPy elementwise gradient comparison already passed. Before any model experiment, only that test's row-sum tolerance changed to `np.finfo(np.float32).eps / 2` (`5.96046448e-8`). Production code, protocol, `1e-5` analytic control and dominance threshold remained fixed. The original failed log was retained; the six focused tests and full **101-test** suite then passed without skips. There was no actual-model retry, tuning or result selection.

To reproduce, obtain the seven pinned public model assets using [download_pythia.py](../../scripts/download_pythia.py) and the optional versions in [requirements-real-activation.txt](../../requirements-real-activation.txt), including the CPU torch wheel from its official index. The diagnostic itself uses offline local loading, rejects loader overrides and performs no downloads or remote-code execution. From the repository root, use a fresh output directory:

```shell
python experiments/activation_gradient_probe.py --model-dir local-state/models/pythia-14m-cf967c0 --data fixtures/activation-training/data.json --manifest fixtures/activation-training/manifest.json --protocol fixtures/activation-gradient/protocol.json --output reports/runs/my-activation-gradient
```

| Provenance record | SHA256 |
| --- | --- |
| Predeclared protocol file | `133ac86c71ef28870f7380bae55812f30a007165ae8bd2590c3485d90e432744` |
| Configuration | `7c0df9154e71da9a2a472cc07373b156f2ceb2150c6934b340202bcf73307029` |
| Data file | `321e3c8113a5490f078c9b6c8f0d8dc9877e52d2b47a1295669b28814d820580` |
| Training manifest file | `1ef9779024091875d28959165c84c7ac390875df3bb9ea8b5a892dc43db17280` |
| Frozen experiment source | `dce002c7db7aaaf7b4e75ce7be88a180857831a244f450acd793b6c3189354fd` |
| Final pre-run tests | `a8f6657bef9d81852a756c2f744046cb14f93872dc2008af4c288158f8a64566` |
| Stable numerical payload | `9d6437eb6fce77f19422733803abd077cf5bb04b8b0188ba74b5900067946606` |
| Observation payload, excluding its own hash | `8fe72f3bc6f138933e6ca488526f693c3b3ff415585ae00b6cec5c9863ee6f0b` |
| Published report JSON file bytes | `d9d02f8b503d5036bf1853d3b783a02c1980abab14bcc86489ea37e7d19abf34` |

This confines the finding to three overlapping seed batches of existing synthetic prose at one pretrained checkpoint. It isolates CE saves while leaving every other eligible model save compressed. It neither localizes the remaining error nor tests normalization exclusion, training convergence, useful-scale language quality, GPU behavior, AttnRes or learned depth routing. Activation-compressed training is established related work, including [ActNN](https://arxiv.org/abs/2104.14129); this is a bounded diagnostic, not a new algorithm or reproduction of that method.
