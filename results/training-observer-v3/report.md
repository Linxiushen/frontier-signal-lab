# Pinned training observer v3: five controlled cases pass

The sole frozen Windows engineering suite passed **5/5 cases** in
**40.7390677 seconds**. Three independent workers each loaded
the pinned local Pythia-14m and completed exactly two dense AdamW updates:
**3 model loads, 6 updates total**. No compression arm or holdout evaluation ran.

| Fixed case | Recorded result | Wall seconds | Retained exits |
| --- | --- | ---: | ---: |
| healthy_dense2 | normal_completion | 13.998 | 5 |
| dense2_busy_deadline | timeout | 13.372 | 5 |
| dense2_private_cap64 | memory_private_limit | 11.828 | 5 |
| prehandshake_exit37 | expected_prehandshake_exit37 | 0.468 | 1 |
| injected_import_failure38 | expected_injected_import_failure38 | 0.747 | 5 |

Execution: `2026-10-17T09:07:30.348344+00:00` to `2026-10-17T09:08:11.087094+00:00`.
The implementation was frozen at `2026-10-17T09:07:22.790330+00:00` after 66 guarded
producer/mock and independent synthetic-auditor test groups passed. ML imports,
native workloads, subprocesses and networking were forbidden in those tests.
This suite had one attempt, zero retries and no post-outcome repair.

## What v3 adds

V2's three import completions contained a denied `socket.bind` name without its
caller or arguments. That [failed record](../training-observer-v2/report.md)
remains unchanged. V3 separately declared one narrow local capability policy.
Each of its three ML workers saved one **allowed bind attempt** during import:
Windows AF_INET6=23, SOCK_STREAM=1, proto0, tuple2 exactly `(::1, integer0)`.
The recorded prefix has two exact frames in the pinned
`urllib3/util/connection.py`: `_has_ipv6:127` and `<module>:137`, followed by an
outside-package boundary. File and opaque canonical path hashes match the
freeze. The identical cumulative event persists through every later stage and
terminal receipt; no unexpected denial, drop, overflow or truncation occurred.

This establishes the saved v3 attempt's provenance. It does not retrospectively
identify v2's event, record OS bind success, cover the whole import stack, or
provide native network isolation. Other monitored bind/connect/DNS/sendto
attempts remain denied. Import-failure budget0 and each worker's separate
synthetic denial are checked independently. Propagating errors now retain the
bounded guard, phase and timestamp, and hidden worker-failure files reject success.

## Workload, memory, liveness and cleanup

The frozen revision is `cf967c0a9a04383db6f7b1108d86b2962634b4ac`, CPU float32,
eager attention, local-files-only and no remote code. Seed503, two fixed batches,
all 14,067,712 parameters and 76 parameter tensors are pinned. The unchanged
historical loader and dense training helper supply the actual operations.
Counters and parameter hashes are receipts, not independent per-call tracing.

All 16 synchronized parent/self memory brackets pass, with maximum absolute
difference4096bytes. Twenty-two held role inventories and 37 timestamped
controller/worker controls pass. Preimport native threads are4; loaded stages7;
Torch intraop/interop settings are1/1. These are bounded snapshots, not continuous
child absence, loaded-code integrity or exact thread ownership.

The healthy 64MiB allocation increases sampled resident memory by67,108,864bytes
and private memory by67,239,936bytes. The busy timeout spans1.515425seconds with
1.5native CPU seconds and maximum sample gap0.021907seconds. The private-cap
arm's termination API returns0.238772seconds after the allocated self-before reading;
the first crossing exceeds the742,895,616byte limit by16,908,288bytes.
This sampled post-training threshold permits overshoot; it is not an import or
training hard cap. All21retained identities exit, all5Jobs become empty, and
maximum cleanup is0.398941seconds. Exit37 and missing-module exit38 are precise
negative controls; unrelated exceptions cannot satisfy them.

Healthy held off/on sampler windows last about0.401seconds each. Saved parent
native CPU deltas are0 versus0.140625seconds. This visible observation cost must
be retained. The windows run while the worker is held, in a fixed order; they
do **not** estimate causal training slowdown. Current readings and process
lifetime peaks do not isolate a backward peak or establish memory savings.

## Replay saved evidence

```powershell
python -S -m scripts.audit_training_observer_v3 --report results/training-observer-v3/report.json --protocol fixtures/training-observer-v3/protocol.json --freeze fixtures/training-observer-v3/implementation.json --output reports/runs/your-fresh-review/v3-audit.json
```

This portable command checks raw fixed controls/stages and saved hashes without
Torch, Windows APIs, subprocesses or model execution. It returns
**27204/27204** checks passed; seven optional
local executable/model/provider file checks remain explicitly unperformed.
The separate saved [local file audit](local-file-audit.json) passes
**27211/27211**, with all optional checks
performed on this machine. Neither is a new model run or independent OS remeasurement.

| Artifact | SHA256 |
| --- | --- |
| [report.json](report.json) | `714310728dec612e64876e5637b52fdfade03748f208948ed9c2f4b0b003179d` |
| [protocol](../../fixtures/training-observer-v3/protocol.json) | `b248a981ffe9db8aea50f4a0c85d057e968620df372c74acb0835e2b046e3552` |
| [implementation freeze](../../fixtures/training-observer-v3/implementation.json) | `3e72671b15a04e0ec99b6968e721d0f74f70bff51a30d7052ecb24cc229e1c21` |
| [frozen-audit.json](frozen-audit.json) | `951971fcd039bb0e591719b3f7c2758b31e8fdaacd37424dcdada57113934053` |

The previous six failed scientific cost/final-quality screens and invalid
historical parent RSS stay unchanged. This bounded two-update integration clears
an engineering prerequisite; it provides no training-quality, compression,
speed, GPU or production-reliability result. Next freeze a separate measurement
study with observer duty-cycle controls and isolated training-memory boundaries
before another cost comparison; do not rescue the failed settings by seed/lr search.
