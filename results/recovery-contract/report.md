# Recovery contract probe

Deterministic offline state-machine fault injection. Results follow the explicit protocol assumptions; they do not reproduce upstream bugs.

| Protocol | ACK loss | Stale context | Duplicate effect | Retry resurrection | Missing failed-score evidence |
| --- | ---: | ---: | ---: | ---: | ---: |
| naive_callback_before_persist | 3 | 1 | 1 | 1 | 1 |
| durable_log_persist_before_hook | 0 | 1 | 1 | 1 | 1 |
| versioned_idempotent_journal | 0 | 0 | 0 | 0 | 0 |

These are violation counts across enumerated traces, not estimated probabilities. Crash cuts are protocol-local boundaries, so identical cut numbers need not describe identical actions.

## Model boundaries

- Synthetic protocols; no upstream implementation is executed or reproduced.
- Single-process fail-stop crashes; durable writes are atomic and never torn.
- The versioned receipt and effect update is atomic in one local store; external exactly-once effects require their own transaction or idempotency key.
- Only acknowledged messages are covered by the loss metric. All protocols may lose generated messages crashed before persistence.
- A stale turn means committing after compaction using the previous context version.
- No durable accepted-turn/completed-result ledger is modeled. A discarded or crash-lost queued turn can escape all five safety metrics; zero violations does not establish liveness.
- Scoring failure evidence is required only after an observed score_fail event; a pre-journal crash has no magical evidence recovery.
- Counts summarize this finite deterministic scenario suite; they are not real-world failure rates or model capability scores.

All protocols lose the unacknowledged message at the post-generation/pre-persistence cut. `unacknowledged_message_loss` is exported separately and excluded from ACK loss.

Each run in `probe.json` includes input events, durable before/after snapshots, volatile context, and an external observation oracle. Every observed contract failure also has a standalone JSON trace in `counterexamples/`.

## Public inspiration (reports/proposals, not reproduced defects)

- https://github.com/earendil-works/pi/issues/10979
- https://github.com/earendil-works/pi/issues/10982
- https://github.com/openclaw/openclaw/pull/173018
- https://github.com/PrimeIntellect-ai/verifiers/pull/2857
