# Pinned pi SQLite adapter

`cloudflare.ts` is an unmodified file from earendil-works/pi at commit
`f7e3cb5433ba9500d4381d201e628bb5301c9924`, the merge of PR #10937.
It remains under its upstream MIT license, included in `LICENSE`.
`provenance.json` records source URLs, exact bytes, hashes and fetch times.

The independent probe executes `DurableObjectSqliteDatabase` over a local
`node:sqlite` stand-in. A Node module hook replaces its unused `SqliteStorage`
factory dependency with a sentinel that throws on use. The source file itself
is not patched. The probe records this substitution and checks that the factory
was not called.

This isolates the actual adapter queue and transaction primitives. It does not
execute the higher-level Pico storage contract, namespace migrations, the full
pi harness or Cloudflare's production runtime. The upstream test suite already
contains related queued-write and direct-write rollback cases; this work does
not claim to invent those contracts.
