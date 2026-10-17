# Observer duty: end-barrier ordering rejected

**Joint acceptance is false.** One frozen four-worker study performed four local
Pythia-14m loads and 64 dense AdamW updates. The producer reported four successful
cases; the frozen independent auditor rejects one prefinish ordering condition
in every case: **5524/5528 checks pass, four remain rejected**. Optional local-file
hashing gives 5528/5532 with the same four failures. Passing checks are not a
replacement acceptance decision.

The raw report and all 176 per-worker JSON receipts are unchanged. No retry,
threshold change, frozen-code repair, compression arm, holdout scoring or
checkpoint was performed. Earlier six failed cost/final-quality screens and
invalid historical parent RSS remain unchanged.

## What failed

The controller emits `postvalidation-continue`, then immediately checks the
retained worker and native process, then emits `finish`. It does not wait for
the worker's acceptance of that continue command. Saved clocks show both live
checks and the finish emission **before** that acceptance in all four cases.
The frozen auditor requires worker acceptance before the live checks. The gap
from live check to worker acceptance is about **3.0–20.4 ms**. Both processes were
alive/Job members at the recorded checks, and all 20 retained identities later
exited 0 with four empty Jobs; that does not satisfy the missing ordered barrier.
There is no evidence here of a process death or failed training step.

## Recorded data from the rejected study

These are descriptive saved values, **not an accepted overhead result**. Initial
weights, schedule, final parameter digest and the complete 16-loss trajectory
match exactly across all four workers. Fixed order was OFF / ON / ON / OFF,
seed 503, one CPU intra/inter-op thread and fresh AdamW state per worker.

| Case | Full-loop wall s | Parent CPU s, wider window | Selected observations | Selected query/snapshot wall / loop wall |
| --- | ---: | ---: | ---: | ---: |
| pair1_off | 3.122702 | 0.031250 | unobserved | unobserved |
| pair1_on | 3.309922 | 1.984375 | 109 | 61.08% |
| pair2_on | 3.482533 | 2.062500 | 102 | 58.47% |
| pair2_off | 3.133741 | 0.000000 | unobserved | unobserved |

The producer's two ON/OFF ratios are **1.059954 / 1.111302**, geometric mean
**1.085325**. They remain unaccepted study data, with only two exploratory pairs;
do not claim a validated 8.5% slowdown, negligible overhead or general causality.

ON selected 109/102 observations at 32.93/29.29 per second, with maximum
boundary-inclusive gaps 0.05288/0.05161 seconds. The target was 20 ms; realized
frequency was lower. Retained global Toolhelp snapshots took about 2.016/2.031 s
in aggregate, versus 0.00570/0.00560 s for memory/native-CPU queries. The
58.47–61.08% selected query wall fractions are not CPU fractions or total observer
cost. Parent native CPU spans the wider release-to-completion window, including
common polling and control work.

ON sampled current resident maxima were 583827456 / 583987200 bytes; private
maxima were 691802112 / 691744768 bytes. These are whole-process sampled lower
bounds, not isolated backward/full peaks, memory savings, a hard cap or GPU
memory. OFF memory is null/unobserved. Loading, final hashing/validation and held
boundary scans are outside the timed full loop; loading/allocator history is
still part of the process. Active global process counts do not admit roles.

## Verify and next gate

The [frozen audit](frozen-audit.json), [optional local byte audit](local-file-audit.json),
[post-outcome summary](summary.json), [raw report](report.json) and
[prefreeze tests](prefreeze-guarded-tests.json) retain their separate meanings.
The 45 prefreeze tests are mocks/mutations, not extra model runs.
See the [protocol and commands](../../fixtures/observer-duty/README.md).

The frozen success-audit command must continue to exit 1 on this record. A
separate post-outcome preservation checker verifies that exact rejection; its
success never grants experiment acceptance. Future work must separately freeze
an actual end-barrier fix: wait for the exact worker continue acknowledgment,
then timestamp retained live checks and finish emission; include a delayed-ack
mock that forbids early finish. Preserve this record and rerun no part of this
suite. Any later query-cost reduction needs a new declared treatment and controls,
not a retrospective correction of these numbers.
