# Natural-text CPU training cost diagnostic

**The original run has a known invalid parent RSS observer.** Its receipt audit
can pass while the measured process is wrong. Read the
[validity supplement](../../results/activation-cost/measurement-validity.json):
native worker self-peaks remain separate observations, and actual-worker memory
cap enforcement was not established. The frozen implementation is preserved
with this failure. The commands below reproduce that original design; they do
not repair its process-identity monitoring or establish reliable memory caps.

This fixture freezes Alice's Adventures in Wonderland for training and Through
the Looking-Glass for deferred final evaluation, both by Lewis Carroll
(1832–1898). The [book 11](https://www.gutenberg.org/ebooks/11) and
[book 12](https://www.gutenberg.org/ebooks/12) catalogs describe the original
works as public domain in the USA. The exact downloaded text files retain their
complete Project Gutenberg notices, credits and license. Those source terms
apply to the books; the repository's MIT license applies to original tooling.

`manifest.json` pins the source, tokenizer, preparation script and split bytes.
`protocol.json` records the design before model execution; `implementation.json`
records reviewed implementation hashes before dispatch. These are local dated
receipts, not an external preregistration or a tamper-proof attestation.

`scripts/prepare_activation_cost.py` normalizes line endings, starts each book
at its actual chapter-I heading and excludes the Gutenberg header/footer. It
selects the first 128 train and 64 final-evaluation blocks of 65 tokens using the
pinned Pythia tokenizer, without special tokens or padding. Positions 0–63
predict positions 1–64. Full blocks are disjoint across splits and earlier
fixtures. Blocks can cross chapter boundaries within a book; they never join
different sources.

Training workers read the train split. A separate evaluator reads the final
split only after all 12 predetermined training endpoints have been saved and
hashed. It evaluates the initial model and every endpoint once, without model
selection, intermediate evaluation or retries. The test bytes are public and
locally accessible: this is a procedural evaluation boundary, not a hidden
benchmark. Same-author fiction, small fixed prefixes and unknown pretraining
overlap preclude a broad model-quality or clean-generalization claim.

The two methods use fresh pinned Pythia-14m weights, float32 CPU/eager execution,
one thread, dropout disabled and the same AdamW settings. The token arm runs
64 steps; the time arm completes atomic steps until 60 seconds, with a fixed
one-second admissible overshoot. Separate two-step workers measure instrumented
codec callbacks and saved payloads. Their timings are not subtracted from or
equated with end-to-end training cost. OS process-lifetime resident peaks and
sampled training resident sets are distinct from logical payloads and GPU memory.

After installing the pinned dependencies used by the other model probes:

```bash
python scripts/download_pythia.py --output local-state/cost-model --record local-state/cost-model-assets.json
python experiments/activation_cost_probe.py --model-dir local-state/cost-model --fixture fixtures/activation-cost --output local-state/cost-reproduction
python -S scripts/audit_activation_cost.py --report local-state/cost-reproduction/report.json --output local-state/cost-reproduction-audit.json
```

The original run, all failed screens, measured costs and final evaluation are
documented in the [research record](../../research/2026-10-16-training-cost-and-final-evaluation.md)
and [complete receipts](../../results/activation-cost/report.json).
Do not overwrite the original result directory when reproducing.

To check the recorded receipts without Torch, weights or network access:

```bash
python -S scripts/audit_activation_cost.py --report results/activation-cost/report.json --output local-state/cost-recorded-audit.json
```

Run from the repository root with a fresh output path. Native process memory
receipts are supported on Windows and Linux; the original costs are measured
on Windows, and another host is not expected to reproduce clocks or peaks.
The receipt audit checks hashes, complete endpoint coverage, arithmetic and
declared gates; it does not rerun model losses or independently measure memory.
