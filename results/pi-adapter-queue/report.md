# Pinned pi adapter queue probe

Runs the actual unmodified adapter primitive over a local node:sqlite stand-in. The unused factory import is replaced by an explicit fail-closed sentinel.

| Scenario | Promise/guard checks | Exact SQL rows | Passed |
|---|---|---|---|
| queued_write_commit | true | true | true |
| queued_write_abort | true | true | true |
| direct_write_abort_control | true | true | true |
| transaction_after_abort | true | true | true |
| retained_handle_after_commit | true | true | true |
| retained_handle_after_abort | true | true | true |

The direct-write negative control deliberately bypasses the adapter queue: its returned write is rolled back by the enclosing aborted transaction. It is evidence of the boundary, not a claimed adapter failure.

Unused SqliteStorage factory open attempts: **0**.

Pinned source SHA256: `428b68034173066227c8d2beff111e3a9852afd9b4215e30bc4ff6c315f47b20`.

Result SHA256 (canonical JSON excluding result_sha256): `7b5df023acea9c596764f779776a411c5382f8300a3071a36d6f2df675fd9d7d`.

## Scope

- Executes the unmodified pinned DurableObjectSqliteDatabase class, with the unused higher-level storage factory dependency substituted. This is not the full pi/Pico storage contract.
- Local synchronous SQLite SQL and BEGIN/COMMIT/ROLLBACK approximate the structural storage interface; Cloudflare runtime scheduling, isolation and durability are not reproduced.
- No power loss, process crash, namespace migration, network service, real external effect or production exactly-once guarantee is tested.
- Adapter instances share a queue only when given the same storage object. Direct storage calls bypass it; the negative control demonstrates a completed direct write rolling back with the enclosing transaction.
- Promise settlement and exact final SQL rows measure bounded local progress. Six deterministic traces do not establish general liveness or production reliability.
- The upstream test suite already contains related queue and direct-write cases; this independent integration probe does not claim to invent them.
- No network API is called by the probe or reviewed adapter. This is a source/import restriction, not an operating-system network sandbox.

Upstream source: https://github.com/earendil-works/pi/blob/f7e3cb5433ba9500d4381d201e628bb5301c9924/packages/durable/src/storage/sqlite/cloudflare.ts
