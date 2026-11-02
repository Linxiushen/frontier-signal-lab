# Scoped-v2 native generation: finite integration accepted

The separately preregistered `pi-scoped-generation-native-v1` suite passed its frozen auditor on 2026-11-02 UTC. An independent reviewer reread the original saved evidence and all nine immutable copied SQLite endpoints, reproduced the acceptance dictionary and verified that all 94 original files remained unchanged. The archive contains exactly **94 files / 2,082,999 bytes**. One H2 native suite ran, with zero retries and zero real model loads.

The actual caller is the opt-in `openScopedGenerationService` wrapper around the unchanged installed native Harness, GenerationTask and ToolTask, using official deterministic local Faux and real loopback HTTP. Two isolated SQLite Sessions deliberately reuse numeric conversation IDs and every request ID/key while carrying different payloads. Scope binds both the HTTP resource and `(scope,key)` SQL primary key. This integrates the published scoped adapter into the native recovery chain; it does not migrate a legacy database.

| Frozen workload or outcome | Observed |
| --- | ---: |
| Unique arrivals / admitted / overloaded | 18 / 12 / 6 |
| Exact host retries / changed-content conflicts | 4 / 4 |
| Native generation / unique tool tasks / tool execute entries | 12 / 12 / 14 |
| Provider tool-call factories / host terminals / native terminal tasks | 12 / 12 / 24 |
| Native processes / forced kills and reopens | 3 / 2 |
| Independent HTTP server processes / graceful reopens | 3 / 2 |
| Recovered reservations / final active | 5 / 0 |
| Expected eligible effects / actual effects | 9 / 9 |
| Actual effects / admitted requests | 9 / 12 |
| Effect GET / POST SQL attempts | 13 / 14 |
| POST created / denied / duplicate / conflict | 9 / 1 / 2 / 2 |

The asymmetric controls are substantive. Remote revocation denies service0's original revoke request, pre-effect cancellation aborts service1's cancel request, and host revocation denies service0's live request. Their other-scope counterparts retain the same keys and succeed. The fourth control commits service0's post request remotely while withholding its reply, durably marks cancellation and revokes remote authority, then kills the native process. Recovery reads the historical receipt by GET while permission remains false, before version3 authorization; no second mutation POST is needed for recovery. Later deliberate exact/changed effect controls return 200/409. All three negative identities lack effect rows. The post-commit cancelled identity retains its one historical effect.

| Descriptive time or observation | Value |
| --- | ---: |
| Suite, excluding authentication | 7.563 s |
| Source/runtime authentication | 31.062 s |
| Full controller, including authentication | 38.625 s |
| Complete CLI, including startup/imports/exit | 39.062 s |
| Host offer-to-observed-terminal p50 / p95 / maximum | 151 / 2434 / 2434 ms |
| Maximum admission call latency, 26 calls | 18.506 ms |
| Fixture useful effects per suite second | 1.190 |
| Maximum sampled native private bytes | 109,461,504 B |
| Maximum sampled independent-server private bytes | 15,421,440 B |
| Observer callback / flush totals | 2.3548 / 2.5800 ms |
| Encoded request / observed response body bytes, settled operations | 3,273 / 14,697 B |

These times include fixed transport/reply holds, restart boundaries, explicit reconciliation/reaping, copies and audit. The CLI excludes preparation, tests, reviews and publication. The throughput is a descriptive fixture calculation, not a production rate or speedup. The 9/9 eligible disposition outcome is not model-quality evidence. Memory figures are lower-bound sampled maxima; per-process first/interior/end observation gaps and distinct OS peak-working-set counters are retained in `report.json`. Controller and simultaneous total memory are unmeasured. Callback/flush totals have no observer-OFF comparison.

There are 27 persisted effect HTTP attempts but only 26 settled client effect-result events: the killed held-reply POST need not emit a client result. Across control and effect traffic there are 52 settled HTTP-result events. Body counts cover encoded request payloads and observed response chunks only for those events; headers, socket/wire traffic and unobserved killed operations are unmeasured.

The original failed concurrent native suite remains failed with `KeyError('service')`, `execution_accepted=false` and no acceptance rescue. Its 95 raw files and manifest were verified, and its report matches the preexisting HEAD bytes. This is a different scoped workload with a separate protocol, eight-source freeze and pre-execution reviews. The frozen source/runtime and old scientific evidence were preserved; H1/H3/H4 are unchanged.

Validation is limited to one trusted Windows owner, two native Sessions, finite capacity 2 reservations per Session, deterministic Faux and local loopback HTTP/SQLite. It does not establish tenant authentication, concurrent native ownership, arbitrary interleavings, atomic permission-and-network commit, general external exactly-once, real model quality, GPU/distributed operation or production SLOs. Historical ledgers grow even though active admission is bounded.

Evidence: [`report.json`](report.json), [`raw-manifest.json`](raw-manifest.json), [`original saved-byte review`](execution-receipts/radar-postoutcome-review.json), [`control/metric review`](execution-receipts/radar-controls-metrics-review.json), [`launch receipt`](execution-receipts/launch-receipt.json). Freeze SHA256: `cf0c485bd5d7e915324028fd1d52aff716961408d3a0452ea8208058b34811ac`. Raw manifest SHA256: `10fdac5c74e998abc3aa6756ca3df9f8aac01de95196ac1b1d04aea5f2168ee5`.
