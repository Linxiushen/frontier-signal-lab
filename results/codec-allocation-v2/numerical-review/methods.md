# Descriptive numerical review of the saved codec allocation v2 suite

This is a post-outcome, stdlib-only review of saved JSON. It does not import the producer, frozen auditor, Torch, NumPy or upstream code, and does not launch a model, provider, observer or new experiment. The sole actual suite contains eight sequential workers, each with one model load, one forward with exact cross entropy, one backward and zero optimizer updates. No holdout is opened. Seed 503, fixed batch indices [116, 73], batch shape [2, 65], Pythia-14m revision cf967c0a9a04383db6f7b1108d86b2962634b4ac and the original fixed case order are retained.

`numerical-summary.json` lists hashes and byte counts for every consumed report, protocol, operation and allocator trace. `summarize.py` independently rebuilds pointer epochs from the raw timestamped allocation/free events, joins storage observations to strict live intervals, recomputes callback-created/temporary/returned allocations and recomputes all held owner subset totals. It compares those computations with the saved reducer outputs; 19,478/19,478 consistency checks pass. This is saved-receipt arithmetic, not OS remeasurement or a repetition of the experiment.

This review code and these summaries were written after observing the suite outcome. They are outside the frozen experiment implementation and do not alter its gates or acceptance. From the repository root, any standard Python with the standard library can reproduce and compare the numerical review:

```text
python results/codec-allocation-v2/numerical-review/summarize.py --expected-summary results/codec-allocation-v2/numerical-review/numerical-summary.json
```

The default input paths are the public `results/codec-allocation-v2/` evidence and `fixtures/codec-allocation-v2/protocol.json`; the script locates them from its own repository location, independently of the current working directory. Without `--output`, it writes no files and prints a compact verification receipt. `--output PATH` additionally saves the complete recomputation to a new file, rejecting an existing target. The saved `summarized_at` review timestamp is the only field excluded from expected-summary equality; all input hashes, values, ratios, storage lifetime rows and check outcomes must match. A timestamp-independent payload SHA256 is also printed. No private model assets, environment directory, external package, network access or ML execution is needed.

## Timing definitions and pairing

The reported study operator wall time is the sum of the saved forward-plus-cross-entropy timer and backward timer. It excludes the owner snapshot between the operators and post-backward scalar extraction, deletion, gradient hashing/finiteness checks, zero_grad and owner snapshots. The wider forward-start-to-backward-completed interval includes the between-operator owner snapshot and is separately recorded. None of these times include model loading or the complete worker lifecycle.

ON callback times sum the clock around the codec body itself. They exclude registry updates and profiler record_function setup/teardown. OFF callback times are null, not zero. These callback-body sums and ON/OFF elapsed ratios do not measure total observer cost.

| Case | Forward+CE s | Backward s | Operator sum s | ON pack-body sum s | ON unpack-body sum s |
|---|---:|---:|---:|---:|---:|
| 01 OFF dense | 0.054716900 | 0.073623200 | 0.128340100 | null | null |
| 02 OFF INT8 | 0.063676600 | 0.078649600 | 0.142326200 | null | null |
| 03 OFF INT8 | 0.063260000 | 0.075419500 | 0.138679500 | null | null |
| 04 OFF dense | 0.054968800 | 0.073856100 | 0.128824900 | null | null |
| 05 ON dense | 0.067696900 | 0.088297200 | 0.155994100 | 0.001140799 | 0.000071600 |
| 06 ON INT8 | 0.078044000 | 0.088949400 | 0.166993400 | 0.011303099 | 0.001695200 |
| 07 ON INT8 | 0.080692100 | 0.090690700 | 0.171382800 | 0.011487300 | 0.001717799 |
| 08 ON dense | 0.067483000 | 0.086981100 | 0.154464100 | 0.001143100 | 0.000076200 |

The first and second occurrences of each method are paired in the frozen order: 05/01 and 08/04 for dense ON/OFF, 06/02 and 07/03 for INT8 ON/OFF. OFF method ratios pair adjacent outer/inner positions, 02/01 and 03/04. Each ratio is numerator timer divided by denominator timer. The geometric mean is exp(mean(log(ratio))). The JSON gives separate forward, backward and operator-sum ratios; the table below uses the operator sum.

| Description | First ratio | Second ratio | Geometric mean |
|---|---:|---:|---:|
| Dense ON/OFF | 1.215474353 | 1.199023636 | 1.207220973 |
| INT8 ON/OFF | 1.173314540 | 1.235819280 | 1.204161422 |
| OFF INT8/dense | 1.108976851 | 1.076496082 | 1.092615776 |

There are two observations per cell on one host in one fixed sequence, with all OFF workers before all ON workers. No randomization, confidence interval, independent replication or causal overhead claim follows. Dense uses the same saved-tensor hook and protected module scopes; it is a hooked dense comparator.

## Raw allocator requests, callbacks and returned backing

The profiler starts before model preparation/loading and covers the held postload interval, operators, post-operator validation/zero_grad and owner boundaries. It is not an isolated forward/backward trace. The following quantities are CPU allocator requested bytes. Repeated allocations contribute repeatedly to cumulative totals; those totals are not simultaneously live memory or resident/private process capacity.

| ON case | Raw events | Positive allocations | Negative frees | Cumulative positive requested B | Cumulative freed requested B | Right-censored allocations / requested B |
|---|---:|---:|---:|---:|---:|---:|
| 05 dense | 2,584 | 1,331 | 1,253 | 510,189,936 | 453,918,032 | 78 / 56,271,904 |
| 06 INT8 | 3,572 | 1,825 | 1,747 | 539,068,051 | 482,796,147 | 78 / 56,271,904 |
| 07 INT8 | 3,572 | 1,825 | 1,747 | 539,068,051 | 482,796,147 | 78 / 56,271,904 |
| 08 dense | 2,584 | 1,331 | 1,253 | 510,189,936 | 453,918,032 | 78 / 56,271,904 |

All event allocation IDs are missing; the frozen identity policy uses pointer epochs. No equal-time same-pointer ambiguity, unknown preexisting free or reduction problem occurs in these saved traces. The largest single positive request in each full trace is 28,143,920 B, separate from callback workspace.

Each ON case has 352 callbacks (176 pack, 176 unpack), including 33 outer pack/unpack calls and 19 eligible outer saves. Dense callbacks create zero profiler-reported allocations within their callback markers, but still return preexisting backing and consume elapsed time. This is not zero Python/runtime/observer cost.

In each ON INT8 case, callbacks create 494 allocations totalling 28,878,115 requested B. Pack creates 456 / 21,669,155 B; unpack creates 38 / 7,208,960 B. Of all created allocations, 437 are same-thread temporaries created and destroyed strictly inside their callback and excluded from identified returned backing. The largest single callback's simultaneously live temporary requests are 524,800 B for pack and 262,144 B for unpack. These differ from the largest single callback's cumulative created requests: 1,575,089 B for pack and 524,288 B for unpack. Neither is a process or GPU peak.

The 19 eligible INT8 packs return 38 distinct allocations: 19 code backings / 901,120 B plus 19 scale backings / 9,728 B, totalling 910,848 B. The 19 compressed unpacks return 19 newly created decoded float backings / 3,604,480 B. Returned backing is separate from temporary workspace. Exact callbacks may return old allocations, so returned allocation unions cannot be read as newly allocated callback bytes. The JSON separately records all-returned unions and the subset created strictly inside the returning callback.

## Held boundaries and outer storage lifetimes

| ON method (both occurrences identical) | After forward+CE selected B | After backward selected B | After loss/logits deletion selected B | After zero_grad selected B |
|---|---:|---:|---:|---:|
| Dense | 37,321,728 | 30,487,552 | 30,487,552 | 30,487,552 |
| INT8 | 34,628,096 | 30,487,552 | 30,487,552 | 30,487,552 |

Every registered owner row has a unique allocator binding and agrees with its weak strong-ownership probe. This establishes complete coverage only of the selected registered saved-source/payload/decoded subset. It includes exact and parameter backing and omits unregistered buffers; it is not all saved activations, a whole-process measurement or a peak. The after-forward subset difference is 2,693,632 B, not an OS/GPU memory saving claim.

For dense, the 19 outer eligible source storages total 3,604,480 requested B. The 19 returned payload storages alias those same 19 sources, so their byte totals must not be added. All 19 have live backing and strong ownership at after-forward; all have been freed and owner-expired by after-backward and remain so at the final two probes. Dense has no decoded role.

For INT8, all 19 eligible source storages / 3,604,480 B are already freed and owner-expired at after-forward. All 38 code/scale payload storages / 910,848 B are live at that probe and freed/owner-expired by after-backward. All 19 decoded float storages / 3,604,480 B are created during backward and freed/owner-expired before the after-backward probe. They are not yet registered at after-forward; that point supplies no decoded-owner expiry observation. Every individual outer-source/payload/codes/scales/decoded storage's creation, destruction, observed allocator lifetime and censoring state appears in the JSON, together with each of the four boundary role aggregates. Role groups overlap and are not additive.

Strong-owner expiry and allocator free describe backing lifetime, not pages returned to the OS. ON profiler/weak registry/held snapshots alter lifetime and timing. This tiny forward/backward diagnostic has no optimizer update, quality endpoint, full training peak, production proof or GPU measurement; the historical failed scientific screens and invalid old RSS remain unchanged.
