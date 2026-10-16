# Full-model activation-compression training diagnostic

Backward-only int8 saved-tensor compression reduced the retained activation-payload inventory by **54.01%**, but the measured CPU training loops took **1.47–1.52 times** as long and process lifetime peaks increased by **23.22–24.86 MiB**. Both methods worsened the fixed holdout NLL from the pretrained baseline. This simple compression policy does not demonstrate a practical training-memory, throughput or model-quality benefit on this diagnostic.

This is actual full-model causal-language-model fine-tuning of Apache-2.0 `EleutherAI/pythia-14m`, revision `cf967c0a9a04383db6f7b1108d86b2962634b4ac`, using local pinned safetensors assets. All **14,067,712 parameters** were trainable. Every one of the 144 training steps checked finite gradients for all 76 parameter tensors and finite updated parameters. Each worker's final global parameter hash changed. This verifies full gradient coverage and an actual model update; it does not assert a nonzero update to every individual parameter element.

The [data and predeclared manifest](../../fixtures/activation-training/manifest.json) use separate repository-original MIT synthetic prose files. Each split contains eight nonoverlapping 65-token blocks: 64 inputs predict the following 64 targets, without padding or cross-block transitions. Each worker used **24 AdamW steps × batch size 2 × 64 targets = 3,072 training target positions**, six passes over 512 unique target positions. Seeds 11, 29 and 47 determine the repeated shuffled batch schedule. Paired methods had exactly the same initial parameter hash, schedule, data hash, initial holdout NLL and first-batch forward loss.

AdamW used learning rate `1e-4`, betas `(0.9, 0.999)`, epsilon `1e-8` and zero weight decay, with no clipping, checkpointing or optimizer warmup. The model used float32 eager attention and zero dropout. Six fresh CPU processes ran sequentially, one per method/seed, with a 180-second hard training-loop timeout. All six completed; none required a retry, tuning or replacement. The fixed holdout was evaluated once before and once after training, with no intermediate holdout selection. It is a small observed synthetic diagnostic, not a sealed or never-read benchmark. The train text had previously been used for frozen activation capture.

The forward computation remains dense float32. Saved-tensor hooks compress eligible finite CPU float32 tensors with at least 256 elements, using per-last-dimension `maxabs/127` scales, round/clamp to `[-127,127]`, and a scale of one for zero vectors. They retain only newly allocated int8 codes and float32 scales for compressed tensors. Parameter-backed storage, including transposed or reshaped aliases, is excluded by backing-storage identity. Backward reconstructs the saved operands, giving **approximate parameter gradients**; there is no identity STE and no forward weight/activation quantization. The policy includes attention/MLP intermediates and CE/log-softmax saves, not just residual history.

Holdout NLL is in nats per target token; lower is better. Every evaluation scored the same 512 holdout target positions.

| Seed | Initial pretrained NLL | Dense final NLL | Int8 final NLL | Int8 minus dense |
| --- | ---: | ---: | ---: | ---: |
| 11 | 4.731054 | 6.100292 | 5.666831 | -0.433462 |
| 29 | 4.731054 | 6.068892 | 5.530739 | -0.538153 |
| 47 | 4.731054 | 6.063068 | 5.474782 | -0.588287 |

Int8 ended with a lower diagnostic NLL than dense, while both finished worse than the unmodified checkpoint. The changed optimization trajectory, slower fitting or other approximation effects could explain the difference; this experiment does not identify a cause or establish a generalization gain. The last observed training-batch NLL was `0.539–0.660` for dense and `2.722–3.413` for int8; these are batch observations, not final full-training-set evaluations. Int8 parameter-gradient L2 maxima reached `1,047–1,888`, versus `62–305` for dense. Finite gradients therefore do not establish gradient fidelity.

The runtime was Windows AMD64, Python 3.12.14, PyTorch 2.9.1+cpu, Transformers 4.57.3 and NumPy 2.3.5, with torch intra-op/inter-op and numerical-library thread limits set to one. Component values below are medians of the 24 changing training steps inside each worker; they are not independent process replicates or confidence intervals, and componentwise medians need not add to the median total. Pack and unpack callback times are already included in forward and backward respectively.

| Seed | Method | Loop seconds | Pack ms | Forward + CE ms | Unpack ms | Backward ms | AdamW ms | Instrumented step ms | Lifetime peak MiB |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 11 | Dense | 7.997 | 2.599 | 44.508 | 0.153 | 65.520 | 70.817 | 322.444 | 579.95 |
| 11 | Int8 saved | 11.782 | 137.178 | 178.568 | 25.973 | 91.196 | 71.476 | 482.765 | 604.80 |
| 29 | Dense | 7.835 | 2.576 | 43.801 | 0.146 | 66.359 | 70.535 | 320.396 | 580.77 |
| 29 | Int8 saved | 11.849 | 136.956 | 177.884 | 26.359 | 91.014 | 70.541 | 480.188 | 604.91 |
| 47 | Dense | 7.902 | 2.597 | 44.635 | 0.147 | 65.543 | 70.060 | 321.194 | 580.82 |
| 47 | Int8 saved | 12.004 | 139.267 | 180.195 | 26.282 | 92.558 | 72.111 | 486.782 | 604.04 |

The dense route also runs identity saved-tensor hooks and metadata accounting. Training-loop wall time includes batch selection, `zero_grad`, codec construction, numerical checks and memory observations. Per-step timing starts after `zero_grad` and codec construction. Its total includes gradient norms and finite checks: roughly 72–74 ms before AdamW and 68 ms after AdamW at the medians. This is an instrumented comparison, not optimized framework throughput. Model loading and the two holdout evaluations are outside the loop budget; the first step includes AdamW state initialization. Training tokens and updates are matched; **wall-clock budgets are measured, not matched**.

Each step recorded 180 saves: 51 parameter-storage exclusions, 100 eligible float32 saves, two integer saves and 27 small/scalar exclusions. Int8 compressed and reconstructed all 100 eligible saves. The stable shape audit includes two `[128,50304]` eligible saves from the loss path. All steps/methods kept the same exclusion rules.

| Per-step inventory | Dense bytes | Int8 saved bytes |
| --- | ---: | ---: |
| Original logical saved bytes, counting duplicate saves | 90,058,756 | 90,058,756 |
| Retained logical payload bytes, counting duplicate saves | 90,058,756 | 45,476,868 |
| Unique retained activation backing storage | 32,590,852 | 14,989,316 |
| Unique retained parameter backing storage, excluded from compression | 30,487,552 | 30,487,552 |

Storage inventories include full backing storage of aliases and exclude optimizer state and unrelated live tensors. Original-source pointer unions can reuse addresses after compression and are diagnostic only. The OS measurement is Windows `GetProcessMemoryInfo.PeakWorkingSetSize`: a lifetime high-water mark including imports, model, gradients, AdamW, holdout evaluation, hashing and finite/norm instrumentation. It is not an isolated training allocation peak. Smaller saved payloads did not translate into a smaller measured process peak in this run. No GPU-memory conclusion follows.

[ActNN: Reducing Training Memory Footprint via 2-Bit Activation Compressed Training](https://arxiv.org/abs/2104.14129), Chen et al. (2021), predates this experiment and studies randomly quantized saved activations, gradient variance and mixed-precision policies. This deterministic symmetric int8 hook is an original minimal diagnostic in that established area; it does not reproduce ActNN's method, theory or reported results. It also does not implement AttnRes, learned depth queries or residual-bank compression specifically.

Replay requires the separately downloaded immutable local model assets; it performs no network access or remote-code loading. Install the optional versions from [requirements-real-activation.txt](../../requirements-real-activation.txt), including the CPU torch wheel from its official index, then run from the repository root:

```shell
python experiments/activation_training_probe.py --model-dir local-state/models/pythia-14m-cf967c0 --data fixtures/activation-training/data.json --manifest fixtures/activation-training/manifest.json --output reports/runs/my-activation-training --seeds 11 29 47 --steps 24 --batch-size 2 --lr 0.0001 --max-seconds 180
```

The command requires a fresh output directory and enforces the manifest's predeclared settings, data hash, tokenizer/model pins and loader-override exclusions. A timeout, nonfinite/missing gradient, invalid asset or incomplete paired worker prevents a completed report. The six focused tests cover independent quantized backward operands, exact dense forward values, parameter-alias exclusions, payload ownership, explicit next-token targets/optimizer updates, data integrity/disjointness, loader overrides and paired schedule budgets. The full suite passed 95 tests before execution. Raw per-worker records and [report.json](report.json) retain every step; no rerun or parameter selection was made after seeing these results.

| Provenance record | SHA256 |
| --- | --- |
| Predeclared data file | `321e3c8113a5490f078c9b6c8f0d8dc9877e52d2b47a1295669b28814d820580` |
| Predeclared manifest file | `1ef9779024091875d28959165c84c7ac390875df3bb9ea8b5a892dc43db17280` |
| Predeclared design configuration | `6c0ed010bb7a37507b44ffb54f9fd3788fb2c4241ad72886e22d9a9779ff39d1` |
| Executed configuration | `8b019eb9ccc7ab950e4834101d0e7eb2113236358b3b58e6fe5ea8069c4ca29c` |
| Training experiment source | `3bf8279b527ac71595157f3ce5539ba09f16df8a6a7fcd51565b98315babe74c` |
| Common initial parameter state | `20db486869e839f80554c84da5d405b831de170a49841a85b3af3c530bcabd04` |
| Stable numerical payload | `3b23184bec741fa44ac03ed884b9948f005f667074a966fe548ed9cf2713f1c1` |
| Observation payload, excluding its own hash | `f2b6fbf04ae7f7ec7fc4738a4a5c92de71e4dd7db4699b3c44782c00815ac086` |
| Published report file bytes | `85a8e3bf0b9b828ca8ce460218ef530de9788799b91634ccd713f4ab6a6a4418` |

This completes a bounded full-backbone optimizer and matched-token cost diagnostic. Equal-wall-time comparisons, natural-text evaluation, learned depth routing, training at useful scale and GPU measurements remain open gates. No practical benefit or new research priority is inferred from the payload-byte reduction alone.
