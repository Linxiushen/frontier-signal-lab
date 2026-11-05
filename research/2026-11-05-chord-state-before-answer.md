# Pi Chord: state visibility before a remote answer

Pi commit [d7a988d](https://github.com/earendil-works/pi/commit/d7a988d18d2a27f78f1cdcc0597154e916d95ed9), authored by `badlogic` and committed on 2026-11-05 at 10:45:40Z, changes a real remote-call path: a provider or relay sends its origin's waiting state before a tracked call's result or error. This review pins parent `af79b0c3d75c099d37365dcbc033414b5c384835`. The source package is `@earendil-works/chord` 1.5.0, MIT; the commit is not evidence of an npm release or adoption by our installed 1.4.0 runtime.

The previous radar captured only the message excerpt. This review authenticates all 13 changed paths before/after where present, direct remote helpers, the ordered channel and pinned policy/package files. It reads source and author test design; it executes no upstream code, tests, native runtime, model or scientific experiment. Full source identities and HTTP receipts are bound by the accompanying review receipt.

## Concrete caller and failure

The new runnable example models a session-title rename: terminal client → server relay → session worker. The worker awaits its local document change and its report to the server's session index, then answers. The client holds that index and temporarily displays an optimistic title.

Previously, two unacknowledged state/binding messages could fill the provider's window. The rename's index update then waited for credit, while the result could pass it. Dropping the optimistic value on result delivery could briefly expose the old index value. This is a source-level explanation of the old path and the author's finite example, not our reproduction of a running application.

In [`ProviderSide.reply`](https://github.com/earendil-works/pi/blob/d7a988d18d2a27f78f1cdcc0597154e916d95ed9/packages/chord/src/remote/provider.ts), a still-tracked call is removed, waiting state is sent if present, then the answer is sent. `#sendWaiting` batches every waiting hold for that origin into one state message, rather than only the called hold. The same reply path handles valid forwarded answers, so a relay sends its own waiting state before forwarding a worker's answer. Empty waiting state produces no extra message. Waiting bindings retain their ordinary credit path.

## Ordering is implemented across both ends

[`Channel`](https://github.com/earendil-works/pi/blob/d7a988d18d2a27f78f1cdcc0597154e916d95ed9/packages/chord/src/link/channel.ts) holds later received messages while a handler's asynchronous operation finishes and releases them in order. `HostLink.inflate` uses that path for asynchronous decompression. [`ConsumerSide`](https://github.com/earendil-works/pi/blob/d7a988d18d2a27f78f1cdcc0597154e916d95ed9/packages/chord/src/remote/consumer.ts) prepares state entries, applies them in a host batch, then sends their acknowledgement; result/error handling separately settles the outgoing call. This supports the source's intended state-before-answer ordering, including the asynchronous-inflate path. Invalid or oversized parts have their own refusal/hold-failure behavior; successful application is not guaranteed for arbitrary malformed input.

The new `TuiScope.optimistic` keeps the latest shown value until all calls registered through that helper settle. Resolution and rejection both decrement the pending count; it returns the original promise, leaving errors to its caller. Disposal suppresses redraw callbacks. This is a shared pending-value helper, not per-operation rollback or a model of conflict resolution. React documentation uses React's existing optimistic/transition APIs.

## Backpressure and persistence are separate boundaries

Ordinary own-state credit remains K=2. The exceptional state still increments in-flight/own-sent counters and joins the sender FIFO, so acknowledgements count it before normal credit opens again. The design argues at most one extra state per answer, with extra messages and running calls bounded together by N under its ordered acknowledgement/replacement-call argument; `HostLink` announces N=256. We have not independently stress-tested that argument, cancellation interleavings or arbitrary peers.

This is a count mechanism, not a process-memory ceiling. One exceptional message can carry multiple waiting holds and their payloads. Multiple upstream workers/origins have separate windows. `CallWindow` keeps excess local submissions in a set, and `Channel` retains later received byte arrays during asynchronous handling; this change adds no aggregate bound to those queues. It supplies no new caller admission limit, byte window or causal latency/throughput result.

An acknowledgement here follows replica application; it is not a durable checkpoint or fsync receipt. The documented guarantee excludes effects committed after answering and changes on hosts that neither answer nor relay the answer. A binding waiting through reload can still show its prior value until its new snapshot arrives. No current-authority, idempotent-effect, cancellation, two-process-restart, external exactly-once or scoring-version gate follows from this ordering rule.

## Evidence and next integration boundary

The author adds four provider test cases for a full window/all waiting holds, FIFO credit accounting, empty waiting state and ordinary-path state-message count; one relay case for local state plus forwarded answers; and three optimistic-helper cases for completion, overlap/rejection and disposal. Existing slow-peer tests move mutations to server-local calls because remote answers now flush waiting state. Example 63 uses in-memory hosts/links and a stalled client. These are reviewed definitions, not passing local tests or production observations. No performance benchmark accompanies the inspected change.

Our inference is a narrower engineering criterion: a completion event in an agent application must name which state is already visible, separately from persistence, authority and effect completion. The native integration point is an actual Chord client/relay/worker application that reads server state after a call settles. Any future comparison must first justify that caller and freeze the adjacent versions, hold/call/worker counts, payload sizes, acknowledgement schedule and resource ceilings. Predeclare state-at-settlement equality for success and error paths, overlap/cancellation and unsupported late-effect controls; then measure completed/failed task denominators, effective throughput, end-to-end/tail latency, queued bytes/resource maxima and observation cost. Restart or durable-effect claims require their own receipts and failure controls.

This source review introduces no new observer prerequisite and does not reopen our accepted finite H2 or native evaluation retry fixtures. Our existing native runtime version is unchanged. H1's negative/invalid-memory evidence, prior failed freezes and full H3/H4 unmet gates remain intact. The pinned Pi contribution guide requires prior maintainer `lgtm`; this review sends no issue, PR or comment and establishes no contribution admission.

[Source identities and review receipt](receipts/20261105T125316Z-chord-state-before-answer.json).
