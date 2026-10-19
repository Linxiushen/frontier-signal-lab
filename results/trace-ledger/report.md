# Serialized thread trace ledger

One frozen standard-library thread fixture passed on 2026-10-19 at
09:42:59 UTC (17:42:59 Asia/Shanghai), without retries. This is an original
engineering prerequisite for future observation code. It does not change any
H1/H2/H3/H4 scientific conclusion.

An earlier rejected native-observer run retained duplicate sequence 6 and
missing sequence 8. The unit fixture deterministically reproduces the unlocked
algorithm's mechanism as `0,0,2`; it does not reconstruct missing old events.
The new component holds one lock across sequence assignment, UTF-8 admission,
write, flush and committed-state publication. Pre-I/O capacity refusal preserves
the committed prefix. Uncertain I/O poisons the ledger and forbids further I/O.

| Frozen arm | Saved result |
| --- | --- |
| Four workers, 64 attempts each | 256 unique rows, sequence 0–255; 13,202 bytes |
| Row cap | 7 commits, 25 pre-I/O refusals; 315 bytes |
| Exact byte cap | 7 commits, 25 pre-I/O refusals; 322 of 322 bytes |
| Short write | Zero committed rows; 42 uncertain bytes retained; later append refused |
| Write exception | Zero committed rows; 5 uncertain bytes retained; later append refused |
| Flush exception | Zero committed rows; complete 43-byte row remains uncertain; later append refused |
| Recursive write callback | Explicit rejection, zero committed rows and zero saved bytes; later append refused |

All cooperative threads stopped within the fixed deadlines. Seven reader
controls reject duplicate/gapped sequences, truncation, oversize input, duplicate
JSON keys, NaN and numeric exponent overflow. Ten finite unit controls cover the
old race, serialization, capacity admission, UTF-8 limits, immutable retained
records, uncertain I/O and recursion. Final tests restore their audit guard and
patched entrypoints after the class, preserving shared unittest discovery.

The independent auditor reads the actual saved files without importing the
producer or running threads. It regenerates ID universes and byte budgets,
checks canonical rows, sequence/admission mappings, exact fault tails, poison
metadata, artifact hashes and the frozen public-source hashes. Its saved
[audit](independent-audit.json) is distinct from the producer's acceptance.
The raw [result](result.json), seven `.jsonl` files, [unit receipt](unit-tests.json),
[release seal](release-seal.json) and [execution receipt](execution.json) are
retained alongside this report. The superseded unit receipt is explicitly
pre-execution; it does not bind the final isolation fix.

Result SHA256:
`ee1ed08e413e016fb36b97db8ed7b36aabdc90aad9355683a789c85427344f8e`.
Protocol SHA256:
`3ecc37a542e879a857c2cb608fb3fc6480a32379ed6f770f9bf5d7571dd12ec4`.
Implementation freeze SHA256:
`2e89785efdb4e2b89ea7f8a99104d0a957b0080b951a3234812fffa360ab8f55`.
Seed 20261019 fixes inputs, not scheduling, admitted identities or trace hashes.
The observed suite interval is diagnostic metadata, not a performance estimate.

The sink must be initially empty, exclusively owned by one ledger in one
process. Flush is not fsync or power-loss durability. Admitted-byte caps do not
bound temporary serialization memory, and arbitrary sinks can block. Deadlines
here cover only a cooperative in-memory fixture. The component is not integrated
into the native observer; old topology, missing-event and sequence failures
remain unchanged. No Node, SDK, model, provider or network target was executed.

The next engineering test requires a separately frozen native integration and
topology policy, exact saved identities and contiguous events, physical cleanup
and independent validation. It is not released by this result. Historical H1
cost/quality failures and invalid parent RSS, broad H2 recovery/liveness gates,
and planned H3/H4 status remain.

[Verify or reproduce this fixture](../../fixtures/trace-ledger/README.md).
