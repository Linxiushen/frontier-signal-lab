# Pi durable service v2: native workload ran, frozen acceptance failed

The sole frozen suite ran on 2026-10-31 12:09:34–12:09:39 UTC. It reached all
three worker stages, including two controller-injected process terminations and
two reopens of the same native Pi database. **Frozen acceptance failed** in our
final SQLite query. Pi stores `documents.kind` as a JSON-encoded string; our
literal `kind='frontier.service'` matched no document. Indexing the missing row
raised `TypeError`. This is our acceptance-query error, not a Pi recovery bug.

The failure remains unchanged. There was no retry and no repair to the seven
frozen v2 sources or the five frozen v1 sources. Later controller checks were
not reached; a post-outcome inspection cannot turn that into frozen acceptance.

The actual caller is the optional adapter over official
`@earendil-works/pi-durable@1.4.0` Harness/Session/native scheduler and Node
SQLite, on Node 24.19.0 Windows x64. Two logical client conversations share one
Session/database and two active admission slots. The workload targets live-work
admission, current host-authority checks and local transactional effects plus
task checkpoints. The context-entrypoint error from v1 was corrected in separate
files, with a real installed export positive check and wrong-root negative check
before storage/Harness/task execution. Neither check ran the service workload.

| Saved observation | Result |
| --- | --- |
| Worker PIDs / exits | 11456 / 1, 43292 / 1, 41688 / 0; first two killed, final worker closed normally |
| Worker-stage wall time | 1.671 s, 1.688 s, 1.719 s; includes module startup and injected gates |
| Admission calls | 12: six admitted, three duplicate identities, one overload, one obsolete-authority refusal, one payload conflict |
| Native task records, inspected after outcome | Six terminal: four completed/committed, one completed/denied, one aborted |
| Local effects, inspected after outcome | Four exact payloads, each count 1; denied/cancelled effects absent; zero active requests |
| Document publications in saved trace | 20, strictly increasing sequence values; last sequence 31 matches the retained endpoint in the independent copy |
| Maximum sampled private usage by stage | 83,857,408 / 85,684,224 / 84,291,584 B |
| Maximum observed OS peak working set by stage | 91,865,088 / 91,955,200 / 92,041,216 B |

An independent auditor copied SQLite/WAL/SHM and opened only that copy. Integrity
was `ok`; native task IDs/outcomes, the encoded-kind document endpoint, admission
denominators, capacity and saved publications were consistent. All 21 original
raw files, 219,250 bytes, retained their hashes. These are explicitly
**post-outcome preservation observations**, not retroactive acceptance.
Session checkpoints compact prior document revisions; the retained database is
not an independent complete historical publication trace.

The pre-execution freeze pins seven sources, Node and the same 12,765-file
runtime manifest used by v1. Two pure Node tests, the real export check and the
canonical Python suite (930 pass / 81 skip, 1,011 methods) passed before the
native attempt. They and static review missed the SQLite kind serialization
boundary. The [protocol](../../fixtures/pi-durable-service-v2/protocol.json),
[freeze](../../fixtures/pi-durable-service-v2/implementation.json), raw SQLite
bytes, process/trace receipts and independent preservation review are retained.

This is one Windows host, trusted-host authority and same-transaction local
SQLite effects. It does not establish independent tenants, external-provider
exactly-once effects, GenerationTask/model/provider behavior, concurrent writers,
distributed execution or production reliability. Only active admissions are
bounded; request/effect history grows. Resource readings cover startup plus the
gated workload and do not establish continuous private peaks, isolated memory,
causal observation overhead, throughput gains or tail-latency guarantees.

The separately named v3 controller now handles the native encoded-kind endpoint
and rejects old freezes. Six native-schema/old-freeze regressions and a lookup
on a separate saved-database copy pass after the outcome. This preparation runs
no native suite and is complete. The next attempt must separately freeze it on
a later round, keeping the same v2 producer/worker workload and resource limits.
H1's original 5 GiB disk gate and all earlier scientific failures remain.

Check the saved record without Node or a database open:

```bash
python -S scripts/check_pi_durable_service_v2_failure.py
```

That command preserves the rejected result; it does not execute the runtime.
