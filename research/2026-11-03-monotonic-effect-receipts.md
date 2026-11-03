# Keep an acknowledged effect receipt after a late refusal

An overlapping callback can observe a missing remote effect, then finish after
another callback has already saved that effect's valid receipt. The original
`makeEffectDispatcher` then overwrites the durable intent's `committed` status
with `aborted` or `denied`. Its effect record and receipt remain present, so the
host records disagree and the late caller reports refusal for acknowledged work.

This is an engineering regression in our exported dispatcher, reproduced on
unchanged commit `d6795d77e96147233f9d8edeb12c1ab963806896`. The original service's
SHA256 is `b82b0585d3638b80a1e5455659a3af44f2ee63eecb611f3a22a2f12fa2528af8`.
The controlled host and transport are test doubles. This reproduction does not
establish that the prior finite native suites exercised overlapping dispatches.

## Caller, fix and rollback

The caller is the optional native generation adapter's tool-effect dispatcher,
which persists an intent, looks up or applies the remote effect, then commits its
disposition. The operational risk is conflicting durable outcomes when delayed
lookups, permission refusals and cancellation callbacks overlap for one request.
Larger request counts make this an integration concern; no frequency or scale
performance has been measured.

The opt-in
[`openReceiptGenerationService`](../experiments/pi_generation_receipt_service.mjs)
retains the existing Harness/GenerationTask/ToolTask caller and transport contract.
Its refusal transaction checks the current host and intent identity again. If
another callback has already committed the intent, both stored receipts must match
the original identity. The late callback returns `existing`, preserves those
records and emits `effect-disposition-superseded`. It does not set `effectDenied`
or emit `effect-refused` in that case. Ordinary refusals still persist; a valid
historical receipt arriving after refusal can still be acknowledged.

The original service and every frozen source/result remain byte-for-byte intact.
The new factory mechanically copies the old native caller with only its exported
name and dispatcher binding changed, and imports the unchanged identity,
quarantine and paused-recovery helpers. This duplication preserves the published
freezes. Callers opt in by choosing `openReceiptGenerationService` and supplying
the same explicit `effectClient`, scope and native-runtime options; retaining the
old factory is the rollback. The new factory itself has not been opened against
the optional native runtime in this pass.

## Reproduction and checks

[`pi_generation_receipt_service.test.mjs`](../tests/pi_generation_receipt_service.test.mjs)
uses controlled promise barriers to test cancellation, current host revocation,
an aborted signal, delayed remote refusal and the reversed acknowledgement order.
Changed host identity and malformed/foreign stored receipts must still reject.
Ordinary denial, unknown transport outcome and foreign remote response remain
separate outcomes. No timing sleeps decide the racing transaction order.

The same test source, with only its dispatcher import redirected to the unchanged
original export, exits 1: Node reports 11 test nodes, 2 passed and 9 failed
(including parent nodes). Against the new dispatcher all 11 pass. Another 21
adjacent tests pass, including the existing loopback HTTP/SQLite fixtures and
paused recovery/worker controls. These are engineering checks; they execute no
native Harness, real model or scientific suite.

Local immutable command/output receipts are retained in
`reports/runs/20261103T011121Z/receipt-validation/`; a public digest manifest is
[`20261103T011121Z-monotonic-receipt.json`](receipts/20261103T011121Z-monotonic-receipt.json).
Run the new regression with:

```sh
node --test tests/pi_generation_receipt_service.test.mjs
```

## What remains open

This change protects a receipt already acknowledged by another callback in the
same host. It does not serialize all dispatches, resolve every unknown remote
outcome, add tenant authentication or establish multi-owner correctness or
external exactly-once behavior. The HTTP authority check and remote mutation are
still separate from host authority. No native cancellation/restart acceptance,
model quality, GPU, distributed, production, throughput or latency result is
added. H1–H4 scientific objects, the earlier failed concurrent freeze and the
accepted finite scoped-v2 slice retain their previous status.

Further native work needs a separately preregistered actual caller and concrete
authority/cancellation/receipt interleaving, bounded admission/recovery limits,
two process reopens and independent effect/terminal checks. This repair alone
does not authorize an unchanged scientific rerun or another observer prerequisite.
