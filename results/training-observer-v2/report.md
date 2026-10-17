# Pinned training observer v2: FAIL after package import

The single frozen Windows integration attempt **failed: 2/5 cases passed**.
All three ML cases completed Torch `2.9.1+cpu` and Transformers `4.57.3`
imports, then failed the provider guard before the parent accepted `postimport`.
**Actual pretrained model loads: 0. Actual optimizer updates: 0.** The intended
healthy training, busy-forward deadline, private-memory threshold and held
sampler-overhead gates therefore remain unexecuted.

| Fixed case | Recorded result | Wall seconds | Retained exits |
| --- | --- | ---: | ---: |
| healthy_dense2 | provider guard rejected after imports; failed | 6.397 | 5 |
| dense2_busy_deadline | provider guard rejected after imports; failed | 6.174 | 5 |
| dense2_private_cap64 | provider guard rejected after imports; failed | 6.242 | 5 |
| prehandshake_exit37 | exact exit37 and absent handshake; passed | 0.478 | 1 |
| injected_import_failure38 | exact missing-module failure and both Python exits38; passed | 0.720 | 5 |

The actual run was `2026-10-17T07:04:00.499375+00:00` to
`2026-10-17T07:04:20.848275+00:00`, lasting **20.3491467 seconds**.
The protocol was declared at `2026-10-17T06:56:08.687024+00:00` and the
implementation frozen at `2026-10-17T07:03:42.816056+00:00`. There was one
acceptance suite and no retry, changed threshold or post-result implementation
repair. Its plan permitted three model loads and six updates; neither occurred.

All **21 retained process handles were observed exited**, and all **five Jobs
had active count0** within their cleanup budgets. The three failed ML cases
retain `failure_cleanup`; this is cleanup evidence, not successful training or
busy/cap enforcement. The prehandshake control retains only the launcher;
the actual interpreter identity remains unavailable in that case.

## What the failure records establish

The parent error is the combined check's generic message:
`ObserverError: stage identity/thread count differs`. Each saved
`postimport-ready.json` has the authenticated worker PID, a positive integer
native thread count of7, both expected package versions, and
`unexpected_denied_events: ["socket.bind"]`. The PID/thread subconditions pass;
the frozen `validate_provider` contract requires an empty unexpected-event
list and rejects this event. The parent consequently never records a validated
`postimport` stage or issues its measurement/release controls. The raw receipt
is retained rather than inserted retrospectively into the accepted stages.

Before that failure, four authenticated cases passed their held `preimport`
memory bracket and exact process-role gates. The policy checks a venv launcher,
its distinct base interpreter and native cmd, plus one frozen/pinned conhost per
registered launcher/native owner. A held before-native inventory has3 identities;
a held preimport inventory has5. These snapshots and retained handles do not
establish continuous child absence, loaded-code integrity or exact thread
ownership. A Python audit hook and offline loader configuration do not establish
native network isolation or external-provider execution.

## Static candidate, without runtime attribution

Offline source inspection found a compatible candidate in installed
`urllib3 2.8.0`: `urllib3/util/connection.py:137` calls `_has_ipv6("::1")` at
module scope. Line127 attempts an IPv6 socket `bind((host, 0))`; the surrounding
`except Exception` can swallow the hook's `PermissionError` and let import
complete. Its file SHA256 is
`2633bbdb69731e5ccb5cf4e4afd65605d86c7979cc5633126f50c92d5ad74a74`.
There is a visible static import chain from Transformers utilities through
Requests and urllib3 to this module.

**This is a static candidate, not a demonstrated caller.** V2 saved the denied
event name but no address, socket family, calling stack or loaded module origin.
It cannot establish that the actual attempted bind was loopback or came from
this function. [The selected static diagnosis](static-diagnosis.json) preserves
that distinction and hashes the three raw receipts. No inspected third-party
package/model import, network action or experiment was run for the diagnosis.

## Checks preserve the rejection

The frozen independent portable acceptance audit passes **11,715/11,725** checks
and **rejects ten**. They include the failed overall acceptance plus each ML
case's failed status, incomplete stage inventory and absent accepted
`postimport`. Its verdict is `passed: false`; the passing receipt/hash checks
do not clear those failed gates. The post-outcome saved-record checker verifies
that this particular negative result, raw controls/receipts and cleanup remain
unchanged. A successful preservation check does not upgrade acceptance.

The first publication's CI found one error among 531 tests (67 skipped): the
new post-outcome mutation test assumed Git retained an empty case directory.
The [portability fix](ci-portability-fix.json) explicitly simulates a fresh
checkout and creates the malicious receipt's parent before testing its rejection.
The corrected 15 guarded test groups pass. Frozen producer/protocol/auditor and
experiment receipts are unchanged; no actual experiment was retried. This test
fix does not turn the failed training integration into a pass.

To replay saved evidence only, from the repository root:

```powershell
python -S -X utf8 scripts/check_training_observer_v2_record.py
python -S -X utf8 scripts/audit_training_observer_v2.py --report results/training-observer-v2/report.json --protocol fixtures/training-observer-v2/protocol.json --freeze fixtures/training-observer-v2/implementation.json --output reports/runs/your-fresh-review/frozen-audit.json
```

The first command should report preservation consistency with
`experiment_acceptance_passed: false`. The second must still reject this saved
acceptance and exit1; use a fresh output filename. Both read saved files and
hashes, without native observer calls, model loading or training.

| Artifact | SHA256 |
| --- | --- |
| [report.json](report.json) | `5a6cec898c46c1daaebd48d3ce0543eac3d097b6848b737c2047b379aa495873` |
| [protocol](../../fixtures/training-observer-v2/protocol.json) | `d381c42ac6f21fc33ac27a4fdc9980b1cd7beeee32f82f7295c58afa742cfd23` |
| [implementation freeze](../../fixtures/training-observer-v2/implementation.json) | `a07656ffb21da55e750300b88e69ceead85b914dbef48855072a3fe1af5722ec` |
| [frozen-audit.json](frozen-audit.json) | `f2d012b248ed3c50ccee2372f581982b3da12ce67948857a817d9d9e832439b6` |

## Next gate

A later pass may declare a new actual pinned training integration with bounded,
sanitized audit-event arguments and source-frame provenance. Any narrow
loopback capability-probe allowance must be explicit, source-pinned and
independently tested before that new freeze, with other provider operations
still rejected. It remains a proposal. Execute at most one newly frozen suite
in that later pass; do not rerun or repair v2 to replace this failure, or extend
inventory-only work instead of reaching the actual loader/two-update gates.
Historical invalid RSS, unestablished worker cap and failed cost/final-quality
screens remain unchanged. This result clears no training-release gate.
