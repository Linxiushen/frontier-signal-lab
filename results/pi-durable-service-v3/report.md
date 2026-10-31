# Pi durable service v3: accepted native two-restart slice

One separately frozen suite passed on 2026-10-31, 14:04:13–14:04:18 UTC.
The unchanged v2 adapter and worker ran over official
`@earendil-works/pi-durable@1.4.0` / Chord 1.4.0, Node 24.19.0 and native
Node SQLite on one Windows host. Two logical client conversations share one
durable Session/database and a two-slot admission budget. This accepts the
fixed custom-task integration slice; full agent/provider and production
behavior remain unverified.

The v3 controller fixes our JSON-encoded `documents.kind` lookup and requires
its own exact source hash in a new freeze. All eight frozen source hashes and
the runtime's 12,765-file manifest were checked before execution. The prior
v1 export failure and v2 final-query failure remain failures, with their
twelve source files and raw records unchanged. Neither was retried.

| Frozen workload and observation | Result |
| --- | --- |
| Processes | PIDs 45032, 9344, 20160; exits 1, 1, 0. The controller killed the first two at held post-effect checkpoints; the final worker closed normally |
| Recovery | Two actual process restarts reopen the same SQLite database. Recovered tasks resume at `finish`; progress and a final new task complete after the respective restart boundaries |
| Admission decisions | 12: six admitted, three duplicate identities, one overload refusal, one stale-authority refusal, one payload conflict |
| Native tasks | Six terminal: four completed/committed, one completed/denied after current authority was revoked, one aborted before its effect |
| Local effects | Four intended payloads, each count 1; denied/cancelled effects absent; zero active admissions at completion |
| Capacity and persistence | Maximum active 2; 20 observed committed-document publications have strictly increasing sequences. Last sequence 31 and value match the retained database endpoint |
| Independent database-copy audit | Integrity `ok`; two conversations, exact task IDs/outcomes, four payloads and final document agree. Original 21 files / 223,614 bytes retain their hashes |

This exercises real Harness/Session/TaskRuntime/registry/SQLite code, with
custom tasks and an optional host adapter. Current trusted-host authority is
checked inside the same transaction as the local effect. Admission deduplication
retains durable task identities; a changed payload conflicts. Aborting a held
pre-effect task frees capacity, allowing subsequent work. SQLite's session
checkpoints compact old revisions: the database retains revision 31, while
the saved trace supplies the 20-publication history. It is not an independent
complete database history.

The predeclared limits were 90 s per suite, 25 s per process, 8 s per condition,
128 MiB V8 heap, sampled process private memory below 1 GiB, output below
10 MiB and at least 1 GiB free disk. The three startup-inclusive stage times
were 1.594, 1.594 and 1.578 s. Maximum sampled private bytes were 85,278,720 /
83,705,856 / 84,905,984; maximum observed OS working-set high-water readings
were 92,479,488 / 91,877,376 / 93,331,456 B. Polling can miss peaks; the V8 heap
limit is not a whole-process memory bound.

Native execution took 4.802242 s including startup and injected gates, giving
four committed local effects / 4.802242 s = 0.833 effects/s descriptively.
The 12 admission-call timings have nearest-rank p50 0.9273 ms and p95/p99
1.5936 ms, both equal to the maximum at this sample size. These are not service
tail guarantees or a throughput improvement: there is no matched baseline,
arrival-load study, isolated observer-cost measurement or communication
benchmark. The invocation also spent about 10 s verifying runtime bytes before
the native suite timer began.

Before freezing, the canonical Python suite passed 936 methods with 81 skips
(1,017 total), the two pure Node admission controls passed, and the installed
positive/wrong-root export checks passed without storage, Harness or tasks.
An independent reviewer then opened only a copied SQLite/WAL/SHM set and checked
the saved source, process, admission, task and trace evidence. It ran no new
native suite. See the [protocol](../../fixtures/pi-durable-service-v3/protocol.json),
[freeze](../../fixtures/pi-durable-service-v3/implementation.json),
[independent review](independent-outcome-review.json) and [raw manifest](raw-manifest.json).

The integration gate for this fixed slice is closed. The next experiment must
separately preregister a bounded arrival load and supported effect/cancellation
boundary on this same adapter, with matched success, useful throughput,
end-to-end tails, resources and observation costs. There is no external-provider
exactly-once guarantee, independent tenant authentication, concurrent-writer
authority, GenerationTask/model, GPU, distributed or production validation.
Only active admission is bounded; request/effect history grows. H1's original
5 GiB disk gate and scientific failures remain; H3/H4 remain planned.

Audit the archived result without Node or a database open:

```bash
python -S scripts/check_pi_durable_service_v3.py
```

This command checks saved evidence and does not execute recovery again. The
native controller refuses an existing output directory; the saved freeze is
the record of the single original attempt.
