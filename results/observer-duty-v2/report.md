# Observer duty v2: the final acknowledgment barrier passes

**The separately frozen v2 study passes engineering acceptance:** 6185/6185
portable audit checks and 6189/6189 with optional local-file checks, with no
rejections. One execution performed **four pinned local Pythia-14m loads and 64
dense AdamW updates**. The correction waits for the final worker acknowledgment
before checking retained live processes and emitting finish.

The [v1 study](../observer-duty/report.md) remains rejected on all four original
ordering checks. Its frozen files and recorded data remain unchanged, as do the
six earlier failed scientific cost/final-quality screens and invalid historical
parent RSS. V2 changes no training or sampler treatment and establishes no
compression, model-quality, GPU or production result.

## What passed

The protocol was declared at 12:50:56 UTC and frozen at 12:56:36 UTC on
2026-10-17. The sole suite ran from 12:56:56 to 12:57:56 UTC, taking 60.064705
seconds including setup, controls and cleanup. Its 176 per-worker JSON receipts
and raw report are retained.

All four cases satisfy the saved order:

`continue request <= worker acceptance <= parent wait completion <= both retained live checks <= finish emission`

The parent authenticates the exact nonce, worker PID/retained creation identity,
control envelope, filename and next index. Its wait deadline is bounded once by
five seconds and the original case/suite deadlines. An acknowledgment may precede
the parent's wait start; the recorded cases all accepted during the wait. Wait
durations were 22.053 / 21.624 / 21.973 / 22.095 ms in case order. These waits are
outside the timed training loop.

The four workers used seed 503, fresh empty AdamW state, the same 16 fixed batches,
CPU float32/eager and one intra/inter-op thread in **OFF / ON / ON / OFF** order.
All initial/schedule hashes, final parameter hashes and entire 16-loss trajectories
match exactly. There are 24 held role censuses, 20 memory brackets and 48 emitted
controls. All 20 retained process identities exited 0 and all four Jobs became
empty. Exact provider receipts retain one pinned urllib3 import capability-probe
audit attempt per worker; this does not establish OS bind success or native
network isolation.

## Descriptive observation costs

| Case | Full-loop wall s | Parent CPU s, wider window | Selected observations | Selected query/snapshot wall / loop wall |
| --- | ---: | ---: | ---: | ---: |
| pair1_off | 3.053044 | 0.015625 | unobserved | unobserved |
| pair1_on | 3.175089 | 2.328125 | 147 | 73.39% |
| pair2_on | 3.202095 | 2.343750 | 142 | 70.82% |
| pair2_off | 3.015668 | 0.000000 | unobserved | unobserved |

The two ON/OFF wall ratios are **1.039975 / 1.061819**, with geometric mean
**1.050840**. This describes two counterbalanced pairs under this fixed
intervention. There is no favorable slowdown threshold or population estimate;
these observations do not establish a general 5.1% overhead, negligible cost or
causal attribution to an individual query. The difference from v1's rejected
ratios is not evidence of an improvement.

ON retained 149/144 raw active observations; 147/142 were wholly inside the actual
helper loop. Realized selected rates were 46.30/44.35 per second, with maximum
boundary-inclusive gaps of 0.04725/0.04431 seconds. The 20 ms target did not imply
an exact 50 Hz realized rate.

Selected global Toolhelp snapshots consumed 2.323257/2.260963 seconds of wall
time, versus 0.006852/0.006860 seconds for memory/native-CPU queries. They dominate
the recorded query wall sums. The 70.82–73.39% fractions are **wall fractions**,
not CPU fractions, training slowdown percentages or total observer costs. They
exclude boundary-crossing queries and common polling/control work. Parent native
CPU covers a wider release-to-completion-detection window than the worker loop.
Active global process counts do not establish admitted roles or continuous child
absence.

ON current resident maxima were 584208384 / 584470528 bytes; private maxima were
691773440 / 692207616 bytes. These are sampled lower bounds on whole-process
current readings, including allocator history. **OFF is null/unobserved.** The
readings do not isolate backward/full peaks, memory savings, a hard cap or GPU
memory. Loading, final hashing/validation, held scans and the acknowledgment
barrier sit outside the timed loop; prior allocations remain part of the process.

## Verify and continue

The [raw report](report.json), [summary](summary.json), [frozen portable audit](frozen-audit.json)
and [local-file audit](local-file-audit.json) retain separate meanings. The
[61 prefreeze mock/synthetic tests](prefreeze-guarded-tests.json) comprise 33
producer and 28 independent audit tests, including delayed/missing/malformed
acknowledgment and early-finish controls; they are not additional model runs.
See the [protocol, limits and replay command](../../fixtures/observer-duty-v2/README.md).

Portable saved-receipt replay must return exit 0 for this record. It checks saved
identity/role/provider/control/cleanup consistency and hashes, without live OS
remeasurement or training. Passing this finite engineering study does not change
the earlier scientific failures or the pending H3/H4 execution status. A future
query-cost reduction needs a separately declared observer treatment and matched
controls; changing this record or pooling its two pairs with v1 would not provide
that comparison.
