# SaveScope

**Check what saved-tensor compression changes in your gradients and actual AdamW updates.**

SaveScope is a small, original diagnostic toolkit for people experimenting with
compressed backward operands. It compares exact and rowwise INT8 saved tensors,
keeps explicitly selected module scopes exact, and reports errors for every
trainable parameter tensor. The loss is constructed outside SaveScope's hooks.

[Interactive recorded case](https://linxiushen.github.io/frontier-signal-lab/) ·
[Python API](#use-your-own-model) · [Evidence and limits](#evidence-and-limits) ·
[Contribute a counterexample](CONTRIBUTING.md)

## Try it without Torch, a GPU, an account, or a model download

Clone this repository and install the local package with Python 3.11+:

```bash
git clone https://github.com/Linxiushen/frontier-signal-lab.git
cd frontier-signal-lab
python -m pip install .
python -m savescope replay --output replay
python -m savescope inspect replay/report.json
```

Open `replay/index.html`. It is an interactive, self-contained report: switch
batches, compare gradient and update errors, filter parameters, and download
the JSON. All observations are bundled and checked against a SHA256 manifest.
**Replay executes no model.** The observation time and raw evidence links are
shown in the report. A content hash detects changes; it is not a signature.

Use a fresh output directory for each run. Reports never overwrite prior runs.
There are no external scripts, fonts, telemetry or API calls in the viewer.

## Execute the tiny example

Install CPU Torch from its official index, then NumPy:

```bash
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.9.1+cpu
python -m pip install "numpy>=1.26,<3"
python -m savescope demo --output tiny-run
```

This actually runs a tiny attention block with fixed random inputs. It compares
three save policies against the same weights and RNG state, then performs real
first-step AdamW updates on detached parameter clones. It downloads no weights
or datasets. The demo is an engineering example, not another Pythia result or
evidence of model quality.

## Use your own model

```python
import torch
from savescope import audit
from savescope.demo import as_report
from savescope.report import write_report

torch.manual_seed(11)
model = torch.nn.Sequential(
    torch.nn.Linear(32, 64), torch.nn.LayerNorm(64),
    torch.nn.GELU(), torch.nn.Linear(64, 8),
)
x, target = torch.randn(4, 32), torch.randn(4, 8)

result = audit(
    model,
    forward_fn=lambda m: m(x),
    loss_fn=lambda output: (output - target).square().mean(),
    policies=("dense", "int8", "int8_keep_sensitive"),
    optimizer_kwargs={"lr": 1e-4, "weight_decay": 0.01},
)
write_report(as_report(result, title="My model / fixed batch"), "my-audit")
```

`audit` requires CPU float32 strided parameters and eager, first-order execution.
It restores registered parameters, buffers, original gradients, module training
modes and RNG state. By default each arm gets fresh zero moments for one cloned
AdamW step. To inspect a point during training, pass your existing optimizer:

```python
# Between training steps; audit recomputes gradients from these callbacks:
result = audit(model, lambda m: m(x), lambda y: (y - target).square().mean(),
               optimizer=optimizer)
```

SaveScope captures the current moments and each parameter's step counter once,
then starts every policy from that same snapshot on private clones. It never
steps or loads state into the caller's optimizer. The report records the input
state and checks the actual native update against an independent NumPy reference.
Parameters with no audit gradient keep their moments and counters unchanged;
parameters whose optimizer state is still absent retain lazy initialization.
Existing caller gradients are restored afterward; they are not accumulated into
the audit's gradients. Use callbacks that define the batch/loss you want to inspect.

This initial stateful API supports an exact `torch.optim.AdamW` with **one group
covering every trainable model parameter exactly once**. Use ordinary CPU
float32 moments and CPU float32/float64 scalar step counters with integral values
in `[0, 2**24)`. AMSGrad, maximize, capturable,
differentiable, fused/foreach execution, custom optimizer subclasses or step
hooks, extra/missing parameters, multiple groups and malformed/nonfinite state
are rejected before the forward callback. `optimizer_kwargs` and `optimizer`
are mutually exclusive. Unsupported input never silently falls back to fresh
moments. Callback or concurrent optimizer mutations are unsupported: they are
detected and rejected, and their external effects are not restored.

One common-state update does not prove a stateful training trajectory or quality.

Policies:

| Policy | Saved tensors inside model forward |
| --- | --- |
| `dense` | Exact; required baseline |
| `int8` | Eligible finite float32 saves are compressed rowwise |
| `int8_keep_sensitive` | Same compression, with actual `LayerNorm` and `MultiheadAttention` forward scopes exact |

The compression threshold is 256 elements. Parameter-storage aliases and
unsupported tensors stay exact. Add your actual attention module type with
`exact_module_types=(YourAttentionClass,)`; a matching name or tensor shape does
not select a module. Exact ancestors keep their child saves exact. Inventory
records scope and payload counts; it is not an allocator profiler.

The forward callback must use the supplied model; loss must be constructed in
the loss callback. Input/target mutation, external side effects, structural
changes, concurrent calls, checkpointing, `torch.compile`, DDP, higher-order
autograd, caller-installed saved-tensor hooks, and arbitrary custom autograd
code are outside v0's contract. Use a
fresh model instance if your forward has side effects that cannot be restored.

Independent NumPy formulas check native parameter and moment updates with
explicit float32 rounding bounds, including per-parameter bias correction when
an existing optimizer is supplied. Scientific disagreement with
dense is a valid diagnostic result. Invalid execution/control failures raise an
error; low fidelity is not disguised as a program crash.

## Evidence and limits

The bundled case starts with a pinned public Pythia-14m checkpoint and three
fixed, overlapping batches of original synthetic stories (320 unique target
positions). Preserving all saves inside six actual attention forwards, on top
of exact CE and 13 exact LayerNorm scopes, reduced full-gradient relative L2
from **7.61 / 7.70 / 4.05** to **0.0408 / 0.0407 / 0.0345**. This is a broad scope
intervention: projections, rotary operations, attention and output projection.
It does not identify one causal operand.

The additional first-step AdamW diagnostic has its own
[predeclared protocol](fixtures/activation-update/README.md),
[raw results](results/activation-update/report.json) and
[result interpretation](results/activation-update/report.md).
Read that gate separately from the gradient gate.

The update result is **negative**: actual update relative L2 was **0.1193 /
0.1167 / 0.1090**, exceeding the predeclared 0.10 ceiling in every batch despite
the high gradient cosines. Other parts of the joint gate passed; the joint gate
failed. All native parameter/moment checks passed the independent NumPy bounds.
This is the reason to inspect the update rather than stop at gradient cosine.

Earlier interventions and training had negative results. Exact CE and then
exact LayerNorm saves did **not** halve gradient error. Earlier matched-token
training ran slower, used higher measured CPU peak memory, and regressed on
both synthetic holdouts. See the [training report](results/activation-training/report.md)
and [full research history](RESEARCH_LAB.zh.md).

- No demonstrated memory reduction, speedup, general model-quality improvement,
  GPU result or new architecture.
- Logical saved payload bytes are not measured peak RAM or VRAM. Diagnostic
  clones and retained dense references add overhead.
- First-step AdamW can react strongly to gradient signs and small coordinates.
  A high gradient cosine is not an optimizer-update guarantee.
- The hooks/INT8 technique is established prior work; this project contributes
  an inspectable diagnostic workflow, not a claim to invent it. See
  [PyTorch's saved-tensors tutorial](https://docs.pytorch.org/tutorials/intermediate/autograd_saved_tensors_hooks_tutorial.html)
  and [ActNN](https://github.com/ucbrise/actnn).

The original toolkit/code and original random/synthetic examples are MIT.
Pythia is Apache-2.0; weights are not included in the package.

## Reproduce the full recorded case

The full diagnostic also needs the pinned Transformers stack and seven
hash-verified public model assets. It makes no paid API calls:

```bash
python -m pip install -r requirements-real-activation.txt
python scripts/download_pythia.py --output local-state/models/pythia-14m-cf967c0 --record local-state/model-assets.json
python experiments/activation_attention_gradient_probe.py --model-dir local-state/models/pythia-14m-cf967c0 --data fixtures/activation-training/data.json --manifest fixtures/activation-training/manifest.json --protocol fixtures/activation-attention-gradient/protocol.json --output reports/runs/my-attention
python experiments/activation_update_probe.py --help
```

See the update protocol for the exact same-runtime baseline requirement and
command. Numeric hashes may differ across platforms; cross-platform bitwise
agreement is not a scientific requirement.

To render another SaveScope report: `python -m savescope report input.json --output rendered`.
To test only this toolkit: `python -m unittest discover -s tests -p "test_savescope*.py" -v`.

The [frozen accumulated-state integration](fixtures/savescope-optimizer-state/protocol.json)
uses a tiny original random fixture, four warmup updates, unequal parameter
counters and a never-used parameter. It compares the dense audit against a
separately cloned native optimizer and retains fresh-reset and failure controls.
Run it into a new directory with
`python experiments/savescope_optimizer_probe.py --output my-state-check`.
This verifies product behavior; the six historical compression cost/quality
failures remain separate.
The [recorded result, trajectory and hashes](results/savescope-optimizer-state/report.md)
are available for inspection.

## The useful next contribution

Bring one independently reproducible scope/parameter where gradient and update
metrics disagree, or an operator the scope selector misses. Include the exact
operator class, dtype, seed, loss boundary and report. A failure with a small
reproducer is more useful than a star.
