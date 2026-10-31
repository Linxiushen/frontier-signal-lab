# Pi durable service v1: rejected before workload admission

The one frozen native attempt failed at `Harness.open` on 2026-10-31
10:26:05–10:26:07 UTC. The adapter imported `BACKGROUND_CONTEXT` from Chord's
root module, which does not export that value. It passed `undefined` to the
correct three-argument Harness API. This is our adapter error, not evidence of
a Pi scheduler or persistence defect.

One Node process exited 1 after 1.547 seconds. **Zero conversations, admission
attempts, tasks, effects, forced kills or restarts occurred.** All planned
capacity, authority, cancellation and two-restart checks remain unexecuted.
There was no retry; this consumes the round's one H2 experiment allowance.

The exact runtime was `@earendil-works/pi-durable@1.4.0` on Node 24.19.0 Windows
x64. The pre-execution freeze covers five sources and 12,765 installed runtime
files, 79,754,718 bytes. The [protocol](../../fixtures/pi-durable-service-v1/protocol.json),
[freeze](../../fixtures/pi-durable-service-v1/implementation.json), lockfile,
full dependency byte manifest and original SQLite/WAL/SHM bytes are retained.
An independent auditor copied the database and checked only that copy:
integrity `ok`, with zero conversations/tasks/submissions/documents/revisions;
the six original raw-file hashes stayed unchanged. This preserves the failure
and does not accept execution.

Two pure admission/fingerprint tests passed before execution. The canonical
Python suite passed 927 methods with 81 skips; an earlier `-S` invocation hid
NumPy and produced 11 import errors, retained in the ignored run. Static review
and those tests missed the actual module export boundary. The failed startup
yielded 83,951,616 B maximum sampled private usage and 91,418,624 B maximum
observed OS peak working set. These are one failed process's resource readings,
not service capacity, latency, observer overhead or performance results.

The intended service slice uses two logical conversations in one durable
Session/database, a two-active-task admission limit, trusted-host versioned
authority, and local document effects committed with native task checkpoints.
It does not establish independent tenants, external exactly-once effects,
GenerationTask/model/provider behavior or production reliability. Request
history is not bounded by the active-task limit.

The next version must explicitly resolve Chord's `context` entrypoint, validate
that real export boundary, and separately freeze the same complete workload
before a later sole attempt. Frozen v1 sources remain unchanged. H1's original
5 GiB disk gate, prior failures and closed observer prerequisites remain.

Run the portable saved-record check without opening a database or starting Node:

```bash
python -S scripts/check_pi_durable_service_v1_failure.py
```

This check does not install or execute the Pi runtime. Full native reproduction
requires the archived lockfile and a new, separately preregistered output/freeze;
the failed output directory must never be reused.
