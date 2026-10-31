# Pi native bounded-burst load: one accepted fixed suite

On 2026-10-31, 16:11:18–16:11:39 UTC, one separately frozen suite passed four arms on the unchanged v2 adapter, official Pi/Chord1.4.0 and Node24.19.0. Each arm has four logical conversations in **one durable Session/database**, three bursts of four unique arrivals, three identity/authority probes per burst, and two actual process kills/reopens. Twelve distinct process starts and eight kills/reopens were observed; final workers close normally. There were no models or providers.

All four arrivals in a burst are offered before any effect is released. Overload refusals are not retried. Conversation1 is revoked after first admission; one later admitted task is cancelled before effect release. Every arm has one denied and one aborted task, neither with an effect. The other admitted tasks each commit their exact local payload once. Recovered tasks resume `finish`; capacity is never exceeded and final active count is zero.

| Arm | Admitted / offered | Overload refusals | Committed / effect-eligible offered | Arm wall s | Effects / arm s | Committed observed p95 ms | Max sampled private B | Sink callback / final flush ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cap2-direct | 6/12 | 6 | 4/10 | 5.079 | 0.788 | 1687 | 85594112 | 60.287 / 0.004 |
| cap2-buffered | 6/12 | 6 | 4/10 | 4.985 | 0.802 | 1674 | 85561344 | 17.745 / 2.814 |
| cap4-buffered | 12/12 | 0 | 10/10 | 5.344 | 1.871 | 1754 | 85250048 | 17.338 / 2.924 |
| cap4-direct | 12/12 | 0 | 10/10 | 5.516 | 1.813 | 1955 | 85143552 | 79.235 / 0.002 |

The 12 unique arrivals and 10 effect-eligible targets are separate denominators; the 21 admission calls also include three duplicate, three conflict and three stale-authority probes. Capacity2 admits6/refuses6 and commits4, while capacity4 admits12/refuses0 and commits10. These are the specified finite-burst outcomes, not a claim that capacity4 improves a general service. Accepted sets differ, so their latency distributions do too. Full per-arm p50/p95/p99, all-admitted and committed-only timing, admission timing, queried OS working-set high-water and output/database bytes are in `report.json`.

Arm wall includes startup, injected gates/delays, two restarts, endpoint database reads and controller acceptance. Process-stage wall is separately recorded. The suite wall is21.094s; the invocation additionally verified12,765 runtime files before the suite timer. End-to-end timings use arrival-to-observed-terminal epoch milliseconds, including held checkpoints and restart startup. Polling/clock resolution and only4or10 committed samples limit interpretation; p95/p99 here equal the maximum. They do not establish service tails or SLOs.

Direct/buffered full-arm wall ratios were 1.019 at capacity2 and 1.032 at capacity4, with reversed mode order at the second capacity. One pair each supplies descriptive observations only. Direct mode appends each serialized event synchronously; buffered mode retains serialized lines and writes once at each stage checkpoint. Callback costs include serialization and the selected sink; buffered final join/write is timed separately. Common commit subscription, retained publication snapshots, controller and OS queries remain present in both modes and are not isolated observer overhead. Neither mode calls fsync, and the injected kills occur only after final log flush. This does not prove buffered logs survive arbitrary crash windows.

The frozen ceilings were120s per suite,20s per process,8s per condition,128MiB V8 heap, polled private memory below256MiB, total output below20MiB and at least1GiB free disk. Whole-process peaks are not continuously measured; the V8 heap ceiling is not total process memory. This local SQLite workload has no communication benchmark. Only active admission is bounded; durable request/effect history grows.

Independent review opened only copied SQLite/WAL/SHM sets and rederived task identities, four conversations per arm, terminal outcomes, exact effects,21admission decisions, capacity, recovery and sink log byte counts. Database endpoints retain only sequence36(capacity2) or58(capacity4); the22/40-publication histories come from saved traces, not complete retained database history. All93rawfiles/1,156,630bytes and frozen sources remain unchanged. See [independent review](independent-outcome-review.json), [raw manifest](raw-manifest.json) and [protocol](../../fixtures/pi-durable-load/protocol.json).

The fixed burst gate is closed. Next work returns directly to this caller: separately freeze time-paced arrivals, a bounded retry/backpressure policy and supported pre/post-effect cancellation semantics. Distinct durable Sessions and actual agent-task/provider effects remain separate integration gates. Trusted-host authority and same-transaction local SQLite effects do not prove tenant authentication, external exactly-once, concurrent-writer, GenerationTask, GPU, distributed or production properties. V1/v2 failures and the accepted v3 fixed slice remain unchanged. H1 original5GiB disk gate and prior scientific failures remain; H3/H4 are unchanged.

Before freezing, the Python suite ran1,024methods(943pass/81skip), followed by8final focused controls after prefreeze refinements;2pure Node controls and syntax checks passed. This is distinct from the one native suite.

Audit archived records without Node or a database open:

```bash
python -S scripts/check_pi_durable_load.py
```

The saved-record checker verifies hashes and serialized acceptance. It does not independently reopen SQLite or rerun recovery; the separate copied-database review supplies that evidence. The native controller refuses an existing output directory.
