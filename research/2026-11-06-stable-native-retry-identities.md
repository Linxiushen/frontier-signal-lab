# Stable retry identities and physical attempt accounting

Verifiers merged [PR 3057](https://github.com/PrimeIntellect-ai/verifiers/pull/3057), authored by Mika Senghaas (`mikasenghaas`), on 2026-11-06 at 00:46:39 UTC. It gives logical episodes and agent runs stable identities within their respective retry loops, with separate attempt numbers and fresh subprocess work directories. The proposal dates from November 3; the merge is the new event.

This review compares parent `d295ca87d6dacee7949ab68c665e023e5c36dbe3` with landed `f167a92e3730d017f591dcaac0e94c437f238733`: eight changed files, 144 additions and 12 deletions. The public repository is MIT licensed. Twenty-nine full source versions, complete tree proofs and the exact diff are bound by the [curated receipt](receipts/20261106T005029Z-verifiers-retry-identities.json). This is source and test-definition inspection only; no upstream tests or native/model experiment ran here.

## Two nested retry identities

[`RunSlot`](https://github.com/PrimeIntellect-ai/verifiers/blob/f167a92e3730d017f591dcaac0e94c437f238733/verifiers/v1/env.py#L62) now owns an episode UUID. `Env.run_slot` passes that ID into each whole-episode attempt and increments a counter from one. It resets the slot's live trace list for the next attempt and calls the completion callback after the retry helper returns the final episode. Reconstructing a finished slot copies the recorded episode ID.

Separately, [`Agent.run`](https://github.com/PrimeIntellect-ai/verifiers/blob/f167a92e3730d017f591dcaac0e94c437f238733/verifiers/v1/agent.py#L688) mints a trace UUID before its own retry loop. Those rollout attempts share that trace ID and have their own counter. The episode agent discards the abandoned attempt from the live view before registering its replacement; only the final returned trace joins the episode's completed trace list.

A whole-episode retry creates fresh episode agents and can invoke `Agent.run` again. That invocation mints another trace ID and starts its trace counter again. An episode can therefore retain its ID while its agent-run IDs change. Neither UUID defaults nor the new integer fields persist an allocator or counter across process restarts. Direct callers supplying their own IDs also need an explicit contract.

## Logical identity does not preserve every cost

Owned rollout backends receive the trace ID as their logical name. The subprocess backend now uses [`tempfile.mkdtemp`](https://github.com/PrimeIntellect-ai/verifiers/blob/f167a92e3730d017f591dcaac0e94c437f238733/verifiers/v1/runtimes/backends/subprocess.py#L106) under the cache root, avoiding collision with a previous same-name directory. A fresh directory is a physical allocation; its uniqueness provides no measured cleanup or retention bound. Docker's container UUID and Prime's service-returned sandbox ID are separate physical identities.

The retry helpers retain earlier errors on the final object even when its current `ok` verdict is true. They do not merge every abandoned attempt's complete trace graph, usage, rewards or artifacts into a spend journal. Error history and a final score cannot reconstruct every physical request or runtime allocation. Per-trace scoring remains in `Rollout.close`; environment finalization remains in `Env.run_episode`. This diff changes neither scoring policy nor evaluator/version admission.

There are also separate transport retries. Captured OpenAI client construction sets `MAX_RETRIES=0`, while harness or runtime SDKs can own their own retries. An episode attempt, an agent attempt and an HTTP transmission are different accounting units. The PR does not measure their combined multiplier.

The actual [`vf-run` caller](https://github.com/PrimeIntellect-ai/verifiers/blob/f167a92e3730d017f591dcaac0e94c437f238733/verifiers/v1/cli/run.py#L68) records run identity and appends the final episode through `on_complete`. Its trace writer stores artifact paths under the trace ID, then appends JSONL with a process-local async lock and cancellation shielding. It has no fsync, deduplication transaction or durable attempt reservation. The CLI refuses a nonempty existing trace file; it does not implement resume through these IDs.

## Evidence and proposed native acceptance

The two new async test definitions use a substituted `FakeRollout` and `FakeEnv.run_episode`. They check three logical attempts, stable IDs and retained error history. They were inspected, not executed here, and do not exercise real HTTP, subprocess cleanup, scoring, cancellation or restart. The author's reports of unit tests, Prime sandboxes, evaluations and a four-rollout nested-retry case remain author claims. The linked prime-rl companion and cross-version readers were not independently validated.

Actual caller/load: batched `run_episodes -> Env.run_slot -> Env.run_episode -> Agent.run -> Rollout`, followed by final persistence. With concurrent retries, several physical allocations can map to one logical unit while final storage omits earlier costs. Whole-episode retries can repeat score or effect work. A concurrency semaphore also does not by itself bound the number of already scheduled task objects.

The integration points are the slot/episode ID and attempt, agent-run trace ID and attempt, live discard/replacement callbacks, physical backend identity and final writer. Our inference is that budget and recovery integration should bind these scopes explicitly, retaining immutable task/model/judge/version and content identity plus independent physical spends.

Before a future justified run, preregister workload, concurrency, transport/framework retry policies and resource ceilings. Require the intended identity and counter invariants, all-attempt spend custody, current admission and cancellation, successful controls, bounded backlog and cleanup, and no budget reset or duplicate effect through two process restarts. Report success/quality, effective throughput, end-to-end and tail latency, measured resource/communication peaks and observer cost. These are proposed criteria, not a new protocol or result.

Our [native retry](../results/verifiers-budget-native-retry/report.md) and [exhaustion](../results/verifiers-budget-native-exhaustion/report.md) studies remain pinned to `f5f5c9ace86b9720049cb6e98d05d14d77042486` and their finite gates stay closed. The parent [GEPA admission review](2026-11-05-gepa-failed-episode-admission.md) addresses a distinct current-episode success check. No dependency adoption, unchanged fixture rerun, H1 negative-result revision or H1-H4 scientific upgrade follows from this source review. GPU, distributed and production behavior remain unmeasured.
