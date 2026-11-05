# GEPA failed-episode admission at the optimizer boundary

Verifiers merged [PR 3082](https://github.com/PrimeIntellect-ai/verifiers/pull/3082) on 2026-11-05 at 20:34:37 UTC. The change rejects a failed episode before the standard GEPA adapter returns candidate scores and reflection trajectories. This is a new landed source change, not a local model, optimizer or native-run result.

The author is `xeophon` / Florian Brand; the merge committer is GitHub's `web-flow`. It is an ecosystem contribution, not evidence that Will Brown authored this fix or that an author's affiliation changed. The referenced issue 2977 was opened earlier; its closure is not a new research release.

The exact comparison is parent `308619da69c2e918c6b7c96e68f746485a913dba` against landed `d295ca87d6dacee7949ab68c665e023e5c36dbe3`. Only `verifiers/v1/gepa/adapter.py` changes: three added lines and one removed line, including the docstring. The repository is public and MIT licensed. Full saved sources and API receipts are bound by the [curated source receipt](receipts/20261105T205502Z-gepa-failed-episode-admission.json); rolling raw captures remain local.

## What the actual caller does

In [`GEPAAdapter.evaluate`](https://github.com/PrimeIntellect-ai/verifiers/blob/d295ca87d6dacee7949ab68c665e023e5c36dbe3/verifiers/v1/gepa/adapter.py), `_run_batch` first invokes `Env.run_slot` for the candidate's task slots. The adapter then computes one `_episode_score` per returned episode, and only afterwards constructs an `EvaluationBatch` containing scores, outputs and optional trajectories.

The parent scorer rejected any episode containing a dropped trace, then averaged the rewards of traces with a nonempty reward mapping. It did not check `episode.ok`. The landed scorer keeps the dropped check first and adds a `ValueError`, including the episode ID, when `episode.ok` is false. A successful episode without scored traces still scores zero. The existing mean and its trace membership rule remain unchanged.

The PR author's concrete failure mechanism is that a participant can record a positive reward before another judge or finalization step fails. A positive partial reward therefore does not establish that the episode completed. The source change closes this admission gap in the standard GEPA evaluation return path. It does not replace a failed episode with zero or selectively return the other successful members of that batch.

`Episode.ok` records the final attempt verdict. Historical errors can remain after a successful retry, so checking whether `errors` is nonempty would impose different semantics. This source review does not claim every episode with an error history is rejected.

## Boundaries that remain open

All rollouts in the batch have already run when scoring begins. `Env.run_slot` invokes the runner's completion callback before returning; the GEPA runner can already have appended the episode to its trace log. Rejection supplies neither a budget refund nor rollback of model calls, effects or persistence. The change does not bound the number of pending tasks, retry traffic, retained traces or memory.

`make_reflective_dataset` is unchanged and contains no independent failed-episode check. The new guard prevents the ordinary `evaluate` path from returning the failed batch to reflection; it does not authenticate an externally constructed `EvaluationBatch` passed directly to that method. General training admission, custom environment completion policies, restart reconstruction and external scoring consumers require their own contracts.

No test file changes in this commit. Adjacent test definitions and source semantics were inspected; no upstream test suite, GEPA run, provider call, model or scientific experiment was executed locally. Author statements and source inspection do not establish a passing regression or a real-model quality improvement.

## Engineering implication and next gate

Actual caller/load: native GEPA prompt optimization over batched tasks, potentially with several participant traces and a separate judge. At larger batch and candidate counts, treating partial reward as a completed result can contaminate candidate ranking and the teacher's reflection data, while a late fail-fast exception still leaves the rollout cost spent.

The native integration point is the adapter's episode-to-score admission immediately after `Env.run_slot`, with the existing runner persistence hook retained. A future justified integration should keep the parent/landed versions explicit and reversible. Before execution, freeze task, model, evaluator, adapter and optimizer versions; candidate and physical request budgets; concurrency and resource ceilings; retry/recovery policy; and the accepted-score denominator.

Proposed acceptance controls, not results: a failed positive-reward episode must not enter ranking or ordinary reflection; successful zero and recovered-error episodes must retain their documented behavior; a dropped seat must reject the episode; mixed batches, persisted failed artifacts, teardown and resumed attempts must preserve identity and spent allowances. Report useful completed evaluations, all failed/dropped/scored memberships, end-to-end and tail latency, peak resources and observation cost under the fixed workload. No new experiment is preregistered or executed here.

Our earlier [native exhaustion result](../results/verifiers-budget-native-exhaustion/report.md) already keeps outer failed outcomes at a NULL selectable reward and a spent allowance. That deterministic fixture did not establish GEPA's multi-participant partial-positive-reward behavior. This source evidence sharpens a downstream integration boundary without upgrading full H3/H4, rerunning a closed fixture, changing H1's negative results or reopening H2's accepted finite gates.
