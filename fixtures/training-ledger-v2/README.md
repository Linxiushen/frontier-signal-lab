# Actual pretrained caller ledger v2

One original frozen CPU attempt, two producer cases complete. Frozen saved-byte
acceptance **rejects** the old raw-file inventory: it omitted seven new progress
receipts. The producer reports success; post-outcome preservation is separate.
No source, timeout or result was repaired after execution, and no rerun occurred.

See [the report](../../results/training-ledger-v2/report.md), [protocol](protocol.json)
and [freeze](implementation.json). Portable saved-byte checks execute no model:

```bash
python -S -m scripts.audit_training_ledger_v2 --output results/training-ledger-v2/raw --protocol fixtures/training-ledger-v2/protocol.json --freeze fixtures/training-ledger-v2/implementation.json
# Expected failure: healthy:exact_raw_identity_controls_stages_loop_completion_files
python -S -m scripts.check_training_ledger_v2_preservation --output results/training-ledger-v2/raw --protocol fixtures/training-ledger-v2/protocol.json --freeze fixtures/training-ledger-v2/implementation.json
```

The second command replays an explicitly reconciled complete raw-file union;
it does not upgrade preregistered acceptance. Actual execution uses the existing
local Windows runtime/model/data paths in the ignored execution plan. It is not
part of portable tests and must not be rerun under this frozen one-attempt plan.
Keep v1 and every predecessor byte unchanged. No GPU/API purchase is required.
