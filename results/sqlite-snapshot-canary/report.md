# SQLite snapshot correctness canary

**A structurally valid database copy can still omit committed application state.**
In this fixed local WAL fixture, copying only the main database file restored
generation 0. SQLite's online backup restored committed generation 1. Both
passed `integrity_check`. This is a reusable acceptance canary for known SQLite
semantics, not a new backup algorithm or an upstream defect reproduction.

| Restored database | First fresh reader | Second fresh reader | Integrity | Uncommitted generation 2 |
| --- | --- | --- | --- | --- |
| Original database and its WAL | generation 1 | generation 1 | both `ok` | absent |
| Main file copied alone | generation 0, stale | generation 0, stale | both `ok` | absent |
| `Connection.backup` output | generation 1 | generation 1 | both `ok` | absent |

The stale copy is the intended negative control. It omits one committed message,
its receipt and the context-version advance. Its structural check does not
detect this application-level loss. The online backup and source match the
independently declared full rows, not just a producer's success label.

## Reproduce or inspect

Python 3.11+ and its standard-library SQLite are sufficient. No model, account,
network request or GPU is needed. Run from the repository root using a **new**
output directory:

```bash
python -S experiments/sqlite_snapshot_canary.py --protocol fixtures/sqlite-snapshot-canary/protocol.json --freeze fixtures/sqlite-snapshot-canary/implementation.json --output reports/my-snapshot-canary
python -S scripts/audit_sqlite_snapshot_canary.py --result reports/my-snapshot-canary
```

The first command executes the fixture. It refuses an existing output directory
and checks the frozen code, tests and configuration before starting. It does not
retry or tune failed outcomes. The second command verifies saved receipts and
literal outcomes without opening databases or starting processes. To inspect
this committed run, use `--result results/sqlite-snapshot-canary`.

## Fixed execution

The [protocol](../../fixtures/sqlite-snapshot-canary/protocol.json) declares seed
0, no random draws, WAL, `synchronous=FULL`, automatic checkpointing disabled,
literal context/message/receipt rows and explicit process barriers. The writer
commits generation 0 and truncates its WAL at a checkpoint, commits generation 1,
then holds actual generation-2 writes in an uncommitted transaction. While that
writer remains alive, the controller copies only the main file, then a separate
process runs `Connection.backup`. Only after both captures does the writer
terminate with `os._exit(86)`; six fresh reader processes inspect the three
databases twice each.

This sole suite ran on Windows with SQLite 3.53.1 at
2026-10-17 21:10:00.714–21:10:02.293 UTC
(2026-10-18 05:10 Asia/Shanghai). Code/configuration/auditor were frozen at
21:09:54.639 UTC. Eight direct worker processes exited as declared: writer 86,
backup and six readers 0. There were no retries. The recorded 1.579-second wall
time describes this fixture; it is not a comparative performance measurement.
Work has a 60-second budget, 10-second worker waits and bounded cleanup waits.

Fourteen guarded pure tests pass, including stale-but-valid outcomes, partial
rows, missing readers, altered hashes, malformed output and refusal to reuse an
output directory. The saved-receipt auditor passes, and three disposable receipt
mutations are rejected. An [independent review](independent-review.json) separately
recomputed raw rows, hashes, ordering and actor exits. These checks overlap and
do not represent independent experimental repetitions.

The [raw events](events.jsonl), [worker outputs](raw/writer.jsonl), SQLite files,
phase-labelled physical hashes, [original report](report.json),
[audit](audit.json) and [validation record](validation.json) are retained.
The original report's canonical payload SHA256 is
`557721dab016458ebf28f53bffde3dcd8070d925e79572508c6532adcc60e7ca`.

## What this establishes

SQLite documents the [WAL as part of persistent database state](https://www.sqlite.org/wal.html#the_wal_file)
and the [online backup snapshot contract](https://www.sqlite.org/backup.html#file_and_database_connection_locking).
Those are existing mechanisms. Our contribution is an executable, frozen
application-row acceptance check with a retained stale-copy counterexample.
The [documentation receipt](../../research/receipts/20261017T210009Z-sqlite-documentation.json)
separates retrieval time from an unknown original publication date.

`mode=ro` does not imply zero physical side effects: in this writable directory,
readers created zero-byte WAL and 32-KiB SHM files for the copy/backup, and changed
the source SHM hash. Phase inventories record these changes. Database rows and
the source main/WAL bytes remain distinct from those auxiliary-file effects.

The writer is held at barriers, not under sustained concurrent write/checkpoint
stress. Uncommitted writes may remain in SQLite's page cache; their physical
arrival in the WAL is not asserted. Fail-stop exit does not simulate power loss,
torn storage or corruption. The two fresh readers per database are not two
Gateway service restarts. Generic rows do not execute provider calls or external
business effects. Actual packaged-agent authority, cancellation, cleanup,
durable-effect receipts and liveness remain separate unmet H2 gates. H1's cost
and quality failures and the planned H3/H4 experiments are unchanged.
