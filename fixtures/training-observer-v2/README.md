# Pinned pretrained training observer v2

This frozen Windows experiment planned an offline Pythia-14m loader and exactly
two dense AdamW updates in each of three ML cases. Its sole recorded attempt
**failed after package import: 2/5 controls passed, 0 models loaded and 0
optimizer updates completed**. The three ML cases completed Torch and
Transformers imports, then their `socket.bind` denial records violated the
provider contract. The exact prehandshake exit37 and injected missing-module
exit38 controls passed. All 21 retained handles exited and all 5 Jobs were empty.
See [the failure report](../../results/training-observer-v2/report.md).

`protocol.json` declares the fixed model revision/assets, train fixture, seed503,
two batches, AdamW settings, five ordered cases and nonrenewable deadlines.
`implementation.json` freezes the new producer/tests, independent auditor/tests,
historical dependencies and four executable file/opaque path roles: launcher,
base Python interpreter, System32 cmd and conhost. No weights are bundled.

The new authorization controls have a fixed sequence, fresh nonce, exact current
role-decision reference, controller publish-start clock and worker acceptance
clock. Held role inventories use the immutable role evaluator solely for
identity admission; its `training_permitted: false` metadata is preserved.
This separate v2 protocol authorizes the planned ML actions. `emitted_perf_counter`
is measured just before atomic file publication, not at the OS hard-link instant.
The worker receipts record authenticated read/acceptance and subsequent action
ordering, with no claim of continuous process or loaded-code observation.

The intended healthy/busy/private-cap cases, native cleanup, stage memory and
sampler-overhead boundaries are specified in the protocol. In this execution
the parent accepted only `preimport`; it did not reach model load, updates,
post-training cap/timeout enforcement or held overhead windows. Raw
`postimport-ready.json` files survive even though their provider guard failed.
The combined generic PID/thread error must be read alongside those raw records:
PID and positive thread7 are correct; the unexpected `socket.bind` event is the
rejecting subcondition. Static urllib3 IPv6-probe source is a candidate only;
the recorded event lacks an endpoint or call stack.

The frozen portable auditor rejects 10 of 11,725 checks. A separate post-outcome
checker confirms preservation of the failed evidence; it cannot change that
acceptance verdict. To inspect saved evidence without executing the experiment:

```powershell
python -S -X utf8 scripts/check_training_observer_v2_record.py
python -S -X utf8 scripts/audit_training_observer_v2.py --report results/training-observer-v2/report.json --protocol fixtures/training-observer-v2/protocol.json --freeze fixtures/training-observer-v2/implementation.json --output reports/runs/your-fresh-review/frozen-audit.json
```

The preservation checker should retain `experiment_acceptance_passed: false`;
the acceptance auditor should exit1. Use a fresh output path. These are offline
receipt/hash checks, not a model or Windows observer replay.

Do not rerun this version or change its frozen sources, protocol, thresholds or
saved results. A future pass may freeze at most one new actual loader/two-update
integration after independently reviewing bounded provider diagnostics and any
explicit capability-probe policy. Python audit guards do not sandbox native
networking. Neither this failed run nor any future engineering acceptance repairs
historical RSS/cap validity or establishes compression quality, training cost,
GPU/provider correctness or production reliability.
