# Receipt preservation through overlapping native recovery

One separately preregistered H2 suite passed once, with zero retries and zero real-model loads. The actual caller is the published opt-in `openReceiptGenerationService`, public `reconcile()` on a reopened paused Harness, native GenerationTask/ToolTask checkpoints, two isolated SQLite Sessions, official deterministic local Faux, and an independent scoped loopback HTTP/SQLite store.

Two concurrent public recovery calls per Session deliver obsolete real HTTP observations after another call acknowledges the effect. Service0 holds an actual second GET404, permits first POST201 and receipt persistence, revokes current host authority, then delivers the missing response. Service1 obtains an actual POST403 while authority is false **before** any create, holds its callback, restores authority for first POST201 acknowledgement, revokes again, then delivers the old refusal. The server intentionally returns an existing receipt before checking current authority; no403 was invented after an effect already existed. Both callbacks return existing through the receipt-monotonic dispatcher, emit superseded, and preserve the original committed receipts without `effectDenied`.

After these paired recoveries finish while paused, the caller durably cancels the two already committed first-conversation requests and is killed again. On the second reopen, the unchanged native recovery helper marks those exact generation/tool pairs before scheduling. Their native submissions become unanswered/aborted while both historical effect receipts remain intact. The two original positive chains replay their tool checkpoints on the same task IDs and finish existing. Neither recovery starts another provider generation. The second-reopen acknowledgement/replay issues no HTTP effect operation.

| Frozen workload/outcome | Observed |
|---|---:|
| Unique arrivals / admissions / overloads | 12 / 8 / 4 |
| Exact host retries / changed-content conflicts | 2 / 2 |
| Generation tasks / tool tasks / Faux calls | 8 / 8 / 8 |
| Native processes / forced kills and reopens | 3 / 2 |
| Independent effect-server processes / graceful reopens | 3 / 2 |
| Superseded late callbacks / concurrent reconcile pairs | 2 / 2 |
| Eligible fixture effects / count1 rows | 6 / 6 |
| GET404 / POST201 / POST403 attempts | 10 / 6 / 1 |
| Native aborted / completed tasks | 4 / 12 |
| Host terminals / final active reservations | 8 / 0 |

Fresh stage2 negative controls confirm that ordinary refusal remains effective: current host denial returns denied, and a held durable cancellation marker returns aborted; each performs a real GET404 and creates no POST/effect. Both live tool/generation pairs complete and their submissions are done. This differs from aborting a recovered native pair, whose tasks end aborted and submission unanswered. Two fresh positive controls succeed. Capacity is2 per Session; rejected arrivals never persist or submit. Session-scoped numeric IDs/keys deliberately repeat with different payloads and do not collide in the independent effect store.

The immutable stopped-copy audit independently joins exact submission/user/assistant/generation/tool identities, verifies receipt/state/authority ordering, rereads nine copied native/effect endpoints, and matches server request logs to SQL attempts. All97 original raw files / 1,907,083bytes are copied exactly and hash-bound in [raw-manifest.json](raw-manifest.json). All167 old frozen sources and3782 prior tracked fixture/result files remain unchanged. The earlier concurrent freeze remains failed; this result does not rescue it.

Suite time is 7.813s, source/runtime authentication 32.328s, full controller 40.141s, and complete CLI 40.609s. Descriptive useful throughput is 0.768fixture effects/s over suite time. Host offer-to-observed-terminal p50/p95/max is116/5218/5218ms, including deliberate holds and restarts. Across all16 admission calls, p50/p95/max is1.5974/15.6412/15.6412ms. These costs have no comparison baseline and establish no performance improvement or service SLO.

Native/server sampled private maxima are108,773,376/15,327,232bytes. Separate working-set/OS peak-working-set samples and sampling gaps remain in [report.json](report.json); they are not continuous peaks or simultaneous totals.35 settled HTTP client results comprise17 effect calls and18 authority/snapshot controls, with1977 request-body and7682 response-body bytes, excluding wire/header traffic.226 buffered events total162,944bytes; callback/flush totals are2.0369/3.6931ms. No observer-OFF comparison estimates causal overhead.

Use the opt-in factory with the same explicit scoped effect client and native options; selecting the original `openGenerationService` is the rollback. The new reusable barrier module schedules delivery around actual transport calls and never supplies receipts. Preparation passed3 Node barrier tests,7 offline malformed-evidence tests and worker syntax checks. After archival, the saved-byte checker passed and the portable suite ran1196 tests successfully with81 skipped. These checks do not execute another native suite. The frozen source/review/runtime identities are in [the implementation freeze](../../fixtures/pi-receipt-recovery/implementation.json). The portable checker reads only saved data:

```sh
python -S scripts/check_pi_receipt_recovery.py
```

This finite same-owner boundary is CLOSED. Controlled callbacks and official Faux do not establish real-model quality, tenant authentication, concurrent native owners, arbitrary interleavings, remote linearizability, general exactly-once, GPU/distributed/production behavior or performance. Histories grow despite bounded active reservations; authority checks and external mutation are not atomic. H1/H3/H4, the original H1 resource gate/invalid RSS and all previous failed/negative evidence remain unchanged. Further work needs a new actual caller/defect and separate complete preregistration, with no unchanged rerun or observer detour.
