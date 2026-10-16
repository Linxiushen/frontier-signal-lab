# SaveScope v0.1

The person using this tool has just changed what autograd saves and wants to
decide whether to trust the resulting backward pass before paying for training.
The first task is to inspect full-gradient error and actual optimizer-update
error against an exact baseline, then find the worst parameter tensors.

Deliverables: an installable Python package, an executable CPU-only tiny demo,
a reusable audit API, a zero-dependency replay of a recorded Pythia case, and a
standalone interactive report. Replay performs no model execution. The real
model diagnostic is a separate predeclared first-step AdamW experiment.

## Interface decisions

- Domain: saved operands, exact scopes, backward passes, gradient direction,
  optimizer deltas, parameter tensors, source fingerprints.
- Color world: graphite instrument panels, off-white lab paper, blue scope
  traces, muted steel table rules, amber threshold markers, red failed checks.
- Signature: a paired **gradient / actual update** comparator, coupled to a
  per-parameter error table and explicit exact-save scope labels. Changing a
  batch or measurement changes both together.
- Rejected defaults: a grid of promotional score cards (use one comparison
  workbench); rainbow series (use the same blue trace against graphite);
  oversized app navigation (use a compact instrument header and batch rail).
- Feel: a quiet diagnostic instrument. The large figure is the candidate error;
  provenance and caveats remain readable beside it.
- Tokens: graphite/paper/trace/threshold/failed; 4px spacing base; 14px body,
  11px metadata, 18/28/44px hierarchy; tabular monospace measurements. Borders
  establish structure without shadows. 44px controls, visible focus, responsive
  table overflow. No external fonts, assets, telemetry or network requests.

## Boundaries

v0 is CPU float32 eager first-order execution, not a GPU memory optimizer.
Logical saved payloads are not allocator peaks; gradient fidelity is not model
quality. The original cost/holdout failures stay linked. No novelty, leadership,
endorsement or employment claims are part of this product.

Distribution starts with a runnable public artifact and a specific technical
question. Drafts must distinguish recorded evidence from live execution. No
mass tagging, manufactured engagement or unrelated upstream issues.
