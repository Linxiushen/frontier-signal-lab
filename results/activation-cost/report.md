# CPU training cost and deferred final-evaluation receipts

All six predeclared directional screens failed. The frozen execution completed;
the receipt-consistency audit passed 598 checks, while a separate review found
**invalid parent RSS sampling and unestablished actual-worker memory-cap enforcement**.
Read [measurement-validity.json](measurement-validity.json) before interpreting
the unmodified [report.json](report.json). A passing receipt audit is not a
passing experiment or measurement-validity check.

Initial heldout mean NLL: **4.457542557** (lower is better).
Every dense and compressed endpoint regressed versus that initial model. This
does not isolate compression as the cause: both training methods regress.

Pairs below are **dense / INT8 with exact norm+attention saves**, all three seeds.
Token arm: 64 updates, 8,192 target positions per endpoint.
Peak is native worker self-reported process-lifetime resident high-water through
loop end, in MiB (2^20 bytes), including imports/model/setup; not isolated
training peak. Parent RSS samples must not be used.

| Seed | Loop wall seconds | Native lifetime peak MiB | Final heldout NLL | Joint screen |
| --- | --- | --- | --- | --- |
| 503 | 11.899079 / 13.355544 | 559.613281 / 559.773438 | 4.574105818 / 4.546694003 | failed |
| 701 | 12.083676 / 12.855667 | 560.027344 / 559.750000 | 4.602038879 / 4.600431066 | failed |
| 907 | 11.838140 / 12.477783 | 559.433594 / 559.433594 | 4.587996807 / 4.600448988 | failed |

Time arm: atomic updates until 60 seconds; all six controls satisfy the declared
[60,61] second window without reaching the step cap.

| Seed | Completed updates | Loop wall seconds | Final heldout NLL | Time control / joint screen |
| --- | --- | --- | --- | --- |
| 503 | 322 / 299 | 60.029880 / 60.116162 | 5.642478772 / 5.634735636 | valid / failed |
| 701 | 322 / 300 | 60.140776 / 60.166576 | 5.636638254 / 5.656550504 | valid / failed |
| 907 | 322 / 301 | 60.188726 / 60.153958 | 5.594762564 / 5.597567298 | valid / failed |

The separate two-step profiles compressed19 outer saves per step, with13 actual
norm and6 actual attention forward scopes retained exactly and exact CE outside
hooks. Outer nonparameter backing-union bytes were3,605,504 dense versus911,872
compressed; this is neither total model memory nor allocator peak savings.
Compressed outer pack callbacks were8.2163–8.3946ms and unpack
1.4392–1.6567ms per instrumented profile step. Profiles use
initial weights, include timer/inventory overhead and do not measure long-run
average codec cost. Necessary finite-input scans remain in the timed codec.

The original run has12 sequential training workers,6 fresh two-step profiling
workers,2,250 primary updates and12 profiling updates; native76parameter counters
and final finite-state checks are recorded. There is no NumPy update-reference
validation in this cost loop. All endpoints were checkpointed and hashed before
one initial plus12 final evaluations, each64 fixed blocks /4,096 target positions.
No endpoint selection, intermediate heldout score, retry or scientific rerun.

[Protocol](../../fixtures/activation-cost/protocol.json),
[implementation freeze](../../fixtures/activation-cost/implementation.json),
[independent freeze review](implementation-audit.json),
[data provenance and reproduction](../../fixtures/activation-cost/README.md),
[hardware inventory](environment.json), and
[full research interpretation](../../research/2026-10-16-training-cost-and-final-evaluation.md).
No checkpoints, model weights, local absolute paths or raw release file are
bundled. Endpoint identities and checkpoint digests remain in the exact report;
the local release hash cannot authenticate its unpublished bytes or timing.

```bash
python -S scripts/audit_activation_cost.py --report results/activation-cost/report.json --output local-state/cost-recorded-audit.json
```

Run from the repository root. This audit requires only the standard library and
the pinned protocol; it does not recompute model scores, raw memories or enforce
the validity supplement. CI audits these Windows receipts and engineering
fixtures; it does not independently reproduce the scientific cost run.

One Windows host, CPU float32/eager/one-thread, Pythia14m, same-author fiction
prefixes, possible pretraining overlap, one run per method/seed and short fixed
training prevent general quality, convergence, statistical, GPU, AttnRes or
performance claims. See [SHA256SUMS](SHA256SUMS) for exact published file bytes.
