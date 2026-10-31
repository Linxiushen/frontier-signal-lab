# Native paced load across two durable Sessions

One separately preregistered suite passed on 2026-10-31, 18:12:53–18:13:06 UTC, using the unchanged accepted Pi/Chord1.4.0 adapter and Node24.19.0 on one Windows host. Each arm opens two independent native Harness instances (Session subclasses), each with its own SQLite database and two conversations. These are custom native tasks with trusted-host authority and same-database transactional local effects; no model or provider runs.

The fixed order is immediate refusal, then bounded retry. In each of three stages, 12 load identities alternate Sessions at scheduled 0,10,...110ms. Two held control tasks initially fill each Session's two slots, and control release starts at120ms. The schedule never waits for task completion, but serialized native admission and observation can delay actual offering. Actual lateness is retained, so this is a finite paced workload, not a stationary open-loop rate sweep. The deliberate busy interval precedes all scheduled arrivals and determines the refusal baseline.

The optional single-owner queue requires serially awaited offer/tick calls: at most four pending identities, eight admission attempts including initial, and at least20ms between retry starts. Retry age is checked before an admission starts and must be below200ms; it is not an async completion/cancellation deadline. Overflow is promptly refused as backpressured. Pending entries drain before each injected crash; queue crash durability is not tested. Histories, finished records and durable request/effect logs grow.

| Arm | Load effects / offered | Refused / backpressured / exhausted | Load admission attempts | Max pending / attempts | Arm wall s | Load effects / arm s | Load terminal p95 ms | Sampled private B | Callback / flush ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| refuse | 0/36 | 36 / 0 / 0 | 36 | 0 / 1 | 5.313 | 0.000 | null (n=0) | 85454848 | 2.669 / 3.338 |
| retry | 12/36 | 0 / 24 / 0 | 92 | 4 / 7 | 6.719 | 1.786 | 256 | 85118976 | 3.428 / 3.279 |

Both arms separately admit all14 control identities: four held post-effect survivors across two crashes, two authority-denied tasks, two pre-effect aborts, two post-effect aborts and four ordinary commits. Denied and pre-effect-aborted tasks have no effect; each post-effect abort retains its already committed payload once. All admitted native tasks reach their expected terminal outcome; recovered pending tasks resume their exact finish checkpoint, and all local effects have exact payload/count1. Each Session reaches active2 and ends at0. Six distinct worker PIDs, four controller kills and four process reopen cycles are recorded; each reopened worker opens both databases. No pending caller queue survives a crash in this workload.

Refusal accounts for all36 load identities and has no load latency sample. Retry admits12/36 and backpressures24/36; all12 admitted loads commit. Its92 native admission attempts cost56 more calls than refusal. No native exhaustion occurs in this run; pure unit controls cover attempt and age exhaustion, including native overload result identity. This single fixed-order pair, deliberately held capacity and unequal accepted cohorts do not establish causal speedup, general acceptance gain, service capacity or production tails.

Arm wall includes startup, synthetic gates, two reopens, endpoint database reads and controller acceptance. It excludes runtime-file verification before the suite timer. Retry load arrival-to-observed-terminal p50/p95/p99 are193/256/256ms (n=12). Polling, epoch-clock resolution, delayed observations and only12 samples limit these descriptive tails; control-recovery observations additionally include held checkpoints and restart time. Complete all-admitted latency, native admission timing, offered lateness, queried OS working-set high-water, database/raw bytes and callback/flush costs are in report.json.

Common commit subscriptions, serialized history, observation and controller/OS polling remain in both arms. Callback timing measures event serialization and buffer insertion; final join/write is measured separately. These are component observation costs, not isolated total observer overhead. Logs are flushed before the injected kills and no fsync is requested, so arbitrary-crash log durability is untested. There is no network communication benchmark or model-quality endpoint.

The original ceilings are120s suite/20s process/8s condition,128MiB V8 heap, polled private memory below256MiB, complete output below20MiB, at least1GiB free disk and20ms controller polls. Sampled private is not a continuous peak; queried OS working-set high-water differs from private memory, and V8 heap is not total process memory. All53 raw files/1,277,022bytes are retained with exact hashes. Independent review opened only complete copied SQLite/WAL/SHM sets, rederived identities/tasks/effects/authority/recovery and acceptance metrics, verified12,765 runtime files and all frozen source pins, then rehashed unchanged original raw bytes.

Before freezing, the final Python suite ran1,034 methods (953passed/81skipped), with9 focused Python and8 pure Node controls plus syntax validation. Independent static reviewers caught and resolved result-provenance and control-admission gaps before any native execution. Those tests are distinct from this one native suite; no native retry occurred.

The finite paced/two-native-Session/bounded-pending custom-task gate is CLOSED. Return directly to the same runtime actual GenerationTask/tool/provider boundary under a separate complete preregistration, including two distinct Sessions, bounded load, current authority, cancellation and two process reopens. Use no-cost local provider/transport fixtures if required and label them as fixtures, not model quality; external effect custody/idempotency and full-agent/model/tenant/concurrent-writer/production claims remain unverified. No observer-only prerequisite expansion.

V1/v2 failed freezes and earlier accepted slices remain unchanged. H1 retains the original5GiB free-disk gate and previous negative results; H3/H4 remain unchanged. The actual GenerationTask/provider, external effects, tenant authentication, concurrent writers, GPU/multihost and production properties are not validated by this result.

[Frozen protocol](../../fixtures/pi-durable-paced/protocol.json) · [Independent outcome review](independent-outcome-review.json) · [Raw manifest](raw-manifest.json)

Verify the saved evidence without starting Node or opening SQLite:

```bash
python -S scripts/check_pi_durable_paced.py
```

This checker verifies saved bytes and serialized acceptance. The separate copied-database audit provides database evidence; CI does not rerun the native workload. The native controller refuses an existing outcome directory. The archived `independent-outcome-review.py` is an exact source snapshot of that one-off review with its original ignored-run layout; use the checker above as the portable public entrypoint.
