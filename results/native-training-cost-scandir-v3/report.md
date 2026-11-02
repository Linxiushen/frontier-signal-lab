# Native training cost v3: dense completion, compression caller failure

One separately frozen suite ran once on 2026-11-02 and **failed on its second training case**. Dense seed503 completed64 AdamW updates/8192 target tokens; the corresponding saved-activation INT8 case loaded the model but returned `ValueError: too many values to unpack (expected 2)` in the train phase. Ten remaining cases and every final evaluation were unrun. There is no paired cost, memory-benefit or quality result, and no retry.

The actual caller is the accepted native training/trace-ledger integration with pinned Pythia-14m, CPU float32/eager, one thread, the original Alice training fixture and identical initial AdamW. The compression treatment is existing saved-activation INT8 excluding norm/attention, not a learned residual-bank architecture. Its operational question remains whether complete compression training, including packing/retrieval, data, backward, optimizer, checkpoint and observation costs, meets matched token/time budgets and sealed endpoint-quality gates.

## Execution and environment

The CLI ran05:10:42.137919–05:11:14.809442Z, exit1, with32.6698775 seconds of outer monotonic subprocess time. That includes its in-process authentication/preflight and native stages, but excludes preparation, wrapper checks and post-outcome review. The inner suite was31.5072632 seconds. The original12jobs, seeds503/701/907, LR1e-4,64-step/60-second arms,20-second import deadline,180-second maximum case and1200-second suite budget were unchanged. Free disk25,758,629,888B and memory28,783,611,904B passed the original5GiB/8GiB preflight gates.

Both cases used the same explicitly revised composite environment: a prepared Transformers4.57.3 copy with the historical scandir enumeration backport, plus the currently configured base Python runtime. The base Python executable and DLL hashes differ from the old pin; all three have valid OpenAI OpCo signatures. Both executable version strings report3.12.14, but that does not establish binary equivalence or explain the change. Complete prepared-runtime26,720-file and current-base1,028-file inventories were authenticated. The old-pin preparation refusal and an unexecuted draft wording correction remain retained. **Startup completion cannot be attributed to scandir alone.**

The dense and INT8 import stages completed in5.3541193 and4.7339985 seconds respectively, within the unchanged20-second deadline. Both models loaded;14bounded import markers were saved. This establishes local startup for those two cases in this composite environment, not a startup speedup or support for all remaining jobs.

## Observed outcomes and costs

| Endpoint | Dense seed503 | INT8 seed503 |
| --- | --- | --- |
| Complete case wall |22.1533256s|9.2541176s, failed|
| Completed updates/targets |64 /8192|No completed loop receipt|
| Training-loop wall / CPU |11.2163431 /11.21875s|Unavailable|
| Loop-only useful throughput |730.362822 targets/s|Unavailable|
| Step latency n64, p50/p95/p99 |0.1724059 /0.1827532 /0.2455298s|Unavailable|
| Final evaluation |Unrun|Unrun|

The dense endpoint parameter hash is `4f5407f206433ba247c3b45647e59d4d7931224442dcdc776f3ac934105b7ecc`; its complete retained checkpoint hashes to `be605ee5af36558898106b44aa27cf5498a709879a05fcb98cd4f94cf9e8a3be`. Loop throughput excludes startup/checkpoint/evaluation and cannot serve as complete paired throughput. The suite stops on the first failure; no missing work is imputed.

For dense, the retained training interpreter's observed OS **lifetime working-set high-water through the postloop boundary** was588,431,360B. Maximum sampled private bytes were697,319,424B and sampled resident bytes588,333,056B;561in-loop samples had a maximum gap0.0207464s. Parent memory-query wall cost was0.1121335s and recorded native CPU cost0.03125s. These are different endpoints: sampled private values are lower bounds, lifetime working-set high-water includes prior process history, and none is isolated activation/device memory. There is no matched compression endpoint or OFF arm for causal observation overhead, memory savings or performance claims. Communication/GPU/distributed performance was not tested.

The dense ledger has569rows/316,083B; the failed case has5rows/2,428B. All ten retained process handles exited and both Jobs became empty. Dense exit codes were all0; the failed case retained57347/57347/57347/1/0. Exact raw controls, identity, sampling, cleanup and import evidence are preserved; finite handle observations do not establish continuous process coverage.

## Concrete integration blocker and separate preparation

The frozen caller passes `cost.preservation_modules(model)` directly to `preserve_scopes`. The producer returns `(norms, attentions)` with13and6named module pairs, while the context expects a flat iterable of `(name, module)` pairs. Source review explains how the outer13-entry list causes unpacking to fail before batch access. The original worker saved an exception string without a traceback, so this is a source-supported explanation, not a captured stack localization.

The separately named [v4 caller](../../experiments/native_training_cost_scopes_v4.py) flattens those two ordered groups before entering the existing context. Its [entrypoint](../../scripts/run_native_training_cost_scopes_v4.py) and [pure regression](../../tests/test_native_training_cost_scopes_v4.py) are independent of the old frozen files. The real `preserve_scopes`/codec context reproduces the old failure before first batch indexing; the new caller installs all19wrappers in order, reaches a first-batch sentinel, and restores both class and instance forwards after that exception. No forward, backward, optimizer step, ML import or native workload occurs in these controls. Three new plus nine neighboring controls pass. Independent normalized-AST review confirms otherwise identical caller/launcher behavior and extended source pins only.

This prerequisite is complete. The next action is a **future, separately frozen execution of the original full12-case workload** through that corrected caller, retaining resources, deadlines, independent quality gates and every old failure. There is no new v4 freeze or native attempt this round, timeout widening, observer-only detour, seed/LR rescue or acceptance rewrite.

## Preservation and reproducibility

All93original files/58,889,795B were rehashed and independently copied byte-for-byte; the50-check saved-outcome review passes while **execution remains rejected**. The frozen saved auditor also reports receipt integrity true/execution accepted false and does not rehash checkpoints; the independent preservation review separately hashes the opaque checkpoint. Neither executes a model. The92metadata files/2,590,660B are published unchanged in `raw/`. The56,299,135B checkpoint remains in the ignored original run directory and is **omitted from the public selection**; the [full raw manifest](raw-manifest.json) records its exact hash. Model weights are not bundled.

The [executed protocol](../../fixtures/native-training-cost-scandir-v3/protocol.json), [implementation freeze](../../fixtures/native-training-cost-scandir-v3/implementation.json), exact CLI/environment receipts and independent reviews accompany the negative result. The [selected manifest](selected-manifest.json) hashes the publication selection. Saved metadata auditing needs no Torch/model execution:

```text
python -S -X utf8 scripts/audit_native_training_cost.py --output results/native-training-cost-scandir-v3/raw
```

A retained first focused-test invocation used a nonexistent module; its corrected12pure/mocked prefreeze methods passed, without changing source/tests. That invocation error did not run a model. Post-outcome canonical portable validation and scope are in [validation.json](validation.json); ordinary tests do not rescue native acceptance.

The earlier six joint scientific screen failures and invalid parent RSS remain unchanged. Actual-caller ledger v3 stays accepted/closed; this cost suite stays failed. Existing public LookingGlass data would provide procedural sealing only, not fresh generalization. H2/H3/H4 are unchanged; GPU, multi-node, production, learned-bank quality and complete comparative cost remain unverified.
