# Two updates: logical state and native process memory disagree

**One separately frozen worker completes one Pythia-14m load and two dense AdamW
updates, passing 23382/23382 portable receipt checks and 23386/23386 with optional
local-file checks.** The record contains eight operator intervals, nine training
inventories, twelve held memory brackets, thirteen role censuses and 26
acknowledged controls. All five retained identities exited 0 and the Job became
empty; 110 per-worker raw JSON receipts are preserved.

This finite engineering pass does not mean every operator was sampled. Both
`zero_grad` intervals had zero fully contained active queries, so their current
sample maxima remain **null / unobserved**. The other six phases have finite
sampled lower bounds. The structural result is explicit first-update AdamW state
creation and second-update reuse; native process changes do not equal logical
tensor bytes.

A separate [independent outcome review](independent-outcome-summary.json) passes
6,943 independently recomputed checks. Its optional local-file replay overlaps the
frozen audit; these counts are not additive model tests.

## Execution and timing boundary

The protocol was declared at 17:10:36 UTC, frozen at 17:15:31 UTC and executed
once from 17:15:45 to 17:16:00 UTC on 2026-10-17. Total suite wall was
**15.589065 seconds**, including import, loading, instrumentation and cleanup.
There was one fresh pinned offline Pythia-14m worker, seed 503, CPU float32/eager,
threads 1/1, empty initial AdamW state and two fixed batches `[116,73]` and
`[14,52]`. No warmup, retry, extra model, compression arm, holdout or checkpoint
was used.

The eight operator wall intervals sum to **0.428679 seconds**. The instrumented
span from the first operator start through entry into B8 is **1.987344 seconds**;
it includes intervening holds, controls, receipts and separately timed optimizer
housekeeping. It excludes B8's subsequent hold and final validation. These are
different timing scopes, not an estimate of total monitoring overhead or
uninstrumented training throughput. Operator clocks include clock reads and
fixed dispatch overhead; inventory, files, held scans, hashes and loss-scalar
housekeeping lie outside them.

The two optimizer housekeeping intervals total **0.0005185 seconds**; their
individual walls were 0.0002711 and 0.0002474 seconds. Nine primitive inventories
total **0.0159451 seconds**, excluding their JSON writing and other holds. These
selected costs do not exhaust all instrumentation work. Each wider parent CPU
window also includes polling/control and completion detection; its zero readings
are observations at native timer resolution, not evidence of zero cost.

## Eight operators and the sampling gap

The parent queried current memory/native CPU through the retained, authenticated
actual-interpreter handle with a 20 ms target. There were **37 raw queries,
22 wholly contained selected queries and 15 excluded queries**. All excluded
rows remain saved. No active Toolhelp snapshot was performed; its fields are
null/unperformed.

| Update / operator | Operator wall, ms | Selected / raw queries | Active sampled resident maximum, bytes | Active sampled private maximum, bytes |
| --- | ---: | ---: | ---: | ---: |
| 1 / zero_grad | 0.299300 | 0 / 2 | null / unobserved | null / unobserved |
| 1 / forward + CE | 55.301200 | 3 / 4 | 406847488 | 476561408 |
| 1 / backward | 70.751100 | 4 / 5 | 444043264 | 511438848 |
| 1 / optimizer.step | 122.027400 | 6 / 9 | 580792320 | 688640000 |
| 2 / zero_grad | 0.300600 | 0 / 2 | null / unobserved | null / unobserved |
| 2 / forward + CE | 40.265300 | 2 / 4 | 583004160 | 691482624 |
| 2 / backward | 64.340800 | 3 / 5 | 583081984 | 691552256 |
| 2 / optimizer.step | 75.393200 | 4 / 6 | 583610368 | 692207616 |

The zero_grad walls were about 0.2993 and 0.3006 ms. Their held endpoint readings
below do not repair the absence of an interior query. The six sampled phases had
maximum endpoint-inclusive gaps of about 19.9648–20.4516 ms. Even those gaps
provide **no upper bound on missed peak bytes**; the saved
`missed_peak_bytes_upper_bound` remains null for all eight operators. Current
resident/private maxima are whole-process sampled lower bounds, not isolated
backward/full peaks, hard caps or GPU memory.

The first optimizer wall was 122.027400 ms and the second 75.393200 ms. These
ordered calls differ in prior allocator/kernel history, gradients, batches and
instrumentation history. One first call and one second call are not replicated
causal treatments or an isolated AdamW initialization-cost estimate.

## Logical state at held boundaries

Every training boundary completed full self-before, retained-parent and
self-after native query intervals in order before its richer primitive inventory.
The model has 76 parameter tensors containing **56270848 logical bytes**, plus
one 16-byte model buffer. Parameters, gradients, moments, step scalars and a live
loss scalar are recorded separately. Backing capacity is deduplicated across
categories within each snapshot only; raw addresses are not published or unioned
across boundaries.

Both backward boundaries have 76 gradients containing 56270848 logical bytes.
Optimizer state is empty through B3. At B4 it has 76 entries: 152 moment tensors
containing **112541696 logical bytes**, plus 76 float32 step scalars containing
**304 bytes**, all counters 1. Counts and moment logical capacity remain the same
through the second update; all counters are 2 at B8. No additional training was
used to establish this sequence.

| Held boundary | Inventoried unique backing union, bytes | Parent current resident, bytes | Parent current private, bytes |
| --- | ---: | ---: | ---: |
| B0 / loaded baseline | 56270864 | 352387072 | 380121088 |
| B1 / 1 / zero_grad | 56270864 | 352559104 | 380121088 |
| B2 / 1 / forward + CE | 56270868 | 415961088 | 476561408 |
| B3 / 1 / backward | 112541716 | 444047360 | 511438848 |
| B4 / 1 / optimizer + housekeeping | 225083712 | 580853760 | 688640000 |
| B5 / 2 / zero_grad | 168812864 | 580222976 | 688787456 |
| B6 / 2 / forward + CE | 168812868 | 583004160 | 691482624 |
| B7 / 2 / backward | 225083716 | 583540736 | 692207616 |
| B8 / 2 / optimizer + housekeeping | 225083712 | 583610368 | 692207616 |

B4 and B8 follow separately timed scalar logging and deletion of the live loss
binding. They are **post-optimizer-housekeeping boundaries**, not instantaneous
optimizer-return memory. The 4-byte loss is present at B2/B3 and B6/B7. Inputs,
batches, saved activations, temporary operator buffers, Python objects, native
libraries, allocator slack and other process allocations are outside this tensor
inventory even when they remain in native current readings.

The differences are visible without converting logical bytes into physical
allocation claims:

| Boundary change | Logical category change | Backing union change, bytes | Resident change, bytes | Private change, bytes |
| --- | --- | ---: | ---: | ---: |
| B3 → B4 | moments +112541696; step scalars +304; loss −4 | +112541996 | +136806400 | +177201152 |
| B4 → B5 | gradients −56270848 | −56270848 | −630784 | +147456 |
| B6 → B7 | gradients +56270848 | +56270848 | +536576 | +724992 |
| B7 → B8 | loss −4; moment capacity unchanged | −4 | +69632 | 0 |

For example, clearing gradient references at B5 removes 56270848 logical bytes,
while resident decreases only 630784 bytes and private increases 147456 bytes.
The next backward restores the same logical gradient size while current resident
increases 536576 bytes. These signed observations are compatible with allocator
reuse and other process history, but do not isolate their causes. There was no
requirement that OS current memory fall by the gradient size or track moment
creation byte for byte.

Holds deliberately prolong graph/loss lifetimes. Self queries, provider receipts,
role scans, inventory construction, JSON and allocation history perturb later
readings. The native current bracket precedes the logical snapshot, so they are
not exactly simultaneous. This is an instrumented sequence with stage labels,
not an uninstrumented tensor-only memory decomposition.

## Custody, verification and limits

The initial and final parameter hashes differ, all 76 final parameter/gradient/
moment checks are finite and all optimizer counters equal 2. Logged losses
4.0769915581 and 4.2589492798 are different-batch trajectory receipts, not quality
or improvement evidence. The exact final continue acknowledgment preceded both
retained live checks and finish emission. The single pinned urllib3 import
capability-probe diagnostic stayed cumulative; it does not prove OS bind success
or native network isolation. Held role checks do not prove continuous process
absence or production reliability.

See the [raw report](report.json), [summary](summary.json), [portable frozen audit](frozen-audit.json)
and [optional local-file audit](local-file-audit.json). From the repository root,
choose a fresh output filename for a saved-receipt replay:

```powershell
python -S -X utf8 -m scripts.audit_training_phase_memory --report results/training-phase-memory/report.json --protocol fixtures/training-phase-memory/protocol.json --freeze fixtures/training-phase-memory/implementation.json --output reports/runs/your-fresh-review/training-phase-memory-audit.json
```

The auditor recomputes saved custody, interval selection, logical arithmetic and
source/raw hashes without importing Torch or performing live/native measurements.
The 23386-check local-file record additionally verifies explicitly supplied local
executable/provider/model paths; it is not a new model run. A new machine or
changed source/protocol needs its own reviewed freeze.

| Artifact | SHA256 |
| --- | --- |
| Raw report | `f48812bf945a7fdfcb76afcde2336dd545e9263876f2cb363c9189a60f87b8ca` |
| Protocol | `dc935322fcddc13380b0a9aee88a60d3ef2826051cd18d8145196b98ecaa4c85` |
| Implementation freeze | `56e643f3d5fd2f17834f88da4cb499e6d543f813aee7db134369e4194dff80c6` |
| Producer | `616fb694a36a1205f425f3e2db118e4ff4139a6d948a2e9e4c5e000c54ed0d3a` |
| Portable auditor | `b98bdadf4004004452d880af38a2a86c70920f89c1a98417394d60d3f2dd000d` |

Historical v1 ordering rejections, accepted v2/query-treatment finite records,
six failed scientific cost/final-quality screens and invalid historical parent
RSS retain their prior status. H3/H4 remain unexecuted. This result supplies no
compression advantage, model-quality improvement, isolated peak, hard-cap,
GPU or production claim. Any subsequent treatment needs separate controls and
freeze; these two updates were not retried or adjusted after observing them.
