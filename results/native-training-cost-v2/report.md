# Native complete training cost v2: import deadline failure

The corrected CLI crossed the frozen path checks and launched the first native case, but stopped at the original 20-second `postimport-ready.json` deadline. **No pretrained model loaded, optimizer update ran, or final evaluation occurred.** The remaining 11 cases were not launched. This is a startup failure, with no training-cost, memory-benefit or quality result.

One original invocation ran on 2026-10-22 from 06:02:15.814969Z to 06:02:38.345152Z and exited 1. There was no retry. Execution revision 2 retains the core study ID `native-matched-training-cost-v1`; the 49 core source files, 50 accepted-caller source files, 12 jobs, seeds 503/701/907, LR 1e-4, data, thresholds and budgets are unchanged. The new freeze also pins the existing corrected launcher and its two portable test files (52 source files total).

## What the evidence establishes

The five saved import markers are `site-start`, `site-complete`, `torch-start`, `torch-complete`, and `transformers-start`. The Torch start/completion marker interval is 11.419279 seconds. Neither `transformers-complete` nor `postimport-ready.json` was recorded before termination. There is no worker failure receipt, Python traceback or submodule stack identifying why Transformers had not completed; a slow import, blocked import, dependency failure or other root cause has not been established. The earlier ledger-v1 timeout remains independently unexplained.

The worker completed the preimport acknowledgment and retained-identity checks: one actual-interpreter memory sample, two held censuses, and two ledger rows / 776 bytes. Five retained identities exited with termination code 57347 (0xE003); Job active count was zero, cleanup took 0.0409294 seconds and no cleanup/close error was saved. These startup observations do not measure training memory or cost. Saved Python-audit guard receipts through the last marker contain no unexpected denial and no allowed local probe; they do not attest later activity or native network isolation. All processes were launched through background CLI with hidden native windows; no input-device or visible-browser automation was used.

The frozen auditor reports `receipt_integrity_passed=true` and `execution_accepted=false`. Its failed-case path has limited checks. A separate post-outcome, read-only review verifies all 20 raw files, 52 frozen sources plus the accepted caller's 50 sources, exact report/case copies, import prefix/identity/provider pins, controls and ordering, ledger bytes, held role receipts, retained exits and absence of later artifacts (180 checks). Preservation is not execution acceptance; neither review launches a model or native workload.

## Invocation and validation

The pre-execution controls use the real parser and unchanged runner through path/hash/precondition checks, then a sentinel stops before native `run_case`; executable/model/resource checks are mocked. Relative paths containing spaces reach that boundary, while wrong output/source pins are refused before directory creation. Nine focused methods and the full 1002-method portable suite passed before freezing (921 passed, 81 skipped). They did not predict or validate native import completion.

```text
python -S -X utf8 scripts/run_native_training_cost.py --protocol fixtures/native-training-cost-v2/protocol.json --freeze fixtures/native-training-cost-v2/implementation.json --output reports/runs/20261022T055547Z/native-training-cost-v2 --plan reports/runs/20261022T055547Z/cost-execution-plan.json
```

The invocation's exact argv and timestamps are saved in `execution.receipt.json`. The local plan contains machine-specific executable/model paths and is not published. The immutable freeze records hashes of executables, runtime files, model assets and data. The output is single-use: do not rerun this version or widen its deadline after seeing the outcome. The read-only auditor is reproducible against the selected raw files:

```text
python -S -X utf8 scripts/audit_native_training_cost.py --output results/native-training-cost-v2/raw
```

## Engineering gate and limits

The actual-caller ledger-v3 integration remains accepted and closed. The intended next result still concerns matched complete dense/compressed training in this actual caller, including pack/retrieve, forward/backward, AdamW, data work, observation and checkpoint costs, valid native memory endpoints and final evaluation. The treatment is existing saved-activation INT8 excluding norm/attention, **not a learned residual-bank architecture**. The planned endpoint is actual-interpreter OS lifetime working-set high-water before checkpoint; sampled private values would remain lower bounds. Neither endpoint was reached.

The existing public Alice/LookingGlass fixture is reused; its sealed evaluation would be procedural isolation, not a fresh generalization or data-cleanliness claim. No final-quality gate was evaluated. Six historical H1 joint failures and invalid historical parent RSS remain unchanged; no H2/H3/H4 gate is upgraded.

Unchanged full-suite repetition is blocked by the import deadline. If pursued again, first separately preregister a bounded failure-observation/control at this same caller's import boundary, with a specific question, resource ceiling and exit condition; then return to the complete workload. Do not create another observer-only campaign, blindly extend timeouts or rescue seeds/LR/thresholds. This pass performs no second model/native attempt. Evidence is local single-machine CPU startup only; GPU, multi-node, production performance, full cost and quality remain unverified.

## Saved evidence

- [Failure counters and limits](failure.json)
- [Validation scope](validation.json) and [independent preservation review](preservation-review.json)
- [Original suite report](raw/report.json), [failed case](raw/token-503-0-case.json), and [ledger](raw/token-503-0/trace.jsonl)
- [Versioned protocol](../../fixtures/native-training-cost-v2/protocol.json) and [implementation freeze](../../fixtures/native-training-cost-v2/implementation.json)
- [Selected file hashes](selected-manifest.json)
- [Prior path failure](../native-training-cost/report.md) and [accepted actual-caller ledger](../training-ledger-v3/report.md)
