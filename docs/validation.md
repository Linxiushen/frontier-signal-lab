# SaveScope v0.1 validation

Local validation on 2026-10-16 used Python3.12.14, Torch2.9.1+cpu and
NumPy2.3.5 on Windows. No paid APIs or GPU resources were used.

- **148 tests passed, no skips** in the full repository suite (26.45s).
  This includes 21 reusable-audit contract tests, eight portable-report tests,
  six optimizer-reference tests, and the 113 existing tests.
- Built `frontier_savescope-0.1.0-py3-none-any.whl`, installed it in an isolated
  target, changed away from the checkout, and ran replay with `python -I -S`.
  The package's replay succeeded with site-packages disabled and neither
  Torch nor NumPy imported. Wheel SHA256:
  `df10712e71f0f154cfcff2c5f6a0c77476d573a06841cfe0564fde8512ea6e09`.
- Executed the documented Python API example and `savescope demo`. They ran
  actual CPU forward/backward and independent cloned AdamW steps with no model
  or dataset downloads. These are engineering examples, not a second scientific
  experiment or a fresh Pythia reproduction.
- Visually checked the report at desktop and 390px mobile width, switched
  batches/measurements, and filtered parameter names. No body overflow at390px;
  wide parameter tables scroll within their container. External report strings
  use text nodes; JSON cannot terminate its script element.
- The one predeclared new Pythia experiment made nine real AdamW clone steps.
  Its scientific joint gates failed on all three fixed batches. Independent
  parameter/moment controls passed, and prior gradient records matched.
- An independent read-only audit made 7,693 checks on chronology, hashes,
  recorded reference receipts, sufficient-statistic aggregation, and gates,
  with no failures. A separate 178-check audit verified the packaged replay
  against reviewed raw observations. These checks inspect metrics/receipts;
  they do not independently recompute unexported raw arrays.

The [scientific result](../results/activation-update/report.md) has its own
source/config/protocol/worker hashes. The bundled replay content SHA256 is
`85f36b31f557caafa7d229544d0f498a1d0eedfe7714bded3a0bb1a47ea17477`.
Cross-platform numeric hashes need not be identical. Logical payload inventory
is not measured allocator peak memory.

GitHub Actions separately checks portable wheel installation, the actual tiny
CPU audit, and the full same-runtime Pythia diagnostic. Consult the live Actions
status for remote validation; local success does not establish a remote result.

The initial Linux package run exposed a one-ULP difference between equivalent
FP64 norm reductions in one engineering assertion. That assertion now allows
at most four FP64 ULPs while checking each cloned gradient element exactly
against the original direct-autograd gradient snapshot. The audit implementation,
recorded scientific results and wheel above are unchanged.
