# Native observer → ledger v2: four producer cases, frozen audit rejected

The unchanged `ObservedWindowsJob` adapter executed all four stdlib Windows cases once on 2026-10-21, 13:56:09–13:56:11 UTC. **Frozen acceptance remains false.** The independent saved-byte auditor rejected the partial-write tail; a separate read of the fourth case also exposed an overly narrow auditor topology assumption. No native retry, model load, optimizer update or scientific experiment occurred.

The engineering caller is the existing Windows Job memory observer writing through the bounded, serialized JSONL ledger. The new version reuses the actual adapter and native implementation, adding retained identity admission at two held boundaries. It closes part of the concrete v1 topology blocker; it is not yet integration into the pretrained training caller or evidence of scale performance.

| Case | Producer result | Committed trace rows | Retained exits / final Job count |
| --- | --- | --- | --- |
| Four threads × eight samples | pass | 34, exact 32 request IDs | 2 / 0 |
| Row cap | expected refusal; no later sample/I/O | 1 | 2 / 0 |
| Five-byte partial write | expected error; poisoned ledger; no retry | 1 plus uncertain five-byte tail | 2 / 0 |
| Unregistered same-image Python | extra Python and its console child rejected | 2, no samples | 4 / 0 |

Eight bounded held inventories retain exact PID/creation handles, OS image hashes, normalized path hashes, parent relationships, live Job membership and matching before/after Job counts. Each initial inventory contains the direct pinned worker and its exact System32 `conhost.exe` child. The same console identity remains pinned at the final held boundary. The rejection case additionally retains a same-image Python child and that child's own console process; the policy rejects both. All ten retained processes exit; four Jobs become empty and both handle-close paths succeed. This identifies processes in **this v2 execution only**. The unretained extra process in v1 remains unidentified.

Two frozen auditor defects prevent acceptance:

1. Canonical JSON sorts keys. Sample rows start with `emitted_perf_counter`, so the actual partial tail is the five bytes `{"emi`. The frozen auditor incorrectly expects `{"kin`. It stops at that assertion. The other candidate bytes were not saved; the attempted full-row hash is not a reconstruction of the failed row.
2. A separate read-only fourth-case audit also rejects. It assumes three nodes, all non-primary nodes directly parented by the registered worker. The native negative control has four nodes, including a console child of the unregistered Python. The producer's admission policy correctly rejects both extra identities; the saved-byte auditor does not describe that observed rejection topology.

The frozen producer, auditor, tests, protocol and implementation hashes are preserved. A **post-outcome preservation checker**, written after observing these failures, verifies the saved canonical prefixes/tail, exact inventories, denial decisions and cleanup. Its success does not repair or replace the preregistered acceptance gate. It is separate computation by the same agent, with no independent live-process attestation.

Before freeze, 85 relevant pure/mock controls passed; the full base suite ran 956 tests, with 875 passing and 81 optional-environment skips. Seven new policy/auditor tests include mutations for exact images, paths, identities, membership, replacement, incomplete inventories, duplicate requests, timestamps and trace tails. Those pre-freeze tests missed the two auditor assumptions above. Post-outcome saved-evidence tests additionally preserve rejection and catch cleanup, identity, admission, image, poison and tail mutations.

Recheck the selected bytes, without native execution, from the repository root:

```console
python -m scripts.audit_observed_job_v2 --output results/observed-job-v2/raw --protocol fixtures/observed-job-v2/protocol.json --freeze fixtures/observed-job-v2/implementation.json --root .
# Expected: AssertionError; frozen acceptance is rejected.
python -m scripts.check_observed_job_v2_failure
# Expected: preservation_passed true, frozen_acceptance false.
python -m unittest tests.test_observed_job_v2 tests.test_observed_job_v2_failure
```

Next, correct these two saved-byte schema assumptions in a separately frozen version of **the same integration**, with pre-freeze actual partial-write schema and helper-console controls. After that gate passes, return directly to a separately frozen actual training-caller integration; do not expand standalone observer diagnostics. Matched dense/bank full training cost and sealed quality remain a separate preregistration.

This is one local stdlib engineering run. Held inventories are not continuous descendant isolation. File/OS calls have cooperative bounds, not hard deadlines; flush is not fsync; ledger output caps do not bound temporary serialization memory. The 32 queries are not a throughput/tail-latency study, sampled memory is not a complete training peak, and no GPU, distributed, quality, production or compression benefit follows. Historical scientific failures and invalid RSS evidence remain unchanged.
