# Contributing

SaveScope welcomes independent reproductions, counterexamples, compatibility fixes, and small model/operator adapters. Start with [SAVESCOPE.md](SAVESCOPE.md) for the supported CPU float32 workflow. The broader repository also keeps public research evidence and experiments; a contribution should state which part it changes.

## Choose one useful task

- Reproduce the no-model-download tiny audit from a fresh environment and record the report plus exact setup.
- Add a minimal failure case for repeated/shared modules, nested saved-tensor hooks, exceptions, or scope restoration. Report unsupported behavior explicitly.
- Add one small, licensed architecture/operator adapter with matched dense-reference controls. GPU, compilation, checkpointing, mixed precision, and distributed support require their own evidence.
- Improve report interpretation with a concrete example that distinguishes saved inventory, gradient error, optimizer-update error, and measured process/device costs.
- Correct a source claim using a first-party URL, observation date, and the narrow fact that the source establishes.

Before adding a substantial API or integration, open an issue describing the user problem, minimal example, support boundary, and proposed evidence. Search existing issues first. A focused PR can also start as a draft. Do not create issues in other projects merely to promote this repository.

## A useful bug report or reproduction

Include the repository commit, Python/Torch/NumPy versions, OS and device, exact install/run commands, the smallest reproducer, expected behavior, and actual result. Attach or link a generated report where you have the right to share it. State whether it came from a **recorded replay**, an **executed tiny demo**, or a new **executed audit**; a successful replay is not a fresh model run.

For numerical changes, state the shapes, dtypes, seeds, parameters covered, input/data source, model revision/license, and compression policy/module types. Use identical initial weights, inputs, optimizer configuration and initial state for the reference and candidate, and control relevant randomness. The initial API compares one AdamW step with fresh moments; stateful optimizer replay needs a separately declared extension and controls. Preserve dense-reference gradient and actual parameter-delta comparisons; comparing only loss or final parameter norms can hide an error. Include zero-reference/nonfinite handling and skipped or missing parameter gradients.

Keep predeclared thresholds and failed gates. Do not loosen a tolerance to make a report pass without explaining the numerical reason and providing a separate comparison. A negative result is a valid contribution.

Reports can contain parameter names, paths, and experimental metadata. Review them before sharing. Do not submit credentials, private data, model weights, or raw activation/gradient arrays without a concrete need and the necessary rights. For most bugs, a synthetic reproducer and metadata are sufficient.

## Validate the change

Run checks relevant to the behavior you change and include the exact commands/results in the PR. The base suite is:

```bash
python -m unittest discover -s tests -v
```

To check just the toolkit, use `python -m unittest discover -s tests -p "test_savescope*.py" -v`. Optional Torch-dependent checks may skip when Torch is absent; state the skips and separately run the relevant checks in a documented supported CPU environment for audit-engine changes. An executed `python -m savescope demo --output tiny-run` is a useful end-to-end check. Use a new output directory to preserve previous evidence. Documentation-only changes do not need a model run.

Add a regression test for a real correctness failure or support claim. Tests should compare observable behavior to a reference, including cleanup after failure where relevant. Do not add a test that merely repeats the implementation.

For performance or memory claims, report a matched baseline/candidate, hardware and software, shape/dtype, warmup/repeats, measurement scope, reconstruction/packing overhead, and regressions. Logical saved-tensor bytes are not peak VRAM or process memory. Gradient/update agreement in one configuration does not establish training quality or broader support.

## Keep the evidence and attribution inspectable

Keep a PR to one concrete outcome. Link the issue or explain the reproducer, the change, actual commands/results, and remaining limitations. Separate passed, failed, skipped, and unrun checks. Retain third-party notices and licenses; original project code is MIT. New external data/models need an explicit source, revision, and license compatible with the proposed use.

For research-source updates, distinguish an author's own work from repository-wide activity, a proposal from merged code, and an observed public statement from an inference. No contribution should assert a private roadmap, unannounced employer, endorsement, or unmeasured benefit. The project does not send automated promotions or messages to researchers.
