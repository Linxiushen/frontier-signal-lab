# Frozen pretrained activation / autograd replay

On this CPU replay, per-step int8 packing with an identity straight-through estimator (STE) produced finite outputs and operator gradients, but increased the observed time and process lifetime peak for all three pseudoquery seeds. Saved-for-backward storage was identical to dense. This implementation therefore provides no memory or throughput benefit on the measured fixture.

The input is an authentic frozen `EleutherAI/pythia-14m` activation bank from Apache-2.0 checkpoint `cf967c0a9a04383db6f7b1108d86b2962634b4ac`. Six consistently captured **pre-block residual states**, from four 128-token windows of original repository-owned text without padding, form float32 `[6, 512, 128]` (1,572,864 bytes). These cumulative Pythia residuals are an independent operator fixture; they are not AttnRes branch outputs. See [capture manifest](../../fixtures/real-activation/manifest.json) for checkpoint assets, capture configuration, source files and exact input provenance.

The shared 128-dimensional pseudoquery is deterministic Gaussian noise divided by `sqrt(128)`, independently seeded with 11, 29 and 47. It is never learned or updated. For each token, the operator takes a depth softmax of `RMSNorm(bank) dot query`, then mixes the unnormalized bank vectors; RMSNorm epsilon is `1e-6`. The scalar diagnostic loss is `mean(output**2)`. It has no language-model quality interpretation.

The int8 route recomputes per-depth/token `maxabs/127` scales and rounded/clamped codes on **every** forward step, replaces a zero scale with one, and materializes a float32 decoded bank. Codes and scales are detached. `decoded = bank + (dequantized - bank).detach()` explicitly supplies an identity surrogate gradient. Reported bank gradients belong to detached leaf copies of the captured bank; no gradient reaches the pretrained backbone and no optimizer runs.

All outputs and gradients were finite. Dense outputs passed an independent float64 NumPy reference at `rtol=2e-5, atol=2e-6`; observed maximum absolute differences were `2.50e-7`–`5.27e-7`. Relative L2 deviations of int8 from dense are:

| Pseudoquery seed | Output | Bank leaf gradient | Query gradient |
| --- | ---: | ---: | ---: |
| 11 | 0.8952% | 1.2820% | 0.6152% |
| 29 | 0.9030% | 1.0587% | 0.4634% |
| 47 | 0.8659% | 1.4719% | 0.4416% |

The observed runtime was Windows AMD64, Python 3.12.14, NumPy 2.3.5 and PyTorch 2.9.1+cpu, with one torch intra-op/inter-op thread and thread environment limits of one. Each method/seed used a fresh process: six processes total, each with one warmup and three timed steps. The three steps reuse identical inputs without parameter updates; they are **not independent process replicates**. The table reports componentwise medians in milliseconds, which need not add to the median total.

| Seed | Method | Pack | Decode + STE | Readout | Forward + loss | Backward | Forward + backward | Process peak MiB |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 11 | Dense | 0 | 0 | 0.819 | 0.874 | 1.908 | 2.782 | 207.91 |
| 11 | Int8 + identity STE | 2.077 | 1.275 | 1.339 | 4.817 | 3.790 | 7.987 | 210.86 |
| 29 | Dense | 0 | 0 | 0.743 | 0.787 | 1.811 | 2.620 | 207.88 |
| 29 | Int8 + identity STE | 0.901 | 0.527 | 0.764 | 2.238 | 1.816 | 3.961 | 210.49 |
| 47 | Dense | 0 | 0 | 0.927 | 0.974 | 2.158 | 3.128 | 208.68 |
| 47 | Int8 + identity STE | 0.970 | 0.603 | 0.861 | 2.488 | 1.945 | 4.359 | 210.67 |

The Windows process peak is `GetProcessMemoryInfo.PeakWorkingSetSize`, a lifetime high-water mark including imports, input validation/copies, warmup, timed steps, one extra untimed saved-tensor inspection, and output persistence. It is not an isolated operator allocation peak. The original NumPy bank and float32 autograd leaf remain resident in both methods; int8 also materializes a decoded float32 bank. Timing and peak observations are machine-specific and do not establish a general speed ratio or statistical significance.

Saved-tensor hooks run in the separate untimed step. Both methods, for every seed, recorded **6,603,264 logical saved bytes including duplicate saves**, and **3,432,960 unique backing-storage bytes across six storages / ten saves**. The storage union includes aliases of live inputs and each alias's entire backing storage. These are inventories, not process-memory measurements or additional allocations; they cannot be added to the OS peak. Smaller int8 code storage alone does not show training-memory savings.

A prior pilot overlapped a recapture task. Its timing and memory observations were excluded. The published measurement reran the same experiment sequentially after capture and tests exited. Its complete stable numerical payload SHA256 exactly matches the pilot, including output/gradient hashes and saved-tensor inventories; variable timing/memory data have a separate observation hash. No pilot timing was averaged into this table.

Replay the persisted trace without downloading model weights or installing Transformers:

```shell
python -m pip install numpy==2.3.5
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.9.1+cpu
python experiments/real_activation_autograd_probe.py --trace fixtures/real-activation/bank.npz --manifest fixtures/real-activation/manifest.json --output reports/runs/my-activation-replay --seeds 11 29 47 --warmup 1 --repeats 3
```

Use a fresh output directory. The command fails if optional PyTorch is absent; it never substitutes synthetic input. Model recapture separately used Transformers 4.57.3 and safetensors 0.7.0. The six focused tests check independent NumPy output, double-precision dense gradcheck, the STE derivative against dense evaluated at decoded values, per-step repacking, saved-storage deduplication, trace-hash tampering and bounded preallocation, plus a fresh-worker test fixture. The full repository suite passed 89 tests in the configured environment. Exact numerical hashes document this runtime; cross-platform replay is assessed with numerical tolerance, not exact float hashes.

The published [machine-readable report](report.json) separates stable numeric results from variable observations. Its SHA256 records are:

| Record | SHA256 |
| --- | --- |
| Raw bank, little-endian float32 C-order bytes | `587f34ed10ef6f1c602fe773818f93daabf5924acce351af55880eacbe601433` |
| Trace NPZ file | `e536d4a3543b1a0ba26bd12b71e794f17fe7989873ff9e88d79094184cdcfe53` |
| Trace manifest file | `160ac875f1b353e64b862dc5ddb7af615977c8316ca15020ab1979f562e82553` |
| Canonical capture configuration | `c64d5d716658c2dd14423c89c4171c3bedbbe19d9bbf18bbb9ae67803d6632e3` |
| Canonical operator configuration | `9144df2d079d44f7e20e0a6adc8ac0e4f408af18353ad7c52b6093aa3a2afc69` |
| Operator source | `8821c7f0e3bd0f452d9785b635c7a8fb49e7e8994e3bb5c04caebe58384db54c` |
| Stable numerical payload | `a61b7dabb97e9e38f3016e628d9de4129d9d2919741b1ca8fe4f40373f2b07c5` |
| Complete observation payload, excluding its own hash field | `e9a0e0ac75d64e1134ddcf73a608b49fd78f10a702171fab11ab95e46f1e4d68` |
| Published report file bytes | `e1af02dcd4d5316c1aab0ad8d83db516037d911f50523f6f01ff83561c159e52` |

This clears an actual-activation/operator-backward diagnostic gate. Matched-budget model training, learned queries, faithful quantization gradients, model quality, deeper-model generalization, GPU savings and upstream AttnRes reproduction remain untested.
