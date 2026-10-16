# Hugging Face Show and Tell draft — not posted

Destination: [Show and Tell](https://discuss.huggingface.co/c/show-and-tell/65). Its [guidance](https://discuss.huggingface.co/t/about-the-show-and-tell-category/30513) asks for open-source insights and technical details rather than promotion. Follow [forum guidelines](https://discuss.huggingface.co/guidelines). Our account's posting access is unverified. Confirm the product commit and every command before publication.

This is a forum draft. A Hub article would additionally require the publishing eligibility in the [current article documentation](https://huggingface.co/docs/hub/en/blog-articles). No article, HF repository, or Space has been created. Do not reuse this AI-generated draft on Hacker News.

---

Title: A 0.999 gradient cosine still left 11–12% first-step AdamW update error: a Pythia-14m audit

In our fixed Pythia-14m saved-tensor compression case, gradient cosines of about 0.999 still left actual first-step AdamW parameter-delta relative L2 errors of 0.109–0.119 against dense. All three predeclared joint gates failed the absolute error condition. These were three overlapping synthetic batches (320 unique target positions), CPU float32, fresh optimizer moments, learning rate 1e-4 and weight decay 0.01. The result is a bounded negative diagnostic, not a statement about all optimizers or training runs.

We're building SaveScope, a small CPU float32 audit toolkit for people experimenting with PyTorch saved-tensor compression. It compares compression policies with a dense reference and produces an inspectable report of saved scopes, parameter-gradient differences, and actual first-step AdamW parameter-update differences. The initial optimizer contract uses fresh moments; it does not replay stateful optimizer trajectories.

[Source and quickstart](https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/SAVESCOPE.md) · [Contribution guide](https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/CONTRIBUTING.md) · MIT original code

The motivation came from a fixed-parameter Pythia-14m diagnostic. An unchanged forward calculation did not imply a faithful backward pass. Keeping exact CE saves restored a local analytic gradient control, but the full-model gate failed; preserving actual LayerNorm saves still failed. Adding exact saves within six actual attention forwards brought full-gradient relative L2 from 4.05–7.70 to 0.034–0.041 over three fixed batches. The [report is pinned to a public commit](https://github.com/Linxiushen/frontier-signal-lab/blob/4c9683a408625817500843161e40383527c30455/results/activation-attention-gradient/report.md).

This identifies a broad forward scope containing several operations, rather than a particular operand. We then applied the same gradients to disjoint weight/optimizer clones, measured actual float32 parameter changes, and checked native parameter and moment updates against independent NumPy equations within declared rounding bounds. All 76 parameter-gradient records matched the same-runtime attention diagnostic in every arm. The separate [predeclared update protocol](https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/fixtures/activation-update/README.md) required update relative L2 <= 0.10, cosine >= 0.99, and at least halving the norm-only error with cosine no worse in every batch.

| Fixed batch seed | Gradient cosine | Actual first-step update relative L2 | Update cosine | Joint gate |
| --- | --- | --- | --- | --- |
| 11 | 0.999169 | 0.119295 | 0.992884 | Failed |
| 29 | 0.999173 | 0.116722 | 0.993188 | Failed |
| 47 | 0.999406 | 0.108971 | 0.994063 | Failed |

The update error improved relative to the norm-only baseline, but its absolute value exceeded 0.10 in all three batches. The [executed update report](https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/results/activation-update/report.md) preserves that failure without retuning the gate. This single fresh-moment step says nothing about accumulated optimizer state or convergence.

Our [earlier small training experiment](https://github.com/Linxiushen/frontier-signal-lab/blob/4c9683a408625817500843161e40383527c30455/results/activation-training/report.md) reduced logical saved inventory by 54%, but ran slower on CPU and had a higher process peak. Both training arms' final holdout NLL were worse than their initial values. We have no training-quality, GPU-memory, or throughput gain to advertise.

PyTorch already provides [saved-tensor hooks](https://docs.pytorch.org/tutorials/intermediate/autograd_saved_tensors_hooks_tutorial.html). SaveScope's purpose is to make policy comparisons, scope boundaries, reference controls, and failures easier to inspect and reproduce.

With Python 3.11+, inspect the bundled recorded case without installing Torch or downloading weights:

```bash
git clone --branch savescope-v0.1.0 --depth 1 https://github.com/Linxiushen/frontier-signal-lab.git
cd frontier-signal-lab
python -m pip install .
python -m savescope replay --output replay
python -m savescope inspect replay/report.json
```

Open `replay/index.html`. Replay exports existing observations; it does not execute a model. For an executed tiny-model audit without a model download, install the optional CPU dependencies in the quickstart and run:

```bash
python -m savescope demo --output tiny-run
```

The new tiny-model run and the recorded Pythia gradient/update case are separate pieces of evidence. The initial supported audit surface is CPU float32; other precision modes, compiled/distributed execution, checkpoint interactions, and accelerator costs need their own validation.

We would value a specific Transformers contribution: **a minimal adapter for a second small architecture with actual module-type scopes and matched weights, inputs, RNG, fresh optimizer state, plus dense-reference gradient and update comparisons.** A useful negative result is welcome. Please record the model revision/license, environment, exact command, per-parameter coverage, and failed checks; avoid uploading private data or weights.

For people already using saved-tensor hooks: which tiny, independently reproducible case most clearly exposes a scope boundary or restoration error? Please include a reference and minimal reproducer rather than a general benchmark claim. We can then turn it into a focused compatibility task.

---

Publication checks: pin the new update/protocol/product links to the verified release; confirm fresh install/replay/demo behavior; keep the tiny demo distinct from the Pythia recorded case; use a live Space/demo link only after its public build and content are verified. Do not duplicate this announcement in the Research or Spaces categories. Use those categories only for a distinct research or deployment question.
