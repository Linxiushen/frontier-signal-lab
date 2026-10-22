# Same-caller import observation: one stack capture, cost execution still blocked

One separately frozen observation in the existing native training-cost caller captured a Python stack at 15 seconds, then hit the unchanged 20-second postimport deadline. The saved stack points to `transformers/utils/import_utils.py:2580 create_import_structure_from_path`, called by `define_import_structure` at line 2867. **This identifies a sampled execution location, not a proven root cause, deadlock or import-latency benchmark.** No model loaded, optimizer update, training loop or evaluation ran; the other 11 original jobs were unrun. There was no retry.

The exact CLI ran on 2026-10-22 08:05:51.620680Z–08:06:14.366258Z and exited 1. The original 49-source `native_training_cost.run` / `run_case` / worker, identity, role admission, provider guard, controls and cleanup were unchanged. A separately pinned wrapper selects the same worker path, arms `faulthandler.dump_traceback_later(15, repeat=False, exit=False)` only at its import boundary, and unconditionally raises before returning successful packages to the original model-loading path. Prior cost-v2's 52 sources and accepted caller-v3's 50 sources remain unchanged.

## Observation and limits

Five progress markers end with `transformers-start`; `torch-complete` exists. The 1,944-byte dump has one `Timeout (0:00:15)!` header and frames through the actual `native_training_cost.worker` and wrapper. The arm receipt matches the retained interpreter PID/creation time/nonce and precedes import markers. No import completion or disarm receipt exists: the fixed deadline terminated the process before the wrapper's `finally` could run. No hidden worker exception or traceback was recorded.

All five retained identities exited with termination code 57347 (0xE003); Job active count was zero. Two held censuses and one preimport sample produced two ledger rows / 774 bytes; cleanup took 0.041527 seconds. Those observations are not training memory/cost measurements. Saved Python-audit provider receipts through the last marker contain no unexpected denial or allowed probe; they do not attest subsequent or native network behavior.

The stack file was opened by the authenticated worker wrapper after the preimport continuation. Its contents have no independent nonce field; attribution relies on that pinned code path, matching arm receipt and the saved file. `faulthandler` adds a watchdog thread and output I/O, so this observation does not establish equivalence to the prior timing. The 8 MiB output ceiling is a retained-output acceptance check after cleanup, not a filesystem quota. No repeated dump is scheduled. Prefreeze portable tests may warm caches.

The stack's `import_utils.py` file was not among the old selected runtime hashes. A separate **post-outcome** read records its current SHA256 and the recursive import-structure code at those lines; that is a candidate explanation, not proof of the exact bytes executing at capture or the source of the deadline overrun. No native/model rerun, dependency change or timeout increase was performed to test it.

## Validation

Twelve focused methods passed before freezing. The full suite ran 1005 methods: 924 passed, 81 skipped. New portable controls exercise completion and original-exception paths, verify one-shot arm/cancellation/file lifetime and the unconditional no-model stop, and refuse the old freeze before native launch. An initial invalid mock nonce caused two control errors and was corrected before freezing; it did not launch a native process. These portable controls are not a native import-completion result.

A post-outcome standard-library review verifies all 22 raw files, exact case/report copies, source hashes, controls, ordering, identity/provider pins, ledger bytes, stack arm/header/location/size, retained exits and empty Job (186 checks). It launches no model or native workload. **The bounded location observation is accepted; training-cost execution remains rejected.** All raw files, including the original stack filenames/frames, are copied byte-for-byte; the stack contains no frame locals.

## Exit condition and next integration

This one-shot import observation is finished. Keep the accepted actual-caller ledger integration closed. The same 20-second startup contract remains unsupported for this local environment; do not repeat unchanged cost suites or expand another observer-only campaign. Further work must identify and validate a specific dependency/initialization fix or explicitly narrow support, then return directly to separately preregistered matched complete dense/INT8 training. A wider deadline would change the operational contract and needs a reasoned new preregistration, not retrospective rescue.

The six historical H1 joint failures, invalid historical parent RSS and all H2–H4 scientific gates remain. The INT8 treatment is not a learned residual-bank architecture. Complete training cost, actual-process lifetime working-set endpoint, sampled-private limits and reused-data procedural final evaluation are still unmeasured. Evidence covers one local single-machine CPU/native startup; no GPU, multi-node or production conclusion follows. Only background CLI/API was used.

- [Metrics and limits](metrics.json), [preservation review](preservation-review.json), [execution argv](execution.receipt.json)
- [Original stack](raw/token-503-0/import-stack.txt), [arm receipt](raw/token-503-0/import-stack-armed.json), [failed case](raw/token-503-0-case.json)
- [Versioned protocol](../../fixtures/native-training-import-observation/protocol.json), [freeze](../../fixtures/native-training-import-observation/implementation.json)
- [Post-outcome source read](post-outcome-import-source.json), [selected hashes](selected-manifest.json)
- [Original cost-v2 failure](../native-training-cost-v2/report.md)
