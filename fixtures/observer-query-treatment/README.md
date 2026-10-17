# Memory queries with and without Toolhelp

**The sole frozen study passes its finite engineering acceptance:** 8894/8894
portable checks and 8898/8898 with optional local files. See the [actual results,
limits and raw receipts](../../results/observer-query-treatment/report.md).

This [protocol](protocol.json) declares a new **M / T / T / M** treatment study.
All four workers receive current memory/native-CPU queries through the retained
interpreter handle. T additionally takes a global Toolhelp snapshot after each
query; M performs no active snapshot. There is no observation-off baseline.

Four fresh pinned local Pythia-14m workers each run the same 16 dense AdamW updates,
seed 503, fixed batches and CPU float32/eager/thread 1/1: four loads and 64 updates
maximum. Common completion polling targets 20 ms, skips missed slots without
bursts and records actual frequency/gaps. Worker code, held memory brackets,
role/liveness/provider policies, exact final acknowledgment barrier and original
60-second case/240-second suite/four-second cleanup bounds remain from v2.

## Declared measurements

Both treatments save every query interval, exact PID/creation identity, current
resident/private reading and native-CPU reading. T saves actual snapshot intervals
and global process counts. M snapshot clocks/counts and selected snapshot wall
sum are **null/unperformed**, not fabricated zero measurements.

M selects only queries wholly inside the unchanged full training helper. T also
requires its following snapshot to lie wholly inside. All boundary-crossing rows
remain saved. Both require at least 20 selected observations and a maximum
0.5-second gap, including loop boundaries. Current resident/private maxima are
whole-process sampled lower bounds, including allocation history; they do not
isolate backward/full peaks, memory savings, hard caps or GPU memory.

Selected query/snapshot wall sums and their fraction of worker-loop wall describe
the declared query work. They exclude nonselected rows and common polling/control
costs. Parent native CPU spans the wider release-to-completion-detection window.
Wall fractions are not CPU fractions, total observer overhead or isolated causal
query cost. Global Toolhelp counts do not admit active process roles or establish
continuous isolation; identical held role scans apply to both arms outside the
loop. Python audit enforcement is not native network isolation.

Both actual M windows reported a native parent-CPU delta of 0.0 seconds. This is
an observation at the counter's resolution, not evidence of zero query cost.
Their selected memory-query wall sums are nonzero. Two observed T/M loop-wall
ratios, 1.069392/1.016469, remain descriptive pairs rather than a general slowdown
or savings estimate.

All four initial/schedule/final parameter hashes and complete 16-loss trajectories
must match exactly before pair interpretation. Two T/M loop-wall ratios, signed
T-minus-M seconds, signed ratio-minus-one and geometric mean retain positive and
negative values. There is no favorable performance threshold, population estimate,
general causal/production claim or estimate of all-observation overhead. Failure
withholds comparisons and is preserved.

## Saved-receipt replay

Run the portable auditor from the repository root with a new output filename:

~~~powershell
python -S -X utf8 -m scripts.audit_observer_query_treatment --report results/observer-query-treatment/report.json --protocol fixtures/observer-query-treatment/protocol.json --freeze fixtures/observer-query-treatment/implementation.json --output reports/runs/your-fresh-review/observer-query-treatment-audit.json
~~~

The auditor reads saved JSON and source/dependency/raw-file hashes without ML,
native execution, live process queries or training. It also checks the pinned
historical v2 report and portable/local audit files. This published record returns
exit 0 with 8894 checks. Optional local executable/model/provider checks remain
unperformed unless explicitly supplied; the published 8898-check local-file audit
is separate. Saved consistency is not an OS remeasurement.

## Optional separately reviewed Windows reproduction

Review exact source/auditor, pinned offline assets, executable files and canonical
path hashes, provider source and treatment protocol first. Prepare a new reviewed
reproduction freeze before at most one suite in a nonexistent fresh directory;
preserve the historical freeze and any failed outcome.

~~~powershell
& "<PINNED_VENV_PYTHON>" -S -X utf8 -m experiments.observer_query_treatment --python "<PINNED_VENV_PYTHON>" --base-python "<PINNED_BASE_PYTHON>" --native "<PINNED_SYSTEM32_CMD_EXE>" --conhost "<PINNED_SYSTEM32_CONHOST_EXE>" --provider-source "<PINNED_SITE_PACKAGES>\urllib3\util\connection.py" --model-dir "<PINNED_LOCAL_MODEL_DIR>" --fixture fixtures/activation-cost --protocol "<REVIEWED_REPRODUCTION_PROTOCOL_JSON>" --freeze "<REVIEWED_REPRODUCTION_FREEZE_JSON>" --output reports/runs/your-fresh-reproduction/observer-query-treatment
~~~

A different machine/path needs a separately reviewed freeze. Any protocol/source
change also needs its own declared auditor pins; do not edit historical pins.
There is no real-workload preflight, automatic retry, seed/learning-rate rescue,
provider purchase, download, compression arm, holdout evaluation or checkpoint.

The finite [v2 acknowledgment study](../../results/observer-duty-v2/report.md)
retains its 6185 portable/6189 local checks. The [v1 ordering rejection](../../results/observer-duty/report.md),
six scientific cost/final-quality failures and invalid historical RSS remain
unchanged. This finite treatment study grants no model-quality, compression, GPU,
backward-peak or production-reliability claim.
