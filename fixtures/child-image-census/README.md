# Child-image census, v1

This standard-library Windows tool follows a failed process-set assumption in the separately frozen pretrained-training observer. It performs no training and provides no ML release path. [Recorded result](../../results/child-image-census/report.md).

Two fixed ordered cases take held snapshots before/after the native cmd control. The second adds a distinct nonce-authenticated base-Python helper, takes one more snapshot, rejects the helper even though its executable matches the actual worker, then terminates the whole Job. Every additional image remains unapproved; graceful observation success is not workload admission.

`protocol.json` fixes the cases, 20-second case/45-second suite budgets, five-second stage and four-second cleanup limits, maximum 16 descendants/16 tree levels, exact known roles and failure behavior. Synchronous OS and file calls cannot be preempted; late completion fails acceptance. Count/depth/query limits fail the census while retaining observed PID/parent rows and available partial image evidence.

`implementation.json` binds the exact producer, mocked tests, historical dependencies, three executable hashes and portable auditor before the one recorded suite. Actual local absolute executable paths are not published. File-path bytes are hashed at query time; this is not loaded-code attestation. The protocol uses barriers instead of a random seed, and each child identity uses a fresh nonce.

Verify the saved evidence on any standard Python host:

This frozen auditor intentionally exits1 for the recorded two self-hash failures. `python -S -m scripts.check_child_image_census_record` instead verifies the pinned negative record and keeps experimental acceptance false; it was written after the run.

```bash
python -S -m scripts.audit_child_image_census --report results/child-image-census/report.json --protocol fixtures/child-image-census/protocol.json --freeze fixtures/child-image-census/implementation.json --output reports/child-image-census-audit.json
```

To execute on Windows, provide the exact frozen launcher, base interpreter and System32 cmd.exe paths explicitly. Use a fresh directory; preserve this report and do not replace it. Changed binaries/code/policy require a separately declared version.

```powershell
& $CensusPython -S -X utf8 -m experiments.child_image_census --python $CensusPython --base-python $CensusBasePython --native $CensusNativeCmd --protocol fixtures/child-image-census/protocol.json --freeze fixtures/child-image-census/implementation.json --output reports/runs/your-new-directory/census-acceptance
```

No dependency install, model/network fallback, provider call, GPU job or historical scientific rerun is part of this experiment. [Research interpretation](../../research/2026-10-17-child-images-and-versioned-evidence.md).
