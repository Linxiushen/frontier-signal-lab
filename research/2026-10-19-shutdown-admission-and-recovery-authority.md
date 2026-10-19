# Shutdown admission is separate from recovery authority

Reviewed 2026-10-19T13:30:38.081122+00:00. This is one bounded source review of [OpenClaw #177223](https://github.com/openclaw/openclaw/pull/177223), created 2026-10-19T10:00:16Z and merged at 10:37:37Z. It was already a deferred lead; its event time predates this pass. Peter Steinberger (`steipete`) authored the PR/commit and merged it; `web-flow` is the squash committer. The repository is public and the exact landed license is MIT. No upstream code was imported or executed locally.

## What the exact source changes

The landed [3825c6a6](https://github.com/openclaw/openclaw/commit/3825c6a60b81ec0348d55b60708e70ea5312858e) and adjacent parent `2920e7377d9497c3af88f00c7f3696cc357de481` contain seven modified files. All seven full pairs and the license body were decoded and checked against Git blob SHA1 and saved SHA256. The three production files implement two boundaries:

- `server-lifecycle.ts` keeps the admitted in-process binding available through execution/finalizer settlement, then retires dispatch readiness/binding in final teardown. The existing new-entry fence remains. The complete close-plan dependency closure was not reviewed.
- The reconcile guard carries its service cancellation signal into coordinator recovery, through its queue wait and session admission. The existing provider-settlement join and FIFO predecessor tail remain. An exact duplicate in-flight recovery returns the existing foreground promise before the later caller's signal path; this is not proof of general per-caller cancellation.

The new queued-recovery regression holds a real session mutation and expects service stop while it is still held. It asserts no mocked provider provisioning/destruction/bootstrap and intact durable provisioning/allocation. The binding integration holds a finalizer, checks availability during cleanup and entry refusal, then checks binding unavailable afterward. These are useful executable upstream assertions, not local results. The committed process E2E uses synthetic local SSE/provider behavior, a wall-clock `Date.now` <10s assertion and selected PID checks; it boots that compiled Gateway once. It does not itself prove a second boot, restored parent authority, live provider settlement or a monotonic production deadline.

## Author reports, including negative results

The PR body reports 3 binding tests, 31 provisioning tests and 28 coordinator tests. A first candidate run found a missing test spy and was corrected. Its 105.72s three-file run and 53.45s final single-file run have different scopes. The scripted process E2E passes both baseline and candidate; its 12.187/9.623s test-only and 20.54/43.66s preparation-inclusive walls are not a paired causal speed comparison.

Separately the author reports two concurrent real-model Linux pairs, 16 CPUs per side, independent state/ports and a common barrier; pair 2 swaps CPU halves:

| Pair | Baseline SIGTERM exit | Candidate SIGTERM exit | Candidate delta | Baseline/candidate lifecycle-wake release |
| --- | ---: | ---: | ---: | ---: |
| 1 | 1030 ms | 1083 ms | +53 ms | 125/129 ms |
| 2 | 1826 ms | 3064 ms | +1238 ms | 1129/2430 ms |

The candidate is slower in both pairs. Both miss the target of settling every owner within 1 second in pair 2; its lifecycle-wake tail is longer on the candidate. Run registries clear in 25/29 ms and 29/28 ms, so an empty registry is insufficient to establish full settlement. Exit 0 and no surviving reported children do not establish a speedup, unconditional timing neutrality or the cause of the tail. The original 85-second incident remains unreproduced and unattributed.

The author reports all four next boots as `started=2 settled=1 failed=0 skipped=0`. Peer and streaming turns complete, while lifecycle wake settles as `operator_authority_unavailable`. A persisted synthetic-device pilot also fails to restore authority. Parent-wake resumption remains a proof gap. The compiled comparison uses baseline `f2f019d60638d9813d2324e5126d7b1d2666fce5` plus the three production changes, not an independently authenticated adjacent packaged A/B. Its hashes, final rebase identity, logs and model runs were not independently verified here.

## CI custody and coverage limits

The PR-head check endpoint returns 100 of 190 rows: 30 success, 69 skipped and one failed `PR context and evidence` check. The author reports a selected final test run green and an earlier headings check corrected; without the other 90 rows or job logs this does not establish all-head green or independently attribute the retained failure. Landed-head metadata contains 39 rows: 5 success, 32 skipped, 2 cancelled.

The initial custody audit incorrectly required complete PR-head CI inventory and failed that check. It is retained unchanged. A separate 56-check offline audit verifies source custody and explicitly preserves the incomplete inventory. No network retry repaired this limit. The [public receipt](receipts/20261019T132018Z-shutdown-admission.json) binds all seven pairs, raw response hashes, both audit hashes, author reports and limits.

## H2 research revision and next falsifier

Our inference is that shutdown tests must separately observe queued cancellation, already-started effects, retained cleanup binding and restored authority. Neither a clean exit nor an empty run registry demonstrates successful resumed parent work. This narrows H2's next experiment criteria; it does not upgrade runtime evidence.

Pin authentic adjacent packaged Gateway runtimes and complete lifecycle/session/provider dependencies. Hold both coordinator and session admission, then cancel before provider entry; independently verify bounded settlement, zero provider/write entry and unchanged durable provisioning. Contrast already-started provider/write work: retain exact FIFO/lease ownership until actual settlement, reject late writes/reordered successors, and measure logical abort, run-registry drain, finalizer drain, provider/OS exit and authority restoration separately under preregistered monotonic deadlines. Fence new entry while retaining the admitted binding through cleanup; test shutdown during held finalizers and deduplicated recovery with a later caller's cancellation. Independently boot twice with interrupted peer, stream and yielded-parent wake, current device/role authority, exact durable identities and healthy/refused/revoked-authority controls. A clean exit/empty registry or operator_authority_unavailable does not satisfy successful parent-wake recovery. Missing/mismatched effects, lost FIFO/custody, unauthorized continuation or a missed bound falsifies the corresponding claim. Freeze matched-host baseline/candidate timing and negative controls before any speed claim. Proposed only; no local experiment released.

No local experiment was released. Existing H1 bank/consumer training intervention and sealed quality gates remain unmet; H2 lacks the authenticated packaged fixtures and complete authority/provider/restart harness. Repeating the accepted WAL or trace primitives would not test this change. H1's six cost/quality failures and invalid historical parentRSS, prior native observer rejections and H3/H4 planned status remain. No GPU/API purchase or researcher contact occurred.
