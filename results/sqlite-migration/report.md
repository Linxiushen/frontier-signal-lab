# SQLite migration recovery probe

Independent generic schema with real SQLite transactions and subprocess fail-stop exits. No upstream implementation is reproduced.

Both policies preserve the raw legacy rows. False-clean diagnostics and unresolved obligations are measured separately from data loss.

| Policy | Crash point | Atomic | Replay idempotent | Raw preserved | False clean | Accepted total | Still accepted | Runnable | Blocked | Done |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|
| silent_skip | none | True | True | True | True | 6 | 3 | 1 | 2 | 0 |
| silent_skip | after_row_write | True | True | True | True | 6 | 3 | 1 | 2 | 0 |
| silent_skip | after_diagnostic_step | True | True | True | True | 6 | 3 | 1 | 2 | 0 |
| silent_skip | before_commit | True | True | True | True | 6 | 3 | 1 | 2 | 0 |
| silent_skip | after_commit | True | True | True | True | 6 | 3 | 1 | 2 | 0 |
| warn_preserve | none | True | True | True | False | 6 | 0 | 1 | 5 | 0 |
| warn_preserve | after_row_write | True | True | True | False | 6 | 0 | 1 | 5 | 0 |
| warn_preserve | after_diagnostic_step | True | True | True | False | 6 | 0 | 1 | 5 | 0 |
| warn_preserve | before_commit | True | True | True | False | 6 | 0 | 1 | 5 | 0 |
| warn_preserve | after_commit | True | True | True | False | 6 | 0 | 1 | 5 | 0 |

`Accepted total` is the fixed admission obligation count; `Still accepted` means no runnable/blocked/done classification. Blocking is not success. None of these tasks executes a business result.

Each trace includes actual reopened rows, logical SQL dumps, transaction/replay checks and snapshot hashes. Counterexamples include false-clean diagnostics as negative results.

Result SHA256 (canonical JSON excluding result_sha256): `4a1c4724212a1ae7a3c2f53e40a7707eb40e4623aeef3ae629f8f3c6cb51e639`

## Limits

- Generic fixture and schema, not an OpenClaw reproduction, migration compatibility test, or confirmed deployed defect.
- A subsequent upstream revision added malformed-binding warnings; this historical silent/warn comparison does not assert that the current upstream proposal remains silent.
- Both policies retain every original value_json row; silent_skip can report clean despite undecodable rows. It does not delete assignments.
- warn_preserve makes unresolved obligations explicit; retaining or blocking a task is not business completion or automatic data repair.
- No task executes a business result, so done_obligations must remain zero. Runnable is eligibility, not evidence of eventual completion.
- Unknown requester evidence never authorizes newly retiring an active binding. Existing retired state is preserved; only explicit terminal evidence with confirmed requester creates a retirement in this fixture.
- Malformed-row ground truth is the fixed fixture specification, independent of decode(). Original-row hashes cover SQLite TEXT values re-encoded as UTF-8, not original database-file bytes.
- Replay idempotence means logical rows remain equal, not zero writes; INSERT OR REPLACE may rewrite physical storage. Re-migration preserves independently completed obligations.
- Hard process exits exercise local SQLite transaction rollback and restart; they do not simulate power loss, disk corruption, network partitions, concurrent writers, or torn storage writes.
- No external side effect or exactly-once delivery is tested. No compaction or stale-turn scheduler is implemented.
- The finite selected checkpoints and fixtures establish neither production reliability nor general liveness. SQL snapshots are logical database dumps, not physical disk forensic images.

Public inspiration: https://github.com/openclaw/openclaw/pull/173018#discussion_r4282004743
