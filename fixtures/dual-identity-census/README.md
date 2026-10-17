# Dual self-path and retained OS-image census, v1

This new standard-library Windows experiment separates two identities that the earlier frozen child-image census incorrectly treated as equivalent. The earlier producer, protocol, freeze, auditor and rejected result stay unchanged. This code is derived from the original producer at SHA256 `999707e2b92b3e7b7a75b252b740c20efd1d770bf76eea745f65fa3c1de90ed4`.

The worker reports `sys.executable` as a file identity: basename, file SHA256 and an opaque normalized-realpath SHA256. Its declared self-path role is the frozen venv launcher. Independently, the parent's retained OS handle identifies the actual worker process image against the frozen base interpreter role. The injected helper declares its self-path role as base interpreter, while its OS image is checked separately against that role. Each path and content contract must pass independently; equal or different executable hashes do not establish or refute the other identity. Public receipts contain no actual local absolute executable paths and no ambiguous `runtime_executable_*` aliases.

Two ordered no-ML cases retain the same bounded controls: graceful native cmd census, then a separate helper rejection case. Five held snapshots identify observed children, preserve unknown images as unapproved, and verify all retained exits and empty Jobs. The helper remains unapproved by exact PID and creation identity even when both of its image descriptions match the actual worker. No training release path exists; model loads and optimizer steps remain zero.

The declaration fixes 20 seconds per case, 45 seconds for the suite, five seconds per stage and four seconds for cleanup, with at most 16 descendants and 16 tree levels. All limits are clamped to nonrenewable case and suite deadlines, including final handle close. Synchronous OS/file calls cannot be preempted; late completion fails. Incomplete identity, query errors, count/depth overflow, missing known members or cleanup failure retain evidence and fail acceptance.

Before execution, the root reviews the exact protocol, source, test, dependency, executable and independent auditor hashes, writes a new implementation freeze, then executes at most one fresh-output suite. The freeze also binds the three canonical executable path digests. The producer checks those digests and actual auditor file hashes before launching a child. New-census preflight used guarded mocked/synthetic tests. The final declaration separately permits existing repository CPU numerical/CLI regression tests; the draft timestamp and scope clarification are retained. The one recorded suite passes both cases and the frozen portable430/local431 checks. See the [recorded result](../../results/dual-identity-census/report.md).

```powershell
& $DualCensusPython -S -X utf8 -m experiments.dual_identity_census --python $DualCensusPython --base-python $DualCensusBasePython --native $DualCensusNativeCmd --protocol fixtures/dual-identity-census/protocol.json --freeze fixtures/dual-identity-census/implementation.json --output reports/runs/your-new-directory/dual-identity-census-acceptance
```

This experiment does not identify the eight historical unrecorded images, admit a training workload, validate continuous coverage or loaded code integrity, repair historical RSS measurements, or change any prior scientific failure. Loader, thread, provider, training, liveness, cap and sampler-overhead gates require separately declared evidence.

Verify the saved receipts without launching processes or importing ML:

```bash
python -S -m scripts.audit_dual_identity_census --report results/dual-identity-census/report.json --output reports/dual-identity-audit.json
```
