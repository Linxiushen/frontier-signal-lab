# Common memory queries, optional Toolhelp snapshots

**One frozen M/T/T/M study passes finite engineering acceptance:** 8894/8894
portable audit checks and 8898/8898 with optional local-file checks. Four fresh
pinned local Pythia-14m workers performed **four model loads and 64 dense AdamW
updates**. Every worker received retained-handle memory/native-CPU queries; only
T additionally took active global Toolhelp snapshots. There is no observation-off
baseline.

The two observed T/M training-loop wall ratios are **1.069392 / 1.016469**. These
are two descriptive pairs, not a population estimate, general causal result,
savings claim or measurement of total monitoring cost. No favorable performance
threshold was used.

## Execution and custody

The protocol was declared at 14:57:40 UTC, frozen at 15:06:14 UTC and executed
once from 15:06:29 to 15:07:32 UTC on 2026-10-17. Total suite wall time was
63.456861 seconds, including setup, controls and cleanup. The raw report and
176 per-worker JSON receipts are retained. A separate outcome review independently
recomputed 97 saved-receipt/hash/arithmetic checks without another workload.

Workers ran in **M / T / T / M** order, with seed 503, fresh empty AdamW state,
the same 16 fixed batches, CPU float32/eager and one intra/inter-op thread. All
four initial/schedule/final parameter hashes and entire 16-loss trajectories
match exactly. Losses and parameter changes are trajectory receipts, not quality
evaluation.

The unchanged v2 final barrier authenticated the exact worker acknowledgment
before parent wait completion, both retained live checks and finish emission.
There were 24 held role censuses, 20 held memory brackets and 48 emitted controls.
All 20 retained identities exited 0 and all four Jobs became empty. Exact pinned
provider diagnostics retain one urllib3 import capability-probe audit attempt per
worker; this establishes neither OS bind success nor native network isolation.

## Recorded query costs

M means `memory_only`; T means `memory_and_toolhelp`. Both use the same 20 ms
completion polling target. These table values use only observations wholly inside
the actual worker loop, while parent CPU covers the wider release-to-completion
detection window.

| Case | Loop wall s | Parent CPU s, wider window | Selected / raw observations | Memory/CPU query wall s | Snapshot wall s | Selected query work / loop wall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| pair1_memory | 3.080093 | 0.000000 | 154 / 156 | 0.008848 | null / unperformed | 0.2873% |
| pair1_toolhelp | 3.293826 | 2.343750 | 134 / 136 | 0.006624 | 2.230975 | 67.9331% |
| pair2_toolhelp | 3.199178 | 2.328125 | 139 / 142 | 0.007071 | 2.255356 | 70.7190% |
| pair2_memory | 3.147344 | 0.000000 | 157 / 159 | 0.009638 | null / unperformed | 0.3062% |

The M parent-CPU deltas of zero are observations at the native counter's
resolution. **They do not establish zero cost:** M performed actual queries and
has nonzero query wall sums. M snapshot start/end/count and snapshot wall are
null because those active snapshots were not performed.

The large T snapshot wall sums dominate its selected query work. Wall fractions
are not CPU fractions, slowdown percentages or total observer costs. They exclude
boundary-crossing queries and common polling/control work; parent native CPU
includes the wider window. Global Toolhelp counts are query metadata, not active
role admission or proof of continuous child absence. The same held role scans and
liveness policy remain in both treatments.

Selected query rates in case order were 50.00 / 40.68 / 43.45 / 49.88 per second.
Maximum boundary-inclusive gaps were 0.02052 / 0.04596 / 0.04777 / 0.02229 seconds.
The 20 ms target did not promise identical realized frequencies. M selects complete
memory-query intervals; T also requires its following snapshot to fit inside the
loop. Every excluded boundary row remains saved, so selected work has this
treatment-specific boundary rather than a common event count.

| Pair | T/M loop-wall ratio | Signed T minus M, seconds | Signed relative wall change |
| --- | ---: | ---: | ---: |
| pair1_toolhelp / pair1_memory | 1.0693918120894939 | +0.213733 | +6.9392% |
| pair2_toolhelp / pair2_memory | 1.016469188001794 | +0.051834 | +1.6469% |

The geometric mean ratio is **1.042595**; its signed relative change is
**+4.2595%**. Signs are preserved, including negative values in the declared
analysis if T had been faster. Two short counterbalanced pairs cannot establish
that Toolhelp alone generally causes this change. Neither treatment measures
observation-off execution, and these data do not estimate all-observation
overhead. Comparisons with the earlier v2 study would mix different runs and
controls.

## Current memory readings

| Case | Sampled current resident maximum, bytes | Sampled current private maximum, bytes |
| --- | ---: | ---: |
| pair1_memory | 584409088 | 692174848 |
| pair1_toolhelp | 584388608 | 692142080 |
| pair2_toolhelp | 584081408 | 691970048 |
| pair2_memory | 584531968 | 692056064 |

All four memory results are **sampled lower bounds on whole-process current
readings**, including model, optimizer, gradients and allocator history. They are
not isolated backward/full peaks, memory savings, GPU memory or hard caps.
Different cadence and boundary selection also prevent reading these maxima as a
memory benefit. Loading, final hashing/validation, held scans and the final
acknowledgment barrier are outside the timed loop; prior allocations remain in
the process.

## Verify and preserve the limits

See the [raw report](report.json), [summary](summary.json), [frozen portable audit](frozen-audit.json),
[local-file audit](local-file-audit.json) and [73 prefreeze mock/synthetic tests](prefreeze-guarded-tests.json).
The tests comprise 37 producer and 36 independent auditor tests; they are separate
from the four actual model workers. From the repository root, select a new output:

~~~powershell
python -S -X utf8 -m scripts.audit_observer_query_treatment --report results/observer-query-treatment/report.json --protocol fixtures/observer-query-treatment/protocol.json --freeze fixtures/observer-query-treatment/implementation.json --output reports/runs/your-fresh-review/observer-query-treatment-audit.json
~~~

This returns exit 0 for the saved record and checks source/dependency/raw bytes,
receipt consistency, arithmetic and pinned historical v2 evidence. It imports no
ML and performs no live process or training measurement. Optional local executable,
model and provider-file checks require their explicit paths. See the [protocol and
separately reviewed Windows reproduction command](../../fixtures/observer-query-treatment/README.md).

The [v2 acknowledgment study](../observer-duty-v2/report.md) keeps its finite
6185/6189-check acceptance. The [v1 study](../observer-duty/report.md) keeps all
four ordering rejections. Six failed scientific cost/final-quality screens,
invalid historical RSS and H3/H4's unexecuted status remain unchanged. No
compression, model-quality, GPU, isolated-peak or production-reliability result
follows from this treatment study. Any next treatment needs its own predeclared
controls and freeze; this suite was not retried or adjusted after its outcome.
