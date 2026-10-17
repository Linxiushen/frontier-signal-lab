# Admit registered roles, reject the same executable in another role

The separately frozen Windows role-policy probe passes all three fixed engineering controls. It admits the prescribed launcher/interpreter/native graph with one exact console auxiliary per registered console owner, then rejects either an additional Python interpreter or an additional native command using the same frozen executable files. Training remains forbidden.

| Case | Held inventory sizes | Last-held identities exited | Final Job count |
| --- | --- | --- | --- |
| Healthy role admission | 3, 5 | 5; all exit 0 | 0 |
| Unregistered same-image Python | 3, 5, 7 | 7; controlled Python exits 57347 | 0 |
| Unregistered same-image cmd | 3, 5, 7 | 7; controlled Python exits 57347 | 0 |

The two rejection cases preserve the original five admitted identities. Only the injected identity and its observed console child remain rejected. Native and console exit codes are retained individually: stdin teardown can produce a normal native exit during whole-Job termination, so a universal termination-code rule would be inaccurate.

The final declaration was written at `2026-10-17T05:01:12.568869+00:00`, followed by the implementation freeze at `05:02:02.905253+00:00`. The sole suite ran `05:02:20.726053–05:02:22.998908+00:00`, taking **2.272196 seconds**. There were no retries, process preflight, model loads or optimizer updates. The 47 targeted guarded mock/synthetic tests passed with zero forbidden native/process/network/ML attempts; no broad local numerical/model regression suite was executed this pass.

The frozen independent report auditor passes **1053/1053 portable checks** and **1054/1054 checks with local executable-file rehash**. It checks raw retained identities, topology, path/file hashes, role decisions, auxiliary identity pins, held liveness, counts, budgets and cleanup without importing the producer or starting processes. The [protocol](../../fixtures/role-policy-probe/protocol.json), [freeze](../../fixtures/role-policy-probe/implementation.json), [raw report](report.json), [19 original trace files](trace-manifest.json) and [independent saved-result review](independent-result-review.json) are retained.

The report-only auditor does not read controller trace files. A separate post-hoc review checks their nonce, purpose, decision index/label and prohibited-release absence. Those control envelopes do not include monotonic emission timestamps; ordering is supported by the frozen producer/worker code and compatible saved receipts, not independently timestamped control emissions.

This is an exact-one console contract for one frozen Windows launch environment. Held snapshots are not continuous child monitoring, loaded-code attestation, provider custody or production proof. Historical parent RSS remains invalid, the eight old unrecorded child images remain unknown, the earlier frozen census remains rejected, and all six natural-text cost/final-quality screens remain failed. The next useful experiment must integrate the actual pinned pretrained loader and training observer, including thread/native/provider behavior, two updates, precise failure controls, liveness, private-memory threshold, overhead and cleanup; this probe does not authorize training by itself.

Replay the saved evidence using only the standard library:

```bash
python -S -m scripts.audit_role_policy_probe --report results/role-policy-probe/report.json --output reports/role-policy-audit.json
```
