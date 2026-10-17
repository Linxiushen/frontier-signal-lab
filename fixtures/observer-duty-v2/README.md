# Observer duty v2: wait for the final acknowledgment

**The new v2 record passes its frozen engineering acceptance:** 6185/6185 portable
checks and 6189/6189 with optional local files. See the [actual outcome and raw
receipts](../../results/observer-duty-v2/report.md). This separate study corrects
the controller's final acknowledgment barrier; the [v1 record](../../results/observer-duty/report.md)
keeps all four frozen rejections.

The [protocol](protocol.json) was declared before the [implementation freeze](implementation.json)
and the sole v2 execution. Four fresh Windows workers run in **OFF / ON / ON / OFF**
order. Each loads pinned local Pythia-14m revision
`cf967c0a9a04383db6f7b1108d86b2962634b4ac`, starts with empty AdamW state and
executes the same 16 dense updates, seed 503, CPU float32/eager and one intra/inter-op
thread: **four loads and 64 updates**. The workload, optimizer, fixed batch schedule,
sampler, role policy and provider allowance match v1. There is no compression arm,
holdout scoring, checkpoint, GPU work, download or seed/learning-rate search.

## The corrected barrier

After emitting `postvalidation-continue.json`, the controller waits for the exact
`postvalidation-continue-accepted.json`. It authenticates the nonce, worker role,
retained interpreter PID, original PID/creation identity, full control envelope,
filename and next control index 11. The receipt saves request, wait start/end,
unchanged raw acknowledgment and a nonrenewable deadline of
`min(wait start + 5 seconds, original case deadline, original suite deadline)`.

Worker acceptance must follow the request and precede wait completion. Both
retained worker/native live checks must follow that completion and precede finish
emission. An acknowledgment may already exist when the parent starts waiting.
Missing, malformed, premature, future or wrong-identity acknowledgment fails the
case and prevents the live checks and finish. Saved receipts are rechecked before
producer success and independently replayed by the frozen auditor. Case/suite
bounds remain 60/240 seconds, with at most four seconds for verified cleanup.

The [61 prefreeze tests](../../results/observer-duty-v2/prefreeze-guarded-tests.json)
are 33 producer mock tests and 28 independent synthetic audit tests. They include
delayed acknowledgment, bounded timeout, wrong PID, future time and forbidden early
finish controls. They are separate from the four actual model workers.

## Measurement boundaries

- Both arms use the same 20 ms completion polling target. ON also queries the
  retained interpreter's current memory/native CPU and a global Toolhelp snapshot;
  OFF performs neither active query. OFF memory is **null/unobserved**.
- Worker signals bracket the unchanged full training helper. Loading, parameter
  hashing, validation, held role scans and the final acknowledgment barrier sit
  outside that loop. Query/snapshot intervals enter the ON summary only when wholly
  contained by its start/end. At least 20 selected observations and a maximum
  0.5-second gap, including boundaries, are fixed validity gates.
- ON current resident/private maxima are sampled lower bounds on whole-process
  readings, including model, optimizer, gradients and allocator history. They do
  not isolate backward/full peaks, memory savings, a hard cap or GPU memory.
- Parent native CPU covers the wider release-to-completion-detection window.
  Selected query/snapshot wall fractions exclude boundary-crossing queries and
  common polling/control costs; they are neither CPU fractions nor total observer
  overhead. Global Toolhelp counts do not admit process roles.
- All four initial/schedule hashes, final parameter hashes and complete 16-loss
  trajectories must match before interpreting the two ON/OFF wall ratios. These
  two counterbalanced pairs are descriptive under a fixed intervention, without a
  favorable ratio threshold, population inference or general causal claim.

Exact retained Job/PID/creation/executable/path and bounded role policies are
unchanged. Four exact pinned urllib3 import capability-probe audit attempts are
retained, one per worker; Python audit enforcement is not native network isolation
or evidence that an OS bind succeeded. Held inventories do not prove continuous
child absence. Each normal case requires all five retained identities to exit 0
and an empty Job. A hidden worker failure rejects success.

## Replay the published saved receipts

From the repository root, select a new output filename:

~~~powershell
python -S -X utf8 -m scripts.audit_observer_duty_v2 --report results/observer-duty-v2/report.json --protocol fixtures/observer-duty-v2/protocol.json --freeze fixtures/observer-duty-v2/implementation.json --output reports/runs/your-fresh-review/observer-duty-v2-audit.json
~~~

This portable command reads saved JSON and source/dependency/raw-file hashes. It
does not import ML, query live Windows processes or rerun training. The published
record returns exit 0. Passing replay checks saved consistency, not a fresh OS
measurement. Local executable/model/provider-file checks remain unperformed unless
their optional paths are explicitly supplied; the published local-file audit is
the separate 6189-check record.

## Optional separately reviewed Windows reproduction

Review the exact source, auditor, pinned offline assets, executable files and
opaque paths, provider source and protocol first. Prepare a **new reviewed
reproduction freeze** before any execution; preserve the published freeze. Run at
most one new suite in a directory that does not exist:

~~~powershell
& "<PINNED_VENV_PYTHON>" -S -X utf8 -m experiments.observer_duty_v2 --python "<PINNED_VENV_PYTHON>" --base-python "<PINNED_BASE_PYTHON>" --native "<PINNED_SYSTEM32_CMD_EXE>" --conhost "<PINNED_SYSTEM32_CONHOST_EXE>" --provider-source "<PINNED_SITE_PACKAGES>\urllib3\util\connection.py" --model-dir "<PINNED_LOCAL_MODEL_DIR>" --fixture fixtures/activation-cost --protocol "<REVIEWED_REPRODUCTION_PROTOCOL_JSON>" --freeze "<REVIEWED_REPRODUCTION_FREEZE_JSON>" --output reports/runs/your-fresh-reproduction/observer-duty-v2
~~~

Every placeholder must match that reproduction's reviewed pins, including canonical
path hashes. A different machine/path needs a new reviewed freeze. Changing the
protocol or source also requires a separately declared, reviewed auditor; do not
edit this historical auditor's pins. There is no automatic retry, real-workload
preflight or adjustment after observing an outcome. Preserve failures and withhold
ratios when validity fails.

V2 does not accept v1 retrospectively, clear the six failed scientific cost/final
quality screens or validate historical parent RSS. It establishes no compression,
quality, GPU or production-reliability result. Any lower-cost observer treatment
needs its own declared controls and freeze.
