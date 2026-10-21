# Native observer / ledger integration v3

One separately frozen local Windows integration passes all four producer cases
and the independent saved-byte acceptance auditor. This closes the stdlib
ledger→native-observer prerequisite. The actual pretrained training caller is
the next integration; no model was loaded or updated in this run.

## Caller, change and acceptance

The caller is `ObservedWindowsJob`: retained Windows Job process memory queries
feed `BoundedJSONLLedger` and one exclusively owned binary file. Concurrent
sampling needs coherent request identities and contiguous publication, while a
trace failure must still terminate, verify and close native resources.

V3 reuses v2's **unchanged** producer cases, worker, admission policy, adapter,
native observer and ledger. The new version corrects two saved-byte audit schema
assumptions before execution: a sorted sample's five-byte partial prefix is
`{"emi`, and the negative case includes the unregistered Python worker's own
console child. Both unregistered identities must be refused; image equality
does not confer admission. The original v1/v2 frozen code and failed acceptance
results remain intact. The unidentified extra in v1 stays unidentified.

The [protocol](../../fixtures/observed-job-v3/protocol.json),
[13-source freeze](../../fixtures/observed-job-v3/implementation.json) and
[pre-execution review](../../fixtures/observed-job-v3/pre-execution-review.json)
precede the one native suite. Fixed order, four threads × eight samples,
64-row/32-KiB-row/1-MiB-total admission ceilings, 20-second case/65-second suite
ceilings and a separate four-second cooperative cleanup allowance were retained.
There was no native retry, threshold change or post-outcome code repair.

## Observed results

| Case | Saved evidence | Outcome |
| --- | --- | --- |
| Threaded sampling | 32 unique requests from four sampler threads; 34 contiguous rows including start/close | Pass |
| Row capacity | One committed start row; next sample refused before I/O; later sampling denied | Pass |
| Partial write | One committed start row plus the exact five uncommitted bytes `{"emi`; poisoned sink; later sampling denied | Pass |
| Unregistered Python | Initial worker/console identities pinned; final four-node inventory includes helper and helper console; both extras rejected | Pass |

Eight held inventories and all ten retained process exits are saved. Each of
the four Jobs is empty and both handle-close paths complete. The healthy worker
exits normally; fault/negative workers are explicitly terminated. There are 38
committed rows across the suite. These are correctness counts, not throughput
or latency measurements.

The [native report](raw/report.json), [execution receipt](execution.json),
[frozen auditor receipt](frozen-audit.json) and
[selected byte manifest](selected-manifest.json) preserve the actual attempt.
The independent auditor reconstructs canonical committed bytes, checks the
partial tail, caller/sample identity and timing, both inventory decisions, and
the exact final retained-exit identity set. Its result is four cases, ten exits
and 38 committed rows accepted. “Independent” here means a separate saved-byte
implementation with no producer/native imports; it is not independent human
review or a second live execution.

Before freezing, 94 focused controls passed. These include actual adapter and
`FileSink` serialization faults with mocked native collaborators, four-node
helper-console fixtures and rejection mutations, and a replay of archived v2
bytes through the new schema. That archive replay is a regression fixture,
not a retroactive upgrade of v2 acceptance. Full local discovery ran 965 tests:
884 passed, 81 skipped. No new control test starts a child or native backend.

Recheck the published saved bytes without launching a process or model:

```sh
python -S -B scripts/audit_observed_job_v3.py \
  --output results/observed-job-v3/raw \
  --protocol fixtures/observed-job-v3/protocol.json \
  --freeze fixtures/observed-job-v3/implementation.json --root .
```

## Exit and next integration

The prerequisite is closed at **single-host Windows/stdlib integration**.
Next, connect this ledger to the existing retained **actual interpreter** in
`experiments/training_observer_v3.py` (`sample`/`read_stage`/`run_case`), keeping
the launcher/native distinction, pinned model/assets, provider guard, exact
acknowledgment barrier and cleanup controls. Freeze this actual caller before
any model execution. Do not open another observer-only prerequisite.

After that integration, separately preregister matched dense/bank complete
training cost and sealed final quality. Include data, packing/retrieval,
forward/backward, optimizer and observation costs; distinguish allocator
endpoints, sampled native memory and logical payload. No seed/LR rescue of the
six failed training screens is authorized by this engineering result.

This run establishes no training quality, compression savings, total observer
cost, GPU, multi-machine or production result. A held census is not continuous
isolation; arbitrary file/OS calls may block. Flush is not fsync, and admitted
output bytes do not bound temporary serialization memory. H1's six failed
cost/quality screens and invalid historical parent RSS, and H2–H4's unmet real
runtime/restart/evaluation gates, remain unchanged.
