# Native observer / trace ledger integration v1

**Native acceptance failed. Do not rerun this frozen attempt.** This is an
experimental source adapter, not a supported training-harness integration.

`ObservedWindowsJob` composes the existing Windows JobObject observer with the
bounded JSONL ledger. It serializes native sampling and event writes, retains
ownership before logging, refuses sampling after a trace error, and still
attempts native cleanup and both handle-close paths. Existing observer/ledger
implementations are unchanged. A caller can keep using those components
directly; this adapter has not replaced the actual training entry point.

The fixed workload was four threads with eight samples each, followed by row-cap
and partial-write controls. The first native case failed at the expected-one
process check with **two active Job processes**, before sampling threads started.
The remaining cases were not run. Only the worker identity was retained; the
extra process was not identified. Job accounting returned to zero and the
retained worker exited with `0xE003`. These cleanup receipts do not establish
identity or individual exit evidence for the extra process.

From the repository root, with any supported Python and no ML dependencies:

```bash
python -S -B scripts/check_observed_job_failure.py
python -S -B -m unittest discover -s tests -p 'test_observed_job*.py' -v
```

These commands check saved negative evidence and mock controls; they launch no
native worker and do not turn failure into acceptance. The frozen acceptance
auditor remains unchanged and **exits unsuccessfully** on the saved run:

```bash
python -S -B scripts/audit_observed_job.py --output results/observed-job/raw --protocol fixtures/observed-job/protocol.json --freeze fixtures/observed-job/implementation.json --root .
```

The exact original native command is preserved in
[`native-execution.json`](../../results/observed-job/native-execution.json).
Its fixed output location already exists in the original workspace; reuse is
forbidden by the original protocol. A future native attempt requires a new
freeze and directory, explicit retained role census using existing role-policy
code, useful assertion diagnostics, the same sampling/fault/cleanup gates, and
return to the training integration after those gates pass. Merely changing the
expected count to two cannot authorize an unidentified process.

The seven adapter unit cases mock native collaborators. The later three
preservation cases include seven mutation subcontrols, not seven additional
native executions. Flush is not fsync. Arbitrary sinks can block; serialized
access does not provide hard shutdown deadlines, distributed consistency,
device-memory measurement, performance improvement or production validation.

See the [negative report](../../results/observed-job/report.md) for timestamps,
fixed limits and scientific boundaries.
