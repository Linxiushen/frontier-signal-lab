# PyTorch Projects draft — not posted

Destination: [Projects](https://discuss.pytorch.org/c/projects/33), whose [category description](https://discuss.pytorch.org/t/about-the-projects-category/117648) invites people to share how they use PyTorch. Review the [forum guidelines](https://discuss.pytorch.org/guidelines). Account posting permissions are unverified. Before posting, confirm the public release contains the toolkit and pin the update-report/protocol links below to that commit. This draft has not been submitted. Do not reuse this AI-generated text on Hacker News.

---

Title: SaveScope: a 0.999 gradient cosine still left 11–12% first-step AdamW update error

On a pinned Pythia-14m checkpoint, preserving saved tensors inside six attention forwards, alongside exact CE and 13 LayerNorm scopes, brought full-gradient cosine to approximately 0.999. Actual float32 first-step AdamW parameter-delta relative L2 errors against dense were still **0.1193 / 0.1167 / 0.1090**. All three predeclared joint gates failed the absolute error ceiling of 0.10; cosine and relative-improvement conditions passed.

Conditions matter: CPU float32, three overlapping synthetic batches with 320 unique target positions, fresh zero moments, learning rate 1e-4, and weight decay 0.01. Native parameter/moment updates passed independent NumPy rounding bounds. These are broad execution scopes, without attribution to one operand or evidence about stateful training, quality, GPU memory, or speed. [Executed report](https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/results/activation-update/report.md) · [Predeclared protocol](https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/fixtures/activation-update/README.md).

SaveScope packages this inspection workflow: saved-scope inventories, dense-reference gradients, actual fresh-moment AdamW updates on parameter clones, and per-parameter reports. PyTorch's [saved-tensor hooks](https://docs.pytorch.org/tutorials/intermediate/autograd_saved_tensors_hooks_tutorial.html) are established functionality; the contribution here is audit tooling and reproducible controls.

With Python 3.11+, inspect the bundled recorded case without Torch or model downloads:

```bash
git clone --branch savescope-v0.1.0 --depth 1 https://github.com/Linxiushen/frontier-signal-lab.git
cd frontier-signal-lab
python -m pip install .
python -m savescope replay --output replay
```

Open `replay/index.html`. Replay executes no model. The [guide](https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/SAVESCOPE.md) also documents an actual tiny CPU demo needing no downloaded weights.

For an existing CPU float32 model, fixed `x`/`target`, and your actual `MyAttention` module class:

```python
from savescope import audit
result = audit(
    model, forward_fn=lambda m: m(x),
    loss_fn=lambda y: (y - target).square().mean(),
    exact_module_types=(MyAttention,),
    optimizer_kwargs={"lr": 1e-4, "weight_decay": 0.01},
)
```

The initial contract is eager, first-order execution with fresh optimizer moments; checkpointing, compilation, distributed execution, and arbitrary callback side effects are unsupported. Logical saved bytes are separate from allocator peaks.

Which small operator or architecture adapter would best test exact-save scope selection? We would value **one independent minimal reproducer**, particularly a reused-module or exception/restoration case, with actual module types, seed, loss boundary, reference gradients, and parameter deltas. Failed gates are welcome: [contribution guide](https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/CONTRIBUTING.md).

Implementation and this draft used AI assistance. Protocols, controls, source, and raw reports are published for independent inspection and reproduction. Original tooling is MIT.
