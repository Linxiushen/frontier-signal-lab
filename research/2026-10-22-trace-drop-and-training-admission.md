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

## 2026-10-23: GEPA rejects the whole episode after rollout

Verifiers [PR #2972](https://github.com/PrimeIntellect-ai/verifiers/pull/2972), by **xeophon**, merged at **2026-10-23T20:42:29Z** as `fe1f4bcd398f3783fd30d1016f59230dee1884b7` (parent `6bc2ea8fad467b6b4bf69a6e78e9bb37f64904b6`). Four complete immutable source pairs were read and their Git blob hashes verified: the adapter, trace, episode and MIT license. Only the adapter changes, by two lines; the merge adds no tests. This is a newly verified consumer boundary, separate from #2960's storage semantics.

`GEPAAdapter.evaluate` completes `_run_batch`, then computes `_episode_score` before returning an `EvaluationBatch`. The new guard raises `ValueError` if **any** trace is dropped. A mixed-seat episode is rejected in full; it does not average only the remaining seats. Normal evaluation therefore returns neither scores nor captured trajectories for that batch. The PR explains that GEPA needs one numeric score per input and cannot represent an excluded example. The direct adapter code implements that refusal; external GEPA exception handling was not reviewed.

| Episode at this pinned version | Static scoring path |
| --- | --- |
| Recorded finite zero, no drop | Retains the zero in the scored mean |
| Reward-less seat, no drop | Omits the seat from the mean; no scored seats still yields `0.0` |
| Dropped seat with earlier reward | Raises before computing the mean |
| Reward-less dropped seat | Also raises; cannot become an implicit zero |
| Mixed dropped and valid seats | Rejects the entire episode and prevents the batch return |

The guard runs **after rollout**. `_run_batch` passes `on_complete` into `env.run_slot`, so this change establishes no rollback of earlier persistence callbacks, consumed tokens or other effects. `make_reflective_dataset` is unchanged and has no independent drop check: a normal failed evaluation cannot supply its returned trajectories, but an externally constructed batch is a separate boundary. This merge does not establish prime-rl filtering, whole-run shutdown, retries or recovery correctness.

For H3/H4 integration, freeze native versions, candidate/task/seat membership and resource limits before running the table's controls, including an empty drop reason. Check actual `evaluate(capture_traces=True)` return/failure membership and optimizer teardown/retry/recovery, retain completed rollout costs and artifacts, and test externally supplied reflection batches separately. Report attempted versus returned batch/task/seat counts with success, useful throughput, tail latency and resources. A fail-closed optimizer adapter does not by itself validate cheaper evaluation, improved model quality or durable effects.

No upstream package or test, model, service or scientific experiment was executed for this source review. Existing H1 failures and all unmet native acceptance gates remain unchanged. [Exact source receipt](receipts/20261023T220622Z-gepa-drop-admission.json).
