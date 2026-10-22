# Dropped traces can still be successful

Verifiers [PR #2960](https://github.com/PrimeIntellect-ai/verifiers/pull/2960), by **mikasenghaas**, merged at **2026-10-22T20:57:53Z** as `2f6ed0ce6e04e26b713801a3e701e857b6f36452`. We verified all sixteen complete parent/landed file pairs, Git blob hashes and exact PR/merge patch replay, then inspected the changed production and test code. This is source evidence; no upstream package, provider, model or trainer was executed locally.

`Trace.dropped` is a reason independent of `ok` and errors. `drop(reason)` retains the first reason; `is_dropped` checks `is not None`, so even an empty reason is a drop. The operation does not erase an already recorded reward. `Trace.reward` still sums non-None rewards, and an empty map still totals zero. A consumer that checks only `ok` or a scalar reward therefore cannot determine training eligibility.

| State in this version | Recorded behavior | Required consumer distinction |
| --- | --- | --- |
| Finite zero reward | A reward entry exists | A scored wrong answer can be trainable |
| Callback returns `None` | `Task.score` omits that value | This alone does not call `drop` |
| Explicit drop | Reason exists; `ok` may remain true | Exclude from means and training admission |
| Nonfinite reward value | `record_reward` raises | A scoring failure, not an implicit drop |

A rubric criterion has scored `choices` and disjoint `drop` answers. Scored values must be finite. A drop answer applies even at zero criterion weight: the rubric records answer indicators, drops the trace and returns `None` before weighted aggregation. The agentic-judge environment propagates the reason to the solver. These are changes to selection policy and denominators, not proof that task quality improved.

The drop participates in scoring state. A shared `scoring_transaction` restores it with partial state/rewards/metrics/info on `BaseException`. Isolated `grade_task` commits the scored copy's drop only after grading and `on_score` complete. `Task.rescore` refuses errored traces and clears an existing drop before rescoring. The commit removes `UnscoredError` and the old post-score NaN-to-None path; our earlier [cap/skip review](2026-10-22-rollout-cap-and-scoring-policy.md) remains evidence about its pinned earlier commit. Ordinary `scoring_skipped` and explicit dropped are separate policies.

`format_mean` filters dropped traces before both displayed means; replay and serve deltas expose the reason. No trainer file changes in this commit. The author explicitly warns that prime-rl's `iter_trainable_traces` must exclude dropped traces before adopting this version. We have not checked downstream dependency adoption or established a current prime-rl defect. The author's no-retry/resume-retention statement and private live isolated-grading rollout are reports, not independently verified behavior here.

Four new unit functions check rubric drop metrics, selected criterion validation, NaN reward rejection and shared-transaction rollback. The sixteen-file commit adds no complete rollout/resume/trainer or isolated-grading test. The reported 221-pass/nine-skip suite, private model run and manual style/type checks are author assertions; no upstream CI logs or local upstream tests were reviewed/executed.

H4's real caller is rollout → rubric/shared-or-isolated grading → persisted trace/replay → training-batch admission. At scale, an omitted filter admits policy-excluded samples, while silently changing the denominator can improve an apparent mean without improving the workload. Before execution, freeze authentic runner/rubric/trainer versions, workload IDs, resource ceiling and acceptance thresholds. Include finite zero, `None` without drop, scoring skip, explicit drop with prior rewards, zero-weight drop, nonfinite failure, shared rollback, isolated failure/commit, rescore, duplicate callbacks and two process recoveries. Preserve attempted/scored/skipped/dropped/failed/admitted memberships **and intersections**; these states need not form a disjoint partition. Reject any dropped training member, duplicate accepted score/effect or unexplained denominator change. Report success, useful throughput, end-to-end/tail latency, resources and observation costs on the fixed workload. These are unmet native integration gates.

Scientific status and all negative results are preserved. Zero scientific/native/model experiments ran in this pass; H1's accepted caller ledger/import observation stay closed and its twenty-second startup remains unsupported. [Exact source receipt](receipts/20261022T220202Z-verifiers-trace-drop.json); landed MIT license verified, full upstream implementations not redistributed.
