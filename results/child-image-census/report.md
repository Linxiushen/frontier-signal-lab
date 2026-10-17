# Bounded Windows child-image census

The single frozen two-case identity-only suite is **NOT ACCEPTED**. Both producer runtime flags are true, but the frozen auditor rejects two self-reported executable-hash checks. It recorded 5 held snapshots and cleaned up 12 retained process identities across both cases. Actual model loads and optimizer updates: **0**. Training remained forbidden.

| Case | Producer runtime flag | Held snapshots | Retained identities | Final Job count |
| --- | --- | --- | --- | --- |
| native_census_graceful | True | 2 | 5 | 0 |
| injected_python_rejection | True | 3 | 7 | 0 |

Actual execution: `2026-10-17T00:59:56.844334+00:00` to `2026-10-17T00:59:58.228609+00:00`, 1.384134 seconds; one attempt, zero retries. The code, protocol and portable auditor were frozen before this suite. [Exact report](report.json), [derived summary](summary.json), [trace hashes](trace-manifest.json).

New samples identified additional images (conhost.exe, python.exe) using retained handles, PID/creation, parent links, live Job membership, OS image query, file SHA256 and opaque normalized-path digest. Every extra PID remained **unapproved**. The explicit helper uses the same base-Python executable; image equality did not promote it to an approved role. The rejection control terminates the whole Job and checks all retained exits.

The portable saved-receipt audit reports 422/424 checks, passed=False. Its `base_worker_self_hash` assumption fails in both cases: Python's `sys.executable` file hash is the venv launcher, while the retained OS image hash is the base interpreter. Every recorded actual-worker OS image matches the frozen base hash; these are distinct fields. The frozen auditor and its rejection remain unchanged. A future version must model both identities before new training admission. [Audit receipt](census-audit-portable.json) / [independent producer review](census-independent-review.json) / [independent auditor review](census-auditor-independent-review.json).

The [post-run pinned rejection check](../../scripts/check_child_image_census_record.py) verifies these exact saved failures and hashes; its success does not grant experimental acceptance. Receipt checks do not repeat the OS measurement or authenticate coherently rewritten evidence.

These are **new** bounded snapshots. They cannot identify the eight historical children whose images were not recorded in the [failed pretrained integration](../training-observer/report.md). File hashes do not attest loaded image/DLL integrity; Job counts do not establish continuous child coverage. No loader, training, provider, GPU, isolated memory, sampler overhead, quality or cost gate is cleared.

Verify without Windows APIs, child processes, Torch or model assets:

The frozen auditor below intentionally returns exit1 with the two preserved `base_worker_self_hash` failures. To check the pinned negative record, run `python -S -m scripts.check_child_image_census_record`; that post-run check keeps experimental acceptance false.

```bash
python -S -m scripts.audit_child_image_census --report results/child-image-census/report.json --protocol fixtures/child-image-census/protocol.json --freeze fixtures/child-image-census/implementation.json --output reports/child-image-census-audit.json
```

Report SHA256: `d43d85b84e0634b6b460d6db529367fa9cd44f41141a765d043935d4c8aec6b0`. [Frozen protocol and reproduction](../../fixtures/child-image-census/README.md).
