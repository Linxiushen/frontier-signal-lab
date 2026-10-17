# Observer duty during fixed dense training

**Published outcome: joint acceptance false.** The frozen auditor rejects four
end-barrier ordering checks. See the [unchanged failure and recorded data](../../results/observer-duty/report.md).
The success auditor below must exit 1 for the published report; a separate
post-outcome preservation checker does not turn that rejection into acceptance.

This separately frozen measurement study compares active observation with common
completion polling. It uses four fresh Windows workers in **OFF / ON / ON / OFF**
order. Each loads the same pinned local Pythia-14m, starts with empty AdamW state,
and runs the same **16 dense updates**, seed 503 and fixed 16-batch schedule:
four model loads and 64 updates maximum. The protocol allows 60 seconds per case,
240 seconds for the suite and 4 seconds for verified cleanup.

Read [protocol.json](protocol.json) for the predeclared workload, controls and
limits. The unchanged historical loader and dense training helper perform the
actual work. There is no compression arm, holdout evaluation, checkpoint, GPU
work, download or seed/learning-rate search.

## What is measured

- Both arms poll completion every 20 ms. ON also queries the retained training
  interpreter's current memory/native CPU and takes a global Toolhelp snapshot.
  OFF performs neither active query; its training-memory result is **null**,
  meaning unobserved. Held boundary measurements apply to both arms.
- Worker signals bracket the full training helper. Loading, parameter hashing,
  postvalidation and held role scans occur outside that loop. Only query and
  snapshot intervals wholly inside its recorded start/end enter the ON summary.
  At least 20 selected observations and a maximum 0.5-second gap, including loop
  boundaries, are fixed validity requirements. Actual frequency is reported.
- ON resident/private maxima are **sampled lower bounds on whole-process current
  memory**. They include model, optimizer, gradients and allocator history.
  They do not isolate a backward/full peak, memory savings or a hard training cap.
  OFF cannot serve as a zero-memory baseline.
- Parent native CPU spans the wider control-release-to-completion-detection
  window. Selected query/snapshot wall sums and their fraction describe only
  wholly contained query work; they are not total observer overhead or exact
  parent CPU during the worker loop.
- All four initial/schedule hashes, final parameter hashes and complete 16-loss
  trajectories must match exactly before interpreting the two ON/OFF wall
  ratios and their geometric mean. These two counterbalanced pairs are
  exploratory observations under a fixed intervention, with no favorable ratio
  threshold or general causal/production claim. Losses are trajectory receipts.

The frozen Job, PID/creation, executable/path and role policies are reused.
Bounded held inventories admit the same launcher/interpreter/native/console
roles; an active global Toolhelp count does not admit roles or establish
continuous child absence. The exact pinned urllib3 import-probe allowance remains
unchanged. Python audit enforcement is not native network isolation. Normal
completion requires all five retained identities to exit 0 and an empty Job;
hidden worker failures reject success and preserve diagnostics.

## Replay saved receipts

From the repository root, use a saved report and a new output filename:

~~~powershell
python -S -X utf8 -m scripts.audit_observer_duty --report results/observer-duty/report.json --protocol fixtures/observer-duty/protocol.json --freeze fixtures/observer-duty/implementation.json --output reports/runs/your-fresh-review/observer-duty-audit.json
~~~

This portable audit reads saved JSON and file hashes; it does not import ML,
query Windows processes or rerun training. Optional local executable, model and
provider-file checks remain explicitly unperformed unless their paths are supplied.
Passing replay validates saved receipt consistency, not an independent OS
remeasurement.

The published success audit deliberately exits 1 with four known rejections.
To verify exact preservation of this negative record without running a model:

~~~bash
python -S -m scripts.check_observer_duty_record
~~~

This separate **post-outcome** checker returns 0 only when the original rejection
is preserved; `experiment_acceptance_passed` remains false. Five guarded
post-outcome mutation tests and 28 preservation checks do not add to the 45
prefreeze tests or change their acceptance rules.

## Optional separately declared Windows reproduction

Only after reviewing and freezing the exact source, auditor, offline assets,
executable files/opaque paths and provider source, run at most **one** new suite
in a directory that does not yet exist:

~~~powershell
& "<PINNED_VENV_PYTHON>" -S -X utf8 -m experiments.observer_duty_probe --python "<PINNED_VENV_PYTHON>" --base-python "<PINNED_BASE_PYTHON>" --native "<PINNED_SYSTEM32_CMD_EXE>" --conhost "<PINNED_SYSTEM32_CONHOST_EXE>" --provider-source "<PINNED_SITE_PACKAGES>\urllib3\util\connection.py" --model-dir "<PINNED_LOCAL_MODEL_DIR>" --fixture fixtures/activation-cost --protocol "<REVIEWED_REPRODUCTION_PROTOCOL_JSON>" --freeze "<REVIEWED_REPRODUCTION_FREEZE_JSON>" --output reports/runs/your-fresh-reproduction/observer-duty
~~~

Every placeholder must match that reproduction's reviewed freeze, including
canonical path hashes. A different machine/path requires a separately reviewed
freeze before execution; preserve the published historical freeze. There is no
automatic retry, real-workload preflight or adjustment after an outcome. Keep
failed cases and withhold ratio interpretation when validity fails.

The previous failed joint cost/final-quality screens and invalid historical RSS
measurements remain unchanged. This study does not establish a compression,
quality, GPU or production-reliability result.
